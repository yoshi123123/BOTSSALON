"""Core booking business logic: create / reschedule / cancel appointments.

Double-booking protection strategy:
  1. A partial unique index (master_id, start_at) on active rows (DB-level guard).
  2. `overlapping_active(... FOR UPDATE)` inside the same transaction so two
     concurrent bookings serialize on the master's rows.
  3. A final availability re-check before commit.
The Redis slot hold prevents the race in the UI window; the DB is the source of truth.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    ACTIVE_STATUSES,
    Appointment,
    AppointmentStatus,
    Master,
    Service,
    User,
)
from app.repositories.appointments import AppointmentRepository
from app.repositories.catalog import MasterRepository


class SlotTakenError(Exception):
    """Raised when the requested slot is no longer free."""


class NotOwnerError(Exception):
    """Raised when a user tries to modify an appointment they don't own."""


class TooLateError(Exception):
    """Raised when cancelling later than the allowed window."""


class BookingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.appt_repo = AppointmentRepository(session)
        self.master_repo = MasterRepository(session)

    async def create(
        self,
        *,
        client: User,
        master: Master,
        service: Service,
        start_at: dt.datetime,
        client_comment: str | None,
    ) -> Appointment:
        ms = await self.master_repo.master_service(master.id, service.id)
        duration = self.master_repo.effective_duration(ms, service)
        price = self.master_repo.effective_price(ms, service)
        buffer = service.buffer_minutes
        end_at = start_at + dt.timedelta(minutes=duration + buffer)

        # Lock overlapping active rows; if any exist, the slot is taken.
        overlapping = await self.appt_repo.overlapping_active(master.id, start_at, end_at)
        if overlapping:
            raise SlotTakenError

        appointment = Appointment(
            client_id=client.id,
            master_id=master.id,
            service_id=service.id,
            start_at=start_at,
            end_at=end_at,
            price=price,
            status=AppointmentStatus.pending,
            client_comment=client_comment,
        )
        self.session.add(appointment)
        try:
            await self.session.flush()
        except IntegrityError as exc:  # partial unique index tripped
            await self.session.rollback()
            raise SlotTakenError from exc

        await self.appt_repo.add_history(
            appointment.id, client.id, "created", None, f"{start_at.isoformat()}"
        )
        return appointment

    async def set_status(
        self,
        appointment: Appointment,
        status: AppointmentStatus,
        changed_by: User | None,
        reason: str | None = None,
    ) -> None:
        old = appointment.status.value
        appointment.status = status
        if reason:
            appointment.cancellation_reason = reason
        await self.appt_repo.add_history(
            appointment.id,
            changed_by.id if changed_by else None,
            f"status:{status.value}",
            old,
            status.value,
        )
        await self.session.flush()

    async def cancel_by_client(
        self, appointment: Appointment, client: User, reason: str | None
    ) -> None:
        if appointment.client_id != client.id:
            raise NotOwnerError
        now = dt.datetime.now(settings.tz)
        if appointment.start_at - now < dt.timedelta(hours=settings.min_cancel_hours):
            raise TooLateError
        await self.set_status(
            appointment, AppointmentStatus.cancelled_by_client, client, reason
        )

    async def reschedule(
        self,
        appointment: Appointment,
        actor: User,
        new_start: dt.datetime,
    ) -> None:
        if appointment.client_id != actor.id and actor.role.value in {"client"}:
            raise NotOwnerError
        service = appointment.service
        ms = await self.master_repo.master_service(appointment.master_id, service.id)
        duration = self.master_repo.effective_duration(ms, service)
        buffer = service.buffer_minutes
        new_end = new_start + dt.timedelta(minutes=duration + buffer)

        # Free the old slot conceptually by moving status; then re-check target.
        overlapping = await self.appt_repo.overlapping_active(
            appointment.master_id, new_start, new_end
        )
        overlapping = [o for o in overlapping if o.id != appointment.id]
        if overlapping:
            raise SlotTakenError

        old = f"{appointment.start_at.isoformat()}"
        appointment.start_at = new_start
        appointment.end_at = new_end
        appointment.status = AppointmentStatus.confirmed
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise SlotTakenError from exc
        await self.appt_repo.add_history(
            appointment.id, actor.id, "rescheduled", old, new_start.isoformat()
        )
