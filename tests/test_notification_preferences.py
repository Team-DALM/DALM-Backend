import asyncio
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_notification_preference_repository
from app.main import create_app
from app.token_store import InMemoryRefreshTokenStore

SETTINGS = Settings(jwt_secret="test-secret-that-is-long-enough-for-preference-tests")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeDependency:
    async def ping(self):
        pass

    async def close(self):
        pass


class FakeRepository:
    def __init__(self):
        self.device = None
        self.settings = SimpleNamespace(
            validation_enabled=True,
            match_enabled=True,
            postcard_enabled=True,
            search_expired_enabled=True,
            system_enabled=True,
        )

    async def register_device(self, user_id, token, platform):
        self.device = (user_id, token, platform)

    async def get_settings(self, user_id):
        return self.settings

    async def update_settings(self, user_id, values):
        for key, value in values.items():
            setattr(self.settings, key, value)
        return self.settings


def make_client():
    dependency = FakeDependency()
    repository = FakeRepository()
    app = create_app(
        SETTINGS,
        database=dependency,
        cache=dependency,
        refresh_store=InMemoryRefreshTokenStore(),
    )
    app.dependency_overrides[get_notification_preference_repository] = lambda: repository
    client = TestClient(app)
    token = asyncio.run(client.app.state.token_service.issue_pair(str(USER_ID))).access_token
    return client, {"Authorization": f"Bearer {token}"}, repository


def test_register_device_token():
    client, headers, repository = make_client()
    response = client.post(
        "/v1/device-tokens", headers=headers, json={"token": " fcm-token ", "platform": "IOS"}
    )
    assert response.status_code == 204
    assert repository.device == (USER_ID, "fcm-token", "IOS")


def test_get_and_patch_notification_settings():
    client, headers, repository = make_client()
    initial = client.get("/v1/notification-settings", headers=headers)
    updated = client.patch(
        "/v1/notification-settings",
        headers=headers,
        json={"match_enabled": False, "postcard_enabled": False},
    )
    assert initial.json()["data"]["match_enabled"] is True
    assert updated.json()["data"]["match_enabled"] is False
    assert repository.settings.postcard_enabled is False


def test_empty_settings_patch_is_rejected():
    client, headers, _ = make_client()
    response = client.patch("/v1/notification-settings", headers=headers, json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_NOTIFICATION_SETTINGS"
