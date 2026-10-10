"""Regression tests: Railway DB URLs, input validation, status guards, master change."""
from __future__ import annotations

import datetime as dt

import pytest

from app.config import normalize_database_url, settings
from app.db.models import AppointmentStatus, Master, MasterService, Role, User
from app.handlers.booking import normalize_phone
from app.repositories.appointments import AppointmentRepository
from app.services.booking import (
    BookingService,
    NotActiveError,
    NotOwnerError,
    SlotTakenError,
)


def _future_slot(hour: int = 11) -> dt.datetime:
    day = dt.datetime.now(settings.tz).date() + dt.timedelta(days=3)
    return dt.datetime.combine(day, dt.time(hour, 0), tzinfo=settings.tz)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgresql://postgres:secret@postgres.railway.internal:5432/railway",
            "postgresql+asyncpg://postgres:secret@postgres.railway.internal:5432/railway",
        ),
        ("postgres://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        ("postgresql+asyncpg://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgresql+psycopg2://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgresql://u:p@h/db?sslmode=require", "postgresql+asyncpg://u:p@h/db?ssl=require"),
        (
            "postgresql://u:p%40x@h/db?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p%40x@h/db?ssl=require",
        ),
        ("sqlite+aiosqlite:///:memory:", "sqlite+aiosqlite:///:memory:"),
    ],
)
def test_normalize_database_url(raw: str, expected: str) -> None:
    assert normalize_database_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+373 60 123 456", "+37360123456"),
        ("060-123-456", "060123456"),
        ("(022) 12-34-56", "022123456"),
        ("📅 Записаться", None),
        ("hello", None),
        ("1" * 40, None),
        ("12", None),
    ],
)
def test_normalize_phone(raw: str, expected: str | None) -> None:
    assert normalize_phone(raw) == expected


async def _book(session, seeded, hour: int = 11):
    appt = await BookingService(session).create(
        client=seeded["client"], master=seeded["master"], service=seeded["service"],
        start_at=_future_slot(hour), client_comment=None,
    )
    return await AppointmentRepository(session).get(appt.id)


@pytest.mark.asyncio
async def test_custom_hours_open_a_day_off_weekday(session, seeded):
    from app.db.models import ScheduleException
    from app.repositories.catalog import MasterRepository
    from app.services.availability import AvailabilityService

    day = _future_slot().date()
    sched = await MasterRepository(session).schedule_for_weekday(seeded["master"].id, day.weekday())
    sched.is_working_day = False
    session.add(ScheduleException(master_id=seeded["master"].id, date=day,
                                  exception_type="custom_hours",
                                  start_time=dt.time(12, 0), end_time=dt.time(14, 0)))
    await session.flush()
    svc = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    slots = await svc.free_slots(seeded["master"], seeded["service"], day)
    assert [s.time() for s in slots] == [dt.time(12, 0), dt.time(12, 30), dt.time(13, 0)]


@pytest.mark.asyncio
async def test_cancelled_appointment_cannot_be_rescheduled_or_cancelled(session, seeded):
    booking = BookingService(session)
    appt = await _book(session, seeded)
    await booking.set_status(appt, AppointmentStatus.cancelled_by_master, None, "занят")
    with pytest.raises(NotActiveError):
        await booking.reschedule(appt, seeded["client"], _future_slot(15), by_client=True)
    with pytest.raises(NotActiveError):
        await booking.cancel_by_client(appt, seeded["client"], "x")
    assert appt.status == AppointmentStatus.cancelled_by_master


@pytest.mark.asyncio
async def test_other_client_cannot_reschedule(session, seeded):
    stranger = User(telegram_id=5555, role=Role.client, full_name="Чужой")
    session.add(stranger)
    await session.flush()
    appt = await _book(session, seeded)
    with pytest.raises(NotOwnerError):
        await BookingService(session).reschedule(appt, stranger, _future_slot(15), by_client=True)


@pytest.mark.asyncio
async def test_reactivation_into_taken_slot_is_rejected(session, seeded):
    booking = BookingService(session)
    first = await _book(session, seeded, 11)
    await booking.set_status(first, AppointmentStatus.cancelled_by_client, seeded["client"])
    second = await _book(session, seeded, 11)  # the freed time is booked again
    assert second.id != first.id
    with pytest.raises(SlotTakenError):
        await booking.set_status(first, AppointmentStatus.confirmed, None)
    assert first.status == AppointmentStatus.cancelled_by_client
    # Confirming an active (pending) appointment is unaffected.
    await booking.set_status(second, AppointmentStatus.confirmed, None)
    assert second.status == AppointmentStatus.confirmed


@pytest.mark.asyncio
async def test_change_master_updates_relationship(session, seeded):
    other_user = User(telegram_id=7777, role=Role.master, full_name="Другой мастер")
    session.add(other_user)
    await session.flush()
    other = Master(user_id=other_user.id, rating=4.0, review_count=0, experience_years=1)
    session.add(other)
    await session.flush()
    session.add(MasterService(master_id=other.id, service_id=seeded["service"].id))
    await session.flush()
    other = await session.get(Master, other.id)
    await session.refresh(other, ["user"])

    appt = await _book(session, seeded)
    await BookingService(session).change_master(appt, other, seeded["client"])
    assert appt.master_id == other.id
    assert appt.master.user.full_name == "Другой мастер"


@pytest.mark.asyncio
async def test_change_master_rejects_busy_master(session, seeded):
    other_user = User(telegram_id=8888, role=Role.master, full_name="Занятой")
    session.add(other_user)
    await session.flush()
    other = Master(user_id=other_user.id, rating=4.0, review_count=0, experience_years=1)
    session.add(other)
    await session.flush()
    session.add(MasterService(master_id=other.id, service_id=seeded["service"].id))
    await session.flush()
    await session.refresh(other, ["user"])
    # The other master already has a client at 11:00.
    await BookingService(session).create(
        client=seeded["client"], master=other, service=seeded["service"],
        start_at=_future_slot(11), client_comment=None,
    )
    appt = await _book(session, seeded, 11)
    with pytest.raises(SlotTakenError):
        await BookingService(session).change_master(appt, other, seeded["client"])
    assert appt.master_id == seeded["master"].id


def test_reminder_windows_follow_settings(monkeypatch):
    from app.background import scheduler

    monkeypatch.setattr(settings, "reminder_hours_before", 12)
    monkeypatch.setattr(settings, "reminder_hours_before_2", 1)
    assert scheduler._reminder_windows() == {"12h": 12, "1h": 1}
    monkeypatch.setattr(settings, "reminder_hours_before_2", 0)
    assert scheduler._reminder_windows() == {"12h": 12}


def test_admin_ids_parsing(monkeypatch):
    monkeypatch.setattr(settings, "admin_ids", " 123, 456 ;-100200, abc,")
    assert settings.admin_id_set == {123, 456, -100200}


@pytest.mark.asyncio
async def test_status_guard_uses_fresh_row(session, seeded):
    """The client cancels (in another transaction) while the master's handler still holds
    a 'pending' copy: confirming must fail instead of resurrecting the appointment."""
    from sqlalchemy import update

    from app.db.models import Appointment

    appt = await _book(session, seeded)
    await session.execute(
        update(Appointment)
        .where(Appointment.id == appt.id)
        .values(status=AppointmentStatus.cancelled_by_client)
        .execution_options(synchronize_session=False)
    )
    assert appt.status == AppointmentStatus.pending  # stale in-memory copy
    with pytest.raises(NotActiveError):
        await BookingService(session).set_status(
            appt, AppointmentStatus.confirmed, None, allowed_from={AppointmentStatus.pending}
        )
    assert appt.status == AppointmentStatus.cancelled_by_client


@pytest.mark.asyncio
async def test_staff_rescheduling_own_booking_as_client_needs_master(session, seeded):
    seeded["client"].role = Role.admin  # e.g. the salon owner booking for themselves
    appt = await _book(session, seeded)
    await BookingService(session).reschedule(appt, seeded["client"], _future_slot(15), by_client=True)
    assert appt.status == AppointmentStatus.pending


@pytest.mark.asyncio
async def test_bind_master_telegram_id_after_first_boot(session, monkeypatch):
    from sqlalchemy import select

    from app.seed import bind_master_telegram_id, seed_demo

    monkeypatch.setattr(settings, "master_telegram_id", None)
    assert await seed_demo(session) is True
    monkeypatch.setattr(settings, "master_telegram_id", 424242)
    assert await bind_master_telegram_id(session) is True
    master = (
        await session.execute(select(Master).join(User, User.id == Master.user_id)
                              .where(User.telegram_id == 424242))
    ).scalar_one()
    assert master.specialization.startswith("Мужские")
    assert await bind_master_telegram_id(session) is False  # idempotent
    assert await seed_demo(session) is False  # still recognised as seeded


@pytest.mark.asyncio
async def test_salon_env_vars_override_stored_settings(session, monkeypatch):
    from app.repositories.users import SalonRepository
    from app.seed import seed_demo, sync_salon_settings

    await seed_demo(session)
    monkeypatch.setattr(settings, "salon_name", "New Name")
    monkeypatch.setattr(settings, "salon_phone", "+37369999999")
    explicit = set(settings.model_fields_set) | {"salon_name", "salon_phone"}
    monkeypatch.setattr(type(settings), "model_fields_set", property(lambda self: explicit))
    await sync_salon_settings(session)
    salon = await SalonRepository(session).get()
    assert salon.name == "New Name"
    assert salon.phone == "+37369999999"
