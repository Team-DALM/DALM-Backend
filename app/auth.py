from typing import Protocol

from app.errors import ApiError
from app.kakao import KakaoClient
from app.models import User, UserStatus
from app.schemas import AuthData, AuthUser
from app.tokens import TokenService


class UserStore(Protocol):
    async def get_by_kakao_id(self, kakao_id: str) -> User | None: ...

    async def create_from_kakao(self, kakao_id: str) -> User: ...


class AuthService:
    def __init__(
        self,
        kakao_client: KakaoClient,
        users: UserStore,
        tokens: TokenService,
    ) -> None:
        self._kakao_client = kakao_client
        self._users = users
        self._tokens = tokens

    async def login_with_kakao(self, kakao_access_token: str) -> tuple[AuthData, bool]:
        profile = await self._kakao_client.get_profile(kakao_access_token)
        user = await self._users.get_by_kakao_id(profile.kakao_id)
        is_new_user = user is None
        if user is None:
            user = await self._users.create_from_kakao(profile.kakao_id)

        if user.status == UserStatus.RESTRICTED.value:
            raise ApiError(403, "ACCOUNT_RESTRICTED", "이용이 제한된 계정입니다.")
        if user.status == UserStatus.WITHDRAWN.value:
            raise ApiError(403, "ACCOUNT_WITHDRAWN", "탈퇴한 계정입니다.")

        token_pair = await self._tokens.issue_pair(str(user.id))
        return (
            AuthData(
                is_new_user=is_new_user,
                onboarding_required=user.onboarding_required,
                tokens=token_pair,
                user=AuthUser(
                    id=user.id,
                    nickname=user.nickname,
                    status=user.status,
                ),
            ),
            is_new_user,
        )

