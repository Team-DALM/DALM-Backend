import asyncio
from typing import Protocol

from redis.asyncio import Redis


class RefreshTokenStore(Protocol):
    async def register(self, token_id: str, subject: str, ttl_seconds: int) -> None: ...

    async def rotate(
        self,
        old_token_id: str,
        new_token_id: str,
        subject: str,
        ttl_seconds: int,
    ) -> bool: ...

    async def revoke(self, token_id: str, subject: str) -> bool: ...


class InMemoryRefreshTokenStore:
    def __init__(self) -> None:
        self._active: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def register(self, token_id: str, subject: str, ttl_seconds: int) -> None:
        del ttl_seconds
        async with self._lock:
            self._active[token_id] = subject

    async def rotate(
        self,
        old_token_id: str,
        new_token_id: str,
        subject: str,
        ttl_seconds: int,
    ) -> bool:
        del ttl_seconds
        async with self._lock:
            if self._active.get(old_token_id) != subject:
                return False
            del self._active[old_token_id]
            self._active[new_token_id] = subject
            return True

    async def revoke(self, token_id: str, subject: str) -> bool:
        async with self._lock:
            if self._active.get(token_id) != subject:
                return False
            del self._active[token_id]
            return True


class RedisRefreshTokenStore:
    _rotate_script = """
    local old_key = KEYS[1]
    local new_key = KEYS[2]
    local subject = ARGV[1]
    local ttl = tonumber(ARGV[2])
    if redis.call('GET', old_key) ~= subject then
      return 0
    end
    redis.call('DEL', old_key)
    redis.call('SET', new_key, subject, 'EX', ttl)
    return 1
    """
    _revoke_script = """
    local key = KEYS[1]
    local subject = ARGV[1]
    if redis.call('GET', key) ~= subject then
      return 0
    end
    redis.call('DEL', key)
    return 1
    """

    def __init__(self, client: Redis, key_prefix: str = "auth:refresh:") -> None:
        self._client = client
        self._key_prefix = key_prefix

    def _key(self, token_id: str) -> str:
        return f"{self._key_prefix}{token_id}"

    async def register(self, token_id: str, subject: str, ttl_seconds: int) -> None:
        await self._client.set(self._key(token_id), subject, ex=ttl_seconds)

    async def rotate(
        self,
        old_token_id: str,
        new_token_id: str,
        subject: str,
        ttl_seconds: int,
    ) -> bool:
        result = await self._client.eval(
            self._rotate_script,
            2,
            self._key(old_token_id),
            self._key(new_token_id),
            subject,
            ttl_seconds,
        )
        return bool(result)

    async def revoke(self, token_id: str, subject: str) -> bool:
        result = await self._client.eval(
            self._revoke_script,
            1,
            self._key(token_id),
            subject,
        )
        return bool(result)

