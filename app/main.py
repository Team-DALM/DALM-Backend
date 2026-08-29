from typing import Annotated

from fastapi import Depends, FastAPI, Response, status

from app.config import Settings
from app.dependencies import get_token_service, require_access_token
from app.errors import ApiError, api_error_handler
from app.schemas import ApiResponse, RefreshTokenRequest, TokenPair
from app.token_store import InMemoryRefreshTokenStore
from app.tokens import TokenClaims, TokenService


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    app = FastAPI(title="DALM API", version="0.1.0")
    app.state.token_service = TokenService(
        resolved_settings,
        InMemoryRefreshTokenStore(),
    )
    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]

    @app.get("/health", tags=["System"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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

