"""LMS-010 (ТЗ Этап 4): проверка целостности черновика перед публикацией."""
from app.models import Course, CourseVersion, LearningItem, LearningItemType, ProblemRevision
from app.schemas import LearningItemCreate, QuizQuestion, SnapStep
from app.services.course_admin import create_item, set_item_archived
from app.services.course_validator import normalize_draft_positions, validate_course_before_publish
from tests.conftest import as_user, make_user


def _make_course(db):
    course = Course(title="C")
    db.add(course)
    db.flush()
    db.add(CourseVersion(course_id=course.id, version_number=1))
    db.commit()
    return course


def _codes(errors) -> set[str]:
    return {e.code for e in errors}


def test_complete_course_has_no_errors(db_session):
    course = _make_course(db_session)
    problem = ProblemRevision(task_id=1, revision_number=1, title="T")
    db_session.add(problem)
    db_session.commit()

    create_item(db_session, course.id, LearningItemCreate(type="task", title="Задача", problem_revision_id=problem.id))
    create_item(db_session, course.id, LearningItemCreate(
        type="oge_task", title="ОГЭ", content="Условие задачи", oge_answer="12", position=1,
    ))
    create_item(db_session, course.id, LearningItemCreate(
        type="quiz", title="Тест", quiz_questions=[QuizQuestion(text="?", options=[])], position=2,
    ))
    create_item(db_session, course.id, LearningItemCreate(
        type="snap_task", title="Snap", steps=[SnapStep(title="Шаг 1")], position=3,
    ))

    assert validate_course_before_publish(db_session, course.id) == []


def test_oge_task_without_content_or_answer_is_reported(db_session):
    course = _make_course(db_session)
    item = create_item(db_session, course.id, LearningItemCreate(type="oge_task", title="ОГЭ", oge_answer="12"))
    # content изначально пуст (не передавали) — проверяем именно это,
    # answer намеренно затираем напрямую в базе (через API это не создать
    # с пустым ответом — see create_item's 422 для пустого oge_answer).
    item.oge_answer = {"answer": ""}
    db_session.commit()

    errors = validate_course_before_publish(db_session, course.id)
    assert "OGE_CONTENT_REQUIRED" in _codes(errors)
    assert "OGE_ANSWER_REQUIRED" in _codes(errors)


def test_task_without_problem_revision_is_reported(db_session):
    course = _make_course(db_session)
    problem = ProblemRevision(task_id=1, revision_number=1, title="T")
    db_session.add(problem)
    db_session.commit()
    item = create_item(db_session, course.id, LearningItemCreate(type="task", title="Задача", problem_revision_id=problem.id))
    # Руками обрываем связь — обычный API этого не допускает, но дефект
    # данных (например, от ручной миграции) должен попасть в отчёт.
    item.problem_revision_id = None
    db_session.commit()

    errors = validate_course_before_publish(db_session, course.id)
    assert "TASK_PROBLEM_REQUIRED" in _codes(errors)


def test_quiz_without_questions_is_reported(db_session):
    course = _make_course(db_session)
    item = create_item(db_session, course.id, LearningItemCreate(
        type="quiz", title="Тест", quiz_questions=[QuizQuestion(text="?", options=[])],
    ))
    item.quiz_questions = []
    db_session.commit()

    errors = validate_course_before_publish(db_session, course.id)
    assert "QUIZ_QUESTIONS_REQUIRED" in _codes(errors)


def test_snap_task_without_steps_is_reported(db_session):
    course = _make_course(db_session)
    item = create_item(db_session, course.id, LearningItemCreate(type="snap_task", title="Snap", steps=[SnapStep(title="Шаг 1")]))
    item.steps = []
    db_session.commit()

    errors = validate_course_before_publish(db_session, course.id)
    assert "STEPS_REQUIRED" in _codes(errors)


def test_archived_required_item_is_reported(db_session):
    course = _make_course(db_session)
    item = create_item(db_session, course.id, LearningItemCreate(
        type="oge_task", title="ОГЭ", content="Условие", oge_answer="12", is_required=True,
    ))
    set_item_archived(db_session, item.id, True)

    errors = validate_course_before_publish(db_session, course.id)
    assert "ARCHIVED_REQUIRED_ITEM" in _codes(errors)


def test_duplicate_position_among_siblings_is_reported(db_session):
    course = _make_course(db_session)
    create_item(db_session, course.id, LearningItemCreate(type="module", title="M1", position=0))
    create_item(db_session, course.id, LearningItemCreate(type="module", title="M2", position=0))

    errors = validate_course_before_publish(db_session, course.id)
    assert "DUPLICATE_POSITION" in _codes(errors)
    assert sum(1 for e in errors if e.code == "DUPLICATE_POSITION") == 2


def test_normalize_draft_positions_repairs_duplicate_sibling_positions(db_session):
    course = _make_course(db_session)
    first = create_item(db_session, course.id, LearningItemCreate(type="module", title="M1", position=22))
    second = create_item(db_session, course.id, LearningItemCreate(type="module", title="M2", position=22))

    changed = normalize_draft_positions(db_session, course.id)
    db_session.refresh(first)
    db_session.refresh(second)

    assert changed == 2
    assert [first.position, second.position] == [0, 1]
    assert "DUPLICATE_POSITION" not in _codes(validate_course_before_publish(db_session, course.id))


def test_unlock_rule_pointing_to_missing_item_is_reported(db_session):
    course = _make_course(db_session)
    item = create_item(db_session, course.id, LearningItemCreate(
        type="theory", title="Теория", unlock_rules={"after_item_id": 999999},
    ))
    errors = validate_course_before_publish(db_session, course.id)
    matching = [e for e in errors if e.code == "UNLOCK_RULE_INVALID"]
    assert len(matching) == 1
    assert matching[0].item_id == item.id


def test_broken_parent_reference_is_reported(db_session):
    course = _make_course(db_session)
    item = create_item(db_session, course.id, LearningItemCreate(type="module", title="M1"))
    # Обычный API не даёт сослаться на несуществующего родителя —
    # имитируем порчу данных прямой записью в базу.
    item.parent_id = 999999
    db_session.commit()

    errors = validate_course_before_publish(db_session, course.id)
    assert "BROKEN_PARENT_REFERENCE" in _codes(errors)


def test_cycle_in_tree_is_reported(db_session):
    course = _make_course(db_session)
    module = create_item(db_session, course.id, LearningItemCreate(type="module", title="M1"))
    submodule = create_item(db_session, course.id, LearningItemCreate(type="submodule", title="S1", parent_id=module.id))
    # Замыкаем цикл напрямую в базе — update_item это запрещает
    # (_collect_descendant_ids), значит через нормальный API такого не
    # добиться; дефектные данные всё равно должны быть пойманы валидатором.
    db_session.query(LearningItem).filter(LearningItem.id == module.id).update({"parent_id": submodule.id})
    db_session.commit()

    errors = validate_course_before_publish(db_session, course.id)
    assert "CYCLE_DETECTED" in _codes(errors)


def test_publish_endpoint_blocked_when_course_has_validation_errors(client, db_session):
    """Публикация запрещена при наличии ошибок (ТЗ Этап 4) — но только для
    явного POST .../publish, не для авто-republish после отдельных правок
    (см. комментарий в app/services/course_validator.py)."""
    methodist = make_user(db_session, "methodist")
    as_user(client, methodist)
    course = client.post("/api/courses", json={"title": "Курс с незаконченным заданием"}).json()

    item = client.post(f"/api/courses/{course['id']}/items", json={
        "type": "oge_task", "title": "ОГЭ", "oge_answer": "12",
    }).json()

    validation = client.get(f"/api/courses/{course['id']}/validation").json()
    assert validation["valid"] is False
    assert any(e["code"] == "OGE_CONTENT_REQUIRED" for e in validation["errors"])

    resp = client.post(f"/api/courses/{course['id']}/publish")
    assert resp.status_code == 422
    assert resp.json()["detail"]["valid"] is False

    # Чиним — публикация должна пройти.
    client.put(f"/api/courses/items/{item['id']}", json={"content": "Условие задачи"})
    validation = client.get(f"/api/courses/{course['id']}/validation").json()
    assert validation["valid"] is True
    assert client.post(f"/api/courses/{course['id']}/publish").status_code == 200
