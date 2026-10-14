"""SSO: destination for the "Назад в кабинет" button comes only from the
HMAC-signed LMS token (claim `return_to`), never from a query param — stored
on User.return_to_url at login time and exposed via /api/auth/me so the
Layout header button keeps working across page reloads and after the
Codelab session itself expires (п.1/4/21 of the student-cabinet spec)."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import jwt

from app.config import settings
from app.models import User


def _sso_token(**overrides) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iss": "tirskix-lms",
        "aud": "codelab",
        "external_ref": "lp-student-555",
        "full_name": "Иванов Иван Александрович",
        "role": "student",
        "groups": [],
        "directions": [],
        "return_to": "https://tirskix.space/student-portal",
        "iat": now,
        "exp": now + timedelta(seconds=60),
        "jti": str(uuid4()),
    }
    payload.update(overrides)
    return jwt.encode(payload, settings.sso_kodex_shared_secret, algorithm="HS256")


def test_sso_login_stores_return_to_and_me_exposes_it(client, db_session):
    token = _sso_token()
    resp = client.get(f"/api/auth/sso?token={token}", follow_redirects=False)
    assert resp.status_code == 302

    user = db_session.query(User).filter(User.external_ref == "lp-student-555").first()
    assert user is not None
    assert user.return_to_url == "https://tirskix.space/student-portal"

    cookie = resp.cookies.get("codelab_session")
    me = client.get("/api/auth/me", cookies={"codelab_session": cookie})
    assert me.status_code == 200
    assert me.json()["return_to_url"] == "https://tirskix.space/student-portal"


def test_return_to_is_refreshed_on_repeat_login_with_new_destination(client, db_session):
    client.get(f"/api/auth/sso?token={_sso_token()}", follow_redirects=False)

    second_token = _sso_token(return_to="https://tirskix.space/student-portal/other")
    resp2 = client.get(f"/api/auth/sso?token={second_token}", follow_redirects=False)
    assert resp2.status_code == 302

    user = db_session.query(User).filter(User.external_ref == "lp-student-555").first()
    assert user.return_to_url == "https://tirskix.space/student-portal/other"


def test_missing_return_to_claim_leaves_field_null(client, db_session):
    now = datetime.now(timezone.utc)
    payload = {
        "iss": "tirskix-lms", "aud": "codelab", "external_ref": "lp-student-556",
        "full_name": "Петров Пётр", "role": "student", "groups": [], "directions": [],
        "iat": now, "exp": now + timedelta(seconds=60), "jti": str(uuid4()),
    }
    token = jwt.encode(payload, settings.sso_kodex_shared_secret, algorithm="HS256")
    client.get(f"/api/auth/sso?token={token}", follow_redirects=False)

    user = db_session.query(User).filter(User.external_ref == "lp-student-556").first()
    assert user.return_to_url is None


def test_tampered_signature_is_rejected(client):
    bad_token = _sso_token() + "tampered"
    resp = client.get(f"/api/auth/sso?token={bad_token}", follow_redirects=False)
    assert resp.status_code == 401
