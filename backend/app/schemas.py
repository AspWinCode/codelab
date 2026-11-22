from datetime import datetime
from typing import Any, List, Optional, Union

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

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
    template_code: Optional[str]
    # IDE-002: последний код ученика по ЭТОЙ задаче — фронт подставляет его в
    # редактор при открытии, а не то, что осталось в редакторе от предыдущей.
    draft_code: Optional[str]
    # Момент последнего серверного сохранения черновика — фронт сравнивает
    # его со своей локальной резервной копией (localStorage) при открытии
    # задачи, чтобы не перезатереть более свежие несохранённые правки уже
    # устаревшим ответом сервера и не подставить стартовый шаблон поверх
    # существующего черновика.
    draft_updated_at: Optional[datetime] = None


class CourseCreate(BaseModel):
    title: str
    slug: Optional[str] = None
    description: Optional[str] = None


class CourseUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None


class CourseArchiveIn(BaseModel):
    archived: bool


class CourseOut(BaseModel):
    id: int
    slug: Optional[str]
    title: str
    description: Optional[str]
    status: str
    is_archived: bool = False

    model_config = ConfigDict(from_attributes=True)


class CourseDraftStatusOut(BaseModel):
    course_id: int
    active_version_number: Optional[int] = None
    draft_version_number: Optional[int] = None
    has_unpublished_changes: bool


class SnapStep(BaseModel):
    """Один этап Snap!-задания — панель Snap! в нём не участвует, она одна
    и статична на весь элемент, листаются только текст слева."""

    title: str
    content: str = ""


class QuizOption(BaseModel):
    text: str
    correct: bool = False


class QuizQuestion(BaseModel):
    """Один тип вопроса — несколько правильных ответов (checkbox). Живёт
    прямо на элементе дерева (LearningItem.quiz_questions), не в отдельном
    банке — вопросы между тестами не переиспользуются."""

    text: str
    options: List[QuizOption] = []


class QuizAttemptCreate(BaseModel):
    # answers[i] — индексы отмеченных учеником вариантов вопроса №i, в
    # порядке item.quiz_questions на момент отправки попытки.
    answers: List[List[int]]


class QuizAttemptOut(BaseModel):
    id: int
    item_id: int
    score: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OgePreviewCheckIn(BaseModel):
    """Этап 5 (ТЗ) — предпросмотр: тот же ввод, что и у настоящей попытки,
    но ответ только проверяется (check_oge_answer), ничего не сохраняется."""

    answer: str


class OgePreviewCheckOut(BaseModel):
    is_correct: bool


class QuizPreviewCheckIn(BaseModel):
    answers: List[List[int]]


class QuizPreviewCheckOut(BaseModel):
    score: float


class OgeAnswerIn(BaseModel):
    """Новый формат oge_answer (ТЗ п.16.9 — старый плоский текст ответа
    продолжает работать через LearningItemCreate/Update.oge_answer: str,
    см. ниже и app/services/oge_checker.py)."""

    checker: str = "text"  # number|text|integer|decimal|boolean|custom
    answer: str
    accepted_answers: List[str] = []
    case_sensitive: bool = False
    ignore_spaces: bool = True
    tolerance: Optional[float] = None
    explanation: Optional[str] = None

    @field_validator("checker")
    @classmethod
    def _validate_checker(cls, v: str) -> str:
        allowed = {"number", "text", "integer", "decimal", "boolean", "custom"}
        if v not in allowed:
            raise ValueError(f"Неизвестный тип проверки: {v}")
        return v


class OgeAttemptOut(BaseModel):
    id: int
    item_id: int
    score: float
    created_at: datetime
    file_original_filename: Optional[str] = None
    file_size: Optional[int] = None
    # Заполняются только для ответа сразу после отправки и только если
    # методист разрешил их показывать в настройках задания.
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class LearningItemCreate(BaseModel):
    """LMS-001..004: элемент дерева курса. Для type="task" обязателен
    problem_revision_id — сама задача создаётся отдельно, POST /courses/{id}/tasks.
    Для type="snap_task" — steps (непустой список этапов).

    4 структурных типа — module/submodule/topic/subtopic — образуют жёсткую
    иерархию (каждый только внутри непосредственного родителя, см.
    app/services/tree_rules.py); остальные типы — контент, может лежать на
    любом из этих уровней или в корне курса."""

    type: str  # theory|video|file|link|quiz|oge_task|task|manual|checkpoint|snap_task|project|module|submodule|topic|subtopic
    title: str
    description: Optional[str] = None
    content: Optional[str] = None
    parent_id: Optional[int] = None
    is_required: bool = True
    weight: float = 1.0
    position: int = 0
    unlock_rules: dict = {}
    problem_revision_id: Optional[int] = None
    steps: Optional[List[SnapStep]] = None
    quiz_questions: Optional[List[QuizQuestion]] = None
    # str — старый плоский формат (обратная совместимость); OgeAnswerIn —
    # новый гибкий чекер (ТЗ п.16.9, см. app/services/oge_checker.py).
    oge_answer: Optional[Union[str, OgeAnswerIn]] = None
    # Только для type="oge_task" — ограничение попыток и что показывать
    # ученику после отправки (см. app/services/oge_checker.py — применяются
    # в course_admin.submit_oge_attempt).
    oge_max_attempts: Optional[int] = None  # null = не ограничено
    oge_allow_retry_after_success: bool = True
    oge_show_result_immediately: bool = True
    oge_show_correct_answer: bool = False
    # Только для type="project" — срок сдачи (см. ProjectSubmission).
    due_at: Optional[datetime] = None
    # Только для type="project" — если "turtle", фронтенд показывает справа
    # iframe-редактор черепашки вместо формы ручной загрузки файла.
    embed_editor: Optional[str] = None


class LearningItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    parent_id: Optional[int] = None
    is_required: Optional[bool] = None
    weight: Optional[float] = None
    position: Optional[int] = None
    unlock_rules: Optional[dict] = None
    steps: Optional[List[SnapStep]] = None
    quiz_questions: Optional[List[QuizQuestion]] = None
    oge_answer: Optional[Union[str, OgeAnswerIn]] = None
    oge_max_attempts: Optional[int] = None
    oge_allow_retry_after_success: Optional[bool] = None
    oge_show_result_immediately: Optional[bool] = None
    oge_show_correct_answer: Optional[bool] = None
    due_at: Optional[datetime] = None
    embed_editor: Optional[str] = None


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
    steps: Optional[List[SnapStep]] = None
    # ВНИМАНИЕ: содержит правильные ответы (QuizOption.correct) — этот
    # объект уходит студенту только через build_student_tree, которая
    # обязана стереть correct у каждого варианта (см. course_admin.py).
    # Отдельной "student"-схемы нет специально: тип элемента один и тот же
    # (LearningItemTree) что для методиста, что для ученика.
    quiz_questions: Optional[List[QuizQuestion]] = None
    oge_answer: Optional[dict] = None
    oge_max_attempts: Optional[int] = None
    oge_allow_retry_after_success: bool = True
    oge_show_result_immediately: bool = True
    oge_show_correct_answer: bool = False
    due_at: Optional[datetime] = None
    embed_editor: Optional[str] = None

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


class OgeTaskAnalyticsOut(BaseModel):
    """ANA-001/002 для ОГЭ: статистика по одному заданию."""

    item_id: int
    title: str
    module_title: Optional[str]
    topic_title: Optional[str]
    enrolled_count: int
    students_attempted: int
    correct_count: int
    incorrect_count: int
    correct_rate_percent: float
    avg_attempts: Optional[float]
    median_attempts: Optional[float]
    students_not_attempted: int
    avg_score: float
    last_attempt_at: Optional[datetime]


class OgeModuleStatsOut(BaseModel):
    module_title: str
    tasks_count: int
    attempts_total: int
    avg_correct_rate_percent: float


class OgeOverviewOut(BaseModel):
    total_tasks: int
    solved_tasks: int
    avg_correct_rate_percent: float
    total_attempts: int
    completion_percent: float
    hardest_tasks: List[OgeTaskAnalyticsOut]
    easiest_tasks: List[OgeTaskAnalyticsOut]
    by_module: List[OgeModuleStatsOut]


class ValidationErrorOut(BaseModel):
    """LMS-010 (ТЗ Этап 4): одна проблема целостности черновика перед
    публикацией — см. app/services/course_validator.py."""

    item_id: Optional[int]
    code: str
    message: str

    model_config = ConfigDict(from_attributes=True)


class CourseValidationOut(BaseModel):
    valid: bool
    errors: List[ValidationErrorOut]
    warnings: List[ValidationErrorOut] = []


class CourseAnalyticsOut(BaseModel):
    generated_at: datetime  # ANA-005: дата актуальности метрик
    overview: CourseOverviewOut
    tasks: List[TaskDifficultyOut]
    oge_overview: OgeOverviewOut
    oge_tasks: List[OgeTaskAnalyticsOut]


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
    # LMS: по этому id (не совпадает с LearningItem.id дерева курса!) можно
    # запросить GET /lms-admin/tasks/{problem_revision_id} и показать
    # преподавателю задачу целиком, включая скрытые тесты.
    problem_revision_id: int




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
    # Вывод студента и требуемый вывод с одного и того же первого
    # несовпавшего теста (см. комментарий у Submission.actual_output в
    # models.py) + готовое объяснение ошибки на русском — None при ACCEPTED.
    actual_output: Optional[str] = None
    expected_output: Optional[str] = None
    error_explanation: Optional[str] = None
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


class DraftIn(BaseModel):
    """IDE-002: автосохранение кода без прогона/отправки — фронт шлёт это с
    debounce по мере набора, а не только попутно с "Запустить"/"Отправить"."""

    problem_revision_id: int
    code: str


class DraftOut(BaseModel):
    updated_at: datetime


class RunResult(BaseModel):
    stdout: str
    stderr: str
    timed_out: bool
    # Готовое объяснение на русском по типу исключения — дополняет stderr,
    # не заменяет его (см. app/services/error_explain.py). None, если ошибки
    # нет или её тип не распознан.
    error_explanation: Optional[str] = None


class MeOut(BaseModel):
    id: int
    external_ref: str
    full_name: str
    role: str
    groups: List[str]
    directions: List[str]
    return_to_url: Optional[str] = None

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


class ProjectFileCommentOut(BaseModel):
    id: int
    author_id: int
    author_full_name: str
    body: str
    created_at: datetime


class ProjectFileOut(BaseModel):
    id: int
    original_filename: str
    content_type: str
    size: int
    uploaded_at: datetime
    comments: List[ProjectFileCommentOut] = []


class ProjectAttemptSummary(BaseModel):
    """Короткая карточка прошлой попытки — для истории пересдач."""

    id: int
    attempt_number: int
    status: str
    submitted_at: Optional[datetime]
    score: Optional[float]


class ProjectSubmissionOut(BaseModel):
    """Ученический и штатный (staff) взгляд на попытку сдачи проекта.
    is_overdue считается на бэкенде относительно LearningItem.due_at, чтобы
    не дублировать логику дат на фронте."""

    id: int
    learning_item_id: int
    attempt_number: int
    status: str
    submitted_at: Optional[datetime]
    reviewed_at: Optional[datetime]
    score: Optional[float]
    review_comment: Optional[str]
    due_at: Optional[datetime]
    is_overdue: bool
    files: List[ProjectFileOut] = []
    history: List[ProjectAttemptSummary] = []


class ProjectSubmissionReviewOut(ProjectSubmissionOut):
    """Строка в списке сдач курса для тренера/методиста — с данными ученика."""

    student_external_ref: str
    student_full_name: str
    item_title: str


class ProjectFileCommentIn(BaseModel):
    body: str


class ProjectReviewIn(BaseModel):
    decision: str  # accepted | needs_revision
    score: Optional[float] = None
    comment: str

    @field_validator("decision")
    @classmethod
    def _decision_must_be_known(cls, value: str) -> str:
        if value not in ("accepted", "needs_revision"):
            raise ValueError("decision должен быть 'accepted' или 'needs_revision'")
        return value

    @field_validator("comment")
    @classmethod
    def _comment_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Комментарий обязателен при проверке проекта")
        return value

    @model_validator(mode="after")
    def _score_required_when_accepted(self) -> "ProjectReviewIn":
        if self.decision == "accepted" and self.score is None:
            raise ValueError("При принятии работы нужно поставить оценку")
        return self


class EnvironmentOut(BaseModel):
    """ADM-001: пункт реестра окружений исполнения — методист выбирает
    отсюда при создании задачи (ProblemRevisionCreate.language)."""

    id: str
    label: str
    allowed_libraries: List[str]
    status: str  # ready | beta
    status_note: str


class FieldChangeOut(BaseModel):
    field: str
    old_value: Any = None
    new_value: Any = None

    model_config = ConfigDict(from_attributes=True)


class ItemChangeOut(BaseModel):
    item_id: int
    title: str
    type: str
    fields: List[FieldChangeOut]

    model_config = ConfigDict(from_attributes=True)


class ItemRefOut(BaseModel):
    item_id: int
    title: str
    type: str

    model_config = ConfigDict(from_attributes=True)


class ChangeSetOut(BaseModel):
    """Этап 10 (ТЗ): один элемент истории изменений курса — диф между двумя
    последовательными опубликованными версиями (= одна правка методиста,
    т.к. публикация здесь автоматическая после каждой правки — см.
    app/services/course_changes.py)."""

    version_number: int
    published_at: Optional[datetime]
    author: Optional[str]
    added: List[ItemRefOut]
    removed: List[ItemRefOut]
    changed: List[ItemChangeOut]

    model_config = ConfigDict(from_attributes=True)


class BulkEditIn(BaseModel):
    """Этап 9 (ТЗ) — массовое редактирование. Какие из required/weight/
    max_attempts/parent_id/target_course_id нужны, зависит от operation —
    см. app/routers/lms_admin.py::bulk_edit_items."""

    item_ids: List[int]
    operation: str  # archive|unarchive|delete|set_required|set_weight|set_max_attempts|move|copy_to_course
    required: Optional[bool] = None
    weight: Optional[float] = None
    max_attempts: Optional[int] = None
    parent_id: Optional[int] = None
    target_course_id: Optional[int] = None

    @field_validator("operation")
    @classmethod
    def _validate_operation(cls, v: str) -> str:
        allowed = {"archive", "unarchive", "delete", "set_required", "set_weight", "set_max_attempts", "move", "copy_to_course"}
        if v not in allowed:
            raise ValueError(f"Неизвестная операция: {v}")
        return v

    @field_validator("item_ids")
    @classmethod
    def _validate_item_ids(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("item_ids не может быть пустым")
        return v


class BulkEditItemResultOut(BaseModel):
    item_id: int
    ok: bool
    error: Optional[str] = None


class BulkEditOut(BaseModel):
    operation: str
    results: List[BulkEditItemResultOut]
    succeeded: int
    failed: int


class ImportRowOut(BaseModel):
    """Этап 8 (ТЗ): одна строка импорта заданий ОГЭ из CSV/XLSX — для
    предпросмотра до создания (app/services/task_import.py)."""

    line: int
    title: str
    module: str
    errors: List[str]
    duplicate: bool
    valid: bool


class ImportPreviewOut(BaseModel):
    rows: List[ImportRowOut]
    valid_count: int
    error_count: int
    duplicate_count: int


class ImportResultOut(BaseModel):
    created: int
    skipped_invalid: int
    skipped_duplicate: int
    total_rows: int
    published: bool
