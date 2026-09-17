import asyncio
from datetime import timedelta
from typing import Protocol

from google.api_core.exceptions import GoogleAPIError, NotFound, PreconditionFailed
from google.auth.transport.requests import Request
from google.cloud import storage

from app.errors import ApiError


class PhotoStorage(Protocol):
    async def upload(self, key: str, content: bytes, content_type: str) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def signed_url(self, key: str, expires_in: int) -> str: ...


class UnconfiguredPhotoStorage:
    @staticmethod
    def _error() -> ApiError:
        return ApiError(
            503,
            "PHOTO_STORAGE_NOT_CONFIGURED",
            "사진 저장소가 아직 설정되지 않았습니다.",
        )

    async def upload(self, key: str, content: bytes, content_type: str) -> None:
        del key, content, content_type
        raise self._error()

    async def delete(self, key: str) -> None:
        del key

    async def signed_url(self, key: str, expires_in: int) -> str:
        del key, expires_in
        raise self._error()


class GcsPhotoStorage:
    def __init__(self, bucket_name: str, *, client: storage.Client | None = None) -> None:
        self._client = client or storage.Client()
        self._bucket = self._client.bucket(bucket_name)

    async def upload(self, key: str, content: bytes, content_type: str) -> None:
        blob = self._bucket.blob(key)
        try:
            await asyncio.to_thread(
                blob.upload_from_string,
                content,
                content_type=content_type,
                if_generation_match=0,
            )
        except PreconditionFailed as exc:
            raise ApiError(
                409, "PHOTO_OBJECT_CONFLICT", "사진 저장 경로가 이미 존재합니다."
            ) from exc
        except GoogleAPIError as exc:
            raise ApiError(
                503, "PHOTO_STORAGE_UNAVAILABLE", "사진 저장소를 사용할 수 없습니다."
            ) from exc

    async def delete(self, key: str) -> None:
        blob = self._bucket.blob(key)
        try:
            await asyncio.to_thread(blob.delete)
        except NotFound:
            return
        except GoogleAPIError as exc:
            raise ApiError(
                503, "PHOTO_STORAGE_UNAVAILABLE", "사진 저장소를 사용할 수 없습니다."
            ) from exc

    async def signed_url(self, key: str, expires_in: int) -> str:
        blob = self._bucket.blob(key)

        def generate() -> str:
            credentials = self._client._credentials
            kwargs = {}
            if not hasattr(credentials, "sign_bytes"):
                credentials.refresh(Request())
                service_account_email = getattr(credentials, "service_account_email", None)
                if service_account_email:
                    kwargs = {
                        "service_account_email": service_account_email,
                        "access_token": credentials.token,
                    }
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expires_in),
                method="GET",
                **kwargs,
            )

        try:
            return await asyncio.to_thread(generate)
        except (GoogleAPIError, AttributeError, ValueError) as exc:
            raise ApiError(
                503, "PHOTO_STORAGE_UNAVAILABLE", "사진 저장소를 사용할 수 없습니다."
            ) from exc
