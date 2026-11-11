from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx
import orjson

from app.core.config import settings

log = logging.getLogger("anymodel")

# Фазы, которые уходят в интерфейс как «пишет / рассуждает / ищет…»
PHASE_CONNECT = "connecting"
PHASE_THINKING = "thinking"
PHASE_REASONING = "reasoning"
PHASE_SEARCHING = "searching"
PHASE_VISION = "vision"
PHASE_TYPING = "typing"
PHASE_DONE = "done"


class AnyModelError(RuntimeError):
    def __init__(self, message: str, *, status: int = 0, code: str = "", request_id: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code
        self.request_id = request_id

    @property
    def user_text(self) -> str:
        if self.status == 402:
            return "У провайдера закончился баланс. Напишите в поддержку."
        if self.status == 429:
            return "Слишком много запросов к модели. Попробуйте через минуту."
        if self.status in (404, 406):
            return "Эта модель сейчас недоступна. Выберите другую."
        if self.status == 400 and self.code == "output_budget_exhausted":
            return "Ответ не поместился в лимит. Начните новый чат или сократите вопрос."
        if self.status >= 500 or self.status == 0:
            return "Провайдер не ответил. Попробуйте ещё раз."
        return f"Ошибка модели: {self}"


@dataclass(slots=True)
class StreamEvent:
    """Одно событие стрима: либо смена фазы, либо текст, либо финал."""

    type: str  # phase | delta | reasoning | citations | usage
    phase: str = ""
    text: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    searches: int = 0
    estimated: bool = False


class AnyModelClient:
    """
    Тонкая обёртка над OpenAI-совместимым /v1/chat/completions AnyModel.
    Один httpx-клиент на процесс: keep-alive важен для стрима.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            async with self._lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        base_url=settings.anymodel_base_url.rstrip("/"),
                        headers={
                            "Authorization": f"Bearer {settings.anymodel_api_key}",
                            "Content-Type": "application/json",
                        },
                        timeout=httpx.Timeout(connect=20.0, read=600.0, write=60.0, pool=20.0),
                        limits=httpx.Limits(max_connections=100, max_keepalive_connections=40),
                    )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── вспомогательное ─────────────────────────────────────
    async def balance(self) -> dict[str, Any]:
        c = await self.client()
        r = await c.get("/balance")
        _raise_for_error(r)
        return r.json()

    async def catalog(self) -> list[dict[str, Any]]:
        c = await self.client()
        r = await c.get("/models")
        _raise_for_error(r)
        return r.json().get("data", [])

    # ── основной стрим ──────────────────────────────────────
    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        web_search: bool = False,
        has_images: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens:
            body["max_tokens"] = max_tokens
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        if web_search:
            body["tools"] = [{"type": "web_search"}]

        c = await self.client()
        phase = PHASE_VISION if has_images else PHASE_CONNECT
        yield StreamEvent("phase", phase=phase)

        text_started = False
        reasoning_started = False
        searching = False
        usage: dict[str, Any] = {}
        seen_citations: set[str] = set()

        try:
            async with c.stream("POST", "/chat/completions", json=body) as resp:
                if resp.status_code >= 400:
                    raw = await resp.aread()
                    _raise_payload(resp.status_code, raw, resp.headers.get("x-request-id", ""))

                yield StreamEvent("phase", phase=PHASE_THINKING)

                async for line in resp.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = orjson.loads(data)
                    except orjson.JSONDecodeError:
                        continue

                    if chunk.get("usage"):
                        usage = chunk["usage"]

                    err = chunk.get("error")
                    if err:
                        raise AnyModelError(
                            str(err.get("message") or "stream error"),
                            status=int(err.get("status") or 503),
                            code=str(err.get("code") or ""),
                        )

                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}

                        # размышления: разные провайдеры называют поле по-разному
                        think = (
                            delta.get("reasoning_content")
                            or delta.get("reasoning")
                            or ((delta.get("thinking") or {}).get("content")
                                if isinstance(delta.get("thinking"), dict) else delta.get("thinking"))
                        )
                        if isinstance(think, str) and think:
                            if not reasoning_started:
                                reasoning_started = True
                                yield StreamEvent("phase", phase=PHASE_REASONING)
                            yield StreamEvent("reasoning", text=think)

                        # признак работающего веб-поиска
                        calls = delta.get("tool_calls") or []
                        if calls and not searching:
                            names = " ".join(
                                str((tc.get("function") or {}).get("name") or tc.get("type") or "")
                                for tc in calls
                            )
                            if "search" in names.lower():
                                searching = True
                                yield StreamEvent("phase", phase=PHASE_SEARCHING)

                        for ann in delta.get("annotations") or []:
                            cit = ann.get("url_citation") or {}
                            url = cit.get("url")
                            if url and url not in seen_citations:
                                seen_citations.add(url)
                                yield StreamEvent(
                                    "citations",
                                    citations=[{"url": url, "title": cit.get("title") or url}],
                                )

                        content = delta.get("content")
                        if isinstance(content, list):  # Anthropic-подобная форма блоков
                            content = "".join(
                                b.get("text", "") for b in content if isinstance(b, dict)
                            )
                        if content:
                            if not text_started:
                                text_started = True
                                yield StreamEvent("phase", phase=PHASE_TYPING)
                            yield StreamEvent("delta", text=content)

        except AnyModelError:
            raise
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            raise AnyModelError("Модель не ответила вовремя", status=503, code="gateway_timeout") from e
        except httpx.HTTPError as e:
            raise AnyModelError(f"Сеть недоступна: {e}", status=0) from e

        yield StreamEvent("usage", usage=usage)

    async def complete(
        self, *, model: str, messages: list[dict[str, Any]], max_tokens: int = 256
    ) -> tuple[str, Usage]:
        """Нестримовый вызов — для заголовков чатов и служебных задач."""
        c = await self.client()
        r = await c.post(
            "/chat/completions",
            json={"model": model, "messages": messages, "max_tokens": max_tokens},
        )
        _raise_for_error(r)
        data = r.json()
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        u = data.get("usage") or {}
        return text.strip(), Usage(
            prompt_tokens=int(u.get("prompt_tokens") or 0),
            completion_tokens=int(u.get("completion_tokens") or 0),
        )


def _raise_for_error(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    _raise_payload(r.status_code, r.content, r.headers.get("x-request-id", ""))


def _raise_payload(status: int, raw: bytes, request_id: str) -> None:
    message, code = f"HTTP {status}", ""
    try:
        err = (orjson.loads(raw) or {}).get("error") or {}
        message = str(err.get("message") or message)
        code = str(err.get("code") or "")
        request_id = str(err.get("request_id") or request_id)
    except Exception:  # ответ CDN, не JSON
        snippet = raw[:200].decode("utf-8", "replace")
        if snippet:
            message = snippet
    log.warning("anymodel error %s %s %s", status, code, request_id)
    raise AnyModelError(message, status=status, code=code, request_id=request_id)


anymodel = AnyModelClient()
