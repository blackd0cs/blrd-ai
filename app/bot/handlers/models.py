from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot import service
from app.bot.handlers.billing import send_paywall
from app.bot.keyboards import models_kb
from app.core import energy as energy_svc
from app.core.catalog import catalog
from app.core.models import User
from aiogram.filters import Command

router = Router(name="models")


def _header(user: User) -> str:
    plan = catalog.plan("pro" if user.is_pro else "free")
    return (
        f"<b>Выберите модель</b>\n"
        f"Баланс: {energy_svc.energy_display(user.energy_tokens)} из {plan.energy} энергии\n"
        f"<i>×коэффициент — во столько раз запрос дороже базового</i>"
    )


@router.message(Command("model"))
@router.message(F.text == "🧠 Модель")
async def choose(message: Message, user: User) -> None:
    plan = "pro" if user.is_pro else "free"
    await message.answer(_header(user), reply_markup=models_kb(plan, user.current_model))


@router.callback_query(F.data.startswith("m:"))
async def pick(call: CallbackQuery, user: User) -> None:
    idx = int(call.data.split(":")[1])
    models = catalog.models()
    if idx >= len(models):
        await call.answer("Модель больше недоступна", show_alert=True)
        return
    model = models[idx]
    plan = "pro" if user.is_pro else "free"

    if not model.allowed_for(plan):
        await call.answer("Эта модель доступна в Pro", show_alert=True)
        await send_paywall(call.message, user)
        return

    await service.set_model(user.id, model.path)
    await call.answer(f"Модель: {model.name}")
    try:
        await call.message.edit_text(_header(user), reply_markup=models_kb(plan, model.path))
    except Exception:
        pass
