"""Подписанный сервер-к-серверу API для learning-portal-main: методист и
преподаватель работают через свой аккаунт LMS, не заходя в Codelab напрямую
(решение от 2026-09-21, см. README «Интеграция с порталом»). LMS уже проверила
роль и права пользователя на своей стороне — здесь только доверяем подписи
общим секретом (как enroll/unenroll/lms-progress в lms_integration.py) и
заводим/обновляем лёгкую учётку методиста/преподавателя в Codelab для
атрибуции (created_by_id, AuditEvent.actor_id).

Контракт согласован с backend/app/services/codelab_studio.py в
learning-portal-main — менять пути и подпись запроса только синхронно с той
стороной.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Course, LearningItem, LoginEvent, User
from app.schemas import (
    AdminLoginEventOut,
    AdminSystemStatusOut,
    AdminUserBlockIn,
    AdminUserOut,
    CourseAnalyticsOut,
    CourseCreate,
    CourseOut,
    LearningItemCreate,
    LearningItemOut,
    LearningItemTree,
    LearningItemUpdate,
    ManualGradeIn,
    ProblemRevisionCreate,
    ProblemRevisionOut,
    RerunSubmissionsIn,
    RerunSubmissionsOut,
    SubmissionOut,
    SubmissionReviewOut,
)
from app.security import verify_lms_signature
from app.services import admin_status, analytics, course_admin
from app.services.progress_calc import apply_manual_grade

router = APIRouter()


def resolve_staff_user(
    db: Session = Depends(get_db),
    staff_external_ref: str = Query(..., description='Например "lp-user-42"'),
    staff_full_name: str = Query(...),
    staff_role: str = Query(..., description="methodist | teacher | admin"),
    x_lp_signature: str = Header(default=""),
) -> User:
    if staff_role not in ("methodist", "teacher", "admin"):
        raise HTTPException(status_code=422, detail="Недопустимая роль")
    if not verify_lms_signature(staff_external_ref.encode(), x_lp_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверная подпись")

    user = db.query(User).filter(User.external_ref == staff_external_ref).first()
    if not user:
        user = User(external_ref=staff_external_ref, full_name=staff_full_name, role=staff_role)
        db.add(user)
    else:
        user.full_name = staff_full_name
        user.role = staff_role
    db.commit()
    db.refresh(user)
    return user


@router.get("/courses", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """RBAC-002: методист видит только свои курсы (для управления ими).
    Teacher/admin видят все опубликованные курсы платформы — им нужно
    выбирать среди курсов, которые создавали разные методисты, чтобы
    посмотреть посылки/аналитику своей группы, привязка "курс → методист"
    для этого не имеет значения."""
    query = db.query(Course)
    if staff.role == "methodist":
        query = query.filter(Course.created_by_id == staff.id)
    return query.order_by(Course.id).all()


@router.post("/courses", response_model=CourseOut)
def create_course(payload: CourseCreate, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    return course_admin.create_course(db, payload, created_by_id=staff.id)


@router.post("/courses/{course_id}/tasks", response_model=ProblemRevisionOut)
def create_task(
    course_id: int,
    payload: ProblemRevisionCreate,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return course_admin.create_task(db, course_id, payload, author_id=staff.id)


@router.post("/courses/{course_id}/items", response_model=LearningItemOut)
def create_item(
    course_id: int,
    payload: LearningItemCreate,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return course_admin.create_item(db, course_id, payload)


@router.put("/items/{item_id}", response_model=LearningItemOut)
def update_item(
    item_id: int,
    payload: LearningItemUpdate,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    _, course = course_admin.get_course_for_item(db, item_id)
    course_admin.ensure_course_owner(course, staff)
    return course_admin.update_item(db, item_id, payload)


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    _, course = course_admin.get_course_for_item(db, item_id)
    course_admin.ensure_course_owner(course, staff)
    course_admin.delete_item(db, item_id)
    return {"ok": True}


@router.get("/courses/{course_id}/tree", response_model=list[LearningItemTree])
def get_tree(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """Всегда черновик — это рабочая версия методиста, не то, что видят ученики."""
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    version = course_admin.get_draft_version(db, course_id)
    items = db.query(LearningItem).filter(LearningItem.course_version_id == version.id).order_by(LearningItem.position).all()
    return course_admin.build_tree(items)


@router.post("/courses/{course_id}/publish", response_model=CourseOut)
async def publish_course(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return await course_admin.publish_course(db, course_id, actor_id=staff.id)


@router.post("/courses/{course_id}/unpublish", response_model=CourseOut)
async def unpublish_course(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return await course_admin.unpublish_course(db, course_id, actor_id=staff.id)


@router.get("/courses/{course_id}/submissions", response_model=list[SubmissionReviewOut])
def list_course_submissions(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """TCH-001/003: преподаватель/методист смотрит посылки учеников по курсу.
    RBAC-002: методисту — только по своим курсам; у преподавателя фильтрация
    по своим группам делается на стороне LMS (там есть группы), см. README."""
    if staff.role == "methodist":
        course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    return course_admin.list_course_submissions(db, course_id)


@router.put("/courses/{course_id}/submissions/{submission_id}/grade", response_model=SubmissionOut)
def grade_submission(
    course_id: int,
    submission_id: int,
    payload: ManualGradeIn,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """GRD-004/TCH-004: ручная корректировка результата с обязательным
    комментарием. course_id в пути — не только для методиста (RBAC-002:
    только свои курсы), но и чтобы LMS могла ДО вызова дёшево проверить, что
    посылка относится именно к тому курсу/группе, к которым у вызывающего
    тренера есть доступ (см. codelab.py в learning-portal-main) — раньше
    эндпоинт принимал только submission_id, и такую проверку сделать было
    нечем."""
    course = course_admin.get_course_or_404(db, course_id)
    if staff.role == "methodist":
        course_admin.ensure_course_owner(course, staff)

    actual_course = course_admin.get_course_for_submission(db, submission_id)
    if actual_course and actual_course.id != course_id:
        raise HTTPException(status_code=404, detail="Посылка не относится к указанному курсу")

    return apply_manual_grade(db, submission_id, payload.score, payload.comment)


@router.post("/courses/{course_id}/submissions/rerun", response_model=RerunSubmissionsOut)
def rerun_submissions(
    course_id: int,
    payload: RerunSubmissionsIn,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """TASK-007: массовая перепроверка после исправления тестов задачи.
    RBAC-002: методисту — только по своим курсам; в очередь встают только
    те посылки из переданного списка, чьи задачи реально принадлежат этому
    курсу (нельзя перезапустить чужую посылку, угадав id)."""
    if staff.role == "methodist":
        course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)
    requeued = course_admin.rerun_submissions(db, course_id, payload.submission_ids)
    return RerunSubmissionsOut(requeued=requeued)


@router.get("/courses/{course_id}/analytics", response_model=CourseAnalyticsOut)
def get_course_analytics(course_id: int, db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """ANA-001/002/005: сводка по курсу и рейтинг задач по сложности.
    RBAC-002: методисту — только по своим курсам."""
    from datetime import datetime, timezone

    if staff.role == "methodist":
        course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), staff)

    return CourseAnalyticsOut(
        generated_at=datetime.now(timezone.utc),
        overview=analytics.course_overview(db, course_id),
        tasks=analytics.task_difficulty(db, course_id),
    )


@router.get("/admin/status", response_model=AdminSystemStatusOut)
def get_system_status(db: Session = Depends(get_db), staff: User = Depends(resolve_staff_user)):
    """ADM-004: очередь, признаки живости воркера, недавние системные
    ошибки, ёмкость хранилища. Только администратор — не методист/преподаватель,
    это эксплуатационная, а не учебная информация."""
    if staff.role != "admin":
        raise HTTPException(status_code=403, detail="Доступно только администратору")
    return admin_status.get_system_status(db)


def _require_admin(staff: User) -> None:
    if staff.role != "admin":
        raise HTTPException(status_code=403, detail="Доступно только администратору")


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


@router.get("/admin/users", response_model=list[AdminUserOut])
def list_users(
    q: str | None = Query(default=None, description="Поиск по имени или external_ref"),
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """IAM-004: поиск пользователей для блокировки/просмотра истории входов."""
    _require_admin(staff)
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter((User.full_name.ilike(like)) | (User.external_ref.ilike(like)))
    return query.order_by(User.full_name).limit(50).all()


@router.put("/admin/users/{user_id}/block", response_model=AdminUserOut)
def set_user_blocked(
    user_id: int,
    payload: AdminUserBlockIn,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """IAM-004: блокировка/разблокировка учётной записи."""
    _require_admin(staff)
    user = _get_user_or_404(db, user_id)
    user.is_blocked = payload.blocked
    db.commit()
    db.refresh(user)
    return user


@router.post("/admin/users/{user_id}/terminate-sessions", response_model=AdminUserOut)
def terminate_user_sessions(
    user_id: int,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """IAM-004: "завершить активные сессии" — токены без состояния на сервере,
    поэтому отзываем все, выданные до текущего момента (см. app/deps.py)."""
    from datetime import datetime, timezone

    _require_admin(staff)
    user = _get_user_or_404(db, user_id)
    user.sessions_invalidated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


@router.get("/admin/users/{user_id}/login-history", response_model=list[AdminLoginEventOut])
def get_user_login_history(
    user_id: int,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """IAM-004: история входов пользователя."""
    _require_admin(staff)
    _get_user_or_404(db, user_id)
    return (
        db.query(LoginEvent)
        .filter(LoginEvent.user_id == user_id)
        .order_by(LoginEvent.created_at.desc())
        .limit(50)
        .all()
    )
