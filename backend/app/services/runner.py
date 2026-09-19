"""ВНИМАНИЕ: это НЕ изолированная среда исполнения (JDG-002, JDG-003, SEC-004).
Код ученика выполняется локальным subprocess с таймаутом — годится только для
разработки на своей машине. Перед продакшеном нужно заменить на настоящий
Runner без доступа к БД, секретам и сети (Docker/gVisor/Firecracker), см. README.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from app.schemas import RunResult


def run_python(code: str, stdin: str, time_limit_ms: int = 2000) -> RunResult:
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
