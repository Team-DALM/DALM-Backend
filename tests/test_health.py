from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TEST_SETTINGS = Settings(jwt_secret="test-secret-that-is-long-enough-for-health")


class FakeDependency:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.closed = False

    async def ping(self) -> None:
        if not self.available:
            raise ConnectionError("dependency unavailable")

    async def close(self) -> None:
        self.closed = True


def test_health_is_independent_from_external_dependencies() -> None:
    database = FakeDependency(available=False)
    cache = FakeDependency(available=False)

    with TestClient(create_app(TEST_SETTINGS, database=database, cache=cache)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert database.closed is True
    assert cache.closed is True


def test_readiness_reports_healthy_dependencies() -> None:
    with TestClient(
        create_app(
            TEST_SETTINGS,
            database=FakeDependency(),
            cache=FakeDependency(),
        )
    ) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"database": "ok", "redis": "ok"},
    }


def test_readiness_returns_503_when_a_dependency_is_unavailable() -> None:
    with TestClient(
        create_app(
            TEST_SETTINGS,
            database=FakeDependency(available=False),
            cache=FakeDependency(),
        )
    ) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {"database": "unavailable", "redis": "ok"},
    }

