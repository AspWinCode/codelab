"""TASK-007: массовая перепроверка после исправления тестов — только среди
посылок, которые реально относятся к заявленному курсу (RBAC-002)."""
from app.models import (
    Course,
    CourseVersion,
    LearningItem,
    LearningItemType,
    ProblemRevision,
    Submission,
    SubmissionStatus,
    User,
)
from tests.conftest import as_user, make_user


def _course_with_submission(db, title, verdict_score=0.0, created_by_id=None):
    course = Course(title=title, created_by_id=created_by_id)
    db.add(course)
    db.flush()
    version = CourseVersion(course_id=course.id, version_number=1)
    db.add(version)
    db.flush()
    problem = ProblemRevision(task_id=course.id * 100, revision_number=1, title="T")
    db.add(problem)
    db.flush()
    item = LearningItem(course_version_id=version.id, type=LearningItemType.TASK, title="Task", problem_revision_id=problem.id)
    db.add(item)
    student = User(external_ref=f"lp-student-{title}", full_name="Student", role="student")
    db.add(student)
    db.flush()
    sub = Submission(user_id=student.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, score=verdict_score)
    db.add(sub)
    db.commit()
    return course, sub


def test_rerun_via_cookie_session_requeues_own_course_submission(client, db_session):
    methodist = make_user(db_session, "methodist")
    course, sub = _course_with_submission(db_session, "A", created_by_id=methodist.id)

    as_user(client, methodist)
    resp = client.post(f"/api/courses/{course.id}/submissions/rerun", json={"submission_ids": [sub.id]})
    assert resp.status_code == 200
    assert resp.json()["requeued"] == 1

    db_session.refresh(sub)
    assert sub.status == SubmissionStatus.QUEUED
    assert sub.priority == 10
    assert sub.score is None


def test_rerun_ignores_submission_ids_from_other_course(client, db_session):
    methodist = make_user(db_session, "methodist")
    course_a, sub_a = _course_with_submission(db_session, "A", created_by_id=methodist.id)
    course_b, sub_b = _course_with_submission(db_session, "B", created_by_id=methodist.id)

    as_user(client, methodist)
    # Запрос утверждает course_a, но передаёт id посылки из course_b.
    resp = client.post(f"/api/courses/{course_a.id}/submissions/rerun", json={"submission_ids": [sub_a.id, sub_b.id]})
    assert resp.status_code == 200
    assert resp.json()["requeued"] == 1  # только своя посылка

    db_session.refresh(sub_b)
    assert sub_b.status == SubmissionStatus.DONE  # чужая посылка не тронута


def test_rerun_via_lms_admin_rejects_foreign_methodist(client, db_session):
    import hashlib
    import hmac

    from app.config import settings

    def sig(ref: str) -> str:
        return hmac.new(settings.sso_kodex_shared_secret.encode(), ref.encode(), hashlib.sha256).hexdigest()

    owner = make_user(db_session, "methodist", external_ref="lp-user-a")
    course, sub = _course_with_submission(db_session, "A", created_by_id=owner.id)

    qs_owner = "staff_external_ref=lp-user-a&staff_full_name=A&staff_role=methodist"
    resp = client.post(
        f"/api/lms-admin/courses/{course.id}/submissions/rerun?{qs_owner}",
        json={"submission_ids": [sub.id]},
        headers={"X-LP-Signature": sig("lp-user-a")},
    )
    assert resp.status_code == 200
    assert resp.json()["requeued"] == 1

    qs_stranger = "staff_external_ref=lp-user-b&staff_full_name=B&staff_role=methodist"
    resp = client.post(
        f"/api/lms-admin/courses/{course.id}/submissions/rerun?{qs_stranger}",
        json={"submission_ids": [sub.id]},
        headers={"X-LP-Signature": sig("lp-user-b")},
    )
    assert resp.status_code == 403
