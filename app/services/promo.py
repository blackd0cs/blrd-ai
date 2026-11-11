from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import energy as energy_svc
from app.core.models import Promo, PromoUse, User, utcnow


class PromoError(Exception):
    pass


async def redeem(session: AsyncSession, user: User, code: str) -> str:
    code = (code or "").strip().upper()
    if not code:
        raise PromoError("Введите промокод")

    promo = (
        await session.execute(select(Promo).where(Promo.code == code))
    ).scalar_one_or_none()
    if promo is None or not promo.is_active:
        raise PromoError("Промокод не найден")
    if promo.expires_at and promo.expires_at <= utcnow():
        raise PromoError("Промокод истёк")
    if promo.max_uses and promo.used >= promo.max_uses:
        raise PromoError("Промокод уже использован")

    already = (
        await session.execute(
            select(PromoUse).where(PromoUse.promo_id == promo.id, PromoUse.user_id == user.id)
        )
    ).scalar_one_or_none()
    if already:
        raise PromoError("Вы уже активировали этот промокод")

    if promo.kind == "energy":
        energy_svc.add_energy(user, promo.energy)
        message = f"Начислено {promo.energy} энергии"
    else:
        energy_svc.grant_pro(user, promo.days)
        message = f"Pro активирован на {promo.days} дней"

    promo.used += 1
    session.add(PromoUse(promo_id=promo.id, user_id=user.id))
    await session.flush()
    return message
