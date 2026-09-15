from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.apple import AppleClient
from app.auth import AuthService
from app.errors import ApiError
from app.kakao import KakaoClient
from app.repositories import (
    HomeRepository,
    NotificationPreferenceRepository,
    NotificationRepository,
    PostcardRepository,
    ReportRepository,
    SafetyRepository,
    UserRepository,
)
from app.tokens import TokenClaims, TokenService

bearer_scheme = HTTPBearer(auto_error=False)


def get_token_service(request: Request) -> TokenService:
    return request.app.state.token_service


def get_kakao_client(request: Request) -> KakaoClient:
    return request.app.state.kakao_client


def get_apple_client(request: Request) -> AppleClient:
    return request.app.state.apple_client


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async for session in request.app.state.database.session():
        yield session


def get_user_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserRepository:
    return UserRepository(session)


def get_home_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HomeRepository:
    return HomeRepository(session)


def get_notification_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NotificationRepository:
    return NotificationRepository(session)


def get_notification_preference_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NotificationPreferenceRepository:
    return NotificationPreferenceRepository(session)


def get_postcard_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PostcardRepository:
    return PostcardRepository(session)


def get_report_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReportRepository:
    return ReportRepository(session)


def get_safety_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SafetyRepository:
    return SafetyRepository(session)


def get_auth_service(
    kakao: Annotated[KakaoClient, Depends(get_kakao_client)],
    apple: Annotated[AppleClient, Depends(get_apple_client)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> AuthService:
    return AuthService(kakao, apple, users, tokens)


def require_access_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Annotated[TokenService, Depends(get_token_service)],
) -> TokenClaims:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "인증이 필요합니다.")
    return service.decode(credentials.credentials, "access")
