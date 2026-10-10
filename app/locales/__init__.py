"""Minimal i18n. Texts stored in dicts, not in handlers. Russian is default."""
from __future__ import annotations

from app.locales.en import EN
from app.locales.ro import RO
from app.locales.ru import RU

_LOCALES: dict[str, dict[str, str]] = {"ru": RU, "ro": RO, "en": EN}
DEFAULT = "ru"


def variants(key: str) -> set[str]:
    """The text of `key` in every language (for matching reply-keyboard buttons)."""
    return {t(key, lang) for lang in _LOCALES}


def t(key: str, lang: str = DEFAULT, /, **kwargs: object) -> str:
    table = _LOCALES.get(lang, RU)
    template = table.get(key) or RU.get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template
