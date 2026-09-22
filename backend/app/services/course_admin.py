"""Общая логика конструктора курса (LMS-001..006, TASK-001..004), вызываемая
из двух мест:
- app/routers/courses.py — прямой вход методиста в браузер Codelab по SSO-cookie;
- app/routers/lms_admin.py — сервер-к-серверу от learning-portal-main (методист
  и преподаватель работают через свой аккаунт LMS, без входа в Codelab напрямую;
  это основной путь, см. README).
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    Course,
    CourseStatus,
    CourseVersion,
    LearningItem,
    LearningItemType,
    ProblemRevision,
    Submission,
    SubmissionStatus,
    User,
)
from app.schemas import (
    CourseCreate,
    LearningItemCreate,
    LearningItemOut,
    LearningItemTree,
    LearningItemUpdate,
    ProblemRevisionCreate,
    ProblemRevisionStudentOut,
    ProblemTestOut,
    SubmissionReviewOut,
)
from app.services.lms_client import notify_course_webhook
from app.services.progress_calc import is_item_unlocked, resolve_official_score
from app.services.tree_rules import validate_parent


def get_course_or_404(db: Session, course_id: int) -> Course:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")
    return course


def ensure_course_owner(course: Course, staff: User) -> None:
    """RBAC-002: методист получает доступ только к курсам, которые создал
    сам — не ко всем курсам платформы. Admin — без ограничений; teacher сюда
    не должен попадать вообще (мутирующие эндпоинты курса на стороне LMS
    гейтятся codelab.manage, которым обладает только методист)."""
    if staff.role == "admin":
        return
    if course.created_by_id != staff.id:
        raise HTTPException(status_code=403, detail="Курс создан другим методистом — нет доступа")


def get_course_for_submission(db: Session, submission_id: int) -> Optional[Course]:
    """None, если задача посылки ни к одному курсу не привязана (например,
    прогон вне дерева) — тогда владельца проверить нечем, пропускаем."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        return None
    item = (
        db.query(LearningItem)
        .filter(LearningItem.problem_revision_id == submission.problem_revision_id)
        .first()
    )
    if not item:
        return None
    version = db.query(CourseVersion).filter(CourseVersion.id == item.course_version_id).first()
    return db.query(Course).filter(Course.id == version.course_id).first() if version else None


def get_course_for_item(db: Session, item_id: int) -> tuple[LearningItem, Course]:
    item = db.query(LearningItem).filter(LearningItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Элемент не найден")
    version = db.query(CourseVersion).filter(CourseVersion.id == item.course_version_id).first()
    course = db.query(Course).filter(Course.id == version.course_id).first() if version else None
    if not course:
        raise HTTPException(status_code=404, detail="Курс элемента не найден")
    return item, course


def get_draft_version(db: Session, course_id: int) -> CourseVersion:
    """Черновик — версия без published_at, последняя по номеру (LMS-006:
    изменение черновика не должно менять уже опубликованную версию)."""
    version = (
        db.query(CourseVersion)
        .filter(CourseVersion.course_id == course_id, CourseVersion.published_at.is_(None))
        .order_by(CourseVersion.version_number.desc())
        .first()
    )
    if not version:
        raise HTTPException(status_code=409, detail="У курса нет открытого черновика для редактирования")
    return version


def build_tree(
    items: list[LearningItem],
    unlocked_ids: set[int] | None = None,
    completed_ids: set[int] | None = None,
) -> list[LearningItemTree]:
    # LearningItemOut (без "children") — иначе model_validate(item) читает
    # реальный ORM-relationship LearningItem.children и рекурсивно тянет его
    # из БД, задваивая узлы поверх дерева, которое мы строим вручную ниже.
    nodes = {
        i.id: LearningItemTree(
            **LearningItemOut.model_validate(i).model_dump(),
            children=[],
            unlocked=True if unlocked_ids is None else i.id in unlocked_ids,
            completed=False if completed_ids is None else i.id in completed_ids,
        )
        for i in items
    }
    roots: list[LearningItemTree] = []
    for item in items:
        node = nodes[item.id]
        if item.parent_id and item.parent_id in nodes:
            nodes[item.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


def build_student_tree(db: Session, user_id: int, items: list[LearningItem]) -> list[LearningItemTree]:
    items_by_id = {i.id: i for i in items}
    unlocked_ids = {i.id for i in items if is_item_unlocked(db, user_id, i, items_by_id)}
    completed_ids = {
        i.id for i in items
        if i.type == LearningItemType.TASK and i.problem_revision_id
        and (resolve_official_score(db, user_id, i.problem_revision_id) or 0) > 0
    }
    # Архивация каскадится на всё поддерево при самом действии (см.
    # set_item_archived), поэтому фильтровать по собственному is_archived
    # здесь достаточно — не может остаться неархивный потомок архивного узла.
    visible_items = [i for i in items if not i.is_archived]
    return build_tree(visible_items, unlocked_ids, completed_ids)


def create_course(db: Session, payload: CourseCreate, created_by_id: int | None) -> Course:
    course = Course(title=payload.title, slug=payload.slug, description=payload.description, created_by_id=created_by_id)
    db.add(course)
    db.flush()
    db.add(CourseVersion(course_id=course.id, version_number=1))
    db.commit()
    db.refresh(course)
    return course


def create_task(db: Session, course_id: int, payload: ProblemRevisionCreate, author_id: int | None) -> ProblemRevision:
    """Создаёт задачу (первую ревизию — task_id сквозной по всей платформе,
    не по курсу, TASK-006). Привязка к дереву — create_item с type="task"."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    last = db.query(ProblemRevision).order_by(ProblemRevision.task_id.desc()).first()
    next_task_id = (last.task_id + 1) if last else 1
    revision = ProblemRevision(
        task_id=next_task_id,
        revision_number=1,
        author_id=author_id,
        **payload.model_dump(exclude={"tests"}),
        tests=[t.model_dump() for t in payload.tests],
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    return revision


def get_task_or_404(db: Session, problem_revision_id: int) -> ProblemRevision:
    task = db.query(ProblemRevision).filter(ProblemRevision.id == problem_revision_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return task


def get_course_for_task(db: Session, problem_revision_id: int) -> Optional[Course]:
    """None — задача создана, но ещё ни к одному элементу дерева не
    привязана (create_task отдельно от create_item, TASK-006): владельца
    проверить нечем, дальше решает вызывающий код."""
    item = db.query(LearningItem).filter(LearningItem.problem_revision_id == problem_revision_id).first()
    if not item:
        return None
    version = db.query(CourseVersion).filter(CourseVersion.id == item.course_version_id).first()
    return db.query(Course).filter(Course.id == version.course_id).first() if version else None


def update_task(db: Session, problem_revision_id: int, payload: ProblemRevisionCreate) -> ProblemRevision:
    """Правки применяются к СУЩЕСТВУЮЩЕЙ ревизии на месте (не создают новую) —
    так массовая перепроверка (TASK-007, rerun_submissions) после починки
    тестов действительно перепроверяет посылки по исправленным тестам: они
    хранят problem_revision_id, а не копию тестов на момент отправки."""
    task = get_task_or_404(db, problem_revision_id)
    for field, value in payload.model_dump(exclude={"tests"}).items():
        setattr(task, field, value)
    task.tests = [t.model_dump() for t in payload.tests]
    db.commit()
    db.refresh(task)
    return task


def to_student_problem_out(task: ProblemRevision) -> ProblemRevisionStudentOut:
    """STU-003: студент не должен получить вход/эталонный вывод скрытых
    тестов (иначе можно захардкодить решение под конкретный скрытый набор,
    не решая задачу) — отдаём только is_hidden=False."""
    visible = [ProblemTestOut(**t) for t in (task.tests or []) if not t.get("is_hidden")]
    return ProblemRevisionStudentOut(
        id=task.id,
        title=task.title,
        statement=task.statement,
        input_format=task.input_format,
        output_format=task.output_format,
        constraints=task.constraints,
        time_limit_ms=task.time_limit_ms,
        memory_limit_mb=task.memory_limit_mb,
        language=task.language,
        allowed_libraries=task.allowed_libraries,
        visible_tests=visible,
    )


def create_item(db: Session, course_id: int, payload: LearningItemCreate) -> LearningItem:
    version = get_draft_version(db, course_id)

    try:
        item_type = LearningItemType(payload.type)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Неизвестный тип элемента: {payload.type}")

    if item_type == LearningItemType.TASK and not payload.problem_revision_id:
        raise HTTPException(status_code=422, detail="Для элемента типа task нужен problem_revision_id")
    if item_type == LearningItemType.SNAP_TASK and not payload.steps:
        raise HTTPException(status_code=422, detail="Для элемента типа snap_task нужен хотя бы один этап (steps)")

    parent: Optional[LearningItem] = None
    if payload.parent_id is not None:
        parent = (
            db.query(LearningItem)
            .filter(LearningItem.id == payload.parent_id, LearningItem.course_version_id == version.id)
            .first()
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Родительский элемент не найден в черновике этого курса")

    validate_parent(item_type, parent)

    item = LearningItem(
        course_version_id=version.id,
        parent_id=payload.parent_id,
        type=item_type,
        title=payload.title,
        description=payload.description,
        content=payload.content,
        is_required=payload.is_required,
        weight=payload.weight,
        position=payload.position,
        unlock_rules=payload.unlock_rules,
        problem_revision_id=payload.problem_revision_id,
        steps=[s.model_dump() for s in payload.steps] if payload.steps else None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _get_draft_item_or_404(db: Session, item_id: int) -> LearningItem:
    item = db.query(LearningItem).filter(LearningItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Элемент не найден")
    version = db.query(CourseVersion).filter(CourseVersion.id == item.course_version_id).first()
    if version and version.published_at is not None:
        raise HTTPException(status_code=409, detail="Нельзя менять уже опубликованную версию курса")
    return item


def _collect_descendant_ids(db: Session, root_id: int) -> list[int]:
    """Обход в ширину — id возвращаются уровень за уровнем (родители раньше
    своих детей), это важно для порядка каскадного удаления ниже."""
    all_ids: list[int] = []
    frontier = [root_id]
    while frontier:
        children = db.query(LearningItem.id).filter(LearningItem.parent_id.in_(frontier)).all()
        child_ids = [c.id for c in children]
        all_ids.extend(child_ids)
        frontier = child_ids
    return all_ids


def update_item(db: Session, item_id: int, payload: LearningItemUpdate) -> LearningItem:
    item = _get_draft_item_or_404(db, item_id)

    updates = payload.model_dump(exclude_unset=True)
    if "parent_id" in updates:
        new_parent_id = updates["parent_id"]
        if new_parent_id == item_id:
            raise HTTPException(status_code=422, detail="Элемент не может быть родителем самому себе")
        new_parent = db.query(LearningItem).filter(LearningItem.id == new_parent_id).first() if new_parent_id is not None else None
        if new_parent_id is not None and not new_parent:
            raise HTTPException(status_code=404, detail="Родительский элемент не найден")
        if new_parent is not None and new_parent.id in _collect_descendant_ids(db, item_id):
            raise HTTPException(status_code=422, detail="Нельзя переместить узел внутрь его же поддерева")
        validate_parent(item.type, new_parent)

    for field, value in updates.items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, item_id: int) -> None:
    """Каскадно удаляет узел вместе со всем поддеревом (иерархия
    Модуль/Подмодуль/Тема/Подтема — снос ветки целиком, по решению
    владельца продукта 2026-09-22). Порядок — от листьев к корню, иначе
    self-referential FK parent_id не даст удалить родителя раньше детей."""
    item = _get_draft_item_or_404(db, item_id)

    descendant_ids = _collect_descendant_ids(db, item_id)
    for descendant_id in reversed(descendant_ids):
        db.query(LearningItem).filter(LearningItem.id == descendant_id).delete()
    db.delete(item)
    db.commit()


def set_item_archived(db: Session, item_id: int, archived: bool) -> LearningItem:
    """Архивация каскадится на всё поддерево — скрытая тема прячет и все
    свои подтемы/материалы, не только себя (симметрично delete_item)."""
    item = _get_draft_item_or_404(db, item_id)

    ids = [item_id, *_collect_descendant_ids(db, item_id)]
    db.query(LearningItem).filter(LearningItem.id.in_(ids)).update({"is_archived": archived}, synchronize_session=False)
    db.commit()
    db.refresh(item)
    return item


async def publish_course(db: Session, course_id: int, actor_id: int | None) -> Course:
    """LMS-005/006: текущий черновик становится неизменяемой опубликованной
    версией (published_at, course.active_version_id), а для дальнейшего
    редактирования сразу открывается новый черновик — клон только что
    опубликованного дерева, чтобы правки не задевали уже назначенное
    ученикам. Проверка целостности перед публикацией (LMS-010) — TODO."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    draft = get_draft_version(db, course_id)

    draft.published_at = datetime.now(timezone.utc)
    course.active_version_id = draft.id
    course.status = CourseStatus.PUBLISHED
    db.flush()

    new_version = CourseVersion(course_id=course.id, version_number=draft.version_number + 1)
    db.add(new_version)
    db.flush()

    old_items = (
        db.query(LearningItem)
        .filter(LearningItem.course_version_id == draft.id)
        .order_by(LearningItem.id)
        .all()
    )
    id_map: dict[int, int] = {}
    for old in old_items:
        clone = LearningItem(
            course_version_id=new_version.id,
            parent_id=None,  # проставим вторым проходом по id_map
            type=old.type,
            title=old.title,
            description=old.description,
            content=old.content,
            is_required=old.is_required,
            weight=old.weight,
            position=old.position,
            unlock_rules=old.unlock_rules,
            problem_revision_id=old.problem_revision_id,
            is_archived=old.is_archived,
            steps=old.steps,
        )
        db.add(clone)
        db.flush()
        id_map[old.id] = clone.id
    for old in old_items:
        if old.parent_id:
            db.query(LearningItem).filter(LearningItem.id == id_map[old.id]).update(
                {"parent_id": id_map[old.parent_id]}
            )

    db.add(AuditEvent(actor_id=actor_id, action="course_publish", object_type="course", object_id=course.id, meta={"version_id": draft.id}))
    db.commit()
    db.refresh(course)

    await notify_course_webhook(course, "published")
    return course


def rerun_submissions(db: Session, course_id: int, submission_ids: list[int]) -> int:
    """TASK-007: массовая перепроверка после исправления тестов задачи.
    Учитываются только посылки, чьи задачи реально принадлежат этому курсу
    (любой версии) — не позволяет переставить в очередь чужие посылки,
    даже если их id угадать."""
    version_ids = [v.id for v in db.query(CourseVersion).filter(CourseVersion.course_id == course_id)]
    problem_ids = {
        i.problem_revision_id
        for i in db.query(LearningItem).filter(
            LearningItem.course_version_id.in_(version_ids), LearningItem.type == LearningItemType.TASK
        )
        if i.problem_revision_id
    }
    if not problem_ids:
        return 0

    submissions = (
        db.query(Submission)
        .filter(Submission.id.in_(submission_ids), Submission.problem_revision_id.in_(problem_ids))
        .all()
    )
    for s in submissions:
        s.status = SubmissionStatus.QUEUED
        s.priority = 10
        s.verdict = None
        s.score = None
        s.stdout = None
        s.stderr = None
    db.commit()
    return len(submissions)


def list_course_submissions(db: Session, course_id: int) -> list[SubmissionReviewOut]:
    """TCH-001/003: посылки по задачам активной (опубликованной) версии
    курса — преподаватель просматривает исходный код и результаты. Версия
    методиста-черновика намеренно не включается — там ещё нет реальных
    зачислений и посылок учеников."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")
    if not course.active_version_id:
        return []

    task_items = (
        db.query(LearningItem)
        .filter(LearningItem.course_version_id == course.active_version_id, LearningItem.type == LearningItemType.TASK)
        .all()
    )
    problem_to_title = {i.problem_revision_id: i.title for i in task_items if i.problem_revision_id}
    if not problem_to_title:
        return []

    submissions = (
        db.query(Submission)
        .filter(Submission.problem_revision_id.in_(problem_to_title.keys()))
        .order_by(Submission.created_at.desc())
        .all()
    )
    user_ids = {s.user_id for s in submissions}
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    return [
        SubmissionReviewOut(
            submission_id=s.id,
            student_external_ref=users_by_id[s.user_id].external_ref if s.user_id in users_by_id else "?",
            student_full_name=users_by_id[s.user_id].full_name if s.user_id in users_by_id else "?",
            item_title=problem_to_title.get(s.problem_revision_id, f"Задача {s.problem_revision_id}"),
            code=s.code,
            status=s.status.value,
            verdict=s.verdict.value if s.verdict else None,
            score=s.score,
            manual_score_override=s.manual_score_override,
            manual_comment=s.manual_comment,
            created_at=s.created_at,
        )
        for s in submissions
    ]


async def unpublish_course(db: Session, course_id: int, actor_id: int | None) -> Course:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    course.status = CourseStatus.ARCHIVED
    db.add(AuditEvent(actor_id=actor_id, action="course_unpublish", object_type="course", object_id=course.id))
    db.commit()
    db.refresh(course)

    await notify_course_webhook(course, "unpublished")
    return course
