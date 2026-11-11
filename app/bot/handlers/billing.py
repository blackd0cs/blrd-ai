from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import main_menu, pro_kb
from app.core import energy as energy_svc
from app.core.catalog import catalog
from app.core.db import session_scope
from app.core.models import Payment, User
from app.services import platega, promo as promo_svc

log = logging.getLogger("bot.billing")
router = Router(name="billing")


class PromoFlow(StatesGroup):
    waiting = State()


def paywall_text() -> str:
    pro = catalog.pro()
    feats = "\n".join(f"✓ {f}" for f in pro.features)
    return (
        f"<b>blrd ai Pro</b>\n"
        f"<b>{pro.price_rub} ₽</b> в месяц, без автосписаний\n\n{feats}\n\n"
        f"<i>1 энергия = {catalog.energy_unit} базовых токенов. "
        f"Pro получает {pro.energy} энергии на {pro.days} дней.</i>"
    )


async def send_paywall(message: Message, user: User) -> None:
    await message.answer(paywall_text(), reply_markup=pro_kb())


@router.message(Command("pro"))
@router.message(F.text == "💎 Pro")
async def pro_cmd(message: Message, user: User) -> None:
    if user.is_pro:
        until = f" до {user.plan_until:%d.%m.%Y}" if user.plan_until else ""
        await message.answer(
            f"У вас уже <b>Pro</b>{until}.\n"
            f"Энергия: {energy_svc.energy_display(user.energy_tokens)} из {catalog.pro().energy}.\n"
            "Оплата продлит подписку с текущей даты окончания.",
            reply_markup=pro_kb(),
        )
        return
    await send_paywall(message, user)


@router.callback_query(F.data == "pro")
async def pro_cb(call: CallbackQuery, user: User) -> None:
    await call.answer()
    await send_paywall(call.message, user)


@router.callback_query(F.data == "pay")
async def pay(call: CallbackQuery, user: User) -> None:
    await call.answer("Создаю платёж…")
    try:
        async with session_scope() as s:
            db_user = await s.get(User, user.id)
            payment = await platega.create_payment(s, db_user, source="bot")
            pay_url, pid, amount = payment.pay_url, payment.id, payment.amount
    except platega.PlategaError as e:
        log.error("payment failed uid=%s: %s", user.id, e)
        await call.message.answer(
            "Не получилось создать платёж. Попробуйте позже или напишите в поддержку."
        )
        return

    await call.message.answer(
        f"<b>Оплата {amount:g} ₽</b>\n"
        "Нажмите «Перейти к оплате». После успешной оплаты Pro включится автоматически — "
        "если уведомление не пришло, нажмите «Проверить».",
        reply_markup=pro_kb(pay_url, pid),
    )


@router.callback_query(F.data.startswith("chk:"))
async def check(call: CallbackQuery, user: User) -> None:
    pid = int(call.data.split(":")[1])
    async with session_scope() as s:
        payment = await s.get(Payment, pid)
        if payment is None or payment.user_id != user.id:
            await call.answer("Платёж не найден", show_alert=True)
            return
        if payment.applied:
            await call.answer("Pro уже активирован", show_alert=True)
            return
        if not payment.tx_id:
            await call.answer("Платёж ещё не создан на стороне Platega", show_alert=True)
            return
        try:
            remote = await platega.fetch_status(payment.tx_id)
        except platega.PlategaError as e:
            log.info("check failed %s: %s", payment.tx_id, e)
            await call.answer("Platega не отвечает, попробуйте через минуту", show_alert=True)
            return
        _, granted = await platega.apply_callback(
            s, {"id": payment.tx_id, "status": remote.get("status"), "payload": ""}
        )

    if granted:
        await call.answer("Готово!")
        await call.message.answer(
            f"✅ <b>Pro активирован</b> на {catalog.pro().days} дней.\n"
            f"Начислено {catalog.pro().energy} энергии — все модели открыты.",
            reply_markup=main_menu(),
        )
    else:
        await call.answer("Оплата пока не подтверждена", show_alert=True)


# ── промокоды ──────────────────────────────────────────────
@router.callback_query(F.data == "promo")
async def promo_ask(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(PromoFlow.waiting)
    await call.message.answer("Отправьте промокод одним сообщением. Отмена — /cancel")


@router.message(Command("promo"))
async def promo_cmd(message: Message, user: User, state: FSMContext) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await state.set_state(PromoFlow.waiting)
        await message.answer("Отправьте промокод одним сообщением. Отмена — /cancel")
        return
    await _apply(message, user, parts[1], state)


@router.message(Command("cancel"), StateFilter(PromoFlow.waiting))
async def promo_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменил.")


@router.message(StateFilter(PromoFlow.waiting), F.text)
async def promo_input(message: Message, user: User, state: FSMContext) -> None:
    await _apply(message, user, message.text or "", state)


async def _apply(message: Message, user: User, code: str, state: FSMContext) -> None:
    async with session_scope() as s:
        db_user = await s.get(User, user.id)
        try:
            text = await promo_svc.redeem(s, db_user, code)
        except promo_svc.PromoError as e:
            await message.answer(f"❌ {e}")
            return
        energy = energy_svc.energy_display(db_user.energy_tokens)
    await state.clear()
    await message.answer(f"✅ {text}\nЭнергия: {energy}", reply_markup=main_menu())
