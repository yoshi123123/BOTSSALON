"""Application entry point: sets up the bot, dispatcher, middlewares and polling."""
from __future__ import annotations

import asyncio
import contextlib

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.config import settings
from app.db.base import async_session_factory, engine
from app.handlers import build_root_router
from app.handlers import errors as errors_handler
from app.integrations.sms.provider import build_sms_provider
from app.logging_config import setup_logging
from app.middlewares.context import ContextMiddleware
from app.middlewares.deps import DepsMiddleware
from app.middlewares.menu_reset import MenuResetMiddleware
from app.services.notifications import NotificationService

log = structlog.get_logger(__name__)

DB_CONNECT_ATTEMPTS = 30
DB_CONNECT_DELAY = 2.0  # seconds
TELEGRAM_START_ATTEMPTS = 5
SHUTDOWN_GRACE = 8.0  # seconds to let in-flight updates finish after SIGTERM


def _run_migrations_sync() -> None:
    """Apply Alembic migrations. Runs in a worker thread because alembic's
    async env.py calls asyncio.run(), which is illegal inside a running loop."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent  # project root (contains alembic.ini)
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.attributes["configure_logger"] = False  # keep the app's logging setup
    command.upgrade(cfg, "head")


async def _wait_for_db() -> None:
    """On Railway the database (and the private network) may come up after the bot
    container; retry for a while instead of crash-looping."""
    for attempt in range(1, DB_CONNECT_ATTEMPTS + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001 - any connection problem is retried
            if attempt == DB_CONNECT_ATTEMPTS:
                raise
            log.warning("db.unavailable", attempt=attempt, error=str(exc))
            await asyncio.sleep(DB_CONNECT_DELAY)


async def main() -> None:
    setup_logging()
    log.info(
        "bot.boot",
        database=make_url(settings.database_url).render_as_string(hide_password=True),
        timezone=settings.timezone,
        admins=len(settings.admin_id_set),
    )

    await _wait_for_db()

    # Auto-apply DB migrations on every boot (no-op when already up to date),
    # so the bot works with a plain `python -m app.main` start command.
    try:
        await asyncio.to_thread(_run_migrations_sync)
        log.info("migrations.applied")
    except Exception as exc:  # noqa: BLE001 - surface the reason, then fail fast
        log.error("migrations.failed", error=str(exc))
        raise

    # Demo data on first boot (idempotent, skips if present). Disable with SEED_DEMO=false.
    # Then apply MASTER_TELEGRAM_ID and SALON_* env vars (also when set after first boot).
    from app.seed import bind_master_telegram_id, seed_demo, sync_salon_settings

    try:
        async with async_session_factory() as session:
            created = await seed_demo(session) if settings.seed_demo else False
            bound = await bind_master_telegram_id(session)
            await sync_salon_settings(session)
            await session.commit()
            log.info("seed.checked", created=created, master_bound=bound)
    except Exception as exc:  # noqa: BLE001 - seed must never block the bot
        log.error("seed.failed", error=str(exc))

    # Plain-text messages: texts contain user input (names, comments, reviews), and
    # none of the templates use markup, so HTML parsing would only break on '<' or '&'.
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=None))
    # Process updates of one user sequentially: protects FSM flows from double taps.
    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())

    sms = build_sms_provider()
    notifier = NotificationService(bot, sms)

    # Inner middlewares: DB session + user resolution, then dependency injection.
    context_mw = ContextMiddleware()
    deps_mw = DepsMiddleware(notifier)
    dp.message.middleware(context_mw)
    dp.callback_query.middleware(context_mw)
    dp.message.middleware(deps_mw)
    dp.callback_query.middleware(deps_mw)
    # Outer: runs before filters, so a main-menu tap ends any unfinished dialog step.
    dp.message.outer_middleware(MenuResetMiddleware())

    dp.include_router(errors_handler.router)
    dp.include_router(build_root_router())

    # In-process reminders / digests / auto-completion (no separate worker needed).
    from app.background.scheduler import scheduler_loop

    scheduler_task = asyncio.create_task(scheduler_loop(bot, sms))

    log.info("bot.starting")
    try:
        # Keep updates that arrived while the bot was restarting (e.g. a redeploy).
        for attempt in range(1, TELEGRAM_START_ATTEMPTS + 1):
            try:
                await bot.delete_webhook(drop_pending_updates=False)
                break
            except TelegramNetworkError as exc:
                if attempt == TELEGRAM_START_ATTEMPTS:
                    raise
                log.warning("telegram.unavailable", attempt=attempt, error=str(exc))
                await asyncio.sleep(2 * attempt)
        # handle_signals (default) stops polling gracefully on SIGTERM / SIGINT.
        await dp.start_polling(
            bot, allowed_updates=dp.resolve_used_update_types(), close_bot_session=False
        )
    finally:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task
        # Let updates that were already taken from Telegram finish (they would be lost).
        in_flight = [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        if in_flight:
            await asyncio.wait(in_flight, timeout=SHUTDOWN_GRACE)
        await bot.session.close()
        await engine.dispose()
        log.info("bot.stopped")


if __name__ == "__main__":
    asyncio.run(main())
