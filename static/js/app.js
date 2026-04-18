// Theme / font / density / UI-language controls, persisted in localStorage.
// Also shared helpers the other pages use.

const LS = {
  theme: "ldii:theme",
  accent: "ldii:accent",
  font: "ldii:font",
  size: "ldii:size",
  density: "ldii:density",
  lang: "ldii:lang",
};

const DEFAULTS = {
  theme: "sepia", accent: "saffron", font: "serif", size: "m",
  density: "cozy", lang: "en",
};

function applySettings(s) {
  const r = document.documentElement;
  r.setAttribute("data-theme", s.theme);
  r.setAttribute("data-accent", s.accent);
  r.setAttribute("data-font", s.font);
  r.setAttribute("data-size", s.size);
  r.setAttribute("data-density", s.density);
  r.setAttribute("data-lang", s.lang);
  applyLabels(s.lang);
}

function loadSettings() {
  return {
    theme: localStorage.getItem(LS.theme) || DEFAULTS.theme,
    accent: localStorage.getItem(LS.accent) || DEFAULTS.accent,
    font: localStorage.getItem(LS.font) || DEFAULTS.font,
    size: localStorage.getItem(LS.size) || DEFAULTS.size,
    density: localStorage.getItem(LS.density) || DEFAULTS.density,
    lang: localStorage.getItem(LS.lang) || DEFAULTS.lang,
  };
}

function saveSetting(key, value) { localStorage.setItem(LS[key], value); }

// ---- label translations (Devanagari for a few nav/UI strings) ----
const LABELS = {
  en: {
    "nav.home": "Home",
    "nav.browse": "Browse",
    "nav.authors": "Authors",
    "nav.subjects": "Subjects",
    "nav.languages": "Languages",
    "nav.timeline": "Timeline",
    "ui.settings": "Settings",
    "ui.theme": "Theme",
    "ui.accent": "Accent",
    "ui.font": "Font",
    "ui.size": "Size",
    "ui.density": "Density",
    "ui.language": "UI language",
    "theme.light": "Light", "theme.dark": "Dark", "theme.sepia": "Sepia", "theme.saffron": "Saffron",
    "font.sans": "Sans", "font.serif": "Serif", "font.tiro": "Tiro",
    "size.s": "S", "size.m": "M", "size.l": "L",
    "density.compact": "Compact", "density.cozy": "Cozy", "density.spacious": "Spacious",
    "lang.en": "EN", "lang.hi": "हि",
    "brand.sub": "LD Institute of Indology · Manuscripts",
    "reset": "Reset",
  },
  hi: {
    "nav.home": "मुखपृष्ठ",
    "nav.browse": "सूची",
    "nav.authors": "लेखक",
    "nav.subjects": "विषय",
    "nav.languages": "भाषाएँ",
    "nav.timeline": "कालक्रम",
    "ui.settings": "सेटिंग्स",
    "ui.theme": "थीम",
    "ui.accent": "रंग",
    "ui.font": "फ़ॉन्ट",
    "ui.size": "आकार",
    "ui.density": "घनत्व",
    "ui.language": "भाषा",
    "theme.light": "हल्का", "theme.dark": "गहरा", "theme.sepia": "सेपिया", "theme.saffron": "केसरिया",
    "font.sans": "सैन्स", "font.serif": "सेरिफ़", "font.tiro": "तिरो",
    "size.s": "छोटा", "size.m": "मध्यम", "size.l": "बड़ा",
    "density.compact": "सघन", "density.cozy": "सामान्य", "density.spacious": "विस्तृत",
    "lang.en": "EN", "lang.hi": "हि",
    "brand.sub": "एल.डी. इंस्टिट्यूट ऑफ़ इंडोलॉजी · हस्तलिखित सूची",
    "reset": "रीसेट",
  },
};

function applyLabels(lang) {
  const dict = LABELS[lang] || LABELS.en;
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    if (dict[key]) el.textContent = dict[key];
  });
}

// ---- settings panel wiring ----
function initSettings() {
  const settings = loadSettings();
  applySettings(settings);

  const btn = document.getElementById("settings-btn");
  const panel = document.getElementById("settings-panel");
  if (!btn || !panel) return;

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    panel.classList.toggle("open");
  });
  document.addEventListener("click", (e) => {
    if (!panel.contains(e.target) && e.target !== btn) panel.classList.remove("open");
  });

  panel.querySelectorAll("[data-set]").forEach(el => {
    const [key, value] = el.getAttribute("data-set").split(":");
    if (settings[key] === value) el.classList.add("on");
    el.addEventListener("click", () => {
      settings[key] = value;
      saveSetting(key, value);
      applySettings(settings);
      // refresh "on" state within this group
      panel.querySelectorAll(`[data-set^="${key}:"]`).forEach(n => n.classList.remove("on"));
      el.classList.add("on");
    });
  });

  const reset = document.getElementById("settings-reset");
  if (reset) reset.addEventListener("click", () => {
    Object.keys(DEFAULTS).forEach(k => localStorage.removeItem(LS[k]));
    applySettings(DEFAULTS);
    panel.querySelectorAll("[data-set]").forEach(el => {
      const [k, v] = el.getAttribute("data-set").split(":");
      el.classList.toggle("on", DEFAULTS[k] === v);
    });
  });
}

// ---- keyboard shortcuts ----
function initShortcuts() {
  const hints = {
    "/": () => { const s = document.getElementById("q"); if (s) { s.focus(); return true; } return false; },
    "h": () => { window.location.href = "/"; },
    "b": () => { window.location.href = "/browse"; },
    "a": () => { window.location.href = "/authors"; },
    "s": () => { window.location.href = "/subjects"; },
    "l": () => { window.location.href = "/languages"; },
    "t": () => { window.location.href = "/timeline"; },
  };
  let lastG = 0;
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select")) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const key = e.key.toLowerCase();
    if (key === "/") { if (hints["/"]()) e.preventDefault(); return; }
    if (key === "g") { lastG = Date.now(); return; }
    if (Date.now() - lastG < 900 && hints[key]) { hints[key](); lastG = 0; }
    if (key === "?") showShortcutsHelp();
  });
}

function showShortcutsHelp() {
  alert(
    "Keyboard shortcuts:\n" +
    "  /  focus search\n" +
    "  g then h  → Home\n" +
    "  g then b  → Browse\n" +
    "  g then a  → Authors\n" +
    "  g then s  → Subjects\n" +
    "  g then l  → Languages\n" +
    "  g then t  → Timeline"
  );
}

// ---- small helpers ----
function fmt(n) { return new Intl.NumberFormat("en-IN").format(n); }
function ordinalCentury(n) {
  n = parseInt(n, 10);
  const s = ["th","st","nd","rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
}
function buildQuery(params) {
  return Object.entries(params)
    .filter(([,v]) => v !== "" && v !== null && v !== undefined)
    .map(([k,v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v))
    .join("&");
}
function animateCount(el, to, duration = 900) {
  if (!el) return;
  const from = 0;
  const start = performance.now();
  function step(now) {
    const p = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(Math.round(from + (to - from) * eased));
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// ---- boot ----
document.addEventListener("DOMContentLoaded", () => {
  initSettings();
  initShortcuts();
  document.body.classList.add("page-in");
});

// expose
window.LDII = { fmt, ordinalCentury, escapeHtml, buildQuery, animateCount, loadSettings };
