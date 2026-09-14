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

    async def revoke_all(self, subject: str) -> int: ...


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

    async def revoke_all(self, subject: str) -> int:
        async with self._lock:
            token_ids = [token_id for token_id, owner in self._active.items() if owner == subject]
            for token_id in token_ids:
                del self._active[token_id]
            return len(token_ids)


class RedisRefreshTokenStore:
    _rotate_script = """
    local old_key = KEYS[1]
    local new_key = KEYS[2]
    local subject_key = KEYS[3]
    local subject = ARGV[1]
    local ttl = tonumber(ARGV[2])
    if redis.call('GET', old_key) ~= subject then
      return 0
    end
    redis.call('DEL', old_key)
    redis.call('SET', new_key, subject, 'EX', ttl)
    redis.call('SREM', subject_key, old_key)
    redis.call('SADD', subject_key, new_key)
    redis.call('EXPIRE', subject_key, ttl)
    return 1
    """
    _revoke_script = """
    local key = KEYS[1]
    local subject_key = KEYS[2]
    local subject = ARGV[1]
    if redis.call('GET', key) ~= subject then
      return 0
    end
    redis.call('DEL', key)
    redis.call('SREM', subject_key, key)
    return 1
    """
    _revoke_all_script = """
    local subject_key = KEYS[1]
    local keys = redis.call('SMEMBERS', subject_key)
    for _, key in ipairs(keys) do
      redis.call('DEL', key)
    end
    redis.call('DEL', subject_key)
    return #keys
    """

    def __init__(self, client: Redis, key_prefix: str = "auth:refresh:") -> None:
        self._client = client
        self._key_prefix = key_prefix

    def _key(self, token_id: str) -> str:
        return f"{self._key_prefix}{token_id}"

    def _subject_key(self, subject: str) -> str:
        return f"{self._key_prefix}subject:{subject}"

    async def register(self, token_id: str, subject: str, ttl_seconds: int) -> None:
        token_key = self._key(token_id)
        subject_key = self._subject_key(subject)
        async with self._client.pipeline(transaction=True) as pipeline:
            pipeline.set(token_key, subject, ex=ttl_seconds)
            pipeline.sadd(subject_key, token_key)
            pipeline.expire(subject_key, ttl_seconds)
            await pipeline.execute()

    async def rotate(
        self,
        old_token_id: str,
        new_token_id: str,
        subject: str,
        ttl_seconds: int,
    ) -> bool:
        result = await self._client.eval(
            self._rotate_script,
            3,
            self._key(old_token_id),
            self._key(new_token_id),
            self._subject_key(subject),
            subject,
            ttl_seconds,
        )
        return bool(result)

    async def revoke(self, token_id: str, subject: str) -> bool:
        result = await self._client.eval(
            self._revoke_script,
            2,
            self._key(token_id),
            self._subject_key(subject),
            subject,
        )
        return bool(result)

    async def revoke_all(self, subject: str) -> int:
        result = await self._client.eval(
            self._revoke_all_script,
            1,
            self._subject_key(subject),
        )
        return int(result)
