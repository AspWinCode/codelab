from app.models import Course, Enrollment, LearningItem, LearningItemType, Submission, User, Verdict
from sqlalchemy.orm import Session


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

    # Прогресс считается по версии курса, зафиксированной в назначении
    # (MGR-003) — правки черновика после публикации на неё не влияют (STU-003).
    courses = []
    enrollments = db.query(Enrollment).filter(Enrollment.user_id == user.id).all()
    for enrollment in enrollments:
        version_id = enrollment.course_version_id
        if not version_id:
            continue
        course = db.query(Course).filter(Course.id == enrollment.course_id).first()
        if not course:
            continue
        task_items = (
            db.query(LearningItem)
            .filter(LearningItem.course_version_id == version_id, LearningItem.type == LearningItemType.TASK)
            .all()
        )
        if not task_items:
            continue
        problem_ids = {item.problem_revision_id for item in task_items if item.problem_revision_id}
        solved = problem_ids & accepted_by_problem.keys()
        courses.append({
            "course_id": course.id,
            "course_title": course.title,
            "tasks_total": len(problem_ids),
            "tasks_solved": len(solved),
            "points": int(sum(accepted_by_problem[pid].score or 0 for pid in solved)),
        })

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
