"""Изолированный Runner на Docker — JDG-002, JDG-003, SEC-004.

Каждый прогон — одноразовый контейнер:
- без сети (JDG-003: доступ в интернет из Runner запрещён по умолчанию);
- read-only корневая ФС + ограниченный по размеру tmpfs без exec, кроме
  окружений, которым для запуска нужно писать и исполнять файл (сейчас —
  только cpp17, где скомпилированный бинарник больше негде разместить,
  см. Environment.tmp_exec в app/services/environments.py);
- лимиты CPU, RAM (без свопа сверх лимита) и числа процессов — защита от
  fork-бомб и чрезмерного потребления ресурсов (JDG-002);
- без Linux capabilities и без privilege escalation (SEC-004);
- от непривилегированного пользователя (uid/gid 65534, "nobody");
- без доступа к БД, секретам и метаданным облака — контейнер вообще не
  видит переменные окружения и файлы хост-процесса, кроме примонтированных
  read-only файлов решения (и, для SQL-окружения, файла базы-фикстуры).

Уничтожается сразу после завершения через --rm; при таймауте контейнер
принудительно убивается по имени (JDG-011) — не полагаемся на завершение
дочернего процесса `docker run` со стороны хоста, это не останавливает сам
контейнер.

Какой образ и какая команда запускается — определяет реестр окружений
(ADM-001/002/003, app/services/environments.py), не этот модуль: здесь
только универсальный механизм изоляции и обрезки вывода, общий для всех
языков.

Требует установленный Docker (Engine/Desktop) на узле, где работает Judge,
и собранные образы окружений (см. backend/sandbox/*/Dockerfile).
"""
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from app.config import settings
from app.schemas import RunResult
from app.services.environments import Environment, get_environment

# Запас поверх лимита задачи на старт/остановку контейнера — не часть
# лимита времени самого решения, только защита от зависшего docker run.
STARTUP_GRACE_SECONDS = 5

# Ровно то, что показываем ученику/преподавателю.
OUTPUT_DISPLAY_LIMIT = 20_000
# JDG-002: решение пишет в stdout/stderr без ограничения по памяти самого
# контейнера (лимит --memory ограничивает контейнер, а не размер данных,
# которые он успевает вытолкнуть в pipe) — если раньше собирать весь вывод
# subprocess.run(capture_output=True) и обрезать уже потом, решение,
# печатающее гигабайты в цикле, успеет исчерпать память самого процесса
# Judge на хосте до этой обрезки. Поэтому читаем поток чанками и обрезаем
# по ходу чтения; если поток продолжает расти намного дальше того, что
# вообще может понадобиться показать, обрубаем прогон досрочно, не дожидаясь
# истечения обычного тайм-лимита задачи.
OUTPUT_KILL_THRESHOLD = 200_000
_READ_CHUNK_SIZE = 65_536
_POLL_INTERVAL_SECONDS = 0.05


def _build_docker_args(
    container_name: str,
    environment: Environment,
    host_code_path: str,
    memory_limit_mb: int,
    extra_mounts: list[tuple[str, str]] | None = None,
) -> list[str]:
    tmpfs_opts = "rw,size=64m,nosuid" + ("" if environment.tmp_exec else ",noexec")
    args = [
        "docker", "run",
        "--rm",
        "--name", container_name,
        "--network", "none",
        "--read-only",
        "--tmpfs", f"/tmp:{tmpfs_opts}",
        "--memory", f"{memory_limit_mb}m",
        "--memory-swap", f"{memory_limit_mb}m",
        "--cpus", str(settings.runner_cpus),
        "--pids-limit", str(settings.runner_pids_limit),
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "65534:65534",
        "-i",
        "-v", f"{host_code_path}:/sandbox/{environment.file_name}:ro",
    ]
    for host_path, container_path in extra_mounts or []:
        args += ["-v", f"{host_path}:{container_path}:ro"]
    args += [environment.docker_image, *environment.container_cmd]
    return args


def _read_capped(stream, cap: int, kill_threshold: int, exceeded: threading.Event, result: dict, key: str) -> None:
    """Читает поток чанками, храня в памяти не больше `cap` символов, но
    продолжая вычитывать (и отбрасывать) всё остальное — иначе процесс с
    полным pipe-буфером зависнет на записи (deadlock), а не завершится."""
    kept = []
    kept_len = 0
    total = 0
    while True:
        chunk = stream.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if kept_len < cap:
            take = chunk[: cap - kept_len]
            kept.append(take)
            kept_len += len(take)
        if total >= kill_threshold:
            exceeded.set()
    result[key] = "".join(kept)


def run_sandboxed(
    environment_id: str,
    code: str,
    stdin: str,
    time_limit_ms: int = 2000,
    memory_limit_mb: int = 256,
    extra_files: dict[str, bytes] | None = None,
) -> RunResult:
    """extra_files: {путь_в_контейнере: содержимое} — например, файл базы
    для sql-sqlite (ADM-003, собирается в app/services/runner.py из
    ProblemRevision.sql_fixture); монтируется read-only рядом с решением."""
    environment = get_environment(environment_id)
    container_name = f"codelab-run-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory() as tmp:
        code_path = Path(tmp) / environment.file_name
        code_path.write_text(code, encoding="utf-8")

        extra_mounts: list[tuple[str, str]] = []
        for container_path, data in (extra_files or {}).items():
            host_path = Path(tmp) / Path(container_path).name
            host_path.write_bytes(data)
            extra_mounts.append((str(host_path), container_path))

        args = _build_docker_args(container_name, environment, str(code_path), memory_limit_mb, extra_mounts)

        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Docker не найден на этом узле. RUNNER_BACKEND=docker требует установленный "
                "Docker Engine/Desktop — либо поставьте Docker, либо (только для локальной "
                "разработки без чужого кода) переключитесь на RUNNER_BACKEND=subprocess."
            )

        try:
            proc.stdin.write(stdin)
            proc.stdin.close()
        except BrokenPipeError:
            pass  # решение не читает stdin (или уже упало) — не наша проблема здесь

        exceeded = threading.Event()
        result: dict = {}
        readers = [
            threading.Thread(target=_read_capped, args=(proc.stdout, OUTPUT_DISPLAY_LIMIT, OUTPUT_KILL_THRESHOLD, exceeded, result, "stdout")),
            threading.Thread(target=_read_capped, args=(proc.stderr, OUTPUT_DISPLAY_LIMIT, OUTPUT_KILL_THRESHOLD, exceeded, result, "stderr")),
        ]
        for t in readers:
            t.start()

        deadline = time.monotonic() + (time_limit_ms / 1000) + STARTUP_GRACE_SECONDS
        timed_out = False
        while proc.poll() is None:
            if exceeded.is_set() or time.monotonic() >= deadline:
                timed_out = not exceeded.is_set()
                # `docker run` (клиент) продолжит жить, если не остановить контейнер
                # явно по имени (JDG-011) — убийство самого клиентского процесса не
                # останавливает контейнер.
                subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=10)
                break
            time.sleep(_POLL_INTERVAL_SECONDS)

        for t in readers:
            t.join(timeout=10)
        proc.wait(timeout=10)

        return RunResult(stdout=result.get("stdout", ""), stderr=result.get("stderr", ""), timed_out=timed_out)
