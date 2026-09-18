import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.matching import SqlMatchFinalizationStore, finalize_match
from app.models import Notification


class FakeStore:
    def __init__(self):
        self.call = None
        self.match_id = uuid4()

    async def finalize(self, first_photo_id, second_photo_id, **kwargs):
        self.call = (first_photo_id, second_photo_id, kwargs)
        return self.match_id


def test_finalize_match_orders_locks_and_normalizes_explanation():
    store = FakeStore()
    first, second = uuid4(), uuid4()
    now = datetime.now(UTC)

    result = asyncio.run(
        finalize_match(store, first, second, explanation="  빛과 구도가 닮았어요.  ", now=now)
    )

    assert result == store.match_id
    assert [str(store.call[0]), str(store.call[1])] == sorted((str(first), str(second)))
    assert store.call[2]["explanation"] == "빛과 구도가 닮았어요."
    assert store.call[2]["now"] == now


def test_finalize_match_rejects_same_photo():
    photo_id = uuid4()
    with pytest.raises(ApiError) as error:
        asyncio.run(finalize_match(FakeStore(), photo_id, photo_id, explanation="설명"))
    assert error.value.code == "SAME_PHOTO_MATCH"


def test_finalize_match_requires_explanation():
    with pytest.raises(ApiError) as error:
        asyncio.run(finalize_match(FakeStore(), uuid4(), uuid4(), explanation="   "))
    assert error.value.code == "MATCH_EXPLANATION_REQUIRED"


def test_sql_match_finalization_creates_notification_for_both_users():
    now = datetime.now(UTC)
    photos = [
        SimpleNamespace(
            id=uuid4(), user_id=uuid4(), status="SEARCHING", search_expires_at=now + timedelta(days=1)
        )
        for _ in range(2)
    ]

    class Result:
        def __init__(self, values=None, first=None):
            self.values = values or []
            self._first = first

        def scalars(self):
            return self.values

        def first(self):
            return self._first

    class Session:
        def __init__(self):
            self.results = [Result(photos), Result(first=None)]
            self.added = []

        async def execute(self, statement):
            return self.results.pop(0)

        def add(self, value):
            self.added.append(value)

        def add_all(self, values):
            self.added.extend(values)

        async def commit(self):
            pass

        async def rollback(self):
            pass

    session = Session()
    match_id = asyncio.run(
        finalize_match(
            SqlMatchFinalizationStore(session), photos[0].id, photos[1].id,
            explanation="닮은 장면", now=now,
        )
    )

    notifications = [value for value in session.added if isinstance(value, Notification)]
    assert len(notifications) == 2
    assert {item.user_id for item in notifications} == {photo.user_id for photo in photos}
    assert all(item.target_id == match_id and item.type == "MATCHED" for item in notifications)
