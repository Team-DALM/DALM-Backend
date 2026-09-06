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

TEST_SETTINGS = Settings(jwt_secret="test-secret-that-is-long-enough-for-home-apis")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeDependency:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeHomeRepository:
    def __init__(self) -> None:
        self.today_photo = None
        self.match_card = None
        self.searching_photos = []
        self.unviewed = (None, 0)
        self.viewed_at = None
        self.list_args = None

    async def get_today_photo(self, user_id, today):
        assert user_id == USER_ID
        assert isinstance(today, date)
        return self.today_photo

    async def get_match_card_for_photo(self, user_id, photo_id):
        return self.match_card

    async def list_searching_photos(self, user_id, **kwargs):
        assert user_id == USER_ID
        self.list_args = kwargs
        return self.searching_photos

    async def get_next_unviewed_match(self, user_id, today):
        assert user_id == USER_ID
        return self.unviewed

    async def mark_match_viewed(self, user_id, match_id):
        assert user_id == USER_ID
        return self.viewed_at


def make_client(repository: FakeHomeRepository) -> tuple[TestClient, str]:
    dependency = FakeDependency()
    app = create_app(
        TEST_SETTINGS,
        database=dependency,
        cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
    )
    app.dependency_overrides[get_home_repository] = lambda: repository
    client = TestClient(app)
    token = asyncio.run(client.app.state.token_service.issue_pair(str(USER_ID))).access_token
    return client, token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def photo(**overrides):
    values = {
        "id": uuid4(),
        "status": "SEARCHING",
        "image_url": "https://example.com/photo.jpg",
        "ai_title": "비가 그친 골목",
        "registered_at": datetime.now(UTC),
        "search_expires_at": datetime.now(UTC) + timedelta(days=6, hours=1),
        "rejection_code": None,
        "rejection_message": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_today_photo_returns_empty_contract() -> None:
    repository = FakeHomeRepository()
    client, token = make_client(repository)

    response = client.get("/v1/photos/today", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["data"] == {"can_register": True, "photo": None}


def test_today_rejected_photo_can_be_registered_again() -> None:
    repository = FakeHomeRepository()
    repository.today_photo = photo(
        status="REJECTED",
        ai_title=None,
        search_expires_at=None,
        rejection_code="TOO_BLURRY",
        rejection_message="사진이 너무 흐릿해요.",
    )
    client, token = make_client(repository)

    data = client.get("/v1/photos/today", headers=auth(token)).json()["data"]

    assert data["can_register"] is True
    assert data["photo"]["rejection"] == {
        "code": "TOO_BLURRY",
        "message": "사진이 너무 흐릿해요.",
    }
    assert data["photo"]["remaining_days"] is None


def test_today_matched_photo_contains_partner_data() -> None:
    repository = FakeHomeRepository()
    today_photo = photo(status="MATCHED", search_expires_at=None)
    repository.today_photo = today_photo
    repository.match_card = MatchCardRow(
        uuid4(),
        today_photo.id,
        today_photo.image_url,
        "https://example.com/partner.jpg",
        "서로 다른 날의 빛",
        datetime.now(UTC),
    )
    client, token = make_client(repository)

    result = client.get("/v1/photos/today", headers=auth(token)).json()["data"]["photo"]

    assert result["match_id"] == str(repository.match_card.match_id)
    assert result["partner_image_url"] == "https://example.com/partner.jpg"
    assert result["matched_at"] is not None


def test_searching_moments_exclude_today_and_paginate() -> None:
    repository = FakeHomeRepository()
    repository.searching_photos = [photo() for _ in range(3)]
    client, token = make_client(repository)

    response = client.get(
        "/v1/moments?status=SEARCHING&exclude_today=true&size=2",
        headers=auth(token),
    )
    data = response.json()["data"]

    assert response.status_code == 200
    assert len(data["items"]) == 2
    assert data["items"][0]["photo_id"]
    assert data["items"][0]["remaining_days"] == 7
    assert data["has_next"] is True
    assert data["next_cursor"] is not None
    assert repository.list_args["exclude_today"] is True
    assert repository.list_args["size"] == 2


def test_unviewed_match_and_idempotent_view_contract() -> None:
    repository = FakeHomeRepository()
    match_id = uuid4()
    matched_at = datetime.now(UTC)
    repository.unviewed = (
        MatchCardRow(
            match_id,
            uuid4(),
            "https://example.com/mine.jpg",
            "https://example.com/partner.jpg",
            "닮은 순간",
            matched_at,
        ),
        2,
    )
    repository.viewed_at = matched_at + timedelta(minutes=1)
    client, token = make_client(repository)

    unviewed = client.get("/v1/matches/unviewed/next", headers=auth(token)).json()["data"]
    viewed = client.patch(f"/v1/matches/{match_id}/viewed", headers=auth(token)).json()["data"]

    assert unviewed["match"]["match_id"] == str(match_id)
    assert unviewed["unviewed_match_count"] == 2
    assert viewed == {
        "match_id": str(match_id),
        "viewed_at": repository.viewed_at.isoformat().replace("+00:00", "Z"),
    }


def test_viewing_unknown_match_returns_404() -> None:
    repository = FakeHomeRepository()
    client, token = make_client(repository)

    response = client.patch(f"/v1/matches/{uuid4()}/viewed", headers=auth(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MATCH_NOT_FOUND"
