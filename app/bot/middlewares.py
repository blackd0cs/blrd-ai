from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

from app.core import energy as energy_svc
from app.core import settings_store
from app.core.config import settings
from app.core.db import session_scope
from app.core.security import upsert_user

log = logging.getLogger("bot.mw")


class UserMiddleware(BaseMiddleware):
    """Создаёт/обновляет пользователя и кладёт его в data['user']."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg: TgUser | None = data.get("event_from_user")
        if tg is None or tg.is_bot:
            return None

        async with session_scope() as s:
            user = await upsert_user(
                s,
                {
                    "id": tg.id,
                    "username": tg.username,
                    "first_name": tg.first_name,
                    "last_name": tg.last_name,
                    "language_code": tg.language_code,
                },
                source="bot",
            )
            maintenance, maint_text = await settings_store.maintenance(s)
            energy_svc.ensure_plan_state(user)

        if user.is_banned:
            text = user.ban_reason or "Доступ к боту закрыт."
            if isinstance(event, Message):
                await event.answer(f"⛔️ {text}")
            elif isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            return None

        if maintenance and not (user.is_admin or user.id in settings.admin_ids):
            msg = f"🛠 {maint_text}"
            if isinstance(event, Message):
                await event.answer(msg)
            elif isinstance(event, CallbackQuery):
                await event.answer(maint_text, show_alert=True)
            return None

        data["user"] = user
        return await handler(event, data)
