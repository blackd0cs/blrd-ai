from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Telegram ───────────────────────────────────────────
    bot_token: str = ""
    bot_username: str = ""
    webapp_url: str = "http://localhost:8080"
    # Читается строкой: иначе pydantic-settings пытается разобрать значение
    # как JSON и одиночный id превращается в int, а не в список.
    admin_ids_raw: str = Field(
        default="",
        validation_alias=AliasChoices("ADMIN_IDS", "admin_ids", "admin_ids_raw"),
    )

    # ── AnyModel ───────────────────────────────────────────
    anymodel_api_key: str = ""
    anymodel_base_url: str = "https://anymodel.org/v1"

    # ── Platega ────────────────────────────────────────────
    platega_merchant_id: str = ""
    platega_secret: str = ""
    platega_base_url: str = "https://app.platega.io"
    platega_payment_method: int = 2
    platega_callback_secret_check: bool = True

    # ── Приложение ─────────────────────────────────────────
    secret_key: str = "dev-secret-change-me"
    database_url: str = "sqlite+aiosqlite:///./data/blrd.db"
    data_dir: Path = ROOT / "data"
    public_host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"
    # Локальная отладка: вход в веб без Telegram под этим id.
    # В продакшене оставить 0 — иначе любой получит доступ к аккаунту.
    dev_auth_id: int = 0

    # ── Админка ────────────────────────────────────────────
    admin_password: str = "admin"

    # ── Экономика ──────────────────────────────────────────
    tokens_per_energy: int = 3000
    web_search_base_cost: int = 40_000
    max_upload_mb: int = 20

    # ── производные значения ───────────────────────────────
    @property
    def admin_ids(self) -> list[int]:
        """ADMIN_IDS=111,222 или 111;222 или одиночный id — всё равно список."""
        raw = str(self.admin_ids_raw or "").strip().strip("[]")
        out: list[int] = []
        for part in raw.replace(";", ",").replace(" ", ",").split(","):
            part = part.strip().strip("'\"")
            if not part:
                continue
            try:
                out.append(int(part))
            except ValueError:
                continue
        return out

    @property
    def uploads_dir(self) -> Path:
        p = self.data_dir / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def config_dir(self) -> Path:
        return ROOT / "config"

    @property
    def web_dir(self) -> Path:
        return ROOT / "web"

    @property
    def callback_url(self) -> str:
        return f"{self.webapp_url.rstrip('/')}/api/payments/platega/callback"

    @property
    def sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
