import asyncio
import math
from uuid import uuid4

from app.ai_embedding_worker import EmbeddingJob, run_embedding_once
from app.ai_validation_worker import DownloadedImage
from app.embedding_jobs import score_embeddings
from app.photo_embeddings import MockPhotoEmbeddingProvider


class FakeBackend:
    def __init__(self, job=None):
        self.job = job
        self.completed = None
        self.failed = None

    async def claim(self, worker_id):
        return self.job

    async def download(self, image_url):
        return DownloadedImage(b"image", "image/webp")

    async def complete(self, job_id, **values):
        self.completed = (job_id, values)

    async def fail(self, job_id, **values):
        self.failed = (job_id, values)


def test_embedding_worker_extracts_and_submits_result():
    job = EmbeddingJob(uuid4(), uuid4(), "https://storage/photo", 1)
    backend = FakeBackend(job)

    processed = asyncio.run(
        run_embedding_once(
            backend, MockPhotoEmbeddingProvider(dimensions=4), worker_id="embedding-1"
        )
    )

    assert processed is True
    assert backend.failed is None
    assert backend.completed[0] == job.job_id
    assert backend.completed[1]["worker_id"] == "embedding-1"


def test_identical_embeddings_produce_perfect_feature_scores():
    provider = MockPhotoEmbeddingProvider(dimensions=4)
    embedding = asyncio.run(provider.extract(b"same", content_type="image/webp"))

    scores = score_embeddings(embedding, embedding)

    assert all(math.isclose(value, 1) for value in scores.values())


def test_embedding_worker_returns_false_for_empty_queue():
    assert asyncio.run(
        run_embedding_once(FakeBackend(), MockPhotoEmbeddingProvider(), worker_id="worker")
    ) is False
