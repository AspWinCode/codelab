"""ANA-001/002: агрегаты курса и рейтинг задач по сложности."""
from datetime import datetime, timedelta, timezone

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
from app.services.analytics import course_overview, task_difficulty


def _setup_course(db):
    course = Course(title="C")
    db.add(course)
    db.flush()
    version = CourseVersion(course_id=course.id, version_number=1, published_at=datetime.now(timezone.utc))
    db.add(version)
    db.flush()
    course.active_version_id = version.id

    problem = ProblemRevision(task_id=1, revision_number=1, title="Hard task")
    db.add(problem)
    db.flush()
    item = LearningItem(course_version_id=version.id, type=LearningItemType.TASK, title="Hard task", problem_revision_id=problem.id)
    db.add(item)
    db.commit()
    return course, problem, item


def _make_student(db, ref):
    u = User(external_ref=ref, full_name=ref, role="student")
    db.add(u)
    db.flush()
    return u


def test_course_overview_counts_completion_and_overdue(db_session):
    course, problem, item = _setup_course(db_session)
    s1 = _make_student(db_session, "s1")
    s2 = _make_student(db_session, "s2")

    # s1 — завершил курс, зачисление ещё не истекло
    db_session.add(Enrollment(user_id=s1.id, course_id=course.id, course_version_id=course.active_version_id, status=EnrollmentStatus.ACTIVE))
    db_session.add(Progress(user_id=s1.id, course_id=course.id, completed_items=1, total_items=1, percent=100.0, points=100))

    # s2 — не завершил, дедлайн (ends_at) уже прошёл → просрочено
    db_session.add(Enrollment(
        user_id=s2.id, course_id=course.id, course_version_id=course.active_version_id,
        status=EnrollmentStatus.ACTIVE, ends_at=datetime.now(timezone.utc) - timedelta(days=1),
    ))
    db_session.add(Progress(user_id=s2.id, course_id=course.id, completed_items=0, total_items=1, percent=0.0, points=0))
    db_session.add(Submission(user_id=s1.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, verdict=Verdict.ACCEPTED, score=100.0))
    db_session.commit()

    overview = course_overview(db_session, course.id)
    assert overview["enrolled_count"] == 2
    assert overview["completed_count"] == 1
    assert overview["completion_percent"] == 50.0
    assert overview["overdue_count"] == 1
    assert overview["total_attempts"] == 1
    assert overview["avg_score"] == 50.0  # (100 + 0) / 2


def test_task_difficulty_ranks_failures_and_attempts(db_session):
    course, problem, item = _setup_course(db_session)
    s1 = _make_student(db_session, "s1")
    s2 = _make_student(db_session, "s2")
    s3 = _make_student(db_session, "s3")
    for s in (s1, s2, s3):
        db_session.add(Enrollment(user_id=s.id, course_id=course.id, course_version_id=course.active_version_id, status=EnrollmentStatus.ACTIVE))
    db_session.commit()

    # s1: две неудачные попытки, потом решил — 3 попытки до решения
    db_session.add(Submission(user_id=s1.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, verdict=Verdict.WRONG_ANSWER, score=0.0))
    db_session.add(Submission(user_id=s1.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, verdict=Verdict.RUNTIME_ERROR, score=0.0))
    db_session.add(Submission(user_id=s1.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, verdict=Verdict.ACCEPTED, score=100.0))
    # s2: одна неудачная попытка, не решил
    db_session.add(Submission(user_id=s2.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, verdict=Verdict.WRONG_ANSWER, score=0.0))
    # s3: вообще не пытался (отказ)
    db_session.commit()

    rows = task_difficulty(db_session, course.id)
    assert len(rows) == 1
    row = rows[0]
    assert row["attempts_total"] == 4
    assert row["students_attempted"] == 2
    assert row["students_solved"] == 1
    assert row["students_not_attempted"] == 1  # s3
    assert row["avg_attempts_to_solve"] == 3.0  # s1 решил с 3-й попытки
    assert row["failure_rate_percent"] == 50.0  # 1 из 2 пытавшихся не решил
    assert row["most_common_failure_verdict"] == "Wrong Answer"  # 2 WA vs 1 RE
