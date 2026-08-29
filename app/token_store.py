import asyncio


class InMemoryRefreshTokenStore:
    """Atomic one-time-use refresh-token store.

    Replace this implementation with a shared database or Redis before running
    multiple API processes. The interface keeps that migration isolated.
    """

    def __init__(self) -> None:
        self._active: set[str] = set()
        self._lock = asyncio.Lock()

    async def register(self, token_id: str) -> None:
        async with self._lock:
            self._active.add(token_id)

    async def rotate(self, old_token_id: str, new_token_id: str) -> bool:
        async with self._lock:
            if old_token_id not in self._active:
                return False
            self._active.remove(old_token_id)
            self._active.add(new_token_id)
            return True

    async def revoke(self, token_id: str) -> bool:
        async with self._lock:
            if token_id not in self._active:
                return False
            self._active.remove(token_id)
            return True

