from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AuthIn(BaseModel):
    init_data: str = Field(default="", alias="initData")

    model_config = {"populate_by_name": True}


class AttachmentIn(BaseModel):
    id: str
    kind: str = "doc"
    name: str = ""
    mime: str = ""


class SendIn(BaseModel):
    text: str = ""
    model: str | None = None
    attachments: list[AttachmentIn] = Field(default_factory=list)


class ChatIn(BaseModel):
    title: str | None = None
    model: str | None = None


class PromoIn(BaseModel):
    code: str


def user_public(user, *, energy_display, plan) -> dict[str, Any]:
    return {
        "id": user.id,
        "name": user.display_name,
        "username": user.username,
        "photo_url": user.photo_url,
        "plan": "pro" if user.is_pro else "free",
        "plan_title": plan.title,
        "plan_until": user.plan_until.isoformat() if user.plan_until else None,
        "energy": energy_display,
        "energy_max": plan.energy,
        "max_attachments": plan.max_attachments,
        "is_admin": user.is_admin,
        "model": user.current_model,
    }
