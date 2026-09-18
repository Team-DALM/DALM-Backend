"""Run the mock photo embedding and automatic matching worker."""

import argparse
import asyncio
import os
import socket

from app.ai_embedding_worker import HttpEmbeddingBackend, run_embedding_once
from app.photo_embeddings import MockPhotoEmbeddingProvider


async def run(*, once: bool) -> None:
    backend = HttpEmbeddingBackend(
        os.getenv("DALM_API_BASE_URL", "http://localhost:8000"),
        internal_api_key=os.getenv("DALM_INTERNAL_API_KEY") or None,
        timeout_seconds=float(os.getenv("DALM_VALIDATION_HTTP_TIMEOUT_SECONDS", "30")),
    )
    provider = MockPhotoEmbeddingProvider(
        dimensions=int(os.getenv("DALM_MOCK_EMBEDDING_DIMENSIONS", "8"))
    )
    worker_id = os.getenv("DALM_EMBEDDING_WORKER_ID", f"embedding-{socket.gethostname()}")
    poll_seconds = float(os.getenv("DALM_EMBEDDING_POLL_SECONDS", "5"))
    try:
        while True:
            processed = await run_embedding_once(backend, provider, worker_id=worker_id)
            if once:
                print(f"processed_job={str(processed).lower()}")
                return
            if not processed:
                await asyncio.sleep(poll_seconds)
    finally:
        await backend.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    asyncio.run(run(once=parser.parse_args().once))
