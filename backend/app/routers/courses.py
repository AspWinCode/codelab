"""Прямой вход методиста в браузер Codelab по SSO-cookie. По решению от
2026-09-21 это больше не основной путь — методист и преподаватель работают
через свой аккаунт LMS (см. app/routers/lms_admin.py, README, раздел
«Интеграция с порталом»). Эндпоинты здесь оставлены как рабочий низкоуровневый
путь для локальной отладки Codelab без портала и как основа, которую
переиспользует app/services/course_admin.py."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models import Course, CourseStatus, Enrollment, LearningItem, User
from app.schemas import (
    CourseCreate,
    CourseOut,
    LastPositionIn,
    LearningItemCreate,
    LearningItemOut,
    LearningItemTree,
    LearningItemUpdate,
    ProblemRevisionCreate,
    ProblemRevisionOut,
    RerunSubmissionsIn,
    RerunSubmissionsOut,
)
from app.services import course_admin

router = APIRouter()


@router.get("", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Course)
    if user.role == "student":
        query = query.filter(Course.status == CourseStatus.PUBLISHED)
    elif user.role == "methodist":
        query = query.filter(Course.created_by_id == user.id)
    return query.order_by(Course.id).all()


@router.post("", response_model=CourseOut)
def create_course(payload: CourseCreate, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    return course_admin.create_course(db, payload, created_by_id=user.id)


@router.post("/{course_id}/tasks", response_model=ProblemRevisionOut)
def create_task(
    course_id: int,
    payload: ProblemRevisionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    return course_admin.create_task(db, course_id, payload, author_id=user.id)


@router.post("/{course_id}/items", response_model=LearningItemOut)
def create_item(
    course_id: int,
    payload: LearningItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    return course_admin.create_item(db, course_id, payload)


@router.get("/items/{item_id}", response_model=LearningItemOut)
def get_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    item = db.query(LearningItem).filter(LearningItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Элемент не найден")
    return item


@router.put("/items/{item_id}", response_model=LearningItemOut)
def update_item(
    item_id: int,
    payload: LearningItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    _, course = course_admin.get_course_for_item(db, item_id)
    course_admin.ensure_course_owner(course, user)
    return course_admin.update_item(db, item_id, payload)


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    _, course = course_admin.get_course_for_item(db, item_id)
    course_admin.ensure_course_owner(course, user)
    course_admin.delete_item(db, item_id)
    return {"ok": True}


@router.get("/{course_id}/tree", response_model=list[LearningItemTree])
def get_tree(course_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    if user.role == "student":
        # STU-002/STU-003: ученик видит только опубликованную версию, прогресс
        # считается по ней и не может поменяться из-за правок черновика.
        if not course.active_version_id:
            raise HTTPException(status_code=404, detail="Курс ещё не опубликован")
        version_id = course.active_version_id
    else:
        course_admin.ensure_course_owner(course, user)
        version_id = course_admin.get_draft_version(db, course_id).id

    items = db.query(LearningItem).filter(LearningItem.course_version_id == version_id).order_by(LearningItem.position).all()

    if user.role != "student":
        return course_admin.build_tree(items)
    return course_admin.build_student_tree(db, user.id, items)


@router.put("/{course_id}/last-position")
def set_last_position(
    course_id: int,
    payload: LastPositionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """STU-005: сохраняет последнюю открытую позицию в материале курса —
    "продолжить обучение с неё" на главной странице ученика."""
    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == user.id, Enrollment.course_id == course_id)
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Вы не записаны на этот курс")

    item = db.query(LearningItem).filter(LearningItem.id == payload.item_id).first()
    if not item or item.course_version_id != enrollment.course_version_id:
        raise HTTPException(status_code=422, detail="Элемент не относится к назначенной версии курса")

    enrollment.last_item_id = payload.item_id
    db.commit()
    return {"ok": True}


@router.post("/{course_id}/publish", response_model=CourseOut)
async def publish_course(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    return await course_admin.publish_course(db, course_id, actor_id=user.id)


@router.post("/{course_id}/unpublish", response_model=CourseOut)
async def unpublish_course(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    return await course_admin.unpublish_course(db, course_id, actor_id=user.id)


@router.post("/{course_id}/submissions/rerun", response_model=RerunSubmissionsOut)
def rerun_submissions(
    course_id: int,
    payload: RerunSubmissionsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    """TASK-007: массовая перепроверка после исправления тестов задачи."""
    course_admin.ensure_course_owner(course_admin.get_course_or_404(db, course_id), user)
    requeued = course_admin.rerun_submissions(db, course_id, payload.submission_ids)
    return RerunSubmissionsOut(requeued=requeued)
