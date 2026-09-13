import asyncio
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.apple import AppleClient
from app.errors import ApiError

CLIENT_ID = "com.dalm.app"
ISSUER = "https://appleid.apple.com"
KEY_ID = "apple-key-id"


def make_client(*, response_status: int = 200) -> tuple[AppleClient, rsa.RSAPrivateKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": KEY_ID, "alg": "RS256", "use": "sig"})

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://appleid.apple.test/auth/keys"
        return httpx.Response(response_status, json={"keys": [public_jwk]})

    return (
        AppleClient(
            "https://appleid.apple.test/auth/keys",
            ISSUER,
            (CLIENT_ID,),
            1,
            transport=httpx.MockTransport(handler),
        ),
        private_key,
    )


def identity_token(private_key: rsa.RSAPrivateKey, **overrides: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "001234.abcd",
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": KEY_ID})


def test_apple_client_verifies_identity_token() -> None:
    client, private_key = make_client()

    profile = asyncio.run(client.verify_identity_token(identity_token(private_key)))

    assert profile.apple_id == "001234.abcd"


def test_apple_client_rejects_wrong_audience() -> None:
    client, private_key = make_client()

    with pytest.raises(ApiError) as error:
        asyncio.run(
            client.verify_identity_token(identity_token(private_key, aud="another.app"))
        )

    assert error.value.status_code == 401
    assert error.value.code == "AUTHENTICATION_FAILED"


def test_apple_client_maps_jwks_failure_to_upstream_error() -> None:
    client, private_key = make_client(response_status=503)

    with pytest.raises(ApiError) as error:
        asyncio.run(client.verify_identity_token(identity_token(private_key)))

    assert error.value.status_code == 502
    assert error.value.code == "APPLE_API_UNAVAILABLE"


def test_apple_client_requires_client_id_configuration() -> None:
    client = AppleClient("https://example.test/keys", ISSUER, (), 1)

    with pytest.raises(ApiError) as error:
        asyncio.run(client.verify_identity_token("token"))

    assert error.value.status_code == 503
    assert error.value.code == "APPLE_LOGIN_NOT_CONFIGURED"
