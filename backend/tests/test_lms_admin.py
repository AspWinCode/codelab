"""Подписанный admin-API для LMS: методист/преподаватель работают через свой
аккаунт портала, не заходя в Codelab по браузерной cookie-сессии."""
import hashlib
import hmac
from datetime import datetime, timezone

from app.config import settings
from app.models import Course, CourseVersion, LearningItem, LearningItemType, ProblemRevision, Submission, SubmissionStatus, User


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Методист", role="methodist"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


def test_rejects_bad_signature(client):
    resp = client.post(f"/api/lms-admin/courses?{_staff_qs()}", json={"title": "C"}, headers={"X-LP-Signature": "wrong"})
    assert resp.status_code == 401


def test_rejects_unknown_role(client):
    resp = client.post(
        f"/api/lms-admin/courses?{_staff_qs(role='sales')}",
        json={"title": "C"},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 422


def test_create_course_creates_staff_user_lazily(client, db_session):
    assert db_session.query(User).filter(User.external_ref == "lp-user-1").first() is None

    resp = client.post(
        f"/api/lms-admin/courses?{_staff_qs()}",
        json={"title": "Python с нуля"},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 200
    course = resp.json()
    assert course["title"] == "Python с нуля"

    staff = db_session.query(User).filter(User.external_ref == "lp-user-1").first()
    assert staff is not None
    assert staff.role == "methodist"

    db_course = db_session.query(Course).filter(Course.id == course["id"]).first()
    assert db_course.created_by_id == staff.id


def test_full_authoring_and_publish_flow(client, db_session):
    sig = _sig("lp-user-1")
    qs = _staff_qs()

    course = client.post(f"/api/lms-admin/courses?{qs}", json={"title": "C"}, headers={"X-LP-Signature": sig}).json()
    task = client.post(
        f"/api/lms-admin/courses/{course['id']}/tasks?{qs}",
        json={"title": "Сумма", "tests": [{"input": "2 3\n", "expected": "5\n"}]},
        headers={"X-LP-Signature": sig},
    ).json()
    item = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={"type": "task", "title": "Задача 1", "problem_revision_id": task["id"]},
        headers={"X-LP-Signature": sig},
    ).json()

    tree = client.get(f"/api/lms-admin/courses/{course['id']}/tree?{qs}", headers={"X-LP-Signature": sig}).json()
    assert len(tree) == 1 and tree[0]["id"] == item["id"]

    publish_resp = client.post(f"/api/lms-admin/courses/{course['id']}/publish?{qs}", headers={"X-LP-Signature": sig})
    assert publish_resp.status_code == 200
    assert publish_resp.json()["status"] == "published"

    db_course = db_session.query(Course).filter(Course.id == course["id"]).first()
    assert db_course.active_version_id is not None


def test_list_and_grade_submissions(client, db_session):
    sig = _sig("lp-user-2")
    qs = _staff_qs(external_ref="lp-user-2", full_name="Пётр Тренер", role="teacher")

    course = Course(title="C")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, version_number=1, published_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    db_session.add(version)
    db_session.flush()
    course.active_version_id = version.id

    problem = ProblemRevision(task_id=1, revision_number=1, title="T")
    db_session.add(problem)
    db_session.flush()
    item = LearningItem(course_version_id=version.id, type=LearningItemType.TASK, title="Задача", problem_revision_id=problem.id)
    db_session.add(item)

    student = User(external_ref="lp-student-1", full_name="Ученик", role="student")
    db_session.add(student)
    db_session.flush()
    sub = Submission(user_id=student.id, problem_revision_id=problem.id, code="print(1)", status=SubmissionStatus.DONE, score=40.0)
    db_session.add(sub)
    db_session.commit()

    resp = client.get(f"/api/lms-admin/courses/{course.id}/submissions?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["student_full_name"] == "Ученик"
    assert body[0]["code"] == "print(1)"

    grade_resp = client.put(
        f"/api/lms-admin/submissions/{sub.id}/grade?{qs}",
        json={"score": 90.0, "comment": "Работает, но неаккуратно"},
        headers={"X-LP-Signature": sig},
    )
    assert grade_resp.status_code == 200
    assert grade_resp.json()["manual_score_override"] == 90.0


def test_grade_requires_comment(client, db_session):
    sig = _sig("lp-user-2")
    qs = _staff_qs(external_ref="lp-user-2", full_name="Пётр Тренер", role="teacher")

    problem = ProblemRevision(task_id=1, revision_number=1, title="T")
    db_session.add(problem)
    db_session.flush()
    student = User(external_ref="lp-student-1", full_name="Ученик", role="student")
    db_session.add(student)
    db_session.flush()
    sub = Submission(user_id=student.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, score=10.0)
    db_session.add(sub)
    db_session.commit()

    resp = client.put(
        f"/api/lms-admin/submissions/{sub.id}/grade?{qs}",
        json={"score": 50.0, "comment": "   "},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 422
