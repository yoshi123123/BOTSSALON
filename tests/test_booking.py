"""Booking tests: create, double-booking protection, reschedule, cancel."""
from __future__ import annotations

import datetime as dt

import pytest

from app.config import settings
from app.db.models import AppointmentStatus
from app.services.booking import BookingService, SlotTakenError, TooLateError


def _future_slot(hour: int = 11) -> dt.datetime:
    today = dt.datetime.now(settings.tz).date()
    day = today + dt.timedelta(days=2)
    return dt.datetime.combine(day, dt.time(hour, 0), tzinfo=settings.tz)


@pytest.mark.asyncio
async def test_create_in_free_slot(session, seeded):
    booking = BookingService(session)
    appt = await booking.create(
        client=seeded["client"],
        master=seeded["master"],
        service=seeded["service"],
        start_at=_future_slot(11),
        client_comment=None,
    )
    assert appt.id is not None
    assert appt.status == AppointmentStatus.pending
    assert float(appt.price) == 250.0


@pytest.mark.asyncio
async def test_double_booking_blocked(session, seeded):
    booking = BookingService(session)
    slot = _future_slot(12)
    await booking.create(
        client=seeded["client"], master=seeded["master"], service=seeded["service"],
        start_at=slot, client_comment=None,
    )
    await session.flush()
    with pytest.raises(SlotTakenError):
        await booking.create(
            client=seeded["client"], master=seeded["master"], service=seeded["service"],
            start_at=slot, client_comment=None,
        )


@pytest.mark.asyncio
async def test_overlapping_booking_blocked(session, seeded):
    booking = BookingService(session)
    # 60-min service at 12:00 blocks 12:30 start of another 60-min booking.
    await booking.create(
        client=seeded["client"], master=seeded["master"], service=seeded["service"],
        start_at=_future_slot(12), client_comment=None,
    )
    await session.flush()
    with pytest.raises(SlotTakenError):
        await booking.create(
            client=seeded["client"], master=seeded["master"], service=seeded["service"],
            start_at=_future_slot(12) + dt.timedelta(minutes=30), client_comment=None,
        )


@pytest.mark.asyncio
async def test_reschedule(session, seeded):
    booking = BookingService(session)
    appt = await booking.create(
        client=seeded["client"], master=seeded["master"], service=seeded["service"],
        start_at=_future_slot(11), client_comment=None,
    )
    await session.flush()
    # Reload with relationships for reschedule (needs appt.service)
    from app.repositories.appointments import AppointmentRepository
    full = await AppointmentRepository(session).get(appt.id)
    new_slot = _future_slot(15)
    await booking.reschedule(full, seeded["client"], new_slot, by_client=True)
    assert full.start_at == new_slot
    # A time picked by the client goes back to the master for confirmation.
    assert full.status == AppointmentStatus.pending


@pytest.mark.asyncio
async def test_reschedule_by_admin_is_confirmed(session, seeded):
    from app.db.models import Role, User
    from app.repositories.appointments import AppointmentRepository

    admin = User(telegram_id=3000, role=Role.admin, full_name="Админ")
    session.add(admin)
    await session.flush()
    booking = BookingService(session)
    appt = await booking.create(
        client=seeded["client"], master=seeded["master"], service=seeded["service"],
        start_at=_future_slot(11), client_comment=None,
    )
    full = await AppointmentRepository(session).get(appt.id)
    await booking.reschedule(full, admin, _future_slot(16), by_client=False)
    assert full.status == AppointmentStatus.confirmed


@pytest.mark.asyncio
async def test_client_reschedule_too_late(session, seeded):
    from app.repositories.appointments import AppointmentRepository

    booking = BookingService(session)
    soon = dt.datetime.now(settings.tz) + dt.timedelta(hours=1)
    appt = await booking.create(
        client=seeded["client"], master=seeded["master"], service=seeded["service"],
        start_at=soon, client_comment=None,
    )
    full = await AppointmentRepository(session).get(appt.id)
    with pytest.raises(TooLateError):
        await booking.reschedule(full, seeded["client"], _future_slot(15), by_client=True)


@pytest.mark.asyncio
async def test_cannot_book_master_without_service(session, seeded):
    from app.db.models import Service
    from app.services.booking import UnavailableError

    other = Service(name="Не оказывается", default_price=1, default_duration_minutes=30)
    session.add(other)
    await session.flush()
    with pytest.raises(UnavailableError):
        await BookingService(session).create(
            client=seeded["client"], master=seeded["master"], service=other,
            start_at=_future_slot(11), client_comment=None,
        )


@pytest.mark.asyncio
async def test_cancel_too_late(session, seeded):
    booking = BookingService(session)
    # Slot 1 hour from now -> inside the 2h min-cancel window.
    soon = dt.datetime.now(settings.tz) + dt.timedelta(hours=1)
    appt = await booking.create(
        client=seeded["client"], master=seeded["master"], service=seeded["service"],
        start_at=soon, client_comment=None,
    )
    await session.flush()
    with pytest.raises(TooLateError):
        await booking.cancel_by_client(appt, seeded["client"], "передумал")


@pytest.mark.asyncio
async def test_cancel_ok(session, seeded):
    booking = BookingService(session)
    appt = await booking.create(
        client=seeded["client"], master=seeded["master"], service=seeded["service"],
        start_at=_future_slot(11), client_comment=None,
    )
    await session.flush()
    await booking.cancel_by_client(appt, seeded["client"], "заболел")
    assert appt.status == AppointmentStatus.cancelled_by_client
