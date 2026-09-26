"""LMS-001..006: дерево курса, привязка задачи, публикация версии с клонированием
черновика и запрет редактирования уже опубликованной версии."""
from app.models import Course, CourseVersion, LearningItem, ProblemRevision
from tests.conftest import as_user, make_user


def test_course_tree_and_publish_flow(client, db_session):
    methodist = make_user(db_session, "methodist")
    student = make_user(db_session, "student", external_ref="lp-student-1")

    as_user(client, methodist)
    course = client.post("/api/courses", json={"title": "Python с нуля"}).json()

    task = client.post(f"/api/courses/{course['id']}/tasks", json={
        "title": "Сумма двух чисел",
        "tests": [{"input": "2 3\n", "expected": "5\n"}],
    }).json()

    module = client.post(f"/api/courses/{course['id']}/items", json={
        "type": "module", "title": "Модуль 1", "position": 0,
    }).json()
    item = client.post(f"/api/courses/{course['id']}/items", json={
        "type": "task", "title": "Задача: сумма", "parent_id": module["id"],
        "problem_revision_id": task["id"], "position": 0,
    }).json()

    # Студент не видит дерево непубликованного курса.
    as_user(client, student)
    resp = client.get(f"/api/courses/{course['id']}/tree")
    assert resp.status_code == 404

    as_user(client, methodist)
    tree = client.get(f"/api/courses/{course['id']}/tree").json()
    assert len(tree) == 1
    assert tree[0]["id"] == module["id"]
    assert tree[0]["children"][0]["id"] == item["id"]

    publish_resp = client.post(f"/api/courses/{course['id']}/publish")
    assert publish_resp.status_code == 200
    published = publish_resp.json()
    assert published["status"] == "published"

    # Студент теперь видит опубликованную версию дерева.
    as_user(client, student)
    student_tree = client.get(f"/api/courses/{course['id']}/tree").json()
    assert len(student_tree) == 1
    assert student_tree[0]["title"] == "Модуль 1"

    # Черновик после публикации — новая версия с клоном дерева, отдельная от опубликованной.
    as_user(client, methodist)
    course_row = db_session.query(Course).filter(Course.id == course["id"]).first()
    versions = db_session.query(CourseVersion).filter(CourseVersion.course_id == course["id"]).all()
    assert len(versions) == 2
    draft = [v for v in versions if v.published_at is None][0]
    published_version = [v for v in versions if v.published_at is not None][0]
    assert course_row.active_version_id == published_version.id
    assert draft.id != published_version.id

    draft_items = db_session.query(LearningItem).filter(LearningItem.course_version_id == draft.id).all()
    assert len(draft_items) == 2  # клон модуля + задачи в новом черновике

    # Опубликованную версию редактировать нельзя.
    published_item_id = db_session.query(LearningItem).filter(LearningItem.course_version_id == published_version.id, LearningItem.parent_id.isnot(None)).first().id
    resp = client.put(f"/api/courses/items/{published_item_id}", json={"title": "Хак"})
    assert resp.status_code == 409

    # А черновик — можно.
    draft_item_id = [i.id for i in draft_items if i.parent_id is not None][0]
    resp = client.put(f"/api/courses/items/{draft_item_id}", json={"title": "Переименовано"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Переименовано"


def test_republish_clones_quiz_questions(client, db_session):
    """Регресс: publish_course клонирует дерево черновика в новую версию,
    но клон LearningItem не копировал quiz_questions — после повторной
    публикации курса с тестом (type=quiz) вопросы у клона терялись."""
    methodist = make_user(db_session, "methodist")

    as_user(client, methodist)
    course = client.post("/api/courses", json={"title": "Курс с тестом"}).json()

    quiz_item = client.post(f"/api/courses/{course['id']}/items", json={
        "type": "quiz", "title": "Тест по теме", "position": 0,
        "quiz_questions": [
            {"text": "2 + 2?", "options": [{"text": "4", "correct": True}, {"text": "5", "correct": False}]},
        ],
    }).json()
    assert quiz_item["quiz_questions"]

    # Первая публикация создаёт черновик следующей версии — клонируем его снова.
    assert client.post(f"/api/courses/{course['id']}/publish").status_code == 200
    assert client.post(f"/api/courses/{course['id']}/publish").status_code == 200

    versions = db_session.query(CourseVersion).filter(CourseVersion.course_id == course["id"]).all()
    draft = [v for v in versions if v.published_at is None][0]
    cloned_quiz = (
        db_session.query(LearningItem)
        .filter(LearningItem.course_version_id == draft.id, LearningItem.type == "quiz")
        .first()
    )
    assert cloned_quiz.quiz_questions
    assert cloned_quiz.quiz_questions[0]["text"] == "2 + 2?"


def test_methodist_cannot_edit_foreign_course_via_cookie_session(client, db_session):
    """RBAC-002 — та же проверка владения, что и у /api/lms-admin/*, должна
    действовать и на прямом браузерном SSO-cookie входе методиста, а не
    только на серверном пути от LMS."""
    methodist_a = make_user(db_session, "methodist", external_ref="lp-user-a")
    methodist_b = make_user(db_session, "methodist", external_ref="lp-user-b")

    as_user(client, methodist_a)
    course = client.post("/api/courses", json={"title": "Курс A"}).json()

    as_user(client, methodist_b)
    resp = client.post(f"/api/courses/{course['id']}/tasks", json={"title": "T", "tests": []})
    assert resp.status_code == 403

    resp = client.get(f"/api/courses/{course['id']}/tree")
    assert resp.status_code == 403

    resp = client.post(f"/api/courses/{course['id']}/publish")
    assert resp.status_code == 403

    listed = client.get("/api/courses").json()
    assert course["id"] not in [c["id"] for c in listed]
