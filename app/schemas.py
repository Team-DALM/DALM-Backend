from datetime import date as Date
from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """API 공통 성공 응답."""

    data: T = Field(description="요청 결과 데이터")
    error: None = Field(default=None, description="성공 응답에서는 항상 null")


class KakaoLoginRequest(BaseModel):
    """카카오 로그인 요청."""

    access_token: str = Field(
        min_length=1,
        description="Flutter 카카오 SDK에서 발급받은 카카오 Access Token",
        examples=["kakao-access-token"],
    )


class AppleLoginRequest(BaseModel):
    identity_token: str = Field(min_length=1)


class RefreshTokenRequest(BaseModel):
    """토큰 재발급 또는 로그아웃 요청."""

    refresh_token: str = Field(
        min_length=1,
        description="DALM 로그인 또는 토큰 재발급 응답으로 받은 Refresh Token",
    )


class TokenPair(BaseModel):
    """DALM 서비스 인증 토큰 묶음."""

    access_token: str = Field(description="보호 API 호출에 사용하는 JWT Access Token")
    refresh_token: str = Field(description="서비스 토큰 재발급에 사용하는 Refresh Token")
    token_type: Literal["Bearer"] = Field(
        default="Bearer",
        description="Authorization 헤더에 사용하는 인증 방식",
    )
    expires_in: int = Field(description="Access Token 만료까지 남은 시간(초)")


class AuthUser(BaseModel):
    """로그인한 사용자 정보."""

    id: UUID = Field(description="사용자 고유 ID")
    nickname: str | None = Field(description="사용자 닉네임. 미설정 시 null")
    status: str = Field(description="사용자 계정 상태")


class AuthData(BaseModel):
    """로그인 결과."""

    is_new_user: bool = Field(description="이번 로그인에서 새로 가입한 사용자인지 여부")
    onboarding_required: bool = Field(
        description="약관 동의와 프로필 설정이 필요한지 여부"
    )
    tokens: TokenPair = Field(description="DALM 서비스 인증 토큰")
    user: AuthUser = Field(description="로그인한 사용자 정보")


class UserStats(BaseModel):
    photo_count: int = Field(ge=0)
    match_count: int = Field(ge=0)
    received_postcard_count: int = Field(default=0, ge=0)


class UserProfile(BaseModel):
    id: UUID
    nickname: str
    profile_image_url: str | None = None
    bio: str | None = None
    status: str
    stats: UserStats
    created_at: datetime


class WithdrawRequest(BaseModel):
    confirmation: Literal[True]


class HomeState(StrEnum):
    """홈 화면 표시 상태."""

    EMPTY = "EMPTY"
    TODAY_AVAILABLE_WITH_HISTORY = "TODAY_AVAILABLE_WITH_HISTORY"
    TODAY_SEARCHING = "TODAY_SEARCHING"
    PREVIOUS_MATCHED = "PREVIOUS_MATCHED"
    TODAY_MATCHED = "TODAY_MATCHED"


class HomePhotoSummary(BaseModel):
    """홈 화면에 표시할 사진 요약."""

    id: UUID = Field(description="사진 고유 ID")
    image_url: str = Field(description="사진 이미지 URL")
    captured_at: datetime = Field(description="사진 촬영 시각")
    search_day: int = Field(description="매칭 탐색 진행 일수", ge=1, le=7)


class HomeMatchSummary(BaseModel):
    """홈 화면에 표시할 새 매칭 요약."""

    id: UUID = Field(description="매칭 고유 ID")
    photo_id: UUID = Field(description="내 사진 고유 ID")
    photo_image_url: str = Field(description="매칭된 상대 사진 이미지 URL")
    matched_at: datetime = Field(description="매칭 성사 시각")
    distance_km: float | None = Field(
        default=None,
        description="상대와의 거리(km). 알 수 없으면 null",
        ge=0,
    )


class HomeData(BaseModel):
    """홈 화면 구성에 필요한 상태 데이터."""

    date: Date = Field(description="한국 시간 기준 오늘 날짜")
    state: HomeState = Field(description="프론트 화면 분기에 사용하는 홈 상태")
    can_upload_today: bool = Field(description="오늘 새 사진을 등록할 수 있는지 여부")
    today_photo: HomePhotoSummary | None = Field(
        default=None,
        description="오늘 등록한 사진. 없으면 null",
    )
    searching_photos: list[HomePhotoSummary] = Field(
        default_factory=list,
        description="현재 매칭을 탐색 중인 사진 목록",
    )
    new_match: HomeMatchSummary | None = Field(
        default=None,
        description="새로 확인할 매칭. 없으면 null",
    )


class PhotoRejection(BaseModel):
    """사진 검증 거절 사유."""

    code: str = Field(description="프론트 분기 처리용 거절 코드")
    message: str = Field(description="사용자에게 표시할 거절 사유")


class TodayPhoto(BaseModel):
    """오늘 등록한 사진과 처리 상태."""

    id: UUID = Field(description="사진 고유 ID")
    status: str = Field(description="사진 처리 상태")
    image_url: str = Field(description="내 사진 이미지 URL")
    ai_title: str | None = Field(default=None, description="AI가 생성한 사진 제목")
    registered_at: datetime = Field(description="사진 등록 시각")
    search_expires_at: datetime | None = Field(
        default=None,
        description="매칭 탐색 종료 예정 시각",
    )
    remaining_days: int | None = Field(
        default=None,
        description="매칭 탐색 종료까지 남은 일수",
        ge=0,
        le=7,
    )
    rejection: PhotoRejection | None = Field(
        default=None,
        description="사진이 거절된 경우의 사유",
    )
    match_id: UUID | None = Field(
        default=None,
        description="성사된 매칭 고유 ID",
    )
    partner_image_url: str | None = Field(
        default=None,
        description="매칭된 상대 사진 이미지 URL",
    )
    matched_at: datetime | None = Field(
        default=None,
        description="매칭 성사 시각",
    )


class TodayPhotoData(BaseModel):
    """오늘의 사진 조회 결과."""

    can_register: bool = Field(description="오늘 사진을 등록할 수 있는지 여부")
    photo: TodayPhoto | None = Field(description="오늘 등록한 사진. 없으면 null")


class MomentPhoto(BaseModel):
    """매칭을 기다리는 순간 사진."""

    photo_id: UUID = Field(description="사진 고유 ID")
    image_url: str = Field(description="사진 이미지 URL")
    ai_title: str | None = Field(default=None, description="AI가 생성한 사진 제목")
    status: str = Field(description="사진 처리 상태")
    registered_at: datetime = Field(description="사진 등록 시각")
    search_expires_at: datetime | None = Field(
        default=None,
        description="매칭 탐색 종료 예정 시각",
    )
    remaining_days: int | None = Field(
        default=None,
        description="매칭 탐색 종료까지 남은 일수",
        ge=0,
        le=7,
    )
    match_id: UUID | None = None
    matched_at: datetime | None = None
    hidden: bool = False


class MomentListData(BaseModel):
    """매칭 대기 순간 목록 조회 결과."""

    items: list[MomentPhoto] = Field(description="현재 페이지의 순간 목록")
    next_cursor: str | None = Field(description="다음 페이지 조회용 커서. 없으면 null")
    has_next: bool = Field(description="다음 페이지 존재 여부")


class UnviewedMatch(BaseModel):
    """아직 확인하지 않은 매칭."""

    match_id: UUID = Field(description="매칭 고유 ID")
    my_photo_id: UUID = Field(description="매칭에 사용된 내 사진 고유 ID")
    my_image_url: str = Field(description="내 사진 이미지 URL")
    partner_image_url: str = Field(description="매칭된 상대 사진 이미지 URL")
    ai_title: str | None = Field(default=None, description="AI가 생성한 매칭 제목")
    matched_at: datetime = Field(description="매칭 성사 시각")


class UnviewedMatchData(BaseModel):
    """확인하지 않은 다음 매칭 조회 결과."""

    match: UnviewedMatch | None = Field(
        description="다음 미확인 매칭. 없으면 null"
    )
    unviewed_match_count: int = Field(
        description="전체 미확인 매칭 개수",
        ge=0,
    )


class ViewedMatchData(BaseModel):
    """매칭 확인 처리 결과."""

    match_id: UUID = Field(description="확인 처리한 매칭 고유 ID")
    viewed_at: datetime = Field(description="매칭을 확인한 시각")


class MatchedPhoto(BaseModel):
    id: UUID
    image_url: str
    registered_at: datetime
    deleted: bool = False


class MatchPartner(BaseModel):
    id: UUID
    nickname: str
    profile_image_url: str | None = None


class CreateReportRequest(BaseModel):
    target_type: Literal["PHOTO", "POSTCARD", "USER"]
    target_id: UUID
    reason_code: Literal[
        "INAPPROPRIATE_PHOTO",
        "SEXUAL_OR_VIOLENT",
        "HATE_OR_DISCRIMINATION",
        "PERSONAL_INFORMATION",
        "ADVERTISEMENT",
        "OFFENSIVE_POSTCARD",
        "OTHER",
    ]
    detail: str | None = Field(default=None, max_length=1000)


class ReportData(BaseModel):
    id: UUID
    target_type: str
    target_id: UUID
    reason_code: str
    status: str
    created_at: datetime


class PublicUser(BaseModel):
    id: UUID
    nickname: str
    profile_image_url: str | None = None


class MatchDetailData(BaseModel):
    id: UUID
    my_photo: MatchedPhoto
    partner_photo: MatchedPhoto
    partner: MatchPartner | None
    explanation: str
    matched_at: datetime
    hidden: bool
    postcard_permission: Literal[
        "CAN_SEND",
        "WAITING_FOR_FIRST",
        "ALREADY_SENT",
        "BLOCKED",
    ]


class MatchVisibilityRequest(BaseModel):
    hidden: bool


class MatchVisibilityData(BaseModel):
    match_id: UUID
    hidden: bool


class BlockedUser(BaseModel):
    user: PublicUser
    blocked_at: datetime


class BlockedUserListData(BaseModel):
    items: list[BlockedUser]
    next_cursor: str | None
    has_next: bool


class NotificationData(BaseModel):
    id: UUID
    type: str
    title: str
    message: str
    target_type: str | None = None
    target_id: UUID | None = None
    is_read: bool
    created_at: datetime


class NotificationListData(BaseModel):
    items: list[NotificationData]
    unread_count: int = Field(ge=0)
    next_cursor: str | None
    has_next: bool


class SendPostcardRequest(BaseModel):
    content: str = Field(min_length=1, max_length=200)


class PostcardUser(BaseModel):
    id: UUID
    nickname: str
    profile_image_url: str | None = None


class PostcardData(BaseModel):
    id: UUID
    match_id: UUID
    sender: PostcardUser
    receiver: PostcardUser
    content: str
    is_read: bool
    read_at: datetime | None
    sent_at: datetime
    moment_thumbnail_url: str


class PostcardListData(BaseModel):
    items: list[PostcardData]
    next_cursor: str | None
    has_next: bool


class DeviceTokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    platform: Literal["IOS", "ANDROID"]


class NotificationSettingsData(BaseModel):
    validation_enabled: bool
    match_enabled: bool
    postcard_enabled: bool
    search_expired_enabled: bool
    system_enabled: bool


class UpdateNotificationSettingsRequest(BaseModel):
    validation_enabled: bool | None = None
    match_enabled: bool | None = None
    postcard_enabled: bool | None = None
    search_expired_enabled: bool | None = None
    system_enabled: bool | None = None
