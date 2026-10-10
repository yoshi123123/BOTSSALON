"""Availability tests: working hours, day-off, breaks, duration, buffer."""
from __future__ import annotations

import datetime as dt

import pytest

from app.config import settings
from app.db.models import ScheduleException
from app.repositories.appointments import AppointmentRepository
from app.repositories.catalog import MasterRepository
from app.services.availability import AvailabilityService


def _next_weekday(target_wd: int) -> dt.date:
    today = dt.datetime.now(settings.tz).date()
    for offset in range(1, 9):
        d = today + dt.timedelta(days=offset)
        if d.weekday() == target_wd:
            return d
    return today + dt.timedelta(days=1)


@pytest.mark.asyncio
async def test_free_slots_on_working_day(session, seeded):
    svc = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    day = _next_weekday(2)  # some future weekday
    slots = await svc.free_slots(seeded["master"], seeded["service"], day)
    assert len(slots) > 0
    # First slot should be within working hours (10:00-18:00), 60-min service
    assert all(10 <= s.hour < 18 for s in slots)


@pytest.mark.asyncio
async def test_no_slots_on_day_off(session, seeded):
    day = _next_weekday(3)
    session.add(
        ScheduleException(
            master_id=seeded["master"].id, date=day, exception_type="day_off", reason="отпуск"
        )
    )
    await session.flush()
    svc = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    slots = await svc.free_slots(seeded["master"], seeded["service"], day)
    assert slots == []


@pytest.mark.asyncio
async def test_non_working_weekday(session, seeded):
    day = _next_weekday(4)
    sched = await MasterRepository(session).schedule_for_weekday(seeded["master"].id, day.weekday())
    sched.is_working_day = False
    await session.flush()
    svc = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    assert await svc.free_slots(seeded["master"], seeded["service"], day) == []


@pytest.mark.asyncio
async def test_break_excludes_slots(session, seeded):
    day = _next_weekday(2)
    sched = await MasterRepository(session).schedule_for_weekday(seeded["master"].id, day.weekday())
    sched.break_start = dt.time(13, 0)
    sched.break_end = dt.time(14, 0)
    await session.flush()
    svc = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    slots = await svc.free_slots(seeded["master"], seeded["service"], day)
    # A 60-min service starting 12:30 or 13:00 or 13:30 would hit the break.
    for s in slots:
        end = s + dt.timedelta(minutes=60)
        assert not (s < dt.datetime.combine(day, dt.time(14, 0), tzinfo=settings.tz)
                    and end > dt.datetime.combine(day, dt.time(13, 0), tzinfo=settings.tz))


@pytest.mark.asyncio
async def test_buffer_after_last_client_may_exceed_closing_time(session, seeded):
    day = _next_weekday(2)
    seeded["service"].buffer_minutes = 30
    await session.flush()
    svc = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    slots = await svc.free_slots(seeded["master"], seeded["service"], day)
    # The 60-min service itself must end by 18:00; the cleanup buffer after the last
    # client of the day does not need to fit into working hours.
    closing = dt.datetime.combine(day, dt.time(18, 0), tzinfo=settings.tz)
    assert slots[-1] == closing - dt.timedelta(minutes=60)
    assert all(s + dt.timedelta(minutes=60) <= closing for s in slots)


@pytest.mark.asyncio
async def test_buffer_separates_appointments(session, seeded):
    from app.services.booking import BookingService

    day = _next_weekday(2)
    seeded["service"].buffer_minutes = 30
    await session.flush()
    start = dt.datetime.combine(day, dt.time(11, 0), tzinfo=settings.tz)
    await BookingService(session).create(
        client=seeded["client"], master=seeded["master"], service=seeded["service"],
        start_at=start, client_comment=None,
    )
    svc = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    slots = await svc.free_slots(seeded["master"], seeded["service"], day)
    # 11:00 + 60 min + 30 min buffer -> next start not before 12:30; and a slot before
    # 11:00 must leave its own buffer: 9:30 + 90 > 11:00 so 09:30 is out, 10:00 is out.
    assert start not in slots
    assert dt.datetime.combine(day, dt.time(12, 0), tzinfo=settings.tz) not in slots
    assert dt.datetime.combine(day, dt.time(12, 30), tzinfo=settings.tz) in slots
    assert dt.datetime.combine(day, dt.time(10, 0), tzinfo=settings.tz) not in slots


@pytest.mark.asyncio
async def test_is_bookable_rejects_forged_times(session, seeded):
    day = _next_weekday(2)
    svc = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    ok = dt.datetime.combine(day, dt.time(11, 0), tzinfo=settings.tz)
    night = dt.datetime.combine(day, dt.time(3, 0), tzinfo=settings.tz)
    odd = dt.datetime.combine(day, dt.time(11, 7), tzinfo=settings.tz)
    assert await svc.is_bookable(seeded["master"], seeded["service"], ok) is True
    assert await svc.is_bookable(seeded["master"], seeded["service"], night) is False
    assert await svc.is_bookable(seeded["master"], seeded["service"], odd) is False
