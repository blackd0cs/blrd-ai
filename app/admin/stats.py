from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import energy as energy_svc
from app.core.catalog import catalog
from app.core.models import Chat, Message, Payment, Promo, UsageLog, User, utcnow


async def dashboard(session: AsyncSession) -> dict[str, Any]:
    now = utcnow()
    day = now - dt.timedelta(days=1)
    week = now - dt.timedelta(days=7)

    users_total = await session.scalar(select(func.count()).select_from(User)) or 0
    users_day = await session.scalar(
        select(func.count()).select_from(User).where(User.created_at >= day)
    ) or 0
    users_week = await session.scalar(
        select(func.count()).select_from(User).where(User.created_at >= week)
    ) or 0
    active_week = await session.scalar(
        select(func.count()).select_from(User).where(User.last_seen >= week)
    ) or 0
    banned = await session.scalar(
        select(func.count()).select_from(User).where(User.is_banned == True)  # noqa: E712
    ) or 0
    pro_active = await session.scalar(
        select(func.count()).select_from(User).where(
            User.plan == "pro", (User.plan_until == None) | (User.plan_until > now)  # noqa: E711
        )
    ) or 0

    revenue_total = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.applied == True)  # noqa: E712
    ) or 0
    revenue_month = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.applied == True, Payment.paid_at >= now - dt.timedelta(days=30)  # noqa: E712
        )
    ) or 0
    payments_paid = await session.scalar(
        select(func.count()).select_from(Payment).where(Payment.applied == True)  # noqa: E712
    ) or 0
    payments_pending = await session.scalar(
        select(func.count()).select_from(Payment).where(Payment.status == "PENDING")
    ) or 0

    requests_total = await session.scalar(select(func.count()).select_from(UsageLog)) or 0
    requests_day = await session.scalar(
        select(func.count()).select_from(UsageLog).where(UsageLog.created_at >= day)
    ) or 0
    tokens_total = await session.scalar(
        select(func.coalesce(func.sum(UsageLog.base_cost), 0))
    ) or 0
    tokens_day = await session.scalar(
        select(func.coalesce(func.sum(UsageLog.base_cost), 0)).where(UsageLog.created_at >= day)
    ) or 0
    searches = await session.scalar(
        select(func.coalesce(func.sum(UsageLog.searches), 0))
    ) or 0

    chats = await session.scalar(select(func.count()).select_from(Chat)) or 0
    messages = await session.scalar(select(func.count()).select_from(Message)) or 0

    by_model = (
        await session.execute(
            select(
                UsageLog.model,
                func.count().label("n"),
                func.coalesce(func.sum(UsageLog.base_cost), 0).label("cost"),
            )
            .group_by(UsageLog.model)
            .order_by(func.count().desc())
            .limit(12)
        )
    ).all()

    by_source = (
        await session.execute(
            select(UsageLog.source, func.count()).group_by(UsageLog.source)
        )
    ).all()

    # дневной ряд считаем в Python: один SQL на оба движка
    rows = (
        await session.execute(
            select(UsageLog.created_at, UsageLog.base_cost).where(
                UsageLog.created_at >= now - dt.timedelta(days=14)
            )
        )
    ).all()
    buckets: dict[str, dict[str, int]] = {}
    for i in range(13, -1, -1):
        key = (now - dt.timedelta(days=i)).strftime("%d.%m")
        buckets[key] = {"requests": 0, "tokens": 0}
    for created, cost in rows:
        key = created.strftime("%d.%m")
        if key in buckets:
            buckets[key]["requests"] += 1
            buckets[key]["tokens"] += int(cost or 0)
    peak = max((b["requests"] for b in buckets.values()), default=0) or 1
    series = [
        {"day": k, "requests": v["requests"], "tokens": v["tokens"],
         "height": round(v["requests"] / peak * 100)}
        for k, v in buckets.items()
    ]

    promos_active = await session.scalar(
        select(func.count()).select_from(Promo).where(Promo.is_active == True)  # noqa: E712
    ) or 0

    unit = catalog.energy_unit
    return {
        "users": {
            "total": users_total, "day": users_day, "week": users_week,
            "active_week": active_week, "pro": pro_active, "banned": banned,
            "conversion": round(pro_active / users_total * 100, 1) if users_total else 0.0,
        },
        "money": {
            "total": int(revenue_total), "month": int(revenue_month),
            "paid": payments_paid, "pending": payments_pending,
            "arpu": round(revenue_total / users_total, 1) if users_total else 0.0,
        },
        "usage": {
            "requests": requests_total, "requests_day": requests_day,
            "tokens": int(tokens_total), "tokens_day": int(tokens_day),
            "energy": energy_svc.energy_display(int(tokens_total)),
            "energy_day": energy_svc.energy_display(int(tokens_day)),
            "searches": int(searches),
            "cost_usd": round(int(tokens_total) / 1_000_000 * 0.05, 2),
        },
        "content": {"chats": chats, "messages": messages},
        "by_model": [
            {"model": m or "—", "name": (catalog.get(m).name if catalog.get(m) else m or "—"),
             "requests": n, "energy": energy_svc.energy_display(int(c))}
            for m, n, c in by_model
        ],
        "by_source": {s or "—": n for s, n in by_source},
        "series": series,
        "promos_active": promos_active,
        "unit": unit,
    }


async def user_detail(session: AsyncSession, user_id: int) -> dict[str, Any] | None:
    user = await session.get(User, user_id)
    if user is None:
        return None

    chats = await session.scalar(
        select(func.count()).select_from(Chat).where(Chat.user_id == user_id)
    ) or 0
    messages = await session.scalar(
        select(func.count()).select_from(Message).join(Chat).where(Chat.user_id == user_id)
    ) or 0
    logs = (
        await session.execute(
            select(UsageLog).where(UsageLog.user_id == user_id)
            .order_by(UsageLog.id.desc()).limit(25)
        )
    ).scalars().all()
    payments = (
        await session.execute(
            select(Payment).where(Payment.user_id == user_id)
            .order_by(Payment.id.desc()).limit(10)
        )
    ).scalars().all()
    recent_chats = (
        await session.execute(
            select(Chat).where(Chat.user_id == user_id)
            .order_by(Chat.updated_at.desc()).limit(10)
        )
    ).scalars().all()

    plan = catalog.plan("pro" if user.is_pro else "free")
    return {
        "user": user,
        "plan": plan,
        "energy": energy_svc.energy_display(user.energy_tokens),
        "spent_energy": energy_svc.energy_display(user.spent_tokens or 0),
        "chats": chats,
        "messages": messages,
        "logs": logs,
        "payments": payments,
        "recent_chats": recent_chats,
    }
