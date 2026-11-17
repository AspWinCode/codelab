"""Этап 10 (ТЗ) — история изменений курса: GET .../changes.

Важная особенность ЭТОГО проекта: публикация курса автоматическая после
КАЖДОЙ правки методиста (auto_publish_item, см. course_admin.py — решение
2026-10-xx, см. README) — то есть черновик и активная (опубликованная)
версия почти всегда совпадают, а каждая правка сама по себе уже создаёт
новую опубликованную версию с собственной записью в AuditEvent (actor_id,
created_at). Поэтому "история изменений" здесь — не диф "черновик против
опубликованного" (он почти всегда пуст и ничего не скажет методисту), а
список дифов между ПОСЛЕДОВАТЕЛЬНЫМИ опубликованными версиями: каждая такая
пара — это ровно одна правка методиста, с точным автором и датой ИЗ
AuditEvent этой публикации, а не из эвристики."""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import AuditEvent, Course, CourseVersion, LearningItem, User
from app.services.course_admin import _match_item_trees

TRACKED_FIELDS = [
    "title", "description", "content", "is_required", "weight", "position",
    "unlock_rules", "problem_revision_id", "steps", "quiz_questions", "oge_answer",
    "oge_max_attempts", "oge_allow_retry_after_success", "oge_show_result_immediately",
    "oge_show_correct_answer", "due_at", "embed_editor", "is_archived",
]


def _normalize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "value"):  # enum (LearningItemType и т.п.)
        return value.value
    return value


@dataclass
class FieldChange:
    field: str
    old_value: Any
    new_value: Any


@dataclass
class ItemChange:
    item_id: int
    title: str
    type: str
    fields: list[FieldChange] = field(default_factory=list)


@dataclass
class ItemRef:
    item_id: int
    title: str
    type: str


@dataclass
class ChangeSet:
    version_number: int
    published_at: Optional[datetime]
    author: Optional[str]
    added: list[ItemRef]
    removed: list[ItemRef]
    changed: list[ItemChange]


def _diff_versions(from_items: list[LearningItem], to_items: list[LearningItem]) -> tuple[list[ItemRef], list[ItemRef], list[ItemChange]]:
    """from_items — более старая версия, to_items — более новая. Сопоставление
    "тот же элемент" — source_item_id (to-элемент ссылается на from-элемент,
    с которого склонирован при публикации), с фолбэком _match_item_trees для
    версий до появления этого поля."""
    mapping: dict[int, int] = {}  # from.id -> to.id
    by_source = {i.source_item_id: i.id for i in to_items if i.source_item_id}
    for f in from_items:
        if f.id in by_source:
            mapping[f.id] = by_source[f.id]
    unmatched_from = [f for f in from_items if f.id not in mapping]
    if unmatched_from:
        matched_to_ids = set(mapping.values())
        remaining_to = [t for t in to_items if t.id not in matched_to_ids]
        mapping.update(_match_item_trees(unmatched_from, remaining_to))

    from_by_id = {f.id: f for f in from_items}
    to_by_id = {t.id: t for t in to_items}
    matched_to_ids = set(mapping.values())

    added = [ItemRef(item_id=t.id, title=t.title, type=t.type.value) for t in to_items if t.id not in matched_to_ids]
    removed = [ItemRef(item_id=f.id, title=f.title, type=f.type.value) for f in from_items if f.id not in mapping]

    changed: list[ItemChange] = []
    for from_id, to_id in mapping.items():
        f_item, t_item = from_by_id[from_id], to_by_id[to_id]
        field_changes: list[FieldChange] = []
        for attr in TRACKED_FIELDS:
            old_v, new_v = _normalize(getattr(f_item, attr)), _normalize(getattr(t_item, attr))
            if old_v != new_v:
                field_changes.append(FieldChange(field=attr, old_value=old_v, new_value=new_v))

        # parent_id: id в разных версиях не сопоставимы напрямую — "родитель
        # не поменялся" значит "новый parent_id — это to-образ старого".
        old_parent_as_to = mapping.get(f_item.parent_id) if f_item.parent_id else None
        if old_parent_as_to != t_item.parent_id:
            field_changes.append(FieldChange(field="parent_id", old_value=f_item.parent_id, new_value=t_item.parent_id))

        if field_changes:
            changed.append(ItemChange(item_id=to_id, title=t_item.title, type=t_item.type.value, fields=field_changes))

    return added, removed, changed


def get_course_changes(db: Session, course_id: int, limit: int = 20) -> list[ChangeSet]:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    versions = (
        db.query(CourseVersion)
        .filter(CourseVersion.course_id == course_id, CourseVersion.published_at.isnot(None))
        .order_by(CourseVersion.version_number)
        .all()
    )
    if len(versions) < 2:
        return []

    publish_events = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == "course_publish", AuditEvent.object_type == "course", AuditEvent.object_id == course_id)
        .order_by(AuditEvent.created_at)
        .all()
    )
    # meta.version_id — id версии, которая СТАЛА опубликованной этим событием
    # (см. publish_course). Несколько событий на одну версию теоретически
    # невозможны (публикация необратима), поэтому первое совпадение — то.
    author_by_version_id: dict[int, Optional[str]] = {}
    for event in publish_events:
        version_id = event.meta.get("version_id") if event.meta else None
        if version_id is None or version_id in author_by_version_id:
            continue
        author = db.query(User).filter(User.id == event.actor_id).first() if event.actor_id else None
        author_by_version_id[version_id] = author.full_name if author else None

    pairs = list(zip(versions, versions[1:]))[-limit:]
    changesets: list[ChangeSet] = []
    for from_version, to_version in reversed(pairs):  # самые свежие первыми
        from_items = db.query(LearningItem).filter(LearningItem.course_version_id == from_version.id).all()
        to_items = db.query(LearningItem).filter(LearningItem.course_version_id == to_version.id).all()
        added, removed, changed = _diff_versions(from_items, to_items)
        if not (added or removed or changed):
            continue
        changesets.append(ChangeSet(
            version_number=to_version.version_number,
            published_at=to_version.published_at,
            author=author_by_version_id.get(to_version.id),
            added=added, removed=removed, changed=changed,
        ))
    return changesets
