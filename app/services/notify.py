from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger("notify")
API = "https://api.telegram.org/bot{token}/{method}"


async def send_message(chat_id: int, text: str, *, parse_mode: str = "HTML",
                       reply_markup: dict | None = None) -> bool:
    if not settings.bot_token:
        return False
    body: dict = {
        "chat_id": chat_id,
        "text": text[:4096],
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        body["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(API.format(token=settings.bot_token, method="sendMessage"), json=body)
        if r.status_code >= 400:
            log.warning("sendMessage %s: %s", r.status_code, r.text[:200])
            return False
        return True
    except httpx.HTTPError as e:
        log.warning("sendMessage failed: %s", e)
        return False


async def notify_payment(user_id: int, days: int) -> None:
    await send_message(
        user_id,
        f"<b>Оплата прошла</b>\nPro активирован на {days} дней. "
        f"Начислено 1 000 энергии — все модели открыты.",
        reply_markup={
            "inline_keyboard": [[{"text": "Открыть приложение",
                                  "web_app": {"url": settings.webapp_url}}]]
        },
    )
