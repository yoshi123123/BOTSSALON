"""In-process background scheduler: reminders, auto-completion, review prompts.

Runs as an asyncio task inside the bot process. Idempotency marks live in the
`sent_notifications` Postgres table (INSERT .. ON CONFLICT DO NOTHING), so each
notification is sent exactly once and the guarantee survives restarts.

Every CHECK_INTERVAL seconds it:
  1. Sends client reminders 24h and 2h before active appointments.
  2. Sends a morning digest (once per day) to each master with today's bookings.
  3. Marks past confirmed/pending appointments as completed and asks the
     client to leave a review.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, cast

import structlog
from aiogram import Bot
from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.base import async_session_factory
from app.db.models import (
    ACTIVE_STATUSES,
    Appointment,
    AppointmentHistory,
    AppointmentStatus,
    Master,
    SentNotification,
    User,
)
from app.integrations.sms.provider import SMSProvider
from app.keyboards.builders import review_kb
from app.locales import t
from app.repositories.users import SalonRepository
from app.services.notifications import NotificationService, is_real_chat
from app.utils.format import fmt_date, fmt_time

log = structlog.get_logger(__name__)

CHECK_INTERVAL = 300  # seconds (5 min)
DIGEST_HOUR = 8  # local time
MARK_RETENTION_DAYS = 30


def _reminder_windows() -> dict[str, int]:
    """Reminder windows from settings (REMINDER_HOURS_BEFORE / _2), e.g. {"24h": 24, "2h": 2}."""
    hours = {settings.reminder_hours_before, settings.reminder_hours_before_2}
    return {f"{h}h": h for h in sorted(hours, reverse=True) if h > 0}


async def _mark_once(session: AsyncSession, key: str) -> bool:
    """True exactly once per key: INSERT .. ON CONFLICT DO NOTHING."""
    stmt = pg_insert(SentNotification).values(key=key).on_conflict_do_nothing()
    res = cast(CursorResult[Any], await session.execute(stmt))
    return bool(res.rowcount)


async def _mark_exists(session: AsyncSession, key: str) -> bool:
    res = await session.execute(select(SentNotification.key).where(SentNotification.key == key))
    return res.scalar_one_or_none() is not None


async def _booked_or_moved_at(session: AsyncSession, appt: Appointment) -> dt.datetime | None:
    """When the client last saw this time: booking creation or the latest reschedule."""
    res = await session.execute(
        select(func.max(AppointmentHistory.created_at)).where(
            AppointmentHistory.appointment_id == appt.id,
            AppointmentHistory.action == "rescheduled",
        )
    )
    moved_at = res.scalar_one_or_none()
    candidates = [x for x in (appt.created_at, moved_at) if x is not None]
    return max(candidates) if candidates else None


async def _send_reminders(notifier: NotificationService) -> None:
    now = dt.datetime.now(settings.tz)
    # Narrowest window first: when several windows apply at once (e.g. the bot was down,
    # or the booking was just moved), the client gets one reminder, not two.
    windows = sorted(_reminder_windows().items(), key=lambda item: item[1])
    async with async_session_factory() as session:
        salon = await SalonRepository(session).get()
        address = (salon.address if salon else settings.salon_address) or "—"
        for index, (label, hours) in enumerate(windows):
            window = dt.timedelta(hours=hours)
            res = await session.execute(
                select(Appointment)
                .where(
                    Appointment.start_at > now,
                    Appointment.start_at <= now + window,
                    Appointment.status.in_(list(ACTIVE_STATUSES)),
                )
                .options(
                    selectinload(Appointment.service),
                    selectinload(Appointment.master).selectinload(Master.user),
                    selectinload(Appointment.client),
                )
            )
            for appt in res.scalars().all():
                start_ts = int(appt.start_at.timestamp())
                if await _mark_exists(session, f"remind:{appt.id}:{label}"):
                    continue  # already sent by a previous version of the bot
                # Keyed by start time too, so a rescheduled appointment is reminded again.
                if not await _mark_once(session, f"remind:{appt.id}:{label}:{start_ts}"):
                    continue
                for wider_label, _ in windows[index + 1 :]:  # covered by this reminder
                    await _mark_once(session, f"remind:{appt.id}:{wider_label}:{start_ts}")
                seen_at = await _booked_or_moved_at(session, appt)
                client = appt.client
                if (
                    (seen_at is not None and seen_at > appt.start_at - window)
                    # Booked/moved inside this window: the client has just seen the details.
                    or not is_real_chat(client.telegram_id)  # demo clients have no chat
                ):
                    await session.commit()
                    continue
                text = t(
                    "notify.client.reminder",
                    client.language,
                    service=appt.service.name,
                    master=appt.master.user.full_name or "-",
                    date=fmt_date(appt.start_at, client.language),
                    time=fmt_time(appt.start_at),
                    address=address,
                )
                await notifier.send_telegram(client.telegram_id, text)
                log.info("reminder.sent", appointment_id=appt.id, window=label)
                # Commit the marks right after sending: a later error must not roll them
                # back and make this reminder go out a second time.
                await session.commit()
        await session.commit()


async def _send_daily_digest(notifier: NotificationService) -> None:
    now = dt.datetime.now(settings.tz)
    if now.hour < DIGEST_HOUR:
        return
    day_start = dt.datetime.combine(now.date(), dt.time.min, tzinfo=settings.tz)
    day_end = day_start + dt.timedelta(days=1)
    async with async_session_factory() as session:
        if not await _mark_once(session, f"digest:{now.date().isoformat()}"):
            await session.rollback()
            return
        masters = (
            (
                await session.execute(
                    select(Master)
                    .where(Master.is_active.is_(True))
                    .options(selectinload(Master.user))
                )
            )
            .scalars()
            .all()
        )
        for master in masters:
            if not is_real_chat(master.user.telegram_id):  # demo masters
                continue
            res = await session.execute(
                select(Appointment)
                .where(
                    Appointment.master_id == master.id,
                    Appointment.start_at >= day_start,
                    Appointment.start_at < day_end,
                    Appointment.status.in_(list(ACTIVE_STATUSES)),
                )
                .order_by(Appointment.start_at)
                .options(selectinload(Appointment.service))
            )
            appts = res.scalars().all()
            if not appts:
                continue
            items = "\n".join(f"{fmt_time(a.start_at)} — {a.service.name}" for a in appts)
            await notifier.send_telegram(
                master.user.telegram_id,
                t("notify.master.daily", master.user.language, items=items),
            )
        await session.commit()


async def _complete_past_and_ask_reviews(notifier: NotificationService) -> None:
    now = dt.datetime.now(settings.tz)
    async with async_session_factory() as session:
        res = await session.execute(
            select(Appointment)
            .where(
                Appointment.end_at < now,
                Appointment.status.in_(list(ACTIVE_STATUSES)),
            )
            .options(
                selectinload(Appointment.master).selectinload(Master.user),
                selectinload(Appointment.client),
            )
        )
        for appt in res.scalars().all():
            appt.status = AppointmentStatus.completed
            if await _mark_once(session, f"review_ask:{appt.id}"):
                await session.commit()  # status + mark first, then the message
                client: User = appt.client
                if is_real_chat(client.telegram_id):
                    await notifier.send_telegram(
                        client.telegram_id,
                        t(
                            "review.ask",
                            client.language,
                            master=appt.master.user.full_name or "-",
                        ),
                        review_kb(appt.id, client.language),
                    )
        # Prune old idempotency marks.
        await session.execute(
            delete(SentNotification).where(
                SentNotification.created_at
                < dt.datetime.now(dt.UTC) - dt.timedelta(days=MARK_RETENTION_DAYS)
            )
        )
        await session.commit()


async def scheduler_loop(bot: Bot, sms: SMSProvider) -> None:
    notifier = NotificationService(bot, sms)
    log.info("scheduler.started", interval=CHECK_INTERVAL)
    jobs = (_send_reminders, _send_daily_digest, _complete_past_and_ask_reviews)
    while True:
        for job in jobs:  # independent: one failing job must not block the others
            try:
                await job(notifier)
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                log.error("scheduler.error", job=job.__name__, error=str(exc), exc_info=exc)
        await asyncio.sleep(CHECK_INTERVAL)
