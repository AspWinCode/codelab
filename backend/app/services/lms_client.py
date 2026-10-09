"""Исходящие вызовы в портал: вебхук публикации курса и сдачи/пересдачи
проекта (см. codelab.py router в learning-portal-main — контракт менять
только синхронно с той стороной). Один и тот же endpoint, один и тот же
механизм подписи — событие различается полем "event" в теле."""
import json
import logging
from datetime import datetime

import httpx

from app.config import settings
from app.models import Course
from app.security import sign_for_lms

logger = logging.getLogger(__name__)


async def _post_webhook(body: bytes, event: str, log_ctx: str) -> None:
    if not settings.sso_kodex_shared_secret:
        logger.warning("SSO_KODEX_SHARED_SECRET не настроен — вебхук в портал не отправлен")
        return
    signature = sign_for_lms(body)
    url = f"{settings.lms_base_url.rstrip('/')}/api/v1/codelab/courses/webhook"
    try:
        # Best-effort (см. README): тренер в любом случае увидит сдачу в
        # очереди при следующем открытии раздела — не ретраим и не падаем,
        # если портал недоступен или ответил не 200.
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, content=body, headers={
                "Content-Type": "application/json",
                "X-LP-Signature": signature,
            })
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Не удалось уведомить портал о %s (%s): %s", log_ctx, event, e)


async def notify_course_webhook(course: Course, event: str) -> None:
    body = json.dumps({
        "event": event,
        "course": {
            "id": course.id,
            "slug": course.slug,
            "title": course.title,
            "description": course.description,
            "status": course.status.value if hasattr(course.status, "value") else course.status,
        },
    }).encode("utf-8")
    await _post_webhook(body, event, f"курсе {course.id}")


async def notify_project_submission_webhook(
    event: str,
    submission_id: int,
    course_id: int,
    item_id: int,
    attempt_number: int,
    submitted_at: datetime,
    student_external_ref: str,
) -> None:
    """event: "project_submitted" (attempt_number == 1) или
    "project_resubmitted" (attempt_number > 1, после needs_revision) —
    тренер получает push/email вместо того, чтобы узнавать о сдаче только
    при открытии "Работы учеников". submission.id + attempt_number — для
    дедупликации на стороне LMS при повторной доставке (best-effort, без
    гарантии "ровно один раз" — см. README)."""
    body = json.dumps({
        "event": event,
        "submission": {
            "id": submission_id,
            "course_id": course_id,
            "item_id": item_id,
            "attempt_number": attempt_number,
            "submitted_at": submitted_at.isoformat(),
            "student_external_ref": student_external_ref,
        },
    }).encode("utf-8")
    await _post_webhook(body, event, f"сдаче проекта {submission_id}")
