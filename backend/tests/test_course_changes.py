"""Этап 10 (ТЗ): GET .../changes — история изменений курса. Публикация тут
автоматическая после каждой правки (auto_publish_item), поэтому "диф
черновик/активная версия" почти всегда пуст — осмысленная история это диф
между последовательными ОПУБЛИКОВАННЫМИ версиями (см.
app/services/course_changes.py)."""
import hashlib
import hmac

from app.config import settings


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


def _tree(client, qs, sig, course_id):
    resp = client.get(f"/api/lms-admin/courses/{course_id}/tree?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _flatten(nodes):
    return [n for node in nodes for n in [node, *_flatten(node["children"])]]


def _changes(client, qs, sig, course_id):
    resp = client.get(f"/api/lms-admin/courses/{course_id}/changes?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_no_history_before_second_publish(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    # create_item сам публикует один раз (auto_publish_item) — это первая
    # и единственная опубликованная версия, сравнивать историю ещё не с чем.
    _make_item(client, qs, sig, course["id"], type="theory", title="A")

    assert _changes(client, qs, sig, course["id"]) == []


def test_editing_content_appears_as_changed_with_author_and_date(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    _make_item(client, qs, sig, course["id"], type="theory", title="A", content="Старый текст")

    item_id = _tree(client, qs, sig, course["id"])[0]["id"]
    client.put(f"/api/lms-admin/items/{item_id}?{qs}", json={"content": "Новый текст"}, headers={"X-LP-Signature": sig})

    changes = _changes(client, qs, sig, course["id"])
    assert len(changes) == 1
    changeset = changes[0]
    assert changeset["author"] == "Иван Методист"
    assert changeset["published_at"] is not None
    assert changeset["added"] == []
    assert changeset["removed"] == []
    assert len(changeset["changed"]) == 1
    item_change = changeset["changed"][0]
    assert item_change["title"] == "A"
    content_change = next(f for f in item_change["fields"] if f["field"] == "content")
    assert content_change["old_value"] == "Старый текст"
    assert content_change["new_value"] == "Новый текст"


def test_deleting_item_appears_as_removed(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    _make_item(client, qs, sig, course["id"], type="theory", title="A")

    item_id = _tree(client, qs, sig, course["id"])[0]["id"]
    resp = client.request("DELETE", f"/api/lms-admin/items/{item_id}?{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 200, resp.text

    changes = _changes(client, qs, sig, course["id"])
    assert len(changes) == 1
    assert changes[0]["added"] == []
    assert len(changes[0]["removed"]) == 1
    assert changes[0]["removed"][0]["title"] == "A"
    assert changes[0]["changed"] == []


def test_adding_item_appears_as_added(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    _make_item(client, qs, sig, course["id"], type="theory", title="A")
    _make_item(client, qs, sig, course["id"], type="theory", title="B")

    changes = _changes(client, qs, sig, course["id"])
    assert len(changes) == 1
    assert len(changes[0]["added"]) == 1
    assert changes[0]["added"][0]["title"] == "B"
    assert changes[0]["removed"] == []
    assert changes[0]["changed"] == []


def test_moving_item_between_modules_is_reported_as_parent_id_change(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    _make_item(client, qs, sig, course["id"], type="module", title="M1", position=0)
    _make_item(client, qs, sig, course["id"], type="module", title="M2", position=1)
    tree = _tree(client, qs, sig, course["id"])
    m1_id = next(n["id"] for n in tree if n["title"] == "M1")
    m2_id = next(n["id"] for n in tree if n["title"] == "M2")
    _make_item(client, qs, sig, course["id"], type="theory", title="A", parent_id=m1_id)

    tree = _tree(client, qs, sig, course["id"])
    m2_id = next(n["id"] for n in tree if n["title"] == "M2")
    a_id = next(c["id"] for n in tree if n["title"] == "M1" for c in n["children"])
    client.put(f"/api/lms-admin/items/{a_id}?{qs}", json={"parent_id": m2_id}, headers={"X-LP-Signature": sig})

    changes = _changes(client, qs, sig, course["id"])
    # Каждое отдельное действие методиста (создать M1, создать M2, создать A,
    # переместить A) публикуется отдельно — проверяем именно последний
    # changeset (перемещение), не весь список.
    move_changeset = changes[0]
    assert len(move_changeset["changed"]) == 1
    fields = {f["field"] for f in move_changeset["changed"][0]["fields"]}
    assert "parent_id" in fields


def test_history_is_ordered_most_recent_first(client, db_session):
    qs, sig = _staff_qs(), _sig("lp-user-1")
    course = _make_course(client, qs, sig)
    _make_item(client, qs, sig, course["id"], type="theory", title="A", content="v1")

    item_id = _tree(client, qs, sig, course["id"])[0]["id"]
    client.put(f"/api/lms-admin/items/{item_id}?{qs}", json={"content": "v2"}, headers={"X-LP-Signature": sig})
    item_id = _tree(client, qs, sig, course["id"])[0]["id"]
    client.put(f"/api/lms-admin/items/{item_id}?{qs}", json={"content": "v3"}, headers={"X-LP-Signature": sig})

    changes = _changes(client, qs, sig, course["id"])
    assert len(changes) == 2
    newest, oldest = changes
    assert newest["version_number"] > oldest["version_number"]
    newest_content = next(f for f in newest["changed"][0]["fields"] if f["field"] == "content")
    assert newest_content == {"field": "content", "old_value": "v2", "new_value": "v3"}
