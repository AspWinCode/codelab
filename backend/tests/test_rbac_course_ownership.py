"""RBAC-002: методист получает доступ только к своим курсам, не ко всем."""
import hashlib
import hmac

from app.config import settings


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _qs(external_ref: str, full_name: str, role: str) -> str:
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


METHODIST_A = ("lp-user-a", "Методист A", "methodist")
METHODIST_B = ("lp-user-b", "Методист B", "methodist")
TEACHER = ("lp-user-t", "Тренер T", "teacher")


def _create_course_as(client, staff) -> dict:
    ref, name, role = staff
    return client.post(
        f"/api/lms-admin/courses?{_qs(ref, name, role)}",
        json={"title": f"Курс {ref}"},
        headers={"X-LP-Signature": _sig(ref)},
    ).json()


def test_methodist_cannot_edit_foreign_course(client, db_session):
    course_a = _create_course_as(client, METHODIST_A)

    ref_b, name_b, role_b = METHODIST_B
    qs_b = _qs(ref_b, name_b, role_b)
    sig_b = _sig(ref_b)

    # Методист B не может создать задачу/элемент в курсе методиста A.
    resp = client.post(
        f"/api/lms-admin/courses/{course_a['id']}/tasks?{qs_b}",
        json={"title": "T", "tests": []},
        headers={"X-LP-Signature": sig_b},
    )
    assert resp.status_code == 403

    resp = client.get(f"/api/lms-admin/courses/{course_a['id']}/tree?{qs_b}", headers={"X-LP-Signature": sig_b})
    assert resp.status_code == 403

    resp = client.post(f"/api/lms-admin/courses/{course_a['id']}/publish?{qs_b}", headers={"X-LP-Signature": sig_b})
    assert resp.status_code == 403


def test_methodist_list_courses_shows_only_own(client, db_session):
    course_a = _create_course_as(client, METHODIST_A)
    _create_course_as(client, METHODIST_B)

    ref_a, name_a, role_a = METHODIST_A
    resp = client.get(f"/api/lms-admin/courses?{_qs(ref_a, name_a, role_a)}", headers={"X-LP-Signature": _sig(ref_a)})
    courses = resp.json()
    assert [c["id"] for c in courses] == [course_a["id"]]


def test_teacher_sees_all_published_courses_for_picker(client, db_session):
    _create_course_as(client, METHODIST_A)
    _create_course_as(client, METHODIST_B)

    ref_t, name_t, role_t = TEACHER
    resp = client.get(f"/api/lms-admin/courses?{_qs(ref_t, name_t, role_t)}", headers={"X-LP-Signature": _sig(ref_t)})
    assert len(resp.json()) == 2


def test_own_course_actions_still_work(client, db_session):
    course_a = _create_course_as(client, METHODIST_A)
    ref_a, name_a, role_a = METHODIST_A
    qs_a = _qs(ref_a, name_a, role_a)
    sig_a = _sig(ref_a)

    resp = client.post(
        f"/api/lms-admin/courses/{course_a['id']}/tasks?{qs_a}",
        json={"title": "T", "tests": []},
        headers={"X-LP-Signature": sig_a},
    )
    assert resp.status_code == 200

    resp = client.post(f"/api/lms-admin/courses/{course_a['id']}/publish?{qs_a}", headers={"X-LP-Signature": sig_a})
    assert resp.status_code == 200
