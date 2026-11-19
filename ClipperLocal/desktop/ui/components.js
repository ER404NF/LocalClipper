// Chat room used by the Agent, Production crew and Coding crew pages.
import { $, $$, API, ICON, api, av, closeModal, esc, guard, md, modal, post, state, toast } from "./core.js";

export function chatRoom(el, room, { placeholder = "Message…", suggestions = [], onCard } = {}) {
  el.innerHTML = `<div class="chatwrap">
      <div class="msgs"><div class="msgs-in" data-msgs></div></div>
      <div class="composer"><div class="composer-in">
        <div class="row" data-sugg style="margin-bottom:8px"></div>
        <form class="box" data-form><label class="sr" for="in-${room}">Message</label>
          <textarea id="in-${room}" rows="1" placeholder="${esc(placeholder)}"></textarea>
          <button class="sendbtn" aria-label="Send">${ICON.send}</button></form>
      </div></div></div>`;
  const box = $("[data-msgs]", el), input = $("textarea", el);
  let last = 0, waiting = false, timer;

  const renderRow = (r) => {
    const d = r.data || {};
    if (r.role === "user") return `<div class="m-user">${esc(r.content)}</div>`;
    if (r.role === "event") return `<div class="m-event">${esc(r.content)}</div>`;
    if (r.role === "tool") {
      let res = r.content; try { res = JSON.stringify(JSON.parse(r.content), null, 2); } catch {}
      const args = d.args ? Object.entries(d.args).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(", ") : "";
      let html = `<div class="m-tool"><details><summary>✓ ${esc(r.author ? r.author + " · " : "")}${esc(d.name)}(${esc(args).slice(0, 110)})</summary><pre>${esc(res).slice(0, 5000)}</pre></details></div>`;
      if (r.action) html += actionCard(r.action);
      if (d.qr) html += `<div class="qr">${d.qr}<p>Scan with a phone on the same Wi-Fi</p></div>`;
      return html;
    }
    // assistant
    let html = "";
    if (r.content) html += `<div class="m-ag ${d.error ? "err" : ""}">${av(r.author || "Agent", 28)}<div class="body"><div class="who"><b style="color:var(--paper);font-weight:600">${esc(r.author || "Agent")}</b>${d.to_teammate ? " · to teammate" : ""}</div>${md(r.content)}</div></div>`;
    if (d.shortlist) html += shortlistCard(d.shortlist, r.id);
    if (d.edited) html += `<div class="m-card"><div class="row"><b>#${d.edited} is edited</b><a class="btn sm pri" href="#/review" style="margin-left:auto;text-decoration:none">Review it</a></div></div>`;
    if (d.concepts) html += conceptCard(d.change, d.concepts);
    if (d.build_button) html += `<div class="m-card"><div class="row"><span>Build change #${d.change} on a safe copy?</span><button class="btn pri sm" style="margin-left:auto" data-build="${d.change}">Build it</button><button class="btn sm" data-discard="${d.change}">Drop it</button></div></div>`;
    if (d.review) html += `<div class="m-card"><div class="row"><b>Change #${d.change} is ready to review</b><button class="btn pri sm" style="margin-left:auto" data-review="${d.change}">Review</button></div></div>`;
    return html;
  };

  async function load(full = false) {
    const rows = await api(`/api/chat?room=${room}&after=${full ? 0 : last}`);
    if (full) { box.innerHTML = ""; last = 0; }
    const atBottom = el.querySelector(".msgs").scrollHeight - el.querySelector(".msgs").scrollTop - el.querySelector(".msgs").clientHeight < 120;
    $("[data-typing]", box)?.remove();
    for (const r of rows) {
      if (r.id <= last) continue;
      box.insertAdjacentHTML("beforeend", renderRow(r));
      last = r.id;
      if (r.role === "assistant" && r.content && !(r.data || {}).tool_calls) waiting = false;
    }
    if (waiting) box.insertAdjacentHTML("beforeend", `<div class="typing" data-typing>Working on it…</div>`);
    if (rows.length || full) { const m = el.querySelector(".msgs"); if (atBottom || full) m.scrollTop = m.scrollHeight; }
    $("[data-sugg]", el).innerHTML = last ? "" : suggestions.map((s) => `<button class="chip" type="button">${esc(s)}</button>`).join("");
    $$("[data-sugg] .chip", el).forEach((b) => (b.onclick = () => send(b.textContent)));
  }
  async function send(text) {
    text = (text || "").trim(); if (!text) return;
    input.value = ""; waiting = true;
    await guard(() => post("/api/chat", { room, text }));
    await load();
  }
  $("[data-form]", el).onsubmit = (e) => { e.preventDefault(); send(input.value); };
  input.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input.value); } };
  input.oninput = () => { input.style.height = "auto"; input.style.height = Math.min(160, input.scrollHeight) + "px"; };

  el.addEventListener("click", async (e) => {
    const t = e.target.closest("button"); if (!t) return;
    if (t.dataset.confirm) { await guard(() => post(`/api/actions/${t.dataset.confirm}/confirm`)); toast("Publishing started"); load(true); }
    if (t.dataset.cancel) { await guard(() => post(`/api/actions/${t.dataset.cancel}/cancel`)); load(true); }
    if (t.dataset.edit) {
      const ids = $$(`[data-sl="${t.dataset.edit}"]:checked`, el).map((x) => +x.value);
      if (!ids.length) return toast("Tick at least one clip");
      await guard(() => post("/api/crew/edit", { clip_ids: ids })); toast("Editing started: two clips at a time"); load();
    }
    if (t.dataset.build) { await guard(() => post(`/api/changes/${t.dataset.build}/build`, { concept: t.dataset.concept != null ? +t.dataset.concept : null })); load(); }
    if (t.dataset.discard) { await guard(() => post(`/api/changes/${t.dataset.discard}/discard`)); load(); }
    if (t.dataset.review) reviewChange(+t.dataset.review);
    if (t.dataset.zoom) modal(`<h3>${esc(t.dataset.title)}</h3><iframe title="Concept preview" src="${API}/api/changes/${t.dataset.zoom}/concept/${t.dataset.i}?accent=${encodeURIComponent(getComputedStyle(document.documentElement).getPropertyValue("--accent").trim())}" style="width:100%;height:60vh;border:1px solid var(--line);border-radius:8px;background:#0A0A0A"></iframe><div class="row" style="margin-top:10px"><button class="btn pri" data-build="${t.dataset.zoom}" data-concept="${t.dataset.i}">Build this one</button><button class="btn" onclick="document.getElementById('modal').classList.add('hidden')">Close</button></div>`);
  });
  $("#modalBox").addEventListener("click", async (e) => {
    const t = e.target.closest("[data-build]"); if (!t || !el.isConnected) return;
    closeModal(); await guard(() => post(`/api/changes/${t.dataset.build}/build`, { concept: +t.dataset.concept })); load();
  });

  load(true);
  timer = setInterval(() => el.isConnected ? load().catch(() => {}) : clearInterval(timer), 1800);
  return { send, reload: () => load(true) };
}

function actionCard(a) {
  const done = a.status !== "pending";
  return `<div class="m-card"><div class="row"><b>Publish request #${a.id}</b><span class="pill ${done ? (a.status === "confirmed" ? "ok" : "") : "warn"}" style="margin-left:auto">${done ? esc(a.status) : "Needs your OK"}</span></div>
    <pre>${esc(a.summary)}</pre>
    ${done ? "" : `<div class="row"><button class="btn pri" data-confirm="${a.id}">Confirm &amp; publish</button><button class="btn" data-cancel="${a.id}">Cancel</button></div>`}</div>`;
}

function shortlistCard(ids, key) {
  return `<div class="m-card" data-shortlist="${key}"><div class="row"><b>Shortlist · pick what to edit</b><span class="pill warn" style="margin-left:auto">Waiting for you</span></div>
    <div class="col" data-sl-list="${key}">${ids.map((id) => `<label class="row" style="background:var(--panel);border-radius:8px;padding:8px"><input type="checkbox" checked data-sl="${key}" value="${id}"><span data-slc="${id}">Clip #${id}</span></label>`).join("")}</div>
    <div class="row"><button class="btn pri" data-edit="${key}">Start editing</button><a class="btn" href="#/clips" style="text-decoration:none">Look at them first</a></div></div>`;
}

function conceptCard(cid, concepts) {
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  return `<div class="m-card"><div class="concepts">${concepts.map((c) => `<div class="concept">
      <iframe title="${esc(c.name)}" src="${API}/api/changes/${cid}/concept/${c.i}?accent=${encodeURIComponent(accent)}" loading="lazy"></iframe>
      <b class="small">${esc(c.name)}</b><span class="small mut">${esc(c.description)}</span>
      <div class="row"><button class="btn sm pri" data-build="${cid}" data-concept="${c.i}">Build this</button><button class="btn sm" data-zoom="${cid}" data-i="${c.i}" data-title="${esc(c.name)}">Bigger</button></div></div>`).join("")}</div></div>`;
}

export async function reviewChange(cid) {
  const c = await api(`/api/changes/${cid}`);
  modal(`<h3>Review change #${c.id}</h3><p class="mut small">${esc(c.request)}</p>
    <div class="col"><b class="small">Checks</b>${(c.checks || []).map((k) => `<div class="small"><span class="${k.ok ? "ok-t" : "bad-t"}">${k.ok ? "✓" : "✕"}</span> ${esc(k.name)} ${k.detail ? `<span class="sub">· ${esc(k.detail.slice(0, 160))}</span>` : ""}</div>`).join("") || "<span class='sub small'>none</span>"}
    <b class="small">Files</b>${(c.files || []).map((f) => `<div class="mono"><span class="mut">${esc(f.file)}</span> <span class="ok-t">+${f.added}</span> <span class="bad-t">−${f.removed}</span></div>`).join("")}
    <details><summary class="small">Show code</summary><pre class="mono" data-diff style="max-height:300px;overflow:auto;background:#070707;padding:8px;border-radius:8px">loading…</pre></details>
    <div data-preview-box></div>
    <div class="row" style="margin-top:6px">${c.status === "review" ? `<button class="btn" data-preview="${c.id}">Preview live</button><button class="btn pri" data-apply="${c.id}">Apply &amp; save</button><button class="btn" data-dis="${c.id}">Discard</button>` : c.status === "applied" ? `<button class="btn" data-undo="${c.id}">Undo this change</button>` : `<span class="pill">${esc(c.status)}</span>`}<button class="btn" data-close>Close</button></div></div>`);
  api(`/api/changes/${cid}/diff`).then((t) => { const d = $("[data-diff]"); if (d) d.textContent = t || "(no code yet)"; }).catch(() => {});
  $("#modalBox").onclick = async (e) => {
    const t = e.target.closest("button"); if (!t) return;
    if (t.dataset.close != null) { stopPreview(); closeModal(); }
    if (t.dataset.preview) {
      const box = $("[data-preview-box]");
      box.innerHTML = `<div class="small mut" style="margin:8px 0">Starting the changed app next to this one…</div>`;
      t.disabled = true;
      const r = await guard(() => post(`/api/changes/${t.dataset.preview}/preview`));
      t.disabled = false;
      if (r && r.url) {
        box.innerHTML = `<div class="row small" style="margin:8px 0"><span class="pill">Preview · your real app is untouched</span>
          <button class="btn sm" data-preview-full>Full screen</button></div>
          <iframe src="${r.url}" title="Preview" style="width:100%;height:58vh;border:1px solid var(--line);border-radius:10px;background:var(--bg)"></iframe>`;
        box.querySelector("[data-preview-full]").onclick = () => box.querySelector("iframe").requestFullscreen?.();
      } else box.innerHTML = `<div class="small bad-t" style="margin:8px 0">${esc((r && r.error) || "Preview failed")}</div>`;
    }
    if (t.dataset.apply) { const r = await guard(() => post(`/api/changes/${t.dataset.apply}/apply`)); if (r && r.ok) { closeModal(); afterChange(r); } }
    if (t.dataset.dis) { stopPreview(); await guard(() => post(`/api/changes/${t.dataset.dis}/discard`)); closeModal(); }
    if (t.dataset.undo) { const r = await guard(() => post(`/api/changes/${t.dataset.undo}/undo`)); if (r && r.ok) { closeModal(); afterChange(r); } }
  };
}

function stopPreview() { fetch(`${API}/api/changes/preview`, { method: "DELETE" }).catch(() => {}); }

// After apply/undo: screen-only changes just reload; Python changes restart the engine first.
function afterChange(r) {
  if (r.restart) restartEngine();
  else { toast("Change applied. Reloading the screens…"); setTimeout(() => location.reload(), 900); }
}

async function waitForEngine(ms = 30000) {
  const end = Date.now() + ms;
  await new Promise((ok) => setTimeout(ok, 1500));
  while (Date.now() < end) {
    try { const r = await fetch(`${API}/api/health`, { cache: "no-store" }); if (r.ok) return true; } catch (e) {}
    await new Promise((ok) => setTimeout(ok, 700));
  }
  return false;
}

export async function restartEngine() {
  toast("Saving and restarting the engine to load the change…");
  const T = window.__TAURI__ && window.__TAURI__.core;
  try {
    if (T) await T.invoke("restart_engine");
    else await fetch(`${API}/api/restart`, { method: "POST" });
  } catch (e) {
    try { await fetch(`${API}/api/restart`, { method: "POST" }); } catch (e2) {}
  }
  const ok = await waitForEngine();
  if (ok) location.reload();
  else toast("The engine didn't come back. Close and reopen ClipperLocal; if it still fails, Undo the change.");
}
