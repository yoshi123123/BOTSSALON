"""Fallback handlers, registered last.

FSM state lives in memory, so after a restart (e.g. a Railway redeploy) inline buttons
of an unfinished dialog no longer match any handler. Without an answer Telegram keeps
the button spinner going; tell the user to start over instead.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db.models import User
from app.keyboards.builders import main_menu
from app.locales import t

router = Router(name="fallback")


@router.callback_query()
async def stale_callback(query: CallbackQuery, user: User) -> None:
    # A short toast, not a modal alert: this is also what a double tap on an already
    # handled button gets, and an alarming popup there would suggest a failure.
    await query.answer(t("error.stale", user.language))


@router.message(F.chat.type == "private")
async def unknown_message(message: Message, user: User, is_admin: bool, state: FSMContext) -> None:
    if await state.get_state() is not None:
        # The current step expects a button press (or a different kind of input).
        await message.answer(t("fallback.use_buttons", user.language))
        return
    await message.answer(
        t("fallback.unknown", user.language), reply_markup=main_menu(user.language, is_admin)
    )
