"""Snap!-задание (type=snap_task): пошаговая инструкция слева, статичная
панель Snap! справа — шаги хранятся как steps, отдельной сущности (как у
task/ProblemRevision) не заводим, это просто список {title, content}."""
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


def test_create_snap_task_with_steps(client):
    course, qs, sig = _create_course(client)
    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={
            "type": "snap_task",
            "title": "Первая программа в Snap!",
            "steps": [
                {"title": "Шаг 1", "content": "<p>Перетащи блок «когда флаг нажат».</p>"},
                {"title": "Шаг 2", "content": "<p>Добавь блок «идти вперёд».</p>"},
            ],
            "position": 0,
        },
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()
    assert item["type"] == "snap_task"
    assert len(item["steps"]) == 2
    assert item["steps"][0]["title"] == "Шаг 1"


def test_create_snap_task_without_steps_rejected(client):
    course, qs, sig = _create_course(client)
    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={"type": "snap_task", "title": "Пусто", "position": 0},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 422


def test_update_snap_task_steps(client):
    course, qs, sig = _create_course(client)
    item = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={
            "type": "snap_task", "title": "Задание",
            "steps": [{"title": "Шаг 1", "content": "A"}],
            "position": 0,
        },
        headers={"X-LP-Signature": sig},
    ).json()

    resp = client.put(
        f"/api/lms-admin/items/{item['id']}?{qs}",
        json={"steps": [
            {"title": "Шаг 1", "content": "A"},
            {"title": "Шаг 2", "content": "B"},
            {"title": "Шаг 3", "content": "C"},
        ]},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["steps"]) == 3


def test_snap_task_appears_in_tree(client):
    course, qs, sig = _create_course(client)
    client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={
            "type": "snap_task", "title": "Задание в дереве",
            "steps": [{"title": "Шаг 1", "content": "A"}],
            "position": 0,
        },
        headers={"X-LP-Signature": sig},
    )
    tree = client.get(f"/api/lms-admin/courses/{course['id']}/tree?{qs}", headers={"X-LP-Signature": sig}).json()
    assert len(tree) == 1
    assert tree[0]["type"] == "snap_task"
    assert tree[0]["steps"][0]["title"] == "Шаг 1"
