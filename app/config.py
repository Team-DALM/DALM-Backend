import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    jwt_secret: str
    access_token_ttl_seconds: int = 1_800
    refresh_token_ttl_seconds: int = 2_592_000
    jwt_algorithm: str = "HS256"

    @classmethod
    def from_env(cls) -> "Settings":
        secret = os.getenv("DALM_JWT_SECRET", "")
        if len(secret) < 32:
            raise RuntimeError("DALM_JWT_SECRET must contain at least 32 characters")
        return cls(
            jwt_secret=secret,
            access_token_ttl_seconds=int(
                os.getenv("DALM_ACCESS_TOKEN_TTL_SECONDS", "1800")
            ),
            refresh_token_ttl_seconds=int(
                os.getenv("DALM_REFRESH_TOKEN_TTL_SECONDS", "2592000")
            ),
        )

