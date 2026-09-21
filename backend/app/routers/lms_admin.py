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
from app.models import Course, LearningItem, User
from app.schemas import (
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
    SubmissionOut,
    SubmissionReviewOut,
)
from app.security import verify_lms_signature
from app.services import analytics, course_admin
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


@router.put("/submissions/{submission_id}/grade", response_model=SubmissionOut)
def grade_submission(
    submission_id: int,
    payload: ManualGradeIn,
    db: Session = Depends(get_db),
    staff: User = Depends(resolve_staff_user),
):
    """GRD-004/TCH-004: ручная корректировка результата с обязательным комментарием.
    RBAC-002: методисту — только по своим курсам (если курс определить не
    удалось, проверять нечего — пропускаем, не блокируем легитимную оценку)."""
    if staff.role == "methodist":
        course = course_admin.get_course_for_submission(db, submission_id)
        if course:
            course_admin.ensure_course_owner(course, staff)
    return apply_manual_grade(db, submission_id, payload.score, payload.comment)


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
