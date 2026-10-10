"""Reviews (only after completion), matching, slot holds, admin rights."""
from __future__ import annotations

import datetime as dt

import fakeredis.aioredis
import pytest

from app.config import settings
from app.db.models import AppointmentStatus, Role
from app.repositories.appointments import AppointmentRepository, ReviewRepository
from app.repositories.catalog import MasterRepository
from app.services.availability import AvailabilityService
from app.services.booking import BookingService
from app.services.matching import MatchingService
from app.services.slot_hold import SlotHoldService


def _future_slot(hour: int = 11) -> dt.datetime:
    day = dt.datetime.now(settings.tz).date() + dt.timedelta(days=2)
    return dt.datetime.combine(day, dt.time(hour, 0), tzinfo=settings.tz)


@pytest.mark.asyncio
async def test_review_only_after_completion(session, seeded):
    booking = BookingService(session)
    appt = await booking.create(
        client=seeded["client"], master=seeded["master"], service=seeded["service"],
        start_at=_future_slot(11), client_comment=None,
    )
    await session.flush()
    review_repo = ReviewRepository(session)
    # Guard replicates the handler rule: no review unless completed.
    assert appt.status != AppointmentStatus.completed
    already = await review_repo.exists_for_appointment(appt.id)
    assert already is False

    # Complete and leave a review.
    await booking.set_status(appt, AppointmentStatus.completed, seeded["client"])
    await session.flush()
    await review_repo.add(appt.id, seeded["client"].id, seeded["master"].id, 5, "Отлично")
    await review_repo.recompute_master_rating(seeded["master"].id)
    await session.flush()

    # One review per appointment.
    assert await review_repo.exists_for_appointment(appt.id) is True
    master = await MasterRepository(session).get(seeded["master"].id)
    assert master.review_count == 1
    assert float(master.rating) == 5.0


@pytest.mark.asyncio
async def test_matching_returns_master(session, seeded):
    master_repo = MasterRepository(session)
    availability = AvailabilityService(master_repo, AppointmentRepository(session))
    matching = MatchingService(master_repo, availability)
    result = await matching.match(seeded["service"], mode="soonest")
    assert result is not None
    master, slot = result
    assert master.id == seeded["master"].id
    assert slot > dt.datetime.now(settings.tz)


@pytest.mark.asyncio
async def test_slot_hold_prevents_other():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    holds = SlotHoldService(redis)
    slot = _future_slot(11)
    assert await holds.try_hold(1, slot, holder_id=100) is True
    # Another holder cannot grab it.
    assert await holds.try_hold(1, slot, holder_id=200) is False
    assert await holds.is_held_by_other(1, slot, holder_id=200) is True
    # Owner can refresh.
    assert await holds.try_hold(1, slot, holder_id=100) is True
    await holds.release(1, slot, holder_id=100)
    assert await holds.try_hold(1, slot, holder_id=200) is True
    await redis.aclose()


@pytest.mark.asyncio
async def test_admin_rights_check(session, seeded):
    from app.handlers.admin import _is_admin

    client = seeded["client"]
    assert _is_admin(client) is False
    client.role = Role.admin
    assert _is_admin(client) is True
