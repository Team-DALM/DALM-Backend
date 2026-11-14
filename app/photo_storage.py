import asyncio
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

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


class S3PhotoStorage:
    """Private S3 objects using the EC2 instance role, without static access keys."""

    def __init__(self, bucket_name: str, *, region: str, client=None) -> None:
        self._bucket = bucket_name
        self._client = client or boto3.client(
            "s3",
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )

    @staticmethod
    def _unavailable() -> ApiError:
        return ApiError(503, "PHOTO_STORAGE_UNAVAILABLE", "사진 저장소를 사용할 수 없습니다.")

    async def upload(self, key: str, content: bytes, content_type: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket, Key=key, Body=content,
                ContentType=content_type, IfNoneMatch="*",
            )
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 412:
                raise ApiError(
                    409, "PHOTO_OBJECT_CONFLICT", "사진 저장 경로가 이미 존재합니다."
                ) from exc
            raise self._unavailable() from exc
        except BotoCoreError as exc:
            raise self._unavailable() from exc

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable() from exc

    async def signed_url(self, key: str, expires_in: int) -> str:
        try:
            return await asyncio.to_thread(
                self._client.generate_presigned_url,
                "get_object", Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable() from exc
