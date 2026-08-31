from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.token_store import InMemoryRefreshTokenStore

TEST_SETTINGS = Settings(
    jwt_secret="test-secret-that-is-long-enough-for-hs256",
    access_token_ttl_seconds=300,
    refresh_token_ttl_seconds=3600,
)


class FakeDependency:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


def make_client(settings: Settings = TEST_SETTINGS) -> TestClient:
    dependency = FakeDependency()
    return TestClient(
        create_app(
            settings,
            database=dependency,
            cache=dependency,
            refresh_store=InMemoryRefreshTokenStore(),
        )
    )


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


def test_expired_refresh_token_has_specific_error_code() -> None:
    settings = Settings(
        jwt_secret=TEST_SETTINGS.jwt_secret,
        access_token_ttl_seconds=300,
        refresh_token_ttl_seconds=-1,
    )
    client = make_client(settings)
    pair = issue_pair(client)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": pair.refresh_token},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "REFRESH_TOKEN_EXPIRED"


def test_expired_access_token_has_specific_error_code() -> None:
    settings = Settings(
        jwt_secret=TEST_SETTINGS.jwt_secret,
        access_token_ttl_seconds=-1,
        refresh_token_ttl_seconds=3600,
    )
    client = make_client(settings)
    pair = issue_pair(client)

    response = client.post(
        "/v1/auth/logout",
        json={"refresh_token": pair.refresh_token},
        headers={"Authorization": f"Bearer {pair.access_token}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ACCESS_TOKEN_EXPIRED"


def test_expired_access_token_cannot_be_used_as_refresh_token() -> None:
    settings = Settings(
        jwt_secret=TEST_SETTINGS.jwt_secret,
        access_token_ttl_seconds=-1,
        refresh_token_ttl_seconds=3600,
    )
    client = make_client(settings)
    pair = issue_pair(client)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": pair.access_token},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


def test_expired_refresh_token_cannot_be_used_as_access_token() -> None:
    settings = Settings(
        jwt_secret=TEST_SETTINGS.jwt_secret,
        access_token_ttl_seconds=300,
        refresh_token_ttl_seconds=-1,
    )
    client = make_client(settings)
    pair = issue_pair(client)

    response = client.post(
        "/v1/auth/logout",
        json={"refresh_token": pair.refresh_token},
        headers={"Authorization": f"Bearer {pair.refresh_token}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


def test_logout_requires_access_token_and_revokes_refresh_token() -> None:
    client = make_client()
    pair = issue_pair(client)

    missing = client.post(
        "/v1/auth/logout",
        json={"refresh_token": pair.refresh_token},
    )
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    success = client.post(
        "/v1/auth/logout",
        json={"refresh_token": pair.refresh_token},
        headers={"Authorization": f"Bearer {pair.access_token}"},
    )
    assert success.status_code == 204

    refresh = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": pair.refresh_token},
    )
    assert refresh.status_code == 401


def test_logout_rejects_refresh_token_from_another_user() -> None:
    client = make_client()
    first = issue_pair(client, "user-1")
    second = issue_pair(client, "user-2")

    response = client.post(
        "/v1/auth/logout",
        json={"refresh_token": second.refresh_token},
        headers={"Authorization": f"Bearer {first.access_token}"},
    )

    assert response.status_code == 401


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
