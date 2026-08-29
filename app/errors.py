from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "data": None,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id,
            },
        },
        headers={"X-Request-ID": request_id},
    )

