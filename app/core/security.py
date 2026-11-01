from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.energy import ensure_plan_state, plan_quota_base
from app.core.models import User, utcnow

INIT_DATA_TTL = 24 * 3600
SESSION_TTL = 30 * 24 * 3600

_session_signer = URLSafeTimedSerializer(settings.secret_key, salt="webapp-session")
_admin_signer = URLSafeTimedSerializer(settings.secret_key, salt="admin-session")


# ── Telegram initData ──────────────────────────────────────
def verify_init_data(init_data: str, *, ttl: int = INIT_DATA_TTL) -> dict[str, Any]:
    """
    Проверяет подпись Mini App по алгоритму Telegram:
    secret = HMAC_SHA256("WebAppData", bot_token); hash = HMAC_SHA256(secret, data_check_string).
    """
    if not init_data:
        raise ValueError("empty init_data")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise ValueError("no hash")

    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise ValueError("bad signature")

    auth_date = int(pairs.get("auth_date", "0") or 0)
    if ttl and auth_date and time.time() - auth_date > ttl:
        raise ValueError("init_data expired")

    user_raw = pairs.get("user")
    if not user_raw:
        raise ValueError("no user in init_data")
    pairs["user"] = json.loads(user_raw)
    return pairs


# ── сессии веб-приложения ──────────────────────────────────
def issue_session(user_id: int) -> str:
    return _session_signer.dumps({"uid": user_id})


def read_session(token: str) -> int | None:
    try:
        data = _session_signer.loads(token, max_age=SESSION_TTL)
        return int(data["uid"])
    except (BadSignature, KeyError, ValueError, TypeError):
        return None


# ── пользователи ───────────────────────────────────────────
async def upsert_user(
    session: AsyncSession,
    tg: dict[str, Any],
    *,
    source: str = "web",
) -> User:
    uid = int(tg["id"])
    user = await session.get(User, uid)
    created = user is None
    if created:
        user = User(
            id=uid,
            plan="free",
            energy_tokens=plan_quota_base("free"),
            source=source,
            is_admin=uid in settings.admin_ids,
        )
        session.add(user)

    user.username = tg.get("username") or user.username
    user.first_name = tg.get("first_name") or user.first_name
    user.last_name = tg.get("last_name") or user.last_name
    user.language = tg.get("language_code") or user.language
    if tg.get("photo_url"):
        user.photo_url = tg["photo_url"]
    if uid in settings.admin_ids:
        user.is_admin = True
    user.last_seen = utcnow()

    ensure_plan_state(user)
    await session.flush()
    return user


async def current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    """
    Авторизация запроса веб-приложения. Принимает:
      - заголовок Authorization: tma <initData>  (первый запрос / мобильный клиент)
      - заголовок X-Session или cookie bs        (далее)
    """
    uid: int | None = None

    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("tma "):
        try:
            data = verify_init_data(auth[4:].strip())
        except ValueError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"initData: {e}") from e
        user = await upsert_user(session, data["user"])
        _guard(user)
        return user

    token = request.headers.get("x-session") or request.cookies.get("bs")
    if token:
        uid = read_session(token)

    if uid is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")

    user = await session.get(User, uid)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user gone")
    if ensure_plan_state(user):
        await session.flush()
    _guard(user)
    return user


def _guard(user: User) -> None:
    if user.is_banned:
        raise HTTPException(status.HTTP_403_FORBIDDEN, user.ban_reason or "Доступ заблокирован")


# ── админка ────────────────────────────────────────────────
def issue_admin_session(login: str) -> str:
    return _admin_signer.dumps({"login": login})


def check_admin_cookie(token: str | None) -> bool:
    if not token:
        return False
    try:
        _admin_signer.loads(token, max_age=12 * 3600)
        return True
    except BadSignature:
        return False


async def require_admin(request: Request) -> bool:
    if not check_admin_cookie(request.cookies.get("badm")):
        raise HTTPException(status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/admin/login"})
    return True
