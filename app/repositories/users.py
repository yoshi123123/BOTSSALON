"""User & salon settings data access."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Role, SalonSettings, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        res = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return res.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_or_create(
        self, telegram_id: int, full_name: str | None, username: str | None, language: str
    ) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = User(
                telegram_id=telegram_id,
                full_name=full_name,
                username=username,
                language=language,
                role=Role.client,
            )
            self.session.add(user)
            await self.session.flush()
        return user

    async def set_language(self, user: User, language: str) -> None:
        user.language = language
        await self.session.flush()

    async def set_contact(self, user: User, full_name: str, phone: str) -> None:
        user.full_name = full_name
        user.phone = phone
        await self.session.flush()

    async def all_clients(self) -> list[User]:
        res = await self.session.execute(
            select(User).where(User.role == Role.client, User.is_active.is_(True))
        )
        return list(res.scalars().all())

    async def search_clients(self, term: str) -> list[User]:
        like = f"%{term}%"
        res = await self.session.execute(
            select(User).where(
                User.role == Role.client,
                (User.full_name.ilike(like)) | (User.phone.ilike(like)),
            )
        )
        return list(res.scalars().all())


class SalonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> SalonSettings | None:
        res = await self.session.execute(select(SalonSettings).limit(1))
        return res.scalar_one_or_none()
