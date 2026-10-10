"""Keyboard builders — reply menus and inline keyboards."""
from __future__ import annotations

import datetime as dt

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.db.models import Master, Service
from app.keyboards.callbacks import (
    AdminCb,
    ApptActionCb,
    ConfirmCb,
    DateCb,
    LangCb,
    MasterApptCb,
    MasterCb,
    MasterModeCb,
    PortfolioCb,
    ReviewCb,
    ServiceCb,
    SkipCb,
    TimeCb,
)
from app.locales import t
from app.utils.format import fmt_short_date


def main_menu(lang: str, is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t("menu.book", lang)), KeyboardButton(text=t("menu.my", lang))],
        [
            KeyboardButton(text=t("menu.masters", lang)),
            KeyboardButton(text=t("menu.services", lang)),
        ],
        [
            KeyboardButton(text=t("menu.contacts", lang)),
            KeyboardButton(text=t("menu.support", lang)),
        ],
        [KeyboardButton(text=t("menu.language", lang))],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=t("admin.menu", lang))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def contact_request(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("book.share_button", lang), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def services_kb(services: list[Service], lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in services:
        b.button(
            text=f"{s.name} · {int(s.default_price)} {settings.currency}",
            callback_data=ServiceCb(service_id=s.id),
        )
    b.adjust(1)
    return b.as_markup()


def master_mode_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("book.pick_master_self", lang), callback_data=MasterModeCb(mode="self"))
    b.button(
        text=t("book.auto_soonest", lang), callback_data=MasterModeCb(mode="auto_soonest")
    )
    b.button(text=t("book.auto_best", lang), callback_data=MasterModeCb(mode="auto_best"))
    b.adjust(1)
    return b.as_markup()


def master_card_kb(master: Master, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("master.portfolio", lang), callback_data=MasterCb(master_id=master.id, action="portfolio"))
    b.button(text=t("master.reviews", lang), callback_data=MasterCb(master_id=master.id, action="reviews"))
    b.button(text=t("master.choose", lang), callback_data=MasterCb(master_id=master.id, action="pick"))
    b.adjust(2, 1)
    return b.as_markup()


def portfolio_kb(master_id: int, index: int, total: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if index > 0:
        b.button(text=t("prev", lang), callback_data=PortfolioCb(master_id=master_id, index=index - 1))
    if index < total - 1:
        b.button(text=t("next", lang), callback_data=PortfolioCb(master_id=master_id, index=index + 1))
    b.button(text=t("master.book_to", lang), callback_data=MasterCb(master_id=master_id, action="pick"))
    b.adjust(2, 1)
    return b.as_markup()


def dates_kb(days: list[dt.date], lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in days:
        b.button(text=fmt_short_date(d), callback_data=DateCb(iso=d.isoformat()))
    b.adjust(4)
    return b.as_markup()


def times_kb(slots: list[dt.datetime], lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in slots:
        b.button(text=s.strftime("%H:%M"), callback_data=TimeCb(ts=int(s.timestamp())))
    b.adjust(4)
    return b.as_markup()


def comment_skip_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("book.skip", lang), callback_data=SkipCb(what="comment"))
    return b.as_markup()


def confirm_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("confirm", lang), callback_data=ConfirmCb(action="confirm"))
    b.button(text=t("edit", lang), callback_data=ConfirmCb(action="edit"))
    b.button(text=t("cancel", lang), callback_data=ConfirmCb(action="cancel"))
    b.adjust(1)
    return b.as_markup()


def my_appt_kb(appointment_id: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("my.reschedule", lang), callback_data=ApptActionCb(appointment_id=appointment_id, action="reschedule"))
    b.button(text=t("my.cancel", lang), callback_data=ApptActionCb(appointment_id=appointment_id, action="cancel"))
    b.adjust(1)
    return b.as_markup()


def master_new_appt_kb(appointment_id: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("notify.master.confirm", lang), callback_data=MasterApptCb(appointment_id=appointment_id, action="confirm"))
    b.button(text=t("notify.master.decline", lang), callback_data=MasterApptCb(appointment_id=appointment_id, action="decline"))
    b.adjust(2)
    return b.as_markup()


def review_kb(appointment_id: int, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in range(1, 6):
        b.button(text="⭐" * r, callback_data=ReviewCb(appointment_id=appointment_id, rating=r))
    b.adjust(1)
    return b.as_markup()


def review_text_skip_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("book.skip", lang), callback_data=SkipCb(what="review"))
    return b.as_markup()


def lang_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🇷🇺 Русский", callback_data=LangCb(code="ru"))
    b.button(text="🇷🇴 Română", callback_data=LangCb(code="ro"))
    b.button(text="🇬🇧 English", callback_data=LangCb(code="en"))
    b.adjust(1)
    return b.as_markup()


def admin_menu_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for section, key in [
        ("today", "admin.today"),
        ("all", "admin.all"),
        ("masters", "admin.masters"),
        ("services", "admin.services"),
        ("clients", "admin.clients"),
        ("reviews", "admin.reviews"),
        ("stats", "admin.stats"),
        ("broadcast", "admin.broadcast"),
        ("export", "admin.export"),
        ("settings", "admin.settings"),
    ]:
        b.button(text=t(key, lang), callback_data=AdminCb(section=section))
    b.adjust(2)
    return b.as_markup()
