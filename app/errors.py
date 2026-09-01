from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            },
        },
        headers={"X-Request-ID": request_id},
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return _error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


async def infrastructure_error_handler(request: Request, exc: Exception) -> JSONResponse:
    del exc
    return _error_response(
        request,
        status_code=503,
        code="SERVICE_UNAVAILABLE",
        message="일시적으로 서비스를 이용할 수 없습니다.",
    )

