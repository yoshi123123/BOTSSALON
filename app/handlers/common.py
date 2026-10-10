"""Common handlers: /start, main menu buttons, language, contacts, support."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SUPPORTED_LANGUAGES, settings
from app.db.models import User
from app.keyboards.builders import lang_kb, main_menu
from app.keyboards.callbacks import LangCb
from app.locales import t
from app.repositories.catalog import ServiceRepository
from app.repositories.users import SalonRepository, UserRepository
from app.utils.format import chunk_text

router = Router(name="common")


async def _salon_name(session: AsyncSession) -> str:
    salon = await SalonRepository(session).get()
    return salon.name if salon else settings.salon_name


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    user: User,
    is_admin: bool,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    # First contact: offer a language choice once.
    if not user.language_selected:
        await message.answer(t("onboarding.choose_lang", user.language), reply_markup=lang_kb())
        return
    name = await _salon_name(session)
    await message.answer(
        t("start.greeting", user.language, salon=name),
        reply_markup=main_menu(user.language, is_admin),
    )


@router.message(F.text.in_({t("menu.language", "ru"), t("menu.language", "ro"), t("menu.language", "en")}))
async def choose_language(message: Message, user: User) -> None:
    await message.answer(t("lang.choose", user.language), reply_markup=lang_kb())


@router.callback_query(LangCb.filter())
async def set_language(
    query: CallbackQuery,
    callback_data: LangCb,
    user: User,
    is_admin: bool,
    session: AsyncSession,
) -> None:
    if callback_data.code not in SUPPORTED_LANGUAGES:
        await query.answer()
        return
    await UserRepository(session).set_language(user, callback_data.code)
    user.language_selected = True
    await session.flush()
    name = await _salon_name(session)
    await query.message.answer(  # type: ignore[union-attr]
        t("lang.set", callback_data.code)
        + "\n\n"
        + t("start.greeting", callback_data.code, salon=name),
        reply_markup=main_menu(callback_data.code, is_admin),
    )
    await query.answer()


@router.message(F.text.in_({t("menu.contacts", "ru"), t("menu.contacts", "ro"), t("menu.contacts", "en")}))
async def contacts(message: Message, user: User, session: AsyncSession) -> None:
    salon = await SalonRepository(session).get()
    name = salon.name if salon else settings.salon_name
    address = (salon.address if salon else settings.salon_address) or "—"
    phone = (salon.phone if salon else settings.salon_phone) or "—"
    await message.answer(t("contacts.card", user.language, name=name, address=address, phone=phone))


@router.message(F.text.in_({t("menu.support", "ru"), t("menu.support", "ro"), t("menu.support", "en")}))
async def support(message: Message, user: User, session: AsyncSession) -> None:
    salon = await SalonRepository(session).get()
    phone = (salon.phone if salon else settings.salon_phone) or "—"
    await message.answer(t("support.text", user.language, contact=phone))


@router.message(F.text.in_({t("menu.services", "ru"), t("menu.services", "ro"), t("menu.services", "en")}))
async def services_list(message: Message, user: User, session: AsyncSession) -> None:
    services = await ServiceRepository(session).list_active()
    if not services:
        await message.answer("—")
        return
    lines = [
        f"• {s.name} — {int(s.default_price)} {settings.currency}, "
        f"{s.default_duration_minutes} мин"
        for s in services
    ]
    for part in chunk_text("\n".join(lines)):
        await message.answer(part)


@router.message(F.text.in_({t("menu.masters", "ru"), t("menu.masters", "ro"), t("menu.masters", "en")}))
async def masters_list(message: Message, user: User, session: AsyncSession) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models import Master
    from app.keyboards.builders import master_card_kb

    res = await session.execute(
        select(Master)
        .where(Master.is_active.is_(True))
        .options(selectinload(Master.user))
        .order_by(Master.rating.desc())
    )
    masters = list(res.scalars().all())
    if not masters:
        await message.answer("—")
        return
    for m in masters:
        text = t(
            "master.card",
            user.language,
            name=m.user.full_name or "Мастер",
            spec=m.specialization or "—",
            exp=m.experience_years,
            rating=float(m.rating),
            reviews=m.review_count,
            price=0,
            currency=settings.currency,
        )
        # Trim the "От 0 MDL" line for the generic list
        text = text.rsplit("\n", 1)[0]
        await message.answer(text, reply_markup=master_card_kb(m, user.language))
