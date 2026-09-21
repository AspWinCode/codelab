"""ADM-004: очередь, признаки зависшего воркера, системные ошибки, хранилище."""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models import ProblemRevision, Submission, SubmissionStatus, User


def _sig(ref: str) -> str:
    return hmac.new(settings.sso_kodex_shared_secret.encode(), ref.encode(), hashlib.sha256).hexdigest()


def _qs(role: str) -> str:
    return f"staff_external_ref=lp-user-1&staff_full_name=U&staff_role={role}"


def test_status_forbidden_for_methodist(client, db_session):
    resp = client.get(f"/api/lms-admin/admin/status?{_qs('methodist')}", headers={"X-LP-Signature": _sig("lp-user-1")})
    assert resp.status_code == 403


def test_status_reports_queue_and_stalled_worker(client, db_session):
    student = User(external_ref="lp-student-1", full_name="S", role="student")
    db_session.add(student)
    db_session.flush()
    problem = ProblemRevision(task_id=1, revision_number=1, title="T")
    db_session.add(problem)
    db_session.flush()

    # Старая посылка в очереди — воркер должен считаться зависшим.
    old_submission = Submission(
        user_id=student.id, problem_revision_id=problem.id, code="x",
        status=SubmissionStatus.QUEUED,
    )
    db_session.add(old_submission)
    db_session.flush()
    db_session.query(Submission).filter(Submission.id == old_submission.id).update(
        {"created_at": datetime.now(timezone.utc) - timedelta(minutes=30)}
    )
    db_session.add(Submission(
        user_id=student.id, problem_revision_id=problem.id, code="x",
        status=SubmissionStatus.SYSTEM_ERROR,
    ))
    db_session.commit()

    resp = client.get(f"/api/lms-admin/admin/status?{_qs('admin')}", headers={"X-LP-Signature": _sig("lp-user-1")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"]["queued_count"] == 1
    assert body["queue"]["worker_likely_stalled"] is True
    assert body["queue"]["oldest_queued_age_seconds"] >= 1700  # ~30 минут
    assert body["errors"]["system_errors_last_24h"] == 1
    assert body["storage"]["disk_total_bytes"] > 0


def test_status_healthy_queue_not_stalled(client, db_session):
    student = User(external_ref="lp-student-1", full_name="S", role="student")
    db_session.add(student)
    db_session.flush()
    problem = ProblemRevision(task_id=1, revision_number=1, title="T")
    db_session.add(problem)
    db_session.flush()
    db_session.add(Submission(user_id=student.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.QUEUED))
    db_session.commit()

    resp = client.get(f"/api/lms-admin/admin/status?{_qs('admin')}", headers={"X-LP-Signature": _sig("lp-user-1")})
    body = resp.json()
    assert body["queue"]["queued_count"] == 1
    assert body["queue"]["worker_likely_stalled"] is False
