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
    """Apple 로그인 요청."""

    identity_token: str = Field(
        min_length=1,
        description="Apple 로그인에서 발급받은 Identity Token",
        examples=["apple-identity-token"],
    )


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
    """사용자 활동 통계."""

    photo_count: int = Field(ge=0, description="등록한 전체 사진 수")
    match_count: int = Field(ge=0, description="성사된 전체 매칭 수")
    received_postcard_count: int = Field(default=0, ge=0, description="받은 전체 엽서 수")


class UserProfile(BaseModel):
    """사용자 프로필."""

    id: UUID = Field(description="사용자 고유 ID")
    nickname: str = Field(description="사용자 닉네임")
    profile_image_url: str | None = Field(default=None, description="프로필 이미지 URL")
    bio: str | None = Field(default=None, description="사용자 한 줄 소개")
    status: str = Field(description="사용자 계정 상태")
    stats: UserStats = Field(description="사용자 활동 통계")
    created_at: datetime = Field(description="사용자 가입 시각")


class WithdrawRequest(BaseModel):
    """회원 탈퇴 확인 요청."""

    confirmation: Literal[True] = Field(description="회원 탈퇴 확인 값. 반드시 true")


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
    """상태별 순간 사진."""

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
    match_id: UUID | None = Field(default=None, description="성사된 매칭 고유 ID")
    matched_at: datetime | None = Field(default=None, description="매칭 성사 시각")
    hidden: bool = Field(default=False, description="내 순간 목록에서 숨김 처리되었는지 여부")
    postcard_permission: Literal[
        "CAN_SEND",
        "WAITING_FOR_FIRST",
        "ALREADY_SENT",
        "BLOCKED",
    ] | None = Field(
        default=None,
        description="매칭 완료 순간의 엽서 발송 가능 상태. 매칭 전에는 null",
    )


class MomentListData(BaseModel):
    """상태별 순간 목록 조회 결과."""

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
    """매칭에 참여한 사진."""

    id: UUID = Field(description="사진 고유 ID")
    image_url: str = Field(description="사진 이미지 URL")
    registered_at: datetime = Field(description="사진 등록 시각")
    deleted: bool = Field(default=False, description="사진 삭제 여부")


class MatchPartner(BaseModel):
    """매칭 상대 사용자 정보."""

    id: UUID = Field(description="상대 사용자 고유 ID")
    nickname: str = Field(description="상대 사용자 닉네임")
    profile_image_url: str | None = Field(default=None, description="상대 프로필 이미지 URL")


class CreateReportRequest(BaseModel):
    """콘텐츠 또는 사용자 신고 요청."""

    target_type: Literal["PHOTO", "POSTCARD", "USER"] = Field(
        description="신고 대상 유형"
    )
    target_id: UUID = Field(description="신고 대상 고유 ID")
    reason_code: Literal[
        "INAPPROPRIATE_PHOTO",
        "SEXUAL_OR_VIOLENT",
        "HATE_OR_DISCRIMINATION",
        "PERSONAL_INFORMATION",
        "ADVERTISEMENT",
        "OFFENSIVE_POSTCARD",
        "OTHER",
    ] = Field(description="신고 사유 코드")
    detail: str | None = Field(
        default=None,
        max_length=1000,
        description="신고 사유 상세 내용. 최대 1,000자",
    )


class ReportData(BaseModel):
    """접수된 신고 정보."""

    id: UUID = Field(description="신고 고유 ID")
    target_type: str = Field(description="신고 대상 유형")
    target_id: UUID = Field(description="신고 대상 고유 ID")
    reason_code: str = Field(description="신고 사유 코드")
    status: str = Field(description="신고 처리 상태")
    created_at: datetime = Field(description="신고 접수 시각")


class PublicUser(BaseModel):
    """외부에 공개되는 사용자 요약 정보."""

    id: UUID = Field(description="사용자 고유 ID")
    nickname: str = Field(description="사용자 닉네임")
    profile_image_url: str | None = Field(default=None, description="프로필 이미지 URL")


class MatchDetailData(BaseModel):
    """매칭 상세 정보."""

    id: UUID = Field(description="매칭 고유 ID")
    my_photo: MatchedPhoto = Field(description="매칭에 참여한 내 사진")
    partner_photo: MatchedPhoto = Field(description="매칭된 상대 사진")
    partner: MatchPartner | None = Field(description="매칭 상대 정보. 탈퇴한 경우 null")
    explanation: str = Field(description="두 사진이 매칭된 이유")
    matched_at: datetime = Field(description="매칭 성사 시각")
    hidden: bool = Field(description="내 순간 목록에서 숨김 처리되었는지 여부")
    postcard_permission: Literal[
        "CAN_SEND",
        "WAITING_FOR_FIRST",
        "ALREADY_SENT",
        "BLOCKED",
    ] = Field(description="현재 사용자의 엽서 발송 가능 상태")


class MatchVisibilityRequest(BaseModel):
    """매칭 숨김 상태 변경 요청."""

    hidden: bool = Field(description="숨기려면 true, 다시 표시하려면 false")


class MatchVisibilityData(BaseModel):
    """변경된 매칭 숨김 상태."""

    match_id: UUID = Field(description="매칭 고유 ID")
    hidden: bool = Field(description="변경 후 숨김 여부")


class BlockedUser(BaseModel):
    """차단한 사용자 정보."""

    user: PublicUser = Field(description="차단한 사용자 요약")
    blocked_at: datetime = Field(description="차단한 시각")


class BlockedUserListData(BaseModel):
    """차단 사용자 목록 조회 결과."""

    items: list[BlockedUser] = Field(description="현재 페이지의 차단 사용자 목록")
    next_cursor: str | None = Field(description="다음 페이지 조회용 커서. 없으면 null")
    has_next: bool = Field(description="다음 페이지 존재 여부")


class NotificationData(BaseModel):
    """사용자 알림 정보."""

    id: UUID = Field(description="알림 고유 ID")
    type: str = Field(description="알림 유형")
    title: str = Field(description="알림 제목")
    message: str = Field(description="알림 본문")
    target_type: str | None = Field(default=None, description="연결된 대상 유형")
    target_id: UUID | None = Field(default=None, description="연결된 대상 고유 ID")
    is_read: bool = Field(description="읽음 여부")
    created_at: datetime = Field(description="알림 생성 시각")


class NotificationListData(BaseModel):
    """알림 목록 조회 결과."""

    items: list[NotificationData] = Field(description="현재 페이지의 알림 목록")
    unread_count: int = Field(ge=0, description="전체 읽지 않은 알림 개수")
    next_cursor: str | None = Field(description="다음 페이지 조회용 커서. 없으면 null")
    has_next: bool = Field(description="다음 페이지 존재 여부")


class SendPostcardRequest(BaseModel):
    """엽서 발송 요청."""

    content: str = Field(
        min_length=1,
        max_length=200,
        description="엽서 본문. 공백 제거 후 1~200자",
    )


class PostcardUser(BaseModel):
    """엽서 발신자 또는 수신자 정보."""

    id: UUID = Field(description="사용자 고유 ID")
    nickname: str = Field(description="사용자 닉네임")
    profile_image_url: str | None = Field(default=None, description="프로필 이미지 URL")


class PostcardData(BaseModel):
    """엽서 상세 정보."""

    id: UUID = Field(description="엽서 고유 ID")
    match_id: UUID = Field(description="엽서가 연결된 매칭 고유 ID")
    sender: PostcardUser = Field(description="엽서 발신자")
    receiver: PostcardUser = Field(description="엽서 수신자")
    content: str = Field(description="엽서 본문")
    is_read: bool = Field(description="수신자의 읽음 여부")
    read_at: datetime | None = Field(description="수신자가 읽은 시각. 읽지 않았으면 null")
    sent_at: datetime = Field(description="엽서 발송 시각")
    moment_thumbnail_url: str = Field(description="매칭된 내 순간 썸네일 URL")


class PostcardListData(BaseModel):
    """엽서 보관함 목록 조회 결과."""

    items: list[PostcardData] = Field(description="현재 페이지의 엽서 목록")
    next_cursor: str | None = Field(description="다음 페이지 조회용 커서. 없으면 null")
    has_next: bool = Field(description="다음 페이지 존재 여부")


class DeviceTokenRequest(BaseModel):
    """푸시 알림 기기 토큰 등록 요청."""

    token: str = Field(min_length=1, max_length=512, description="FCM 기기 등록 토큰")
    platform: Literal["IOS", "ANDROID"] = Field(description="기기 운영체제")


class NotificationSettingsData(BaseModel):
    """알림 유형별 수신 설정."""

    validation_enabled: bool = Field(description="사진 검증 결과 알림 수신 여부")
    match_enabled: bool = Field(description="매칭 성사 알림 수신 여부")
    postcard_enabled: bool = Field(description="엽서 수신 알림 수신 여부")
    search_expired_enabled: bool = Field(description="매칭 탐색 만료 알림 수신 여부")
    system_enabled: bool = Field(description="서비스 공지 알림 수신 여부")


class UpdateNotificationSettingsRequest(BaseModel):
    """알림 유형별 수신 설정 변경 요청."""

    validation_enabled: bool | None = Field(default=None, description="사진 검증 결과 알림 수신 여부")
    match_enabled: bool | None = Field(default=None, description="매칭 성사 알림 수신 여부")
    postcard_enabled: bool | None = Field(default=None, description="엽서 수신 알림 수신 여부")
    search_expired_enabled: bool | None = Field(
        default=None,
        description="매칭 탐색 만료 알림 수신 여부",
    )
    system_enabled: bool | None = Field(default=None, description="서비스 공지 알림 수신 여부")
