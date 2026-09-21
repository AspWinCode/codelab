"""Фиксирует флаги изоляции контейнера (JDG-002/003, SEC-004) — если кто-то
случайно уберёт --network none или --cap-drop ALL при рефакторинге, тест упадёт."""
from app.services.environments import get_environment
from app.services.runner_docker import _build_docker_args

PYTHON3 = get_environment("python3")
CPP17 = get_environment("cpp17")


def test_sandbox_flags_present():
    args = _build_docker_args("codelab-run-test", PYTHON3, "/host/tmp/solution.py", 256)

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
    args = _build_docker_args("codelab-run-test", PYTHON3, "/host/tmp/solution.py", 256)
    mount_index = args.index("-v") + 1
    assert args[mount_index] == "/host/tmp/solution.py:/sandbox/solution.py:ro"


def test_python_tmpfs_stays_noexec():
    args = _build_docker_args("codelab-run-test", PYTHON3, "/host/tmp/solution.py", 256)
    tmpfs = args[args.index("--tmpfs") + 1]
    assert "noexec" in tmpfs


def test_cpp_tmpfs_drops_noexec_for_compiled_binary():
    """cpp17 — единственное окружение, которому нужно записать и исполнить
    скомпилированный бинарник (Environment.tmp_exec, ADM-001/002/003)."""
    args = _build_docker_args("codelab-run-test", CPP17, "/host/tmp/solution.cpp", 256)
    tmpfs = args[args.index("--tmpfs") + 1]
    assert "noexec" not in tmpfs


def test_extra_mounts_appended_read_only():
    args = _build_docker_args(
        "codelab-run-test", PYTHON3, "/host/tmp/solution.py", 256,
        extra_mounts=[("/host/tmp/db.sqlite3", "/sandbox/db.sqlite3")],
    )
    assert "/host/tmp/db.sqlite3:/sandbox/db.sqlite3:ro" in args


def test_container_cmd_appended_after_image():
    args = _build_docker_args("codelab-run-test", CPP17, "/host/tmp/solution.cpp", 256)
    assert args[-len(CPP17.container_cmd):] == CPP17.container_cmd
    assert args[-len(CPP17.container_cmd) - 1] == CPP17.docker_image
