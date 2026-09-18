from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx

from app.ai_validation_worker import DownloadedImage, ValidationProviderError
from app.photo_embeddings import PhotoEmbeddingData, PhotoEmbeddingProvider


@dataclass(frozen=True, slots=True)
class EmbeddingJob:
    job_id: UUID
    photo_id: UUID
    image_url: str
    attempt: int


class EmbeddingBackend(Protocol):
    async def claim(self, worker_id: str) -> EmbeddingJob | None: ...
    async def download(self, image_url: str) -> DownloadedImage: ...
    async def complete(self, job_id: UUID, *, worker_id: str, embedding: PhotoEmbeddingData): ...
    async def fail(self, job_id: UUID, *, worker_id: str, error: ValidationProviderError): ...


class HttpEmbeddingBackend:
    def __init__(self, base_url: str, *, internal_api_key: str | None, timeout_seconds: float = 30):
        self._headers = {"X-DALM-Internal-Key": internal_api_key} if internal_api_key else {}
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_seconds)

    async def close(self):
        await self._client.aclose()

    async def claim(self, worker_id: str):
        response = await self._client.post(
            "/internal/v1/photo-embeddings/claim", json={"worker_id": worker_id},
            headers=self._headers,
        )
        response.raise_for_status()
        job = response.json()["data"]["job"]
        return None if job is None else EmbeddingJob(
            UUID(job["job_id"]), UUID(job["photo_id"]), job["image_url"], job["attempt"]
        )

    async def download(self, image_url: str):
        try:
            response = await self._client.get(image_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValidationProviderError(
                "IMAGE_DOWNLOAD_FAILED", "failed to download image", retryable=True
            ) from exc
        return DownloadedImage(
            response.content, response.headers.get("content-type", "application/octet-stream")
        )

    async def complete(self, job_id, *, worker_id, embedding):
        response = await self._client.post(
            f"/internal/v1/photo-embeddings/{job_id}/result",
            json={"worker_id": worker_id, "scene": embedding.scene,
                  "object_action": embedding.object_action, "composition": embedding.composition,
                  "color": embedding.color, "mood": embedding.mood, "labels": embedding.labels,
                  "model_name": embedding.model_name, "model_version": embedding.model_version},
            headers=self._headers,
        )
        response.raise_for_status()

    async def fail(self, job_id, *, worker_id, error):
        response = await self._client.post(
            f"/internal/v1/photo-embeddings/{job_id}/failure",
            json={"worker_id": worker_id, "error_code": error.code,
                  "error_message": str(error), "retryable": error.retryable},
            headers=self._headers,
        )
        response.raise_for_status()


async def run_embedding_once(backend: EmbeddingBackend, provider: PhotoEmbeddingProvider,
                             *, worker_id: str) -> bool:
    job = await backend.claim(worker_id)
    if job is None:
        return False
    try:
        image = await backend.download(job.image_url)
        embedding = await provider.extract(image.content, content_type=image.content_type)
    except (ValidationProviderError, ValueError) as exc:
        error = exc if isinstance(exc, ValidationProviderError) else ValidationProviderError(
            "EMBEDDING_INVALID_INPUT", str(exc), retryable=False
        )
        await backend.fail(job.job_id, worker_id=worker_id, error=error)
        return True
    await backend.complete(job.job_id, worker_id=worker_id, embedding=embedding)
    return True
