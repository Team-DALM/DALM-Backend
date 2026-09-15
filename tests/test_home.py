import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_home_repository
from app.main import create_app
from app.repositories import MatchCardRow
from app.token_store import InMemoryRefreshTokenStore

TEST_SETTINGS = Settings(jwt_secret="test-secret-that-is-long-enough-for-home")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeDependency:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeHomeRepository:
    def __init__(self):
        self.today_photo = None
        self.searching = []
        self.unviewed = (None, 0)

    async def get_today_photo(self, user_id, today):
        return self.today_photo

    async def list_searching_photos(self, user_id, **kwargs):
        return self.searching

    async def get_next_unviewed_match(self, user_id, today):
        return self.unviewed


def make_client(repository=None) -> TestClient:
    dependency = FakeDependency()
    app = create_app(
        TEST_SETTINGS,
        database=dependency,
        cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
    )
    app.dependency_overrides[get_home_repository] = lambda: repository or FakeHomeRepository()
    return TestClient(app)


def issue_access_token(client: TestClient) -> str:
    pair = asyncio.run(client.app.state.token_service.issue_pair(str(USER_ID)))
    return pair.access_token


def test_home_returns_empty_state_for_authenticated_user() -> None:
    client = make_client()
    access_token = issue_access_token(client)

    response = client.get(
        "/v1/home",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert date.fromisoformat(body["data"]["date"])
    assert body["data"] == {
        "date": body["data"]["date"],
        "state": "EMPTY",
        "can_upload_today": True,
        "today_photo": None,
        "searching_photos": [],
        "new_match": None,
    }


def test_home_requires_authorization_header() -> None:
    response = make_client().get("/v1/home")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_home_returns_today_searching_state():
    repository = FakeHomeRepository()
    repository.today_photo = SimpleNamespace(
        id=uuid4(),
        status="SEARCHING",
        image_url="https://example.com/today.jpg",
        registered_at=datetime.now(UTC),
        search_expires_at=datetime.now(UTC) + timedelta(days=6),
    )
    client = make_client(repository)

    response = client.get(
        "/v1/home", headers={"Authorization": f"Bearer {issue_access_token(client)}"}
    )

    assert response.json()["data"]["state"] == "TODAY_SEARCHING"
    assert response.json()["data"]["can_upload_today"] is False
    assert response.json()["data"]["today_photo"]["id"] == str(repository.today_photo.id)


def test_home_prioritizes_previous_unviewed_match():
    repository = FakeHomeRepository()
    matched_at = datetime.now(UTC)
    match_id = uuid4()
    repository.unviewed = (
        MatchCardRow(
            match_id,
            uuid4(),
            "https://example.com/mine.jpg",
            "https://example.com/partner.jpg",
            "닮은 순간",
            matched_at,
        ),
        1,
    )
    client = make_client(repository)

    response = client.get(
        "/v1/home", headers={"Authorization": f"Bearer {issue_access_token(client)}"}
    )

    assert response.json()["data"]["state"] == "PREVIOUS_MATCHED"
    assert response.json()["data"]["new_match"]["id"] == str(match_id)
