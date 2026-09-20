"""JDG-001, JDG-012, NFR-005: воркер очереди проверки.

Один или несколько процессов `python -m app.worker` разбирают очередь
параллельно — `SELECT ... FOR UPDATE SKIP LOCKED` не даёт двум воркерам
взять одну и ту же посылку (JDG-012 "защита от повторного выполнения уже
завершённой посылки"), поэтому горизонтальное масштабирование Runner'ов —
это просто больше процессов воркера (NFR-005), без координации между ними.

Очередь — таблица `submissions` в той же Postgres, а не отдельный брокер
(Redis/RabbitMQ): проще для MVP, но при очень высокой частоте отправок
Postgres станет узким местом раньше выделенной очереди — см. README.
"""
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ProblemRevision, Submission, SubmissionStatus
from app.services.judge import judge_submission
from app.services.progress_calc import recompute_progress_for_submission

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0
# JDG-012: повтор безопасных технических ошибок — например Docker-демон
# на секунду недоступен при рестарте. Не относится к ошибкам самого решения
# ученика (те возвращаются как обычный verdict, не как исключение).
MAX_TECHNICAL_RETRIES = 2


def _claim_next_submission(db: Session) -> Submission | None:
    stmt = (
        select(Submission)
        .where(Submission.status == SubmissionStatus.QUEUED)
        .order_by(Submission.priority.desc(), Submission.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    submission = db.execute(stmt).scalar_one_or_none()
    if submission:
        submission.status = SubmissionStatus.RUNNING
        db.commit()
    return submission


def _process_submission(db: Session, submission: Submission) -> None:
    problem = db.query(ProblemRevision).filter(ProblemRevision.id == submission.problem_revision_id).first()
    if not problem:
        submission.status = SubmissionStatus.SYSTEM_ERROR
        submission.stderr = "Задача была удалена после отправки решения"
        db.commit()
        return

    last_error: Exception | None = None
    for attempt in range(1, MAX_TECHNICAL_RETRIES + 2):
        try:
            verdict, score, stdout, stderr = judge_submission(problem, submission.code)
            submission.verdict = verdict
            submission.score = score
            submission.stdout = stdout
            submission.stderr = stderr
            submission.status = SubmissionStatus.DONE
            db.commit()
            recompute_progress_for_submission(db, submission)  # GRD-005
            return
        except Exception as e:  # техническая ошибка Runner'а/Judge, не вердикт по решению
            last_error = e
            logger.warning("Посылка %s: техническая ошибка (попытка %s): %s", submission.id, attempt, e)
            time.sleep(min(2 ** attempt, 10))

    # JDG-010: Internal Error не должен ухудшать баллы и не должен списывать попытку
    # (см. фильтр SubmissionStatus.SYSTEM_ERROR в routers/submissions.py).
    submission.status = SubmissionStatus.SYSTEM_ERROR
    submission.stderr = f"Внутренняя ошибка проверки после {MAX_TECHNICAL_RETRIES + 1} попыток: {last_error}"
    db.commit()


def run_forever() -> None:
    logger.info("Codelab Judge worker запущен")
    while True:
        db = SessionLocal()
        try:
            submission = _claim_next_submission(db)
            if submission is None:
                db.close()
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            _process_submission(db, submission)
        except Exception:
            logger.exception("Воркер: непредвиденная ошибка обработки очереди")
            db.rollback()
        finally:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
