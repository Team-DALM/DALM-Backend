from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    WITHDRAWN = "WITHDRAWN"


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    kakao_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    apple_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(12), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=UserStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def onboarding_required(self) -> bool:
        return self.nickname is None


class PhotoStatus(StrEnum):
    VALIDATING = "VALIDATING"
    REJECTED = "REJECTED"
    SEARCHING = "SEARCHING"
    MATCHED = "MATCHED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    image_url: Mapped[str] = mapped_column(String(2048))
    ai_title: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), index=True)
    registered_date: Mapped[date] = mapped_column(Date, index=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    search_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_code: Mapped[str | None] = mapped_column(String(50))
    rejection_message: Mapped[str | None] = mapped_column(String(200))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    explanation: Mapped[str] = mapped_column(Text)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MatchParticipant(Base):
    __tablename__ = "match_participants"
    __table_args__ = (UniqueConstraint("photo_id"),)

    match_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("matches.id"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True, index=True
    )
    photo_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("photos.id"), nullable=False
    )
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Block(Base):
    __tablename__ = "blocks"

    blocker_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    blocked_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    reporter_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), index=True)
    reason_code: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
