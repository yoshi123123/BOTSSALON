"""Appointment, history and review data access."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    ACTIVE_STATUSES,
    Appointment,
    AppointmentHistory,
    AppointmentStatus,
    Master,
    Review,
)


class AppointmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, appointment_id: int) -> Appointment | None:
        res = await self.session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.master).selectinload(Master.user),
                selectinload(Appointment.client),
            )
        )
        return res.scalar_one_or_none()

    async def overlapping_active(
        self, master_id: int, start_at: dt.datetime, end_at: dt.datetime
    ) -> list[Appointment]:
        """Return active appointments that overlap [start_at, end_at) for a master.

        Locks the rows FOR UPDATE to guarantee no concurrent double-booking.
        """
        stmt = (
            select(Appointment)
            .where(
                Appointment.master_id == master_id,
                Appointment.status.in_(list(ACTIVE_STATUSES)),
                and_(Appointment.start_at < end_at, Appointment.end_at > start_at),
            )
            .with_for_update()
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def active_for_master_on_day(
        self, master_id: int, day: dt.date, tz: dt.tzinfo
    ) -> list[Appointment]:
        day_start = dt.datetime.combine(day, dt.time.min, tzinfo=tz)
        day_end = day_start + dt.timedelta(days=1)
        res = await self.session.execute(
            select(Appointment)
            .where(
                Appointment.master_id == master_id,
                Appointment.status.in_(list(ACTIVE_STATUSES)),
                Appointment.start_at >= day_start,
                Appointment.start_at < day_end,
            )
            .order_by(Appointment.start_at)
        )
        return list(res.scalars().all())

    async def upcoming_for_client(self, client_id: int, now: dt.datetime) -> list[Appointment]:
        res = await self.session.execute(
            select(Appointment)
            .where(
                Appointment.client_id == client_id,
                Appointment.start_at >= now,
                Appointment.status.in_(list(ACTIVE_STATUSES)),
            )
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.master).selectinload(Master.user),
            )
            .order_by(Appointment.start_at)
        )
        return list(res.scalars().all())

    async def last_for_client(self, client_id: int) -> Appointment | None:
        res = await self.session.execute(
            select(Appointment)
            .where(Appointment.client_id == client_id)
            .order_by(Appointment.created_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def add_history(
        self,
        appointment_id: int,
        changed_by_user_id: int | None,
        action: str,
        old_data: str | None = None,
        new_data: str | None = None,
    ) -> None:
        self.session.add(
            AppointmentHistory(
                appointment_id=appointment_id,
                changed_by_user_id=changed_by_user_id,
                action=action,
                old_data=old_data,
                new_data=new_data,
            )
        )
        await self.session.flush()

    # --- stats helpers ---
    async def count_between(
        self, start: dt.datetime, end: dt.datetime, status: AppointmentStatus | None = None
    ) -> int:
        stmt = select(func.count(Appointment.id)).where(
            Appointment.start_at >= start, Appointment.start_at < end
        )
        if status is not None:
            stmt = stmt.where(Appointment.status == status)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def revenue_between(self, start: dt.datetime, end: dt.datetime) -> float:
        res = await self.session.execute(
            select(func.coalesce(func.sum(Appointment.price), 0)).where(
                Appointment.start_at >= start,
                Appointment.start_at < end,
                Appointment.status == AppointmentStatus.completed,
            )
        )
        return float(res.scalar_one())

    async def today_appointments(self, day_start: dt.datetime, day_end: dt.datetime) -> list[Appointment]:
        res = await self.session.execute(
            select(Appointment)
            .where(Appointment.start_at >= day_start, Appointment.start_at < day_end)
            .options(
                selectinload(Appointment.service),
                selectinload(Appointment.master).selectinload(Master.user),
                selectinload(Appointment.client),
            )
            .order_by(Appointment.start_at)
        )
        return list(res.scalars().all())


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists_for_appointment(self, appointment_id: int) -> bool:
        res = await self.session.execute(
            select(Review.id).where(Review.appointment_id == appointment_id)
        )
        return res.scalar_one_or_none() is not None

    async def add(
        self, appointment_id: int, client_id: int, master_id: int, rating: int, text: str | None
    ) -> Review:
        review = Review(
            appointment_id=appointment_id,
            client_id=client_id,
            master_id=master_id,
            rating=rating,
            text=text,
        )
        self.session.add(review)
        await self.session.flush()
        return review

    async def recompute_master_rating(self, master_id: int) -> None:
        res = await self.session.execute(
            select(func.avg(Review.rating), func.count(Review.id)).where(
                Review.master_id == master_id, Review.is_visible.is_(True)
            )
        )
        avg, count = res.one()
        master = await self.session.get(Master, master_id)
        if master:
            master.rating = round(float(avg), 1) if avg is not None else 0.0
            master.review_count = int(count)
            await self.session.flush()
