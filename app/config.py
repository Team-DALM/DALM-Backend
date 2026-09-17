import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    jwt_secret: str
    database_url: str = "postgresql+asyncpg://dalm:dalm@localhost:5433/dalm"
    redis_url: str = "redis://localhost:6380/0"
    kakao_user_info_url: str = "https://kapi.kakao.com/v2/user/me"
    kakao_timeout_seconds: float = 5.0
    apple_client_ids: tuple[str, ...] = ()
    apple_jwks_url: str = "https://appleid.apple.com/auth/keys"
    apple_issuer: str = "https://appleid.apple.com"
    apple_timeout_seconds: float = 5.0
    access_token_ttl_seconds: int = 1_800
    refresh_token_ttl_seconds: int = 2_592_000
    jwt_algorithm: str = "HS256"
    gcs_bucket: str | None = None
    photo_max_bytes: int = 10 * 1024 * 1024
    photo_min_width: int = 800
    photo_min_height: int = 1000
    photo_signed_url_ttl_seconds: int = 900

    @classmethod
    def from_env(cls) -> "Settings":
        secret = os.getenv("DALM_JWT_SECRET", "")
        if len(secret) < 32:
            raise RuntimeError("DALM_JWT_SECRET must contain at least 32 characters")
        return cls(
            jwt_secret=secret,
            database_url=os.getenv(
                "DALM_DATABASE_URL",
                "postgresql+asyncpg://dalm:dalm@localhost:5433/dalm",
            ),
            redis_url=os.getenv("DALM_REDIS_URL", "redis://localhost:6380/0"),
            kakao_user_info_url=os.getenv(
                "DALM_KAKAO_USER_INFO_URL",
                "https://kapi.kakao.com/v2/user/me",
            ),
            kakao_timeout_seconds=float(os.getenv("DALM_KAKAO_TIMEOUT_SECONDS", "5")),
            apple_client_ids=tuple(
                value.strip()
                for value in os.getenv("DALM_APPLE_CLIENT_IDS", "").split(",")
                if value.strip()
            ),
            apple_jwks_url=os.getenv("DALM_APPLE_JWKS_URL", "https://appleid.apple.com/auth/keys"),
            apple_issuer=os.getenv("DALM_APPLE_ISSUER", "https://appleid.apple.com"),
            apple_timeout_seconds=float(os.getenv("DALM_APPLE_TIMEOUT_SECONDS", "5")),
            access_token_ttl_seconds=int(os.getenv("DALM_ACCESS_TOKEN_TTL_SECONDS", "1800")),
            refresh_token_ttl_seconds=int(os.getenv("DALM_REFRESH_TOKEN_TTL_SECONDS", "2592000")),
            gcs_bucket=os.getenv("DALM_GCS_BUCKET") or None,
            photo_max_bytes=int(os.getenv("DALM_PHOTO_MAX_BYTES", str(10 * 1024 * 1024))),
            photo_min_width=int(os.getenv("DALM_PHOTO_MIN_WIDTH", "800")),
            photo_min_height=int(os.getenv("DALM_PHOTO_MIN_HEIGHT", "1000")),
            photo_signed_url_ttl_seconds=int(os.getenv("DALM_PHOTO_SIGNED_URL_TTL_SECONDS", "900")),
        )
