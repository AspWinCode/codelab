"""Точка входа для исполнения кода ученика — выбирает Runner по настройке
RUNNER_BACKEND и окружение по ADM-001/002/003 (см. app/services/environments.py).
По умолчанию RUNNER_BACKEND=docker (изолированный, единственный вариант для
чужого кода — JDG-002/003, SEC-004); "subprocess" — только для локальной
разработки на машине без Docker и только для Python (см. runner_subprocess.py) —
компилятор C++/sqlite3/Xvfb для остальных окружений там взять неоткуда."""
import sqlite3

from app.config import settings
from app.schemas import RunResult
from app.services.environments import get_environment

_SUBPROCESS_SUPPORTED_ENVIRONMENTS = {"python3", "python3-data"}


def execute_code(
    environment_id: str,
    code: str,
    stdin: str,
    time_limit_ms: int = 2000,
    memory_limit_mb: int = 256,
    extra_files: dict[str, bytes] | None = None,
) -> RunResult:
    environment = get_environment(environment_id)  # ValueError на неизвестном id — пусть вызывающий решает, как это отразить в вердикте

    if settings.runner_backend == "subprocess":
        if environment_id not in _SUBPROCESS_SUPPORTED_ENVIRONMENTS:
            raise RuntimeError(
                f"RUNNER_BACKEND=subprocess поддерживает только Python — окружению "
                f"'{environment.label}' нужен компилятор/интерпретатор, которого на "
                f"хосте вне контейнера может не быть. Переключитесь на RUNNER_BACKEND=docker."
            )
        from app.services.runner_subprocess import run_python as _run_subprocess

        return _run_subprocess(code, stdin, time_limit_ms)

    from app.services.runner_docker import run_sandboxed

    return run_sandboxed(environment_id, code, stdin, time_limit_ms, memory_limit_mb, extra_files)


def build_sqlite_fixture(fixture_sql: str) -> bytes:
    """ADM-003: методист описывает схему+seed для SQL-задачи один раз
    (ProblemRevision.sql_fixture), а не как отдельный файл на диске —
    свежая база собирается на лету перед каждым прогоном через встроенный
    sqlite3 (доверенный код методиста, не решение ученика) и монтируется
    в контейнер read-only рядом с решением."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(fixture_sql)
        return conn.serialize()
    finally:
        conn.close()


def extra_files_for_problem(problem) -> dict[str, bytes] | None:
    if problem.language == "sql-sqlite" and problem.sql_fixture:
        return {"/sandbox/db.sqlite3": build_sqlite_fixture(problem.sql_fixture)}
    return None


def run_for_problem(problem, code: str, stdin: str) -> RunResult:
    return execute_code(
        problem.language,
        code,
        stdin,
        problem.time_limit_ms,
        problem.memory_limit_mb,
        extra_files_for_problem(problem),
    )
