from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.errors import ApiError
from app.models import (
    Block,
    DeviceToken,
    Match,
    MatchParticipant,
    Notification,
    NotificationSetting,
    Photo,
    Postcard,
    Report,
    User,
    UserTerm,
)


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

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def complete_onboarding(
        self,
        user_id: UUID,
        *,
        nickname: str,
        bio: str | None,
        marketing_agreed: bool,
        service_terms_version: str,
        privacy_policy_version: str,
    ) -> User:
        user = await self.get_by_id(user_id)
        if user is None or user.status == "WITHDRAWN":
            raise ApiError(404, "USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
        if not user.onboarding_required:
            raise ApiError(409, "ONBOARDING_ALREADY_COMPLETED", "이미 온보딩을 완료했습니다.")
        user.nickname = nickname
        user.bio = bio
        user.marketing_agreed = marketing_agreed
        terms = (
            ("SERVICE", service_terms_version, True),
            ("PRIVACY", privacy_policy_version, True),
            ("AGE_14", "1", True),
            ("MARKETING", "1", marketing_agreed),
        )
        self._session.add_all(
            UserTerm(user_id=user_id, term_type=kind, term_version=version, agreed=agreed)
            for kind, version, agreed in terms
        )
        await self._commit_profile_change()
        await self._session.refresh(user)
        return user

    async def update_profile(
        self, user_id: UUID, *, nickname: str | None, bio: str | None, update_bio: bool
    ) -> User:
        user = await self.get_by_id(user_id)
        if user is None or user.status == "WITHDRAWN":
            raise ApiError(404, "USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
        if user.onboarding_required:
            raise ApiError(409, "ONBOARDING_REQUIRED", "온보딩을 먼저 완료해주세요.")
        if nickname is not None:
            user.nickname = nickname
        if update_bio:
            user.bio = bio
        await self._commit_profile_change()
        await self._session.refresh(user)
        return user

    async def withdraw(self, user_id: UUID) -> None:
        user = await self.get_by_id(user_id)
        if user is None or user.status == "WITHDRAWN":
            raise ApiError(404, "USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
        user.status = "WITHDRAWN"
        user.nickname = None
        user.bio = None
        user.profile_image_key = None
        user.withdrawn_at = datetime.now(UTC)
        await self._session.commit()

    async def get_stats(self, user_id: UUID) -> tuple[int, int, int]:
        photo_count = int(
            (
                await self._session.execute(
                    select(func.count(Photo.id)).where(
                        Photo.user_id == user_id, Photo.status != "DELETED"
                    )
                )
            ).scalar_one()
        )
        match_count = int(
            (
                await self._session.execute(
                    select(func.count(MatchParticipant.match_id)).where(
                        MatchParticipant.user_id == user_id,
                        MatchParticipant.hidden_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        return photo_count, match_count, 0

    async def _commit_profile_change(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ApiError(409, "NICKNAME_CONFLICT", "이미 사용 중인 닉네임입니다.") from exc


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
    postcard_permission: str | None


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
    postcard_permission: str


def resolve_postcard_permission(
    *,
    blocked: bool,
    sent_by_user: bool,
    user_is_first_sender: bool,
    first_sender_has_sent: bool,
) -> str:
    if blocked:
        return "BLOCKED"
    if sent_by_user:
        return "ALREADY_SENT"
    if not user_is_first_sender and not first_sender_has_sent:
        return "WAITING_FOR_FIRST"
    return "CAN_SEND"


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
                (
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
                )
                .scalars()
                .first()
            )
            if participant is not None:
                participant.hidden_at = datetime.now(UTC)

        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ApiError(409, "REPORT_ALREADY_EXISTS", "이미 접수한 신고입니다.") from exc
        await self._session.refresh(report)
        return report


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
            raise ApiError(409, "USER_ALREADY_BLOCKED", "이미 차단한 사용자입니다.") from exc

    async def unblock(self, blocker_id: UUID, blocked_id: UUID) -> None:
        await self._session.execute(
            delete(Block).where(Block.blocker_id == blocker_id, Block.blocked_id == blocked_id)
        )
        await self._session.commit()


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: UUID,
        type: str,
        title: str,
        message: str,
        target_type: str | None,
        target_id: UUID | None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            target_type=target_type,
            target_id=target_id,
        )
        self._session.add(notification)
        await self._session.commit()
        await self._session.refresh(notification)
        return notification

    async def list(
        self,
        user_id: UUID,
        *,
        unread_only: bool,
        size: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> tuple[list[Notification], int]:
        filters = [Notification.user_id == user_id, Notification.deleted_at.is_(None)]
        if unread_only:
            filters.append(Notification.read_at.is_(None))
        query = (
            select(Notification)
            .where(*filters)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(size + 1)
        )
        if cursor:
            created_at, notification_id = cursor
            query = query.where(
                (Notification.created_at < created_at)
                | ((Notification.created_at == created_at) & (Notification.id < notification_id))
            )
        items = list((await self._session.execute(query)).scalars().all())
        unread_count = int(
            (
                await self._session.execute(
                    select(func.count(Notification.id)).where(
                        Notification.user_id == user_id,
                        Notification.deleted_at.is_(None),
                        Notification.read_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        return items, unread_count

    async def mark_read(self, user_id: UUID, notification_id: UUID) -> Notification:
        notification = (
            await self._session.execute(
                select(Notification).where(
                    Notification.id == notification_id,
                    Notification.user_id == user_id,
                    Notification.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if notification is None:
            raise ApiError(404, "NOTIFICATION_NOT_FOUND", "알림을 찾을 수 없습니다.")
        if notification.read_at is None:
            notification.read_at = datetime.now(UTC)
            await self._session.commit()
        return notification

    async def mark_all_read(self, user_id: UUID) -> None:
        await self._session.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.deleted_at.is_(None),
                Notification.read_at.is_(None),
            )
            .values(read_at=datetime.now(UTC))
        )
        await self._session.commit()


@dataclass(frozen=True)
class PostcardRow:
    id: UUID
    match_id: UUID
    sender_id: UUID
    sender_nickname: str
    receiver_id: UUID
    receiver_nickname: str
    content: str
    read_at: datetime | None
    sent_at: datetime
    moment_thumbnail_url: str


class PostcardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _row_query(self, user_id: UUID):
        sender = aliased(User)
        receiver = aliased(User)
        viewer_participant = aliased(MatchParticipant)
        viewer_photo = aliased(Photo)
        return (
            select(
                Postcard.id,
                Postcard.match_id,
                Postcard.sender_id,
                sender.nickname,
                Postcard.receiver_id,
                receiver.nickname,
                Postcard.content,
                Postcard.read_at,
                Postcard.sent_at,
                viewer_photo.image_url,
            )
            .join(sender, sender.id == Postcard.sender_id)
            .join(receiver, receiver.id == Postcard.receiver_id)
            .join(
                viewer_participant,
                and_(
                    viewer_participant.match_id == Postcard.match_id,
                    viewer_participant.user_id == user_id,
                ),
            )
            .join(viewer_photo, viewer_photo.id == viewer_participant.photo_id)
        )

    async def send(
        self, user_id: UUID, match_id: UUID, content: str, idempotency_key: UUID | None
    ) -> PostcardRow:
        if idempotency_key is not None:
            existing_id = (
                await self._session.execute(
                    select(Postcard.id).where(
                        Postcard.sender_id == user_id,
                        Postcard.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one_or_none()
            if existing_id is not None:
                return await self.get(user_id, existing_id)
        participants = list(
            (
                await self._session.execute(
                    select(MatchParticipant, Photo)
                    .join(Photo, Photo.id == MatchParticipant.photo_id)
                    .where(MatchParticipant.match_id == match_id)
                    .order_by(Photo.registered_at.asc(), Photo.id.asc())
                    .with_for_update()
                )
            ).all()
        )
        if len(participants) != 2 or user_id not in {row[0].user_id for row in participants}:
            raise ApiError(404, "MATCH_NOT_FOUND", "매칭을 찾을 수 없습니다.")
        first_id = participants[0][0].user_id
        receiver_id = next(row[0].user_id for row in participants if row[0].user_id != user_id)
        blocked = (
            await self._session.execute(
                select(Block.blocker_id).where(
                    or_(
                        and_(Block.blocker_id == user_id, Block.blocked_id == receiver_id),
                        and_(Block.blocker_id == receiver_id, Block.blocked_id == user_id),
                    )
                )
            )
        ).first()
        if blocked:
            raise ApiError(409, "USER_BLOCKED", "차단 관계에서는 엽서를 보낼 수 없습니다.")
        if user_id != first_id:
            first_sent = (
                await self._session.execute(
                    select(Postcard.id).where(
                        Postcard.match_id == match_id, Postcard.sender_id == first_id
                    )
                )
            ).scalar_one_or_none()
            if first_sent is None:
                raise ApiError(409, "POSTCARD_ORDER_NOT_ALLOWED", "첫 엽서를 기다리고 있습니다.")
        postcard = Postcard(
            match_id=match_id,
            sender_id=user_id,
            receiver_id=receiver_id,
            content=content,
            idempotency_key=idempotency_key,
        )
        self._session.add(postcard)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ApiError(409, "POSTCARD_ALREADY_SENT", "이미 엽서를 보냈습니다.") from exc
        return await self.get(user_id, postcard.id)

    async def list(
        self, user_id: UUID, *, mailbox: str, size: int, cursor: tuple[datetime, UUID] | None
    ) -> list[PostcardRow]:
        owner = Postcard.receiver_id if mailbox == "received" else Postcard.sender_id
        deleted = (
            Postcard.receiver_deleted_at if mailbox == "received" else Postcard.sender_deleted_at
        )
        query = (
            self._row_query(user_id)
            .where(owner == user_id, deleted.is_(None))
            .order_by(Postcard.sent_at.desc(), Postcard.id.desc())
            .limit(size + 1)
        )
        if cursor:
            sent_at, postcard_id = cursor
            query = query.where(
                (Postcard.sent_at < sent_at)
                | ((Postcard.sent_at == sent_at) & (Postcard.id < postcard_id))
            )
        return [PostcardRow(*row) for row in (await self._session.execute(query)).all()]

    async def get(self, user_id: UUID, postcard_id: UUID) -> PostcardRow:
        row = (
            await self._session.execute(
                self._row_query(user_id).where(
                    Postcard.id == postcard_id,
                    or_(
                        and_(Postcard.sender_id == user_id, Postcard.sender_deleted_at.is_(None)),
                        and_(
                            Postcard.receiver_id == user_id, Postcard.receiver_deleted_at.is_(None)
                        ),
                    ),
                )
            )
        ).first()
        if row is None:
            raise ApiError(404, "POSTCARD_NOT_FOUND", "엽서를 찾을 수 없습니다.")
        return PostcardRow(*row)

    async def mark_read(self, user_id: UUID, postcard_id: UUID) -> PostcardRow:
        postcard = await self._session.get(Postcard, postcard_id)
        if postcard is None or postcard.receiver_id != user_id or postcard.receiver_deleted_at:
            raise ApiError(404, "POSTCARD_NOT_FOUND", "엽서를 찾을 수 없습니다.")
        if postcard.read_at is None:
            postcard.read_at = datetime.now(UTC)
            await self._session.commit()
        return await self.get(user_id, postcard_id)

    async def delete(self, user_id: UUID, postcard_id: UUID) -> None:
        postcard = await self._session.get(Postcard, postcard_id)
        if postcard is None:
            raise ApiError(404, "POSTCARD_NOT_FOUND", "엽서를 찾을 수 없습니다.")
        now = datetime.now(UTC)
        if postcard.sender_id == user_id and postcard.sender_deleted_at is None:
            postcard.sender_deleted_at = now
        elif postcard.receiver_id == user_id and postcard.receiver_deleted_at is None:
            postcard.receiver_deleted_at = now
        else:
            raise ApiError(404, "POSTCARD_NOT_FOUND", "엽서를 찾을 수 없습니다.")
        await self._session.commit()


class NotificationPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_device(self, user_id: UUID, token: str, platform: str) -> None:
        item = (
            await self._session.execute(select(DeviceToken).where(DeviceToken.token == token))
        ).scalar_one_or_none()
        if item is None:
            item = DeviceToken(user_id=user_id, token=token, platform=platform)
            self._session.add(item)
        else:
            item.user_id = user_id
            item.platform = platform
            item.last_used_at = datetime.now(UTC)
        await self._session.commit()

    async def get_settings(self, user_id: UUID) -> NotificationSetting:
        settings = await self._session.get(NotificationSetting, user_id)
        if settings is None:
            settings = NotificationSetting(user_id=user_id)
            self._session.add(settings)
            await self._session.commit()
            await self._session.refresh(settings)
        return settings

    async def update_settings(self, user_id: UUID, values: dict[str, bool]) -> NotificationSetting:
        settings = await self.get_settings(user_id)
        for name, value in values.items():
            setattr(settings, name, value)
        await self._session.commit()
        return settings


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

    async def create_photo(
        self,
        *,
        photo_id: UUID,
        user_id: UUID,
        image_url: str,
        storage_key: str,
        checksum: str,
        registered_date: date,
    ) -> Photo:
        user = await self._session.get(User, user_id)
        if user is None or user.status != "ACTIVE":
            raise ApiError(
                403, "ACCOUNT_NOT_ACTIVE", "활성 상태의 사용자만 사진을 등록할 수 있습니다."
            )
        if user.onboarding_required:
            raise ApiError(409, "ONBOARDING_REQUIRED", "온보딩을 먼저 완료해주세요.")

        active_photo = (
            await self._session.execute(
                select(Photo.id).where(
                    Photo.user_id == user_id,
                    Photo.registered_date == registered_date,
                    Photo.status.in_({"VALIDATING", "SEARCHING", "MATCHED", "EXPIRED"}),
                )
            )
        ).scalar_one_or_none()
        if active_photo is not None:
            raise ApiError(409, "TODAY_PHOTO_ALREADY_EXISTS", "오늘 등록한 사진이 이미 있습니다.")
        duplicate = (
            await self._session.execute(
                select(Photo.id).where(Photo.user_id == user_id, Photo.checksum == checksum)
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ApiError(409, "DUPLICATE_PHOTO", "이미 등록한 사진입니다.")

        photo = Photo(
            id=photo_id,
            user_id=user_id,
            image_url=image_url,
            storage_key=storage_key,
            checksum=checksum,
            status="VALIDATING",
            registered_date=registered_date,
        )
        self._session.add(photo)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ApiError(
                409, "PHOTO_CONFLICT", "사진을 등록할 수 없습니다. 다시 확인해주세요."
            ) from exc
        await self._session.refresh(photo)
        return photo

    async def can_access_photo(self, user_id: UUID, photo_id: UUID) -> bool:
        owned = (
            await self._session.execute(
                select(Photo.id).where(
                    Photo.id == photo_id,
                    Photo.user_id == user_id,
                    Photo.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if owned is not None:
            return True
        target_participant = aliased(MatchParticipant)
        viewer_participant = aliased(MatchParticipant)
        shared_match = (
            await self._session.execute(
                select(target_participant.match_id)
                .join(
                    viewer_participant,
                    viewer_participant.match_id == target_participant.match_id,
                )
                .where(
                    target_participant.photo_id == photo_id,
                    viewer_participant.user_id == user_id,
                )
            )
        ).first()
        return shared_match is not None

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
        partner = aliased(MatchParticipant)
        partner_photo = aliased(Photo)
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
                partner_photo.registered_at,
                partner_photo.id,
                exists(
                    select(Block.blocker_id).where(
                        or_(
                            and_(Block.blocker_id == user_id, Block.blocked_id == partner.user_id),
                            and_(Block.blocker_id == partner.user_id, Block.blocked_id == user_id),
                        )
                    )
                ),
                exists(
                    select(Postcard.id).where(
                        Postcard.match_id == participant.match_id,
                        Postcard.sender_id == user_id,
                    )
                ),
                exists(select(Postcard.id).where(Postcard.match_id == participant.match_id)),
            )
            .outerjoin(
                participant,
                and_(participant.photo_id == Photo.id, participant.user_id == user_id),
            )
            .outerjoin(
                partner,
                and_(
                    partner.match_id == participant.match_id,
                    partner.user_id != user_id,
                ),
            )
            .outerjoin(partner_photo, partner_photo.id == partner.photo_id)
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
        rows = (await self._session.execute(query)).all()
        return [
            MomentRow(
                photo_id=row[0],
                image_url=row[1],
                ai_title=row[2],
                status=row[3],
                registered_at=row[4],
                search_expires_at=row[5],
                match_id=row[6],
                matched_at=row[7],
                hidden=row[8] is not None,
                postcard_permission=(
                    resolve_postcard_permission(
                        blocked=bool(row[11]),
                        sent_by_user=bool(row[12]),
                        user_is_first_sender=(row[4], row[0]) <= (row[9], row[10]),
                        first_sender_has_sent=bool(row[13]),
                    )
                    if row[3] == "MATCHED" and row[6] is not None
                    else None
                ),
            )
            for row in rows
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
                    exists(
                        select(Postcard.id).where(
                            Postcard.match_id == Match.id,
                            Postcard.sender_id == user_id,
                        )
                    ),
                    exists(select(Postcard.id).where(Postcard.match_id == Match.id)),
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
            postcard_permission=resolve_postcard_permission(
                blocked=bool(row[14]),
                sent_by_user=bool(row[15]),
                user_is_first_sender=(row[3], row[1]) <= (row[7], row[5]),
                first_sender_has_sent=bool(row[16]),
            ),
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
