from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
    ReplyKeyboardMarkup, WebAppInfo,
)

from app.core.catalog import ModelSpec, catalog
from app.core.config import settings


def main_menu() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🧠 Модель"), KeyboardButton(text="⚡ Баланс")],
        [KeyboardButton(text="🆕 Новый чат"), KeyboardButton(text="💎 Pro")],
        [KeyboardButton(text="🆘 Поддержка")],
    ]
    if settings.webapp_url.startswith("https://"):
        rows.insert(0, [KeyboardButton(
            text="💬 Открыть приложение",
            web_app=WebAppInfo(url=settings.webapp_url),
        )])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def webapp_button(text: str = "Открыть приложение") -> InlineKeyboardMarkup | None:
    if not settings.webapp_url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.webapp_url))]
    ])


def support_kb(url: str) -> InlineKeyboardMarkup | None:
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆘 Написать в поддержку", url=url)]
    ])


def share_kb(bot_username: str, text: str) -> InlineKeyboardMarkup | None:
    if not bot_username:
        return None
    link = f"https://t.me/{bot_username}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📣 Поделиться ботом",
            switch_inline_query=f"{text} {link}",
        )]
    ])


def stop_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏹ Остановить", callback_data="stop")]
    ])


def models_kb(plan: str, current: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i, m in enumerate(catalog.models()):
        rows.append([InlineKeyboardButton(text=_model_label(m, plan, current), callback_data=f"m:{i}")])
    if plan != "pro":
        rows.append([InlineKeyboardButton(text="💎 Открыть все модели — Pro", callback_data="pro")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _model_label(m: ModelSpec, plan: str, current: str | None) -> str:
    mark = "✅ " if m.path == current else ""
    if not m.allowed_for(plan):
        return f"🔒 {m.name} · PRO"
    price = "бесплатно" if m.free else f"×{m.multiplier:g}"
    eye = " 👁" if m.vision else ""
    return f"{mark}{m.name} · {price}{eye}"


def pro_kb(pay_url: str | None = None, payment_id: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if pay_url:
        rows.append([InlineKeyboardButton(text="💳 Перейти к оплате", url=pay_url)])
        rows.append([InlineKeyboardButton(text="🔄 Я оплатил, проверить", callback_data=f"chk:{payment_id}")])
    else:
        pro = catalog.pro()
        rows.append([InlineKeyboardButton(
            text=f"💎 Оформить Pro — {pro.price_rub} ₽", callback_data="pay")])
    rows.append([InlineKeyboardButton(text="🎁 У меня есть промокод", callback_data="promo")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
