"""Expire photos whose seven-day search period has ended."""

import asyncio

from app.config import Settings
from app.database import Database
from app.expiration import SqlExpirationStore, expire_searching_photos


async def main() -> None:
    database = Database(Settings.from_env().database_url)
    try:
        async for session in database.session():
            photo_ids = await expire_searching_photos(SqlExpirationStore(session))
            print(f"expired_photos={len(photo_ids)}")
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
