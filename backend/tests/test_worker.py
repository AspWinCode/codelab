"""JDG-001/012: очередь переводит посылку QUEUED → RUNNING → DONE и не
обрабатывает уже завершённую посылку повторно."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models import ProblemRevision, Submission, SubmissionStatus, User
from app.worker import _claim_next_submission, _process_submission


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_claim_processes_and_wont_reclaim(db_session, monkeypatch):
    # settings — уже сконструированный объект (Settings() при импорте config.py),
    # setenv на него не подействует — правим атрибут напрямую.
    monkeypatch.setattr(settings, "runner_backend", "subprocess")

    user = User(external_ref="lp-student-1", full_name="Test", role="student")
    db_session.add(user)
    db_session.flush()
    problem = ProblemRevision(
        task_id=1,
        revision_number=1,
        title="Sum",
        tests=[{"input": "", "expected": "2\n"}],
        time_limit_ms=2000,
        memory_limit_mb=256,
    )
    db_session.add(problem)
    db_session.flush()
    submission = Submission(
        user_id=user.id,
        problem_revision_id=problem.id,
        code="print(1+1)",
        status=SubmissionStatus.QUEUED,
    )
    db_session.add(submission)
    db_session.commit()

    claimed = _claim_next_submission(db_session)
    assert claimed is not None
    assert claimed.status == SubmissionStatus.RUNNING

    _process_submission(db_session, claimed)
    db_session.refresh(claimed)
    assert claimed.status == SubmissionStatus.DONE
    assert claimed.verdict == "Accepted"
    assert claimed.score == 100.0

    assert _claim_next_submission(db_session) is None


def test_priority_order(db_session):
    user = User(external_ref="lp-student-1", full_name="Test", role="student")
    db_session.add(user)
    db_session.flush()
    problem = ProblemRevision(task_id=1, revision_number=1, title="X", tests=[])
    db_session.add(problem)
    db_session.flush()

    low = Submission(user_id=user.id, problem_revision_id=problem.id, code="x", status=SubmissionStatus.QUEUED, priority=0)
    high = Submission(user_id=user.id, problem_revision_id=problem.id, code="y", status=SubmissionStatus.QUEUED, priority=10)
    db_session.add_all([low, high])
    db_session.commit()

    claimed = _claim_next_submission(db_session)
    assert claimed.id == high.id
