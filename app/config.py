"""Application configuration via Pydantic Settings. All secrets come from env / .env."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

SUPPORTED_LANGUAGES = ("ru", "ro", "en")


def normalize_database_url(url: str) -> str:
    """Make any Postgres URL usable by SQLAlchemy's async engine.

    Railway / Heroku / Render hand out ``postgresql://`` or ``postgres://`` URLs, which
    SQLAlchemy maps to a sync driver. We always talk to Postgres through asyncpg, which
    also does not understand libpq's ``sslmode=`` query parameter (it uses ``ssl=``).
    Non-Postgres URLs (e.g. sqlite+aiosqlite for tests) are returned unchanged.
    Parsed with SQLAlchemy's own URL parser, so unusual passwords survive unchanged.
    """
    url = url.strip()
    if not url:
        return url
    try:
        parsed = make_url(url)
    except ArgumentError:
        return url  # let create_async_engine report the problem
    backend = parsed.drivername.split("+", 1)[0].lower()
    if backend not in {"postgres", "postgresql"}:
        return url
    query: dict[str, str | tuple[str, ...]] = {}
    for key, value in parsed.query.items():
        if key == "sslmode":
            query["ssl"] = value
        elif key in {"channel_binding", "options", "target_session_attrs"}:
            continue  # libpq-only parameters that asyncpg would reject
        else:
            query[key] = value
    parsed = parsed.set(drivername="postgresql+asyncpg", query=query)
    return parsed.render_as_string(hide_password=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    bot_token: str = Field(..., alias="BOT_TOKEN")
    admin_ids: str = Field("", alias="ADMIN_IDS")  # comma-separated telegram ids

    # Database
    database_url: str = Field(..., alias="DATABASE_URL")  # postgresql://... or postgresql+asyncpg://...

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

    # Demo data
    seed_demo: bool = Field(True, alias="SEED_DEMO")
    master_telegram_id: int | None = Field(None, alias="MASTER_TELEGRAM_ID")

    @field_validator("bot_token", "database_url")
    @classmethod
    def _not_blank(cls, value: str, info) -> str:  # noqa: ANN001
        if not value or not value.strip():
            raise ValueError(f"{info.field_name.upper()} is empty")
        return value.strip()

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, value: str) -> str:
        return normalize_database_url(value)

    @field_validator("master_telegram_id", mode="before")
    @classmethod
    def _blank_master_id(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("default_language")
    @classmethod
    def _known_language(cls, value: str) -> str:
        value = value.strip().lower()
        return value if value in SUPPORTED_LANGUAGES else "ru"

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        ZoneInfo(value.strip())  # raises early with a clear error if unknown
        return value.strip()

    @property
    def admin_id_set(self) -> set[int]:
        ids: set[int] = set()
        for part in self.admin_ids.replace(";", ",").split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                ids.add(int(part))
        return ids

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


settings = Settings()  # type: ignore[call-arg]
