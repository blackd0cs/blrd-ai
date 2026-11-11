from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Setting, utcnow

DEFAULTS: dict[str, Any] = {
    "maintenance": {"enabled": False, "message": "Идут технические работы, скоро вернёмся."},
    "signup_enabled": {"enabled": True},
    "welcome": {
        "text": "Привет! Я БЕЛЕБАЛАРДЫХ AI — доступ к лучшим моделям прямо в Telegram.\n"
                "Открой приложение кнопкой ниже или просто напиши мне сообщение."
    },
    "system_prompt": {"enabled": False},  # общий промпт из models.yml для обычных моделей
    "rate_limit": {"per_minute": 20},
    # пустые значения означают «взять из .env»
    "links": {"support_url": "", "share_text": "", "bot_username": ""},
}


async def get(session: AsyncSession, key: str) -> Any:
    row = await session.get(Setting, key)
    if row is None or row.value is None:
        return DEFAULTS.get(key)
    merged = dict(DEFAULTS.get(key) or {})
    merged.update(row.value)
    return merged


async def put(session: AsyncSession, key: str, value: dict[str, Any]) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
    await session.flush()


async def maintenance(session: AsyncSession) -> tuple[bool, str]:
    data = await get(session, "maintenance") or {}
    return bool(data.get("enabled")), str(data.get("message") or "")


async def links(session: AsyncSession) -> dict[str, str]:
    """Ссылки с подстановкой значений из .env, если в админке не заданы."""
    from app.core.config import settings

    data = await get(session, "links") or {}
    return {
        "bot_username": (data.get("bot_username") or settings.bot_username or "").lstrip("@"),
        "support_url": data.get("support_url") or settings.support_url or "",
        "share_text": data.get("share_text") or settings.share_text
                      or "Все топовые нейросети в одном боте",
    }
