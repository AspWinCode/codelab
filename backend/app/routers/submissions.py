"""IDE-003/004, JDG-001: запуск (синхронно, без создания посылки) и отправка
решения (ставится в очередь — обрабатывает app/worker.py, см. JDG-001/012)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models import Draft, ProblemRevision, Submission, SubmissionStatus, User
from app.schemas import ManualGradeIn, RunRequest, RunResult, SubmissionCreate, SubmissionOut
from app.services.progress_calc import apply_manual_grade
from app.services.runner import run_python

router = APIRouter()


@router.post("/run", response_model=RunResult)
def run_code(payload: RunRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    problem = db.query(ProblemRevision).filter(ProblemRevision.id == payload.problem_revision_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    draft = (
        db.query(Draft)
        .filter(Draft.user_id == user.id, Draft.problem_revision_id == problem.id)
        .first()
    )
    if draft:
        draft.code = payload.code
    else:
        db.add(Draft(user_id=user.id, problem_revision_id=problem.id, code=payload.code))
    db.commit()

    return run_python(payload.code, payload.stdin, problem.time_limit_ms, problem.memory_limit_mb)


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


