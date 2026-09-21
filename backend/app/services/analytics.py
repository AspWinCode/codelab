"""ANA-001/002: агрегированные метрики по курсу и рейтинг задач по сложности
для методиста. Считаются по данным, которые Judge и так пишет при каждой
проверке — отдельного сбора метрик не требуется."""
from datetime import datetime, timezone
from statistics import median
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Course,
    Enrollment,
    EnrollmentStatus,
    LearningItem,
    LearningItemType,
    Progress,
    Submission,
    Verdict,
)


def course_overview(db: Session, course_id: int) -> dict:
    """ANA-001: процент завершения, средний/медианный балл, число попыток,
    просроченные назначения (Enrollment.ends_at)."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.course_id == course_id, Enrollment.status == EnrollmentStatus.ACTIVE)
        .all()
    )
    enrolled_count = len(enrollments)

    progresses = db.query(Progress).filter(Progress.course_id == course_id).all()
    progress_by_user = {p.user_id: p for p in progresses}
    completed_count = sum(1 for p in progresses if p.total_items and p.completed_items >= p.total_items)
    percents = [p.percent for p in progresses]
    avg_score = round(sum(percents) / len(percents), 1) if percents else 0.0
    median_score = round(median(percents), 1) if percents else 0.0

    task_items = (
        db.query(LearningItem)
        .filter(LearningItem.course_version_id == course.active_version_id, LearningItem.type == LearningItemType.TASK)
        .all()
        if course.active_version_id else []
    )
    problem_ids = [i.problem_revision_id for i in task_items if i.problem_revision_id]
    total_attempts = (
        db.query(Submission).filter(Submission.problem_revision_id.in_(problem_ids)).count()
        if problem_ids else 0
    )

    now = datetime.now(timezone.utc)
    overdue_count = 0
    for e in enrollments:
        ends_at = e.ends_at
        if ends_at is None:
            continue
        # SQLite (используется для локального запуска без Postgres, см. README)
        # не сохраняет tzinfo даже для DateTime(timezone=True) — без этого
        # сравнение naive/aware datetime падает с TypeError.
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        if ends_at >= now:
            continue
        p = progress_by_user.get(e.user_id)
        if not (p and p.total_items and p.completed_items >= p.total_items):
            overdue_count += 1

    return {
        "course_id": course_id,
        "enrolled_count": enrolled_count,
        "completed_count": completed_count,
        "completion_percent": round(100 * completed_count / enrolled_count, 1) if enrolled_count else 0.0,
        "avg_score": avg_score,
        "median_score": median_score,
        "total_attempts": total_attempts,
        "overdue_count": overdue_count,
    }


def task_difficulty(db: Session, course_id: int) -> list[dict]:
    """ANA-002: рейтинг задач по доле ошибок, среднему числу попыток до
    решения и числу отказов (зачислен, но ни разу не пытался решить)."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")
    if not course.active_version_id:
        return []

    task_items = (
        db.query(LearningItem)
        .filter(LearningItem.course_version_id == course.active_version_id, LearningItem.type == LearningItemType.TASK)
        .order_by(LearningItem.position)
        .all()
    )
    enrolled_user_ids = {
        e.user_id
        for e in db.query(Enrollment).filter(Enrollment.course_id == course_id, Enrollment.status == EnrollmentStatus.ACTIVE)
    }

    rows = []
    for item in task_items:
        if not item.problem_revision_id:
            continue
        submissions = (
            db.query(Submission)
            .filter(Submission.problem_revision_id == item.problem_revision_id)
            .order_by(Submission.created_at)
            .all()
        )
        attempted_users = {s.user_id for s in submissions}
        solved_users: set[int] = set()
        attempts_to_solve: list[int] = []
        per_user_attempts: dict[int, int] = {}
        failure_verdicts: dict[str, int] = {}

        for s in submissions:
            per_user_attempts[s.user_id] = per_user_attempts.get(s.user_id, 0) + 1
            if s.verdict == Verdict.ACCEPTED:
                if s.user_id not in solved_users:
                    solved_users.add(s.user_id)
                    attempts_to_solve.append(per_user_attempts[s.user_id])
            elif s.verdict:
                failure_verdicts[s.verdict.value] = failure_verdicts.get(s.verdict.value, 0) + 1

        not_attempted = len(enrolled_user_ids - attempted_users)
        failure_rate = round(100 * (1 - len(solved_users) / len(attempted_users)), 1) if attempted_users else 0.0
        avg_attempts = round(sum(attempts_to_solve) / len(attempts_to_solve), 1) if attempts_to_solve else None
        most_common_failure: Optional[str] = max(failure_verdicts, key=failure_verdicts.get) if failure_verdicts else None

        rows.append({
            "item_id": item.id,
            "title": item.title,
            "attempts_total": len(submissions),
            "students_attempted": len(attempted_users),
            "students_solved": len(solved_users),
            "students_not_attempted": not_attempted,
            "failure_rate_percent": failure_rate,
            "avg_attempts_to_solve": avg_attempts,
            "most_common_failure_verdict": most_common_failure,
        })
    return rows
