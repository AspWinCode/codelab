import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import auth, courses, dashboard, lms_admin, lms_integration, submissions, uploads

app = FastAPI(title="Codelab API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(courses.router, prefix="/api/courses", tags=["courses"])
app.include_router(submissions.router, prefix="/api/submissions", tags=["submissions"])
# Без общего префикса /api — контракт lms_integration фиксирован путями
# /api/internal/... и /api/admin/... как в learning-portal-main.
app.include_router(lms_integration.router, prefix="/api", tags=["lms-integration"])
app.include_router(uploads.router, prefix="/api/uploads", tags=["uploads"])
app.include_router(dashboard.router, prefix="/api/me", tags=["dashboard"])
app.include_router(lms_admin.router, prefix="/api/lms-admin", tags=["lms-admin"])

# EDT-002: прямая раздача загруженных файлов редактора. В README отмечено,
# что для прода это должно стать объектным хранилищем за CDN/подписанными
# URL, а не диском самого API-процесса.
os.makedirs(settings.uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.uploads_dir), name="uploads")


@app.get("/health")
def health():
    return {"status": "ok"}
