import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_postcard_repository
from app.main import create_app
from app.repositories import PostcardRow
from app.token_store import InMemoryRefreshTokenStore

SETTINGS = Settings(jwt_secret="test-secret-that-is-long-enough-for-postcard-tests")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeDependency:
    async def ping(self):
        pass

    async def close(self):
        pass


def row(index=0, read=False):
    return PostcardRow(
        uuid4(),
        uuid4(),
        USER_ID,
        "달음",
        uuid4(),
        "나란",
        "반가워요",
        datetime.now(UTC) if read else None,
        datetime.now(UTC) - timedelta(minutes=index),
        "https://example.com/moment.jpg",
    )


class FakePostcardRepository:
    def __init__(self):
        self.rows = []
        self.sent = None
        self.deleted = None

    async def send(self, user_id, match_id, content):
        self.sent = (user_id, match_id, content)
        item = row()
        self.rows = [item]
        return item

    async def list(self, user_id, **kwargs):
        return self.rows

    async def get(self, user_id, postcard_id):
        return self.rows[0]

    async def mark_read(self, user_id, postcard_id):
        item = self.rows[0]
        return (
            PostcardRow(*item.__dict__.values())
            if item.read_at
            else PostcardRow(
                item.id,
                item.match_id,
                item.sender_id,
                item.sender_nickname,
                item.receiver_id,
                item.receiver_nickname,
                item.content,
                datetime.now(UTC),
                item.sent_at,
                item.moment_thumbnail_url,
            )
        )

    async def delete(self, user_id, postcard_id):
        self.deleted = postcard_id


def make_client(repository=None):
    dependency = FakeDependency()
    repository = repository or FakePostcardRepository()
    app = create_app(
        SETTINGS,
        database=dependency,
        cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
    )
    app.dependency_overrides[get_postcard_repository] = lambda: repository
    client = TestClient(app)
    token = asyncio.run(client.app.state.token_service.issue_pair(str(USER_ID))).access_token
    return client, {"Authorization": f"Bearer {token}"}, repository


def test_send_postcard_trims_content():
    client, headers, repository = make_client()
    match_id = uuid4()

    response = client.post(
        f"/v1/matches/{match_id}/postcards",
        headers=headers,
        json={"content": "  반가워요  "},
    )

    assert response.status_code == 201
    assert repository.sent == (USER_ID, match_id, "반가워요")


def test_send_postcard_rejects_blank_content():
    client, headers, repository = make_client()

    response = client.post(
        f"/v1/matches/{uuid4()}/postcards", headers=headers, json={"content": "   "}
    )

    assert response.status_code == 422
    assert repository.sent is None


def test_list_postcards_uses_cursor_pagination():
    repository = FakePostcardRepository()
    repository.rows = [row(i) for i in range(3)]
    client, headers, _ = make_client(repository)

    response = client.get("/v1/postcards/received?size=2", headers=headers)

    data = response.json()["data"]
    assert len(data["items"]) == 2
    assert data["has_next"] is True
    assert data["next_cursor"]


def test_read_and_delete_postcard():
    repository = FakePostcardRepository()
    item = row()
    repository.rows = [item]
    client, headers, _ = make_client(repository)

    read = client.patch(f"/v1/postcards/{item.id}/read", headers=headers)
    deleted = client.delete(f"/v1/postcards/{item.id}", headers=headers)

    assert read.status_code == 200
    assert read.json()["data"]["is_read"] is True
    assert deleted.status_code == 204
    assert repository.deleted == item.id
