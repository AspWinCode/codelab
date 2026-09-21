"""IAM-004: блокировка аккаунта, завершение сессий, история входов."""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from jose import jwt as jose_jwt

from app.config import settings
from app.models import LoginEvent, User
from app.security import ALGORITHM, create_local_session_token


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-admin-1", full_name="Админ", role="admin"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


def test_non_admin_staff_gets_403(client):
    resp = client.get(
        f"/api/lms-admin/admin/users?{_staff_qs(role='methodist')}",
        headers={"X-LP-Signature": _sig("lp-admin-1")},
    )
    assert resp.status_code == 403


def test_block_user_rejects_cookie_session(client, db_session):
    student = User(external_ref="lp-student-2", full_name="Студент", role="student")
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)

    token = create_local_session_token(student.id)
    client.cookies.set("codelab_session", token)

    resp = client.get("/api/auth/me")
    assert resp.status_code == 200

    qs = _staff_qs()
    sig = _sig("lp-admin-1")
    block_resp = client.put(
        f"/api/lms-admin/admin/users/{student.id}/block?{qs}",
        json={"blocked": True},
        headers={"X-LP-Signature": sig},
    )
    assert block_resp.status_code == 200

    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def _token_with_iat(user_id: int, iat: datetime) -> str:
    """Строит токен с явным iat — JWT хранит его с точностью до секунды, а
    sessions_invalidated_at пишется с микросекундами, поэтому сравнение
    вплотную к границе секунды нестабильно на реальных часах; тест берёт
    заведомый зазор в обе стороны вместо гонки со временем."""
    payload = {"sub": str(user_id), "iat": iat, "exp": iat + timedelta(hours=12)}
    return jose_jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def test_terminate_sessions_invalidates_old_token_not_new(client, db_session):
    student = User(external_ref="lp-student-3", full_name="Студент", role="student")
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)

    now = datetime.now(timezone.utc)
    old_token = _token_with_iat(student.id, now - timedelta(minutes=1))

    qs = _staff_qs()
    sig = _sig("lp-admin-1")
    resp = client.post(
        f"/api/lms-admin/admin/users/{student.id}/terminate-sessions?{qs}",
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200

    client.cookies.set("codelab_session", old_token)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401

    new_token = _token_with_iat(student.id, now + timedelta(minutes=1))
    client.cookies.set("codelab_session", new_token)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200


def test_login_history_recorded_and_listed(client, db_session):
    student = User(external_ref="lp-student-4", full_name="Студент", role="student")
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)

    db_session.add(LoginEvent(user_id=student.id))
    db_session.add(LoginEvent(user_id=student.id))
    db_session.commit()

    qs = _staff_qs()
    sig = _sig("lp-admin-1")
    resp = client.get(
        f"/api/lms-admin/admin/users/{student.id}/login-history?{qs}",
        headers={"X-LP-Signature": sig},
    )
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 2


def test_list_users_search(client, db_session):
    db_session.add(User(external_ref="lp-alpha", full_name="Алиса Иванова", role="student"))
    db_session.add(User(external_ref="lp-beta", full_name="Борис Петров", role="student"))
    db_session.commit()

    qs = _staff_qs()
    sig = _sig("lp-admin-1")
    resp = client.get(f"/api/lms-admin/admin/users?q=Алиса&{qs}", headers={"X-LP-Signature": sig})
    assert resp.status_code == 200
    names = [u["full_name"] for u in resp.json()]
    assert "Алиса Иванова" in names
    assert "Борис Петров" not in names
