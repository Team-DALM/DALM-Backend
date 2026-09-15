from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        reporter_id: UUID,
        target_type: str,
        target_id: UUID,
        reason_code: str,
        detail: str | None,
    ) -> Report:
        if target_type == "USER":
            if target_id == reporter_id:
                raise ApiError(422, "CANNOT_REPORT_SELF", "본인은 신고할 수 없습니다.")
            exists_target = (
                await self._session.execute(
                    select(User.id).where(User.id == target_id, User.status != "WITHDRAWN")
                )
            ).scalar_one_or_none()
        elif target_type == "PHOTO":
            exists_target = (
                await self._session.execute(
                    select(Photo.id).where(Photo.id == target_id, Photo.deleted_at.is_(None))
                )
            ).scalar_one_or_none()
        else:
            raise ApiError(
                422,
                "POSTCARD_REPORT_NOT_AVAILABLE",
                "엽서 기능이 준비된 후 엽서를 신고할 수 있습니다.",
            )
        if exists_target is None:
            raise ApiError(404, "REPORT_TARGET_NOT_FOUND", "신고 대상을 찾을 수 없습니다.")

        report = Report(
            reporter_id=reporter_id,
            target_type=target_type,
            target_id=target_id,
            reason_code=reason_code,
            detail=detail,
            status="PENDING",
        )
        self._session.add(report)
        if target_type == "USER":
            already_blocked = await self._session.get(Block, (reporter_id, target_id))
            if already_blocked is None:
                self._session.add(Block(blocker_id=reporter_id, blocked_id=target_id))
        else:
            target_participant = aliased(MatchParticipant)
            participant = (
                await self._session.execute(
                    select(MatchParticipant)
                    .join(
                        target_participant,
                        target_participant.match_id == MatchParticipant.match_id,
                    )
                    .where(
                        MatchParticipant.user_id == reporter_id,
                        target_participant.photo_id == target_id,
                    )
                )
            ).scalars().first()
            if participant is not None:
                participant.hidden_at = datetime.now(UTC)
                
@dataclass(frozen=True)
class BlockedUserRow:
    user_id: UUID
    nickname: str
    profile_image_url: str | None
    blocked_at: datetime


class SafetyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_blocks(
        self,
        blocker_id: UUID,
        *,
        size: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> list[BlockedUserRow]:
        query = (
            select(Block.blocked_id, User.nickname, Block.created_at)
            .join(User, User.id == Block.blocked_id)
            .where(Block.blocker_id == blocker_id, User.status != "WITHDRAWN")
            .order_by(Block.created_at.desc(), Block.blocked_id.desc())
            .limit(size + 1)
        )
        if cursor:
            blocked_at, user_id = cursor
            query = query.where(
                (Block.created_at < blocked_at)
                | ((Block.created_at == blocked_at) & (Block.blocked_id < user_id))
            )
        rows = (await self._session.execute(query)).all()
        return [BlockedUserRow(row[0], row[1] or "알 수 없는 사용자", None, row[2]) for row in rows]

    async def block(self, blocker_id: UUID, blocked_id: UUID) -> None:
        if blocker_id == blocked_id:
            raise ApiError(409, "CANNOT_BLOCK_SELF", "본인은 차단할 수 없습니다.")
        target = (
            await self._session.execute(
                select(User.id).where(User.id == blocked_id, User.status != "WITHDRAWN")
            )
        ).scalar_one_or_none()
        if target is None:
            raise ApiError(404, "USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
        self._session.add(Block(blocker_id=blocker_id, blocked_id=blocked_id))
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ApiError(409, "REPORT_ALREADY_EXISTS", "이미 접수한 신고입니다.") from exc
        await self._session.refresh(report)
        return report
            raise ApiError(409, "USER_ALREADY_BLOCKED", "이미 차단한 사용자입니다.") from exc

    async def unblock(self, blocker_id: UUID, blocked_id: UUID) -> None:
        await self._session.execute(
            delete(Block).where(Block.blocker_id == blocker_id, Block.blocked_id == blocked_id)
        )
        await self._session.commit()

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
