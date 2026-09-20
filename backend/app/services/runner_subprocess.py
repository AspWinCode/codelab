"""ВНИМАНИЕ: это НЕ изолированная среда исполнения (JDG-002, JDG-003, SEC-004).
Код ученика выполняется локальным subprocess с полным доступом к хосту —
без сети, диска и процессов не ограничивает. Используется только когда
RUNNER_BACKEND=subprocess (по умолчанию — docker, см. runner_docker.py и
runner.py). Годится исключительно для разработки на машине без Docker;
никогда не включайте это в проде — недоверенный код получит доступ к
файловой системе, окружению процесса и (потенциально) сети хоста.
"""
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from app.schemas import RunResult

logger = logging.getLogger(__name__)


def run_python(code: str, stdin: str, time_limit_ms: int = 2000) -> RunResult:
    logger.warning(
        "RUNNER_BACKEND=subprocess: код исполняется БЕЗ изоляции (SEC-004 нарушен). "
        "Допустимо только для локальной разработки без Docker."
    )
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "solution.py"
        script.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=time_limit_ms / 1000,
            )
            return RunResult(stdout=proc.stdout[:20_000], stderr=proc.stderr[:20_000], timed_out=False)
        except subprocess.TimeoutExpired as e:
            return RunResult(stdout=(e.stdout or "")[:20_000], stderr=(e.stderr or "")[:20_000], timed_out=True)
