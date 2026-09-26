"""Проект с ручной проверкой (type=project): ученик прикрепляет файлы,
тренер смотрит/комментирует/принимает или отправляет на доработку, может
напомнить о сдаче. Ученические эндпоинты — app/routers/projects.py (cookie
через get_current_user, подменяется as_user из conftest); эндпоинты
сотрудника — app/routers/lms_admin.py (HMAC как test_lms_admin_uploads.py)."""
import hashlib
import hmac
import io
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models import (
    Course,
    CourseVersion,
    Enrollment,
    EnrollmentStatus,
    LearningItem,
    LearningItemType,
    User,
)

from tests.conftest import as_user, make_user


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Тренер", role="teacher"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


def _staff_headers(external_ref="lp-user-1"):
    return {"X-LP-Signature": _sig(external_ref)}


def _make_published_project(db, due_at=None):
    course = Course(title="Курс с проектом")
    db.add(course)
    db.flush()
    version = CourseVersion(course_id=course.id, version_number=1, published_at=datetime.now(timezone.utc))
    db.add(version)
    db.flush()
    course.active_version_id = version.id
    item = LearningItem(
        course_version_id=version.id, type=LearningItemType.PROJECT, title="Итоговый проект", due_at=due_at,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return course, version, item


def _enroll(db, user, course, version):
    db.add(Enrollment(user_id=user.id, course_id=course.id, course_version_id=version.id, status=EnrollmentStatus.ACTIVE))
    db.commit()


def test_student_can_attach_file_submit_and_not_edit_after(client, db_session):
    course, version, item = _make_published_project(db_session)
    student = make_user(db_session, "student", "lp-student-1")
    _enroll(db_session, student, course, version)
    as_user(client, student)

    resp = client.get(f"/api/projects/items/{item.id}/submission")
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"

    upload = client.post(
        f"/api/projects/items/{item.id}/files",
        files={"file": ("solution.py", io.BytesIO(b"print(1)"), "text/x-python")},
    )
    assert upload.status_code == 201
    assert upload.json()["original_filename"] == "solution.py"

    submission_id = resp.json()["id"]
    submitted = client.post(f"/api/projects/submissions/{submission_id}/submit")
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"

    # Нельзя донести файл после отправки.
    again = client.post(
        f"/api/projects/items/{item.id}/files",
        files={"file": ("extra.py", io.BytesIO(b"x"), "text/x-python")},
    )
    assert again.status_code == 409


def test_student_cannot_submit_without_files(client, db_session):
    course, version, item = _make_published_project(db_session)
    student = make_user(db_session, "student", "lp-student-2")
    _enroll(db_session, student, course, version)
    as_user(client, student)

    resp = client.get(f"/api/projects/items/{item.id}/submission")
    submission_id = resp.json()["id"]

    submitted = client.post(f"/api/projects/submissions/{submission_id}/submit")
    assert submitted.status_code == 422


def test_upload_rejects_disallowed_extension(client, db_session):
    course, version, item = _make_published_project(db_session)
    student = make_user(db_session, "student", "lp-student-3")
    _enroll(db_session, student, course, version)
    as_user(client, student)

    resp = client.post(
        f"/api/projects/items/{item.id}/files",
        files={"file": ("virus.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert resp.status_code == 422


def test_staff_roster_includes_students_who_never_started(client, db_session):
    """Тренер должен видеть в списке и тех, кто ещё не открывал проект —
    иначе некому слать напоминание "не забудь сдать"."""
    course, version, item = _make_published_project(db_session)
    student = make_user(db_session, "student", "lp-student-4")
    _enroll(db_session, student, course, version)

    resp = client.get(
        f"/api/lms-admin/courses/{course.id}/projects/{item.id}/submissions?{_staff_qs()}",
        headers=_staff_headers(),
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "draft"
    assert rows[0]["student_external_ref"] == "lp-student-4"


def test_full_review_cycle_needs_revision_then_accept(client, db_session):
    course, version, item = _make_published_project(db_session)
    student = make_user(db_session, "student", "lp-student-5")
    _enroll(db_session, student, course, version)
    as_user(client, student)

    sub_id = client.get(f"/api/projects/items/{item.id}/submission").json()["id"]
    client.post(f"/api/projects/items/{item.id}/files", files={"file": ("a.py", io.BytesIO(b"1"), "text/x-python")})
    client.post(f"/api/projects/submissions/{sub_id}/submit")

    # Тренер комментирует файл и отправляет на доработку без оценки.
    file_id = client.get(f"/api/lms-admin/projects/submissions/{sub_id}?{_staff_qs()}", headers=_staff_headers()).json()["files"][0]["id"]
    comment = client.post(
        f"/api/lms-admin/projects/files/{file_id}/comments?{_staff_qs()}",
        json={"body": "Не хватает обработки ошибок"},
        headers=_staff_headers(),
    )
    assert comment.status_code == 201

    review = client.put(
        f"/api/lms-admin/projects/submissions/{sub_id}/review?{_staff_qs()}",
        json={"decision": "needs_revision", "comment": "Поправь и досдай"},
        headers=_staff_headers(),
    )
    assert review.status_code == 200
    assert review.json()["status"] == "needs_revision"

    # decision=accepted без оценки — 422 (score обязателен).
    bad_accept = client.put(
        f"/api/lms-admin/projects/submissions/{sub_id}/review?{_staff_qs()}",
        json={"decision": "accepted", "comment": "ok"},
        headers=_staff_headers(),
    )
    assert bad_accept.status_code == 422

    # Простой просмотр статуса не заводит новую попытку сам по себе.
    as_user(client, student)
    still_old = client.get(f"/api/projects/items/{item.id}/submission").json()
    assert still_old["id"] == sub_id
    assert still_old["status"] == "needs_revision"

    # Донос файла — вот что заводит новую попытку (attempt 2), не трогая старую.
    uploaded = client.post(
        f"/api/projects/items/{item.id}/files", files={"file": ("b.py", io.BytesIO(b"2"), "text/x-python")},
    )
    assert uploaded.status_code == 201
    new_sub = client.get(f"/api/projects/items/{item.id}/submission").json()
    assert new_sub["attempt_number"] == 2
    assert new_sub["id"] != sub_id
    client.post(f"/api/projects/submissions/{new_sub['id']}/submit")

    accepted = client.put(
        f"/api/lms-admin/projects/submissions/{new_sub['id']}/review?{_staff_qs()}",
        json={"decision": "accepted", "score": 95, "comment": "Отлично"},
        headers=_staff_headers(),
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["score"] == 95

    # История содержит первую (доработочную) попытку.
    detail = client.get(f"/api/lms-admin/projects/submissions/{new_sub['id']}?{_staff_qs()}", headers=_staff_headers()).json()
    assert len(detail["history"]) == 1
    assert detail["history"][0]["status"] == "needs_revision"


def test_reminder_marks_overdue_when_due_date_passed(client, db_session):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    course, version, item = _make_published_project(db_session, due_at=past)
    student = make_user(db_session, "student", "lp-student-6")
    _enroll(db_session, student, course, version)

    rows = client.get(
        f"/api/lms-admin/courses/{course.id}/projects/{item.id}/submissions?{_staff_qs()}",
        headers=_staff_headers(),
    ).json()
    assert rows[0]["is_overdue"] is True

    remind = client.post(
        f"/api/lms-admin/projects/submissions/{rows[0]['id']}/remind?{_staff_qs()}",
        headers=_staff_headers(),
    )
    assert remind.status_code == 200


def test_student_cannot_download_others_file(client, db_session):
    course, version, item = _make_published_project(db_session)
    student = make_user(db_session, "student", "lp-student-7")
    other = make_user(db_session, "student", "lp-student-8")
    _enroll(db_session, student, course, version)
    _enroll(db_session, other, course, version)

    as_user(client, student)
    sub_id = client.get(f"/api/projects/items/{item.id}/submission").json()["id"]
    file_id = client.post(
        f"/api/projects/items/{item.id}/files", files={"file": ("a.py", io.BytesIO(b"1"), "text/x-python")},
    ).json()["id"]

    as_user(client, other)
    resp = client.get(f"/api/projects/files/{file_id}/download")
    assert resp.status_code == 403
