"""All SQLAlchemy 2.0 ORM models."""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Role(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    master = "master"
    client = "client"


class AppointmentStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    completed = "completed"
    cancelled_by_client = "cancelled_by_client"
    cancelled_by_master = "cancelled_by_master"
    cancelled_by_admin = "cancelled_by_admin"
    rescheduled = "rescheduled"
    no_show = "no_show"


CANCELLED_STATUSES = {
    AppointmentStatus.cancelled_by_client,
    AppointmentStatus.cancelled_by_master,
    AppointmentStatus.cancelled_by_admin,
}
ACTIVE_STATUSES = {AppointmentStatus.pending, AppointmentStatus.confirmed}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.client)
    full_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    username: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(4), default="ru")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    master: Mapped["Master | None"] = relationship(back_populates="user", uselist=False)


class Master(Base):
    __tablename__ = "masters"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    specialization: Mapped[str | None] = mapped_column(String(255))
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float] = mapped_column(Numeric(3, 1), default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    telegram_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sms_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_phone: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="master")
    services: Mapped[list["MasterService"]] = relationship(back_populates="master")
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="master")
    portfolio: Mapped[list["PortfolioItem"]] = relationship(back_populates="master")


class ServiceCategory(Base):
    __tablename__ = "service_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("service_categories.id"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    default_price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    default_duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)
    photo_file_id: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MasterService(Base):
    __tablename__ = "master_services"
    __table_args__ = (UniqueConstraint("master_id", "service_id", name="uq_master_service"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    custom_price: Mapped[float | None] = mapped_column(Numeric(10, 2))
    custom_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    master: Mapped[Master] = relationship(back_populates="services")
    service: Mapped[Service] = relationship()


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (UniqueConstraint("master_id", "weekday", name="uq_master_weekday"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"))
    weekday: Mapped[int] = mapped_column(Integer)  # 0=Mon .. 6=Sun
    start_time: Mapped[dt.time] = mapped_column(Time)
    end_time: Mapped[dt.time] = mapped_column(Time)
    break_start: Mapped[dt.time | None] = mapped_column(Time)
    break_end: Mapped[dt.time | None] = mapped_column(Time)
    is_working_day: Mapped[bool] = mapped_column(Boolean, default=True)

    master: Mapped[Master] = relationship(back_populates="schedules")


class ScheduleException(Base):
    __tablename__ = "schedule_exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"))
    date: Mapped[dt.date] = mapped_column()
    start_time: Mapped[dt.time | None] = mapped_column(Time)
    end_time: Mapped[dt.time | None] = mapped_column(Time)
    exception_type: Mapped[str] = mapped_column(String(32))  # day_off | block | custom_hours
    reason: Mapped[str | None] = mapped_column(String(255))


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index(
            "uq_active_master_start",
            "master_id",
            "start_at",
            unique=True,
            postgresql_where="status IN ('pending','confirmed')",
        ),
        Index("ix_appt_master_time", "master_id", "start_at", "end_at"),
        Index("ix_appt_client", "client_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    start_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus), default=AppointmentStatus.pending
    )
    client_comment: Mapped[str | None] = mapped_column(Text)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    client: Mapped[User] = relationship()
    master: Mapped[Master] = relationship()
    service: Mapped[Service] = relationship()


class AppointmentHistory(Base):
    __tablename__ = "appointment_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"))
    changed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    old_data: Mapped[str | None] = mapped_column(Text)
    new_data: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PortfolioItem(Base):
    __tablename__ = "portfolio_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"))
    telegram_file_id: Mapped[str] = mapped_column(String(255))
    caption: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    master: Mapped[Master] = relationship(back_populates="portfolio")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("appointment_id", name="uq_review_appointment"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_rating_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"))
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"))
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"))
    channel: Mapped[str] = mapped_column(String(16))  # telegram | sms
    notification_type: Mapped[str] = mapped_column(String(32))
    scheduled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)


class SalonSettings(Base):
    __tablename__ = "salon_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="Мой салон")
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(32))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Chisinau")
    currency: Mapped[str] = mapped_column(String(8), default="MDL")
    map_url: Mapped[str | None] = mapped_column(String(500))
    cancellation_policy: Mapped[str | None] = mapped_column(Text)
    greeting_text: Mapped[str | None] = mapped_column(Text)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
