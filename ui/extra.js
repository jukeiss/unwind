/* Unwind extras: malware triage report, class browser, wallet history timeline, Obsidian-style extras. */
"use strict";

/* ================================================================ malware triage */
const SEV = { 0: ["info", "t-muted"], 1: ["low", "t-info"], 2: ["medium", "t-warn"], 3: ["high", "t-danger"] };
const attackUrl = id => `https://attack.mitre.org/techniques/${id.trim().replace(".", "/")}/`;

async function renderTriage(box, path, tab) {
  box.innerHTML = `<div class="view-scroll"><div class="page">${loading("Reading the file statically (it is never run)…")}</div></div>`;
  let r;
  try { r = await api("mal", "analyze", { path }); }
  catch (e) { $(".page", box).innerHTML = errBox(e); return; }
  tab.triage = r;
  const m = r.macos || {}, b = r.bundle || {}, io = r.iocs || {}, dec = r.decoded || { items: [] }, y = r.yara || {};
  const tone = r.score >= 60 ? "danger" : r.score >= 30 ? "warn" : r.score >= 10 ? "info" : "good";
  const yesno = (v, good = true) => v == null ? "—" : `<span class="pill ${v === good ? "t-good" : "t-warn"}">${v ? "yes" : "no"}</span>`;
  const iocList = (k, label) => {
    const v = io[k]; if (!v || !v.length) return "";
    const item = x => {
      if (typeof x === "string") return `<div class="mono ioc">${esc(x)}</div>`;
      if (x.address) return `<div class="ioc">${chainChip(x.chain)} <span class="addr" data-wallet="${esc(x.address)}" data-chain="${esc(x.chain)}">${esc(x.address)}</span></div>`;
      return `<div class="mono ioc${x.common ? " faint" : ""}">${esc(x.domain || x.value || x.ip || JSON.stringify(x))}${x.common ? " (common)" : ""}${x.scope && x.scope !== "public" ? ` <span class="faint">${esc(x.scope)}</span>` : ""}</div>`;
    };
    return `<div class="card"><h3>${esc(label)} <span class="muted">${v.length}</span></h3>${v.slice(0, 80).map(item).join("")}</div>`;
  };
  const ents = Object.entries(m.entitlements || {});
  $(".page", box).innerHTML = `
    <div class="verdict ${tone}"><div class="gauge"><div style="width:${Math.max(3, r.score)}%"></div></div>
      <div><div class="vt">${esc(r.verdict)} <span class="faint">· score ${r.score}/100</span></div><div class="muted" style="font-size:12.5px">${esc(r.note || "")}</div></div>
      <div class="acts"><button class="btn sm" data-t="save">${ICONS.save} Save report</button><button class="btn sm" data-t="rep" title="Only the SHA-256 is sent">Check hash reputation</button><button class="btn sm primary" data-t="ai">✦ Ask AI to assess</button></div></div>
    <div id="tri-rep"></div>
    <div class="grid2">
      <div class="card"><h3>File</h3><dl class="kv"><dt>Name</dt><dd>${esc(r.name)}</dd><dt>Kind</dt><dd>${esc(r.kind)}${r.arch ? " · " + esc(r.arch) : ""}</dd><dt>Size</dt><dd>${(r.size || 0).toLocaleString()} bytes${r.truncated ? " (read first part)" : ""}</dd>
        <dt>Entropy</dt><dd>${r.entropy} ${r.entropy > 7.2 ? `<span class="pill t-warn">packed / encrypted?</span>` : ""}</dd>
        ${Object.entries(r.hashes || {}).map(([k, h]) => `<dt>${k.toUpperCase()}</dt><dd class="mono" style="font-size:11.5px">${esc(h)} <button class="ib" data-copy="${esc(h)}">${ICONS.copy}</button></dd>`).join("")}
        <dt>Imports</dt><dd>${r.import_count ?? "—"}</dd><dt>Strings</dt><dd>${(r.string_count || 0).toLocaleString()}</dd></dl></div>
      ${r.kind === "macho" || m.signed !== undefined ? `<div class="card"><h3>Code signature & Gatekeeper</h3><dl class="kv">
        <dt>Signed</dt><dd>${yesno(m.signed)}${m.adhoc ? ` <span class="pill t-warn">ad-hoc</span>` : ""}</dd><dt>Signature valid</dt><dd>${yesno(m.signature_valid)}${m.signature_error ? `<div class="faint">${esc(m.signature_error)}</div>` : ""}</dd>
        <dt>Notarized</dt><dd>${(m.authority || [])[0] === "Software Signing" ? `<span class="pill t-good">Apple system binary</span>` : yesno(m.notarized)}</dd><dt>Gatekeeper</dt><dd>${esc(m.gatekeeper || "—")}${m.gatekeeper_source ? ` <span class="faint">${esc(m.gatekeeper_source)}</span>` : ""}</dd>
        <dt>Hardened runtime</dt><dd>${yesno(m.hardened_runtime)}</dd><dt>Team ID</dt><dd>${esc(m.team_id || "—")}</dd>
        <dt>Signed by</dt><dd>${(m.authority || []).map(esc).join(" → ") || "—"}</dd><dt>Quarantine flag</dt><dd>${m.quarantine ? `<span class="pill t-info" title="${esc(m.quarantine)}">downloaded</span>` : "none"}</dd></dl></div>` : ""}
    </div>
    <div class="card"><h3>Capabilities <span class="muted">${r.capabilities.length}</span> ${(r.attack || []).length ? `<span class="faint" style="font-weight:400">· MITRE ATT&CK: ${r.attack.map(a => `<a href="${attackUrl(a)}" target="_blank" rel="noopener noreferrer">${esc(a)}</a>`).join(", ")}</span>` : ""}</h3>
      ${r.capabilities.length ? `<div class="tbl-wrap" style="border:0"><table class="tbl"><thead><tr><th>Severity</th><th>What it can do</th><th>ATT&CK</th><th>Evidence</th></tr></thead><tbody>${r.capabilities.map(c => `<tr><td><span class="pill ${SEV[c.severity][1]}">${SEV[c.severity][0]}</span></td><td>${esc(c.title)}</td>
        <td class="nw">${String(c.attack || "-").split(",").map(a => a.trim()).filter(a => a && a !== "-").map(a => `<a href="${attackUrl(a)}" target="_blank" rel="noopener noreferrer">${esc(a)}</a>`).join(", ") || "—"}</td>
        <td class="mono" style="font-size:11.5px;overflow-wrap:anywhere">${(c.evidence || []).slice(0, 6).map(esc).join("<br>")}</td></tr>`).join("")}</tbody></table></div>` : `<div class="muted">No suspicious capabilities found.</div>`}</div>
    ${dec.items.length ? `<div class="card"><h3>Hidden strings <span class="muted">${dec.count} decoded</span></h3><p class="muted" style="margin:0 0 8px;font-size:12.5px">Text stored encoded inside the file (base64, hex, single-byte XOR), decoded without running anything.</p>
      <div class="tbl-wrap" style="border:0"><table class="tbl"><thead><tr><th>Method</th><th>Decoded</th><th>Encoded</th></tr></thead><tbody>${dec.items.slice(0, 80).map(d => `<tr><td class="nw"><span class="pill ${d.interesting ? "t-warn" : "t-muted"}">${esc(d.method)}</span></td><td class="mono" style="font-size:12px;overflow-wrap:anywhere">${esc(d.decoded.slice(0, 300))}</td><td class="mono faint" style="font-size:11px;overflow-wrap:anywhere">${esc(d.encoded.slice(0, 60))}</td></tr>`).join("")}</tbody></table></div></div>` : ""}
    <div class="grid2">${iocList("wallets", "Crypto wallets")}${iocList("urls", "URLs")}${iocList("domains", "Domains")}${iocList("ips", "IP addresses")}${iocList("emails", "Emails")}${iocList("webhooks", "Webhooks & bots")}${iocList("onion", "Onion addresses")}${iocList("telegram_bots", "Telegram bot tokens")}</div>
    ${ents.length ? `<div class="card"><h3>Entitlements <span class="muted">${ents.length}</span></h3>${ents.map(([k, v]) => `<div class="mono" style="font-size:12px">${esc(k)} = ${esc(String(v))}</div>`).join("")}</div>` : ""}
    ${b.plist ? `<div class="card"><h3>App bundle</h3><dl class="kv">${Object.entries(b.plist).slice(0, 16).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(String(v)).slice(0, 160)}</dd>`).join("")}
      <dt>Executables</dt><dd class="mono" style="font-size:12px">${(b.executables || []).map(esc).join("<br>") || "—"}</dd><dt>Launch items</dt><dd class="mono" style="font-size:12px">${(b.launch_items || []).map(esc).join("<br>") || "none"}</dd><dt>Scripts</dt><dd class="mono" style="font-size:12px">${(b.scripts || []).map(esc).join("<br>") || "none"}</dd></dl></div>` : ""}
    <div class="card"><h3>YARA</h3>${y.available ? `${(y.matches || []).length ? y.matches.map(x => `<div><span class="pill t-danger">${esc(x.rule)}</span> <span class="faint">${esc(x.file || "")}</span></div>`).join("") : `<div class="muted">No rule matched.</div>`}<div class="faint" style="font-size:12px;margin-top:6px">Rules: ${esc((y.rule_files || []).join(", ") || "none")} in <span class="mono">${esc(y.rules_dir || "")}</span></div>` : `<div class="muted">${esc(y.note || "YARA not installed (brew install yara).")}</div>`}</div>
    ${(r.sections || []).length ? `<div class="card"><h3>Sections by entropy</h3>${r.sections.slice(0, 30).map(sec => `<div class="secrow"><span class="mono">${esc(sec.name)}</span><div class="ebar"><i style="width:${(sec.entropy / 8) * 100}%;background:${sec.entropy > 7.2 ? "var(--warn)" : "var(--accent)"}"></i></div><span class="mono faint">${sec.entropy}</span></div>`).join("")}</div>` : ""}`;
  box.onclick = async e => {
    const a = e.target.closest("[data-t]"); if (!a) return;
    if (a.dataset.t === "save") { try { const s = await api("mal", "save", { report: r, reputation_result: tab.reputation || null }); await refreshTree(); toast("Saved"); openNote(s.path, true); } catch (er) { toast(er.message, true); } }
    if (a.dataset.t === "rep") {
      const el = $("#tri-rep", box); el.innerHTML = loading("Looking up the hash…");
      try {
        const rp = tab.reputation = await api("mal", "reputation", { sha256: r.hashes.sha256 });
        const vt = rp.virustotal, mb = rp.malwarebazaar;
        el.innerHTML = `<div class="callout ${vt?.malicious ? "danger" : "info"}"><div>${vt ? (vt.found ? `<b>VirusTotal:</b> ${vt.malicious ?? 0} engines flag it as malicious, ${vt.suspicious ?? 0} suspicious${vt.names ? ` · names: ${esc((vt.names || []).slice(0, 4).join(", "))}` : ""}` : `<b>VirusTotal:</b> ${esc(vt.note || "not found")}`) : "<b>VirusTotal:</b> add a key in Settings"}<br>
          ${mb ? (mb.found ? `<b>MalwareBazaar:</b> known sample${mb.signature ? ` · family ${esc(mb.signature)}` : ""}${mb.tags ? ` · tags ${esc((mb.tags || []).join(", "))}` : ""}` : `<b>MalwareBazaar:</b> ${esc(mb.note || "not found")}`) : "<b>MalwareBazaar:</b> add a key in Settings"}</div></div>`;
      } catch (er) { el.innerHTML = errBox(er); }
    }
    if (a.dataset.t === "ai") {
      const slim = { name: r.name, kind: r.kind, score: r.score, verdict: r.verdict, entropy: r.entropy, macos: r.macos, capabilities: r.capabilities, iocs: r.iocs,
        hidden_strings: (dec.items || []).slice(0, 20), yara: (y.matches || []), attack: r.attack, bundle: { launch_items: b.launch_items, scripts: b.scripts } };
      openAssistant();
      aiSend(`Assess whether ${r.name} looks malicious. Weigh the evidence (signature, capabilities, indicators, hidden strings), say what it most likely is, what it would do if run, and what I should check next. You may use the bin_* tools on ${path} for details. Don't suggest running it.`,
        { full: `Assess whether ${r.name} looks malicious. Weigh the evidence (signature, capabilities, indicators, hidden strings), say what it most likely is, what it would do if run, and what to check next. You may call bin_* tools on ${path}. Never suggest running the sample.\n\nStatic triage report:\n${JSON.stringify(slim).slice(0, 24000)}`, context: `File ${path}` });
    }
  };
}

/* ================================================================ class browser */
async function renderClasses(box, path, arch, tab, v) {
  box.innerHTML = `<div style="padding:10px 18px;display:flex;gap:8px;align-items:center"><input class="inp mono" id="cf-${tab.id}" placeholder="Filter classes or methods…" style="flex:1"><span class="muted" id="cc-${tab.id}"></span></div><div class="view-scroll" id="cl-${tab.id}" style="padding:0 18px 30px"></div>`;
  const list = $(`#cl-${tab.id}`); list.innerHTML = loading("Reading Objective-C / Swift metadata…");
  let d;
  try { d = await api("bin", "objc", { path, arch }); } catch (e) { list.innerHTML = errBox(e); return; }
  if (!d.total) { list.innerHTML = `<div class="empty"><h2>No Objective-C / Swift class metadata</h2><p>Pure C/C++ programs and scripts don't have any. Use Functions and Strings instead.</p></div>`; return; }
  const draw = q => {
    q = (q || "").toLowerCase();
    const cls = d.classes.filter(c => !q || c.name.toLowerCase().includes(q) || c.methods.some(m => m.sel.toLowerCase().includes(q)));
    $(`#cc-${tab.id}`).textContent = `${cls.length} classes · ${cls.reduce((a, c) => a + c.methods.length, 0)} methods`;
    list.innerHTML = cls.slice(0, 400).map(c => `<details class="cls" ${q ? "open" : ""}><summary><b class="mono">${esc(c.name)}</b>${c.superclass ? ` <span class="faint">: ${esc(c.superclass)}</span>` : ""} <span class="faint">${c.methods.length} methods${c.ivars.length ? ` · ${c.ivars.length} fields` : ""}</span></summary>
      ${c.methods.filter(m => !q || c.name.toLowerCase().includes(q) || m.sel.toLowerCase().includes(q)).map(m => `<div class="meth" ${m.addr ? `data-ma="${m.addr}"` : ""}><span class="mono">${m.kind} ${esc(m.sel)}</span><span class="faint mono">${m.addr ? m.addr.replace(/^0x0*/, "") : ""}</span></div>`).join("")}
      ${c.ivars.length ? `<div class="faint mono" style="font-size:11.5px;padding:4px 10px">fields: ${c.ivars.slice(0, 40).map(esc).join(", ")}</div>` : ""}</details>`).join("");
  };
  $(`#cf-${tab.id}`).oninput = e => draw(e.target.value);
  list.onclick = e => { const mm = e.target.closest("[data-ma]"); if (mm) { v.go("functions"); setTimeout(() => v.disasm({ address: mm.dataset.ma }), 40); } };
  draw("");
}

/* ================================================================ wallet history */
const ACT = {
  bought: ["Bought", "↘", "var(--in)"], sold: ["Sold", "↗", "var(--out)"], swap: ["Swap", "⇄", "var(--accent)"],
  nft_buy: ["NFT buy", "◆", "var(--in)"], nft_sell: ["NFT sale", "◇", "var(--out)"], mint: ["Mint", "✦", "var(--good)"],
  create: ["Created", "⚒", "var(--warn)"], bridge: ["Bridge", "⤳", "var(--info)"], approve: ["Approval", "✓", "var(--muted)"],
  receive: ["Received", "←", "var(--in)"], send: ["Sent", "→", "var(--out)"], self: ["Self", "↻", "var(--muted)"],
  mined: ["Mined", "⛏", "var(--good)"], airdrop: ["Spam", "⚠", "var(--faint)"], burn: ["Burn", "🜂", "var(--muted)"], call: ["Contract call", "ƒ", "var(--muted)"],
};
const FILTERS = [["all", "All"], ["buy", "Bought"], ["sell", "Sold"], ["swap", "Swaps"], ["nft", "NFTs"], ["mint", "Minted"], ["create", "Created"], ["receive", "Received"], ["send", "Sent"], ["bridge", "Bridged"], ["approve", "Approvals"], ["failed", "Failed"], ["airdrop", "Spam"]];
const FMATCH = { buy: a => a.type === "bought" || a.type === "nft_buy", sell: a => a.type === "sold" || a.type === "nft_sell", swap: a => ["swap", "bought", "sold"].includes(a.type),
  nft: a => ["nft_buy", "nft_sell", "mint"].includes(a.type) && (a.in.concat(a.out)).some(x => x.kind === "nft"), failed: a => a.failed };

async function renderHistory(box, w, tab) {
  const H = tab.hist ||= { items: [], cursor: null, done: false, started: false, filter: "all", q: "", day: null, res: null, stop: false };
  const sym = w.symbol;
  const paint = () => {
    const res = H.res || { actions: [], summary: { by_type: {}, days: {}, bought: [], sold: [], nfts: [], created: [], peers: [] } };
    const s = res.summary;
    const acts = res.actions.filter(a => (H.filter === "all" ? a.type !== "airdrop" : H.filter === "airdrop" ? a.type === "airdrop" : (FMATCH[H.filter] || (x => x.type === H.filter))(a))
      && (!H.day || String(a.time).startsWith(H.day))
      && (!H.q || (a.title + " " + (a.counterparty || "") + " " + (a.counterparty_label || "") + " " + a.hash).toLowerCase().includes(H.q.toLowerCase())));
    const days = {}; acts.slice(0, 1500).forEach(a => (days[String(a.time).slice(0, 10)] ||= []).push(a));
    const card = (title, rows, empty) => `<div class="hcard"><div class="k">${title}</div>${rows || `<div class="faint">${empty}</div>`}</div>`;
    const assetRows = list => list.slice(0, 6).map(b => `<div class="hrow"><span>${esc(b.asset)}</span><span class="num muted">${esc(fmtAmt(b.amount))}${b.usd ? " · " + fmtUsd(b.usd) : ""} · ${b.count}×</span></div>`).join("");
    box.innerHTML = `
      <div class="hbar"><span class="muted">${H.items.length ? `${(s.actions || 0).toLocaleString()} transactions loaded${s.first ? ` · ${esc(dateStr(s.first).slice(0, 10))} → ${esc(dateStr(s.last).slice(0, 10))}` : ""}` : "Loading history…"}</span>
        <span class="grow"></span>${H.loadingAll ? `<span class="spin"></span><span class="muted">${H.items.length.toLocaleString()} transfers…</span><button class="btn sm" data-h="stop">Stop</button>` :
        H.done ? `<span class="pill t-good">complete history</span>` : `<button class="btn sm" data-h="more">Load more</button><button class="btn sm primary" data-h="all">Load everything</button>`}</div>
      <div class="hcards">
        ${card("Bought", assetRows(s.bought), "Nothing bought yet in what's loaded")}
        ${card("Sold", assetRows(s.sold), "Nothing sold")}
        ${card(`NFTs <span class="faint">${s.nfts.length}</span>`, s.nfts.length ? `<div class="nfts">${s.nfts.slice(0, 12).map(n => n.image ? `<img src="${esc(n.image)}" alt="${esc(n.name)}" title="${esc(n.type + ": " + n.name + (n.token_id ? " #" + n.token_id : ""))}" loading="lazy" referrerpolicy="no-referrer">` : `<span class="nft-ph" title="${esc(n.name)}">${esc((n.name || "?").slice(0, 2))}</span>`).join("")}</div><div class="faint" style="font-size:11.5px">${["nft_buy", "mint", "nft_sell"].map(t => `${s.nfts.filter(n => n.type === t).length} ${ACT[t][0].toLowerCase()}`).join(" · ")}</div>` : "", "No NFT buys, sales or mints")}
        ${card(`Created <span class="faint">${s.created.length}</span>`, s.created.slice(0, 6).map(c => `<div class="hrow"><span>${esc(c.title)}</span><span>${addrLink(c.contract, null, w.chain)}</span></div>`).join(""), "No contracts or tokens deployed")}
        ${card("Activity", `<div class="hrow"><span>Active days</span><span class="num">${s.active_days || 0}</span></div><div class="hrow"><span>Fees paid</span><span class="num">${esc(fmtAmt(s.fees || 0, sym))}</span></div>${Object.entries(s.by_type || {}).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([t, n]) => `<div class="hrow"><span>${esc((ACT[t] || [t])[0])}</span><span class="num">${n}</span></div>`).join("")}`, "")}
        ${card("Deals with most", s.peers.slice(0, 6).map(p => `<div class="hrow"><span>${addrLink(p.address, p.label, w.chain)}</span><span class="num muted">${p.count}× ${p.in_usd + p.out_usd ? "· " + fmtUsd(p.in_usd + p.out_usd) : ""}</span></div>`).join(""), "—")}
      </div>
      ${heatmap(s.days || {}, H.day)}
      <div class="hfilters">${FILTERS.map(([k, l]) => `<button data-f="${k}" class="${H.filter === k ? "on" : ""}">${l}</button>`).join("")}<span class="grow"></span>${H.day ? `<button class="btn sm ghost" data-h="clearday">Day: ${H.day} ✕</button>` : ""}<input class="inp" id="hq-${tab.id}" placeholder="Search history…" value="${esc(H.q)}" style="width:200px"></div>
      <div class="timeline">${Object.entries(days).map(([d, list]) => `<div class="tday">${esc(new Date(d + "T12:00:00Z").toLocaleDateString(undefined, { weekday: "short", year: "numeric", month: "short", day: "numeric" }))} <span class="faint">${list.length}</span></div>` + list.map(a => {
        const [lab, ic, col] = ACT[a.type] || ["?", "•", "var(--muted)"];
        return `<div class="tact${a.failed ? " failed" : ""}"><span class="tic" style="--c:${col}">${ic}</span><div class="tmain"><div class="tt">${esc(a.title)}</div>
          <div class="ts">${esc(lab)}${a.counterparty ? ` · ${addrLink(a.counterparty, a.counterparty_label, w.chain)}` : ""} · ${esc(dateStr(a.time).slice(11))} · ${txLink(a.hash, w.chain)}</div></div><div class="tv num">${a.usd ? fmtUsd(a.usd) : ""}</div></div>`;
      }).join("")).join("") || `<div class="empty">${H.items.length ? "Nothing matches this filter." : ""}</div>`}${acts.length > 1500 ? `<div class="faint" style="padding:10px">Showing the newest 1,500. Narrow with a filter or a day.</div>` : ""}</div>`;
    $(`#hq-${tab.id}`).oninput = e => { H.q = e.target.value; clearTimeout(H.t); H.t = setTimeout(() => { const pos = e.target.selectionStart; paint(); const i = $(`#hq-${tab.id}`); i.focus(); i.setSelectionRange(pos, pos); }, 200); };
  };
  const analyze = async () => { H.res = await api("hist", "analyze", { address: w.address, items: H.items }); };
  const loadPage = async pages => {
    const r = await api("hist", "page", { address: w.address, chain: w.chain, cursor: H.cursor, pages });
    H.items = H.items.concat(r.items); H.cursor = r.cursor; H.done = r.done;
  };
  box.onclick = async e => {
    const f = e.target.closest("[data-f]"); if (f) { H.filter = f.dataset.f; paint(); return; }
    const d = e.target.closest("[data-day]"); if (d) { H.day = H.day === d.dataset.day ? null : d.dataset.day; paint(); return; }
    const h = e.target.closest("[data-h]"); if (!h) return;
    if (h.dataset.h === "clearday") { H.day = null; paint(); }
    if (h.dataset.h === "stop") H.stop = true;
    if (h.dataset.h === "more") { h.disabled = true; try { await loadPage(2); await analyze(); } catch (er) { toast(er.message, true); } paint(); }
    if (h.dataset.h === "all") {
      H.loadingAll = true; H.stop = false; paint();
      try { while (!H.done && !H.stop) { await loadPage(3); await analyze(); if (tab.id === S.active && sub_is_history(tab)) paint(); } }
      catch (er) { toast(er.message, true); }
      H.loadingAll = false; paint();
    }
  };
  if (!H.started) {
    H.started = true; paint();
    try { await loadPage(2); await analyze(); } catch (er) { box.innerHTML = errBox(er); H.started = false; return; }
  }
  paint();
}
function sub_is_history(tab) { return !!$(".hbar", tab.el); }
function heatmap(days, selected) {
  const keys = Object.keys(days).sort(); if (!keys.length) return "";
  const end = new Date(keys[keys.length - 1] + "T00:00:00Z"); const start = new Date(end); start.setUTCDate(start.getUTCDate() - 7 * 52 - end.getUTCDay());
  const max = Math.max(...Object.values(days)); let cells = "", d = new Date(start), months = "", lastM = -1, col = 0;
  while (d <= end) {
    const k = d.toISOString().slice(0, 10), n = days[k] || 0, lvl = n ? Math.min(4, 1 + Math.floor((n / max) * 3.999)) : 0;
    if (d.getUTCDay() === 0) { if (d.getUTCMonth() !== lastM) { months += `<span style="grid-column:${col + 1}">${d.toLocaleString(undefined, { month: "short", timeZone: "UTC" })}</span>`; lastM = d.getUTCMonth(); } col++; }
    cells += `<i class="l${lvl}${selected === k ? " sel" : ""}" style="grid-column:${col};grid-row:${d.getUTCDay() + 1}" ${n ? `data-day="${k}"` : ""} title="${k}: ${n} transaction${n === 1 ? "" : "s"}"></i>`;
    d.setUTCDate(d.getUTCDate() + 1);
  }
  const older = keys.filter(k => new Date(k) < start).length;
  return `<div class="heat"><div class="hm-months" style="grid-template-columns:repeat(${col},11px)">${months}</div><div class="hm" style="grid-template-columns:repeat(${col},11px)">${cells}</div><div class="faint" style="font-size:11.5px">Last 12 months of loaded activity${older ? ` · ${older} older active days not shown` : ""}. Click a day to filter.</div></div>`;
}

/* ================================================================ Obsidian-style extras */
// Outline of the current note (shown under backlinks)
(() => {
  const base = VIEWS.note;
  VIEWS.note = tab => {
    const v = base(tab);
    v.outline = el => {
      const hs = $$(".reading h1, .reading h2, .reading h3, .reading h4", tab.el);
      if (!hs.length) return;
      const sec = document.createElement("div"); sec.className = "rsec";
      sec.innerHTML = `<h4>Outline <span class="cnt">${hs.length}</span></h4><div class="rlist">${hs.map((h, i) => `<div class="ritem" data-h="${i}" style="padding-left:${8 + (+h.tagName[1] - 1) * 12}px"><div class="rt">${esc(h.textContent)}</div></div>`).join("")}</div>`;
      sec.onclick = e => { const it = e.target.closest("[data-h]"); if (it) hs[+it.dataset.h].scrollIntoView({ behavior: "smooth", block: "start" }); };
      el.prepend(sec);
    };
    const load = v.load; v.load = async (...a) => { await load(...a); if (tab.id === S.active) renderRight(); };
    return v;
  };
})();

// Bookmarks (shown above the file tree)
const bookmarks = { list: store.get("bookmarks", []) };
function renderBookmarks() {
  let el = $("#bookmarks");
  if (!el) { el = document.createElement("div"); el.id = "bookmarks"; $("#pane-files").insertBefore(el, $("#tree")); }
  const live = bookmarks.list.filter(p => S.tree.files.some(f => f.path === p));
  el.innerHTML = live.length ? `<div class="pane-title" style="padding:4px 14px">Bookmarks</div><div style="padding:0 6px 6px">${live.map(p => { const f = S.tree.files.find(x => x.path === p); return `<div class="ti" data-file="${esc(p)}"><span class="star">★</span><span class="nm">${esc(f.type === "address" && f.label ? f.label : f.name)}</span></div>`; }).join("")}</div>` : "";
  el.onclick = e => { const n = e.target.closest("[data-file]"); if (n) openNote(n.dataset.file, e.metaKey || e.ctrlKey); };
}
function toggleBookmark(path) {
  if (!path) { toast("Open a note first", true); return; }
  const i = bookmarks.list.indexOf(path);
  i >= 0 ? bookmarks.list.splice(i, 1) : bookmarks.list.unshift(path);
  store.set("bookmarks", bookmarks.list); renderBookmarks(); toast(i >= 0 ? "Bookmark removed" : "Bookmarked");
}
bus.on("vault", renderBookmarks);

// Daily notes and templates
const TEMPLATES = {
  "Daily note": "# {{date}}\n\n## Leads\n- \n\n## Wallets looked at\n- \n\n## Notes\n",
  "Wallet investigation": "---\ntype: case\ntags:\n  - case\n---\n# {{title}}\n\n> [!abstract] Started {{date}}\n\n## Subject wallet\n- [[address-here]]\n\n## What I know\n- \n\n## Leads (unconfirmed)\n- \n\n## Evidence (tx hashes)\n- \n\n## Next steps\n- [ ] Trace funds in and out\n- [ ] Check mixer exposure\n- [ ] Check same-key wallets on other chains\n",
  "Malware sample": "---\ntype: malware\ntags:\n  - malware\n---\n# {{title}}\n\n> [!warning] Analysed statically. Never run the sample.\n\n| | |\n|---|---|\n| SHA-256 | |\n| Source | |\n| First seen | {{date}} |\n\n## Behaviour (from code)\n- \n\n## Indicators\n- \n\n## Wallets\n- \n",
  "Reverse engineering": "# {{title}}\n\n## Binary\n- Path: \n- Version: \n\n## Functions of interest\n| Address | Name | What it does |\n|---|---|---|\n|  |  |  |\n\n## Findings\n- \n",
};
const today = () => new Date().toISOString().slice(0, 10);
const fillTpl = (t, title) => t.replaceAll("{{date}}", today()).replaceAll("{{title}}", title || today());
async function openDaily() {
  const path = `Journal/${today()}.md`;
  if (!S.tree.files.some(f => f.path === path)) { try { await api("vault", "write", { path, content: fillTpl(TEMPLATES["Daily note"]) }); await refreshTree(); } catch (e) { toast(e.message, true); return; } }
  openNote(path, true);
}
async function ensureTemplates() {
  for (const [name, body] of Object.entries(TEMPLATES)) {
    const p = `Templates/${name}.md`;
    if (!S.tree.files.some(f => f.path === p)) { try { await api("vault", "write", { path: p, content: body }); } catch { } }
  }
  await refreshTree();
}
async function newFromTemplate() {
  await ensureTemplates();
  const tpls = S.tree.files.filter(f => f.path.startsWith("Templates/"));
  const pick = await promptInline(`Template: ${tpls.map(t => t.name).join(" · ")}`, tpls[0]?.name || "");
  if (!pick) return;
  const t = tpls.find(x => x.name.toLowerCase() === pick.toLowerCase()) || tpls.find(x => x.name.toLowerCase().startsWith(pick.toLowerCase()));
  if (!t) { toast("No template with that name", true); return; }
  const title = await promptInline("Title for the new note", t.name);
  if (!title) return;
  try {
    const tpl = await api("vault", "read", { path: t.path });
    const folder = /malware/i.test(t.name) ? "Malware" : /wallet|case/i.test(t.name) ? "Cases" : /reverse/i.test(t.name) ? "Binaries" : "";
    const r = await api("vault", "create", { folder, title, content: fillTpl(tpl.content, title) });
    await refreshTree(); openTab("note", { path: r.path, mode: "edit" }, { newTab: true });
  } catch (e) { toast(e.message, true); }
}
COMMANDS.push(
  { label: "Open today's daily note", kbd: "⌘D", icon: "note", run: openDaily },
  { label: "New note from template", icon: "note", run: newFromTemplate },
  { label: "Bookmark / unbookmark this note", icon: "star", run: () => { const t = cur(); toggleBookmark(t?.type === "note" ? t.st.path : null); } },
  { label: "Malware triage of a file", icon: "binary", run: async () => { const p = await promptInline("Path of the file or .app to triage (it is never run)", ""); if (p) { const t = openTab("binary", { path: p }, { newTab: true }); } } },
);
document.addEventListener("keydown", e => {
  if (!(e.metaKey || e.ctrlKey)) return;
  if (e.key.toLowerCase() === "d" && !e.shiftKey) { e.preventDefault(); openDaily(); }
});
