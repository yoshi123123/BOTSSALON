"""Client booking flow (FSM): service -> master -> date -> time -> contact -> confirm."""
from __future__ import annotations

import datetime as dt

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Contact, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User
from app.keyboards.builders import (
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
from app.locales import t
from app.repositories.appointments import AppointmentRepository
from app.repositories.catalog import MasterRepository, ServiceRepository
from app.repositories.users import SalonRepository, UserRepository
from app.services.availability import AvailabilityService
from app.services.booking import BookingService, SlotTakenError
from app.services.matching import MatchingService
from app.services.notifications import NotificationService
from app.services.slot_hold import SlotHoldService
from app.states import BookingStates
from app.utils.format import fmt_date, fmt_time, stars

router = Router(name="booking")

DATE_CHOICES = 8  # number of upcoming days offered


def _redis(data_bot_deps: dict) -> Redis:
    return data_bot_deps["redis"]


@router.message(F.text.in_({t("menu.book", "ru"), t("menu.book", "ro"), t("menu.book", "en")}))
async def start_booking(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    services = await ServiceRepository(session).list_active()
    if not services:
        await message.answer(t("book.no_masters", user.language))
        return
    await state.clear()
    await state.set_state(BookingStates.choosing_service)
    await message.answer(t("book.choose_service", user.language), reply_markup=services_kb(services, user.language))


@router.callback_query(BookingStates.choosing_service, ServiceCb.filter())
async def chose_service(
    query: CallbackQuery, callback_data: ServiceCb, user: User, state: FSMContext
) -> None:
    await state.update_data(service_id=callback_data.service_id)
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
    redis: Redis,
) -> None:
    data = await state.get_data()
    service = await ServiceRepository(session).get(data["service_id"])
    if service is None:
        await query.answer()
        return
    master_repo = MasterRepository(session)
    appt_repo = AppointmentRepository(session)
    availability = AvailabilityService(master_repo, appt_repo, redis)

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
    master, slot = result
    await state.update_data(master_id=master.id)
    await _offer_dates(query.message, user, master.id, service.id, session, state, redis)  # type: ignore[arg-type]
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
    lines = [f"{stars(r.rating)}\n{r.text or ''}".strip() for r in reviews]
    await query.message.answer("\n\n".join(lines))  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(MasterCb.filter(F.action == "pick"))
async def pick_master(
    query: CallbackQuery,
    callback_data: MasterCb,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    redis: Redis,
) -> None:
    data = await state.get_data()
    if "service_id" not in data:
        # Master picked outside the booking flow — start booking from services.
        services = await ServiceRepository(session).list_active()
        await state.clear()
        await state.set_state(BookingStates.choosing_service)
        await query.message.answer(  # type: ignore[union-attr]
            t("book.choose_service", user.language),
            reply_markup=services_kb(services, user.language),
        )
        await query.answer()
        return
    await state.update_data(master_id=callback_data.master_id)
    await _offer_dates(query.message, user, callback_data.master_id, data["service_id"], session, state, redis)  # type: ignore[arg-type]
    await query.answer()


async def _offer_dates(
    message: Message,
    user: User,
    master_id: int,
    service_id: int,
    session: AsyncSession,
    state: FSMContext,
    redis: Redis,
) -> None:
    master = await MasterRepository(session).get(master_id)
    service = await ServiceRepository(session).get(service_id)
    if master is None or service is None:
        await message.answer(t("error.generic", user.language))
        return
    availability = AvailabilityService(
        MasterRepository(session), AppointmentRepository(session), redis
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
    redis: Redis,
) -> None:
    data = await state.get_data()
    master = await MasterRepository(session).get(data["master_id"])
    service = await ServiceRepository(session).get(data["service_id"])
    if master is None or service is None:
        await query.answer(t("error.generic", user.language), show_alert=True)
        return
    day = dt.date.fromisoformat(callback_data.iso)
    availability = AvailabilityService(
        MasterRepository(session), AppointmentRepository(session), redis
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
    redis: Redis,
) -> None:
    data = await state.get_data()
    start_at = dt.datetime.fromtimestamp(callback_data.ts, tz=settings.tz)
    holds = SlotHoldService(redis)
    ok = await holds.try_hold(data["master_id"], start_at, user.telegram_id)
    if not ok:
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
    contact_msg: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    contact: Contact = contact_msg.contact  # type: ignore[assignment]
    name = (contact.first_name or "") + (f" {contact.last_name}" if contact.last_name else "")
    await UserRepository(session).set_contact(user, name.strip() or user.full_name or "Клиент", contact.phone_number)
    await state.set_state(BookingStates.entering_comment)
    await contact_msg.answer(t("book.ask_comment", user.language), reply_markup=comment_skip_kb(user.language))


@router.message(BookingStates.entering_contact, F.text)
async def got_phone_text(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    phone = message.text.strip()
    await UserRepository(session).set_contact(user, user.full_name or "Клиент", phone)
    await state.set_state(BookingStates.entering_comment)
    await message.answer(t("book.ask_comment", user.language), reply_markup=comment_skip_kb(user.language))


@router.message(BookingStates.entering_comment, F.text)
async def got_comment(message: Message, user: User, session: AsyncSession, state: FSMContext) -> None:
    await state.update_data(comment=message.text.strip())
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
    master = await MasterRepository(session).get(data["master_id"])
    service = await ServiceRepository(session).get(data["service_id"])
    salon = await SalonRepository(session).get()
    ms = await MasterRepository(session).master_service(master.id, service.id)  # type: ignore[union-attr]
    duration = MasterRepository(session).effective_duration(ms, service)  # type: ignore[arg-type]
    price = MasterRepository(session).effective_price(ms, service)  # type: ignore[arg-type]
    start_at = dt.datetime.fromtimestamp(data["ts"], tz=settings.tz)
    await state.set_state(BookingStates.confirming)
    await message.answer(
        t(
            "book.summary",
            user.language,
            service=service.name,  # type: ignore[union-attr]
            master=master.user.full_name or "Мастер",  # type: ignore[union-attr]
            date=fmt_date(start_at),
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
    redis: Redis,
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
    holds = SlotHoldService(redis)
    if not await holds.owns(master.id, start_at, user.telegram_id):
        await query.answer(t("book.hold_expired", user.language), show_alert=True)
        await state.clear()
        return

    booking = BookingService(session)
    try:
        appointment = await booking.create(
            client=user,
            master=master,
            service=service,
            start_at=start_at,
            client_comment=data.get("comment"),
        )
    except SlotTakenError:
        await query.answer(t("book.slot_taken", user.language), show_alert=True)
        await holds.release(master.id, start_at, user.telegram_id)
        await state.clear()
        return

    await session.flush()
    await holds.release(master.id, start_at, user.telegram_id)
    # Reload with relationships for notification.
    full = await AppointmentRepository(session).get(appointment.id)
    await notifier.notify_master_new(full, master_new_appt_kb(appointment.id, master.user.language))  # type: ignore[arg-type]
    await query.message.edit_text(t("book.confirmed", user.language))  # type: ignore[union-attr]
    await query.message.answer(t("menu.title", user.language), reply_markup=main_menu(user.language, is_admin))  # type: ignore[union-attr]
    await state.clear()
    await query.answer()


@router.callback_query(BookingStates.confirming, ConfirmCb.filter(F.action == "cancel"))
async def cancel_booking(query: CallbackQuery, user: User, state: FSMContext, is_admin: bool) -> None:
    await state.clear()
    await query.message.edit_text(t("cancel", user.language))  # type: ignore[union-attr]
    await query.message.answer(t("menu.title", user.language), reply_markup=main_menu(user.language, is_admin))  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(BookingStates.confirming, ConfirmCb.filter(F.action == "edit"))
async def edit_booking(
    query: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    services = await ServiceRepository(session).list_active()
    await state.set_state(BookingStates.choosing_service)
    await query.message.answer(  # type: ignore[union-attr]
        t("book.choose_service", user.language), reply_markup=services_kb(services, user.language)
    )
    await query.answer()
