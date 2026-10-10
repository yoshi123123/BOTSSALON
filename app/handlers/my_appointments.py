"""Client 'My appointments': view, cancel, reschedule."""
from __future__ import annotations

import datetime as dt

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AppointmentStatus, User
from app.keyboards.builders import dates_kb, my_appt_kb, times_kb
from app.keyboards.callbacks import ApptActionCb, DateCb, TimeCb
from app.locales import t
from app.repositories.appointments import AppointmentRepository
from app.repositories.catalog import MasterRepository, ServiceRepository
from app.services.availability import AvailabilityService
from app.services.booking import BookingService, NotOwnerError, SlotTakenError, TooLateError
from app.services.notifications import NotificationService
from app.states import CancelStates, RescheduleStates
from app.utils.format import fmt_date, fmt_time

router = Router(name="my_appointments")

DATE_CHOICES = 8


@router.message(F.text.in_({t("menu.my", "ru"), t("menu.my", "ro"), t("menu.my", "en")}))
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
            date=fmt_date(a.start_at),
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
    now = dt.datetime.now(settings.tz)
    if appt.start_at - now < dt.timedelta(hours=settings.min_cancel_hours):
        await query.answer(
            t("my.cancel_too_late", user.language, hours=settings.min_cancel_hours), show_alert=True
        )
        return
    await state.set_state(CancelStates.entering_reason)
    await state.update_data(appointment_id=appt.id)
    await query.message.answer(t("my.cancel_reason", user.language))  # type: ignore[union-attr]
    await query.answer()


@router.message(CancelStates.entering_reason, F.text)
async def do_cancel(
    message: Message, user: User, session: AsyncSession, state: FSMContext, notifier: NotificationService
) -> None:
    data = await state.get_data()
    appt = await AppointmentRepository(session).get(data["appointment_id"])
    if appt is None:
        await state.clear()
        return
    booking = BookingService(session)
    try:
        await booking.cancel_by_client(appt, user, message.text.strip())
    except NotOwnerError:
        await message.answer(t("error.not_owner", user.language))
        await state.clear()
        return
    except TooLateError:
        await message.answer(t("my.cancel_too_late", user.language, hours=settings.min_cancel_hours))
        await state.clear()
        return
    await session.flush()
    if appt.master.telegram_notifications_enabled:
        await notifier.notify_client(
            appt.master.user.telegram_id,
            f"❌ Запись отменена клиентом: {fmt_date(appt.start_at)} {fmt_time(appt.start_at)}",
        )
    await message.answer(t("my.cancelled", user.language))
    await state.clear()


@router.callback_query(ApptActionCb.filter(F.action == "reschedule"))
async def start_reschedule(
    query: CallbackQuery,
    callback_data: ApptActionCb,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    redis: Redis,
) -> None:
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    if appt is None or appt.client_id != user.id:
        await query.answer(t("error.not_owner", user.language), show_alert=True)
        return
    availability = AvailabilityService(MasterRepository(session), AppointmentRepository(session), redis)
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
    redis: Redis,
) -> None:
    data = await state.get_data()
    appt = await AppointmentRepository(session).get(data["appointment_id"])
    if appt is None:
        await query.answer()
        return
    day = dt.date.fromisoformat(callback_data.iso)
    availability = AvailabilityService(MasterRepository(session), AppointmentRepository(session), redis)
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
    booking = BookingService(session)
    try:
        await booking.reschedule(appt, user, new_start)
    except (NotOwnerError,):
        await query.answer(t("error.not_owner", user.language), show_alert=True)
        return
    except SlotTakenError:
        await query.answer(t("book.slot_taken", user.language), show_alert=True)
        return
    await session.flush()
    if appt.master.telegram_notifications_enabled:
        await notifier.notify_client(
            appt.master.user.telegram_id,
            f"🔄 Запись перенесена: {fmt_date(new_start)} {fmt_time(new_start)}",
        )
    await query.message.edit_text(t("my.rescheduled", user.language))  # type: ignore[union-attr]
    await state.clear()
    await query.answer()
