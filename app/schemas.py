from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    data: T
    error: None = None


class KakaoLoginRequest(BaseModel):
    access_token: str = Field(min_length=1)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int


class AuthUser(BaseModel):
    id: UUID
    nickname: str | None
    status: str


class AuthData(BaseModel):
    is_new_user: bool
    onboarding_required: bool
    tokens: TokenPair
    user: AuthUser

