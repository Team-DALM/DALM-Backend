from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_kakao_id(self, kakao_id: str) -> User | None:
        result = await self._session.execute(select(User).where(User.kakao_id == kakao_id))
        return result.scalar_one_or_none()

    async def create_from_kakao(self, kakao_id: str) -> User:
        user = User(kakao_id=kakao_id)
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = await self.get_by_kakao_id(kakao_id)
            if existing is None:
                raise
            return existing
        await self._session.refresh(user)
        return user

