// Live pages: Browser (account tabs), Phone, Autopilot, Daily report.
import { $, $$, API, ICON, TAURI, ago, api, av, esc, guard, header, invoke, num, post, reveal, state, stepRow, toast } from "./core.js";

const actState = (s) => ({ done: "done", now: "now", retry: "waiting", failed: "failed", paused: "waiting", waiting: "waiting" }[s] || "done");

// ------------------------------------------------------------------ Browser
export const browser = {
  key: null,
  render(el) {
    el.innerHTML = `<div class="tabs" role="tablist" aria-label="Account tabs" data-tabs></div>
      <div class="row" style="padding:8px 16px;background:var(--surf);border-bottom:1px solid var(--line);flex:none">
        <span class="grow mono mut" data-url style="height:30px;display:flex;align-items:center;padding:0 12px;border-radius:7px;background:var(--panel);border:1px solid var(--line2)">—</span>
        <span class="small" data-net></span>
        <button class="btn" data-open>${TAURI ? "Open in the browser window" : "Open in a new tab"}</button></div>
      <div class="page"><div class="split" style="min-height:100%"><section class="main" style="padding:20px;background:var(--panel)">
        <div class="mirror" data-mirror><div class="empty">The crew's view of this tab shows here while they work.</div></div>
        <form class="row" data-ask style="margin-top:12px"><label class="sr" for="tabask">Ask the crew to do something in this tab</label>
          <input id="tabask" class="grow" placeholder="Ask the crew to do something in this tab, e.g. check the last 3 posts went live">
          <select data-who aria-label="Who"><option>Clipper A</option><option>Clipper B</option></select><button class="btn pri">Do it</button></form></section>
      <aside class="sidepanel" aria-label="Agent activity"><div class="row" data-who-now><b>Activity</b></div><div class="steps" data-steps></div>
        <div class="row"><button class="btn" data-pause>Pause everything</button><button class="btn" data-take>Take over</button></div>
        <div style="border-top:1px solid var(--line);padding-top:14px" class="col"><b class="small">Ready to drop</b><div data-files class="col"></div></div>
        <p class="small sub" style="margin-top:auto">In these tabs the crew uploads, edits in the site's editor, writes captions, schedules, posts and reads stats. It doesn't browse around, message or follow anyone.</p></aside></div></div>`;
    this.refresh(el, true);
  },
  async refresh(el) {
    const tabs = await api("/api/tabs");
    if (!tabs.length) { $("[data-tabs]", el).innerHTML = `<span class="small sub" style="padding:8px">No accounts yet. Add them on the Channels page.</span>`; return; }
    if (!this.key || !tabs.find((t) => t.key === this.key)) this.key = tabs[0].key;
    const dotc = { tiktok: "var(--paper)", instagram: "#E1306C", youtube: "var(--bad)" };
    $("[data-tabs]", el).innerHTML = tabs.map((t) => `<button class="tab" role="tab" aria-selected="${t.key === this.key}" data-tab="${esc(t.key)}"><span class="dot" style="border-radius:2px;background:${dotc[t.platform]}"></span>${esc(t.key)}${t.agent ? av(t.agent, 16) : ""}</button>`).join("");
    const t = tabs.find((x) => x.key === this.key);
    $("[data-url]", el).textContent = t.upload_url;
    const net = state.status?.italy_box || {};
    $("[data-net]", el).innerHTML = t.proxy ? (net.ok ? `<span class="ok-t">● Italy box · ${esc(net.city || "")}</span>` : `<span class="bad-t">● Italy box offline</span>`) : `<span class="warn-t">● direct (no proxy)</span>`;
    const acts = await api(`/api/tabs/${encodeURIComponent(this.key)}/activity`);
    const who = acts[0]?.who;
    $("[data-who-now]", el).innerHTML = who && Date.now() / 1000 - acts[0].created_at < 120 ? `${av(who)}<b>${esc(who)} in this tab</b>` : `<b>Activity</b><span class="small sub">${acts[0] ? "last " + ago(acts[0].created_at) : "nothing yet"}</span>`;
    $("[data-steps]", el).innerHTML = acts.slice(0, 10).reverse().map((a) => stepRow(actState(a.state), a.step)).join("") || `<span class="small sub">No tasks in this tab yet.</span>`;
    if (acts[0]) $("[data-mirror]", el).innerHTML = `<img alt="What the crew sees in ${esc(this.key)}" src="${API}/api/tabs/${encodeURIComponent(this.key)}/shot?t=${acts[0].id}">`;
    const ready = await api("/api/clips?status=approved");
    $("[data-files]", el).innerHTML = ready.slice(0, 5).map((c) => `<button class="row card" style="padding:8px 10px;color:var(--paper);text-align:left" data-file="${c.id}">${ICON.file}<span class="mono">#${c.id}</span><span class="small mut grow">${esc(c.title.slice(0, 40))}</span></button>`).join("") || `<span class="small sub">Approved clips show here.</span>`;
  },
  bind(el) {
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.dataset.tab) { this.key = t.dataset.tab; this.refresh(el); }
      if (t.dataset.open != null) {
        const tab = (await api("/api/tabs")).find((x) => x.key === this.key);
        if (TAURI) guard(() => invoke("open_browser", { tab: this.key })); else window.open(tab.upload_url, "_blank");
      }
      if (t.dataset.take != null) { await guard(() => post(`/api/tabs/${encodeURIComponent(this.key)}/takeover`)); if (TAURI) invoke("open_browser", { tab: this.key }); toast("The crew stopped. The tab is yours."); }
      if (t.dataset.pause != null) { await guard(() => post("/api/autopilot/pause", { on: true })); toast("Everything paused. Resume on the Autopilot page."); }
      if (t.dataset.file) { const r = await guard(() => post(`/api/clips/${t.dataset.file}/export`)); if (r) reveal(r.path); }
    });
    el.addEventListener("submit", async (e) => {
      if (!e.target.matches("[data-ask]")) return; e.preventDefault();
      const goal = $("#tabask", el).value.trim(); if (!goal) return;
      await guard(() => post(`/api/tabs/${encodeURIComponent(this.key)}/task`, { goal, who: $("[data-who]", el).value }));
      $("#tabask", el).value = ""; toast("On it. Watch the activity on the right.");
    });
  },
};

// ------------------------------------------------------------------ Phone
export const phone = {
  render(el) {
    el.innerHTML = header("Phone", `<span data-model>Android over USB</span>`, `<button class="btn" data-pause>Pause</button><button class="btn" data-shot>Refresh screen</button>`) +
      `<div class="page"><div class="pagepad"><div class="row" style="align-items:flex-start;gap:24px">
        <section class="col" style="align-items:center;flex:none"><div class="phoneframe" data-screen><span class="small sub" style="padding:20px;text-align:center">Phone screen shows here</span></div><span class="small sub">Live mirror</span></section>
        <section class="col grow" style="min-width:300px"><div class="card pad col"><div class="row" data-who><b>What the crew is doing</b></div><div class="steps" data-steps></div></div>
          <form class="card pad col" data-ask><b>Ask the crew to do something on the phone</b><label class="sr" for="phask">Task</label><input id="phask" placeholder="e.g. open Edits and check the drafts"><div class="row"><select data-wh aria-label="Who"><option>Clipper B</option><option>Clipper A</option></select><button class="btn pri">Do it</button></div></form></section>
        <aside class="card pad col" style="flex:1 1 260px;max-width:340px" data-status><b>Phone status</b></aside></div></div></div>`;
    this.refresh(el, true);
  },
  async refresh(el, first) {
    const [s, acts] = await Promise.all([api("/api/phone/status"), api("/api/phone/activity")]);
    const kv = (k, v, c = "") => `<div class="row small"><span class="sub">${k}</span><span class="${c}" style="margin-left:auto">${esc(v)}</span></div>`;
    $("[data-model]", el).textContent = s.connected ? `${s.model} · USB` : "No phone connected";
    $("[data-status]", el).innerHTML = `<b>Phone status</b>` + (s.connected ? kv("Connection", "USB · connected", "ok-t") + kv("Internet", s.vpn ? "through a VPN (Italy box)" : "NOT through the Italy box", s.vpn ? "ok-t" : "bad-t")
      + kv("Battery", `${s.battery}${s.charging ? " · charging" : ""}`) + kv("Free space", s.free) + kv("Edits app", s.edits || "not found", s.edits ? "" : "warn-t")
      : `<p class="small bad-t">${esc(s.error)}</p><ol class="small mut"><li>Settings → About phone → tap Build number 7 times</li><li>Developer options → turn on USB debugging</li><li>Plug the phone into this PC and tap Allow</li><li>Tailscale app: use the Italy box as exit node</li></ol>`);
    $("[data-steps]", el).innerHTML = acts.slice(0, 10).reverse().map((a) => stepRow(actState(a.state), a.step)).join("") || `<span class="small sub">Nothing yet.</span>`;
    $("[data-who]", el).innerHTML = acts[0] && Date.now() / 1000 - acts[0].created_at < 120 ? `${av(acts[0].who)}<b>${esc(acts[0].who)} on the phone</b><span class="small sub" style="margin-left:auto">${esc(acts[0].task.slice(0, 60))}</span>` : `<b>What the crew is doing</b>`;
    if (s.connected && (first || (acts[0] && Date.now() / 1000 - acts[0].created_at < 120))) $("[data-screen]", el).innerHTML = `<img alt="Phone screen" src="${API}/api/phone/shot?fresh=${first ? 1 : 0}&t=${Date.now()}">`;
  },
  bind(el) {
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.dataset.pause != null) { await guard(() => post("/api/autopilot/pause", { on: true })); toast("Paused"); }
      if (t.dataset.shot != null) this.refresh(el, true);
    });
    el.addEventListener("submit", async (e) => {
      if (!e.target.matches("[data-ask]")) return; e.preventDefault();
      const goal = $("#phask", el).value.trim(); if (!goal) return;
      await guard(() => post("/api/phone/task", { goal, who: $("[data-wh]", el).value })); toast("On it");
    });
  },
};

// ------------------------------------------------------------------ Autopilot
const methodLabel = { native: "scheduled inside the app", phone: "phone · Edits", tab: "account tab", api: "API" };
const itemCls = (s) => ({ posted: "ok-t", scheduled: "ok-t", failed: "bad-t", needs_you: "warn-t", working: "acc-t" }[s] || "sub");
export const autopilot = {
  render(el) {
    el.innerHTML = header("Autopilot", "Approve tomorrow's plan tonight. The crew schedules and posts, you check in whenever you want.",
      `<label class="row small" style="font-weight:600"><input type="checkbox" role="switch" data-on> Autopilot on</label><button class="btn danger" data-pause>Pause everything</button>`) +
      `<div class="page"><div class="pagepad"><div class="row" style="align-items:flex-start;gap:24px">
        <section class="col grow" style="min-width:560px">
          <div class="card"><div class="row pad" style="border-bottom:1px solid var(--line)"><div class="grow"><b>Tomorrow</b><div class="small sub" data-sum></div></div><button class="btn" data-build>Rebuild plan</button><button class="btn pri" data-approve>Approve plan</button></div>
            <div class="scrollx"><table class="table" data-tom></table></div></div>
          <div class="card"><div class="pad" style="border-bottom:1px solid var(--line)"><b>Today</b></div><div class="scrollx"><table class="table" data-today></table></div></div>
          <div class="card pad col" data-rules></div></section>
        <aside class="col" style="flex:1 1 320px;max-width:380px">
          <div class="card pad col"><div class="row"><b>Live now</b><span class="dot" style="background:var(--ok)"></span></div><div data-live class="col small"></div></div>
          <form class="card pad col" data-fb><b>Feedback</b><label class="sr" for="apfb">Feedback</label><textarea id="apfb" rows="3" placeholder="Anything about a clip, a caption or a time. The crew fixes it before the next post."></textarea><button class="btn">Send to crew</button></form></aside></div></div></div>`;
    this.refresh(el, true);
  },
  async refresh(el, first) {
    const s = await api("/api/autopilot");
    $("[data-on]", el).checked = s.enabled;
    const p = $("[data-pause]", el); p.textContent = s.paused ? "Resume" : "Pause everything"; p.className = s.paused ? "btn pri" : "btn danger";
    const rows = (items) => items.length ? `<thead><tr><th>Time</th><th>Account</th><th>Clip</th><th>How</th><th>Crew</th><th>Status</th><th></th></tr></thead><tbody>${items.map((i) => `<tr>
      <td class="mono mut">${esc(i.at)}</td><td><b style="font-weight:500">${esc(i.channel)}</b></td><td class="mut">#${i.clip_id} ${esc((i.title || "").slice(0, 44))}</td>
      <td class="mut small">${methodLabel[i.method] || i.method}${i.method === "native" ? ` <span class="ok-t">· PC can be off</span>` : ` <span class="warn-t">· PC on</span>`}</td><td>${av(i.crew, 20)}</td>
      <td class="small ${itemCls(i.status)}">${esc(i.status.replace("_", " "))}${i.message ? `<div class="tiny sub">${esc(i.message.slice(0, 80))}</div>` : ""}</td>
      <td>${["draft", "waiting"].includes(i.status) ? `<button class="btn sm" data-skip="${i.id}">Skip</button>` : ["failed", "needs_you"].includes(i.status) ? `<button class="btn sm" data-retry="${i.id}">Retry</button>` : ""}</td></tr>`).join("")}</tbody>`
      : `<tbody><tr><td class="empty">Nothing planned. Approve clips, then Rebuild plan.</td></tr></tbody>`;
    $("[data-tom]", el).innerHTML = rows(s.tomorrow);
    $("[data-today]", el).innerHTML = rows(s.today);
    const native = s.tomorrow.filter((i) => i.method === "native").length;
    const approved = s.tomorrow.length && s.tomorrow.every((i) => i.status !== "draft");
    $("[data-sum]", el).textContent = `${s.tomorrow.length} posts · ${s.timezone} · ${native} go out even if the PC is off` + (approved ? " · approved ✓" : "");
    $("[data-approve]", el).disabled = !s.tomorrow.length || approved;
    if (first) {
      const st = await api("/api/settings"); const a = st.autopilot || {};
      $("[data-rules]", el).innerHTML = `<b>Rules the crew follows</b>
        <div class="row small"><label class="f">Post from<input type="time" data-set="window_start" value="${esc(a.window_start)}"></label><label class="f">until<input type="time" data-set="window_end" value="${esc(a.window_end)}"></label>
        <label class="f">Max per account per day<input type="number" min="1" max="6" data-set="max_per_account_per_day" value="${a.max_per_account_per_day}" style="width:80px"></label>
        <label class="f">Minutes between posts<input type="number" min="5" data-set="gap_minutes" value="${a.gap_minutes}" style="width:80px"></label>
        <label class="f">Ask me under score<input type="number" step="0.5" data-set="min_score" value="${a.min_score}" style="width:80px"></label></div>
        <label class="row small mut"><input type="checkbox" data-set="require_italy_box" ${a.require_italy_box ? "checked" : ""}> Never post if the Italy box is offline</label>`;
    }
    const tabs = await api("/api/tabs").catch(() => []);
    const live = tabs.filter((t) => t.agent);
    $("[data-live]", el).innerHTML = live.map((t) => `<div class="row">${av(t.agent, 22)}<span class="mut grow">${esc(t.last.step.slice(0, 60))} · <a href="#/browser">${esc(t.key)}</a></span></div>`).join("") || `<span class="sub">The crew is idle.</span>`;
  },
  bind(el) {
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.dataset.build != null) { await guard(() => post("/api/autopilot/plan", {})); this.refresh(el); }
      if (t.dataset.approve != null) { if (!confirm("Approve tomorrow's plan? The crew starts scheduling the TikTok and YouTube posts now.")) return; await guard(() => post("/api/autopilot/approve", {})); this.refresh(el); }
      if (t.dataset.pause != null) { const s = await api("/api/autopilot"); await guard(() => post("/api/autopilot/pause", { on: !s.paused })); this.refresh(el); }
      if (t.dataset.skip) { await guard(() => api(`/api/autopilot/items/${t.dataset.skip}`, { method: "PATCH", body: { status: "skipped" } })); this.refresh(el); }
      if (t.dataset.retry) { await guard(() => api(`/api/autopilot/items/${t.dataset.retry}`, { method: "PATCH", body: { status: "waiting" } })); toast("Queued again"); this.refresh(el); }
    });
    el.addEventListener("change", async (e) => {
      const t = e.target;
      if (t.matches("[data-on]")) { await guard(() => post("/api/autopilot/enabled", { on: t.checked })); toast(t.checked ? "Autopilot on" : "Autopilot off"); }
      if (t.dataset.set) { const v = t.type === "checkbox" ? t.checked : t.type === "number" ? +t.value : t.value; await guard(() => post("/api/settings", { section: "autopilot", key: t.dataset.set, value: v })); toast("Saved"); }
    });
    el.addEventListener("submit", async (e) => {
      if (!e.target.matches("[data-fb]")) return; e.preventDefault();
      const text = $("#apfb", el).value.trim(); if (!text) return;
      await guard(() => post("/api/crew/feedback", { text, target: "publish plan" })); $("#apfb", el).value = ""; toast("Sent to the crew");
    });
  },
};

// ------------------------------------------------------------------ Daily report
export const report = {
  render(el) {
    el.innerHTML = header("Daily report", `<span data-day></span>`, `<button class="btn" data-refresh>Write it again</button>`) + `<div class="page"><div class="pagepad" data-body></div></div>`;
    this.refresh(el);
  },
  async refresh(el, force) {
    const r = await api("/api/report" + (force ? "?refresh=true" : ""));
    $("[data-day]", el).textContent = r.day;
    const tile = (k, v, s, c = "mut") => `<div class="card pad tile"><div class="k">${k}</div><div class="v">${v}</div><div class="small ${c}">${s}</div></div>`;
    const nb = r.italy_box || {};
    $("[data-body]", el).innerHTML = `<section class="tiles">${tile("Posted", `${r.posted} of ${r.planned}`, r.failed.length ? `${r.failed.length} need you` : "all good", r.failed.length ? "warn-t" : "ok-t")}
        ${tile("Campaign earnings", "$" + (r.money?.earned ?? 0), "all campaigns, entered/read")}${tile("Campaign views", num(r.money?.views), "counted by campaigns")}
        ${tile("Italy box", nb.ok ? "Online" : "Offline", nb.ok ? `${esc(nb.city)}, ${esc(nb.country)}` : esc(nb.error || ""), nb.ok ? "ok-t" : "bad-t")}</section>
      <div class="row" style="align-items:flex-start;gap:16px"><section class="card grow" style="min-width:420px"><div class="pad" style="border-bottom:1px solid var(--line)"><b>Posts</b></div>
        <table class="table"><tbody>${r.items.map((i) => `<tr><td class="mono mut">${esc(i.at)}</td><td>${esc(i.channel)}</td><td class="mut">#${i.clip_id} ${esc((i.title || "").slice(0, 40))}</td><td class="small ${itemCls(i.status)}">● ${esc(i.status.replace("_", " "))}</td></tr>`).join("") || `<tr><td class="empty">Nothing planned for this day.</td></tr>`}</tbody></table></section>
      <aside class="col" style="flex:1 1 320px;max-width:400px">${r.failed.map((f) => `<div class="card pad col" style="border-color:#4A2228;background:#1A1114"><b class="bad-t">${esc(f.channel)} · not posted</b><span class="small mut">${esc(f.message || "")}</span><div class="row"><button class="btn pri sm" data-retry="${f.id}">Retry</button><a class="btn sm" href="#/browser" style="text-decoration:none">I'll post it</a></div></div>`).join("")}
        <div class="card pad col"><b>Crew notes</b>${(r.notes || []).slice(0, 5).map((n) => `<div class="small mut">${esc(n.slice(0, 180))}</div>`).join("") || `<span class="small sub">No notes today.</span>`}</div>
        <div class="card pad col"><b>Monetization progress</b>${(r.money?.progress || []).flatMap((p) => p.metrics.filter((m) => m.goal).map((m) => `<div class="row small"><span class="sub">${esc(p.channel)} · ${esc(m.label)}</span><span style="margin-left:auto">${num(m.value)} / ${num(m.goal)}</span></div>`)).join("") || `<span class="small sub">Check accounts on the Monetization page.</span>`}</div></aside></div>`;
  },
  bind(el) {
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.dataset.refresh != null) this.refresh(el, true);
      if (t.dataset.retry) { await guard(() => api(`/api/autopilot/items/${t.dataset.retry}`, { method: "PATCH", body: { status: "waiting" } })); toast("Queued again"); }
    });
  },
};
