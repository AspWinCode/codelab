"""NTF-001/003: создание внутренних уведомлений с учётом настроек
пользователя. Email/push/мессенджеры (NTF-002) — не реализованы, см. README."""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import MANDATORY_NOTIFICATION_TYPES, Notification, NotificationPreference, NotificationType


def is_enabled(db: Session, user_id: int, ntype: NotificationType) -> bool:
    if ntype in MANDATORY_NOTIFICATION_TYPES:
        return True
    pref = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user_id, NotificationPreference.type == ntype)
        .first()
    )
    return pref.enabled if pref else True  # по умолчанию включено, пока явно не выключили


def notify(db: Session, user_id: int, ntype: NotificationType, title: str, body: Optional[str] = None) -> None:
    if not is_enabled(db, user_id, ntype):
        return
    db.add(Notification(user_id=user_id, type=ntype, title=title, body=body))
    db.commit()
