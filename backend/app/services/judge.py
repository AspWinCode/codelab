"""JDG-004, JDG-005: минимальный Checker (точное сравнение / без пробелов по краям)
и сведение результата по группам тестов (JDG-008 — упрощённо, без весов групп)."""
from app.models import ProblemRevision, Verdict
from app.schemas import RunResult
from app.services.runner import run_for_problem


def _compare(expected: str, actual: str, checker: str) -> bool:
    if checker == "trimmed":
        return expected.strip() == actual.strip()
    if checker == "exact":
        return expected == actual
    # numeric/custom — TODO: сравнение с погрешностью (JDG-007), custom Checker.
    return expected.strip() == actual.strip()


def judge_submission(problem: ProblemRevision, code: str) -> tuple[Verdict, float, str, str]:
    """Возвращает (verdict, score 0..100, stdout последнего теста, stderr)."""
    tests = problem.tests or []
    if not tests:
        return Verdict.INTERNAL_ERROR, 0.0, "", "У задачи нет тестов"

    passed = 0
    last_stdout, last_stderr = "", ""
    for test in tests:
        result: RunResult = run_for_problem(problem, code, test.get("input", ""))
        last_stdout, last_stderr = result.stdout, result.stderr
        if result.timed_out:
            return Verdict.TIME_LIMIT_EXCEEDED, round(100 * passed / len(tests), 2), last_stdout, last_stderr
        if result.stderr:
            return Verdict.RUNTIME_ERROR, round(100 * passed / len(tests), 2), last_stdout, last_stderr
        if _compare(test.get("expected", ""), result.stdout, problem.checker):
            passed += 1

    score = round(100 * passed / len(tests), 2)
    verdict = Verdict.ACCEPTED if passed == len(tests) else Verdict.WRONG_ANSWER
    return verdict, score, last_stdout, last_stderr
