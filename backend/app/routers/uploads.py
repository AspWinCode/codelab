"""EDT-002, EDT-008, SEC-005: загрузка файлов для редактора контента —
allowlist форматов, лимит размера, безопасное имя (UUID, не имя от клиента),
исполняемые файлы запрещены по умолчанию (allowlist, а не blocklist —
неизвестное расширение отклоняется, а не пропускается).

Антивирусная проверка (SEC-005) и выдача через подписанный/контролируемый
URL — не реализованы, см. README; сейчас файл сразу доступен по прямой
статической ссылке.
"""
from fastapi import APIRouter, Depends, UploadFile
from fastapi import File as FastAPIFile

from app.deps import require_role
from app.models import User
from app.schemas import UploadOut
from app.services.uploads import save_upload

router = APIRouter()


@router.post("", response_model=UploadOut)
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    user: User = Depends(require_role("methodist", "admin")),
):
    return await save_upload(file.filename or "", file.read)
