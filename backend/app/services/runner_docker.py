"""Изолированный Runner на Docker — JDG-002, JDG-003, SEC-004.

Каждый прогон — одноразовый контейнер:
- без сети (JDG-003: доступ в интернет из Runner запрещён по умолчанию);
- read-only корневая ФС + ограниченный по размеру tmpfs без exec (нет
  доступа на запись за пределы /tmp, нельзя исполнять файлы из /tmp);
- лимиты CPU, RAM (без свопа сверх лимита) и числа процессов — защита от
  fork-бомб и чрезмерного потребления ресурсов (JDG-002);
- без Linux capabilities и без privilege escalation (SEC-004);
- от непривилегированного пользователя (uid/gid 65534, "nobody");
- без доступа к БД, секретам и метаданным облака — контейнер вообще не
  видит переменные окружения и файлы хост-процесса, кроме примонтированного
  read-only файла с решением.

Уничтожается сразу после завершения через --rm; при таймауте контейнер
принудительно убивается по имени (JDG-011) — не полагаемся на завершение
дочернего процесса `docker run` со стороны хоста, это не останавливает сам
контейнер.

Требует установленный Docker (Engine/Desktop) на узле, где работает Judge,
и собранный образ `codelab-runner:python3.12` (см. sandbox/Dockerfile).
"""
import subprocess
import tempfile
import uuid
from pathlib import Path

from app.config import settings
from app.schemas import RunResult

CONTAINER_CODE_PATH = "/sandbox/solution.py"
# Запас поверх лимита задачи на старт/остановку контейнера — не часть
# лимита времени самого решения, только защита от зависшего docker run.
STARTUP_GRACE_SECONDS = 5


def _build_docker_args(container_name: str, host_code_path: str, memory_limit_mb: int) -> list[str]:
    return [
        "docker", "run",
        "--rm",
        "--name", container_name,
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=64m,noexec,nosuid",
        "--memory", f"{memory_limit_mb}m",
        "--memory-swap", f"{memory_limit_mb}m",
        "--cpus", str(settings.runner_cpus),
        "--pids-limit", str(settings.runner_pids_limit),
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "65534:65534",
        "-i",
        "-v", f"{host_code_path}:{CONTAINER_CODE_PATH}:ro",
        settings.runner_docker_image,
        "python3", CONTAINER_CODE_PATH,
    ]


def run_python_sandboxed(code: str, stdin: str, time_limit_ms: int = 2000, memory_limit_mb: int = 256) -> RunResult:
    container_name = f"codelab-run-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory() as tmp:
        code_path = Path(tmp) / "solution.py"
        code_path.write_text(code, encoding="utf-8")
        args = _build_docker_args(container_name, str(code_path), memory_limit_mb)

        try:
            proc = subprocess.run(
                args,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=(time_limit_ms / 1000) + STARTUP_GRACE_SECONDS,
            )
            return RunResult(stdout=proc.stdout[:20_000], stderr=proc.stderr[:20_000], timed_out=False)
        except subprocess.TimeoutExpired as e:
            # `docker run` (клиент) убит по таймауту — сам контейнер продолжит жить,
            # если не остановить его явно по имени (JDG-011).
            subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=10)
            return RunResult(stdout=(e.stdout or "")[:20_000], stderr=(e.stderr or "")[:20_000], timed_out=True)
        except FileNotFoundError:
            raise RuntimeError(
                "Docker не найден на этом узле. RUNNER_BACKEND=docker требует установленный "
                "Docker Engine/Desktop — либо поставьте Docker, либо (только для локальной "
                "разработки без чужого кода) переключитесь на RUNNER_BACKEND=subprocess."
            )
