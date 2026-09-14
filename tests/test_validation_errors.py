from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.token_store import InMemoryRefreshTokenStore


class FakeDependency:
    async def ping(self): pass
    async def close(self): pass


def test_request_validation_errors_use_common_envelope():
    dependency = FakeDependency()
    client = TestClient(create_app(
        Settings(jwt_secret="test-secret-that-is-long-enough-for-validation"),
        database=dependency, cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
    ))

    response = client.post("/v1/auth/refresh", json={"refresh_token": ""})

    assert response.status_code == 422
    assert response.json()["data"] is None
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["message"] == "요청값이 올바르지 않습니다."
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


def test_validation_error_preserves_request_id():
    dependency = FakeDependency()
    client = TestClient(create_app(
        Settings(jwt_secret="test-secret-that-is-long-enough-for-validation"),
        database=dependency, cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
    ))

    response = client.post(
        "/v1/auth/refresh", json={}, headers={"X-Request-ID": "client-request-id"}
    )

    assert response.json()["error"]["request_id"] == "client-request-id"
