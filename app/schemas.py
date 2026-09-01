from datetime import date, datetime
from enum import StrEnum
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


class HomeState(StrEnum):
    EMPTY = "EMPTY"
    TODAY_AVAILABLE_WITH_HISTORY = "TODAY_AVAILABLE_WITH_HISTORY"
    TODAY_SEARCHING = "TODAY_SEARCHING"
    PREVIOUS_MATCHED = "PREVIOUS_MATCHED"
    TODAY_MATCHED = "TODAY_MATCHED"


class HomePhotoSummary(BaseModel):
    id: UUID
    image_url: str
    captured_at: datetime
    search_day: int = Field(ge=1, le=7)


class HomeMatchSummary(BaseModel):
    id: UUID
    photo_id: UUID
    photo_image_url: str
    matched_at: datetime
    distance_km: float | None = Field(default=None, ge=0)


class HomeData(BaseModel):
    date: date
    state: HomeState
    can_upload_today: bool
    today_photo: HomePhotoSummary | None = None
    searching_photos: list[HomePhotoSummary] = Field(default_factory=list)
    new_match: HomeMatchSummary | None = None
