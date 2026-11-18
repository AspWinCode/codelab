"""EDT-002/008: серверная (HMAC) загрузка файла — методист работает через
свой аккаунт LMS, у него нет cookie-сессии Codelab (routers/uploads.py),
поэтому нужен отдельный путь на admin-API (лежит в одном общем сервисе,
app/services/uploads.py, с cookie-путём — без дублирования правил)."""
import hashlib
import hmac
import io

import pytest

from app.config import settings


def _sig(external_ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), external_ref.encode(), hashlib.sha256).hexdigest()


def _staff_qs(external_ref="lp-user-1", full_name="Иван Методист", role="methodist"):
    return f"staff_external_ref={external_ref}&staff_full_name={full_name}&staff_role={role}"


PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"fake-rest-of-png"

# Этап 11 (ТЗ): с проверкой MIME по содержимому фиктивные байты без
# правильной магической сигнатуры больше не проходят — каждому расширению
# нужны байты, с которых реально начинается такой файл.
ATTACHMENT_MAGIC = {
    "task.doc": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"rest-of-doc",
    "task.docx": b"PK\x03\x04" + b"rest-of-docx",
    "task.rar": b"Rar!\x1a\x07" + b"rest-of-rar",
    "task.zip": b"PK\x03\x04" + b"rest-of-zip",
}


def test_upload_requires_valid_signature(client):
    resp = client.post(
        f"/api/lms-admin/uploads?{_staff_qs()}",
        files={"file": ("pic.png", io.BytesIO(PNG_MAGIC), "image/png")},
        headers={"X-LP-Signature": "wrong"},
    )
    assert resp.status_code == 401


def test_upload_image_ok(client):
    resp = client.post(
        f"/api/lms-admin/uploads?{_staff_qs()}",
        files={"file": ("pic.png", io.BytesIO(PNG_MAGIC), "image/png")},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith("/uploads/")
    assert body["content_type"] == "image/png"


def test_upload_rejects_content_not_matching_claimed_extension(client):
    """Этап 11 (ТЗ): MIME проверяется по содержимому — произвольные байты
    под разрешённым расширением (но не похожие на этот формат) отклоняются,
    даже если расширение само по себе в allowlist."""
    resp = client.post(
        f"/api/lms-admin/uploads?{_staff_qs()}",
        files={"file": ("pic.png", io.BytesIO(b"not actually a png"), "image/png")},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 422


def test_upload_rejects_renamed_executable(client):
    """Этап 11 (ТЗ): переименованный .exe в .png всё равно отклоняется —
    универсальный запрет исполняемых файлов работает независимо от
    расширения, которое прислал клиент."""
    resp = client.post(
        f"/api/lms-admin/uploads?{_staff_qs()}",
        files={"file": ("totally-a-pic.png", io.BytesIO(b"MZ" + b"\x00" * 30), "image/png")},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("filename", ["task.doc", "task.docx", "task.rar", "task.zip"])
def test_upload_task_attachment_formats_ok(client, filename):
    resp = client.post(
        f"/api/lms-admin/uploads?{_staff_qs()}",
        files={"file": (filename, io.BytesIO(ATTACHMENT_MAGIC[filename]), "application/octet-stream")},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("/uploads/")


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
        files={"file": ("pic.png", io.BytesIO(PNG_MAGIC), "image/png")},
        headers={"X-LP-Signature": _sig("lp-user-1")},
    )
    assert resp.status_code == 200
