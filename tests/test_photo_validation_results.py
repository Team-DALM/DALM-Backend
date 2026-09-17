from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_photo_validation_repository
from app.main import create_app
from app.token_store import InMemoryRefreshTokenStore

JOB_ID = UUID("11111111-1111-1111-1111-111111111111")
PHOTO_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeDependency:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeValidationRepository:
    def __init__(self) -> None:
        self.received = None

    async def apply_result(self, job_id, **values):
        self.received = (job_id, values)
        return SimpleNamespace(
            id=job_id,
            photo_id=PHOTO_ID,
            status=values["status"],
            completed_at=datetime.now(UTC),
        )


def make_client(*, internal_api_key="internal-test-key"):
    dependency = FakeDependency()
    repository = FakeValidationRepository()
    app = create_app(
        Settings(
            jwt_secret="test-secret-that-is-long-enough-for-validation-result",
            internal_api_key=internal_api_key,
        ),
        database=dependency,
        cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
    )
    app.dependency_overrides[get_photo_validation_repository] = lambda: repository
    return TestClient(app), repository


def result_payload(**overrides):
    payload = {
        "status": "PASSED",
        "scores": {"quality": 0.91, "safety": 0.99},
        "model_name": "dalm-validator",
        "model_version": "1.0.0",
        "processing_time_ms": 820,
    }
    payload.update(overrides)
    return payload


def test_internal_result_requires_valid_key():
    client, repository = make_client()

    response = client.post(
        f"/internal/v1/photo-validations/{JOB_ID}/result",
        json=result_payload(),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_INTERNAL_API_KEY"
    assert repository.received is None


def test_internal_result_is_disabled_without_configured_key():
    client, _ = make_client(internal_api_key=None)

    response = client.post(
        f"/internal/v1/photo-validations/{JOB_ID}/result",
        headers={"X-DALM-Internal-Key": "any-key"},
        json=result_payload(),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INTERNAL_API_NOT_CONFIGURED"


def test_passed_result_is_forwarded_and_returns_searching():
    client, repository = make_client()

    response = client.post(
        f"/internal/v1/photo-validations/{JOB_ID}/result",
        headers={"X-DALM-Internal-Key": "internal-test-key"},
        json=result_payload(),
    )

    assert response.status_code == 200
    assert response.json()["data"]["photo_status"] == "SEARCHING"
    assert repository.received[0] == JOB_ID
    assert repository.received[1]["scores"]["quality"] == 0.91


def test_rejected_result_requires_rejection_code():
    client, repository = make_client()

    response = client.post(
        f"/internal/v1/photo-validations/{JOB_ID}/result",
        headers={"X-DALM-Internal-Key": "internal-test-key"},
        json=result_payload(status="REJECTED"),
    )

    assert response.status_code == 422
    assert repository.received is None


def test_rejected_result_returns_rejected():
    client, repository = make_client()

    response = client.post(
        f"/internal/v1/photo-validations/{JOB_ID}/result",
        headers={"X-DALM-Internal-Key": "internal-test-key"},
        json=result_payload(status="REJECTED", rejection_code="TOO_BLURRY"),
    )

    assert response.status_code == 200
    assert response.json()["data"]["photo_status"] == "REJECTED"
    assert repository.received[1]["rejection_code"] == "TOO_BLURRY"


def test_scores_must_be_probabilities():
    client, repository = make_client()

    response = client.post(
        f"/internal/v1/photo-validations/{JOB_ID}/result",
        headers={"X-DALM-Internal-Key": "internal-test-key"},
        json=result_payload(scores={"quality": 1.1}),
    )

    assert response.status_code == 422
    assert repository.received is None
