/* Markdown → HTML. Тот же рендер, что в макете; добавлена защита при стриминге. */
window.MD = (() => {
  const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  function inline(t) {
    return t
      .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      /* без lookbehind: старые WebView в Telegram на нём падали целиком */
      .replace(/(^|[\s(])\*([^\s*][^*]*?)\*(?=$|[\s.,!?)])/g, "$1<em>$2</em>")
      .replace(/(^|[\s(])_([^\s_][^_]*?)_(?=$|[\s.,!?)])/g, "$1<em>$2</em>")
      .replace(/~~(.+?)~~/g, "<s>$1</s>");
  }

  function render(src) {
    const stash = [];
    let t = String(src || "").replace(/```([^\n`]*)\n([\s\S]*?)(?:```|$)/g, (m, lang, body) => {
      stash.push(`<pre><div class="code-head"><span>${esc(lang.trim() || "code")}</span>`
        + `<button data-copy>Копировать</button></div>`
        + `<code>${esc(body.replace(/\n+$/, ""))}</code></pre>`);
      return `\u0000${stash.length - 1}\u0000`;
    });
    t = t.replace(/`([^`\n]+)`/g, (m, c) => {
      stash.push(`<code class="inline">${esc(c)}</code>`);
      return `\u0000${stash.length - 1}\u0000`;
    });
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

  return { render, renderPartial, esc };
})();

/* Копирование кода — одним слушателем на документ */
document.addEventListener("click", e => {
  const btn = e.target.closest("[data-copy]");
  if (!btn) return;
  const code = btn.closest("pre")?.querySelector("code")?.textContent || "";
  const done = () => {
    window.Haptic.ok();
    btn.textContent = "Скопировано";
    setTimeout(() => (btn.textContent = "Копировать"), 1600);
  };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(code).then(done).catch(() => {
      window.Haptic.err();
      window.toast?.("Буфер недоступен в этом окружении");
    });
  } else {
    window.Haptic.err();
    window.toast?.("Буфер недоступен в этом окружении");
  }
});
