from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, courses, lms_integration, submissions

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


@app.get("/health")
def health():
    return {"status": "ok"}
