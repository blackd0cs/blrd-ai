from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer,
    JSON, String, Text, TypeDecorator, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class UTCDateTime(TypeDecorator):
    """
    Р”Р°С‚Р° РІСЃРµРіРґР° РїСЂРёС…РѕРґРёС‚ РёР· Р‘Р” СЃ tzinfo=UTC.
    SQLite РЅРµ С…СЂР°РЅРёС‚ РїРѕСЏСЃ, Рё Р±РµР· СЌС‚РѕРіРѕ СЃСЂР°РІРЅРµРЅРёРµ СЃ utcnow() РїР°РґР°РµС‚
    РЅР° offset-naive vs offset-aware.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)

    def process_result_value(self, value: dt.datetime | None, dialect) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram id
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    photo_url: Mapped[str | None] = mapped_column(String(512))
    language: Mapped[str | None] = mapped_column(String(8), default="ru")

    plan: Mapped[str] = mapped_column(String(16), default="free")
    plan_until: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    energy_tokens: Mapped[int] = mapped_column(BigInteger, default=0)   # Р±Р°Р·РѕРІС‹Рµ С‚РѕРєРµРЅС‹
    refill_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())

    current_model: Mapped[str | None] = mapped_column(String(128))

    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    ban_reason: Mapped[str | None] = mapped_column(String(512))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    requests: Mapped[int] = mapped_column(Integer, default=0)
    spent_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    paid_total: Mapped[int] = mapped_column(Integer, default=0)  # СЂСѓР±Р»Рё

    source: Mapped[str | None] = mapped_column(String(32))  # bot / web / ref
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)

    chats: Mapped[list["Chat"]] = relationship(back_populates="user")

    @property
    def display_name(self) -> str:
        name = " ".join(x for x in (self.first_name, self.last_name) if x).strip()
        return name or (f"@{self.username}" if self.username else f"id{self.id}")

    @property
    def is_pro(self) -> bool:
        if self.plan != "pro":
            return False
        if self.plan_until is None:
            return True
        return self.plan_until > utcnow()


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="РќРѕРІС‹Р№ С‡Р°С‚")
    model: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(8), default="web")  # web | bot
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)

    user: Mapped[User] = relationship(back_populates="chats")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan",
        order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128))
    attachments: Mapped[list[Any] | None] = mapped_column(JSON)
    citations: Mapped[list[Any] | None] = mapped_column(JSON)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    base_cost: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)

    chat: Mapped[Chat] = relationship(back_populates="messages")


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # uuid4 hex
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # image | doc
    file_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    rel_path: Mapped[str] = mapped_column(String(300))
    text_excerpt: Mapped[str | None] = mapped_column(Text)  # РґР»СЏ РґРѕРєСѓРјРµРЅС‚РѕРІ
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tx_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # id РІ Platega
    amount: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    plan: Mapped[str] = mapped_column(String(16), default="pro")
    days: Mapped[int] = mapped_column(Integer, default=30)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)  # Р·Р°С‰РёС‚Р° РѕС‚ РґРІРѕР№РЅРѕР№ РІС‹РґР°С‡Рё
    source: Mapped[str] = mapped_column(String(8), default="web")
    pay_url: Mapped[str | None] = mapped_column(String(600))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    paid_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())


class Promo(Base):
    __tablename__ = "promos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="pro")  # pro | energy
    days: Mapped[int] = mapped_column(Integer, default=30)        # РґР»СЏ kind=pro
    energy: Mapped[int] = mapped_column(Integer, default=0)       # РґР»СЏ kind=energy
    max_uses: Mapped[int] = mapped_column(Integer, default=1)     # 0 = Р±РµР· Р»РёРјРёС‚Р°
    used: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    comment: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PromoUse(Base):
    __tablename__ = "promo_uses"
    __table_args__ = (UniqueConstraint("promo_id", "user_id", name="uq_promo_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promo_id: Mapped[int] = mapped_column(Integer, ForeignKey("promos.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)


class UsageLog(Base):
    __tablename__ = "usage_log"
    __table_args__ = (Index("ix_usage_user_time", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    model: Mapped[str] = mapped_column(String(128))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    base_cost: Mapped[int] = mapped_column(Integer, default=0)
    searches: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(8), default="web")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(Text, default="")
    photo_path: Mapped[str | None] = mapped_column(String(300))
    audience: Mapped[str] = mapped_column(String(16), default="all")  # all | free | pro | active
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|done|failed
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())


class Setting(Base):
    """Runtime-РЅР°СЃС‚СЂРѕР№РєРё: С‚РµС…СЂР°Р±РѕС‚С‹, Р»РёРјРёС‚С‹, С‚РµРєСЃС‚С‹."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)

