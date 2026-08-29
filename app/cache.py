from redis.asyncio import Redis


class Cache:
    def __init__(self, url: str, *, client: Redis | None = None) -> None:
        self.client = client or Redis.from_url(url, decode_responses=True)

    async def ping(self) -> None:
        await self.client.ping()

    async def close(self) -> None:
        await self.client.aclose()

