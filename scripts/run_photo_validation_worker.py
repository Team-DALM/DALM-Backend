"""Run the replaceable photo-validation worker with the mock provider."""

import argparse
import asyncio
import os
import socket

from app.ai_validation_worker import (
    HttpValidationBackend,
    create_mock_validation_provider,
    run_validation_once,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="claim at most one job and exit")
    return parser.parse_args()


async def run(*, once: bool) -> None:
    base_url = os.getenv("DALM_API_BASE_URL", "http://localhost:8000")
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
    try:
        while True:
            processed = await run_validation_once(backend, provider, worker_id=worker_id)
            if once:
                print(f"processed_job={str(processed).lower()}")
                return
            if not processed:
                await asyncio.sleep(poll_seconds)
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(run(once=parse_args().once))
