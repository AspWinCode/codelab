"""GDevelop-задание (type=gdevelop_task) — тот же паттерн, что snap_task
(см. test_snap_task.py): шаги слева, статичная панель GDevelop справа."""
import hashlib
import hmac

from app.config import settings


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Методист", role="methodist"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


def _create_course(client):
    qs = _staff_qs()
    sig = _sig("lp-user-1")
    course = client.post(f"/api/lms-admin/courses?{qs}", json={"title": "C"}, headers={"X-LP-Signature": sig}).json()
    return course, qs, sig


def test_create_gdevelop_task_with_steps(client):
    course, qs, sig = _create_course(client)
    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={
            "type": "gdevelop_task",
            "title": "Первая сцена в GDevelop",
            "steps": [
                {"title": "Шаг 1", "content": "<p>Создай новый объект-спрайт.</p>"},
                {"title": "Шаг 2", "content": "<p>Добавь событие движения по клавишам.</p>"},
            ],
            "position": 0,
        },
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()
    assert item["type"] == "gdevelop_task"
    assert len(item["steps"]) == 2
    assert item["steps"][0]["title"] == "Шаг 1"


def test_create_gdevelop_task_without_steps_rejected(client):
    course, qs, sig = _create_course(client)
    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={"type": "gdevelop_task", "title": "Пусто", "position": 0},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 422


def test_gdevelop_task_appears_in_tree(client):
    course, qs, sig = _create_course(client)
    client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={
            "type": "gdevelop_task", "title": "Задание в дереве",
            "steps": [{"title": "Шаг 1", "content": "A"}],
            "position": 0,
        },
        headers={"X-LP-Signature": sig},
    )
    tree = client.get(f"/api/lms-admin/courses/{course['id']}/tree?{qs}", headers={"X-LP-Signature": sig}).json()
    assert len(tree) == 1
    assert tree[0]["type"] == "gdevelop_task"
    assert tree[0]["steps"][0]["title"] == "Шаг 1"
