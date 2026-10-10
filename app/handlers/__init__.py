"""Router aggregation. Order matters: specific routers before generic menu."""
from __future__ import annotations

from aiogram import Router

from app.handlers import admin, admin_edit, booking, common, master, my_appointments, reviews


def build_root_router() -> Router:
    root = Router()
    root.include_router(common.router)
    root.include_router(booking.router)
    root.include_router(my_appointments.router)
    root.include_router(master.router)
    root.include_router(reviews.router)
    root.include_router(admin_edit.router)
    root.include_router(admin.router)
    return root
