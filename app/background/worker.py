"""Arq worker: reminders and daily master digests.

Reminders are stored in Redis (Arq's job queue), so scheduled jobs survive a
restart. A cron job runs every 10 minutes and sends reminders for appointments
that fall into the reminder windows and have not yet been reminded.
"""
from __future__ import annotations

import datetime as dt

import structlog
from aiogram import Bot
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.base import async_session_factory
from app.db.models import ACTIVE_STATUSES, Appointment, Master, User
from app.integrations.sms.provider import build_sms_provider
from app.locales import t
from app.repositories.users import SalonRepository
from app.services.notifications import NotificationService
from app.utils.format import fmt_date, fmt_time

log = structlog.get_logger(__name__)

# Redis keys used to mark that a reminder was already sent (idempotency).
_REMIND_PREFIX = "reminded"


def _remind_key(appointment_id: int, window: str) -> str:
    return f"{_REMIND_PREFIX}:{appointment_id}:{window}"


async def send_reminders(ctx: dict) -> None:
    bot: Bot = ctx["bot"]
    redis = ctx["redis"]
    sms = build_sms_provider()
    notifier = NotificationService(bot, sms)
    now = dt.datetime.now(settings.tz)

    windows = {
        "24h": settings.reminder_hours_before,
        "2h": settings.reminder_hours_before_2,
    }
    async with async_session_factory() as session:
        salon = await SalonRepository(session).get()
        address = (salon.address if salon else settings.salon_address) or "—"
        for label, hours in windows.items():
            target = now + dt.timedelta(hours=hours)
            lo = target - dt.timedelta(minutes=10)
            hi = target + dt.timedelta(minutes=10)
            res = await session.execute(
                select(Appointment)
                .where(
                    and_(
                        Appointment.start_at >= lo,
                        Appointment.start_at <= hi,
                        Appointment.status.in_(list(ACTIVE_STATUSES)),
                    )
                )
                .options(selectinload(Appointment.service))
            )
            for appt in res.scalars().all():
                key = _remind_key(appt.id, label)
                if await redis.get(key):
                    continue
                client = await session.get(User, appt.client_id)
                master = await session.get(Master, appt.master_id)
                if client is None or master is None:
                    continue
                master_name = master.user.full_name or "-"
                text = t(
                    "notify.client.reminder",
                    client.language,
                    service=appt.service.name,
                    master=master_name,
                    date=fmt_date(appt.start_at),
                    time=fmt_time(appt.start_at),
                    address=address,
                )
                await notifier.send_telegram(client.telegram_id, text)
                await redis.set(key, "1", ex=hours * 3600 + 3600)
                log.info("reminder.sent", appointment_id=appt.id, window=label)


async def send_daily_master_digest(ctx: dict) -> None:
    """Morning digest: today's appointments for each master."""
    bot: Bot = ctx["bot"]
    sms = build_sms_provider()
    notifier = NotificationService(bot, sms)
    now = dt.datetime.now(settings.tz)
    day_start = dt.datetime.combine(now.date(), dt.time.min, tzinfo=settings.tz)
    day_end = day_start + dt.timedelta(days=1)

    async with async_session_factory() as session:
        masters = (
            await session.execute(
                select(Master).where(Master.is_active.is_(True)).options(selectinload(Master.user))
            )
        ).scalars().all()
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
            lang = master.user.language
            await notifier.send_telegram(master.user.telegram_id, t("notify.master.daily", lang, items=items))


async def startup(ctx: dict) -> None:
    ctx["bot"] = Bot(token=settings.bot_token)
    log.info("worker.startup")


async def shutdown(ctx: dict) -> None:
    await ctx["bot"].session.close()
    log.info("worker.shutdown")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = startup
    on_shutdown = shutdown
    functions = [send_reminders, send_daily_master_digest]
    cron_jobs = [
        cron(send_reminders, minute=set(range(0, 60, 10))),
        cron(send_daily_master_digest, hour={8}, minute={0}),
    ]
