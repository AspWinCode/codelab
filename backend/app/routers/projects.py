"""Ученический доступ к сдаче проектов (type=project): прикрепить файлы,
отправить на проверку, скачать своё, посмотреть комментарии/оценку.
Проверка сотрудником — app/routers/lms_admin.py."""
from fastapi import APIRouter, Depends, File as FastAPIFile, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import ProjectSubmission, User
from app.schemas import ProjectFileOut, ProjectSubmissionOut
from app.services import project_admin
from app.services.project_files import project_file_path

router = APIRouter()


@router.get("/items/{item_id}/submission", response_model=ProjectSubmissionOut)
def get_my_submission(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = project_admin.get_project_item_or_404(db, item_id)
    submission = project_admin.get_or_create_current_submission(db, item_id, user.id)
    return project_admin.to_submission_out(db, item, submission)


@router.post("/items/{item_id}/files", response_model=ProjectFileOut, status_code=201)
async def upload_file(
    item_id: int,
    file: UploadFile = FastAPIFile(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    f = await project_admin.attach_file(db, item_id, user.id, file.filename or "", file.content_type or "", file.read)
    return ProjectFileOut(
        id=f.id, original_filename=f.original_filename, content_type=f.content_type,
        size=f.size, uploaded_at=f.uploaded_at, comments=[],
    )


@router.delete("/files/{file_id}")
def delete_file(file_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_admin.remove_own_file(db, file_id, user.id)
    return {"ok": True}


@router.post("/submissions/{submission_id}/submit", response_model=ProjectSubmissionOut)
def submit(submission_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    submission = project_admin.submit_submission(db, submission_id, user.id)
    item = project_admin.get_project_item_or_404(db, submission.learning_item_id)
    return project_admin.to_submission_out(db, item, submission)


@router.get("/files/{file_id}/download")
def download_file(file_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = project_admin.get_file_or_404(db, file_id)
    submission = db.query(ProjectSubmission).filter(ProjectSubmission.id == f.submission_id).first()
    is_owner = submission is not None and submission.user_id == user.id
    is_staff = user.role in ("teacher", "methodist", "admin")
    if not is_owner and not is_staff:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    path = project_file_path(f.stored_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден на диске")
    return FileResponse(path, media_type=f.content_type, filename=f.original_filename)
