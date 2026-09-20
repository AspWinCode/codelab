"""Точка входа для исполнения кода ученика — выбирает Runner по настройке
RUNNER_BACKEND. По умолчанию "docker" (изолированный, единственный вариант
для чужого кода — JDG-002/003, SEC-004); "subprocess" — только для локальной
разработки на машине без Docker, см. runner_subprocess.py."""
from app.config import settings
from app.schemas import RunResult


def run_python(code: str, stdin: str, time_limit_ms: int = 2000, memory_limit_mb: int = 256) -> RunResult:
    if settings.runner_backend == "subprocess":
        from app.services.runner_subprocess import run_python as _run_subprocess

        return _run_subprocess(code, stdin, time_limit_ms)

    from app.services.runner_docker import run_python_sandboxed

    return run_python_sandboxed(code, stdin, time_limit_ms, memory_limit_mb)
