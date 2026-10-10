"""Review flow: only after a completed appointment, one review per appointment."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppointmentStatus, User
from app.keyboards.builders import review_text_skip_kb
from app.keyboards.callbacks import ReviewCb, SkipCb
from app.locales import t
from app.repositories.appointments import AppointmentRepository, ReviewRepository
from app.states import ReviewStates

router = Router(name="reviews")


@router.callback_query(ReviewCb.filter())
async def rate(
    query: CallbackQuery, callback_data: ReviewCb, user: User, session: AsyncSession, state: FSMContext
) -> None:
    appt = await AppointmentRepository(session).get(callback_data.appointment_id)
    if appt is None or appt.client_id != user.id:
        await query.answer(t("error.not_owner", user.language), show_alert=True)
        return
    if appt.status != AppointmentStatus.completed:
        await query.answer(t("review.already", user.language), show_alert=True)
        return
    review_repo = ReviewRepository(session)
    if await review_repo.exists_for_appointment(appt.id):
        await query.answer(t("review.already", user.language), show_alert=True)
        return
    await state.set_state(ReviewStates.text)
    await state.update_data(appointment_id=appt.id, master_id=appt.master_id, rating=callback_data.rating)
    await query.message.answer(t("review.ask_text", user.language), reply_markup=review_text_skip_kb(user.language))  # type: ignore[union-attr]
    await query.answer()


@router.message(ReviewStates.text, F.text)
async def review_text(message: Message, user: User, session: AsyncSession, state: FSMContext) -> None:
    await _save_review(message, user, session, state, message.text.strip())


@router.callback_query(ReviewStates.text, SkipCb.filter(F.what == "review"))
async def review_skip(query: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    await _save_review(query.message, user, session, state, None)  # type: ignore[arg-type]
    await query.answer()


async def _save_review(
    message: Message, user: User, session: AsyncSession, state: FSMContext, text: str | None
) -> None:
    data = await state.get_data()
    review_repo = ReviewRepository(session)
    if await review_repo.exists_for_appointment(data["appointment_id"]):
        await message.answer(t("review.already", user.language))
        await state.clear()
        return
    await review_repo.add(
        appointment_id=data["appointment_id"],
        client_id=user.id,
        master_id=data["master_id"],
        rating=data["rating"],
        text=text,
    )
    await review_repo.recompute_master_rating(data["master_id"])
    await session.flush()
    await message.answer(t("review.thanks", user.language))
    await state.clear()
