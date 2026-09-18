import asyncio
import math
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.photo_embeddings import (
    MockPhotoEmbeddingProvider,
    PhotoEmbeddingData,
    build_candidate_query,
    extract_and_store_embedding,
)


class FakeStore:
    def __init__(self):
        self.saved = None

    async def save(self, photo_id, embedding):
        self.saved = (photo_id, embedding)


def test_mock_embedding_is_deterministic_normalized_and_stored():
    photo_id = uuid4()
    store = FakeStore()
    provider = MockPhotoEmbeddingProvider(dimensions=6)

    first = asyncio.run(
        extract_and_store_embedding(
            store,
            provider,
            photo_id=photo_id,
            image=b"same-image",
            content_type="image/webp",
        )
    )
    second = asyncio.run(provider.extract(b"same-image", content_type="image/webp"))

    assert first == second
    assert store.saved == (photo_id, first)
    assert first.model_name == "dalm-mock-embedding"
    assert all(len(vector) == 6 for vector in _vectors(first))
    assert all(
        math.isclose(math.sqrt(sum(value * value for value in vector)), 1, abs_tol=1e-7)
        for vector in _vectors(first)
    )


def test_embedding_contract_rejects_empty_or_non_finite_vectors():
    values = {
        "scene": (0.1,),
        "object_action": (0.2,),
        "composition": (0.3,),
        "color": (0.4,),
        "mood": (0.5,),
        "labels": {},
        "model_name": "model",
        "model_version": "1",
    }
    with pytest.raises(ValueError, match="empty"):
        PhotoEmbeddingData(**{**values, "scene": ()})
    with pytest.raises(ValueError, match="finite"):
        PhotoEmbeddingData(**{**values, "mood": (float("nan"),)})


def test_candidate_query_enforces_seven_day_active_unblocked_policy():
    query = build_candidate_query(
        uuid4(),
        uuid4(),
        now=datetime(2026, 9, 18, tzinfo=UTC),
        limit=25,
    )
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "JOIN photo_embeddings" in sql
    assert "photos.status = 'SEARCHING'" in sql
    assert "photos.registered_at >= '2026-09-11" in sql
    assert "photos.search_expires_at > '2026-09-18" in sql
    assert "NOT (EXISTS" in sql
    assert "blocks.blocker_id" in sql
    assert "LIMIT 25" in sql


def _vectors(embedding: PhotoEmbeddingData):
    return (
        embedding.scene,
        embedding.object_action,
        embedding.composition,
        embedding.color,
        embedding.mood,
    )
