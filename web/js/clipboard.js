/* =========================================================
   clipboard.js — копирование, которое надёжно работает в WebView.

   В Telegram на Android и iOS navigator.clipboard часто
   отсутствует или отклоняет запись (не secure context,
   нет разрешения, либо теряется жест пользователя при async).
   Поэтому порядок такой:
     1. Синхронная попытка через legacy execCommand внутри жеста
     2. Если не прошло — пробуем navigator.clipboard.writeText
     3. При отказе снова legacy.
   ========================================================= */
window.Clip = (() => {
  function legacy(text) {
    const s = String(text == null ? "" : text);
    const el = document.createElement("textarea");
    el.value = s;
    el.setAttribute("readonly", "");
    el.contentEditable = "true";          /* iOS: иначе select() не работает */
    el.style.cssText =
      "position:fixed;top:0;left:0;width:1px;height:1px;padding:0;border:0;" +
      "outline:0;opacity:0.01;z-index:-1;font-size:16px";  /* 16px — чтобы iOS не зумил */
    document.body.appendChild(el);

    const sel = document.getSelection();
    const saved = sel && sel.rangeCount > 0 ? sel.getRangeAt(0) : null;

    let ok = false;
    try {
      el.focus({ preventScroll: true });
      el.select();
      el.setSelectionRange(0, s.length);   /* iOS требует явный диапазон */
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }

    el.remove();
    if (saved && sel) {
      try { sel.removeAllRanges(); sel.addRange(saved); } catch (e) {}
    }
    return ok;
  }

  /* Возвращает Promise<boolean>. Вызывать только из обработчика события пользователя. */
  async function copy(text) {
    const s = String(text == null ? "" : text);
    if (!s) return false;

    // 1. Сначала пробуем синхронный путь — он гарантированно укладывается в жест пользователя (iOS)
    try {
      if (legacy(s)) return true;
    } catch (e) {}

    // 2. Если синхронно не получилось — пробуем современный async API
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      try {
        await navigator.clipboard.writeText(s);
        return true;
      } catch (e) {
        // 3. Последняя попытка
        return legacy(s);
      }
    }

    return false;
  }

  return { copy, legacy };
})();
