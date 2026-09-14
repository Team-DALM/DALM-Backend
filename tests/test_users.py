import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_user_repository
from app.main import create_app
from app.token_store import InMemoryRefreshTokenStore

TEST_SETTINGS = Settings(jwt_secret="test-secret-that-is-long-enough-for-user-tests")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeDependency:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


def user(nickname="달음", bio=None, status="ACTIVE"):
    return SimpleNamespace(
        id=USER_ID,
        nickname=nickname,
        bio=bio,
        status=status,
        onboarding_required=nickname is None,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


class FakeUserRepository:
    def __init__(self) -> None:
        self.current = user(nickname=None)
        self.onboarding_values = None
        self.update_values = None
        self.withdrawn = False

    async def get_by_id(self, user_id):
        assert user_id == USER_ID
        return self.current

    async def complete_onboarding(self, user_id, **values):
        assert user_id == USER_ID
        self.onboarding_values = values
        self.current = user(values["nickname"], values["bio"])
        return self.current

    async def update_profile(self, user_id, **values):
        assert user_id == USER_ID
        self.update_values = values
        nickname = values["nickname"] or self.current.nickname
        bio = values["bio"] if values["update_bio"] else self.current.bio
        self.current = user(nickname, bio)
        return self.current

    async def withdraw(self, user_id):
        assert user_id == USER_ID
        self.withdrawn = True

    async def get_stats(self, user_id):
        assert user_id == USER_ID
        return 3, 2, 0


def make_client(repository=None):
    dependency = FakeDependency()
    repository = repository or FakeUserRepository()
    app = create_app(
        TEST_SETTINGS,
        database=dependency,
        cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
    )
    app.dependency_overrides[get_user_repository] = lambda: repository
    client = TestClient(app)
    token = asyncio.run(client.app.state.token_service.issue_pair(str(USER_ID))).access_token
    return client, token, repository


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_complete_onboarding_saves_terms_and_profile() -> None:
    client, token, repository = make_client()

    response = client.post(
        "/v1/users/onboarding",
        headers=auth(token),
        data={
            "nickname": "  달음이  ",
            "bio": "  오늘의 장면  ",
            "service_terms_agreed": "true",
            "privacy_policy_agreed": "true",
            "age_14_confirmed": "true",
            "marketing_agreed": "false",
            "service_terms_version": "2026-09",
            "privacy_policy_version": "2026-09",
        },
    )

    assert response.status_code == 201
    assert response.json()["data"]["nickname"] == "달음이"
    assert response.json()["data"]["stats"] == {
        "photo_count": 3,
        "match_count": 2,
        "received_postcard_count": 0,
    }
    assert repository.onboarding_values["bio"] == "오늘의 장면"
    assert repository.onboarding_values["service_terms_version"] == "2026-09"


def test_onboarding_requires_all_mandatory_terms() -> None:
    client, token, repository = make_client()

    response = client.post(
        "/v1/users/onboarding",
        headers=auth(token),
        data={
            "nickname": "달음이",
            "service_terms_agreed": "true",
            "privacy_policy_agreed": "false",
            "age_14_confirmed": "true",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUIRED_TERMS_NOT_AGREED"
    assert repository.onboarding_values is None


def test_profile_image_is_explicitly_deferred_until_storage_is_ready() -> None:
    client, token, repository = make_client()

    response = client.post(
        "/v1/users/onboarding",
        headers=auth(token),
        data={
            "nickname": "달음이",
            "service_terms_agreed": "true",
            "privacy_policy_agreed": "true",
            "age_14_confirmed": "true",
        },
        files={"profile_image": ("profile.jpg", b"not-uploaded", "image/jpeg")},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PROFILE_IMAGE_STORAGE_NOT_CONFIGURED"
    assert repository.onboarding_values is None


def test_get_and_update_my_profile() -> None:
    repository = FakeUserRepository()
    repository.current = user("달음", "기존 소개")
    client, token, _ = make_client(repository)

    profile = client.get("/v1/users/me", headers=auth(token))
    updated = client.patch(
        "/v1/users/me",
        headers=auth(token),
        data={"nickname": "새달음", "bio": "새 소개"},
    )

    assert profile.status_code == 200
    assert profile.json()["data"]["nickname"] == "달음"
    assert updated.status_code == 200
    assert updated.json()["data"]["nickname"] == "새달음"
    assert repository.update_values["update_bio"] is True


def test_update_profile_rejects_empty_request() -> None:
    repository = FakeUserRepository()
    repository.current = user()
    client, token, _ = make_client(repository)

    response = client.patch("/v1/users/me", headers=auth(token), data={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_PROFILE_UPDATE"


def test_withdraw_requires_explicit_confirmation() -> None:
    repository = FakeUserRepository()
    repository.current = user()
    client, token, _ = make_client(repository)

    rejected = client.request(
        "DELETE", "/v1/users/me", headers=auth(token), json={"confirmation": False}
    )
    accepted = client.request(
        "DELETE", "/v1/users/me", headers=auth(token), json={"confirmation": True}
    )

    assert rejected.status_code == 422
    assert accepted.status_code == 202
    assert repository.withdrawn is True
