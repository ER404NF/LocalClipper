// Work pages: Agent, Production crew, Edit & review, Pipeline, Clips.
import { $, $$, API, api, av, esc, guard, header, num, post, reveal, state, stepRow, toast } from "./core.js";
import { chatRoom } from "./components.js";

const STAGES = [["finding", "1 · Finding"], ["clipping", "2 · Clipping"], ["editing", "3 · Editing"], ["publishing", "4 · Publishing"]];
const stLabel = (s) => ({ ready: "needs review", edited: "edited · review", queued_edit: "waiting to edit", editing: "editing" }[s] || s);
const stClass = (s) => (s === "error" || s === "failed" ? "bad-t" : s === "posted" ? "ok-t" : s === "ready" || s === "edited" ? "warn-t" : s === "approved" ? "acc-t" : "sub");

// ------------------------------------------------------------------ Agent
export const agent = {
  render(el) {
    el.innerHTML = header("Agent", `Runs on this computer · ${esc(state.status?.model || "")} via Ollama`, `<button class="btn" data-clear>New chat</button>`) +
      `<div class="page"><div class="split" style="height:100%"><section class="main" data-room style="height:100%"></section>
       <aside class="sidepanel" aria-label="Live pipeline"><div class="row"><b>Pipeline</b><span class="dot" style="background:var(--ok)"></span><span class="small sub">live</span><a href="#/pipeline" class="small" style="margin-left:auto">Open board</a></div>
       <div data-mini class="col"></div>
       <div style="border-top:1px solid var(--line);padding-top:14px" class="col"><div class="row"><b>Needs review</b><a href="#/clips" class="small" style="margin-left:auto">All</a></div><div data-review class="col"></div></div></aside></div></div>`;
    chatRoom($("[data-room]", el), "agent", { placeholder: "Ask the agent anything, or tell it what you want the crews to do…",
      suggestions: ["What's the status?", "What did the crew post today?", "Ask the crew to hunt today's best clips", "Remember: kaicenat clips do best at 19:00"] });
    $("[data-clear]", el).onclick = async () => { await guard(() => api("/api/chat?room=agent", { method: "DELETE" })); agent.render(el); };
    this.refresh(el);
  },
  async refresh(el) {
    const b = await api("/api/board");
    const total = (k) => (b[k] || []).length;
    $("[data-mini]", el).innerHTML = STAGES.map(([k, t]) => `<div class="col" style="gap:5px"><div class="row small"><span class="mut">${t}</span><b style="margin-left:auto">${total(k)}</b></div>
      <div class="bar" style="height:4px"><span style="width:${Math.min(100, total(k) * 25)}%"></span></div>
      <div class="small sub">${esc((b[k] || [])[0] ? (b[k][0].label + " · " + (b[k][0].detail || stLabel(b[k][0].status))) : "nothing right now").slice(0, 70)}</div></div>`).join("");
    const rev = (b.publishing || []).filter((i) => i.status === "ready" || i.status === "edited").slice(0, 4);
    $("[data-review]", el).innerHTML = rev.map((i) => `<a href="#/clips" class="row" style="text-decoration:none"><span class="thumb" style="width:30px;height:52px"></span><span class="grow"><span style="display:block;font-weight:500;font-size:13px">${esc(i.detail || i.label)}</span><span class="small sub">${esc(i.label)}</span></span><span class="small warn-t">${(i.score || 0).toFixed(1)}</span></a>`).join("") || `<span class="small sub">Nothing waiting.</span>`;
  },
};

// ------------------------------------------------------------------ Production crew
function crewPhase(b, chat) {
  const busy = [...(b.finding || []), ...(b.clipping || [])].length;
  if (busy) return 0;
  const waitingPick = chat.some((r) => (r.data || {}).shortlist);
  const editing = (b.editing || []).some((i) => ["queued_edit", "editing"].includes(i.status));
  const edited = (b.publishing || []).some((i) => i.status === "edited");
  if (editing) return 3; if (edited) return 4;
  if ((b.publishing || []).some((i) => i.status === "approved")) return 5;
  return waitingPick ? 2 : 0;
}
export const crew = {
  render(el) {
    el.innerHTML = header("Production crew", "Two clippers hunting, cutting, reviewing each other and posting",
      `<ol class="row small" data-steps style="list-style:none;margin:0;padding:0"></ol><button class="btn pri" data-hunt>Start a hunt</button><a class="btn" href="#/review" style="text-decoration:none">Edit &amp; review</a>`) +
      `<div class="page"><div class="split" style="height:100%"><section class="main" data-room style="height:100%"></section>
       <aside class="sidepanel" aria-label="Crew status"><b>Crew</b><div data-crew class="col"></div>
       <div style="border-top:1px solid var(--line);padding-top:14px" class="col small"><b style="font-size:13px">Crew rules</b>
         <div class="mut">✓ Review each other's clips before showing you</div><div class="mut">✓ Only streamers on your campaign list</div>
         <div class="mut">✓ Ask you before editing and before posting</div><div class="mut">✓ Never post without the Italy box</div></div></aside></div></div>`;
    this.room = chatRoom($("[data-room]", el), "production", { placeholder: "Talk to the crew… @A or @B for one of them",
      suggestions: ["Hunt today's best GTA 6 moments from our streamers", "@B research how top GTA 6 clip pages edit this week", "Use split-screen when the clip has slow parts"] });
    $("[data-hunt]", el).onclick = async () => { await guard(() => post("/api/crew/hunt", {})); toast("Hunt started. The crew reports in the room."); };
    this.refresh(el);
  },
  async refresh(el) {
    const [b, chat, tabs] = await Promise.all([api("/api/board"), api("/api/chat?room=production"), api("/api/tabs").catch(() => [])]);
    const phase = crewPhase(b, chat);
    $("[data-steps]", el).innerHTML = ["Hunt", "Cross-review", "Your pick", "Edit", "Your feedback", "Publish"].map((s, i) =>
      `<li class="${i < phase ? "ok-t" : i === phase ? "" : "sub"}" style="${i === phase ? "background:var(--accent);color:var(--ink);font-weight:600;border-radius:99px;padding:3px 10px" : ""}">${i < phase ? "✓ " : ""}${s}</li>`).join(`<li class="sub">—</li>`);
    const acts = await api("/api/tabs").catch(() => []);
    const st = state.status || {};
    const streamers = st.streamers || [];
    const chans = (st.channels || []).map((c) => c.key).sort();
    $("[data-crew]", el).innerHTML = ["Clipper A", "Clipper B"].map((who, n) => {
      const mineTabs = chans.filter((_, i) => i % 2 === n);
      const live = acts.find((t) => t.agent === who);
      const lastMsg = [...chat].reverse().find((r) => r.author === who && r.content);
      return `<div class="card pad col" style="gap:8px"><div class="row">${av(who)}<b>${who}</b><span class="small ${live ? "acc-t" : "ok-t"}" style="margin-left:auto">● ${live ? "in " + esc(live.key) : "ready"}</span></div>
        <div class="small mut">Covers: ${esc(streamers.filter((_, i) => i % 2 === n).join(", ") || "—")}</div>
        ${lastMsg ? `<div class="small sub">“${esc(lastMsg.content.slice(0, 110))}”</div>` : ""}
        <div class="row">${mineTabs.map((k) => `<span class="pill">${esc(k)}</span>`).join("")}</div></div>`;
    }).join("");
  },
};

// ------------------------------------------------------------------ Edit & review
export const review = {
  render(el) {
    el.innerHTML = header("Edit & review", "Each clipper edits one clip at a time. Watch, give feedback, approve.",
      `<a class="btn" href="#/autopilot" style="text-decoration:none">Publish plan →</a>`) + `<div class="page"><div class="pagepad" data-list></div></div>`;
    this.refresh(el, true);
  },
  async refresh(el, force) {
    const box = $("[data-list]", el);
    if (!force && box.contains(document.activeElement) && document.activeElement.tagName !== "BUTTON") return;
    if (!force && $$("video", box).some((v) => !v.paused)) return;
    const clips = await api("/api/clips?status=queued_edit,editing,edited");
    box.innerHTML = clips.length ? `<div class="grid2">${clips.map((c) => {
      const v = c.variants || {};
      const ver = Object.keys(v)[0];
      return `<section class="card pad row" style="align-items:flex-start;gap:14px" data-c="${c.id}">
        <div class="col" style="width:180px;flex:none;gap:6px"><div class="player" style="width:180px">${ver ? `<video src="${API}${v[ver]}?t=${c.status}" controls preload="metadata" data-vid></video>` : `<div class="empty small">${c.status === "editing" ? "rendering…" : "waiting…"}</div>`}</div>
          ${ver ? `<div class="seg" role="tablist">${Object.keys(v).map((k, i) => `<button role="tab" aria-selected="${i === 0}" data-ver="${API}${v[k]}">${k}</button>`).join("")}</div>` : ""}</div>
        <div class="col grow" style="gap:8px"><div class="row">${av(c.editor || "Clipper A", 22)}<b>#${c.id} · ${esc(c.title || c.hook)}</b></div>
          <div class="small ${c.status === "edited" ? "ok-t" : "acc-t"}">${esc(stLabel(c.status))}${c.layout ? " · " + esc(c.layout) + " layout" : ""} · ${c.length}s</div>
          <div class="small mut" style="background:var(--panel);border-radius:8px;padding:8px 10px">Hook: “${esc(c.hook)}”${Object.entries(c.review || {}).map(([w, r]) => `<br>${esc(w)}: ${esc(r.verdict)}${r.note ? " · " + esc(r.note) : ""}`).join("")}</div>
          <div class="row">${["Stronger hook", "Cut first 2s", "Shorter", "Bigger captions", "Try split-screen", "No split-screen"].map((q) => `<button class="chip" data-quick="${q}">${q}</button>`).join("")}</div>
          <label class="f">Feedback to ${esc(c.editor || "the crew")}<input data-fb placeholder="e.g. end it right after the splash"></label>
          <div class="row"><button class="btn paper" data-ok ${c.status !== "edited" ? "disabled" : ""}>Approve</button><button class="btn" data-send>Send feedback</button></div></div></section>`;
    }).join("")}</div>` : `<div class="empty">Nothing being edited. Pick clips from a shortlist in the crew room, or tick clips on the Clips page.</div>`;
  },
  bind(el) {
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("button"); if (!t) return;
      const card = t.closest("[data-c]"); if (!card) return;
      const id = +card.dataset.c;
      if (t.dataset.ver) { $$("[data-ver]", card).forEach((b) => b.setAttribute("aria-selected", b === t)); $("[data-vid]", card).src = t.dataset.ver; }
      if (t.dataset.quick) { $("[data-fb]", card).value = t.dataset.quick; }
      if (t.dataset.send != null) { const text = $("[data-fb]", card).value.trim(); if (!text) return toast("Write the feedback first");
        await guard(() => post("/api/crew/feedback", { clip_id: id, text })); toast("Sent. The crew re-edits it."); }
      if (t.dataset.ok != null) { await guard(() => api(`/api/clips/${id}`, { method: "PATCH", body: { status: "approved" } })); toast("Approved. It goes into the next publish plan."); this.refresh(el, true); }
    });
  },
};

// ------------------------------------------------------------------ Pipeline
export const pipeline = {
  render(el) {
    el.innerHTML = header("Pipeline", "Everything the crews are working on, live", `<a class="btn pri" href="#/crew" style="text-decoration:none">Start a hunt</a>`) +
      `<div class="page"><div class="pagepad"><div class="scrollx"><div class="board" data-board></div></div></div></div>`;
    this.refresh(el);
  },
  async refresh(el) {
    const b = await api("/api/board");
    $("[data-board]", el).innerHTML = STAGES.map(([k, t], i) => `<section aria-label="${t}"><div class="colh" style="border-color:${["var(--blue2)", "var(--accent-text)", "var(--warn)", "var(--ok)"][i]}">${t}<span class="sub" style="margin-left:auto">${(b[k] || []).length}</span></div>
      ${(b[k] || []).map((it) => `<button class="item" data-type="${it.type}" data-id="${it.id}" data-status="${it.status}"><div class="row small sub">${it.who ? av(it.who, 18) : ""}<span>${esc(it.label)}</span>${it.score ? `<span class="warn-t" style="margin-left:auto">${it.score.toFixed(1)}</span>` : ""}</div>
        <b style="font-weight:500">${esc((it.detail || it.title || "").slice(0, 80))}</b><span class="small ${stClass(it.status)}">${esc(stLabel(it.status))}${it.posts ? Object.entries(it.posts).filter(([, v]) => v.ok).map(([k]) => " · " + k + " ✓").join("") : ""}</span></button>`).join("") || `<div class="small sub" style="padding:6px">empty</div>`}</section>`).join("");
  },
  bind(el) {
    el.addEventListener("click", async (e) => {
      const t = e.target.closest(".item"); if (!t) return;
      if (t.dataset.type === "clip") location.hash = "#/clips?c=" + t.dataset.id;
      else if (t.dataset.status === "error" && confirm("Retry this video?")) { await guard(() => post(`/api/sources/${t.dataset.id}/retry`)); this.refresh(el); }
    });
  },
};

// ------------------------------------------------------------------ Clips
export const clips = {
  sel: null, filter: "ready,edited",
  render(el) {
    el.innerHTML = header("Clips", "", `<div class="seg" role="tablist" data-filter>${[["ready,edited", "Needs review"], ["approved", "Approved"], ["posted", "Posted"], ["rejected", "Rejected"], ["", "All"]]
      .map(([v, l]) => `<button role="tab" aria-selected="${v === this.filter}" data-f="${v}">${l}</button>`).join("")}</div>
      <button class="btn" data-comp>Compilation from ticked</button><button class="btn" data-edit>Crew: edit ticked</button>`) +
      `<div class="page"><div class="split"><section class="main" style="padding:20px 24px"><div class="clipgrid" data-grid></div></section><section class="sidepanel" data-editor style="flex-basis:620px;background:var(--panel)"></section></div></div>`;
    const m = location.hash.match(/c=(\d+)/); if (m) { this.sel = +m[1]; this.filter = ""; }
    this.refresh(el, true);
  },
  async refresh(el, force) {
    if (!force && (el.querySelector("[data-editor]").contains(document.activeElement) || $$("video", el).some((v) => !v.paused))) return;
    const list = await api("/api/clips?status=" + this.filter);
    this.list = list;
    const ticked = new Set($$("[data-tick]:checked", el).map((x) => +x.value));
    $("[data-grid]", el).innerHTML = list.length ? list.map((c) => `<div class="col" style="gap:6px"><button class="cthumb" aria-pressed="${c.id === this.sel}" data-pick="${c.id}">
        <span class="v">${c.video ? `<video src="${API}${c.video}#t=1" preload="metadata" muted></video>` : ""}<span class="len">${c.is_compilation ? "comp" : c.length + "s"}</span></span></button>
        <label class="row small"><input type="checkbox" data-tick value="${c.id}" ${ticked.has(c.id) ? "checked" : ""}><span>#${c.id} ${esc(c.streamer || "compilation")}</span><span class="warn-t" style="margin-left:auto">${(c.score || 0).toFixed(1)}</span></label></div>`).join("")
      : `<div class="empty">No clips here yet. Start a hunt in the crew room.</div>`;
    if (!this.sel && list[0]) this.sel = list[0].id;
    this.editor(el);
  },
  editor(el) {
    const c = (this.list || []).find((x) => x.id === this.sel);
    const box = $("[data-editor]", el);
    if (!c) { box.innerHTML = `<div class="empty">Pick a clip.</div>`; return; }
    const chans = (state.status?.channels || []);
    box.innerHTML = `<div class="row"><div class="grow"><b style="font-size:15px">#${c.id} · ${esc(c.title)}</b><div class="small sub">${esc(c.streamer || "compilation")} · ${c.is_compilation ? "compilation" : `${c.start.toFixed(1)}s → ${c.end.toFixed(1)}s`} · score <span class="warn-t">${(c.score || 0).toFixed(1)}</span>${c.found_by ? " · found by " + esc(c.found_by) : ""}</div></div>
      <button class="btn" data-st="rejected">Reject</button><button class="btn paper" data-st="approved">Approve</button></div>
      <div class="row" style="align-items:flex-start;gap:18px"><div class="player">${c.video ? `<video src="${API}${c.video}?v=${encodeURIComponent(c.render_path + c.status)}" controls preload="metadata"></video>` : `<div class="empty">rendering…</div>`}</div>
        <div class="col grow" style="min-width:240px"><label class="f">Hook · on screen first 4s<input data-k="hook" value="${esc(c.hook)}"></label>
          <label class="f">Title<input data-k="title" value="${esc(c.title)}"></label>
          <label class="f">Caption<textarea data-k="description" rows="3">${esc(c.description)}</textarea></label>
          <label class="f">Layout<select data-k="layout">${["", "blur", "facecam", "split", "crop", "bubble"].map((l) => `<option value="${l}" ${l === (c.layout || "") ? "selected" : ""}>${l || "default"}</option>`).join("")}</select></label>
          <div class="small sub" style="background:var(--surf);border:1px solid var(--line2);border-radius:8px;padding:8px 10px"><b class="mut">Why the AI picked it:</b> ${esc(c.reason)}</div></div></div>
      ${c.is_compilation ? "" : `<div class="row"><label class="f">Start (s)<input type="number" step="0.5" data-k="start" value="${c.start.toFixed(1)}" style="width:100px"></label><label class="f">End (s)<input type="number" step="0.5" data-k="end" value="${c.end.toFixed(1)}" style="width:100px"></label><button class="btn" data-save style="align-self:flex-end">Save (re-renders if needed)</button></div>`}
      <div style="border-top:1px solid var(--line);padding-top:14px" class="col"><b class="small mut">Publish to</b>
        <div class="row">${chans.map((ch) => `<label class="target"><input type="checkbox" data-ch value="${esc(ch.key)}">${esc(ch.key)}<span class="tiny sub">${ch.method}</span></label>`).join("") || `<span class="small sub">Connect accounts on the Channels page.</span>`}</div>
        <div class="row"><button class="btn pri" data-pub>Publish now</button><button class="btn" data-qr>Send to my phone</button><button class="btn" data-export>Export file</button></div>
        <div class="small">${Object.entries(c.posts || {}).map(([k, v]) => `<div class="${v.ok ? "ok-t" : "warn-t"}">${esc(k)}: ${esc(v.msg)}</div>`).join("")}</div></div>`;
  },
  bind(el) {
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.dataset.f != null) { this.filter = t.dataset.f; this.sel = null; return this.render(el); }
      if (t.dataset.pick) { this.sel = +t.dataset.pick; $$("[data-pick]", el).forEach((b) => b.setAttribute("aria-pressed", +b.dataset.pick === this.sel)); return this.editor(el); }
      const id = this.sel;
      const vals = () => Object.fromEntries($$("[data-k]", el).map((i) => [i.dataset.k, i.type === "number" ? +i.value : i.value]));
      if (t.dataset.save != null) { const r = await guard(() => api(`/api/clips/${id}`, { method: "PATCH", body: vals() })); if (r) toast(r.rerender ? "Saved, re-rendering…" : "Saved"); }
      if (t.dataset.st) { await guard(() => api(`/api/clips/${id}`, { method: "PATCH", body: { ...vals(), status: t.dataset.st } })); this.refresh(el, true); }
      if (t.dataset.pub != null) { const chs = $$("[data-ch]:checked", el).map((x) => x.value); if (!chs.length) return toast("Tick at least one account");
        if (!confirm(`Publish #${id} to ${chs.join(", ")} now? The crew posts it in each account.`)) return;
        await guard(() => post(`/api/clips/${id}/publish`, { channels: chs })); toast("The crew is publishing it. Watch on the Browser page."); }
      if (t.dataset.qr != null) { const r = await guard(() => post(`/api/clips/${id}/phone`)); if (r) { const { modal } = await import("./core.js"); modal(`<h3>Send #${id} to your phone</h3><div class="qr" style="margin:auto">${r.qr_svg}</div><p class="small mut">Same Wi-Fi. Link valid ${r.expires_in_min} min.</p><button class="btn" onclick="document.getElementById('modal').classList.add('hidden')">Close</button>`); } }
      if (t.dataset.export != null) { const r = await guard(() => post(`/api/clips/${id}/export`)); if (r) reveal(r.path); }
      if (t.dataset.comp != null) { const ids = $$("[data-tick]:checked", el).map((x) => +x.value); await guard(() => post("/api/compilation", { clip_ids: ids })); toast("Building the compilation…"); }
      if (t.dataset.edit != null) { const ids = $$("[data-tick]:checked", el).map((x) => +x.value); if (!ids.length) return toast("Tick clips first"); await guard(() => post("/api/crew/edit", { clip_ids: ids })); toast("The crew is editing them, two at a time."); }
    });
  },
};
