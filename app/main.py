"""Application entry point: sets up the bot, dispatcher, middlewares and polling."""
from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from app.config import settings
from app.handlers import build_root_router
from app.handlers import errors as errors_handler
from app.integrations.sms.provider import build_sms_provider
from app.logging_config import setup_logging
from app.middlewares.context import ContextMiddleware
from app.middlewares.deps import DepsMiddleware
from app.services.notifications import NotificationService

log = structlog.get_logger(__name__)


def _run_migrations_sync() -> None:
    """Apply Alembic migrations. Runs in a worker thread because alembic's
    async env.py calls asyncio.run(), which is illegal inside a running loop."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent  # project root (contains alembic.ini)
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")


async def main() -> None:
    setup_logging()

    # Auto-apply DB migrations on every boot (no-op when already up to date),
    # so the bot works with a plain `python -m app.main` start command.
    try:
        await asyncio.to_thread(_run_migrations_sync)
        log.info("migrations.applied")
    except Exception as exc:  # noqa: BLE001 - surface the reason, then fail fast
        log.error("migrations.failed", error=str(exc))
        raise

    # Auto-apply demo data on first boot (idempotent, skips if present).
    from app.db.base import async_session_factory
    from app.seed import seed_demo

    try:
        async with async_session_factory() as session:
            created = await seed_demo(session)
            await session.commit()
            log.info("seed.checked", created=created)
    except Exception as exc:  # noqa: BLE001 - seed must never block the bot
        log.error("seed.failed", error=str(exc))

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    storage = RedisStorage(redis)
    dp = Dispatcher(storage=storage)

    sms = build_sms_provider()
    notifier = NotificationService(bot, sms)

    # Outer middlewares: DB session + user resolution, then dependency injection.
    context_mw = ContextMiddleware()
    deps_mw = DepsMiddleware(redis, notifier)
    dp.message.middleware(context_mw)
    dp.callback_query.middleware(context_mw)
    dp.message.middleware(deps_mw)
    dp.callback_query.middleware(deps_mw)

    dp.include_router(errors_handler.router)
    dp.include_router(build_root_router())

    # In-process reminders / digests / auto-completion (no separate worker needed).
    from app.background.scheduler import scheduler_loop

    scheduler_task = asyncio.create_task(scheduler_loop(bot, redis, sms))

    log.info("bot.starting")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        await bot.session.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
