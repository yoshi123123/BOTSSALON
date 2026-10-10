"""Demo seed: salon settings, categories, services, masters with schedules,
ratings and reviews. Idempotent — safe to run on every startup: if demo data
already exists, it does nothing.

Run manually:  python -m app.seed
Or automatically at bot startup (see app/main.py).
"""
from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import async_session_factory
from app.db.models import (
    Appointment,
    AppointmentStatus,
    Master,
    MasterService,
    Review,
    Role,
    SalonSettings,
    Schedule,
    Service,
    ServiceCategory,
    User,
)

# Demo masters use obviously-fake telegram ids (negative range is not possible,
# so use small reserved ids that no real user will have).
DEMO_MARKER_TG_ID = 1  # existence of this user == seed already applied


async def _already_seeded(session: AsyncSession) -> bool:
    """Skip when demo data was applied before, or the owner already has a real catalog."""
    res = await session.execute(select(User.id).where(User.telegram_id == DEMO_MARKER_TG_ID))
    if res.scalar_one_or_none() is not None:
        return True
    res = await session.execute(select(Service.id).limit(1))
    return res.scalar_one_or_none() is not None


async def seed_demo(session: AsyncSession) -> bool:
    """Populate demo data. Returns True if seeding happened, False if skipped."""
    if await _already_seeded(session):
        return False

    # --- salon settings ---
    salon = (await session.execute(select(SalonSettings).limit(1))).scalar_one_or_none()
    if salon is None:
        session.add(
            SalonSettings(
                name=settings.salon_name,
                address=settings.salon_address or None,
                phone=settings.salon_phone or None,
                timezone=settings.timezone,
                currency=settings.currency,
            )
        )

    # --- categories ---
    cat_hair = ServiceCategory(name="Парикмахерские услуги", sort_order=1)
    cat_nails = ServiceCategory(name="Ногтевой сервис", sort_order=2)
    session.add_all([cat_hair, cat_nails])
    await session.flush()

    # --- services ---
    services = {
        "men_cut": Service(category_id=cat_hair.id, name="Мужская стрижка",
                           description="Классическая или модельная стрижка",
                           default_price=250, default_duration_minutes=45, buffer_minutes=10),
        "women_cut": Service(category_id=cat_hair.id, name="Женская стрижка",
                             description="Стрижка любой сложности с укладкой",
                             default_price=400, default_duration_minutes=60, buffer_minutes=10),
        "color": Service(category_id=cat_hair.id, name="Окрашивание",
                         description="Однотонное окрашивание, тонирование",
                         default_price=800, default_duration_minutes=120, buffer_minutes=15),
        "beard": Service(category_id=cat_hair.id, name="Оформление бороды",
                         description="Моделирование и уход",
                         default_price=180, default_duration_minutes=30, buffer_minutes=5),
        "manicure": Service(category_id=cat_nails.id, name="Маникюр",
                            description="Классический / аппаратный, покрытие гель-лак",
                            default_price=350, default_duration_minutes=90, buffer_minutes=10),
        "pedicure": Service(category_id=cat_nails.id, name="Педикюр",
                            description="Аппаратный педикюр с покрытием",
                            default_price=450, default_duration_minutes=90, buffer_minutes=10),
    }
    session.add_all(services.values())
    await session.flush()

    # --- masters (demo users with tiny fake telegram ids 1..3) ---
    def make_user(tg: int, name: str) -> User:
        return User(telegram_id=tg, role=Role.master, full_name=name,
                    phone=f"+37360000{tg:03d}", language="ru")

    u1 = make_user(1, "Ион Барберу")
    u2 = make_user(2, "Мария Стилист")
    u3 = make_user(3, "Анна Нейл")
    session.add_all([u1, u2, u3])
    await session.flush()

    m1 = Master(user_id=u1.id, specialization="Мужские стрижки, борода",
                description="Барбер с международными сертификатами", experience_years=7,
                rating=4.9, review_count=0)
    m2 = Master(user_id=u2.id, specialization="Женские стрижки, окрашивание",
                description="Колорист, работает с любыми техниками", experience_years=9,
                rating=4.8, review_count=0)
    m3 = Master(user_id=u3.id, specialization="Маникюр, педикюр",
                description="Мастер ногтевого сервиса, стерильность 100%", experience_years=5,
                rating=5.0, review_count=0)
    session.add_all([m1, m2, m3])
    await session.flush()

    # --- master ↔ services ---
    links = [
        (m1, ["men_cut", "beard"]),
        (m2, ["women_cut", "color", "men_cut"]),
        (m3, ["manicure", "pedicure"]),
    ]
    for master, keys in links:
        for key in keys:
            session.add(MasterService(master_id=master.id, service_id=services[key].id))

    # --- schedules: Mon-Sat 10:00-19:00, lunch 14-15; Sunday off ---
    for master in (m1, m2, m3):
        for wd in range(6):
            session.add(Schedule(master_id=master.id, weekday=wd,
                                 start_time=dt.time(10, 0), end_time=dt.time(19, 0),
                                 break_start=dt.time(14, 0), break_end=dt.time(15, 0),
                                 is_working_day=True))
        session.add(Schedule(master_id=master.id, weekday=6,
                             start_time=dt.time(10, 0), end_time=dt.time(19, 0),
                             is_working_day=False))

    # --- demo client + completed appointments + reviews (so ratings are real) ---
    demo_client = User(telegram_id=4, role=Role.client, full_name="Демо Клиент",
                       phone="+37360000004", language="ru")
    session.add(demo_client)
    await session.flush()

    tz = settings.tz
    past = dt.datetime.now(tz) - dt.timedelta(days=7)
    review_data = [
        (m1, services["men_cut"], 5, "Отличная стрижка, очень доволен!"),
        (m1, services["beard"], 5, "Борода — огонь. Рекомендую."),
        (m2, services["color"], 5, "Цвет получился именно такой, как хотела."),
        (m2, services["women_cut"], 4, "Хорошая стрижка, чуть долго ждала."),
        (m3, services["manicure"], 5, "Идеальный маникюр, держится третью неделю."),
    ]
    for i, (master, service, rating, text) in enumerate(review_data):
        start = past + dt.timedelta(hours=i * 2)
        appt = Appointment(
            client_id=demo_client.id, master_id=master.id, service_id=service.id,
            start_at=start, end_at=start + dt.timedelta(minutes=60),
            price=service.default_price, status=AppointmentStatus.completed,
        )
        session.add(appt)
        await session.flush()
        session.add(Review(appointment_id=appt.id, client_id=demo_client.id,
                           master_id=master.id, rating=rating, text=text))

    # recompute ratings from the actual reviews
    from app.repositories.appointments import ReviewRepository
    review_repo = ReviewRepository(session)
    for master in (m1, m2, m3):
        await review_repo.recompute_master_rating(master.id)

    await session.flush()
    return True


async def sync_salon_settings(session: AsyncSession) -> None:
    """Apply SALON_* / TIMEZONE / CURRENCY env vars that are explicitly set to the stored
    salon settings, so changing them in Railway Variables takes effect on redeploy."""
    salon = (await session.execute(select(SalonSettings).limit(1))).scalar_one_or_none()
    if salon is None:
        return  # handlers fall back to the env values
    explicit = settings.model_fields_set
    mapping = {
        "salon_name": "name",
        "salon_address": "address",
        "salon_phone": "phone",
        "timezone": "timezone",
        "currency": "currency",
    }
    for field, column in mapping.items():
        if field in explicit:
            value = getattr(settings, field) or None
            if column in {"name", "timezone", "currency"} and value is None:
                continue  # NOT NULL columns
            setattr(salon, column, value)
    await session.flush()


async def bind_master_telegram_id(session: AsyncSession) -> bool:
    """MASTER_TELEGRAM_ID: attach a real Telegram account to the first demo master so that
    new-booking notifications (with Confirm/Decline buttons) reach a real person.
    Idempotent and safe to run on every start (also when the variable is set later)."""
    tg_id = settings.master_telegram_id
    if not tg_id:
        return False
    demo_master = (
        await session.execute(
            select(Master).join(User, User.id == Master.user_id)
            .where(User.telegram_id == DEMO_MARKER_TG_ID)
        )
    ).scalar_one_or_none()
    if demo_master is None:
        return False  # no demo master left (already bound or demo data removed)
    real = (
        await session.execute(select(User).where(User.telegram_id == tg_id))
    ).scalar_one_or_none()
    if real is None:
        demo_user = await session.get(User, demo_master.user_id)
        real = User(telegram_id=tg_id, full_name=demo_user.full_name if demo_user else None,
                    language="ru", language_selected=False)
        session.add(real)
        await session.flush()
    already_master = (
        await session.execute(select(Master.id).where(Master.user_id == real.id))
    ).scalar_one_or_none()
    if already_master is not None:
        return False
    if real.role == Role.client:
        real.role = Role.master
    demo_master.user_id = real.id
    await session.flush()
    return True


async def main() -> None:
    async with async_session_factory() as session:
        created = await seed_demo(session)
        await bind_master_telegram_id(session)
        await sync_salon_settings(session)
        await session.commit()
        print("Seed:", "created demo data" if created else "already present, skipped")


if __name__ == "__main__":
    asyncio.run(main())
