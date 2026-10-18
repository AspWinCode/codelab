"""IDE-003/004, JDG-001: запуск (синхронно, без создания посылки) и отправка
решения (ставится в очередь — обрабатывает app/worker.py, см. JDG-001/012)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models import Draft, ProblemRevision, Submission, SubmissionStatus, User
from app.schemas import DraftIn, DraftOut, ManualGradeIn, RunRequest, RunResult, SubmissionCreate, SubmissionOut
from app.services.error_explain import explain_stderr_ru, explain_timeout_ru
from app.services.progress_calc import apply_manual_grade
from app.services.runner import run_for_problem

router = APIRouter()


def _upsert_draft(db: Session, user_id: int, problem_revision_id: int, code: str) -> Draft:
    draft = (
        db.query(Draft)
        .filter(Draft.user_id == user_id, Draft.problem_revision_id == problem_revision_id)
        .first()
    )
    if draft:
        draft.code = code
    else:
        draft = Draft(user_id=user_id, problem_revision_id=problem_revision_id, code=code)
        db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.put("/draft", response_model=DraftOut)
def save_draft(payload: DraftIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """IDE-002: автосохранение кода по мере набора (с debounce на фронте) —
    отдельно от "Запустить"/"Отправить", чтобы код не терялся при обычном
    переключении между задачами или уходе со страницы без явного действия."""
    problem = db.query(ProblemRevision).filter(ProblemRevision.id == payload.problem_revision_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    draft = _upsert_draft(db, user.id, payload.problem_revision_id, payload.code)
    return DraftOut(updated_at=draft.updated_at)


@router.post("/run", response_model=RunResult)
def run_code(payload: RunRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    problem = db.query(ProblemRevision).filter(ProblemRevision.id == payload.problem_revision_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    _upsert_draft(db, user.id, problem.id, payload.code)

    # db.commit() инвалидирует закэшированные атрибуты ORM-объектов
    # (SQLAlchemy expire_on_commit=True по умолчанию) — обращаемся к полям,
    # которые нужны run_for_problem, пока сессия ещё жива, чтобы они
    # перезагрузились и закэшировались в объекте; иначе обращение к ним
    # после db.close() ниже упадёт DetachedInstanceError.
    _ = (problem.language, problem.time_limit_ms, problem.memory_limit_mb, problem.sql_fixture)

    # Не держим соединение с БД на время docker-прогона (секунды — запуск
    # контейнера судьи) — иначе при одновременной нагрузке (много учеников
    # жмут "Запустить" разом) пул соединений исчерпывается быстрее, чем
    # освобождается, и валит таймаутами даже не связанные с запуском
    # запросы (см. инцидент с 504 13.10.2026: QueuePool limit reached).
    db.close()

    result = run_for_problem(problem, payload.code, payload.stdin)
    result.error_explanation = explain_timeout_ru() if result.timed_out else explain_stderr_ru(result.stderr)
    return result


@router.post("", response_model=SubmissionOut)
def submit(payload: SubmissionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """JDG-001: создаёт посылку со статусом "В очереди" — саму проверку
    выполняет app/worker.py. Клиент опрашивает GET /{id} до статуса done."""
    problem = db.query(ProblemRevision).filter(ProblemRevision.id == payload.problem_revision_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    if problem.max_attempts is not None:
        attempts = (
            db.query(Submission)
            .filter(
                Submission.user_id == user.id,
                Submission.problem_revision_id == problem.id,
                Submission.status != SubmissionStatus.SYSTEM_ERROR,
            )
            .count()
        )
        if attempts >= problem.max_attempts:
            raise HTTPException(status_code=400, detail="Исчерпано число попыток")

    submission = Submission(
        user_id=user.id,
        problem_revision_id=problem.id,
        code=payload.code,
        language=payload.language,
        status=SubmissionStatus.QUEUED,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


@router.get("/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Посылка не найдена")
    if submission.user_id != user.id and user.role not in ("teacher", "methodist", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return submission


@router.get("", response_model=list[SubmissionOut])
def my_submissions(problem_revision_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(Submission)
        .filter(Submission.user_id == user.id, Submission.problem_revision_id == problem_revision_id)
        .order_by(Submission.created_at.desc())
        .all()
    )


@router.put("/{submission_id}/grade", response_model=SubmissionOut)
def manual_grade(
    submission_id: int,
    payload: ManualGradeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("teacher", "methodist", "admin")),
):
    return apply_manual_grade(db, submission_id, payload.score, payload.comment)


