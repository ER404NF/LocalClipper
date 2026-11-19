// ClipperLocal app shell: sidebar, router, engine boot, live refresh.
import { $, API, ICON, api, esc, setAccent, state } from "./core.js";
import * as W from "./pages_work.js";
import * as L from "./pages_live.js";
import * as G from "./pages_grow.js";
import * as S from "./pages_setup.js";

const PAGES = {
  agent: W.agent, crew: W.crew, review: W.review, pipeline: W.pipeline, clips: W.clips,
  browser: L.browser, phone: L.phone, autopilot: L.autopilot, report: L.report,
  trends: G.trends, money: G.money,
  channels: S.channels, formats: S.formats, models: S.models, brain: S.brain, coding: S.coding, settings: S.settings,
};
const NAV = [
  ["Work", [["agent", "Agent", ICON.agent], ["crew", "Production crew", ICON.crew], ["pipeline", "Pipeline", ICON.pipeline], ["clips", "Clips", ICON.clips],
    ["browser", "Browser", ICON.browser], ["phone", "Phone", ICON.phone], ["autopilot", "Autopilot", ICON.autopilot]]],
  ["Grow", [["report", "Daily report", ICON.report], ["trends", "Trends", ICON.trends], ["money", "Monetization", ICON.money]]],
  ["Setup", [["channels", "Channels", ICON.channels], ["formats", "Formats", ICON.formats], ["models", "AI models", ICON.models],
    ["brain", "Brain", ICON.brain], ["coding", "Coding crew", ICON.coding], ["settings", "Settings", ICON.settings]]],
];

function renderNav(current) {
  const s = state.status || {};
  const extra = { clips: `<span class="badge">${s.review_count || ""}</span>`, browser: `<span class="note">${(s.channels || []).length || ""}</span>`,
    autopilot: `<span class="note" style="color:${s.autopilot?.paused ? "var(--bad)" : s.autopilot?.enabled ? "var(--ok)" : ""}">${s.autopilot?.paused ? "paused" : s.autopilot?.enabled ? "on" : "off"}</span>` };
  $("#nav").innerHTML = NAV.map(([lbl, items]) => `<div class="navlbl">${lbl}</div>` + items.map(([id, name, icon]) =>
    `<a class="nav" href="#/${id}" ${id === current || (current === "review" && id === "crew") ? 'aria-current="page"' : ""}>${icon}${name}${extra[id] || ""}</a>`).join("")).join("");
}

function renderSys() {
  const s = state.status || {};
  const nb = s.italy_box || {};
  const line = (ok, text) => `<div><span class="dot" style="background:${ok ? "var(--ok)" : "var(--bad)"}"></span>${esc(text)}</div>`;
  $("#sys").innerHTML = line(s.ollama, `AI · ${s.model || ""}`) + line(s.twitch, "Twitch API") + line(nb.ok, nb.ok ? `Italy box · ${nb.city || "online"}` : "Italy box offline")
    + line(s.ffmpeg, "ffmpeg") + `<div style="border:1px solid var(--line3);border-radius:6px;padding:3px 8px;align-self:flex-start;color:var(--paper)">${s.monetization_mode ? "Monetization · 61–90s" : "Campaign mode · 20–60s"}</div>`;
}

function route() {
  const id = (location.hash.replace(/^#\/?/, "").split("?")[0]) || "agent";
  const page = PAGES[id] || PAGES.agent;
  state.page = page;
  renderNav(id);
  const main = $("#main");
  const fresh = main.cloneNode(false); main.replaceWith(fresh);   // drop old page listeners
  page.render(fresh);
  page.bind?.(fresh);
}

async function loadStatus() {
  state.status = await api("/api/status");
  setAccent(state.status.accent);
  renderSys();
  renderNav((location.hash.replace(/^#\/?/, "").split("?")[0]) || "agent");
}

async function boot() {
  const t0 = Date.now();
  for (;;) {
    try {
      if (API) {  // built-in copy inside the exe: switch to the live screens served by the engine
        const r = await fetch(`${API}/api/health`, { cache: "no-store" });
        if (r.ok) { location.replace(`${API}/`); return; }
      } else { await loadStatus(); break; }
    } catch {}
    $("#bootMsg").innerHTML = (Date.now() - t0) / 1000 < 40 ? "Starting the engine…"
      : "The engine isn't starting.<br>Run the ClipperLocal installer again (it repairs things). Details: <code>data/engine.log</code>.";
    await new Promise((r) => setTimeout(r, 700));
  }
  $("#boot").classList.add("hidden");
  if (state.status.preview) {
    const b = document.createElement("div");
    b.textContent = "PREVIEW of a coding crew change · nothing here is saved";
    b.style.cssText = "position:fixed;top:0;left:50%;transform:translateX(-50%);z-index:99;background:var(--accent);color:#000;font:600 12px Inter,sans-serif;padding:4px 12px;border-radius:0 0 8px 8px";
    document.body.appendChild(b);
  }
  window.addEventListener("hashchange", route);
  route();
  setInterval(async () => {
    try { await loadStatus(); } catch { return; }
    const p = state.page, el = $("#main");
    if (p && p.refresh && !document.hidden) Promise.resolve().then(() => p.refresh(el)).catch(() => {});
  }, 3500);
}
boot();
