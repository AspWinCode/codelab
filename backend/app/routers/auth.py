"""IAM-001..003: вход по SSO-токену от портала."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import AuditEvent, Course, Enrollment, EnrollmentStatus, NotificationType, User
from app.schemas import MeOut
from app.security import create_local_session_token, verify_lms_sso_token
from app.services.notifications import notify

router = APIRouter()


@router.get("/sso")
def sso_login(response: Response, token: str = Query(...), course: int | None = Query(default=None), db: Session = Depends(get_db)):
    try:
        payload = verify_lms_sso_token(token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    external_ref = payload["external_ref"]
    user = db.query(User).filter(User.external_ref == external_ref).first()
    is_new = user is None
    if not user:
        # IAM-002: создаём локальную учётку по доверенным атрибутам SSO при первом входе.
        user = User(
            external_ref=external_ref,
            full_name=payload.get("full_name", external_ref),
            role=payload.get("role", "student"),
            groups=payload.get("groups", []),
            directions=payload.get("directions", []),
        )
        db.add(user)
        db.flush()
    else:
        user.full_name = payload.get("full_name", user.full_name)
        user.groups = payload.get("groups", user.groups)
        user.directions = payload.get("directions", user.directions)

    if user.is_blocked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Аккаунт заблокирован")

    newly_enrolled_course_title = None
    if course is not None:
        enrollment = (
            db.query(Enrollment)
            .filter(Enrollment.user_id == user.id, Enrollment.course_id == course)
            .first()
        )
        if not enrollment:
            course_obj = db.query(Course).filter(Course.id == course).first()
            if course_obj:
                # MGR-003: назначение фиксирует точную версию курса на момент выдачи.
                db.add(Enrollment(
                    user_id=user.id,
                    course_id=course,
                    course_version_id=course_obj.active_version_id,
                    status=EnrollmentStatus.ACTIVE,
                    source="lms",
                ))
                newly_enrolled_course_title = course_obj.title
        elif enrollment.status == EnrollmentStatus.REVOKED:
            enrollment.status = EnrollmentStatus.ACTIVE

    db.add(AuditEvent(
        actor_id=user.id,
        action="sso_login",
        object_type="user",
        object_id=user.id,
        meta={"new_account": is_new, "course": course},
    ))
    db.commit()

    if newly_enrolled_course_title:
        # NTF-001: уведомление о назначении курса — на случай, если ученик
        # оказался зачислен именно здесь (без предварительного enroll() от LMS).
        notify(db, user.id, NotificationType.COURSE_ASSIGNED, f"Вам назначен курс «{newly_enrolled_course_title}»")

    session_token = create_local_session_token(user.id)
    response = Response(status_code=status.HTTP_302_FOUND)
    response.headers["Location"] = (
        f"{settings.frontend_base_url}/courses/{course}" if course else settings.frontend_base_url
    )
    response.set_cookie(
        "codelab_session",
        session_token,
        httponly=True,
        samesite="lax",
        secure=settings.frontend_base_url.startswith("https"),
        max_age=12 * 3600,
    )
    return response


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("codelab_session")
    return {"ok": True}
