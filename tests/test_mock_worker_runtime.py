import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from scripts import run_photo_validation_worker as worker
from tests.test_home_apis import FakeDependency


def test_inline_mock_api_does_not_start_polling_worker(monkeypatch):
    run = AsyncMock()
    monkeypatch.setattr(worker, "run", run)
    settings = Settings(
        jwt_secret="test-secret-that-is-at-least-32-characters",
        mock_validation_on_upload=True,
    )
    with TestClient(create_app(settings, database=FakeDependency(), cache=FakeDependency())) as client:
        assert client.get("/health").status_code == 200
    run.assert_not_called()


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


def test_internal_key_secret_newline_is_normalized(monkeypatch):
    from app.ai_validation_worker import HttpValidationBackend

    monkeypatch.setenv("DALM_INTERNAL_API_KEY", "internal-test-key\n")
    assert Settings.from_env().internal_api_key == "internal-test-key"
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"data": {"job": None}})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle),
                                    base_url="http://localhost") as client:
            backend = HttpValidationBackend("http://localhost",
                                            internal_api_key="internal-test-key\n", client=client)
            assert await backend.claim("test-worker") is None

    asyncio.run(exercise())
    assert requests[0].headers["X-DALM-Internal-Key"] == "internal-test-key"
