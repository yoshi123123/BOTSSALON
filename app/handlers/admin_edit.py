"""Admin appointment editing: view card (with phone & username), reschedule,
change master, change status, cancel. Every change notifies the client and all
configured admins."""
from __future__ import annotations

import datetime as dt

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import Appointment, AppointmentStatus, Master, Role, User
from app.keyboards.builders import dates_kb, times_kb
from app.keyboards.callbacks import AdminApptCb, AdminPickCb, DateCb, TimeCb
from app.locales import t
from app.repositories.appointments import AppointmentRepository
from app.repositories.catalog import MasterRepository
from app.services.availability import AvailabilityService
from app.services.booking import BookingService, SlotTakenError
from app.services.notifications import NotificationService
from app.states import AdminEditStates
from app.utils.format import fmt_date, fmt_time

router = Router(name="admin_edit")

DATE_CHOICES = 8


def _is_admin(user: User | None) -> bool:
    if user is None:
        return False
    return user.role in {Role.admin, Role.owner} or user.telegram_id in settings.admin_id_set


def _edit_kb(appointment_id: int, lang: str):
    b = InlineKeyboardBuilder()
    b.button(text=t("aedit.reschedule", lang),
             callback_data=AdminApptCb(appointment_id=appointment_id, action="reschedule"))
    b.button(text=t("aedit.master", lang),
             callback_data=AdminApptCb(appointment_id=appointment_id, action="master"))
    b.button(text=t("aedit.status", lang),
             callback_data=AdminApptCb(appointment_id=appointment_id, action="status"))
    b.button(text=t("aedit.cancel", lang),
             callback_data=AdminApptCb(appointment_id=appointment_id, action="cancel"))
    b.adjust(1)
    return b.as_markup()


async def _card_text(appt: Appointment, lang: str) -> str:
    return t(
        "aedit.card",
        lang,
        id=appt.id,
        service=appt.service.name,
        master=appt.master.user.full_name or "-",
        date=fmt_date(appt.start_at),
        time=fmt_time(appt.start_at),
        status=t(f"status.{appt.status.value}", lang),
        price=int(appt.price),
        currency=settings.currency,
        client=appt.client.full_name or "—",
        phone=appt.client.phone or "—",
        username=f"@{appt.client.username}" if appt.client.username else "—",
        comment=appt.client_comment or "—",
    )


async def _notify_change(
    notifier: NotificationService,
    appt: Appointment,
    what_admin: str,
    what_client: str,
    by: str,
) -> None:
    """Notify all admins + the client + the master about a change."""
    await notifier.notify_admins(
        t(
            "notify.admin.change",
            "ru",
            id=appt.id,
            by=by,
            what=what_admin,
            client=appt.client.full_name or "-",
            phone=appt.client.phone or "-",
            service=appt.service.name,
            master=appt.master.user.full_name or "-",
            date=fmt_date(appt.start_at),
            time=fmt_time(appt.start_at),
        )
    )
    if appt.client.telegram_id > 1000:  # skip demo clients
        await notifier.notify_client(
            appt.client.telegram_id,
            t(
                "notify.client.admin_changed",
                appt.client.language,
                what=what_client,
                service=appt.service.name,
                master=appt.master.user.full_name or "-",
                date=fmt_date(appt.start_at),
                time=fmt_time(appt.start_at),
            ),
        )
    if appt.master.telegram_notifications_enabled and appt.master.user.telegram_id > 1000:
        await notifier.notify_client(
            appt.master.user.telegram_id,
            f"🛠 #{appt.id}: {what_admin} — {fmt_date(appt.start_at)} {fmt_time(appt.start_at)}",
        )


@router.callback_query(AdminApptCb.filter(F.action == "view"))
async def view_card(
    query: CallbackQuery, callback_data: AdminApptCb, user: User, session: AsyncSession
) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    if appt is None:
        await query.answer(t("admin.empty", user.language), show_alert=True)
        return
    await query.message.answer(  # type: ignore[union-attr]
        await _card_text(appt, user.language),
        reply_markup=_edit_kb(appt.id, user.language),
    )
    await query.answer()


# ---------- reschedule ----------
@router.callback_query(AdminApptCb.filter(F.action == "reschedule"))
async def start_reschedule(
    query: CallbackQuery,
    callback_data: AdminApptCb,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    redis: Redis,
) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    if appt is None:
        await query.answer()
        return
    availability = AvailabilityService(
        MasterRepository(session), AppointmentRepository(session), redis
    )
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
    await state.set_state(AdminEditStates.choosing_date)
    await state.update_data(appointment_id=appt.id)
    await query.message.answer(  # type: ignore[union-attr]
        t("book.choose_date", user.language), reply_markup=dates_kb(days, user.language)
    )
    await query.answer()


@router.callback_query(AdminEditStates.choosing_date, DateCb.filter())
async def pick_date(
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
    availability = AvailabilityService(
        MasterRepository(session), AppointmentRepository(session), redis
    )
    slots = await availability.free_slots(appt.master, appt.service, day)
    if not slots:
        await query.answer(t("book.no_slots", user.language), show_alert=True)
        return
    await state.set_state(AdminEditStates.choosing_time)
    await query.message.edit_text(  # type: ignore[union-attr]
        t("book.choose_time", user.language), reply_markup=times_kb(slots, user.language)
    )
    await query.answer()


@router.callback_query(AdminEditStates.choosing_time, TimeCb.filter())
async def pick_time(
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
        await state.clear()
        await query.answer()
        return
    old = f"{fmt_date(appt.start_at)} {fmt_time(appt.start_at)}"
    new_start = dt.datetime.fromtimestamp(callback_data.ts, tz=settings.tz)
    try:
        await BookingService(session).reschedule(appt, user, new_start)
    except SlotTakenError:
        await query.answer(t("book.slot_taken", user.language), show_alert=True)
        return
    await session.flush()
    what = f"Перенос: {old} → {fmt_date(new_start)} {fmt_time(new_start)}"
    await _notify_change(notifier, appt, what, what, by="админ")
    await query.message.edit_text(t("aedit.done", user.language))  # type: ignore[union-attr]
    await state.clear()
    await query.answer()


# ---------- change master ----------
@router.callback_query(AdminApptCb.filter(F.action == "master"))
async def choose_master(
    query: CallbackQuery, callback_data: AdminApptCb, user: User, session: AsyncSession
) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    if appt is None:
        await query.answer()
        return
    masters = await MasterRepository(session).list_for_service(appt.service_id)
    b = InlineKeyboardBuilder()
    for m in masters:
        if m.id == appt.master_id:
            continue
        b.button(
            text=f"{m.user.full_name} ⭐{float(m.rating)}",
            callback_data=AdminPickCb(appointment_id=appt.id, kind="master", value=str(m.id)),
        )
    b.adjust(1)
    await query.message.answer(  # type: ignore[union-attr]
        t("aedit.pick_master", user.language), reply_markup=b.as_markup()
    )
    await query.answer()


@router.callback_query(AdminPickCb.filter(F.kind == "master"))
async def set_master(
    query: CallbackQuery,
    callback_data: AdminPickCb,
    user: User,
    session: AsyncSession,
    notifier: NotificationService,
) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    new_master = await MasterRepository(session).get(int(callback_data.value))
    if appt is None or new_master is None:
        await query.answer()
        return
    ms = await MasterRepository(session).master_service(new_master.id, appt.service_id)
    if ms is None or not ms.is_active:
        await query.answer(t("aedit.master_cant", user.language), show_alert=True)
        return
    # Ensure the target master is free at this time.
    repo = AppointmentRepository(session)
    overlapping = await repo.overlapping_active(new_master.id, appt.start_at, appt.end_at)
    if overlapping:
        await query.answer(t("book.slot_taken", user.language), show_alert=True)
        return
    old_name = appt.master.user.full_name or "-"
    appt.master_id = new_master.id
    await repo.add_history(appt.id, user.id, "master_changed", old_name,
                           new_master.user.full_name or "-")
    await session.flush()
    # reload relationships
    appt = await repo.get(appt.id)
    what = f"Смена мастера: {old_name} → {new_master.user.full_name}"
    await _notify_change(notifier, appt, what, what, by="админ")
    await query.message.edit_text(t("aedit.done", user.language))  # type: ignore[union-attr]
    await query.answer()


# ---------- change status ----------
_STATUS_CHOICES = [
    AppointmentStatus.pending,
    AppointmentStatus.confirmed,
    AppointmentStatus.completed,
    AppointmentStatus.no_show,
]


@router.callback_query(AdminApptCb.filter(F.action == "status"))
async def choose_status(
    query: CallbackQuery, callback_data: AdminApptCb, user: User, session: AsyncSession
) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    b = InlineKeyboardBuilder()
    for st in _STATUS_CHOICES:
        b.button(
            text=t(f"status.{st.value}", user.language),
            callback_data=AdminPickCb(
                appointment_id=callback_data.appointment_id, kind="status", value=st.value
            ),
        )
    b.adjust(2)
    await query.message.answer(  # type: ignore[union-attr]
        t("aedit.pick_status", user.language), reply_markup=b.as_markup()
    )
    await query.answer()


@router.callback_query(AdminPickCb.filter(F.kind == "status"))
async def set_status(
    query: CallbackQuery,
    callback_data: AdminPickCb,
    user: User,
    session: AsyncSession,
    notifier: NotificationService,
) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    if appt is None:
        await query.answer()
        return
    new_status = AppointmentStatus(callback_data.value)
    old = t(f"status.{appt.status.value}", user.language)
    await BookingService(session).set_status(appt, new_status, user)
    await session.flush()
    what = f"Статус: {old} → {t(f'status.{new_status.value}', user.language)}"
    await _notify_change(notifier, appt, what, what, by="админ")
    await query.message.edit_text(t("aedit.done", user.language))  # type: ignore[union-attr]
    await query.answer()


# ---------- cancel ----------
@router.callback_query(AdminApptCb.filter(F.action == "cancel"))
async def cancel_appt(
    query: CallbackQuery,
    callback_data: AdminApptCb,
    user: User,
    session: AsyncSession,
    notifier: NotificationService,
) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    if appt is None:
        await query.answer()
        return
    await BookingService(session).set_status(
        appt, AppointmentStatus.cancelled_by_admin, user, "отменено администратором"
    )
    await session.flush()
    what = t("aedit.cancelled", user.language)
    await _notify_change(notifier, appt, what, what, by="админ")
    await query.message.edit_text(t("aedit.cancelled", user.language))  # type: ignore[union-attr]
    await query.answer()
