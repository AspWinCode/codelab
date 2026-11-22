"""Редактирование/архивация/удаление курса самого по себе (не элементов
дерева — для них это уже было, см. test_learning_item_hierarchy.py)."""
import hashlib
import hmac

from app.config import settings


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Методист", role="methodist"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


def _create_course(client, title="C"):
    qs = _staff_qs()
    sig = _sig("lp-user-1")
    course = client.post(f"/api/lms-admin/courses?{qs}", json={"title": title}, headers={"X-LP-Signature": sig}).json()
    return course, qs, sig


def test_update_course_title(client):
    course, qs, sig = _create_course(client)
    resp = client.put(
        f"/api/lms-admin/courses/{course['id']}?{qs}",
        json={"title": "Новое название", "description": "descr"},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Новое название"
    assert body["description"] == "descr"


def test_archive_and_unarchive_course(client):
    course, qs, sig = _create_course(client)
    resp = client.put(
        f"/api/lms-admin/courses/{course['id']}/archive?{qs}",
        json={"archived": True},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_archived"] is True

    resp = client.put(
        f"/api/lms-admin/courses/{course['id']}/archive?{qs}",
        json={"archived": False},
        headers={"X-LP-Signature": sig},
    )
    assert resp.json()["is_archived"] is False


def test_delete_draft_course(client):
    course, qs, sig = _create_course(client)
    resp = client.delete(f"/api/lms-admin/courses/{course['id']}?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 204, resp.text

    resp = client.get(f"/api/lms-admin/courses?{qs}", headers={"X-LP-Signature": sig})
    assert course["id"] not in [c["id"] for c in resp.json()]


def test_delete_published_course_rejected(client):
    course, qs, sig = _create_course(client)
    client.post(f"/api/lms-admin/courses/{course['id']}/publish?{qs}", headers={"X-LP-Signature": sig})

    resp = client.delete(f"/api/lms-admin/courses/{course['id']}?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 409


def test_delete_published_course_with_tasks_is_rejected(client):
    course, qs, sig = _create_course(client)
    task = client.post(
        f"/api/lms-admin/courses/{course['id']}/tasks?{qs}",
        json={"title": "T", "tests": [{"input": "1", "expected": "1", "is_hidden": False}]},
        headers={"X-LP-Signature": sig},
    ).json()
    client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={"type": "task", "title": "T", "problem_revision_id": task["id"], "position": 0},
        headers={"X-LP-Signature": sig},
    )

    # Добавление элемента автоматически публикует курс, поэтому удаление
    # опубликованного курса должно быть запрещено вместе с его задачами.
    resp = client.delete(f"/api/lms-admin/courses/{course['id']}?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 409

    resp = client.get(f"/api/lms-admin/tasks/{task['id']}?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 200


def test_foreign_methodist_cannot_edit_or_delete(client):
    course, qs, sig = _create_course(client)
    other_qs = _staff_qs(external_ref="lp-user-2", full_name="Другой Методист")
    other_sig = _sig("lp-user-2")

    resp = client.put(
        f"/api/lms-admin/courses/{course['id']}?{other_qs}",
        json={"title": "Захват"},
        headers={"X-LP-Signature": other_sig},
    )
    assert resp.status_code == 403

    resp = client.delete(f"/api/lms-admin/courses/{course['id']}?{other_qs}", headers={"X-LP-Signature": other_sig})
    assert resp.status_code == 403


def test_item_mutations_can_stay_in_draft_until_publish(client, db_session):
    """Методист может накопить несколько изменений, проверить черновик и
    опубликовать их одной операцией. Старый publish=true по умолчанию остаётся
    совместимым с существующим клиентом."""
    course, qs, sig = _create_course(client)
    module = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}&publish=false",
        json={"type": "module", "title": "Черновик", "position": 0},
        headers={"X-LP-Signature": sig},
    )
    assert module.status_code == 200, module.text
    module_id = module.json()["id"]

    child = client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}&publish=false",
        json={"type": "theory", "title": "Материал", "parent_id": module_id, "position": 0},
        headers={"X-LP-Signature": sig},
    )
    assert child.status_code == 200, child.text

    validation = client.get(
        f"/api/lms-admin/courses/{course['id']}/validation?{qs}",
        headers={"X-LP-Signature": sig},
    )
    assert validation.status_code == 200
    assert validation.json()["valid"] is True

    draft_status = client.get(
        f"/api/lms-admin/courses/{course['id']}/draft-status?{qs}",
        headers={"X-LP-Signature": sig},
    )
    assert draft_status.status_code == 200
    assert draft_status.json()["has_unpublished_changes"] is True

    draft = client.get(
        f"/api/lms-admin/courses/{course['id']}/tree?{qs}",
        headers={"X-LP-Signature": sig},
    ).json()
    assert draft[0]["title"] == "Черновик"
    assert draft[0]["children"][0]["title"] == "Материал"

    publish = client.post(
        f"/api/lms-admin/courses/{course['id']}/publish?{qs}",
        headers={"X-LP-Signature": sig},
    )
    assert publish.status_code == 200, publish.text
    assert publish.json()["status"] == "published"

    draft_status = client.get(
        f"/api/lms-admin/courses/{course['id']}/draft-status?{qs}",
        headers={"X-LP-Signature": sig},
    )
    assert draft_status.json()["has_unpublished_changes"] is False
