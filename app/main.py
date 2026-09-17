import asyncio
import base64
import binascii
import hmac
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Annotated, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, Header, Query, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.apple import AppleClient
from app.auth import AuthService
from app.cache import Cache
from app.config import Settings
from app.database import Database
from app.dependencies import (
    get_auth_service,
    get_home_repository,
    get_notification_preference_repository,
    get_notification_repository,
    get_photo_storage,
    get_photo_validation_repository,
    get_postcard_repository,
    get_report_repository,
    get_safety_repository,
    get_token_service,
    get_user_repository,
    require_access_token,
)
from app.errors import (
    ApiError,
    api_error_handler,
    infrastructure_error_handler,
    request_validation_error_handler,
)
from app.kakao import KakaoClient
from app.models import Notification
from app.photo_storage import GcsPhotoStorage, PhotoStorage, UnconfiguredPhotoStorage
from app.photo_upload import process_photo
from app.repositories import (
    HomeRepository,
    MatchDetailRow,
    NotificationPreferenceRepository,
    NotificationRepository,
    PhotoValidationRepository,
    PostcardRepository,
    PostcardRow,
    ReportRepository,
    SafetyRepository,
    UserRepository,
)
from app.schemas import (
    ApiResponse,
    AppleLoginRequest,
    AuthData,
    BlockedUser,
    BlockedUserListData,
    CreatePhotoData,
    CreateReportRequest,
    DeviceTokenRequest,
    HomeData,
    HomeMatchSummary,
    HomePhotoSummary,
    HomeState,
    KakaoLoginRequest,
    MatchDetailData,
    MatchedPhoto,
    MatchPartner,
    MatchVisibilityData,
    MatchVisibilityRequest,
    MomentListData,
    MomentPhoto,
    NotificationData,
    NotificationListData,
    NotificationSettingsData,
    PhotoRejection,
    PhotoValidationClaimData,
    PhotoValidationClaimRequest,
    PhotoValidationFailureData,
    PhotoValidationFailureRequest,
    PhotoValidationJobData,
    PhotoValidationResultData,
    PhotoValidationResultRequest,
    PostcardData,
    PostcardListData,
    PostcardUser,
    PublicUser,
    RefreshTokenRequest,
    ReportData,
    SendPostcardRequest,
    TodayPhoto,
    TodayPhotoData,
    TokenPair,
    UnviewedMatch,
    UnviewedMatchData,
    UpdateNotificationSettingsRequest,
    UserProfile,
    UserStats,
    ViewedMatchData,
    WithdrawRequest,
)
from app.token_store import (
    InMemoryRefreshTokenStore,
    RedisRefreshTokenStore,
    RefreshTokenStore,
)
from app.tokens import TokenClaims, TokenService


class HealthDependency(Protocol):
    async def ping(self) -> None: ...

    async def close(self) -> None: ...


async def _dependency_status(dependency: HealthDependency) -> str:
    try:
        await dependency.ping()
        return "ok"
    except (OSError, RedisError, SQLAlchemyError):
        return "unavailable"


def create_app(
    settings: Settings | None = None,
    *,
    database: HealthDependency | None = None,
    cache: HealthDependency | None = None,
    refresh_store: RefreshTokenStore | None = None,
    kakao_client: KakaoClient | None = None,
    apple_client: AppleClient | None = None,
    photo_storage: PhotoStorage | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_database = database or Database(resolved_settings.database_url)
    resolved_cache = cache or Cache(resolved_settings.redis_url)
    if refresh_store is not None:
        resolved_refresh_store = refresh_store
    elif cache is not None:
        resolved_refresh_store = InMemoryRefreshTokenStore()
    else:
        resolved_refresh_store = RedisRefreshTokenStore(resolved_cache.client)  # type: ignore[attr-defined]
    resolved_kakao_client = kakao_client or KakaoClient(
        resolved_settings.kakao_user_info_url,
        resolved_settings.kakao_timeout_seconds,
    )
    resolved_apple_client = apple_client or AppleClient(
        resolved_settings.apple_jwks_url,
        resolved_settings.apple_issuer,
        resolved_settings.apple_client_ids,
        resolved_settings.apple_timeout_seconds,
    )
    resolved_photo_storage = photo_storage or (
        GcsPhotoStorage(resolved_settings.gcs_bucket)
        if resolved_settings.gcs_bucket
        else UnconfiguredPhotoStorage()
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.database = resolved_database
        app.state.cache = resolved_cache
        try:
            yield
        finally:
            await asyncio.gather(
                resolved_database.close(),
                resolved_cache.close(),
            )

    app = FastAPI(
        title="DALM API",
        description="DALM Flutter 앱에서 사용하는 백엔드 REST API입니다.",
        version="0.1.0",
        openapi_tags=[
            {"name": "Auth", "description": "카카오 로그인과 서비스 토큰 관리"},
            {"name": "Users", "description": "사용자 온보딩, 프로필 및 회원 탈퇴"},
            {"name": "Home", "description": "홈 화면 상태 조회"},
            {"name": "Photos", "description": "등록 사진 조회 및 삭제"},
            {"name": "Moments", "description": "상태별 순간 목록 조회"},
            {"name": "Matches", "description": "매칭 조회, 확인 및 숨김 상태 관리"},
            {"name": "Safety", "description": "사용자 차단과 콘텐츠 신고"},
            {"name": "Notifications", "description": "알림 조회, 읽음 처리 및 수신 설정"},
            {"name": "Postcards", "description": "매칭 상대와 주고받는 엽서 및 보관함"},
            {"name": "Internal", "description": "내부 서비스 간 연동"},
            {"name": "System", "description": "서버 및 의존 서비스 상태 확인"},
        ],
        lifespan=lifespan,
    )
    app.state.token_service = TokenService(resolved_settings, resolved_refresh_store)
    app.state.kakao_client = resolved_kakao_client
    app.state.apple_client = resolved_apple_client
    app.state.photo_storage = resolved_photo_storage
    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RedisError, infrastructure_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(SQLAlchemyError, infrastructure_error_handler)  # type: ignore[arg-type]

    def verify_internal_key(internal_key: str | None) -> None:
        expected_key = resolved_settings.internal_api_key
        if expected_key is None:
            raise ApiError(
                503,
                "INTERNAL_API_NOT_CONFIGURED",
                "내부 API 인증이 설정되지 않았습니다.",
            )
        if internal_key is None or not hmac.compare_digest(internal_key, expected_key):
            raise ApiError(401, "INVALID_INTERNAL_API_KEY", "내부 API 인증에 실패했습니다.")

    @app.get(
        "/health",
        tags=["System"],
        summary="서버 상태 확인",
        description="API 프로세스가 정상적으로 응답하는지 확인합니다.",
    )
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/ready",
        tags=["System"],
        summary="서비스 준비 상태 확인",
        description="PostgreSQL과 Redis 연결 상태를 확인합니다.",
    )
    async def readiness() -> Response:
        database_status, redis_status = await asyncio.gather(
            _dependency_status(resolved_database),
            _dependency_status(resolved_cache),
        )
        ready = database_status == "ok" and redis_status == "ok"
        return JSONResponse(
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "ready" if ready else "not_ready",
                "dependencies": {
                    "database": database_status,
                    "redis": redis_status,
                },
            },
        )

    @app.post(
        "/v1/auth/kakao",
        response_model=ApiResponse[AuthData],
        tags=["Auth"],
        summary="카카오 로그인",
        description=(
            "Flutter에서 발급받은 카카오 Access Token으로 로그인합니다. "
            "처음 로그인한 사용자는 회원 정보를 생성하며 HTTP 201을 반환합니다."
        ),
    )
    async def login_with_kakao(
        request: KakaoLoginRequest,
        response: Response,
        service: Annotated[AuthService, Depends(get_auth_service)],
    ) -> ApiResponse[AuthData]:
        data, is_new_user = await service.login_with_kakao(request.access_token)
        response.status_code = status.HTTP_201_CREATED if is_new_user else status.HTTP_200_OK
        return ApiResponse(data=data)

    @app.post(
        "/v1/auth/apple",
        response_model=ApiResponse[AuthData],
        tags=["Auth"],
        summary="Apple 로그인",
        description=(
            "Apple에서 발급받은 Identity Token으로 로그인합니다. "
            "처음 로그인한 사용자는 회원 정보를 생성하며 HTTP 201을 반환합니다."
        ),
    )
    async def login_with_apple(
        request: AppleLoginRequest,
        response: Response,
        service: Annotated[AuthService, Depends(get_auth_service)],
    ) -> ApiResponse[AuthData]:
        data, is_new_user = await service.login_with_apple(request.identity_token)
        response.status_code = status.HTTP_201_CREATED if is_new_user else status.HTTP_200_OK
        return ApiResponse(data=data)

    @app.post(
        "/v1/auth/refresh",
        response_model=ApiResponse[TokenPair],
        tags=["Auth"],
        summary="서비스 토큰 재발급",
        description="Refresh Token을 검증하고 새로운 Access Token과 Refresh Token을 발급합니다.",
    )
    async def refresh_token(
        request: RefreshTokenRequest,
        service: Annotated[TokenService, Depends(get_token_service)],
    ) -> ApiResponse[TokenPair]:
        return ApiResponse(data=await service.rotate(request.refresh_token))

    @app.post(
        "/v1/auth/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["Auth"],
        summary="로그아웃",
        description="Bearer Access Token을 검증한 뒤 전달받은 Refresh Token을 폐기합니다.",
    )
    async def logout(
        request: RefreshTokenRequest,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        service: Annotated[TokenService, Depends(get_token_service)],
    ) -> None:
        await service.revoke(request.refresh_token, claims.subject)

    def normalized_nickname(value: str) -> str:
        nickname = value.strip()
        if not 2 <= len(nickname) <= 12:
            raise ApiError(422, "INVALID_NICKNAME", "닉네임은 2~12자로 입력해주세요.")
        return nickname

    def normalized_bio(value: str | None) -> str | None:
        if value is None:
            return None
        bio = value.strip()
        if len(bio) > 100:
            raise ApiError(422, "INVALID_BIO", "한 줄 소개는 100자 이하로 입력해주세요.")
        return bio or None

    async def user_profile(repository: UserRepository, user) -> UserProfile:
        photo_count, match_count, received_postcard_count = await repository.get_stats(user.id)
        return UserProfile(
            id=user.id,
            nickname=user.nickname,
            profile_image_url=None,
            bio=user.bio,
            status=user.status,
            stats=UserStats(
                photo_count=photo_count,
                match_count=match_count,
                received_postcard_count=received_postcard_count,
            ),
            created_at=user.created_at,
        )

    @app.post(
        "/v1/users/onboarding",
        response_model=ApiResponse[UserProfile],
        status_code=status.HTTP_201_CREATED,
        tags=["Users"],
        summary="사용자 온보딩 완료",
        description=(
            "필수 약관 동의와 닉네임 등 초기 프로필 정보를 저장하여 온보딩을 완료합니다. "
            "프로필 이미지 업로드는 저장소 설정 전까지 지원하지 않습니다."
        ),
    )
    async def complete_onboarding(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[UserRepository, Depends(get_user_repository)],
        nickname: Annotated[str, Form()],
        service_terms_agreed: Annotated[bool, Form()],
        privacy_policy_agreed: Annotated[bool, Form()],
        age_14_confirmed: Annotated[bool, Form()],
        profile_image: Annotated[UploadFile | None, File()] = None,
        bio: Annotated[str | None, Form()] = None,
        marketing_agreed: Annotated[bool, Form()] = False,
        service_terms_version: Annotated[str, Form()] = "1.0",
        privacy_policy_version: Annotated[str, Form()] = "1.0",
    ) -> ApiResponse[UserProfile]:
        if profile_image is not None:
            raise ApiError(
                503,
                "PROFILE_IMAGE_STORAGE_NOT_CONFIGURED",
                "프로필 이미지 저장소가 아직 준비되지 않았습니다.",
            )
        if not (service_terms_agreed and privacy_policy_agreed and age_14_confirmed):
            raise ApiError(422, "REQUIRED_TERMS_NOT_AGREED", "필수 약관에 동의해야 합니다.")
        user = await repository.complete_onboarding(
            authenticated_user_id(claims),
            nickname=normalized_nickname(nickname),
            bio=normalized_bio(bio),
            marketing_agreed=marketing_agreed,
            service_terms_version=service_terms_version,
            privacy_policy_version=privacy_policy_version,
        )
        return ApiResponse(data=await user_profile(repository, user))

    @app.get(
        "/v1/users/me",
        response_model=ApiResponse[UserProfile],
        tags=["Users"],
        summary="내 프로필 조회",
        description="로그인 사용자의 프로필과 사진·매칭·받은 엽서 통계를 조회합니다.",
    )
    async def get_my_profile(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[UserRepository, Depends(get_user_repository)],
    ) -> ApiResponse[UserProfile]:
        user = await repository.get_by_id(authenticated_user_id(claims))
        if user is None or user.status == "WITHDRAWN":
            raise ApiError(404, "USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
        if user.onboarding_required:
            raise ApiError(409, "ONBOARDING_REQUIRED", "온보딩을 먼저 완료해주세요.")
        return ApiResponse(data=await user_profile(repository, user))

    @app.patch(
        "/v1/users/me",
        response_model=ApiResponse[UserProfile],
        tags=["Users"],
        summary="내 프로필 수정",
        description=(
            "로그인 사용자의 닉네임과 한 줄 소개를 수정합니다. "
            "프로필 이미지 변경은 저장소 설정 전까지 지원하지 않습니다."
        ),
    )
    async def update_my_profile(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[UserRepository, Depends(get_user_repository)],
        nickname: Annotated[str | None, Form()] = None,
        bio: Annotated[str | None, Form()] = None,
        profile_image: Annotated[UploadFile | None, File()] = None,
        remove_profile_image: Annotated[bool, Form()] = False,
    ) -> ApiResponse[UserProfile]:
        if profile_image is not None or remove_profile_image:
            raise ApiError(
                503,
                "PROFILE_IMAGE_STORAGE_NOT_CONFIGURED",
                "프로필 이미지 저장소가 아직 준비되지 않았습니다.",
            )
        if nickname is None and bio is None:
            raise ApiError(422, "EMPTY_PROFILE_UPDATE", "수정할 프로필 정보를 입력해주세요.")
        user = await repository.update_profile(
            authenticated_user_id(claims),
            nickname=normalized_nickname(nickname) if nickname is not None else None,
            bio=normalized_bio(bio),
            update_bio=bio is not None,
        )
        return ApiResponse(data=await user_profile(repository, user))

    @app.delete(
        "/v1/users/me",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["Users"],
        summary="회원 탈퇴",
        description="계정을 탈퇴 상태로 변경하고 해당 사용자의 모든 Refresh Token을 폐기합니다.",
    )
    async def withdraw_my_account(
        request: WithdrawRequest,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[UserRepository, Depends(get_user_repository)],
        token_service: Annotated[TokenService, Depends(get_token_service)],
    ) -> None:
        del request
        await repository.withdraw(authenticated_user_id(claims))
        await token_service.revoke_all(claims.subject)

    @app.get(
        "/v1/home",
        response_model=ApiResponse[HomeData],
        tags=["Home"],
        summary="홈 화면 상태 조회",
        description="로그인 사용자의 오늘 날짜와 사진 등록 가능 여부를 조회합니다.",
    )
    async def get_home(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[HomeRepository, Depends(get_home_repository)],
    ) -> ApiResponse[HomeData]:
        user_id = authenticated_user_id(claims)
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        today_photo = await repository.get_today_photo(user_id, today)
        searching = await repository.list_searching_photos(
            user_id,
            today=today,
            exclude_today=True,
            size=3,
            cursor=None,
        )
        unviewed_match, _ = await repository.get_next_unviewed_match(user_id, today)

        can_upload = today_photo is None or today_photo.status in {"REJECTED", "DELETED"}
        active_today = (
            HomePhotoSummary(
                id=today_photo.id,
                image_url=today_photo.image_url,
                captured_at=today_photo.registered_at,
                search_day=(
                    max(1, 8 - (remaining_days(today_photo.search_expires_at) or 7))
                    if today_photo.status == "SEARCHING"
                    else 1
                ),
            )
            if today_photo is not None and today_photo.status not in {"REJECTED", "DELETED"}
            else None
        )
        searching_summaries = [
            HomePhotoSummary(
                id=photo.id,
                image_url=photo.image_url,
                captured_at=photo.registered_at,
                search_day=max(1, 8 - (remaining_days(photo.search_expires_at) or 7)),
            )
            for photo in searching[:3]
        ]
        new_match = (
            HomeMatchSummary(
                id=unviewed_match.match_id,
                photo_id=unviewed_match.my_photo_id,
                photo_image_url=unviewed_match.partner_image_url,
                matched_at=unviewed_match.matched_at,
            )
            if unviewed_match
            else None
        )
        if today_photo is not None and today_photo.status == "MATCHED":
            home_state = HomeState.TODAY_MATCHED
        elif today_photo is not None and today_photo.status in {"VALIDATING", "SEARCHING"}:
            home_state = HomeState.TODAY_SEARCHING
        elif new_match is not None:
            home_state = HomeState.PREVIOUS_MATCHED
        elif searching_summaries:
            home_state = HomeState.TODAY_AVAILABLE_WITH_HISTORY
        else:
            home_state = HomeState.EMPTY
        return ApiResponse(
            data=HomeData(
                date=today,
                state=home_state,
                can_upload_today=can_upload,
                today_photo=active_today,
                searching_photos=searching_summaries,
                new_match=new_match,
            )
        )

    def authenticated_user_id(claims: TokenClaims) -> UUID:
        try:
            return UUID(claims.subject)
        except ValueError as exc:
            raise ApiError(401, "INVALID_ACCESS_TOKEN", "유효하지 않은 인증 정보입니다.") from exc

    def remaining_days(expires_at: datetime | None) -> int | None:
        if expires_at is None:
            return None
        value = math.ceil((expires_at - datetime.now(UTC)).total_seconds() / 86400)
        return min(7, max(0, value))

    def encode_cursor(registered_at: datetime, photo_id: UUID) -> str:
        raw = f"{registered_at.isoformat()}|{photo_id}".encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def decode_cursor(value: str | None) -> tuple[datetime, UUID] | None:
        if value is None:
            return None
        try:
            padded = value + "=" * (-len(value) % 4)
            timestamp, photo_id = base64.urlsafe_b64decode(padded).decode().split("|", 1)
            parsed = datetime.fromisoformat(timestamp)
            if parsed.tzinfo is None:
                raise ValueError
            return parsed, UUID(photo_id)
        except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise ApiError(422, "INVALID_CURSOR", "cursor 형식이 올바르지 않습니다.") from exc

    @app.post(
        "/v1/photos",
        response_model=ApiResponse[CreatePhotoData],
        status_code=status.HTTP_202_ACCEPTED,
        tags=["Photos"],
        summary="오늘 사진 등록",
        description=(
            "4:5 사진을 검증하고 EXIF 정보를 제거한 뒤 비공개 저장소에 저장합니다. "
            "등록 직후 상태는 VALIDATING입니다."
        ),
    )
    async def create_photo(
        image: Annotated[UploadFile, File(description="JPEG, PNG 또는 WEBP 형식의 4:5 이미지")],
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[HomeRepository, Depends(get_home_repository)],
        storage: Annotated[PhotoStorage, Depends(get_photo_storage)],
    ) -> ApiResponse[CreatePhotoData]:
        photo_id = uuid4()
        user_id = authenticated_user_id(claims)
        raw = await image.read(resolved_settings.photo_max_bytes + 1)
        await image.close()
        processed = process_photo(
            raw,
            image.content_type,
            max_bytes=resolved_settings.photo_max_bytes,
            min_width=resolved_settings.photo_min_width,
            min_height=resolved_settings.photo_min_height,
        )
        storage_key = f"photos/{user_id}/{photo_id}/original.webp"
        await storage.upload(storage_key, processed.content, processed.content_type)
        try:
            photo = await repository.create_photo(
                photo_id=photo_id,
                user_id=user_id,
                image_url=f"/v1/photos/{photo_id}/image",
                storage_key=storage_key,
                checksum=processed.checksum,
                registered_date=datetime.now(ZoneInfo("Asia/Seoul")).date(),
            )
        except Exception:
            with suppress(Exception):
                await storage.delete(storage_key)
            raise
        return ApiResponse(
            data=CreatePhotoData(
                photo_id=photo_id,
                status="VALIDATING",
                registered_at=photo.registered_at,
            )
        )

    @app.post(
        "/internal/v1/photo-validations/{job_id}/result",
        response_model=ApiResponse[PhotoValidationResultData],
        tags=["Internal"],
        summary="사진 검증 결과 반영",
        description="내부 AI 검증 서비스의 최종 결과를 원자적으로 사진 상태에 반영합니다.",
    )
    async def apply_photo_validation_result(
        job_id: UUID,
        body: PhotoValidationResultRequest,
        repository: Annotated[
            PhotoValidationRepository, Depends(get_photo_validation_repository)
        ],
        internal_key: Annotated[str | None, Header(alias="X-DALM-Internal-Key")] = None,
    ) -> ApiResponse[PhotoValidationResultData]:
        verify_internal_key(internal_key)
        result = await repository.apply_result(job_id, **body.model_dump())
        return ApiResponse(
            data=PhotoValidationResultData(
                job_id=result.id,
                photo_id=result.photo_id,
                status=result.status,
                photo_status="SEARCHING" if result.status == "PASSED" else "REJECTED",
                completed_at=result.completed_at,
            )
        )

    @app.post(
        "/internal/v1/photo-validations/claim",
        response_model=ApiResponse[PhotoValidationClaimData],
        tags=["Internal"],
        summary="사진 검증 작업 선점",
        description="대기 중이거나 실행 제한 시간을 넘긴 사진 검증 작업 하나를 선점합니다.",
    )
    async def claim_photo_validation(
        body: PhotoValidationClaimRequest,
        repository: Annotated[
            PhotoValidationRepository, Depends(get_photo_validation_repository)
        ],
        storage: Annotated[PhotoStorage, Depends(get_photo_storage)],
        internal_key: Annotated[str | None, Header(alias="X-DALM-Internal-Key")] = None,
    ) -> ApiResponse[PhotoValidationClaimData]:
        verify_internal_key(internal_key)
        claimed = await repository.claim_next(
            worker_id=body.worker_id,
            lease_seconds=resolved_settings.validation_lease_seconds,
        )
        if claimed is None:
            return ApiResponse(data=PhotoValidationClaimData(job=None))
        validation, photo = claimed
        image_url = await storage.signed_url(
            photo.storage_key,
            resolved_settings.photo_signed_url_ttl_seconds,
        )
        return ApiResponse(
            data=PhotoValidationClaimData(
                job=PhotoValidationJobData(
                    job_id=validation.id,
                    photo_id=photo.id,
                    storage_key=photo.storage_key,
                    image_url=image_url,
                    checks=[
                        "QUALITY",
                        "SCREENSHOT",
                        "TEXT_DOMINANT",
                        "QR_BARCODE",
                        "SENSITIVE_INFORMATION",
                        "SAFETY",
                        "ADVERTISEMENT",
                    ],
                    attempt=validation.attempt_count,
                )
            )
        )

    @app.post(
        "/internal/v1/photo-validations/{job_id}/failure",
        response_model=ApiResponse[PhotoValidationFailureData],
        tags=["Internal"],
        summary="사진 검증 실행 오류 반영",
        description="AI 실행 오류를 기록하고 재시도 또는 최종 실패 상태를 결정합니다.",
    )
    async def fail_photo_validation(
        job_id: UUID,
        body: PhotoValidationFailureRequest,
        repository: Annotated[
            PhotoValidationRepository, Depends(get_photo_validation_repository)
        ],
        internal_key: Annotated[str | None, Header(alias="X-DALM-Internal-Key")] = None,
    ) -> ApiResponse[PhotoValidationFailureData]:
        verify_internal_key(internal_key)
        result = await repository.record_failure(
            job_id,
            **body.model_dump(),
            max_attempts=resolved_settings.validation_max_attempts,
            retry_base_seconds=resolved_settings.validation_retry_base_seconds,
        )
        return ApiResponse(
            data=PhotoValidationFailureData(
                job_id=result.id,
                status=result.status,
                attempt_count=result.attempt_count,
                next_attempt_at=result.next_attempt_at,
            )
        )

    @app.get(
        "/v1/photos/{photo_id}/image",
        response_class=RedirectResponse,
        tags=["Photos"],
        summary="사진 이미지 접근",
        description="사진 접근 권한을 확인한 후 짧게 유효한 비공개 저장소 URL로 이동합니다.",
    )
    async def get_photo_image(
        photo_id: UUID,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[HomeRepository, Depends(get_home_repository)],
        storage: Annotated[PhotoStorage, Depends(get_photo_storage)],
    ) -> RedirectResponse:
        photo = await repository.get_photo(photo_id)
        if photo is None or photo.deleted_at is not None or photo.storage_key is None:
            raise ApiError(404, "PHOTO_NOT_FOUND", "사진을 찾을 수 없습니다.")
        if not await repository.can_access_photo(authenticated_user_id(claims), photo_id):
            raise ApiError(403, "PHOTO_ACCESS_DENIED", "사진에 접근할 권한이 없습니다.")
        signed_url = await storage.signed_url(
            photo.storage_key, resolved_settings.photo_signed_url_ttl_seconds
        )
        return RedirectResponse(signed_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    @app.get(
        "/v1/photos/today",
        response_model=ApiResponse[TodayPhotoData],
        tags=["Photos"],
        summary="오늘의 사진 조회",
        description="로그인 사용자가 오늘 등록한 사진과 처리·매칭 상태를 조회합니다.",
    )
    async def get_today_photo(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[HomeRepository, Depends(get_home_repository)],
    ) -> ApiResponse[TodayPhotoData]:
        user_id = authenticated_user_id(claims)
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        photo = await repository.get_today_photo(user_id, today)
        if photo is None:
            return ApiResponse(data=TodayPhotoData(can_register=True, photo=None))

        match = None
        if photo.status == "MATCHED":
            match = await repository.get_match_card_for_photo(user_id, photo.id)
        rejection = None
        if photo.status == "REJECTED" and photo.rejection_code and photo.rejection_message:
            rejection = PhotoRejection(
                code=photo.rejection_code,
                message=photo.rejection_message,
            )
        return ApiResponse(
            data=TodayPhotoData(
                can_register=photo.status == "REJECTED",
                photo=TodayPhoto(
                    id=photo.id,
                    status=photo.status,
                    image_url=photo.image_url,
                    ai_title=photo.ai_title,
                    registered_at=photo.registered_at,
                    search_expires_at=photo.search_expires_at,
                    remaining_days=(
                        remaining_days(photo.search_expires_at)
                        if photo.status == "SEARCHING"
                        else None
                    ),
                    rejection=rejection,
                    match_id=match.match_id if match else None,
                    partner_image_url=match.partner_image_url if match else None,
                    matched_at=match.matched_at if match else None,
                ),
            )
        )

    @app.get(
        "/v1/photos/{photo_id}",
        response_model=ApiResponse[TodayPhoto],
        tags=["Photos"],
        summary="사진 상세 조회",
        description="로그인 사용자가 등록한 사진의 처리·매칭 상태를 상세 조회합니다.",
    )
    async def get_photo(
        photo_id: UUID,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[HomeRepository, Depends(get_home_repository)],
    ) -> ApiResponse[TodayPhoto]:
        user_id = authenticated_user_id(claims)
        photo = await repository.get_photo(photo_id)
        if photo is None or photo.status == "DELETED":
            raise ApiError(404, "PHOTO_NOT_FOUND", "사진을 찾을 수 없습니다.")
        if photo.user_id != user_id:
            raise ApiError(403, "PHOTO_NOT_OWNED", "본인의 사진만 조회할 수 있습니다.")
        match = (
            await repository.get_match_card_for_photo(user_id, photo.id)
            if photo.status == "MATCHED"
            else None
        )
        rejection = (
            PhotoRejection(code=photo.rejection_code, message=photo.rejection_message)
            if photo.status == "REJECTED" and photo.rejection_code and photo.rejection_message
            else None
        )
        return ApiResponse(
            data=TodayPhoto(
                id=photo.id,
                status=photo.status,
                image_url=photo.image_url,
                ai_title=photo.ai_title,
                registered_at=photo.registered_at,
                search_expires_at=photo.search_expires_at,
                remaining_days=(
                    remaining_days(photo.search_expires_at) if photo.status == "SEARCHING" else None
                ),
                rejection=rejection,
                match_id=match.match_id if match else None,
                partner_image_url=match.partner_image_url if match else None,
                matched_at=match.matched_at if match else None,
            )
        )

    @app.delete(
        "/v1/photos/{photo_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["Photos"],
        summary="사진 삭제",
        description="매칭 탐색 중이거나 만료된 본인 사진을 소프트 삭제합니다.",
    )
    async def delete_photo(
        photo_id: UUID,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[HomeRepository, Depends(get_home_repository)],
    ) -> None:
        await repository.delete_photo(authenticated_user_id(claims), photo_id)

    @app.get(
        "/v1/moments",
        response_model=ApiResponse[MomentListData],
        tags=["Moments"],
        summary="상태별 순간 목록 조회",
        description=(
            "로그인 사용자의 순간을 전체·매칭 중·매칭 완료·만료·숨김 상태로 필터링하여 "
            "커서 기반 페이지네이션으로 조회합니다."
        ),
    )
    async def list_moments(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[HomeRepository, Depends(get_home_repository)],
        photo_status: Annotated[
            str,
            Query(alias="status", pattern="^(ALL|SEARCHING|MATCHED|EXPIRED|HIDDEN)$"),
        ] = "ALL",
        exclude_today: bool = False,
        size: Annotated[int, Query(ge=1, le=50)] = 20,
        cursor: str | None = None,
    ) -> ApiResponse[MomentListData]:
        photos = await repository.list_moments(
            authenticated_user_id(claims),
            status=photo_status,
            today=datetime.now(ZoneInfo("Asia/Seoul")).date(),
            exclude_today=exclude_today,
            size=size,
            cursor=decode_cursor(cursor),
        )
        has_next = len(photos) > size
        page = photos[:size]
        next_cursor = (
            encode_cursor(page[-1].registered_at, page[-1].photo_id) if has_next and page else None
        )
        return ApiResponse(
            data=MomentListData(
                items=[
                    MomentPhoto(
                        photo_id=photo.photo_id,
                        image_url=photo.image_url,
                        ai_title=photo.ai_title,
                        status=photo.status,
                        registered_at=photo.registered_at,
                        search_expires_at=photo.search_expires_at,
                        remaining_days=(
                            remaining_days(photo.search_expires_at)
                            if photo.status == "SEARCHING"
                            else None
                        ),
                        match_id=photo.match_id,
                        matched_at=photo.matched_at,
                        hidden=photo.hidden,
                        postcard_permission=photo.postcard_permission,
                    )
                    for photo in page
                ],
                next_cursor=next_cursor,
                has_next=has_next,
            )
        )

    @app.get(
        "/v1/matches/unviewed/next",
        response_model=ApiResponse[UnviewedMatchData],
        tags=["Matches"],
        summary="확인하지 않은 다음 매칭 조회",
        description="아직 확인하지 않은 매칭 중 다음 항목과 전체 미확인 개수를 조회합니다.",
    )
    async def get_next_unviewed_match(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[HomeRepository, Depends(get_home_repository)],
    ) -> ApiResponse[UnviewedMatchData]:
        row, count = await repository.get_next_unviewed_match(
            authenticated_user_id(claims), datetime.now(ZoneInfo("Asia/Seoul")).date()
        )
        match = UnviewedMatch(**row.__dict__) if row else None
        return ApiResponse(data=UnviewedMatchData(match=match, unviewed_match_count=count))

    @app.patch(
        "/v1/matches/{match_id}/viewed",
        response_model=ApiResponse[ViewedMatchData],
        tags=["Matches"],
        summary="매칭 확인 처리",
        description="지정한 매칭을 사용자가 확인한 상태로 변경합니다.",
    )
    async def mark_match_viewed(
        match_id: UUID,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[HomeRepository, Depends(get_home_repository)],
    ) -> ApiResponse[ViewedMatchData]:
        viewed_at = await repository.mark_match_viewed(authenticated_user_id(claims), match_id)
        if viewed_at is None:
            raise ApiError(404, "MATCH_NOT_FOUND", "매칭을 찾을 수 없습니다.")
        return ApiResponse(data=ViewedMatchData(match_id=match_id, viewed_at=viewed_at))

    def match_detail_data(row: MatchDetailRow) -> MatchDetailData:
        return MatchDetailData(
            id=row.match_id,
            my_photo=MatchedPhoto(
                id=row.my_photo_id,
                image_url=row.my_image_url,
                registered_at=row.my_registered_at,
                deleted=row.my_deleted,
            ),
            partner_photo=MatchedPhoto(
                id=row.partner_photo_id,
                image_url=row.partner_image_url,
                registered_at=row.partner_registered_at,
                deleted=row.partner_deleted,
            ),
            partner=MatchPartner(id=row.partner_id, nickname=row.partner_nickname),
            explanation=row.explanation,
            matched_at=row.matched_at,
            hidden=row.hidden,
            postcard_permission=row.postcard_permission,
        )

    @app.get(
        "/v1/matches/{match_id}",
        response_model=ApiResponse[MatchDetailData],
        tags=["Matches"],
        summary="매칭 상세 조회",
        description="매칭에 참여한 내 사진과 상대 사진, 매칭 설명 및 엽서 발송 가능 상태를 조회합니다.",
    )
    async def get_match(
        match_id: UUID,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[HomeRepository, Depends(get_home_repository)],
    ) -> ApiResponse[MatchDetailData]:
        row = await repository.get_match_detail(authenticated_user_id(claims), match_id)
        if row is None:
            raise ApiError(404, "MATCH_NOT_FOUND", "매칭을 찾을 수 없습니다.")
        return ApiResponse(data=match_detail_data(row))

    @app.patch(
        "/v1/matches/{match_id}/visibility",
        response_model=ApiResponse[MatchVisibilityData],
        tags=["Matches"],
        summary="매칭 숨김 상태 변경",
        description="내 순간 목록에서 지정한 매칭을 숨기거나 다시 표시합니다.",
    )
    async def update_match_visibility(
        match_id: UUID,
        request: MatchVisibilityRequest,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[HomeRepository, Depends(get_home_repository)],
    ) -> ApiResponse[MatchVisibilityData]:
        hidden = await repository.update_match_visibility(
            authenticated_user_id(claims), match_id, hidden=request.hidden
        )
        if hidden is None:
            raise ApiError(404, "MATCH_NOT_FOUND", "매칭을 찾을 수 없습니다.")
        return ApiResponse(data=MatchVisibilityData(match_id=match_id, hidden=hidden))

    @app.post(
        "/v1/reports",
        response_model=ApiResponse[ReportData],
        status_code=status.HTTP_201_CREATED,
        tags=["Safety"],
        summary="콘텐츠 또는 사용자 신고",
        description=(
            "사진·엽서·사용자를 신고합니다. 사용자 신고 시 해당 사용자를 함께 차단하며, "
            "사진 신고 시 관련 매칭을 내 목록에서 숨깁니다."
        ),
    )
    async def create_report(
        request: CreateReportRequest,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[ReportRepository, Depends(get_report_repository)],
    ) -> ApiResponse[ReportData]:
        report = await repository.create(
            reporter_id=authenticated_user_id(claims),
            target_type=request.target_type,
            target_id=request.target_id,
            reason_code=request.reason_code,
            detail=request.detail.strip() if request.detail else None,
        )
        return ApiResponse(
            data=ReportData(
                id=report.id,
                target_type=report.target_type,
                target_id=report.target_id,
                reason_code=report.reason_code,
                status=report.status,
                created_at=report.created_at,
            )
        )

    @app.get(
        "/v1/blocks",
        response_model=ApiResponse[BlockedUserListData],
        tags=["Safety"],
        summary="차단 사용자 목록 조회",
        description="로그인 사용자가 차단한 사용자 목록을 커서 기반 페이지네이션으로 조회합니다.",
    )
    async def list_blocked_users(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[SafetyRepository, Depends(get_safety_repository)],
        size: Annotated[int, Query(ge=1, le=50)] = 20,
        cursor: str | None = None,
    ) -> ApiResponse[BlockedUserListData]:
        rows = await repository.list_blocks(
            authenticated_user_id(claims), size=size, cursor=decode_cursor(cursor)
        )
        has_next = len(rows) > size
        page = rows[:size]
        next_cursor = (
            encode_cursor(page[-1].blocked_at, page[-1].user_id) if has_next and page else None
        )
        return ApiResponse(
            data=BlockedUserListData(
                items=[
                    BlockedUser(
                        user=PublicUser(
                            id=row.user_id,
                            nickname=row.nickname,
                            profile_image_url=row.profile_image_url,
                        ),
                        blocked_at=row.blocked_at,
                    )
                    for row in page
                ],
                next_cursor=next_cursor,
                has_next=has_next,
            )
        )

    @app.post(
        "/v1/blocks/{user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["Safety"],
        summary="사용자 차단",
        description="지정한 사용자를 차단합니다. 본인은 차단할 수 없으며 중복 차단은 거절됩니다.",
    )
    async def block_user(
        user_id: UUID,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[SafetyRepository, Depends(get_safety_repository)],
    ) -> None:
        await repository.block(authenticated_user_id(claims), user_id)

    @app.delete(
        "/v1/blocks/{user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["Safety"],
        summary="사용자 차단 해제",
        description="지정한 사용자의 차단을 해제합니다. 이미 해제된 경우에도 성공으로 처리합니다.",
    )
    async def unblock_user(
        user_id: UUID,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[SafetyRepository, Depends(get_safety_repository)],
    ) -> None:
        await repository.unblock(authenticated_user_id(claims), user_id)

    def notification_data(notification: Notification) -> NotificationData:
        return NotificationData(
            id=notification.id,
            type=notification.type,
            title=notification.title,
            message=notification.message,
            target_type=notification.target_type,
            target_id=notification.target_id,
            is_read=notification.read_at is not None,
            created_at=notification.created_at,
        )

    @app.get(
        "/v1/notifications",
        response_model=ApiResponse[NotificationListData],
        tags=["Notifications"],
        summary="알림 목록 조회",
        description="로그인 사용자의 알림을 최신순으로 조회하며 읽지 않은 알림 개수를 함께 반환합니다.",
    )
    async def list_notifications(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[NotificationRepository, Depends(get_notification_repository)],
        unread_only: bool = False,
        size: Annotated[int, Query(ge=1, le=50)] = 20,
        cursor: str | None = None,
    ) -> ApiResponse[NotificationListData]:
        items, unread_count = await repository.list(
            authenticated_user_id(claims),
            unread_only=unread_only,
            size=size,
            cursor=decode_cursor(cursor),
        )
        has_next = len(items) > size
        page = items[:size]
        next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if has_next and page else None
        return ApiResponse(
            data=NotificationListData(
                items=[notification_data(item) for item in page],
                unread_count=unread_count,
                next_cursor=next_cursor,
                has_next=has_next,
            )
        )

    @app.patch(
        "/v1/notifications/{notification_id}/read",
        response_model=ApiResponse[NotificationData],
        tags=["Notifications"],
        summary="알림 읽음 처리",
        description="로그인 사용자의 지정한 알림 한 건을 읽음 상태로 변경합니다.",
    )
    async def mark_notification_read(
        notification_id: UUID,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[NotificationRepository, Depends(get_notification_repository)],
    ) -> ApiResponse[NotificationData]:
        item = await repository.mark_read(authenticated_user_id(claims), notification_id)
        return ApiResponse(data=notification_data(item))

    @app.patch(
        "/v1/notifications/read-all",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["Notifications"],
        summary="모든 알림 읽음 처리",
        description="로그인 사용자의 읽지 않은 알림을 모두 읽음 상태로 변경합니다.",
    )
    async def mark_all_notifications_read(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[NotificationRepository, Depends(get_notification_repository)],
    ) -> None:
        await repository.mark_all_read(authenticated_user_id(claims))

    def postcard_data(row: PostcardRow) -> PostcardData:
        return PostcardData(
            id=row.id,
            match_id=row.match_id,
            sender=PostcardUser(id=row.sender_id, nickname=row.sender_nickname),
            receiver=PostcardUser(id=row.receiver_id, nickname=row.receiver_nickname),
            content=row.content,
            is_read=row.read_at is not None,
            read_at=row.read_at,
            sent_at=row.sent_at,
            moment_thumbnail_url=row.moment_thumbnail_url,
        )

    @app.post(
        "/v1/matches/{match_id}/postcards",
        response_model=ApiResponse[PostcardData],
        status_code=status.HTTP_201_CREATED,
        tags=["Postcards"],
        summary="엽서 발송",
        description=(
            "매칭된 상대에게 엽서를 발송합니다. 먼저 등록된 사진의 사용자가 시작하고, 이후 "
            "서로 한 장씩 번갈아 답장합니다. Idempotency-Key로 같은 요청을 안전하게 재시도할 수 있습니다."
        ),
    )
    async def send_postcard(
        match_id: UUID,
        request: SendPostcardRequest,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[PostcardRepository, Depends(get_postcard_repository)],
        idempotency_key: Annotated[UUID | None, Header(alias="Idempotency-Key")] = None,
    ) -> ApiResponse[PostcardData]:
        content = request.content.strip()
        if not content:
            raise ApiError(422, "INVALID_POSTCARD_CONTENT", "엽서 내용을 입력해주세요.")
        row = await repository.send(
            authenticated_user_id(claims), match_id, content, idempotency_key
        )
        return ApiResponse(data=postcard_data(row))

    async def postcard_list(
        mailbox: str, user_id: UUID, repository: PostcardRepository, size: int, cursor: str | None
    ) -> ApiResponse[PostcardListData]:
        rows = await repository.list(
            user_id, mailbox=mailbox, size=size, cursor=decode_cursor(cursor)
        )
        has_next = len(rows) > size
        page = rows[:size]
        next_cursor = encode_cursor(page[-1].sent_at, page[-1].id) if has_next and page else None
        return ApiResponse(
            data=PostcardListData(
                items=[postcard_data(row) for row in page],
                next_cursor=next_cursor,
                has_next=has_next,
            )
        )

    @app.get(
        "/v1/postcards/received",
        response_model=ApiResponse[PostcardListData],
        tags=["Postcards"],
        summary="받은 엽서 목록 조회",
        description="로그인 사용자가 받은 엽서를 최신순으로 페이지네이션하여 조회합니다.",
    )
    async def list_received_postcards(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[PostcardRepository, Depends(get_postcard_repository)],
        size: Annotated[int, Query(ge=1, le=50)] = 20,
        cursor: str | None = None,
    ) -> ApiResponse[PostcardListData]:
        return await postcard_list(
            "received", authenticated_user_id(claims), repository, size, cursor
        )

    @app.get(
        "/v1/postcards/sent",
        response_model=ApiResponse[PostcardListData],
        tags=["Postcards"],
        summary="보낸 엽서 목록 조회",
        description="로그인 사용자가 보낸 엽서를 최신순으로 페이지네이션하여 조회합니다.",
    )
    async def list_sent_postcards(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[PostcardRepository, Depends(get_postcard_repository)],
        size: Annotated[int, Query(ge=1, le=50)] = 20,
        cursor: str | None = None,
    ) -> ApiResponse[PostcardListData]:
        return await postcard_list("sent", authenticated_user_id(claims), repository, size, cursor)

    @app.get(
        "/v1/postcards/{postcard_id}",
        response_model=ApiResponse[PostcardData],
        tags=["Postcards"],
        summary="엽서 상세 조회",
        description="로그인 사용자가 보내거나 받은 엽서 한 건의 상세 내용을 조회합니다.",
    )
    async def get_postcard(
        postcard_id: UUID,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[PostcardRepository, Depends(get_postcard_repository)],
    ) -> ApiResponse[PostcardData]:
        return ApiResponse(
            data=postcard_data(await repository.get(authenticated_user_id(claims), postcard_id))
        )

    @app.delete(
        "/v1/postcards/{postcard_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["Postcards"],
        summary="엽서 삭제",
        description="엽서를 로그인 사용자의 보관함에서만 삭제합니다. 상대방 보관함에는 영향을 주지 않습니다.",
    )
    async def delete_postcard(
        postcard_id: UUID,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[PostcardRepository, Depends(get_postcard_repository)],
    ) -> None:
        await repository.delete(authenticated_user_id(claims), postcard_id)

    @app.patch(
        "/v1/postcards/{postcard_id}/read",
        response_model=ApiResponse[PostcardData],
        tags=["Postcards"],
        summary="엽서 읽음 처리",
        description="로그인 사용자가 받은 엽서를 읽음 상태로 변경합니다.",
    )
    async def mark_postcard_read(
        postcard_id: UUID,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[PostcardRepository, Depends(get_postcard_repository)],
    ) -> ApiResponse[PostcardData]:
        return ApiResponse(
            data=postcard_data(
                await repository.mark_read(authenticated_user_id(claims), postcard_id)
            )
        )

    def notification_settings_data(settings) -> NotificationSettingsData:
        return NotificationSettingsData(
            validation_enabled=settings.validation_enabled,
            match_enabled=settings.match_enabled,
            postcard_enabled=settings.postcard_enabled,
            search_expired_enabled=settings.search_expired_enabled,
            system_enabled=settings.system_enabled,
        )

    @app.post(
        "/v1/device-tokens",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["Notifications"],
        summary="기기 푸시 토큰 등록",
        description="푸시 알림 발송에 사용할 iOS 또는 Android 기기 토큰을 등록하거나 갱신합니다.",
    )
    async def register_device_token(
        request: DeviceTokenRequest,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[
            NotificationPreferenceRepository,
            Depends(get_notification_preference_repository),
        ],
    ) -> None:
        token = request.token.strip()
        if not token:
            raise ApiError(422, "INVALID_DEVICE_TOKEN", "기기 토큰을 입력해주세요.")
        await repository.register_device(authenticated_user_id(claims), token, request.platform)

    @app.get(
        "/v1/notification-settings",
        response_model=ApiResponse[NotificationSettingsData],
        tags=["Notifications"],
        summary="알림 설정 조회",
        description="로그인 사용자의 알림 유형별 수신 설정을 조회합니다. 최초 조회 시 기본 설정을 생성합니다.",
    )
    async def get_notification_settings(
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[
            NotificationPreferenceRepository,
            Depends(get_notification_preference_repository),
        ],
    ) -> ApiResponse[NotificationSettingsData]:
        settings = await repository.get_settings(authenticated_user_id(claims))
        return ApiResponse(data=notification_settings_data(settings))

    @app.patch(
        "/v1/notification-settings",
        response_model=ApiResponse[NotificationSettingsData],
        tags=["Notifications"],
        summary="알림 설정 변경",
        description="전달한 알림 유형의 수신 설정만 선택적으로 변경합니다.",
    )
    async def update_notification_settings(
        request: UpdateNotificationSettingsRequest,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        repository: Annotated[
            NotificationPreferenceRepository,
            Depends(get_notification_preference_repository),
        ],
    ) -> ApiResponse[NotificationSettingsData]:
        values = request.model_dump(exclude_none=True)
        if not values:
            raise ApiError(422, "EMPTY_NOTIFICATION_SETTINGS", "변경할 알림 설정을 입력해주세요.")
        settings = await repository.update_settings(authenticated_user_id(claims), values)
        return ApiResponse(data=notification_settings_data(settings))

    return app


app = create_app()
