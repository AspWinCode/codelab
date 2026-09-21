"""ADM-004: состояние очереди, признаки живости воркера, недавние системные
ошибки, ёмкость хранилища. Только для роли admin — не методисту/преподавателю."""
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Submission, SubmissionStatus

# Если самая старая посылка в очереди ждёт дольше этого — считаем воркер
# зависшим/не запущенным (это эвристика, не гарантия).
STALLED_QUEUE_THRESHOLD = timedelta(minutes=5)
RECENT_ERRORS_WINDOW = timedelta(hours=24)


def get_system_status(db: Session) -> dict:
    now = datetime.now(timezone.utc)

    queued_count = db.query(Submission).filter(Submission.status == SubmissionStatus.QUEUED).count()
    running_count = db.query(Submission).filter(Submission.status == SubmissionStatus.RUNNING).count()

    oldest_queued = (
        db.query(Submission)
        .filter(Submission.status == SubmissionStatus.QUEUED)
        .order_by(Submission.created_at.asc())
        .first()
    )
    oldest_queued_age_seconds = None
    worker_likely_stalled = False
    if oldest_queued:
        created_at = oldest_queued.created_at
        if created_at.tzinfo is None:  # см. services/analytics.py — та же особенность SQLite
            created_at = created_at.replace(tzinfo=timezone.utc)
        age = now - created_at
        oldest_queued_age_seconds = int(age.total_seconds())
        worker_likely_stalled = age > STALLED_QUEUE_THRESHOLD

    since = now - RECENT_ERRORS_WINDOW
    recent_system_errors = (
        db.query(Submission)
        .filter(Submission.status == SubmissionStatus.SYSTEM_ERROR, Submission.created_at >= since)
        .count()
    )

    uploads_path = Path(settings.uploads_dir)
    uploads_size_bytes = sum(f.stat().st_size for f in uploads_path.rglob("*") if f.is_file()) if uploads_path.exists() else 0
    disk_total, disk_used, disk_free = shutil.disk_usage(uploads_path if uploads_path.exists() else Path("."))

    return {
        "generated_at": now,
        "queue": {
            "queued_count": queued_count,
            "running_count": running_count,
            "oldest_queued_age_seconds": oldest_queued_age_seconds,
            "worker_likely_stalled": worker_likely_stalled,
        },
        "errors": {
            "system_errors_last_24h": recent_system_errors,
        },
        "storage": {
            "uploads_size_bytes": uploads_size_bytes,
            "disk_free_bytes": disk_free,
            "disk_total_bytes": disk_total,
        },
    }
