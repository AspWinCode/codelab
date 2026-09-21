"""GRD-002, GRD-004, GRD-005: официальный результат задачи по политике
(лучший/последний/первая принятая попытка), пересчёт прогресса курса и
доступности зависимых элементов после каждой оценки.

GRD-003 (штраф за попытки/просрочку) не реализован — нет ни счётчика
"платных" попыток сверх бесплатных, ни хранения дедлайна на элементе,
см. README.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Course,
    Enrollment,
    LearningItem,
    LearningItemType,
    NotificationType,
    ProblemRevision,
    Progress,
    Submission,
    SubmissionStatus,
    Verdict,
)
from app.services.notifications import notify


def _effective_score(submission: Submission) -> float:
    # GRD-004: ручная корректировка приоритетнее авто-результата, но исходный
    # результат (submission.score/verdict) никогда не перезаписывается.
    if submission.manual_score_override is not None:
        return submission.manual_score_override
    return submission.score or 0.0


def resolve_official_score(db: Session, user_id: int, problem_revision_id: int) -> Optional[float]:
    """GRD-002: официальный балл по задаче — лучший/последний/первая принятая
    попытка, в зависимости от scoring_policy задачи. None — попыток ещё не было."""
    problem = db.query(ProblemRevision).filter(ProblemRevision.id == problem_revision_id).first()
    if not problem:
        return None

    submissions = (
        db.query(Submission)
        .filter(
            Submission.user_id == user_id,
            Submission.problem_revision_id == problem_revision_id,
            Submission.status == SubmissionStatus.DONE,
        )
        .order_by(Submission.created_at.asc())
        .all()
    )
    if not submissions:
        return None

    if problem.scoring_policy == "last":
        return _effective_score(submissions[-1])
    if problem.scoring_policy == "first_accepted":
        for s in submissions:
            if s.verdict == Verdict.ACCEPTED:
                return _effective_score(s)
        return None
    # "best" — политика по умолчанию.
    return max(_effective_score(s) for s in submissions)


def _item_passed(db: Session, user_id: int, item: LearningItem) -> bool:
    if item.type != LearningItemType.TASK or not item.problem_revision_id:
        return False
    score = resolve_official_score(db, user_id, item.problem_revision_id)
    return score is not None and score > 0


def is_item_unlocked(db: Session, user_id: int, item: LearningItem, items_by_id: dict[int, LearningItem]) -> bool:
    """LMS-004: условие открытия — сейчас поддерживается только
    {"after_item_id": <id>}. Без unlock_rules элемент открыт всегда."""
    after_id = (item.unlock_rules or {}).get("after_item_id")
    if not after_id:
        return True
    predecessor = items_by_id.get(after_id)
    if not predecessor:
        return True
    return _item_passed(db, user_id, predecessor)


def recompute_progress_for_submission(db: Session, submission: Submission) -> None:
    """GRD-005: достижение/отзыв результата пересчитывает прогресс курса.
    Вызывается после того, как посылка получила статус done (воркером) или
    после ручной корректировки оценки (PUT /submissions/{id}/grade)."""
    items = (
        db.query(LearningItem)
        .filter(LearningItem.problem_revision_id == submission.problem_revision_id)
        .all()
    )
    version_ids = {i.course_version_id for i in items}
    if not version_ids:
        return

    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == submission.user_id, Enrollment.course_version_id.in_(version_ids))
        .all()
    )
    for enrollment in enrollments:
        _recompute_course_progress(db, enrollment)


def _recompute_course_progress(db: Session, enrollment: Enrollment) -> None:
    task_items = (
        db.query(LearningItem)
        .filter(LearningItem.course_version_id == enrollment.course_version_id, LearningItem.type == LearningItemType.TASK)
        .all()
    )
    required_items = [i for i in task_items if i.is_required and i.problem_revision_id]

    total = len(required_items)
    completed = 0
    points = 0.0
    for item in required_items:
        score = resolve_official_score(db, enrollment.user_id, item.problem_revision_id)
        if score is not None:
            points += score * item.weight
            if score > 0:
                completed += 1

    progress = (
        db.query(Progress)
        .filter(Progress.user_id == enrollment.user_id, Progress.course_id == enrollment.course_id)
        .first()
    )
    if not progress:
        progress = Progress(user_id=enrollment.user_id, course_id=enrollment.course_id)
        db.add(progress)

    progress.completed_items = completed
    progress.total_items = total
    progress.percent = round(100 * completed / total, 2) if total else 0.0
    progress.points = int(points)
    db.commit()


def apply_manual_grade(db: Session, submission_id: int, score: float, comment: str) -> Submission:
    """GRD-004: ручная корректировка результата — исходный авто-результат
    (submission.score/verdict) не трогаем, комментарий обязателен."""
    from fastapi import HTTPException

    if not comment.strip():
        raise HTTPException(status_code=422, detail="Комментарий обязателен при ручной корректировке")

    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Посылка не найдена")

    submission.manual_score_override = score
    submission.manual_comment = comment
    db.commit()
    db.refresh(submission)

    recompute_progress_for_submission(db, submission)  # GRD-005

    # NTF-001: результат ручной проверки + комментарий преподавателя — одно
    # уведомление, комментарий у нас всегда идёт вместе с оценкой.
    item = (
        db.query(LearningItem)
        .filter(LearningItem.problem_revision_id == submission.problem_revision_id)
        .first()
    )
    task_title = item.title if item else f"задача {submission.problem_revision_id}"
    notify(
        db, submission.user_id, NotificationType.MANUAL_REVIEW_RESULT,
        f"Проверена работа: {task_title}",
        body=f"Балл: {score}. {comment}",
    )

    return submission
