from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ProblemRevision, Submission, User, Verdict


def compute_progress_for_lms(db: Session, user: User) -> dict:
    """Собирает данные для CodelabStudentProgress на стороне портала
    (backend/app/schemas/codelab.py в learning-portal-main)."""
    submissions = (
        db.query(Submission)
        .filter(Submission.user_id == user.id)
        .order_by(Submission.created_at.desc())
        .all()
    )
    if not submissions:
        return None

    accepted_by_problem: dict[int, Submission] = {}
    for s in submissions:
        if s.verdict == Verdict.ACCEPTED and s.problem_revision_id not in accepted_by_problem:
            accepted_by_problem[s.problem_revision_id] = s

    points_total = int(sum((s.score or 0) for s in accepted_by_problem.values()))

    courses = []  # TODO: сгруппировать по курсу через LearningItem, когда появится реальная привязка задач к курсу.

    recent = [
        {
            "id": s.id,
            "task_title": s.problem_revision.title if s.problem_revision else f"Задача {s.problem_revision_id}",
            "verdict": s.verdict.value if s.verdict else None,
            "status": s.status.value,
            "created_at": s.created_at.isoformat(),
        }
        for s in submissions[:10]
    ]

    return {
        "points_total": points_total,
        "rank_name": None,
        "courses": courses,
        "recent_submissions": recent,
    }
