/* Приложение: состояние, рендер, стриминг, листы. */
(() => {
const tg = window.Telegram?.WebApp;
const $ = id => document.getElementById(id);

const state = {
  user: null,
  plan: "free",
  models: [],
  pro: { price_rub: 150, days: 30, energy: 1000, features: [] },
  modelPath: null,
  chats: [],
  chatId: null,
  messages: [],
  pending: [],      // {localId, kind, name, file, url, id|null, uploading}
  busy: false,
  sidebar: false,
  abort: null,
  maintenance: null,
};

const ICON_DOC = `<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M5 2.5h5l3 3v10H5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M10 2.5v3h3" stroke="currentColor" stroke-width="1.4"/></svg>`;
const ICON_UP = `<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 15.5V4.5m0 0L5 9.5M10 4.5l5 5" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICON_STOP = `<svg width="16" height="16" viewBox="0 0 16 16"><rect x="3" y="3" width="10" height="10" rx="2.6" fill="currentColor"/></svg>`;
const ICON_CHECK = `<svg width="19" height="19" viewBox="0 0 18 18" fill="none"><path d="M4 9.4l3.2 3.1L14 5.8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICON_TRASH = `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 5h10M6.5 5V3.5h3V5M4.8 5l.7 8h5l.7-8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICON_WARN = `<svg width="19" height="19" viewBox="0 0 20 20" fill="none" style="flex:none;margin-top:2px"><path d="M10 3.5l7 13H3l7-13zM10 8.5v4M10 14.4v.2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

const FALLBACK_AVATAR = "data:image/svg+xml;utf8," + encodeURIComponent(
  `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
   <rect width='64' height='64' fill='#140a22'/>
   <circle cx='19' cy='21' r='15' fill='#7b2ff7' opacity='.85'/>
   <circle cx='45' cy='29' r='17' fill='#2f7bff' opacity='.75'/>
   <circle cx='28' cy='49' r='14' fill='#ff2fb3' opacity='.6'/>
   <circle cx='50' cy='53' r='11' fill='#00e0d0' opacity='.5'/></svg>`);

/* ===================== утилиты ===================== */
const esc = window.MD.esc;
const model = () => state.models.find(m => m.path === state.modelPath) || state.models[0] || null;
const chat = () => state.chats.find(c => c.id === state.chatId) || null;
const isPro = () => state.plan === "pro";
const locked = m => !!m && m.locked;

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

/* ===================== рендер шапки ===================== */
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

/* ===================== рендер сообщений ===================== */
function attachmentHTML(a) {
  if (a.kind === "image") {
    return `<img class="ph" data-file="${esc(a.id || "")}" src="${a.url || ""}" alt="${esc(a.name || "")}">`;
  }
  return `<div class="chip">${ICON_DOC}<span>${esc(a.name || "файл")}</span></div>`;
}

function messageHTML(m) {
  if (m.role === "user") {
    const atts = (m.atts || []).map(attachmentHTML).join("");
    return `<div class="msg user" data-id="${m.id || ""}"><div class="col">
      ${atts ? `<div class="atts">${atts}</div>` : ""}
      ${m.content ? `<div class="bubble">${esc(m.content)}</div>` : ""}</div></div>`;
  }
  return `<div class="msg assistant" data-id="${m.id || ""}"><div class="body">
    ${m.reasoning ? thinkHTML(m.reasoning, false) : ""}
    ${window.MD.render(m.content || "")}
    ${citesHTML(m.citations)}</div></div>`;
}

function thinkHTML(text, open) {
  return `<details class="think"${open ? " open" : ""}>
    <summary>🧩 Размышления модели</summary>
    <div class="txt">${esc(text)}</div></details>`;
}

function citesHTML(items) {
  if (!items || !items.length) return "";
  const rows = items.slice(0, 10).map((c, i) =>
    `<a href="${esc(c.url)}" target="_blank" rel="noopener">
       <span class="n">${i + 1}.</span><span class="t">${esc(c.title || c.url)}</span></a>`).join("");
  return `<div class="cites">${rows}</div>`;
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

function renderChat(force) {
  const box = $("scroll");
  if (!state.messages.length) {
    const m = model();
    box.innerHTML = `<div class="empty"><div>
      <h1>blrd ai</h1>
      <p>Спроси что угодно${m ? `. Модель: ${esc(m.name)}` : ""}</p>
      <div class="sugg">
        <button data-q="Объясни простыми словами, как работают нейросети">Объясни просто</button>
        <button data-q="Напиши функцию на Python и объясни её">Код на Python</button>
        <button data-q="Составь план на неделю по пунктам">Составь план</button>
      </div></div></div>`;
    box.querySelectorAll(".sugg button").forEach(b => b.onclick = () => {
      $("ta").value = b.dataset.q;
      syncSend();
      send();
    });
    return;
  }
  box.innerHTML = state.messages.map(messageHTML).join("");
  hydrateImages(box);
  toBottom(force);
}

function renderChats() {
  $("chats").innerHTML = state.chats.map(c => `
    <button class="chat-item ${c.id === state.chatId ? "active" : ""}" data-haptic="off" data-id="${c.id}">
      <span class="t">${esc(c.title)}</span>
      <span class="del" data-del="${c.id}">${ICON_TRASH}</span>
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

function renderPending() {
  const box = $("pending");
  box.hidden = !state.pending.length;
  box.innerHTML = state.pending.map((a, i) => {
    const inner = a.kind === "image"
      ? `<img src="${a.url || ""}" alt="">`
      : `<div class="chip">${ICON_DOC}<span>${esc(a.name)}</span></div>`;
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

/* ===================== сайдбар ===================== */
function openSidebar() { state.sidebar = true; $("sidebar").classList.add("open"); $("scrim").classList.add("show"); }
function closeSidebar() { state.sidebar = false; $("sidebar").classList.remove("open"); $("scrim").classList.remove("show"); }
$("burger").onclick = openSidebar;
$("close-sb").onclick = closeSidebar;
$("scrim").onclick = () => { window.Haptic.tap(); closeSidebar(); };

/* ===================== листы ===================== */
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
    const right = lk ? `<span class="tag">PRO</span>` : (m.path === state.modelPath ? ICON_CHECK : "");
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
      if (!state.messages.length) renderChat(true);
      toast(`Модель: ${m.name}`);
      try {
        await window.API.selectModel(m.path);
        if (state.chatId) await window.API.patchChat(state.chatId, { model: m.path });
      } catch (e) { /* выбор модели не критичен: уйдёт с запросом */ }
    };
  });
}
$("pill").onclick = () => ($("layer").querySelector(".sheet") ? closeSheet() : modelSheet());

function paywall(reason) {
  const pro = state.pro;
  const feats = (pro.features || []).map(f => `<li>${ICON_CHECK}<span>${esc(f)}</span></li>`).join("");
  const el = sheet(`<div class="handle"></div>
    <div class="paywall">
      ${reason ? `<div class="msg-error" style="margin-bottom:16px">${ICON_WARN}<div>${esc(reason)}</div></div>` : ""}
      <h2>blrd ai Pro</h2>
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
      openPayLink(url);
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

function openPayLink(url) {
  if (tg?.openLink) tg.openLink(url, { try_instant_view: false });
  else window.open(url, "_blank", "noopener");
}

/* Пока окно оплаты открыто, опрашиваем статус: колбэк может прийти позже. */
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
    } catch (e) { /* молча: пользователь ещё платит */ }
    if (tries > 100) clearInterval(timer);  // ~5 минут
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

/* ===================== данные ===================== */
function applyUser(user) {
  state.user = user;
  state.plan = user.plan;
  if (!state.modelPath) state.modelPath = user.model;
  renderHeader();
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
$("new-side").onclick = newChat;

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

/* ===================== вложения ===================== */
function clearPending() {
  state.pending.forEach(a => a.url && URL.revokeObjectURL(a.url));
  state.pending = [];
  renderPending();
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

/* ===================== отправка ===================== */
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
  b.innerHTML = mode === "send" ? ICON_UP : ICON_STOP;
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
  const chatId = state.chatId;
  const sentAtts = atts.map(a => ({ id: a.id, kind: a.kind, name: a.name, url: a.url }));

  state.messages.push({ role: "user", content: text, atts: sentAtts });
  ta.value = "";
  ta.style.height = "auto";
  state.pending = state.pending.filter(a => !a.id);
  renderPending();
  state.busy = true;
  setSendMode("stop");
  syncSend();
  stick = true;
  renderChat(true);

  /* контейнер ответа: фаза → размышления → текст */
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  wrap.innerHTML = `<div class="body"><div class="phase">
    <span class="dots"><i></i><i></i><i></i></span><span class="lbl">подключаюсь</span></div></div>`;
  $("scroll").appendChild(wrap);
  toBottom(true);

  const acc = { text: "", think: "", cites: [], phase: "connecting" };
  let raf = 0;

  const paint = () => {
    raf = 0;
    const body = wrap.querySelector(".body");
    const phaseHTML = acc.text
      ? ""
      : `<div class="phase"><span class="dots"><i></i><i></i><i></i></span>
         <span class="lbl">${esc(acc.label || "думает")}</span></div>`;
    const thinkHtml = acc.think ? thinkHTML(acc.think, !acc.text) : "";
    const textHtml = acc.text
      ? window.MD.renderPartial(acc.text) + `<span class="caret"></span>`
      : "";
    body.innerHTML = phaseHTML + thinkHtml + textHtml;
    toBottom();
  };
  const schedule = () => { if (!raf) raf = requestAnimationFrame(paint); };

  const controller = new AbortController();
  state.abort = controller;
  let doneEvent = null;
  let errorEvent = null;

  try {
    await window.API.stream(chatId, {
      text,
      model: m.path,
      attachments: atts.map(a => ({ id: a.id, kind: a.kind, name: a.name })),
    }, ev => {
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
    }, controller.signal);
  } catch (e) {
    if (e.name === "AbortError") {
      errorEvent = null;  // прерывание пользователем: написанное сохранено на сервере
    } else {
      errorEvent = { message: e.message || "Сбой соединения", code: "network" };
    }
  } finally {
    state.abort = null;
    state.busy = false;
    setSendMode("send");
    syncSend();
    if (raf) cancelAnimationFrame(raf);
  }

  /* финальная отрисовка */
  const cites = acc.cites.length ? acc.cites : (doneEvent?.citations || []);
  const body = wrap.querySelector(".body");

  if (errorEvent && !acc.text) {
    wrap.remove();
    showError(errorEvent);
  } else {
    body.innerHTML = (acc.think ? thinkHTML(acc.think, false) : "")
      + window.MD.render(acc.text)
      + citesHTML(cites);
    hydrateImages(body);
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

function showError(ev) {
  const needPro = ev.code === "need_pro" || ev.code === "no_energy";
  const el = document.createElement("div");
  el.className = "msg assistant";
  el.innerHTML = `<div class="msg-error">${ICON_WARN}<div>${esc(ev.message)}
    ${needPro ? `<button data-up>Открыть Pro →</button>` : ""}</div></div>`;
  $("scroll").appendChild(el);
  el.querySelector("[data-up]")?.addEventListener("click", () => paywall(ev.message));
  window.Haptic.err();
  toBottom(true);
}

/* ===================== старт ===================== */
function setupTelegram() {
  if (!tg) return;
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.("#000000");
  tg.setBackgroundColor?.("#000000");
  tg.disableVerticalSwipes?.();
  tg.onEvent?.("viewportChanged", () => toBottom());
}

function maintenanceScreen(message) {
  boot(`<h1>Технические работы</h1><p>${esc(message || "Скоро вернёмся.")}</p>
    <button class="cta" onclick="location.reload()">Обновить</button>`);
}

function authErrorScreen(e) {
  const inTelegram = !!tg?.initData;
  const text = inTelegram
    ? (e.message || "Не удалось войти")
    : "Откройте приложение через бота в Telegram.\nДля локальной проверки задайте DEV_AUTH_ID в .env";
  boot(`<h1>Вход не выполнен</h1><p>${esc(text)}</p>
    <button class="cta" onclick="location.reload()">Повторить</button>`);
}

async function start() {
  setupTelegram();
  setSendMode("send");
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
  state.maintenance = data.maintenance;
  if (data.maintenance?.enabled && !data.user.is_admin) {
    maintenanceScreen(data.maintenance.message);
    return;
  }

  try {
    await loadModels();
    await loadChats();
  } catch (e) {
    boot(`<h1>Сервер недоступен</h1><p>${esc(e.message || "")}</p>
      <button class="cta" onclick="location.reload()">Повторить</button>`);
    return;
  }

  if (state.chats.length) await openChat(state.chats[0].id, { silent: true });
  else await newChat();

  boot("", false);
}

document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if ($("layer").innerHTML) closeSheet();
  else if (state.sidebar) closeSidebar();
});

/* возврат из окна оплаты — перепроверяем тариф */
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

start();
})();
