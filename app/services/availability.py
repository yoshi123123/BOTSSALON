"""Availability computation: which time slots are actually bookable.

Takes into account: master's weekday schedule, breaks, day-off / block exceptions,
existing active appointments, service duration + buffer, and the salon timezone.
"""
from __future__ import annotations

import datetime as dt

from redis.asyncio import Redis

from app.config import settings
from app.db.models import Master, Schedule, ScheduleException, Service
from app.repositories.appointments import AppointmentRepository
from app.repositories.catalog import MasterRepository
from app.services.slot_hold import SlotHoldService

SLOT_STEP_MINUTES = 30  # granularity of offered start times


class AvailabilityService:
    def __init__(
        self,
        master_repo: MasterRepository,
        appt_repo: AppointmentRepository,
        redis: Redis | None = None,
    ) -> None:
        self.master_repo = master_repo
        self.appt_repo = appt_repo
        self.holds = SlotHoldService(redis) if redis is not None else None

    async def free_slots(
        self,
        master: Master,
        service: Service,
        day: dt.date,
        holder_id: int | None = None,
    ) -> list[dt.datetime]:
        tz = settings.tz
        ms = await self.master_repo.master_service(master.id, service.id)
        duration = self.master_repo.effective_duration(ms, service)
        buffer = service.buffer_minutes
        total = duration + buffer

        schedule = await self.master_repo.schedule_for_weekday(master.id, day.weekday())
        if schedule is None or not schedule.is_working_day:
            return []

        exceptions = await self.master_repo.exceptions_for_date(master.id, day)
        if any(e.exception_type == "day_off" for e in exceptions):
            return []

        work_start, work_end = self._effective_hours(schedule, exceptions)
        if work_start is None or work_end is None:
            return []

        existing = await self.appt_repo.active_for_master_on_day(master.id, day, tz)
        busy: list[tuple[dt.datetime, dt.datetime]] = [
            (a.start_at.astimezone(tz), a.end_at.astimezone(tz)) for a in existing
        ]
        for e in exceptions:
            if e.exception_type == "block" and e.start_time and e.end_time:
                busy.append(
                    (
                        dt.datetime.combine(day, e.start_time, tzinfo=tz),
                        dt.datetime.combine(day, e.end_time, tzinfo=tz),
                    )
                )
        if schedule.break_start and schedule.break_end:
            busy.append(
                (
                    dt.datetime.combine(day, schedule.break_start, tzinfo=tz),
                    dt.datetime.combine(day, schedule.break_end, tzinfo=tz),
                )
            )

        now = dt.datetime.now(tz)
        day_start = dt.datetime.combine(day, work_start, tzinfo=tz)
        day_end = dt.datetime.combine(day, work_end, tzinfo=tz)

        slots: list[dt.datetime] = []
        cursor = day_start
        step = dt.timedelta(minutes=SLOT_STEP_MINUTES)
        while cursor + dt.timedelta(minutes=total) <= day_end + dt.timedelta(minutes=buffer):
            slot_end = cursor + dt.timedelta(minutes=total)
            if cursor <= now:
                cursor += step
                continue
            if slot_end > day_end + dt.timedelta(minutes=buffer):
                break
            if not self._overlaps_any(cursor, slot_end, busy):
                if self.holds is not None and holder_id is not None:
                    if await self.holds.is_held_by_other(master.id, cursor, holder_id):
                        cursor += step
                        continue
                slots.append(cursor)
            cursor += step
        return slots

    async def has_any_slot(self, master: Master, service: Service, day: dt.date) -> bool:
        return len(await self.free_slots(master, service, day)) > 0

    async def next_available(
        self, master: Master, service: Service, days_ahead: int = 14
    ) -> dt.datetime | None:
        today = dt.datetime.now(settings.tz).date()
        for offset in range(days_ahead):
            day = today + dt.timedelta(days=offset)
            slots = await self.free_slots(master, service, day)
            if slots:
                return slots[0]
        return None

    @staticmethod
    def _effective_hours(
        schedule: Schedule, exceptions: list[ScheduleException]
    ) -> tuple[dt.time | None, dt.time | None]:
        for e in exceptions:
            if e.exception_type == "custom_hours" and e.start_time and e.end_time:
                return e.start_time, e.end_time
        return schedule.start_time, schedule.end_time

    @staticmethod
    def _overlaps_any(
        start: dt.datetime, end: dt.datetime, busy: list[tuple[dt.datetime, dt.datetime]]
    ) -> bool:
        return any(start < b_end and end > b_start for b_start, b_end in busy)
