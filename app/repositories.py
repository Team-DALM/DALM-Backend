from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Block, Match, MatchParticipant, Photo, Report, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_kakao_id(self, kakao_id: str) -> User | None:
        result = await self._session.execute(select(User).where(User.kakao_id == kakao_id))
        return result.scalar_one_or_none()

    async def create_from_kakao(self, kakao_id: str) -> User:
        user = User(kakao_id=kakao_id)
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = await self.get_by_kakao_id(kakao_id)
            if existing is None:
                raise
            return existing
        await self._session.refresh(user)
        return user

    async def get_by_apple_id(self, apple_id: str) -> User | None:
        result = await self._session.execute(select(User).where(User.apple_id == apple_id))
        return result.scalar_one_or_none()

    async def create_from_apple(self, apple_id: str) -> User:
        user = User(apple_id=apple_id)
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = await self.get_by_apple_id(apple_id)
            if existing is None:
                raise
            return existing
        await self._session.refresh(user)
        return user


@dataclass(frozen=True)
class MatchCardRow:
    match_id: UUID
    my_photo_id: UUID
    my_image_url: str
    partner_image_url: str
    ai_title: str | None
    matched_at: datetime


class HomeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_today_photo(self, user_id: UUID, today: date) -> Photo | None:
        result = await self._session.execute(
            select(Photo)
            .where(Photo.user_id == user_id, Photo.registered_date == today)
            .where(Photo.status != "DELETED")
            .order_by(Photo.registered_at.desc(), Photo.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_photo(self, photo_id: UUID) -> Photo | None:
        return await self._session.get(Photo, photo_id)

    async def delete_photo(self, user_id: UUID, photo_id: UUID) -> None:
        photo = await self.get_photo(photo_id)
        if photo is None or photo.status == "DELETED":
            raise ApiError(404, "PHOTO_NOT_FOUND", "사진을 찾을 수 없습니다.")
        if photo.user_id != user_id:
            raise ApiError(403, "PHOTO_NOT_OWNED", "본인의 사진만 삭제할 수 있습니다.")
        if photo.status not in {"SEARCHING", "EXPIRED"}:
            code = (
                "PHOTO_ALREADY_MATCHED" if photo.status == "MATCHED" else "PHOTO_DELETE_NOT_ALLOWED"
            )
            raise ApiError(409, code, "현재 상태에서는 사진을 삭제할 수 없습니다.")
        photo.status = "DELETED"
        photo.deleted_at = datetime.now(UTC)
        await self._session.commit()

    async def get_match_card_for_photo(self, user_id: UUID, photo_id: UUID) -> MatchCardRow | None:
        mine = MatchParticipant
        partner = MatchParticipant.__table__.alias("partner")
        partner_photo = Photo.__table__.alias("partner_photo")
        result = await self._session.execute(
            select(
                Match.id,
                Photo.id,
                Photo.image_url,
                partner_photo.c.image_url,
                Match.explanation,
                Match.matched_at,
            )
            .join(mine, mine.match_id == Match.id)
            .join(Photo, Photo.id == mine.photo_id)
            .join(
                partner,
                (partner.c.match_id == Match.id) & (partner.c.user_id != user_id),
            )
            .join(partner_photo, partner_photo.c.id == partner.c.photo_id)
            .where(mine.user_id == user_id, mine.photo_id == photo_id)
        )
        row = result.one_or_none()
        return MatchCardRow(*row) if row else None

    async def list_searching_photos(
        self,
        user_id: UUID,
        *,
        today: date,
        exclude_today: bool,
        size: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> list[Photo]:
        query = (
            select(Photo)
            .where(
                Photo.user_id == user_id,
                Photo.status == "SEARCHING",
                Photo.deleted_at.is_(None),
            )
            .order_by(Photo.registered_at.desc(), Photo.id.desc())
            .limit(size + 1)
        )
        if exclude_today:
            query = query.where(Photo.registered_date != today)
        if cursor:
            registered_at, photo_id = cursor
            query = query.where(
                (Photo.registered_at < registered_at)
                | ((Photo.registered_at == registered_at) & (Photo.id < photo_id))
            )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_next_unviewed_match(
        self, user_id: UUID, today: date
    ) -> tuple[MatchCardRow | None, int]:
        mine = MatchParticipant
        partner = MatchParticipant.__table__.alias("partner")
        partner_photo = Photo.__table__.alias("partner_photo")
        filters = (
            mine.user_id == user_id,
            mine.viewed_at.is_(None),
            mine.hidden_at.is_(None),
            Photo.registered_date != today,
            Photo.deleted_at.is_(None),
            partner_photo.c.deleted_at.is_(None),
            ~exists(
                select(Block.blocked_id).where(
                    or_(
                        and_(
                            Block.blocker_id == user_id,
                            Block.blocked_id == partner.c.user_id,
                        ),
                        and_(
                            Block.blocker_id == partner.c.user_id,
                            Block.blocked_id == user_id,
                        ),
                    )
                )
            ),
            ~exists(
                select(Report.id).where(
                    Report.reporter_id == user_id,
                    or_(
                        and_(
                            Report.target_type == "PHOTO",
                            Report.target_id == partner.c.photo_id,
                        ),
                        and_(
                            Report.target_type == "USER",
                            Report.target_id == partner.c.user_id,
                        ),
                    ),
                )
            ),
        )
        base = (
            select(
                Match.id,
                Photo.id,
                Photo.image_url,
                partner_photo.c.image_url,
                Match.explanation,
                Match.matched_at,
            )
            .join(mine, mine.match_id == Match.id)
            .join(Photo, Photo.id == mine.photo_id)
            .join(
                partner,
                (partner.c.match_id == Match.id) & (partner.c.user_id != user_id),
            )
            .join(partner_photo, partner_photo.c.id == partner.c.photo_id)
            .where(*filters)
        )
        row = (
            await self._session.execute(base.order_by(Match.matched_at.asc()).limit(1))
        ).one_or_none()
        count_query = (
            select(func.count(Match.id))
            .join(mine, mine.match_id == Match.id)
            .join(Photo, Photo.id == mine.photo_id)
            .join(
                partner,
                (partner.c.match_id == Match.id) & (partner.c.user_id != user_id),
            )
            .join(partner_photo, partner_photo.c.id == partner.c.photo_id)
            .where(*filters)
        )
        count = int((await self._session.execute(count_query)).scalar_one())
        return (MatchCardRow(*row) if row else None, count)

    async def mark_match_viewed(self, user_id: UUID, match_id: UUID) -> datetime | None:
        result = await self._session.execute(
            select(MatchParticipant).where(
                MatchParticipant.match_id == match_id,
                MatchParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()
        if participant is None:
            return None
        if participant.viewed_at is None:
            participant.viewed_at = datetime.now(UTC)
            await self._session.commit()
        return participant.viewed_at
