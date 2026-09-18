import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.expiration import SqlExpirationStore, expire_searching_photos
from app.models import Notification


class FakeStore:
    def __init__(self):
        self.now = None
        self.ids = [uuid4(), uuid4()]

    async def expire_due(self, now):
        self.now = now
        return self.ids


def test_expire_searching_photos_passes_aware_time_and_returns_ids():
    store = FakeStore()
    now = datetime(2026, 9, 14, tzinfo=UTC)

    result = asyncio.run(expire_searching_photos(store, now=now))

    assert result == store.ids
    assert store.now == now


def test_expiration_rejects_naive_time():
    naive_now = datetime.now(UTC).replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(expire_searching_photos(FakeStore(), now=naive_now))


def test_sql_expiration_creates_notification_in_same_commit():
    photo_id, user_id = uuid4(), uuid4()

    class Result:
        def all(self):
            return [(photo_id, user_id)]

    class Session:
        def __init__(self):
            self.added = []
            self.committed = False

        async def execute(self, statement):
            return Result()

        def add_all(self, values):
            self.added.extend(values)

        async def commit(self):
            self.committed = True

    session = Session()
    result = asyncio.run(
        expire_searching_photos(SqlExpirationStore(session), now=datetime.now(UTC))
    )

    assert result == [photo_id]
    assert session.committed is True
    assert len(session.added) == 1
    notification = session.added[0]
    assert isinstance(notification, Notification)
    assert notification.user_id == user_id
    assert notification.target_id == photo_id
    assert notification.type == "SEARCH_EXPIRED"
