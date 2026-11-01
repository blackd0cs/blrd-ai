from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot import service
from app.bot.keyboards import pro_kb, stop_kb
from app.bot.streamer import Streamer
from app.core import energy as energy_svc
from app.core.catalog import catalog
from app.core.db import session_scope
from app.core.models import User
from app.services import files as files_svc, pipeline
from app.services.limits import busy_users, limiter

log = logging.getLogger("bot.chat")
router = Router(name="chat")

MAX_INPUT_CHARS = 20_000
ALBUM_DELAY = 0.8

_tasks: dict[int, asyncio.Task] = {}
_albums: dict[str, dict[str, Any]] = {}


# ── приём сообщений ────────────────────────────────────────
@router.message(Command("stop"))
async def stop_cmd(message: Message, user: User) -> None:
    task = _tasks.get(user.id)
    if task and not task.done():
        task.cancel()
        await message.answer("⏹ Остановил.")
    else:
        await message.answer("Сейчас ничего не генерируется.")


@router.callback_query(F.data == "stop")
async def stop_cb(call: CallbackQuery, user: User) -> None:
    task = _tasks.get(user.id)
    if task and not task.done():
        task.cancel()
        await call.answer("Остановлено")
    else:
        await call.answer("Уже готово")


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, user: User, bot: Bot) -> None:
    text = (message.text or "").strip()
    if len(text) > MAX_INPUT_CHARS:
        await message.answer(
            f"Сообщение длиннее {MAX_INPUT_CHARS} символов. "
            "Пришлите его файлом — я прочитаю документ."
        )
        return
    await generate(bot, message, user, text, [])


@router.message(F.photo | F.document | F.caption)
async def on_media(message: Message, user: User, bot: Bot) -> None:
    if message.media_group_id:
        await _buffer_album(bot, message, user)
        return
    att = await _save_attachment(bot, message, user)
    if att is None:
        return
    await generate(bot, message, user, (message.caption or "").strip(), [att])


async def _buffer_album(bot: Bot, message: Message, user: User) -> None:
    """Альбом приходит отдельными апдейтами: собираем по media_group_id."""
    key = f"{message.chat.id}:{message.media_group_id}"
    box = _albums.setdefault(key, {"messages": [], "task": None})
    box["messages"].append(message)
    if box["task"]:
        box["task"].cancel()

    async def flush() -> None:
        try:
            await asyncio.sleep(ALBUM_DELAY)
        except asyncio.CancelledError:
            return
        group = _albums.pop(key, {}).get("messages") or []
        if not group:
            return
        plan = catalog.plan("pro" if user.is_pro else "free")
        limit = max(plan.max_attachments, 1)
        atts: list[dict[str, Any]] = []
        for m in group[:limit]:
            att = await _save_attachment(bot, m, user, quiet=True)
            if att:
                atts.append(att)
        if not atts:
            await group[0].answer("Не удалось принять файлы. Вложения доступны в Pro.",
                                  reply_markup=pro_kb())
            return
        caption = next((m.caption for m in group if m.caption), "") or ""
        if len(group) > limit:
            await group[0].answer(f"Взял первые {limit} вложения из {len(group)}.")
        await generate(bot, group[-1], user, caption.strip(), atts)

    box["task"] = asyncio.create_task(flush())


async def _save_attachment(
    bot: Bot, message: Message, user: User, *, quiet: bool = False
) -> dict[str, Any] | None:
    plan = catalog.plan("pro" if user.is_pro else "free")
    if plan.max_attachments <= 0:
        if not quiet:
            await message.answer(
                "📎 Вложения доступны в <b>Pro</b>. Текстом отвечу на любом тарифе.",
                reply_markup=pro_kb(),
            )
        return None

    if message.photo:
        tg_file = message.photo[-1]
        name = f"photo_{message.message_id}.jpg"
        mime = "image/jpeg"
    elif message.document:
        tg_file = message.document
        name = message.document.file_name or f"file_{message.message_id}"
        mime = message.document.mime_type or "application/octet-stream"
    else:
        return None

    size = getattr(tg_file, "file_size", 0) or 0
    if size > 20 * 1024 * 1024:  # лимит Bot API на скачивание
        if not quiet:
            await message.answer("Файл больше 20 МБ — Telegram не даёт его скачать боту.")
        return None

    try:
        buf = await bot.download(tg_file)
        data = buf.read()
    except Exception as e:
        log.warning("download failed: %s", e)
        if not quiet:
            await message.answer("Не смог скачать файл из Telegram. Попробуйте ещё раз.")
        return None

    try:
        async with session_scope() as s:
            att = await files_svc.save_upload(
                s, user_id=user.id, data=data, file_name=name, mime=mime
            )
            payload = {"id": att.id, "kind": att.kind, "name": att.file_name, "mime": att.mime}
    except ValueError as e:
        if not quiet:
            await message.answer(f"⚠️ {e}")
        return None

    if payload["kind"] == "doc" and not att.text_excerpt:
        if not quiet:
            await message.answer(
                "Из этого файла не получилось извлечь текст. "
                "Понимаю PDF, DOCX, TXT, CSV, JSON и код."
            )
    return payload


# ── генерация ──────────────────────────────────────────────
async def generate(
    bot: Bot, message: Message, user: User, text: str, atts: list[dict[str, Any]]
) -> None:
    if not text and not atts:
        return

    if user.id in busy_users or (user.id in _tasks and not _tasks[user.id].done()):
        await message.answer("Дождитесь предыдущего ответа или нажмите /stop.")
        return
    if not limiter.check(user.id):
        await message.answer(f"Слишком часто. Подождите {limiter.retry_after(user.id)} с.")
        return

    plan = catalog.plan("pro" if user.is_pro else "free")
    model = catalog.get(user.current_model) or catalog.default_model(plan.code)

    if not energy_svc.can_afford(user, model):
        await message.answer(
            "⚡️ Закончилась энергия.\n"
            f"Бесплатные модели остаются доступными: "
            f"{', '.join(m.name for m in catalog.models_for(plan.code) if m.free) or '—'}.",
            reply_markup=pro_kb(),
        )
        return

    has_image = any(a["kind"] == "image" for a in atts)
    if has_image and not model.vision:
        vision = [m.name for m in catalog.models_for(plan.code) if m.vision]
        await message.answer(
            f"<b>{model.name}</b> не смотрит картинки — опишу по тексту.\n"
            + (f"Модели с 👁: {', '.join(vision)} (/model)" if vision else
               "Модели с поддержкой картинок есть в Pro.")
        )

    chat_id = await service.active_chat_id(user.id, model=model.path)
    placeholder = await message.answer("<i>⏳ подключаюсь…</i>", reply_markup=stop_kb())
    streamer = Streamer(bot, placeholder, stop_kb())

    task = asyncio.create_task(
        _run(bot, message, user, streamer, chat_id, text, atts, model.path)
    )
    _tasks[user.id] = task
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        _tasks.pop(user.id, None)


async def _run(
    bot: Bot,
    message: Message,
    user: User,
    streamer: Streamer,
    chat_id: int,
    text: str,
    atts: list[dict[str, Any]],
    model_path: str,
) -> None:
    gen = pipeline.run(
        user_id=user.id,
        chat_id=chat_id,
        text=text,
        attachments=atts,
        source="bot",
        model_path=model_path,
    )
    citations: list[dict[str, Any]] = []
    busy_users.add(user.id)
    typing = asyncio.create_task(_keep_typing(bot, message.chat.id))

    try:
        async for ev in gen:
            kind = ev.get("type")
            if kind == "phase":
                await streamer.set_phase(ev["phase"], ev["label"])
            elif kind == "delta":
                await streamer.add(ev["text"])
            elif kind == "citations":
                citations.extend(ev["items"])
            elif kind == "error":
                kb = pro_kb() if ev.get("code") in ("need_pro", "no_energy") else None
                await streamer.fail(ev["message"], kb)
                return
            elif kind == "done":
                await streamer.finish(
                    footer=_footer(ev, model_path, truncated=ev.get("truncated")),
                    citations=citations or ev.get("citations") or [],
                )
                return
    except asyncio.CancelledError:
        await gen.aclose()
        await streamer.finish(footer="<i>⏹ остановлено</i>", citations=citations)
        raise
    except Exception as e:
        log.exception("bot generation crashed uid=%s", user.id)
        await streamer.fail(f"Внутренняя ошибка: {e}")
    finally:
        typing.cancel()
        busy_users.discard(user.id)


async def _keep_typing(bot: Bot, chat_id: int) -> None:
    try:
        while True:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
            await asyncio.sleep(4.5)
    except (asyncio.CancelledError, Exception):
        return


def _footer(ev: dict[str, Any], model_path: str, truncated: bool = False) -> str:
    model = catalog.get(model_path)
    cost = energy_svc.to_energy(int(ev.get("cost") or 0))
    parts = [f"<i>{model.name if model else model_path}"]
    if cost:
        parts.append(f"−{cost:g} энергии")
    parts.append(f"осталось {ev.get('energy', 0)}")
    if ev.get("searches"):
        parts.append(f"поисков: {ev['searches']}")
    if truncated:
        parts.append("ответ прерван провайдером")
    return " · ".join(parts) + "</i>"
