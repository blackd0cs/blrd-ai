from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from sqlalchemy import delete, select

from app.core import energy as energy_svc
from app.core import settings_store
from app.core.catalog import catalog
from app.core.db import session_scope
from app.core.models import Chat, Message, User, utcnow
from app.services import prompt as prompt_svc
from app.services.anymodel import AnyModelError, StreamEvent, anymodel

log = logging.getLogger("pipeline")

PHASE_LABELS = {
    "connecting": "думает",
    "thinking": "думает",
    "reasoning": "рассуждает",
    "searching": "поиск в интернете",
    "vision": "просматривает фото",
    "typing": "пишет",
    "done": "готово",
}


class GenerationDenied(Exception):
    def __init__(self, message: str, *, code: str = "denied"):
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class Result:
    text: str = ""
    reasoning: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    searches: int = 0
    cost: int = 0
    energy_left: int = 0
    aborted: bool = False


async def run(
    *,
    user_id: int,
    chat_id: int,
    text: str = "",
    attachments: list[dict[str, Any]] | None = None,
    source: str = "web",
    model_path: str | None = None,
    regenerate: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """
    Генератор событий SSE. При regenerate=True новое сообщение пользователя
    не добавляется: удаляются ответы после последнего вопроса и он идёт в модель снова.
    """
    attachments = attachments or []

    # ── подготовка ──────────────────────────────────────────
    async with session_scope() as s:
        user = await s.get(User, user_id)
        if user is None:
            yield _err("Пользователь не найден", "no_user")
            return
        if user.is_banned:
            yield _err(user.ban_reason or "Доступ заблокирован", "banned")
            return
        energy_svc.ensure_plan_state(user)

        chat = await s.get(Chat, chat_id)
        if chat is None or chat.user_id != user_id or chat.is_deleted:
            yield _err("Чат не найден", "no_chat")
            return

        plan = catalog.plan(user.plan if user.is_pro else "free")
        model = catalog.get(model_path or chat.model or user.current_model) \
            or catalog.default_model(plan.code)
        if not model.allowed_for(plan.code):
            yield _err(f"Модель «{model.name}» доступна в Pro", "need_pro")
            return
        if not energy_svc.can_afford(user, model):
            yield _err("Закончилась энергия", "no_energy")
            return

        if not regenerate:
            if attachments and plan.max_attachments <= 0:
                yield _err("Вложения доступны в Pro", "need_pro")
                return
            if len(attachments) > max(plan.max_attachments, 0):
                yield _err(f"Не больше {plan.max_attachments} вложений за раз", "too_many")
                return

        chat.model = model.path
        user.current_model = model.path
        chat.updated_at = utcnow()

        rows = await s.execute(
            select(Message).where(Message.chat_id == chat.id).order_by(Message.id)
        )
        history = list(rows.scalars())

        if regenerate:
            last_user = next((m for m in reversed(history) if m.role == "user"), None)
            if last_user is None:
                yield _err("Нечего перегенерировать", "no_question")
                return
            tail = [m.id for m in history if m.id > last_user.id]
            if tail:
                await s.execute(delete(Message).where(Message.id.in_(tail)))
                history = [m for m in history if m.id <= last_user.id]
        else:
            question = Message(
                chat_id=chat.id, role="user", content=text or "",
                attachments=attachments or None, model=model.path,
            )
            s.add(question)
            await s.flush()
            history.append(question)

        new_title = None
        if not regenerate and chat.title in ("Новый чат", "", None):
            new_title = prompt_svc.title_from_text(
                text or (attachments[0]["name"] if attachments else "")
            )
            chat.title = new_title

        # общий промпт из models.yml — только если включён в админке;
        # у фирменной модели свой промпт и он работает всегда
        sp = await settings_store.get(s, "system_prompt") or {}
        payload, has_images = await prompt_svc.build_payload(
            s, history=history, model=model, context_messages=plan.context_messages,
            use_global_prompt=bool(sp.get("enabled")),
        )
        plan_code, model_path_final = plan.code, model.path
        api_model = model.api_path   # фирменная модель вызывает свою базовую
        web_search = model.web_search and plan.web_search
        effort = "medium" if model.reasoning else None

    yield {"type": "meta", "model": model_path_final, "title": new_title}

    # ── стрим ───────────────────────────────────────────────
    res = Result()
    chunks: list[str] = []
    think: list[str] = []
    failed: AnyModelError | None = None

    try:
        stream = anymodel.stream_chat(
            model=api_model,
            messages=payload,
            web_search=web_search,
            reasoning_effort=effort,
            has_images=has_images,
        )
        async for ev in stream:
            out = _translate(ev)
            if ev.type == "delta":
                chunks.append(ev.text)
            elif ev.type == "reasoning":
                think.append(ev.text)
            elif ev.type == "citations":
                res.citations.extend(ev.citations)
            elif ev.type == "usage":
                res.tokens_in = int(ev.usage.get("prompt_tokens") or 0)
                res.tokens_out = int(ev.usage.get("completion_tokens") or 0)
                res.searches = int(ev.usage.get("web_search_requests") or 0)
            if out:
                yield out
    except AnyModelError as e:
        failed = e
        log.warning("generation failed uid=%s model=%s (%s): %s",
                    user_id, model_path_final, api_model, e)
    except (GeneratorExit, KeyboardInterrupt):
        raise
    except BaseException as e:
        res.aborted = True
        log.info("generation aborted uid=%s: %r", user_id, e)
        await _finalize(user_id, chat_id, model_path_final, chunks, think, res, source, plan_code)
        raise

    res.text = "".join(chunks)
    res.reasoning = "".join(think)

    if failed is not None and not res.text:
        async with session_scope() as s:
            user = await s.get(User, user_id)
            if user:
                res.energy_left = energy_svc.energy_display(user.energy_tokens)
        yield _err(failed.user_text, failed.code or "upstream")
        return

    msg_id, cost, left = await _finalize(
        user_id, chat_id, model_path_final, chunks, think, res, source, plan_code
    )
    yield {
        "type": "done",
        "message_id": msg_id,
        "cost": cost,
        "energy": left,
        "tokens_in": res.tokens_in,
        "tokens_out": res.tokens_out,
        "searches": res.searches,
        "citations": res.citations,
        "title": new_title,
        "truncated": bool(failed),
    }


async def _finalize(
    user_id: int,
    chat_id: int,
    model_path: str,
    chunks: list[str],
    think: list[str],
    res: Result,
    source: str,
    plan_code: str,
) -> tuple[int | None, int, int]:
    text = "".join(chunks)
    reasoning = "".join(think)
    model = catalog.get(model_path) or catalog.default_model(plan_code)

    if not res.tokens_out and text:
        res.tokens_out = max(1, len(text) // 3)
        res.tokens_in = res.tokens_in or max(1, sum(len(c) for c in chunks) // 12)

    async with session_scope() as s:
        user = await s.get(User, user_id)
        chat = await s.get(Chat, chat_id)
        if user is None or chat is None:
            return None, 0, 0

        if text or reasoning:
            cost = await energy_svc.charge(
                s, user, model, res.tokens_in, res.tokens_out,
                searches=res.searches, source=source, ok=not res.aborted,
            )
            msg = Message(
                chat_id=chat_id, role="assistant", content=text,
                reasoning=reasoning or None, model=model_path,
                citations=_clean_citations(res.citations),
                tokens_in=res.tokens_in, tokens_out=res.tokens_out, base_cost=cost,
            )
            s.add(msg)
            chat.updated_at = utcnow()
            await s.flush()
            return msg.id, cost, energy_svc.energy_display(user.energy_tokens)

        return None, 0, energy_svc.energy_display(user.energy_tokens)


def _translate(ev: StreamEvent) -> dict[str, Any] | None:
    if ev.type == "phase":
        return {"type": "phase", "phase": ev.phase, "label": PHASE_LABELS.get(ev.phase, "работает")}
    if ev.type == "delta":
        return {"type": "delta", "text": ev.text}
    if ev.type == "reasoning":
        return {"type": "reasoning", "text": ev.text}
    if ev.type == "citations":
        return {"type": "citations", "items": ev.citations}
    return None


def _clean_citations(items: list[dict[str, Any]]) -> list[dict[str, str]] | None:
    """В БД кладём только http(s)-ссылки, без повторов, не больше 20."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for c in items or []:
        url = str((c or {}).get("url") or "")
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append({"url": url[:1000], "title": str(c.get("title") or url)[:300]})
        if len(out) >= 20:
            break
    return out or None


def _err(message: str, code: str) -> dict[str, Any]:
    return {"type": "error", "message": message, "code": code}
