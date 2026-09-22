"""Иерархия дерева курса: ровно 4 фиксированных структурных уровня —
Модуль → Подмодуль → Тема → Подтема — каждый следующий обязан лежать
непосредственно внутри предыдущего, порядок нельзя перескочить. Контентные
типы (theory/video/file/link/quiz/task/manual/checkpoint) не структурные —
могут лежать на любом из четырёх уровней или в корне курса, но сами не
могут быть родителем ни для чего (не листовые узлы запрещены)."""
from typing import Optional

from fastapi import HTTPException

from app.models import LearningItem, LearningItemType

# Чей непосредственный родитель обязателен для каждого структурного уровня;
# None — верхний уровень иерархии (может быть только в корне курса).
STRUCTURAL_PARENT: dict[LearningItemType, Optional[LearningItemType]] = {
    LearningItemType.MODULE: None,
    LearningItemType.SUBMODULE: LearningItemType.MODULE,
    LearningItemType.TOPIC: LearningItemType.SUBMODULE,
    LearningItemType.SUBTOPIC: LearningItemType.TOPIC,
}

STRUCTURAL_TYPES = frozenset(STRUCTURAL_PARENT)

_LABELS = {
    LearningItemType.MODULE: "Модуль",
    LearningItemType.SUBMODULE: "Подмодуль",
    LearningItemType.TOPIC: "Тема",
    LearningItemType.SUBTOPIC: "Подтема",
}


def validate_parent(item_type: LearningItemType, parent: Optional[LearningItem]) -> None:
    """Бросает 422, если parent не годится в родители для item_type по
    правилам 4-уровневой иерархии. Вызывается и при создании, и при
    перемещении узла (смене parent_id)."""
    if item_type in STRUCTURAL_TYPES:
        expected = STRUCTURAL_PARENT[item_type]
        label = _LABELS[item_type]
        if expected is None:
            if parent is not None:
                raise HTTPException(status_code=422, detail=f"{label} — верхний уровень иерархии, не может быть вложен")
        else:
            expected_label = _LABELS[expected]
            if parent is None or parent.type != expected:
                raise HTTPException(status_code=422, detail=f"{label} может лежать только непосредственно внутри «{expected_label}»")
    else:
        # Контент: любой из 4 структурных уровней или корень курса — но не
        # внутри другого контента (материал/задача не может иметь детей).
        if parent is not None and parent.type not in STRUCTURAL_TYPES:
            raise HTTPException(status_code=422, detail="Материал/задачу нельзя вкладывать в другой материал/задачу")
