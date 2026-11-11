from __future__ import annotations

import datetime as dt
import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.catalog import ModelSpec, catalog
from app.core.config import settings
from app.core.models import UsageLog, User, utcnow


def unit() -> int:
    return catalog.energy_unit or settings.tokens_per_energy


def to_energy(base_tokens: int) -> float:
    return round(base_tokens / unit(), 2)


def to_base(energy: float) -> int:
    return int(round(energy * unit()))


def energy_display(base_tokens: int) -> int:
    """Целое число энергии для интерфейса (вниз, чтобы не обещать лишнего)."""
    return max(0, int(base_tokens // unit()))


def price_base(model: ModelSpec, tokens_in: int, tokens_out: int, searches: int = 0) -> int:
    """Базовые токены за запрос: единый множитель на вход и выход."""
    if model.multiplier <= 0:
        return searches * settings.web_search_base_cost
    cost = math.ceil((tokens_in + tokens_out) * model.multiplier)
    cost += searches * settings.web_search_base_cost
    return max(1, cost)


def plan_quota_base(plan_code: str) -> int:
    return to_base(catalog.plan(plan_code).energy)


def can_afford(user: User, model: ModelSpec) -> bool:
    """Бесплатные модели не требуют баланса; платным нужна хотя бы 1 энергия."""
    if model.multiplier <= 0:
        return True
    return user.energy_tokens >= unit()


async def charge(
    session: AsyncSession,
    user: User,
    model: ModelSpec,
    tokens_in: int,
    tokens_out: int,
    *,
    searches: int = 0,
    source: str = "web",
    ok: bool = True,
) -> int:
    """Списывает базовые токены и пишет лог. Возвращает списанное."""
    cost = price_base(model, tokens_in, tokens_out, searches)
    user.energy_tokens = max(0, user.energy_tokens - cost)
    user.spent_tokens = (user.spent_tokens or 0) + cost
    user.requests = (user.requests or 0) + 1
    user.last_seen = utcnow()
    session.add(
        UsageLog(
            user_id=user.id, model=model.path, tokens_in=tokens_in,
            tokens_out=tokens_out, base_cost=cost, searches=searches,
            source=source, ok=ok,
        )
    )
    await session.flush()
    return cost


def ensure_plan_state(user: User) -> bool:
    """
    Приводит тариф и баланс в актуальное состояние:
    истёк Pro -> Free, подошёл срок автопополнения Free -> пополнить.
    Возвращает True, если что-то изменилось.
    """
    changed = False
    now = utcnow()

    if user.plan == "pro" and user.plan_until and user.plan_until <= now:
        user.plan = "free"
        user.plan_until = None
        user.energy_tokens = plan_quota_base("free")
        user.refill_at = now + dt.timedelta(days=catalog.plan("free").refill_days or 30)
        changed = True

    if user.plan == "free":
        if user.refill_at is None:
            days = catalog.plan("free").refill_days or 30
            user.refill_at = now + dt.timedelta(days=days)
            changed = True
        elif user.refill_at <= now:
            user.energy_tokens = max(user.energy_tokens, plan_quota_base("free"))
            days = catalog.plan("free").refill_days or 30
            user.refill_at = now + dt.timedelta(days=days)
            changed = True

    # модель из конфига могла стать недоступной тарифу
    m = catalog.get(user.current_model)
    if m is None or not m.allowed_for(user.plan):
        user.current_model = catalog.default_model(user.plan).path
        changed = True

    return changed


def grant_pro(user: User, days: int | None = None, *, add_energy: bool = True) -> None:
    """Продлевает Pro (накопительно) и выдаёт месячную квоту энергии."""
    pro = catalog.pro()
    days = days or pro.days or 30
    now = utcnow()
    base = user.plan_until if (user.plan == "pro" and user.plan_until and user.plan_until > now) else now
    user.plan = "pro"
    user.plan_until = base + dt.timedelta(days=days)
    user.refill_at = None
    if add_energy:
        user.energy_tokens = max(user.energy_tokens, 0) + plan_quota_base("pro")


def add_energy(user: User, energy: float) -> None:
    user.energy_tokens = max(0, user.energy_tokens + to_base(energy))
