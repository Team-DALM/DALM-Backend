from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.config import Settings
from app.dependencies import get_auth_service
from app.main import create_app


class FakeDependency:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


def unavailable_auth_service():
    raise RedisError("redis unavailable")


def test_redis_failure_uses_common_service_unavailable_contract() -> None:
    dependency = FakeDependency()
    app = create_app(
        Settings(jwt_secret="test-secret-that-is-long-enough-for-infra"),
        database=dependency,
        cache=dependency,
    )
    app.dependency_overrides[get_auth_service] = unavailable_auth_service

    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/kakao",
            json={"access_token": "kakao-token"},
        )

    assert response.status_code == 503
    assert response.json()["data"] is None
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert response.json()["error"]["request_id"]

