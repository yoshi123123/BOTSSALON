"""Master-side handlers: confirm / decline incoming appointments."""
from __future__ import annotations

import contextlib

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ACTIVE_STATUSES, Appointment, AppointmentStatus, Master, User
from app.keyboards.builders import FREE_TEXT
from app.keyboards.callbacks import MasterApptCb
from app.locales import t
from app.repositories.appointments import AppointmentRepository
from app.repositories.catalog import MasterRepository
from app.services.booking import BookingService, NotActiveError, SlotTakenError
from app.services.notifications import NotificationService
from app.states import MasterDeclineStates
from app.utils.format import fmt_date, fmt_time

router = Router(name="master")

MAX_REASON_LEN = 500


async def _ensure_master(session: AsyncSession, user: User) -> Master | None:
    return await MasterRepository(session).get_by_user_telegram_id(user.telegram_id)


def _status_text(appt: Appointment, lang: str) -> str:
    return t("appt.status_now", lang, status=t(f"status.{appt.status.value}", lang))


def _moved_text(appt: Appointment, lang: str) -> str:
    return t("appt.moved", lang, date=fmt_date(appt.start_at, lang), time=fmt_time(appt.start_at))


async def _drop_buttons(query: CallbackQuery) -> None:
    with contextlib.suppress(TelegramBadRequest):
        await query.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]


@router.callback_query(MasterApptCb.filter(F.action == "confirm"))
async def master_confirm(
    query: CallbackQuery,
    callback_data: MasterApptCb,
    user: User,
    session: AsyncSession,
    notifier: NotificationService,
) -> None:
    master = await _ensure_master(session, user)
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    if master is None or appt is None or appt.master_id != master.id:
        await query.answer(t("error.not_owner", user.language), show_alert=True)
        return
    if int(appt.start_at.timestamp()) != callback_data.ts:
        # An old notification: the client has moved the booking since.
        await query.answer(_moved_text(appt, user.language), show_alert=True)
        await _drop_buttons(query)
        return
    try:
        # Only a still-pending booking can be confirmed; checked on the locked row, so a
        # cancellation that lands at the same moment wins.
        await BookingService(session).set_status(
            appt, AppointmentStatus.confirmed, user, allowed_from={AppointmentStatus.pending}
        )
    except (NotActiveError, SlotTakenError):
        await query.answer(_status_text(appt, user.language), show_alert=True)
        await _drop_buttons(query)
        return
    await session.commit()
    await notifier.notify_client(
        appt.client.telegram_id,
        t(
            "notify.client.confirmed",
            appt.client.language,
            date=fmt_date(appt.start_at, appt.client.language),
            time=fmt_time(appt.start_at),
        ),
    )
    with contextlib.suppress(TelegramBadRequest):
        await query.message.edit_text(  # type: ignore[union-attr]
            (query.message.text or "") + "\n\n✅ Подтверждено"  # type: ignore[union-attr]
        )
    await query.answer()


@router.callback_query(MasterApptCb.filter(F.action == "decline"))
async def master_decline_start(
    query: CallbackQuery, callback_data: MasterApptCb, user: User, session: AsyncSession, state: FSMContext
) -> None:
    master = await _ensure_master(session, user)
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    if master is None or appt is None or appt.master_id != master.id:
        await query.answer(t("error.not_owner", user.language), show_alert=True)
        return
    if int(appt.start_at.timestamp()) != callback_data.ts:
        await query.answer(_moved_text(appt, user.language), show_alert=True)
        await _drop_buttons(query)
        return
    if appt.status not in ACTIVE_STATUSES:
        await query.answer(_status_text(appt, user.language), show_alert=True)
        await _drop_buttons(query)
        return
    await state.set_state(MasterDeclineStates.reason)
    await state.update_data(appointment_id=appt.id, ts=callback_data.ts)
    await query.message.answer(t("notify.master.decline_reason", user.language))  # type: ignore[union-attr]
    await query.answer()


@router.message(MasterDeclineStates.reason, FREE_TEXT)
async def master_decline_reason(
    message: Message, user: User, session: AsyncSession, state: FSMContext, notifier: NotificationService
) -> None:
    data = await state.get_data()
    await state.clear()
    master = await _ensure_master(session, user)
    appt = await AppointmentRepository(session).get(data["appointment_id"])
    if master is None or appt is None or appt.master_id != master.id:
        await message.answer(t("error.not_owner", user.language))
        return
    if int(appt.start_at.timestamp()) != data.get("ts"):
        await message.answer(_moved_text(appt, user.language))
        return
    reason = (message.text or "").strip()[:MAX_REASON_LEN]
    try:
        await BookingService(session).set_status(
            appt, AppointmentStatus.cancelled_by_master, user, reason, allowed_from=ACTIVE_STATUSES
        )
    except (NotActiveError, SlotTakenError):
        await message.answer(_status_text(appt, user.language))
        return
    await session.commit()
    await notifier.notify_client(
        appt.client.telegram_id,
        t(
            "notify.client.declined",
            appt.client.language,
            date=fmt_date(appt.start_at, appt.client.language),
            time=fmt_time(appt.start_at),
            reason=reason,
        ),
    )
    await notifier.notify_admins(
        f"🛠 Запись #{appt.id} отклонена мастером {appt.master.user.full_name or '-'}\n"
        f"Клиент: {appt.client.full_name or '-'} {appt.client.phone or '-'}\n"
        f"Было: {fmt_date(appt.start_at)} {fmt_time(appt.start_at)}\n"
        f"Причина: {reason}"
    )
    await message.answer(t("done", user.language))
