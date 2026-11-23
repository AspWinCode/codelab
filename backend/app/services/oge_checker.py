"""Гибкая проверка ответов ОГЭ (замена прямого actual == expected).

oge_answer хранится в LearningItem.oge_answer как JSON. Старый формат
(созданный до этой доработки) — просто {"answer": "12"}, без "checker":
такие задания продолжают проверяться по старому правилу (сравнение после
strip() и замены "," на "."), чтобы не переломить уже опубликованные курсы
(см. ТЗ п.16.9 — обратная совместимость).

Новый формат:
{
  "checker": "number"|"text"|"integer"|"decimal"|"boolean"|"custom",
  "answer": "12",
  "accepted_answers": ["12", "12.0", "12,0"],
  "case_sensitive": false,
  "ignore_spaces": true,
  "tolerance": 0.01  # только для decimal
}
"""
from typing import Optional


def _normalize_number(value: str) -> Optional[float]:
    """"," и "." — один и тот же десятичный разделитель; "−" (U+2212,
    типографский минус, который студенты копируют из условий задач) —
    то же самое, что "-"."""
    cleaned = value.strip().replace(",", ".").replace("−", "-")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _candidates(oge_answer: dict) -> list[str]:
    answer = str(oge_answer.get("answer", ""))
    accepted = [str(a) for a in (oge_answer.get("accepted_answers") or [])]
    return [answer, *accepted]


def _check_number(submitted: str, candidates: list[str]) -> bool:
    actual = _normalize_number(submitted)
    if actual is None:
        return False
    return any(_normalize_number(c) == actual for c in candidates)


def _check_integer(submitted: str, candidates: list[str]) -> bool:
    actual = _normalize_number(submitted)
    if actual is None or not actual.is_integer():
        return False
    return any(
        (expected := _normalize_number(c)) is not None and expected.is_integer() and expected == actual
        for c in candidates
    )


def _check_decimal(submitted: str, candidates: list[str], tolerance: float) -> bool:
    actual = _normalize_number(submitted)
    if actual is None:
        return False
    for c in candidates:
        expected = _normalize_number(c)
        if expected is not None and abs(expected - actual) <= tolerance:
            return True
    return False


def _check_boolean(submitted: str, candidates: list[str]) -> bool:
    truthy = {"да", "true", "1", "верно", "yes"}
    falsy = {"нет", "false", "0", "неверно", "no"}

    def _as_bool(value: str) -> Optional[bool]:
        v = value.strip().lower()
        if v in truthy:
            return True
        if v in falsy:
            return False
        return None

    actual = _as_bool(submitted)
    if actual is None:
        return False
    return any(_as_bool(c) == actual for c in candidates)


def _check_text(submitted: str, candidates: list[str], case_sensitive: bool, ignore_spaces: bool) -> bool:
    def _norm(value: str) -> str:
        v = value.strip() if ignore_spaces else value
        return v if case_sensitive else v.lower()

    actual = _norm(submitted)
    return any(_norm(c) == actual for c in candidates)


def check_oge_answer(oge_answer: dict, submitted: str) -> bool:
    """True, если submitted принимается как правильный ответ для oge_answer."""
    checker = oge_answer.get("checker")
    if checker is None:
        # Старый формат тоже должен принимать ответ независимо от регистра:
        # часть опубликованных заданий ещё не содержит поля checker.
        expected = str(oge_answer.get("answer", "")).strip().replace(",", ".").casefold()
        actual = str(submitted).strip().replace(",", ".").casefold()
        return actual == expected

    candidates = _candidates(oge_answer)
    if checker == "number":
        return _check_number(submitted, candidates)
    if checker == "integer":
        return _check_integer(submitted, candidates)
    if checker == "decimal":
        tolerance = float(oge_answer.get("tolerance") or 0)
        return _check_decimal(submitted, candidates, tolerance)
    if checker == "boolean":
        return _check_boolean(submitted, candidates)
    # "text" и "custom" (без отдельного движка проверки пока — ведёт себя как text)
    case_sensitive = bool(oge_answer.get("case_sensitive", False))
    ignore_spaces = bool(oge_answer.get("ignore_spaces", True))
    return _check_text(submitted, candidates, case_sensitive, ignore_spaces)
