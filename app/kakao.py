from dataclasses import dataclass

import httpx

from app.errors import ApiError


@dataclass(frozen=True, slots=True)
class KakaoProfile:
    kakao_id: str


class KakaoClient:
    def __init__(
        self,
        user_info_url: str,
        timeout_seconds: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._user_info_url = user_info_url
        self._timeout = timeout_seconds
        self._transport = transport

    async def get_profile(self, access_token: str) -> KakaoProfile:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.get(
                    self._user_info_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.RequestError as exc:
            raise ApiError(
                502,
                "KAKAO_API_UNAVAILABLE",
                "카카오 인증 서버에 연결할 수 없습니다.",
            ) from exc

        if response.status_code in {401, 403}:
            raise ApiError(401, "AUTHENTICATION_FAILED", "카카오 인증에 실패했습니다.")
        if response.is_error:
            raise ApiError(
                502,
                "KAKAO_API_UNAVAILABLE",
                "카카오 인증 서버 요청에 실패했습니다.",
            )

        try:
            kakao_id = str(response.json()["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError(
                502,
                "KAKAO_INVALID_RESPONSE",
                "카카오 인증 응답을 처리할 수 없습니다.",
            ) from exc
        return KakaoProfile(kakao_id=kakao_id)

