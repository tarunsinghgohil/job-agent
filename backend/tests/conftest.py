"""Shared test fixtures.

Each test gets its own in-memory database and a TestClient whose `get_db`
dependency is overridden to use it, so tests never touch the real database and
never share state with one another.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.models.identity import User

TEST_PASSWORD = "test-password-12345"


@pytest.fixture(autouse=True)
def _isolate_agent_registry():
    """The agent registry is a process-wide module dict.

    ``app.main``'s lifespan calls ``wire_agents()`` on startup, which
    permanently replaces placeholder agents with real implementations. Any
    test that spins up the app (directly or via the ``client`` fixture) would
    otherwise leak that wiring into every test that runs afterward in the same
    process. Snapshotting and restoring the dict keeps each test's view of the
    registry independent of what ran before it.
    """
    from app.agents import registry

    snapshot = dict(registry._REGISTRY)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(snapshot)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """The limiters are process-global singletons; tests must not share state."""
    from app.core.deps import ai_limiter, general_limiter, login_limiter

    login_limiter.reset()
    ai_limiter.reset()
    general_limiter.reset()
    yield
    login_limiter.reset()
    ai_limiter.reset()
    general_limiter.reset()


@pytest.fixture()
def engine():
    """One in-memory database, shared across connections within a test."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def db(engine) -> Iterator[Session]:
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = maker()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture()
def upload_dir(monkeypatch) -> Iterator[Path]:
    """Point uploads at a throwaway directory for the duration of a test."""
    with tempfile.TemporaryDirectory() as tmp:
        from app.core.config import settings

        monkeypatch.setattr(settings, "data_dir", tmp)
        yield Path(tmp) / "uploads"


@pytest.fixture()
def client(engine, monkeypatch) -> Iterator[TestClient]:
    from app.core.config import settings
    from app.db.session import get_db
    from app.main import app

    # The scheduler has no place in a test process.
    monkeypatch.setattr(settings, "scheduler_enabled", False)

    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def override_get_db() -> Iterator[Session]:
        session = maker()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def owner(engine) -> User:
    """A seeded owner account with profile, preferences and answers."""
    from sqlalchemy.orm import sessionmaker

    from app.cli import _seed_user_data
    from app.services.auth import create_user

    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = maker()
    try:
        user = create_user(
            session, "owner@example.com", TEST_PASSWORD, full_name="Test Owner", is_owner=True
        )
        _seed_user_data(session, user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user
    finally:
        session.close()


@pytest.fixture()
def auth_client(client: TestClient, owner: User) -> TestClient:
    """A TestClient carrying a valid access token for the seeded owner."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture()
def sample_job(auth_client: TestClient) -> dict:
    """A job that satisfies the seeded policy, so it scores well."""
    response = auth_client.post(
        "/api/v1/jobs",
        json={
            "title": "Senior Frontend Developer",
            "company": "Example Product Co",
            "location": "Remote",
            "is_remote": True,
            "employment_type": "full_time",
            "industry": "software",
            "salary_min_lpa": 16,
            "salary_max_lpa": 22,
            "description": (
                "We are hiring a React developer. You will work with React, TypeScript, "
                "Redux Toolkit and Next.js to build REST APIs driven interfaces. "
                "Testing with Jest is part of the job. 4+ years of experience required."
            ),
            "url": "https://example.com/jobs/frontend-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
