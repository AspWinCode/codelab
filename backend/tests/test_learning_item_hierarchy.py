"""Иерархия дерева курса: 4 фиксированных структурных уровня
(Модуль → Подмодуль → Тема → Подтема), каскадное удаление и архивация
поддерева, запрет вкладывать контент в контент (см. app/services/tree_rules.py,
решение владельца продукта 2026-09-22)."""
import hashlib
import hmac

from app.config import settings
from app.models import LearningItem


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Методист", role="methodist"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


def _make_course(client):
    qs = _staff_qs()
    sig = _sig("lp-user-1")
    course = client.post(f"/api/lms-admin/courses?{qs}", json={"title": "C"}, headers={"X-LP-Signature": sig}).json()
    return course, qs, sig


def _create_item(client, course_id, qs, sig, **kwargs):
    return client.post(f"/api/lms-admin/courses/{course_id}/items?{qs}", json=kwargs, headers={"X-LP-Signature": sig})


def _find_item(nodes, title):
    for node in nodes:
        if node["title"] == title:
            return node
        found = _find_item(node["children"], title)
        if found:
            return found
    return None


def _current_item(client, course_id, qs, sig, title):
    resp = client.get(f"/api/lms-admin/courses/{course_id}/tree?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 200, resp.text
    item = _find_item(resp.json(), title)
    assert item is not None, f"Не найден элемент {title!r} в текущем черновике"
    return item


def test_full_chain_module_submodule_topic_subtopic_ok(client):
    course, qs, sig = _make_course(client)
    module = _create_item(client, course["id"], qs, sig, type="module", title="M1", position=0).json()
    submodule = _create_item(client, course["id"], qs, sig, type="submodule", title="S1", parent_id=module["id"], position=0).json()
    topic = _create_item(client, course["id"], qs, sig, type="topic", title="T1", parent_id=submodule["id"], position=0).json()
    subtopic = _create_item(client, course["id"], qs, sig, type="subtopic", title="ST1", parent_id=topic["id"], position=0).json()
    assert subtopic["parent_id"] is not None


def test_module_rejects_parent(client):
    course, qs, sig = _make_course(client)
    parent = _create_item(client, course["id"], qs, sig, type="module", title="M1", position=0).json()
    resp = _create_item(client, course["id"], qs, sig, type="module", title="M2", parent_id=parent["id"], position=0)
    assert resp.status_code == 422


def test_submodule_requires_module_parent(client):
    course, qs, sig = _make_course(client)
    topic_like = _create_item(client, course["id"], qs, sig, type="topic", title="not a module", position=0)
    # topic без родителя тоже должен быть отвергнут (нужен submodule-родитель) —
    # но сначала создание самого topic без родителя тоже невалидно.
    assert topic_like.status_code == 422

    theory = _create_item(client, course["id"], qs, sig, type="theory", title="Content", position=0).json()
    resp = _create_item(client, course["id"], qs, sig, type="submodule", title="S1", parent_id=theory["id"], position=0)
    assert resp.status_code == 422


def test_topic_skip_level_rejected(client):
    course, qs, sig = _make_course(client)
    module = _create_item(client, course["id"], qs, sig, type="module", title="M1", position=0).json()
    # Тема напрямую под модулем — минуя подмодуль — запрещена.
    resp = _create_item(client, course["id"], qs, sig, type="topic", title="T1", parent_id=module["id"], position=0)
    assert resp.status_code == 422


def test_content_can_live_at_any_structural_level(client):
    course, qs, sig = _make_course(client)
    module = _create_item(client, course["id"], qs, sig, type="module", title="M1", position=0).json()
    submodule = _create_item(client, course["id"], qs, sig, type="submodule", title="S1", parent_id=module["id"], position=0).json()
    topic = _create_item(client, course["id"], qs, sig, type="topic", title="T1", parent_id=submodule["id"], position=0).json()
    subtopic = _create_item(client, course["id"], qs, sig, type="subtopic", title="ST1", parent_id=topic["id"], position=0).json()

    for parent_title in (None, "M1", "S1", "T1", "ST1"):
        parent_id = _current_item(client, course["id"], qs, sig, parent_title)["id"] if parent_title else None
        resp = _create_item(client, course["id"], qs, sig, type="theory", title="Материал", parent_id=parent_id, position=0)
        assert resp.status_code == 200, resp.text


def test_content_cannot_have_children(client):
    course, qs, sig = _make_course(client)
    theory = _create_item(client, course["id"], qs, sig, type="theory", title="Материал", position=0).json()
    resp = _create_item(client, course["id"], qs, sig, type="theory", title="Вложенный", parent_id=theory["id"], position=0)
    assert resp.status_code == 422


def test_cascade_delete_removes_whole_subtree(client, db_session):
    course, qs, sig = _make_course(client)
    module = _create_item(client, course["id"], qs, sig, type="module", title="M1", position=0).json()
    submodule = _create_item(client, course["id"], qs, sig, type="submodule", title="S1", parent_id=module["id"], position=0).json()
    topic = _create_item(client, course["id"], qs, sig, type="topic", title="T1", parent_id=submodule["id"], position=0).json()
    theory = _create_item(client, course["id"], qs, sig, type="theory", title="Материал", parent_id=topic["id"], position=0).json()

    current_module = _current_item(client, course["id"], qs, sig, "M1")
    resp = client.delete(f"/api/lms-admin/items/{current_module['id']}?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 200

    # Исторические опубликованные версии сохраняются. Проверяем текущий
    # черновик, из которого удалено всё поддерево.
    assert _find_item(
        client.get(f"/api/lms-admin/courses/{course['id']}/tree?{qs}", headers={"X-LP-Signature": sig}).json(),
        "M1",
    ) is None


def test_archive_cascades_to_descendants_and_hides_from_student(client, db_session):
    from tests.conftest import as_user, make_user

    course, qs, sig = _make_course(client)
    module = _create_item(client, course["id"], qs, sig, type="module", title="M1", position=0).json()
    topic_task = _create_item(client, course["id"], qs, sig, type="theory", title="Материал", parent_id=module["id"], position=0).json()

    current_module = _current_item(client, course["id"], qs, sig, "M1")
    resp = client.put(
        f"/api/lms-admin/items/{current_module['id']}/archive?{qs}", json={"archived": True}, headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200
    assert resp.json()["is_archived"] is True

    db_session.expire_all()
    child = db_session.query(LearningItem).filter(LearningItem.title == "Материал").order_by(LearningItem.id.desc()).first()
    assert child.is_archived is True

    # Разархивация до публикации — доступна, тоже каскадом.
    current_module = _current_item(client, course["id"], qs, sig, "M1")
    resp = client.put(
        f"/api/lms-admin/items/{current_module['id']}/archive?{qs}", json={"archived": False}, headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200
    db_session.expire_all()
    child = db_session.query(LearningItem).filter(LearningItem.title == "Материал").order_by(LearningItem.id.desc()).first()
    assert child.is_archived is False

    # Архивируем снова и публикуем — архивные узлы не должны попасть ученику.
    current_module = _current_item(client, course["id"], qs, sig, "M1")
    client.put(f"/api/lms-admin/items/{current_module['id']}/archive?{qs}", json={"archived": True}, headers={"X-LP-Signature": sig})
    client.post(f"/api/lms-admin/courses/{course['id']}/publish?{qs}", headers={"X-LP-Signature": sig})

    student = make_user(db_session, "student", external_ref="lp-student-archive-test")
    as_user(client, student)
    tree = client.get(f"/api/courses/{course['id']}/tree").json()
    assert tree == []


def test_move_item_into_own_subtree_rejected(client):
    course, qs, sig = _make_course(client)
    module = _create_item(client, course["id"], qs, sig, type="module", title="M1", position=0).json()
    submodule = _create_item(client, course["id"], qs, sig, type="submodule", title="S1", parent_id=module["id"], position=0).json()

    current_module = _current_item(client, course["id"], qs, sig, "M1")
    current_submodule = _current_item(client, course["id"], qs, sig, "S1")
    resp = client.put(
        f"/api/lms-admin/items/{current_module['id']}?{qs}", json={"parent_id": current_submodule["id"]}, headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 422
