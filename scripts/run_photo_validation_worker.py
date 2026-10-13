"""Run the replaceable photo-validation worker with the mock provider."""

import argparse
import asyncio
import logging
import os
import socket

import httpx

from app.ai_validation_worker import (
    HttpValidationBackend,
    create_mock_validation_provider,
    run_validation_once,
)

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="claim at most one job and exit")
    return parser.parse_args()


async def run(*, once: bool) -> None:
    base_url = os.getenv("DALM_API_BASE_URL", f"http://127.0.0.1:{os.getenv('PORT', '8000')}")
    worker_id = os.getenv("DALM_VALIDATION_WORKER_ID", f"mock-{socket.gethostname()}")
    mode = os.getenv("DALM_MOCK_VALIDATION_RESULT", "PASSED")
    poll_seconds = float(os.getenv("DALM_VALIDATION_POLL_SECONDS", "5"))
    if poll_seconds <= 0:
        raise RuntimeError("DALM_VALIDATION_POLL_SECONDS must be greater than zero")

    backend = HttpValidationBackend(
        base_url,
        internal_api_key=os.getenv("DALM_INTERNAL_API_KEY") or None,
        timeout_seconds=float(os.getenv("DALM_VALIDATION_HTTP_TIMEOUT_SECONDS", "30")),
    )
    try:
        provider = create_mock_validation_provider(mode)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    logger.warning("Mock validation worker started (mode=%s)", mode)
    try:
        while True:
            try:
                processed = await run_validation_once(backend, provider, worker_id=worker_id)
            except httpx.HTTPError as exc:
                # API startup, transient outages and expired leases must not stop polling.
                # Do not log exception text: download errors can contain signed URLs.
                logger.warning("Mock validation worker request failed (%s)", type(exc).__name__)
                if once:
                    raise
                await asyncio.sleep(poll_seconds)
                continue
            if processed:
                logger.info("Mock validation worker processed a job (mode=%s)", mode)
            if once:
                print(f"processed_job={str(processed).lower()}")
                return
            if not processed:
                await asyncio.sleep(poll_seconds)
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(run(once=parse_args().once))
