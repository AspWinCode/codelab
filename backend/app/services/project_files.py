"""Хранение файлов, прикреплённых учеником к проекту (type=project).

В отличие от services/uploads.py (картинки/видео для редактора методиста —
публичная статика под /uploads), это приватное хранилище: файл отдаётся
только через авторизованный эндпоинт (routers/projects.py, routers/lms_admin.py),
никогда не маунтится как статика (см. app/main.py)."""
import uuid
from pathlib import Path

from fastapi import HTTPException

from app.config import settings

PROJECT_UPLOADS_ROOT = Path(settings.project_uploads_dir)
PROJECT_UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)


class SavedProjectFile:
    def __init__(self, stored_name: str, content_type: str, size: int):
        self.stored_name = stored_name
        self.content_type = content_type
        self.size = size


async def save_project_file(filename: str, content_type: str, read_chunk) -> SavedProjectFile:
    """read_chunk(n) — awaitable, как UploadFile.read(n)."""
    ext = Path(filename or "").suffix.lstrip(".").lower()
    allowed = settings.upload_allowed_project_extensions
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

    # Случайное имя на диске — не то, что прислал ученик (SEC-005/SEC-006,
    # как services/uploads.py::save_upload).
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    (PROJECT_UPLOADS_ROOT / stored_name).write_bytes(data)

    return SavedProjectFile(
        stored_name=stored_name,
        content_type=content_type or "application/octet-stream",
        size=len(data),
    )


def project_file_path(stored_name: str) -> Path:
    return PROJECT_UPLOADS_ROOT / stored_name


def delete_project_file(stored_name: str) -> None:
    path = project_file_path(stored_name)
    if path.exists():
        path.unlink()
