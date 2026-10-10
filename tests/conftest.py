"""Shared fixtures. Uses in-memory SQLite so tests run without Postgres.

Note: the partial unique index (postgresql_where) is Postgres-only; on SQLite the
double-booking guard is exercised via the FOR-UPDATE overlap check in BookingService,
which is the primary application-level protection.
"""
from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    Master,
    MasterService,
    Role,
    Schedule,
    Service,
    User,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded(session):
    """Create a client, a master, a service, master_service link and a full schedule."""
    client = User(telegram_id=1000, role=Role.client, full_name="Клиент", phone="+3730001")
    muser = User(telegram_id=2000, role=Role.master, full_name="Мастер", phone="+3730002")
    session.add_all([client, muser])
    await session.flush()

    master = Master(user_id=muser.id, rating=5.0, review_count=0, experience_years=5)
    service = Service(name="Стрижка", default_price=250, default_duration_minutes=60, buffer_minutes=0)
    session.add_all([master, service])
    await session.flush()

    session.add(MasterService(master_id=master.id, service_id=service.id))
    # Every weekday 10:00-18:00, no break
    for wd in range(7):
        session.add(
            Schedule(
                master_id=master.id,
                weekday=wd,
                start_time=dt.time(10, 0),
                end_time=dt.time(18, 0),
                is_working_day=True,
            )
        )
    await session.flush()
    return {"client": client, "master": master, "service": service, "muser": muser}
