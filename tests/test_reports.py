import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_report_repository
from app.errors import ApiError
from app.main import create_app
from app.token_store import InMemoryRefreshTokenStore

SETTINGS = Settings(jwt_secret="test-secret-that-is-long-enough-for-report-tests")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeDependency:
    async def ping(self): pass
    async def close(self): pass


class FakeReportRepository:
    def __init__(self): self.values = None

    async def create(self, **values):
        self.values = values
        if values["target_type"] == "POSTCARD":
            raise ApiError(422, "POSTCARD_REPORT_NOT_AVAILABLE", "아직 준비되지 않았습니다.")
        return SimpleNamespace(
            id=uuid4(), status="PENDING", created_at=datetime.now(UTC), **values
        )


def make_client():
    dependency = FakeDependency()
    repository = FakeReportRepository()
    app = create_app(
        SETTINGS, database=dependency, cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
    )
    app.dependency_overrides[get_report_repository] = lambda: repository
    client = TestClient(app)
    token = asyncio.run(client.app.state.token_service.issue_pair(str(USER_ID))).access_token
    return client, {"Authorization": f"Bearer {token}"}, repository


def test_create_user_report():
    client, headers, repository = make_client()
    target_id = uuid4()

    response = client.post(
        "/v1/reports",
        headers=headers,
        json={
            "target_type": "USER",
            "target_id": str(target_id),
            "reason_code": "HATE_OR_DISCRIMINATION",
            "detail": "  불쾌한 표현  ",
        },
    )

    assert response.status_code == 201
    assert response.json()["data"]["status"] == "PENDING"
    assert repository.values["reporter_id"] == USER_ID
    assert repository.values["detail"] == "불쾌한 표현"


def test_report_rejects_unknown_reason():
    client, headers, repository = make_client()

    response = client.post(
        "/v1/reports",
        headers=headers,
        json={"target_type": "USER", "target_id": str(uuid4()), "reason_code": "UNKNOWN"},
    )

    assert response.status_code == 422
    assert repository.values is None


def test_postcard_report_is_explicitly_deferred():
    client, headers, _ = make_client()

    response = client.post(
        "/v1/reports",
        headers=headers,
        json={
            "target_type": "POSTCARD",
            "target_id": str(uuid4()),
            "reason_code": "OFFENSIVE_POSTCARD",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "POSTCARD_REPORT_NOT_AVAILABLE"
