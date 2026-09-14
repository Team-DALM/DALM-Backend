from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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


@dataclass(frozen=True)
class MomentRow:
    photo_id: UUID
    image_url: str
    ai_title: str | None
    status: str
    registered_at: datetime
    search_expires_at: datetime | None
    match_id: UUID | None
    matched_at: datetime | None
    hidden: bool


@dataclass(frozen=True)
class MatchDetailRow:
    match_id: UUID
    my_photo_id: UUID
    my_image_url: str
    my_registered_at: datetime
    my_deleted: bool
    partner_photo_id: UUID
    partner_image_url: str
    partner_registered_at: datetime
    partner_deleted: bool
    partner_id: UUID
    partner_nickname: str
    explanation: str
    matched_at: datetime
    hidden: bool
    blocked: bool


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

    async def list_moments(
        self,
        user_id: UUID,
        *,
        status: str,
        today: date,
        exclude_today: bool,
        size: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> list[MomentRow]:
        participant = aliased(MatchParticipant)
        match = aliased(Match)
        query = (
            select(
                Photo.id,
                Photo.image_url,
                Photo.ai_title,
                Photo.status,
                Photo.registered_at,
                Photo.search_expires_at,
                participant.match_id,
                match.matched_at,
                participant.hidden_at,
            )
            .outerjoin(
                participant,
                and_(participant.photo_id == Photo.id, participant.user_id == user_id),
            )
            .outerjoin(match, match.id == participant.match_id)
            .where(Photo.user_id == user_id, Photo.deleted_at.is_(None))
            .order_by(Photo.registered_at.desc(), Photo.id.desc())
            .limit(size + 1)
        )
        if status == "HIDDEN":
            query = query.where(participant.hidden_at.is_not(None))
        elif status != "ALL":
            query = query.where(Photo.status == status, participant.hidden_at.is_(None))
        else:
            query = query.where(participant.hidden_at.is_(None))
        if exclude_today:
            query = query.where(Photo.registered_date != today)
        if cursor:
            registered_at, photo_id = cursor
            query = query.where(
                (Photo.registered_at < registered_at)
                | ((Photo.registered_at == registered_at) & (Photo.id < photo_id))
            )
        return [
            MomentRow(*row[:-1], hidden=row[-1] is not None)
            for row in (await self._session.execute(query)).all()
        ]

    async def get_match_detail(self, user_id: UUID, match_id: UUID) -> MatchDetailRow | None:
        mine = aliased(MatchParticipant)
        partner = aliased(MatchParticipant)
        my_photo = aliased(Photo)
        partner_photo = aliased(Photo)
        partner_user = aliased(User)
        row = (
            await self._session.execute(
                select(
                    Match.id,
                    my_photo.id,
                    my_photo.image_url,
                    my_photo.registered_at,
                    my_photo.deleted_at,
                    partner_photo.id,
                    partner_photo.image_url,
                    partner_photo.registered_at,
                    partner_photo.deleted_at,
                    partner_user.id,
                    partner_user.nickname,
                    Match.explanation,
                    Match.matched_at,
                    mine.hidden_at,
                    exists(
                        select(Block.blocker_id).where(
                            or_(
                                and_(
                                    Block.blocker_id == user_id, Block.blocked_id == partner.user_id
                                ),
                                and_(
                                    Block.blocker_id == partner.user_id, Block.blocked_id == user_id
                                ),
                            )
                        )
                    ),
                )
                .join(mine, and_(mine.match_id == Match.id, mine.user_id == user_id))
                .join(partner, and_(partner.match_id == Match.id, partner.user_id != user_id))
                .join(my_photo, my_photo.id == mine.photo_id)
                .join(partner_photo, partner_photo.id == partner.photo_id)
                .join(partner_user, partner_user.id == partner.user_id)
                .where(Match.id == match_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return MatchDetailRow(
            match_id=row[0],
            my_photo_id=row[1],
            my_image_url=row[2],
            my_registered_at=row[3],
            my_deleted=row[4] is not None,
            partner_photo_id=row[5],
            partner_image_url=row[6],
            partner_registered_at=row[7],
            partner_deleted=row[8] is not None,
            partner_id=row[9],
            partner_nickname=row[10] or "알 수 없는 사용자",
            explanation=row[11],
            matched_at=row[12],
            hidden=row[13] is not None,
            blocked=bool(row[14]),
        )

    async def update_match_visibility(
        self, user_id: UUID, match_id: UUID, *, hidden: bool
    ) -> bool | None:
        participant = (
            await self._session.execute(
                select(MatchParticipant).where(
                    MatchParticipant.match_id == match_id,
                    MatchParticipant.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if participant is None:
            return None
        participant.hidden_at = datetime.now(UTC) if hidden else None
        await self._session.commit()
        return hidden

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
