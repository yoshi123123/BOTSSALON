"""Middleware injecting shared singletons (redis, notifier) into handler data."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from redis.asyncio import Redis

from app.services.notifications import NotificationService


class DepsMiddleware(BaseMiddleware):
    def __init__(self, redis: Redis, notifier: NotificationService) -> None:
        self.redis = redis
        self.notifier = notifier

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["redis"] = self.redis
        data["notifier"] = self.notifier
        return await handler(event, data)
