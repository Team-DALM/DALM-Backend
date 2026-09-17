import asyncio
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.dependencies import get_home_repository
from app.errors import ApiError
from app.main import create_app
from app.photo_upload import process_photo
from app.token_store import InMemoryRefreshTokenStore

USER_ID = UUID("11111111-1111-1111-1111-111111111111")
SETTINGS = Settings(
    jwt_secret="test-secret-that-is-long-enough-for-photo-upload",
    photo_min_width=80,
    photo_min_height=100,
)


class FakeDependency:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded = None
        self.deleted = []
        self.signed = None

    async def upload(self, key, content, content_type):
        self.uploaded = (key, content, content_type)

    async def delete(self, key):
        self.deleted.append(key)

    async def signed_url(self, key, expires_in):
        self.signed = (key, expires_in)
        return "https://storage.example/signed"


class FakeRepository:
    def __init__(self) -> None:
        self.created = None
        self.photo = None
        self.allowed = True
        self.failure = None

    async def create_photo(self, **values):
        if self.failure:
            raise self.failure
        self.created = values
        return SimpleNamespace(registered_at=datetime.now(UTC), **values)

    async def get_photo(self, photo_id):
        return self.photo

    async def can_access_photo(self, user_id, photo_id):
        assert user_id == USER_ID
        return self.allowed


def image_bytes(width=80, height=100, *, format="JPEG", exif=None):
    output = BytesIO()
    Image.new("RGB", (width, height), "navy").save(output, format=format, exif=exif or b"")
    return output.getvalue()


def make_client(repository=None, storage=None):
    dependency = FakeDependency()
    repository = repository or FakeRepository()
    storage = storage or FakeStorage()
    app = create_app(
        SETTINGS,
        database=dependency,
        cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
        photo_storage=storage,
    )
    app.dependency_overrides[get_home_repository] = lambda: repository
    client = TestClient(app)
    token = asyncio.run(client.app.state.token_service.issue_pair(str(USER_ID))).access_token
    return client, token, repository, storage


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_process_photo_normalizes_to_webp_and_strips_metadata():
    exif = Image.Exif()
    exif[0x010E] = "private metadata"
    result = process_photo(
        image_bytes(exif=exif),
        "image/jpeg",
        max_bytes=1_000_000,
        min_width=80,
        min_height=100,
    )

    assert result.content_type == "image/webp"
    with Image.open(BytesIO(result.content)) as image:
        assert image.size == (80, 100)
        assert not image.getexif()


def test_create_photo_uploads_private_object_and_creates_validating_row():
    client, token, repository, storage = make_client()

    response = client.post(
        "/v1/photos",
        headers=auth(token),
        files={"image": ("moment.jpg", image_bytes(), "image/jpeg")},
    )

    assert response.status_code == 202
    assert response.json()["data"]["status"] == "VALIDATING"
    assert storage.uploaded[0].startswith(f"photos/{USER_ID}/")
    assert storage.uploaded[0].endswith("/original.webp")
    assert storage.uploaded[2] == "image/webp"
    assert repository.created["user_id"] == USER_ID
    assert repository.created["checksum"]


def test_create_photo_deletes_object_when_database_write_fails():
    repository = FakeRepository()
    repository.failure = ApiError(409, "TODAY_PHOTO_ALREADY_EXISTS", "이미 있습니다.")
    storage = FakeStorage()
    client, token, _, _ = make_client(repository, storage)

    response = client.post(
        "/v1/photos",
        headers=auth(token),
        files={"image": ("moment.jpg", image_bytes(), "image/jpeg")},
    )

    assert response.status_code == 409
    assert storage.deleted == [storage.uploaded[0]]


def test_create_photo_rejects_wrong_ratio_before_upload():
    client, token, _, storage = make_client()

    response = client.post(
        "/v1/photos",
        headers=auth(token),
        files={"image": ("square.jpg", image_bytes(100, 100), "image/jpeg")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_IMAGE_RATIO"
    assert storage.uploaded is None


def test_create_photo_rejects_mismatched_declared_content_type():
    client, token, _, storage = make_client()

    response = client.post(
        "/v1/photos",
        headers=auth(token),
        files={"image": ("moment.png", image_bytes(), "image/png")},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "IMAGE_CONTENT_TYPE_MISMATCH"
    assert storage.uploaded is None


def test_photo_image_redirect_requires_access_and_uses_short_lived_url():
    repository = FakeRepository()
    repository.photo = SimpleNamespace(
        storage_key="photos/user/photo/original.webp", deleted_at=None
    )
    storage = FakeStorage()
    client, token, _, _ = make_client(repository, storage)

    response = client.get(
        "/v1/photos/22222222-2222-2222-2222-222222222222/image",
        headers=auth(token),
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "https://storage.example/signed"
    assert storage.signed == ("photos/user/photo/original.webp", 900)
