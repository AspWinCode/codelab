"""ADM-001/002/003: диспетчер запуска по окружению (app/services/runner.py) —
RUNNER_BACKEND=subprocess годится только для Python (нет компилятора/sqlite3/
Xvfb на голом хосте), sqlite-фикстура собирается из ProblemRevision.sql_fixture
доверенным кодом методиста, а не решением ученика."""
import sqlite3

import pytest

from app.config import settings
from app.models import ProblemRevision
from app.services.runner import build_sqlite_fixture, execute_code, extra_files_for_problem, run_for_problem


def test_subprocess_backend_runs_python3(monkeypatch):
    monkeypatch.setattr(settings, "runner_backend", "subprocess")
    result = execute_code("python3", "print(1 + 1)", "")
    assert result.stdout.strip() == "2"


def test_multiple_input_calls_read_separate_lines(monkeypatch):
    """Баг: кнопка "Запустить" падала с EOFError на второй/третьей строке
    input(), потому что stdin было негде взять вторую строку (однострочное
    поле на фронтенде, см. CoursePage.tsx) — здесь проверяем сам Runner:
    три строки stdin корректно уходят в три отдельных input()."""
    monkeypatch.setattr(settings, "runner_backend", "subprocess")
    code = "a = input()\nb = input()\nc = input()\nprint(int(a) + int(b) + int(c))"
    result = execute_code("python3", code, "2\n3\n4\n")
    assert result.stderr == ""
    assert result.stdout.strip() == "9"


def test_crlf_stdin_normalized_to_lf(monkeypatch):
    """stdin со вставленными Windows-переносами ("\\r\\n") не должен оставлять
    "\\r" в значении, прочитанном input() — иначе int("2\\r") падает/не
    совпадает с ожидаемым выводом теста, хотя для пользователя это та же
    строка "2"."""
    monkeypatch.setattr(settings, "runner_backend", "subprocess")
    code = "a = input()\nb = input()\nprint(repr(a), repr(b))"
    result = execute_code("python3", code, "2\r\n3\r\n")
    assert result.stderr == ""
    assert result.stdout.strip() == "'2' '3'"


def test_subprocess_backend_rejects_cpp(monkeypatch):
    monkeypatch.setattr(settings, "runner_backend", "subprocess")
    with pytest.raises(RuntimeError):
        execute_code("cpp17", "int main(){}", "")


def test_subprocess_backend_rejects_sql(monkeypatch):
    monkeypatch.setattr(settings, "runner_backend", "subprocess")
    with pytest.raises(RuntimeError):
        execute_code("sql-sqlite", "SELECT 1;", "")


def test_unknown_environment_raises():
    with pytest.raises(ValueError):
        execute_code("java21", "", "")


def test_build_sqlite_fixture_produces_working_db():
    data = build_sqlite_fixture("CREATE TABLE t (x INTEGER); INSERT INTO t VALUES (42);")
    conn = sqlite3.connect(":memory:")
    conn.deserialize(data)
    row = conn.execute("SELECT x FROM t").fetchone()
    assert row == (42,)


def test_extra_files_for_problem_only_for_sql_with_fixture():
    python_problem = ProblemRevision(task_id=1, revision_number=1, title="P", language="python3")
    assert extra_files_for_problem(python_problem) is None

    sql_no_fixture = ProblemRevision(task_id=1, revision_number=1, title="Q", language="sql-sqlite")
    assert extra_files_for_problem(sql_no_fixture) is None

    sql_with_fixture = ProblemRevision(
        task_id=1, revision_number=1, title="R", language="sql-sqlite",
        sql_fixture="CREATE TABLE t (x INTEGER);",
    )
    extra = extra_files_for_problem(sql_with_fixture)
    assert extra is not None and "/sandbox/db.sqlite3" in extra


def test_run_for_problem_uses_subprocess_for_python(monkeypatch):
    monkeypatch.setattr(settings, "runner_backend", "subprocess")
    problem = ProblemRevision(
        task_id=1, revision_number=1, title="P", language="python3",
        time_limit_ms=2000, memory_limit_mb=256,
    )
    result = run_for_problem(problem, "print('ok')", "")
    assert result.stdout.strip() == "ok"
