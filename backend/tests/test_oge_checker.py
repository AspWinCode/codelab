"""Этап 2 (ТЗ п.16.9): гибкая проверка ответов ОГЭ — number/text/integer/
decimal/boolean + обратная совместимость со старым форматом oge_answer."""
from app.services.oge_checker import check_oge_answer


def test_legacy_format_without_checker_compares_like_before():
    oge_answer = {"answer": "12"}
    assert check_oge_answer(oge_answer, "12")
    assert check_oge_answer(oge_answer, "12,0") is False  # старое поведение: только strip + "," -> "."
    assert check_oge_answer(oge_answer, " 12 ")
    assert check_oge_answer(oge_answer, "13") is False


def test_number_checker_treats_dot_and_comma_as_equal():
    oge_answer = {"checker": "number", "answer": "2"}
    assert check_oge_answer(oge_answer, "2")
    assert check_oge_answer(oge_answer, "2.0")
    assert check_oge_answer(oge_answer, "2,0")
    assert check_oge_answer(oge_answer, "3") is False


def test_number_checker_handles_negative_and_typographic_minus():
    oge_answer = {"checker": "number", "answer": "-5"}
    assert check_oge_answer(oge_answer, "-5")
    assert check_oge_answer(oge_answer, "−5")  # типографский минус U+2212


def test_number_checker_ignores_surrounding_spaces():
    oge_answer = {"checker": "number", "answer": "7"}
    assert check_oge_answer(oge_answer, "  7  ")


def test_number_checker_accepts_additional_accepted_answers():
    oge_answer = {"checker": "number", "answer": "12", "accepted_answers": ["12.5"]}
    assert check_oge_answer(oge_answer, "12.5")
    assert check_oge_answer(oge_answer, "13") is False


def test_integer_checker_rejects_non_integer_value():
    oge_answer = {"checker": "integer", "answer": "2"}
    assert check_oge_answer(oge_answer, "2")
    assert check_oge_answer(oge_answer, "2.5") is False
    assert check_oge_answer(oge_answer, "2.0")  # 2.0 целое по значению


def test_decimal_checker_respects_tolerance():
    oge_answer = {"checker": "decimal", "answer": "3.14", "tolerance": 0.01}
    assert check_oge_answer(oge_answer, "3.14")
    assert check_oge_answer(oge_answer, "3.145")
    assert check_oge_answer(oge_answer, "3.2") is False


def test_text_checker_case_sensitivity_setting():
    oge_answer = {"checker": "text", "answer": "Москва", "case_sensitive": True}
    assert check_oge_answer(oge_answer, "Москва")
    assert check_oge_answer(oge_answer, "москва") is False

    oge_answer_insensitive = {"checker": "text", "answer": "Москва", "case_sensitive": False}
    assert check_oge_answer(oge_answer_insensitive, "москва")


def test_text_checker_multiple_accepted_variants():
    oge_answer = {"checker": "text", "answer": "кот", "accepted_answers": ["кошка", "котёнок"]}
    assert check_oge_answer(oge_answer, "кошка")
    assert check_oge_answer(oge_answer, "пёс") is False


def test_text_checker_ignores_spaces_by_default():
    oge_answer = {"checker": "text", "answer": "ответ"}
    assert check_oge_answer(oge_answer, "  ответ  ")


def test_boolean_checker_accepts_russian_and_english_variants():
    oge_answer = {"checker": "boolean", "answer": "да"}
    assert check_oge_answer(oge_answer, "Да")
    assert check_oge_answer(oge_answer, "true")
    assert check_oge_answer(oge_answer, "нет") is False
