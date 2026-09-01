import asyncio
from datetime import date

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.token_store import InMemoryRefreshTokenStore

TEST_SETTINGS = Settings(jwt_secret="test-secret-that-is-long-enough-for-home")


class FakeDependency:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


def make_client() -> TestClient:
    dependency = FakeDependency()
    return TestClient(
        create_app(
            TEST_SETTINGS,
            database=dependency,
            cache=dependency,
            refresh_store=InMemoryRefreshTokenStore(),
        )
    )


def issue_access_token(client: TestClient) -> str:
    pair = asyncio.run(client.app.state.token_service.issue_pair("user-1"))
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
