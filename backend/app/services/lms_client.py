"""Исходящие вызовы в портал: вебхук публикации курса (см. codelab.py router
в learning-portal-main — контракт менять только синхронно с той стороной)."""
import json
import logging

import httpx

from app.config import settings
from app.models import Course
from app.security import sign_for_lms

logger = logging.getLogger(__name__)


async def notify_course_webhook(course: Course, event: str) -> None:
    if not settings.sso_kodex_shared_secret:
        logger.warning("SSO_KODEX_SHARED_SECRET не настроен — вебхук в портал не отправлен")
        return
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
    signature = sign_for_lms(body)
    url = f"{settings.lms_base_url.rstrip('/')}/api/v1/codelab/courses/webhook"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, content=body, headers={
                "Content-Type": "application/json",
                "X-LP-Signature": signature,
            })
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Не удалось уведомить портал о курсе %s (%s): %s", course.id, event, e)
