import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.auth.compute_engine.credentials import Credentials
from google.auth.exceptions import RefreshError, TransportError

from app.errors import ApiError
from app.photo_storage import SIGNING_SCOPES, GcsPhotoStorage


def make_storage(credentials):
    blob = Mock()
    blob.generate_signed_url.return_value = "https://storage.example/signed"
    bucket = Mock()
    bucket.blob.return_value = blob
    client = SimpleNamespace(_credentials=credentials, bucket=Mock(return_value=bucket))
    return GcsPhotoStorage("private-photos", client=client), blob


def test_cloud_run_signing_refreshes_separate_cloud_platform_credentials(monkeypatch):
    original = Credentials(scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
    original.token = "storage-token"
    refreshed = []

    def refresh(credentials, request):
        refreshed.append(credentials)
        credentials.token = "signing-token"
        credentials._service_account_email = "runtime@example.iam.gserviceaccount.com"

    monkeypatch.setattr(Credentials, "refresh", refresh)
    storage, blob = make_storage(original)
    assert asyncio.run(storage.signed_url("photos/test.webp", 900)) == blob.generate_signed_url.return_value
    assert refreshed[0] is not original
    assert refreshed[0].scopes == SIGNING_SCOPES
    assert original.token == "storage-token"
    blob.generate_signed_url.assert_called_once_with(
        version="v4", expiration=timedelta(seconds=900), method="GET",
        service_account_email="runtime@example.iam.gserviceaccount.com",
        access_token="signing-token",
    )


def test_private_key_signing_does_not_refresh_credentials():
    credentials = SimpleNamespace(sign_bytes=Mock(), refresh=Mock())
    storage, blob = make_storage(credentials)
    asyncio.run(storage.signed_url("photos/test.webp", 60))
    credentials.refresh.assert_not_called()
    blob.generate_signed_url.assert_called_once_with(
        version="v4", expiration=timedelta(seconds=60), method="GET"
    )


@pytest.mark.parametrize("error", [TransportError("signBlob denied"), RefreshError("refresh failed")])
def test_auth_signing_errors_become_storage_unavailable(error, caplog):
    storage, blob = make_storage(SimpleNamespace(sign_bytes=Mock()))
    blob.generate_signed_url.side_effect = error
    with pytest.raises(ApiError) as caught:
        asyncio.run(storage.signed_url("photos/test.webp", 60))
    assert caught.value.status_code == 503
    assert caught.value.code == "PHOTO_STORAGE_UNAVAILABLE"
    assert "Photo URL signing failed" in caplog.text
