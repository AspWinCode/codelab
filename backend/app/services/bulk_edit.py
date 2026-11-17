"""Этап 9 (ТЗ) — массовое редактирование элементов курса методистом:
переместить, архивировать/разархивировать, удалить, изменить обязательность/
вес/лимит попыток, скопировать в другой курс. "Изменить тип" сознательно не
реализовано — смена типа требует данных, которых у другого типа может не
быть (steps/quiz_questions/problem_revision_id/oge_answer), и без контракта
конкретной UI-формы это было бы либо тихой потерей данных, либо гаданием,
что подставить вместо них.

Каждая операция здесь переиспользует per-item функции course_admin.py
(update_item/delete_item/set_item_archived) — массовость только избавляет
методиста от N кликов, не ослабляет ни одну из их проверок (черновик,
иерархия, отсутствие циклов и т.п.)."""
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import LearningItem
from app.schemas import LearningItemUpdate
from app.services.course_admin import delete_item, get_draft_version, set_item_archived, update_item


@dataclass
class BulkOpResult:
    item_id: int
    ok: bool
    error: Optional[str] = None


def items_in_draft(db: Session, course_id: int, item_ids: list[int]) -> dict[int, LearningItem]:
    """Отфильтровывает item_ids до тех, что реально лежат в черновике ЭТОГО
    курса — иначе зная свой course_id, можно было бы массовой операцией
    задеть элемент из чужого курса, просто угадав его id (RBAC-002)."""
    version = get_draft_version(db, course_id)
    items = db.query(LearningItem).filter(
        LearningItem.id.in_(item_ids), LearningItem.course_version_id == version.id,
    ).all()
    return {i.id: i for i in items}


def _next_position(db: Session, version_id: int, parent_id: Optional[int]) -> int:
    max_position = db.query(func.max(LearningItem.position)).filter(
        LearningItem.course_version_id == version_id, LearningItem.parent_id == parent_id,
    ).scalar()
    return 0 if max_position is None else max_position + 1


def _run_per_item(db: Session, course_id: int, item_ids: list[int], action) -> list[BulkOpResult]:
    by_id = items_in_draft(db, course_id, item_ids)
    results = []
    for item_id in item_ids:
        if item_id not in by_id:
            results.append(BulkOpResult(item_id, False, "Элемент не найден в этом курсе"))
            continue
        try:
            action(item_id)
            results.append(BulkOpResult(item_id, True))
        except HTTPException as e:
            results.append(BulkOpResult(item_id, False, str(e.detail)))
    return results


def bulk_archive(db: Session, course_id: int, item_ids: list[int], archived: bool) -> list[BulkOpResult]:
    return _run_per_item(db, course_id, item_ids, lambda item_id: set_item_archived(db, item_id, archived))


def bulk_delete(db: Session, course_id: int, item_ids: list[int]) -> list[BulkOpResult]:
    return _run_per_item(db, course_id, item_ids, lambda item_id: delete_item(db, item_id))


def bulk_set_required(db: Session, course_id: int, item_ids: list[int], required: bool) -> list[BulkOpResult]:
    return _run_per_item(db, course_id, item_ids, lambda item_id: update_item(db, item_id, LearningItemUpdate(is_required=required)))


def bulk_set_weight(db: Session, course_id: int, item_ids: list[int], weight: float) -> list[BulkOpResult]:
    return _run_per_item(db, course_id, item_ids, lambda item_id: update_item(db, item_id, LearningItemUpdate(weight=weight)))


def bulk_set_max_attempts(db: Session, course_id: int, item_ids: list[int], max_attempts: Optional[int]) -> list[BulkOpResult]:
    """Применимо к заданиям ОГЭ (oge_max_attempts) — на других типах
    элементов поле просто ни на что не влияет (update_item его всё равно
    примет, это не ошибка пользователя)."""
    return _run_per_item(db, course_id, item_ids, lambda item_id: update_item(db, item_id, LearningItemUpdate(oge_max_attempts=max_attempts)))


def bulk_move(db: Session, course_id: int, item_ids: list[int], new_parent_id: Optional[int]) -> list[BulkOpResult]:
    """Все выбранные элементы переезжают к одному новому родителю, друг за
    другом в конец его детей — update_item сам проверит иерархию (тип
    нового родителя подходит, нет цикла) на каждом элементе."""
    version = get_draft_version(db, course_id)
    position = _next_position(db, version.id, new_parent_id)
    results = []
    by_id = items_in_draft(db, course_id, item_ids)
    for item_id in item_ids:
        if item_id not in by_id:
            results.append(BulkOpResult(item_id, False, "Элемент не найден в этом курсе"))
            continue
        try:
            update_item(db, item_id, LearningItemUpdate(parent_id=new_parent_id, position=position))
            position += 1
            results.append(BulkOpResult(item_id, True))
        except HTTPException as e:
            results.append(BulkOpResult(item_id, False, str(e.detail)))
    return results


def _clone_subtree(db: Session, root: LearningItem, target_version_id: int, target_parent_id: Optional[int], position: int) -> LearningItem:
    """unlock_rules намеренно не переносится — after_item_id в нём ссылается
    на id элемента в ИСХОДНОМ курсе, в целевом курсе это либо чужой
    произвольный элемент, либо (чаще) вообще не существующий id."""
    clone = LearningItem(
        course_version_id=target_version_id,
        parent_id=target_parent_id,
        type=root.type,
        title=root.title,
        description=root.description,
        content=root.content,
        is_required=root.is_required,
        weight=root.weight,
        position=position,
        unlock_rules={},
        problem_revision_id=root.problem_revision_id,
        steps=root.steps,
        quiz_questions=root.quiz_questions,
        oge_answer=root.oge_answer,
        oge_max_attempts=root.oge_max_attempts,
        oge_allow_retry_after_success=root.oge_allow_retry_after_success,
        oge_show_result_immediately=root.oge_show_result_immediately,
        oge_show_correct_answer=root.oge_show_correct_answer,
        due_at=root.due_at,
        embed_editor=root.embed_editor,
    )
    db.add(clone)
    db.flush()
    children = (
        db.query(LearningItem)
        .filter(LearningItem.parent_id == root.id)
        .order_by(LearningItem.position)
        .all()
    )
    for i, child in enumerate(children):
        _clone_subtree(db, child, target_version_id, clone.id, i)
    return clone


def bulk_copy_to_course(
    db: Session, source_course_id: int, item_ids: list[int], target_course_id: int,
) -> list[BulkOpResult]:
    """Копирует поддерево каждого выбранного элемента в КОРЕНЬ черновика
    целевого курса (ТЗ не уточняет, в какой раздел целевого курса это
    должно лечь, — методисту проще перетащить уже скопированное на место,
    чем гадать правильную секцию автоматически)."""
    by_id = items_in_draft(db, source_course_id, item_ids)
    target_version = get_draft_version(db, target_course_id)
    position = _next_position(db, target_version.id, None)
    results = []
    for item_id in item_ids:
        if item_id not in by_id:
            results.append(BulkOpResult(item_id, False, "Элемент не найден в этом курсе"))
            continue
        try:
            _clone_subtree(db, by_id[item_id], target_version.id, None, position)
            position += 1
            db.commit()
            results.append(BulkOpResult(item_id, True))
        except Exception as e:
            db.rollback()
            results.append(BulkOpResult(item_id, False, str(e)))
    return results
