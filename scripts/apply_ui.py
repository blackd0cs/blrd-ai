"""
Выбор модели: плавающий поиск, группы с логотипами, лёгкое затемнение сверху.
Поднимает версию кеша в index.html.

  uv run python scripts\apply_ui.py            # применить
  uv run python scripts\apply_ui.py --dry-run  # показать, что изменится, ничего не записывая

Повторный запуск безопасен. Копии изменённых файлов: backups\<время>\.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── что вставляем ──────────────────────────────────────────
CSS_BLOCK = r"""
/* >>> выбор модели: плавающий поиск (scripts/apply_ui.py) */
.sheet.ms{display:flex;flex-direction:column;height:84%;overflow:hidden;padding-top:0}
.sheet.ms .energy{flex:none}
.sheet.ms .handle{position:absolute;top:6px;left:50%;margin:0;transform:translateX(-50%);z-index:4}
.sheet.ms::before{
  content:"";position:absolute;left:0;right:0;top:0;height:92px;z-index:2;pointer-events:none;
  background:linear-gradient(180deg,
    rgba(16,16,19,.78) 0%, rgba(16,16,19,.55) 30%, rgba(16,16,19,.26) 62%, rgba(16,16,19,0) 100%);
}
.ms-head{position:absolute;top:22px;left:10px;right:10px;z-index:5;display:flex;padding:0;pointer-events:none}
.ms-search-wrap{display:flex;align-items:center;width:46px;height:46px;border-radius:23px;padding:0;
  pointer-events:auto;transition:width .38s cubic-bezier(.3,.9,.3,1);
  box-shadow:0 1px 0 var(--glass-hi) inset,0 -1px 0 rgba(0,0,0,.28) inset,0 10px 30px rgba(0,0,0,.55)}
.ms-search-wrap.open{width:100%}
.ms-search-btn{width:46px;height:46px;flex:none;display:grid;place-items:center;color:#ececee;
  position:relative;z-index:1;transition:transform .12s}
.ms-search-btn .ic{width:19px;height:19px}
.ms-search-wrap:not(.open) .ms-search-btn:active{transform:scale(.88)}
.ms-search{flex:1;min-width:0;height:100%;background:none;border:0;outline:none;padding:0;
  color:var(--text);font:inherit;font-size:16px;-webkit-appearance:none;appearance:none;
  position:relative;z-index:1;opacity:0;transition:opacity .2s ease}
.ms-search-wrap.open .ms-search{opacity:1;transition-delay:.12s}
.ms-search::placeholder{color:var(--dim)}
.ms-clear{width:34px;height:34px;margin-right:6px;border-radius:50%;flex:none;
  display:grid;place-items:center;color:#d4d4d8;background:rgba(255,255,255,.1);
  box-shadow:0 1px 0 rgba(255,255,255,.14) inset;position:relative;z-index:1;
  opacity:0;transform:scale(.6);pointer-events:none;transition:opacity .2s,transform .2s}
.ms-search-wrap.open .ms-clear{opacity:1;transform:none;pointer-events:auto;transition-delay:.14s}
.ms-clear .ic{width:12px;height:12px}
.ms-list{flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;
  padding-top:22px;position:relative;z-index:1;transition:padding-top .3s cubic-bezier(.3,.9,.3,1)}
.ms-list.searching{padding-top:76px}
.ms-empty{color:var(--dim);text-align:center;padding:30px 0}
.ms-group{display:flex;align-items:center;gap:8px;margin:18px 10px 6px;min-height:20px;
  font-size:14px;font-weight:600;color:var(--dim);text-transform:none;letter-spacing:-.01em}
.ms-list .ms-group:first-child{margin:13px 10px 10px 66px}
.ms-list.searching .ms-group:first-child{margin:4px 10px 6px}
.v-logo{width:18px;height:18px;border-radius:5px;object-fit:contain;flex:none}
/* <<< выбор модели */
"""

JS_BLOCK = r"""
/* ── выбор модели: поиск и группы ────────────────────── */
function modelSections() {
  const out = [];
  const popular = state.models.filter(m => m.popular);
  if (popular.length) out.push({ title: "Популярное", items: popular });
  const branded = state.models.filter(m => m.branded);
  if (branded.length) out.push({ title: "Фирменные", items: branded });
  const byVendor = new Map();
  for (const m of state.models) {
    if (m.branded) continue;
    const v = m.vendor || "Другие";
    if (!byVendor.has(v)) byVendor.set(v, []);
    byVendor.get(v).push(m);
  }
  for (const [v, items] of byVendor) out.push({ title: v, items });
  return out;
}

function groupHeadHTML(title) {
  const src = (I.vendorLogos || {})[title];
  const logo = src ? `<img class="v-logo" src="${attr(src)}" alt="" onerror="this.remove()">` : "";
  return `<h3 class="ms-group">${logo}<span>${esc(title)}</span></h3>`;
}

function modelRowHTML(m) {
  const lk = locked(m);
  const bits = [m.multiplier === 0 ? "бесплатно" : `×${m.multiplier} энергии`];
  if (m.vision) bits.push("видит картинки");
  if (m.web_search) bits.push("ищет в интернете");
  const right = lk ? `<span class="tag">PRO</span>` : (m.path === state.modelPath ? I.check : "");
  return `<button class="m-row ${m.path === state.modelPath ? "sel" : ""} ${lk ? "locked" : ""}"
    data-haptic="off" data-p="${attr(m.path)}">
    <div class="meta">
      <div class="nm">${esc(m.name)}${m.branded ? ` <span class="tag brand">blrd</span>` : ""}</div>
      ${m.description ? `<div class="desc">${esc(m.description)}</div>` : ""}
      <div class="sub">${bits.join(" · ")}</div>
    </div>${right}</button>`;
}

function modelMatches(m, words) {
  const hay = `${m.name} ${m.short} ${m.vendor || ""} ${m.path} ${m.description || ""}`.toLowerCase();
  return words.every(w => hay.includes(w));
}

const SEARCH_ICON = I.search || `<svg class="ic" viewBox="0 0 20 20" fill="none"><circle cx="9" cy="9" r="5.8" stroke="currentColor" stroke-width="1.7"/><path d="M13.4 13.4L17 17" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;
const CLOSE_ICON = I.close || `<svg class="ic" viewBox="0 0 18 18" fill="none"><path d="M4 4l10 10M14 4L4 14" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>`;

function modelSheet() {
  $("pill").classList.add("open");
  const sections = modelSections();

  const el = sheet(`<div class="handle"></div>
    <div class="ms-head">
      <div class="ms-search-wrap glass">
        <button class="ms-search-btn" type="button" data-haptic="off" aria-label="Поиск">${SEARCH_ICON}</button>
        <input class="ms-search" type="text" inputmode="search" placeholder="Поиск модели"
               autocomplete="off" autocorrect="off" spellcheck="false" enterkeyhint="search" tabindex="-1">
        <button class="ms-clear" type="button" data-haptic="off" aria-label="Закрыть поиск">${CLOSE_ICON}</button>
      </div>
    </div>
    <div class="ms-list"></div>
    <div class="energy">Баланс: ${state.user.energy} из ${state.user.energy_max} энергии</div>`, { cls: "ms" });

  const list = el.querySelector(".ms-list");
  const wrap = el.querySelector(".ms-search-wrap");
  const input = el.querySelector(".ms-search");

  const draw = () => {
    const words = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    list.innerHTML = words.length
      ? (state.models.filter(m => modelMatches(m, words)).map(modelRowHTML).join("")
          || `<div class="ms-empty">Ничего не найдено</div>`)
      : sections.map(s => groupHeadHTML(s.title) + s.items.map(modelRowHTML).join("")).join("");
    list.scrollTop = 0;
  };

  const openSearch = () => {
    if (wrap.classList.contains("open")) { input.focus(); return; }
    window.Haptic.tap();
    wrap.classList.add("open");
    list.classList.add("searching");
    input.tabIndex = 0;
    input.focus();             // синхронно в обработчике нажатия, иначе iOS не откроет клавиатуру
  };

  const closeSearch = () => {
    const had = !!input.value;
    input.value = "";
    input.tabIndex = -1;
    wrap.classList.remove("open");
    list.classList.remove("searching");
    input.blur();
    if (had) draw();
  };

  el.querySelector(".ms-search-btn").addEventListener("click", openSearch);
  el.querySelector(".ms-clear").addEventListener("pointerdown", e => e.preventDefault());
  el.querySelector(".ms-clear").addEventListener("click", () => { window.Haptic.tap(); closeSearch(); });

  input.addEventListener("input", draw);
  input.addEventListener("keydown", e => {
    if (e.key === "Enter") input.blur();
    if (e.key === "Escape") { e.stopPropagation(); closeSearch(); }
  });
  input.addEventListener("blur", () => { if (!input.value.trim()) closeSearch(); });

  list.addEventListener("pointerdown", e => {
    const row = e.target.closest(".m-row");
    if (!row) return;
    const m = state.models.find(x => x.path === row.dataset.p);
    locked(m) ? window.Haptic.err() : window.Haptic.select();
  });

  list.addEventListener("click", async e => {
    const row = e.target.closest(".m-row");
    if (!row) return;
    const m = state.models.find(x => x.path === row.dataset.p);
    if (!m) return;
    if (locked(m)) { closeSheet(); paywall(); return; }
    state.modelPath = m.path;
    closeSheet();
    renderHeader();
    toast(`Модель: ${m.name}`);
    try {
      await window.API.selectModel(m.path);
      if (state.chatId) await window.API.patchChat(state.chatId, { model: m.path });
    } catch (err) { /* уйдёт вместе с запросом */ }
  });

  draw();
  list.querySelector(".m-row.sel")?.scrollIntoView({ block: "center" });
}
$("pill").onclick = () => ($("layer").querySelector(".sheet") ? closeSheet() : modelSheet());
"""

ICON_SEARCH = r"""  search: `<svg class="ic" viewBox="0 0 20 20" fill="none"><circle cx="9" cy="9" r="5.8" stroke="currentColor" stroke-width="1.7"/><path d="M13.4 13.4L17 17" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,

"""

ICON_VENDORS = """  /* ─── логотипы групп в выборе модели: впишите ссылки ── */
  vendorLogos: {
    "Популярное": "",
    "Фирменные": "/img/logo.png",
    "Anthropic": "",
    "OpenAI": "",
    "Google": "",
    "xAI": "",
    "Moonshot": "",
    "Zhipu": "",
    "DeepSeek": "",
    "Qwen": "",
    "MiniMax": "",
    "NVIDIA": "",
    "Muse": "",
    "Jev": "",
    "Другие": "",
  },

"""


# ── файлы ──────────────────────────────────────────────────
def read(rel: str) -> str:
    with open(ROOT / rel, encoding="utf-8", newline="") as f:
        return f.read()


def nl(block: str, like: str) -> str:
    """Переводы строк вставки — как в файле (CRLF или LF)."""
    block = block.replace("\r\n", "\n")
    return block.replace("\n", "\r\n") if "\r\n" in like else block


# ── ui.css ─────────────────────────────────────────────────
OLD_CSS = re.compile(r"\.ms-|\.sheet\.ms\b|\.v-logo")
OLD_COMMENTS = ("выбор модели", "поиск модели", "плавающим поиском")


def css_tokens(text: str) -> list[tuple[str, str]]:
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(("comment", text[i:j]))
            i = j
            continue
        if text[i].isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            out.append(("ws", text[i:j]))
            i = j
            continue
        b = text.find("{", i)
        if b < 0:
            out.append(("raw", text[i:]))
            break
        depth, j = 0, b
        while j < n:
            if text.startswith("/*", j):
                k = text.find("*/", j + 2)
                j = n if k < 0 else k + 2
                continue
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        out.append(("rule", text[i:j]))
        i = j
    return out


def patch_css(text: str) -> tuple[str, str]:
    removed = 0
    kept: list[str] = []
    for kind, chunk in css_tokens(text):
        if kind == "rule":
            prelude = chunk.split("{", 1)[0].strip()
            if not prelude.startswith("@") and OLD_CSS.search(prelude):
                removed += 1
                continue
        if kind == "comment" and any(c in chunk for c in OLD_COMMENTS):
            continue
        kept.append(chunk)
    body = re.sub(r"(\r?\n[ \t]*){3,}", lambda m: m.group(1) * 2, "".join(kept)).rstrip()
    new = body + nl("\n" + CSS_BLOCK, text)
    return new, f"убрано старых правил: {removed}, добавлен новый блок"


# ── app.js ─────────────────────────────────────────────────
def patch_app(text: str) -> tuple[str, str]:
    markers = ("/* ── выбор модели", "const TAB_ALL", "let pickerTab", "function modelSections(",
               "function groupHeadHTML(", "function modelRowHTML(", "function modelMatches(",
               "const SEARCH_ICON", "function modelSheet(")
    starts = [p for p in (text.find(m) for m in markers) if p >= 0]
    end = re.search(r'^\$\("pill"\)\.onclick\s*=.*$', text, re.M)
    if not starts or not end:
        raise SystemExit("app.js: не нашёл выбор модели или строку $(\"pill\").onclick — пришлите файл")
    start = text.rfind("\n", 0, min(starts)) + 1
    region = text[start:end.end()]
    for danger in ("function paywall(", "function sheet(", "function citesSheet(", "async function send("):
        if danger in region:
            raise SystemExit(f"app.js: в заменяемый участок попала {danger} — порядок функций другой, "
                             "остановился, чтобы ничего не сломать")
    new = text[:start] + nl(JS_BLOCK.strip("\n"), text) + text[end.end():]
    for once in ("function modelSheet(", "const SEARCH_ICON", "function modelSections(", '$("pill").onclick'):
        if new.count(once) != 1:
            raise SystemExit(f"app.js: «{once}» встречается {new.count(once)} раз — правка отменена")
    return new, f"заменён участок выбора модели ({region.count(chr(10)) + 1} строк)"


# ── icons.js ───────────────────────────────────────────────
def patch_icons(text: str) -> tuple[str, str]:
    m = re.search(r"^[ \t]*logoUrl\s*:", text, re.M)
    if not m:
        raise SystemExit("icons.js: не нашёл logoUrl")
    at = m.start()
    prev = text.rfind("\n", 0, max(0, at - 1))
    if "логотип в сайдбаре" in text[prev + 1:at]:
        at = prev + 1
    add, notes = "", []
    if not re.search(r"^[ \t]*search\s*:", text, re.M):
        add += ICON_SEARCH
        notes.append("иконка search")
    if "vendorLogos" not in text:
        add += ICON_VENDORS
        notes.append("vendorLogos")
    if not add:
        return text, "уже на месте"
    return text[:at] + nl(add, text) + text[at:], "добавлено: " + ", ".join(notes)


# ── index.html ─────────────────────────────────────────────
def patch_index(text: str) -> tuple[str, str, int]:
    found = [int(v) for v in re.findall(r"\?v=(\d+)", text)]
    ver = (max(found) if found else 0) + 1
    new = re.sub(r"\?v=\d+", f"?v={ver}", text)
    if not found:
        return text, "нет ?v= — проверьте подключение скриптов вручную", ver
    return new, f"версия кеша → v={ver} (мест: {len(found)})", ver


def patch_check(text: str, ver: int) -> tuple[str, str]:
    new = re.sub(r'(?<=[?"])v=\d+', f"v={ver}", text).replace("ms-tabs", "ms-search-wrap")
    return new, f"проверки обновлены под v={ver}"


# ── запуск ─────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="ничего не записывать")
    args = ap.parse_args()

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = ROOT / "backups" / stamp
    changes: list[tuple[str, str, str]] = []

    def plan(rel: str, fn, *extra):
        p = ROOT / rel
        if not p.exists():
            print(f"[SKIP] {rel}: файла нет")
            return None
        old = read(rel)
        res = fn(old, *extra)
        new, note = res[0], res[1]
        status = "без изменений" if new == old else note
        print(f"[{'OK  ' if new != old else '----'}] {rel}: {status}")
        if new != old:
            changes.append((rel, old, new))
        return res

    plan("web/css/ui.css", patch_css)
    plan("web/js/app.js", patch_app)
    plan("web/js/icons.js", patch_icons)
    res = plan("web/index.html", patch_index)
    ver = res[2] if res else 0
    if ver:
        plan("scripts/check_update.py", patch_check, ver)

    if args.dry_run:
        print("\n--dry-run: ничего не записано")
        return
    if not changes:
        print("\nМенять нечего")
        return

    for rel, old, new in changes:
        dst = backup_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
        with open(ROOT / rel, "w", encoding="utf-8", newline="") as f:
            f.write(new)
    print(f"\nЗаписано файлов: {len(changes)}. Копии: {backup_dir.relative_to(ROOT)}")

    node = shutil.which("node")
    if node:
        for rel in ("web/js/app.js", "web/js/icons.js"):
            p = subprocess.run([node, "--check", str(ROOT / rel)], capture_output=True, text=True, encoding="utf-8")
            print(f"[{'OK  ' if p.returncode == 0 else 'FAIL'}] синтаксис {rel}"
                  + ("" if p.returncode == 0 else "\n" + p.stderr.strip()[:500]))
    else:
        print("[WARN] node не найден — синтаксис JS не проверен")

    print("\nДальше: закройте Mini App в Telegram (смахните) и откройте заново.")


if __name__ == "__main__":
    main()
