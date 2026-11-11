/* Markdown → HTML, формулы через KaTeX, копирование в буфер. */
window.MD = (() => {
  const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const attr = s => String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function inline(t) {
    return t
      .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)"]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      /* без lookbehind: старые WebView в Telegram на нём падали целиком */
      .replace(/(^|[\s(])\*([^\s*][^*]*?)\*(?=$|[\s.,!?)])/g, "$1<em>$2</em>")
      .replace(/(^|[\s(])_([^\s_][^_]*?)_(?=$|[\s.,!?)])/g, "$1<em>$2</em>")
      .replace(/~~(.+?)~~/g, "<s>$1</s>");
  }

  /* KaTeX ещё не загрузился или формула битая — показываем исходник */
  function tex(src, display, raw) {
    const k = window.katex;
    if (k && typeof k.renderToString === "function") {
      try {
        return k.renderToString(src, {
          displayMode: display, throwOnError: false, strict: "ignore", output: "html",
        });
      } catch (e) { /* ниже исходник */ }
    }
    return `<span class="math-raw">${esc(raw)}</span>`;
  }

  function render(src) {
    const stash = [];
    const keep = html => { stash.push(html); return `\u0000${stash.length - 1}\u0000`; };

    let t = String(src || "").replace(/```([^\n`]*)\n([\s\S]*?)(?:```|$)/g, (m, lang, body) =>
      keep(`<pre><div class="code-head"><span>${esc(lang.trim() || "code")}</span>`
        + `<button data-copy-code>Копировать</button></div>`
        + `<code>${esc(body.replace(/\n+$/, ""))}</code></pre>`));

    /* инлайн-код раньше формул: $ внутри `...` не трогаем */
    t = t.replace(/`([^`\n]+)`/g, (m, c) => keep(`<code class="inline">${esc(c)}</code>`));

    const block = (f, raw) => `\n${keep(`<div class="math-block">${tex(f.trim(), true, raw)}</div>`)}\n`;
    const inl = (f, raw) => keep(`<span class="math-inline">${tex(f.trim(), false, raw)}</span>`);
    t = t
      .replace(/\$\$([\s\S]+?)\$\$/g, (m, f) => block(f, m))
      .replace(/\\\[([\s\S]+?)\\\]/g, (m, f) => block(f, m))
      .replace(/\\\(([\s\S]+?)\\\)/g, (m, f) => inl(f, m))
      /* $x$: без пробелов у границ и без цифры после — иначе «$5 и $10» стало бы формулой */
      .replace(/(^|[^\\$\w])\$([^\s$](?:[^$\n]*?[^\s$\\])?)\$(?![\w$])/g,
        (m, pre, f) => pre + inl(f, m.slice(pre.length)));

    t = esc(t);

    const lines = t.split("\n");
    let out = "", para = [], list = null, table = null;
    const flushP = () => { if (para.length) { out += `<p>${inline(para.join("<br>"))}</p>`; para = []; } };
    const flushL = () => {
      if (list) {
        out += `<${list.tag}>${list.items.map(i => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`;
        list = null;
      }
    };
    const flushT = () => {
      if (!table) return;
      const row = (cells, tag) => `<tr>${cells.map(c => `<${tag}>${inline(c)}</${tag}>`).join("")}</tr>`;
      out += `<table><thead>${row(table.head, "th")}</thead>`
        + `<tbody>${table.rows.map(r => row(r, "td")).join("")}</tbody></table>`;
      table = null;
    };
    const flushAll = () => { flushP(); flushL(); flushT(); };
    const cells = l => l.replace(/^\||\|$/g, "").split("|").map(c => c.trim());

    for (let i = 0; i < lines.length; i++) {
      const l = lines[i], tr = l.trim();
      if (!tr) { flushAll(); continue; }
      if (/^\u0000\d+\u0000$/.test(tr)) { flushAll(); out += stash[+tr.slice(1, -1)]; continue; }
      if (/^#{1,6}\s/.test(tr)) { flushAll(); out += `<h3>${inline(tr.replace(/^#{1,6}\s*/, ""))}</h3>`; continue; }
      if (/^(---|\*\*\*|___)$/.test(tr)) { flushAll(); out += "<hr>"; continue; }
      if (/^&gt;\s?/.test(tr)) { flushAll(); out += `<blockquote>${inline(tr.replace(/^&gt;\s?/, ""))}</blockquote>`; continue; }
      if (tr.startsWith("|") && /^\|[\s:|-]+\|$/.test((lines[i + 1] || "").trim())) {
        flushAll(); table = { head: cells(tr), rows: [] }; i++; continue;
      }
      if (table && tr.startsWith("|")) { table.rows.push(cells(tr)); continue; }
      flushT();
      const ul = tr.match(/^[-*+]\s+(.*)$/), ol = tr.match(/^\d+[.)]\s+(.*)$/);
      if (ul || ol) {
        const tag = ul ? "ul" : "ol";
        flushP();
        if (!list || list.tag !== tag) { flushL(); list = { tag, items: [] }; }
        list.items.push((ul || ol)[1]);
        continue;
      }
      flushL(); para.push(tr);
    }
    flushAll();
    for (let i = 0; i < stash.length; i++) out = out.split(`\u0000${i}\u0000`).join(stash[i]);
    return out;
  }

  /* Частичный текст: незакрытый блок кода дорисовывается, чтобы вёрстка не прыгала. */
  function renderPartial(src) {
    let t = String(src || "");
    if ((t.match(/```/g) || []).length % 2) t += "\n```";
    return render(t);
  }

  /* Синхронный путь первым: в WebView Telegram clipboard API часто отклоняется,
     а после await жест пользователя уже истёк и execCommand не сработает. */
  function legacyCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none";
    document.body.appendChild(ta);
    const sel = document.getSelection();
    const prev = sel && sel.rangeCount ? sel.getRangeAt(0) : null;
    ta.select();
    ta.setSelectionRange(0, text.length);
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    if (prev && sel) { sel.removeAllRanges(); sel.addRange(prev); }
    return ok;
  }

  async function copy(text) {
    if (legacyCopy(text)) return true;
    if (navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* ниже false */ }
    }
    return false;
  }

  return { render, renderPartial, esc, attr, copy };
})();

/* Копирование блока кода */
document.addEventListener("click", async e => {
  const btn = e.target.closest("[data-copy-code]");
  if (!btn) return;
  const code = btn.closest("pre")?.querySelector("code")?.textContent || "";
  if (await window.MD.copy(code)) {
    window.Haptic.ok();
    btn.textContent = "Скопировано";
    setTimeout(() => (btn.textContent = "Копировать"), 1600);
  } else {
    window.Haptic.err();
    window.toast?.("Буфер недоступен в этом окружении");
  }
});

