from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, Message

from app.services.tgformat import md_to_html, preview_for_stream, split_html

log = logging.getLogger("bot.stream")

MIN_INTERVAL = 1.2
CURSOR = " ▍"

PHASE_ICONS = {
    "connecting": "⏳",
    "thinking": "💭",
    "reasoning": "🧩",
    "searching": "🌐",
    "vision": "🖼",
    "typing": "✍️",
}


class Streamer:
    """Один ответ модели = одно сообщение, которое превращается из статуса в текст."""

    def __init__(self, bot: Bot, message: Message, markup: InlineKeyboardMarkup | None = None):
        self.bot = bot
        self.msg = message
        self.markup = markup
        self.text = ""
        self.label = "думает"
        self.icon = "💭"
        self._last_edit = 0.0
        self._rendered = ""
        self._lock = asyncio.Lock()

    async def set_phase(self, phase: str, label: str) -> None:
        self.label = label
        self.icon = PHASE_ICONS.get(phase, "⏳")
        if not self.text:
            await self._render(force=True)

    async def add(self, chunk: str) -> None:
        self.text += chunk
        await self._render()

    def _body(self, final: bool = False) -> str:
        if not self.text:
            return f"<i>{self.icon} {self.label}…</i>"
        if final:
            return md_to_html(self.text)
        return preview_for_stream(self.text) + CURSOR

    async def _render(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_edit < MIN_INTERVAL:
            return
        async with self._lock:
            body = self._body()
            if body == self._rendered:
                return
            self._last_edit = time.monotonic()
            await self._edit(body, self.markup)
            self._rendered = body

    async def _edit(self, text: str, markup: InlineKeyboardMarkup | None) -> None:
        try:
            await self.msg.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except TelegramRetryAfter as e:
            self._last_edit = time.monotonic() + e.retry_after
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                return
            log.warning("edit failed: %s", e)
            try:  # сломалась разметка — отдаём текстом, лишь бы ответ дошёл
                await self.msg.edit_text(self.text[:4000], reply_markup=markup)
            except TelegramBadRequest:
                pass

    async def finish(self, footer: str = "", citations: list[dict] | None = None) -> None:
        """Финальный рендер: длинный ответ уезжает дополнительными сообщениями."""
        async with self._lock:
            body = md_to_html(self.text) if self.text else "<i>Пустой ответ модели.</i>"
            if citations:
                links = "\n".join(
                    f"{i + 1}. <a href=\"{c['url']}\">{_short(c.get('title') or c['url'])}</a>"
                    for i, c in enumerate(citations[:8])
                )
                body += f"\n\n<b>Источники</b>\n{links}"
            chunks = split_html(body) or [body]

            await self._edit(chunks[0] + (f"\n\n{footer}" if footer and len(chunks) == 1 else ""), None)
            for i, part in enumerate(chunks[1:], start=1):
                tail = f"\n\n{footer}" if footer and i == len(chunks) - 1 else ""
                try:
                    await self.bot.send_message(
                        self.msg.chat.id, part + tail, disable_web_page_preview=True
                    )
                except TelegramBadRequest as e:
                    log.warning("send tail failed: %s", e)
                await asyncio.sleep(0.3)

    async def fail(self, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        async with self._lock:
            if self.text:
                await self._edit(md_to_html(self.text) + f"\n\n<i>{text}</i>", markup)
            else:
                await self._edit(f"⚠️ {text}", markup)


def _short(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s[:n] + ("…" if len(s) > n else "")
