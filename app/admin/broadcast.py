from __future__ import annotations

import asyncio
import datetime as dt
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import session_scope
from app.core.models import Broadcast, User, utcnow

log = logging.getLogger("broadcast")

SEND_DELAY = 0.06   # ~16 сообщений в секунду, лимит Telegram — 30
POLL_DELAY = 5.0
CAPTION_LIMIT = 1024


def photos_dir() -> Path:
    p = settings.data_dir / "broadcasts"
    p.mkdir(parents=True, exist_ok=True)
    return p


async def audience_ids(session: AsyncSession, audience: str) -> list[int]:
    now = utcnow()
    q = select(User.id).where(User.is_banned == False)  # noqa: E712
    if audience == "pro":
        q = q.where(User.plan == "pro", (User.plan_until == None) | (User.plan_until > now))  # noqa: E711
    elif audience == "free":
        q = q.where((User.plan != "pro") | ((User.plan_until != None) & (User.plan_until <= now)))  # noqa: E711
    elif audience == "active":
        q = q.where(User.last_seen >= now - dt.timedelta(days=7))
    rows = await session.execute(q)
    return [int(x) for x in rows.scalars()]


async def enqueue(
    session: AsyncSession, *, text: str, audience: str, photo_path: str | None
) -> Broadcast:
    ids = await audience_ids(session, audience)
    item = Broadcast(
        text=text, photo_path=photo_path, audience=audience,
        status="queued", total=len(ids),
    )
    session.add(item)
    await session.flush()
    return item


async def worker(bot) -> None:
    """Фоновая задача в процессе бота: берёт очередь и рассылает."""
    from aiogram.exceptions import (
        TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest,
    )
    from aiogram.types import FSInputFile

    log.info("рассылки: воркер запущен")
    while True:
        try:
            async with session_scope() as s:
                row = await s.execute(
                    select(Broadcast).where(Broadcast.status == "queued")
                    .order_by(Broadcast.id).limit(1)
                )
                item = row.scalar_one_or_none()
                if item is None:
                    bid = None
                else:
                    item.status = "running"
                    bid = item.id
                    text, photo, audience = item.text, item.photo_path, item.audience
                    ids = await audience_ids(s, audience)
                    item.total = len(ids)

            if bid is None:
                await asyncio.sleep(POLL_DELAY)
                continue

            log.info("рассылка %s: %d получателей", bid, len(ids))
            sent = failed = 0
            photo_file = None
            if photo:
                path = settings.data_dir / photo
                photo_file = FSInputFile(path) if path.exists() else None

            for i, uid in enumerate(ids, start=1):
                try:
                    if photo_file is not None:
                        await bot.send_photo(
                            uid, photo_file, caption=text[:CAPTION_LIMIT] or None
                        )
                    else:
                        await bot.send_message(uid, text[:4096], disable_web_page_preview=True)
                    sent += 1
                except TelegramRetryAfter as e:
                    log.warning("flood wait %ss", e.retry_after)
                    await asyncio.sleep(e.retry_after + 1)
                    continue
                except TelegramForbiddenError:
                    failed += 1  # бот заблокирован пользователем
                except TelegramBadRequest as e:
                    failed += 1
                    log.debug("send to %s failed: %s", uid, e)
                except Exception as e:
                    failed += 1
                    log.warning("send to %s crashed: %s", uid, e)

                await asyncio.sleep(SEND_DELAY)

                if i % 50 == 0:
                    async with session_scope() as s:
                        b = await s.get(Broadcast, bid)
                        if b:
                            b.sent, b.failed = sent, failed

            async with session_scope() as s:
                b = await s.get(Broadcast, bid)
                if b:
                    b.sent, b.failed = sent, failed
                    b.status = "done"
                    b.finished_at = utcnow()
            log.info("рассылка %s готова: %d отправлено, %d ошибок", bid, sent, failed)

        except asyncio.CancelledError:
            log.info("рассылки: воркер остановлен")
            return
        except Exception:
            log.exception("воркер рассылок упал, перезапуск через 15 с")
            await asyncio.sleep(15)
