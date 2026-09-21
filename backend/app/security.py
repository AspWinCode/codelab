"""Проверка JWT от портала (SSO) и HMAC-подписи серверных запросов между системами.
Общий секрет SSO_KODEX_SHARED_SECRET — тот же, что у портала (не путать с локальным
SECRET_KEY сессий codelab)."""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from app.config import settings

ALGORITHM = "HS256"


def verify_lms_sso_token(token: str) -> dict:
    """Проверяет одноразовый JWT портала: подпись, aud="codelab", срок действия."""
    if not settings.sso_kodex_shared_secret:
        raise ValueError("SSO_KODEX_SHARED_SECRET не настроен")
    try:
        payload = jwt.decode(
            token,
            settings.sso_kodex_shared_secret,
            algorithms=[ALGORITHM],
            audience="codelab",
        )
    except JWTError as e:
        raise ValueError(f"Недействительный SSO-токен: {e}")
    return payload


def verify_lms_signature(body: bytes, signature: str) -> bool:
    """HMAC(body, secret) — для входящих вебхуков/запросов от портала."""
    if not settings.sso_kodex_shared_secret or not signature:
        return False
    expected = hmac.new(
        settings.sso_kodex_shared_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def sign_for_lms(payload: bytes) -> str:
    """HMAC подписи исходящих запросов к порталу (например, вебхук публикации курса)."""
    return hmac.new(
        settings.sso_kodex_shared_secret.encode(), payload, hashlib.sha256
    ).hexdigest()


def create_local_session_token(user_id: int, ttl_hours: int = 12) -> str:
    """Локальная сессия codelab после успешного SSO — отдельный секрет от SSO_KODEX_SHARED_SECRET."""
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=ttl_hours)}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_local_session_token(token: str) -> Optional[tuple[int, datetime]]:
    """(user_id, issued_at) — issued_at нужен app/deps.py, чтобы отклонять
    токены, выданные до User.sessions_invalidated_at (IAM-004: "завершить
    активные сессии" для JWT без состояния на сервере)."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        issued_at = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        return int(payload["sub"]), issued_at
    except (JWTError, KeyError, ValueError):
        return None
