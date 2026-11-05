/* =========================================================
   БЕЛЕБАЛАРДЫХ AI — Mini App
   ========================================================= */
(() => {
const tg = window.Telegram?.WebApp;
const $ = id => document.getElementById(id);
const I = window.ICONS;

const REASON_OPEN_WHILE_STREAM = true;   // рассуждения видны сразу, без нажатия

const state = {
  user: null,
  plan: "free",
  models: [],
  pro: { price_rub: 150, days: 30, energy: 1000, features: [] },
  cfg: { bot_username: "", support_url: "", share_text: "" },
  modelPath: null,
  chats: [],
  chatId: null,
  messages: [],
  pending: [],
  busy: false,
  sidebar: false,
  abort: null,
  homeScreen: "unsupported",
};

/* =====================================================
   Telegram: совместимость, fullscreen, отступы
   ===================================================== */

/* Старые клиенты объявляют метод, но бросают WebAppMethodUnsupported
   при вызове — поэтому любой вызов идёт через эту обёртку. */
function tgCall(fn, ...args) {
  if (typeof fn !== "function") return undefined;
  try {
    return fn.apply(tg, args);
  } catch (e) {
    return undefined;
  }
}

const tgAtLeast = v => {
  try { return !!tg?.isVersionAtLeast?.(v); } catch (e) { return false; }
};

function applyInsets() {
  const root = document.documentElement;
  const safe = tg?.safeAreaInset || { top: 0, bottom: 0, left: 0, right: 0 };
  const content = tg?.contentSafeAreaInset || { top: 0, bottom: 0, left: 0, right: 0 };

  /* top: вырез экрана + полоса с кнопками «Закрыть» и «…» */
  const top = (safe.top || 0) + (content.top || 0);
  const bottom = (safe.bottom || 0) + (content.bottom || 0);
  const side = Math.max(safe.left || 0, safe.right || 0, content.left || 0, content.right || 0);

  root.style.setProperty("--tg-top", `${top}px`);
  root.style.setProperty("--tg-bottom", `${bottom}px`);
  root.style.setProperty("--tg-side", `${side}px`);

  const h = $("header")?.offsetHeight;
  if (h) root.style.setProperty("--head-h", `${h - top}px`);
}

function setupTelegram() {
  if (!tg) { applyInsets(); return; }

  tgCall(tg.ready);
  tgCall(tg.expand);
  tgCall(tg.setHeaderColor, "#000000");
  tgCall(tg.setBackgroundColor, "#000000");
  tgCall(tg.disableVerticalSwipes);

  /* Fullscreen — Bot API 8.0 и только телефоны */
  if (tgAtLeast("8.0") && ["android", "ios"].includes(tg.platform) && !tg.isFullscreen) {
    tgCall(tg.requestFullscreen);
  }

  for (const ev of ["safeAreaChanged", "contentSafeAreaChanged", "fullscreenChanged", "viewportChanged"]) {
    tgCall(tg.onEvent, ev, () => { applyInsets(); toBottom(); });
  }

  /* Добавление на домашний экран — Bot API 8.0 */
  if (tgAtLeast("8.0")) {
    tgCall(tg.checkHomeScreenStatus, status => {
      state.homeScreen = status || "unknown";
      renderSidebarActions();
    });
  } else {
    state.homeScreen = "unsupported";
  }

  applyInsets();
  setTimeout(applyInsets, 400);   // iOS сообщает отступы с задержкой
}

/* =====================================================
   Иконки в статической разметке
   ===================================================== */
function mountIcons() {
  $("burger").innerHTML = I.menu;
  $("new-top").innerHTML = I.newChat;
  $("close-sb").innerHTML = I.close;
  $("pill-chev").innerHTML = I.chevron;
  $("attach").innerHTML = I.attach;

  const logo = $("sb-logo");
  if (I.logoUrl) {
    logo.src = I.logoUrl;
    logo.onerror = () => { logo.hidden = true; };
  } else {
    logo.hidden = true;
  }
}

/* =====================================================
   Утилиты
   ===================================================== */
const esc = window.MD.esc;
const model = () => state.models.find(m => m.path === state.modelPath) || state.models[0] || null;
const isPro = () => state.plan === "pro";
const locked = m => !!m && m.locked;

const FALLBACK_AVATAR = "data:image/svg+xml;utf8," + encodeURIComponent(
  `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
   <rect width='64' height='64' fill='#140a22'/>
   <circle cx='19' cy='21' r='15' fill='#7b2ff7' opacity='.85'/>
   <circle cx='45' cy='29' r='17' fill='#2f7bff' opacity='.75'/>
   <circle cx='28' cy='49' r='14' fill='#ff2fb3' opacity='.6'/>
   <circle cx='50' cy='53' r='11' fill='#00e0d0' opacity='.5'/></svg>`);

function toast(text) {
  $("frame").querySelectorAll(".toast").forEach(t => t.remove());
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  $("frame").appendChild(el);
  setTimeout(() => el.remove(), 2800);
}
window.toast = toast;

let stick = true;
$("scroll").addEventListener("scroll", () => {
  const el = $("scroll");
  stick = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
});
const toBottom = force => { if (force || stick) $("scroll").scrollTop = $("scroll").scrollHeight; };

function boot(html, show = true) {
  const b = $("boot");
  if (!show) { b.classList.add("hide"); return; }
  b.classList.remove("hide");
  b.querySelector(".boot-inner").innerHTML = html;
}

async function copyText(text) {
  // Пробуем современный API
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) { console.warn("clipboard writeText failed:", e); }
  }
  // Запасной путь для старых браузеров и Telegram WebView
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0.01";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch (e) {
    console.warn("execCommand copy failed:", e);
    return false;
  }
}

/* =====================================================
   Шапка
   ===================================================== */
function renderHeader() {
  const m = model();
  $("pill-name").textContent = m ? m.short : "—";
  $("pill-plan").textContent = isPro() ? "Pro" : "Free";

  const u = state.user;
  if (!u) return;
  $("u-name").textContent = u.name;
  $("u-plan").textContent = `${isPro() ? "Pro" : "Free"} · ${u.energy} энергии`;

  const src = u.photo_url || FALLBACK_AVATAR;
  for (const id of ["av-top", "av-side"]) {
    const img = $(id).querySelector("img");
    if (img.dataset.src !== src) {
      img.dataset.src = src;
      img.src = src;
      img.onerror = () => { img.src = FALLBACK_AVATAR; };
    }
  }
}

/* =====================================================
   Сообщения
   ===================================================== */
function attachmentHTML(a) {
  if (a.kind === "image") {
    return `<img class="ph" data-file="${esc(a.id || "")}" src="${a.url || ""}" alt="${esc(a.name || "")}">`;
  }
  return `<div class="chip">${I.doc}<span>${esc(a.name || "файл")}</span></div>`;
}

function actsHTML(kind, idx) {
  const copy = `<button class="act" data-copy="${idx}" aria-label="Копировать" title="Копировать">${I.copy}</button>`;
  if (kind === "user") return `<div class="acts">${copy}</div>`;
  const retry = `<button class="act" data-retry="1" aria-label="Повторить" title="Перегенерировать">${I.retry}</button>`;
  return `<div class="acts">${copy}${retry}</div>`;
}

function reasonHTML(text, open) {
  if (!text) return "";
  return `<div class="reason ${open ? "open" : ""}">
    <button class="reason-head" data-reason-toggle>
      <span>Рассуждения</span>
      <span class="arw">${I.chevron}</span>
    </button>
    <div class="reason-box"><div class="reason-scroll">${esc(text)}</div></div>
  </div>`;
}

function citesHTML(items) {
  if (!items || !items.length) return "";
  const rows = items.slice(0, 3).map((c, i) =>
    `<a href="${esc(c.url)}" target="_blank" rel="noopener">
       <span class="n">${i + 1}.</span><span class="t">${esc(c.title || c.url)}</span></a>`).join("");
  return `<div class="cites"><div class="cites-title">Источники</div>${rows}</div>`;
}

function messageHTML(m, idx) {
  if (m.role === "user") {
    const atts = (m.atts || []).map(attachmentHTML).join("");
    return `<div class="msg user" data-idx="${idx}"><div class="col">
      ${atts ? `<div class="atts">${atts}</div>` : ""}
      ${m.content ? `<div class="bubble">${esc(m.content)}</div>` : ""}
      ${m.content ? actsHTML("user", idx) : ""}</div></div>`;
  }
  if (m.error) {
    return `<div class="msg assistant" data-idx="${idx}">
      <div class="msg-error">${I.warn}<div>${esc(m.content)}
        ${m.needPro ? `<button class="e-up" data-paywall>Открыть Pro →</button>` : ""}</div></div>
      ${actsHTML("assistant", idx)}</div>`;
  }
  return `<div class="msg assistant" data-idx="${idx}"><div class="body">
    ${reasonHTML(m.reasoning, false)}
    ${window.MD.render(m.content || "")}
    ${citesHTML(m.citations)}</div>
    ${actsHTML("assistant", idx)}</div>`;
}

async function hydrateImages(root) {
  for (const img of root.querySelectorAll("img[data-file]")) {
    const id = img.dataset.file;
    if (!id || img.src) continue;
    try {
      img.src = await window.API.fileUrl(id);
    } catch (e) {
      img.remove();
    }
  }
}

/* =====================================================
   Пустой экран
   ===================================================== */
const GREETINGS = [
  "Привет, {name}!",
  "О чём поболтаем?",
  "Чем помочь, {name}?",
  "Слушаю внимательно",
  "С чего начнём?",
  "Рад видеть, {name}",
  "Что обсудим сегодня?",
  "Готов к работе",
  "Какие планы, {name}?",
  "Спрашивай что угодно",
];

const HINTS = [
  "Объясни простыми словами",
  "Напиши код на Python",
  "Составь план на неделю",
  "Переведи текст",
  "Придумай название",
  "Разбери эту ошибку",
  "Сделай таблицу сравнения",
  "Сократи текст вдвое",
  "Напиши письмо вежливо",
  "Посчитай экономику",
  "Опиши фото",
  "Найди ошибки в тексте",
];



function renderChat(force) {
  const box = $("scroll");
  if (!state.messages.length) {
    box.innerHTML = emptyHTML();
    return;
  }
  box.innerHTML = state.messages.map(messageHTML).join("");
  hydrateImages(box);
  toBottom(force);
}

/* =====================================================
   Список чатов
   ===================================================== */
function renderChat(force) {
  const box = $("scroll");
  if (!state.messages.length) {
    box.innerHTML = emptyScreen();
    return;
  }
  box.innerHTML = state.messages.map(messageHTML).join("");
  hydrateImages(box);
  toBottom(force);
}

/* =====================================================
   Список чатов
   ===================================================== */
function renderChats() {
  $("chats").innerHTML = state.chats.map(c => `
    <button class="chat-item ${c.id === state.chatId ? "active" : ""}" data-haptic="off" data-id="${c.id}">
      <span class="t">${esc(c.title)}</span>
      <span class="del" data-del="${c.id}">${I.trash}</span>
    </button>`).join("") || `<div class="sb-label">Пока пусто</div>`;

  $("chats").querySelectorAll(".chat-item").forEach(el => {
    el.addEventListener("pointerdown", e => {
      e.target.closest("[data-del]") ? window.Haptic.press() : window.Haptic.select();
    });
    el.onclick = async e => {
      const del = e.target.closest("[data-del]");
      if (del) {
        e.stopPropagation();
        await removeChat(+del.dataset.del);
        return;
      }
      await openChat(+el.dataset.id);
    };
  });
}

/* =====================================================
   Сайдбар
   ===================================================== */
function renderSidebarActions() {
  const items = [
    { id: "new", icon: I.newChat, label: "Новый чат" },
    { id: "share", icon: I.share, label: "Поделиться ботом" },
    { id: "support", icon: I.support, label: "Поддержка" },
  ];

  /* кнопку показываем только там, где метод реально работает */
  const canHome = tgAtLeast("8.0")
    && (state.homeScreen === "missed" || state.homeScreen === "unknown");
  if (canHome) {
    items.push({ id: "home", icon: I.home, label: "Добавить на домашний экран" });
  }

  $("sb-acts").innerHTML = items.map(
    it => `<button class="sb-act" data-act="${it.id}">${it.icon}<span>${it.label}</span></button>`
  ).join("");

  $("sb-acts").querySelectorAll("[data-act]").forEach(b => {
    b.onclick = () => sidebarAction(b.dataset.act);
  });
}

async function sidebarAction(id) {
  if (id === "new") { await newChat(); return; }

  if (id === "share") {
    const uname = state.cfg.bot_username;
    if (!uname) { toast("Ссылка на бота не настроена"); return; }
    const url = `https://t.me/${uname}`;
    const text = state.cfg.share_text || "Все топовые нейросети в одном боте";
    const share = `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`;
    if (tgCall(tg?.openTelegramLink, share) === undefined) {
      window.open(share, "_blank", "noopener");
    }
    closeSidebar();
    return;
  }

  if (id === "support") {
    const url = state.cfg.support_url;
    if (!url) { toast("Поддержка пока не настроена"); return; }
    const opened = url.includes("t.me/")
      ? tgCall(tg?.openTelegramLink, url)
      : tgCall(tg?.openLink, url);
    if (opened === undefined) window.open(url, "_blank", "noopener");
    closeSidebar();
    return;
  }

  if (id === "home") {
    if (!tgAtLeast("8.0")) {
      toast("Обновите Telegram, чтобы добавить приложение на экран");
      return;
    }
    tgCall(tg.onEvent, "homeScreenAdded", () => {
      state.homeScreen = "added";
      renderSidebarActions();
      window.Haptic.ok();
      toast("Добавлено на домашний экран");
    });
    if (tgCall(tg.addToHomeScreen) === undefined) {
      toast("Это устройство не поддерживает такую установку");
    }
  }
}

function openSidebar() {
  state.sidebar = true;
  $("sidebar").classList.add("open");
  $("scrim").classList.add("show");
}
function closeSidebar() {
  state.sidebar = false;
  $("sidebar").classList.remove("open");
  $("scrim").classList.remove("show");
}
$("burger").onclick = openSidebar;
$("close-sb").onclick = closeSidebar;
$("scrim").onclick = () => { window.Haptic.tap(); closeSidebar(); };

/* =====================================================
   Листы
   ===================================================== */
function closeSheet() { $("layer").innerHTML = ""; $("pill").classList.remove("open"); }

function sheet(inner, { onClose } = {}) {
  $("layer").innerHTML = `<div class="sheet-wrap"><div class="sheet-bg" data-close></div>
    <div class="sheet">${inner}</div></div>`;
  $("layer").querySelector("[data-close]").onclick = () => {
    window.Haptic.tap();
    closeSheet();
    onClose?.();
  };
  return $("layer").querySelector(".sheet");
}

function modelSheet() {
  $("pill").classList.add("open");
  const rows = state.models.map(m => {
    const lk = locked(m);
    const bits = [m.multiplier === 0 ? "бесплатно" : `×${m.multiplier} энергии`];
    if (m.vision) bits.push("видит картинки");
    if (m.web_search) bits.push("ищет в интернете");
    const right = lk ? `<span class="tag">PRO</span>` : (m.path === state.modelPath ? I.check : "");
    return `<button class="m-row ${m.path === state.modelPath ? "sel" : ""} ${lk ? "locked" : ""}"
      data-haptic="off" data-p="${esc(m.path)}">
      <div class="meta"><div class="nm">${esc(m.name)}</div><div class="sub">${bits.join(" · ")}</div></div>
      ${right}</button>`;
  }).join("");

  const el = sheet(`<div class="handle"></div><h3>Модель</h3>${rows}
    <div class="energy">Баланс: ${state.user.energy} из ${state.user.energy_max} энергии</div>`);

  el.querySelectorAll(".m-row").forEach(row => {
    const m = state.models.find(x => x.path === row.dataset.p);
    row.addEventListener("pointerdown", () => locked(m) ? window.Haptic.err() : window.Haptic.select());
    row.onclick = async () => {
      if (locked(m)) { closeSheet(); paywall(); return; }
      state.modelPath = m.path;
      closeSheet();
      renderHeader();
      toast(`Модель: ${m.name}`);
      try {
        await window.API.selectModel(m.path);
        if (state.chatId) await window.API.patchChat(state.chatId, { model: m.path });
      } catch (e) { /* уйдёт вместе с запросом */ }
    };
  });
}
$("pill").onclick = () => ($("layer").querySelector(".sheet") ? closeSheet() : modelSheet());

function paywall(reason) {
  const pro = state.pro;
  const feats = (pro.features || []).map(f => `<li>${I.check}<span>${esc(f)}</span></li>`).join("");
  const el = sheet(`<div class="handle"></div>
    <div class="paywall">
      ${reason ? `<div class="msg-error" style="margin-bottom:16px">${I.warn}<div>${esc(reason)}</div></div>` : ""}
      <h2>БЕЛЕБАЛАРДЫХ Pro</h2>
      <div class="price">${pro.price_rub} ₽</div>
      <div class="per">за ${pro.days} дней, без автосписаний</div>
      <ul>${feats}</ul>
      <button class="cta" data-pay>Оформить Pro</button>
      <div class="promo">
        <input id="promo" placeholder="Промокод" autocapitalize="characters" autocomplete="off" />
        <button class="cta ghost" data-promo>Применить</button>
      </div>
      <div class="hint">Оплата через Platega. Сейчас: ${isPro() ? "Pro" : "Free"} · ${state.user.energy} энергии</div>
    </div>`);

  el.querySelector("[data-pay]").onclick = async e => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "Создаём платёж…";
    try {
      const { payment_id, url } = await window.API.createPayment();
      window.Haptic.rigid();
      if (tgCall(tg?.openLink, url, { try_instant_view: false }) === undefined) {
        window.open(url, "_blank", "noopener");
      }
      watchPayment(payment_id);
      btn.textContent = "Открыли страницу оплаты";
    } catch (err) {
      window.Haptic.err();
      btn.disabled = false;
      btn.textContent = "Оформить Pro";
      toast(err.message || "Не удалось создать платёж");
    }
  };

  const input = el.querySelector("#promo");
  input.oninput = e => (e.target.value = e.target.value.toUpperCase());
  el.querySelector("[data-promo]").onclick = async () => {
    const code = input.value.trim();
    if (!code) { window.Haptic.err(); toast("Введите промокод"); return; }
    try {
      const res = await window.API.redeemPromo(code);
      applyUser(res.user);
      await loadModels();
      window.Haptic.ok();
      closeSheet();
      toast(res.message);
    } catch (e) {
      window.Haptic.err();
      toast(e.message || "Промокод не найден");
    }
  };
}

function watchPayment(id) {
  let tries = 0;
  const timer = setInterval(async () => {
    tries++;
    try {
      const res = await window.API.paymentStatus(id);
      if (res.applied) {
        clearInterval(timer);
        applyUser(res.user);
        await loadModels();
        window.Haptic.ok();
        closeSheet();
        toast("Pro активирован");
        return;
      }
    } catch (e) { /* платёж ещё идёт */ }
    if (tries > 100) clearInterval(timer);
  }, 3000);
}

async function profileSheet() {
  const u = state.user;
  const pct = Math.max(2, Math.min(100, Math.round(u.energy / (u.energy_max || 1) * 100)));
  const until = u.plan_until ? new Date(u.plan_until).toLocaleDateString("ru-RU") : null;
  const el = sheet(`<div class="handle"></div>
    <div class="prof">
      <div class="avatar"><img src="${esc(u.photo_url || FALLBACK_AVATAR)}" alt=""></div>
      <div><div class="nm">${esc(u.name)}</div>
        <div class="sub">${isPro() ? "Pro" : "Free"}${until ? ` до ${until}` : ""}</div></div>
    </div>
    <div class="bar"><i style="width:${pct}%"></i></div>
    <div class="energy">${u.energy} из ${u.energy_max} энергии</div>
    <div class="rows" id="stats"><div class="row"><span>Загружаем статистику…</span><span></span></div></div>
    ${isPro() ? "" : `<button class="cta" data-up>Открыть все модели — ${state.pro.price_rub} ₽</button>`}`);

  el.querySelector("[data-up]")?.addEventListener("click", () => { closeSheet(); paywall(); });

  try {
    const u2 = await window.API.usage();
    el.querySelector("#stats").innerHTML = `
      <div class="row"><span>Запросов</span><span>${u2.requests}</span></div>
      <div class="row"><span>Сообщений</span><span>${u2.messages}</span></div>
      <div class="row"><span>Потрачено энергии</span><span>${u2.spent_energy}</span></div>`;
  } catch (e) {
    el.querySelector("#stats").innerHTML = `<div class="row"><span>Статистика недоступна</span><span></span></div>`;
  }
}
$("sb-foot").onclick = () => { closeSidebar(); profileSheet(); };

/* =====================================================
   Данные
   ===================================================== */
function applyUser(user) {
  state.user = user;
  state.plan = user.plan;
  if (!state.modelPath) state.modelPath = user.model;
  renderHeader();
}

async function loadConfig() {
  try {
    state.cfg = await window.API.config();
  } catch (e) { /* ссылки просто не покажутся */ }
  renderSidebarActions();
}

/* Пустой экран нового чата. Стили инлайн: вёрстка не зависит
   от того, какая версия ui.css сейчас в кеше WebView. */
/* Пустой экран нового чата. Своя разметка и свои классы (.es-*),
   чтобы правила .empty из app.css на него не действовали. */
function emptyScreen() {
  const name = (state.user?.name || "").split(" ")[0] || "друг";
  const phrase = (GREETINGS[Math.floor(Math.random() * GREETINGS.length)]
    || "О чём поболтаем?").replace("{name}", name);
  const m = model();
  const energy = state.user?.energy ?? 0;
  const max = state.user?.energy_max ?? 0;

  const half = Math.ceil(HINTS.length / 2);
  const chips = list => [...list, ...list]
    .map(t => `<span class="mq-chip">${esc(t)}</span>`).join("");

  const edge = side =>
    `position:absolute;top:0;bottom:0;${side}:0;width:88px;z-index:3;pointer-events:none;`
    + `background:linear-gradient(${side === "left" ? "90deg" : "270deg"},`
    + `#000 0%,rgba(0,0,0,.92) 40%,rgba(0,0,0,0) 100%)`;

  return `<div class="es-wrap">
    <div class="es-title">${esc(phrase)}</div>
    <div class="es-sub">Модель: <b>${esc(m ? m.name : "—")}</b> · ${energy} из ${max} энергии</div>
    <div class="marquee" style="position:relative;margin-top:24px;overflow:hidden;
         pointer-events:none;-webkit-mask-image:none;mask-image:none">
      <div style="${edge("left")}"></div>
      <div style="${edge("right")}"></div>
      <div class="mq-row a">${chips(HINTS.slice(0, half))}</div>
      <div class="mq-row b">${chips(HINTS.slice(half))}</div>
    </div>
  </div>`;
}




async function loadModels() {
  const data = await window.API.models();
  state.models = data.models;
  state.pro = data.pro;
  state.plan = data.plan;
  if (state.user) {
    state.user.energy = data.energy;
    state.user.energy_max = data.energy_max;
  }
  const current = state.models.find(m => m.path === (state.modelPath || data.current));
  state.modelPath = current && !current.locked
    ? current.path
    : (state.models.find(m => !m.locked)?.path || data.current);
  renderHeader();
}

async function loadChats() {
  const data = await window.API.chats();
  state.chats = data.chats;
  renderChats();
}

async function openChat(id, { silent = false } = {}) {
  try {
    const data = await window.API.chat(id);
    state.chatId = data.id;
    state.messages = data.messages;
    if (data.model) {
      const m = state.models.find(x => x.path === data.model);
      if (m && !m.locked) state.modelPath = m.path;
    }
  } catch (e) {
    toast("Не удалось открыть чат");
    return;
  }
  if (!silent) closeSidebar();
  renderHeader();
  renderChats();
  renderChat(true);
}

async function newChat() {
  if (state.busy) stopStream();
  try {
    const c = await window.API.createChat(state.modelPath);
    state.chats.unshift({ id: c.id, title: c.title, model: c.model });
    state.chatId = c.id;
    state.messages = [];
  } catch (e) {
    toast("Сервер не отвечает");
    return;
  }
  clearPending();
  closeSidebar();
  renderChats();
  renderChat(true);
  syncSend();
}
$("new-top").onclick = newChat;

async function removeChat(id) {
  const wasActive = state.chatId === id;
  state.chats = state.chats.filter(c => c.id !== id);
  renderChats();
  window.Haptic.warn();
  toast("Чат удалён");
  try {
    await window.API.deleteChat(id);
  } catch (e) {
    toast("Не удалось удалить на сервере");
  }
  if (wasActive) {
    const next = state.chats[0];
    if (next) await openChat(next.id, { silent: true });
    else await newChat();
  }
}

/* =====================================================
   Вложения
   ===================================================== */
function clearPending() {
  state.pending.forEach(a => a.url && URL.revokeObjectURL(a.url));
  state.pending = [];
  renderPending();
}

function renderPending() {
  const box = $("pending");
  box.hidden = !state.pending.length;
  box.innerHTML = state.pending.map((a, i) => {
    const inner = a.kind === "image"
      ? `<img src="${a.url || ""}" alt="">`
      : `<div class="chip">${I.doc}<span>${esc(a.name)}</span></div>`;
    return `<div class="th ${a.uploading ? "up" : ""}">${inner}
      <button class="rm" data-haptic="off" data-i="${i}" aria-label="Убрать">✕</button></div>`;
  }).join("");
  box.querySelectorAll(".rm").forEach(b => b.onclick = () => {
    window.Haptic.press();
    const [removed] = state.pending.splice(+b.dataset.i, 1);
    if (removed?.url) URL.revokeObjectURL(removed.url);
    renderPending();
    syncSend();
  });
}

$("attach").onclick = () => {
  if (!state.user) return;
  if ((state.user.max_attachments || 0) <= 0) {
    window.Haptic.err();
    paywall("Вложения доступны в Pro");
    return;
  }
  $("file-input").click();
};

$("file-input").onchange = async e => {
  const files = Array.from(e.target.files || []);
  e.target.value = "";
  const limit = state.user.max_attachments || 0;
  for (const file of files) {
    if (state.pending.length >= limit) {
      toast(`Не больше ${limit} вложений за раз`);
      break;
    }
    const kind = file.type.startsWith("image/") ? "image" : "doc";
    const item = {
      localId: Math.random().toString(36).slice(2),
      kind,
      name: file.name,
      url: kind === "image" ? URL.createObjectURL(file) : "",
      id: null,
      uploading: true,
    };
    state.pending.push(item);
    renderPending();
    syncSend();

    try {
      const res = await window.API.upload(file);
      item.id = res.id;
      item.kind = res.kind;
      item.uploading = false;
    } catch (err) {
      state.pending = state.pending.filter(x => x.localId !== item.localId);
      if (item.url) URL.revokeObjectURL(item.url);
      window.Haptic.err();
      toast(err.message || `Не удалось загрузить ${file.name}`);
    }
    renderPending();
    syncSend();
  }
};

/* =====================================================
   Композер
   ===================================================== */
const ta = $("ta");

function syncSend() {
  const b = $("send");
  if (state.busy) { b.disabled = false; return; }
  const uploading = state.pending.some(a => a.uploading);
  b.disabled = uploading || !(ta.value.trim() || state.pending.some(a => a.id));
}

function setSendMode(mode) {
  const b = $("send");
  b.classList.toggle("send", mode === "send");
  b.innerHTML = mode === "send" ? I.send : I.stop;
  b.setAttribute("aria-label", mode === "send" ? "Отправить" : "Остановить");
}

$("send").onclick = () => (state.busy ? stopStream() : send());

ta.addEventListener("input", () => {
  const before = ta.style.height;
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 132) + "px";
  if (before && before !== ta.style.height) window.Haptic.soft();
  syncSend();
});
ta.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && window.innerWidth > 900) {
    e.preventDefault();
    send();
  }
});

function stopStream() {
  if (state.abort) {
    state.abort.abort();
    window.Haptic.warn();
  }
}

/* =====================================================
   Отправка и стрим
   ===================================================== */
async function send() {
  const text = ta.value.trim();
  const atts = state.pending.filter(a => a.id);
  if ((!text && !atts.length) || state.busy) return;
  if (state.pending.some(a => a.uploading)) { toast("Файлы ещё загружаются"); return; }

  const m = model();
  if (!m) { toast("Модель не выбрана"); return; }
  if (m.multiplier > 0 && state.user.energy < 1) {
    window.Haptic.err();
    paywall("Закончилась энергия");
    return;
  }

  if (!state.chatId) {
    await newChat();
    if (!state.chatId) return;
  }

  window.Haptic.press();
  const sentAtts = atts.map(a => ({ id: a.id, kind: a.kind, name: a.name, url: a.url }));

  state.messages.push({ role: "user", content: text, atts: sentAtts });
  ta.value = "";
  ta.style.height = "auto";
  state.pending = state.pending.filter(a => !a.id);
  renderPending();
  stick = true;
  renderChat(true);

  await runStream(state.chatId, {
    text,
    model: m.path,
    attachments: atts.map(a => ({ id: a.id, kind: a.kind, name: a.name })),
  });
}

async function regenerate() {
  if (state.busy || !state.chatId) return;

  /* последнее сообщение ассистента (включая ошибку) убираем из вида */
  for (let i = state.messages.length - 1; i >= 0; i--) {
    if (state.messages[i].role === "assistant") { state.messages.splice(i, 1); break; }
  }
  stick = true;
  renderChat(true);
  window.Haptic.press();

  await runStream(state.chatId, { model: model()?.path }, { regenerate: true });
}

async function runStream(chatId, payload, { regenerate: isRetry = false } = {}) {
  state.busy = true;
  setSendMode("stop");
  syncSend();

  const wrap = document.createElement("div");
  wrap.className = "msg assistant streaming";
  wrap.innerHTML = `<div class="body"><div class="phase">
    <span class="lbl">подключаюсь</span></div></div>`;
  $("scroll").appendChild(wrap);
  toBottom(true);

  const acc = {
    text: "", think: "", cites: [],
    phase: "connecting", label: "подключаюсь",
    reasonOpen: REASON_OPEN_WHILE_STREAM,
  };
  let raf = 0;

  /* делегированный обработчик читает это, когда рассуждения
     свернули во время стрима: иначе следующий кадр вернёт их обратно */
  window.__accRef = acc;

    const paint = () => {
    raf = 0;
    const body = wrap.querySelector(".body");
    const prevScroll = body.querySelector(".reason-scroll");
    const wasBottom = prevScroll
      ? prevScroll.scrollHeight - prevScroll.scrollTop - prevScroll.clientHeight < 40
      : true;

    let html = "";

    /* пока нет ни текста, ни размышлений — только строка фазы */
    if (!acc.think && !acc.text) {
      html = `<div class="phase"><span class="lbl">${esc(acc.label)}</span></div>`;
    } else {
      if (acc.think) {
        /* заголовок блока сам показывает фазу, отдельной строки быть не должно */
        const head = acc.text ? "Рассуждения" : esc(acc.label);
        html += `<div class="reason ${acc.reasonOpen ? "open" : ""}">
          <button class="reason-head" data-reason-toggle>
            <span class="${acc.text ? "" : "lbl"}">${head}</span>
            <span class="arw">${I.chevron}</span>
          </button>
          <div class="reason-box"><div class="reason-scroll">${esc(acc.think)}</div></div>
        </div>`;
      }
      if (acc.text) {
        html += window.MD.renderPartial(acc.text) + `<span class="caret"></span>`;
      }
    }

    body.innerHTML = html;

    const box = body.querySelector(".reason-scroll");
    if (box && wasBottom) box.scrollTop = box.scrollHeight;
    toBottom();
  };

  const schedule = () => { if (!raf) raf = requestAnimationFrame(paint); };

  const controller = new AbortController();
  state.abort = controller;
  let doneEvent = null;
  let errorEvent = null;

  const onEvent = ev => {
    switch (ev.type) {
      case "phase":
        acc.phase = ev.phase;
        acc.label = ev.label;
        if (ev.phase === "typing") window.Haptic.soft();
        schedule();
        break;
      case "reasoning":
        acc.think += ev.text;
        schedule();
        break;
      case "delta":
        acc.text += ev.text;
        schedule();
        break;
      case "citations":
        acc.cites.push(...ev.items);
        break;
      case "meta":
        if (ev.title) {
          const c = state.chats.find(x => x.id === chatId);
          if (c) { c.title = ev.title; renderChats(); }
        }
        break;
      case "done":
        doneEvent = ev;
        break;
      case "error":
        errorEvent = ev;
        break;
    }
  };

  try {
    if (isRetry) await window.API.regenerate(chatId, payload, onEvent, controller.signal);
    else await window.API.stream(chatId, payload, onEvent, controller.signal);
  } catch (e) {
    if (e.name === "AbortError") errorEvent = null;
    else errorEvent = { message: e.message || "Сбой соединения", code: "network" };
  } finally {
    state.abort = null;
    state.busy = false;
    setSendMode("send");
    syncSend();
    if (raf) cancelAnimationFrame(raf);
    window.__accRef = null;
  }

  const cites = acc.cites.length ? acc.cites : (doneEvent?.citations || []);
  wrap.remove();

  if (errorEvent && !acc.text) {
    const needPro = errorEvent.code === "need_pro" || errorEvent.code === "no_energy";
    state.messages.push({
      role: "assistant", content: errorEvent.message,
      error: true, needPro,
    });
    window.Haptic.err();
  } else {
    state.messages.push({
      id: doneEvent?.message_id,
      role: "assistant",
      content: acc.text,
      reasoning: acc.think,
      citations: cites,
    });
    if (errorEvent) toast(errorEvent.message);
    else window.Haptic.ok();
  }

  renderChat(true);

  if (doneEvent) {
    state.user.energy = doneEvent.energy;
    renderHeader();
    if (doneEvent.title) {
      const c = state.chats.find(x => x.id === chatId);
      if (c) { c.title = doneEvent.title; renderChats(); }
    }
  } else {
    try {
      const res = await window.API.me();
      applyUser(res.user);
    } catch (e) {}
    if (controller.signal.aborted) await openChat(chatId, { silent: true });
  }
  toBottom();
}

/* =====================================================
   Делегированные обработчики
   ===================================================== */
document.addEventListener("click", async e => {
  /* развернуть/свернуть рассуждения */
  const rt = e.target.closest("[data-reason-toggle]");
  if (rt) {
    const block = rt.closest(".reason");
    block.classList.toggle("open");
    window.Haptic.select();
    const open = block.classList.contains("open");
    if (open) {
      const box = block.querySelector(".reason-scroll");
      if (box) box.scrollTop = box.scrollHeight;
    }
    /* во время стрима запоминаем выбор, иначе следующий кадр его сбросит */
    if (block.closest(".streaming") && window.__accRef) {
      window.__accRef.reasonOpen = open;
    }
    return;
  }

  /* копировать */
  const cp = e.target.closest("[data-copy]");
  if (cp) {
    const idx = +cp.dataset.copy;
    const msg = state.messages[idx];
    if (!msg) return;
    const ok = await copyText(msg.content || "");
    if (ok) {
      window.Haptic.ok();
      cp.classList.add("done");
      cp.innerHTML = I.check;
      setTimeout(() => { cp.classList.remove("done"); cp.innerHTML = I.copy; }, 1500);
    } else {
      window.Haptic.err();
      toast("Буфер недоступен");
    }
    return;
  }

  /* перегенерировать */
  if (e.target.closest("[data-retry]")) {
    await regenerate();
    return;
  }

  /* пейволл из ошибки */
  const pw = e.target.closest("[data-paywall]");
  if (pw) {
    const msg = state.messages[+pw.closest(".msg")?.dataset.idx];
    paywall(msg?.content);
  }
});

document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if ($("layer").innerHTML) closeSheet();
  else if (state.sidebar) closeSidebar();
});

document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState !== "visible" || !state.user) return;
  try {
    const res = await window.API.me();
    const wasPro = isPro();
    applyUser(res.user);
    if (!wasPro && isPro()) {
      await loadModels();
      window.Haptic.ok();
      toast("Pro активирован");
      closeSheet();
    }
  } catch (e) {}
});

window.addEventListener("resize", applyInsets);

/* =====================================================
   Старт
   ===================================================== */
function maintenanceScreen(message) {
  boot(`<h1>Технические работы</h1><p>${esc(message || "Скоро вернёмся.")}</p>
    <button class="cta" onclick="location.reload()">Обновить</button>`);
}

function authErrorScreen(e) {
  const inTelegram = !!tg?.initData;
  const reason = e?.message ? `<p>${esc(e.message)}</p>` : "";
  const hint = inTelegram
    ? ""
    : `<p>Откройте приложение через бота в Telegram.
         Для локальной проверки задайте DEV_AUTH_ID в .env и перезапустите сервер.</p>`;
  boot(`<h1>Вход не выполнен</h1>${reason}${hint}
    <button class="cta" onclick="location.reload()">Повторить</button>`);
  console.error("auth failed", e);
}

async function start() {
  mountIcons();

  /* несовместимость клиента Telegram не должна блокировать приложение */
  try {
    setupTelegram();
  } catch (e) {
    console.warn("Telegram init failed", e);
    applyInsets();
  }

  setSendMode("send");
  renderSidebarActions();
  renderPending();
  syncSend();

  let data;
  try {
    data = await window.API.auth();
  } catch (e) {
    authErrorScreen(e);
    return;
  }

  applyUser(data.user);
  if (data.maintenance?.enabled && !data.user.is_admin) {
    maintenanceScreen(data.maintenance.message);
    return;
  }

  try {
    await loadModels();
    await loadChats();
    await loadConfig();
  } catch (e) {
    boot(`<h1>Сервер недоступен</h1><p>${esc(e.message || "")}</p>
      <button class="cta" onclick="location.reload()">Повторить</button>`);
    return;
  }

  if (state.chats.length) await openChat(state.chats[0].id, { silent: true });
  else await newChat();

  applyInsets();
  boot("", false);
}

start();
})();
