from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Block, Photo, PhotoEmbedding


@dataclass(frozen=True, slots=True)
class PhotoEmbeddingData:
    scene: tuple[float, ...]
    object_action: tuple[float, ...]
    composition: tuple[float, ...]
    color: tuple[float, ...]
    mood: tuple[float, ...]
    labels: dict[str, list[str]]
    model_name: str
    model_version: str

    def __post_init__(self) -> None:
        vectors = (
            self.scene,
            self.object_action,
            self.composition,
            self.color,
            self.mood,
        )
        if any(not vector for vector in vectors):
            raise ValueError("embedding vectors cannot be empty")
        if any(not math.isfinite(value) for vector in vectors for value in vector):
            raise ValueError("embedding vectors must contain finite values")
        if not self.model_name.strip() or not self.model_version.strip():
            raise ValueError("embedding model name and version are required")


@dataclass(frozen=True, slots=True)
class EmbeddingCandidate:
    photo_id: UUID
    user_id: UUID
    registered_at: datetime
    embedding: PhotoEmbeddingData


class PhotoEmbeddingProvider(Protocol):
    async def extract(self, image: bytes, *, content_type: str) -> PhotoEmbeddingData: ...


class PhotoEmbeddingStore(Protocol):
    async def save(self, photo_id: UUID, embedding: PhotoEmbeddingData) -> None: ...


class MockPhotoEmbeddingProvider:
    """Deterministic placeholder whose output can be replaced by the AI provider."""

    def __init__(self, *, dimensions: int = 8) -> None:
        if dimensions < 1:
            raise ValueError("embedding dimensions must be positive")
        self._dimensions = dimensions

    @staticmethod
    def _unit_vector(seed: bytes, dimensions: int) -> tuple[float, ...]:
        values = []
        counter = 0
        while len(values) < dimensions:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            values.extend((byte / 127.5) - 1 for byte in digest)
            counter += 1
        selected = values[:dimensions]
        magnitude = math.sqrt(sum(value * value for value in selected))
        return tuple(round(value / magnitude, 8) for value in selected)

    async def extract(self, image: bytes, *, content_type: str) -> PhotoEmbeddingData:
        if not image:
            raise ValueError("image cannot be empty")
        base = hashlib.sha256(content_type.encode() + b"\0" + image).digest()
        return PhotoEmbeddingData(
            scene=self._unit_vector(base + b"scene", self._dimensions),
            object_action=self._unit_vector(base + b"object-action", self._dimensions),
            composition=self._unit_vector(base + b"composition", self._dimensions),
            color=self._unit_vector(base + b"color", self._dimensions),
            mood=self._unit_vector(base + b"mood", self._dimensions),
            labels={"source": ["mock"]},
            model_name="dalm-mock-embedding",
            model_version="1",
        )


class SqlPhotoEmbeddingStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, photo_id: UUID, embedding: PhotoEmbeddingData) -> None:
        values = {
            "id": uuid4(),
            "photo_id": photo_id,
            "scene_vector": list(embedding.scene),
            "object_action_vector": list(embedding.object_action),
            "composition_vector": list(embedding.composition),
            "color_vector": list(embedding.color),
            "mood_vector": list(embedding.mood),
            "labels": embedding.labels,
            "model_name": embedding.model_name,
            "model_version": embedding.model_version,
        }
        statement = insert(PhotoEmbedding).values(**values)
        update_values = {
            key: value for key, value in values.items() if key not in {"id", "photo_id"}
        }
        statement = statement.on_conflict_do_update(
            index_elements=[PhotoEmbedding.photo_id],
            set_=update_values,
        )
        await self._session.execute(statement)
        await self._session.commit()

    async def list_candidates(
        self,
        source_photo_id: UUID,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[EmbeddingCandidate]:
        if not 1 <= limit <= 500:
            raise ValueError("candidate limit must be between 1 and 500")
        effective_now = now or datetime.now(UTC)
        if effective_now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        source = (
            await self._session.execute(select(Photo).where(Photo.id == source_photo_id))
        ).scalar_one_or_none()
        if source is None:
            raise ApiError(404, "PHOTO_NOT_FOUND", "사진을 찾을 수 없습니다.")
        if (
            source.status != "SEARCHING"
            or source.search_expires_at is None
            or source.search_expires_at <= effective_now
        ):
            raise ApiError(409, "PHOTO_NOT_SEARCHING", "매칭 탐색 중인 사진이 아닙니다.")

        rows = (
            await self._session.execute(
                build_candidate_query(
                    source_photo_id,
                    source.user_id,
                    now=effective_now,
                    limit=limit,
                )
            )
        ).all()
        return [
            EmbeddingCandidate(
                photo_id=photo.id,
                user_id=photo.user_id,
                registered_at=photo.registered_at,
                embedding=_embedding_data(embedding),
            )
            for photo, embedding in rows
        ]


def build_candidate_query(
    source_photo_id: UUID,
    source_user_id: UUID,
    *,
    now: datetime,
    limit: int,
):
    blocked = exists(
        select(Block.blocker_id).where(
            or_(
                and_(Block.blocker_id == source_user_id, Block.blocked_id == Photo.user_id),
                and_(Block.blocker_id == Photo.user_id, Block.blocked_id == source_user_id),
            )
        )
    )
    return (
        select(Photo, PhotoEmbedding)
        .join(PhotoEmbedding, PhotoEmbedding.photo_id == Photo.id)
        .where(
            Photo.id != source_photo_id,
            Photo.user_id != source_user_id,
            Photo.status == "SEARCHING",
            Photo.deleted_at.is_(None),
            Photo.registered_at >= now - timedelta(days=7),
            Photo.search_expires_at.is_not(None),
            Photo.search_expires_at > now,
            ~blocked,
        )
        .order_by(Photo.registered_at.asc(), Photo.id.asc())
        .limit(limit)
    )


def _embedding_data(row: PhotoEmbedding) -> PhotoEmbeddingData:
    return PhotoEmbeddingData(
        scene=tuple(row.scene_vector),
        object_action=tuple(row.object_action_vector),
        composition=tuple(row.composition_vector),
        color=tuple(row.color_vector),
        mood=tuple(row.mood_vector),
        labels=row.labels or {},
        model_name=row.model_name,
        model_version=row.model_version,
    )


async def extract_and_store_embedding(
    store: PhotoEmbeddingStore,
    provider: PhotoEmbeddingProvider,
    *,
    photo_id: UUID,
    image: bytes,
    content_type: str,
) -> PhotoEmbeddingData:
    embedding = await provider.extract(image, content_type=content_type)
    await store.save(photo_id, embedding)
    return embedding
