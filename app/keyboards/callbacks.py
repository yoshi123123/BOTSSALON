"""Typed callback data via aiogram CallbackData factories."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class ServiceCb(CallbackData, prefix="svc"):
    service_id: int


class MasterModeCb(CallbackData, prefix="mmode"):
    mode: str  # self | auto_soonest | auto_best


class MasterCb(CallbackData, prefix="mst"):
    master_id: int
    action: str  # pick | portfolio | reviews


class PortfolioCb(CallbackData, prefix="pf"):
    master_id: int
    index: int


class DateCb(CallbackData, prefix="date"):
    iso: str  # YYYY-MM-DD


class TimeCb(CallbackData, prefix="time"):
    ts: int  # unix timestamp of slot start


class ConfirmCb(CallbackData, prefix="cfm"):
    action: str  # confirm | edit | cancel


class ApptActionCb(CallbackData, prefix="appt"):
    appointment_id: int
    action: str  # cancel | reschedule | repeat | confirm_visit


class MasterApptCb(CallbackData, prefix="mappt"):
    appointment_id: int
    action: str  # confirm | decline
    ts: int  # appointment start the master was shown (stale after a reschedule)


class ReviewCb(CallbackData, prefix="rev"):
    appointment_id: int
    rating: int


class LangCb(CallbackData, prefix="lang"):
    code: str


class AdminCb(CallbackData, prefix="adm"):
    section: str


class AdminApptCb(CallbackData, prefix="aappt"):
    appointment_id: int
    action: str  # view | reschedule | master | status | cancel


class AdminPickCb(CallbackData, prefix="apick"):
    appointment_id: int
    kind: str  # master | status
    value: str


class SkipCb(CallbackData, prefix="skip"):
    what: str
