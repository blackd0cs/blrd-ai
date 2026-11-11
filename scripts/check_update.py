"""
Проверка обновления.
  python scripts/check_update.py
  python scripts/check_update.py --http http://127.0.0.1:8080   # ещё и запущенный сервер
Код выхода 1, если что-то не прошло.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)                       # относительный путь SQLite считается от корня
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

stats = {"ok": 0, "fail": 0, "warn": 0}


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 56 - len(title)))


def report(ok: bool, title: str, detail: str = "") -> None:
    stats["ok" if ok else "fail"] += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {title}" + (f"\n         → {detail}" if detail and not ok else ""))


def warn(title: str, detail: str = "") -> None:
    stats["warn"] += 1
    print(f"[WARN] {title}" + (f"\n         → {detail}" if detail else ""))


def read(rel: str) -> str | None:
    p = ROOT / rel
    return p.read_text("utf-8", errors="replace") if p.exists() else None


def has(rel: str, title: str, *needles: str) -> None:
    text = read(rel)
    if text is None:
        report(False, title, f"нет файла {rel}")
        return
    missing = [n for n in needles if n not in text]
    report(not missing, title, f"{rel}: не найдено {missing}")


def lacks(rel: str, title: str, *needles: str) -> None:
    text = read(rel)
    if text is None:
        report(False, title, f"нет файла {rel}")
        return
    found = [n for n in needles if n in text]
    report(not found, title, f"{rel}: осталось {found}")


def count(rel: str, title: str, needle: str, expected: int) -> None:
    text = read(rel) or ""
    n = text.count(needle)
    report(n == expected, title, f"{rel}: «{needle}» встречается {n} раз, нужно {expected}")


# ── 1. правки в файлах ─────────────────────────────────────
def static_checks() -> None:
    section("Веб: index.html")
    for js in ("icons", "haptic", "markdown", "api", "app"):
        count("web/index.html", f"{js}.js подключён один раз", f"/js/{js}.js", 1)
    count("web/index.html", "app.css подключён один раз", "/css/app.css", 1)
    count("web/index.html", "ui.css подключён один раз", "/css/ui.css", 1)
    has("web/index.html", "KaTeX подключён", "katex.min.js", "katex.min.css", "katex:ready")

    section("Веб: markdown.js")
    has("web/js/markdown.js", "формулы и новое копирование",
        "data-copy-code", "legacyCopy", "renderToString", "math-block", "attr, copy")
    lacks("web/js/markdown.js", "старая кнопка data-copy и старый LaTeX убраны",
          "<button data-copy>", "latex-display")

    section("Веб: app.js")
    count("web/js/app.js", "renderChat объявлена один раз", "function renderChat(", 1)
    lacks("web/js/app.js", "убраны copyText, emptyHTML, «подключаюсь», старый data-copy",
          "copyText", "emptyHTML", "подключаюсь", 'data-copy="', "dataset.copy;")
    has("web/js/app.js", "источники, выбор модели, копирование, KaTeX",
        "data-copy-msg", "citesSheet", "citesBtnHTML", "modelSections", "ms-search-wrap",
        "ms-search", 'cls: "ms"', "katex:ready", "const attr = window.MD.attr")

    section("Веб: CSS")
    has("web/css/ui.css", "новые стили в ui.css",
        ".math-block", ".cites-btn", ".favs", ".src-row", ".ms-search-wrap", ".sheet.ms", ".tag.brand")
    lacks("web/css/ui.css", "старый .latex-display убран из ui.css", ".latex-display")
    lacks("web/css/app.css", "старые блоки LaTeX и источников убраны из app.css",
          ".latex-display", ".latex-inline", ".cites-title", ".cites a")

    section("Бэкенд")
    has("app/core/catalog.py", "catalog.py: фирменные модели и производители",
        "branded_file", "def save_branded", "def delete_branded", "def api_path",
        "def guess_vendor", "def base_models", '"vendor": self.vendor')
    has("app/core/models.py", "models.py: колонка citations", "citations: Mapped")
    has("app/core/db.py", "db.py: досоздание колонки", "_add_missing_columns", "ADD COLUMN")
    has("app/core/settings_store.py", "settings_store: ключ system_prompt", '"system_prompt"')
    has("app/services/prompt.py", "prompt.py: use_global_prompt",
        "use_global_prompt", "model.system_prompt")
    has("app/services/pipeline.py", "pipeline.py: api_model и citations",
        "api_model", "model=api_model", "_clean_citations", "settings_store", '"connecting": "думает"')
    lacks("app/services/pipeline.py", "pipeline.py: нет «подключаюсь»", "подключаюсь")
    has("app/api/routes.py", "api/routes.py: citations в get_chat", '"citations": m.citations')
    has("app/bot/handlers/chat.py", "бот: «думает» в заглушке", "думает…")
    lacks("app/bot/handlers/chat.py", "бот: нет «подключаюсь»", "подключаюсь")
    has("app/bot/streamer.py", "бот: иконка фазы connecting", '"connecting": "💭"')

    section("Админка")
    has("app/admin/routes.py", "routes.py: фирменные модели и общий промпт",
        '"/branded"', '"/branded/delete"', "_config_ctx", "global_prompt", '"sp": sp')
    has("app/admin/templates/base.html", "base.html: мобильная вёрстка",
        "@media (max-width:720px)", "min(200px,100%)", ".chk", "scrollIntoView")
    has("app/admin/templates/login.html", "login.html: ширина под телефон", "min(320px")
    has("app/admin/templates/settings.html", "settings.html: переключатель промпта", "global_prompt")
    has("app/admin/templates/config.html", "config.html: форма фирменных моделей",
        "/admin/branded", "base_models", "system_prompt", "plan_codes")


# ── 2. Python: импорт, каталог, шаблоны ────────────────────
def python_checks() -> None:
    section("Python: импорт модулей")
    try:
        import app.main  # noqa: F401
        report(True, "app.main импортируется")
    except Exception as e:
        report(False, "app.main импортируется", repr(e))
        return
    try:
        from app.admin import routes as admin_routes
        report(True, "app.admin.routes импортируется")
    except Exception as e:
        # app.main глотает ImportError админки молча — поэтому проверяем отдельно
        report(False, "app.admin.routes импортируется", repr(e))
        admin_routes = None
    try:
        import app.bot.handlers  # noqa: F401
        report(True, "модули бота импортируются")
    except Exception as e:
        report(False, "модули бота импортируются", repr(e))

    section("Python: каталог моделей")
    from app.core.catalog import catalog

    try:
        catalog.reload()
    except Exception as e:
        report(False, "каталог загружается", repr(e))
        return
    models = catalog.models()
    base = catalog.base_models()
    branded = [m for m in models if m.branded]
    report(bool(models), f"каталог загружен: всего {len(models)}, обычных {len(base)}, фирменных {len(branded)}")

    pub = models[0].to_public("free") if models else {}
    need = {"vendor", "popular", "branded", "description"}
    report(need <= set(pub), "to_public отдаёт vendor/popular/branded/description",
           f"нет ключей {need - set(pub)}")
    leaked = [m.path for m in models if "system_prompt" in m.to_public("pro")]
    report(not leaked, "системный промпт не уходит клиенту", f"утекает у {leaked}")

    vendors: dict[str, int] = {}
    for m in base:
        vendors[m.vendor] = vendors.get(m.vendor, 0) + 1
    print("         производители: " + ", ".join(f"{v} {n}" for v, n in vendors.items()))
    others = [m.name for m in base if m.vendor == "Другие"]
    if others:
        warn(f"{len(others)} моделей попали в «Другие»",
             "добавьте им vendor: \"…\" в models.yml: " + ", ".join(others[:8]))
    if not any(m.popular for m in models):
        warn("нет ни одной модели с popular: true — раздела «Популярное» не будет")

    raw = catalog.branded_raw()
    if len(raw) != len(branded):
        warn(f"в branded.yml {len(raw)} записей, загружено {len(branded)}",
             "у пропущенных нет базовой модели в models.yml или занят ID (подробности в логе)")
    base_paths = {m.path for m in base}
    bad = [m.path for m in branded if m.upstream not in base_paths]
    report(not bad, "у фирменных моделей существует базовая модель", f"нет базы у {bad}")

    section("Python: функции")
    from app.core import settings_store
    from app.core.models import Message
    from app.services import pipeline, prompt

    report("use_global_prompt" in inspect.signature(prompt.build_payload).parameters,
           "build_payload принимает use_global_prompt")
    report(settings_store.DEFAULTS.get("system_prompt", {}).get("enabled") is False,
           "общий промпт по умолчанию выключен")
    report(pipeline.PHASE_LABELS.get("connecting") == "думает", "фаза connecting = «думает»")
    try:
        cleaned = pipeline._clean_citations([
            {"url": "javascript:alert(1)"}, {"url": "https://a.com", "title": "A"},
            {"url": "https://a.com"}, {"url": "http://b.org"},
        ])
        report(cleaned is not None and [c["url"] for c in cleaned] == ["https://a.com", "http://b.org"],
               "_clean_citations отсекает опасные ссылки и повторы", str(cleaned))
    except Exception as e:
        report(False, "_clean_citations работает", repr(e))
    report("citations" in Message.__table__.c, "в модели Message есть колонка citations")

    if admin_routes is not None:
        paths = {getattr(r, "path", "") for r in admin_routes.router.routes}
        need_paths = {"/admin/branded", "/admin/branded/delete", "/admin/settings", "/admin/config"}
        report(need_paths <= paths, "маршруты админки зарегистрированы", f"нет {need_paths - paths}")
        report("global_prompt" in inspect.signature(admin_routes.settings_save).parameters,
               "settings_save принимает global_prompt")

        section("Админка: шаблоны")
        tdir = ROOT / "app/admin/templates"
        for f in sorted(tdir.glob("*.html")):
            try:
                admin_routes.templates.env.get_template(f.name)
                report(True, f"{f.name} компилируется")
            except Exception as e:
                report(False, f"{f.name} компилируется", repr(e))
        try:
            ctx = admin_routes._config_ctx()
            ctx.update(ok=None, err=None, weak_password=False)
            html = admin_routes.templates.env.get_template("config.html").render(**ctx)
            report("Фирменные модели" in html, "config.html рендерится с реальным каталогом")
        except Exception as e:
            report(False, "config.html рендерится с реальным каталогом", repr(e))


# ── 3. БД: только чтение ───────────────────────────────────
async def db_check() -> None:
    section("База данных (только чтение)")
    from sqlalchemy import inspect as sa_inspect

    from app.core.config import settings
    from app.core.db import engine

    print(f"         движок: {settings.database_url.split('://')[0]}")

    def cols(conn):
        insp = sa_inspect(conn)
        if not insp.has_table("messages"):
            return None
        return {c["name"] for c in insp.get_columns("messages")}

    try:
        async with engine.connect() as conn:
            c = await conn.run_sync(cols)
    except Exception as e:
        report(False, "подключение к БД", repr(e))
        return
    finally:
        await engine.dispose()
    if c is None:
        warn("таблицы messages нет — БД пустая, создастся при первом запуске")
    else:
        report("citations" in c, "колонка messages.citations есть в БД",
               "запустите приложение один раз — init_db добавит её")


# ── 4. JS: синтаксис и поведение markdown.js ───────────────
NODE_TEST = r"""
const file = process.argv[process.argv.length - 1];
global.window = {}; global.document = { addEventListener() {} }; global.navigator = {};
require(file);
const r = s => window.MD.render(s);
const code = r("```py\nx = 1\n```");
console.log(JSON.stringify([
  ["$x^2$ становится формулой", r("Площадь $x^2$ тут").includes("math-inline")],
  ["$$…$$ становится блоком", r("$$a+b$$").includes("math-block")],
  ["\\(…\\) становится формулой", r("\\(a_1\\)").includes("math-inline")],
  ["\\[…\\] становится блоком", r("\\[\\frac{a}{b}\\]").includes("math-block")],
  ["«$5 и $10» НЕ формула", !r("Цена $5 и $10").includes("math")],
  ["$ внутри `кода` НЕ формула", !r("`echo $HOME$`").includes("math")],
  ["у блока кода кнопка data-copy-code", code.includes("data-copy-code")],
  ["у блока кода нет старого data-copy", !/data-copy[ >]/.test(code)],
  ["MD.copy существует", typeof window.MD.copy === "function"],
  ["MD.attr экранирует кавычки", window.MD.attr('"') === "&quot;"],
  ["без KaTeX формула видна исходником", r("$y$").includes("math-raw")],
]));
"""


def js_checks() -> None:
    section("JS")
    node = shutil.which("node")
    if not node:
        warn("node не найден — JS-проверки пропущены",
             "поставьте Node.js (https://nodejs.org) или проверьте в браузере")
        return
    for rel in ("web/js/app.js", "web/js/markdown.js", "web/js/api.js",
                "web/js/icons.js", "web/js/haptic.js"):
        p = subprocess.run([node, "--check", str(ROOT / rel)],
                           capture_output=True, text=True, encoding="utf-8")
        report(p.returncode == 0, f"{rel}: синтаксис", (p.stderr or "").strip()[:400])

    p = subprocess.run([node, "-e", NODE_TEST, str(ROOT / "web/js/markdown.js")],
                       capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        report(False, "markdown.js выполняется", (p.stderr or "").strip()[:400])
        return
    for title, ok in json.loads(p.stdout.strip().splitlines()[-1]):
        report(bool(ok), f"markdown: {title}")


# ── 5. запущенный сервер ───────────────────────────────────
def http_checks(base: str) -> None:
    section(f"Сервер {base}")
    import httpx

    try:
        with httpx.Client(base_url=base, timeout=10, follow_redirects=False) as c:
            r = c.get("/health")
            report(r.status_code == 200 and r.json().get("ok"), "/health отвечает", f"HTTP {r.status_code}")
            html = c.get("/").text
            report(html.count("/js/app.js") == 1 and "v=9" in html,
                   "сервер отдаёт новый index.html", "старая версия — перезапустите/пересоберите")
            js = c.get("/js/app.js?v=9").text
            report("data-copy-msg" in js, "сервер отдаёт новый app.js")
            css = c.get("/css/ui.css?v=9").text
            report(".ms-search-wrap" in css, "сервер отдаёт новый ui.css")
            r = c.get("/admin/login")
            report(r.status_code in (200, 303), "/admin/login открывается", f"HTTP {r.status_code}")
    except httpx.HTTPError as e:
        report(False, "сервер доступен", repr(e))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", help="адрес запущенного сервера, например http://127.0.0.1:8080")
    args = ap.parse_args()

    static_checks()
    python_checks()
    asyncio.run(db_check())
    js_checks()
    if args.http:
        http_checks(args.http.rstrip("/"))

    print(f"\nИтого: {stats['ok']} OK, {stats['fail']} FAIL, {stats['warn']} WARN")
    sys.exit(1 if stats["fail"] else 0)


if __name__ == "__main__":
    main()
