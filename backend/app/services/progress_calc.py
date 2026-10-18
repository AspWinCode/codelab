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
    ProjectSubmission,
    ProjectSubmissionStatus,
    Progress,
    QuizAttempt,
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


def _official_submission(db: Session, user_id: int, problem_revision_id: int) -> Optional[Submission]:
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
        return submissions[-1]
    if problem.scoring_policy == "first_accepted":
        return next((s for s in submissions if s.verdict == Verdict.ACCEPTED), None)
    return max(submissions, key=lambda s: (_effective_score(s), s.verdict == Verdict.ACCEPTED))


def resolve_official_quiz_score(db: Session, user_id: int, item_id: int) -> Optional[float]:
    """Аналог resolve_official_score для теста — лучший результат из всех
    попыток (единственная политика подсчёта, у теста нет scoring_policy как
    у задачи — не нужно, пока не попросили)."""
    best = (
        db.query(QuizAttempt.score)
        .filter(QuizAttempt.user_id == user_id, QuizAttempt.item_id == item_id)
        .order_by(QuizAttempt.score.desc())
        .first()
    )
    return best[0] if best else None


def _latest_project_submission(db: Session, user_id: int, item_id: int) -> Optional[ProjectSubmission]:
    """"На доработку" заводит новую попытку (attempt_number+1), старая
    остаётся в истории (см. app/services/project_admin.py) — для прогресса
    и индикатора "пройдено" важна только последняя."""
    return (
        db.query(ProjectSubmission)
        .filter(ProjectSubmission.user_id == user_id, ProjectSubmission.learning_item_id == item_id)
        .order_by(ProjectSubmission.attempt_number.desc())
        .first()
    )


def _resolve_official_item_score(db: Session, user_id: int, item: LearningItem) -> Optional[float]:
    if item.type == LearningItemType.TASK and item.problem_revision_id:
        return resolve_official_score(db, user_id, item.problem_revision_id)
    if item.type == LearningItemType.QUIZ:
        return resolve_official_quiz_score(db, user_id, item.id)
    if item.type == LearningItemType.PROJECT:
        submission = _latest_project_submission(db, user_id, item.id)
        if not submission or submission.status != ProjectSubmissionStatus.ACCEPTED:
            return None
        # Тренер не обязан проставлять числовую оценку, чтобы принять работу
        # (review_comment/score опциональны) — считаем её полным баллом, раз
        # статус "принято" уже и есть критерий прохождения для проекта.
        return submission.score if submission.score is not None else 100.0
    return None


def is_item_passed(db: Session, user_id: int, item: LearningItem) -> bool:
    """Задача/тест считаются пройденными только при ПОЛНОМ балле (100) —
    частично верное решение (Wrong Answer с частичным score > 0 за
    пройденные тесты) не должно засчитываться как решённое, открывать
    зависимый контент или попадать в "решено" на дашборде/в дереве курса.
    Проект считается пройденным по статусу "принято" тренером — числовая
    оценка на нём опциональна и не обязана достигать 100, поэтому не
    используем общий порог "score >= 100" ниже (см. _resolve_official_item_score)."""
    if item.type == LearningItemType.TASK and item.problem_revision_id:
        submission = _official_submission(db, user_id, item.problem_revision_id)
        if not submission or _effective_score(submission) < 100:
            return False
        # A full score from the judge must be Accepted. A teacher's explicit
        # manual grade may override the automatic verdict.
        return submission.verdict == Verdict.ACCEPTED or submission.manual_score_override is not None
    if item.type == LearningItemType.PROJECT:
        submission = _latest_project_submission(db, user_id, item.id)
        return bool(submission and submission.status == ProjectSubmissionStatus.ACCEPTED)
    score = _resolve_official_item_score(db, user_id, item)
    return score is not None and score >= 100


def is_item_unlocked(db: Session, user_id: int, item: LearningItem, items_by_id: dict[int, LearningItem]) -> bool:
    """LMS-004: условие открытия — сейчас поддерживается только
    {"after_item_id": <id>}. Без unlock_rules элемент открыт всегда."""
    after_id = (item.unlock_rules or {}).get("after_item_id")
    if not after_id:
        return True
    predecessor = items_by_id.get(after_id)
    if not predecessor:
        return True
    return is_item_passed(db, user_id, predecessor)


def recompute_progress_for_quiz_attempt(db: Session, attempt: QuizAttempt) -> None:
    """Аналог recompute_progress_for_submission (GRD-005) для теста —
    вызывается сразу после сохранения попытки (подсчёт синхронный, без
    очереди воркера, см. submissions.py)."""
    item = db.query(LearningItem).filter(LearningItem.id == attempt.item_id).first()
    if not item:
        return
    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == attempt.user_id, Enrollment.course_version_id == item.course_version_id)
        .all()
    )
    for enrollment in enrollments:
        _recompute_course_progress(db, enrollment)


def recompute_progress_for_project(db: Session, submission: ProjectSubmission) -> None:
    """Аналог recompute_progress_for_submission для проекта — вызывается
    после решения тренера (принято/на доработку), см.
    app/services/project_admin.py::apply_project_review."""
    item = db.query(LearningItem).filter(LearningItem.id == submission.learning_item_id).first()
    if not item:
        return
    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == submission.user_id, Enrollment.course_version_id == item.course_version_id)
        .all()
    )
    for enrollment in enrollments:
        _recompute_course_progress(db, enrollment)


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
    gradable_items = (
        db.query(LearningItem)
        .filter(
            LearningItem.course_version_id == enrollment.course_version_id,
            LearningItem.type.in_([LearningItemType.TASK, LearningItemType.QUIZ, LearningItemType.PROJECT]),
        )
        .all()
    )
    required_items = [
        i for i in gradable_items
        if i.is_required and (i.problem_revision_id if i.type == LearningItemType.TASK else True)
    ]

    total = len(required_items)
    completed = 0
    points = 0.0
    for item in required_items:
        score = _resolve_official_item_score(db, enrollment.user_id, item)
        if score is not None:
            points += score * item.weight  # очки — по фактическому баллу, в т.ч. частичному
        # Не "score >= 100" напрямую — у проекта критерий прохождения
        # это статус "принято", а не обязательно полный балл (см.
        # is_item_passed/_resolve_official_item_score выше).
        if is_item_passed(db, enrollment.user_id, item):
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
