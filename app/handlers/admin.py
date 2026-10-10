"""Admin panel: menu, today, stats, broadcast, CSV export. Access checked by Telegram ID/role."""
from __future__ import annotations

import csv
import datetime as dt
import io

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AppointmentStatus, Role, User
from app.keyboards.builders import admin_menu_kb
from app.keyboards.callbacks import AdminCb, ConfirmCb
from app.locales import t
from app.repositories.appointments import AppointmentRepository
from app.repositories.users import UserRepository
from app.services.notifications import NotificationService
from app.states import BroadcastStates
from app.utils.format import fmt_date, fmt_time

router = Router(name="admin")


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
    lines = [
        f"{fmt_time(a.start_at)} · {a.service.name} · "
        f"{a.master.user.full_name} · {a.client.full_name or a.client.phone or '-'} · "
        f"{t(f'status.{a.status.value}', user.language)}"
        for a in appts
    ]
    await query.message.answer("\n".join(lines))  # type: ignore[union-attr]
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
    lines = [t("admin.all.header", user.language)]
    for a in appts[:30]:
        lines.append(
            f"{fmt_date(a.start_at)} {fmt_time(a.start_at)} · {a.service.name} · "
            f"{a.master.user.full_name} · {a.client.full_name or a.client.phone or '-'} · "
            f"{t(f'status.{a.status.value}', user.language)}"
        )
    await query.message.answer("\n".join(lines))  # type: ignore[union-attr]
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
    items = []
    for m in masters:
        sched = (
            await session.execute(
                select(Schedule).where(
                    Schedule.master_id == m.id, Schedule.weekday == weekday
                )
            )
        ).scalar_one_or_none()
        day_off = (
            await session.execute(
                select(ScheduleException.id).where(
                    ScheduleException.master_id == m.id,
                    ScheduleException.date == today,
                    ScheduleException.exception_type == "day_off",
                )
            )
        ).scalar_one_or_none()
        if sched and sched.is_working_day and not day_off:
            appts = await AppointmentRepository(session).active_for_master_on_day(
                m.id, today, settings.tz
            )
            items.append(
                f"✅ {m.user.full_name} — {sched.start_time:%H:%M}–{sched.end_time:%H:%M}, "
                f"записей: {len(appts)}, ⭐ {float(m.rating)}"
            )
        else:
            items.append(f"🏖 {m.user.full_name} — выходной")
    if not items:
        await query.message.answer(t("admin.masters.none_today", user.language))  # type: ignore[union-attr]
    else:
        await query.message.answer(  # type: ignore[union-attr]
            t("admin.masters.today", user.language, items="\n".join(items))
        )
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
    await query.message.answer("\n".join(lines))  # type: ignore[union-attr]
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
        f"• {c.full_name or '—'} · {c.phone or '—'}" for c in clients[:50]
    )
    await query.message.answer(  # type: ignore[union-attr]
        t("admin.clients.list", user.language, count=len(clients), items=items)
    )
    await query.answer()


@router.callback_query(AdminCb.filter(F.section == "reviews"))
async def admin_reviews(query: CallbackQuery, user: User, session: AsyncSession) -> None:
    if not _is_admin(user):
        await query.answer(t("admin.only", user.language), show_alert=True)
        return
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

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
        parts.append(f"{'⭐' * r.rating} {muser.full_name if muser else '-'}\n{r.text or ''}".strip())
    await query.message.answer(  # type: ignore[union-attr]
        t("admin.reviews.list", user.language, items="\n\n".join(parts))
    )
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
                a.service.name,
                a.master.user.full_name,
                a.client.full_name,
                a.client.phone,
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


@router.message(BroadcastStates.text, F.text)
async def broadcast_confirm(message: Message, user: User, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(user):
        return
    clients = await UserRepository(session).all_clients()
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
    import asyncio

    data = await state.get_data()
    clients = await UserRepository(session).all_clients()
    ok = fail = 0
    for c in clients:
        sent = await notifier.send_telegram(c.telegram_id, data["text"])
        ok += int(sent)
        fail += int(not sent)
        await asyncio.sleep(0.05)  # rate limiting ~20 msg/s
    await query.message.edit_text(  # type: ignore[union-attr]
        t("admin.broadcast.done", user.language, ok=ok, fail=fail)
    )
    await state.clear()
    await query.answer()


@router.callback_query(BroadcastStates.confirm, ConfirmCb.filter(F.action == "cancel"))
async def broadcast_cancel(query: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.clear()
    await query.message.edit_text(t("cancel", user.language))  # type: ignore[union-attr]
    await query.answer()
