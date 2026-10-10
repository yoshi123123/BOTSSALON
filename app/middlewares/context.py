"""Middleware: open a DB session per update, resolve/create the user, inject deps."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser

from app.config import settings
from app.db.base import async_session_factory
from app.db.models import Role, User
from app.repositories.users import UserRepository


class ContextMiddleware(BaseMiddleware):
    """Provides `session` and `user` to every handler. Commits on success."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        async with async_session_factory() as session:
            data["session"] = session
            user: User | None = None
            if tg_user is not None:
                repo = UserRepository(session)
                user = await repo.get_or_create(
                    telegram_id=tg_user.id,
                    full_name=tg_user.full_name,
                    username=tg_user.username,
                    language=settings.default_language,
                )
                # Promote configured admins.
                if tg_user.id in settings.admin_id_set and user.role == Role.client:
                    user.role = Role.admin
                    await session.flush()
            data["user"] = user
            data["is_admin"] = bool(
                user and user.role in {Role.admin, Role.owner}
            ) or (tg_user is not None and tg_user.id in settings.admin_id_set)
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
