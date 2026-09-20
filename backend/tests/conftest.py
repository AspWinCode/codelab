import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.deps import get_current_user
from app.main import app
from app.models import User


@pytest.fixture()
def db_session():
    # StaticPool: TestClient гоняет запросы в threadpool, а SQLite ":memory:"
    # без него даёт отдельную (пустую) базу на каждое новое соединение/поток.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(client: TestClient, user: User):
    """Подменяет текущего пользователя для запросов через этот клиент."""
    client.app.dependency_overrides[get_current_user] = lambda: user


def make_user(db_session, role: str, external_ref: str = None) -> User:
    user = User(external_ref=external_ref or f"lp-test-{role}", full_name=f"Test {role}", role=role)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user
