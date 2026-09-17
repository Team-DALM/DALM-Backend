from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    profile_image_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(100), nullable=True)
    marketing_agreed: Mapped[bool] = mapped_column(Boolean, default=False)
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


class UserTerm(Base):
    __tablename__ = "user_terms"
    __table_args__ = (UniqueConstraint("user_id", "term_type", "term_version"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    term_type: Mapped[str] = mapped_column(String(30))
    term_version: Mapped[str] = mapped_column(String(20))
    agreed: Mapped[bool] = mapped_column(Boolean)
    agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PhotoStatus(StrEnum):
    VALIDATING = "VALIDATING"
    REJECTED = "REJECTED"
    SEARCHING = "SEARCHING"
    MATCHED = "MATCHED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class Photo(Base):
    __tablename__ = "photos"
    __table_args__ = (UniqueConstraint("user_id", "checksum"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    image_url: Mapped[str] = mapped_column(String(2048))
    storage_key: Mapped[str | None] = mapped_column(String(500), unique=True)
    checksum: Mapped[str | None] = mapped_column(String(64))
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


class PhotoValidation(Base):
    __tablename__ = "photo_validations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'PASSED', 'REJECTED', 'FAILED')",
            name="photo_validations_status_ck",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    photo_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("photos.id"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    scores: Mapped[dict[str, float] | None] = mapped_column(JSON)
    rejection_code: Mapped[str | None] = mapped_column(String(50))
    model_name: Mapped[str | None] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(50))
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(500))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(String(500))
    target_type: Mapped[str | None] = mapped_column(String(20))
    target_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Postcard(Base):
    __tablename__ = "postcards"
    __table_args__ = (
        UniqueConstraint("match_id", "sender_id"),
        UniqueConstraint("sender_id", "idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    match_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("matches.id"))
    sender_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"))
    receiver_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(String(200))
    idempotency_key: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sender_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receiver_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    token: Mapped[str] = mapped_column(String(512), unique=True)
    platform: Mapped[str] = mapped_column(String(10))
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationSetting(Base):
    __tablename__ = "notification_settings"

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    validation_enabled: Mapped[bool] = mapped_column(default=True)
    match_enabled: Mapped[bool] = mapped_column(default=True)
    postcard_enabled: Mapped[bool] = mapped_column(default=True)
    search_expired_enabled: Mapped[bool] = mapped_column(default=True)
    system_enabled: Mapped[bool] = mapped_column(default=True)
