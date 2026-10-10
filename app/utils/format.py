"""Datetime formatting helpers in salon timezone."""
from __future__ import annotations

import datetime as dt

from app.config import settings

_MONTHS_RU = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def to_local(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=settings.tz)
    return value.astimezone(settings.tz)


def fmt_date(value: dt.datetime) -> str:
    local = to_local(value)
    return f"{local.day} {_MONTHS_RU[local.month - 1]} {local.year}"


def fmt_time(value: dt.datetime) -> str:
    return to_local(value).strftime("%H:%M")


def fmt_short_date(value: dt.date) -> str:
    return value.strftime("%d.%m")


def stars(rating: float) -> str:
    full = int(round(rating))
    return "⭐" * max(0, min(5, full))
