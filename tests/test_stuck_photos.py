import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.errors import ApiError
from app.repositories import HomeRepository


@pytest.mark.parametrize("status", ["VALIDATING", "REJECTED", "SEARCHING", "EXPIRED"])
def test_owner_can_delete_unmatched_photo(status):
    user_id = uuid4()
    photo = SimpleNamespace(id=uuid4(), user_id=user_id, status=status, deleted_at=None)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: photo)),
        commit=AsyncMock(),
    )
    asyncio.run(HomeRepository(session).delete_photo(user_id, photo.id))
    assert photo.status == "DELETED"
    assert photo.deleted_at is not None
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("owned,status", [(False, "VALIDATING"), (True, "MATCHED")])
def test_delete_preserves_ownership_and_matched_photo(owned, status):
    user_id = uuid4()
    photo = SimpleNamespace(
        id=uuid4(), user_id=user_id if owned else uuid4(), status=status, deleted_at=None
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: photo)),
        commit=AsyncMock(),
    )
    with pytest.raises(ApiError):
        asyncio.run(HomeRepository(session).delete_photo(user_id, photo.id))
    assert photo.status == status
    session.commit.assert_not_awaited()


def test_stale_recovery_is_scoped_and_conditional():
    user_id = uuid4()
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)), commit=AsyncMock()
    )
    before = datetime.now(UTC)
    asyncio.run(HomeRepository(session).expire_stale_validations(user_id))
    statement = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    params = statement.params
    assert params["user_id_1"] == user_id
    assert params["status_1"] == "VALIDATING"
    assert params["status"] == "REJECTED"
    assert 899 <= (before - params["registered_at_1"]).total_seconds() <= 901
    session.commit.assert_awaited_once()
