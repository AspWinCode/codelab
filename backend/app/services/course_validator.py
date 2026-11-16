"""LMS-010 (ТЗ Этап 4): проверка целостности черновика курса перед
публикацией. Часть правил (STRUCTURAL_PARENT из tree_rules.py) уже
гарантирована на create/update — здесь добавляем то, что НЕ проверяется
при обычном редактировании: заполненность контента по типам, уникальность
позиций среди соседей, ссылки unlock_rules, архивация обязательных
элементов и защитные проверки битых ссылок/циклов (на случай ручного
вмешательства в базу — обычный API создать их не даёт).

validate_course_before_publish() сам по себе ничего не запрещает — вызов
кладёт результат либо в GET .../validation (методисту для просмотра),
либо в явный POST .../publish (где он блокирует публикацию при ошибках).
Он НЕ стоит на внутренних авто-republish вызовах после отдельных правок
(update_task/delete_item и т.п., см. course_admin.publish_course) — это
другой, более низкоуровневый механизм переноса черновика в новую версию,
и блокировать его тут же сломало бы редактирование любого курса, в
котором уже есть незаконченный элемент где-то в другом месте дерева
(развязка "сохранить черновик" / "опубликовать" — отдельная задача,
ТЗ Этап 10)."""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.models import LearningItem, LearningItemType
from app.services.course_admin import get_draft_version, get_course_or_404

_STEPS_TYPES = frozenset({LearningItemType.SNAP_TASK, LearningItemType.GDEVELOP_TASK, LearningItemType.TURTLE_TASK})


@dataclass
class ValidationError:
    item_id: Optional[int]
    code: str
    message: str


def _find_cycle_item_ids(items: list[LearningItem]) -> set[int]:
    by_id = {i.id: i for i in items}
    cyclic: set[int] = set()
    for item in items:
        seen: set[int] = {item.id}
        node = item
        while node and node.parent_id is not None:
            if node.parent_id in seen:
                cyclic.add(item.id)
                break
            seen.add(node.parent_id)
            node = by_id.get(node.parent_id)
    return cyclic


def validate_course_before_publish(db: Session, course_id: int) -> list[ValidationError]:
    get_course_or_404(db, course_id)
    version = get_draft_version(db, course_id)

    items = (
        db.query(LearningItem)
        .filter(LearningItem.course_version_id == version.id)
        .all()
    )
    by_id = {i.id: i for i in items}
    errors: list[ValidationError] = []

    for item in items:
        if item.parent_id is not None and item.parent_id not in by_id:
            errors.append(ValidationError(item.id, "BROKEN_PARENT_REFERENCE", f"«{item.title}»: родитель не найден в этой версии курса"))

    for item_id in _find_cycle_item_ids(items):
        errors.append(ValidationError(item_id, "CYCLE_DETECTED", f"«{by_id[item_id].title}»: цикл в дереве родителей"))

    position_groups: dict[tuple, list[LearningItem]] = {}
    for item in items:
        position_groups.setdefault((item.parent_id, item.position), []).append(item)
    for (_, position), group in position_groups.items():
        if len(group) > 1:
            for item in group:
                errors.append(ValidationError(item.id, "DUPLICATE_POSITION", f"«{item.title}»: позиция {position} повторяется у нескольких элементов одного родителя"))

    for item in items:
        if item.type == LearningItemType.OGE_TASK:
            if not (item.content or "").strip():
                errors.append(ValidationError(item.id, "OGE_CONTENT_REQUIRED", f"«{item.title}»: не указан текст условия"))
            if not str((item.oge_answer or {}).get("answer", "")).strip():
                errors.append(ValidationError(item.id, "OGE_ANSWER_REQUIRED", f"«{item.title}»: не указан правильный ответ"))
        elif item.type == LearningItemType.TASK:
            if not item.problem_revision_id:
                errors.append(ValidationError(item.id, "TASK_PROBLEM_REQUIRED", f"«{item.title}»: не привязана программная задача"))
        elif item.type == LearningItemType.QUIZ:
            if not item.quiz_questions:
                errors.append(ValidationError(item.id, "QUIZ_QUESTIONS_REQUIRED", f"«{item.title}»: нет ни одного вопроса"))
        elif item.type in _STEPS_TYPES:
            if not item.steps:
                errors.append(ValidationError(item.id, "STEPS_REQUIRED", f"«{item.title}»: нет ни одного этапа"))

        if item.is_required and item.is_archived:
            errors.append(ValidationError(item.id, "ARCHIVED_REQUIRED_ITEM", f"«{item.title}»: обязательный элемент архивирован"))

        after_item_id = (item.unlock_rules or {}).get("after_item_id")
        if after_item_id is not None and after_item_id not in by_id:
            errors.append(ValidationError(item.id, "UNLOCK_RULE_INVALID", f"«{item.title}»: unlock_rules ссылается на несуществующий элемент {after_item_id}"))

    return errors
