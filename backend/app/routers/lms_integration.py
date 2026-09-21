"""Эндпоинты, вызываемые сервером портала (learning-portal-main/backend/app/services/
codelab_sso.py). Контракт зафиксирован там — менять только синхронно с той стороной."""
from fastapi import APIRouter, Body, Header, HTTPException, Request, status
from sqlalchemy.orm import Session
from fastapi import Depends

from app.database import get_db
from app.models import Course, Enrollment, EnrollmentStatus, NotificationType, User
from app.security import verify_lms_signature
from app.services.notifications import notify
from app.services.progress import compute_progress_for_lms

router = APIRouter()


def _check_signature(external_ref: str, signature: str) -> None:
    if not verify_lms_signature(external_ref.encode(), signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверная подпись")


@router.get("/internal/lms-progress/{external_ref}")
def lms_progress(
    external_ref: str,
    db: Session = Depends(get_db),
    x_lp_signature: str = Header(default=""),
):
    _check_signature(external_ref, x_lp_signature)
    user = db.query(User).filter(User.external_ref == external_ref).first()
    if not user:
        raise HTTPException(status_code=404, detail="Ученик ещё не заходил в Codelab")

    data = compute_progress_for_lms(db, user)
    if data is None:
        raise HTTPException(status_code=404, detail="Ученик ещё не отправлял решений")
    return data


@router.post("/admin/courses/{course_id}/enroll")
def enroll(
    course_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    x_lp_signature: str = Header(default=""),
):
    external_ref = payload.get("externalRef")
    if not external_ref:
        raise HTTPException(status_code=422, detail="externalRef обязателен")
    _check_signature(external_ref, x_lp_signature)

    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    user = db.query(User).filter(User.external_ref == external_ref).first()
    if not user:
        # Ученик ещё не заходил по SSO — создаём учётку заранее, чтобы зачисление сработало.
        user = User(external_ref=external_ref, full_name=external_ref, role="student")
        db.add(user)
        db.flush()

    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == user.id, Enrollment.course_id == course_id)
        .first()
    )
    is_new_or_reactivated = not enrollment or enrollment.status == EnrollmentStatus.REVOKED
    if enrollment:
        enrollment.status = EnrollmentStatus.ACTIVE
        enrollment.course_version_id = course.active_version_id
    else:
        # MGR-003: назначение фиксирует точную версию курса на момент выдачи.
        db.add(Enrollment(
            user_id=user.id,
            course_id=course_id,
            course_version_id=course.active_version_id,
            status=EnrollmentStatus.ACTIVE,
            source="lms",
        ))
    db.commit()

    if is_new_or_reactivated:
        # NTF-001: уведомление о назначении курса.
        notify(db, user.id, NotificationType.COURSE_ASSIGNED, f"Вам назначен курс «{course.title}»")

    return {"ok": True}


@router.delete("/admin/courses/{course_id}/enroll/{external_ref}")
def unenroll(
    course_id: int,
    external_ref: str,
    db: Session = Depends(get_db),
    x_lp_signature: str = Header(default=""),
):
    _check_signature(external_ref, x_lp_signature)

    user = db.query(User).filter(User.external_ref == external_ref).first()
    if not user:
        raise HTTPException(status_code=404, detail="Ученик не найден")

    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == user.id, Enrollment.course_id == course_id)
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Зачисление не найдено")

    # MGR-004: отзыв доступа не удаляет историю прогресса и попыток.
    enrollment.status = EnrollmentStatus.REVOKED
    db.commit()
    return {"ok": True}
