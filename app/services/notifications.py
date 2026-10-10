"""Notification dispatch to masters and clients via Telegram (primary) and SMS."""
from __future__ import annotations

import asyncio
import datetime as dt

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from app.config import settings
from app.db.models import Appointment, Master
from app.integrations.sms.provider import SMSProvider
from app.locales import t
from app.utils.format import fmt_date, fmt_time

log = structlog.get_logger(__name__)

# Demo users created by app.seed use tiny fake telegram ids; there is no chat to write to.
DEMO_TG_ID_MAX = 1000
MAX_RETRY_AFTER = 30  # seconds we are willing to wait on a flood-control response


def is_real_chat(telegram_id: int | None) -> bool:
    # Negative ids are group chats (allowed as ADMIN_IDS targets for notifications).
    return telegram_id is not None and (telegram_id > DEMO_TG_ID_MAX or telegram_id < 0)


class NotificationService:
    def __init__(self, bot: Bot, sms: SMSProvider) -> None:
        self.bot = bot
        self.sms = sms

    async def send_telegram(
        self,
        telegram_id: int,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        """Best effort: never raises, so a failed notification can't undo a booking."""
        if not is_real_chat(telegram_id):
            return False
        for attempt in (1, 2):
            try:
                await self.bot.send_message(telegram_id, text, reply_markup=markup)
                return True
            except TelegramRetryAfter as exc:
                if attempt == 2 or exc.retry_after > MAX_RETRY_AFTER:
                    log.warning("notify.tg.flood", telegram_id=telegram_id, retry_after=exc.retry_after)
                    return False
                await asyncio.sleep(exc.retry_after)
            except TelegramForbiddenError:
                log.info("notify.tg.blocked", telegram_id=telegram_id)
                return False
            except TelegramAPIError as exc:
                log.warning("notify.tg.failed", telegram_id=telegram_id, error=str(exc))
                return False
            except Exception as exc:  # noqa: BLE001 - e.g. timeouts outside aiogram's wrapper
                log.warning("notify.tg.error", telegram_id=telegram_id, error=str(exc))
                return False
        return False

    async def send_sms(self, phone: str, text: str) -> bool:
        try:
            return await self.sms.send(phone, text)
        except Exception as exc:  # noqa: BLE001 - SMS must never break the flow
            log.warning("notify.sms.error", error=str(exc))
            return False

    async def notify_master_new(
        self, appointment: Appointment, markup: InlineKeyboardMarkup | None
    ) -> None:
        master: Master = appointment.master
        lang = master.user.language
        text = t(
            "notify.master.new",
            lang,
            client=appointment.client.full_name or "-",
            phone=appointment.client.phone or "-",
            service=appointment.service.name,
            date=fmt_date(appointment.start_at, lang),
            time=fmt_time(appointment.start_at),
            duration=int((appointment.end_at - appointment.start_at).total_seconds() // 60)
            - (appointment.service.buffer_minutes or 0),
            price=int(appointment.price),
            currency=settings.currency,
            comment=appointment.client_comment or "—",
        )
        if master.telegram_notifications_enabled:
            await self.send_telegram(master.user.telegram_id, text, markup)
        if master.sms_notifications_enabled and master.sms_phone:
            sms_text = (
                f"Новая запись: {appointment.client.full_name}, "
                f"{appointment.service.name}, {fmt_date(appointment.start_at)} в "
                f"{fmt_time(appointment.start_at)}. Тел: {appointment.client.phone}"
            )
            await self.send_sms(master.sms_phone, sms_text)

    async def notify_master_rescheduled(
        self, appointment: Appointment, old_start: dt.datetime, markup: InlineKeyboardMarkup | None
    ) -> None:
        master: Master = appointment.master
        text = t(
            "notify.master.rescheduled",
            master.user.language,
            client=appointment.client.full_name or "-",
            phone=appointment.client.phone or "-",
            service=appointment.service.name,
            old=f"{fmt_date(old_start, master.user.language)} {fmt_time(old_start)}",
            date=fmt_date(appointment.start_at, master.user.language),
            time=fmt_time(appointment.start_at),
        )
        if master.telegram_notifications_enabled:
            await self.send_telegram(master.user.telegram_id, text, markup)

    async def notify_master(self, master: Master, text: str) -> None:
        """Plain service message to a master, respecting their notification setting."""
        if master.telegram_notifications_enabled:
            await self.send_telegram(master.user.telegram_id, text)

    async def notify_client(
        self, telegram_id: int, text: str, markup: InlineKeyboardMarkup | None = None
    ) -> None:
        await self.send_telegram(telegram_id, text, markup)

    async def notify_admins(self, text: str) -> None:
        """Send a service message to every configured admin (ADMIN_IDS)."""
        for admin_id in settings.admin_id_set:
            await self.send_telegram(admin_id, text)
