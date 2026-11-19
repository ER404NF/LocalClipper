// Grow pages: Trends, Monetization.
import { $, $$, ago, api, esc, guard, header, num, post, state, toast } from "./core.js";

export const trends = {
  render(el) {
    el.innerHTML = header("Trends", "Researched on the web by the production crew", `<button class="btn pri" data-now>Research now</button>`) +
      `<div class="page"><div class="pagepad"><div class="row" style="align-items:flex-start;gap:24px">
        <section class="grid2 grow" style="min-width:520px" data-cards></section>
        <aside class="col" style="flex:1 1 300px;max-width:360px"><form class="card pad col" data-ask><b>Ask the crew</b><label class="sr" for="trq">Research question</label>
          <textarea id="trq" rows="3" placeholder="e.g. how are the biggest GTA 6 clip pages editing their Reels this week?"></textarea><button class="btn">Research</button></form>
          <div class="card pad col small mut"><b style="color:var(--paper);font-size:13px">How it works</b>Clipper B searches the web, reads a few good sources and saves each finding here with links. "Use on next clips" writes it into the crew's brain so they apply it.</div></aside></div></div></div>`;
    this.refresh(el);
  },
  async refresh(el) {
    const list = await api("/api/trends");
    $("[data-cards]", el).innerHTML = list.map((t) => `<article class="card pad col" style="gap:8px"><div class="row"><span class="tiny acc-t" style="font-weight:600;letter-spacing:.5px;text-transform:uppercase">${esc(t.kind)}</span><span class="small sub" style="margin-left:auto">${ago(t.created_at)}</span></div>
      <b>${esc(t.title)}</b><div class="small mut">${esc(t.body)}</div>
      <div class="small sub">${t.sources.length} sources ${t.sources.slice(0, 3).map((s, i) => `<a href="${esc(s)}" target="_blank" rel="noopener">[${i + 1}]</a>`).join(" ")}</div>
      <div class="row">${t.status === "used" ? `<span class="pill ok">in use</span>` : `<button class="btn paper sm" data-use="${t.id}">Use on next clips</button>`}</div></article>`).join("")
      || `<div class="empty card">No findings yet. Press Research now.</div>`;
  },
  bind(el) {
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.dataset.now != null) { await guard(() => post("/api/trends/research", {})); toast("Clipper B is researching. Findings appear here."); }
      if (t.dataset.use) { await guard(() => post(`/api/trends/${t.dataset.use}/use`)); this.refresh(el); }
    });
    el.addEventListener("submit", async (e) => {
      if (!e.target.matches("[data-ask]")) return; e.preventDefault();
      const q = $("#trq", el).value.trim(); if (!q) return;
      await guard(() => post("/api/trends/research", { question: q })); $("#trq", el).value = ""; toast("Researching…");
    });
  },
};

export const money = {
  render(el) {
    el.innerHTML = header("Monetization", "Campaign earnings and how close each account is to platform payouts") +
      `<div class="page"><div class="pagepad" data-body></div></div>`;
    this.refresh(el);
  },
  async refresh(el) {
    if (el.querySelector("[data-body]").contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
    const m = await api("/api/money");
    const tile = (k, v, s) => `<div class="card pad tile"><div class="k">${k}</div><div class="v">${v}</div><div class="small mut">${s}</div></div>`;
    $("[data-body]", el).innerHTML = `<section class="tiles">${tile("Campaign earnings", "$" + m.earned, `${m.campaigns.length} campaigns`)}${tile("Approved campaign views", num(m.views), "as counted by campaigns")}</section>
      <section class="card"><div class="row pad" style="border-bottom:1px solid var(--line)"><b class="grow">Campaigns</b><span class="small sub">Update the numbers from Whop / Vyro, or ask the crew to read them.</span></div>
        <div class="scrollx"><table class="table"><thead><tr><th>Campaign</th><th>Streamer</th><th>$ per 1K</th><th>Views</th><th>Earned</th><th>Status</th><th></th></tr></thead><tbody>
        ${m.campaigns.map((c) => `<tr data-id="${c.id}"><td><input data-k="name" value="${esc(c.name)}"></td><td><input data-k="streamer" value="${esc(c.streamer)}" style="width:120px"></td><td><input data-k="rate" type="number" step="0.1" value="${c.rate}" style="width:80px"></td><td><input data-k="views" type="number" value="${c.views}" style="width:110px"></td><td><input data-k="earned" type="number" step="0.01" value="${c.earned}" style="width:90px"></td><td><select data-k="status">${["active", "in review", "paid", "ended"].map((s) => `<option ${s === c.status ? "selected" : ""}>${s}</option>`).join("")}</select></td><td><button class="btn sm" data-save>Save</button></td></tr>`).join("")}
        <tr data-id=""><td><input data-k="name" placeholder="New campaign name"></td><td><input data-k="streamer" placeholder="streamer" style="width:120px"></td><td><input data-k="rate" type="number" step="0.1" placeholder="1.5" style="width:80px"></td><td><input data-k="views" type="number" value="0" style="width:110px"></td><td><input data-k="earned" type="number" value="0" style="width:90px"></td><td><select data-k="status"><option>active</option></select></td><td><button class="btn sm pri" data-save>Add</button></td></tr></tbody></table></div></section>
      <section class="grid2">${m.progress.map((p) => `<div class="card pad col"><div class="row"><b>${esc(p.channel)}</b><span class="small sub" style="margin-left:auto">${p.checked_at ? "checked " + ago(p.checked_at) : "not checked yet"}</span></div>
        ${p.metrics.map((x) => `<div class="col" style="gap:4px"><div class="row small"><span class="mut">${esc(x.label)}</span><span style="margin-left:auto">${num(x.value)}${x.goal ? " / " + num(x.goal) : ""}</span></div>${x.goal ? `<div class="bar"><span style="width:${Math.min(100, 100 * (x.value || 0) / x.goal)}%"></span></div>` : ""}</div>`).join("")}
        ${p.platform === "youtube" ? `<div class="small warn-t">From Feb 1, 2027 the Shorts target becomes 20M views in 90 days.</div>` : p.platform === "tiktok" ? `<div class="small sub">Creator Rewards: 18+ account holder, 1 min+ original videos.</div>` : ""}
        <button class="btn sm" data-check="${esc(p.channel)}" style="align-self:flex-start">Ask the crew to check now</button></div>`).join("") || `<div class="empty card">Add accounts on the Channels page.</div>`}</section>`;
  },
  bind(el) {
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.dataset.save != null) {
        const tr = t.closest("tr"); const v = Object.fromEntries($$("[data-k]", tr).map((i) => [i.dataset.k, i.type === "number" ? +i.value || 0 : i.value]));
        if (!v.name) return toast("Give the campaign a name");
        await guard(() => post("/api/money/campaigns", { ...v, id: tr.dataset.id ? +tr.dataset.id : null })); toast("Saved"); document.activeElement.blur(); this.refresh(el);
      }
      if (t.dataset.check) { await guard(() => post("/api/money/check", { channel: t.dataset.check })); toast("The crew is opening the account's dashboard"); }
    });
  },
};
