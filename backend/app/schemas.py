from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ProblemTestIn(BaseModel):
    input: str
    expected: str
    is_hidden: bool = False
    group: str = "default"
    weight: float = 1.0


class ProblemRevisionCreate(BaseModel):
    title: str
    statement: str = ""
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    constraints: Optional[str] = None
    examples: List[dict] = []
    template_code: Optional[str] = None
    reference_solution: Optional[str] = None
    language: str = "python3"
    time_limit_ms: int = 2000
    memory_limit_mb: int = 256
    allowed_libraries: List[str] = []
    tests: List[ProblemTestIn] = []
    checker: str = "exact"
    max_attempts: Optional[int] = None
    scoring_policy: str = "best"


class ProblemRevisionOut(ProblemRevisionCreate):
    id: int
    task_id: int
    revision_number: int

    model_config = ConfigDict(from_attributes=True)


class CourseCreate(BaseModel):
    title: str
    slug: Optional[str] = None
    description: Optional[str] = None


class CourseOut(BaseModel):
    id: int
    slug: Optional[str]
    title: str
    description: Optional[str]
    status: str

    model_config = ConfigDict(from_attributes=True)


class LearningItemCreate(BaseModel):
    """LMS-001..004: элемент дерева курса. Для type="task" обязателен
    problem_revision_id — сама задача создаётся отдельно, POST /courses/{id}/tasks."""

    type: str  # theory | video | file | link | quiz | task | manual | checkpoint
    title: str
    description: Optional[str] = None
    content: Optional[str] = None
    parent_id: Optional[int] = None
    is_required: bool = True
    weight: float = 1.0
    position: int = 0
    unlock_rules: dict = {}
    problem_revision_id: Optional[int] = None


class LearningItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    parent_id: Optional[int] = None
    is_required: Optional[bool] = None
    weight: Optional[float] = None
    position: Optional[int] = None
    unlock_rules: Optional[dict] = None


class LearningItemOut(BaseModel):
    id: int
    type: str
    content: Optional[str] = None
    title: str
    description: Optional[str]
    parent_id: Optional[int]
    is_required: bool
    weight: float
    position: int
    unlock_rules: dict
    problem_revision_id: Optional[int]

    model_config = ConfigDict(from_attributes=True)


class LearningItemTree(LearningItemOut):
    children: List["LearningItemTree"] = []
    # STU-002: заблокированные элементы видны, но недоступны для прохождения
    # (LMS-004, unlock_rules). Смысл только для взгляда ученика — методисту
    # черновик всегда возвращается с unlocked=True.
    unlocked: bool = True


class UploadOut(BaseModel):
    """EDT-002/008: результат загрузки файла в редактор контента."""

    url: str
    content_type: str
    size: int


class SubmissionCreate(BaseModel):
    problem_revision_id: int
    code: str
    language: str = "python3"


class SubmissionOut(BaseModel):
    id: int
    status: str
    verdict: Optional[str]
    score: Optional[float]
    stdout: Optional[str]
    stderr: Optional[str]
    # GRD-004: ручная корректировка хранится отдельно от исходного авто-результата выше.
    manual_score_override: Optional[float] = None
    manual_comment: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ManualGradeIn(BaseModel):
    """GRD-004: ручная корректировка результата — комментарий обязателен."""

    score: float
    comment: str


class RunRequest(BaseModel):
    """IDE-003: запуск на пользовательском вводе без создания оцениваемой посылки."""

    problem_revision_id: int
    code: str
    stdin: str = ""


class RunResult(BaseModel):
    stdout: str
    stderr: str
    timed_out: bool


class MeOut(BaseModel):
    id: int
    external_ref: str
    full_name: str
    role: str
    groups: List[str]
    directions: List[str]

    model_config = ConfigDict(from_attributes=True)
