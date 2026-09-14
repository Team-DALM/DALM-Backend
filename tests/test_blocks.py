import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_safety_repository
from app.errors import ApiError
from app.main import create_app
from app.repositories import BlockedUserRow
from app.token_store import InMemoryRefreshTokenStore

SETTINGS = Settings(jwt_secret="test-secret-that-is-long-enough-for-block-tests")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeDependency:
    async def ping(self): pass
    async def close(self): pass


class FakeSafetyRepository:
    def __init__(self):
        self.rows = []
        self.blocked = None
        self.unblocked = None

    async def list_blocks(self, blocker_id, **kwargs):
        assert blocker_id == USER_ID
        return self.rows

    async def block(self, blocker_id, blocked_id):
        if blocker_id == blocked_id:
            raise ApiError(409, "CANNOT_BLOCK_SELF", "본인은 차단할 수 없습니다.")
        self.blocked = blocked_id

    async def unblock(self, blocker_id, blocked_id):
        self.unblocked = blocked_id


def make_client(repository=None):
    dependency = FakeDependency()
    repository = repository or FakeSafetyRepository()
    app = create_app(
        SETTINGS, database=dependency, cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
    )
    app.dependency_overrides[get_safety_repository] = lambda: repository
    client = TestClient(app)
    token = asyncio.run(client.app.state.token_service.issue_pair(str(USER_ID))).access_token
    return client, {"Authorization": f"Bearer {token}"}, repository


def test_list_blocks_uses_cursor_pagination():
    repository = FakeSafetyRepository()
    now = datetime.now(UTC)
    repository.rows = [
        BlockedUserRow(uuid4(), f"사용자{i}", None, now - timedelta(minutes=i))
        for i in range(3)
    ]
    client, headers, _ = make_client(repository)

    response = client.get("/v1/blocks?size=2", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["items"]) == 2
    assert data["has_next"] is True
    assert data["next_cursor"]


def test_block_and_idempotent_unblock():
    client, headers, repository = make_client()
    target = uuid4()

    blocked = client.post(f"/v1/blocks/{target}", headers=headers)
    unblocked = client.delete(f"/v1/blocks/{target}", headers=headers)

    assert blocked.status_code == 204
    assert unblocked.status_code == 204
    assert repository.blocked == target
    assert repository.unblocked == target


def test_cannot_block_self():
    client, headers, _ = make_client()

    response = client.post(f"/v1/blocks/{USER_ID}", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANNOT_BLOCK_SELF"
