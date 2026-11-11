/* Виброотклик: нативный в Telegram, navigator.vibrate вне него. */
window.Haptic = (() => {
  const tg = window.Telegram?.WebApp;
  const hf = tg?.HapticFeedback;
  const tgOK = !!(hf && typeof hf.impactOccurred === "function");
  const vibOK = !tgOK && typeof navigator.vibrate === "function";
  let last = 0, on = true;

  const fire = (native, pattern, force) => {
    if (!on) return;
    const now = performance.now();
    if (!force && now - last < 45) return;
    last = now;
    try { if (tgOK) native(); else if (vibOK) navigator.vibrate(pattern); } catch (e) {}
  };

  return {
    get enabled() { return on; },
    set enabled(v) { on = !!v; },
    tap:    () => fire(() => hf.impactOccurred("light"),  8),
    press:  () => fire(() => hf.impactOccurred("medium"), 16),
    heavy:  () => fire(() => hf.impactOccurred("heavy"),  26),
    soft:   () => fire(() => hf.impactOccurred("soft"),   6),
    rigid:  () => fire(() => hf.impactOccurred("rigid"),  11),
    select: () => fire(() => (hf.selectionChanged ? hf.selectionChanged() : hf.impactOccurred("light")), 5),
    ok:     () => fire(() => hf.notificationOccurred("success"), [11, 45, 22], true),
    warn:   () => fire(() => hf.notificationOccurred("warning"), [16, 55, 16], true),
    err:    () => fire(() => hf.notificationOccurred("error"),   [22, 55, 22, 55, 22], true)
  };
})();

document.addEventListener("pointerdown", e => {
  const el = e.target.closest("button,[role=button]");
  if (!el || el.disabled || el.dataset.haptic === "off") return;
  window.Haptic.tap();
}, true);
