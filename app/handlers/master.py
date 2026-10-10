"""Master-side handlers: confirm / decline incoming appointments, daily schedule."""
from __future__ import annotations

import datetime as dt

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AppointmentStatus, User
from app.keyboards.callbacks import MasterApptCb
from app.locales import t
from app.repositories.appointments import AppointmentRepository
from app.repositories.catalog import MasterRepository
from app.services.booking import BookingService
from app.services.notifications import NotificationService
from app.states import MasterDeclineStates
from app.utils.format import fmt_date, fmt_time

router = Router(name="master")


async def _ensure_master(session: AsyncSession, user: User):
    return await MasterRepository(session).get_by_user_telegram_id(user.telegram_id)


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
    await BookingService(session).set_status(appt, AppointmentStatus.confirmed, user)
    await session.flush()
    await notifier.notify_client(
        appt.client.telegram_id,
        t("notify.client.confirmed", appt.client.language, date=fmt_date(appt.start_at), time=fmt_time(appt.start_at)),
    )
    await query.message.edit_text(  # type: ignore[union-attr]
        (query.message.text or "") + "\n\n✅ Подтверждено"
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
    await state.set_state(MasterDeclineStates.reason)
    await state.update_data(appointment_id=appt.id)
    await query.message.answer(t("notify.master.decline_reason", user.language))  # type: ignore[union-attr]
    await query.answer()


@router.message(MasterDeclineStates.reason, F.text)
async def master_decline_reason(
    message: Message, user: User, session: AsyncSession, state: FSMContext, notifier: NotificationService
) -> None:
    data = await state.get_data()
    appt = await AppointmentRepository(session).get(data["appointment_id"])
    if appt is None:
        await state.clear()
        return
    reason = message.text.strip()
    await BookingService(session).set_status(
        appt, AppointmentStatus.cancelled_by_master, user, reason
    )
    await session.flush()
    await notifier.notify_client(
        appt.client.telegram_id,
        t(
            "notify.client.declined",
            appt.client.language,
            date=fmt_date(appt.start_at),
            time=fmt_time(appt.start_at),
            reason=reason,
        ),
    )
    await message.answer(t("done", user.language))
    await state.clear()
