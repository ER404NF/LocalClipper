// Shared helpers for every page.
export const TAURI = window.__TAURI__ && window.__TAURI__.core;
// Served by an engine (the real one on 8765, or a coding-crew preview on 8798): talk to that same engine.
// Built-in copy inside the exe (tauri://, tauri.localhost): talk to the real engine.
export const API = ["127.0.0.1", "localhost"].includes(location.hostname) ? "" : "http://127.0.0.1:8765";
export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const state = { status: null, page: null };

export async function api(path, opts = {}) {
  const r = await fetch(API + path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const ct = r.headers.get("content-type") || "";
  const j = ct.includes("json") ? await r.json().catch(() => ({})) : await r.text();
  if (!r.ok) throw new Error((j && j.detail) || r.statusText);
  return j;
}
export const post = (path, body = {}) => api(path, { method: "POST", body });
export const invoke = (cmd, args) => (TAURI ? TAURI.invoke(cmd, args) : Promise.reject(new Error("desktop app only")));

export function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), 4500);
}
export function modal(html) { $("#modalBox").innerHTML = html; $("#modal").classList.remove("hidden"); }
export function closeModal() { $("#modal").classList.add("hidden"); }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
export async function guard(fn) { try { return await fn(); } catch (e) { toast("⚠ " + e.message); } }

export const AV = { "Agent": "M", "Clipper A": "A", "Clipper B": "B", "Planner": "P", "Coder": "C", "Designer": "D", "Operator": "M" };
export const av = (who, size = 24) => { const k = AV[who] || "M"; return `<span class="av av-${k}" style="width:${size}px;height:${size}px" aria-hidden="true">${k === "M" ? "AI" : k}</span>`; };
export const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
export const ago = (t) => { if (!t) return ""; const s = Date.now() / 1000 - t; return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`; };
export const num = (n) => n == null ? "—" : n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M" : n >= 1e3 ? (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K" : String(Math.round(n));

const P = 'aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';
export const ICON = {
  agent: `<svg ${P}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
  crew: `<svg ${P}><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4.5-6.2"/></svg>`,
  pipeline: `<svg ${P}><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M15 3v18"/></svg>`,
  clips: `<svg ${P}><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4"/></svg>`,
  browser: `<svg ${P}><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M7 6.5h.01M10 6.5h.01"/></svg>`,
  phone: `<svg ${P}><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></svg>`,
  autopilot: `<svg ${P}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>`,
  report: `<svg ${P}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/></svg>`,
  trends: `<svg ${P}><path d="m3 17 6-6 4 4 8-8"/><path d="M14 7h7v7"/></svg>`,
  money: `<svg ${P}><circle cx="12" cy="12" r="9"/><path d="M15 9.5a3 3 0 0 0-3-1.5c-1.7 0-3 .9-3 2.2 0 3 6 1.6 6 4.6 0 1.3-1.3 2.2-3 2.2a3 3 0 0 1-3-1.5M12 6.5V8M12 16v1.5"/></svg>`,
  channels: `<svg ${P}><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></svg>`,
  formats: `<svg ${P}><path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/></svg>`,
  models: `<svg ${P}><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/></svg>`,
  brain: `<svg ${P}><circle cx="12" cy="5" r="2"/><circle cx="5" cy="17" r="2"/><circle cx="19" cy="17" r="2"/><circle cx="12" cy="12" r="2"/><path d="M12 7v3M10.5 13.2 6.5 15.8M13.5 13.2l4 2.6"/></svg>`,
  coding: `<svg ${P}><path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/></svg>`,
  settings: `<svg ${P}><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/></svg>`,
  send: `<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/></svg>`,
  file: `<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M10 8.5v7l5.5-3.5z"/></svg>`,
};

export function setAccent(hex) {
  const h = (hex || "#2F7BFF").replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  const lift = (c) => Math.round(c + (255 - c) * 0.45);
  const s = document.documentElement.style;
  s.setProperty("--accent", "#" + h);
  s.setProperty("--accent-soft", `rgba(${r},${g},${b},.14)`);
  s.setProperty("--accent-line", `rgba(${r},${g},${b},.5)`);
  s.setProperty("--accent-text", `rgb(${lift(r)},${lift(g)},${lift(b)})`);
}

export function header(title, sub = "", right = "") {
  return `<header class="topbar"><div><div class="t">${title}</div>${sub ? `<div class="s">${sub}</div>` : ""}</div><div class="right">${right}</div></header>`;
}

export async function reveal(path) {
  if (TAURI) return guard(() => invoke("reveal_file", { path }));
  toast("File: " + path);
}
export function go(route) { location.hash = "#/" + route; }
export function stepRow(state, text) {
  const i = state === "done" ? `<span class="i ok-t">✓</span>` : state === "now" ? `<span class="i"><span class="dot" style="width:10px;height:10px;background:var(--accent);margin-top:4px"></span></span>`
    : state === "failed" ? `<span class="i bad-t">✕</span>` : state === "waiting" ? `<span class="i warn-t">!</span>` : `<span class="i"><span class="dot" style="width:10px;height:10px;border:1.5px solid #45433E;margin-top:4px"></span></span>`;
  const col = state === "next" ? "sub" : state === "done" ? "mut" : "";
  return `<div class="step ${col}">${i}<span>${esc(text)}</span></div>`;
}
