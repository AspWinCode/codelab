"""ADM-001: реестр окружений в серверном admin-API и валидация ProblemRevisionCreate.language."""
import hashlib
import hmac

from app.config import settings


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Методист", role="methodist"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


def test_list_environments(client):
    resp = client.get(f"/api/lms-admin/environments?{_staff_qs()}", headers={"X-LP-Signature": _sig("lp-user-1")})
    assert resp.status_code == 200
    ids = {e["id"] for e in resp.json()}
    assert ids == {"python3", "python3-data", "cpp17", "sql-sqlite", "arcade"}
    arcade = next(e for e in resp.json() if e["id"] == "arcade")
    assert arcade["status"] == "beta"


def test_create_task_rejects_unknown_language(client):
    qs = _staff_qs()
    sig = _sig("lp-user-1")
    course = client.post(f"/api/lms-admin/courses?{qs}", json={"title": "C"}, headers={"X-LP-Signature": sig}).json()

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/tasks?{qs}",
        json={"title": "Задача", "language": "java21", "tests": [{"input": "", "expected": "1\n"}]},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 422


def test_create_cpp_task_with_registered_language(client):
    qs = _staff_qs()
    sig = _sig("lp-user-1")
    course = client.post(f"/api/lms-admin/courses?{qs}", json={"title": "C"}, headers={"X-LP-Signature": sig}).json()

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/tasks?{qs}",
        json={"title": "Задача на C++", "language": "cpp17", "tests": [{"input": "", "expected": "1\n"}]},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200
    assert resp.json()["language"] == "cpp17"


def test_create_sql_task_with_fixture(client):
    qs = _staff_qs()
    sig = _sig("lp-user-1")
    course = client.post(f"/api/lms-admin/courses?{qs}", json={"title": "C"}, headers={"X-LP-Signature": sig}).json()

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/tasks?{qs}",
        json={
            "title": "Задача на SQL",
            "language": "sql-sqlite",
            "sql_fixture": "CREATE TABLE t (x INTEGER); INSERT INTO t VALUES (1);",
            "tests": [{"input": "", "expected": "x\n1\n"}],
        },
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200
    assert resp.json()["sql_fixture"].startswith("CREATE TABLE")
