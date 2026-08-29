from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TEST_SETTINGS = Settings(
    jwt_secret="test-secret-that-is-long-enough-for-hs256",
    access_token_ttl_seconds=300,
    refresh_token_ttl_seconds=3600,
)


def make_client() -> TestClient:
    return TestClient(create_app(TEST_SETTINGS))


def issue_pair(client: TestClient, subject: str = "user-1"):
    import asyncio

    return asyncio.run(client.app.state.token_service.issue_pair(subject))


def test_refresh_rotates_token_pair_and_matches_flutter_contract() -> None:
    client = make_client()
    original = issue_pair(client)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": original.refresh_token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"]["access_token"] != original.access_token
    assert body["data"]["refresh_token"] != original.refresh_token
    assert body["data"]["token_type"] == "Bearer"
    assert body["data"]["expires_in"] == 300


def test_refresh_token_cannot_be_reused() -> None:
    client = make_client()
    original = issue_pair(client)

    assert client.post(
        "/v1/auth/refresh", json={"refresh_token": original.refresh_token}
    ).status_code == 200
    response = client.post(
        "/v1/auth/refresh", json={"refresh_token": original.refresh_token}
    )

    assert response.status_code == 401
    assert response.json()["data"] is None
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"
    assert response.json()["error"]["request_id"]


def test_access_token_cannot_refresh() -> None:
    client = make_client()
    original = issue_pair(client)

    response = client.post(
        "/v1/auth/refresh", json={"refresh_token": original.access_token}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


def test_protected_endpoint_requires_bearer_access_token() -> None:
    client = make_client()

    missing = client.post("/v1/auth/logout")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    pair = issue_pair(client)
    success = client.post(
        "/v1/auth/logout",
        headers={"Authorization": f"Bearer {pair.access_token}"},
    )
    assert success.status_code == 204


def test_concurrent_refresh_allows_only_one_rotation() -> None:
    client = make_client()
    original = issue_pair(client)

    def refresh() -> int:
        return client.post(
            "/v1/auth/refresh", json={"refresh_token": original.refresh_token}
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as executor:
        statuses = list(executor.map(lambda _: refresh(), range(4)))

    assert statuses.count(200) == 1
    assert statuses.count(401) == 3

