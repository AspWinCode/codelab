"""GRD/STU: редактирование существующей задачи методистом (тесты — видимые
и скрытые, description/условие) и студенческий вид задачи без reference_solution
и скрытых тестов — раньше ни того, ни другого не было (STU-003)."""
import hashlib
import hmac

from app.config import settings
from tests.conftest import as_user, make_user


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Методист", role="methodist"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


def _create_course_and_task(client):
    qs = _staff_qs()
    sig = _sig("lp-user-1")
    course = client.post(f"/api/lms-admin/courses?{qs}", json={"title": "C"}, headers={"X-LP-Signature": sig}).json()
    task = client.post(
        f"/api/lms-admin/courses/{course['id']}/tasks?{qs}",
        json={
            "title": "Сумма",
            "statement": "<p>Даны два числа.</p>",
            "tests": [
                {"input": "2 3\n", "expected": "5\n", "is_hidden": False},
                {"input": "10 20\n", "expected": "30\n", "is_hidden": True},
            ],
        },
        headers={"X-LP-Signature": sig},
    ).json()
    item = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={"type": "task", "title": "Сумма", "problem_revision_id": task["id"], "position": 0},
        headers={"X-LP-Signature": sig},
    ).json()
    return course, task, item, qs, sig


def test_update_task_mutates_in_place(client):
    course, task, item, qs, sig = _create_course_and_task(client)

    resp = client.put(
        f"/api/lms-admin/tasks/{task['id']}?{qs}",
        json={
            "title": "Сумма (испр.)",
            "statement": "<p>Исправленное условие</p>",
            "tests": [{"input": "1 1\n", "expected": "2\n", "is_hidden": False}],
        },
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["id"] == task["id"]  # тот же id — не новая ревизия
    assert updated["title"] == "Сумма (испр.)"
    assert len(updated["tests"]) == 1


def test_foreign_methodist_cannot_edit_task(client):
    course, task, item, qs, sig = _create_course_and_task(client)

    other_qs = _staff_qs(external_ref="lp-user-2", full_name="Другой", role="methodist")
    other_sig = _sig("lp-user-2")
    resp = client.put(
        f"/api/lms-admin/tasks/{task['id']}?{other_qs}",
        json={"title": "Хак"},
        headers={"X-LP-Signature": other_sig},
    )
    assert resp.status_code == 403


def test_student_sees_statement_and_only_visible_tests(client, db_session):
    course, task, item, qs, sig = _create_course_and_task(client)
    client.post(f"/api/lms-admin/courses/{course['id']}/publish?{qs}", headers={"X-LP-Signature": sig})

    student = make_user(db_session, "student", external_ref="lp-student-task-view")
    as_user(client, student)

    resp = client.get(f"/api/courses/problems/{task['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["statement"] == "<p>Даны два числа.</p>"
    assert len(body["visible_tests"]) == 1
    assert body["visible_tests"][0]["input"] == "2 3\n"
    assert "reference_solution" not in body
    assert "tests" not in body  # только visible_tests, не полный список со скрытыми
