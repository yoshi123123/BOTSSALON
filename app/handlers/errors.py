"""Global error handler: log full detail, show a friendly message to the user."""
from __future__ import annotations

import structlog
from aiogram import Router
from aiogram.types import ErrorEvent

from app.locales import t

log = structlog.get_logger(__name__)

router = Router(name="errors")


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    log.error("handler.exception", error=str(event.exception), exc_info=event.exception)
    update = event.update
    lang = "ru"
    try:
        if update.message is not None:
            await update.message.answer(t("error.generic", lang))
        elif update.callback_query is not None:
            await update.callback_query.answer(t("error.generic", lang), show_alert=True)
    except Exception:  # pragma: no cover - best effort
        pass
    return True
