"""EDT-002/008: серверная (HMAC) загрузка файла — методист работает через
свой аккаунт LMS, у него нет cookie-сессии Codelab (routers/uploads.py),
поэтому нужен отдельный путь на admin-API (лежит в одном общем сервисе,
app/services/uploads.py, с cookie-путём — без дублирования правил)."""
import hashlib
import hmac
import io

from app.config import settings


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Методист", role="methodist"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


def test_upload_requires_valid_signature(client):
    resp = client.post(
        f"/api/lms-admin/uploads?{_staff_qs()}",
        files={"file": ("pic.png", io.BytesIO(b"fake-png-bytes"), "image/png")},
        headers={"X-LP-Signature": "wrong"},
    )
    assert resp.status_code == 401


def test_upload_image_ok(client):
    resp = client.post(
        f"/api/lms-admin/uploads?{_staff_qs()}",
        files={"file": ("pic.png", io.BytesIO(b"fake-png-bytes"), "image/png")},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith("/uploads/")
    assert body["content_type"] == "image/png"


def test_upload_rejects_disallowed_extension(client):
    resp = client.post(
        f"/api/lms-admin/uploads?{_staff_qs()}",
        files={"file": ("script.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 422


def test_upload_available_to_teacher_role_too(client):
    """Загрузка нужна только методисту (авторство), но резолвер стаффа
    (resolve_staff_user) не различает роли на этом эндпоинте — сверяем, что
    он хотя бы не падает 4xx на другой валидной роли, раз явного запрета нет."""
    resp = client.post(
        f"/api/lms-admin/uploads?{_staff_qs(role='teacher')}",
        files={"file": ("pic.png", io.BytesIO(b"fake-png-bytes"), "image/png")},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 200
