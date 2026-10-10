"""Client 'My appointments': view, cancel, reschedule."""
from __future__ import annotations

import datetime as dt

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import ACTIVE_STATUSES, Appointment, User
from app.keyboards.builders import FREE_TEXT, dates_kb, master_new_appt_kb, my_appt_kb, times_kb
from app.keyboards.callbacks import ApptActionCb, DateCb, TimeCb
from app.locales import t, variants
from app.repositories.appointments import AppointmentRepository
from app.repositories.catalog import MasterRepository
from app.services.availability import AvailabilityService
from app.services.booking import (
    BookingService,
    NotActiveError,
    NotOwnerError,
    SlotTakenError,
    TooLateError,
)
from app.services.notifications import NotificationService
from app.states import CancelStates, RescheduleStates
from app.utils.format import fmt_date, fmt_time, to_local

router = Router(name="my_appointments")

DATE_CHOICES = 8
MAX_REASON_LEN = 500


def _is_upcoming_active(appt: Appointment) -> bool:
    return appt.status in ACTIVE_STATUSES and to_local(appt.start_at) > dt.datetime.now(settings.tz)


@router.message(F.text.in_(variants("menu.my")))
async def my_appointments(message: Message, user: User, session: AsyncSession) -> None:
    now = dt.datetime.now(settings.tz)
    appts = await AppointmentRepository(session).upcoming_for_client(user.id, now)
    if not appts:
        await message.answer(t("my.empty", user.language))
        return
    for a in appts:
        text = t(
            "my.item",
            user.language,
            service=a.service.name,
            master=a.master.user.full_name or "Мастер",
            date=fmt_date(a.start_at, user.language),
            time=fmt_time(a.start_at),
            status=t(f"status.{a.status.value}", user.language),
            price=int(a.price),
            currency=settings.currency,
        )
        await message.answer(text, reply_markup=my_appt_kb(a.id, user.language))


@router.callback_query(ApptActionCb.filter(F.action == "cancel"))
async def ask_cancel_reason(
    query: CallbackQuery, callback_data: ApptActionCb, user: User, session: AsyncSession, state: FSMContext
) -> None:
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    if appt is None or appt.client_id != user.id:
        await query.answer(t("error.not_owner", user.language), show_alert=True)
        return
    if not _is_upcoming_active(appt):
        await query.answer(t("appt.not_active", user.language), show_alert=True)
        return
    now = dt.datetime.now(settings.tz)
    if to_local(appt.start_at) - now < dt.timedelta(hours=settings.min_cancel_hours):
        await query.answer(
            t("my.cancel_too_late", user.language, hours=settings.min_cancel_hours), show_alert=True
        )
        return
    await state.set_state(CancelStates.entering_reason)
    await state.update_data(appointment_id=appt.id)
    await query.message.answer(t("my.cancel_reason", user.language))  # type: ignore[union-attr]
    await query.answer()


@router.message(CancelStates.entering_reason, FREE_TEXT)
async def do_cancel(
    message: Message, user: User, session: AsyncSession, state: FSMContext, notifier: NotificationService
) -> None:
    data = await state.get_data()
    appt = await AppointmentRepository(session).get(data["appointment_id"])
    if appt is None:
        await state.clear()
        return
    reason = (message.text or "").strip()[:MAX_REASON_LEN]
    booking = BookingService(session)
    try:
        await booking.cancel_by_client(appt, user, reason)
    except NotOwnerError:
        await message.answer(t("error.not_owner", user.language))
        await state.clear()
        return
    except NotActiveError:
        await message.answer(t("appt.not_active", user.language))
        await state.clear()
        return
    except TooLateError:
        await message.answer(t("my.cancel_too_late", user.language, hours=settings.min_cancel_hours))
        await state.clear()
        return
    await session.commit()
    await state.clear()
    await notifier.notify_master(
        appt.master,
        f"❌ Запись отменена клиентом: {appt.service.name}, "
        f"{fmt_date(appt.start_at)} {fmt_time(appt.start_at)}",
    )
    await notifier.notify_admins(
        f"🛠 Запись #{appt.id} отменена клиентом\n"
        f"Клиент: {appt.client.full_name or '-'} {appt.client.phone or '-'}\n"
        f"Услуга: {appt.service.name} · Мастер: {appt.master.user.full_name}\n"
        f"Было: {fmt_date(appt.start_at)} {fmt_time(appt.start_at)}\n"
        f"Причина: {reason}"
    )
    await message.answer(t("my.cancelled", user.language))


@router.callback_query(ApptActionCb.filter(F.action == "reschedule"))
async def start_reschedule(
    query: CallbackQuery,
    callback_data: ApptActionCb,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    if appt is None or appt.client_id != user.id:
        await query.answer(t("error.not_owner", user.language), show_alert=True)
        return
    if not _is_upcoming_active(appt):
        await query.answer(t("appt.not_active", user.language), show_alert=True)
        return
    if to_local(appt.start_at) - dt.datetime.now(settings.tz) < dt.timedelta(hours=settings.min_cancel_hours):
        await query.answer(
            t("my.reschedule_too_late", user.language, hours=settings.min_cancel_hours),
            show_alert=True,
        )
        return
    availability = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    today = dt.datetime.now(settings.tz).date()
    days: list[dt.date] = []
    for offset in range(DATE_CHOICES * 2):
        day = today + dt.timedelta(days=offset)
        if await availability.has_any_slot(appt.master, appt.service, day):
            days.append(day)
        if len(days) >= DATE_CHOICES:
            break
    if not days:
        await query.answer(t("book.no_slots", user.language), show_alert=True)
        return
    await state.set_state(RescheduleStates.choosing_date)
    await state.update_data(appointment_id=appt.id)
    await query.message.answer(t("book.choose_date", user.language), reply_markup=dates_kb(days, user.language))  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(RescheduleStates.choosing_date, DateCb.filter())
async def reschedule_pick_date(
    query: CallbackQuery,
    callback_data: DateCb,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    appt = await AppointmentRepository(session).get(data["appointment_id"])
    if appt is None:
        await query.answer()
        return
    try:
        day = dt.date.fromisoformat(callback_data.iso)
    except ValueError:
        await query.answer()
        return
    availability = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    slots = await availability.free_slots(appt.master, appt.service, day, holder_id=user.telegram_id)
    if not slots:
        await query.answer(t("book.no_slots", user.language), show_alert=True)
        return
    await state.set_state(RescheduleStates.choosing_time)
    await query.message.edit_text(t("book.choose_time", user.language), reply_markup=times_kb(slots, user.language))  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(RescheduleStates.choosing_time, TimeCb.filter())
async def reschedule_pick_time(
    query: CallbackQuery,
    callback_data: TimeCb,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    notifier: NotificationService,
) -> None:
    data = await state.get_data()
    appt = await AppointmentRepository(session).get(data["appointment_id"])
    if appt is None:
        await query.answer()
        return
    new_start = dt.datetime.fromtimestamp(callback_data.ts, tz=settings.tz)
    availability = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    if not await availability.is_bookable(appt.master, appt.service, new_start, holder_id=user.telegram_id):
        await query.answer(t("book.slot_taken", user.language), show_alert=True)
        return
    old_start = appt.start_at
    booking = BookingService(session)
    try:
        await booking.reschedule(appt, user, new_start, by_client=True)
    except NotOwnerError:
        await query.answer(t("error.not_owner", user.language), show_alert=True)
        return
    except NotActiveError:
        await state.clear()
        await query.answer(t("appt.not_active", user.language), show_alert=True)
        return
    except TooLateError:
        await state.clear()
        await query.answer(
            t("my.reschedule_too_late", user.language, hours=settings.min_cancel_hours),
            show_alert=True,
        )
        return
    except SlotTakenError:
        await query.answer(t("book.slot_taken", user.language), show_alert=True)
        return
    await session.commit()
    await state.clear()
    # The new time goes back to "pending": the master confirms or declines it again.
    await notifier.notify_master_rescheduled(
        appt, old_start, master_new_appt_kb(appt, appt.master.user.language)
    )
    await notifier.notify_admins(
        f"🛠 Запись #{appt.id} перенесена клиентом\n"
        f"Клиент: {appt.client.full_name or '-'} {appt.client.phone or '-'}\n"
        f"Услуга: {appt.service.name} · Мастер: {appt.master.user.full_name}\n"
        f"Новое время: {fmt_date(new_start)} {fmt_time(new_start)}"
    )
    await query.message.edit_text(t("my.rescheduled", user.language))  # type: ignore[union-attr]
    await query.answer()
