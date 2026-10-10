"""Automatic master matching: soonest availability or best rating."""
from __future__ import annotations

import datetime as dt

from app.db.models import Master, Service
from app.repositories.catalog import MasterRepository
from app.services.availability import AvailabilityService


class MatchingService:
    def __init__(
        self, master_repo: MasterRepository, availability: AvailabilityService
    ) -> None:
        self.master_repo = master_repo
        self.availability = availability

    async def match(
        self, service: Service, mode: str, days_ahead: int = 14
    ) -> tuple[Master, dt.datetime] | None:
        """Return (master, earliest_slot) or None. mode = 'soonest' | 'best'."""
        masters = await self.master_repo.list_for_service(service.id)
        candidates: list[tuple[Master, dt.datetime]] = []
        for master in masters:
            slot = await self.availability.next_available(master, service, days_ahead)
            if slot is not None:
                candidates.append((master, slot))
        if not candidates:
            return None
        if mode == "best":
            candidates.sort(key=lambda x: (-float(x[0].rating), x[1]))
        else:  # soonest
            candidates.sort(key=lambda x: (x[1], -float(x[0].rating)))
        return candidates[0]
