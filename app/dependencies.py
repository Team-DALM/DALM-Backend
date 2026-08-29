from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import ApiError
from app.tokens import TokenClaims, TokenService

bearer_scheme = HTTPBearer(auto_error=False)


def get_token_service(request: Request) -> TokenService:
    return request.app.state.token_service


def require_access_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Annotated[TokenService, Depends(get_token_service)],
) -> TokenClaims:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "인증이 필요합니다.")
    return service.decode(credentials.credentials, "access")

