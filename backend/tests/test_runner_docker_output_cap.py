"""JDG-002: вывод решения обрезается по ходу чтения потока, а не после того,
как subprocess соберёт всё в память — иначе решение, печатающее гигабайты,
успело бы исчерпать память процесса Judge до обрезки."""
from unittest.mock import patch

from app.services import runner_docker
from app.services.runner_docker import OUTPUT_DISPLAY_LIMIT, OUTPUT_KILL_THRESHOLD, run_python_sandboxed


class _FakeStream:
    def __init__(self, data: str):
        self._data = data
        self._pos = 0

    def read(self, n: int) -> str:
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


class _FakeStdin:
    def write(self, s):
        pass

    def close(self):
        pass


class _FakeProc:
    """poll() всегда None ("ещё выполняется") — так main-поток обязательно
    доходит до проверки `exceeded`/дедлайна на каждой итерации опроса, как
    и было бы с реальным зависшим контейнером."""

    def __init__(self, stdout_data: str, stderr_data: str = ""):
        self.stdout = _FakeStream(stdout_data)
        self.stderr = _FakeStream(stderr_data)
        self.stdin = _FakeStdin()

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0


def test_normal_output_returned_untouched():
    small = "hello\n"
    # poll() у фейка всегда None ("ещё выполняется"), поэтому единственный способ
    # выйти из цикла опроса — по дедлайну; подменяем monotonic() так, чтобы он
    # истёк сразу на первой проверке, а не ждать реальные секунды в тесте.
    with patch.object(runner_docker.subprocess, "Popen", return_value=_FakeProc(small)), \
         patch.object(runner_docker.subprocess, "run") as mock_run, \
         patch.object(runner_docker, "_POLL_INTERVAL_SECONDS", 0), \
         patch.object(runner_docker.time, "monotonic", side_effect=[0, 100, 100, 100, 100]):
        result = run_python_sandboxed("print('hello')", "", time_limit_ms=1)

    assert result.stdout == small
    assert result.timed_out is True  # дедлайн истёк по времени, а не по объёму — это ожидаемо для этого фейка
    mock_run.assert_called_once()  # docker kill вызван, раз пришлось выйти по дедлайну


def test_output_far_beyond_display_limit_is_capped_and_kills_early():
    huge = "x" * (OUTPUT_KILL_THRESHOLD + 1_000)
    with patch.object(runner_docker.subprocess, "Popen", return_value=_FakeProc(huge)), \
         patch.object(runner_docker.subprocess, "run") as mock_run:
        result = run_python_sandboxed("while True: print('x' * 100_000)", "")

    assert len(result.stdout) == OUTPUT_DISPLAY_LIMIT
    assert result.stdout == "x" * OUTPUT_DISPLAY_LIMIT
    # обрублен из-за объёма вывода, а не из-за обычного тайм-лимита задачи
    assert result.timed_out is False
    mock_run.assert_called_once()
    kill_args = mock_run.call_args[0][0]
    assert kill_args[:2] == ["docker", "kill"]
