"""EDT-002, EDT-008, SEC-005: загрузка файлов для редактора контента —
allowlist форматов, лимит размера, безопасное имя (UUID, не имя от клиента),
исполняемые файлы запрещены по умолчанию (allowlist, а не blocklist —
неизвестное расширение отклоняется, а не пропускается).

Антивирусная проверка (SEC-005) и выдача через подписанный/контролируемый
URL — не реализованы, см. README; сейчас файл сразу доступен по прямой
статической ссылке.
"""
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi import File as FastAPIFile

from app.config import settings
from app.deps import require_role
from app.models import User
from app.schemas import UploadOut

router = APIRouter()

UPLOADS_ROOT = Path(settings.uploads_dir)
UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)


@router.post("", response_model=UploadOut)
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    user: User = Depends(require_role("methodist", "admin")),
):
    ext = Path(file.filename or "").suffix.lstrip(".").lower()
    allowed = settings.upload_allowed_extensions
    if ext not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Формат .{ext or '?'} не разрешён. Разрешены: {', '.join(sorted(allowed))}",
        )

    max_size = allowed[ext]
    data = await file.read(max_size + 1)
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
