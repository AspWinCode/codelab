"""Прямой вход методиста в браузер Codelab по SSO-cookie. По решению от
2026-09-21 это больше не основной путь — методист и преподаватель работают
через свой аккаунт LMS (см. app/routers/lms_admin.py, README, раздел
«Интеграция с порталом»). Эндпоинты здесь оставлены как рабочий низкоуровневый
путь для локальной отладки Codelab без портала и как основа, которую
переиспользует app/services/course_admin.py."""
from fastapi import APIRouter, Depends, File as FastAPIFile, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models import Course, CourseStatus, Enrollment, EnrollmentStatus, LearningItem, OgeAttempt, User
from app.schemas import (
    CourseArchiveIn,
    CourseCreate,
    CourseOut,
    CourseUpdate,
    CourseValidationOut,
    LastPositionIn,
    LearningItemArchiveIn,
    LearningItemCreate,
    LearningItemOut,
    LearningItemTree,
    LearningItemUpdate,
    OgePreviewCheckIn,
    OgePreviewCheckOut,
    ProblemRevisionCreate,
    ProblemRevisionOut,
    ProblemRevisionStudentOut,
    QuizAttemptCreate,
    QuizAttemptOut,
    QuizPreviewCheckIn,
    QuizPreviewCheckOut,
    OgeAttemptOut,
    RerunSubmissionsIn,
    RerunSubmissionsOut,
)
from app.services import course_admin
from app.services.course_validator import validate_course_before_publish
from app.services.oge_files import oge_file_path, save_oge_file

router = APIRouter()


@router.get("", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Course)
    if user.role == "student":
        query = query.filter(Course.status == CourseStatus.PUBLISHED)
    elif user.role == "methodist":
        query = query.filter(Course.created_by_id == user.id)
    return query.order_by(Course.id).all()


@router.post("", response_model=CourseOut)
def create_course(payload: CourseCreate, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    return course_admin.create_course(db, payload, created_by_id=user.id)


@router.post("/{course_id}/tasks", response_model=ProblemRevisionOut)
def create_task(
    course_id: int,
    payload: ProblemRevisionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    return course_admin.create_task(db, course_id, payload, author_id=user.id)


def _ensure_task_owner(db: Session, problem_revision_id: int, user: User) -> None:
    course = course_admin.get_course_for_task(db, problem_revision_id)
    if course:
        course_admin.ensure_course_owner(course, user)


@router.get("/tasks/{problem_revision_id}", response_model=ProblemRevisionOut)
def get_task(problem_revision_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    task = course_admin.get_task_or_404(db, problem_revision_id)
    _ensure_task_owner(db, problem_revision_id, user)
    return task


@router.put("/tasks/{problem_revision_id}", response_model=ProblemRevisionOut)
async def update_task(
    problem_revision_id: int,
    payload: ProblemRevisionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    course_admin.get_task_or_404(db, problem_revision_id)
    _ensure_task_owner(db, problem_revision_id, user)
    result = course_admin.update_task(db, problem_revision_id, payload)
    course = course_admin.get_course_for_task(db, problem_revision_id)
    if course:
        await course_admin.publish_course(db, course.id, actor_id=user.id)
    return result


@router.get("/problems/{problem_revision_id}", response_model=ProblemRevisionStudentOut)
def get_problem_for_student(problem_revision_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """STU-003: условие задачи (statement/input_format/output_format) и
    видимые примеры — без reference_solution и скрытых тестов. Раньше это
    вообще не отдавалось ученику: CoursePage показывал только редактор кода,
    без условия задачи."""
    task = course_admin.get_task_or_404(db, problem_revision_id)
    return course_admin.to_student_problem_out(db, task, user)


@router.post("/quizzes/{item_id}/attempts", response_model=QuizAttemptOut)
def submit_quiz_attempt(
    item_id: int,
    payload: QuizAttemptCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Проверка синхронная — сравнение отмеченных вариантов с эталоном не
    требует песочницы (в отличие от кода в submissions.py/app.worker)."""
    return course_admin.submit_quiz_attempt(db, item_id, user.id, payload.answers)


@router.get("/quizzes/{item_id}/attempts", response_model=list[QuizAttemptOut])
def my_quiz_attempts(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return course_admin.get_quiz_attempts(db, item_id, user.id)


@router.post("/oge/{item_id}/attempts", response_model=OgeAttemptOut)
async def submit_oge_attempt(
    item_id: int,
    answer: str = Form(...),
    file: UploadFile | None = FastAPIFile(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Файл — необязательное приложение к автоответу (например, фото решения
    на бумаге), сам он не проверяется и не влияет на score (см. models.py::OgeAttempt)."""
    saved = await save_oge_file(file.filename or "", file.content_type or "", file.read) if file else None
    return course_admin.submit_oge_attempt(db, item_id, user.id, answer, file=saved, file_original_filename=file.filename if file else None)


@router.get("/oge/{item_id}/attempts", response_model=list[OgeAttemptOut])
def my_oge_attempts(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(OgeAttempt).filter(
        OgeAttempt.item_id == item_id, OgeAttempt.user_id == user.id
    ).order_by(OgeAttempt.created_at.desc()).all()


@router.get("/oge/attempts/{attempt_id}/file")
def download_oge_attempt_file(attempt_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    attempt = db.query(OgeAttempt).filter(OgeAttempt.id == attempt_id).first()
    if not attempt or not attempt.file_stored_name:
        raise HTTPException(status_code=404, detail="Файл не найден")
    is_owner = attempt.user_id == user.id
    is_staff = user.role in ("teacher", "methodist", "admin")
    if not is_owner and not is_staff:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    path = oge_file_path(attempt.file_stored_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден на диске")
    return FileResponse(path, media_type=attempt.file_content_type or "application/octet-stream", filename=attempt.file_original_filename or "file")


@router.post("/{course_id}/items", response_model=LearningItemOut)
async def create_item(
    course_id: int,
    payload: LearningItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    result = course_admin.create_item(db, course_id, payload)
    return await course_admin.auto_publish_item(db, course_id, result.id, actor_id=user.id)


@router.get("/items/{item_id}", response_model=LearningItemOut)
def get_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    item = db.query(LearningItem).filter(LearningItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Элемент не найден")
    return item


@router.put("/items/{item_id}", response_model=LearningItemOut)
async def update_item(
    item_id: int,
    payload: LearningItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    _, course = course_admin.get_course_for_item(db, item_id)
    course_admin.ensure_course_owner(course, user)
    result = course_admin.update_item(db, item_id, payload)
    return await course_admin.auto_publish_item(db, course.id, result.id, actor_id=user.id)


@router.delete("/items/{item_id}")
async def delete_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    _, course = course_admin.get_course_for_item(db, item_id)
    course_admin.ensure_course_owner(course, user)
    course_admin.delete_item(db, item_id)
    await course_admin.publish_course(db, course.id, actor_id=user.id)
    return {"ok": True}


@router.put("/items/{item_id}/archive", response_model=LearningItemOut)
async def archive_item(
    item_id: int,
    payload: LearningItemArchiveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    _, course = course_admin.get_course_for_item(db, item_id)
    course_admin.ensure_course_owner(course, user)
    result = course_admin.set_item_archived(db, item_id, payload.archived)
    return await course_admin.auto_publish_item(db, course.id, result.id, actor_id=user.id)


@router.get("/{course_id}/tree", response_model=list[LearningItemTree])
def get_tree(course_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    if user.role == "student":
        # Students follow the currently published course tree so newly
        # published tasks appear without requiring a new enrollment.
        if not course.active_version_id:
            raise HTTPException(status_code=404, detail="Курс ещё не опубликован")
        version_id = course.active_version_id
    else:
        course_admin.ensure_course_owner(course, user)
        version_id = course_admin.get_draft_version(db, course_id).id

    items = db.query(LearningItem).filter(LearningItem.course_version_id == version_id).order_by(LearningItem.position).all()

    if user.role != "student":
        return course_admin.build_tree(items)
    return course_admin.build_student_tree(db, user.id, items)


@router.get("/{course_id}/preview-tree", response_model=list[LearningItemTree])
def get_preview_tree(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    """Этап 5 (ТЗ) — «Предпросмотр как ученик»: черновик курса в точности в
    том виде, в каком его увидит студент после публикации."""
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    return course_admin.get_preview_tree(db, course_id, user.id)


@router.post("/{course_id}/oge/{item_id}/preview-check", response_model=OgePreviewCheckOut)
def preview_check_oge(
    course_id: int, item_id: int, payload: OgePreviewCheckIn,
    db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin")),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    return OgePreviewCheckOut(is_correct=course_admin.preview_check_oge_answer(db, course_id, item_id, payload.answer))


@router.post("/{course_id}/quiz/{item_id}/preview-check", response_model=QuizPreviewCheckOut)
def preview_check_quiz(
    course_id: int, item_id: int, payload: QuizPreviewCheckIn,
    db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin")),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    return QuizPreviewCheckOut(score=course_admin.preview_check_quiz_answer(db, course_id, item_id, payload.answers))


@router.put("/{course_id}/last-position")
def set_last_position(
    course_id: int,
    payload: LastPositionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """STU-005: сохраняет последнюю открытую позицию в материале курса —
    "продолжить обучение с неё" на главной странице ученика."""
    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == user.id, Enrollment.course_id == course_id)
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Вы не записаны на этот курс")

    item = db.query(LearningItem).filter(LearningItem.id == payload.item_id).first()
    course = db.query(Course).filter(Course.id == course_id).first()
    version_id = course.active_version_id if course and course.active_version_id else enrollment.course_version_id
    if not item or item.course_version_id != version_id:
        raise HTTPException(status_code=422, detail="Элемент не относится к назначенной версии курса")

    enrollment.last_item_id = payload.item_id
    db.commit()
    return {"ok": True}


@router.put("/{course_id}/items/{item_id}/complete")
def complete_content_item(
    course_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Marks a lecture complete when the student explicitly moves forward."""
    enrollment = (
        db.query(Enrollment)
        .filter(
            Enrollment.user_id == user.id,
            Enrollment.course_id == course_id,
            Enrollment.status == EnrollmentStatus.ACTIVE,
        )
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Вы не записаны на этот курс")
    course = db.query(Course).filter(Course.id == course_id).first()
    item = db.query(LearningItem).filter(LearningItem.id == item_id).first()
    version_id = course.active_version_id if course and course.active_version_id else enrollment.course_version_id
    if not item or item.course_version_id != version_id:
        raise HTTPException(status_code=422, detail="Элемент не относится к назначенной версии курса")
    course_admin.mark_content_item_completed(db, user.id, item)
    return {"ok": True}


@router.put("/{course_id}", response_model=CourseOut)
def update_course(
    course_id: int, payload: CourseUpdate,
    db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin")),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    return course_admin.update_course(db, course_id, payload)


@router.put("/{course_id}/archive", response_model=CourseOut)
def archive_course(
    course_id: int, payload: CourseArchiveIn,
    db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin")),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    return course_admin.set_course_archived(db, course_id, payload.archived)


@router.delete("/{course_id}", status_code=204)
def delete_course(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    course_admin.delete_course(db, course_id)


@router.get("/{course_id}/validation", response_model=CourseValidationOut)
def get_course_validation(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    errors = validate_course_before_publish(db, course_id)
    return CourseValidationOut(valid=not errors, errors=errors, warnings=[])


@router.post("/{course_id}/publish", response_model=CourseOut)
async def publish_course(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    errors = validate_course_before_publish(db, course_id)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"valid": False, "errors": [e.__dict__ for e in errors], "warnings": []},
        )
    return await course_admin.publish_course(db, course_id, actor_id=user.id)


@router.post("/{course_id}/unpublish", response_model=CourseOut)
async def unpublish_course(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    return await course_admin.unpublish_course(db, course_id, actor_id=user.id)


@router.post("/{course_id}/submissions/rerun", response_model=RerunSubmissionsOut)
def rerun_submissions(
    course_id: int,
    payload: RerunSubmissionsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    """TASK-007: массовая перепроверка после исправления тестов задачи."""
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    requeued = course_admin.rerun_submissions(db, course_id, payload.submission_ids)
    return RerunSubmissionsOut(requeued=requeued)
