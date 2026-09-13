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


class AppleLoginRequest(BaseModel):
    identity_token: str = Field(min_length=1)


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


class PhotoRejection(BaseModel):
    code: str
    message: str


class TodayPhoto(BaseModel):
    id: UUID
    status: str
    image_url: str
    ai_title: str | None = None
    registered_at: datetime
    search_expires_at: datetime | None = None
    remaining_days: int | None = Field(default=None, ge=0, le=7)
    rejection: PhotoRejection | None = None
    match_id: UUID | None = None
    partner_image_url: str | None = None
    matched_at: datetime | None = None


class TodayPhotoData(BaseModel):
    can_register: bool
    photo: TodayPhoto | None


class MomentPhoto(BaseModel):
    photo_id: UUID
    image_url: str
    ai_title: str | None = None
    status: str
    registered_at: datetime
    search_expires_at: datetime | None = None
    remaining_days: int | None = Field(default=None, ge=0, le=7)


class MomentListData(BaseModel):
    items: list[MomentPhoto]
    next_cursor: str | None
    has_next: bool


class UnviewedMatch(BaseModel):
    match_id: UUID
    my_photo_id: UUID
    my_image_url: str
    partner_image_url: str
    ai_title: str | None = None
    matched_at: datetime


class UnviewedMatchData(BaseModel):
    match: UnviewedMatch | None
    unviewed_match_count: int = Field(ge=0)


class ViewedMatchData(BaseModel):
    match_id: UUID
    viewed_at: datetime
