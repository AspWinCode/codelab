"""Фиксирует флаги изоляции контейнера (JDG-002/003, SEC-004) — если кто-то
случайно уберёт --network none или --cap-drop ALL при рефакторинге, тест упадёт."""
from app.services.runner_docker import _build_docker_args


def test_sandbox_flags_present():
    args = _build_docker_args("codelab-run-test", "/host/tmp/solution.py", 256)

    assert "--network" in args and args[args.index("--network") + 1] == "none"
    assert "--read-only" in args
    assert "--cap-drop" in args and args[args.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in args and args[args.index("--security-opt") + 1] == "no-new-privileges"
    assert "--user" in args and args[args.index("--user") + 1] == "65534:65534"
    assert "--pids-limit" in args
    assert "--memory" in args and args[args.index("--memory") + 1] == "256m"
    assert "--rm" in args
    assert "--name" in args and args[args.index("--name") + 1] == "codelab-run-test"


def test_code_mounted_read_only():
    args = _build_docker_args("codelab-run-test", "/host/tmp/solution.py", 256)
    mount_index = args.index("-v") + 1
    assert args[mount_index] == "/host/tmp/solution.py:/sandbox/solution.py:ro"
