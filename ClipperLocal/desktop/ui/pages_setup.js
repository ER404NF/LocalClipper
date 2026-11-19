// Setup pages: Channels, Formats, AI models, Brain, Coding crew, Settings.
import { $, $$, API, TAURI, ago, api, av, esc, guard, header, invoke, num, post, reveal, setAccent, state, toast } from "./core.js";
import { chatRoom, restartEngine, reviewChange } from "./components.js";

const API_FIELDS = {
  youtube: [["client_secrets", "Client secrets JSON path", "secrets/youtube_client.json"], ["privacy", "Privacy", "public"]],
  instagram: [["ig_user_id", "IG user ID", ""], ["access_token", "Access token", ""], ["graph_url", "Graph URL", "https://graph.facebook.com/v21.0"]],
  tiktok: [["access_token", "Access token", ""], ["mode", "Mode (inbox|direct)", "inbox"], ["privacy_level", "Privacy (direct)", "SELF_ONLY"]],
};

// ------------------------------------------------------------------ Channels
export const channels = {
  render(el) {
    el.innerHTML = header("Channels", "Accounts the crew publishes to · all in your brother's name, used from Italy") +
      `<div class="page"><div class="pagepad"><div class="row" style="align-items:flex-start;gap:24px">
       <section class="col grow" style="min-width:520px;gap:18px"><div class="card pad row" data-net></div><div data-list class="col" style="gap:18px"></div></section>
       <aside class="col" style="flex:1 1 360px;max-width:420px"><form class="card pad col" data-add><b>Connect an account</b>
         <div class="seg" role="radiogroup" aria-label="Platform" data-plat>${["tiktok", "instagram", "youtube"].map((p, i) => `<button type="button" role="radio" aria-selected="${i === 0}" data-p="${p}">${p[0].toUpperCase() + p.slice(1)}</button>`).join("")}</div>
         <label class="f">Name in the app<input data-name placeholder="e.g. main, gta_daily" required></label>
         <label class="f">Internet route<select data-proxy><option value="italy">Italy box · Turin (recommended)</option><option value="direct">Direct, no proxy</option><option value="custom">Custom proxy…</option></select></label>
         <input data-custom class="hidden" placeholder="socks5://host:port">
         <fieldset style="border:0;margin:0;padding:0" class="col"><legend class="small mut" style="margin-bottom:6px">How the crew posts</legend>
           <label class="card pad row" style="align-items:flex-start"><input type="radio" name="m" value="browser" checked><span><b>Browser tab</b><span class="small mut" style="display:block">Its own signed-in tab. The crew uploads, edits, schedules and reads stats there.</span></span></label>
           <label class="card pad row" style="align-items:flex-start"><input type="radio" name="m" value="phone"><span><b>Phone · Edits</b><span class="small mut" style="display:block">Instagram only: the crew uses Edits on the Android phone.</span></span></label>
           <label class="card pad row" style="align-items:flex-start"><input type="radio" name="m" value="api"><span><b>Official API</b><span class="small mut" style="display:block">Posts automatically. Needs a developer app and token.</span></span></label></fieldset>
         <div data-fields class="col"></div>
         <button class="btn pri">Add and open its tab</button></form></aside></div></div></div>`;
    this.plat = "tiktok"; this.fields(el); this.refresh(el);
  },
  fields(el) {
    const m = ($("input[name=m]:checked", el) || {}).value;
    $("[data-fields]", el).innerHTML = m === "api" ? API_FIELDS[this.plat].map(([k, l, d]) => `<label class="f">${l}<input data-api="${k}" value="${esc(d)}"></label>`).join("") : "";
  },
  async refresh(el) {
    if ($("[data-add]", el).contains(document.activeElement)) return;
    const [list, net] = [await api("/api/channels"), state.status?.italy_box || {}];
    $("[data-net]", el).innerHTML = `<div class="grow"><b>Italy box</b><div class="small sub">Old laptop in Turin · reached through Tailscale, nothing open to the internet</div></div>
      <span class="small ${net.ok ? "ok-t" : "bad-t"}">● ${net.ok ? `Online · ${esc(net.city)}, ${esc(net.country)}` : esc(net.error || "offline")}</span><button class="btn" data-checkip>Check IP</button>`;
    const by = { tiktok: [], instagram: [], youtube: [] }; list.forEach((c) => by[c.platform].push(c));
    const dot = { tiktok: "var(--paper)", instagram: "#E1306C", youtube: "var(--bad)" };
    $("[data-list]", el).innerHTML = Object.entries(by).map(([p, cs]) => `<div class="col" style="gap:8px"><div class="row tiny sub" style="font-weight:600;letter-spacing:.6px;text-transform:uppercase"><span class="dot" style="border-radius:2px;background:${dot[p]}"></span>${p}</div>
      <div class="card">${cs.map((c, i) => `<div class="row pad" style="${i ? "border-top:1px solid #1F1E1C" : ""}"><div style="min-width:150px"><b>${esc(c.name)}</b><div class="small sub">${esc(c.key)}</div></div>
        <span class="pill">${{ browser: "Browser tab", api: "Official API", phone: "Phone · Edits" }[c.method]}</span>
        <span class="pill ${c.proxy === "italy" ? "ok" : "warn"}">${c.proxy === "italy" ? "Proxy · Italy box" : c.proxy === "direct" ? "Direct" : "Custom proxy"}</span>
        <span class="small ${c.ready ? "ok-t" : "bad-t"}">● ${c.ready ? "ready" : "missing keys"}</span>
        <span class="small sub">${Object.values(c.stats || {}).length ? Object.entries(c.stats).map(([k, v]) => `${k.replace("_", " ")} ${num(v.value)}`).join(" · ") : ""}</span>
        <div class="row" style="margin-left:auto">${c.method !== "api" ? `<button class="btn sm" data-open="${esc(c.key)}">Open tab</button>` : ""}${c.id ? `<button class="btn sm" data-del="${c.id}" aria-label="Remove ${esc(c.key)}">Remove</button>` : ""}</div></div>`).join("") || `<div class="pad small sub">No ${p} accounts yet.</div>`}</div></div>`).join("");
  },
  bind(el) {
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.dataset.p) { this.plat = t.dataset.p; $$("[data-p]", el).forEach((b) => b.setAttribute("aria-selected", b === t)); this.fields(el); }
      if (t.dataset.checkip != null) { const r = await guard(() => api("/api/network")); if (r) { state.status.italy_box = r; this.refresh(el); toast(r.ok ? `Through ${r.city}, ${r.country} (${r.ip})` : r.error); } }
      if (t.dataset.open) { if (TAURI) guard(() => invoke("open_browser", { tab: t.dataset.open })); else location.hash = "#/browser"; }
      if (t.dataset.del && confirm("Remove this account from the app? Its saved login stays on disk.")) { await guard(() => api(`/api/channels/${t.dataset.del}`, { method: "DELETE" })); this.refresh(el); }
    });
    el.addEventListener("change", (e) => {
      if (e.target.name === "m") this.fields(el);
      if (e.target.matches("[data-proxy]")) $("[data-custom]", el).classList.toggle("hidden", e.target.value !== "custom");
    });
    el.addEventListener("submit", async (e) => {
      if (!e.target.matches("[data-add]")) return; e.preventDefault();
      const method = $("input[name=m]:checked", el).value, name = $("[data-name]", el).value.trim();
      if (method === "phone" && this.plat !== "instagram") return toast("Phone posting is for Instagram (Edits)");
      const pv = $("[data-proxy]", el).value, proxy = pv === "custom" ? $("[data-custom]", el).value.trim() : pv;
      const creds = Object.fromEntries($$("[data-api]", el).map((i) => [i.dataset.api, i.value.trim()]));
      const ok = await guard(() => post("/api/channels", { platform: this.plat, name, method, creds, proxy }));
      if (!ok) return;
      $("[data-name]", el).value = ""; toast(method === "browser" ? "Added. Sign in once in its tab; it stays signed in." : "Added");
      if (method === "browser" && TAURI) setTimeout(() => invoke("open_browser", { tab: `${this.plat}:${name}` }).catch(() => {}), 800);
      this.refresh(el);
    });
  },
};

// ------------------------------------------------------------------ Formats
export const formats = {
  render(el) {
    el.innerHTML = header("Formats & layouts", "Each platform's frame and safe areas, and the layouts the crew can choose") + `<div class="page"><div class="pagepad" data-body></div></div>`;
    this.refresh(el);
  },
  async refresh(el) {
    const f = await api("/api/formats");
    const frame = (name, safe, note) => { const [top, bottom] = safe; return `<div class="card pad row" style="align-items:flex-start;gap:14px;flex:1 1 260px">
      <div style="position:relative;width:120px;height:213px;border-radius:10px;background:var(--thumb);border:1px solid var(--line4);overflow:hidden;flex:none">
        <div style="position:absolute;left:0;right:0;top:0;height:${(top / 1920) * 100}%;background:rgba(242,85,90,.18)"></div>
        <div style="position:absolute;left:0;right:0;bottom:0;height:${(bottom / 1920) * 100}%;background:rgba(242,85,90,.28)"></div>
        <div style="position:absolute;right:0;top:42%;bottom:${(bottom / 1920) * 100}%;width:16%;background:rgba(242,85,90,.28)"></div></div>
      <div class="col small mut" style="gap:6px"><b style="color:var(--paper);font-size:14px">${name}</b><span>1080 × 1920 · 9:16</span><span>Hook below ${top}px · captions above ${bottom}px from the bottom</span><span>${note}</span></div></div>`; };
    const lay = { blur: "Gameplay centered on a blurred copy. Works on every stream.", facecam: "Streamer cam on top, gameplay below. When the reaction is the moment.",
      split: "Stream on top, your own background gameplay below. For clips with slow parts.", crop: "Zoomed into the action, full screen. Loses the sides.", bubble: "Gameplay full screen, face in a corner." };
    $("[data-body]", el).innerHTML = `<section class="row" style="gap:16px;align-items:stretch">${frame("TikTok", f.platforms.tiktok.safe, "Creator Rewards pays on 1 min+")}${frame("Instagram Reels", f.platforms.reels.safe, "Grid crops to 3:4, so the hook stays centered")}${frame("YouTube Shorts", f.platforms.shorts.safe, "Up to 3 min · titles matter for search")}</section>
      <p class="small sub" style="margin:-8px 0 0">Every clip the crew edits is rendered three times, once per platform, keeping text out of the shaded areas.</p>
      <section class="col"><b>Layouts</b><div class="grid2">${f.layouts.map((l) => `<div class="card pad col" style="gap:6px"><b>${l === "split" ? "Split-screen + filler" : l[0].toUpperCase() + l.slice(1)}</b><span class="small mut">${lay[l]}</span></div>`).join("")}</div>
      <p class="small mut">The production crew picks the layout per clip and tells you why. You can change it on the Clips page.</p></section>
      <section class="card pad col"><div class="row"><b class="grow">Filler footage for split-screen</b><button class="btn" data-folder>Open folder</button></div>
        <div class="small mut">Put gameplay you recorded yourself here (for example your own GTA driving). Footage from other games or shows can get copyright claims.</div>
        <div class="row">${f.filler.map((n) => `<span class="pill">${esc(n)}</span>`).join("") || `<span class="small warn-t">No filler yet: split-screen is skipped until you add some.</span>`}</div></section>`;
    $("[data-folder]", el).onclick = () => reveal(f.filler_dir);
  },
};

// ------------------------------------------------------------------ AI models
export const models = {
  render(el) {
    el.innerHTML = header("AI models", "Two local models: one for the Agent + production crew, one for the coding crew. Each agent has its own job, rules and brain access.", `<span class="small" data-ol></span>`) +
      `<div class="page"><div class="pagepad" data-body></div></div>`;
    this.refresh(el, true);
  },
  async refresh(el, force) {
    if (!force && $("[data-body]", el).contains(document.activeElement)) return;
    const m = await api("/api/models");
    $("[data-ol]", el).innerHTML = m.installed.length ? `<span class="ok-t">● Ollama running</span>` : `<span class="bad-t">● Ollama not running</span>`;
    const have = new Set(m.installed.map((x) => x.name));
    const g = m.gpu || {};
    $("[data-body]", el).innerHTML = `<section class="card pad row" style="gap:24px">
        <label class="f" style="flex:1 1 220px">Agent + production crew<select data-team>${[...new Set([m.team_model, ...m.suggested.filter((s) => s.role === "team").map((s) => s.name), ...m.installed.map((x) => x.name)])].map((n) => `<option ${n === m.team_model ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></label>
        <label class="f" style="flex:1 1 220px">Coding crew<select data-coding>${[...new Set([m.coding_model, ...m.suggested.map((s) => s.name), ...m.installed.map((x) => x.name)])].map((n) => `<option ${n === m.coding_model ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></label>
        <div class="col" style="flex:2 1 340px;gap:8px"><div class="row small"><b>GPU memory</b><span class="mut" style="margin-left:auto">${g.name ? `${esc(g.name)} · ${g.used_gb} of ${g.total_gb} GB used` : "no NVIDIA GPU found (runs on CPU or Mac GPU)"}</span></div>
          ${g.total_gb ? `<div class="bar" style="height:10px"><span style="width:${(100 * g.used_gb) / g.total_gb}%"></span></div>` : ""}</div>
        <label class="f">Agents working at once<input type="number" min="1" max="4" data-par value="${m.parallel}" style="width:90px"></label></section>
      <section class="card scrollx"><table class="table"><thead><tr><th>Agent</th><th>Team</th><th>Its job</th><th>Refuses</th></tr></thead><tbody>
        ${m.roles.map((r) => `<tr><td><span class="row" style="flex-wrap:nowrap">${av(r.name)}<b>${esc(r.name)}</b></span></td><td><span class="pill">${esc(r.team)}</span></td><td class="mut small">${esc(r.job)}</td><td class="sub small">${esc(r.refuses)}</td></tr>`).join("")}</tbody></table></section>
      <section class="grid2"><div class="card pad col"><b>Models on this computer</b>${m.installed.map((x) => `<div class="row small"><span class="grow">${esc(x.name)}</span><span class="sub">${x.size_gb} GB</span></div>`).join("") || `<span class="small sub">None yet.</span>`}</div>
        <div class="card pad col"><b>Download</b>${m.suggested.map((s) => { const p = m.pulls[s.name]; return `<div class="row small"><span class="grow"><b style="font-weight:500">${esc(s.name)}</b> <span class="sub">${esc(s.note)}</span></span>
          ${have.has(s.name) ? `<span class="ok-t">installed</span>` : p && p.state === "downloading" ? `<span class="acc-t">${p.pct}%</span>` : p && p.state === "error" ? `<span class="bad-t">${esc(p.error)}</span>` : `<button class="btn sm" data-pull="${esc(s.name)}">Download</button>`}</div>`; }).join("")}</div>
        <div class="card pad col"><b>Helpers</b><div class="row small"><span class="grow">Captions · Whisper ${esc(m.helpers.whisper)}</span><span class="ok-t">ready</span></div>
          <label class="row small"><input type="checkbox" data-vision ${m.helpers.vision ? "checked" : ""}> Let agents look at screenshots (needs a vision model)</label>
          <div class="row small"><span class="grow">Web search · ${m.helpers.search === "brave" ? "Brave API" : "DuckDuckGo"}</span><span class="ok-t">ready</span></div></div></section>`;
  },
  bind(el) {
    el.addEventListener("change", async (e) => {
      const t = e.target;
      if (t.matches("[data-team]")) { await guard(() => post("/api/settings", { section: "team", key: "model", value: t.value })); toast("Crew model set. Download it if it isn't installed."); }
      if (t.matches("[data-coding]")) { await guard(() => post("/api/settings", { section: "team", key: "coding_model", value: t.value })); toast("Coding model set. Download it if it isn't installed."); }
      if (t.matches("[data-par]")) { await guard(() => post("/api/settings", { section: "team", key: "parallel", value: +t.value })); toast("Saved. Ollama must allow this many at once (setup sets it)."); }
      if (t.matches("[data-vision]")) await guard(() => post("/api/settings", { section: "browser", key: "use_vision", value: t.checked }));
    });
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("[data-pull]"); if (!t) return;
      await guard(() => post("/api/models/pull", { name: t.dataset.pull })); toast("Downloading…"); this.refresh(el, true);
    });
  },
};

// ------------------------------------------------------------------ Brain
const TEAMC = { shared: "var(--paper)", production: "var(--accent)", coding: "var(--ok)", learning: "var(--warn)" };
function layout(g, w, h) {
  const N = g.nodes.length, pos = {};
  g.nodes.forEach((n, i) => { const a = (i / Math.max(1, N)) * Math.PI * 2; pos[n.id] = { x: w / 2 + Math.cos(a) * w * 0.3, y: h / 2 + Math.sin(a) * h * 0.3, vx: 0, vy: 0 }; });
  const E = g.edges.filter((e) => pos[e.from] && pos[e.to]);
  for (let it = 0; it < 300; it++) {
    for (const a of g.nodes) for (const b of g.nodes) { if (a === b) continue; const p = pos[a.id], q = pos[b.id]; let dx = p.x - q.x, dy = p.y - q.y; const d2 = dx * dx + dy * dy + 0.01; const f = 2200 / d2; p.vx += (dx / Math.sqrt(d2)) * f; p.vy += (dy / Math.sqrt(d2)) * f; }
    for (const e of E) { const p = pos[e.from], q = pos[e.to]; const dx = q.x - p.x, dy = q.y - p.y; const d = Math.sqrt(dx * dx + dy * dy) || 1; const f = (d - 110) * 0.02; p.vx += (dx / d) * f; p.vy += (dy / d) * f; q.vx -= (dx / d) * f; q.vy -= (dy / d) * f; }
    for (const n of g.nodes) { const p = pos[n.id]; p.vx += (w / 2 - p.x) * 0.004; p.vy += (h / 2 - p.y) * 0.004; p.x += Math.max(-8, Math.min(8, p.vx)); p.y += Math.max(-8, Math.min(8, p.vy)); p.vx *= 0.6; p.vy *= 0.6; p.x = Math.max(30, Math.min(w - 30, p.x)); p.y = Math.max(30, Math.min(h - 30, p.y)); }
  }
  return pos;
}
export const brain = {
  sel: null, team: "",
  render(el) {
    el.innerHTML = header("Brain", "Shared memory for the whole team · everyone reads, each team writes its own · Obsidian-compatible",
      `<div class="seg" role="tablist" data-teams>${[["", "All"], ["shared", "Shared"], ["production", "Production"], ["coding", "Coding"], ["learning", "Learnings"]].map(([v, l]) => `<button role="tab" aria-selected="${v === this.team}" data-t="${v}">${l}</button>`).join("")}</div>
      <label class="sr" for="bsearch">Search notes</label><input id="bsearch" type="search" placeholder="Search notes" style="width:180px"><button class="btn" data-new>New note</button>`) +
      `<div class="page"><div class="split" style="height:100%"><section class="main" style="position:relative;padding:12px 18px"><svg class="graph" data-graph role="img" aria-label="Brain graph"></svg><div data-tip class="card pad small hidden" style="position:absolute;pointer-events:none;max-width:240px"></div>
        <div class="row small mut" style="position:absolute;left:24px;bottom:14px">${Object.entries(TEAMC).map(([t, c]) => `<span class="row"><span class="dot" style="width:9px;height:9px;background:${c}"></span>${t}</span>`).join("")}</div></section>
      <aside class="sidepanel" data-note><div class="empty">Click a dot to open a note.</div></aside></div></div>`;
    this.refresh(el, true);
  },
  async refresh(el, force) {
    if (!force) return;
    const g = await api("/api/brain/graph");
    const svg = $("[data-graph]", el); const w = svg.clientWidth || 800, h = svg.clientHeight || 560;
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    const q = ($("#bsearch", el).value || "").toLowerCase();
    const pos = layout(g, w, h);
    const vis = (n) => (!this.team || n.team === this.team) && (!q || n.title.toLowerCase().includes(q));
    svg.innerHTML = g.edges.filter((e) => pos[e.from] && pos[e.to]).map((e) => `<line x1="${pos[e.from].x}" y1="${pos[e.from].y}" x2="${pos[e.to].x}" y2="${pos[e.to].y}" stroke="#3A3834" stroke-width="1"/>`).join("") +
      g.nodes.map((n) => { const p = pos[n.id], r = 5 + Math.min(10, n.degree * 1.6) + (n.pinned ? 2 : 0), on = vis(n);
        return `<g class="n" data-id="${esc(n.id)}" opacity="${on ? 1 : 0.15}" tabindex="0" role="button" aria-label="${esc(n.title)}">${n.id === this.sel ? `<circle cx="${p.x}" cy="${p.y}" r="${r + 7}" fill="none" stroke="${TEAMC[n.team]}" stroke-width="1.5" opacity=".6"/>` : ""}<circle cx="${p.x}" cy="${p.y}" r="${r}" fill="${TEAMC[n.team]}"/>${r > 8 || n.id === this.sel ? `<text x="${p.x}" y="${p.y + r + 14}" text-anchor="middle">${esc(n.title)}</text>` : ""}</g>`; }).join("");
    this.g = g;
    if (this.sel) this.open(el, this.sel);
  },
  async open(el, slug) {
    this.sel = slug;
    const n = await api(`/api/brain/note/${encodeURIComponent(slug)}`);
    const writer = { shared: "Agent", production: "Production crew", coding: "Coding crew", learning: "Anyone" }[n.team];
    $("[data-note]", el).innerHTML = `<div class="row"><b style="font-size:15px" class="grow">${esc(n.title)}</b><span class="pill" style="color:${TEAMC[n.team]}">${esc(n.team)}</span></div>
      <textarea data-body rows="14" class="notebody" style="width:100%">${esc(n.body)}</textarea>
      <div class="col small sub" style="gap:4px"><div class="row"><span>Written by</span><span style="margin-left:auto;color:var(--paper)">${esc(n.by || "—")} · ${esc(n.updated)}</span></div>
        <div class="row"><span>Can edit</span><span style="margin-left:auto;color:var(--paper)">${writer} (and you)</span></div><div class="row"><span>Can read</span><span style="margin-left:auto;color:var(--paper)">Everyone</span></div>
        <div class="row"><span>Links</span><span style="margin-left:auto">${n.links.map((l) => `<button class="btn sm" data-goto="${esc(l)}">${esc(l)}</button>`).join(" ") || "—"}</span></div></div>
      <div class="row"><button class="btn paper" data-save="${esc(n.slug)}" data-team="${n.team}" data-title="${esc(n.title)}">Save</button><button class="btn" data-pin="${esc(n.slug)}" data-on="${!n.pinned}">${n.pinned ? "Unpin" : "Pin"}</button><button class="btn" data-forget="${esc(n.slug)}">Forget</button></div>
      <p class="small sub">Use [[Note title]] to link notes. Pinned notes are always in the agents' context.</p>`;
  },
  bind(el) {
    el.addEventListener("click", async (e) => {
      const n = e.target.closest(".n"); if (n) { this.open(el, n.dataset.id); return this.refresh(el, true); }
      const t = e.target.closest("button"); if (!t) return;
      if (t.dataset.t != null) { this.team = t.dataset.t; $$("[data-t]", el).forEach((b) => b.setAttribute("aria-selected", b === t)); this.refresh(el, true); }
      if (t.dataset.goto) { this.open(el, t.dataset.goto); this.refresh(el, true); }
      if (t.dataset.save) { await guard(() => post("/api/brain/note", { title: t.dataset.title, team: t.dataset.team, body: $("[data-body]", el).value })); toast("Saved to the brain"); this.refresh(el, true); }
      if (t.dataset.pin) { await guard(() => post(`/api/brain/note/${t.dataset.pin}/pin`, { on: t.dataset.on === "true" })); this.refresh(el, true); }
      if (t.dataset.forget && confirm("Forget this note? The agents won't know it anymore.")) { await guard(() => api(`/api/brain/note/${t.dataset.forget}`, { method: "DELETE" })); this.sel = null; $("[data-note]", el).innerHTML = ""; this.refresh(el, true); }
      if (t.dataset.new != null) {
        const title = prompt("Note title"); if (!title) return;
        const team = prompt("Team: shared, production, coding or learning", "shared"); if (!team) return;
        await guard(() => post("/api/brain/note", { title, team, body: "" })); this.refresh(el, true);
      }
    });
    el.addEventListener("mousemove", (e) => {
      const n = e.target.closest(".n"), tip = $("[data-tip]", el); if (!tip) return;
      if (!n) return tip.classList.add("hidden");
      const node = (this.g?.nodes || []).find((x) => x.id === n.dataset.id); if (!node) return;
      const r = el.querySelector(".main").getBoundingClientRect();
      tip.innerHTML = `<b>${esc(node.title)}</b><div class="sub">${esc(node.team)} · ${node.degree} links · ${esc(node.by || "")}</div>`;
      tip.style.left = e.clientX - r.left + 14 + "px"; tip.style.top = e.clientY - r.top + 10 + "px"; tip.classList.remove("hidden");
    });
    el.addEventListener("input", (e) => { if (e.target.id === "bsearch") this.refresh(el, true); });
  },
};

// ------------------------------------------------------------------ Coding crew
export const coding = {
  render(el) {
    el.innerHTML = header("Coding crew", "Ask how the app works (they read the real code) or describe a change · Planner, Coder, Designer",
      `<span class="row">${av("Planner", 26)}${av("Coder", 26)}${av("Designer", 26)}</span>`) +
      `<div class="page"><div class="split" style="height:100%"><section class="main" data-room style="height:100%"></section>
       <aside class="sidepanel" aria-label="Changes"><b>Changes</b><div data-changes class="col"></div>
         <div class="card pad col small mut"><b style="color:var(--paper);font-size:13px">Safe by default</b><div>Works on a separate copy of the app</div><div>Nothing changes until you press Apply</div><div>Every change can be undone in one click</div><div>Only touches the engine and screens, never the app shell</div></div></aside></div></div>`;
    chatRoom($("[data-room]", el), "coding", { placeholder: "Ask how the app works, or describe a change · @Planner @Coder @Designer",
      suggestions: ["Add a calendar page with every scheduled post this week", "Make the clip cards show which account they went to", "Add a dark/light toggle"] });
    this.refresh(el);
  },
  async refresh(el) {
    const list = await api("/api/changes");
    const cls = { applied: "ok", review: "acc", failed: "bad", undone: "", discarded: "", building: "warn", concepts: "warn", waiting_ok: "warn" };
    $("[data-changes]", el).innerHTML = list.map((c) => `<div class="card pad col" style="gap:6px"><div class="row"><b class="small grow">#${c.id} ${esc(c.request.replace(/^\[app\] Handoff from [^:]+: /, "").slice(0, 70))}</b><span class="pill ${cls[c.status] || ""}">${esc(c.status.replace("_", " "))}</span></div>
      ${(c.plan.steps || []).length ? `<div class="small sub">${c.plan.steps.length} steps · ${(c.plan.files || []).join(", ")}</div>` : ""}
      <div class="row">${["review", "applied"].includes(c.status) ? `<button class="btn sm" data-rev="${c.id}">${c.status === "review" ? "Review" : "Details / Undo"}</button>` : ""}</div></div>`).join("") || `<span class="small sub">No changes yet.</span>`;
  },
  bind(el) {
    el.addEventListener("click", (e) => { const t = e.target.closest("[data-rev]"); if (t) reviewChange(+t.dataset.rev); });
  },
};

// ------------------------------------------------------------------ Settings
export const settings = {
  render(el) {
    el.innerHTML = header("Settings", "", `<span class="small sub">Changes save automatically</span>`) + `<div class="page"><div class="pagepad" data-body style="max-width:860px"></div></div>`;
    this.refresh(el, true);
  },
  async refresh(el, force) {
    if (!force) return;
    const s = await api("/api/settings");
    const row = (title, sub, ctrl) => `<div class="row" style="gap:16px"><div style="flex:1 1 260px"><div style="font-weight:500">${title}</div><div class="small sub">${sub}</div></div>${ctrl}</div>`;
    const inp = (sec, key, v, type = "text", w = 240) => `<input data-s="${sec}.${key}" type="${type}" value="${esc(v ?? "")}" style="width:${w}px">`;
    const sel = (sec, key, v, opts) => `<select data-s="${sec}.${key}">${opts.map(([val, l]) => `<option value="${val}" ${String(val) === String(v) ? "selected" : ""}>${l}</option>`).join("")}</select>`;
    const sect = (t, body) => `<section class="card"><div class="pad" style="border-bottom:1px solid var(--line);font-weight:600">${t}</div><div class="pad col" style="gap:16px">${body}</div></section>`;
    $("[data-body]", el).innerHTML =
      sect("Clipping", row("Mode", "Campaigns pay at any length. TikTok Creator Rewards only pays on videos over 1 minute.", sel("clipping", "monetization_mode", s.clipping.monetization_mode, [[false, "Campaign · 20–60s"], [true, "Monetization · 61–90s"]]))
        + row("Clips per video", "How many candidates are cut from each stream", inp("clipping", "clips_per_source", s.clipping.clips_per_source ?? 5, "number", 90)))
      + sect("Look", row("Default layout", "The crew can still pick per clip", sel("render", "layout", s.render.layout, [["blur", "Blurred background"], ["facecam", "Facecam on top"], ["split", "Split-screen + filler"], ["crop", "Zoomed crop"], ["bubble", "Reaction bubble"]]))
        + row("Burned-in captions", "Word by word, 3 words at a time", sel("render", "captions", s.render.captions ?? true, [[true, "On"], [false, "Off"]]))
        + row("Watermark", "Small text at the bottom of every clip", inp("render", "watermark", s.render.watermark))
        + row("App accent color", "Ink and paper stay; pick the bright color", sel("ui", "accent", s.ui.accent || "#2F7BFF", [["#2F7BFF", "Lightning blue"], ["#FF3347", "Shiny red"]])))
      + sect("Italy box & network", row("Italy box proxy", "From the Italy box setup, e.g. socks5://100.101.102.103:1080", inp("network", "italy_box_proxy", s.network.italy_box_proxy, "text", 300))
        + row("Expected country", "The crew refuses to post if traffic leaves from somewhere else", inp("network", "expect_country", s.network.expect_country, "text", 80)))
      + sect("Autopilot", row("Time zone", "Your brother's local time", inp("autopilot", "timezone", s.autopilot.timezone, "text", 200)) + `<p class="small sub" style="margin:0">Posting window and rules are on the <a href="#/autopilot">Autopilot</a> page.</p>`)
      + sect("Phone", row("Phone serial", "Only if more than one Android is plugged in", inp("phone", "serial", s.phone.serial)) + row("Edits package", "Leave empty to detect it", inp("phone", "edits_package", s.phone.edits_package)))
      + sect("Research", row("Web search", "DuckDuckGo needs no key", sel("research", "provider", s.research.provider, [["ddgs", "DuckDuckGo"], ["brave", "Brave Search API"]])) + row("Brave API key", "Only for Brave", inp("research", "brave_key", s.research.brave_key, "password")))
      + sect("Browser", row("Account tabs", "Inside the app on Windows; separate windows elsewhere", sel("browser", "mode", s.browser.mode || "auto", [["auto", "Automatic"], ["app", "Only inside the app"], ["standalone", "Separate windows"]])))
      + sect("Engine", `<div class="small sub">Videos: <code>${esc(state.status?.assets || "")}</code></div><div class="row"><button class="btn" data-assets>Open assets folder</button><button class="btn" data-restart>Restart engine</button></div>`);
  },
  bind(el) {
    el.addEventListener("change", async (e) => {
      const t = e.target; if (!t.dataset.s) return;
      const [section, key] = t.dataset.s.split(".");
      let value = t.type === "number" ? +t.value : t.value;
      if (value === "true") value = true; if (value === "false") value = false;
      await guard(() => post("/api/settings", { section, key, value }));
      if (section === "ui" && key === "accent") setAccent(value);
      toast("Saved");
    });
    el.addEventListener("click", (e) => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.dataset.assets != null) reveal(state.status.assets);
      if (t.dataset.restart != null) restartEngine();
    });
  },
};
