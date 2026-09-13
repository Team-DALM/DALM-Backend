import asyncio
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWK

from app.errors import ApiError


@dataclass(frozen=True, slots=True)
class AppleProfile:
    apple_id: str


class AppleClient:
    def __init__(
        self,
        jwks_url: str,
        issuer: str,
        client_ids: tuple[str, ...],
        timeout_seconds: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._jwks_url = jwks_url
        self._issuer = issuer
        self._client_ids = client_ids
        self._timeout = timeout_seconds
        self._transport = transport
        self._keys: dict[str, PyJWK] = {}
        self._keys_lock = asyncio.Lock()

    async def verify_identity_token(self, identity_token: str) -> AppleProfile:
        if not self._client_ids:
            raise ApiError(503, "APPLE_LOGIN_NOT_CONFIGURED", "Apple 로그인이 설정되지 않았습니다.")

        try:
            header = jwt.get_unverified_header(identity_token)
            key_id = header["kid"]
            algorithm = header["alg"]
        except (jwt.PyJWTError, KeyError, TypeError) as exc:
            raise self._authentication_failed() from exc
        if not isinstance(key_id, str) or algorithm != "RS256":
            raise self._authentication_failed()

        key = self._keys.get(key_id)
        if key is None:
            await self._refresh_keys()
            key = self._keys.get(key_id)
        if key is None:
            raise self._authentication_failed()

        try:
            claims = jwt.decode(
                identity_token,
                key.key,
                algorithms=["RS256"],
                audience=self._client_ids,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            apple_id = claims["sub"]
            if not isinstance(apple_id, str) or not apple_id:
                raise jwt.InvalidTokenError
        except (jwt.PyJWTError, KeyError, TypeError) as exc:
            raise self._authentication_failed() from exc
        return AppleProfile(apple_id=apple_id)

    async def _refresh_keys(self) -> None:
        async with self._keys_lock:
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout, transport=self._transport
                ) as client:
                    response = await client.get(self._jwks_url)
                response.raise_for_status()
                raw_keys = response.json()["keys"]
                keys = {
                    raw_key["kid"]: PyJWK.from_dict(raw_key)
                    for raw_key in raw_keys
                    if isinstance(raw_key, dict) and isinstance(raw_key.get("kid"), str)
                }
                if not keys:
                    raise ValueError("Apple JWKS did not contain any keys")
            except (
                httpx.RequestError,
                httpx.HTTPStatusError,
                KeyError,
                TypeError,
                ValueError,
                jwt.PyJWTError,
            ) as exc:
                raise ApiError(
                    502,
                    "APPLE_API_UNAVAILABLE",
                    "Apple 인증 서버에 연결할 수 없습니다.",
                ) from exc
            self._keys = keys

    @staticmethod
    def _authentication_failed() -> ApiError:
        return ApiError(401, "AUTHENTICATION_FAILED", "Apple 인증에 실패했습니다.")
