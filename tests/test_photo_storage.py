import asyncio
from unittest.mock import Mock

import pytest

from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.photo_storage import UnconfiguredPhotoStorage


def test_retired_gcs_setting_does_not_enable_storage(monkeypatch):
    monkeypatch.delenv("DALM_S3_BUCKET", raising=False)
    monkeypatch.setenv("DALM_GCS_BUCKET", "deleted-bucket")
    monkeypatch.setenv("DALM_JWT_SECRET", "test-secret-that-is-long-enough-for-storage")
    app = create_app(Settings.from_env())
    storage = app.state.photo_storage
    assert isinstance(storage, UnconfiguredPhotoStorage)
    for operation in (
        storage.upload("photos/key", b"photo", "image/webp"),
        storage.signed_url("photos/key", 60),
    ):
        with pytest.raises(ApiError) as exc:
            asyncio.run(operation)
        assert exc.value.status_code == 503
        assert exc.value.code == "PHOTO_STORAGE_NOT_CONFIGURED"


def test_app_uses_s3_when_configured(monkeypatch):
    factory = Mock()
    monkeypatch.setattr("app.main.S3PhotoStorage", factory)
    app = create_app(Settings(
        jwt_secret="test-secret-that-is-long-enough-for-storage",
        s3_bucket="private-photos",
    ))
    factory.assert_called_once_with("private-photos", region="ap-northeast-2")
    assert app.state.photo_storage is factory.return_value
