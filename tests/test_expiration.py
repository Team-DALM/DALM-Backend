import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.expiration import expire_searching_photos


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
