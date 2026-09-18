from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Literal, Protocol, cast
from uuid import UUID

import httpx

ValidationStatus = Literal["PASSED", "REJECTED"]
MockValidationMode = Literal["PASSED", "REJECTED", "ERROR"]


@dataclass(frozen=True, slots=True)
class ValidationJob:
    job_id: UUID
    photo_id: UUID
    image_url: str
    checks: tuple[str, ...]
    attempt: int


@dataclass(frozen=True, slots=True)
class DownloadedImage:
    content: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class ValidationDecision:
    status: ValidationStatus
    scores: dict[str, float]
    model_name: str
    model_version: str
    rejection_code: str | None = None

    def __post_init__(self) -> None:
        if self.status == "REJECTED" and self.rejection_code is None:
            raise ValueError("REJECTED decisions require a rejection_code")
        if self.status == "PASSED" and self.rejection_code is not None:
            raise ValueError("PASSED decisions cannot include a rejection_code")
        if any(not 0 <= value <= 1 for value in self.scores.values()):
            raise ValueError("validation scores must be between 0 and 1")


class ValidationProviderError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class PhotoValidationProvider(Protocol):
    async def validate(
        self,
        image: bytes,
        *,
        content_type: str,
        checks: tuple[str, ...],
    ) -> ValidationDecision: ...


class ValidationBackend(Protocol):
    async def claim(self, worker_id: str) -> ValidationJob | None: ...

    async def download(self, image_url: str) -> DownloadedImage: ...

    async def complete(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        decision: ValidationDecision,
        processing_time_ms: int,
    ) -> None: ...

    async def fail(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        error: ValidationProviderError,
    ) -> None: ...


class MockPhotoValidationProvider:
    """Deterministic provider for exercising the worker before the AI model is ready."""

    def __init__(
        self,
        mode: MockValidationMode = "PASSED",
        *,
        rejection_code: str = "SCREENSHOT",
    ) -> None:
        self._mode = mode
        self._rejection_code = rejection_code

    async def validate(
        self,
        image: bytes,
        *,
        content_type: str,
        checks: tuple[str, ...],
    ) -> ValidationDecision:
        del content_type
        if not image:
            raise ValidationProviderError(
                "EMPTY_IMAGE",
                "downloaded image is empty",
                retryable=False,
            )
        if self._mode == "ERROR":
            raise ValidationProviderError(
                "MOCK_PROVIDER_UNAVAILABLE",
                "mock provider was configured to simulate a retryable failure",
                retryable=True,
            )
        if self._mode == "REJECTED":
            scores = {check: (0.99 if check == self._rejection_code else 0.01) for check in checks}
            return ValidationDecision(
                status="REJECTED",
                scores=scores,
                rejection_code=self._rejection_code,
                model_name="dalm-mock-validator",
                model_version="1",
            )
        return ValidationDecision(
            status="PASSED",
            scores={check: 0.01 for check in checks},
            model_name="dalm-mock-validator",
            model_version="1",
        )


def create_mock_validation_provider(mode: str) -> MockPhotoValidationProvider:
    normalized = mode.upper()
    if normalized not in {"PASSED", "REJECTED", "ERROR"}:
        raise ValueError("mock validation mode must be PASSED, REJECTED, or ERROR")
    return MockPhotoValidationProvider(cast(MockValidationMode, normalized))


class HttpValidationBackend:
    def __init__(
        self,
        base_url: str,
        *,
        internal_api_key: str | None,
        timeout_seconds: float = 30,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._internal_headers = (
            {"X-DALM-Internal-Key": internal_api_key} if internal_api_key else {}
        )
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def claim(self, worker_id: str) -> ValidationJob | None:
        response = await self._client.post(
            "/internal/v1/photo-validations/claim",
            json={"worker_id": worker_id},
            headers=self._internal_headers,
        )
        response.raise_for_status()
        job = response.json()["data"]["job"]
        if job is None:
            return None
        return ValidationJob(
            job_id=UUID(job["job_id"]),
            photo_id=UUID(job["photo_id"]),
            image_url=job["image_url"],
            checks=tuple(job["checks"]),
            attempt=job["attempt"],
        )

    async def download(self, image_url: str) -> DownloadedImage:
        try:
            response = await self._client.get(image_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValidationProviderError(
                "IMAGE_DOWNLOAD_FAILED",
                "failed to download the photo for validation",
                retryable=True,
            ) from exc
        return DownloadedImage(
            content=response.content,
            content_type=response.headers.get("content-type", "application/octet-stream"),
        )

    async def complete(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        decision: ValidationDecision,
        processing_time_ms: int,
    ) -> None:
        response = await self._client.post(
            f"/internal/v1/photo-validations/{job_id}/result",
            json={
                "status": decision.status,
                "scores": decision.scores,
                "rejection_code": decision.rejection_code,
                "model_name": decision.model_name,
                "model_version": decision.model_version,
                "processing_time_ms": processing_time_ms,
                "worker_id": worker_id,
            },
            headers=self._internal_headers,
        )
        response.raise_for_status()

    async def fail(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        error: ValidationProviderError,
    ) -> None:
        response = await self._client.post(
            f"/internal/v1/photo-validations/{job_id}/failure",
            json={
                "worker_id": worker_id,
                "error_code": error.code,
                "error_message": str(error),
                "retryable": error.retryable,
            },
            headers=self._internal_headers,
        )
        response.raise_for_status()


async def run_validation_once(
    backend: ValidationBackend,
    provider: PhotoValidationProvider,
    *,
    worker_id: str,
) -> bool:
    job = await backend.claim(worker_id)
    if job is None:
        return False

    started_at = monotonic()
    try:
        image = await backend.download(job.image_url)
        decision = await provider.validate(
            image.content,
            content_type=image.content_type,
            checks=job.checks,
        )
    except ValidationProviderError as exc:
        await backend.fail(job.job_id, worker_id=worker_id, error=exc)
        return True

    await backend.complete(
        job.job_id,
        worker_id=worker_id,
        decision=decision,
        processing_time_ms=max(0, round((monotonic() - started_at) * 1000)),
    )
    return True
