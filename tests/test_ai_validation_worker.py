import asyncio
from uuid import uuid4

import httpx

from app.ai_validation_worker import (
    DownloadedImage,
    HttpValidationBackend,
    MockPhotoValidationProvider,
    ValidationDecision,
    ValidationJob,
    ValidationProviderError,
    run_validation_once,
)


class FakeBackend:
    def __init__(self, job: ValidationJob | None, image: bytes = b"image") -> None:
        self.job = job
        self.image = image
        self.completed = None
        self.failed = None

    async def claim(self, worker_id):
        self.claimed_by = worker_id
        return self.job

    async def download(self, image_url):
        self.downloaded_url = image_url
        return DownloadedImage(self.image, "image/webp")

    async def complete(self, job_id, **values):
        self.completed = (job_id, values)

    async def fail(self, job_id, **values):
        self.failed = (job_id, values)


def validation_job() -> ValidationJob:
    return ValidationJob(
        job_id=uuid4(),
        photo_id=uuid4(),
        image_url="https://storage.example/photo.webp",
        checks=("QUALITY", "SCREENSHOT"),
        attempt=1,
    )


def test_mock_provider_passes_and_worker_reports_result():
    job = validation_job()
    backend = FakeBackend(job)

    processed = asyncio.run(
        run_validation_once(
            backend,
            MockPhotoValidationProvider("PASSED"),
            worker_id="worker-1",
        )
    )

    assert processed is True
    assert backend.failed is None
    assert backend.completed[0] == job.job_id
    values = backend.completed[1]
    assert values["worker_id"] == "worker-1"
    assert values["decision"] == ValidationDecision(
        status="PASSED",
        scores={"QUALITY": 0.01, "SCREENSHOT": 0.01},
        model_name="dalm-mock-validator",
        model_version="1",
    )
    assert values["processing_time_ms"] >= 0


def test_mock_provider_rejection_uses_configured_code():
    provider = MockPhotoValidationProvider("REJECTED", rejection_code="SCREENSHOT")

    decision = asyncio.run(
        provider.validate(b"image", content_type="image/webp", checks=("QUALITY", "SCREENSHOT"))
    )

    assert decision.status == "REJECTED"
    assert decision.rejection_code == "SCREENSHOT"
    assert decision.scores == {"QUALITY": 0.01, "SCREENSHOT": 0.99}


def test_provider_failure_is_reported_with_retry_policy():
    job = validation_job()
    backend = FakeBackend(job)

    processed = asyncio.run(
        run_validation_once(
            backend,
            MockPhotoValidationProvider("ERROR"),
            worker_id="worker-2",
        )
    )

    assert processed is True
    assert backend.completed is None
    assert backend.failed[0] == job.job_id
    error = backend.failed[1]["error"]
    assert isinstance(error, ValidationProviderError)
    assert error.code == "MOCK_PROVIDER_UNAVAILABLE"
    assert error.retryable is True


def test_worker_returns_false_when_queue_is_empty():
    backend = FakeBackend(None)

    processed = asyncio.run(
        run_validation_once(backend, MockPhotoValidationProvider(), worker_id="worker-3")
    )

    assert processed is False
    assert backend.completed is None
    assert backend.failed is None


def test_http_backend_obeys_claim_and_result_contract():
    job = validation_job()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/claim"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "job": {
                            "job_id": str(job.job_id),
                            "photo_id": str(job.photo_id),
                            "storage_key": "photos/test.webp",
                            "image_url": job.image_url,
                            "checks": list(job.checks),
                            "attempt": 1,
                        }
                    },
                    "error": None,
                },
            )
        return httpx.Response(200, json={"data": {}, "error": None})

    async def scenario():
        client = httpx.AsyncClient(
            base_url="https://api.example",
            transport=httpx.MockTransport(handler),
        )
        backend = HttpValidationBackend(
            "https://api.example",
            internal_api_key="internal-secret",
            client=client,
        )
        claimed = await backend.claim("worker-http")
        await backend.complete(
            claimed.job_id,
            worker_id="worker-http",
            decision=ValidationDecision(
                status="PASSED",
                scores={"QUALITY": 0.1},
                model_name="mock",
                model_version="1",
            ),
            processing_time_ms=12,
        )
        await client.aclose()
        return claimed

    claimed = asyncio.run(scenario())

    assert claimed == job
    assert requests[0].headers["X-DALM-Internal-Key"] == "internal-secret"
    assert b'"processing_time_ms":12' in requests[1].content


def test_http_backend_does_not_leak_internal_key_to_signed_image_url():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"image", headers={"content-type": "image/webp"})

    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        backend = HttpValidationBackend(
            "https://api.example",
            internal_api_key="internal-secret",
            client=client,
        )
        image = await backend.download("https://storage.example/signed-photo")
        await client.aclose()
        return image

    image = asyncio.run(scenario())

    assert image.content == b"image"
    assert "X-DALM-Internal-Key" not in requests[0].headers
