"""EDT-002/008, SEC-005: allowlist форматов, лимит размера, безопасное имя файла."""
import io

from tests.conftest import as_user, make_user


def test_upload_rejects_disallowed_extension(client, db_session):
    methodist = make_user(db_session, "methodist")
    as_user(client, methodist)

    resp = client.post(
        "/api/uploads",
        files={"file": ("evil.exe", io.BytesIO(b"MZ..."), "application/octet-stream")},
    )
    assert resp.status_code == 422


def test_upload_rejects_oversized_file(client, db_session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "upload_max_image_mb", 0)  # лимит 0 МБ — любой файл больше
    methodist = make_user(db_session, "methodist")
    as_user(client, methodist)

    resp = client.post(
        "/api/uploads",
        files={"file": ("pic.png", io.BytesIO(b"x" * 1024), "image/png")},
    )
    assert resp.status_code == 413


def test_upload_accepts_allowed_image_and_uses_safe_name(client, db_session):
    methodist = make_user(db_session, "methodist")
    as_user(client, methodist)

    resp = client.post(
        "/api/uploads",
        files={"file": ("../../etc/passwd.png", io.BytesIO(b"fake-png-bytes"), "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith("/uploads/")
    # Имя файла на диске — не то, что прислал клиент (SEC-005/SEC-006: без этого
    # был бы path traversal через переданное имя).
    assert ".." not in body["url"]
    assert "passwd" not in body["url"]
    assert body["size"] == len(b"fake-png-bytes")


def test_upload_requires_methodist_role(client, db_session):
    student = make_user(db_session, "student")
    as_user(client, student)

    resp = client.post(
        "/api/uploads",
        files={"file": ("pic.png", io.BytesIO(b"data"), "image/png")},
    )
    assert resp.status_code == 403
