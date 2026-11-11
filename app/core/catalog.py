from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.core.config import settings

log = logging.getLogger("catalog")

# производитель по ключевому слову в названии/пути; поле vendor в YAML важнее
_VENDOR_HINTS: tuple[tuple[str, str], ...] = (
    ("claude", "Anthropic"), ("gpt", "OpenAI"), ("gemini", "Google"), ("gemma", "Google"),
    ("grok", "xAI"), ("kimi", "Moonshot"), ("glm", "Zhipu"), ("deepseek", "DeepSeek"),
    ("qwen", "Qwen"), ("minimax", "MiniMax"), ("nemotron", "NVIDIA"), ("riva", "NVIDIA"),
    ("muse", "Muse"), ("jev", "Jev"), ("clef", "Jev"), ("laya", "Jev"), ("mercury", "Jev"),
)
OTHER_VENDOR = "Другие"
BRANDED_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{1,79}$")


def guess_vendor(name: str, path: str) -> str:
    hay = f"{name} {path}".lower()
    return next((v for key, v in _VENDOR_HINTS if key in hay), OTHER_VENDOR)


@dataclass(slots=True)
class ModelSpec:
    path: str
    name: str
    short: str
    multiplier: float
    plans: tuple[str, ...]
    vision: bool = False
    reasoning: bool = False
    web_search: bool = False
    context: int = 128_000
    default: bool = False
    vendor: str = OTHER_VENDOR
    popular: bool = False
    branded: bool = False
    upstream: str = ""        # для фирменных: какую модель AnyModel вызывать
    system_prompt: str = ""   # для фирменных: свой промпт, наружу не отдаётся
    description: str = ""

    @property
    def free(self) -> bool:
        return self.multiplier == 0

    @property
    def api_path(self) -> str:
        return self.upstream or self.path

    def allowed_for(self, plan: str) -> bool:
        return plan in self.plans

    def to_public(self, plan: str) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "short": self.short,
            "multiplier": self.multiplier,
            "vision": self.vision,
            "reasoning": self.reasoning,
            "web_search": self.web_search,
            "context": self.context,
            "locked": not self.allowed_for(plan),
            "pro": "free" not in self.plans,
            "vendor": self.vendor,
            "popular": self.popular,
            "branded": self.branded,
            "description": self.description,
        }


@dataclass(slots=True)
class PlanSpec:
    code: str
    title: str
    energy: int
    price_rub: int = 0
    days: int = 0
    refill_days: int = 0
    max_attachments: int = 0
    context_messages: int = 10
    web_search: bool = False
    features: tuple[str, ...] = field(default_factory=tuple)


class _Dumper(yaml.SafeDumper):
    pass


def _str_repr(dumper: yaml.SafeDumper, data: str):
    # многострочный промпт пишем блоком |, чтобы файл можно было читать глазами
    return dumper.represent_scalar(
        "tag:yaml.org,2002:str", data, style="|" if "\n" in data else None
    )


_Dumper.add_representer(str, _str_repr)


class _Catalog:
    """Ленивая загрузка конфигов с проверкой mtime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mtimes: dict[Path, float] = {}
        self._models: list[ModelSpec] = []
        self._plans: dict[str, PlanSpec] = {}
        self._system_prompt = ""
        self._energy_unit = settings.tokens_per_energy

    # ── файлы ───────────────────────────────────────────────
    @property
    def models_file(self) -> Path:
        return settings.config_dir / "models.yml"

    @property
    def plans_file(self) -> Path:
        return settings.config_dir / "plans.yml"

    @property
    def branded_file(self) -> Path:
        return settings.config_dir / "branded.yml"

    def _files(self) -> tuple[Path, ...]:
        return (self.models_file, self.plans_file, self.branded_file)

    def _stale(self) -> bool:
        for p in self._files():
            try:
                m = p.stat().st_mtime
            except FileNotFoundError:
                continue
            if self._mtimes.get(p) != m:
                return True
        return False

    def reload(self) -> None:
        with self._lock:
            raw_models = _read_yaml(self.models_file)
            raw_plans = _read_yaml(self.plans_file)
            raw_branded = _read_yaml(self.branded_file)

            models: list[ModelSpec] = []
            for item in raw_models.get("models", []):
                path = str(item["path"])
                name = str(item.get("name") or path)
                models.append(
                    ModelSpec(
                        path=path,
                        name=name,
                        short=str(item.get("short") or name),
                        multiplier=float(_num(item.get("multiplier"), 1)),
                        plans=tuple(str(x) for x in (item.get("plans") or ["pro"])),
                        vision=bool(item.get("vision", False)),
                        reasoning=bool(item.get("reasoning", False)),
                        web_search=bool(item.get("web_search", False)),
                        context=int(_num(item.get("context"), 128_000)),
                        default=bool(item.get("default", False)),
                        vendor=str(item.get("vendor") or guess_vendor(name, path)),
                        popular=bool(item.get("popular", False)),
                        description=str(item.get("description") or "").strip(),
                    )
                )

            base = {m.path: m for m in models}
            branded: list[ModelSpec] = []
            for item in raw_branded.get("models") or []:
                try:
                    spec = _build_branded(item, base)
                except (TypeError, ValueError) as e:
                    log.warning("фирменная модель пропущена: %s", e)
                    continue
                if spec and not any(b.path == spec.path for b in branded):
                    branded.append(spec)

            plans: dict[str, PlanSpec] = {}
            for code, item in (raw_plans.get("plans") or {}).items():
                plans[code] = PlanSpec(
                    code=code,
                    title=str(item.get("title", code.title())),
                    energy=int(_num(item.get("energy"), 0)),
                    price_rub=int(_num(item.get("price_rub"), 0)),
                    days=int(_num(item.get("days"), 0)),
                    refill_days=int(_num(item.get("refill_days"), 0)),
                    max_attachments=int(_num(item.get("max_attachments"), 0)),
                    context_messages=int(_num(item.get("context_messages"), 10)),
                    web_search=bool(item.get("web_search", False)),
                    features=tuple(item.get("features") or ()),
                )

            # фирменные в конце: индексы обычных моделей в клавиатуре бота не сдвигаются
            self._models = models + branded
            self._plans = plans
            self._system_prompt = str(raw_models.get("system_prompt", "")).strip()
            self._energy_unit = int(_num(raw_plans.get("energy_unit"), settings.tokens_per_energy))
            for p in self._files():
                if p.exists():
                    self._mtimes[p] = p.stat().st_mtime

    def _ensure(self) -> None:
        if not self._models or self._stale():
            self.reload()

    # ── доступ ──────────────────────────────────────────────
    @property
    def energy_unit(self) -> int:
        self._ensure()
        return self._energy_unit or settings.tokens_per_energy

    @property
    def system_prompt(self) -> str:
        self._ensure()
        return self._system_prompt

    def models(self) -> list[ModelSpec]:
        self._ensure()
        return list(self._models)

    def base_models(self) -> list[ModelSpec]:
        return [m for m in self.models() if not m.branded]

    def models_for(self, plan: str) -> list[ModelSpec]:
        return [m for m in self.models() if m.allowed_for(plan)]

    def get(self, path: str | None) -> ModelSpec | None:
        if not path:
            return None
        self._ensure()
        return next((m for m in self._models if m.path == path), None)

    def default_model(self, plan: str = "free") -> ModelSpec:
        allowed = self.models_for(plan) or self.models()
        return next((m for m in allowed if m.default), allowed[0])

    def plans(self) -> dict[str, PlanSpec]:
        self._ensure()
        return dict(self._plans)

    def plan(self, code: str) -> PlanSpec:
        self._ensure()
        return self._plans.get(code) or self._plans.get("free") or PlanSpec(
            code="free", title="Free", energy=50
        )

    def pro(self) -> PlanSpec:
        return self.plan("pro")

    # ── фирменные модели (пишет админка) ────────────────────
    def branded_raw(self) -> list[dict[str, Any]]:
        items = _read_yaml(self.branded_file).get("models") or []
        return [dict(i) for i in items if isinstance(i, dict)]

    def save_branded(self, item: dict[str, Any], *, original: str | None = None) -> None:
        path = str(item.get("path") or "").strip().lower()
        if not BRANDED_ID_RE.match(path):
            raise ValueError("ID: латиница в нижнем регистре, цифры и . _ / -, от 2 до 80 символов")
        base = {m.path for m in self.base_models()}
        if path in base:
            raise ValueError(f"ID {path} уже занят обычной моделью")
        upstream = str(item.get("upstream") or "").strip()
        if upstream not in base:
            raise ValueError("Выберите базовую модель из списка")
        name = str(item.get("name") or "").strip()
        if not 1 <= len(name) <= 60:
            raise ValueError("Название: от 1 до 60 символов")
        try:
            mult = float(str(item.get("multiplier", "")).replace(",", ".").strip())
        except ValueError:
            raise ValueError("Коэффициент должен быть числом") from None
        if mult < 0:
            raise ValueError("Коэффициент не может быть отрицательным")
        known = self.plans()
        plans = [str(p) for p in (item.get("plans") or []) if str(p) in known]
        if not plans:
            raise ValueError("Отметьте хотя бы один тариф")
        prompt = str(item.get("system_prompt") or "").replace("\r\n", "\n").strip()
        if len(prompt) > 20_000:
            raise ValueError("Системный промпт длиннее 20 000 символов")

        items = self.branded_raw()
        target = original or path
        if path != target and any(str(i.get("path")) == path for i in items):
            raise ValueError(f"Фирменная модель с ID {path} уже есть")

        entry = {
            "path": path,
            "name": name,
            "short": str(item.get("short") or "").strip()[:24] or name,
            "upstream": upstream,
            "multiplier": int(mult) if mult.is_integer() else mult,
            "plans": plans,
            "popular": bool(item.get("popular")),
            "description": str(item.get("description") or "").strip()[:160],
            "system_prompt": prompt,
        }
        out, placed = [], False
        for i in items:
            if str(i.get("path")) == target:
                out.append(entry)
                placed = True
            else:
                out.append(i)
        if not placed:
            out.append(entry)
        self._write_branded(out)

    def delete_branded(self, path: str) -> None:
        items = self.branded_raw()
        out = [i for i in items if str(i.get("path")) != path]
        if len(out) == len(items):
            raise ValueError("Фирменная модель не найдена")
        self._write_branded(out)

    def _write_branded(self, items: list[dict[str, Any]]) -> None:
        f = self.branded_file
        if f.exists():
            f.with_suffix(f.suffix + ".bak").write_text(f.read_text("utf-8"), "utf-8")
        text = (
            "# Фирменные модели. Файл пишет админка (Модели → Фирменные модели).\n"
            + yaml.dump({"models": items}, Dumper=_Dumper, allow_unicode=True,
                        sort_keys=False, width=1000)
        )
        f.write_text(text, "utf-8")
        self.reload()

    # ── правка YAML из админки ──────────────────────────────
    def raw_text(self, which: str) -> str:
        path = self.models_file if which == "models" else self.plans_file
        return path.read_text("utf-8") if path.exists() else ""

    def save_text(self, which: str, text: str) -> None:
        """Пишет YAML только если он парсится и проходит полную проверку."""
        data = yaml.safe_load(text) or {}
        if which == "models":
            items = data.get("models")
            if not isinstance(items, list) or not items:
                raise ValueError("в models.yml нужен непустой список 'models'")
            seen: set[str] = set()
            for i, m in enumerate(items, 1):
                if not isinstance(m, dict):
                    raise ValueError(f"модель #{i}: должна быть набором полей key: value")
                for key in ("path", "name", "multiplier", "plans"):
                    if key not in m:
                        raise ValueError(f"модель #{i}: нет обязательного поля '{key}'")
                path = str(m["path"]).strip()
                if not path:
                    raise ValueError(f"модель #{i}: пустой path")
                if path in seen:
                    raise ValueError(f"модель #{i}: путь '{path}' повторяется")
                seen.add(path)
                try:
                    mult = float(_num(m["multiplier"], 1))
                except (TypeError, ValueError):
                    raise ValueError(f"{path}: multiplier должен быть числом, а не '{m['multiplier']}'")
                if mult < 0:
                    raise ValueError(f"{path}: multiplier не может быть отрицательным")
                plans = m["plans"]
                if not isinstance(plans, list) or not plans:
                    raise ValueError(f"{path}: plans должен быть списком, например [free, pro]")
                known = set((yaml.safe_load(self.raw_text("plans")) or {}).get("plans") or {})
                bad = [str(x) for x in plans if str(x) not in known]
                if bad:
                    raise ValueError(f"{path}: неизвестные тарифы {bad}, есть {sorted(known)}")
            if not any(m.get("plans") and "free" in m["plans"] and float(m.get("multiplier", 1)) == 0
                       for m in items):
                raise ValueError("нужна хотя бы одна бесплатная модель с тарифом free")
        elif which == "plans":
            plans = data.get("plans")
            if not isinstance(plans, dict) or "free" not in plans:
                raise ValueError("в plans.yml нужен ключ 'plans' с тарифом 'free'")
        else:
            raise ValueError(f"неизвестный файл '{which}'")

        path_file = self.models_file if which == "models" else self.plans_file
        backup = path_file.with_suffix(path_file.suffix + ".bak")
        if path_file.exists():
            backup.write_text(path_file.read_text("utf-8"), "utf-8")
        path_file.write_text(text, "utf-8")
        try:
            self.reload()
        except Exception as e:
            # откат: иначе приложение не поднимется после перезапуска
            if backup.exists():
                path_file.write_text(backup.read_text("utf-8"), "utf-8")
                self.reload()
            raise ValueError(f"конфиг отклонён и возвращён прежний: {e}") from e


def _build_branded(item: Any, base: dict[str, ModelSpec]) -> ModelSpec | None:
    if not isinstance(item, dict):
        return None
    path = str(item.get("path") or "").strip()
    up = base.get(str(item.get("upstream") or "").strip())
    if not path or up is None or path in base:
        log.warning("фирменная модель %r пропущена: нет базовой %r или ID занят",
                    path, item.get("upstream"))
        return None
    name = str(item.get("name") or path)
    return ModelSpec(
        path=path,
        name=name,
        short=str(item.get("short") or name),
        multiplier=float(_num(item.get("multiplier"), up.multiplier)),
        plans=tuple(str(x) for x in (item.get("plans") or up.plans)),
        vision=up.vision,
        reasoning=up.reasoning,
        web_search=up.web_search,
        context=up.context,
        vendor=up.vendor,
        popular=bool(item.get("popular", False)),
        branded=True,
        upstream=up.api_path,
        system_prompt=str(item.get("system_prompt") or "").strip(),
        description=str(item.get("description") or "").strip(),
    )


def _num(value, default):
    """YAML null и пустая строка означают «не задано»."""
    if value is None or value == "":
        return default
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text("utf-8")) or {}


catalog = _Catalog()
