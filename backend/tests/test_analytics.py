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
from app.models import OgeAttempt
from app.services.analytics import course_overview, oge_overview, oge_task_analytics, task_difficulty


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


def _setup_oge_course(db):
    course = Course(title="C-OGE")
    db.add(course)
    db.flush()
    version = CourseVersion(course_id=course.id, version_number=1, published_at=datetime.now(timezone.utc))
    db.add(version)
    db.flush()
    course.active_version_id = version.id

    module = LearningItem(course_version_id=version.id, type=LearningItemType.MODULE, title="Модуль 1")
    db.add(module)
    db.flush()
    topic = LearningItem(course_version_id=version.id, type=LearningItemType.TOPIC, title="Тема 1", parent_id=module.id)
    db.add(topic)
    db.flush()
    easy = LearningItem(
        course_version_id=version.id, type=LearningItemType.OGE_TASK, title="Лёгкое", parent_id=topic.id,
        oge_answer={"answer": "12"},
    )
    hard = LearningItem(
        course_version_id=version.id, type=LearningItemType.OGE_TASK, title="Сложное", parent_id=topic.id,
        oge_answer={"answer": "7"},
    )
    db.add_all([easy, hard])
    db.commit()
    return course, easy, hard


def test_oge_task_analytics_no_attempts(db_session):
    course, easy, hard = _setup_oge_course(db_session)
    s1 = _make_student(db_session, "s1")
    db_session.add(Enrollment(user_id=s1.id, course_id=course.id, course_version_id=course.active_version_id, status=EnrollmentStatus.ACTIVE))
    db_session.commit()

    rows = oge_task_analytics(db_session, course.id)
    assert len(rows) == 2
    for row in rows:
        assert row["students_attempted"] == 0
        assert row["correct_count"] == 0
        assert row["incorrect_count"] == 0
        assert row["students_not_attempted"] == 1
        assert row["correct_rate_percent"] == 0.0
        assert row["avg_attempts"] is None
        assert row["median_attempts"] is None
        assert row["last_attempt_at"] is None


def test_oge_task_analytics_multiple_attempts_and_retry(db_session):
    course, easy, hard = _setup_oge_course(db_session)
    s1 = _make_student(db_session, "s1")
    s2 = _make_student(db_session, "s2")
    s3 = _make_student(db_session, "s3")
    for s in (s1, s2, s3):
        db_session.add(Enrollment(user_id=s.id, course_id=course.id, course_version_id=course.active_version_id, status=EnrollmentStatus.ACTIVE))
    db_session.commit()

    # easy: s1 решил сразу, s2 решил со 2-й попытки (повторная попытка), s3 не пытался
    db_session.add(OgeAttempt(user_id=s1.id, item_id=easy.id, answer="12", score=100.0))
    db_session.add(OgeAttempt(user_id=s2.id, item_id=easy.id, answer="11", score=0.0))
    db_session.add(OgeAttempt(user_id=s2.id, item_id=easy.id, answer="12", score=100.0))
    # hard: только s1 пытался, неправильно
    db_session.add(OgeAttempt(user_id=s1.id, item_id=hard.id, answer="1", score=0.0))
    db_session.commit()

    rows = {r["item_id"]: r for r in oge_task_analytics(db_session, course.id)}

    easy_row = rows[easy.id]
    assert easy_row["module_title"] == "Модуль 1"
    assert easy_row["topic_title"] == "Тема 1"
    assert easy_row["students_attempted"] == 2
    assert easy_row["correct_count"] == 2
    assert easy_row["incorrect_count"] == 1
    assert easy_row["students_not_attempted"] == 1  # s3
    assert easy_row["correct_rate_percent"] == round(100 * 2 / 3, 1)
    assert easy_row["avg_attempts"] == 1.5  # s1: 1, s2: 2
    assert easy_row["median_attempts"] == 1.5
    assert easy_row["last_attempt_at"] is not None

    hard_row = rows[hard.id]
    assert hard_row["students_attempted"] == 1
    assert hard_row["correct_count"] == 0
    assert hard_row["incorrect_count"] == 1
    assert hard_row["students_not_attempted"] == 2
    assert hard_row["correct_rate_percent"] == 0.0


def test_oge_task_analytics_sorts_hardest_and_easiest_by_correct_rate(db_session):
    course, easy, hard = _setup_oge_course(db_session)
    s1 = _make_student(db_session, "s1")
    s2 = _make_student(db_session, "s2")
    for s in (s1, s2):
        db_session.add(Enrollment(user_id=s.id, course_id=course.id, course_version_id=course.active_version_id, status=EnrollmentStatus.ACTIVE))
    db_session.commit()

    # easy: 100% верно
    db_session.add(OgeAttempt(user_id=s1.id, item_id=easy.id, answer="12", score=100.0))
    db_session.add(OgeAttempt(user_id=s2.id, item_id=easy.id, answer="12", score=100.0))
    # hard: 0% верно
    db_session.add(OgeAttempt(user_id=s1.id, item_id=hard.id, answer="1", score=0.0))
    db_session.add(OgeAttempt(user_id=s2.id, item_id=hard.id, answer="2", score=0.0))
    db_session.commit()

    overview = oge_overview(db_session, course.id)
    assert overview["total_tasks"] == 2
    assert overview["solved_tasks"] == 1
    assert overview["total_attempts"] == 4
    assert overview["hardest_tasks"][0]["item_id"] == hard.id
    assert overview["easiest_tasks"][0]["item_id"] == easy.id
    assert len(overview["by_module"]) == 1
    assert overview["by_module"][0]["module_title"] == "Модуль 1"
    assert overview["by_module"][0]["tasks_count"] == 2
