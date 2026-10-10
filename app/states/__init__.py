"""FSM state groups for multi-step dialogs."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BookingStates(StatesGroup):
    choosing_service = State()
    choosing_master_mode = State()
    choosing_master = State()
    choosing_date = State()
    choosing_time = State()
    entering_contact = State()
    entering_comment = State()
    confirming = State()


class CancelStates(StatesGroup):
    entering_reason = State()


class RescheduleStates(StatesGroup):
    choosing_date = State()
    choosing_time = State()


class ReviewStates(StatesGroup):
    rating = State()
    text = State()


class MasterDeclineStates(StatesGroup):
    reason = State()


class BroadcastStates(StatesGroup):
    text = State()
    confirm = State()


class AdminEditStates(StatesGroup):
    choosing_date = State()
    choosing_time = State()
