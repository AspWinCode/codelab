"""Этап 11 (ТЗ): очистка неиспользуемых файлов и ограничение срока хранения
общих загрузок без ссылок (app/cleanup_uploads.py)."""
import os
import time
from pathlib import Path

import pytest

from app.cleanup_uploads import run_once
from app.models import Course, CourseVersion, LearningItem, LearningItemType, OgeAttempt, ProjectFile, ProjectSubmission, ProjectSubmissionStatus, User


@pytest.fixture()
def tmp_upload_dirs(tmp_path, monkeypatch):
    from app.config import settings

    oge_dir = tmp_path / "oge"
    project_dir = tmp_path / "project"
    general_dir = tmp_path / "general"
    oge_dir.mkdir()
    project_dir.mkdir()
    general_dir.mkdir()
    monkeypatch.setattr(settings, "oge_uploads_dir", str(oge_dir))
    monkeypatch.setattr(settings, "project_uploads_dir", str(project_dir))
    monkeypatch.setattr(settings, "uploads_dir", str(general_dir))
    return {"oge": oge_dir, "project": project_dir, "general": general_dir}


def _touch(path: Path, name: str, age_days: int = 0) -> Path:
    f = path / name
    f.write_bytes(b"data")
    if age_days:
        old = time.time() - age_days * 86400
        os.utime(f, (old, old))
    return f


def test_removes_orphaned_oge_file_not_referenced_by_any_attempt(db_session, tmp_upload_dirs):
    _touch(tmp_upload_dirs["oge"], "orphan.jpg")
    referenced = _touch(tmp_upload_dirs["oge"], "referenced.jpg")

    user = User(external_ref="s1", full_name="S", role="student")
    db_session.add(user)
    db_session.flush()
    course = Course(title="C")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, version_number=1)
    db_session.add(version)
    db_session.flush()
    item = LearningItem(course_version_id=version.id, type=LearningItemType.OGE_TASK, title="T", oge_answer={"answer": "1"})
    db_session.add(item)
    db_session.flush()
    db_session.add(OgeAttempt(user_id=user.id, item_id=item.id, answer="1", score=100.0, file_stored_name=referenced.name))
    db_session.commit()

    result = run_once(db_session)
    assert result["removed_oge"] == 1
    assert not (tmp_upload_dirs["oge"] / "orphan.jpg").exists()
    assert referenced.exists()


def test_removes_orphaned_project_file_not_referenced_by_any_row(db_session, tmp_upload_dirs):
    _touch(tmp_upload_dirs["project"], "orphan.py")
    referenced = _touch(tmp_upload_dirs["project"], "referenced.py")

    course = Course(title="C")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, version_number=1)
    db_session.add(version)
    db_session.flush()
    item = LearningItem(course_version_id=version.id, type=LearningItemType.PROJECT, title="P")
    db_session.add(item)
    db_session.flush()
    user = User(external_ref="s2", full_name="S2", role="student")
    db_session.add(user)
    db_session.flush()
    submission = ProjectSubmission(learning_item_id=item.id, user_id=user.id, status=ProjectSubmissionStatus.DRAFT)
    db_session.add(submission)
    db_session.flush()
    db_session.add(ProjectFile(submission_id=submission.id, original_filename="referenced.py", stored_name=referenced.name, content_type="text/x-python", size=4))
    db_session.commit()

    result = run_once(db_session)
    assert result["removed_project"] == 1
    assert not (tmp_upload_dirs["project"] / "orphan.py").exists()
    assert referenced.exists()


def test_keeps_recent_unreferenced_general_upload_but_removes_old_one(db_session, tmp_upload_dirs):
    recent = _touch(tmp_upload_dirs["general"], "recent.png", age_days=1)
    old_unreferenced = _touch(tmp_upload_dirs["general"], "old-unused.png", age_days=40)
    old_referenced = _touch(tmp_upload_dirs["general"], "old-used.png", age_days=40)

    course = Course(title="C")
    db_session.add(course)
    db_session.flush()
    version = CourseVersion(course_id=course.id, version_number=1)
    db_session.add(version)
    db_session.flush()
    db_session.add(LearningItem(
        course_version_id=version.id, type=LearningItemType.THEORY, title="T",
        content=f"![img](/uploads/{old_referenced.name})",
    ))
    db_session.commit()

    result = run_once(db_session)
    assert result["removed_general"] == 1
    assert recent.exists()  # свежий — не трогаем, даже если пока без ссылки
    assert old_referenced.exists()  # есть ссылка в content — не трогаем
    assert not old_unreferenced.exists()  # старый и без ссылки — удалён
