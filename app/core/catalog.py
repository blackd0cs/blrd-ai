from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.core.config import settings


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

    @property
    def free(self) -> bool:
        return self.multiplier == 0

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

    def _stale(self) -> bool:
        for p in (self.models_file, self.plans_file):
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

            models: list[ModelSpec] = []
            for item in raw_models.get("models", []):
                models.append(
                    ModelSpec(
                        path=str(item["path"]),
                        name=str(item.get("name") or item["path"]),
                        short=str(item.get("short") or item.get("name") or item["path"]),
                        multiplier=float(_num(item.get("multiplier"), 1)),
                        plans=tuple(str(x) for x in (item.get("plans") or ["pro"])),
                        vision=bool(item.get("vision", False)),
                        reasoning=bool(item.get("reasoning", False)),
                        web_search=bool(item.get("web_search", False)),
                        context=int(_num(item.get("context"), 128_000)),
                        default=bool(item.get("default", False)),
                    )
                )

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

            self._models = models
            self._plans = plans
            self._system_prompt = str(raw_models.get("system_prompt", "")).strip()
            self._energy_unit = int(_num(raw_plans.get("energy_unit"), settings.tokens_per_energy))
            for p in (self.models_file, self.plans_file):
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

    # ── правка из админки ───────────────────────────────────
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
