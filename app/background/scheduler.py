"""In-process background scheduler: reminders, auto-completion, review prompts.

Runs as an asyncio task inside the bot process, so no separate worker service
is required on the hosting. Redis keys make each notification idempotent
(sent once, survives restarts).

Every CHECK_INTERVAL seconds it:
  1. Sends client reminders 24h and 2h before active appointments.
  2. Sends a morning digest (once per day) to each master with today's bookings.
  3. Marks past confirmed/pending appointments as completed and asks the
     client to leave a review.
"""
from __future__ import annotations

import asyncio
import datetime as dt

import structlog
from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.base import async_session_factory
from app.db.models import (
    ACTIVE_STATUSES,
    Appointment,
    AppointmentStatus,
    Master,
    User,
)
from app.integrations.sms.provider import SMSProvider
from app.keyboards.builders import review_kb
from app.locales import t
from app.repositories.users import SalonRepository
from app.services.notifications import NotificationService
from app.utils.format import fmt_date, fmt_time

log = structlog.get_logger(__name__)

CHECK_INTERVAL = 300  # seconds (5 min)
REMINDER_WINDOWS = {"24h": 24, "2h": 2}
DIGEST_HOUR = 8  # local time


async def _mark_once(redis: Redis, key: str, ttl: int) -> bool:
    """Return True if this is the first time we see the key (SET NX)."""
    return bool(await redis.set(key, "1", ex=ttl, nx=True))


async def _send_reminders(notifier: NotificationService, redis: Redis) -> None:
    now = dt.datetime.now(settings.tz)
    async with async_session_factory() as session:
        salon = await SalonRepository(session).get()
        address = (salon.address if salon else settings.salon_address) or "—"
        for label, hours in REMINDER_WINDOWS.items():
            lo = now
            hi = now + dt.timedelta(hours=hours)
            res = await session.execute(
                select(Appointment)
                .where(
                    Appointment.start_at > lo,
                    Appointment.start_at <= hi,
                    Appointment.status.in_(list(ACTIVE_STATUSES)),
                )
                .options(
                    selectinload(Appointment.service),
                    selectinload(Appointment.master).selectinload(Master.user),
                    selectinload(Appointment.client),
                )
            )
            for appt in res.scalars().all():
                key = f"remind:{appt.id}:{label}"
                if not await _mark_once(redis, key, ttl=hours * 3600 + 3600):
                    continue
                client = appt.client
                text = t(
                    "notify.client.reminder",
                    client.language,
                    service=appt.service.name,
                    master=appt.master.user.full_name or "-",
                    date=fmt_date(appt.start_at),
                    time=fmt_time(appt.start_at),
                    address=address,
                )
                await notifier.send_telegram(client.telegram_id, text)
                log.info("reminder.sent", appointment_id=appt.id, window=label)


async def _send_daily_digest(notifier: NotificationService, redis: Redis) -> None:
    now = dt.datetime.now(settings.tz)
    if now.hour < DIGEST_HOUR:
        return
    day_key = f"digest:{now.date().isoformat()}"
    if not await _mark_once(redis, day_key, ttl=86400):
        return
    day_start = dt.datetime.combine(now.date(), dt.time.min, tzinfo=settings.tz)
    day_end = day_start + dt.timedelta(days=1)
    async with async_session_factory() as session:
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


async def _complete_past_and_ask_reviews(
    notifier: NotificationService, redis: Redis
) -> None:
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
            await session.flush()
            key = f"review_ask:{appt.id}"
            if await _mark_once(redis, key, ttl=7 * 86400):
                client: User = appt.client
                # Skip demo clients without real telegram ids
                if client.telegram_id > 1000:
                    await notifier.send_telegram(
                        client.telegram_id,
                        t(
                            "review.ask",
                            client.language,
                            master=appt.master.user.full_name or "-",
                        ),
                        review_kb(appt.id, client.language),
                    )
        await session.commit()


async def scheduler_loop(bot: Bot, redis: Redis, sms: SMSProvider) -> None:
    notifier = NotificationService(bot, sms)
    log.info("scheduler.started", interval=CHECK_INTERVAL)
    while True:
        try:
            await _send_reminders(notifier, redis)
            await _send_daily_digest(notifier, redis)
            await _complete_past_and_ask_reviews(notifier, redis)
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            log.error("scheduler.error", error=str(exc))
        await asyncio.sleep(CHECK_INTERVAL)
