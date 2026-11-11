from __future__ import annotations

from sqlalchemy import func, select

from app.core.catalog import catalog
from app.core.db import session_scope
from app.core.models import Chat, Message, User, utcnow


async def active_chat_id(user_id: int, *, model: str | None = None) -> int:
    """Последний чат бота; если его нет — создаётся новый."""
    async with session_scope() as s:
        row = await s.execute(
            select(Chat)
            .where(Chat.user_id == user_id, Chat.source == "bot", Chat.is_deleted == False)  # noqa: E712
            .order_by(Chat.updated_at.desc())
            .limit(1)
        )
        chat = row.scalar_one_or_none()
        if chat is not None:
            return chat.id
        user = await s.get(User, user_id)
        path = model or (user.current_model if user else None) or catalog.default_model(
            "pro" if user and user.is_pro else "free"
        ).path
        chat = Chat(user_id=user_id, title="Новый чат", model=path, source="bot")
        s.add(chat)
        await s.flush()
        return chat.id


async def new_chat(user_id: int) -> int:
    async with session_scope() as s:
        user = await s.get(User, user_id)
        path = (user.current_model if user else None) or catalog.default_model("free").path
        chat = Chat(user_id=user_id, title="Новый чат", model=path, source="bot")
        s.add(chat)
        await s.flush()
        return chat.id


async def chat_len(chat_id: int) -> int:
    async with session_scope() as s:
        return int(await s.scalar(
            select(func.count()).select_from(Message).where(Message.chat_id == chat_id)
        ) or 0)


async def set_model(user_id: int, path: str) -> None:
    async with session_scope() as s:
        user = await s.get(User, user_id)
        if user is None:
            return
        user.current_model = path
        row = await s.execute(
            select(Chat)
            .where(Chat.user_id == user_id, Chat.source == "bot", Chat.is_deleted == False)  # noqa: E712
            .order_by(Chat.updated_at.desc()).limit(1)
        )
        chat = row.scalar_one_or_none()
        if chat is not None:
            chat.model = path
            chat.updated_at = utcnow()


async def fresh_user(user_id: int) -> User | None:
    async with session_scope() as s:
        return await s.get(User, user_id)
