import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.matching import finalize_match


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
