"""IDE-003/004, JDG-001: запуск и отправка решения. Проверка выполняется синхронно
в запросе — TODO вынести в очередь + отдельные Runner-узлы (JDG-001, JDG-012, NFR-005)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Draft, ProblemRevision, Submission, SubmissionStatus, User
from app.schemas import RunRequest, RunResult, SubmissionCreate, SubmissionOut
from app.services.judge import judge_submission
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
        status=SubmissionStatus.RUNNING,
    )
    db.add(submission)
    db.flush()

    try:
        verdict, score, stdout, stderr = judge_submission(problem, payload.code)
        submission.verdict = verdict
        submission.score = score
        submission.stdout = stdout
        submission.stderr = stderr
        submission.status = SubmissionStatus.DONE
    except Exception as e:  # JDG-010: Internal Error не должен списывать попытку/ухудшать балл.
        submission.status = SubmissionStatus.SYSTEM_ERROR
        submission.stderr = str(e)

    db.commit()
    db.refresh(submission)
    return submission


@router.get("", response_model=list[SubmissionOut])
def my_submissions(problem_revision_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(Submission)
        .filter(Submission.user_id == user.id, Submission.problem_revision_id == problem_revision_id)
        .order_by(Submission.created_at.desc())
        .all()
    )
