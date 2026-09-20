"""LMS-001..006, LMS-010, TASK-001..004 — конструктор курса: иерархия учебных
элементов, привязка задач, публикация версии. Полноценный редактор контента
(раздел 5.3) сюда пока не входит — см. README, раздел «не реализовано»."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models import (
    AuditEvent,
    Course,
    CourseStatus,
    CourseVersion,
    LearningItem,
    LearningItemType,
    ProblemRevision,
    User,
)
from app.schemas import (
    CourseCreate,
    CourseOut,
    LearningItemCreate,
    LearningItemOut,
    LearningItemTree,
    LearningItemUpdate,
    ProblemRevisionCreate,
    ProblemRevisionOut,
)
from app.services.lms_client import notify_course_webhook

router = APIRouter()


def _get_draft_version(db: Session, course_id: int) -> CourseVersion:
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


def _build_tree(items: list[LearningItem]) -> list[LearningItemTree]:
    # LearningItemOut (без "children") — иначе model_validate(item) читает
    # реальный ORM-relationship LearningItem.children и рекурсивно тянет его
    # из БД, задваивая узлы поверх дерева, которое мы строим вручную ниже.
    nodes = {i.id: LearningItemTree(**LearningItemOut.model_validate(i).model_dump(), children=[]) for i in items}
    roots: list[LearningItemTree] = []
    for item in items:
        node = nodes[item.id]
        if item.parent_id and item.parent_id in nodes:
            nodes[item.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


@router.get("", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Course)
    if user.role == "student":
        query = query.filter(Course.status == CourseStatus.PUBLISHED)
    return query.order_by(Course.id).all()


@router.post("", response_model=CourseOut)
def create_course(payload: CourseCreate, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    course = Course(title=payload.title, slug=payload.slug, description=payload.description, created_by_id=user.id)
    db.add(course)
    db.flush()
    db.add(CourseVersion(course_id=course.id, version_number=1))
    db.commit()
    db.refresh(course)
    return course


@router.post("/{course_id}/tasks", response_model=ProblemRevisionOut)
def create_task(
    course_id: int,
    payload: ProblemRevisionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    """Создаёт задачу (первую ревизию задачи — task_id сквозной по всей
    платформе, не по курсу, TASK-006). Привязка к дереву — POST .../items
    с type="task" и этим problem_revision_id."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    last = db.query(ProblemRevision).order_by(ProblemRevision.task_id.desc()).first()
    next_task_id = (last.task_id + 1) if last else 1
    revision = ProblemRevision(
        task_id=next_task_id,
        revision_number=1,
        author_id=user.id,
        **payload.model_dump(exclude={"tests"}),
        tests=[t.model_dump() for t in payload.tests],
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    return revision


@router.post("/{course_id}/items", response_model=LearningItemOut)
def create_item(
    course_id: int,
    payload: LearningItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    version = _get_draft_version(db, course_id)

    try:
        item_type = LearningItemType(payload.type)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Неизвестный тип элемента: {payload.type}")

    if item_type == LearningItemType.TASK and not payload.problem_revision_id:
        raise HTTPException(status_code=422, detail="Для элемента типа task нужен problem_revision_id")

    if payload.parent_id is not None:
        parent = (
            db.query(LearningItem)
            .filter(LearningItem.id == payload.parent_id, LearningItem.course_version_id == version.id)
            .first()
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Родительский элемент не найден в черновике этого курса")

    item = LearningItem(
        course_version_id=version.id,
        parent_id=payload.parent_id,
        type=item_type,
        title=payload.title,
        description=payload.description,
        is_required=payload.is_required,
        weight=payload.weight,
        position=payload.position,
        unlock_rules=payload.unlock_rules,
        problem_revision_id=payload.problem_revision_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/items/{item_id}", response_model=LearningItemOut)
def update_item(
    item_id: int,
    payload: LearningItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    item = db.query(LearningItem).filter(LearningItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Элемент не найден")

    version = db.query(CourseVersion).filter(CourseVersion.id == item.course_version_id).first()
    if version and version.published_at is not None:
        raise HTTPException(status_code=409, detail="Нельзя менять уже опубликованную версию курса")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    """RBAC-004: удаление учебных сущностей — через архивирование, если на них
    есть назначения/попытки/ссылки из отчётов. У элемента черновика ссылок
    на назначения ещё быть не может (черновик не назначен), поэтому здесь —
    обычное удаление; для опубликованных версий редактирование запрещено выше."""
    item = db.query(LearningItem).filter(LearningItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Элемент не найден")

    version = db.query(CourseVersion).filter(CourseVersion.id == item.course_version_id).first()
    if version and version.published_at is not None:
        raise HTTPException(status_code=409, detail="Нельзя менять уже опубликованную версию курса")

    db.query(LearningItem).filter(LearningItem.parent_id == item_id).update({"parent_id": None})
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.get("/{course_id}/tree", response_model=list[LearningItemTree])
def get_tree(course_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    if user.role == "student":
        # STU-002/STU-003: ученик видит только опубликованную версию, прогресс
        # считается по ней и не может поменяться из-за правок черновика.
        if not course.active_version_id:
            raise HTTPException(status_code=404, detail="Курс ещё не опубликован")
        version_id = course.active_version_id
    else:
        version_id = _get_draft_version(db, course_id).id

    items = db.query(LearningItem).filter(LearningItem.course_version_id == version_id).order_by(LearningItem.position).all()
    return _build_tree(items)


@router.post("/{course_id}/publish", response_model=CourseOut)
async def publish_course(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    """LMS-005/006: текущий черновик становится неизменяемой опубликованной
    версией (published_at, course.active_version_id), а для дальнейшего
    редактирования сразу открывается новый черновик — клон только что
    опубликованного дерева, чтобы правки не затрагивали уже назначенное
    ученикам (LMS-006). Проверка целостности перед публикацией (LMS-010:
    обязательные поля, тесты у задач и т.д.) здесь упрощена — TODO."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    draft = _get_draft_version(db, course_id)

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
            is_required=old.is_required,
            weight=old.weight,
            position=old.position,
            unlock_rules=old.unlock_rules,
            problem_revision_id=old.problem_revision_id,
        )
        db.add(clone)
        db.flush()
        id_map[old.id] = clone.id
    for old in old_items:
        if old.parent_id:
            db.query(LearningItem).filter(LearningItem.id == id_map[old.id]).update(
                {"parent_id": id_map[old.parent_id]}
            )

    db.add(AuditEvent(actor_id=user.id, action="course_publish", object_type="course", object_id=course.id, meta={"version_id": draft.id}))
    db.commit()
    db.refresh(course)

    await notify_course_webhook(course, "published")
    return course


@router.post("/{course_id}/unpublish", response_model=CourseOut)
async def unpublish_course(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    course.status = CourseStatus.ARCHIVED
    db.add(AuditEvent(actor_id=user.id, action="course_unpublish", object_type="course", object_id=course.id))
    db.commit()
    db.refresh(course)

    await notify_course_webhook(course, "unpublished")
    return course
