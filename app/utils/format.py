"""Datetime formatting helpers in salon timezone."""
from __future__ import annotations

import datetime as dt
import re

from app.config import settings

_MONTHS = {
    "ru": [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ],
    "ro": [
        "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
        "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
}


def to_local(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=settings.tz)
    return value.astimezone(settings.tz)


def fmt_date(value: dt.datetime, lang: str = "ru") -> str:
    local = to_local(value)
    months = _MONTHS.get(lang, _MONTHS["ru"])
    return f"{local.day} {months[local.month - 1]} {local.year}"


def fmt_time(value: dt.datetime) -> str:
    return to_local(value).strftime("%H:%M")


def fmt_short_date(value: dt.date) -> str:
    return value.strftime("%d.%m")


def stars(rating: float) -> str:
    full = int(round(rating))
    return "⭐" * max(0, min(5, full))


TELEGRAM_TEXT_LIMIT = 4096


def chunk_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT - 96) -> list[str]:
    """Split a long message on line boundaries so each part fits into one Telegram message."""
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # a single huge line
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current or not parts:
        parts.append(current)
    return parts


_PLAIN_PHONE = re.compile(r"^\+?\d{6,15}$")


def csv_safe(value: object) -> object:
    """Neutralise spreadsheet formulas (=, +, -, @ ...) in user-controlled CSV cells.
    Plain phone numbers like +37360123456 are left as they are."""
    if (
        isinstance(value, str)
        and value[:1] in ("=", "+", "-", "@", "\t", "\r")
        and not _PLAIN_PHONE.fullmatch(value)
    ):
        return "'" + value
    return value
