from datetime import timezone

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import decode_local_session_token


def get_current_user(
    codelab_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    decoded = decode_local_session_token(codelab_session) if codelab_session else None
    if not decoded:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Не авторизован")
    user_id, issued_at = decoded
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.is_blocked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Аккаунт недоступен")

    invalidated_at = user.sessions_invalidated_at
    if invalidated_at is not None:
        if invalidated_at.tzinfo is None:  # см. services/analytics.py — особенность SQLite
            invalidated_at = invalidated_at.replace(tzinfo=timezone.utc)
        if issued_at < invalidated_at:
            # IAM-004: администратор завершил сессии этого пользователя ПОСЛЕ
            # выдачи этого токена — токен больше не действителен.
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия завершена администратором")

    return user


def require_role(*roles: str):
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return user

    return _check
