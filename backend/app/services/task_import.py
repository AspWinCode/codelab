"""Этап 8 (ТЗ) — массовый импорт заданий ОГЭ из CSV/XLSX.

Формат (как в ТЗ, разделитель ";" для CSV):
    title;content;answer;checker;module
    Задача 1;Условие задачи;12;number;Тип 1
    Задача 2;Условие задачи;Москва;text;Тип 2

"module" — название модуля верхнего уровня: существующий переиспользуется
(по точному совпадению title в черновике), иначе заводится новый. DOCX
сознательно не поддержан — условия задач ОГЭ в проекте редактируются через
WYSIWYG на портале (README), а не через плоский текстовый формат, в который
DOCX естественно ложился бы."""
import csv
import io
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AuditEvent, LearningItem, LearningItemType
from app.schemas import LearningItemCreate, OgeAnswerIn
from app.services.course_admin import create_item, get_draft_version

VALID_CHECKERS = {"number", "text", "integer", "decimal", "boolean", "custom"}


@dataclass
class ImportRow:
    line: int
    title: str = ""
    content: str = ""
    answer: str = ""
    checker: str = "text"
    module: str = ""
    errors: list[str] = field(default_factory=list)
    duplicate: bool = False

    @property
    def valid(self) -> bool:
        return not self.errors


def _rows_from_csv(data: bytes) -> list[dict]:
    # utf-8-sig — Excel на Windows сохраняет CSV с BOM, без этого в первом
    # заголовке остаётся невидимый ﻿ и "title" перестаёт совпадать.
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    return [dict(row) for row in reader]


def _rows_from_xlsx(data: bytes) -> list[dict]:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)
    header = [str(h or "").strip().lower() for h in (next(rows_iter, None) or [])]
    rows = []
    for values in rows_iter:
        if values is None or all(v is None for v in values):
            continue
        rows.append({header[i]: values[i] for i in range(len(header)) if i < len(values)})
    return rows


def parse_import_file(filename: str, data: bytes) -> list[ImportRow]:
    lower = filename.lower()
    if lower.endswith(".xlsx"):
        raw_rows = _rows_from_xlsx(data)
    elif lower.endswith(".csv"):
        raw_rows = _rows_from_csv(data)
    else:
        raise HTTPException(status_code=422, detail="Поддерживаются только файлы .csv и .xlsx")

    def cell(raw: dict, key: str) -> str:
        value = raw.get(key)
        return str(value).strip() if value is not None else ""

    rows: list[ImportRow] = []
    for i, raw in enumerate(raw_rows, start=2):  # строка 1 — заголовок
        row = ImportRow(
            line=i,
            title=cell(raw, "title"),
            content=cell(raw, "content"),
            answer=cell(raw, "answer"),
            checker=(cell(raw, "checker") or "text").lower(),
            module=cell(raw, "module"),
        )
        if not row.title:
            row.errors.append("Не указано название (title)")
        if not row.answer:
            row.errors.append("Не указан правильный ответ (answer)")
        if row.checker not in VALID_CHECKERS:
            row.errors.append(f"Неизвестный тип проверки: {row.checker}")
        rows.append(row)
    return rows


def mark_duplicates(db: Session, course_id: int, rows: list[ImportRow]) -> None:
    """Не создавать дубликаты при повторном импорте (ТЗ Этап 8) — считаем
    дублем задание ОГЭ с тем же названием в том же модуле черновика."""
    version = get_draft_version(db, course_id)
    items = db.query(LearningItem).filter(LearningItem.course_version_id == version.id).all()
    by_id = {i.id: i for i in items}
    existing: dict[str, set[str]] = {}
    for item in items:
        if item.type != LearningItemType.OGE_TASK:
            continue
        parent = by_id.get(item.parent_id) if item.parent_id else None
        module_title = parent.title if parent and parent.type == LearningItemType.MODULE else ""
        existing.setdefault(module_title, set()).add(item.title)
    for row in rows:
        if row.title in existing.get(row.module, set()):
            row.duplicate = True


def _next_position(db: Session, version_id: int, parent_id: Optional[int]) -> int:
    max_position = db.query(func.max(LearningItem.position)).filter(
        LearningItem.course_version_id == version_id, LearningItem.parent_id == parent_id,
    ).scalar()
    return 0 if max_position is None else max_position + 1


def _get_or_create_module(
    db: Session, course_id: int, version_id: int, title: str, cache: dict[str, LearningItem],
) -> Optional[LearningItem]:
    if not title:
        return None
    if title in cache:
        return cache[title]
    existing = db.query(LearningItem).filter(
        LearningItem.course_version_id == version_id,
        LearningItem.type == LearningItemType.MODULE,
        LearningItem.title == title,
    ).first()
    if existing:
        cache[title] = existing
        return existing
    position = _next_position(db, version_id, None)
    module = create_item(db, course_id, LearningItemCreate(type="module", title=title, position=position))
    cache[title] = module
    return module


def import_tasks(db: Session, course_id: int, rows: list[ImportRow], actor_id: Optional[int]) -> dict:
    """Создаёт OGE_TASK-элементы из валидных, не-дублирующихся строк.
    Невалидные и дублирующиеся строки молча пропускаются — вызывающий код
    уже показал их методисту через preview до этого вызова (ТЗ: "показать
    предварительный просмотр", "не создавать дубликаты")."""
    version = get_draft_version(db, course_id)
    module_cache: dict[str, LearningItem] = {}
    created = 0
    skipped_invalid = 0
    skipped_duplicate = 0

    for row in rows:
        if not row.valid:
            skipped_invalid += 1
            continue
        if row.duplicate:
            skipped_duplicate += 1
            continue
        module = _get_or_create_module(db, course_id, version.id, row.module, module_cache)
        parent_id = module.id if module else None
        position = _next_position(db, version.id, parent_id)
        create_item(db, course_id, LearningItemCreate(
            type="oge_task", title=row.title, content=row.content, parent_id=parent_id, position=position,
            oge_answer=OgeAnswerIn(checker=row.checker, answer=row.answer),
        ))
        created += 1

    result = {
        "created": created, "skipped_invalid": skipped_invalid,
        "skipped_duplicate": skipped_duplicate, "total_rows": len(rows),
    }
    db.add(AuditEvent(
        actor_id=actor_id, action="course_import_tasks", object_type="course", object_id=course_id,
        meta=result,
    ))
    db.commit()
    return result
