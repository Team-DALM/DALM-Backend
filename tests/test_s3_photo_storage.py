import asyncio
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from app.errors import ApiError
from app.photo_storage import S3PhotoStorage


def make_storage():
    client = Mock()
    return S3PhotoStorage("private-bucket", region="ap-northeast-2", client=client), client


def test_upload_prevents_overwriting_existing_photo():
    storage, client = make_storage()
    asyncio.run(storage.upload("photos/user/id/original.webp", b"photo", "image/webp"))
    client.put_object.assert_called_once_with(
        Bucket="private-bucket", Key="photos/user/id/original.webp", Body=b"photo",
        ContentType="image/webp", IfNoneMatch="*",
    )
    client.put_object.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailed"}, "ResponseMetadata": {"HTTPStatusCode": 412}},
        "PutObject",
    )
    with pytest.raises(ApiError) as exc:
        asyncio.run(storage.upload("photos/user/id/original.webp", b"other", "image/webp"))
    assert exc.value.code == "PHOTO_OBJECT_CONFLICT"


def test_read_url_is_temporary_and_delete_uses_same_key():
    storage, client = make_storage()
    client.generate_presigned_url.return_value = "https://s3.example/signed"
    assert asyncio.run(storage.signed_url("photos/key", 900)) == "https://s3.example/signed"
    client.generate_presigned_url.assert_called_once_with(
        "get_object", Params={"Bucket": "private-bucket", "Key": "photos/key"}, ExpiresIn=900,
    )
    asyncio.run(storage.delete("photos/key"))
    client.delete_object.assert_called_once_with(Bucket="private-bucket", Key="photos/key")


@pytest.mark.parametrize("operation", ["upload", "delete", "signed_url"])
@pytest.mark.parametrize("error", [NoCredentialsError(), ClientError(
    {"Error": {"Code": "AccessDenied"}}, "S3",
)])
def test_aws_failures_return_existing_api_error(operation, error):
    storage, client = make_storage()
    client.put_object.side_effect = error
    client.delete_object.side_effect = error
    client.generate_presigned_url.side_effect = error
    args = {"upload": ("key", b"photo", "image/webp"), "delete": ("key",),
            "signed_url": ("key", 60)}
    with pytest.raises(ApiError) as exc:
        asyncio.run(getattr(storage, operation)(*args[operation]))
    assert exc.value.code == "PHOTO_STORAGE_UNAVAILABLE"
