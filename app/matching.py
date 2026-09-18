from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Block, Match, MatchParticipant, Notification, Photo
from app.notifications import TEMPLATES


class MatchFinalizationStore(Protocol):
    async def finalize(
        self,
        first_photo_id: UUID,
        second_photo_id: UUID,
        *,
        explanation: str,
        now: datetime,
    ) -> UUID: ...


class SqlMatchFinalizationStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def finalize(
        self,
        first_photo_id: UUID,
        second_photo_id: UUID,
        *,
        explanation: str,
        now: datetime,
    ) -> UUID:
        ordered_ids = sorted((first_photo_id, second_photo_id), key=str)
        try:
            photos = list(
                (
                    await self._session.execute(
                        select(Photo)
                        .where(Photo.id.in_(ordered_ids))
                        .order_by(Photo.id.asc())
                        .with_for_update()
                    )
                ).scalars()
            )
            if len(photos) != 2:
                raise ApiError(404, "MATCH_PHOTO_NOT_FOUND", "매칭할 사진을 찾을 수 없습니다.")
            if photos[0].user_id == photos[1].user_id:
                raise ApiError(409, "SAME_USER_MATCH", "같은 사용자의 사진은 매칭할 수 없습니다.")
            if any(photo.status != "SEARCHING" for photo in photos):
                raise ApiError(409, "MATCH_CANDIDATE_CHANGED", "사진이 더 이상 매칭 대기 상태가 아닙니다.")
            if any(
                photo.search_expires_at is None or photo.search_expires_at <= now
                for photo in photos
            ):
                raise ApiError(409, "SEARCH_PERIOD_EXPIRED", "사진의 탐색 기간이 종료되었습니다.")
            first_user_id, second_user_id = photos[0].user_id, photos[1].user_id
            blocked = (
                await self._session.execute(
                    select(Block.blocker_id).where(
                        or_(
                            and_(
                                Block.blocker_id == first_user_id,
                                Block.blocked_id == second_user_id,
                            ),
                            and_(
                                Block.blocker_id == second_user_id,
                                Block.blocked_id == first_user_id,
                            ),
                        )
                    )
                )
            ).first()
            if blocked:
                raise ApiError(409, "USER_BLOCKED", "차단 관계의 사용자는 매칭할 수 없습니다.")

            match_id = uuid4()
            self._session.add(Match(id=match_id, explanation=explanation))
            self._session.add_all(
                MatchParticipant(match_id=match_id, user_id=photo.user_id, photo_id=photo.id)
                for photo in photos
            )
            for photo in photos:
                photo.status = "MATCHED"
                template = TEMPLATES["MATCHED"]
                self._session.add(
                    Notification(
                        user_id=photo.user_id,
                        type="MATCHED",
                        title=template.title,
                        message=template.message,
                        target_type=template.target_type,
                        target_id=match_id,
                    )
                )
            await self._session.commit()
            return match_id
        except (ApiError, SQLAlchemyError):
            await self._session.rollback()
            raise


async def finalize_match(
    store: MatchFinalizationStore,
    first_photo_id: UUID,
    second_photo_id: UUID,
    *,
    explanation: str,
    now: datetime | None = None,
) -> UUID:
    if first_photo_id == second_photo_id:
        raise ApiError(409, "SAME_PHOTO_MATCH", "같은 사진끼리는 매칭할 수 없습니다.")
    normalized_explanation = explanation.strip()
    if not normalized_explanation:
        raise ApiError(422, "MATCH_EXPLANATION_REQUIRED", "매칭 설명이 필요합니다.")
    effective_now = now or datetime.now(UTC)
    if effective_now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    ordered_ids = sorted((first_photo_id, second_photo_id), key=str)
    return await store.finalize(
        ordered_ids[0],
        ordered_ids[1],
        explanation=normalized_explanation,
        now=effective_now,
    )
