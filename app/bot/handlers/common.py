from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.bot import service
from app.bot.keyboards import main_menu, pro_kb, share_kb, support_kb, webapp_button
from app.core import energy as energy_svc
from app.core import settings_store
from app.core.catalog import catalog
from app.core.db import session_scope
from app.core.models import User

router = Router(name="common")


@router.message(CommandStart())
async def start(message: Message, user: User) -> None:
    async with session_scope() as s:
        welcome = await settings_store.get(s, "welcome") or {}
    text = welcome.get("text") or "Привет! Я БЕЛЕБАЛАРДЫХ AI."
    plan = catalog.plan("pro" if user.is_pro else "free")
    await message.answer(
        f"<b>{text}</b>\n\n"
        f"Тариф: <b>{plan.title}</b> · {energy_svc.energy_display(user.energy_tokens)} энергии\n"
        f"Модель: <b>{(catalog.get(user.current_model) or catalog.default_model(plan.code)).name}</b>\n\n"
        "Просто напишите вопрос. Команды: /model /balance /pro /new /support /help",
        reply_markup=main_menu(),
    )
    kb = webapp_button("💬 Открыть приложение")
    if kb:
        await message.answer("В приложении удобнее: история чатов, файлы, форматирование.", reply_markup=kb)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(
        "<b>Что умею</b>\n"
        "• Отвечаю текстом с форматированием, кодом и таблицами\n"
        "• Читаю фото (на моделях с 👁) и документы: PDF, DOCX, TXT, код\n"
        "• Помню контекст внутри чата — /new начинает новый\n\n"
        "<b>Команды</b>\n"
        "/model — выбрать нейросеть\n"
        "/balance — энергия и тариф\n"
        "/pro — подписка и промокод\n"
        "/new — новый чат\n"
        "/support — связаться с поддержкой\n"
        "/share — поделиться ботом\n"
        "/stop — прервать ответ"
    )


@router.message(Command("support"))
@router.message(F.text == "🆘 Поддержка")
async def support(message: Message) -> None:
    async with session_scope() as s:
        links = await settings_store.links(s)
    url = links["support_url"]
    if not url:
        await message.answer(
            "Поддержка пока не настроена. Напишите позже или через приложение."
        )
        return
    await message.answer(
        "<b>Поддержка</b>\n"
        "Опишите проблему одним сообщением: что делали, какая модель, что увидели. "
        "Если была ошибка — приложите её текст.",
        reply_markup=support_kb(url),
    )


@router.message(Command("share"))
async def share(message: Message) -> None:
    async with session_scope() as s:
        links = await settings_store.links(s)
    kb = share_kb(links["bot_username"], links["share_text"])
    if kb is None:
        await message.answer("Ссылка на бота не настроена.")
        return
    await message.answer(
        f"<b>Поделитесь ботом</b>\n{links['share_text']}\n\n"
        f"https://t.me/{links['bot_username']}",
        reply_markup=kb,
    )


@router.message(Command("new"))
@router.message(F.text == "🆕 Новый чат")
async def new_chat(message: Message, user: User) -> None:
    await service.new_chat(user.id)
    model = catalog.get(user.current_model) or catalog.default_model("free")
    await message.answer(f"🆕 Новый чат. Модель: <b>{model.name}</b>")


@router.message(Command("balance"))
@router.message(F.text == "⚡ Баланс")
async def balance(message: Message, user: User) -> None:
    fresh = await service.fresh_user(user.id) or user
    plan = catalog.plan("pro" if fresh.is_pro else "free")
    left = energy_svc.energy_display(fresh.energy_tokens)
    lines = [
        f"<b>Тариф:</b> {plan.title}",
        f"<b>Энергия:</b> {left} из {plan.energy}",
        f"<b>Запросов сделано:</b> {fresh.requests or 0}",
    ]
    if fresh.is_pro and fresh.plan_until:
        lines.append(f"<b>Pro до:</b> {fresh.plan_until:%d.%m.%Y}")
    elif fresh.refill_at:
        lines.append(f"<b>Пополнение:</b> {fresh.refill_at:%d.%m.%Y}")
    kb = None if fresh.is_pro else pro_kb()
    await message.answer("\n".join(lines), reply_markup=kb)
