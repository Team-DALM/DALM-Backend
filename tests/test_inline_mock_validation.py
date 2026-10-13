import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.models import Notification, Photo, PhotoEmbeddingJob, PhotoValidation
from app.repositories import HomeRepository


@pytest.mark.parametrize("mock_passed", [True, False])
def test_upload_commits_matching_photo_and_validation_statuses(mock_passed):
    now = datetime.now(UTC)
    user_id, photo_id = uuid4(), uuid4()
    result = SimpleNamespace(rowcount=0, scalar_one_or_none=lambda: None)
    session = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(status="ACTIVE", onboarding_required=False)),
        execute=AsyncMock(return_value=result), add=Mock(), commit=AsyncMock(), refresh=AsyncMock(),
    )
    photo = asyncio.run(HomeRepository(session).create_photo(
        photo_id=photo_id, user_id=user_id, image_url="/image", storage_key="photos/test.webp",
        checksum="unique-checksum", registered_date=now.date(), mock_passed=mock_passed,
    ))
    added = [call.args[0] for call in session.add.call_args_list]
    validation = next(item for item in added if isinstance(item, PhotoValidation))
    assert isinstance(photo, Photo)
    assert photo in added
    session.commit.assert_awaited_once()
    if mock_passed:
        assert photo.status == "SEARCHING"
        assert (photo.search_expires_at - photo.registered_at).days == 7
        assert validation.status == "PASSED"
        assert validation.model_name == "dalm-mock-validator"
        assert validation.completed_at is not None
        assert any(isinstance(item, PhotoEmbeddingJob) for item in added)
        assert any(isinstance(item, Notification) and item.type == "VALIDATION_PASSED" for item in added)
    else:
        assert photo.status == "VALIDATING"
        assert photo.search_expires_at is None
        assert validation.status == "PENDING"
        assert not any(isinstance(item, PhotoEmbeddingJob) for item in added)
