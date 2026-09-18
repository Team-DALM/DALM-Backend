from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, Photo
from app.notifications import TEMPLATES


class ExpirationStore(Protocol):
    async def expire_due(self, now: datetime) -> list[UUID]: ...


class SqlExpirationStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def expire_due(self, now: datetime) -> list[UUID]:
        result = await self._session.execute(
            update(Photo)
            .where(
                Photo.status == "SEARCHING",
                Photo.search_expires_at.is_not(None),
                Photo.search_expires_at <= now,
                Photo.deleted_at.is_(None),
            )
            .values(status="EXPIRED")
            .returning(Photo.id, Photo.user_id)
        )
        rows = list(result.all())
        template = TEMPLATES["SEARCH_EXPIRED"]
        self._session.add_all(
            Notification(
                user_id=user_id,
                type="SEARCH_EXPIRED",
                title=template.title,
                message=template.message,
                target_type=template.target_type,
                target_id=photo_id,
            )
            for photo_id, user_id in rows
        )
        await self._session.commit()
        return [photo_id for photo_id, _ in rows]


async def expire_searching_photos(
    store: ExpirationStore, *, now: datetime | None = None
) -> list[UUID]:
    effective_now = now or datetime.now(UTC)
    if effective_now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return await store.expire_due(effective_now)
