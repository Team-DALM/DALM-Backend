import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.config import Settings
from app.dependencies import get_home_repository
from app.main import create_app
from app.repositories import (
    HomeRepository,
    MatchCardRow,
    MatchDetailRow,
    MomentRow,
    resolve_postcard_permission,
)
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
        self.match_detail = None
        self.visibility = None
        self.photos = {}
        self.deleted_photo = None

    async def get_today_photo(self, user_id, today):
        assert user_id == USER_ID
        assert isinstance(today, date)
        return self.today_photo

    async def get_match_card_for_photo(self, user_id, photo_id):
        return self.match_card

    async def get_photo(self, photo_id):
        return self.photos.get(photo_id)

    async def delete_photo(self, user_id, photo_id):
        assert user_id == USER_ID
        item = self.photos.get(photo_id)
        if item is None:
            from app.errors import ApiError

            raise ApiError(404, "PHOTO_NOT_FOUND", "사진을 찾을 수 없습니다.")
        self.deleted_photo = photo_id

    async def list_searching_photos(self, user_id, **kwargs):
        assert user_id == USER_ID
        self.list_args = kwargs
        return self.searching_photos

    async def list_moments(self, user_id, **kwargs):
        assert user_id == USER_ID
        self.list_args = kwargs
        return [
            MomentRow(
                photo_id=item.id,
                image_url=item.image_url,
                ai_title=item.ai_title,
                status=item.status,
                registered_at=item.registered_at,
                search_expires_at=item.search_expires_at,
                match_id=getattr(item, "match_id", None),
                matched_at=getattr(item, "matched_at", None),
                hidden=getattr(item, "hidden", False),
                postcard_permission=getattr(item, "postcard_permission", None),
            )
            for item in self.searching_photos
        ]

    async def get_next_unviewed_match(self, user_id, today):
        assert user_id == USER_ID
        return self.unviewed

    async def mark_match_viewed(self, user_id, match_id):
        assert user_id == USER_ID
        return self.viewed_at

    async def get_match_detail(self, user_id, match_id):
        assert user_id == USER_ID
        return self.match_detail

    async def update_match_visibility(self, user_id, match_id, *, hidden):
        assert user_id == USER_ID
        self.visibility = hidden
        return hidden


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


def test_get_photo_checks_owner_and_returns_detail() -> None:
    repository = FakeHomeRepository()
    item = photo(user_id=USER_ID)
    repository.photos[item.id] = item
    client, token = make_client(repository)

    response = client.get(f"/v1/photos/{item.id}", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(item.id)


def test_get_someone_elses_photo_returns_403() -> None:
    repository = FakeHomeRepository()
    item = photo(user_id=uuid4())
    repository.photos[item.id] = item
    client, token = make_client(repository)

    response = client.get(f"/v1/photos/{item.id}", headers=auth(token))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PHOTO_NOT_OWNED"


def test_delete_photo_returns_204() -> None:
    repository = FakeHomeRepository()
    item = photo(user_id=USER_ID)
    repository.photos[item.id] = item
    client, token = make_client(repository)

    response = client.delete(f"/v1/photos/{item.id}", headers=auth(token))

    assert response.status_code == 204
    assert repository.deleted_photo == item.id


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


def test_matched_moments_include_match_and_postcard_state() -> None:
    repository = FakeHomeRepository()
    match_id = uuid4()
    matched_at = datetime.now(UTC)
    repository.searching_photos = [
        photo(
            status="MATCHED",
            search_expires_at=None,
            match_id=match_id,
            matched_at=matched_at,
            postcard_permission="WAITING_FOR_REPLY",
        )
    ]
    client, token = make_client(repository)

    response = client.get("/v1/moments?status=MATCHED", headers=auth(token))
    item = response.json()["data"]["items"][0]

    assert response.status_code == 200
    assert item["match_id"] == str(match_id)
    assert item["matched_at"] == matched_at.isoformat().replace("+00:00", "Z")
    assert item["postcard_permission"] == "WAITING_FOR_REPLY"


def test_postcard_permission_covers_send_order_and_block_state() -> None:
    user_id = uuid4()
    partner_id = uuid4()
    assert (
        resolve_postcard_permission(
            blocked=False,
            user_is_first_sender=True,
            last_sender_id=None,
            user_id=user_id,
        )
        == "CAN_SEND"
    )
    assert (
        resolve_postcard_permission(
            blocked=True,
            user_is_first_sender=True,
            last_sender_id=None,
            user_id=user_id,
        )
        == "BLOCKED"
    )
    assert (
        resolve_postcard_permission(
            blocked=False,
            user_is_first_sender=True,
            last_sender_id=user_id,
            user_id=user_id,
        )
        == "WAITING_FOR_REPLY"
    )
    assert (
        resolve_postcard_permission(
            blocked=False,
            user_is_first_sender=False,
            last_sender_id=None,
            user_id=user_id,
        )
        == "WAITING_FOR_FIRST"
    )
    assert (
        resolve_postcard_permission(
            blocked=False,
            user_is_first_sender=False,
            last_sender_id=partner_id,
            user_id=user_id,
        )
        == "CAN_SEND"
    )


def test_moment_query_with_postcard_state_compiles_for_postgresql() -> None:
    class CompilingSession:
        async def execute(self, statement):
            statement.compile(dialect=postgresql.dialect())
            return SimpleNamespace(all=list)

    rows = asyncio.run(
        HomeRepository(CompilingSession()).list_moments(  # type: ignore[arg-type]
            USER_ID,
            status="MATCHED",
            today=datetime.now(UTC).date(),
            exclude_today=False,
            size=20,
            cursor=None,
        )
    )

    assert rows == []


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


def test_match_detail_returns_both_photos_and_partner() -> None:
    repository = FakeHomeRepository()
    now = datetime.now(UTC)
    match_id = uuid4()
    repository.match_detail = MatchDetailRow(
        match_id=match_id,
        my_photo_id=uuid4(),
        my_image_url="https://example.com/mine.jpg",
        my_registered_at=now - timedelta(days=2),
        my_deleted=False,
        partner_photo_id=uuid4(),
        partner_image_url="https://example.com/partner.jpg",
        partner_registered_at=now - timedelta(days=1),
        partner_deleted=False,
        partner_id=uuid4(),
        partner_nickname="나란",
        explanation="빛과 구도가 닮았어요.",
        matched_at=now,
        hidden=False,
        postcard_permission="CAN_SEND",
    )
    client, token = make_client(repository)

    response = client.get(f"/v1/matches/{match_id}", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["data"]["partner"]["nickname"] == "나란"
    assert response.json()["data"]["postcard_permission"] == "CAN_SEND"


def test_match_visibility_can_hide_and_restore() -> None:
    repository = FakeHomeRepository()
    client, token = make_client(repository)
    match_id = uuid4()

    hidden = client.patch(
        f"/v1/matches/{match_id}/visibility",
        headers=auth(token),
        json={"hidden": True},
    )
    restored = client.patch(
        f"/v1/matches/{match_id}/visibility",
        headers=auth(token),
        json={"hidden": False},
    )

    assert hidden.json()["data"]["hidden"] is True
    assert restored.json()["data"]["hidden"] is False
    assert repository.visibility is False
