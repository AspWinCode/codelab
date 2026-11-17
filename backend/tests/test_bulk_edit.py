"""Этап 9 (ТЗ): массовое редактирование элементов курса методистом."""
import hashlib
import hmac

from app.config import settings
from app.models import LearningItem, LearningItemType
from app.services.course_admin import get_draft_version


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Методист", role="methodist"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


def _make_course(client, qs, sig, title="C"):
    resp = client.post(f"/api/lms-admin/courses?{qs}", json={"title": title}, headers={"X-LP-Signature": sig})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _make_item(client, qs, sig, course_id, **kwargs):
    resp = client.post(f"/api/lms-admin/courses/{course_id}/items?{qs}", json=kwargs, headers={"X-LP-Signature": sig})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _flatten(nodes):
    return [n for node in nodes for n in [node, *_flatten(node["children"])]]


def _current_ids_by_title(client, qs, sig, course_id):
    """create_item авто-публикует курс сразу после каждого вызова
    (course_admin.auto_publish_item) — id, возвращённый одной POST, устаревает,
    как только создаётся ЕЩЁ один элемент того же курса (черновик
    переклонируется в новую версию). Тесты с несколькими одновременно
    живыми элементами поэтому сверяются по дереву, а не по id из ответов."""
    resp = client.get(f"/api/lms-admin/courses/{course_id}/tree?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 200, resp.text
    return {n["title"]: n["id"] for n in _flatten(resp.json())}


def test_bulk_archive_and_unarchive(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    _make_item(client, qs, sig, course["id"], type="theory", title="A")
    _make_item(client, qs, sig, course["id"], type="theory", title="B")
    ids_by_title = _current_ids_by_title(client, qs, sig, course["id"])
    ids = [ids_by_title["A"], ids_by_title["B"]]

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items/bulk?{qs}",
        json={"item_ids": ids, "operation": "archive"},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] == 2 and body["failed"] == 0

    items = db_session.query(LearningItem).filter(LearningItem.id.in_(ids)).all()
    assert all(i.is_archived for i in items)

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items/bulk?{qs}",
        json={"item_ids": ids, "operation": "unarchive"},
        headers={"X-LP-Signature": sig},
    )
    assert resp.json()["succeeded"] == 2
    db_session.expire_all()
    items = db_session.query(LearningItem).filter(LearningItem.id.in_(ids)).all()
    assert all(not i.is_archived for i in items)


def test_bulk_delete(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    a = _make_item(client, qs, sig, course["id"], type="theory", title="A")

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items/bulk?{qs}",
        json={"item_ids": [a["id"]], "operation": "delete"},
        headers={"X-LP-Signature": sig},
    )
    assert resp.json()["succeeded"] == 1
    assert db_session.query(LearningItem).filter(LearningItem.id == a["id"]).first() is None


def test_bulk_set_required_and_weight(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    a = _make_item(client, qs, sig, course["id"], type="theory", title="A", is_required=True, weight=1.0)

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items/bulk?{qs}",
        json={"item_ids": [a["id"]], "operation": "set_required", "required": False},
        headers={"X-LP-Signature": sig},
    )
    assert resp.json()["succeeded"] == 1

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items/bulk?{qs}",
        json={"item_ids": [a["id"]], "operation": "set_weight", "weight": 2.5},
        headers={"X-LP-Signature": sig},
    )
    assert resp.json()["succeeded"] == 1

    db_session.expire_all()
    item = db_session.query(LearningItem).filter(LearningItem.id == a["id"]).first()
    assert item.is_required is False
    assert item.weight == 2.5


def test_bulk_set_max_attempts(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    a = _make_item(client, qs, sig, course["id"], type="oge_task", title="ОГЭ", content="C", oge_answer="1")

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items/bulk?{qs}",
        json={"item_ids": [a["id"]], "operation": "set_max_attempts", "max_attempts": 3},
        headers={"X-LP-Signature": sig},
    )
    assert resp.json()["succeeded"] == 1
    db_session.expire_all()
    item = db_session.query(LearningItem).filter(LearningItem.id == a["id"]).first()
    assert item.oge_max_attempts == 3


def test_bulk_move_reparents_and_avoids_duplicate_positions(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    _make_item(client, qs, sig, course["id"], type="module", title="M1", position=0)
    module_id = _current_ids_by_title(client, qs, sig, course["id"])["M1"]
    _make_item(client, qs, sig, course["id"], type="theory", title="Existing", parent_id=module_id, position=0)
    _make_item(client, qs, sig, course["id"], type="theory", title="A")
    _make_item(client, qs, sig, course["id"], type="theory", title="B")

    ids_by_title = _current_ids_by_title(client, qs, sig, course["id"])
    module_id = ids_by_title["M1"]
    ids = [ids_by_title["A"], ids_by_title["B"]]

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items/bulk?{qs}",
        json={"item_ids": ids, "operation": "move", "parent_id": module_id},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200
    assert resp.json()["succeeded"] == 2

    db_session.expire_all()
    items = db_session.query(LearningItem).filter(LearningItem.id.in_(ids)).all()
    assert all(i.parent_id == module_id for i in items)
    existing_position = db_session.query(LearningItem).filter(LearningItem.id == ids_by_title["Existing"]).first().position
    positions = {existing_position} | {i.position for i in items}
    assert len(positions) == 3  # все три позиции уникальны — без коллизий


def test_bulk_move_rejects_invalid_hierarchy(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    _make_item(client, qs, sig, course["id"], type="theory", title="Содержимое")
    _make_item(client, qs, sig, course["id"], type="theory", title="Другое содержимое")
    ids_by_title = _current_ids_by_title(client, qs, sig, course["id"])

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/items/bulk?{qs}",
        json={"item_ids": [ids_by_title["Другое содержимое"]], "operation": "move", "parent_id": ids_by_title["Содержимое"]},
        headers={"X-LP-Signature": sig},
    )
    body = resp.json()
    assert body["succeeded"] == 0
    assert body["failed"] == 1
    assert body["results"][0]["ok"] is False


def test_bulk_copy_to_another_course(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    source = _make_course(client, qs, sig, title="Источник")
    target = _make_course(client, qs, sig, title="Назначение")
    _make_item(client, qs, sig, source["id"], type="module", title="M1")
    module_id = _current_ids_by_title(client, qs, sig, source["id"])["M1"]
    _make_item(client, qs, sig, source["id"], type="theory", title="Внутри модуля", parent_id=module_id)
    module_id = _current_ids_by_title(client, qs, sig, source["id"])["M1"]

    resp = client.post(
        f"/api/lms-admin/courses/{source['id']}/items/bulk?{qs}",
        json={"item_ids": [module_id], "operation": "copy_to_course", "target_course_id": target["id"]},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200
    assert resp.json()["succeeded"] == 1

    # Сравниваем только живые черновики — у исходного курса "M1" есть ещё и
    # в более старых (уже опубликованных) версиях, авто-публикация создаёт
    # их по одной на каждое create_item (см. _current_ids_by_title выше).
    source_draft_id = get_draft_version(db_session, source["id"]).id
    target_draft_id = get_draft_version(db_session, target["id"]).id
    cloned_modules = (
        db_session.query(LearningItem)
        .filter(
            LearningItem.type == LearningItemType.MODULE, LearningItem.title == "M1",
            LearningItem.course_version_id.in_([source_draft_id, target_draft_id]),
        )
        .all()
    )
    # Один в живом черновике источника, один — новая копия в целевом курсе.
    assert len(cloned_modules) == 2
    copied_module = next(m for m in cloned_modules if m.course_version_id == target_draft_id)
    children = db_session.query(LearningItem).filter(LearningItem.parent_id == copied_module.id).all()
    assert len(children) == 1
    assert children[0].title == "Внутри модуля"


def test_bulk_rejects_item_from_another_course(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course_a = _make_course(client, qs, sig, title="A")
    course_b = _make_course(client, qs, sig, title="B")
    item_b = _make_item(client, qs, sig, course_b["id"], type="theory", title="Чужой")

    resp = client.post(
        f"/api/lms-admin/courses/{course_a['id']}/items/bulk?{qs}",
        json={"item_ids": [item_b["id"]], "operation": "archive"},
        headers={"X-LP-Signature": sig},
    )
    body = resp.json()
    assert body["succeeded"] == 0
    assert body["failed"] == 1
    assert "не найден" in body["results"][0]["error"].lower()


def test_export_items_returns_snapshots(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    a = _make_item(client, qs, sig, course["id"], type="theory", title="A", content="Контент A")

    resp = client.get(f"/api/lms-admin/courses/{course['id']}/items/export?{qs}&item_ids={a['id']}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "A"
    assert body[0]["content"] == "Контент A"
