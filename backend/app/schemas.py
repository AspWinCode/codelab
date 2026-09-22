from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.services.environments import ENVIRONMENTS


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
    language: str = "python3"  # id окружения — см. GET /api/lms-admin/environments (ADM-001)
    # ADM-003: обязателен для language="sql-sqlite" — схема+seed (CREATE TABLE/INSERT).
    sql_fixture: Optional[str] = None
    time_limit_ms: int = 2000
    memory_limit_mb: int = 256
    allowed_libraries: List[str] = []
    tests: List[ProblemTestIn] = []
    checker: str = "exact"
    max_attempts: Optional[int] = None
    scoring_policy: str = "best"

    @field_validator("language")
    @classmethod
    def _language_must_be_registered(cls, value: str) -> str:
        if value not in ENVIRONMENTS:
            raise ValueError(f"Неизвестное окружение исполнения: {value!r}. См. GET /api/lms-admin/environments")
        return value


class ProblemRevisionOut(ProblemRevisionCreate):
    id: int
    task_id: int
    revision_number: int

    model_config = ConfigDict(from_attributes=True)


class ProblemTestOut(BaseModel):
    input: str
    expected: str
    is_hidden: bool = False
    group: str = "default"
    weight: float = 1.0


class ProblemRevisionStudentOut(BaseModel):
    """STU-003: то же, что ProblemRevisionOut, но без reference_solution,
    checker/scoring_policy/max_attempts (не студенческое дело) и без
    скрытых тестов — только visible_tests (см. course_admin.to_student_problem_out)."""

    id: int
    title: str
    statement: str
    input_format: Optional[str]
    output_format: Optional[str]
    constraints: Optional[str]
    time_limit_ms: int
    memory_limit_mb: int
    language: str
    allowed_libraries: List[str]
    visible_tests: List[ProblemTestOut]


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
    problem_revision_id — сама задача создаётся отдельно, POST /courses/{id}/tasks.

    4 структурных типа — module/submodule/topic/subtopic — образуют жёсткую
    иерархию (каждый только внутри непосредственного родителя, см.
    app/services/tree_rules.py); остальные типы — контент, может лежать на
    любом из этих уровней или в корне курса."""

    type: str  # theory|video|file|link|quiz|task|manual|checkpoint|module|submodule|topic|subtopic
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
    is_archived: bool = False

    model_config = ConfigDict(from_attributes=True)


class LearningItemArchiveIn(BaseModel):
    archived: bool


class LearningItemTree(LearningItemOut):
    children: List["LearningItemTree"] = []
    # STU-002: заблокированные элементы видны, но недоступны для прохождения
    # (LMS-004, unlock_rules). Смысл только для взгляда ученика — методисту
    # черновик всегда возвращается с unlocked=True/completed=False.
    unlocked: bool = True
    completed: bool = False


class NextItemOut(BaseModel):
    id: int
    title: str


class DashboardCourseOut(BaseModel):
    """STU-001: главная страница ученика — активные курсы, % прохождения,
    ближайшие дедлайны, следующий рекомендуемый шаг."""

    course_id: int
    title: str
    percent: float
    completed_items: int
    total_items: int
    deadline: Optional[datetime] = None
    next_item: Optional[NextItemOut] = None
    last_item_id: Optional[int] = None


class RecentResultOut(BaseModel):
    submission_id: int
    task_title: str
    verdict: Optional[str]
    score: Optional[float]
    created_at: datetime


class DashboardOut(BaseModel):
    courses: List[DashboardCourseOut]
    recent_results: List[RecentResultOut]


class LastPositionIn(BaseModel):
    item_id: int


class CourseOverviewOut(BaseModel):
    """ANA-001: агрегированные метрики курса."""

    course_id: int
    enrolled_count: int
    completed_count: int
    completion_percent: float
    avg_score: float
    median_score: float
    total_attempts: int
    overdue_count: int


class TaskDifficultyOut(BaseModel):
    """ANA-002: рейтинг задачи по сложности."""

    item_id: int
    title: str
    attempts_total: int
    students_attempted: int
    students_solved: int
    students_not_attempted: int
    failure_rate_percent: float
    avg_attempts_to_solve: Optional[float]
    most_common_failure_verdict: Optional[str]


class CourseAnalyticsOut(BaseModel):
    generated_at: datetime  # ANA-005: дата актуальности метрик
    overview: CourseOverviewOut
    tasks: List[TaskDifficultyOut]


class SubmissionReviewOut(BaseModel):
    """TCH-001/003: обзор посылок курса для преподавателя/методиста."""

    submission_id: int
    student_external_ref: str
    student_full_name: str
    item_title: str
    code: str
    status: str
    verdict: Optional[str]
    score: Optional[float]
    manual_score_override: Optional[float]
    manual_comment: Optional[str]
    created_at: datetime




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


class RerunSubmissionsIn(BaseModel):
    """TASK-007: массовая перепроверка выбранных посылок."""

    submission_ids: List[int]


class RerunSubmissionsOut(BaseModel):
    requeued: int


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


class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    body: Optional[str]
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationPreferenceOut(BaseModel):
    type: str
    enabled: bool
    mandatory: bool  # NTF-003: обязательные показываются, но недоступны для выключения


class NotificationPreferenceUpdate(BaseModel):
    enabled: bool


class AdminQueueStatus(BaseModel):
    queued_count: int
    running_count: int
    oldest_queued_age_seconds: Optional[int]
    worker_likely_stalled: bool


class AdminErrorStatus(BaseModel):
    system_errors_last_24h: int


class AdminStorageStatus(BaseModel):
    uploads_size_bytes: int
    disk_free_bytes: int
    disk_total_bytes: int


class AdminSystemStatusOut(BaseModel):
    """ADM-004."""

    generated_at: datetime
    queue: AdminQueueStatus
    errors: AdminErrorStatus
    storage: AdminStorageStatus


class AdminUserOut(BaseModel):
    """IAM-004: карточка пользователя для блокировки/истории входов."""

    id: int
    external_ref: str
    full_name: str
    role: str
    is_blocked: bool
    last_login_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class AdminUserBlockIn(BaseModel):
    blocked: bool


class AdminLoginEventOut(BaseModel):
    created_at: datetime


class EnvironmentOut(BaseModel):
    """ADM-001: пункт реестра окружений исполнения — методист выбирает
    отсюда при создании задачи (ProblemRevisionCreate.language)."""

    id: str
    label: str
    allowed_libraries: List[str]
    status: str  # ready | beta
    status_note: str
