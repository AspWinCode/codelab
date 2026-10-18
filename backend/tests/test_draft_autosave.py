"""IDE-002: автосохранение кода задачи без прогона/отправки.

Регресс: раньше Draft сохранялся ТОЛЬКО как побочный эффект POST
/submissions/run — если ученик печатал код и уходил со страницы, ни разу не
нажав "Запустить"/"Отправить", набранный код нигде не сохранялся и терялся
при следующем открытии задачи (app/routers/submissions.py не имел отдельного
эндпоинта для черновика)."""
from app.config import settings
from app.models import Draft, ProblemRevision, User
from tests.conftest import as_user, make_user


def _make_problem(db) -> ProblemRevision:
    problem = ProblemRevision(task_id=1, revision_number=1, title="Задача", template_code="pass\n")
    db.add(problem)
    db.commit()
    db.refresh(problem)
    return problem


def test_save_draft_endpoint_persists_without_run_or_submit(client, db_session):
    problem = _make_problem(db_session)
    student = make_user(db_session, "student", "lp-student-draft-1")
    as_user(client, student)

    resp = client.put("/api/submissions/draft", json={
        "problem_revision_id": problem.id, "code": "x = 1\nprint(x)\n",
    })
    assert resp.status_code == 200
    assert "updated_at" in resp.json()

    fetched = client.get(f"/api/courses/problems/{problem.id}").json()
    assert fetched["draft_code"] == "x = 1\nprint(x)\n"
    assert fetched["draft_updated_at"] is not None


def test_save_draft_overwrites_previous_draft_for_same_problem(client, db_session):
    problem = _make_problem(db_session)
    student = make_user(db_session, "student", "lp-student-draft-2")
    as_user(client, student)

    client.put("/api/submissions/draft", json={"problem_revision_id": problem.id, "code": "first"})
    client.put("/api/submissions/draft", json={"problem_revision_id": problem.id, "code": "second"})

    fetched = client.get(f"/api/courses/problems/{problem.id}").json()
    assert fetched["draft_code"] == "second"


def test_drafts_are_isolated_per_user_and_per_problem(client, db_session):
    problem_a = _make_problem(db_session)
    problem_b = _make_problem(db_session)
    alice = make_user(db_session, "student", "lp-alice")
    bob = make_user(db_session, "student", "lp-bob")

    as_user(client, alice)
    client.put("/api/submissions/draft", json={"problem_revision_id": problem_a.id, "code": "alice-a"})
    client.put("/api/submissions/draft", json={"problem_revision_id": problem_b.id, "code": "alice-b"})

    as_user(client, bob)
    client.put("/api/submissions/draft", json={"problem_revision_id": problem_a.id, "code": "bob-a"})

    as_user(client, alice)
    assert client.get(f"/api/courses/problems/{problem_a.id}").json()["draft_code"] == "alice-a"
    assert client.get(f"/api/courses/problems/{problem_b.id}").json()["draft_code"] == "alice-b"

    as_user(client, bob)
    assert client.get(f"/api/courses/problems/{problem_a.id}").json()["draft_code"] == "bob-a"


def test_problem_without_draft_has_no_draft_code_or_timestamp(client, db_session):
    """Без черновика фронт обязан подставлять template_code — а не путать
    "черновика нет" с "черновик — пустая строка"."""
    problem = _make_problem(db_session)
    student = make_user(db_session, "student", "lp-student-draft-3")
    as_user(client, student)

    fetched = client.get(f"/api/courses/problems/{problem.id}").json()
    assert fetched["draft_code"] is None
    assert fetched["draft_updated_at"] is None
    assert fetched["template_code"] == "pass\n"


def test_run_still_saves_draft_as_before(client, db_session, monkeypatch):
    """Регресс-защита: явный эндпоинт черновика не должен был сломать
    прежнее поведение — "Запустить" по-прежнему сохраняет код.

    Проверяем черновик прямым запросом к БД, а не вторым HTTP-вызовом:
    run_code намеренно закрывает свою сессию БД до прогона докера (фикс
    инцидента с исчерпанием пула 13.10.2026) — в проде это отдельная сессия
    на запрос и второй вызов никак не пострадал бы, но тестовый client
    переиспользует один db_session на все запросы теста, так что второй
    HTTP-запрос столкнулся бы с уже отвязанным объектом User, не с багом
    самого продакшен-кода."""
    monkeypatch.setattr(settings, "runner_backend", "subprocess")
    problem = _make_problem(db_session)
    problem_id = problem.id
    student = make_user(db_session, "student", "lp-student-draft-4")
    student_id = student.id  # captured before run_code's db.close() detaches `student`
    as_user(client, student)

    resp = client.post("/api/submissions/run", json={
        "problem_revision_id": problem_id, "code": "print('hi')\n", "stdin": "",
    })
    assert resp.status_code == 200

    draft = (
        db_session.query(Draft)
        .filter(Draft.user_id == student_id, Draft.problem_revision_id == problem_id)
        .first()
    )
    assert draft is not None
    assert draft.code == "print('hi')\n"
