"""EDT-002, EDT-008, SEC-005: общая логика сохранения загруженного файла —
используется и cookie-сессией методиста (routers/uploads.py, дев-путь), и
серверным admin-API от LMS (routers/lms_admin.py, основной путь)."""
import mimetypes
import uuid
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.schemas import UploadOut

UPLOADS_ROOT = Path(settings.uploads_dir)
UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)


async def save_upload(filename: str, read_chunk) -> UploadOut:
    """read_chunk(n) — awaitable, как UploadFile.read(n)."""
    ext = Path(filename or "").suffix.lstrip(".").lower()
    allowed = settings.upload_allowed_extensions
    if ext not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Формат .{ext or '?'} не разрешён. Разрешены: {', '.join(sorted(allowed))}",
        )

    max_size = allowed[ext]
    data = await read_chunk(max_size + 1)
    if len(data) > max_size:
        raise HTTPException(status_code=413, detail=f"Файл больше {max_size // (1024 * 1024)} МБ")
    if len(data) == 0:
        raise HTTPException(status_code=422, detail="Пустой файл")

    # Безопасное имя — случайное, не то, что прислал клиент (SEC-005/SEC-006:
    # без этого можно было бы получить путь вида "../../app/main.py").
    safe_name = f"{uuid.uuid4().hex}.{ext}"
    (UPLOADS_ROOT / safe_name).write_bytes(data)

    content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    return UploadOut(url=f"/uploads/{safe_name}", content_type=content_type, size=len(data))
