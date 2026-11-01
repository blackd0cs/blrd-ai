from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.catalog import ModelSpec, catalog
from app.core.models import Attachment, Message
from app.services import files as files_svc

DOC_TEMPLATE = "\n\n--- Файл «{name}» ---\n{body}\n--- конец файла ---"


async def build_payload(
    session: AsyncSession,
    *,
    history: Sequence[Message],
    model: ModelSpec,
    context_messages: int,
    extra_system: str = "",
) -> tuple[list[dict[str, Any]], bool]:
    """
    Возвращает messages для AnyModel и признак «в запросе есть картинки».
    История обрезается по количеству сообщений тарифа; системный промпт всегда первый.
    """
    system = catalog.system_prompt
    if extra_system:
        system = f"{system}\n\n{extra_system}".strip()
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system.replace("{model_name}", model.name)})

    window = list(history)[-context_messages:] if context_messages > 0 else list(history)
    att_ids = {
        a["id"]
        for m in window
        for a in (m.attachments or [])
        if isinstance(a, dict) and a.get("id")
    }
    atts: dict[str, Attachment] = {}
    if att_ids:
        rows = await session.execute(select(Attachment).where(Attachment.id.in_(att_ids)))
        atts = {a.id: a for a in rows.scalars()}

    has_images = False
    for m in window:
        if m.role == "assistant":
            if m.content:
                out.append({"role": "assistant", "content": m.content})
            continue

        text = m.content or ""
        parts: list[dict[str, Any]] = []
        for raw in m.attachments or []:
            att = atts.get((raw or {}).get("id"))
            if att is None:
                continue
            if att.kind == "image":
                if model.vision:
                    try:
                        parts.append(
                            {"type": "image_url", "image_url": {"url": files_svc.image_data_url(att)}}
                        )
                        has_images = True
                    except Exception:
                        text += f"\n\n[не удалось прочитать изображение {att.file_name}]"
                else:
                    text += f"\n\n[приложено изображение {att.file_name}; эта модель не умеет смотреть картинки]"
            elif att.text_excerpt:
                text += DOC_TEMPLATE.format(name=att.file_name, body=att.text_excerpt)
            else:
                text += f"\n\n[приложен файл {att.file_name}, текст извлечь не удалось]"

        if parts:
            content: Any = ([{"type": "text", "text": text}] if text.strip() else []) + parts
        else:
            content = text
        if content:
            out.append({"role": "user", "content": content})

    return out, has_images


def title_from_text(text: str, fallback: str = "Новый чат") -> str:
    clean = " ".join((text or "").split())
    if not clean:
        return fallback
    return clean[:38] + ("…" if len(clean) > 38 else "")
