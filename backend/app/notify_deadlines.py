"""NTF-001: напоминание о приближении дедлайна. Разовый прогон — предполагается
внешний планировщик (cron), например раз в сутки:

    0 9 * * * /path/to/venv/bin/python -m app.notify_deadlines

Не воркер-демон, в отличие от app/worker.py — здесь нет смысла держать
постоянно работающий процесс, проверка нужна редко.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Enrollment, EnrollmentStatus, NotificationType, Progress
from app.services.notifications import notify

logger = logging.getLogger(__name__)

# За сколько до дедлайна слать напоминание — один раз в этом окне.
REMINDER_WINDOW = timedelta(days=2)


def run_once(db: Optional[Session] = None) -> int:
    """db передаётся явно в тестах (своя БД на тест); при обычном запуске
    из cron открываем и закрываем сессию сами."""
    owns_session = db is None
    if db is None:
        db = SessionLocal()
    sent = 0
    try:
        now = datetime.now(timezone.utc)
        soon = now + REMINDER_WINDOW

        enrollments = (
            db.query(Enrollment)
            .filter(
                Enrollment.status == EnrollmentStatus.ACTIVE,
                Enrollment.ends_at.isnot(None),
                Enrollment.ends_at <= soon,
                Enrollment.ends_at > now,
                Enrollment.deadline_notified_at.is_(None),
            )
            .all()
        )
        for e in enrollments:
            progress = (
                db.query(Progress)
                .filter(Progress.user_id == e.user_id, Progress.course_id == e.course_id)
                .first()
            )
            if progress and progress.total_items and progress.completed_items >= progress.total_items:
                # Уже завершил курс — дедлайн можно не напоминать.
                e.deadline_notified_at = now
                continue

            notify(
                db, e.user_id, NotificationType.DEADLINE_APPROACHING,
                "Скоро дедлайн по курсу",
                body=f"Доступ к курсу закрывается {e.ends_at.strftime('%d.%m.%Y')}.",
            )
            e.deadline_notified_at = now
            sent += 1
        db.commit()
    finally:
        if owns_session:
            db.close()
    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = run_once()
    logger.info("Отправлено напоминаний о дедлайне: %s", count)
