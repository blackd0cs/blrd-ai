/* =========================================================
   mathtex.js — рендер подмножества LaTeX в HTML.
   Без внешних библиотек и CDN: работает в любом WebView
   Telegram, в том числе офлайн и в старых Android-клиентах.

   window.TeX.render(src, display) -> HTML
   window.TeX.scan(text)          -> [{s,e,body,display}]
   window.TeX.normalize(text)     -> text с восстановленными \[ \]
   ========================================================= */
window.TeX = (() => {
  const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  /* ── таблица символов ──────────────────────────────────── */
  const SYM = {
    /* греческий */
    alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", varepsilon: "ε",
    zeta: "ζ", eta: "η", theta: "θ", vartheta: "ϑ", iota: "ι", kappa: "κ",
    lambda: "λ", mu: "μ", nu: "ν", xi: "ξ", pi: "π", varpi: "ϖ", rho: "ρ",
    varrho: "ϱ", sigma: "σ", varsigma: "ς", tau: "τ", upsilon: "υ", phi: "φ",
    varphi: "φ", chi: "χ", psi: "ψ", omega: "ω",
    Gamma: "Γ", Delta: "Δ", Theta: "Θ", Lambda: "Λ", Xi: "Ξ", Pi: "Π",
    Sigma: "Σ", Upsilon: "Υ", Phi: "Φ", Psi: "Ψ", Omega: "Ω",

    /* операции */
    cdot: "·", cdots: "⋯", ldots: "…", dots: "…", vdots: "⋮", ddots: "⋱",
    times: "×", div: "÷", pm: "±", mp: "∓", ast: "∗", star: "⋆",
    circ: "∘", bullet: "∙", oplus: "⊕", ominus: "⊖", otimes: "⊗", odot: "⊙",
    setminus: "∖", amalg: "⨿", wedge: "∧", vee: "∨", land: "∧", lor: "∨",
    neg: "¬", lnot: "¬", oint: "∮",

    /* отношения */
    le: "⩽", leq: "⩽", ge: "⩾", geq: "⩾", ne: "≠", neq: "≠",
    ll: "≪", gg: "≫", equiv: "≡", sim: "∼", simeq: "≃", approx: "≈",
    cong: "≅", propto: "∝", asymp: "≍", doteq: "≐", lesssim: "≲", gtrsim: "≳",

    /* множества и логика */
    in: "∈", notin: "∉", ni: "∋", subset: "⊂", supset: "⊃",
    subseteq: "⊆", supseteq: "⊇", subsetneq: "⊊", cup: "∪", cap: "∩",
    bigcup: "⋃", bigcap: "⋂", emptyset: "∅", varnothing: "∅",
    forall: "∀", exists: "∃", nexists: "∄", therefore: "∴", because: "∵",
    mathbb: null, /* обрабатывается отдельно */

    /* стрелки */
    to: "→", rightarrow: "→", longrightarrow: "⟶", gets: "←", leftarrow: "←",
    longleftarrow: "⟵", leftrightarrow: "↔", longleftrightarrow: "⟷",
    Rightarrow: "⇒", Longrightarrow: "⟹", Leftarrow: "⇐", Longleftarrow: "⟸",
    Leftrightarrow: "⇔", Longleftrightarrow: "⟺", iff: "⇔", implies: "⟹",
    mapsto: "↦", uparrow: "↑", downarrow: "↓", updownarrow: "↕",
    nearrow: "↗", searrow: "↘", swarrow: "↙", nwarrow: "↖",

    /* геометрия */
    perp: "⊥", parallel: "∥", nparallel: "∦", angle: "∠", measuredangle: "∡",
    triangle: "△", square: "□", cong_: "≅", degree: "°", prime: "′",

    /* анализ */
    infty: "∞", partial: "∂", nabla: "∇", int: "∫", iint: "∬", iiint: "∭",
    sum: "∑", prod: "∏", coprod: "∐", surd: "√", Re: "ℜ", Im: "ℑ",
    aleph: "ℵ", hbar: "ℏ", ell: "ℓ", wp: "℘", imath: "ı", jmath: "ȷ",

    /* разное */
    dagger: "†", ddagger: "‡", S: "§", P: "¶", copyright: "©", pounds: "£",
    checkmark: "✓", bowtie: "⋈", models: "⊨", vdash: "⊢", dashv: "⊣",
    lbrace: "{", rbrace: "}", lbrack: "[", rbrack: "]",
    langle: "⟨", rangle: "⟩", lvert: "|", rvert: "|", lVert: "‖", rVert: "‖",
    vert: "|", Vert: "‖", backslash: "\\", colon: ":", quad: " ", qquad: "  ",
  };

  /* имена функций, которые ставятся прямым шрифтом */
  const FUNCS = new Set([
    "sin", "cos", "tan", "cot", "sec", "csc", "sinh", "cosh", "tanh", "coth",
    "arcsin", "arccos", "arctan", "arccot", "ctg", "tg", "arctg", "arcctg",
    "log", "ln", "lg", "exp", "det", "dim", "ker", "deg", "gcd", "lcm",
    "max", "min", "sup", "inf", "arg", "mod", "bmod", "pmod", "Pr", "hom",
  ]);

  /* крупные операторы: выше по размеру, пределы снизу/сверху */
  const BIG = { sum: "∑", prod: "∏", coprod: "∐", int: "∫", iint: "∬", iiint: "∭", oint: "∮", bigcup: "⋃", bigcap: "⋂" };
  const LIMLIKE = new Set(["lim", "limsup", "liminf", "sup", "inf", "max", "min"]);

  const SPACES = { ",": "0.17em", ":": "0.22em", ";": "0.28em", "!": "-0.17em", " ": "0.25em", enspace: "0.5em", thinspace: "0.17em" };

  const ACCENTS = {
    vec: "⟶", overrightarrow: "⟶", overleftarrow: "⟵", overline: "", bar: "¯",
    hat: "ˆ", widehat: "ˆ", tilde: "˜", widetilde: "˜", dot: "˙", ddot: "¨",
    check: "ˇ", breve: "˘", acute: "´", grave: "`", mathring: "˚",
  };

  const UPRIGHT = new Set(["text", "textrm", "textnormal", "mathrm", "operatorname", "mbox", "textsf", "mathsf"]);
  const BOLD = new Set(["textbf", "mathbf", "bf", "boldsymbol", "bm", "pmb"]);
  const ITAL = new Set(["textit", "mathit", "it", "emph"]);
  const MONO = new Set(["texttt", "mathtt", "tt"]);
  const BLACKBOARD = new Set(["mathbb", "Bbb"]);
  const SCRIPT = new Set(["mathcal", "mathscr", "mathfrak"]);

  const BB = { A: "𝔸", B: "𝔹", C: "ℂ", D: "𝔻", E: "𝔼", F: "𝔽", G: "𝔾", H: "ℍ", I: "𝕀", J: "𝕁", K: "𝕂", L: "𝕃", M: "𝕄", N: "ℕ", O: "𝕆", P: "ℙ", Q: "ℚ", R: "ℝ", S: "𝕊", T: "𝕋", U: "𝕌", V: "𝕍", W: "𝕎", X: "𝕏", Y: "𝕐", Z: "ℤ" };

  const DELIMS = { "(": "(", ")": ")", "[": "[", "]": "]", "|": "|", "/": "/", ".": "" };

  const ENVS = {
    pmatrix: ["(", ")"], bmatrix: ["[", "]"], Bmatrix: ["{", "}"],
    vmatrix: ["|", "|"], Vmatrix: ["‖", "‖"], matrix: ["", ""],
    cases: ["{", ""], array: ["", ""], smallmatrix: ["", ""],
    aligned: ["", ""], align: ["", ""], alignat: ["", ""], gathered: ["", ""],
    gather: ["", ""], split: ["", ""], equation: ["", ""], multline: ["", ""],
    subequations: ["", ""],
  };

  /* ── лексер ────────────────────────────────────────────── */
  function tokenize(src) {
    const out = [];
    let i = 0;
    const n = src.length;
    while (i < n) {
      const c = src[i];
      if (c === "\\") {
        const rest = src.slice(i);
        const m = /^\\([a-zA-Z]+)(\*?)/.exec(rest);
        if (m) {
          out.push({ t: "cmd", v: m[1] });
          i += m[0].length;
          continue;
        }
        const d = src[i + 1];
        if (d === "\\") { out.push({ t: "br" }); i += 2; continue; }
        if (d === undefined) { i += 1; continue; }
        if (d in SPACES) { out.push({ t: "sp", v: SPACES[d] }); i += 2; continue; }
        out.push({ t: "ch", v: d, lit: true });
        i += 2;
        continue;
      }
      if (c === "{") { out.push({ t: "{" }); i++; continue; }
      if (c === "}") { out.push({ t: "}" }); i++; continue; }
      if (c === "^") { out.push({ t: "^" }); i++; continue; }
      if (c === "_") { out.push({ t: "_" }); i++; continue; }
      if (c === "&") { out.push({ t: "&" }); i++; continue; }
      if (c === "~") { out.push({ t: "sp", v: "0.25em" }); i++; continue; }
      if (c === "%") { const j = src.indexOf("\n", i); i = j < 0 ? n : j + 1; continue; }
      if (c === "\n" || c === "\r") { out.push({ t: "ch", v: " " }); i++; continue; }
      out.push({ t: "ch", v: c });
      i++;
    }
    return out;
  }

  /* ── помощники разбора ─────────────────────────────────── */
  function rawGroup(tk, st) {
    /* {text} как простая строка — для имён окружений и спецификаций колонок */
    let s = "";
    if (tk[st.i] && tk[st.i].t === "{") {
      st.i++;
      while (st.i < tk.length && tk[st.i].t !== "}") {
        const t = tk[st.i];
        if (t.t === "ch") s += t.v;
        else if (t.t === "cmd") s += t.v;
        st.i++;
      }
      if (tk[st.i]) st.i++;
    }
    return s.trim();
  }

  function optionalRaw(tk, st) {
    /* [n] перед аргументом: корень степени n, спецификация колонок */
    if (!tk[st.i] || tk[st.i].t !== "ch" || tk[st.i].v !== "[") return null;
    const save = st.i;
    st.i++;
    const inner = [];
    let depth = 0;
    while (st.i < tk.length) {
      const t = tk[st.i];
      if (t.t === "{") depth++;
      if (t.t === "}") depth--;
      if (depth === 0 && t.t === "ch" && t.v === "]") { st.i++; return inner; }
      inner.push(t);
      st.i++;
    }
    st.i = save;
    return null;
  }

  function textArg(tk, st) {
    /* аргумент \text{...} — без математического курсива */
    let s = "";
    if (tk[st.i] && tk[st.i].t === "{") {
      st.i++;
      let depth = 1;
      while (st.i < tk.length) {
        const t = tk[st.i];
        if (t.t === "{") depth++;
        if (t.t === "}") { depth--; if (!depth) { st.i++; break; } }
        if (t.t === "ch") s += t.v;
        else if (t.t === "sp") s += " ";
        else if (t.t === "cmd") s += SYM[t.v] || t.v;
        else if (t.t === "_") s += "_";
        else if (t.t === "^") s += "^";
        st.i++;
      }
    } else if (tk[st.i]) {
      const t = tk[st.i];
      s = t.t === "ch" ? t.v : (t.t === "cmd" ? (SYM[t.v] || t.v) : "");
      st.i++;
    }
    return s;
  }

  /* ── сборка атомов ─────────────────────────────────────── */
  function atomHTML(a) {
    const base = a.h;
    if (a.sup != null && a.sub != null) {
      return base + `<span class="tex-ss"><span class="tex-ss-u">${a.sup}</span>`
        + `<span class="tex-ss-d">${a.sub}</span></span>`;
    }
    if (a.sup != null) return base + `<span class="tex-sup">${a.sup}</span>`;
    if (a.sub != null) return base + `<span class="tex-sub">${a.sub}</span>`;
    return base;
  }

  function renderList(tk, st, stop) {
    const atoms = [];
    while (st.i < tk.length) {
      const t = tk[st.i];
      if (t.t === "}") { if (stop === "}") st.i++; break; }
      if (t.t === "cmd" && t.v === "end") break;
      if (t.t === "^" || t.t === "_") {
        st.i++;
        const s = renderOne(tk, st);
        let a = atoms[atoms.length - 1];
        if (!a) { a = { h: "" }; atoms.push(a); }
        if (t.t === "^") a.sup = (a.sup || "") + s;
        else a.sub = (a.sub || "") + s;
        continue;
      }
      const html = renderOne(tk, st);
      if (html !== null) atoms.push({ h: html });
    }
    return atoms.map(atomHTML).join("");
  }

  function charHTML(t) {
    const c = t.v;
    if (c === " ") return " ";
    if (c === "-") return "−";
    if (c === "'") return "′";
    if (/[a-zA-Z]/.test(c) && !t.lit) return `<span class="tex-var">${c}</span>`;
    if (c === "<") return "&lt;";
    if (c === ">") return "&gt;";
    if (c === "&") return "&amp;";
    if (c === "=" || c === "+" || c === "−") return `<span class="tex-bin">${esc(c)}</span>`;
    return esc(c);
  }

  function renderOne(tk, st) {
    const t = tk[st.i];
    if (!t) return "";
    if (t.t === "{") { st.i++; return `<span class="tex-grp">${renderList(tk, st, "}")}</span>`; }
    if (t.t === "}") { st.i++; return ""; }
    if (t.t === "ch") { st.i++; return charHTML(t); }
    if (t.t === "sp") { st.i++; return `<span class="tex-sp" style="width:${t.v}"></span>`; }
    if (t.t === "br") { st.i++; return `<span class="tex-nl"></span>`; }
    if (t.t === "&") { st.i++; return `<span class="tex-sp" style="width:.35em"></span>`; }
    if (t.t === "^" || t.t === "_") { return ""; }

    const name = t.v;
    st.i++;
    return cmdHTML(name, tk, st);
  }

  function arg(tk, st) {
    while (tk[st.i] && tk[st.i].t === "ch" && tk[st.i].v === " ") st.i++;
    if (!tk[st.i]) return "";
    if (tk[st.i].t === "{") { st.i++; return renderList(tk, st, "}"); }
    return renderOne(tk, st);
  }

  function cmdHTML(name, tk, st) {
    /* дроби */
    if (name === "frac" || name === "dfrac" || name === "tfrac" || name === "cfrac") {
      const a = arg(tk, st), b = arg(tk, st);
      const sm = name === "tfrac" ? " tex-frac-sm" : "";
      return `<span class="tex-frac${sm}"><span class="tex-num">${a}</span>`
        + `<span class="tex-den">${b}</span></span>`;
    }
    if (name === "binom" || name === "dbinom" || name === "tbinom") {
      const a = arg(tk, st), b = arg(tk, st);
      return `<span class="tex-delim">(</span><span class="tex-frac tex-binom">`
        + `<span class="tex-num">${a}</span><span class="tex-den">${b}</span></span>`
        + `<span class="tex-delim">)</span>`;
    }
    if (name === "over") return `<span class="tex-sp" style="width:.2em"></span>/<span class="tex-sp" style="width:.2em"></span>`;

    /* корень */
    if (name === "sqrt") {
      const deg = optionalRaw(tk, st);
      const body = arg(tk, st);
      const root = deg ? `<span class="tex-root">${renderList(deg, { i: 0 }, null)}</span>` : "";
      return `<span class="tex-sqrt">${root}<span class="tex-radical">√</span>`
        + `<span class="tex-rad">${body}</span></span>`;
    }

    /* текстовые режимы */
    if (UPRIGHT.has(name)) return `<span class="tex-text">${esc(textArg(tk, st))}</span>`;
    if (BOLD.has(name)) return `<span class="tex-text tex-b">${esc(textArg(tk, st))}</span>`;
    if (ITAL.has(name)) return `<span class="tex-var">${esc(textArg(tk, st))}</span>`;
    if (MONO.has(name)) return `<span class="tex-mono">${esc(textArg(tk, st))}</span>`;
    if (BLACKBOARD.has(name)) {
      const s = textArg(tk, st);
      return `<span class="tex-text">${esc(s.replace(/[A-Z]/g, c => BB[c] || c))}</span>`;
    }
    if (SCRIPT.has(name)) return `<span class="tex-cal">${esc(textArg(tk, st))}</span>`;

    /* надстрочные знаки */
    if (name in ACCENTS) {
      const body = arg(tk, st);
      if (name === "overline" || name === "bar") {
        return `<span class="tex-ovl">${body}</span>`;
      }
      const wide = name === "vec" || name === "overrightarrow" || name === "overleftarrow"
        || name === "widehat" || name === "widetilde";
      return `<span class="tex-acc${wide ? " tex-acc-w" : ""}">`
        + `<span class="tex-acc-m">${ACCENTS[name]}</span>`
        + `<span class="tex-acc-b">${body}</span></span>`;
    }
    if (name === "underline") return `<span class="tex-unl">${arg(tk, st)}</span>`;
    if (name === "underbrace") return `<span class="tex-unl">${arg(tk, st)}</span>`;
    if (name === "overbrace") return `<span class="tex-ovl">${arg(tk, st)}</span>`;

    /* рамка вокруг ответа */
    if (name === "boxed" || name === "fbox" || name === "framebox") {
      return `<span class="tex-boxed">${arg(tk, st)}</span>`;
    }

    /* ограничители */
    if (name === "left" || name === "right" || /^(bigg?|Bigg?)[lrm]?$/.test(name)) {
      const t = tk[st.i];
      if (!t) return "";
      st.i++;
      let ch = "";
      if (t.t === "ch") ch = DELIMS[t.v] !== undefined ? DELIMS[t.v] : t.v;
      else if (t.t === "cmd") ch = SYM[t.v] || "";
      if (!ch) return "";
      const big = /^(bigg|Bigg)/.test(name) ? " tex-delim-xl" : (/^(big|Big)/.test(name) ? " tex-delim-l" : "");
      return `<span class="tex-delim${big}">${esc(ch)}</span>`;
    }

    /* окружения */
    if (name === "begin") return envHTML(tk, st);

    /* служебное — молча пропускаем */
    if (name === "limits" || name === "nolimits" || name === "displaystyle"
      || name === "textstyle" || name === "scriptstyle" || name === "scriptscriptstyle"
      || name === "nonumber" || name === "notag" || name === "noalign"
      || name === "big" || name === "Big" || name === "bigg" || name === "Bigg") {
      return "";
    }
    if (name === "label" || name === "tag" || name === "ref" || name === "eqref"
      || name === "hspace" || name === "vspace" || name === "phantom") {
      rawGroup(tk, st);
      return "";
    }
    if (name === "quad") return `<span class="tex-sp" style="width:1em"></span>`;
    if (name === "qquad") return `<span class="tex-sp" style="width:2em"></span>`;
    if (name === "thinspace" || name === "enspace") return `<span class="tex-sp" style="width:.3em"></span>`;

    /* крупные операторы */
    if (name in BIG) {
      return `<span class="tex-big">${BIG[name]}</span>`;
    }
    if (LIMLIKE.has(name)) return `<span class="tex-op">${esc(name)}</span>`;
    if (FUNCS.has(name)) return `<span class="tex-op">${esc(name)}</span>`;

    /* символы */
    if (SYM[name]) return esc(SYM[name]);

    /* неизвестная команда: показываем прямым шрифтом, не ломая строку */
    return `<span class="tex-op">${esc(name)}</span>`;
  }

  /* ── матрицы, cases, align ─────────────────────────────── */
  function envHTML(tk, st) {
    const name = rawGroup(tk, st);
    const base = name.replace(/\*$/, "");
    if (base === "array" || base === "tabular" || base === "alignat") optionalRaw(tk, st);
    if (base === "array" || base === "tabular") rawGroup(tk, st);

    const body = [];
    let depth = 0;
    while (st.i < tk.length) {
      const t = tk[st.i];
      if (t.t === "cmd" && t.v === "begin") {
        depth++;
        body.push(t);
        st.i++;
        continue;
      }
      if (t.t === "cmd" && t.v === "end") {
        if (depth === 0) { st.i++; rawGroup(tk, st); break; }
        depth--;
        body.push(t);
        st.i++;
        continue;
      }
      body.push(t);
      st.i++;
    }

    /* строки и ячейки по \\ и & на нулевой глубине */
    const rows = [[[]]];
    let d = 0;
    for (const t of body) {
      if (t.t === "{") d++;
      if (t.t === "}") d--;
      if (d === 0 && t.t === "br") { rows.push([[]]); continue; }
      if (d === 0 && t.t === "&") { rows[rows.length - 1].push([]); continue; }
      const row = rows[rows.length - 1];
      row[row.length - 1].push(t);
    }
    while (rows.length && rows[rows.length - 1].every(c => !c.length)) rows.pop();
    if (!rows.length) return "";

    const cols = Math.max(...rows.map(r => r.length));
    const cells = rows.map(r => {
      const out = [];
      for (let i = 0; i < cols; i++) {
        const toks = r[i] || [];
        out.push(`<span class="tex-cell">${renderList(toks, { i: 0 }, null)}</span>`);
      }
      return out.join("");
    }).join("");

    const [l, r] = ENVS[base] || ["", ""];
    const scale = Math.max(1, rows.length * 0.92);
    const dl = l ? `<span class="tex-fence" style="transform:scaleY(${scale.toFixed(2)})">${esc(l)}</span>` : "";
    const dr = r ? `<span class="tex-fence" style="transform:scaleY(${scale.toFixed(2)})">${esc(r)}</span>` : "";
    const align = base === "cases" ? " tex-arr-l" : "";

    return `<span class="tex-env">${dl}<span class="tex-arr${align}" `
      + `style="grid-template-columns:repeat(${cols},auto)">${cells}</span>${dr}</span>`;
  }

  /* ── публичный рендер ──────────────────────────────────── */
  function render(src, display) {
    let html;
    try {
      html = renderList(tokenize(String(src || "")), { i: 0 }, null);
    } catch (e) {
      return `<span class="tex tex-raw">${esc(src)}</span>`;
    }
    if (!html.trim()) return "";
    return display
      ? `<div class="tex tex-display">${html}</div>`
      : `<span class="tex tex-inline">${html}</span>`;
  }

  /* ── поиск формул в тексте ─────────────────────────────── */
  const MATH_ENVS = /^(equation|align|aligned|gather|gathered|multline|cases|split|array|[pbBvV]?matrix|smallmatrix)\*?$/;

  /* Модели часто теряют обратный слэш у \[ — строка остаётся просто "[".
     Восстанавливаем такие пары, иначе формула уходит в текст как есть. */
  function normalize(text) {
    const lines = String(text || "").split("\n");
    for (let i = 0; i < lines.length; i++) {
      if (!/^[ \t]*\\?\[[ \t]*$/.test(lines[i])) continue;
      for (let j = i + 1; j < Math.min(lines.length, i + 60); j++) {
        if (/^[ \t]*$/.test(lines[j])) break;          /* пустая строка — это не формула */
        if (/^[ \t]*\\?\][ \t]*$/.test(lines[j])) {
          lines[i] = "\\[";
          lines[j] = "\\]";
          i = j;
          break;
        }
      }
    }
    return lines.join("\n");
  }

  function scan(text) {
    const s = String(text || "");
    const n = s.length;
    const items = [];
    let i = 0;

    while (i < n) {
      const c = s[i];

      if (c === "\\") {
        const d = s[i + 1];
        if (d === "[") {
          const e = s.indexOf("\\]", i + 2);
          if (e > 0) { items.push({ s: i, e: e + 2, body: s.slice(i + 2, e), display: true }); i = e + 2; continue; }
        }
        if (d === "(") {
          const e = s.indexOf("\\)", i + 2);
          if (e > 0) { items.push({ s: i, e: e + 2, body: s.slice(i + 2, e), display: false }); i = e + 2; continue; }
        }
        if (s.startsWith("\\begin{", i)) {
          const close = s.indexOf("}", i + 7);
          const env = close > 0 ? s.slice(i + 7, close) : "";
          if (MATH_ENVS.test(env)) {
            const tail = `\\end{${env}}`;
            const e = s.indexOf(tail, close);
            if (e > 0) {
              items.push({ s: i, e: e + tail.length, body: s.slice(i, e + tail.length), display: true });
              i = e + tail.length;
              continue;
            }
          }
        }
        i += 2;
        continue;
      }

      if (c === "$") {
        if (s[i + 1] === "$") {
          const e = s.indexOf("$$", i + 2);
          if (e > 0) { items.push({ s: i, e: e + 2, body: s.slice(i + 2, e), display: true }); i = e + 2; continue; }
          i += 2;
          continue;
        }
        /* одиночный $: без пробела сразу после открытия и перед закрытием,
           чтобы «$5 и $7» не превращалось в формулу */
        let j = i + 1;
        if (!s[j] || /\s/.test(s[j])) { i++; continue; }
        while (j < n && s[j] !== "$" && s[j] !== "\n") {
          if (s[j] === "\\") j++;
          j++;
        }
        if (s[j] === "$" && j > i + 1 && !/\s/.test(s[j - 1])) {
          items.push({ s: i, e: j + 1, body: s.slice(i + 1, j), display: false });
          i = j + 1;
          continue;
        }
        i++;
        continue;
      }

      i++;
    }
    return items;
  }

  return { render, scan, normalize, esc };
})();
