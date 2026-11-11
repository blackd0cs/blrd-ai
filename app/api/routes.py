from __future__ import annotations

import asyncio
import logging
from typing import Any

import orjson
from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request,
    Response, UploadFile, status,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import energy as energy_svc
from app.core import settings_store
from app.core.catalog import catalog
from app.core.config import settings
from app.core.db import get_session
from app.core.models import Attachment, Chat, Message, Payment, User, utcnow
from app.core.security import current_user, issue_session, upsert_user, verify_init_data
from app.services import files as files_svc
from app.services import pipeline, platega, promo as promo_svc
from app.services.limits import busy_users, limiter
from app.api.schemas import AuthIn, ChatIn, PromoIn, SendIn, user_public

log = logging.getLogger("api")
router = APIRouter(prefix="/api")


def _plan_of(user: User):
    return catalog.plan("pro" if user.is_pro else "free")


def _me(user: User) -> dict[str, Any]:
    return user_public(
        user,
        energy_display=energy_svc.energy_display(user.energy_tokens),
        plan=_plan_of(user),
    )


# ── авторизация ────────────────────────────────────────────
@router.post("/auth/telegram")
async def auth_telegram(
    payload: AuthIn,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        data = verify_init_data(payload.init_data)
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Telegram не подтвердил вход: {e}") from e

    user = await upsert_user(session, data["user"], source="web")
    if user.is_banned:
        raise HTTPException(status.HTTP_403_FORBIDDEN, user.ban_reason or "Доступ заблокирован")

    token = issue_session(user.id)
    response.set_cookie(
        "bs", token, max_age=30 * 24 * 3600, httponly=True, samesite="none", secure=True
    )
    off, text = await settings_store.maintenance(session)
    return {
        "session": token,
        "user": _me(user),
        "maintenance": {"enabled": off, "message": text},
    }

@router.post("/auth/dev")
async def auth_dev(
    response: Response, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Только для локальной отладки: включается DEV_AUTH_ID в .env."""
    if not settings.dev_auth_id:
        raise HTTPException(404, "not found")
    if settings.webapp_url.startswith("https://"):
        log.warning("DEV_AUTH_ID активен на публичном домене — выключите его")

    user = await upsert_user(
        session,
        {"id": settings.dev_auth_id, "first_name": "Local", "last_name": "Dev",
         "username": "localdev", "language_code": "ru"},
        source="web",
    )
    token = issue_session(user.id)
    response.set_cookie("bs", token, max_age=30 * 24 * 3600, httponly=True, samesite="lax")
    return {"session": token, "user": _me(user), "maintenance": {"enabled": False, "message": ""}}

@router.get("/me")
async def me(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    off, text = await settings_store.maintenance(session)
    return {"user": _me(user), "maintenance": {"enabled": off, "message": text}}

@router.get("/config")
async def public_config(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    data = await settings_store.links(session)
    data["app_name"] = "БЕЛЕБАЛАРДЫХ AI"
    return data

# ── модели и тарифы ────────────────────────────────────────
@router.get("/models")
async def models(user: User = Depends(current_user)) -> dict[str, Any]:
    plan = _plan_of(user)
    pro = catalog.pro()
    return {
        "models": [m.to_public(plan.code) for m in catalog.models()],
        "current": user.current_model or catalog.default_model(plan.code).path,
        "plan": plan.code,
        "energy": energy_svc.energy_display(user.energy_tokens),
        "energy_max": plan.energy,
        "pro": {
            "price_rub": pro.price_rub,
            "days": pro.days,
            "energy": pro.energy,
            "features": list(pro.features),
        },
    }


@router.post("/models/select")
async def select_model(
    body: ChatIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    m = catalog.get(body.model)
    if m is None:
        raise HTTPException(404, "Модель не найдена")
    if not m.allowed_for(_plan_of(user).code):
        raise HTTPException(403, "Модель доступна в Pro")
    user.current_model = m.path
    await session.flush()
    return {"ok": True, "model": m.path}


# ── чаты ───────────────────────────────────────────────────
@router.get("/chats")
async def list_chats(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    rows = await session.execute(
        select(Chat)
        .where(Chat.user_id == user.id, Chat.is_deleted == False)  # noqa: E712
        .order_by(Chat.updated_at.desc())
        .limit(200)
    )
    chats = list(rows.scalars())
    return {
        "chats": [
            {
                "id": c.id,
                "title": c.title,
                "model": c.model,
                "updated_at": c.updated_at.isoformat(),
            }
            for c in chats
        ]
    }


@router.post("/chats")
async def create_chat(
    body: ChatIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    model = catalog.get(body.model) or catalog.get(user.current_model) or catalog.default_model(
        _plan_of(user).code
    )
    chat = Chat(user_id=user.id, title=body.title or "Новый чат", model=model.path, source="web")
    session.add(chat)
    await session.flush()
    return {"id": chat.id, "title": chat.title, "model": chat.model}


@router.get("/chats/{chat_id}")
async def get_chat(
    chat_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    chat = await session.get(Chat, chat_id)
    if chat is None or chat.user_id != user.id or chat.is_deleted:
        raise HTTPException(404, "Чат не найден")
    rows = await session.execute(
        select(Message).where(Message.chat_id == chat.id).order_by(Message.id)
    )
    msgs = list(rows.scalars())
    return {
        "id": chat.id,
        "title": chat.title,
        "model": chat.model,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "reasoning": m.reasoning,
                "atts": m.attachments or [],
                "created_at": m.created_at.isoformat(),
                "citations": m.citations or [],
            }
            for m in msgs
        ],
    }


@router.patch("/chats/{chat_id}")
async def patch_chat(
    chat_id: int,
    body: ChatIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    chat = await session.get(Chat, chat_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(404, "Чат не найден")
    if body.title is not None:
        chat.title = body.title[:200] or chat.title
    if body.model:
        m = catalog.get(body.model)
        if m and m.allowed_for(_plan_of(user).code):
            chat.model = m.path
            user.current_model = m.path
    chat.updated_at = utcnow()
    await session.flush()
    return {"ok": True}


@router.delete("/chats/{chat_id}")
async def delete_chat(
    chat_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    chat = await session.get(Chat, chat_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(404, "Чат не найден")
    await session.execute(delete(Message).where(Message.chat_id == chat.id))
    await session.delete(chat)
    return {"ok": True}


# ── генерация (SSE) ────────────────────────────────────────
async def _guard_generation(
    request: Request, user: User, session: AsyncSession
) -> None:
    """Проверки, общие для первой генерации и перегенерации."""
    off, text = await settings_store.maintenance(session)
    if off and not user.is_admin:
        raise HTTPException(503, text or "Идут технические работы")

    rl = await settings_store.get(session, "rate_limit") or {}
    if not limiter.check(user.id, int(rl.get("per_minute", 20))):
        raise HTTPException(429, "Слишком часто. Подождите немного.", headers={
            "Retry-After": str(limiter.retry_after(user.id))
        })
    if user.id in busy_users:
        raise HTTPException(409, "Предыдущий ответ ещё генерируется")


def _sse(request: Request, uid: int, **kwargs: Any) -> StreamingResponse:
    async def events():
        busy_users.add(uid)
        try:
            gen = pipeline.run(user_id=uid, **kwargs)
            async for ev in gen:
                if await request.is_disconnected():
                    await gen.aclose()
                    break
                yield b"data: " + orjson.dumps(ev) + b"\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("stream crashed uid=%s", uid)
            yield b"data: " + orjson.dumps(
                {"type": "error", "message": f"Внутренняя ошибка: {e}", "code": "internal"}
            ) + b"\n\n"
        finally:
            busy_users.discard(uid)
            yield b"data: [DONE]\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/chats/{chat_id}/send")
async def send(
    chat_id: int,
    body: SendIn,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    await _guard_generation(request, user, session)
    if not body.text.strip() and not body.attachments:
        raise HTTPException(400, "Пустой запрос")

    atts = [a.model_dump() for a in body.attachments]
    if atts:
        ids = [a["id"] for a in atts]
        rows = await session.execute(
            select(Attachment).where(Attachment.id.in_(ids), Attachment.user_id == user.id)
        )
        owned = {a.id: a for a in rows.scalars()}
        if len(owned) != len(ids):
            raise HTTPException(400, "Вложение не найдено")
        atts = [
            {"id": a.id, "kind": a.kind, "name": a.file_name, "mime": a.mime}
            for a in owned.values()
        ]

    uid, model_path, text = user.id, body.model, body.text
    await session.commit()  # стрим живёт долго, соединение освобождаем

    return _sse(
        request, uid,
        chat_id=chat_id, text=text, attachments=atts,
        source="web", model_path=model_path,
    )


@router.post("/chats/{chat_id}/regenerate")
async def regenerate(
    chat_id: int,
    body: ChatIn,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Удаляет последний ответ модели и генерирует его заново по тому же вопросу."""
    await _guard_generation(request, user, session)

    chat = await session.get(Chat, chat_id)
    if chat is None or chat.user_id != user.id or chat.is_deleted:
        raise HTTPException(404, "Чат не найден")

    uid, model_path = user.id, body.model
    await session.commit()

    return _sse(
        request, uid,
        chat_id=chat_id, source="web", model_path=model_path, regenerate=True,
    )


# ── вложения ───────────────────────────────────────────────
@router.post("/files")
async def upload(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    plan = _plan_of(user)
    if plan.max_attachments <= 0:
        raise HTTPException(403, "Вложения доступны в Pro")
    data = await file.read()
    try:
        att = await files_svc.save_upload(
            session,
            user_id=user.id,
            data=data,
            file_name=file.filename or "file",
            mime=file.content_type or "application/octet-stream",
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {
        "id": att.id,
        "kind": att.kind,
        "name": att.file_name,
        "mime": att.mime,
        "size": att.size,
        "url": f"/api/files/{att.id}",
    }


@router.get("/files/{file_id}")
async def get_file(
    file_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    att = await session.get(Attachment, file_id)
    if att is None or (att.user_id != user.id and not user.is_admin):
        raise HTTPException(404, "Файл не найден")
    path = files_svc.abs_path(att)
    if not path.exists():
        raise HTTPException(404, "Файл удалён")
    return FileResponse(path, media_type=att.mime, filename=att.file_name)


# ── оплата и промокоды ─────────────────────────────────────
@router.post("/payments/create")
async def create_payment(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    try:
        payment = await platega.create_payment(session, user, source="web")
    except platega.PlategaError as e:
        log.error("payment create failed uid=%s: %s", user.id, e)
        raise HTTPException(502, str(e)) from e
    return {"payment_id": payment.id, "url": payment.pay_url, "amount": payment.amount}


@router.get("/payments/{payment_id}")
async def payment_status(
    payment_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payment = await session.get(Payment, payment_id)
    if payment is None or payment.user_id != user.id:
        raise HTTPException(404, "Платёж не найден")

    # подстраховка на случай потерянного колбэка
    if payment.status == platega.PENDING and payment.tx_id:
        try:
            remote = await platega.fetch_status(payment.tx_id)
            await platega.apply_callback(
                session, {"id": payment.tx_id, "status": remote.get("status"), "payload": ""}
            )
            await session.refresh(payment)
            await session.refresh(user)
        except platega.PlategaError as e:
            log.info("poll failed %s: %s", payment.tx_id, e)

    return {"status": payment.status, "applied": payment.applied, "user": _me(user)}


@router.post("/payments/platega/callback")
async def platega_callback(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    if not platega.callback_authorized({k.lower(): v for k, v in request.headers.items()}):
        raise HTTPException(403, "bad secret")
    try:
        data = await request.json()
    except Exception as e:
        raise HTTPException(400, "bad json") from e

    payment, granted = await platega.apply_callback(session, data)
    if granted and payment:
        from app.services.notify import notify_payment  # ленивый импорт: бот не нужен вебу

        asyncio.create_task(notify_payment(payment.user_id, payment.days))
    return {"ok": True}


@router.post("/promo/redeem")
async def redeem_promo(
    body: PromoIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        message = await promo_svc.redeem(session, user, body.code)
    except promo_svc.PromoError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "message": message, "user": _me(user)}


# ── статистика пользователя ────────────────────────────────
@router.get("/usage")
async def usage(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    total = await session.scalar(
        select(func.count()).select_from(Message).join(Chat).where(Chat.user_id == user.id)
    )
    plan = _plan_of(user)
    return {
        "requests": user.requests,
        "messages": int(total or 0),
        "spent_energy": energy_svc.energy_display(user.spent_tokens or 0),
        "energy": energy_svc.energy_display(user.energy_tokens),
        "energy_max": plan.energy,
        "plan": plan.code,
        "plan_until": user.plan_until.isoformat() if user.plan_until else None,
    }
