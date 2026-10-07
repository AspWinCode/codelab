"""STU-001/004/005: главная страница ученика и сохранение позиции в материале."""
from datetime import datetime, timezone

from app.models import (
    Course,
    CourseVersion,
    Enrollment,
    EnrollmentStatus,
    ItemCompletion,
    LearningItem,
    LearningItemType,
    ProblemRevision,
    Progress,
    Submission,
    SubmissionStatus,
    Verdict,
)
from tests.conftest import as_user, make_user


def test_dashboard_shows_progress_next_item_and_recent_results(client, db_session):
    student = make_user(db_session, "student")

    course = Course(title="Python с нуля")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, version_number=1, published_at=None)
    db_session.add(version)
    db_session.flush()

    problem1 = ProblemRevision(task_id=1, revision_number=1, title="Задача 1")
    problem2 = ProblemRevision(task_id=2, revision_number=1, title="Задача 2")
    db_session.add_all([problem1, problem2])
    db_session.flush()

    item1 = LearningItem(course_version_id=version.id, type=LearningItemType.TASK, title="Задача 1", problem_revision_id=problem1.id, position=0)
    item2 = LearningItem(course_version_id=version.id, type=LearningItemType.TASK, title="Задача 2", problem_revision_id=problem2.id, position=1)
    db_session.add_all([item1, item2])
    db_session.flush()

    db_session.add(Enrollment(user_id=student.id, course_id=course.id, course_version_id=version.id, status=EnrollmentStatus.ACTIVE))
    db_session.add(Progress(user_id=student.id, course_id=course.id, completed_items=1, total_items=2, percent=50.0, points=100))
    db_session.add(Submission(user_id=student.id, problem_revision_id=problem1.id, code="x", status=SubmissionStatus.DONE, verdict=Verdict.ACCEPTED, score=100.0))
    db_session.commit()

    as_user(client, student)
    resp = client.get("/api/me/dashboard")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["courses"]) == 1
    course_out = body["courses"][0]
    assert course_out["course_id"] == course.id
    assert course_out["percent"] == 50.0
    # Задача 1 сдана — следующий рекомендуемый шаг должен быть Задача 2.
    assert course_out["next_item"]["id"] == item2.id

    assert len(body["recent_results"]) == 1
    assert body["recent_results"][0]["task_title"] == "Задача 1"
    assert body["recent_results"][0]["score"] == 100.0


def test_dashboard_marks_accepted_task_as_solved_not_a_partial_one(client, db_session):
    """Регресс: после Accepted-решения задача должна считаться решённой
    (пропадать из "следующий шаг", засчитываться в проценте), а решение с
    частичным баллом (не все тесты, Wrong Answer) — не должно."""
    student = make_user(db_session, "student")

    course = Course(title="Программист")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, version_number=1, published_at=datetime.now(timezone.utc))
    db_session.add(version)
    db_session.flush()
    course.active_version_id = version.id
    db_session.commit()

    problem1 = ProblemRevision(task_id=1, revision_number=1, title="Задача 1")
    problem2 = ProblemRevision(task_id=2, revision_number=1, title="Задача 2")
    db_session.add_all([problem1, problem2])
    db_session.flush()

    item1 = LearningItem(course_version_id=version.id, type=LearningItemType.TASK, title="Задача 1", problem_revision_id=problem1.id, position=0)
    item2 = LearningItem(course_version_id=version.id, type=LearningItemType.TASK, title="Задача 2", problem_revision_id=problem2.id, position=1)
    db_session.add_all([item1, item2])
    db_session.flush()

    db_session.add(Enrollment(user_id=student.id, course_id=course.id, course_version_id=version.id, status=EnrollmentStatus.ACTIVE))
    # Задача 1 — полностью решена (Accepted, score=100).
    db_session.add(Submission(
        user_id=student.id, problem_revision_id=problem1.id, code="x",
        status=SubmissionStatus.DONE, verdict=Verdict.ACCEPTED, score=100.0,
    ))
    # Задача 2 — только частичный результат (не все тесты прошли).
    db_session.add(Submission(
        user_id=student.id, problem_revision_id=problem2.id, code="y",
        status=SubmissionStatus.DONE, verdict=Verdict.WRONG_ANSWER, score=50.0,
    ))
    db_session.add(Progress(user_id=student.id, course_id=course.id, completed_items=1, total_items=2, percent=50.0, points=150))
    db_session.commit()

    as_user(client, student)
    resp = client.get("/api/me/dashboard")
    assert resp.status_code == 200
    course_out = resp.json()["courses"][0]

    # Задача 1 (Accepted) решена — следующий шаг указывает на Задачу 2, не на Задачу 1.
    assert course_out["next_item"]["id"] == item2.id

    tree_resp = client.get(f"/api/courses/{course.id}/tree")
    tree = {node["id"]: node for node in tree_resp.json()}
    assert tree[item1.id]["completed"] is True  # Accepted — решено
    assert tree[item2.id]["completed"] is False  # частичный балл — не решено


def test_dashboard_does_not_treat_full_wrong_answer_as_solved(client, db_session):
    student = make_user(db_session, "student")
    course = Course(title="Курс")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, version_number=1, published_at=datetime.now(timezone.utc))
    db_session.add(version)
    db_session.flush()
    course.active_version_id = version.id
    problem = ProblemRevision(task_id=1, revision_number=1, title="Задача")
    db_session.add(problem)
    db_session.flush()
    item = LearningItem(course_version_id=version.id, type=LearningItemType.TASK, title="Задача", problem_revision_id=problem.id)
    db_session.add(item)
    db_session.add(Enrollment(user_id=student.id, course_id=course.id, course_version_id=version.id, status=EnrollmentStatus.ACTIVE))
    db_session.add(Submission(
        user_id=student.id, problem_revision_id=problem.id, code="x",
        status=SubmissionStatus.DONE, verdict=Verdict.WRONG_ANSWER, score=100.0,
    ))
    db_session.commit()

    as_user(client, student)
    body = client.get("/api/me/dashboard").json()
    assert body["courses"][0]["completed_items"] == 0
    assert body["courses"][0]["percent"] == 0.0
    assert body["courses"][0]["next_item"]["id"] == item.id


def test_last_position_rejects_item_from_other_course_version(client, db_session):
    student = make_user(db_session, "student")

    course = Course(title="C1")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, version_number=1, published_at=datetime.now(timezone.utc))
    db_session.add(version)
    db_session.flush()
    course.active_version_id = version.id
    other_version = CourseVersion(course_id=course.id, version_number=2)
    db_session.add(other_version)
    db_session.flush()

    foreign_item = LearningItem(course_version_id=other_version.id, type=LearningItemType.THEORY, title="Чужой элемент")
    db_session.add(foreign_item)
    db_session.add(Enrollment(user_id=student.id, course_id=course.id, course_version_id=version.id, status=EnrollmentStatus.ACTIVE))
    db_session.commit()

    as_user(client, student)
    resp = client.put(f"/api/courses/{course.id}/last-position", json={"item_id": foreign_item.id})
    assert resp.status_code == 422


def test_last_position_saves_for_enrolled_course(client, db_session):
    student = make_user(db_session, "student")

    course = Course(title="C1")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, version_number=1, published_at=datetime.now(timezone.utc))
    db_session.add(version)
    db_session.flush()
    course.active_version_id = version.id
    item = LearningItem(course_version_id=version.id, type=LearningItemType.THEORY, title="Урок 1")
    db_session.add(item)
    db_session.add(Enrollment(user_id=student.id, course_id=course.id, course_version_id=version.id, status=EnrollmentStatus.ACTIVE))
    db_session.commit()

    as_user(client, student)
    resp = client.put(f"/api/courses/{course.id}/last-position", json={"item_id": item.id})
    assert resp.status_code == 200

    db_session.refresh(db_session.query(Enrollment).filter(Enrollment.user_id == student.id).first())
    enrollment = db_session.query(Enrollment).filter(Enrollment.user_id == student.id).first()
    assert enrollment.last_item_id == item.id
    completion = db_session.query(ItemCompletion).filter(
        ItemCompletion.user_id == student.id,
        ItemCompletion.item_id == item.id,
    ).one()
    assert completion.item_id == item.id

    tree = client.get(f"/api/courses/{course.id}/tree")
    assert tree.status_code == 200
    assert tree.json()[0]["completed"] is True


def test_last_position_does_not_complete_gradable_item(client, db_session):
    student = make_user(db_session, "student")
    course = Course(title="C1")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, version_number=1, published_at=datetime.now(timezone.utc))
    db_session.add(version)
    db_session.flush()
    course.active_version_id = version.id
    problem = ProblemRevision(task_id=1, revision_number=1, title="Задача")
    db_session.add(problem)
    db_session.flush()
    item = LearningItem(course_version_id=version.id, type=LearningItemType.TASK, title="Задача", problem_revision_id=problem.id)
    db_session.add(item)
    db_session.add(Enrollment(user_id=student.id, course_id=course.id, course_version_id=version.id, status=EnrollmentStatus.ACTIVE))
    db_session.commit()

    as_user(client, student)
    assert client.put(f"/api/courses/{course.id}/last-position", json={"item_id": item.id}).status_code == 200
    assert db_session.query(ItemCompletion).filter(ItemCompletion.item_id == item.id).count() == 0
