"""NTF-001/003: список внутренних уведомлений ученика и управление
необязательными типами (обязательные — MANDATORY_NOTIFICATION_TYPES —
нельзя отключить)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import MANDATORY_NOTIFICATION_TYPES, Notification, NotificationPreference, NotificationType, User
from app.schemas import NotificationOut, NotificationPreferenceOut, NotificationPreferenceUpdate

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    return query.order_by(Notification.created_at.desc()).limit(50).all()


@router.put("/notifications/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .first()
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    notification.is_read = True
    db.commit()
    return {"ok": True}


@router.get("/notification-preferences", response_model=list[NotificationPreferenceOut])
def get_preferences(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prefs = {p.type: p.enabled for p in db.query(NotificationPreference).filter(NotificationPreference.user_id == user.id)}
    return [
        NotificationPreferenceOut(
            type=t.value,
            enabled=True if t in MANDATORY_NOTIFICATION_TYPES else prefs.get(t, True),
            mandatory=t in MANDATORY_NOTIFICATION_TYPES,
        )
        for t in NotificationType
    ]


@router.put("/notification-preferences/{notification_type}", response_model=NotificationPreferenceOut)
def update_preference(
    notification_type: str,
    payload: NotificationPreferenceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        ntype = NotificationType(notification_type)
    except ValueError:
        raise HTTPException(status_code=422, detail="Неизвестный тип уведомления")
    if ntype in MANDATORY_NOTIFICATION_TYPES:
        raise HTTPException(status_code=422, detail="Этот тип уведомлений обязателен и не может быть отключён")

    pref = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user.id, NotificationPreference.type == ntype)
        .first()
    )
    if pref:
        pref.enabled = payload.enabled
    else:
        pref = NotificationPreference(user_id=user.id, type=ntype, enabled=payload.enabled)
        db.add(pref)
    db.commit()
    return NotificationPreferenceOut(type=ntype.value, enabled=payload.enabled, mandatory=False)
