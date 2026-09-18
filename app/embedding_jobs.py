from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.match_ranking import FeatureScores, MatchCandidate, rank_candidates
from app.matching import SqlMatchFinalizationStore, finalize_match
from app.models import Photo, PhotoEmbedding, PhotoEmbeddingJob
from app.photo_embeddings import PhotoEmbeddingData, SqlPhotoEmbeddingStore


class PhotoEmbeddingJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim_next(self, *, worker_id: str, lease_seconds: int):
        now = datetime.now(UTC)
        job = (
            await self._session.execute(
                select(PhotoEmbeddingJob)
                .where(
                    or_(
                        and_(
                            PhotoEmbeddingJob.status == "PENDING",
                            or_(
                                PhotoEmbeddingJob.next_attempt_at.is_(None),
                                PhotoEmbeddingJob.next_attempt_at <= now,
                            ),
                        ),
                        and_(
                            PhotoEmbeddingJob.status == "PROCESSING",
                            PhotoEmbeddingJob.started_at < now - timedelta(seconds=lease_seconds),
                        ),
                    )
                )
                .order_by(PhotoEmbeddingJob.created_at, PhotoEmbeddingJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if job is None:
            await self._session.rollback()
            return None
        photo = await self._session.get(Photo, job.photo_id)
        if photo is None or photo.status != "SEARCHING" or photo.storage_key is None:
            job.status = "FAILED"
            job.error_code = "PHOTO_NOT_AVAILABLE"
            job.completed_at = now
            await self._session.commit()
            return None
        job.status = "PROCESSING"
        job.worker_id = worker_id
        job.attempt_count += 1
        job.started_at = now
        job.next_attempt_at = None
        await self._session.commit()
        return job, photo

    async def apply_result(
        self, job_id: UUID, *, worker_id: str, embedding: PhotoEmbeddingData
    ) -> PhotoEmbeddingJob:
        job = await self._locked_job(job_id, worker_id, completed_ok=True)
        if job.status == "COMPLETED":
            return job
        values = {
            "photo_id": job.photo_id,
            "scene_vector": list(embedding.scene),
            "object_action_vector": list(embedding.object_action),
            "composition_vector": list(embedding.composition),
            "color_vector": list(embedding.color),
            "mood_vector": list(embedding.mood),
            "labels": embedding.labels,
            "model_name": embedding.model_name,
            "model_version": embedding.model_version,
        }
        statement = insert(PhotoEmbedding).values(**values).on_conflict_do_update(
            index_elements=[PhotoEmbedding.photo_id], set_=values
        )
        await self._session.execute(statement)
        job.status = "COMPLETED"
        job.worker_id = None
        job.completed_at = datetime.now(UTC)
        await self._session.commit()
        return job

    async def record_failure(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        error_code: str,
        error_message: str | None,
        retryable: bool,
        max_attempts: int,
        retry_base_seconds: int,
    ) -> PhotoEmbeddingJob:
        job = await self._locked_job(job_id, worker_id)
        now = datetime.now(UTC)
        job.error_code = error_code
        job.error_message = error_message
        job.worker_id = None
        job.started_at = None
        if retryable and job.attempt_count < max_attempts:
            job.status = "PENDING"
            job.next_attempt_at = now + timedelta(
                seconds=retry_base_seconds * 2 ** (job.attempt_count - 1)
            )
        else:
            job.status = "FAILED"
            job.completed_at = now
        await self._session.commit()
        return job

    async def _locked_job(
        self, job_id: UUID, worker_id: str, *, completed_ok: bool = False
    ) -> PhotoEmbeddingJob:
        job = (
            await self._session.execute(
                select(PhotoEmbeddingJob).where(PhotoEmbeddingJob.id == job_id).with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            raise ApiError(404, "EMBEDDING_JOB_NOT_FOUND", "임베딩 작업을 찾을 수 없습니다.")
        if job.status == "COMPLETED":
            if completed_ok:
                return job
            raise ApiError(409, "EMBEDDING_ALREADY_COMPLETED", "이미 완료된 임베딩 작업입니다.")
        if job.status != "PROCESSING" or job.worker_id != worker_id:
            raise ApiError(409, "EMBEDDING_LEASE_LOST", "임베딩 작업의 실행 권한이 만료되었습니다.")
        return job


def _cosine(left, right) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    if denominator == 0:
        return 0.0
    return max(0.0, min(1.0, sum(x * y for x, y in zip(left, right, strict=True)) / denominator))


def score_embeddings(source: PhotoEmbeddingData, candidate: PhotoEmbeddingData) -> FeatureScores:
    scene = _cosine(source.scene, candidate.scene)
    objects = _cosine(source.object_action, candidate.object_action)
    mood = _cosine(source.mood, candidate.mood)
    return FeatureScores(
        scene=scene,
        semantic=(scene + objects + mood) / 3,
        objects=objects,
        composition=_cosine(source.composition, candidate.composition),
        color=_cosine(source.color, candidate.color),
        mood=mood,
    )


async def orchestrate_match(session: AsyncSession, photo_id: UUID) -> UUID | None:
    source = (
        await session.execute(select(PhotoEmbedding).where(PhotoEmbedding.photo_id == photo_id))
    ).scalar_one_or_none()
    if source is None:
        return None
    source_data = _data(source)
    candidates = await SqlPhotoEmbeddingStore(session).list_candidates(photo_id)
    by_id = {candidate.photo_id: candidate for candidate in candidates}
    ranked = rank_candidates(
        [MatchCandidate(item.photo_id, score_embeddings(source_data, item.embedding)) for item in candidates]
    )
    for item in ranked:
        candidate = by_id[item.photo_id]
        explanation = _explanation(item.scores)
        try:
            return await finalize_match(
                SqlMatchFinalizationStore(session), photo_id, candidate.photo_id, explanation=explanation
            )
        except ApiError as exc:
            if exc.code not in {"MATCH_CANDIDATE_CHANGED", "USER_BLOCKED", "SEARCH_PERIOD_EXPIRED"}:
                raise
    return None


def _data(row: PhotoEmbedding) -> PhotoEmbeddingData:
    return PhotoEmbeddingData(
        scene=tuple(row.scene_vector), object_action=tuple(row.object_action_vector),
        composition=tuple(row.composition_vector), color=tuple(row.color_vector),
        mood=tuple(row.mood_vector), labels=row.labels or {},
        model_name=row.model_name, model_version=row.model_version,
    )


def _explanation(scores: FeatureScores) -> str:
    labels = {
        "scene": "장면", "objects": "대상과 행동", "composition": "구도",
        "color": "색감", "mood": "분위기",
    }
    values = {
        "scene": scores.scene, "objects": scores.objects, "composition": scores.composition,
        "color": scores.color, "mood": scores.mood,
    }
    top = sorted(values, key=values.get, reverse=True)[:2]
    return f"{labels[top[0]]}과 {labels[top[1]]}이 닮은 순간이에요."
