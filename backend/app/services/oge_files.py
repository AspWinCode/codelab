"""Необязательный файл к попытке ОГЭ (например, фото решения на бумаге) —
приватное хранилище, как у проектов (services/project_files.py), но со своим
allowlist: сюда ожидаются фото/сканы, а не исходный код."""
import uuid
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.services.file_security import has_shebang, is_compiled_binary, matches_extension
from app.services.project_files import SavedProjectFile

OGE_UPLOADS_ROOT = Path(settings.oge_uploads_dir)
OGE_UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)


async def save_oge_file(filename: str, content_type: str, read_chunk) -> SavedProjectFile:
    """read_chunk(n) — awaitable, как UploadFile.read(n)."""
    ext = Path(filename or "").suffix.lstrip(".").lower()
    allowed = settings.upload_allowed_oge_extensions
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

    # Этап 11 (ТЗ): это фото/сканы решения — шебанг тут заведомо не нужен,
    # как и бинарник под любым расширением.
    if is_compiled_binary(data) or has_shebang(data):
        raise HTTPException(status_code=422, detail="Файл похож на исполняемый — такие загрузки запрещены")
    if not matches_extension(data, ext):
        raise HTTPException(status_code=422, detail=f"Содержимое файла не похоже на формат .{ext}")

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    (OGE_UPLOADS_ROOT / stored_name).write_bytes(data)

    return SavedProjectFile(
        stored_name=stored_name,
        content_type=content_type or "application/octet-stream",
        size=len(data),
    )


def oge_file_path(stored_name: str) -> Path:
    return OGE_UPLOADS_ROOT / stored_name
