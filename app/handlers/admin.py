"""Admin panel: menu, today, stats, broadcast, CSV export. Access checked by Telegram ID/role."""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AppointmentStatus, Role, User
from app.keyboards.builders import FREE_TEXT, admin_menu_kb
from app.keyboards.callbacks import AdminCb, ConfirmCb
from app.locales import t
from app.repositories.appointments import AppointmentRepository
from app.repositories.users import UserRepository
from app.services.notifications import NotificationService, is_real_chat
from app.states import BroadcastStates
from app.utils.format import chunk_text, csv_safe, fmt_date, fmt_time

log = structlog.get_logger(__name__)

router = Router(name="admin")

# Running broadcasts (keep references so the tasks are not garbage-collected).
_BROADCASTS: set[asyncio.Task[None]] = set()


def _is_admin(user: User | None) -> bool:
    if user is None:
        return False
    return user.role in {Role.admin, Role.owner} or user.telegram_id in settings.admin_id_set


@router.message(F.text.in_({t("admin.menu", "ru"), t("admin.menu", "ro"), t("admin.menu", "en")}))
async def admin_menu(message: Message, user: User) -> None:
    if not _is_admin(user):
        await message.answer(t("admin.only", user.language))
        return
    await message.answer(t("admin.menu", user.language), reply_markup=admin_menu_kb(user.language))


def _day_bounds(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(day, dt.time.min, tzinfo=settings.tz)
    return start, start + dt.timedelta(days=1)


@router.callback_query(AdminCb.filter(F.section == "today"))
async def admin_today(query: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    start, end = _day_bounds(dt.datetime.now(settings.tz).date())
    appts = await AppointmentRepository(session).today_appointments(start, end)
    if not appts:
        await query.message.answer(t("my.empty", user.language))  # type: ignore[union-attr]
        await query.answer()
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    from app.keyboards.callbacks import AdminApptCb

    for a in appts[:20]:
        uname = f"@{a.client.username}" if a.client.username else "—"
        text = (
            f"{fmt_time(a.start_at)} · {a.service.name}\n"
            f"Мастер: {a.master.user.full_name}\n"
            f"Клиент: {a.client.full_name or '—'} · {a.client.phone or '—'} · {uname}\n"
            f"Статус: {t(f'status.{a.status.value}', user.language)}"
        )
        b = InlineKeyboardBuilder()
        b.button(text="🛠 Открыть", callback_data=AdminApptCb(appointment_id=a.id, action="view"))
        await query.message.answer(text, reply_markup=b.as_markup())  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(AdminCb.filter(F.section == "all"))
async def admin_all(query: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    now = dt.datetime.now(settings.tz)
    appts = await AppointmentRepository(session).today_appointments(
        now, now + dt.timedelta(days=30)
    )
    if not appts:
        await query.message.answer(t("admin.empty", user.language))  # type: ignore[union-attr]
        await query.answer()
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    from app.keyboards.callbacks import AdminApptCb

    await query.message.answer(t("admin.all.header", user.language))  # type: ignore[union-attr]
    for a in appts[:20]:
        uname = f"@{a.client.username}" if a.client.username else "—"
        text = (
            f"{fmt_date(a.start_at)} {fmt_time(a.start_at)} · {a.service.name}\n"
            f"Мастер: {a.master.user.full_name}\n"
            f"Клиент: {a.client.full_name or '—'} · {a.client.phone or '—'} · {uname}\n"
            f"Статус: {t(f'status.{a.status.value}', user.language)}"
        )
        b = InlineKeyboardBuilder()
        b.button(text="🛠 Открыть", callback_data=AdminApptCb(appointment_id=a.id, action="view"))
        await query.message.answer(text, reply_markup=b.as_markup())  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(AdminCb.filter(F.section == "masters"))
async def admin_masters(query: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models import Master, Schedule, ScheduleException

    today = dt.datetime.now(settings.tz).date()
    weekday = today.weekday()
    res = await session.execute(
        select(Master).where(Master.is_active.is_(True)).options(selectinload(Master.user))
    )
    masters = list(res.scalars().all())
    from app.services.availability import AvailabilityService

    items = []
    for m in masters:
        sched = (
            await session.execute(
                select(Schedule).where(
                    Schedule.master_id == m.id, Schedule.weekday == weekday
                )
            )
        ).scalar_one_or_none()
        exceptions = list(
            (
                await session.execute(
                    select(ScheduleException).where(
                        ScheduleException.master_id == m.id,
                        ScheduleException.date == today,
                    )
                )
            ).scalars()
        )
        start, end = AvailabilityService._effective_hours(sched, exceptions)
        day_off = any(e.exception_type == "day_off" for e in exceptions)
        if start is not None and end is not None and not day_off:
            appts = await AppointmentRepository(session).active_for_master_on_day(
                m.id, today, settings.tz
            )
            items.append(
                f"✅ {m.user.full_name} — {start:%H:%M}–{end:%H:%M}, "
                f"записей: {len(appts)}, ⭐ {float(m.rating)}"
            )
        else:
            items.append(f"🏖 {m.user.full_name} — выходной")
    if not items:
        await query.message.answer(t("admin.masters.none_today", user.language))  # type: ignore[union-attr]
    else:
        for part in chunk_text(t("admin.masters.today", user.language, items="\n".join(items))):
            await query.message.answer(part)  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(AdminCb.filter(F.section == "services"))
async def admin_services(query: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    from app.repositories.catalog import ServiceRepository

    services = await ServiceRepository(session).list_active()
    if not services:
        await query.message.answer(t("admin.empty", user.language))  # type: ignore[union-attr]
        await query.answer()
        return
    lines = [
        f"• {s.name} — {int(s.default_price)} {settings.currency}, "
        f"{s.default_duration_minutes} мин (+{s.buffer_minutes} буфер)"
        for s in services
    ]
    for part in chunk_text("\n".join(lines)):
        await query.message.answer(part)  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(AdminCb.filter(F.section == "clients"))
async def admin_clients(query: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    clients = await UserRepository(session).all_clients()
    if not clients:
        await query.message.answer(t("admin.empty", user.language))  # type: ignore[union-attr]
        await query.answer()
        return
    items = "\n".join(
        f"• {c.full_name or '—'} · {c.phone or '—'} · "
        f"{'@' + c.username if c.username else '—'}"
        for c in clients[:50]
    )
    for part in chunk_text(t("admin.clients.list", user.language, count=len(clients), items=items)):
        await query.message.answer(part)  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(AdminCb.filter(F.section == "reviews"))
async def admin_reviews(query: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    from sqlalchemy import select

    from app.db.models import Master, Review

    res = await session.execute(
        select(Review)
        .where(Review.is_visible.is_(True))
        .order_by(Review.created_at.desc())
        .limit(10)
    )
    reviews = list(res.scalars().all())
    if not reviews:
        await query.message.answer(t("admin.empty", user.language))  # type: ignore[union-attr]
        await query.answer()
        return
    parts = []
    for r in reviews:
        master = await session.get(Master, r.master_id)
        muser = await session.get(User, master.user_id) if master else None
        text = (r.text or "")[:300]
        parts.append(f"{'⭐' * r.rating} {muser.full_name if muser else '-'}\n{text}".strip())
    for part in chunk_text(t("admin.reviews.list", user.language, items="\n\n".join(parts))):
        await query.message.answer(part)  # type: ignore[union-attr]
    await query.answer()


@router.callback_query(AdminCb.filter(F.section == "settings"))
async def admin_settings(query: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    from app.repositories.users import SalonRepository

    salon = await SalonRepository(session).get()
    await query.message.answer(  # type: ignore[union-attr]
        t(
            "admin.settings.body",
            user.language,
            name=salon.name if salon else settings.salon_name,
            address=(salon.address if salon else settings.salon_address) or "—",
            phone=(salon.phone if salon else settings.salon_phone) or "—",
            tz=salon.timezone if salon else settings.timezone,
            currency=salon.currency if salon else settings.currency,
        )
    )
    await query.answer()


@router.callback_query(AdminCb.filter(F.section == "stats"))
async def admin_stats(query: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    repo = AppointmentRepository(session)
    now = dt.datetime.now(settings.tz)
    day_start, day_end = _day_bounds(now.date())
    week_start = day_start - dt.timedelta(days=now.weekday())
    week_end = week_start + dt.timedelta(days=7)

    today = await repo.count_between(day_start, day_end)
    week = await repo.count_between(week_start, week_end)
    completed = await repo.count_between(week_start, week_end, AppointmentStatus.completed)
    cancelled = await repo.count_between(
        week_start, week_end, AppointmentStatus.cancelled_by_client
    )
    no_show = await repo.count_between(week_start, week_end, AppointmentStatus.no_show)
    revenue = await repo.revenue_between(week_start, week_end)

    await query.message.answer(  # type: ignore[union-attr]
        t(
            "admin.stats.body",
            user.language,
            today=today,
            week=week,
            completed=completed,
            cancelled=cancelled,
            no_show=no_show,
            revenue=int(revenue),
            currency=settings.currency,
        )
    )
    await query.answer()


@router.callback_query(AdminCb.filter(F.section == "export"))
async def admin_export(query: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    now = dt.datetime.now(settings.tz)
    start = now - dt.timedelta(days=30)
    appts = await AppointmentRepository(session).today_appointments(start, now + dt.timedelta(days=30))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "date", "time", "service", "master", "client", "phone", "price", "status"])
    for a in appts:
        writer.writerow(
            [
                a.id,
                fmt_date(a.start_at),
                fmt_time(a.start_at),
                csv_safe(a.service.name),
                csv_safe(a.master.user.full_name),
                csv_safe(a.client.full_name),
                csv_safe(a.client.phone),
                int(a.price),
                a.status.value,
            ]
        )
    data = buf.getvalue().encode("utf-8-sig")
    await query.message.answer_document(  # type: ignore[union-attr]
        BufferedInputFile(data, filename="appointments.csv")
    )
    await query.answer()


@router.callback_query(AdminCb.filter(F.section == "broadcast"))
async def broadcast_start(query: CallbackQuery, user: User, state: FSMContext) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    await state.set_state(BroadcastStates.text)
    await query.message.answer(t("admin.broadcast.ask", user.language))  # type: ignore[union-attr]
    await query.answer()


@router.message(BroadcastStates.text, FREE_TEXT)
async def broadcast_confirm(message: Message, user: User, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(user):
        await state.clear()
        return
    clients = [c for c in await UserRepository(session).all_clients() if is_real_chat(c.telegram_id)]
    await state.update_data(text=message.text, count=len(clients))
    await state.set_state(BroadcastStates.confirm)
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    b = InlineKeyboardBuilder()
    b.button(text=t("confirm", user.language), callback_data=ConfirmCb(action="confirm"))
    b.button(text=t("cancel", user.language), callback_data=ConfirmCb(action="cancel"))
    await message.answer(
        t("admin.broadcast.confirm", user.language, count=len(clients)), reply_markup=b.as_markup()
    )


@router.callback_query(BroadcastStates.confirm, ConfirmCb.filter(F.action == "confirm"))
async def broadcast_send(
    query: CallbackQuery, user: User, session: AsyncSession, state: FSMContext, notifier: NotificationService
) -> None:
    if not _is_admin(user):
        await state.clear()
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    data = await state.get_data()
    await state.clear()
    clients = [c for c in await UserRepository(session).all_clients() if is_real_chat(c.telegram_id)]
    chat_ids = [c.telegram_id for c in clients]
    # Answer right away: callback queries expire after a few seconds, while sending to
    # many clients takes a while. The loop runs in the background without a DB session.
    await query.answer()
    await query.message.edit_text(  # type: ignore[union-attr]
        t("admin.broadcast.started", user.language, count=len(chat_ids))
    )
    task = asyncio.create_task(
        _run_broadcast(notifier, chat_ids, data["text"], user.telegram_id, user.language)
    )
    _BROADCASTS.add(task)
    task.add_done_callback(_BROADCASTS.discard)


async def _run_broadcast(
    notifier: NotificationService, chat_ids: list[int], text: str, admin_chat: int, lang: str
) -> None:
    ok = fail = 0
    try:
        for chat_id in chat_ids:
            sent = await notifier.send_telegram(chat_id, text)
            ok += int(sent)
            fail += int(not sent)
            await asyncio.sleep(0.05)  # rate limiting ~20 msg/s
    finally:
        log.info("broadcast.done", ok=ok, fail=fail)
        await notifier.send_telegram(admin_chat, t("admin.broadcast.done", lang, ok=ok, fail=fail))


@router.callback_query(BroadcastStates.confirm, ConfirmCb.filter(F.action == "cancel"))
async def broadcast_cancel(query: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.clear()
    await query.message.edit_text(t("cancel", user.language))  # type: ignore[union-attr]
    await query.answer()
