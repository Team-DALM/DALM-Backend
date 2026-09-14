import asyncio
from uuid import uuid4

from app.notifications import create_event_notification


class FakeWriter:
    def __init__(self): self.values = None
    async def create(self, **values):
        self.values = values
        return values


def test_match_event_builds_consistent_notification():
    writer = FakeWriter()
    user_id, match_id = uuid4(), uuid4()

    result = asyncio.run(create_event_notification(
        writer, user_id=user_id, type="MATCHED", target_id=match_id
    ))

    assert result["user_id"] == user_id
    assert result["target_type"] == "MATCH"
    assert result["target_id"] == match_id
    assert "닮은 순간" in result["title"]


def test_system_event_accepts_custom_message():
    writer = FakeWriter()
    result = asyncio.run(create_event_notification(
        writer, user_id=uuid4(), type="SYSTEM", message="신고 처리가 완료되었습니다."
    ))
    assert result["message"] == "신고 처리가 완료되었습니다."
    assert result["target_id"] is None
