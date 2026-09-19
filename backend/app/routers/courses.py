"""LMS-001, LMS-005, LMS-006, TASK-001..004 — минимальный конструктор курса/задачи
для методиста. Иерархия курс→модуль→...→учебный элемент и полноценный редактор
контента (раздел 5.3) сюда пока не входят — см. README, раздел «не реализовано»."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models import AuditEvent, Course, CourseStatus, CourseVersion, ProblemRevision, User
from app.schemas import CourseCreate, CourseOut, ProblemRevisionCreate, ProblemRevisionOut
from app.services.lms_client import notify_course_webhook

router = APIRouter()


@router.get("", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Course)
    if user.role == "student":
        query = query.filter(Course.status == CourseStatus.PUBLISHED)
    return query.order_by(Course.id).all()


@router.post("", response_model=CourseOut)
def create_course(payload: CourseCreate, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    course = Course(title=payload.title, slug=payload.slug, description=payload.description, created_by_id=user.id)
    db.add(course)
    db.flush()
    db.add(CourseVersion(course_id=course.id, version_number=1))
    db.commit()
    db.refresh(course)
    return course


@router.post("/{course_id}/tasks", response_model=ProblemRevisionOut)
def create_task(
    course_id: int,
    payload: ProblemRevisionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("methodist", "admin")),
):
    """Создаёт задачу (первую ревизию). Привязка к дереву курса — TODO, см. README."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    last = db.query(ProblemRevision).order_by(ProblemRevision.task_id.desc()).first()
    next_task_id = (last.task_id + 1) if last else 1
    revision = ProblemRevision(
        task_id=next_task_id,
        revision_number=1,
        author_id=user.id,
        **payload.model_dump(exclude={"tests"}),
        tests=[t.model_dump() for t in payload.tests],
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    return revision


@router.post("/{course_id}/publish", response_model=CourseOut)
async def publish_course(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    """LMS-005/006/010: публикация создаёт неизменяемую версию. Проверка целостности
    перед публикацией (LMS-010) здесь упрощена — TODO перед проды."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    course.status = CourseStatus.PUBLISHED
    db.add(AuditEvent(actor_id=user.id, action="course_publish", object_type="course", object_id=course.id))
    db.commit()
    db.refresh(course)

    await notify_course_webhook(course, "published")
    return course


@router.post("/{course_id}/unpublish", response_model=CourseOut)
async def unpublish_course(course_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("methodist", "admin"))):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    course.status = CourseStatus.ARCHIVED
    db.add(AuditEvent(actor_id=user.id, action="course_unpublish", object_type="course", object_id=course.id))
    db.commit()
    db.refresh(course)

    await notify_course_webhook(course, "unpublished")
    return course
