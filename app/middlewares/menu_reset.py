"""Outer middleware: a tap on a main-menu button leaves any unfinished dialog.

Without it a half-finished step (e.g. "enter the cancellation reason") stays armed after
the user moved on via the menu, and an unrelated message days later would cancel the
appointment. Runs before filters, so state-bound handlers no longer match.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject

from app.keyboards.builders import MENU_TEXTS
from app.services.slot_hold import SlotHoldService


class MenuResetMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.text in MENU_TEXTS:
            state: FSMContext | None = data.get("state")
            if state is not None and await state.get_state() is not None:
                await state.clear()
                if event.from_user is not None:
                    await SlotHoldService().release_all(event.from_user.id)
        return await handler(event, data)
