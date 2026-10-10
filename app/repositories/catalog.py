"""Service catalog, masters, schedules, portfolio data access."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Master,
    MasterService,
    PortfolioItem,
    Review,
    Schedule,
    ScheduleException,
    Service,
    User,
)


class ServiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[Service]:
        res = await self.session.execute(
            select(Service).where(Service.is_active.is_(True)).order_by(Service.name)
        )
        return list(res.scalars().all())

    async def get(self, service_id: int) -> Service | None:
        return await self.session.get(Service, service_id)


class MasterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, master_id: int) -> Master | None:
        res = await self.session.execute(
            select(Master).where(Master.id == master_id).options(selectinload(Master.user))
        )
        return res.scalar_one_or_none()

    async def get_by_user_telegram_id(self, telegram_id: int) -> Master | None:
        res = await self.session.execute(
            select(Master).join(User).where(User.telegram_id == telegram_id)
        )
        return res.scalar_one_or_none()

    async def list_for_service(self, service_id: int) -> list[Master]:
        res = await self.session.execute(
            select(Master)
            .join(MasterService, MasterService.master_id == Master.id)
            .where(
                MasterService.service_id == service_id,
                MasterService.is_active.is_(True),
                Master.is_active.is_(True),
            )
            .options(selectinload(Master.user))
            .order_by(Master.rating.desc())
        )
        return list(res.scalars().unique().all())

    async def master_service(self, master_id: int, service_id: int) -> MasterService | None:
        res = await self.session.execute(
            select(MasterService).where(
                MasterService.master_id == master_id,
                MasterService.service_id == service_id,
            )
        )
        return res.scalar_one_or_none()

    async def schedule_for_weekday(self, master_id: int, weekday: int) -> Schedule | None:
        res = await self.session.execute(
            select(Schedule).where(
                Schedule.master_id == master_id, Schedule.weekday == weekday
            )
        )
        return res.scalar_one_or_none()

    async def exceptions_for_date(
        self, master_id: int, date: dt.date
    ) -> list[ScheduleException]:
        res = await self.session.execute(
            select(ScheduleException).where(
                ScheduleException.master_id == master_id,
                ScheduleException.date == date,
            )
        )
        return list(res.scalars().all())

    async def portfolio(self, master_id: int) -> list[PortfolioItem]:
        res = await self.session.execute(
            select(PortfolioItem)
            .where(PortfolioItem.master_id == master_id, PortfolioItem.is_active.is_(True))
            .order_by(PortfolioItem.created_at.desc())
        )
        return list(res.scalars().all())

    async def reviews(self, master_id: int, limit: int = 5) -> list[Review]:
        res = await self.session.execute(
            select(Review)
            .where(Review.master_id == master_id, Review.is_visible.is_(True))
            .order_by(Review.created_at.desc())
            .limit(limit)
        )
        return list(res.scalars().all())

    def effective_price(self, ms: MasterService | None, service: Service) -> float:
        if ms and ms.custom_price is not None:
            return float(ms.custom_price)
        return float(service.default_price)

    def effective_duration(self, ms: MasterService | None, service: Service) -> int:
        if ms and ms.custom_duration_minutes is not None:
            return int(ms.custom_duration_minutes)
        return int(service.default_duration_minutes)
