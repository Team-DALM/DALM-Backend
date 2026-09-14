import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_notification_repository
from app.errors import ApiError
from app.main import create_app
from app.token_store import InMemoryRefreshTokenStore

SETTINGS = Settings(jwt_secret="test-secret-that-is-long-enough-for-notification-tests")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeDependency:
    async def ping(self): pass
    async def close(self): pass


def notification(index=0, read=False):
    return SimpleNamespace(
        id=uuid4(), type="MATCHED", title="새로운 순간", message="닮은 순간을 찾았어요.",
        target_type="MATCH", target_id=uuid4(),
        read_at=datetime.now(UTC) if read else None,
        created_at=datetime.now(UTC) - timedelta(minutes=index),
    )


class FakeNotificationRepository:
    def __init__(self):
        self.items = []
        self.marked = None
        self.all_read = False

    async def list(self, user_id, **kwargs):
        assert user_id == USER_ID
        return self.items, sum(item.read_at is None for item in self.items)

    async def mark_read(self, user_id, notification_id):
        self.marked = notification_id
        for item in self.items:
            if item.id == notification_id:
                item.read_at = datetime.now(UTC)
                return item
        raise ApiError(404, "NOTIFICATION_NOT_FOUND", "알림을 찾을 수 없습니다.")

    async def mark_all_read(self, user_id):
        assert user_id == USER_ID
        self.all_read = True


def make_client(repository=None):
    dependency = FakeDependency()
    repository = repository or FakeNotificationRepository()
    app = create_app(
        SETTINGS, database=dependency, cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
    )
    app.dependency_overrides[get_notification_repository] = lambda: repository
    client = TestClient(app)
    token = asyncio.run(client.app.state.token_service.issue_pair(str(USER_ID))).access_token
    return client, {"Authorization": f"Bearer {token}"}, repository


def test_list_notifications_returns_unread_count_and_cursor():
    repository = FakeNotificationRepository()
    repository.items = [notification(i, read=i == 0) for i in range(3)]
    client, headers, _ = make_client(repository)

    response = client.get("/v1/notifications?size=2", headers=headers)

    data = response.json()["data"]
    assert response.status_code == 200
    assert len(data["items"]) == 2
    assert data["unread_count"] == 2
    assert data["has_next"] is True
    assert data["next_cursor"]


def test_mark_notification_read_is_idempotent():
    repository = FakeNotificationRepository()
    item = notification()
    repository.items = [item]
    client, headers, _ = make_client(repository)

    response = client.patch(f"/v1/notifications/{item.id}/read", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["is_read"] is True


def test_mark_unknown_notification_returns_404():
    client, headers, _ = make_client()

    response = client.patch(f"/v1/notifications/{uuid4()}/read", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"


def test_mark_all_notifications_read():
    client, headers, repository = make_client()

    response = client.patch("/v1/notifications/read-all", headers=headers)

    assert response.status_code == 204
    assert repository.all_read is True
