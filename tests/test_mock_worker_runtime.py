import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from scripts import run_photo_validation_worker as worker
from tests.test_home_apis import FakeDependency


def test_api_starts_and_cancels_enabled_worker(monkeypatch):
    events = []

    async def run(*, once):
        assert once is False
        events.append("started")
        try:
            await asyncio.Event().wait()
        finally:
            events.append("stopped")

    monkeypatch.setattr(worker, "run", run)
    settings = Settings(
        jwt_secret="test-secret-that-is-at-least-32-characters",
        internal_api_key="internal-test-key", mock_validation_worker_enabled=True,
    )
    with TestClient(create_app(settings, database=FakeDependency(), cache=FakeDependency())) as client:
        assert client.get("/health").status_code == 200
        assert events == ["started"]
    assert events == ["started", "stopped"]


def test_mock_worker_requires_internal_auth():
    with pytest.raises(RuntimeError, match="DALM_INTERNAL_API_KEY"):
        create_app(Settings(jwt_secret="test-secret-that-is-at-least-32-characters",
                            mock_validation_worker_enabled=True),
                   database=FakeDependency(), cache=FakeDependency())


def test_worker_retries_http_failure_and_closes_on_cancel(monkeypatch):
    backend = AsyncMock()
    monkeypatch.setattr(worker, "HttpValidationBackend", lambda *args, **kwargs: backend)
    attempts = []

    async def process(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("API is starting")
        raise asyncio.CancelledError()

    monkeypatch.setattr(worker, "run_validation_once", process)
    monkeypatch.setattr(worker.asyncio, "sleep", AsyncMock())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.run(once=False))
    assert len(attempts) == 2
    backend.close.assert_awaited_once()
