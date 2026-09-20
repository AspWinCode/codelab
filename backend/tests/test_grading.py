"""GRD-002/004/005: официальный результат по политике, пересчёт Progress,
ручная корректировка с обязательным комментарием, разблокировка LMS-004."""
import pytest

from app.models import (
    Course,
    CourseVersion,
    Enrollment,
    EnrollmentStatus,
    LearningItem,
    LearningItemType,
    ProblemRevision,
    Progress,
    Submission,
    SubmissionStatus,
    User,
    Verdict,
)
from app.services.progress_calc import is_item_unlocked, recompute_progress_for_submission, resolve_official_score


def _make_course_with_task(db, scoring_policy="best", weight=1.0, required=True):
    course = Course(title="C")
    db.add(course)
    db.flush()
    version = CourseVersion(course_id=course.id, version_number=1)
    db.add(version)
    db.flush()
    problem = ProblemRevision(task_id=1, revision_number=1, title="T", scoring_policy=scoring_policy)
    db.add(problem)
    db.flush()
    item = LearningItem(
        course_version_id=version.id,
        type=LearningItemType.TASK,
        title="Задача",
        problem_revision_id=problem.id,
        weight=weight,
        is_required=required,
    )
    db.add(item)
    db.flush()
    return course, version, problem, item


@pytest.mark.parametrize("policy,scores,expected", [
    ("best", [40.0, 100.0, 60.0], 100.0),
    ("last", [40.0, 100.0, 60.0], 60.0),
    ("first_accepted", [(40.0, None), (100.0, Verdict.ACCEPTED), (60.0, Verdict.ACCEPTED)], 100.0),
])
def test_resolve_official_score_policies(db_session, policy, scores, expected):
    course, version, problem, item = _make_course_with_task(db_session, scoring_policy=policy)
    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.flush()

    for entry in scores:
        score, verdict = entry if isinstance(entry, tuple) else (entry, Verdict.WRONG_ANSWER)
        db_session.add(Submission(
            user_id=user.id, problem_revision_id=problem.id, code="x",
            status=SubmissionStatus.DONE, verdict=verdict, score=score,
        ))
    db_session.commit()

    assert resolve_official_score(db_session, user.id, problem.id) == expected


def test_manual_override_takes_precedence(db_session):
    course, version, problem, item = _make_course_with_task(db_session, scoring_policy="best")
    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.flush()
    sub = Submission(user_id=user.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, score=30.0)
    db_session.add(sub)
    db_session.commit()

    assert resolve_official_score(db_session, user.id, problem.id) == 30.0

    sub.manual_score_override = 90.0
    sub.manual_comment = "Проверил руками, тест был кривой"
    db_session.commit()

    # Исходный авто-результат не тронут — только эффективный балл поменялся.
    assert sub.score == 30.0
    assert resolve_official_score(db_session, user.id, problem.id) == 90.0


def test_recompute_progress_after_submission(db_session):
    course, version, problem, item = _make_course_with_task(db_session, weight=2.0)
    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.flush()
    db_session.add(Enrollment(
        user_id=user.id, course_id=course.id, course_version_id=version.id, status=EnrollmentStatus.ACTIVE,
    ))
    sub = Submission(user_id=user.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, score=50.0)
    db_session.add(sub)
    db_session.commit()

    recompute_progress_for_submission(db_session, sub)

    progress = db_session.query(Progress).filter(Progress.user_id == user.id, Progress.course_id == course.id).first()
    assert progress is not None
    assert progress.completed_items == 1
    assert progress.total_items == 1
    assert progress.percent == 100.0
    assert progress.points == 100  # score(50) * weight(2)


def test_item_unlocks_after_predecessor_passed(db_session):
    course, version, problem, item = _make_course_with_task(db_session)
    locked_item = LearningItem(
        course_version_id=version.id,
        type=LearningItemType.THEORY,
        title="Следующая тема",
        unlock_rules={"after_item_id": item.id},
    )
    db_session.add(locked_item)
    db_session.commit()

    user = User(external_ref="lp-1", full_name="U", role="student")
    db_session.add(user)
    db_session.flush()
    items_by_id = {item.id: item, locked_item.id: locked_item}

    assert is_item_unlocked(db_session, user.id, locked_item, items_by_id) is False

    db_session.add(Submission(user_id=user.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, score=100.0))
    db_session.commit()

    assert is_item_unlocked(db_session, user.id, locked_item, items_by_id) is True
