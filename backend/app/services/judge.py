"""JDG-004, JDG-005: минимальный Checker (точное сравнение / без пробелов по краям)
и сведение результата по группам тестов (JDG-008 — упрощённо, без весов групп)."""
from dataclasses import dataclass

from app.models import ProblemRevision, Verdict
from app.schemas import RunResult
from app.services.error_explain import explain_stderr_ru, explain_timeout_ru
from app.services.runner import run_for_problem


def _compare(expected: str, actual: str, checker: str) -> bool:
    if checker == "trimmed":
        return expected.strip() == actual.strip()
    if checker == "exact":
        return expected == actual
    # numeric/custom — TODO: сравнение с погрешностью (JDG-007), custom Checker.
    return expected.strip() == actual.strip()


@dataclass
class JudgeResult:
    verdict: Verdict
    score: float
    stdout: str
    stderr: str
    # Актуальный/требуемый вывод — оба с ОДНОГО И ТОГО ЖЕ первого
    # несовпавшего теста (см. комментарий у Submission.actual_output),
    # None при ACCEPTED.
    actual_output: str | None
    expected_output: str | None
    error_explanation: str | None


def judge_submission(problem: ProblemRevision, code: str) -> JudgeResult:
    tests = problem.tests or []
    if not tests:
        return JudgeResult(Verdict.INTERNAL_ERROR, 0.0, "", "У задачи нет тестов", None, None, None)

    passed = 0
    last_stdout, last_stderr = "", ""
    first_failure_actual: str | None = None
    first_failure_expected: str | None = None
    for test in tests:
        result: RunResult = run_for_problem(problem, code, test.get("input", ""))
        last_stdout, last_stderr = result.stdout, result.stderr
        if result.timed_out:
            if first_failure_expected is None:
                first_failure_actual, first_failure_expected = result.stdout, test.get("expected", "")
            return JudgeResult(
                Verdict.TIME_LIMIT_EXCEEDED, round(100 * passed / len(tests), 2), last_stdout, last_stderr,
                first_failure_actual, first_failure_expected, explain_timeout_ru(),
            )
        if result.stderr:
            if first_failure_expected is None:
                first_failure_actual, first_failure_expected = result.stdout, test.get("expected", "")
            return JudgeResult(
                Verdict.RUNTIME_ERROR, round(100 * passed / len(tests), 2), last_stdout, last_stderr,
                first_failure_actual, first_failure_expected, explain_stderr_ru(result.stderr),
            )
        if _compare(test.get("expected", ""), result.stdout, problem.checker):
            passed += 1
        elif first_failure_expected is None:
            first_failure_actual, first_failure_expected = result.stdout, test.get("expected", "")

    score = round(100 * passed / len(tests), 2)
    verdict = Verdict.ACCEPTED if passed == len(tests) else Verdict.WRONG_ANSWER
    if verdict == Verdict.ACCEPTED:
        first_failure_actual = first_failure_expected = None
    return JudgeResult(verdict, score, last_stdout, last_stderr, first_failure_actual, first_failure_expected, None)
