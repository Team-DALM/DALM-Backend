from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth import AuthService
from app.config import Settings
from app.dependencies import get_auth_service
from app.kakao import KakaoProfile
from app.main import create_app
from app.models import User, UserStatus

TEST_SETTINGS = Settings(jwt_secret="test-secret-that-is-long-enough-for-login")


class FakeDependency:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeKakaoClient:
    async def get_profile(self, access_token: str) -> KakaoProfile:
        assert access_token == "kakao-token"
        return KakaoProfile(kakao_id="123456789")


class FakeUserStore:
    def __init__(self, user: User | None = None) -> None:
        self.user = user

    async def get_by_kakao_id(self, kakao_id: str) -> User | None:
        return self.user

    async def create_from_kakao(self, kakao_id: str) -> User:
        self.user = make_user(kakao_id=kakao_id)
        return self.user


def make_user(
    *,
    kakao_id: str = "123456789",
    nickname: str | None = None,
    status: str = UserStatus.ACTIVE.value,
) -> User:
    return User(
        id=uuid4(),
        kakao_id=kakao_id,
        nickname=nickname,
        status=status,
    )


def make_client(users: FakeUserStore) -> TestClient:
    dependency = FakeDependency()
    app = create_app(TEST_SETTINGS, database=dependency, cache=dependency)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        FakeKakaoClient(),
        users,
        app.state.token_service,
    )
    return TestClient(app)


def test_new_kakao_user_is_created_and_requires_onboarding() -> None:
    with make_client(FakeUserStore()) as client:
        response = client.post(
            "/v1/auth/kakao",
            json={"access_token": "kakao-token"},
        )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["is_new_user"] is True
    assert body["onboarding_required"] is True
    assert body["user"]["nickname"] is None
    assert body["tokens"]["token_type"] == "Bearer"


def test_existing_kakao_user_logs_in_with_200() -> None:
    user = make_user(nickname="달미")

    with make_client(FakeUserStore(user)) as client:
        response = client.post(
            "/v1/auth/kakao",
            json={"access_token": "kakao-token"},
        )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["is_new_user"] is False
    assert body["onboarding_required"] is False
    assert body["user"]["nickname"] == "달미"


def test_restricted_kakao_user_is_rejected() -> None:
    user = make_user(status=UserStatus.RESTRICTED.value)

    with make_client(FakeUserStore(user)) as client:
        response = client.post(
            "/v1/auth/kakao",
            json={"access_token": "kakao-token"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_RESTRICTED"

