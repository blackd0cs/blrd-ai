from __future__ import annotations

import base64
import io
import logging
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.models import Attachment

log = logging.getLogger("files")

IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif"}
TEXT_SUFFIX = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".yml", ".yaml", ".xml", ".html", ".htm",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".go", ".rs", ".c", ".h", ".cpp",
    ".cs", ".php", ".rb", ".sh", ".sql", ".ini", ".toml", ".cfg", ".log", ".env",
}
MAX_IMAGE_SIDE = 1536
MAX_DOC_CHARS = 60_000


def _new_id() -> str:
    return uuid.uuid4().hex


def is_image(mime: str, name: str) -> bool:
    if mime in IMAGE_MIME:
        return True
    return Path(name).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}


async def save_upload(
    session: AsyncSession,
    *,
    user_id: int,
    data: bytes,
    file_name: str,
    mime: str,
) -> Attachment:
    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        raise ValueError(f"Файл больше {settings.max_upload_mb} МБ")
    if not data:
        raise ValueError("Пустой файл")

    att_id = _new_id()
    kind = "image" if is_image(mime, file_name) else "doc"
    sub = settings.uploads_dir / str(user_id)
    sub.mkdir(parents=True, exist_ok=True)
    suffix = Path(file_name).suffix[:12] or (".jpg" if kind == "image" else ".bin")
    path = sub / f"{att_id}{suffix}"
    path.write_bytes(data)

    excerpt: str | None = None
    if kind == "image":
        _ = _load_image_bytes(path)  # ранняя проверка: битый файл не доживёт до модели
    else:
        excerpt = extract_text(path, mime)[:MAX_DOC_CHARS] or None

    att = Attachment(
        id=att_id,
        user_id=user_id,
        kind=kind,
        file_name=file_name[:255],
        mime=mime[:128],
        size=len(data),
        rel_path=str(path.relative_to(settings.data_dir)),
        text_excerpt=excerpt,
    )
    session.add(att)
    await session.flush()
    return att


def abs_path(att: Attachment) -> Path:
    return settings.data_dir / att.rel_path


def _load_image_bytes(path: Path) -> bytes:
    """Приводит картинку к JPEG не больше MAX_IMAGE_SIDE: экономит входные токены."""
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85, optimize=True)
        return buf.getvalue()


def image_data_url(att: Attachment) -> str:
    raw = _load_image_bytes(abs_path(att))
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


def extract_text(path: Path, mime: str = "") -> str:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf" or mime == "application/pdf":
            return _pdf_text(path)
        if suffix in (".docx",) or "wordprocessingml" in mime:
            return _docx_text(path)
        if suffix in TEXT_SUFFIX or mime.startswith("text/"):
            return path.read_bytes().decode("utf-8", "replace")
    except Exception as e:
        log.warning("extract %s failed: %s", path.name, e)
        return ""
    # неизвестный формат: пробуем как текст, иначе пусто
    head = path.read_bytes()[:4096]
    if b"\x00" in head:
        return ""
    return path.read_bytes().decode("utf-8", "replace")


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    for i, page in enumerate(reader.pages[:60]):
        parts.append(page.extract_text() or "")
        if sum(len(p) for p in parts) > MAX_DOC_CHARS:
            parts.append(f"\n…документ обрезан после {i + 1} страниц…")
            break
    return "\n\n".join(parts).strip()


def _docx_text(path: Path) -> str:
    import docx

    doc = docx.Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts).strip()
