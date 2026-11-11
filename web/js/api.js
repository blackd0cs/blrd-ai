/* Клиент API: сессия, REST, SSE-стрим, кеш картинок вложений. */
window.API = (() => {
  const KEY = "blrd.session";
  let token = localStorage.getItem(KEY) || "";

  class ApiError extends Error {
    constructor(message, status, code) {
      super(message);
      this.status = status;
      this.code = code || "";
    }
  }

  const headers = (extra = {}) => {
    const h = { ...extra };
    if (token) h["X-Session"] = token;
    return h;
  };

  async function req(path, { method = "GET", body, raw = false } = {}) {
    const opts = { method, headers: headers(), credentials: "same-origin" };
    if (body instanceof FormData) {
      opts.body = body;
    } else if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }

    let r;
    try {
      r = await fetch(path, opts);
    } catch (e) {
      throw new ApiError("Нет связи с сервером", 0, "network");
    }

    if (r.status === 401) {
      token = "";
      localStorage.removeItem(KEY);
      throw new ApiError("Сессия истекла", 401, "unauthorized");
    }
    if (!r.ok) {
      let detail = `Ошибка ${r.status}`;
      try {
        const data = await r.json();
        detail = data.detail || data.message || detail;
      } catch (e) {}
      throw new ApiError(detail, r.status);
    }
    if (raw) return r;
    return r.status === 204 ? null : r.json();
  }

  /* ── вход ───────────────────────────────────────────────── */
  async function auth() {
    const initData = window.Telegram?.WebApp?.initData || "";
    if (initData) {
      const data = await req("/api/auth/telegram", { method: "POST", body: { initData } });
      token = data.session;
      localStorage.setItem(KEY, token);
      return data;
    }
    if (token) {
      try {
        return await req("/api/me");
      } catch (e) {
        if (e.status !== 401) throw e;
      }
    }
    /* вне Telegram: локальная отладка, если включён DEV_AUTH_ID */
    const data = await req("/api/auth/dev", { method: "POST" });
    token = data.session;
    localStorage.setItem(KEY, token);
    return data;
  }

  /* ── вложения ───────────────────────────────────────────── */
  const blobCache = new Map();

  async function fileUrl(id) {
    if (blobCache.has(id)) return blobCache.get(id);
    const p = (async () => {
      const r = await req(`/api/files/${id}`, { raw: true });
      return URL.createObjectURL(await r.blob());
    })();
    blobCache.set(id, p);
    return p;
  }

  async function upload(file) {
    const fd = new FormData();
    fd.append("file", file, file.name);
    return req("/api/files", { method: "POST", body: fd });
  }

  /* ── SSE: общий разбор потока событий ───────────────────── */
  async function sse(url, payload, onEvent, signal) {
    const r = await fetch(url, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json", Accept: "text/event-stream" }),
      body: JSON.stringify(payload || {}),
      credentials: "same-origin",
      signal,
    });

    if (!r.ok) {
      let detail = `Ошибка ${r.status}`;
      try {
        const data = await r.json();
        detail = data.detail || detail;
      } catch (e) {}
      throw new ApiError(detail, r.status);
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let cut;
      while ((cut = buf.indexOf("\n\n")) !== -1) {
        const frame = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        for (const line of frame.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (!data || data === "[DONE]") continue;
          try {
            onEvent(JSON.parse(data));
          } catch (e) {
            console.warn("bad sse frame", data);
          }
        }
      }
    }
  }

  const stream = (chatId, payload, onEvent, signal) =>
    sse(`/api/chats/${chatId}/send`, payload, onEvent, signal);

  const regenerate = (chatId, payload, onEvent, signal) =>
    sse(`/api/chats/${chatId}/regenerate`, payload, onEvent, signal);

  return {
    ApiError,
    auth,
    me: () => req("/api/me"),
    config: () => req("/api/config"),
    models: () => req("/api/models"),
    selectModel: model => req("/api/models/select", { method: "POST", body: { model } }),
    chats: () => req("/api/chats"),
    chat: id => req(`/api/chats/${id}`),
    createChat: model => req("/api/chats", { method: "POST", body: { model } }),
    patchChat: (id, body) => req(`/api/chats/${id}`, { method: "PATCH", body }),
    deleteChat: id => req(`/api/chats/${id}`, { method: "DELETE" }),
    usage: () => req("/api/usage"),
    createPayment: () => req("/api/payments/create", { method: "POST" }),
    paymentStatus: id => req(`/api/payments/${id}`),
    redeemPromo: code => req("/api/promo/redeem", { method: "POST", body: { code } }),
    upload,
    fileUrl,
    stream,
    regenerate,
    get token() { return token; },
  };
})();
