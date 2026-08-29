import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, Response, status
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.cache import Cache
from app.config import Settings
from app.database import Database
from app.dependencies import get_token_service, require_access_token
from app.errors import ApiError, api_error_handler
from app.schemas import ApiResponse, RefreshTokenRequest, TokenPair
from app.token_store import InMemoryRefreshTokenStore
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
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_database = database or Database(resolved_settings.database_url)
    resolved_cache = cache or Cache(resolved_settings.redis_url)

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
    app.state.token_service = TokenService(
        resolved_settings,
        InMemoryRefreshTokenStore(),
    )
    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]

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

    @app.post("/v1/auth/refresh", response_model=ApiResponse[TokenPair], tags=["Auth"])
    async def refresh_token(
        request: RefreshTokenRequest,
        service: Annotated[TokenService, Depends(get_token_service)],
    ) -> ApiResponse[TokenPair]:
        return ApiResponse(data=await service.rotate(request.refresh_token))

    @app.post("/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["Auth"])
    async def logout(
        response: Response,
        _: Annotated[TokenClaims, Depends(require_access_token)],
    ) -> None:
        response.status_code = status.HTTP_204_NO_CONTENT

    return app


app = create_app()

