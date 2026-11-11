/* =========================================================
   ИКОНКИ. Вставляйте свой SVG между кавычками.
   Правила: viewBox обязателен, fill/stroke — currentColor,
   без width/height (размер задаёт CSS через класс .ic).
   ========================================================= */
window.ICONS = {

  /* ─── шапка и меню ───────────────────────────────── */
  menu: `<svg class="ic" viewBox="0 0 20 20" fill="none"><path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`,

  newChat: `<svg class="ic" viewBox="0 0 24 24" fill="none"><path d="M4.5 19.5h3.6L20 7.6a2.55 2.55 0 00-3.6-3.6L4.5 15.9v3.6z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>`,

  close: `<svg class="ic" viewBox="0 0 18 18" fill="none"><path d="M4 4l10 10M14 4L4 14" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>`,

  chevron: `<svg class="ic" viewBox="0 0 14 14" fill="none"><path d="M3 5.5l4 4 4-4" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  /* ─── действия под сообщением ────────────────────── */
  copy: `<svg class="ic" viewBox="0 0 20 20" fill="none"><rect x="7" y="7" width="9.5" height="10.5" rx="2.6" stroke="currentColor" stroke-width="1.5"/><path d="M13 4.5H6a2.5 2.5 0 00-2.5 2.5v7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,

  retry: `<svg class="ic" viewBox="0 0 20 20" fill="none"><path d="M16.2 10a6.2 6.2 0 11-1.9-4.45" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M16.4 2.8v3.6h-3.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  check: `<svg class="ic" viewBox="0 0 18 18" fill="none"><path d="M4 9.4l3.2 3.1L14 5.8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  /* ─── композер ───────────────────────────────────── */
  attach: `<svg class="ic" viewBox="0 0 22 22" fill="none"><path d="M11 4.5v13M4.5 11h13" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`,

  send: `<svg class="ic" viewBox="0 0 20 20" fill="none"><path d="M10 15.5V4.5m0 0L5 9.5M10 4.5l5 5" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  stop: `<svg class="ic" viewBox="0 0 16 16"><rect x="3" y="3" width="10" height="10" rx="2.6" fill="currentColor"/></svg>`,

  /* ─── сайдбар ────────────────────────────────────── */
  share: `<svg class="ic" viewBox="0 0 24 24" fill="none"><path d="M8.6 13.4l6.8 3.4M15.4 7.2L8.6 10.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="18" cy="5.6" r="2.8" stroke="currentColor" stroke-width="1.6"/><circle cx="6" cy="12" r="2.8" stroke="currentColor" stroke-width="1.6"/><circle cx="18" cy="18.4" r="2.8" stroke="currentColor" stroke-width="1.6"/></svg>`,

  support: `<svg class="ic" viewBox="0 0 24 24" fill="none"><path d="M20.5 12a8.5 8.5 0 10-3.3 6.73l3.3.77-.9-3.2A8.46 8.46 0 0020.5 12z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M9.6 9.7a2.5 2.5 0 114 2.1c-.9.6-1.3 1-1.3 2M12.3 16.3v.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>`,

  home: `<svg class="ic" viewBox="0 0 24 24" fill="none"><rect x="5" y="2.8" width="14" height="18.4" rx="3.2" stroke="currentColor" stroke-width="1.6"/><path d="M12 8v6.4M9 11.4l3 3 3-3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  trash: `<svg class="ic" viewBox="0 0 16 16" fill="none"><path d="M3 5h10M6.5 5V3.5h3V5M4.8 5l.7 8h5l.7-8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  /* ─── прочее ─────────────────────────────────────── */
  doc: `<svg class="ic" viewBox="0 0 18 18" fill="none"><path d="M5 2.5h5l3 3v10H5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M10 2.5v3h3" stroke="currentColor" stroke-width="1.4"/></svg>`,

  warn: `<svg class="ic" viewBox="0 0 20 20" fill="none"><path d="M10 3.5l7 13H3l7-13zM10 8.5v4M10 14.4v.2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  energy: `<svg class="ic" viewBox="0 0 20 20" fill="none"><path d="M11.2 2.5L4.8 11h4l-1 6.5L15.2 9h-4l1-6.5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`,

  brain: `<svg class="ic" viewBox="0 0 20 20" fill="none"><path d="M7.4 3.5A2.9 2.9 0 004.5 6.4v.5A2.6 2.6 0 003.2 9.2c0 1 .54 1.85 1.34 2.3A2.7 2.7 0 007.2 16.5h.2V3.5h-.1zM12.6 3.5a2.9 2.9 0 012.9 2.9v.5a2.6 2.6 0 011.3 2.3c0 1-.54 1.85-1.34 2.3a2.7 2.7 0 01-2.66 4.9h-.2V3.5h.1z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>`,

  search: `<svg class="ic" viewBox="0 0 20 20" fill="none"><circle cx="9" cy="9" r="5.8" stroke="currentColor" stroke-width="1.7"/><path d="M13.4 13.4L17 17" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,

  /* ─── логотипы групп в выборе модели ─────────────── */
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


  /* ─── логотип в сайдбаре: подставьте свой путь ───── */
  logoUrl: "/img/logo.png",
};
