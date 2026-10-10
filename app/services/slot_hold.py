"""Temporary slot reservation, in-process with TTL (no external services).

While a client fills out the booking form, the chosen slot is held so another
client cannot grab it in the UI. Holds auto-expire (settings.slot_hold_seconds).
The database remains the source of truth for double-booking protection; this
only improves UX, so an in-memory store is sufficient for a single bot process.
"""
from __future__ import annotations

import datetime as dt
import time

from app.config import settings

# (master_id, slot start unix ts) -> (holder_id, slot end unix ts, expires_at epoch)
_HOLDS: dict[tuple[int, int], tuple[int, int, float]] = {}


def _key(master_id: int, start_at: dt.datetime) -> tuple[int, int]:
    return (master_id, int(start_at.timestamp()))


def _prune() -> None:
    now = time.time()
    for key, (_, _, expires) in list(_HOLDS.items()):
        if expires <= now:
            _HOLDS.pop(key, None)


def _conflicts(master_id: int, start: int, end: int, holder_id: int) -> bool:
    """Another holder's slot of the same master overlaps [start, end)."""
    for (m_id, h_start), (h_holder, h_end, _) in _HOLDS.items():
        if m_id == master_id and h_holder != holder_id and h_start < end and start < h_end:
            return True
    return False


class SlotHoldService:
    async def try_hold(
        self,
        master_id: int,
        start_at: dt.datetime,
        holder_id: int,
        end_at: dt.datetime | None = None,
    ) -> bool:
        """Acquire or refresh the hold. True if this holder now owns the slot."""
        _prune()
        start = int(start_at.timestamp())
        end = int(end_at.timestamp()) if end_at else start + 1
        if _conflicts(master_id, start, end, holder_id):
            return False
        # One hold per client and master: choosing another time frees the previous one.
        for key, (h_holder, _, _) in list(_HOLDS.items()):
            if key[0] == master_id and h_holder == holder_id:
                _HOLDS.pop(key, None)
        _HOLDS[(master_id, start)] = (holder_id, end, time.time() + settings.slot_hold_seconds)
        return True

    async def is_held_by_other(
        self,
        master_id: int,
        start_at: dt.datetime,
        holder_id: int,
        end_at: dt.datetime | None = None,
    ) -> bool:
        _prune()
        start = int(start_at.timestamp())
        end = int(end_at.timestamp()) if end_at else start + 1
        return _conflicts(master_id, start, end, holder_id)

    async def release(self, master_id: int, start_at: dt.datetime, holder_id: int) -> None:
        key = _key(master_id, start_at)
        current = _HOLDS.get(key)
        if current is not None and current[0] == holder_id:
            _HOLDS.pop(key, None)

    async def release_all(self, holder_id: int) -> None:
        """Drop every hold of this client (they left the booking dialog)."""
        for key, (h_holder, _, _) in list(_HOLDS.items()):
            if h_holder == holder_id:
                _HOLDS.pop(key, None)

    async def owns(self, master_id: int, start_at: dt.datetime, holder_id: int) -> bool:
        _prune()
        current = _HOLDS.get(_key(master_id, start_at))
        return current is not None and current[0] == holder_id
