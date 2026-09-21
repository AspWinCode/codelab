"""ADM-001/002/003: реестр окружений исполнения — явный, неизменяемый на
уровне кода список того, что реально можно запустить, а не "что уж
установлено в образе". ТЗ оставляет открытым вопрос Q-05 (какой именно
набор согласует заказчик) — здесь пять окружений, явно запрошенных
владельцем продукта 2026-09-21 (Python, Python+pandas/numpy, C++, SQL,
Arcade), а не всё, что теоретически можно поддержать.

Каждая запись — отдельный Docker-образ (ADM-002: версии интерпретатора и
разрешённых библиотек фиксируются пересборкой образа с новым тегом, старое
окружение не трогается) и команда запуска внутри контейнера (см.
app/services/runner_docker.py, который читает эту команду, а не решает
сам, как компилировать/запускать конкретный язык).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Environment:
    id: str
    label: str
    docker_image: str
    file_name: str  # имя файла с решением внутри /sandbox
    container_cmd: list[str]  # полная команда запуска (компиляция+запуск — одной командой, см. cpp17)
    allowed_libraries: list[str] = field(default_factory=list)
    # cpp17: скомпилированный бинарник нужно куда-то записать и оттуда же
    # исполнить — снимаем noexec с /tmp только для него (см. runner_docker.py);
    # для интерпретируемых языков noexec остаётся, лишний путь исполнения не нужен.
    tmp_exec: bool = False
    # beta — best-effort: авто-проверка не гарантирует корректность результата
    # (см. arcade — GUI-программу нельзя проверить сравнением stdout/stdout).
    status: str = "ready"
    status_note: str = ""


ENVIRONMENTS: dict[str, Environment] = {
    "python3": Environment(
        id="python3",
        label="Python 3.12",
        docker_image="codelab-runner:python3.12",
        file_name="solution.py",
        container_cmd=["python3", "/sandbox/solution.py"],
    ),
    "python3-data": Environment(
        id="python3-data",
        label="Python 3.12 + pandas/numpy",
        docker_image="codelab-runner:python3.12-data",
        file_name="solution.py",
        container_cmd=["python3", "/sandbox/solution.py"],
        allowed_libraries=["pandas", "numpy"],
    ),
    "cpp17": Environment(
        id="cpp17",
        label="C++17 (g++)",
        docker_image="codelab-runner:cpp17",
        file_name="solution.cpp",
        container_cmd=["sh", "-c", "g++ -O2 -std=c++17 -o /tmp/solution /sandbox/solution.cpp && /tmp/solution"],
        tmp_exec=True,
    ),
    "sql-sqlite": Environment(
        id="sql-sqlite",
        label="SQL (SQLite)",
        docker_image="codelab-runner:sql-sqlite",
        file_name="solution.sql",
        # Данные (схема+seed) методист задаёт в ProblemRevision.sql_fixture —
        # runner.py собирает из них db.sqlite3 и монтирует рядом (ADM-003).
        container_cmd=["sh", "-c", "sqlite3 -header -csv /sandbox/db.sqlite3 < /sandbox/solution.sql"],
    ),
    "arcade": Environment(
        id="arcade",
        label="Python 3.12 + Arcade",
        docker_image="codelab-runner:arcade",
        file_name="solution.py",
        # xvfb-run поднимает виртуальный X-дисплей — без него библиотеке
        # arcade (OpenGL-окно) негде рисовать даже для однократного запуска.
        container_cmd=["sh", "-c", "xvfb-run -a python3 /sandbox/solution.py"],
        allowed_libraries=["arcade"],
        status="beta",
        status_note=(
            "Автопроверка сравнением stdout по факту — это дымовой тест "
            "(программа запустилась и не упала), а не проверка визуального "
            "результата игры: у Judge нет возможности сравнить кадр на "
            "OpenGL-холсте с эталоном. Для содержательной проверки таких "
            "задач нужна либо ручная проверка (GRD-004), либо задача должна "
            "печатать проверяемое состояние в stdout сама."
        ),
    ),
}


def get_environment(environment_id: str) -> Environment:
    try:
        return ENVIRONMENTS[environment_id]
    except KeyError:
        raise ValueError(f"Неизвестное окружение исполнения: {environment_id!r}")


def list_environments() -> list[Environment]:
    return list(ENVIRONMENTS.values())
