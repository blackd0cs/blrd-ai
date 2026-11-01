from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import energy as energy_svc
from app.core.catalog import catalog
from app.core.config import settings
from app.core.models import Payment, User, utcnow

log = logging.getLogger("platega")

# Статусы транзакции Platega
CONFIRMED = "CONFIRMED"
CANCELED = "CANCELED"
PENDING = "PENDING"
TERMINAL_FAIL = {"CANCELED", "CHARGEBACKED", "EXPIRED", "FAILED"}


class PlategaError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    return {
        "X-MerchantId": settings.platega_merchant_id,
        "X-Secret": settings.platega_secret,
        "Content-Type": "application/json",
    }


def configured() -> bool:
    return bool(settings.platega_merchant_id and settings.platega_secret)


async def create_payment(
    session: AsyncSession, user: User, *, source: str = "web"
) -> Payment:
    """Создаёт транзакцию в Platega и возвращает запись с pay_url."""
    pro = catalog.pro()
    amount = float(pro.price_rub or 150)

    payment = Payment(
        user_id=user.id, amount=amount, currency="RUB",
        status=PENDING, plan="pro", days=pro.days or 30, source=source,
    )
    session.add(payment)
    await session.flush()

    if not configured():
        raise PlategaError("Платежи не настроены: заполните PLATEGA_MERCHANT_ID и PLATEGA_SECRET")

    ref = f"{user.id}-{payment.id}-{uuid.uuid4().hex[:8]}"
    body: dict[str, Any] = {
        "paymentMethod": settings.platega_payment_method,
        "amount": amount,
        "currency": "RUB",
        "description": f"Подписка {pro.title} на {pro.days or 30} дней",
        "return": f"{settings.webapp_url.rstrip('/')}/pay/ok?p={payment.id}",
        "failedUrl": f"{settings.webapp_url.rstrip('/')}/pay/fail?p={payment.id}",
        "payload": ref,
        # metadata обязательна для /transaction/process
        "metadata": {"user_id": str(user.id), "payment_id": str(payment.id), "ref": ref},
    }

    url = settings.platega_base_url.rstrip("/") + "/transaction/process"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, json=body, headers=_headers())
    if r.status_code >= 400:
        log.error("platega create failed %s %s", r.status_code, r.text[:400])
        raise PlategaError(f"Platega вернула {r.status_code}")

    data = r.json()
    payment.tx_id = str(data.get("transactionId") or data.get("id") or "") or None
    payment.pay_url = data.get("redirect") or data.get("url") or data.get("paymentUrl")
    payment.raw = data
    await session.flush()

    if not payment.pay_url:
        raise PlategaError("Platega не вернула ссылку на оплату")
    return payment


async def fetch_status(tx_id: str) -> dict[str, Any]:
    url = settings.platega_base_url.rstrip("/") + f"/transaction/{tx_id}"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers=_headers())
    if r.status_code >= 400:
        raise PlategaError(f"status {r.status_code}: {r.text[:200]}")
    return r.json()


async def apply_callback(
    session: AsyncSession, data: dict[str, Any]
) -> tuple[Payment | None, bool]:
    """
    Обрабатывает колбэк. Колбэку не доверяем: статус перепроверяется в API.
    Возвращает (платёж, выдана ли подписка сейчас).
    """
    tx_id = str(data.get("id") or data.get("transactionId") or "")
    payload = str(data.get("payload") or "")
    status = str(data.get("status") or "").upper()

    payment = None
    if tx_id:
        payment = (
            await session.execute(select(Payment).where(Payment.tx_id == tx_id))
        ).scalar_one_or_none()
    if payment is None and payload:
        parts = payload.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            payment = await session.get(Payment, int(parts[1]))
    if payment is None:
        log.warning("callback for unknown tx %s payload=%s", tx_id, payload)
        return None, False

    if payment.applied:
        return payment, False  # идемпотентность: повторный колбэк не выдаёт Pro дважды

    if status == CONFIRMED and payment.tx_id:
        try:
            remote = await fetch_status(payment.tx_id)
            status = str(remote.get("status") or status).upper()
            payment.raw = {"callback": data, "verified": remote}
        except PlategaError as e:
            log.error("verification failed for %s: %s", payment.tx_id, e)
            return payment, False  # Platega повторит колбэк

    payment.status = status
    if status != CONFIRMED:
        await session.flush()
        return payment, False

    user = await session.get(User, payment.user_id)
    if user is None:
        return payment, False

    energy_svc.grant_pro(user, payment.days)
    user.paid_total = (user.paid_total or 0) + int(payment.amount)
    payment.applied = True
    payment.paid_at = utcnow()
    await session.flush()
    log.info("pro granted uid=%s payment=%s", user.id, payment.id)
    return payment, True


def callback_authorized(headers: dict[str, str]) -> bool:
    """
    Platega может подписывать колбэк теми же заголовками мерчанта.
    Если проверка включена, но заголовков нет, пропускаем: статус всё равно
    перепроверяется запросом к API, а жёсткий отказ потеряет уведомление.
    """
    if not settings.platega_callback_secret_check:
        return True
    got = headers.get("x-secret") or headers.get("X-Secret")
    if not got:
        return True
    return got == settings.platega_secret
