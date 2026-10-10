"""Temporary slot reservation via Redis with TTL.

While a client fills out the booking form, the chosen slot is held so another
client cannot grab it. Holds auto-expire (settings.slot_hold_seconds).
"""
from __future__ import annotations

import datetime as dt

from redis.asyncio import Redis

from app.config import settings


def _key(master_id: int, start_at: dt.datetime) -> str:
    return f"hold:{master_id}:{int(start_at.timestamp())}"


class SlotHoldService:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def try_hold(
        self, master_id: int, start_at: dt.datetime, holder_id: int
    ) -> bool:
        """Attempt to hold the slot. Returns True if acquired (SET NX).

        If the same holder already owns the hold, refresh and return True.
        """
        key = _key(master_id, start_at)
        ok = await self.redis.set(
            key, str(holder_id), ex=settings.slot_hold_seconds, nx=True
        )
        if ok:
            return True
        current = await self.redis.get(key)
        if current is not None and int(current) == holder_id:
            await self.redis.expire(key, settings.slot_hold_seconds)
            return True
        return False

    async def is_held_by_other(
        self, master_id: int, start_at: dt.datetime, holder_id: int
    ) -> bool:
        current = await self.redis.get(_key(master_id, start_at))
        return current is not None and int(current) != holder_id

    async def release(self, master_id: int, start_at: dt.datetime, holder_id: int) -> None:
        key = _key(master_id, start_at)
        current = await self.redis.get(key)
        if current is not None and int(current) == holder_id:
            await self.redis.delete(key)

    async def owns(self, master_id: int, start_at: dt.datetime, holder_id: int) -> bool:
        current = await self.redis.get(_key(master_id, start_at))
        return current is not None and int(current) == holder_id
