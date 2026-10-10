"""Application configuration via Pydantic Settings. All secrets come from .env."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    bot_token: str = Field(..., alias="BOT_TOKEN")
    admin_ids: str = Field("", alias="ADMIN_IDS")  # comma-separated telegram ids

    # Database
    database_url: str = Field(..., alias="DATABASE_URL")  # postgresql+asyncpg://...

    # Redis / Arq
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")

    # Salon defaults
    salon_name: str = Field("Мой салон", alias="SALON_NAME")
    salon_address: str = Field("", alias="SALON_ADDRESS")
    salon_phone: str = Field("", alias="SALON_PHONE")
    timezone: str = Field("Europe/Chisinau", alias="TIMEZONE")
    currency: str = Field("MDL", alias="CURRENCY")
    default_language: str = Field("ru", alias="DEFAULT_LANGUAGE")

    # Booking rules
    slot_hold_seconds: int = Field(300, alias="SLOT_HOLD_SECONDS")
    min_cancel_hours: int = Field(2, alias="MIN_CANCEL_HOURS")
    reminder_hours_before: int = Field(24, alias="REMINDER_HOURS_BEFORE")
    reminder_hours_before_2: int = Field(2, alias="REMINDER_HOURS_BEFORE_2")

    # SMS (Twilio)
    sms_enabled: bool = Field(False, alias="SMS_ENABLED")
    twilio_account_sid: str = Field("", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field("", alias="TWILIO_AUTH_TOKEN")
    twilio_from_number: str = Field("", alias="TWILIO_FROM_NUMBER")

    @property
    def admin_id_set(self) -> set[int]:
        return {int(x) for x in self.admin_ids.split(",") if x.strip().isdigit()}

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


settings = Settings()  # type: ignore[call-arg]
