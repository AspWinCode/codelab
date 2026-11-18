"""Этап 11 (ТЗ): "ограничить срок хранения" и "очистка неиспользуемых
файлов". Разовый прогон — внешний планировщик (cron), как и
app/notify_deadlines.py, например раз в сутки:

    0 4 * * * /path/to/venv/bin/python -m app.cleanup_uploads

Что чистит:
1. Приватные файлы (фото к ОГЭ, файлы проектов), на stored_name которых не
   ссылается ни одна запись в БД — остаются на диске, когда запись удалена
   напрямую в базе, минуя код приложения (сам он всегда удаляет и то, и
   другое вместе, см. project_admin.py/course_admin.py).
2. Файлы общей загрузки (картинки/видео материалов курса, uploads_dir) —
   удаляются, только если на их имя НЕТ ссылки ни в одном LearningItem.content/
   description (любой версии курса, не только активной — черновик тоже
   считается) И они старше UPLOAD_RETENTION_DAYS: свежую загрузку не трогаем
   — методист мог прикрепить файл и ещё не сохранить материал с ним."""
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import LearningItem, OgeAttempt, ProjectFile

logger = logging.getLogger(__name__)

UPLOAD_RETENTION_DAYS = int(os.environ.get("UPLOAD_RETENTION_DAYS", "30"))


def _delete_unreferenced(root: Path, referenced_names: set[str]) -> int:
    if not root.exists():
        return 0
    removed = 0
    for path in root.iterdir():
        if path.is_file() and path.name not in referenced_names:
            path.unlink()
            removed += 1
    return removed


def _delete_unreferenced_general_uploads(root: Path, db: Session, retention_days: int) -> int:
    if not root.exists():
        return 0
    # Один большой текст со всем содержимым всех версий всех курсов —
    # дешевле, чем по отдельному запросу на каждый файл на диске.
    rows = db.query(LearningItem.content, LearningItem.description).all()
    haystack = "\n".join(f"{content or ''}\n{description or ''}" for content, description in rows)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    removed = 0
    for path in root.iterdir():
        if not path.is_file():
            continue
        if f"/uploads/{path.name}" in haystack:
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def run_once(db: Optional[Session] = None) -> dict:
    """db передаётся явно в тестах; при обычном запуске из cron открываем и
    закрываем сессию сами (см. app/notify_deadlines.py — тот же приём)."""
    owns_session = db is None
    if db is None:
        db = SessionLocal()
    try:
        oge_referenced = {
            row[0] for row in db.query(OgeAttempt.file_stored_name).filter(OgeAttempt.file_stored_name.isnot(None))
        }
        project_referenced = {row[0] for row in db.query(ProjectFile.stored_name)}

        removed_oge = _delete_unreferenced(Path(settings.oge_uploads_dir), oge_referenced)
        removed_project = _delete_unreferenced(Path(settings.project_uploads_dir), project_referenced)
        removed_general = _delete_unreferenced_general_uploads(
            Path(settings.uploads_dir), db, UPLOAD_RETENTION_DAYS,
        )

        result = {"removed_oge": removed_oge, "removed_project": removed_project, "removed_general": removed_general}
        logger.info("cleanup_uploads: %s", result)
        return result
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_once()
