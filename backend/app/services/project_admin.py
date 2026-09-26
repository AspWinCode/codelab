"""Проект с ручной проверкой (type=project): ученик прикрепляет файлы к
попытке, тренер/методист смотрит, комментирует по файлу, принимает или
отправляет на доработку (заводит новую попытку), может напомнить о сдаче.

Не путать с course_admin.py::list_course_submissions/apply_manual_grade —
это для type=task (код на автопроверку по ProblemRevision), у проекта своя
модель (ProjectSubmission/ProjectFile/ProjectFileComment, см. models.py)."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Course,
    CourseVersion,
    Enrollment,
    EnrollmentStatus,
    LearningItem,
    LearningItemType,
    NotificationType,
    ProjectFile,
    ProjectFileComment,
    ProjectSubmission,
    ProjectSubmissionStatus,
    User,
)
from app.schemas import (
    ProjectAttemptSummary,
    ProjectFileCommentOut,
    ProjectFileOut,
    ProjectReviewIn,
    ProjectSubmissionOut,
    ProjectSubmissionReviewOut,
)
from app.services.notifications import notify
from app.services.project_files import delete_project_file, project_file_path, save_project_file


def get_project_item_or_404(db: Session, item_id: int) -> LearningItem:
    item = db.query(LearningItem).filter(LearningItem.id == item_id).first()
    if not item or item.type != LearningItemType.PROJECT:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return item


def get_course_for_project_item(db: Session, item: LearningItem) -> Optional[Course]:
    version = db.query(CourseVersion).filter(CourseVersion.id == item.course_version_id).first()
    return db.query(Course).filter(Course.id == version.course_id).first() if version else None


def get_course_for_project_submission(db: Session, submission_id: int) -> Optional[Course]:
    submission = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
    if not submission:
        return None
    item = db.query(LearningItem).filter(LearningItem.id == submission.learning_item_id).first()
    return get_course_for_project_item(db, item) if item else None


def _is_overdue(item: LearningItem, submission: Optional[ProjectSubmission]) -> bool:
    if not item.due_at:
        return False
    if submission and submission.status == ProjectSubmissionStatus.ACCEPTED:
        return False
    due_at = item.due_at
    if due_at.tzinfo is None:  # SQLite (тесты) не хранит tz — см. app/deps.py
        due_at = due_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > due_at


def _to_file_out(f: ProjectFile, authors_by_id: dict[int, User]) -> ProjectFileOut:
    return ProjectFileOut(
        id=f.id,
        original_filename=f.original_filename,
        content_type=f.content_type,
        size=f.size,
        uploaded_at=f.uploaded_at,
        comments=[
            ProjectFileCommentOut(
                id=c.id,
                author_id=c.author_id,
                author_full_name=authors_by_id[c.author_id].full_name if c.author_id in authors_by_id else "?",
                body=c.body,
                created_at=c.created_at,
            )
            for c in f.comments
        ],
    )


def to_submission_out(db: Session, item: LearningItem, submission: ProjectSubmission, with_history: bool = False) -> ProjectSubmissionOut:
    author_ids = {c.author_id for f in submission.files for c in f.comments}
    authors_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(author_ids)).all()} if author_ids else {}

    history: list[ProjectAttemptSummary] = []
    if with_history:
        siblings = (
            db.query(ProjectSubmission)
            .filter(
                ProjectSubmission.learning_item_id == submission.learning_item_id,
                ProjectSubmission.user_id == submission.user_id,
                ProjectSubmission.id != submission.id,
            )
            .order_by(ProjectSubmission.attempt_number.desc())
            .all()
        )
        history = [
            ProjectAttemptSummary(
                id=s.id, attempt_number=s.attempt_number, status=s.status.value,
                submitted_at=s.submitted_at, score=s.score,
            )
            for s in siblings
        ]

    return ProjectSubmissionOut(
        id=submission.id,
        learning_item_id=item.id,
        attempt_number=submission.attempt_number,
        status=submission.status.value,
        submitted_at=submission.submitted_at,
        reviewed_at=submission.reviewed_at,
        score=submission.score,
        review_comment=submission.review_comment,
        due_at=item.due_at,
        is_overdue=_is_overdue(item, submission),
        files=[_to_file_out(f, authors_by_id) for f in submission.files],
        history=history,
    )


def _latest_submission(db: Session, item_id: int, user_id: int) -> Optional[ProjectSubmission]:
    return (
        db.query(ProjectSubmission)
        .filter(ProjectSubmission.learning_item_id == item_id, ProjectSubmission.user_id == user_id)
        .order_by(ProjectSubmission.attempt_number.desc())
        .first()
    )


def get_or_create_current_submission(db: Session, item_id: int, user_id: int) -> ProjectSubmission:
    """Для GET — читает, не мутирует переходы статуса; только заводит
    первую попытку, если ученик ещё вообще не открывал сдачу."""
    get_project_item_or_404(db, item_id)
    submission = _latest_submission(db, item_id, user_id)
    if submission:
        return submission
    submission = ProjectSubmission(learning_item_id=item_id, user_id=user_id, attempt_number=1)
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


def get_attachable_submission(db: Session, item_id: int, user_id: int) -> ProjectSubmission:
    """Для прикрепления файла — DRAFT возвращается как есть; NEEDS_REVISION
    заводит новую попытку (пересдача); SUBMITTED/ACCEPTED донести файл не
    даёт, нужно дождаться проверки или это уже финал."""
    submission = get_or_create_current_submission(db, item_id, user_id)
    if submission.status == ProjectSubmissionStatus.DRAFT:
        return submission
    if submission.status == ProjectSubmissionStatus.NEEDS_REVISION:
        new_submission = ProjectSubmission(
            learning_item_id=item_id, user_id=user_id, attempt_number=submission.attempt_number + 1,
        )
        db.add(new_submission)
        db.commit()
        db.refresh(new_submission)
        return new_submission
    if submission.status == ProjectSubmissionStatus.SUBMITTED:
        raise HTTPException(status_code=409, detail="Работа уже отправлена на проверку")
    raise HTTPException(status_code=409, detail="Работа уже принята")


def get_file_or_404(db: Session, file_id: int) -> ProjectFile:
    f = db.query(ProjectFile).filter(ProjectFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Файл не найден")
    return f


async def attach_file(db: Session, item_id: int, user_id: int, filename: str, content_type: str, read_chunk) -> ProjectFile:
    submission = get_attachable_submission(db, item_id, user_id)
    saved = await save_project_file(filename, content_type, read_chunk)
    f = ProjectFile(
        submission_id=submission.id,
        original_filename=filename or saved.stored_name,
        stored_name=saved.stored_name,
        content_type=saved.content_type,
        size=saved.size,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def remove_own_file(db: Session, file_id: int, user_id: int) -> None:
    f = get_file_or_404(db, file_id)
    submission = db.query(ProjectSubmission).filter(ProjectSubmission.id == f.submission_id).first()
    if not submission or submission.user_id != user_id:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    if submission.status != ProjectSubmissionStatus.DRAFT:
        raise HTTPException(status_code=409, detail="Файлы можно удалять только пока работа не отправлена")
    delete_project_file(f.stored_name)
    db.delete(f)
    db.commit()


def submit_submission(db: Session, submission_id: int, user_id: int) -> ProjectSubmission:
    submission = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
    if not submission or submission.user_id != user_id:
        raise HTTPException(status_code=404, detail="Сдача не найдена")
    if submission.status != ProjectSubmissionStatus.DRAFT:
        raise HTTPException(status_code=409, detail="Уже отправлено")
    if not submission.files:
        raise HTTPException(status_code=422, detail="Прикрепите хотя бы один файл")
    submission.status = ProjectSubmissionStatus.SUBMITTED
    submission.submitted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(submission)
    return submission


def _ensure_roster_submissions(db: Session, item: LearningItem) -> list[ProjectSubmission]:
    """Тренер должен видеть в списке и тех, кто ещё не начал сдавать — иначе
    напомнить им нечем (не по кому). Заводит DRAFT-попытку без файлов для
    каждого активно зачисленного на курс ученика, у которого пока нет ни
    одной попытки по этому проекту."""
    course = get_course_for_project_item(db, item)
    if not course:
        return []

    enrolled_user_ids = {
        row[0]
        for row in db.query(Enrollment.user_id).filter(
            Enrollment.course_id == course.id, Enrollment.status == EnrollmentStatus.ACTIVE,
        )
    }
    existing_user_ids = {
        row[0]
        for row in db.query(ProjectSubmission.user_id).filter(ProjectSubmission.learning_item_id == item.id)
    }
    missing = enrolled_user_ids - existing_user_ids
    for user_id in missing:
        db.add(ProjectSubmission(learning_item_id=item.id, user_id=user_id, attempt_number=1))
    if missing:
        db.commit()

    return (
        db.query(ProjectSubmission)
        .filter(ProjectSubmission.learning_item_id == item.id)
        .order_by(ProjectSubmission.user_id, ProjectSubmission.attempt_number.asc())
        .all()
    )


def list_project_submissions(db: Session, item_id: int) -> list[ProjectSubmissionReviewOut]:
    item = get_project_item_or_404(db, item_id)
    course = get_course_for_project_item(db, item)
    if not course or not course.active_version_id or item.course_version_id != course.active_version_id:
        # Проект ещё не опубликован (или это черновик новой версии) — ученики
        # его не видят, сдач быть не может.
        return []

    all_attempts = _ensure_roster_submissions(db, item)
    latest_by_user: dict[int, ProjectSubmission] = {}
    for s in all_attempts:  # отсортировано по attempt_number возрастанию — последнее перезапишет
        latest_by_user[s.user_id] = s

    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(latest_by_user.keys())).all()}

    rows = []
    for user_id, submission in latest_by_user.items():
        user = users_by_id.get(user_id)
        if not user:
            continue
        base = to_submission_out(db, item, submission)
        rows.append(
            ProjectSubmissionReviewOut(
                **base.model_dump(),
                student_external_ref=user.external_ref,
                student_full_name=user.full_name,
                item_title=item.title,
            )
        )
    return rows


def get_submission_detail(db: Session, submission_id: int) -> ProjectSubmissionOut:
    submission = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Сдача не найдена")
    item = db.query(LearningItem).filter(LearningItem.id == submission.learning_item_id).first()
    return to_submission_out(db, item, submission, with_history=True)


def add_file_comment(db: Session, file_id: int, author_id: int, body: str) -> ProjectFileComment:
    get_file_or_404(db, file_id)
    if not body.strip():
        raise HTTPException(status_code=422, detail="Пустой комментарий")
    comment = ProjectFileComment(file_id=file_id, author_id=author_id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def apply_project_review(db: Session, submission_id: int, payload: ProjectReviewIn, reviewer_id: int) -> ProjectSubmission:
    submission = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Сдача не найдена")
    if submission.status != ProjectSubmissionStatus.SUBMITTED:
        raise HTTPException(status_code=409, detail="Проверять можно только отправленную на проверку работу")

    submission.status = (
        ProjectSubmissionStatus.ACCEPTED if payload.decision == "accepted" else ProjectSubmissionStatus.NEEDS_REVISION
    )
    submission.score = payload.score
    submission.review_comment = payload.comment
    submission.reviewed_at = datetime.now(timezone.utc)
    submission.reviewed_by_id = reviewer_id
    db.commit()
    db.refresh(submission)

    item = db.query(LearningItem).filter(LearningItem.id == submission.learning_item_id).first()
    title = item.title if item else "проект"
    if submission.status == ProjectSubmissionStatus.ACCEPTED:
        heading = f"Проект «{title}» принят"
        body = f"Оценка: {payload.score}. {payload.comment}"
    else:
        heading = f"Проект «{title}»: нужна доработка"
        body = payload.comment
    notify(db, submission.user_id, NotificationType.PROJECT_REVIEWED, heading, body=body)

    return submission


def send_reminder(db: Session, submission_id: int) -> None:
    submission = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Сдача не найдена")
    if submission.status in (ProjectSubmissionStatus.SUBMITTED, ProjectSubmissionStatus.ACCEPTED):
        raise HTTPException(status_code=409, detail="Работа уже сдана — напоминание не нужно")

    item = db.query(LearningItem).filter(LearningItem.id == submission.learning_item_id).first()
    title = item.title if item else "проект"
    overdue = _is_overdue(item, submission)
    if overdue:
        body = f"Срок сдачи истёк {item.due_at.strftime('%d.%m.%Y')}. Пожалуйста, сдайте работу как можно скорее."
    elif item.due_at:
        body = f"Не забудьте сдать работу до {item.due_at.strftime('%d.%m.%Y')}."
    else:
        body = "Не забудьте сдать работу."
    notify(db, submission.user_id, NotificationType.PROJECT_REMINDER, f"Напоминание: «{title}»", body=body)
