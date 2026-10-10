"""Client booking flow (FSM): service -> master -> date -> time -> contact -> confirm."""
from __future__ import annotations

import datetime as dt
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Contact, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User
from app.keyboards.builders import (
    FREE_TEXT,
    comment_skip_kb,
    confirm_kb,
    contact_request,
    dates_kb,
    main_menu,
    master_card_kb,
    master_mode_kb,
    master_new_appt_kb,
    portfolio_kb,
    services_kb,
    times_kb,
)
from app.keyboards.callbacks import (
    ConfirmCb,
    DateCb,
    MasterCb,
    MasterModeCb,
    PortfolioCb,
    ServiceCb,
    SkipCb,
    TimeCb,
)
from app.locales import t, variants
from app.repositories.appointments import AppointmentRepository
from app.repositories.catalog import MasterRepository, ServiceRepository
from app.repositories.users import SalonRepository, UserRepository
from app.services.availability import AvailabilityService
from app.services.booking import BookingService, SlotTakenError, UnavailableError
from app.services.matching import MatchingService
from app.services.notifications import NotificationService
from app.services.slot_hold import SlotHoldService
from app.states import BookingStates
from app.utils.format import chunk_text, fmt_date, fmt_time, stars

router = Router(name="booking")

DATE_CHOICES = 8  # number of upcoming days offered
MAX_COMMENT_LEN = 500
PHONE_RE = re.compile(r"^\+?[\d\s\-()]{6,20}$")


def normalize_phone(raw: str) -> str | None:
    """Accept '+373 60 123-456' style input; return None if it is not a phone number."""
    raw = raw.strip()
    if not PHONE_RE.fullmatch(raw):
        return None
    digits = re.sub(r"\D", "", raw)
    if not 6 <= len(digits) <= 15:
        return None
    return ("+" if raw.startswith("+") else "") + digits


@router.message(F.text.in_(variants("menu.book")))
async def start_booking(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    services = await ServiceRepository(session).list_active()
    if not services:
        await message.answer(t("book.no_masters", user.language))
        return
    await _release_hold(state, user)
    await state.clear()
    await state.set_state(BookingStates.choosing_service)
    await message.answer(
        t("book.choose_service", user.language),
        reply_markup=services_kb(services, user.language),
    )


@router.callback_query(BookingStates.choosing_service, ServiceCb.filter())
async def chose_service(
    query: CallbackQuery,
    callback_data: ServiceCb,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    service = await ServiceRepository(session).get(callback_data.service_id)
    if service is None or not service.is_active:
        await query.answer(t("book.no_masters", user.language), show_alert=True)
        return
    await state.update_data(service_id=service.id)
    await state.set_state(BookingStates.choosing_master_mode)
    await query.message.edit_text(  # type: ignore[union-attr]
        t("book.choose_master_mode", user.language), reply_markup=master_mode_kb(user.language)
    )
    await query.answer()


@router.callback_query(BookingStates.choosing_master_mode, MasterModeCb.filter())
async def chose_mode(
    query: CallbackQuery,
    callback_data: MasterModeCb,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    service = await ServiceRepository(session).get(data["service_id"])
    if service is None:
        await query.answer()
        return
    master_repo = MasterRepository(session)
    appt_repo = AppointmentRepository(session)
    availability = AvailabilityService(master_repo, appt_repo)

    if callback_data.mode == "self":
        masters = await master_repo.list_for_service(service.id)
        if not masters:
            await query.message.edit_text(t("book.no_masters", user.language))  # type: ignore[union-attr]
            await query.answer()
            return
        await state.set_state(BookingStates.choosing_master)
        await query.message.delete()  # type: ignore[union-attr]
        for master in masters:
            ms = await master_repo.master_service(master.id, service.id)
            price = master_repo.effective_price(ms, service)
            text = t(
                "master.card",
                user.language,
                name=master.user.full_name or "Мастер",
                spec=master.specialization or "—",
                exp=master.experience_years,
                rating=float(master.rating),
                reviews=master.review_count,
                price=int(price),
                currency=settings.currency,
            )
            await query.message.answer(text, reply_markup=master_card_kb(master, user.language))  # type: ignore[union-attr]
        await query.answer()
        return

    # auto modes
    mode = "best" if callback_data.mode == "auto_best" else "soonest"
    matching = MatchingService(master_repo, availability)
    result = await matching.match(service, mode)
    if result is None:
        await query.message.edit_text(t("book.no_slots", user.language))  # type: ignore[union-attr]
        await query.answer()
        return
    master, _slot = result
    await state.update_data(master_id=master.id)
    await _offer_dates(query.message, user, master.id, service.id, session, state)  # type: ignore[arg-type]
    await query.answer()


@router.callback_query(MasterCb.filter(F.action == "portfolio"))
async def show_portfolio(
    query: CallbackQuery, callback_data: MasterCb, user: User, session: AsyncSession
) -> None:
    await _render_portfolio(query, callback_data.master_id, 0, user, session)


@router.callback_query(PortfolioCb.filter())
async def paginate_portfolio(
    query: CallbackQuery, callback_data: PortfolioCb, user: User, session: AsyncSession
) -> None:
    await _render_portfolio(query, callback_data.master_id, callback_data.index, user, session)


async def _render_portfolio(
    query: CallbackQuery, master_id: int, index: int, user: User, session: AsyncSession
) -> None:
    items = await MasterRepository(session).portfolio(master_id)
    if not items:
        await query.answer(t("master.no_portfolio", user.language), show_alert=True)
        return
    index = max(0, min(index, len(items) - 1))
    item = items[index]
    caption = item.caption or f"{index + 1}/{len(items)}"
    await query.message.answer_photo(  # type: ignore[union-attr]
        item.telegram_file_id,
        caption=caption,
        reply_markup=portfolio_kb(master_id, index, len(items), user.language),
    )
    await query.answer()


@router.callback_query(MasterCb.filter(F.action == "reviews"))
async def show_reviews(
    query: CallbackQuery, callback_data: MasterCb, user: User, session: AsyncSession
) -> None:
    reviews = await MasterRepository(session).reviews(callback_data.master_id)
    if not reviews:
        await query.answer(t("master.no_reviews", user.language), show_alert=True)
        return
    lines = [f"{stars(r.rating)}\n{(r.text or '')[:500]}".strip() for r in reviews]
    for part in chunk_text("\n\n".join(lines)):
        await query.message.answer(part)  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(MasterCb.filter(F.action == "pick"))
async def pick_master(
    query: CallbackQuery,
    callback_data: MasterCb,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    # Switching master is allowed while picking a master, date or time of this booking.
    in_flow = await state.get_state() in {
        BookingStates.choosing_master.state,
        BookingStates.choosing_date.state,
        BookingStates.choosing_time.state,
    }
    if not in_flow or "service_id" not in data:
        # Master picked outside the booking flow (e.g. from the "Masters" list or an old
        # card) — start booking from services instead of reusing a stale service.
        await _release_hold(state, user)
        services = await ServiceRepository(session).list_active()
        await state.clear()
        await state.set_state(BookingStates.choosing_service)
        await query.message.answer(  # type: ignore[union-attr]
            t("book.choose_service", user.language),
            reply_markup=services_kb(services, user.language),
        )
        await query.answer()
        return
    master_repo = MasterRepository(session)
    master = await master_repo.get(callback_data.master_id)
    ms = await master_repo.master_service(callback_data.master_id, data["service_id"])
    if master is None or not master.is_active or ms is None or not ms.is_active:
        await query.answer(t("book.no_masters", user.language), show_alert=True)
        return
    await _release_hold(state, user)
    await state.update_data(master_id=callback_data.master_id)
    await _offer_dates(query.message, user, callback_data.master_id, data["service_id"], session, state)  # type: ignore[arg-type]
    await query.answer()


async def _offer_dates(
    message: Message,
    user: User,
    master_id: int,
    service_id: int,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    master = await MasterRepository(session).get(master_id)
    service = await ServiceRepository(session).get(service_id)
    if master is None or service is None:
        await message.answer(t("error.generic", user.language))
        return
    availability = AvailabilityService(
        MasterRepository(session), AppointmentRepository(session)
    )
    today = dt.datetime.now(settings.tz).date()
    available_days: list[dt.date] = []
    for offset in range(DATE_CHOICES * 2):
        day = today + dt.timedelta(days=offset)
        if await availability.has_any_slot(master, service, day):
            available_days.append(day)
        if len(available_days) >= DATE_CHOICES:
            break
    if not available_days:
        await message.answer(t("book.no_slots", user.language))
        return
    await state.set_state(BookingStates.choosing_date)
    await message.answer(
        t("book.choose_date", user.language), reply_markup=dates_kb(available_days, user.language)
    )


@router.callback_query(BookingStates.choosing_date, DateCb.filter())
async def chose_date(
    query: CallbackQuery,
    callback_data: DateCb,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    master = await MasterRepository(session).get(data["master_id"])
    service = await ServiceRepository(session).get(data["service_id"])
    if master is None or service is None:
        await query.answer(t("error.generic", user.language), show_alert=True)
        return
    try:
        day = dt.date.fromisoformat(callback_data.iso)
    except ValueError:
        await query.answer()
        return
    availability = AvailabilityService(
        MasterRepository(session), AppointmentRepository(session)
    )
    slots = await availability.free_slots(master, service, day, holder_id=user.telegram_id)
    if not slots:
        await query.answer(t("book.no_slots", user.language), show_alert=True)
        return
    await state.update_data(date=callback_data.iso)
    await state.set_state(BookingStates.choosing_time)
    await query.message.edit_text(  # type: ignore[union-attr]
        t("book.choose_time", user.language), reply_markup=times_kb(slots, user.language)
    )
    await query.answer()


@router.callback_query(BookingStates.choosing_time, TimeCb.filter())
async def chose_time(
    query: CallbackQuery,
    callback_data: TimeCb,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    master = await MasterRepository(session).get(data["master_id"])
    service = await ServiceRepository(session).get(data["service_id"])
    if master is None or service is None:
        await query.answer(t("error.generic", user.language), show_alert=True)
        return
    start_at = dt.datetime.fromtimestamp(callback_data.ts, tz=settings.tz)
    availability = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
    if not await availability.is_bookable(master, service, start_at, holder_id=user.telegram_id):
        await query.answer(t("book.slot_taken", user.language), show_alert=True)
        return
    holds = SlotHoldService()
    await _release_hold(state, user)  # a previously chosen time is no longer needed
    end_at = await availability.slot_end(master, service, start_at)
    if not await holds.try_hold(master.id, start_at, user.telegram_id, end_at=end_at):
        await query.answer(t("book.slot_taken", user.language), show_alert=True)
        return
    await state.update_data(ts=callback_data.ts)

    if user.phone:
        await state.set_state(BookingStates.entering_comment)
        await query.message.edit_text(  # type: ignore[union-attr]
            t("book.ask_comment", user.language), reply_markup=comment_skip_kb(user.language)
        )
    else:
        await state.set_state(BookingStates.entering_contact)
        await query.message.answer(  # type: ignore[union-attr]
            t("book.share_contact", user.language), reply_markup=contact_request(user.language)
        )
    await query.answer()


@router.message(BookingStates.entering_contact, F.contact)
async def got_contact(
    contact_msg: Message, user: User, session: AsyncSession, state: FSMContext, is_admin: bool
) -> None:
    contact: Contact = contact_msg.contact  # type: ignore[assignment]
    phone = normalize_phone(contact.phone_number) or contact.phone_number[:32]
    name = (contact.first_name or "") + (f" {contact.last_name}" if contact.last_name else "")
    await UserRepository(session).set_contact(
        user, (name.strip() or user.full_name or "Клиент")[:255], phone
    )
    await state.set_state(BookingStates.entering_comment)
    # The contact keyboard is one-time; bring the main menu back.
    await contact_msg.answer(t("book.contact_saved", user.language), reply_markup=main_menu(user.language, is_admin))
    await contact_msg.answer(t("book.ask_comment", user.language), reply_markup=comment_skip_kb(user.language))


@router.message(BookingStates.entering_contact, FREE_TEXT)
async def got_phone_text(
    message: Message, user: User, session: AsyncSession, state: FSMContext, is_admin: bool
) -> None:
    phone = normalize_phone(message.text or "")
    if phone is None:
        await message.answer(t("book.bad_phone", user.language))
        return
    await UserRepository(session).set_contact(user, user.full_name or "Клиент", phone)
    await state.set_state(BookingStates.entering_comment)
    await message.answer(t("book.contact_saved", user.language), reply_markup=main_menu(user.language, is_admin))
    await message.answer(t("book.ask_comment", user.language), reply_markup=comment_skip_kb(user.language))


@router.message(BookingStates.entering_comment, FREE_TEXT)
async def got_comment(message: Message, user: User, session: AsyncSession, state: FSMContext) -> None:
    await state.update_data(comment=(message.text or "").strip()[:MAX_COMMENT_LEN] or None)
    await _show_summary(message, user, session, state)


@router.callback_query(BookingStates.entering_comment, SkipCb.filter(F.what == "comment"))
async def skip_comment(query: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    await state.update_data(comment=None)
    await _show_summary(query.message, user, session, state)  # type: ignore[arg-type]
    await query.answer()


async def _show_summary(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    data = await state.get_data()
    master_repo = MasterRepository(session)
    master = await master_repo.get(data["master_id"])
    service = await ServiceRepository(session).get(data["service_id"])
    if master is None or service is None:
        await state.clear()
        await message.answer(t("error.generic", user.language))
        return
    salon = await SalonRepository(session).get()
    ms = await master_repo.master_service(master.id, service.id)
    duration = master_repo.effective_duration(ms, service)
    price = master_repo.effective_price(ms, service)
    start_at = dt.datetime.fromtimestamp(data["ts"], tz=settings.tz)
    await state.set_state(BookingStates.confirming)
    await message.answer(
        t(
            "book.summary",
            user.language,
            service=service.name,
            master=master.user.full_name or "Мастер",
            date=fmt_date(start_at, user.language),
            time=fmt_time(start_at),
            duration=duration,
            price=int(price),
            currency=settings.currency,
            address=(salon.address if salon else settings.salon_address) or "—",
            name=user.full_name or "—",
            phone=user.phone or "—",
        ),
        reply_markup=confirm_kb(user.language),
    )


@router.callback_query(BookingStates.confirming, ConfirmCb.filter(F.action == "confirm"))
async def confirm_booking(
    query: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    notifier: NotificationService,
    is_admin: bool,
) -> None:
    data = await state.get_data()
    master = await MasterRepository(session).get(data["master_id"])
    service = await ServiceRepository(session).get(data["service_id"])
    if master is None or service is None:
        await query.answer(t("error.generic", user.language), show_alert=True)
        return
    start_at = dt.datetime.fromtimestamp(data["ts"], tz=settings.tz)
    holds = SlotHoldService()
    if not await holds.owns(master.id, start_at, user.telegram_id):
        await query.answer(t("book.hold_expired", user.language), show_alert=True)
        await state.clear()
        await query.message.answer(t("menu.title", user.language), reply_markup=main_menu(user.language, is_admin))  # type: ignore[union-attr]
        return

    booking = BookingService(session)
    try:
        # Schedule may have changed since the time was offered (day off, block...).
        availability = AvailabilityService(MasterRepository(session), AppointmentRepository(session))
        if not await availability.is_bookable(master, service, start_at, holder_id=user.telegram_id):
            raise SlotTakenError
        appointment = await booking.create(
            client=user,
            master=master,
            service=service,
            start_at=start_at,
            client_comment=data.get("comment"),
        )
    except (SlotTakenError, UnavailableError) as exc:
        key = "book.slot_taken" if isinstance(exc, SlotTakenError) else "book.no_masters"
        await query.answer(t(key, user.language), show_alert=True)
        await holds.release(master.id, start_at, user.telegram_id)
        await state.clear()
        await query.message.answer(t("menu.title", user.language), reply_markup=main_menu(user.language, is_admin))  # type: ignore[union-attr]
        return

    # Persist before notifying: a master may tap "Confirm" right away, and a failure
    # while sending messages must not lose the booking.
    await session.commit()
    await holds.release(master.id, start_at, user.telegram_id)
    await state.clear()
    # Reload with relationships for notification.
    full = await AppointmentRepository(session).get(appointment.id)
    assert full is not None
    await notifier.notify_master_new(full, master_new_appt_kb(full, full.master.user.language))
    await notifier.notify_admins(
        f"🆕 Новая запись #{full.id}\n"
        f"Клиент: {full.client.full_name or '-'} {full.client.phone or '-'} "
        f"{'@' + full.client.username if full.client.username else ''}\n"
        f"Услуга: {full.service.name} · Мастер: {full.master.user.full_name}\n"
        f"Когда: {fmt_date(full.start_at)} {fmt_time(full.start_at)}"
    )
    await query.message.edit_text(t("book.confirmed", user.language))  # type: ignore[union-attr]
    await query.message.answer(t("menu.title", user.language), reply_markup=main_menu(user.language, is_admin))  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(BookingStates.confirming, ConfirmCb.filter(F.action == "cancel"))
async def cancel_booking(query: CallbackQuery, user: User, state: FSMContext, is_admin: bool) -> None:
    await _release_hold(state, user)
    await state.clear()
    await query.message.edit_text(t("cancel", user.language))  # type: ignore[union-attr]
    await query.message.answer(t("menu.title", user.language), reply_markup=main_menu(user.language, is_admin))  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(BookingStates.confirming, ConfirmCb.filter(F.action == "edit"))
async def edit_booking(
    query: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    await _release_hold(state, user)
    services = await ServiceRepository(session).list_active()
    await state.set_state(BookingStates.choosing_service)
    await query.message.answer(  # type: ignore[union-attr]
        t("book.choose_service", user.language), reply_markup=services_kb(services, user.language)
    )
    await query.answer()


async def _release_hold(state: FSMContext, user: User) -> None:
    """Free the slot this user is holding (if any) so others can book it right away."""
    data = await state.get_data()
    if "master_id" in data and "ts" in data:
        start_at = dt.datetime.fromtimestamp(data["ts"], tz=settings.tz)
        await SlotHoldService().release(data["master_id"], start_at, user.telegram_id)
