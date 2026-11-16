"""Этап 5 (ТЗ): предпросмотр черновика курса «как ученик» — та же сборка
дерева, что видит студент, но по черновику, и проверка ответов без
сохранения попытки/прогресса."""
from app.models import OgeAttempt, QuizAttempt
from tests.conftest import as_user, make_user


def test_preview_tree_shows_draft_in_student_shape(client, db_session):
    methodist = make_user(db_session, "methodist")
    as_user(client, methodist)
    course = client.post("/api/courses", json={"title": "C"}).json()

    client.post(f"/api/courses/{course['id']}/items", json={
        "type": "oge_task", "title": "ОГЭ", "content": "Условие", "oge_answer": "12",
    })

    # Черновик ещё не опубликован — обычное /tree для студента вернуло бы 404.
    tree = client.get(f"/api/courses/{course['id']}/preview-tree").json()
    assert len(tree) == 1
    assert tree[0]["type"] == "oge_task"
    assert tree[0]["unlocked"] is True
    assert tree[0]["completed"] is False
    # Student-форма: правильный ответ не должен уходить в теле ответа.
    assert tree[0]["oge_answer"] is None


def test_preview_check_oge_does_not_create_attempt_or_progress(client, db_session):
    methodist = make_user(db_session, "methodist")
    as_user(client, methodist)
    course = client.post("/api/courses", json={"title": "C"}).json()

    item = client.post(f"/api/courses/{course['id']}/items", json={
        "type": "oge_task", "title": "ОГЭ", "content": "Условие", "oge_answer": "12",
    }).json()

    resp = client.post(f"/api/courses/{course['id']}/oge/{item['id']}/preview-check", json={"answer": "12"})
    assert resp.status_code == 200
    assert resp.json()["is_correct"] is True

    resp = client.post(f"/api/courses/{course['id']}/oge/{item['id']}/preview-check", json={"answer": "13"})
    assert resp.json()["is_correct"] is False

    assert db_session.query(OgeAttempt).count() == 0


def test_preview_check_quiz_does_not_create_attempt(client, db_session):
    methodist = make_user(db_session, "methodist")
    as_user(client, methodist)
    course = client.post("/api/courses", json={"title": "C"}).json()

    item = client.post(f"/api/courses/{course['id']}/items", json={
        "type": "quiz", "title": "Тест",
        "quiz_questions": [{"text": "?", "options": [{"text": "A", "correct": True}, {"text": "B", "correct": False}]}],
    }).json()

    resp = client.post(f"/api/courses/{course['id']}/quiz/{item['id']}/preview-check", json={"answers": [[0]]})
    assert resp.json()["score"] == 100.0

    assert db_session.query(QuizAttempt).count() == 0


def test_preview_check_rejects_item_from_another_course(client, db_session):
    methodist = make_user(db_session, "methodist")
    other = make_user(db_session, "methodist", external_ref="lp-other")

    as_user(client, other)
    other_course = client.post("/api/courses", json={"title": "Чужой курс"}).json()
    other_item = client.post(f"/api/courses/{other_course['id']}/items", json={
        "type": "oge_task", "title": "ОГЭ", "content": "Условие", "oge_answer": "99",
    }).json()

    as_user(client, methodist)
    course = client.post("/api/courses", json={"title": "Мой курс"}).json()

    resp = client.post(f"/api/courses/{course['id']}/oge/{other_item['id']}/preview-check", json={"answer": "99"})
    assert resp.status_code == 404
