from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, ORJSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.core.catalog import catalog
from app.core.config import settings
from app.core.db import init_db
from app.services.anymodel import anymodel

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    catalog.reload()
    log.info(
        "started: %d моделей, тарифы %s, 1 энергия = %d токенов",
        len(catalog.models()), list(catalog.plans()), catalog.energy_unit,
    )
    if not settings.anymodel_api_key:
        log.warning("ANYMODEL_API_KEY пуст — генерация ответов не заработает")
    yield
    await anymodel.close()


app = FastAPI(
    title="blrd ai",
    default_response_class=ORJSONResponse,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.webapp_url, "http://localhost:8080", "http://127.0.0.1:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

try:  # админка появится в части 5; без неё приложение всё равно работает
    from app.admin.routes import router as admin_router

    app.include_router(admin_router)
except ImportError:
    log.warning("админ-панель не подключена")


@app.get("/health")
async def health() -> dict[str, object]:
    return {"ok": True, "models": len(catalog.models())}


@app.get("/pay/ok", response_class=HTMLResponse)
async def pay_ok() -> str:
    return _pay_page("Оплата прошла", "Pro активирован. Можно закрывать страницу.", ok=True)


@app.get("/pay/fail", response_class=HTMLResponse)
async def pay_fail() -> str:
    return _pay_page("Оплата не прошла", "Деньги не списаны. Попробуйте ещё раз.", ok=False)


def _pay_page(title: str, text: str, *, ok: bool) -> str:
    color = "#3ddc84" if ok else "#ff5b5b"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>body{{background:#000;color:#f2f2f2;font-family:-apple-system,Inter,sans-serif;
display:grid;place-items:center;height:100vh;margin:0;text-align:center;padding:24px}}
h1{{font-size:26px;margin:0 0 10px;color:{color}}}p{{color:#8e8e93;margin:0 0 24px}}
button{{background:#f2f2f2;color:#000;border:0;border-radius:16px;padding:15px 28px;
font-size:16px;font-weight:600}}</style></head>
<body><div><h1>{title}</h1><p>{text}</p>
<button onclick="window.Telegram?.WebApp?.close()||window.close()">Вернуться</button></div>
<script>window.Telegram?.WebApp?.ready();</script></body></html>"""


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500)


# Mini App отдаётся последним: маршрут "/" не должен перехватывать /api
if settings.web_dir.exists():
    app.mount("/", StaticFiles(directory=str(settings.web_dir), html=True), name="web")
else:
    log.warning("папки %s нет — веб-приложение не отдаётся", settings.web_dir)

    @app.get("/", response_class=HTMLResponse)
    async def placeholder() -> str:
        return "<h1>blrd ai</h1><p>Создайте папку web/ с файлами Mini App.</p>"
