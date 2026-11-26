"""Подписанный сервер-к-серверу API для learning-portal-main: методист и
преподаватель работают через свой аккаунт LMS, не заходя в Codelab напрямую
(решение от 2026-09-21, см. README «Интеграция с порталом»). LMS уже проверила
роль и права пользователя на своей стороне — здесь только доверяем подписи
общим секретом (как enroll/unenroll/lms-progress в lms_integration.py) и
заводим/обновляем лёгкую учётку методиста/преподавателя в Codelab для
атрибуции (created_by_id, AuditEvent.actor_id).

Контракт согласован с backend/app/services/codelab_studio.py в
learning-portal-main — менять пути и подпись запроса только синхронно с той
стороной.
"""
from fastapi import APIRouter, Depends, File as FastAPIFile, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Course, CourseVersion, LearningItem, LoginEvent, User
from app.schemas import (
    AdminLoginEventOut,
    AdminSystemStatusOut,
    AdminUserBlockIn,
    AdminUserOut,
    BulkEditIn,
    BulkEditItemResultOut,
    BulkEditOut,
    ChangeSetOut,
    CourseAnalyticsOut,
    CourseArchiveIn,
    CourseCreate,
    CourseOut,
    CourseDraftStatusOut,
    CourseUpdate,
    CourseValidationOut,
    EnvironmentOut,
    ImportPreviewOut,
    ImportResultOut,
    ImportRowOut,
    LearningItemArchiveIn,
    LearningItemCreate,
    LearningItemOut,
    LearningItemTree,
    LearningItemUpdate,
    ManualGradeIn,
    ProblemRevisionCreate,
    ProblemRevisionOut,
    ProjectFileCommentIn,
    ProjectFileCommentOut,
    ProjectReviewIn,
    ProjectSubmissionOut,
    ProjectSubmissionReviewOut,
    RerunSubmissionsIn,
    RerunSubmissionsOut,
    SubmissionOut,
    SubmissionReviewOut,
    UploadOut,
)
from app.security import verify_lms_signature
from app.services import admin_status, analytics, bulk_edit, course_admin, project_admin
from app.services.course_changes import get_course_changes
from app.services.course_validator import normalize_draft_positions, validate_course_before_publish
from app.services.task_import import import_tasks, mark_duplicates, parse_import_file
from app.services.environments import list_environments
from app.services.progress_calc import apply_manual_grade
from app.services.project_files import project_file_path
from app.services.uploads import save_upload

router = APIRouter()


def resolve_staff_user(
    db: Session = Depends(get_db),
    staff_external_ref: str = Query(..., description='Например "lp-user-42"'),
    staff_full_name: str = Query(...),
    staff_role: str = Query(..., description="methodist | teacher | admin"),
    x_lp_signature: str = Header(default=""),
) -> User:
    if staff_role not in ("methodist", "teacher", "admin"):
        raise HTTPException(status_code=422, detail="Недопустимая роль")
    if not verify_lms_signature(staff_external_ref.encode(), x_lp_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверная подпись")

    user = db.query(User).filter(User.external_ref == staff_external_ref).first()
    if not user:
        user = User(external_ref=staff_external_ref, full_name=staff_full_name, role=staff_role)
        db.add(user)
    else:
        user.full_name = staff_full_name
        user.role = staff_role
    db.commit()
    db.refresh(user)
    return user


@router.get("/environments", response_model=list[EnvironmentOut])
def get_environments(staff: User = Depends(resolve_staff_user)):
    """ADM-001: реестр окружений исполнения — методист выбирает отсюда язык
    задачи (ProblemRevisionCreate.language), а не гадает, что установлено в
    образе. Доступно любому авторизованному сотруднику LMS, не только admin —
    это справочная информация, нужная при авторстве курса."""
    return [
        EnvironmentOut(
            id=e.id, label=e.label, allowed_libraries=e.allowed_libraries,
            status=e.status, status_note=e.status_note,
        )
        for e in list_environments()
    ]


@router.get("/courses", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """RBAC-002: методист видит только свои курсы (для управления ими).
    Teacher/admin видят все опубликованные курсы платформы — им нужно
    выбирать среди курсов, которые создавали разные методисты, чтобы
    посмотреть посылки/аналитику своей группы, привязка "курс → методист"
    для этого не имеет значения."""
    query = db.query(Course)
    if staff.role == "methodist":
        query = query.filter(Course.created_by_id == staff.id)
    return query.order_by(Course.id).all()


@router.post("/courses", response_model=CourseOut)
def create_course(payload: CourseCreate, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    return course_admin.create_course(db, payload, created_by_id=staff.id)


@router.post("/courses/{course_id}/tasks", response_model=ProblemRevisionOut)
def create_task(
    course_id: int,
    payload: ProblemRevisionCreate,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return course_admin.create_task(db, course_id, payload, author_id=staff.id)


def _ensure_task_owner(db: Session, problem_revision_id: int, staff: User, *, allow_teacher: bool = False) -> None:
    course = course_admin.get_course_for_task(db, problem_revision_id)
    if course:
        course_admin.ensure_course_owner(course, staff, allow_teacher=allow_teacher)
    elif staff.role not in ("methodist", "admin") and not (allow_teacher and staff.role == "teacher"):
        # Задача создана, но ещё не привязана в дерево ни одного курса —
        # владельца проверить нечем; пускаем только тех, кто вообще может
        # авторствовать задачи (create_task и так требует того же).
        raise HTTPException(status_code=403, detail="Недостаточно прав")


@router.get("/tasks/{problem_revision_id}", response_model=ProblemRevisionOut)
def get_task(problem_revision_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """Read-only — отдаёт задачу целиком, включая скрытые тесты. Доступно
    и teacher (не только methodist/admin): тренеру нужно видеть задачу
    полностью при разборе посылки ученика (п.14.10.2026)."""
    task = course_admin.get_task_or_404(db, problem_revision_id)
    _ensure_task_owner(db, problem_revision_id, staff, allow_teacher=True)
    return task


@router.put("/tasks/{problem_revision_id}", response_model=ProblemRevisionOut)
async def update_task(
    problem_revision_id: int,
    payload: ProblemRevisionCreate,
    publish: bool = Query(True),
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """Правки применяются на месте — существующие посылки продолжают
    ссылаться на тот же problem_revision_id, TASK-007 (массовая
    перепроверка) после этого перепроверяет их по исправленным тестам."""
    course_admin.get_task_or_404(db, problem_revision_id)
    _ensure_task_owner(db, problem_revision_id, staff)
    result = course_admin.update_task(db, problem_revision_id, payload)
    course = course_admin.get_course_for_task(db, problem_revision_id)
    if course and publish:
        await course_admin.publish_course(db, course.id, actor_id=staff.id)
    return result


@router.post("/courses/{course_id}/items", response_model=LearningItemOut)
async def create_item(
    course_id: int,
    payload: LearningItemCreate,
    publish: bool = Query(True),
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    result = course_admin.create_item(db, course_id, payload)
    if publish:
        return await course_admin.auto_publish_item(db, course_id, result.id, actor_id=staff.id)
    return result


@router.put("/items/{item_id}", response_model=LearningItemOut)
async def update_item(
    item_id: int,
    payload: LearningItemUpdate,
    publish: bool = Query(True),
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    _, course = course_admin.get_course_for_item(db, item_id)
    course_admin.ensure_course_owner(course, staff)
    result = course_admin.update_item(db, item_id, payload)
    if publish:
        return await course_admin.auto_publish_item(db, course.id, result.id, actor_id=staff.id)
    return result


@router.get("/items/{item_id}", response_model=LearningItemOut)
def get_item(item_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """Полное содержимое одного элемента (content/steps/quiz_questions/
    oge_answer) — конструктор дозапрашивает это только при открытии элемента
    на редактирование, т.к. /courses/{course_id}/tree теперь lean (см.
    build_tree)."""
    item, course = course_admin.get_course_for_item(db, item_id)
    course_admin.ensure_course_owner(course, staff)
    return item


@router.delete("/items/{item_id}")
async def delete_item(item_id: int, publish: bool = Query(True), db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    _, course = course_admin.get_course_for_item(db, item_id)
    course_admin.ensure_course_owner(course, staff)
    course_admin.delete_item(db, item_id)
    if publish:
        await course_admin.publish_course(db, course.id, actor_id=staff.id)
    return {"ok": True}


@router.put("/items/{item_id}/archive", response_model=LearningItemOut)
async def archive_item(
    item_id: int,
    payload: LearningItemArchiveIn,
    publish: bool = Query(True),
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """Архивация/разархивация узла — каскадно на всё поддерево, см.
    course_admin.set_item_archived."""
    _, course = course_admin.get_course_for_item(db, item_id)
    course_admin.ensure_course_owner(course, staff)
    result = course_admin.set_item_archived(db, item_id, payload.archived)
    if publish:
        return await course_admin.auto_publish_item(db, course.id, result.id, actor_id=staff.id)
    return result


@router.get("/courses/{course_id}/tree", response_model=list[LearningItemTree])
def get_tree(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """Методист и admin (управляющие роли — см. ensure_course_owner) получают
    черновик для редактирования; преподаватель — только опубликованное
    дерево, чтобы выбрать проект для проверки работ учеников. Иначе "+
    Материал" на узле из опубликованного дерева бьёт в create_item, который
    ищет parent_id среди элементов ЧЕРНОВИКА — и падает 404, потому что
    id узлов опубликованной и черновой версий не совпадают."""
    course = course_admin.get_course_or_404(db, course_id)
    if staff.role in ("methodist", "admin"):
        course_admin.ensure_course_owner(course, staff)
        version = course_admin.get_draft_version(db, course_id)
    else:
        if not course.active_version_id:
            raise HTTPException(status_code=404, detail="Курс ещё не опубликован")
        version = (
            db.query(CourseVersion)
            .filter(CourseVersion.id == course.active_version_id, CourseVersion.course_id == course_id)
            .first()
        )
        if not version:
            raise HTTPException(status_code=404, detail="Опубликованная версия курса не найдена")
    items = db.query(LearningItem).filter(LearningItem.course_version_id == version.id).order_by(LearningItem.position).all()
    return course_admin.build_tree(items, lean=True)


@router.put("/courses/{course_id}", response_model=CourseOut)
def update_course(
    course_id: int, payload: CourseUpdate,
    db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return course_admin.update_course(db, course_id, payload)


@router.put("/courses/{course_id}/archive", response_model=CourseOut)
def archive_course(
    course_id: int, payload: CourseArchiveIn,
    db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return course_admin.set_course_archived(db, course_id, payload.archived)


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    course_admin.delete_course(db, course_id)


@router.get("/courses/{course_id}/changes", response_model=list[ChangeSetOut])
def get_changes(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """Этап 10 (ТЗ): история изменений курса — диф между последовательными
    опубликованными версиями, самые свежие первыми (см.
    app/services/course_changes.py — почему не "черновик против активной")."""
    if staff.role == "methodist":
        course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return get_course_changes(db, course_id)


@router.get("/courses/{course_id}/draft-status", response_model=CourseDraftStatusOut)
def get_draft_status(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    if staff.role == "methodist":
        course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return course_admin.get_draft_status(db, course_id)


@router.get("/courses/{course_id}/validation", response_model=CourseValidationOut)
def get_course_validation(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """LMS-010: список проблем черновика — чтобы фронтенд методиста мог
    показать их до попытки опубликовать (сама публикация блокируется тем
    же списком в publish_course ниже)."""
    if staff.role == "methodist":
        course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    normalize_draft_positions(db, course_id)
    errors = validate_course_before_publish(db, course_id)
    return CourseValidationOut(valid=not errors, errors=errors, warnings=[])


@router.post("/courses/{course_id}/restore-draft", response_model=CourseDraftStatusOut)
def restore_draft(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    course_admin.restore_draft_from_active(db, course_id, actor_id=staff.id)
    return course_admin.get_draft_status(db, course_id)


@router.post("/courses/{course_id}/publish", response_model=CourseOut)
async def publish_course(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    normalize_draft_positions(db, course_id)
    errors = validate_course_before_publish(db, course_id)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"valid": False, "errors": [e.__dict__ for e in errors], "warnings": []},
        )
    return await course_admin.publish_course(db, course_id, actor_id=staff.id)


@router.post("/courses/{course_id}/import-tasks/preview", response_model=ImportPreviewOut)
async def preview_import_tasks(
    course_id: int, file: UploadFile = FastAPIFile(...),
    db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    """Этап 8 (ТЗ): разбор CSV/XLSX без создания элементов — методист видит
    ошибки и дубликаты до подтверждения (POST .../import-tasks ниже)."""
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    data = await file.read()
    rows = parse_import_file(file.filename or "", data)
    mark_duplicates(db, course_id, rows)
    return ImportPreviewOut(
        rows=[ImportRowOut(line=r.line, title=r.title, module=r.module, errors=r.errors, duplicate=r.duplicate, valid=r.valid) for r in rows],
        valid_count=sum(1 for r in rows if r.valid and not r.duplicate),
        error_count=sum(1 for r in rows if not r.valid),
        duplicate_count=sum(1 for r in rows if r.duplicate),
    )


@router.post("/courses/{course_id}/import-tasks", response_model=ImportResultOut)
async def do_import_tasks(
    course_id: int, file: UploadFile = FastAPIFile(...), publish: bool = Query(False),
    db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    """Этап 8 (ТЗ): создаёт задания ОГЭ из валидных, не дублирующихся строк.
    publish=false (по умолчанию) — "Создать как черновик": задания остаются
    неопубликованными, как любая другая правка методиста. publish=true —
    "Создать и опубликовать": сразу вызывает publish_course, который
    (см. Этап 4) сам откажет 422, если черновик в целом невалиден —
    например, другое, не связанное с импортом задание осталось без ответа."""
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    data = await file.read()
    rows = parse_import_file(file.filename or "", data)
    mark_duplicates(db, course_id, rows)
    result = import_tasks(db, course_id, rows, actor_id=staff.id)

    if publish:
        errors = validate_course_before_publish(db, course_id)
        if errors:
            raise HTTPException(
                status_code=422,
                detail={"valid": False, "errors": [e.__dict__ for e in errors], "warnings": [], "import_result": result},
            )
        await course_admin.publish_course(db, course_id, actor_id=staff.id)

    return ImportResultOut(**result, published=publish)


@router.post("/courses/{course_id}/items/bulk", response_model=BulkEditOut)
def bulk_edit_items(
    course_id: int, payload: BulkEditIn,
    db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    """Этап 9 (ТЗ) — массовое редактирование. "Изменить тип" сознательно не
    реализовано (см. app/services/bulk_edit.py)."""
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)

    if payload.operation == "archive":
        results = bulk_edit.bulk_archive(db, course_id, payload.item_ids, True)
    elif payload.operation == "unarchive":
        results = bulk_edit.bulk_archive(db, course_id, payload.item_ids, False)
    elif payload.operation == "delete":
        results = bulk_edit.bulk_delete(db, course_id, payload.item_ids)
    elif payload.operation == "set_required":
        if payload.required is None:
            raise HTTPException(status_code=422, detail="Для set_required нужно поле required")
        results = bulk_edit.bulk_set_required(db, course_id, payload.item_ids, payload.required)
    elif payload.operation == "set_weight":
        if payload.weight is None:
            raise HTTPException(status_code=422, detail="Для set_weight нужно поле weight")
        results = bulk_edit.bulk_set_weight(db, course_id, payload.item_ids, payload.weight)
    elif payload.operation == "set_max_attempts":
        results = bulk_edit.bulk_set_max_attempts(db, course_id, payload.item_ids, payload.max_attempts)
    elif payload.operation == "move":
        if "parent_id" not in payload.model_fields_set:
            raise HTTPException(status_code=422, detail="Для move нужно поле parent_id (null — перенести в корень курса)")
        results = bulk_edit.bulk_move(db, course_id, payload.item_ids, payload.parent_id)
    elif payload.operation == "copy_to_course":
        if payload.target_course_id is None:
            raise HTTPException(status_code=422, detail="Для copy_to_course нужно поле target_course_id")
        course_admin.ensure_course_owner(course_admin.get_course_or_404(db, payload.target_course_id), staff)
        results = bulk_edit.bulk_copy_to_course(db, course_id, payload.item_ids, payload.target_course_id)
    else:
        # Недостижимо — BulkEditIn.operation уже проверен Pydantic-валидатором.
        raise HTTPException(status_code=422, detail=f"Неизвестная операция: {payload.operation}")

    out = [BulkEditItemResultOut(item_id=r.item_id, ok=r.ok, error=r.error) for r in results]
    return BulkEditOut(
        operation=payload.operation, results=out,
        succeeded=sum(1 for r in out if r.ok), failed=sum(1 for r in out if not r.ok),
    )


@router.get("/courses/{course_id}/items/export", response_model=list[LearningItemOut])
def export_items(
    course_id: int, item_ids: list[int] = Query(...),
    db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    """Этап 9 (ТЗ) — "экспортировать": снимок выбранных элементов черновика
    в JSON (порядок — как в item_ids, отсутствующие/чужие id молча
    пропускаются, как и в bulk_edit)."""
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    by_id = bulk_edit.items_in_draft(db, course_id, item_ids)
    return [by_id[i] for i in item_ids if i in by_id]


@router.post("/courses/{course_id}/unpublish", response_model=CourseOut)
async def unpublish_course(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return await course_admin.unpublish_course(db, course_id, actor_id=staff.id)


@router.get("/courses/{course_id}/submissions", response_model=list[SubmissionReviewOut])
def list_course_submissions(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """TCH-001/003: преподаватель/методист смотрит посылки учеников по курсу.
    RBAC-002: методисту — только по своим курсам; у преподавателя фильтрация
    по своим группам делается на стороне LMS (там есть группы), см. README."""
    if staff.role == "methodist":
        course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return course_admin.list_course_submissions(db, course_id)


@router.put("/courses/{course_id}/submissions/{submission_id}/grade", response_model=SubmissionOut)
def grade_submission(
    course_id: int,
    submission_id: int,
    payload: ManualGradeIn,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """GRD-004/TCH-004: ручная корректировка результата с обязательным
    комментарием. course_id в пути — не только для методиста (RBAC-002:
    только свои курсы), но и чтобы LMS могла ДО вызова дёшево проверить, что
    посылка относится именно к тому курсу/группе, к которым у вызывающего
    тренера есть доступ (см. codelab.py в learning-portal-main) — раньше
    эндпоинт принимал только submission_id, и такую проверку сделать было
    нечем."""
    course = course_admin.get_course_or_404(db, course_id)
    if staff.role == "methodist":
        course_admin.ensure_course_owner(course, staff)

    actual_course = course_admin.get_course_for_submission(db, submission_id)
    if actual_course and actual_course.id != course_id:
        raise HTTPException(status_code=404, detail="Посылка не относится к указанному курсу")

    return apply_manual_grade(db, submission_id, payload.score, payload.comment)


@router.post("/courses/{course_id}/submissions/rerun", response_model=RerunSubmissionsOut)
def rerun_submissions(
    course_id: int,
    payload: RerunSubmissionsIn,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """TASK-007: массовая перепроверка после исправления тестов задачи.
    RBAC-002: методисту — только по своим курсам; в очередь встают только
    те посылки из переданного списка, чьи задачи реально принадлежат этому
    курсу (нельзя перезапустить чужую посылку, угадав id)."""
    if staff.role == "methodist":
        course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    requeued = course_admin.rerun_submissions(db, course_id, payload.submission_ids)
    return RerunSubmissionsOut(requeued=requeued)


@router.get("/courses/{course_id}/analytics", response_model=CourseAnalyticsOut)
def get_course_analytics(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """ANA-001/002/005: сводка по курсу и рейтинг задач по сложности.
    RBAC-002: методисту — только по своим курсам."""
    from datetime import datetime, timezone

    if staff.role == "methodist":
        course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)

    oge_tasks = analytics.oge_task_analytics(db, course_id)
    return CourseAnalyticsOut(
        generated_at=datetime.now(timezone.utc),
        overview=analytics.course_overview(db, course_id),
        tasks=analytics.task_difficulty(db, course_id),
        oge_overview=analytics.oge_overview(db, course_id, oge_tasks),
        oge_tasks=oge_tasks,
    )


@router.get("/courses/{course_id}/projects/{item_id}/submissions", response_model=list[ProjectSubmissionReviewOut])
def list_project_submissions(
    course_id: int, item_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    """Ростер сдач проекта — по строке на ученика (последняя попытка), с
    ученика без ни одной попытки заводится пустой DRAFT (см.
    project_admin._ensure_roster_submissions), чтобы тренер мог напомнить и
    тем, кто ещё не начинал. RBAC-002: методисту — только свои курсы; фильтр
    по группе тренера — на портале (learning-portal-main/routers/codelab.py)."""
    if staff.role == "methodist":
        course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)

    item = project_admin.get_project_item_or_404(db, item_id)
    actual_course = project_admin.get_course_for_project_item(db, item)
    if not actual_course or actual_course.id != course_id:
        raise HTTPException(status_code=404, detail="Проект не относится к указанному курсу")

    return project_admin.list_project_submissions(db, item_id)


@router.get("/projects/submissions/{submission_id}", response_model=ProjectSubmissionOut)
def get_project_submission(
    submission_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    course = project_admin.get_course_for_project_submission(db, submission_id)
    if course and staff.role == "methodist":
        course_admin.ensure_course_owner(course, staff)
    return project_admin.get_submission_detail(db, submission_id)


@router.get("/projects/files/{file_id}/download")
def download_project_file(
    file_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    f = project_admin.get_file_or_404(db, file_id)
    course = project_admin.get_course_for_project_submission(db, f.submission_id)
    if course and staff.role == "methodist":
        course_admin.ensure_course_owner(course, staff)

    path = project_file_path(f.stored_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден на диске")
    course_admin.log_file_download(db, staff.id, "project_file", f.id, f.original_filename)
    return FileResponse(path, media_type=f.content_type, filename=f.original_filename)


@router.post("/projects/files/{file_id}/comments", response_model=ProjectFileCommentOut, status_code=201)
def comment_project_file(
    file_id: int, payload: ProjectFileCommentIn, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    course = project_admin.get_course_for_project_submission(
        db, project_admin.get_file_or_404(db, file_id).submission_id,
    )
    if course and staff.role == "methodist":
        course_admin.ensure_course_owner(course, staff)

    comment = project_admin.add_file_comment(db, file_id, staff.id, payload.body)
    return ProjectFileCommentOut(
        id=comment.id, author_id=comment.author_id, author_full_name=staff.full_name,
        body=comment.body, created_at=comment.created_at,
    )


@router.put("/projects/submissions/{submission_id}/review", response_model=ProjectSubmissionOut)
def review_project_submission(
    submission_id: int, payload: ProjectReviewIn, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    """GRD-004-аналог для проектов: комментарий обязателен (см.
    ProjectReviewIn), оценка обязательна при decision=accepted."""
    course = project_admin.get_course_for_project_submission(db, submission_id)
    if course and staff.role == "methodist":
        course_admin.ensure_course_owner(course, staff)

    submission = project_admin.apply_project_review(db, submission_id, payload, staff.id)
    item = project_admin.get_project_item_or_404(db, submission.learning_item_id)
    return project_admin.to_submission_out(db, item, submission)


@router.post("/projects/submissions/{submission_id}/remind")
def remind_project_submission(
    submission_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user),
):
    course = project_admin.get_course_for_project_submission(db, submission_id)
    if course and staff.role == "methodist":
        course_admin.ensure_course_owner(course, staff)

    project_admin.send_reminder(db, submission_id)
    return {"ok": True}


@router.get("/admin/status", response_model=AdminSystemStatusOut)
def get_system_status(db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """ADM-004: очередь, признаки живости воркера, недавние системные
    ошибки, ёмкость хранилища. Только администратор — не методист/преподаватель,
    это эксплуатационная, а не учебная информация."""
    if staff.role != "admin":
        raise HTTPException(status_code=403, detail="Доступно только администратору")
    return admin_status.get_system_status(db)


def _require_admin(staff: User) -> None:
    if staff.role != "admin":
        raise HTTPException(status_code=403, detail="Доступно только администратору")


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


@router.get("/admin/users", response_model=list[AdminUserOut])
def list_users(
    q: str | None = Query(default=None, description="Поиск по имени или external_ref"),
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """IAM-004: поиск пользователей для блокировки/просмотра истории входов."""
    _require_admin(staff)
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter((User.full_name.ilike(like)) | (User.external_ref.ilike(like)))
    return query.order_by(User.full_name).limit(50).all()


@router.put("/admin/users/{user_id}/block", response_model=AdminUserOut)
def set_user_blocked(
    user_id: int,
    payload: AdminUserBlockIn,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """IAM-004: блокировка/разблокировка учётной записи."""
    _require_admin(staff)
    user = _get_user_or_404(db, user_id)
    user.is_blocked = payload.blocked
    db.commit()
    db.refresh(user)
    return user


@router.post("/admin/users/{user_id}/terminate-sessions", response_model=AdminUserOut)
def terminate_user_sessions(
    user_id: int,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """IAM-004: "завершить активные сессии" — токены без состояния на сервере,
    поэтому отзываем все, выданные до текущего момента (см. app/deps.py)."""
    from datetime import datetime, timezone

    _require_admin(staff)
    user = _get_user_or_404(db, user_id)
    user.sessions_invalidated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


@router.get("/admin/users/{user_id}/login-history", response_model=list[AdminLoginEventOut])
def get_user_login_history(
    user_id: int,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """IAM-004: история входов пользователя."""
    _require_admin(staff)
    _get_user_or_404(db, user_id)
    return (
        db.query(LoginEvent)
        .filter(LoginEvent.user_id == user_id)
        .order_by(LoginEvent.created_at.desc())
        .limit(50)
        .all()
    )


@router.post("/uploads", response_model=UploadOut)
async def admin_upload_file(
    file: UploadFile = FastAPIFile(...),
    staff: User = Depends(resolve_staff_user),
):
    """EDT-002/008: загрузка изображения из rich-text редактора методиста —
    методист работает через аккаунт LMS (см. заголовок файла), поэтому
    cookie-сессия Codelab (routers/uploads.py) здесь недоступна и не нужна."""
    return await save_upload(file.filename or "", file.read)
