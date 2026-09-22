"""Модель данных согласно разделу 6 ТЗ. Минимальный набор сущностей и связей;
конкретная схема уточняется на этапе проектирования (см. README)."""
import enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import backref, relationship

from app.database import Base


class CourseStatus(str, enum.Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class EnrollmentStatus(str, enum.Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    REVOKED = "revoked"


class LearningItemType(str, enum.Enum):
    THEORY = "theory"
    VIDEO = "video"
    FILE = "file"
    LINK = "link"
    QUIZ = "quiz"
    TASK = "task"
    MANUAL = "manual"
    CHECKPOINT = "checkpoint"
    # Snap!-задание (блочное программирование, IAM для «Новичок»): слева
    # пошаговая инструкция (см. LearningItem.steps), справа постоянный iframe
    # на snap.tirskix.space — редактор не перезагружается между шагами.
    SNAP_TASK = "snap_task"
    # Структурные узлы дерева курса — организационная иерархия без
    # собственного контента, ровно 4 уровня (см. app/services/tree_rules.py):
    # модуль → подмодуль → тема → подтема. Контентные типы выше могут лежать
    # на любом из этих уровней.
    MODULE = "module"
    SUBMODULE = "submodule"
    TOPIC = "topic"
    SUBTOPIC = "subtopic"


# Статусы посылки — JDG-001, JDG-004.
class SubmissionStatus(str, enum.Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"
    SYSTEM_ERROR = "system_error"


class Verdict(str, enum.Enum):
    ACCEPTED = "Accepted"
    WRONG_ANSWER = "Wrong Answer"
    TIME_LIMIT_EXCEEDED = "Time Limit Exceeded"
    MEMORY_LIMIT_EXCEEDED = "Memory Limit Exceeded"
    RUNTIME_ERROR = "Runtime Error"
    COMPILATION_ERROR = "Compilation Error"
    PRESENTATION_ERROR = "Presentation Error"
    SECURITY_VIOLATION = "Security Violation"
    INTERNAL_ERROR = "Internal Error"


class User(Base):
    """IAM-002: локальная учётка создаётся по доверенным атрибутам SSO при первом входе."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    # "lp-student-{id}" от портала — стабильный ключ вместо имени/email (INT-004).
    external_ref = Column(String(128), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False, default="student")
    # IAM-003: группы/направления, переданные порталом при SSO.
    groups = Column(JSON, nullable=False, default=list)
    directions = Column(JSON, nullable=False, default=list)
    is_blocked = Column(Boolean, nullable=False, default=False)
    # IAM-004: "завершить активные сессии" — раз сессия это подписанный JWT без
    # состояния на сервере, отозвать конкретный токен нельзя; вместо этого
    # любой токен, выданный ДО этой отметки, считается недействительным
    # (проверка в app/deps.py по iat).
    sessions_invalidated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    enrollments = relationship("Enrollment", back_populates="user")
    drafts = relationship("Draft", back_populates="user")
    submissions = relationship("Submission", back_populates="user")


class LoginEvent(Base):
    """IAM-004: история входов — администратор должен её просматривать."""

    __tablename__ = "login_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True)
    slug = Column(String(128), unique=True, nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SQLEnum(CourseStatus), nullable=False, default=CourseStatus.DRAFT)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    versions = relationship(
        "CourseVersion",
        back_populates="course",
        order_by="CourseVersion.version_number",
        foreign_keys="CourseVersion.course_id",
    )
    # Публикация создаёт отдельную версию (LMS-006); это — активная опубликованная.
    # use_alter=True: без этого Alembic/Postgres не могут создать courses и
    # course_versions — у них взаимные внешние ключи (course_versions.course_id
    # наоборот ссылается на courses.id), см. commit-сообщение.
    active_version_id = Column(
        Integer,
        ForeignKey("course_versions.id", use_alter=True, name="fk_courses_active_version"),
        nullable=True,
    )


class CourseVersion(Base):
    """LMS-006: изменение черновика не меняет уже опубликованную версию."""

    __tablename__ = "course_versions"

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="versions", foreign_keys=[course_id])
    items = relationship("LearningItem", back_populates="course_version", order_by="LearningItem.position")

    __table_args__ = (UniqueConstraint("course_id", "version_number", name="uq_course_version"),)


class LearningItem(Base):
    __tablename__ = "learning_items"

    id = Column(Integer, primary_key=True)
    course_version_id = Column(Integer, ForeignKey("course_versions.id"), nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("learning_items.id"), nullable=True)
    type = Column(SQLEnum(LearningItemType), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    # EDT-001: содержимое теории/материала — Markdown с изображениями/видео/кодом/формулами,
    # рендерится на фронтенде (раздел 5.3). Автосохранение — EDT-006, PUT .../items/{id}.
    content = Column(Text, nullable=True)
    is_required = Column(Boolean, nullable=False, default=True)
    weight = Column(Float, nullable=False, default=1.0)
    position = Column(Integer, nullable=False, default=0)
    # Условия открытия — например {"after_item_id": 12, "min_score": 60} (LMS-004).
    unlock_rules = Column(JSON, nullable=False, default=dict)
    problem_revision_id = Column(Integer, ForeignKey("problem_revisions.id"), nullable=True)
    # Шаги для type=snap_task: [{"title": str, "content": html}, ...]. Панель
    # Snap! в них не участвует — она одна и статична на весь элемент, шаги
    # листают только текст инструкции слева.
    steps = Column(JSON, nullable=True)
    # Архивация каскадится на все дочерние узлы в момент действия (см.
    # app/services/tree_rules.py: set_item_archived) — простой флаг, не
    # "скрыт, если у предка is_archived", чтобы не пересчитывать видимость
    # по всей цепочке предков на каждый рендер дерева.
    is_archived = Column(Boolean, nullable=False, default=False)

    course_version = relationship("CourseVersion", back_populates="items")
    # remote_side идёт на backref ("parent"), не на "children" — иначе
    # relationship переворачивается: "children" становится скаляром (None),
    # а "parent" — коллекцией.
    children = relationship("LearningItem", backref=backref("parent", remote_side="LearningItem.id"))
    problem_revision = relationship("ProblemRevision")


class ProblemRevision(Base):
    """Минимальные поля — Приложение Б ТЗ."""

    __tablename__ = "problem_revisions"

    id = Column(Integer, primary_key=True)
    # Стабильный id задачи через ревизии (TASK-006).
    task_id = Column(Integer, nullable=False, index=True)
    revision_number = Column(Integer, nullable=False, default=1)
    title = Column(String(255), nullable=False)
    statement = Column(Text, nullable=False, default="")
    input_format = Column(Text, nullable=True)
    output_format = Column(Text, nullable=True)
    constraints = Column(Text, nullable=True)
    examples = Column(JSON, nullable=False, default=list)  # [{"input": "...", "output": "..."}]
    template_code = Column(Text, nullable=True)
    reference_solution = Column(Text, nullable=True)
    language = Column(String(32), nullable=False, default="python3")  # id из app/services/environments.py (ADM-001/002/003)
    # ADM-003: схема+seed для окружения sql-sqlite — CREATE TABLE/INSERT,
    # исполняется доверенным кодом методиста (не решением ученика) при сборке
    # свежей базы перед каждым прогоном, см. app/services/runner.py.
    sql_fixture = Column(Text, nullable=True)
    time_limit_ms = Column(Integer, nullable=False, default=2000)
    memory_limit_mb = Column(Integer, nullable=False, default=256)
    allowed_libraries = Column(JSON, nullable=False, default=list)
    # [{"input": "...", "expected": "...", "is_hidden": bool, "group": "default", "weight": 1.0}]
    tests = Column(JSON, nullable=False, default=list)
    checker = Column(String(32), nullable=False, default="exact")  # exact | trimmed | numeric | custom
    max_attempts = Column(Integer, nullable=True)  # null = не ограничено (GRD-001)
    scoring_policy = Column(String(16), nullable=False, default="best")  # best | last | first_accepted
    hints = Column(JSON, nullable=False, default=list)
    explanation = Column(Text, nullable=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Enrollment(Base):
    __tablename__ = "enrollments"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    course_version_id = Column(Integer, ForeignKey("course_versions.id"), nullable=True)
    status = Column(SQLEnum(EnrollmentStatus), nullable=False, default=EnrollmentStatus.ACTIVE)
    source = Column(String(32), nullable=False, default="lms")  # lms | manual
    starts_at = Column(DateTime(timezone=True), nullable=True)
    ends_at = Column(DateTime(timezone=True), nullable=True)
    # STU-005: последняя открытая позиция в материале — "продолжить обучение".
    last_item_id = Column(Integer, ForeignKey("learning_items.id"), nullable=True)
    # NTF-001: чтобы не слать напоминание о дедлайне повторно на каждый прогон
    # проверки (см. app/notify_deadlines.py).
    deadline_notified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="enrollments")
    course = relationship("Course")

    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_user_course_enrollment"),)


class Draft(Base):
    """IDE-002: последний сохранённый код ученика по задаче."""

    __tablename__ = "drafts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    problem_revision_id = Column(Integer, ForeignKey("problem_revisions.id"), nullable=False, index=True)
    code = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user = relationship("User", back_populates="drafts")

    __table_args__ = (UniqueConstraint("user_id", "problem_revision_id", name="uq_user_problem_draft"),)


class Submission(Base):
    """Неизменяемая посылка (IDE-004) — ссылается на точную ревизию задачи."""

    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    problem_revision_id = Column(Integer, ForeignKey("problem_revisions.id"), nullable=False, index=True)
    code = Column(Text, nullable=False)
    language = Column(String(32), nullable=False, default="python3")
    status = Column(SQLEnum(SubmissionStatus), nullable=False, default=SubmissionStatus.CREATED)
    # JDG-012: приоритет в очереди — выше забирается раньше (например, ручной
    # перезапуск после починки Checker'а получает приоритет выше обычных посылок).
    priority = Column(Integer, nullable=False, default=0)
    verdict = Column(SQLEnum(Verdict), nullable=True)
    score = Column(Float, nullable=True)
    stdout = Column(Text, nullable=True)
    stderr = Column(Text, nullable=True)
    manual_score_override = Column(Float, nullable=True)  # GRD-004: хранится отдельно от авто-результата
    manual_comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="submissions")
    problem_revision = relationship("ProblemRevision")


class Progress(Base):
    __tablename__ = "progress"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    completed_items = Column(Integer, nullable=False, default=0)
    total_items = Column(Integer, nullable=False, default=0)
    percent = Column(Float, nullable=False, default=0.0)
    points = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user = relationship("User")
    course = relationship("Course")

    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_user_course_progress"),)


class AuditEvent(Base):
    """RBAC-003, OBS-005: журналирование смены ролей, публикаций, ручных правок и т.д."""

    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(64), nullable=False)
    object_type = Column(String(64), nullable=False)
    object_id = Column(Integer, nullable=True)
    result = Column(String(16), nullable=False, default="ok")
    meta = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class NotificationType(str, enum.Enum):
    """NTF-001: назначение курса и результат ручной проверки — обязательные
    (нельзя отключить, NTF-003); приближение дедлайна — необязательное."""

    COURSE_ASSIGNED = "course_assigned"
    DEADLINE_APPROACHING = "deadline_approaching"
    MANUAL_REVIEW_RESULT = "manual_review_result"


MANDATORY_NOTIFICATION_TYPES = {NotificationType.COURSE_ASSIGNED, NotificationType.MANUAL_REVIEW_RESULT}


class Notification(Base):
    """NTF-001: внутренние уведомления. Email/push/мессенджеры (NTF-002) как
    каналы доставки не реализованы — см. README."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(SQLEnum(NotificationType), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


class NotificationPreference(Base):
    """NTF-003: пользователь управляет только необязательными типами —
    обязательные (MANDATORY_NOTIFICATION_TYPES) игнорируют этот флаг."""

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "type", name="uq_user_notification_type"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(SQLEnum(NotificationType), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)

    user = relationship("User")
