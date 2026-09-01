import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, Response, status
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.auth import AuthService
from app.cache import Cache
from app.config import Settings
from app.database import Database
from app.dependencies import get_auth_service, get_token_service, require_access_token
from app.errors import ApiError, api_error_handler, infrastructure_error_handler
from app.kakao import KakaoClient
from app.schemas import (
    ApiResponse,
    AuthData,
    KakaoLoginRequest,
    RefreshTokenRequest,
    TokenPair,
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

    app = FastAPI(title="DALM API", version="0.1.0", lifespan=lifespan)
    app.state.token_service = TokenService(resolved_settings, resolved_refresh_store)
    app.state.kakao_client = resolved_kakao_client
    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RedisError, infrastructure_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(SQLAlchemyError, infrastructure_error_handler)  # type: ignore[arg-type]

    @app.get("/health", tags=["System"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["System"])
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

    @app.post("/v1/auth/kakao", response_model=ApiResponse[AuthData], tags=["Auth"])
    async def login_with_kakao(
        request: KakaoLoginRequest,
        response: Response,
        service: Annotated[AuthService, Depends(get_auth_service)],
    ) -> ApiResponse[AuthData]:
        data, is_new_user = await service.login_with_kakao(request.access_token)
        response.status_code = status.HTTP_201_CREATED if is_new_user else status.HTTP_200_OK
        return ApiResponse(data=data)

    @app.post("/v1/auth/refresh", response_model=ApiResponse[TokenPair], tags=["Auth"])
    async def refresh_token(
        request: RefreshTokenRequest,
        service: Annotated[TokenService, Depends(get_token_service)],
    ) -> ApiResponse[TokenPair]:
        return ApiResponse(data=await service.rotate(request.refresh_token))

    @app.post("/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["Auth"])
    async def logout(
        request: RefreshTokenRequest,
        claims: Annotated[TokenClaims, Depends(require_access_token)],
        service: Annotated[TokenService, Depends(get_token_service)],
    ) -> None:
        await service.revoke(request.refresh_token, claims.subject)

    return app


app = create_app()

