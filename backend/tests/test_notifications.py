"""NTF-001/003: внутренние уведомления и управление необязательными типами."""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models import (
    Course,
    CourseVersion,
    Enrollment,
    EnrollmentStatus,
    LearningItem,
    LearningItemType,
    Notification,
    NotificationPreference,
    NotificationType,
    ProblemRevision,
    Progress,
    Submission,
    SubmissionStatus,
    User,
)
from app.notify_deadlines import run_once
from app.services.notifications import notify
from tests.conftest import as_user, make_user


def _sig(ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), ref.encode(), hashlib.sha256).hexdigest()


def test_enroll_via_lms_creates_course_assigned_notification(client, db_session):
    course = Course(title="Python")
    db_session.add(course)
    db_session.commit()

    external_ref = "lp-student-1"
    resp = client.post(
        f"/api/admin/courses/{course.id}/enroll",
        json={"externalRef": external_ref},
        headers={"X-LP-Signature": _sig(external_ref)},
    )
    assert resp.status_code == 200

    student = db_session.query(User).filter(User.external_ref == external_ref).first()
    notifications = db_session.query(Notification).filter(Notification.user_id == student.id).all()
    assert len(notifications) == 1
    assert notifications[0].type == NotificationType.COURSE_ASSIGNED
    assert "Python" in notifications[0].title


def test_enroll_twice_does_not_duplicate_notification(client, db_session):
    course = Course(title="Python")
    db_session.add(course)
    db_session.commit()
    external_ref = "lp-student-1"
    sig = _sig(external_ref)

    client.post(f"/api/admin/courses/{course.id}/enroll", json={"externalRef": external_ref}, headers={"X-LP-Signature": sig})
    client.post(f"/api/admin/courses/{course.id}/enroll", json={"externalRef": external_ref}, headers={"X-LP-Signature": sig})

    student = db_session.query(User).filter(User.external_ref == external_ref).first()
    count = db_session.query(Notification).filter(Notification.user_id == student.id).count()
    assert count == 1  # уже активен во второй раз — повторного уведомления нет


def test_manual_grade_creates_notification_with_comment(client, db_session):
    teacher = make_user(db_session, "teacher", external_ref="lp-teacher-1")
    student = make_user(db_session, "student", external_ref="lp-student-1")
    problem = ProblemRevision(task_id=1, revision_number=1, title="T")
    db_session.add(problem)
    db_session.flush()
    sub = Submission(user_id=student.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.DONE, score=10.0)
    db_session.add(sub)
    db_session.commit()

    as_user(client, teacher)
    resp = client.put(f"/api/submissions/{sub.id}/grade", json={"score": 90.0, "comment": "Молодец"})
    assert resp.status_code == 200

    notif = db_session.query(Notification).filter(Notification.user_id == student.id).first()
    assert notif is not None
    assert notif.type == NotificationType.MANUAL_REVIEW_RESULT
    assert "Молодец" in notif.body


def test_optional_notification_can_be_disabled(client, db_session):
    student = make_user(db_session, "student")
    as_user(client, student)

    resp = client.put("/api/me/notification-preferences/deadline_approaching", json={"enabled": False})
    assert resp.status_code == 200

    notify(db_session, student.id, NotificationType.DEADLINE_APPROACHING, "test")
    assert db_session.query(Notification).filter(Notification.user_id == student.id).count() == 0


def test_mandatory_notification_cannot_be_disabled(client, db_session):
    student = make_user(db_session, "student")
    as_user(client, student)

    resp = client.put("/api/me/notification-preferences/course_assigned", json={"enabled": False})
    assert resp.status_code == 422

    notify(db_session, student.id, NotificationType.COURSE_ASSIGNED, "test")
    assert db_session.query(Notification).filter(Notification.user_id == student.id).count() == 1


def test_list_and_mark_read(client, db_session):
    student = make_user(db_session, "student")
    db_session.add(Notification(user_id=student.id, type=NotificationType.COURSE_ASSIGNED, title="T1"))
    db_session.commit()
    notif_id = db_session.query(Notification).filter(Notification.user_id == student.id).first().id

    as_user(client, student)
    resp = client.get("/api/me/notifications")
    assert len(resp.json()) == 1
    assert resp.json()[0]["is_read"] is False

    resp = client.put(f"/api/me/notifications/{notif_id}/read")
    assert resp.status_code == 200

    resp = client.get("/api/me/notifications?unread_only=true")
    assert resp.json() == []


def test_deadline_reminder_sent_once_within_window(db_session):
    student = make_user(db_session, "student")
    course = Course(title="C")
    db_session.add(course)
    db_session.flush()
    db_session.add(Enrollment(
        user_id=student.id, course_id=course.id, status=EnrollmentStatus.ACTIVE,
        ends_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))
    db_session.commit()

    sent = run_once(db_session)
    assert sent == 1
    notif = db_session.query(Notification).filter(Notification.user_id == student.id).first()
    assert notif.type == NotificationType.DEADLINE_APPROACHING

    sent_again = run_once(db_session)
    assert sent_again == 0  # deadline_notified_at уже выставлен — повторно не шлём


def test_deadline_reminder_skips_completed_course(db_session):
    student = make_user(db_session, "student")
    course = Course(title="C")
    db_session.add(course)
    db_session.flush()
    db_session.add(Enrollment(
        user_id=student.id, course_id=course.id, status=EnrollmentStatus.ACTIVE,
        ends_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))
    db_session.add(Progress(user_id=student.id, course_id=course.id, completed_items=1, total_items=1, percent=100.0))
    db_session.commit()

    sent = run_once(db_session)
    assert sent == 0
    assert db_session.query(Notification).filter(Notification.user_id == student.id).count() == 0
