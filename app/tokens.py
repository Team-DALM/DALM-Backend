from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from app.config import Settings
from app.errors import ApiError
from app.schemas import TokenPair
from app.token_store import RefreshTokenStore

AUTHENTICATION_FAILED = ApiError(
    401,
    "AUTHENTICATION_FAILED",
    "인증 토큰이 유효하지 않거나 만료되었습니다.",
)
ACCESS_TOKEN_EXPIRED = ApiError(401, "ACCESS_TOKEN_EXPIRED", "액세스 토큰이 만료되었습니다.")
REFRESH_TOKEN_EXPIRED = ApiError(401, "REFRESH_TOKEN_EXPIRED", "리프레시 토큰이 만료되었습니다.")


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: str
    token_id: str
    token_type: str


class TokenService:
    def __init__(self, settings: Settings, store: RefreshTokenStore) -> None:
        self._settings = settings
        self._store = store

    def _encode(self, subject: str, token_type: str, ttl_seconds: int, token_id: str) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": subject,
                "jti": token_id,
                "type": token_type,
                "iat": now,
                "exp": now + timedelta(seconds=ttl_seconds),
            },
            self._settings.jwt_secret,
            algorithm=self._settings.jwt_algorithm,
        )

    def decode(self, token: str, expected_type: str) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=[self._settings.jwt_algorithm],
                options={"require": ["sub", "jti", "type", "iat", "exp"]},
            )
            if payload["type"] != expected_type:
                raise InvalidTokenError("unexpected token type")
            return TokenClaims(
                subject=str(payload["sub"]),
                token_id=str(payload["jti"]),
                token_type=str(payload["type"]),
            )
        except ExpiredSignatureError as exc:
            try:
                expired_payload = jwt.decode(
                    token,
                    self._settings.jwt_secret,
                    algorithms=[self._settings.jwt_algorithm],
                    options={
                        "require": ["sub", "jti", "type", "iat", "exp"],
                        "verify_exp": False,
                    },
                )
                if expired_payload["type"] != expected_type:
                    raise InvalidTokenError("unexpected token type")
            except (InvalidTokenError, KeyError, TypeError) as invalid_exc:
                raise AUTHENTICATION_FAILED from invalid_exc
            if expected_type == "access":
                raise ACCESS_TOKEN_EXPIRED from exc
            if expected_type == "refresh":
                raise REFRESH_TOKEN_EXPIRED from exc
            raise AUTHENTICATION_FAILED from exc
        except (InvalidTokenError, KeyError, TypeError) as exc:
            raise AUTHENTICATION_FAILED from exc

    def _new_pair(self, subject: str) -> tuple[TokenPair, str]:
        access_id = str(uuid4())
        refresh_id = str(uuid4())
        pair = TokenPair(
            access_token=self._encode(
                subject, "access", self._settings.access_token_ttl_seconds, access_id
            ),
            refresh_token=self._encode(
                subject, "refresh", self._settings.refresh_token_ttl_seconds, refresh_id
            ),
            expires_in=self._settings.access_token_ttl_seconds,
        )
        return pair, refresh_id

    async def issue_pair(self, subject: str) -> TokenPair:
        pair, refresh_id = self._new_pair(subject)
        await self._store.register(
            refresh_id,
            subject,
            self._settings.refresh_token_ttl_seconds,
        )
        return pair

    async def rotate(self, refresh_token: str) -> TokenPair:
        claims = self.decode(refresh_token, "refresh")
        pair, new_refresh_id = self._new_pair(claims.subject)
        rotated = await self._store.rotate(
            claims.token_id,
            new_refresh_id,
            claims.subject,
            self._settings.refresh_token_ttl_seconds,
        )
        if not rotated:
            raise AUTHENTICATION_FAILED
        return pair

    async def revoke(self, refresh_token: str, expected_subject: str) -> None:
        claims = self.decode(refresh_token, "refresh")
        if claims.subject != expected_subject:
            raise AUTHENTICATION_FAILED
        if not await self._store.revoke(claims.token_id, claims.subject):
            raise AUTHENTICATION_FAILED
