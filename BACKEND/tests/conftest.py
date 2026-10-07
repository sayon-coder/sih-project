"""
Test configuration and fixtures.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.models import User, Role, UserRole, RoleName
from app.utils import hash_password
from app.utils.cache import cache as response_cache

# Create in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def _clean_response_cache():
    """The process-wide response cache must never leak between tests.

    Tests share one Python process and reuse user/product ids after each
    in-memory DB reset; a cached chat/overview payload from a previous test
    could otherwise be served against fresh data whose revision coincides.
    Within a single test the cache stays active, which is exactly what the
    cache tests exercise.
    """
    response_cache.clear()
    yield
    response_cache.clear()


@pytest.fixture(autouse=True)
def _no_real_email(monkeypatch):
    """Never open a real SMTP connection during a test run.

    The git-ignored ``BACKEND/.env`` carries real SMTP credentials on the
    developer machine; without this guard any test that creates a review
    would silently mail the review desk. Blanking host/username keeps
    ``send_review_email`` on its honest "not configured" path. Tests that
    exercise sending pass explicit ``smtp_*`` arguments instead.
    """
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_username", "")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    # Create tables
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()

    # Seed roles for tests
    for role_name in RoleName:
        role = Role(name=role_name, description=f"{role_name.value} role")
        session.add(role)
    session.commit()

    try:
        yield session
    finally:
        session.close()
        # Drop all tables after test
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with database dependency override."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    user = User(
        username="testuser",
        email="test@example.com",
        password_hash=hash_password("testpassword123"),
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_role(db_session):
    """Create test roles."""
    roles = []
    for role_name in RoleName:
        role = Role(name=role_name, description=f"{role_name.value} role")
        db_session.add(role)
        roles.append(role)
    db_session.commit()
    return roles


@pytest.fixture
def auth_headers(client, test_user):
    """Get authentication headers for a test user."""
    response = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpassword123"}
    )
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def second_user(db_session):
    """Create a second user, used to test authorization boundaries."""
    user = User(
        username="otheruser",
        email="other@example.com",
        password_hash=hash_password("otherpassword123"),
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def second_user_headers(client, second_user):
    """Authentication headers for the second user."""
    response = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "otherpassword123"}
    )
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}
