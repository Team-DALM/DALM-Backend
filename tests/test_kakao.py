import asyncio

import httpx
import pytest

from app.errors import ApiError
from app.kakao import KakaoClient


def test_kakao_client_returns_profile() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer kakao-token"
        return httpx.Response(200, json={"id": 123456789})

    client = KakaoClient(
        "https://kapi.kakao.test/v2/user/me",
        1,
        transport=httpx.MockTransport(handler),
    )

    profile = asyncio.run(client.get_profile("kakao-token"))

    assert profile.kakao_id == "123456789"


def test_kakao_client_maps_invalid_token_to_authentication_error() -> None:
    client = KakaoClient(
        "https://kapi.kakao.test/v2/user/me",
        1,
        transport=httpx.MockTransport(lambda request: httpx.Response(401)),
    )

    with pytest.raises(ApiError) as error:
        asyncio.run(client.get_profile("invalid"))

    assert error.value.status_code == 401
    assert error.value.code == "AUTHENTICATION_FAILED"


def test_kakao_client_maps_invalid_response() -> None:
    client = KakaoClient(
        "https://kapi.kakao.test/v2/user/me",
        1,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )

    with pytest.raises(ApiError) as error:
        asyncio.run(client.get_profile("valid"))

    assert error.value.status_code == 502
    assert error.value.code == "KAKAO_INVALID_RESPONSE"

