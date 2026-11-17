"""Этап 8 (ТЗ): массовый импорт заданий ОГЭ из CSV/XLSX."""
import hashlib
import hmac
import io

from app.config import settings
from app.models import AuditEvent, Course, CourseVersion, LearningItem, LearningItemType
from app.services.task_import import import_tasks, mark_duplicates, parse_import_file


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Методист", role="methodist"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


CSV_SAMPLE = (
    "title;content;answer;checker;module\n"
    "Задача 1;Условие задачи;12;number;Тип 1\n"
    "Задача 2;Условие задачи;Москва;text;Тип 2\n"
).encode("utf-8-sig")


def _make_course(db):
    course = Course(title="C")
    db.add(course)
    db.flush()
    db.add(CourseVersion(course_id=course.id, version_number=1))
    db.commit()
    return course


def test_parse_csv_valid_rows():
    rows = parse_import_file("tasks.csv", CSV_SAMPLE)
    assert len(rows) == 2
    assert rows[0].title == "Задача 1"
    assert rows[0].answer == "12"
    assert rows[0].checker == "number"
    assert rows[0].module == "Тип 1"
    assert rows[0].valid
    assert rows[1].valid


def test_parse_csv_reports_missing_fields_and_bad_checker():
    data = (
        "title;content;answer;checker;module\n"
        ";Условие;;badchecker;Тип 1\n"
    ).encode("utf-8-sig")
    rows = parse_import_file("tasks.csv", data)
    assert len(rows) == 1
    assert not rows[0].valid
    assert any("title" in e for e in rows[0].errors)
    assert any("ответ" in e for e in rows[0].errors)
    assert any("badchecker" in e for e in rows[0].errors)


def test_parse_rejects_unsupported_extension():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        parse_import_file("tasks.docx", b"whatever")


def test_import_tasks_creates_modules_and_items(db_session):
    course = _make_course(db_session)
    rows = parse_import_file("tasks.csv", CSV_SAMPLE)
    mark_duplicates(db_session, course.id, rows)
    result = import_tasks(db_session, course.id, rows, actor_id=None)

    assert result == {"created": 2, "skipped_invalid": 0, "skipped_duplicate": 0, "total_rows": 2}

    modules = db_session.query(LearningItem).filter(LearningItem.type == LearningItemType.MODULE).all()
    assert {m.title for m in modules} == {"Тип 1", "Тип 2"}

    tasks = db_session.query(LearningItem).filter(LearningItem.type == LearningItemType.OGE_TASK).all()
    assert {t.title for t in tasks} == {"Задача 1", "Задача 2"}
    task1 = next(t for t in tasks if t.title == "Задача 1")
    assert task1.oge_answer["checker"] == "number"
    assert task1.oge_answer["answer"] == "12"

    assert db_session.query(AuditEvent).filter(AuditEvent.action == "course_import_tasks").count() == 1


def test_import_tasks_reuses_existing_module_and_skips_duplicates_on_reimport(db_session):
    course = _make_course(db_session)
    rows = parse_import_file("tasks.csv", CSV_SAMPLE)
    mark_duplicates(db_session, course.id, rows)
    import_tasks(db_session, course.id, rows, actor_id=None)

    # Повторный импорт того же файла — не должен создать дубликаты модулей
    # или задач, см. ТЗ Этап 8.
    rows2 = parse_import_file("tasks.csv", CSV_SAMPLE)
    mark_duplicates(db_session, course.id, rows2)
    assert all(r.duplicate for r in rows2)
    result2 = import_tasks(db_session, course.id, rows2, actor_id=None)
    assert result2["created"] == 0
    assert result2["skipped_duplicate"] == 2

    assert db_session.query(LearningItem).filter(LearningItem.type == LearningItemType.MODULE).count() == 2
    assert db_session.query(LearningItem).filter(LearningItem.type == LearningItemType.OGE_TASK).count() == 2


def _make_course_via_api(client, qs, sig):
    resp = client.post(f"/api/lms-admin/courses?{qs}", json={"title": "C"}, headers={"X-LP-Signature": sig})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_preview_endpoint_reports_errors_and_duplicates_without_creating(client, db_session):
    qs = _staff_qs()
    sig = _sig("lp-user-1")
    course = _make_course_via_api(client, qs, sig)

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/import-tasks/preview?{qs}",
        files={"file": ("tasks.csv", io.BytesIO(CSV_SAMPLE), "text/csv")},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid_count"] == 2
    assert body["error_count"] == 0
    assert body["duplicate_count"] == 0
    # preview ничего не создаёт
    assert db_session.query(LearningItem).count() == 0


def test_import_endpoint_creates_draft_without_publishing(client, db_session):
    qs = _staff_qs()
    sig = _sig("lp-user-1")
    course = _make_course_via_api(client, qs, sig)

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/import-tasks?{qs}",
        files={"file": ("tasks.csv", io.BytesIO(CSV_SAMPLE), "text/csv")},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 2
    assert body["published"] is False

    db_course = db_session.query(Course).filter(Course.id == course["id"]).first()
    assert db_course.active_version_id is None  # не опубликовано


def test_import_endpoint_with_publish_true_blocked_by_incomplete_other_item(client, db_session):
    """ТЗ Этап 4+8 вместе: publish=true должен уважать общую валидацию
    курса, не только импортированные строки."""
    qs = _staff_qs()
    sig = _sig("lp-user-1")
    course = _make_course_via_api(client, qs, sig)

    # Левое незавершённое задание ОГЭ, никак не связанное с импортом.
    client.post(
        f"/api/lms-admin/courses/{course['id']}/items?{qs}",
        json={"type": "oge_task", "title": "Незаконченное", "oge_answer": "1"},
        headers={"X-LP-Signature": sig},
    )

    resp = client.post(
        f"/api/lms-admin/courses/{course['id']}/import-tasks?{qs}&publish=true",
        files={"file": ("tasks.csv", io.BytesIO(CSV_SAMPLE), "text/csv")},
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["import_result"]["created"] == 2
