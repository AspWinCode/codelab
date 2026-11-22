"""Этап 3 (ТЗ п.16.9): лимит попыток ОГЭ, запрет повторной попытки после
правильного ответа, отсутствие ограничения по умолчанию."""
import pytest
from fastapi import HTTPException

from app.models import Course, CourseVersion, LearningItemType, User
from app.schemas import LearningItemCreate, OgeAnswerIn
from app.services.course_admin import create_item, submit_oge_attempt


def _setup(db, **item_overrides):
    student_ref = item_overrides.pop("student_ref", "s1")
    course = Course(title="C")
    db.add(course)
    db.flush()
    version = CourseVersion(course_id=course.id, version_number=1)
    db.add(version)
    db.commit()

    payload = {"type": "oge_task", "title": "Задание", "oge_answer": "12", **item_overrides}
    item = create_item(db, course.id, LearningItemCreate(**payload))
    student = User(external_ref=student_ref, full_name="Студент", role="student")
    db.add(student)
    db.commit()
    return item, student


def test_submit_without_limit_allows_unlimited_attempts(db_session):
    item, student = _setup(db_session)
    for answer in ("1", "2", "3"):
        attempt = submit_oge_attempt(db_session, item.id, student.id, answer)
        assert attempt.score == 0.0
    attempt = submit_oge_attempt(db_session, item.id, student.id, "12")
    assert attempt.score == 100.0


def test_submit_raises_when_attempts_exceed_max(db_session):
    item, student = _setup(db_session, oge_max_attempts=2)
    submit_oge_attempt(db_session, item.id, student.id, "1")
    submit_oge_attempt(db_session, item.id, student.id, "2")
    with pytest.raises(HTTPException) as exc_info:
        submit_oge_attempt(db_session, item.id, student.id, "3")
    assert exc_info.value.status_code == 422
    assert "попытки" in exc_info.value.detail.lower()


def test_submit_blocks_retry_after_success_when_disallowed(db_session):
    item, student = _setup(db_session, oge_allow_retry_after_success=False)
    attempt = submit_oge_attempt(db_session, item.id, student.id, "12")
    assert attempt.score == 100.0
    with pytest.raises(HTTPException) as exc_info:
        submit_oge_attempt(db_session, item.id, student.id, "12")
    assert exc_info.value.status_code == 422


def test_submit_allows_retry_after_success_by_default(db_session):
    item, student = _setup(db_session)  # oge_allow_retry_after_success=True по умолчанию
    submit_oge_attempt(db_session, item.id, student.id, "12")
    attempt = submit_oge_attempt(db_session, item.id, student.id, "12")
    assert attempt.score == 100.0


def test_max_attempts_counts_failed_and_successful_attempts_together(db_session):
    item, student = _setup(db_session, oge_max_attempts=1)
    submit_oge_attempt(db_session, item.id, student.id, "12")  # верно, но это уже 1-я попытка
    with pytest.raises(HTTPException):
        submit_oge_attempt(db_session, item.id, student.id, "12")


def test_create_item_accepts_new_flexible_checker_format(db_session):
    course = Course(title="C2")
    db_session.add(course)
    db_session.flush()
    db_session.add(CourseVersion(course_id=course.id, version_number=1))
    db_session.commit()

    item = create_item(
        db_session,
        course.id,
        LearningItemCreate(
            type="oge_task",
            title="Гибкая проверка",
            oge_answer=OgeAnswerIn(checker="number", answer="2", accepted_answers=["2.5"]),
        ),
    )
    assert item.oge_answer["checker"] == "number"

    student = User(external_ref="s2", full_name="Студент2", role="student")
    db_session.add(student)
    db_session.commit()

    assert submit_oge_attempt(db_session, item.id, student.id, "2,0").score == 100.0
    assert submit_oge_attempt(db_session, item.id, student.id, "2.5").score == 100.0


def test_submit_returns_explanation_and_correct_answer_only_when_enabled(db_session):
    answer = OgeAnswerIn(checker="number", answer="12", explanation="Сложите значения в таблице.")
    item, student = _setup(
        db_session,
        oge_answer=answer,
        oge_show_correct_answer=True,
        oge_show_result_immediately=True,
    )
    attempt = submit_oge_attempt(db_session, item.id, student.id, "10")
    assert attempt.correct_answer == "12"
    assert attempt.explanation == "Сложите значения в таблице."

    hidden_item, hidden_student = _setup(
        db_session,
        oge_answer=answer,
        oge_show_correct_answer=False,
        oge_show_result_immediately=False,
        student_ref="s-hidden",
    )
    hidden_attempt = submit_oge_attempt(db_session, hidden_item.id, hidden_student.id, "10")
    assert getattr(hidden_attempt, "correct_answer", None) is None
    assert getattr(hidden_attempt, "explanation", None) is None
