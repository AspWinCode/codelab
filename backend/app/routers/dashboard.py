"""STU-001, STU-004 — главная страница ученика: активные курсы, процент
прохождения, ближайшие дедлайны, последние результаты, следующий
рекомендуемый шаг."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    Course,
    Enrollment,
    EnrollmentStatus,
    LearningItem,
    LearningItemType,
    Progress,
    Submission,
    SubmissionStatus,
    User,
)
from app.schemas import DashboardCourseOut, DashboardOut, NextItemOut, RecentResultOut
from app.services.progress_calc import is_item_unlocked, resolve_official_score

router = APIRouter()


def _find_next_item(db: Session, user_id: int, course_version_id: int) -> NextItemOut | None:
    """Первая незавершённая обязательная задача в порядке дерева, к которой
    у ученика уже есть доступ (LMS-004)."""
    items = (
        db.query(LearningItem)
        .filter(LearningItem.course_version_id == course_version_id)
        .order_by(LearningItem.position)
        .all()
    )
    items_by_id = {i.id: i for i in items}
    for item in items:
        if item.type != LearningItemType.TASK or not item.is_required or not item.problem_revision_id:
            continue
        if not is_item_unlocked(db, user_id, item, items_by_id):
            continue
        score = resolve_official_score(db, user_id, item.problem_revision_id)
        if score is None or score <= 0:
            return NextItemOut(id=item.id, title=item.title)
    return None


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == user.id, Enrollment.status == EnrollmentStatus.ACTIVE)
        .all()
    )

    courses_out = []
    for enrollment in enrollments:
        course = db.query(Course).filter(Course.id == enrollment.course_id).first()
        if not course or not enrollment.course_version_id:
            continue
        progress = (
            db.query(Progress)
            .filter(Progress.user_id == user.id, Progress.course_id == course.id)
            .first()
        )
        courses_out.append(DashboardCourseOut(
            course_id=course.id,
            title=course.title,
            percent=progress.percent if progress else 0.0,
            completed_items=progress.completed_items if progress else 0,
            total_items=progress.total_items if progress else 0,
            deadline=enrollment.ends_at,
            next_item=_find_next_item(db, user.id, enrollment.course_version_id),
            last_item_id=enrollment.last_item_id,
        ))

    # STU-004: последние результаты — по всем посылкам ученика, не только по одному курсу.
    recent_submissions = (
        db.query(Submission)
        .filter(Submission.user_id == user.id, Submission.status == SubmissionStatus.DONE)
        .order_by(Submission.created_at.desc())
        .limit(10)
        .all()
    )
    recent_out = [
        RecentResultOut(
            submission_id=s.id,
            task_title=s.problem_revision.title if s.problem_revision else f"Задача {s.problem_revision_id}",
            verdict=s.verdict.value if s.verdict else None,
            score=s.manual_score_override if s.manual_score_override is not None else s.score,
            created_at=s.created_at,
        )
        for s in recent_submissions
    ]

    return DashboardOut(courses=courses_out, recent_results=recent_out)
