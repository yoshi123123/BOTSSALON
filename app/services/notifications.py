"""Notification dispatch to masters and clients via Telegram (primary) and SMS."""
from __future__ import annotations

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

from app.config import settings
from app.db.models import Appointment, Master
from app.integrations.sms.provider import SMSProvider
from app.locales import t
from app.utils.format import fmt_date, fmt_time

log = structlog.get_logger(__name__)


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
        try:
            await self.bot.send_message(telegram_id, text, reply_markup=markup)
            return True
        except TelegramForbiddenError:
            log.info("notify.tg.blocked", telegram_id=telegram_id)
            return False
        except TelegramBadRequest as exc:
            log.warning("notify.tg.bad_request", error=str(exc))
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
            date=fmt_date(appointment.start_at),
            time=fmt_time(appointment.start_at),
            duration=int((appointment.end_at - appointment.start_at).total_seconds() // 60),
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
            await self.sms.send(master.sms_phone, sms_text)

    async def notify_client(
        self, telegram_id: int, text: str, markup: InlineKeyboardMarkup | None = None
    ) -> None:
        await self.send_telegram(telegram_id, text, markup)
