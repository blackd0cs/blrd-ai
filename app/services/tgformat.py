from __future__ import annotations

import html
import re

TG_LIMIT = 4096
SAFE_CHUNK = 3800  # запас под закрывающие теги при нарезке


def md_to_html(text: str) -> str:
    """
    Markdown → подмножество HTML, которое понимает Telegram:
    b, i, u, s, code, pre, a, blockquote. Всё прочее экранируется.
    """
    if not text:
        return ""

    stash: list[str] = []

    def keep(html_fragment: str) -> str:
        stash.append(html_fragment)
        return f"\x00{len(stash) - 1}\x00"

    # 1. блоки кода
    def code_block(m: re.Match[str]) -> str:
        lang = (m.group(1) or "").strip()
        body = html.escape(m.group(2).rstrip("\n"))
        cls = f' class="language-{html.escape(lang)}"' if lang else ""
        return keep(f"<pre><code{cls}>{body}</code></pre>")

    out = re.sub(r"```([^\n`]*)\n([\s\S]*?)(?:```|\Z)", code_block, text)

    # 2. инлайн-код
    out = re.sub(r"`([^`\n]+)`", lambda m: keep(f"<code>{html.escape(m.group(1))}</code>"), out)

    # 3. остальное экранируем, затем размечаем
    out = html.escape(out)
    lines = out.split("\n")
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"(\*\*\*|---|___)", stripped):
            result.append("—" * 12)
            continue
        if re.fullmatch(r"\x00\d+\x00", stripped):
            result.append(stripped)
            continue

        head = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if head:
            result.append(f"<b>{_inline(head.group(2))}</b>")
            continue

        quote = re.match(r"^&gt;\s?(.*)$", stripped)
        if quote:
            result.append(f"<blockquote>{_inline(quote.group(1))}</blockquote>")
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bullet:
            result.append(f"• {_inline(bullet.group(1))}")
            continue

        num = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if num:
            result.append(f"{num.group(1)}. {_inline(num.group(2))}")
            continue

        # таблицы Telegram не умеет: разделитель убираем, строки оставляем текстом
        if stripped.startswith("|"):
            if re.fullmatch(r"\|[\s:|-]+\|", stripped):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            result.append(_inline(" · ".join(c for c in cells if c)))
            continue

        result.append(_inline(line))

    body = "\n".join(result)
    body = re.sub(r"\n{3,}", "\n\n", body)
    for i, frag in enumerate(stash):
        body = body.replace(f"\x00{i}\x00", frag)
    return body.strip()


def _inline(t: str) -> str:
    t = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"__(.+?)__", r"<b>\1</b>", t)
    t = re.sub(r"(^|[\s(])\*([^\s*][^*]*?)\*(?=$|[\s.,!?)])", r"\1<i>\2</i>", t)
    t = re.sub(r"(^|[\s(])_([^\s_][^_]*?)_(?=$|[\s.,!?)])", r"\1<i>\2</i>", t)
    t = re.sub(r"~~(.+?)~~", r"<s>\1</s>", t)
    return t


def close_open_tags(fragment: str) -> str:
    """
    Закрывает теги, оставшиеся открытыми после обрезки стрима,
    иначе Telegram отвечает «can't parse entities».
    """
    stack: list[str] = []
    for m in re.finditer(r"<(/?)(b|i|u|s|code|pre|a|blockquote)(?:\s[^>]*)?>", fragment):
        tag = m.group(2)
        if m.group(1):
            if tag in stack:
                while stack and stack.pop() != tag:
                    pass
        else:
            stack.append(tag)
    return fragment + "".join(f"</{t}>" for t in reversed(stack))


def split_html(text: str, limit: int = SAFE_CHUNK) -> list[str]:
    """Режет готовый HTML по абзацам/строкам, не разрывая теги."""
    if len(text) <= limit:
        return [text] if text else []

    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = max(window.rfind("</pre>"), window.rfind("\n\n"), window.rfind("\n"))
        if cut < limit // 3:
            cut = limit
        elif window[cut:cut + 6] == "</pre>":
            cut += 6
        piece = rest[:cut]
        chunks.append(close_open_tags(piece).strip())
        rest = rest[cut:].lstrip("\n")
    if rest.strip():
        chunks.append(rest.strip())
    return chunks


def preview_for_stream(partial: str) -> str:
    """
    Частичный Markdown → HTML для редактирования сообщения на ходу:
    незакрытый блок кода дописывается, хвост обрезается с конца.
    """
    text = partial
    if text.count("```") % 2:
        text += "\n```"
    rendered = md_to_html(text)
    if len(rendered) > TG_LIMIT - 120:
        rendered = close_open_tags(rendered[: TG_LIMIT - 400]) + "\n…"
    return rendered
