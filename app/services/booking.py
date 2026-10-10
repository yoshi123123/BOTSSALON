"""Core booking business logic: create / reschedule / cancel appointments.

Double-booking protection strategy:
  1. Every write that occupies a master's time first locks that master's row
     (SELECT ... FOR UPDATE), so concurrent bookings for one master serialize.
     Locking only the overlapping appointment rows is not enough: two transactions
     inserting overlapping intervals see no rows to lock and both succeed.
  2. Under that lock, overlapping active appointments are looked up; any hit means
     the slot is taken.
  3. A partial unique index (master_id, start_at) on active rows is the last
     DB-level guard; the insert runs in a SAVEPOINT so a violation only undoes it.
The in-memory slot hold prevents the race in the UI window; the DB is the source of truth.
"""
from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import AsyncIterator, Collection

from sqlalchemy import select
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
from app.utils.format import to_local


class SlotTakenError(Exception):
    """Raised when the requested slot is no longer free."""


class NotOwnerError(Exception):
    """Raised when a user tries to modify an appointment they don't own."""


class TooLateError(Exception):
    """Raised when cancelling later than the allowed window."""


class NotActiveError(Exception):
    """Raised when the appointment is already cancelled / completed."""


class UnavailableError(Exception):
    """Raised when the master/service is inactive or the master doesn't offer the service."""


class BookingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.appt_repo = AppointmentRepository(session)
        self.master_repo = MasterRepository(session)

    async def _lock_master(self, master_id: int) -> None:
        await self.session.execute(
            select(Master.id).where(Master.id == master_id).with_for_update()
        )

    async def _lock_appointment(self, appointment: Appointment) -> None:
        """Lock the appointment's master, then re-read the appointment row FOR UPDATE.

        Status checks must use the row as it is now: a client may have cancelled (or an
        admin moved the booking) between loading it and pressing a button. The lock order
        master -> appointment is the same everywhere, so it cannot deadlock.
        """
        locked_master_id = appointment.master_id
        await self._lock_master(locked_master_id)
        await self.session.refresh(
            appointment,
            attribute_names=["status", "start_at", "end_at", "master_id", "client_id"],
            with_for_update=True,
        )
        if appointment.master_id != locked_master_id:
            raise SlotTakenError  # moved to another master meanwhile; let the user retry

    async def _ensure_free(
        self,
        master_id: int,
        start_at: dt.datetime,
        end_at: dt.datetime,
        ignore_id: int | None = None,
    ) -> None:
        await self._lock_master(master_id)
        overlapping = await self.appt_repo.overlapping_active(master_id, start_at, end_at)
        if any(o.id != ignore_id for o in overlapping):
            raise SlotTakenError

    @contextlib.asynccontextmanager
    async def _savepoint(self) -> AsyncIterator[None]:
        """Apply the changes made inside the block within a SAVEPOINT: a unique-index
        violation then undoes only them instead of the whole session (a full rollback
        would expire every loaded object and break the rest of the handler)."""
        try:
            async with self.session.begin_nested():
                yield
        except IntegrityError as exc:
            raise SlotTakenError from exc

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
        if ms is None or not ms.is_active or not master.is_active or not service.is_active:
            raise UnavailableError
        duration = self.master_repo.effective_duration(ms, service)
        price = self.master_repo.effective_price(ms, service)
        buffer = service.buffer_minutes
        end_at = start_at + dt.timedelta(minutes=duration + buffer)

        await self._ensure_free(master.id, start_at, end_at)

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
        async with self._savepoint():  # partial unique index is the last guard
            self.session.add(appointment)

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
        *,
        allowed_from: Collection[AppointmentStatus] | None = None,
    ) -> None:
        """Change the status. `allowed_from` restricts which current statuses may change
        (checked against the locked, freshly read row) and raises NotActiveError."""
        await self._lock_appointment(appointment)
        old_status = appointment.status
        if allowed_from is not None and old_status not in allowed_from:
            raise NotActiveError
        if status in ACTIVE_STATUSES and old_status not in ACTIVE_STATUSES:
            # Re-activating a cancelled/finished appointment: its time may be taken.
            await self._ensure_free(
                appointment.master_id,
                appointment.start_at,
                appointment.end_at,
                ignore_id=appointment.id,
            )
        async with self._savepoint():
            appointment.status = status
            if reason:
                appointment.cancellation_reason = reason
        await self.appt_repo.add_history(
            appointment.id,
            changed_by.id if changed_by else None,
            f"status:{status.value}",
            old_status.value,
            status.value,
        )

    async def cancel_by_client(
        self, appointment: Appointment, client: User, reason: str | None
    ) -> None:
        await self._lock_appointment(appointment)
        if appointment.client_id != client.id:
            raise NotOwnerError
        if appointment.status not in ACTIVE_STATUSES:
            raise NotActiveError
        now = dt.datetime.now(settings.tz)
        if to_local(appointment.start_at) - now < dt.timedelta(hours=settings.min_cancel_hours):
            raise TooLateError
        await self.set_status(
            appointment,
            AppointmentStatus.cancelled_by_client,
            client,
            reason,
            allowed_from=ACTIVE_STATUSES,
        )

    async def reschedule(
        self,
        appointment: Appointment,
        actor: User,
        new_start: dt.datetime,
        *,
        by_client: bool,
    ) -> None:
        """Move an appointment. `by_client=True` is the client's own "My appointments"
        flow: ownership and MIN_CANCEL_HOURS are enforced and the new time goes back to
        the master for confirmation. Staff (admin) moves are final."""
        await self._lock_appointment(appointment)
        if by_client and appointment.client_id != actor.id:
            raise NotOwnerError
        if appointment.status not in ACTIVE_STATUSES:
            raise NotActiveError
        if by_client:
            # Moving an appointment is a late cancellation of the original time.
            now = dt.datetime.now(settings.tz)
            if to_local(appointment.start_at) - now < dt.timedelta(hours=settings.min_cancel_hours):
                raise TooLateError
        service = appointment.service
        ms = await self.master_repo.master_service(appointment.master_id, service.id)
        duration = self.master_repo.effective_duration(ms, service)
        buffer = service.buffer_minutes
        new_end = new_start + dt.timedelta(minutes=duration + buffer)

        await self._ensure_free(
            appointment.master_id, new_start, new_end, ignore_id=appointment.id
        )

        old = f"{appointment.start_at.isoformat()}"
        async with self._savepoint():
            appointment.start_at = new_start
            appointment.end_at = new_end
            appointment.status = (
                AppointmentStatus.pending if by_client else AppointmentStatus.confirmed
            )
        await self.appt_repo.add_history(
            appointment.id, actor.id, "rescheduled", old, new_start.isoformat()
        )

    async def change_master(
        self, appointment: Appointment, new_master: Master, actor: User
    ) -> None:
        """Move an appointment to another master at the same time (admin action)."""
        await self._lock_appointment(appointment)
        if appointment.status not in ACTIVE_STATUSES:
            raise NotActiveError
        if new_master.id == appointment.master_id:
            return
        await self._ensure_free(new_master.id, appointment.start_at, appointment.end_at)
        old_name = appointment.master.user.full_name or "-"
        # Assign the relationship (not just master_id) so appointment.master is current.
        async with self._savepoint():
            appointment.master = new_master
        await self.appt_repo.add_history(
            appointment.id, actor.id, "master_changed", old_name, new_master.user.full_name or "-"
        )
