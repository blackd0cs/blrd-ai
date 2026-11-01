from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Setting, utcnow

DEFAULTS: dict[str, Any] = {
    "maintenance": {"enabled": False, "message": "Идут технические работы, скоро вернёмся."},
    "signup_enabled": {"enabled": True},
    "welcome": {
        "text": "Привет! Я blrd ai — доступ к лучшим моделям прямо в Telegram.\n"
                "Открой приложение кнопкой ниже или просто напиши мне сообщение."
    },
    "rate_limit": {"per_minute": 20},
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
