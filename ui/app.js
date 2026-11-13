/* Unwind UI. Plain JS, no build step. */
"use strict";
const TOKEN = document.querySelector('meta[name="unwind-token"]').content;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = MD.esc;
const store = {
  get(k, d) { try { const v = localStorage.getItem("unwind." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("unwind." + k, JSON.stringify(v)); } catch { } },
};

async function api(mod, fn, args = {}) {
  const r = await fetch(`/api/${mod}/${fn}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Unwind-Token": TOKEN }, body: JSON.stringify(args) });
  if (r.status === 403) throw new Error("The app server restarted. Reload this page.");
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "Something went wrong");
  return j.data;
}
const bus = { h: {}, on(e, f) { (this.h[e] ||= []).push(f); }, emit(e, d) { (this.h[e] || []).forEach(f => { try { f(d); } catch (x) { console.error(x); } }); } };

/* ---------------------------------------------------------------- formatting */
const fmtUsd = v => {
  if (v == null || isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
  if (a >= 100) return "$" + Math.round(v).toLocaleString();
  if (a >= 1) return "$" + v.toFixed(2);
  if (a > 0) return "<$1";
  return "$0";
};
const fmtAmt = (v, sym = "") => {
  if (v == null || isNaN(v)) return "—";
  const a = Math.abs(v);
  let s;
  if (a >= 1e15) s = v.toExponential(2);
  else if (a >= 1e12) s = (v / 1e12).toFixed(2) + "T";
  else if (a >= 1e9) s = (v / 1e9).toFixed(2) + "B";
  else if (a >= 1e6) s = (v / 1e6).toFixed(2) + "M";
  else if (a >= 1000) s = Math.round(v).toLocaleString();
  else if (a >= 1) s = (+v.toFixed(4)).toLocaleString(undefined, { maximumFractionDigits: 4 });
  else if (a === 0) s = "0";
  else s = (+v.toPrecision(4)).toString();
  return sym ? `${s} ${sym}` : s;
};
const short = (a, n = 6) => !a ? "" : a.length <= n * 2 + 3 ? a : `${a.slice(0, n)}…${a.slice(-4)}`;
const ago = iso => {
  if (!iso) return "";
  const t = typeof iso === "number" ? iso * 1000 : Date.parse(iso); if (!t) return "";
  const s = (Date.now() - t) / 1000;
  if (s < 60) return "just now"; if (s < 3600) return Math.floor(s / 60) + "m ago"; if (s < 86400) return Math.floor(s / 3600) + "h ago";
  if (s < 86400 * 45) return Math.floor(s / 86400) + "d ago"; if (s < 86400 * 400) return Math.floor(s / 86400 / 30.4) + "mo ago";
  return (s / 86400 / 365.25).toFixed(1) + "y ago";
};
const dateStr = iso => { const t = Date.parse(iso); return t ? new Date(t).toISOString().slice(0, 16).replace("T", " ") : ""; };
const ICONS = {
  note: '<svg viewBox="0 0 24 24"><path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5M8.5 13h7M8.5 17h5"/></svg>',
  graph: '<svg viewBox="0 0 24 24"><circle cx="6" cy="7" r="2.3"/><circle cx="18" cy="6" r="2.3"/><circle cx="12" cy="17" r="2.6"/><path d="M8 8.2 10.8 15M16 7.6l-3 7.2M8.2 7l7.5-.8"/></svg>',
  trace: '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="2.3"/><circle cx="19" cy="6" r="2.3"/><circle cx="19" cy="18" r="2.3"/><path d="M7.2 11 16.8 6.8M7.2 13l9.6 4.2"/></svg>',
  wallet: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18M16 14.5h2"/><path d="M6 6V5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>',
  tx: '<svg viewBox="0 0 24 24"><path d="M4 8h13l-3-3M20 16H7l3 3"/></svg>',
  binary: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8.5 9 6.5 12l2 3M15.5 9l2 3-2 3M13 8l-2 8"/></svg>',
  lab: '<svg viewBox="0 0 24 24"><path d="M9 3h6M10 3v6l-5.5 9.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3"/><path d="M7.5 15h9"/></svg>',
  settings: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/></svg>',
  home: '<svg viewBox="0 0 24 24"><path d="M4 11 12 4l8 7v8.5a1.5 1.5 0 0 1-1.5 1.5H15v-6H9v6H5.5A1.5 1.5 0 0 1 4 19.5z"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  chev: '<svg class="tw" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg>',
  copy: '<svg viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8"/></svg>',
  ext: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/></svg>',
  save: '<svg viewBox="0 0 24 24"><path d="M5 4h11l3 3v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M7 5v14l11-7z"/></svg>',
  edit: '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/></svg>',
  book: '<svg viewBox="0 0 24 24"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5zM20 5.5A1.5 1.5 0 0 0 18.5 4H13v16h5.5a1.5 1.5 0 0 0 1.5-1.5z"/></svg>',
  more: '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>',
  back: '<svg viewBox="0 0 24 24"><path d="M15 6l-6 6 6 6"/></svg>',
  fit: '<svg viewBox="0 0 24 24"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  minus: '<svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg>',
};

/* ---------------------------------------------------------------- global state */
const S = { chains: [], chainMap: {}, flagInfo: {}, info: {}, tree: { files: [], folders: [] }, tabs: [], active: null, seq: 0 };
const TYPE_COLOR = { address: "var(--accent)", case: "var(--warn)", binary: "var(--info)", tx: "var(--muted)", report: "var(--good)", note: "var(--fg-2)", unresolved: "var(--faint)" };
const cssVar = v => v.startsWith("var(") ? getComputedStyle(document.documentElement).getPropertyValue(v.slice(4, -1)).trim() : v;

function toast(msg, err = false, ms = 3800) {
  const t = document.createElement("div"); t.className = "toast" + (err ? " err" : ""); t.textContent = msg;
  $("#toasts").appendChild(t); setTimeout(() => t.remove(), ms);
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied"); }
  catch { toast("Couldn't copy. Select the text and copy it manually.", true); }
}
function pill(flag) {
  const f = S.flagInfo[flag] || { label: flag, tone: "muted", hint: "" };
  return `<span class="pill t-${f.tone}" title="${esc(f.hint || "")}">${esc(f.label)}</span>`;
}
const pills = flags => `<div class="pills">${(flags || []).map(pill).join("")}</div>`;
function chainChip(id, btn = false, on = false) {
  const c = S.chainMap[id] || { name: id, color: "#888" };
  return btn ? `<button class="chain-chip${on ? " on" : ""}" data-chain="${esc(id)}"><i style="background:${c.color}"></i>${esc(c.name)}</button>`
    : `<span class="chain-chip"><i style="background:${c.color}"></i>${esc(c.name)}</span>`;
}
const loading = msg => `<div class="loading"><div class="spin"></div>${esc(msg)}</div>`;
const errBox = e => `<div class="err">${esc(e.message || e)}</div>`;
const addrLink = (a, label, chain) => a ? `<span class="addr" data-wallet="${esc(a)}" data-chain="${esc(chain || "auto")}" title="${esc(a)}">${label ? `<span class="lab">${esc(label)}</span>` : esc(short(a))}</span>` : "—";
const txLink = (h, chain) => h ? `<span class="addr" data-tx="${esc(h)}" data-chain="${esc(chain || "auto")}" title="${esc(h)}">${esc(short(h, 8))}</span>` : "";
function chainSelect(id, value = "auto", allowAuto = true) {
  const groups = {};
  S.chains.forEach(c => { const g = c.testnet ? "Testnets" : c.family === "esplora" ? "UTXO" : (c.family === "blockscout" || c.family === "etherscan") ? "EVM" : "Other"; (groups[g] ||= []).push(c); });
  let o = allowAuto ? `<option value="auto"${value === "auto" ? " selected" : ""}>Auto-detect</option>` : "";
  for (const g of ["UTXO", "EVM", "Other", "Testnets"]) {
    if (!groups[g]) continue;
    o += `<optgroup label="${g}">` + groups[g].map(c => `<option value="${c.id}"${c.id === value ? " selected" : ""}${c.available ? "" : " disabled"}>${esc(c.name)}${c.available ? "" : " (needs key)"}</option>`).join("") + "</optgroup>";
  }
  return `<select class="sel" id="${id}">${o}</select>`;
}
function looksLike(q) {
  q = (q || "").trim();
  if (!q) return null;
  if (/^(\/|~\/)/.test(q) || /\.app\/?$/.test(q)) return "binary";
  if (/^[0-9a-fA-F]{64}:\d+$/.test(q)) return "coin";
  if (/^0x[0-9a-fA-F]{64}$/.test(q) || /^[0-9a-fA-F]{64}$/.test(q) || /^[1-9A-HJ-NP-Za-km-z]{86,88}$/.test(q)) return "tx";
  if (/^0x[0-9a-fA-F]{40}$/.test(q) || /^(bc1|tb1|ltc1)[0-9a-z]{8,}$/i.test(q) || /^[13LMT][1-9A-HJ-NP-Za-km-z]{25,34}$/.test(q) ||
    /^r[1-9A-HJ-NP-Za-km-z]{24,34}$/.test(q) || /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(q) || /^[EUk0][QfF][\w-]{46}$/.test(q) || /^[48][1-9A-HJ-NP-Za-km-z]{94}/.test(q) || /^[\w-]+\.(eth|xyz|base\.eth)$/i.test(q)) return "address";
  return null;
}

/* ---------------------------------------------------------------- tabs */
const VIEWS = {};
function tabKey(type, st) {
  if (type === "note") return "note:" + st.path;
  if (type === "wallet") return "wallet:" + (st.address || "").toLowerCase() + ":" + (st.chain || "auto");
  if (type === "tx") return "tx:" + st.hash;
  if (type === "binary" && st.path) return "binary:" + st.path;
  if (["graph", "settings", "lab"].includes(type)) return type;
  return null;
}
function openTab(type, st = {}, opts = {}) {
  const key = tabKey(type, st);
  if (key && !opts.forceNew) { const ex = S.tabs.find(t => t.key === key); if (ex) { activate(ex.id); if (opts.update) ex.update?.(st); return ex; } }
  const cur = S.tabs.find(t => t.id === S.active);
  if (!opts.newTab && cur && (cur.type === "home" || (cur.type === type && type === "note" && !opts.keep))) {
    if (cur.type !== "home") { closeTab(cur.id, true); } else { closeTab(cur.id, true); }
  }
  const id = "t" + (++S.seq);
  const el = document.createElement("div"); el.className = "view"; el.hidden = true; $("#views").appendChild(el);
  const tab = { id, type, key, st: Object.assign({}, st), el, title: "…" };
  Object.assign(tab, VIEWS[type](tab));
  S.tabs.push(tab);
  tab.mount?.();
  activate(id);
  saveTabs();
  return tab;
}
function activate(id) {
  S.active = id;
  S.tabs.forEach(t => { const on = t.id === id; if (t.el.hidden === on) { t.el.hidden = !on; on ? t.show?.() : t.hide?.(); } });
  renderTabs(); renderRight(); renderStatus(); saveTabs();
  const t = cur(); if (t?.type === "note") highlightTree(t.st.path); else highlightTree(null);
}
function closeTab(id, silent) {
  const i = S.tabs.findIndex(t => t.id === id); if (i < 0) return;
  const t = S.tabs[i]; t.destroy?.(); t.el.remove(); S.tabs.splice(i, 1);
  if (silent) return;
  if (!S.tabs.length) openTab("home");
  else if (S.active === id) activate(S.tabs[Math.min(i, S.tabs.length - 1)].id);
  else renderTabs();
  saveTabs();
}
const cur = () => S.tabs.find(t => t.id === S.active);
function setTitle(tab, title, busy) { tab.title = title; tab.busy = !!busy; renderTabs(); if (tab.id === S.active) document.title = title + " · Unwind"; }
function renderTabs() {
  $("#tabs").innerHTML = S.tabs.map(t => `<button class="tab${t.id === S.active ? " active" : ""}${t.busy ? " busy" : ""}" data-tab="${t.id}" role="tab" title="${esc(t.title)}">
    <span class="t-ic">${ICONS[t.icon || t.type] || ICONS.note}</span><span class="t-nm">${esc(t.title)}</span><span class="t-x" data-close="${t.id}" title="Close (⌘W)">${ICONS.x}</span></button>`).join("");
}
$("#tabs").addEventListener("click", e => {
  const x = e.target.closest("[data-close]"); if (x) { e.stopPropagation(); closeTab(x.dataset.close); return; }
  const t = e.target.closest("[data-tab]"); if (t) activate(t.dataset.tab);
});
$("#tabs").addEventListener("auxclick", e => { const t = e.target.closest("[data-tab]"); if (t && e.button === 1) closeTab(t.dataset.tab); });
$("#new-tab").onclick = () => openTab("home", {}, { newTab: true });
function saveTabs() {
  store.set("tabs", { list: S.tabs.filter(t => t.type !== "home").map(t => ({ type: t.type, st: t.persist ? t.persist() : t.st })), active: S.tabs.findIndex(t => t.id === S.active) });
}
function renderRight() {
  const t = cur(); const rb = $("#right-body");
  if (t?.right) { rb.innerHTML = ""; t.right(rb); } else rb.innerHTML = `<div class="r-empty" style="padding:12px">Nothing to show for this tab.</div>`;
}

/* ---------------------------------------------------------------- global delegation */
document.addEventListener("click", e => {
  const w = e.target.closest("[data-wallet]");
  if (w) { e.preventDefault(); openTab("wallet", { address: w.dataset.wallet, chain: w.dataset.chain || "auto" }, { newTab: e.metaKey || e.ctrlKey }); return; }
  const tx = e.target.closest("[data-tx]");
  if (tx) { e.preventDefault(); openTab("tx", { hash: tx.dataset.tx, chain: tx.dataset.chain || "auto" }, { newTab: e.metaKey || e.ctrlKey }); return; }
  const l = e.target.closest("a.internal");
  if (l) { e.preventDefault(); openLink(l.dataset.link, e.metaKey || e.ctrlKey); return; }
  const tg = e.target.closest("a.tag");
  if (tg) { e.preventDefault(); showPane("search"); $("#search-input").value = "#" + tg.dataset.tag; runSearch(); return; }
  const cp = e.target.closest("[data-copy]");
  if (cp) { e.preventDefault(); copy(cp.dataset.copy); return; }
  const op = e.target.closest("[data-open-note]");
  if (op) { e.preventDefault(); openNote(op.dataset.openNote, e.metaKey || e.ctrlKey); return; }
  if (!e.target.closest("#menu")) $("#menu").hidden = true;
});
function resolveName(name) {
  const n = name.trim().replace(/\.md$/, "").toLowerCase();
  return S.tree.files.find(f => f.path.toLowerCase() === n + ".md") || S.tree.files.find(f => f.name.toLowerCase() === n) || S.tree.files.find(f => (f.label || "").toLowerCase() === n);
}
function openLink(target, newTab) {
  const f = resolveName(target);
  if (f) return openNote(f.path, newTab);
  if (looksLike(target) === "address") return openTab("wallet", { address: target, chain: "auto" }, { newTab });
  if (looksLike(target) === "tx") return openTab("tx", { hash: target, chain: "auto" }, { newTab });
  api("vault", "create", { folder: "", title: target, content: `# ${target}\n\n` }).then(r => { refreshTree(); openNote(r.path, newTab); }).catch(e => toast(e.message, true));
}
function openNote(path, newTab) { return openTab("note", { path, mode: "read" }, { newTab }); }
function showMenu(x, y, items) {
  const m = $("#menu");
  m.innerHTML = items.map((it, i) => it === "-" ? "<hr>" : `<button data-i="${i}" class="${it.danger ? "danger" : ""}">${esc(it.label)}</button>`).join("");
  m.hidden = false;
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(x, innerWidth - r.width - 8) + "px"; m.style.top = Math.min(y, innerHeight - r.height - 8) + "px";
  m.onclick = e => { const b = e.target.closest("[data-i]"); if (!b) return; m.hidden = true; items[+b.dataset.i].run(); };
}
const tip = $("#tooltip");
function showTip(html, e) { if (!html) { tip.hidden = true; return; } tip.innerHTML = html; tip.hidden = false; const r = tip.getBoundingClientRect(); tip.style.left = Math.min(e.clientX + 14, innerWidth - r.width - 8) + "px"; tip.style.top = Math.min(e.clientY + 14, innerHeight - r.height - 8) + "px"; }

/* ---------------------------------------------------------------- sidebars */
const layout = store.get("layout", { left: true, right: true, pane: "files" });
function applyLayout() {
  $("#app").classList.toggle("no-left", !layout.left);
  $("#app").classList.toggle("no-right", !layout.right);
  $$(".rb[data-pane]").forEach(b => b.classList.toggle("on", layout.left && b.dataset.pane === layout.pane));
  $("#pane-files").hidden = layout.pane !== "files"; $("#pane-search").hidden = layout.pane !== "search";
  store.set("layout", layout);
}
function showPane(p) { layout.pane = p; layout.left = true; applyLayout(); if (p === "search") setTimeout(() => $("#search-input").focus(), 0); }
$$(".rb[data-pane]").forEach(b => b.onclick = () => { if (layout.left && layout.pane === b.dataset.pane) { layout.left = false; applyLayout(); } else showPane(b.dataset.pane); });
$$(".rb[data-open]").forEach(b => b.onclick = () => openTab(b.dataset.open, {}, { newTab: b.dataset.open === "trace" || b.dataset.open === "binary" }));
$("#toggle-left").onclick = () => { layout.left = !layout.left; applyLayout(); };
$("#toggle-right").onclick = () => { layout.right = !layout.right; applyLayout(); };

/* file tree */
const openFolders = new Set(store.get("folders", ["Cases", "Wallets"]));
async function refreshTree() {
  try { S.tree = await api("vault", "tree"); } catch (e) { $("#tree").innerHTML = errBox(e); return; }
  renderTree(); renderStatus(); bus.emit("vault");
}
function renderTree() {
  const root = { folders: {}, files: [] };
  const ensure = path => path.split("/").reduce((n, part) => (n.folders[part] ||= { folders: {}, files: [] }), root);
  S.tree.folders.forEach(f => ensure(f));
  S.tree.files.forEach(f => { const parts = f.path.split("/"); const dir = parts.slice(0, -1).join("/"); (dir ? ensure(dir) : root).files.push(f); });
  const dot = f => { const danger = (f.flags || []).some(x => ["mixer", "scam", "mixer_exposure"].includes(x)); return `<i class="dot" style="background:${danger ? "var(--danger)" : TYPE_COLOR[f.type] || "var(--faint)"}"></i>`; };
  const build = (node, prefix) => {
    let h = "";
    Object.keys(node.folders).sort((a, b) => a.localeCompare(b)).forEach(name => {
      const p = prefix ? prefix + "/" + name : name, open = openFolders.has(p);
      h += `<div class="ti folder${open ? " open" : ""}" data-folder="${esc(p)}" role="treeitem" aria-expanded="${open}">${ICONS.chev}<span class="nm">${esc(name)}</span></div>
        <div class="tchildren${open ? "" : " closed"}">${build(node.folders[name], p)}</div>`;
    });
    node.files.sort((a, b) => (a.label || a.name).localeCompare(b.label || b.name)).forEach(f => {
      const lab = f.type === "address" && f.label ? f.label : f.name;
      h += `<div class="ti" data-file="${esc(f.path)}" role="treeitem" title="${esc(f.path)}">${dot(f)}<span class="nm">${esc(lab)}</span></div>`;
    });
    return h;
  };
  const html = build(root, "");
  $("#tree").innerHTML = html || `<div class="tree-empty">No notes yet. Trace a wallet and save it, or press ⌘N.</div>`;
  const t = cur(); if (t?.type === "note") highlightTree(t.st.path);
}
function highlightTree(path) { $$("#tree .ti.active").forEach(x => x.classList.remove("active")); if (path) { const el = $(`#tree [data-file="${CSS.escape(path)}"]`); el?.classList.add("active"); } }
$("#tree").addEventListener("click", e => {
  const f = e.target.closest("[data-folder]");
  if (f) { const p = f.dataset.folder; openFolders.has(p) ? openFolders.delete(p) : openFolders.add(p); store.set("folders", [...openFolders]); renderTree(); return; }
  const n = e.target.closest("[data-file]"); if (n) openNote(n.dataset.file, e.metaKey || e.ctrlKey);
});
$("#tree").addEventListener("contextmenu", e => {
  const n = e.target.closest("[data-file]"); if (!n) return; e.preventDefault();
  const p = n.dataset.file;
  showMenu(e.clientX, e.clientY, [
    { label: "Open in new tab", run: () => openNote(p, true) },
    { label: "Rename…", run: () => renameNote(p) },
    { label: "Copy path", run: () => copy(p) }, "-",
    { label: "Move to trash", danger: true, run: () => deleteNote(p) },
  ]);
});
async function renameNote(p) {
  const name = await promptInline("Rename note", p.split("/").pop().replace(/\.md$/, ""));
  if (!name) return;
  try { const r = await api("vault", "rename", { path: p, new_name: name }); toast(`Renamed. Updated links in ${r.links_updated} notes.`); S.tabs.filter(t => t.type === "note" && t.st.path === p).forEach(t => { t.st.path = r.path; t.key = "note:" + r.path; t.load(); }); refreshTree(); }
  catch (e) { toast(e.message, true); }
}
async function deleteNote(p) {
  const ok = await confirmInline(`Move “${p.split("/").pop()}” to the vault's .trash folder?`, "Move to trash");
  if (!ok) return;
  try { await api("vault", "delete", { path: p }); S.tabs.filter(t => t.type === "note" && t.st.path === p).forEach(t => closeTab(t.id)); refreshTree(); toast("Moved to .trash"); }
  catch (e) { toast(e.message, true); }
}
$("#new-note").onclick = () => newNote();
$("#new-folder").onclick = async () => { const n = await promptInline("New folder", "Cases/"); if (!n) return; try { await api("vault", "mkdir", { path: n }); openFolders.add(n.replace(/\/$/, "")); refreshTree(); } catch (e) { toast(e.message, true); } };
$("#refresh-tree").onclick = () => refreshTree();
async function newNote(folder = "", title = "Untitled") {
  try { const r = await api("vault", "create", { folder, title }); await refreshTree(); openTab("note", { path: r.path, mode: "edit" }, { newTab: true }); }
  catch (e) { toast(e.message, true); }
}

/* inline prompt / confirm (the page shows its own dialogs) */
function promptInline(title, value = "") {
  return new Promise(res => {
    const w = $("#palette"); w.hidden = false;
    const inp = $("#palette-input"); inp.value = value; inp.placeholder = title;
    $("#palette-list").innerHTML = `<div class="pi on"><span class="pt">${esc(title)}: press Enter to confirm, Esc to cancel</span></div>`;
    inp.focus(); inp.select();
    const done = v => { w.hidden = true; inp.onkeydown = null; inp.oninput = null; inp.placeholder = "Type a command, note, address or transaction…"; res(v); };
    inp.oninput = () => { };
    inp.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); done(inp.value.trim()); } if (e.key === "Escape") done(null); };
    w.onclick = e => { if (e.target === w) done(null); };
  });
}
function confirmInline(msg, yes = "Confirm") {
  return new Promise(res => {
    const w = $("#palette"); w.hidden = false;
    const inp = $("#palette-input"); inp.value = ""; inp.placeholder = msg; inp.readOnly = true;
    $("#palette-list").innerHTML = `<div class="pi on" data-v="1"><span class="pt">${esc(yes)}</span><span class="pk2">Enter</span></div><div class="pi" data-v="0"><span class="pt">Cancel</span><span class="pk2">Esc</span></div>`;
    inp.focus();
    const done = v => { w.hidden = true; inp.readOnly = false; inp.onkeydown = null; inp.placeholder = "Type a command, note, address or transaction…"; res(v); };
    inp.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); done(true); } if (e.key === "Escape") done(false); };
    $("#palette-list").onclick = e => { const p = e.target.closest("[data-v]"); if (p) done(p.dataset.v === "1"); };
    w.onclick = e => { if (e.target === w) done(false); };
  });
}

/* search pane */
let searchT;
$("#search-input").addEventListener("input", () => { clearTimeout(searchT); searchT = setTimeout(runSearch, 180); });
async function runSearch() {
  const q = $("#search-input").value.trim(); const box = $("#search-results");
  if (!q) { box.innerHTML = ""; return; }
  try {
    const r = await api("vault", "search", { query: q });
    const rx = q.startsWith("#") ? null : new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "ig");
    const hl = s => rx ? esc(s).replace(rx, m => `<mark>${m}</mark>`) : esc(s);
    box.innerHTML = r.results.length ? r.results.map(x => `<div class="sr" data-open-note="${esc(x.path)}"><div class="sn">${hl(x.label || x.name)}</div>${(x.hits || []).slice(0, 2).map(h => `<div class="sh">${hl(h.text)}</div>`).join("")}</div>`).join("")
      : `<div class="r-empty">No matches.</div>`;
  } catch (e) { box.innerHTML = errBox(e); }
}

/* status bar */
function renderStatus() {
  const n = S.tree.files.length, keyOn = S.info.settings?.etherscan_key_set;
  $("#st-left").innerHTML = `${n} notes · <span title="${esc(S.info.vault || "")}">vault</span>`;
  const t = cur();
  $("#st-right").innerHTML = `${t?.status ? esc(t.status) + " · " : ""}<span class="ok">local</span> · ${S.chains.filter(c => c.available).length}/${S.chains.length} chains · <button data-st="key">Etherscan key ${keyOn ? "on" : "off"}</button> · <button data-st="agent">Connect agent</button>`;
}
$("#status").addEventListener("click", e => { const b = e.target.closest("[data-st]"); if (b) openTab("settings"); });

/* ---------------------------------------------------------------- command palette */
const COMMANDS = [
  { label: "Trace money from an address", kbd: "⌘T", icon: "trace", run: () => openTab("trace", {}, { newTab: true }) },
  { label: "Open graph view", kbd: "⌘G", icon: "graph", run: () => openTab("graph") },
  { label: "Open binary workbench", kbd: "⌘B", icon: "binary", run: () => openTab("binary", {}, { newTab: true }) },
  { label: "Forensics lab: peel chains, clusters, amount matching", icon: "lab", run: () => openTab("lab") },
  { label: "New note", kbd: "⌘N", icon: "note", run: () => newNote() },
  { label: "Search the vault", kbd: "⌘⇧F", icon: "note", run: () => showPane("search") },
  { label: "Settings, Etherscan key and agent connection", icon: "settings", run: () => openTab("settings") },
  { label: "Toggle left sidebar", kbd: "⌘\\", icon: "note", run: () => { layout.left = !layout.left; applyLayout(); } },
  { label: "Toggle right sidebar", icon: "note", run: () => { layout.right = !layout.right; applyLayout(); } },
  { label: "Theme: follow system", icon: "settings", run: () => setTheme("system") },
  { label: "Theme: dark", icon: "settings", run: () => setTheme("dark") },
  { label: "Theme: light", icon: "settings", run: () => setTheme("light") },
  { label: "Close tab", kbd: "⌘W", icon: "x", run: () => S.active && closeTab(S.active) },
];
let palItems = [], palIdx = 0, palMode = "all";
function openPalette(mode = "all") {
  palMode = mode; const w = $("#palette"); w.hidden = false; const inp = $("#palette-input");
  inp.readOnly = false; inp.value = ""; inp.placeholder = mode === "notes" ? "Find a note…" : "Type a command, note, address, transaction or file path…";
  inp.onkeydown = palKey; inp.oninput = palRender; w.onclick = e => { if (e.target === w) w.hidden = true; };
  $("#palette-list").onclick = e => { const p = e.target.closest("[data-pi]"); if (p) { palIdx = +p.dataset.pi; palRun(); } };
  palRender(); inp.focus();
}
function fuzzy(q, s) {
  q = q.toLowerCase(); s = s.toLowerCase(); if (!q) return 1; if (s.includes(q)) return 100 - s.indexOf(q);
  let i = 0, score = 0; for (const ch of s) { if (ch === q[i]) { i++; score++; } if (i === q.length) return score; } return 0;
}
function palRender() {
  const q = $("#palette-input").value.trim(); const items = [];
  const kind = looksLike(q);
  if (kind === "address") { items.push({ label: `Trace money from ${short(q, 10)}`, icon: "trace", grp: "Address", run: () => openTab("trace", { query: q, autorun: true }, { newTab: true }) }); items.push({ label: `Open wallet ${short(q, 10)}`, icon: "wallet", grp: "Address", run: () => openTab("wallet", { address: q, chain: "auto" }, { newTab: true }) }); }
  if (kind === "tx") items.push({ label: `Inspect transaction ${short(q, 10)}`, icon: "tx", grp: "Transaction", run: () => openTab("tx", { hash: q, chain: "auto" }, { newTab: true }) });
  if (kind === "coin") items.push({ label: `Look up coin ${short(q, 10)}`, icon: "lab", grp: "Coin", run: () => openTab("lab", { tool: "coin", inputs: { coin: q } }, { update: true }) });
  if (kind === "binary") items.push({ label: `Open binary ${q}`, icon: "binary", grp: "File", run: () => openTab("binary", { path: q }, { newTab: true }) });
  const notes = S.tree.files.map(f => ({ f, s: Math.max(fuzzy(q, f.label || ""), fuzzy(q, f.name), fuzzy(q, f.path) * 0.8) })).filter(x => x.s > 0).sort((a, b) => b.s - a.s).slice(0, palMode === "notes" ? 40 : 12)
    .map(x => ({ label: x.f.label && x.f.type === "address" ? x.f.label : x.f.name, sub: x.f.path, icon: "note", grp: "Note", run: () => openNote(x.f.path, true) }));
  if (palMode !== "notes") COMMANDS.map(c => ({ c, s: fuzzy(q, c.label) })).filter(x => x.s > 0).sort((a, b) => b.s - a.s).forEach(x => items.push(Object.assign({ grp: "Command" }, x.c)));
  items.push(...notes);
  if (q && palMode === "notes" && !notes.length) items.push({ label: `Create note “${q}”`, icon: "plus", grp: "New", run: () => newNote("", q) });
  palItems = items; palIdx = 0;
  $("#palette-list").innerHTML = items.map((it, i) => `<div class="pi${i === 0 ? " on" : ""}" data-pi="${i}" role="option"><span class="t-ic">${ICONS[it.icon] || ICONS.note}</span><span class="pt">${esc(it.label)}${it.sub ? ` <span class="faint">${esc(it.sub)}</span>` : ""}</span>${it.kbd ? `<kbd>${it.kbd}</kbd>` : `<span class="grp">${esc(it.grp || "")}</span>`}</div>`).join("") || `<div class="pi"><span class="pt muted">Nothing matches.</span></div>`;
}
function palKey(e) {
  const n = palItems.length;
  if (e.key === "ArrowDown") { e.preventDefault(); palIdx = (palIdx + 1) % n; }
  else if (e.key === "ArrowUp") { e.preventDefault(); palIdx = (palIdx - 1 + n) % n; }
  else if (e.key === "Enter") { e.preventDefault(); palRun(); return; }
  else if (e.key === "Escape") { $("#palette").hidden = true; return; }
  else return;
  $$("#palette-list .pi").forEach((el, i) => el.classList.toggle("on", i === palIdx));
  $$("#palette-list .pi")[palIdx]?.scrollIntoView({ block: "nearest" });
}
function palRun() { const it = palItems[palIdx]; if (!it) return; $("#palette").hidden = true; it.run(); }

/* keyboard */
document.addEventListener("keydown", e => {
  const mod = e.metaKey || e.ctrlKey; if (!mod) return;
  const k = e.key.toLowerCase();
  if (k === "k" || (k === "p" && !e.shiftKey)) { e.preventDefault(); openPalette(); }
  else if (k === "o") { e.preventDefault(); openPalette("notes"); }
  else if (k === "n") { e.preventDefault(); newNote(); }
  else if (k === "g") { e.preventDefault(); openTab("graph"); }
  else if (k === "t") { e.preventDefault(); openTab("trace", {}, { newTab: true }); }
  else if (k === "b") { e.preventDefault(); openTab("binary", {}, { newTab: true }); }
  else if (k === "w") { e.preventDefault(); S.active && closeTab(S.active); }
  else if (k === "\\") { e.preventDefault(); layout.left = !layout.left; applyLayout(); }
  else if (k === "f" && e.shiftKey) { e.preventDefault(); showPane("search"); }
  else if (k === "e" && e.shiftKey) { e.preventDefault(); showPane("files"); }
  else if (k === "e") { const t = cur(); if (t?.type === "note") { e.preventDefault(); t.toggleMode(); } }
  else if (k === "s") { const t = cur(); if (t?.save) { e.preventDefault(); t.save(); } }
});
function setTheme(t) { if (t === "system") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t); store.set("theme", t); bus.emit("theme"); }

/* ================================================================ VIEWS */

/* ---------- home */
VIEWS.home = tab => ({
  icon: "home",
  mount() {
    setTitle(tab, "New tab");
    const recent = [...S.tree.files].sort((a, b) => b.mtime - a.mtime).slice(0, 8);
    tab.el.innerHTML = `<div class="view-scroll"><div class="page narrow" style="padding-top:9vh">
      <div><h1 style="font-size:28px;margin:0 0 6px;letter-spacing:-.02em">Where does it go?</h1>
      <p class="muted" style="margin:0">Paste an address, ENS name, transaction hash or coin id to follow the money, or a file path to take a program apart.</p></div>
      <input class="inp big mono" id="home-q" placeholder="bc1q…, 0x…, vitalik.eth, T…, r…, txid, txid:vout, /Applications/…" autocomplete="off" spellcheck="false">
      <div class="examples">Try:
        <button data-q="vitalik.eth">vitalik.eth</button>
        <button data-q="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa">Genesis address</button>
        <button data-q="f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16">First BTC payment</button>
        <button data-q="/System/Applications/Calculator.app">Calculator.app</button></div>
      <div class="grid2">
        <div class="card"><h3>Start</h3><div class="rlist">
          <div class="ritem" data-go="trace"><div class="rt">Trace money</div><div class="rc">Follow funds hop by hop across 40+ chains, with flags for whales, exchanges and mixers.</div></div>
          <div class="ritem" data-go="lab"><div class="rt">Forensics lab</div><div class="rc">Peel chains, clustering, coin history, same-owner links and amount matching.</div></div>
          <div class="ritem" data-go="binary"><div class="rt">Binary workbench</div><div class="rc">Functions, strings, disassembly and cross-references for any program on this Mac.</div></div>
          <div class="ritem" data-go="graph"><div class="rt">Graph view</div><div class="rc">How your cases, wallets and notes connect.</div></div>
        </div></div>
        <div class="card"><h3>Recent notes</h3><div class="rlist">${recent.map(f => `<div class="ritem" data-open-note="${esc(f.path)}"><div class="rt">${esc(f.type === "address" && f.label ? f.label : f.name)}</div><div class="rc">${esc(f.path)}</div></div>`).join("") || `<div class="r-empty">No notes yet.</div>`}</div></div>
      </div></div></div>`;
    const q = $("#home-q", tab.el);
    const go = v => {
      v = v.trim(); const k = looksLike(v);
      if (k === "binary") openTab("binary", { path: v }); else if (k === "tx") openTab("tx", { hash: v, chain: "auto" });
      else if (k === "coin") openTab("lab", { tool: "coin", inputs: { coin: v } }, { update: true });
      else if (k === "address") openTab("wallet", { address: v, chain: "auto" }); else if (v) toast("I don't recognise that. Paste an address, tx hash, coin id (txid:vout) or a file path.", true);
    };
    q.onkeydown = e => { if (e.key === "Enter") go(q.value); };
    tab.el.addEventListener("click", e => { const b = e.target.closest("[data-q]"); if (b) go(b.dataset.q); const g = e.target.closest("[data-go]"); if (g) openTab(g.dataset.go); });
  },
  show() { setTimeout(() => $("#home-q", tab.el)?.focus(), 30); },
  right(el) { el.innerHTML = `<div class="rsec"><h4>Shortcuts</h4><div class="kv"><dt><kbd>⌘K</kbd></dt><dd>Command palette</dd><dt><kbd>⌘O</kbd></dt><dd>Quick switcher</dd><dt><kbd>⌘N</kbd></dt><dd>New note</dd><dt><kbd>⌘E</kbd></dt><dd>Edit / read note</dd><dt><kbd>⌘G</kbd></dt><dd>Graph</dd><dt><kbd>⌘T</kbd></dt><dd>Trace</dd><dt><kbd>⌘B</kbd></dt><dd>Binary</dd><dt><kbd>⌘W</kbd></dt><dd>Close tab</dd></div></div>`; },
});

/* ---------- note */
VIEWS.note = tab => {
  let data = null, saveT = null, dirty = false;
  const v = {
    icon: "note",
    persist: () => ({ path: tab.st.path, mode: tab.st.mode }),
    async load() {
      tab.el.innerHTML = loading("Opening note…");
      try { data = await api("vault", "read", { path: tab.st.path }); } catch (e) { tab.el.innerHTML = `<div class="page">${errBox(e)}</div>`; setTitle(tab, "Missing note"); return; }
      setTitle(tab, data.frontmatter.label && data.frontmatter.type === "address" ? data.frontmatter.label : data.name);
      v.render(); renderRight();
    },
    mount() { v.load(); },
    render() {
      const parts = tab.st.path.split("/");
      const fm = data.frontmatter;
      const actions = fm.type === "address" ? `<button class="btn sm ghost" data-act="wallet">${ICONS.wallet} Wallet</button><button class="btn sm ghost" data-act="trace">${ICONS.trace} Trace</button><button class="btn sm ghost" data-act="refresh">Refresh data</button>` : "";
      tab.el.innerHTML = `<div class="note-head"><div class="crumbs">${parts.slice(0, -1).map(p => `<span>${esc(p)}</span><span class="faint">/</span>`).join("")}<b>${esc(parts.at(-1).replace(/\.md$/, ""))}</b></div><span class="grow"></span>${actions}
        <button class="ib" data-act="mode" title="${tab.st.mode === "edit" ? "Reading view" : "Edit"} (⌘E)">${tab.st.mode === "edit" ? ICONS.book : ICONS.edit}</button><button class="ib" data-act="more" title="More">${ICONS.more}</button></div>
        <div class="note-body" style="position:relative"></div>`;
      const body = $(".note-body", tab.el);
      if (tab.st.mode === "edit") {
        body.innerHTML = `<textarea class="editor" spellcheck="false">${esc(data.content)}</textarea>`;
        const ta = $("textarea", body);
        ta.addEventListener("input", () => { dirty = true; data.content = ta.value; clearTimeout(saveT); saveT = setTimeout(() => v.save(), 700); autocomplete(ta, body); });
        ta.addEventListener("keydown", e => acKey(e, ta));
        ta.addEventListener("blur", () => setTimeout(() => $(".ac", body)?.remove(), 150));
        setTimeout(() => ta.focus(), 0);
      } else {
        const [fmo, md] = MD.parseFrontmatter(data.content);
        const props = Object.keys(fmo).length ? `<div class="props">${Object.entries(fmo).filter(([k]) => !["label_source"].includes(k)).map(([k, val]) => `<div class="pk">${esc(k)}</div><div class="pv">${propVal(k, val)}</div>`).join("")}</div>` : "";
        body.innerHTML = `<div class="reading">${props}${MD.render(md, { resolve: n => !!resolveName(n) })}</div>`;
      }
      tab.el.onclick = e => {
        const a = e.target.closest("[data-act]"); if (!a) return;
        const act = a.dataset.act;
        if (act === "mode") v.toggleMode();
        if (act === "wallet") openTab("wallet", { address: fm.address, chain: (fm.chains || [])[0] || "auto" }, { newTab: true });
        if (act === "trace") openTab("trace", { query: fm.address, chain: (fm.chains || [])[0] || "auto", autorun: true }, { newTab: true });
        if (act === "refresh") { toast("Refreshing wallet data…"); api("vault", "save_wallet", { address: fm.address, chain: (fm.chains || [])[0] || "auto" }).then(() => { v.load(); refreshTree(); toast("Note refreshed"); }).catch(er => toast(er.message, true)); }
        if (act === "more") { const r = a.getBoundingClientRect(); showMenu(r.left - 140, r.bottom + 4, [{ label: "Rename…", run: () => renameNote(tab.st.path) }, { label: "Copy path", run: () => copy(tab.st.path) }, { label: "Show in graph", run: () => { const g = openTab("graph"); setTimeout(() => g.focusNode?.(tab.st.path), 700); } }, "-", { label: "Move to trash", danger: true, run: () => deleteNote(tab.st.path) }]); }
      };
    },
    async save() {
      if (!dirty || !data) return; clearTimeout(saveT); dirty = false;
      try { await api("vault", "write", { path: tab.st.path, content: data.content }); tab.status = "Saved"; renderStatus(); setTimeout(() => { tab.status = ""; renderStatus(); }, 1500); refreshTree(); }
      catch (e) { toast(e.message, true); dirty = true; }
    },
    toggleMode() { if (tab.st.mode === "edit") { v.save(); tab.st.mode = "read"; v.load(); } else { tab.st.mode = "edit"; v.render(); } saveTabs(); },
    destroy() { v.save(); },
    hide() { v.save(); },
    right(el) {
      if (!data) { el.innerHTML = loading("…"); return; }
      const item = x => `<div class="ritem" data-open-note="${esc(x.path)}"><div class="rt">${esc(x.label || x.name)}</div>${x.context ? `<div class="rc">${esc(x.context.replace(/\[\[([^\]|]+)\|?([^\]]*)\]\]/g, (_, a, b) => b || a))}</div>` : ""}</div>`;
      const outs = data.outgoing.filter((o, i, a) => a.findIndex(x => x.target === o.target) === i);
      el.innerHTML = `
        <div class="rsec"><h4>Backlinks <span class="cnt">${data.backlinks.length}</span></h4><div class="rlist">${data.backlinks.map(item).join("") || `<div class="r-empty">No notes link here yet.</div>`}</div></div>
        <div class="rsec"><h4>Outgoing links <span class="cnt">${outs.length}</span></h4><div class="rlist">${outs.slice(0, 60).map(o => o.path ? `<div class="ritem" data-open-note="${esc(o.path)}"><div class="rt">${esc(o.alias || o.target)}</div></div>` : `<div class="ritem" onclick="openLink(${esc(JSON.stringify(o.target))})"><div class="rt" style="opacity:.6">${esc(o.alias || o.target)}</div><div class="rc">Not created yet${looksLike(o.target) === "address" ? ": opens as wallet" : ""}</div></div>`).join("") || `<div class="r-empty">None.</div>`}</div></div>
        <div class="rsec"><h4>Unlinked mentions <span class="cnt">${data.mentions.length}</span></h4><div class="rlist">${data.mentions.map(item).join("") || `<div class="r-empty">None.</div>`}</div></div>
        <div class="rsec"><h4>Tags</h4>${data.tags.length ? `<div class="pills">${data.tags.map(t => `<a class="pill t-accent plain tag" data-tag="${esc(t)}" style="cursor:pointer">#${esc(t)}</a>`).join("")}</div>` : `<div class="r-empty">None.</div>`}</div>`;
      $$("a.tag", el).forEach(a => a.onclick = () => { showPane("search"); $("#search-input").value = "#" + a.dataset.tag; runSearch(); });
    },
  };
  bus.on("vault", () => { if (data && tab.id === S.active) renderRight(); });
  return v;
};
function propVal(k, v) {
  if (k === "flags" && Array.isArray(v)) return pills(v);
  if (k === "chains" && Array.isArray(v)) return v.map(c => chainChip(c)).join("");
  if (k === "chain" && S.chainMap[v]) return chainChip(v);
  if (k === "address" || k === "root") return `<span class="addr" data-wallet="${esc(v)}">${esc(v)}</span>`;
  if (Array.isArray(v)) return v.map(x => `<span class="pill plain">${esc(x)}</span>`).join("");
  return esc(String(v));
}
/* wikilink autocomplete */
function caretXY(ta) {
  const div = document.createElement("div"), s = getComputedStyle(ta);
  ["fontFamily", "fontSize", "lineHeight", "paddingTop", "paddingLeft", "paddingRight", "letterSpacing", "tabSize", "width", "boxSizing", "whiteSpace", "wordWrap"].forEach(p => div.style[p] = s[p]);
  div.style.position = "absolute"; div.style.visibility = "hidden"; div.style.whiteSpace = "pre-wrap"; div.style.wordWrap = "break-word";
  div.textContent = ta.value.slice(0, ta.selectionStart); const sp = document.createElement("span"); sp.textContent = "​"; div.appendChild(sp);
  document.body.appendChild(div); const x = sp.offsetLeft, y = sp.offsetTop; div.remove();
  return [x - ta.scrollLeft, y - ta.scrollTop + parseFloat(s.lineHeight)];
}
function autocomplete(ta, host) {
  const before = ta.value.slice(0, ta.selectionStart); const m = before.match(/\[\[([^\]\n|]*)$/);
  $(".ac", host)?.remove(); if (!m) return;
  const q = m[1]; const items = S.tree.files.map(f => ({ f, s: Math.max(fuzzy(q, f.name), fuzzy(q, f.label || "")) })).filter(x => x.s > 0).sort((a, b) => b.s - a.s).slice(0, 10);
  if (!items.length) return;
  const [x, y] = caretXY(ta); const ac = document.createElement("div"); ac.className = "ac";
  ac.innerHTML = items.map((it, i) => `<div class="${i ? "" : "on"}" data-name="${esc(it.f.name)}" data-label="${esc(it.f.type === "address" ? it.f.label || "" : "")}">${esc(it.f.type === "address" && it.f.label ? it.f.label : it.f.name)}<small>${esc(it.f.path.split("/").slice(0, -1).join("/"))}</small></div>`).join("");
  ac.style.left = Math.min(x, host.clientWidth - 280) + "px"; ac.style.top = y + 4 + "px"; host.appendChild(ac);
  ac.onmousedown = e => { e.preventDefault(); const d = e.target.closest("[data-name]"); if (d) acPick(ta, d); };
}
function acKey(e, ta) {
  const ac = $(".ac", ta.parentElement); if (!ac) return;
  const opts = $$("div", ac); let i = opts.findIndex(o => o.classList.contains("on"));
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); opts[i]?.classList.remove("on"); i = (i + (e.key === "ArrowDown" ? 1 : -1) + opts.length) % opts.length; opts[i].classList.add("on"); }
  else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); acPick(ta, opts[i]); }
  else if (e.key === "Escape") ac.remove();
}
function acPick(ta, d) {
  const before = ta.value.slice(0, ta.selectionStart), after = ta.value.slice(ta.selectionStart);
  const start = before.lastIndexOf("[["); const ins = `[[${d.dataset.name}${d.dataset.label ? "|" + d.dataset.label : ""}]]`;
  const rest = after.startsWith("]]") ? after.slice(2) : after;
  ta.value = before.slice(0, start) + ins + rest; const pos = start + ins.length; ta.setSelectionRange(pos, pos);
  ta.dispatchEvent(new Event("input")); $(".ac", ta.parentElement)?.remove();
}

/* ---------- vault graph */
VIEWS.graph = tab => {
  let g = null, data = null, sel = null;
  const opt = Object.assign({ orphans: true, unresolved: true, filter: "", charge: 260, link: 80 }, store.get("graphopt", {}));
  const v = {
    icon: "graph",
    mount() {
      setTitle(tab, "Graph view");
      tab.el.innerHTML = `<div class="graph-wrap"><div class="g-hint">Drag to pan · scroll to zoom · click a node for details · double-click to open</div>
        <div class="g-panel"><input class="inp" id="g-filter" placeholder="Filter nodes…" value="${esc(opt.filter)}">
        <details open><summary>Filters</summary><div>
          <label class="chk"><input type="checkbox" id="g-orph" ${opt.orphans ? "checked" : ""}> Orphans</label>
          <label class="chk"><input type="checkbox" id="g-unres" ${opt.unresolved ? "checked" : ""}> Unresolved links</label></div></details>
        <details><summary>Forces</summary><div>
          <div class="range"><span class="muted" style="width:70px">Repel</span><input type="range" id="g-charge" min="60" max="900" value="${opt.charge}"></div>
          <div class="range"><span class="muted" style="width:70px">Link length</span><input type="range" id="g-link" min="30" max="220" value="${opt.link}"></div></div></details>
        <button class="btn sm" id="g-fit">${ICONS.fit} Fit to screen</button></div>
        <div class="legend">${Object.entries({ address: "Wallet", case: "Case", binary: "Binary", tx: "Transaction", report: "Report", note: "Note" }).map(([k, l]) => `<span><i style="background:${TYPE_COLOR[k]}"></i>${l}</span>`).join("")}<span><i style="background:transparent;border:2px solid var(--danger)"></i>Mixer / scam</span></div></div>`;
      g = new ForceGraph($(".graph-wrap", tab.el), {
        charge: opt.charge, linkDistance: opt.link,
        nodeRadius: n => n.type === "unresolved" ? 2.6 : 3.5 + Math.sqrt(n.deg || 0) * 1.7,
        nodeColor: n => cssVar(TYPE_COLOR[n.type] || "var(--fg-2)"),
        nodeRing: n => (n.flags || []).some(f => ["mixer", "scam", "mixer_exposure"].includes(f)) ? cssVar("var(--danger)") : null,
        nodeLabel: n => n.label, important: n => n.type === "case" || (n.deg || 0) >= 6,
        onSelect: n => { sel = n; renderRight(); }, onOpen: n => { if (n.type === "unresolved") openLink(n.name, true); else openNote(n.id, true); },
        onHover: (n, e) => showTip(n ? `<b>${esc(n.label)}</b><br><span class="muted">${esc(n.type)} · ${n.deg || 0} links</span>${(n.flags || []).length ? "<br>" + n.flags.map(f => esc(S.flagInfo[f]?.label || f)).join(", ") : ""}` : null, e),
      });
      const save = () => store.set("graphopt", opt);
      $("#g-filter", tab.el).oninput = e => { opt.filter = e.target.value; v.applyFilter(); save(); };
      $("#g-orph", tab.el).onchange = e => { opt.orphans = e.target.checked; v.load(); save(); };
      $("#g-unres", tab.el).onchange = e => { opt.unresolved = e.target.checked; v.load(); save(); };
      $("#g-charge", tab.el).oninput = e => { opt.charge = +e.target.value; g.setOptions({ charge: opt.charge }); save(); };
      $("#g-link", tab.el).oninput = e => { opt.link = +e.target.value; g.setOptions({ linkDistance: opt.link }); save(); };
      $("#g-fit", tab.el).onclick = () => g.fit();
      v.load();
    },
    async load() {
      try { data = await api("vault", "graph", { include_orphans: opt.orphans, include_unresolved: opt.unresolved }); g.setData(data); v.applyFilter(); if (tab.id === S.active) renderRight(); }
      catch (e) { toast(e.message, true); }
    },
    applyFilter() { const q = opt.filter.trim().toLowerCase(); g.setDim(q ? n => !(n.label || "").toLowerCase().includes(q) && !(n.name || "").toLowerCase().includes(q) && !(n.tags || []).some(t => t.toLowerCase().includes(q)) : null); },
    focusNode(id) { g?.focus(id); sel = g?.byId.get(id); renderRight(); },
    destroy() { g?.destroy(); tip.hidden = true; },
    hide() { tip.hidden = true; },
    right(el) {
      if (!sel) { const types = {}; (data?.nodes || []).forEach(n => types[n.type] = (types[n.type] || 0) + 1); el.innerHTML = `<div class="rsec"><h4>Vault graph</h4><div class="kv">${Object.entries(types).map(([k, n]) => `<dt>${esc(k)}</dt><dd class="num">${n}</dd>`).join("")}<dt>links</dt><dd class="num">${data?.edges.length || 0}</dd></div></div><div class="r-empty">Click a node to see its details.</div>`; return; }
      const nb = [...(g.adj.get(sel.id) || [])].map(id => g.byId.get(id)).filter(Boolean);
      el.innerHTML = `<div class="rsec"><div class="insp-title">${esc(sel.label)}</div><div class="muted" style="font-size:12px">${esc(sel.type)}${sel.chain ? " · " + esc(S.chainMap[sel.chain]?.name || sel.chain) : ""}</div>${(sel.flags || []).length ? `<div style="margin-top:8px">${pills(sel.flags)}</div>` : ""}
        <div class="r-acts" style="margin-top:10px">${sel.type === "unresolved" ? `<button class="btn sm" onclick="openLink(${esc(JSON.stringify(sel.name))}, true)">Create / open</button>` : `<button class="btn sm primary" data-open-note="${esc(sel.id)}">Open note</button>`}</div></div>
        <div class="rsec"><h4>Connected <span class="cnt">${nb.length}</span></h4><div class="rlist">${nb.map(n => `<div class="ritem" onclick="cur().focusNode(${esc(JSON.stringify(n.id))})"><div class="rt">${esc(n.label)}</div><div class="rc">${esc(n.type)}</div></div>`).join("")}</div></div>`;
    },
  };
  bus.on("vault", () => { if (g) v.load(); });
  bus.on("theme", () => { g?._readColors(); g?.draw(); });
  return v;
};

/* ---------- trace */
const KIND_COLOR = { wallet: "var(--fg-2)", service: "var(--info)", contract: "var(--faint)", change: "var(--muted)" };
function nodeTone(n) {
  const f = n.flags || [];
  if (f.some(x => ["mixer", "scam", "mixer_exposure"].includes(x))) return "var(--danger)";
  if (f.includes("exchange")) return "var(--info)";
  if (f.some(x => ["whale", "large"].includes(x))) return "var(--accent-2)";
  if (f.some(x => ["fresh", "coinjoin"].includes(x))) return "var(--warn)";
  if (f.includes("vault")) return "var(--good)";
  return null;
}
VIEWS.trace = tab => {
  let g = null, data = null, sel = null, bottom = "endpoints", running = false;
  const st = tab.st;
  Object.assign(st, Object.assign({ query: "", chain: "auto", direction: "out", hops: 2, per_hop: 5, min_usd: 0 }, st));
  const v = {
    icon: "trace",
    persist: () => ({ query: st.query, chain: st.chain, direction: st.direction, hops: st.hops, per_hop: st.per_hop, min_usd: st.min_usd }),
    mount() {
      setTitle(tab, st.query ? "Trace " + short(st.query) : "Trace");
      tab.el.innerHTML = `<div class="toolbar">
          <div class="field q"><label for="tq-${tab.id}">Address or ENS</label><input class="inp mono" id="tq-${tab.id}" value="${esc(st.query)}" placeholder="bc1q…, 0x…, name.eth, T…, r…, So1…" spellcheck="false" autocomplete="off"></div>
          <div class="field"><label>Chain</label>${chainSelect("tc-" + tab.id, st.chain)}</div>
          <div class="field"><label>Follow</label><div class="seg" id="td-${tab.id}">${["out", "in", "both"].map(d => `<button data-d="${d}" class="${st.direction === d ? "on" : ""}">${d === "out" ? "Where it went" : d === "in" ? "Where it came from" : "Both"}</button>`).join("")}</div></div>
          <div class="field"><label>Hops</label><div class="range"><input type="range" min="1" max="6" value="${st.hops}" id="th-${tab.id}"><output>${st.hops}</output></div></div>
          <div class="field"><label>Per hop</label><div class="range"><input type="range" min="1" max="12" value="${st.per_hop}" id="tp-${tab.id}"><output>${st.per_hop}</output></div></div>
          <div class="field"><label>Min $</label><input class="inp" style="width:84px" type="number" min="0" step="10" value="${st.min_usd}" id="tm-${tab.id}"></div>
          <button class="btn primary" id="tr-${tab.id}">${ICONS.play} Trace</button>
        </div>
        <div class="graph-wrap" id="tg-${tab.id}">
          <div class="empty" style="position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center" id="te-${tab.id}"><h2>Follow the money</h2>
          <p>Paste a wallet and choose a direction. Each hop keeps the biggest counterparties; exchanges, contracts and mixers are shown but not followed.</p>
          <div class="examples" style="justify-content:center;margin-top:8px">Examples:
            <button data-ex="vitalik.eth">vitalik.eth</button><button data-ex="bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh" data-dir="in">BTC donations (in)</button>
            <button data-ex="TNUC9Qb1rRpS5CbWLmNMxXBjyFoydXjWFR">Tron wallet</button><button data-ex="rEb8TK3gBgk5auZkwc6sHnwrGVJH8DuaLh" data-dir="in">XRP wallet (in)</button></div></div>
          <div class="zoom-ctl" hidden><button class="ib" data-z="in">${ICONS.plus}</button><button class="ib" data-z="out">${ICONS.minus}</button><button class="ib" data-z="fit">${ICONS.fit}</button></div>
        </div>
        <div class="trace-bottom" hidden><div class="subtabs" id="tb-${tab.id}"></div><div class="body"></div></div>`;
      const q = $(`#tq-${tab.id}`), run = () => v.run();
      q.onkeydown = e => { if (e.key === "Enter") run(); };
      q.oninput = () => st.query = q.value.trim();
      $(`#tc-${tab.id}`).onchange = e => st.chain = e.target.value;
      $(`#td-${tab.id}`).onclick = e => { const b = e.target.closest("[data-d]"); if (!b) return; st.direction = b.dataset.d; $$("button", e.currentTarget).forEach(x => x.classList.toggle("on", x === b)); };
      [["th", "hops"], ["tp", "per_hop"]].forEach(([p, k]) => { const r = $(`#${p}-${tab.id}`); r.oninput = () => { st[k] = +r.value; r.nextElementSibling.value = r.value; }; });
      $(`#tm-${tab.id}`).oninput = e => st.min_usd = +e.target.value || 0;
      $(`#tr-${tab.id}`).onclick = run;
      tab.el.addEventListener("click", e => {
        const ex = e.target.closest("[data-ex]"); if (ex) { st.query = ex.dataset.ex; q.value = st.query; if (ex.dataset.dir) { st.direction = ex.dataset.dir; $$(`#td-${tab.id} button`).forEach(x => x.classList.toggle("on", x.dataset.d === st.direction)); } run(); }
        const z = e.target.closest("[data-z]"); if (z && g) { z.dataset.z === "fit" ? g.fit() : g.zoomBy(z.dataset.z === "in" ? 1.3 : 1 / 1.3); }
        const bt = e.target.closest("[data-bt]"); if (bt) { bottom = bt.dataset.bt; v.renderBottom(); }
        const fn = e.target.closest("[data-focus]"); if (fn && g) { g.focus(fn.dataset.focus); sel = g.byId.get(fn.dataset.focus); renderRight(); }
      });
      if (st.autorun && st.query) { st.autorun = false; setTimeout(run, 50); }
      else setTimeout(() => q.focus(), 30);
    },
    update(nst) { Object.assign(st, nst); $(`#tq-${tab.id}`).value = st.query; if (nst.autorun) v.run(); },
    async run() {
      if (running) return; if (!st.query) { toast("Enter an address or ENS name first", true); return; }
      running = true; setTitle(tab, "Trace " + short(st.query), true);
      const wrap = $(`#tg-${tab.id}`); $(`#te-${tab.id}`)?.remove();
      wrap.querySelector(".progress")?.remove();
      const prog = document.createElement("div"); prog.className = "progress";
      const msgs = ["Finding the chain…", "Loading transfers…", "Ranking counterparties…", "Following the next hop…", "Checking labels and balances…", "Flagging exchanges and mixers…"];
      let mi = 0; prog.innerHTML = `<div class="bar"><i></i></div><div>${msgs[0]}</div><div class="faint" style="font-size:12px">Public explorers are rate-limited: deep traces take 20–60 s.</div>`;
      wrap.appendChild(prog); const mt = setInterval(() => { mi = Math.min(mi + 1, msgs.length - 1); prog.children[1].textContent = msgs[mi]; }, 3500);
      try {
        data = await api("chain", "trace", { address: st.query, chain: st.chain, hops: st.hops, direction: st.direction, per_hop: st.per_hop, min_usd: st.min_usd });
        v.draw();
      } catch (e) { toast(e.message, true); if (!data) wrap.insertAdjacentHTML("beforeend", `<div class="empty" style="position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center"><h2>Trace failed</h2><p>${esc(e.message)}</p></div>`); }
      finally { clearInterval(mt); prog.remove(); running = false; setTitle(tab, "Trace " + (data ? (data.nodes.find(n => n.root)?.label || short(data.root)) : short(st.query))); saveTabs(); }
    },
    draw(keep) {
      const wrap = $(`#tg-${tab.id}`); $$(".empty", wrap).forEach(x => x.remove());
      data.hidden ||= [];
      $(".zoom-ctl", wrap).hidden = false; $(".trace-bottom", tab.el).hidden = false;
      const sign = {};
      if (data.direction === "both") {
        const root = data.nodes.find(n => n.root).id; sign[root] = 0;
        for (let h = 1; h <= data.hops; h++) data.edges.filter(e => e.hop === h).forEach(e => {
          if (sign[e.source] !== undefined && sign[e.target] === undefined) sign[e.target] = sign[e.source] >= 0 ? 1 : -1;
          if (sign[e.target] !== undefined && sign[e.source] === undefined) sign[e.source] = sign[e.target] <= 0 ? -1 : 1;
        });
      }
      const nodes = data.nodes.filter(n => !data.hidden.includes(n.id)).map(n => Object.assign({}, n, { layer: data.direction === "in" ? -n.hop : data.direction === "out" ? n.hop : (sign[n.id] || 1) * n.hop, label: n.label || short(n.address) }));
      const maxUsd = Math.max(1, ...data.edges.map(e => e.usd || 0));
      if (!g) g = new ForceGraph(wrap, {
        directed: true, layered: true, particles: true, layerGap: 230, linkDistance: 110, charge: 420,
        nodeRadius: n => n.root ? 10 : 4.5 + Math.min(8, Math.log10(1 + (n.in_usd || 0) + (n.out_usd || 0)) * 1.25),
        nodeColor: n => n.root ? cssVar("var(--accent)") : cssVar(KIND_COLOR[n.kind] || "var(--fg-2)"),
        nodeRing: n => { const t = nodeTone(n); return t ? cssVar(t) : null; },
        nodeLabel: n => n.label, important: n => n.root || (n.flags || []).some(f => ["exchange", "mixer", "whale", "known"].includes(f)) || n.kind === "service",
        edgeWidth: e => e.change ? 1 : 0.8 + Math.log10(1 + (e.usd || 0)) / Math.log10(1 + maxUsd) * 4.5,
        edgeColor: e => e.change ? cssVar("var(--faint)") : cssVar(e.source === data.nodes.find(n => n.root).id ? "var(--out)" : e.target === data.nodes.find(n => n.root).id ? "var(--in)" : "var(--accent)"),
        edgeDash: e => e.change ? [4, 4] : null,
        onSelect: n => { sel = n; renderRight(); $$(".tbl tr.sel", tab.el).forEach(r => r.classList.remove("sel")); },
        onOpen: n => n.address !== "coinbase" && openTab("wallet", { address: n.address, chain: data.chain }, { newTab: true }),
        onHover: (n, e) => showTip(n ? `<b>${esc(n.label || short(n.address))}</b><br><span class="muted">${esc(n.kind)} · hop ${n.hop}</span><br>in ${fmtUsd(n.in_usd)} · out ${fmtUsd(n.out_usd)}${n.balance != null ? `<br>balance ${fmtAmt(n.balance, data.symbol)} ${n.balance_usd != null ? "(" + fmtUsd(n.balance_usd) + ")" : ""}` : ""}${(n.flags || []).length ? "<br>" + n.flags.map(f => esc(S.flagInfo[f]?.label || f)).join(" · ") : ""}` : null, e),
      });
      g.setData({ nodes, edges: data.edges.filter(e => !data.hidden.includes(e.source) && !data.hidden.includes(e.target)) }, !!keep);
      tab.g = g;
      if (!keep) sel = null;
      renderRight(); v.renderBottom();
      if (!$(".legend", wrap)) wrap.insertAdjacentHTML("beforeend", `<div class="legend"><span><i style="background:var(--accent)"></i>Start</span><span><i style="background:var(--fg-2)"></i>Wallet</span><span><i style="background:var(--info)"></i>Service / exchange</span><span><i style="background:var(--faint)"></i>Contract</span><span><i style="border:2px solid var(--danger)"></i>Mixer / scam</span><span><i style="border:2px solid var(--accent-2)"></i>Whale</span><span><i style="border:2px dashed var(--faint);background:transparent"></i>Change (same owner)</span></div>`);
    },
    renderBottom() {
      const tb = $(`#tb-${tab.id}`), body = $(".trace-bottom .body", tab.el); if (!data) return;
      const cnt = { endpoints: data.endpoints.length, wallets: data.nodes.length, flows: data.edges.length, log: data.log.length };
      tb.innerHTML = Object.entries({ endpoints: "Where it ends up", wallets: "Wallets", flows: "Flows", log: "Log" }).map(([k, l]) => `<button data-bt="${k}" class="${bottom === k ? "on" : ""}">${l}<span class="cnt">${cnt[k]}</span></button>`).join("");
      const byId = Object.fromEntries(data.nodes.map(n => [n.id, n]));
      const nm = n => n ? esc(n.label || short(n.address)) : "?";
      if (bottom === "endpoints") body.innerHTML = data.endpoints.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Wallet</th><th>Kind</th><th class="r">Hop</th><th class="r">Flow</th><th>Flags</th></tr></thead><tbody>${data.endpoints.map(e => `<tr class="click" data-focus="${esc(data.chain === "bitcoin" || data.family === "solana" ? e.address : e.address.toLowerCase())}"><td>${esc(e.label || short(e.address))}</td><td>${esc(e.kind)}</td><td class="r">${e.hop}</td><td class="r">${fmtUsd(e.usd)}</td><td>${pills(e.flags)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="r-empty" style="padding:14px">No endpoints.</div>`;
      if (bottom === "wallets" && (data.hidden || []).length) setTimeout(() => { const b = $(".trace-bottom .body", tab.el); b.insertAdjacentHTML("afterbegin", `<div style="padding:8px 12px" class="muted">${data.hidden.length} hidden · <button class="btn sm ghost" id="unhide-${tab.id}">Show all</button></div>`); $(`#unhide-${tab.id}`).onclick = () => { data.hidden = []; v.draw(true); }; });
      if (bottom === "wallets") body.innerHTML = `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Wallet</th><th class="r">Hop</th><th>Kind</th><th class="r">In</th><th class="r">Out</th><th class="r">Balance</th><th>Flags</th></tr></thead><tbody>${[...data.nodes].sort((a, b) => a.hop - b.hop || (b.in_usd + b.out_usd) - (a.in_usd + a.out_usd)).map(n => `<tr class="click" data-focus="${esc(n.id)}"><td>${nm(n)}</td><td class="r">${n.hop}</td><td>${esc(n.kind)}</td><td class="r">${fmtUsd(n.in_usd)}</td><td class="r">${fmtUsd(n.out_usd)}</td><td class="r">${n.balance != null ? fmtAmt(n.balance, data.symbol) : "—"}</td><td>${pills(n.flags)}</td></tr>`).join("")}</tbody></table></div>`;
      if (bottom === "flows") body.innerHTML = `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>From</th><th>To</th><th>Assets</th><th class="r">USD</th><th class="r">Transfers</th><th>Last</th><th>Tx</th></tr></thead><tbody>${[...data.edges].sort((a, b) => b.usd - a.usd).map(e => `<tr class="click" data-focus="${esc(e.target)}"><td>${nm(byId[e.source])}</td><td>${nm(byId[e.target])}${e.change ? ` <span class="pill t-muted">change</span>` : ""}</td><td class="nw">${Object.entries(e.assets).slice(0, 2).map(([k, a]) => esc(fmtAmt(a, k))).join(", ")}</td><td class="r">${fmtUsd(e.usd)}</td><td class="r">${e.count}</td><td class="nw">${esc(ago(e.last))}</td><td>${txLink(e.txs[0], data.chain)}</td></tr>`).join("")}</tbody></table></div>`;
      if (bottom === "log") body.innerHTML = `<div style="padding:10px 14px" class="mono muted">${data.log.map(esc).join("<br>")}</div>`;
    },
    async expand(n, dir) {
      toast(`Expanding ${n.label || short(n.address)} ${dir === "out" ? "→" : "←"}…`);
      setTitle(tab, tab.title, true);
      try {
        const r = await api("chain", "trace", { address: n.address, chain: data.chain, hops: 1, direction: dir, per_hop: Math.max(4, st.per_hop), min_usd: st.min_usd });
        const have = new Set(data.nodes.map(x => x.id)); let added = 0;
        const hop = dir === "out" ? n.hop + 1 : (data.direction === "in" ? n.hop + 1 : n.hop - 1);
        for (const x of r.nodes) {
          if (x.root || have.has(x.id)) continue;
          data.nodes.push(Object.assign({}, x, { hop, root: false }));
          have.add(x.id); added++;
        }
        const ek = new Set(data.edges.map(e => e.id));
        for (const e of r.edges) if (!ek.has(e.id)) data.edges.push(Object.assign({}, e, { hop: Math.abs(hop) }));
        data.hidden = (data.hidden || []).filter(h => !r.nodes.some(x => x.id === h));
        data.log.push(`expanded ${short(n.address)} ${dir}: +${added} wallets`);
        v.draw(true); toast(added ? `Added ${added} wallets` : "No new wallets in that direction");
      } catch (e) { toast(e.message, true); }
      setTitle(tab, tab.title, false);
    },
    async saveCase() {
      if (!data) return;
      try { const r = await api("vault", "save_trace", { trace: data }); await refreshTree(); toast(`Saved case and ${r.wallet_notes} wallet notes`); openNote(r.path, true); }
      catch (e) { toast(e.message, true); }
    },
    destroy() { g?.destroy(); tip.hidden = true; }, hide() { tip.hidden = true; },
    right(el) {
      if (!data) { el.innerHTML = `<div class="rsec"><h4>How tracing works</h4><div class="muted" style="font-size:12.5px">Each hop loads recent transfers of every wallet on the frontier and keeps the largest counterparties (by USD, then by count). Exchanges, contracts and mixers end a path. On Bitcoin and Litecoin, change outputs are detected and followed as the same owner, so peel chains appear as dashed runs.</div></div>`; return; }
      const root = data.nodes.find(n => n.root);
      if (!sel) {
        el.innerHTML = `<div class="rsec"><div class="insp-title">${esc(root.label || short(root.address))}</div><div style="margin:6px 0">${chainChip(data.chain)}</div>${pills(root.flags)}</div>
          ${root.flags?.includes("mixer_exposure") ? `<div class="callout danger">A mixer appears ${root.mixer_hops} hop(s) away.</div>` : ""}
          ${data.peel_hint ? `<div class="callout warn">${data.change_edges} change hops followed. This may be a peel chain: check it in the lab.</div>` : ""}
          <div class="rsec"><h4>Summary</h4><dl class="kv"><dt>Direction</dt><dd>${esc(data.direction)}</dd><dt>Hops</dt><dd>${data.hops}</dd><dt>Wallets</dt><dd>${data.nodes.length}</dd><dt>Flows</dt><dd>${data.edges.length}</dd><dt>Price</dt><dd>${data.price_usd ? fmtUsd(data.price_usd) + " / " + esc(data.symbol) : "—"}</dd></dl></div>
          ${data.active_chains?.length > 1 ? `<div class="rsec"><h4>Also active on</h4><div class="pills">${data.active_chains.map(c => chainChip(c.chain)).join("")}</div></div>` : ""}
          <div class="r-acts"><button class="btn primary" id="tsave">${ICONS.save} Save case to vault</button><button class="btn" data-wallet="${esc(root.address)}" data-chain="${esc(data.chain)}">${ICONS.wallet} Wallet</button></div>
          <div class="r-empty">Click a wallet in the graph to inspect it.</div>`;
        $("#tsave", el).onclick = () => v.saveCase(); return;
      }
      const n = sel;
      const fl = (n.flags || []).map(f => `<div class="flag-row">${pill(f)}<span class="h">${esc(S.flagInfo[f]?.hint || "")}</span></div>`).join("");
      el.innerHTML = `<div class="rsec"><div class="insp-title">${esc(n.label || short(n.address))}</div>
          <div class="mono muted" style="font-size:11.5px;overflow-wrap:anywhere;margin-top:4px">${esc(n.address)} <button class="ib" data-copy="${esc(n.address)}" title="Copy">${ICONS.copy}</button></div>
          <div class="muted" style="font-size:12px">${esc(n.kind)} · hop ${n.hop}${n.change_of ? " · change of previous wallet" : ""}</div></div>
        ${fl ? `<div class="rsec"><h4>Flags</h4><div class="flag-list">${fl}</div></div>` : ""}
        <div class="rsec"><h4>Numbers</h4><dl class="kv"><dt>Received here</dt><dd class="num">${fmtUsd(n.in_usd)}</dd><dt>Sent on</dt><dd class="num">${fmtUsd(n.out_usd)}</dd>
          <dt>Balance</dt><dd class="num">${n.balance != null ? esc(fmtAmt(n.balance, data.symbol)) + " " + (n.balance_usd != null ? fmtUsd(n.balance_usd) : "") : "—"}</dd>${n.tx_count != null ? `<dt>Transactions</dt><dd class="num">${n.tx_count.toLocaleString()}</dd>` : ""}</dl></div>
        <div class="r-acts">${n.address !== "coinbase" ? `<button class="btn sm primary" data-wallet="${esc(n.address)}" data-chain="${esc(data.chain)}">${ICONS.wallet} Open wallet</button>
          <button class="btn sm" id="tx-out" title="Add this wallet's biggest recipients to the graph">Expand →</button>
          <button class="btn sm" id="tx-in" title="Add this wallet's biggest senders to the graph">← Expand</button>
          <button class="btn sm ghost" id="tlabel" title="Name this wallet (saved to your vault, shown everywhere)">Label</button>
          ${n.root ? "" : `<button class="btn sm ghost" id="thide" title="Remove this wallet from the graph">Hide</button>`}
          <button class="btn sm ghost" id="tfrom">${ICONS.trace} New trace from here</button>
          <a class="btn sm ghost" href="${esc(data.addr_url.replace("{a}", n.address))}" target="_blank" rel="noopener noreferrer">${ICONS.ext} Explorer</a>` : ""}</div>`;
      $("#tx-out", el)?.addEventListener("click", () => v.expand(n, "out"));
      $("#tx-in", el)?.addEventListener("click", () => v.expand(n, "in"));
      $("#thide", el)?.addEventListener("click", () => { data.hidden.push(n.id); sel = null; v.draw(true); toast("Hidden. Restore it from the Wallets tab below."); });
      $("#tlabel", el)?.addEventListener("click", async () => {
        const name = await promptInline("Name for this wallet (blank removes your label)", n.label || "");
        if (name === null) return;
        try {
          await api("vault", "set_label", { address: n.address, label: name, chain: data.chain });
          const dn = data.nodes.find(x => x.id === n.id);
          if (dn) { dn.label = name || null; if (!dn.flags.includes("vault")) dn.flags.push("vault"); }
          n.label = name || null; v.draw(true); refreshTree(); toast(name ? "Labelled" : "Label removed");
        } catch (e) { toast(e.message, true); }
      });
      $("#tfrom", el)?.addEventListener("click", () => openTab("trace", { query: n.address, chain: data.chain, direction: data.direction, hops: data.hops, per_hop: data.per_hop, autorun: true }, { newTab: true }));
    },
  };
  bus.on("theme", () => { g?._readColors(); g?.draw(); });
  return v;
};

/* ---------- wallet */
VIEWS.wallet = tab => {
  let w = null, sub = "history", cache = {};
  const st = tab.st;
  const v = {
    icon: "wallet",
    async mount() {
      setTitle(tab, short(st.address), true);
      tab.el.innerHTML = `<div class="view-scroll"><div class="page">${loading("Looking up " + short(st.address, 10) + "…")}</div></div>`;
      try { w = await api("chain", "wallet", { address: st.address, chain: st.chain }); }
      catch (e) { setTitle(tab, short(st.address)); $(".page", tab.el).innerHTML = errBox(e) + (/Monero/.test(e.message) ? `<p class="muted">Tip: paste a Monero <b>transaction</b> hash in the command palette (⌘K) to inspect its fingerprints, or use <b>Amount matching</b> in the lab on the Bitcoin/Ethereum side of a swap.</p>` : ""); return; }
      st.chain = w.chain; tab.key = tabKey("wallet", st);
      setTitle(tab, w.label || short(w.address)); v.render(); renderRight(); saveTabs();
    },
    render() {
      const utxo = S.chainMap[w.chain]?.kind === "utxo";
      const subs = { history: "History", activity: "Transfers", tokens: `Tokens<span class="cnt">${(w.tokens || []).length}</span>`, ...(utxo ? { coins: "Coins" } : {}), exposure: "Mixer exposure", links: "Same owner", pass: "Pass-through" };
      $(".page", tab.el).innerHTML = `
        <div class="hd"><div style="min-width:0"><h1>${esc(w.label || short(w.address, 10))}</h1>
          <div class="sub">${chainChip(w.chain)}<span class="mono" style="overflow-wrap:anywhere">${esc(w.address)}</span><button class="ib" data-copy="${esc(w.address)}" title="Copy address">${ICONS.copy}</button>${w.address_type ? `<span>${esc(w.address_type)}</span>` : ""}</div>
          <div style="margin-top:8px">${pills(w.flags)}</div></div>
          <div class="acts"><button class="btn primary" data-act="trace">${ICONS.trace} Trace</button><button class="btn" data-act="save">${ICONS.save} ${w.vault_path ? "Refresh note" : "Save to vault"}</button>${w.vault_path ? `<button class="btn ghost" data-open-note="${esc(w.vault_path)}">Open note</button>` : ""}<a class="btn ghost" href="${esc(w.explorer_url)}" target="_blank" rel="noopener noreferrer">${ICONS.ext} Explorer</a></div></div>
        ${w.active_chains?.length > 1 ? `<div class="pills" style="align-items:center"><span class="muted" style="font-size:12px;margin-right:4px">Same address active on</span>${w.active_chains.map(c => chainChip(c.chain, true, c.chain === w.chain)).join("")}</div>` : ""}
        ${w.note ? `<div class="callout warn">${esc(w.note)}</div>` : ""}
        <div class="stats">
          <div class="stat"><div class="k">Balance</div><div class="v">${esc(fmtAmt(w.balance, w.symbol))}</div><div class="s">${fmtUsd(w.balance_usd)}</div></div>
          <div class="stat"><div class="k">Portfolio</div><div class="v">${fmtUsd(w.portfolio_usd)}</div><div class="s">${w.tokens_usd ? fmtUsd(w.tokens_usd) + " in tokens" : "native only"}</div></div>
          <div class="stat"><div class="k">Transactions</div><div class="v">${w.tx_count != null ? w.tx_count.toLocaleString() : w.tx_count_note || "—"}</div><div class="s">${w.token_transfer_count ? w.token_transfer_count.toLocaleString() + " token transfers" : "&nbsp;"}</div></div>
          ${w.total_received != null ? `<div class="stat"><div class="k">Received / sent</div><div class="v">${esc(fmtAmt(w.total_received))}</div><div class="s">${esc(fmtAmt(w.total_sent, w.symbol))} sent</div></div>` : `<div class="stat"><div class="k">${esc(w.symbol)} price</div><div class="v">${fmtUsd(w.price_usd)}</div><div class="s">${esc(w.chain_name)}</div></div>`}
        </div>
        <div class="subtabs" id="ws-${tab.id}">${Object.entries(subs).map(([k, l]) => `<button data-sub="${k}" class="${sub === k ? "on" : ""}">${l}</button>`).join("")}</div>
        <div id="wb-${tab.id}"></div>`;
      tab.el.onclick = e => {
        const s = e.target.closest("[data-sub]"); if (s) { sub = s.dataset.sub; $$(`#ws-${tab.id} button`).forEach(b => b.classList.toggle("on", b === s)); v.renderSub(); return; }
        const c = e.target.closest("button.chain-chip[data-chain]"); if (c) { openTab("wallet", { address: w.address, chain: c.dataset.chain }); return; }
        const a = e.target.closest("[data-act]"); if (!a) return;
        if (a.dataset.act === "trace") openTab("trace", { query: w.address, chain: w.chain, autorun: true }, { newTab: true });
        if (a.dataset.act === "save") v.save(a);
        if (a.dataset.act === "more") v.renderSub(true);
      };
      v.renderSub();
    },
    async save(btn) {
      btn.disabled = true; btn.innerHTML = `<span class="spin"></span> Saving…`;
      try { const r = await api("vault", "save_wallet", { address: w.address, chain: w.chain }); await refreshTree(); w.vault_path = r.path; if (!w.flags.includes("vault")) w.flags.push("vault"); toast("Saved to " + r.path); v.render(); }
      catch (e) { toast(e.message, true); btn.disabled = false; }
    },
    async renderSub(more) {
      const box = $(`#wb-${tab.id}`); const key = sub;
      const loaders = {
        activity: () => api("chain", "activity", { address: w.address, chain: w.chain, limit: more ? 150 : 60 }),
        exposure: () => api("forensics", "exposure", { address: w.address, chain: w.chain }),
        links: () => api("corr", "links", { address: w.address, chain: w.chain, include_cluster: S.chainMap[w.chain]?.kind === "utxo" }),
        pass: () => api("corr", "pass_through", { address: w.address, chain: w.chain }),
        coins: () => api("forensics", "coins", { address: w.address, chain: w.chain }),
      };
      if (key === "history") { renderHistory(box, w, tab); return; }
      if (key === "tokens") { box.innerHTML = (w.tokens || []).length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Token</th><th class="r">Amount</th><th class="r">USD</th><th>Contract</th></tr></thead><tbody>${w.tokens.map(t => `<tr><td>${esc(t.symbol || "?")}${t.name ? ` <span class="muted">${esc(t.name)}</span>` : ""}</td><td class="r">${esc(fmtAmt(t.amount))}</td><td class="r">${fmtUsd(t.usd)}${t.approx ? " ≈" : ""}</td><td class="mono muted">${esc(short(t.contract || ""))}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">No tokens found.</div>`; return; }
      if (!cache[key] || more) { box.innerHTML = loading("Loading…"); try { cache[key] = await loaders[key](); } catch (e) { box.innerHTML = errBox(e); return; } }
      if (sub !== key) return;
      const d = cache[key];
      if (key === "activity") {
        box.innerHTML = d.items.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>When</th><th></th><th class="r">Amount</th><th class="r">USD</th><th>Counterparty</th><th>Tx</th></tr></thead><tbody>${d.items.map(x => `<tr><td class="nw" title="${esc(x.time || "")}">${esc(ago(x.time))}</td>
          <td class="nw"><span class="dir ${x.kind === "call" ? "call" : x.direction}">${x.kind === "call" ? "CALL" : x.direction.toUpperCase()}</span>${x.change ? ` <span class="pill t-muted" title="${esc((x.change_confidence || "") + " confidence")}">change</span>` : ""}${x.mined ? ` <span class="pill t-good">mined</span>` : ""}</td>
          <td class="r nw ${x.direction === "in" ? "pos" : x.direction === "out" && x.amount ? "neg" : ""}">${x.kind === "call" ? `<span class="muted">${esc(x.method || "contract call")}</span>` : (x.direction === "out" ? "−" : x.direction === "in" ? "+" : "") + esc(fmtAmt(x.amount, x.asset))}</td>
          <td class="r">${fmtUsd(x.usd)}</td><td>${x.counterparty ? addrLink(x.counterparty, x.counterparty_label && x.counterparty_label !== "likely change" ? x.counterparty_label : null, w.chain) : "—"}${x.destination_tag ? ` <span class="muted">tag ${esc(x.destination_tag)}</span>` : ""}</td><td>${txLink(x.hash, w.chain)}</td></tr>`).join("")}</tbody></table></div>
          ${d.items.length >= 50 && !more ? `<div style="margin-top:10px"><button class="btn sm" data-act="more">Load more</button></div>` : ""}` : `<div class="empty">No activity found.</div>`;
      }
      if (key === "exposure") {
        const tone = d.risk === "high" ? "danger" : d.risk === "medium" ? "warn" : "good";
        box.innerHTML = `<div class="callout ${tone}"><div><b>${esc(d.verdict[0].toUpperCase() + d.verdict.slice(1))}</b><div class="muted" style="font-size:12.5px">Scanned ${d.scanned_txs} recent transactions.</div></div></div>
          <div class="grid2" style="margin-top:14px"><div class="card"><h3>Origin</h3><dl class="kv"><dt>First seen</dt><dd>${d.first_seen ? esc(dateStr(d.first_seen.time)) + ` (block ${esc(d.first_seen.height)})` : esc(d.first_seen_note || "unknown")}</dd>
            <dt>Funded by</dt><dd>${(d.funded_by || []).map(a => a === "block reward" ? "block reward" : addrLink(a, null, w.chain)).join(", ") || "—"}</dd>
            ${d.first_seen?.mined ? `<dt>Mined by</dt><dd>${esc(d.first_seen.mined.pool || "unknown")}, block ${d.first_seen.mined.height}</dd>` : ""}
            ${d.creator ? `<dt>Created by</dt><dd>${addrLink(d.creator.address, null, w.chain)}</dd>` : ""}</dl></div>
          <div class="card"><h3>Contacts</h3>${d.mixer_hits.length ? d.mixer_hits.map(m => `<div style="margin-bottom:6px"><span class="pill t-danger">${esc(m.mixer)}</span> ${esc(m.direction)} ${m.amount ? esc(fmtAmt(m.amount, m.asset)) : ""} ${txLink(m.hash, w.chain)} <span class="muted">${esc(ago(m.time))}</span>${m.note ? `<div class="muted" style="font-size:12px">${esc(m.note)}</div>` : ""}</div>`).join("") : ""}
            ${d.coinjoins.length ? d.coinjoins.map(c => `<div style="margin-bottom:6px"><span class="pill t-warn">${esc(c.type)}</span> ${txLink(c.txid, w.chain)} <span class="muted">block ${c.height}</span><div class="muted" style="font-size:12px">${esc(c.rule)}</div></div>`).join("") : ""}
            ${!d.mixer_hits.length && !d.coinjoins.length ? `<div class="muted">None found in the scanned history.</div>` : ""}</div></div>`;
      }
      if (key === "links") {
        box.innerHTML = `${d.links.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Chain</th><th>Address</th><th>Relation</th><th>Certainty</th></tr></thead><tbody>${d.links.map(l => `<tr><td>${chainChip(l.chain)}</td><td>${l.address.toLowerCase() === w.address.toLowerCase() ? `<span class="muted">same address</span>` : addrLink(l.address, null, l.chain)}</td><td title="${esc(l.why)}">${esc(l.relation)}</td><td><span class="pill ${l.certainty === "certain" ? "t-good" : "t-warn"}">${esc(l.certainty)}</span></td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">No same-owner wallets found on other chains.</div>`}
          ${(d.notes || []).map(n => `<div class="callout info" style="margin-top:10px">${esc(n)}</div>`).join("")}
          <p class="muted" style="font-size:12.5px">“Certain” means the same private key controls both addresses. “Likely” comes from clustering heuristics.</p>`;
      }
      if (key === "pass") {
        box.innerHTML = `<div class="callout ${d.events.length ? "warn" : "good"}"><b>${esc(d.verdict[0].toUpperCase() + d.verdict.slice(1))}</b>&nbsp;<span class="muted">${d.passed_through} of ${d.incoming} incoming transfers left again within a day for nearly the same amount.</span></div>
          ${d.events.length ? `<div class="tbl-wrap" style="margin-top:12px"><table class="tbl"><thead><tr><th>In</th><th>From</th><th>Out</th><th>To</th><th class="r">Kept</th><th class="r">Gap</th><th>Confidence</th></tr></thead><tbody>${d.events.map(x => `<tr><td class="nw">${esc(fmtAmt(x.amount_in, x.asset))} ${txLink(x.in_tx, w.chain)}</td><td>${addrLink(x.from, null, w.chain)}</td><td class="nw">${esc(fmtAmt(x.amount_out, x.asset))} ${txLink(x.out_tx, w.chain)}</td><td>${addrLink(x.to, null, w.chain)}</td><td class="r">${x.kept_pct}%</td><td class="r">${x.gap_hours}h</td><td><span class="pill ${x.confidence === "strong" ? "t-danger" : "t-warn"}">${esc(x.confidence)}</span> <span class="muted">${esc(x.note)}</span></td></tr>`).join("")}</tbody></table></div>` : ""}`;
      }
      if (key === "coins") {
        box.innerHTML = `<p class="muted" style="margin:0 0 10px">${d.count.toLocaleString()} unspent coins holding ${esc(fmtAmt(d.total, d.symbol))} (${fmtUsd(d.total_usd)}). Showing the ${d.shown} largest. Click a coin for its history.</p>
          <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Coin id</th><th class="r">Value</th><th class="r">Block</th><th>Age</th><th>Origin</th></tr></thead><tbody>${d.coins.map(c => `<tr class="click" data-coin="${esc(c.id)}"><td class="mono">${esc(short(c.txid, 10))}:${c.vout}</td><td class="r">${esc(fmtAmt(c.value, d.symbol))}</td><td class="r">${c.height ?? "mempool"}</td><td>${esc(c.age || "")}</td><td>${c.origin ? `<span class="pill ${c.origin === "mined" ? "t-good" : c.origin === "coinjoin" ? "t-warn" : "t-muted"}">${esc(c.coinjoin_type || c.origin)}</span>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
        $$("[data-coin]", box).forEach(r => r.onclick = () => openTab("lab", { tool: "coin", inputs: { coin: r.dataset.coin, chain: w.chain }, autorun: true }, { update: true }));
      }
    },
    right(el) {
      if (!w) { el.innerHTML = loading("…"); return; }
      el.innerHTML = `<div class="rsec"><h4>Flags</h4><div class="flag-list">${(w.flags || []).map(f => `<div class="flag-row">${pill(f)}<span class="h">${esc(S.flagInfo[f]?.hint || "")}</span></div>`).join("") || `<div class="r-empty">No flags.</div>`}</div></div>
        <div class="rsec"><h4>Next steps</h4><div class="rlist">
          <div class="ritem" data-r="trace-out"><div class="rt">Where did the money go?</div><div class="rc">Trace outgoing funds 2 hops.</div></div>
          <div class="ritem" data-r="trace-in"><div class="rt">Where did it come from?</div><div class="rc">Trace incoming funds 2 hops.</div></div>
          ${S.chainMap[w.chain]?.kind === "utxo" ? `<div class="ritem" data-r="peel"><div class="rt">Is it a peel chain?</div><div class="rc">Follow change outputs from the latest spend.</div></div><div class="ritem" data-r="cluster"><div class="rt">Find its other addresses</div><div class="rc">Common-input clustering.</div></div>` : `<div class="ritem" data-r="sweeps"><div class="rt">Is it a deposit address?</div><div class="rc">Checks if it forwards what it receives.</div></div>`}
          <div class="ritem" data-r="match"><div class="rt">Match amounts elsewhere</div><div class="rc">Find same-amount transfers on other wallets.</div></div>
        </div></div>`;
      el.onclick = e => {
        const r = e.target.closest("[data-r]")?.dataset.r; if (!r) return;
        if (r === "trace-out" || r === "trace-in") openTab("trace", { query: w.address, chain: w.chain, direction: r.slice(6), autorun: true }, { newTab: true });
        else if (r === "match") openTab("lab", { tool: "match", inputs: { sources: `${w.chain}:${w.address}` } }, { update: true });
        else openTab("lab", { tool: r, inputs: { address: w.address, chain: w.chain }, autorun: true }, { update: true });
      };
    },
  };
  return v;
};

/* ---------- transaction */
VIEWS.tx = tab => {
  let t = null;
  const st = tab.st;
  return {
    icon: "tx",
    async mount() {
      setTitle(tab, "Tx " + short(st.hash, 6), true);
      tab.el.innerHTML = `<div class="view-scroll"><div class="page">${loading("Looking up transaction…")}</div></div>`;
      try { t = await api("chain", "tx", { hash: st.hash, chain: st.chain }); } catch (e) { setTitle(tab, "Tx " + short(st.hash, 6)); $(".page", tab.el).innerHTML = errBox(e); return; }
      setTitle(tab, "Tx " + short(st.hash, 6));
      const sym = t.symbol || S.chainMap[t.chain]?.symbol || "";
      const io = (rows, title) => `<div class="card"><h3>${title} <span class="muted">${rows.length}</span></h3><div class="tbl-wrap" style="border:0"><table class="tbl"><tbody>${rows.slice(0, 200).map(r => `<tr${r.coin_id ? ` class="click" data-coin="${esc(r.coin_id)}"` : ""}><td>${r.address === "coinbase" ? `<span class="pill t-good">coinbase</span>` : addrLink(r.address, null, t.chain)}${t.change && t.change.address === r.address && title === "Outputs" ? ` <span class="pill t-muted" title="${esc(t.change.reasons.join("; "))}">change · ${esc(t.change.confidence)}</span>` : ""}</td><td class="r nw">${esc(fmtAmt(r.amount, sym))}</td></tr>`).join("")}</tbody></table></div></div>`;
      let body = "";
      if (t.inputs && Array.isArray(t.inputs)) body += `<div class="grid2">${io(t.inputs, "Inputs")}${io(t.outputs, "Outputs")}</div>`;
      if (t.coinjoin?.coinjoin) body += `<div class="callout warn"><b>CoinJoin: ${esc(t.coinjoin.type)}</b>&nbsp;<span class="muted">${esc(t.coinjoin.rule)}</span></div>`;
      if (t.change) body += `<div class="callout info"><div>Likely change: ${addrLink(t.change.address, null, t.chain)} (${esc(t.change.confidence)} confidence)<div class="muted" style="font-size:12.5px">${t.change.reasons.map(esc).join(" · ")}</div></div></div>`;
      if (t.from || t.to) body += `<div class="card"><dl class="kv"><dt>From</dt><dd>${addrLink(t.from, t.from_label, t.chain)}</dd><dt>To</dt><dd>${addrLink(t.to, t.to_label, t.chain)}</dd>${t.value != null ? `<dt>Value</dt><dd>${esc(fmtAmt(t.value, sym))} ${fmtUsd(t.value_usd)}</dd>` : ""}${t.method ? `<dt>Method</dt><dd class="mono">${esc(t.method)}</dd>` : ""}${t.destination_tag != null ? `<dt>Destination tag</dt><dd>${esc(t.destination_tag)}</dd>` : ""}</dl></div>`;
      if (t.token_transfers?.length) body += `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Asset</th><th class="r">Amount</th><th class="r">USD</th><th>From</th><th>To</th></tr></thead><tbody>${t.token_transfers.map(x => `<tr><td>${esc(x.asset || "?")}</td><td class="r">${esc(fmtAmt(x.amount))}</td><td class="r">${fmtUsd(x.usd)}</td><td>${addrLink(x.from, x.from_label, t.chain)}</td><td>${addrLink(x.to, x.to_label, t.chain)}</td></tr>`).join("")}</tbody></table></div>`;
      if (t.balance_changes) body += `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Account</th><th class="r">SOL change</th></tr></thead><tbody>${t.balance_changes.map(b => `<tr><td>${addrLink(b.address, null, "solana")}</td><td class="r ${b.change > 0 ? "pos" : "neg"}">${b.change > 0 ? "+" : ""}${esc(fmtAmt(b.change))}</td></tr>`).join("")}</tbody></table></div>`;
      if (t.chain === "monero") {
        body += `<div class="stats"><div class="stat"><div class="k">Inputs</div><div class="v">${t.inputs}</div><div class="s">ring size ${t.ring_size}</div></div><div class="stat"><div class="k">Outputs</div><div class="v">${t.outputs}</div><div class="s">${t.amounts_visible ? "amounts visible (coinbase)" : "amounts hidden"}</div></div><div class="stat"><div class="k">Fee</div><div class="v">${esc(fmtAmt(t.fee, "XMR"))}</div><div class="s">${fmtUsd(t.fee_usd)}</div></div><div class="stat"><div class="k">Size</div><div class="v">${(t.size || 0).toLocaleString()} B</div><div class="s">RingCT type ${t.rct_type}</div></div></div>
          <div class="card"><h3>Wallet fingerprints</h3>${t.fingerprints.length ? t.fingerprints.map(f => `<div class="flag-row" style="margin-bottom:6px"><span class="pill ${f.strength === "strong" || f.strength === "certain" ? "t-warn" : "t-info"}">${esc(f.signal)}</span><span class="h">${esc(f.meaning)} <span class="faint">(${esc(f.strength)})</span></span></div>`).join("") : `<div class="muted">Looks like a standard wallet transaction: nothing stands out.</div>`}</div>
          ${t.rings.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Key image</th><th class="r">Ring</th><th class="r">Newest member</th><th class="r">Oldest member</th></tr></thead><tbody>${t.rings.map(r => `<tr><td class="mono">${esc(short(r.key_image, 10))}</td><td class="r">${r.ring_size}</td><td class="r">${r.newest_age_blocks.toLocaleString()} blocks ago</td><td class="r">${r.oldest_age_blocks.toLocaleString()} blocks ago</td></tr>`).join("")}</tbody></table></div>` : ""}
          <div class="callout info">${esc(t.limits)}</div>`;
      }
      $(".page", tab.el).innerHTML = `<div class="hd"><div style="min-width:0"><h1>Transaction</h1><div class="sub">${chainChip(t.chain)}<span class="mono" style="overflow-wrap:anywhere">${esc(t.hash)}</span><button class="ib" data-copy="${esc(t.hash)}">${ICONS.copy}</button></div>
        <div class="sub">${t.time ? esc(dateStr(t.time)) + " UTC · " + esc(ago(t.time)) : ""}${t.block ? ` · block ${esc(t.block)}` : ""}${t.status ? ` · ${esc(t.status)}` : ""}${t.fee != null && t.chain !== "monero" ? ` · fee ${esc(fmtAmt(t.fee, sym))}` : ""}</div></div>
        <div class="acts"><button class="btn" id="txsave">${ICONS.save} Save to vault</button>${t.explorer_url ? `<a class="btn ghost" href="${esc(t.explorer_url)}" target="_blank" rel="noopener noreferrer">${ICONS.ext} Explorer</a>` : ""}</div></div>${body}`;
      $("#txsave", tab.el).onclick = async () => { try { const r = await api("vault", "save_tx", { tx: t }); await refreshTree(); toast("Saved"); openNote(r.path, true); } catch (e) { toast(e.message, true); } };
      $$("[data-coin]", tab.el).forEach(r => r.onclick = e => { if (e.target.closest("[data-wallet]")) return; openTab("lab", { tool: "coin", inputs: { coin: r.dataset.coin, chain: t.chain }, autorun: true }, { update: true }); });
      renderRight();
    },
    right(el) {
      el.innerHTML = t?.inputs && Array.isArray(t.inputs) ? `<div class="rsec"><h4>Tips</h4><div class="muted" style="font-size:12.5px">Click an output to see that coin's full history: the block it was created in, who mined it, and where it went next.</div></div>` : `<div class="r-empty">—</div>`;
    },
  };
};

/* ---------- forensics lab */
const LAB = {
  peel: { name: "Peel chain", desc: "Follows the change output forward, hop by hop. A peel chain is a large balance that sheds small payments each step.", fields: [["address", "Start: txid or address (BTC/LTC)", "text"], ["steps", "Max steps", "number", 25]], run: i => api("heur", "peel", { start: i.address, steps: +i.steps || 25, chain: i.chain }) },
  cluster: { name: "Cluster addresses", desc: "Addresses spent together in one non-CoinJoin transaction are very likely the same wallet. Also follows high-confidence change.", fields: [["address", "Bitcoin / Litecoin address", "text"]], run: i => api("heur", "cluster", { address: i.address, chain: i.chain }) },
  coin: { name: "Coin history", desc: "One coin (txid:vout): the block that created it, the pool that mined that block, where it was spent, and its ancestry.", fields: [["coin", "Coin id (txid:vout)", "text"], ["depth", "Ancestry depth", "number", 4]], run: i => api("forensics", "coin", { id: i.coin, depth: +i.depth || 4, chain: i.chain && i.chain !== "auto" ? i.chain : "bitcoin" }) },
  change: { name: "Change detection", desc: "Which output of a transaction went back to the sender, and why.", fields: [["txid", "Transaction id", "text"]], run: i => api("heur", "change", { t: i.txid, chain: i.chain && i.chain !== "auto" ? i.chain : "bitcoin" }) },
  links: { name: "Same-owner links", desc: "Wallets on other chains controlled by exactly the same key (certain), plus clustering (likely).", fields: [["address", "Any address", "text"], ["include_cluster", "Include clustering (BTC/LTC)", "checkbox"]], run: i => api("corr", "links", { address: i.address, chain: i.chain || "auto", include_cluster: !!i.include_cluster }) },
  match: { name: "Amount matching", desc: "Pairs money leaving some wallets with the same amount arriving at others within a time window, across chains. Built to avoid false positives: round or ambiguous amounts are downgraded, weak matches hidden.", fields: [["sources", "Source wallets (one per line, chain:address)", "textarea"], ["targets", "Target wallets (blank = same list)", "textarea"], ["window_hours", "Window (hours)", "number", 72], ["tolerance_pct", "Tolerance (%)", "number", 0.5], ["include_weak", "Show weak matches", "checkbox"]], run: i => api("corr", "match_amounts", { sources: lines(i.sources), targets: lines(i.targets).length ? lines(i.targets) : null, window_hours: +i.window_hours || 72, tolerance_pct: +i.tolerance_pct || 0.5, include_weak: !!i.include_weak }) },
  sweeps: { name: "Deposit address check", desc: "Does this address forward almost everything it receives to one place? That's how exchange deposit addresses behave.", fields: [["address", "Address", "text"]], run: i => api("heur", "sweeps", { address: i.address, chain: i.chain || "auto" }) },
  monero: { name: "Monero transaction", desc: "Monero hides senders, receivers and amounts. This shows what is public: shape, fee and ring ages as wallet fingerprints.", fields: [["txid", "Monero transaction hash", "text"]], run: i => api("chain", "tx", { hash: i.txid, chain: "monero" }) },
};
const lines = s => (s || "").split(/[\n,]+/).map(x => x.trim()).filter(Boolean);
VIEWS.lab = tab => {
  const st = tab.st; st.tool ||= "peel"; st.inputs ||= {};
  let result = null, running = false;
  const v = {
    icon: "lab",
    persist: () => ({ tool: st.tool, inputs: st.inputs }),
    mount() { setTitle(tab, "Forensics lab"); v.render(); if (st.autorun) { st.autorun = false; v.run(); } },
    update(nst) { st.tool = nst.tool || st.tool; st.inputs = Object.assign({}, nst.inputs || {}); result = null; v.render(); if (nst.autorun) v.run(); },
    render() {
      const T = LAB[st.tool];
      tab.el.innerHTML = `<div class="split"><div class="pane-l"><div class="pane-head"><span class="pane-title">Tools</span></div><div class="rlist" style="padding:0 8px">${Object.entries(LAB).map(([k, t]) => `<div class="ritem${k === st.tool ? " on" : ""}" data-tool="${k}" style="${k === st.tool ? "background:var(--accent-bg)" : ""}"><div class="rt">${esc(t.name)}</div></div>`).join("")}</div></div>
        <div class="pane-r"><div class="view-scroll"><div class="page narrow">
          <div><h1 style="font-size:20px;margin:0 0 4px">${esc(T.name)}</h1><p class="muted" style="margin:0">${esc(T.desc)}</p></div>
          <form class="card" id="lf-${tab.id}" style="display:flex;flex-direction:column;gap:10px">${T.fields.map(([k, label, type, def]) => type === "checkbox" ? `<label class="chk"><input type="checkbox" name="${k}" ${st.inputs[k] ? "checked" : ""}> ${esc(label)}</label>` : `<div class="field"><label>${esc(label)}</label>${type === "textarea" ? `<textarea class="inp mono" name="${k}" rows="4" spellcheck="false">${esc(st.inputs[k] || "")}</textarea>` : `<input class="inp ${type === "text" ? "mono" : ""}" name="${k}" type="${type}" value="${esc(st.inputs[k] ?? def ?? "")}" spellcheck="false" autocomplete="off" ${type === "number" ? 'step="any" style="max-width:140px"' : ""}>`}</div>`).join("")}
            <div style="display:flex;gap:8px;align-items:center">${["peel", "cluster", "coin", "change"].includes(st.tool) ? `<select class="sel" name="chain"><option value="auto">Auto</option><option value="bitcoin">Bitcoin</option><option value="litecoin">Litecoin</option><option value="bitcoin-testnet">Bitcoin testnet</option></select>` : ""}
            <button class="btn primary" type="submit">${ICONS.play} Run</button><span class="grow"></span>${result ? `<button class="btn" type="button" id="lsave">${ICONS.save} Save as report</button>` : ""}</div></form>
          <div id="lr-${tab.id}"></div></div></div></div></div>`;
      const form = $(`#lf-${tab.id}`);
      if (st.inputs.chain && form.chain) form.chain.value = st.inputs.chain;
      form.onsubmit = e => { e.preventDefault(); v.run(); };
      $$("[data-tool]", tab.el).forEach(x => x.onclick = () => { st.tool = x.dataset.tool; result = null; v.render(); saveTabs(); });
      $("#lsave", tab.el)?.addEventListener("click", () => v.save());
      if (result) v.showResult();
    },
    collect() { const f = $(`#lf-${tab.id}`); const o = {}; [...f.elements].forEach(el => { if (!el.name) return; o[el.name] = el.type === "checkbox" ? el.checked : el.value; }); st.inputs = Object.assign(st.inputs, o); saveTabs(); return st.inputs; },
    async run() {
      if (running) return; const T = LAB[st.tool]; const inp = $(`#lf-${tab.id}`) ? v.collect() : st.inputs;
      const box = $(`#lr-${tab.id}`); box.innerHTML = loading("Running " + T.name.toLowerCase() + "…"); running = true; setTitle(tab, "Forensics lab", true);
      try { result = await T.run(inp); v.render(); }
      catch (e) { box.innerHTML = errBox(e); }
      finally { running = false; setTitle(tab, "Forensics lab"); }
    },
    async save() {
      const kind = { peel: "peel", cluster: "cluster", coin: "coin", match: "matches", links: "links" }[st.tool] || st.tool;
      const title = `${LAB[st.tool].name} ${short(st.inputs.address || st.inputs.coin || st.inputs.txid || lines(st.inputs.sources)[0] || "", 8)} ${new Date().toISOString().slice(0, 10)}`;
      try { const r = await api("vault", "save_report", { kind, data: result, title }); await refreshTree(); toast("Saved report"); openNote(r.path, true); } catch (e) { toast(e.message, true); }
    },
    showResult() {
      const box = $(`#lr-${tab.id}`), d = result, ch = d.chain || st.inputs.chain;
      const conf = c => `<span class="pill ${c === "strong" || c === "high" || c === "certain" ? "t-good" : c === "possible" || c === "medium" || c === "likely" ? "t-warn" : "t-muted"}">${esc(c)}</span>`;
      if (st.tool === "peel") box.innerHTML = `<div class="callout ${d.is_peel_chain ? "warn" : "info"}"><div><b>${d.is_peel_chain ? "Peel chain" : "Not a peel chain"}</b> ${conf(d.confidence)}<div class="muted" style="font-size:12.5px">${d.length} steps · peeled ${esc(fmtAmt(d.total_peeled, d.symbol))} (${fmtUsd(d.total_peeled_usd)}) · median change/peel ratio ${(d.median_change_to_peel || 0).toFixed(1)}× · stopped: ${esc(d.stopped_because)}</div></div></div>
        ${d.hops.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th class="r">Step</th><th>Tx</th><th>Peeled to</th><th class="r">Peeled</th><th class="r">Change</th><th>Change confidence</th></tr></thead><tbody>${d.hops.map(h => `<tr><td class="r">${h.step}</td><td>${txLink(h.txid, d.chain)}</td><td>${h.peeled.map(p => addrLink(p.address, null, d.chain)).join(", ")}</td><td class="r">${esc(fmtAmt(h.peel_total))}</td><td class="r">${esc(fmtAmt(h.change))}</td><td>${conf(h.change_confidence)}</td></tr>`).join("")}</tbody></table></div>` : ""}
        ${d.top_destinations?.length ? `<div class="card"><h3>Where the peels went</h3>${d.top_destinations.map(t => `<div>${addrLink(t.address, null, d.chain)} <span class="muted">${esc(fmtAmt(t.value, d.symbol))}</span></div>`).join("")}</div>` : ""}`;
      if (st.tool === "cluster") box.innerHTML = `<div class="callout info"><div><b>${d.size} addresses</b> <span class="muted">· ${esc(d.method)} · ${d.transactions_used} transactions used · ${d.coinjoins_skipped} CoinJoins skipped${d.truncated ? " · stopped early, there may be more" : ""}</span></div></div>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Address</th><th>Why</th><th class="r">Depth</th><th>Via</th></tr></thead><tbody>${d.addresses.map(m => `<tr><td>${addrLink(m.address, null, d.chain)}</td><td>${esc(m.reason)}</td><td class="r">${m.depth}</td><td>${m.via ? txLink(m.via, d.chain) : ""}</td></tr>`).join("")}</tbody></table></div>`;
      if (st.tool === "coin") { const b = d.block || {}; box.innerHTML = `<div class="stats"><div class="stat"><div class="k">Value</div><div class="v">${esc(fmtAmt(d.value, d.symbol))}</div><div class="s">${fmtUsd(d.usd)}</div></div><div class="stat"><div class="k">Created</div><div class="v">block ${esc(d.created.height ?? "—")}</div><div class="s">${esc(d.created.age || "")} ago</div></div><div class="stat"><div class="k">Mined by</div><div class="v">${esc(b.pool || "unknown")}</div><div class="s mono">${esc((b.coinbase_tag || "").slice(0, 28))}</div></div><div class="stat"><div class="k">Status</div><div class="v">${d.spent ? "Spent" : "Unspent"}</div><div class="s">${d.spent ? esc(ago(d.spent.time)) : "still held"}</div></div></div>
        <div class="card"><dl class="kv"><dt>Coin id</dt><dd class="mono">${esc(d.id)}</dd><dt>Held by</dt><dd>${addrLink(d.address, null, d.chain)} <span class="muted">${esc(d.script_type || "")}</span></dd><dt>Origin</dt><dd>${esc(d.origin)}${d.coinjoin?.coinjoin ? ` · ${esc(d.coinjoin.type)}` : ""}</dd><dt>Created in</dt><dd>${txLink(d.created.txid, d.chain)} · ${esc(dateStr(d.created.time))}</dd>${d.spent ? `<dt>Spent in</dt><dd>${txLink(d.spent.txid, d.chain)} · ${esc(dateStr(d.spent.time))}${d.spent.coinjoin?.coinjoin ? ` <span class="pill t-warn">into a CoinJoin</span>` : ""}</dd><dt>Went to</dt><dd>${(d.spent.to || []).map(x => addrLink(x.address, null, d.chain) + ` <span class="muted">${esc(fmtAmt(x.value))}</span>`).join("<br>")}</dd>` : ""}</dl></div>
        ${d.mixer_exposure ? `<div class="callout warn">This coin passed through a CoinJoin in its recent history.</div>` : ""}
        <div class="card"><h3>Ancestry (largest input each step)</h3>${d.ancestry.map(a => `<div style="margin-bottom:6px"><span class="pill ${a.kind === "mined" ? "t-good" : a.kind === "coinjoin" ? "t-warn" : "t-muted"}">${esc(a.kind)}</span> step ${a.step} · block ${esc(a.height ?? "—")} ${a.coin_id ? `· coin <span class="addr" data-coinlink="${esc(a.coin_id)}">${esc(short(a.coin_id, 8))}</span>` : ""} ${a.address ? "· " + addrLink(a.address, null, d.chain) : ""}${a.block ? ` · mined by <b>${esc(a.block.pool || "unknown")}</b>` : ""}</div>`).join("") || `<div class="muted">No earlier history (freshly mined).</div>`}</div>`;
        $$("[data-coinlink]", box).forEach(x => x.onclick = () => { st.inputs.coin = x.dataset.coinlink; v.render(); v.run(); }); }
      if (st.tool === "change") box.innerHTML = d ? `<div class="callout info"><div>Change: ${addrLink(d.address, null, ch)} · ${esc(fmtAmt(d.value))} ${conf(d.confidence)}<ul style="margin:6px 0 0 18px;padding:0">${d.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div></div>` : `<div class="callout">No defensible change guess for this transaction (CoinJoin, single output, or a tie between outputs).</div>`;
      if (st.tool === "links") box.innerHTML = `${d.links.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Chain</th><th>Address</th><th>Relation</th><th>Certainty</th></tr></thead><tbody>${d.links.map(l => `<tr><td>${chainChip(l.chain)}</td><td>${addrLink(l.address, null, l.chain)}</td><td title="${esc(l.why)}">${esc(l.relation)}</td><td>${conf(l.certainty)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">No links found.</div>`}${(d.notes || []).map(n => `<div class="callout info" style="margin-top:8px">${esc(n)}</div>`).join("")}`;
      if (st.tool === "match") box.innerHTML = `<div class="callout ${d.strong ? "warn" : "info"}"><div><b>${d.strong} strong · ${d.possible} possible</b> <span class="muted">· ${d.weak_hidden ? d.weak_hidden + " weak hidden · " : ""}${d.departures_checked} departures × ${d.arrivals_checked} arrivals checked</span><div class="muted" style="font-size:12.5px">${esc(d.method)}</div></div></div>
        ${(d.errors || []).map(x => `<div class="err">${esc(x)}</div>`).join("")}
        ${d.matches.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Confidence</th><th>Left</th><th>Arrived</th><th class="r">Gap</th><th>Why</th></tr></thead><tbody>${d.matches.map(m => `<tr><td>${conf(m.confidence)}</td><td>${addrLink(m.from_wallet, null, m.from_chain)} ${chainChip(m.from_chain)}<br><span class="nw">${esc(fmtAmt(m.out_amount, m.out_asset))}</span> ${txLink(m.out_tx, m.from_chain)}</td><td>${addrLink(m.to_wallet, null, m.to_chain)} ${chainChip(m.to_chain)}<br><span class="nw">${esc(fmtAmt(m.in_amount, m.in_asset))}</span> ${txLink(m.in_tx, m.to_chain)}</td><td class="r">${m.gap_hours}h</td><td class="muted" style="font-size:12px">${m.why.map(esc).join(" · ")}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty"><h2>No matches</h2><p>Nothing passed the false-positive filters. Widen the window or tolerance, or show weak matches.</p></div>`}`;
      if (st.tool === "sweeps") box.innerHTML = `<div class="callout ${d.is_deposit_address ? "warn" : "info"}"><div><b>${esc(d.pattern)}</b><div class="muted" style="font-size:12.5px">${esc(d.explanation || "")}</div>${d.main_destination ? `<div style="margin-top:6px">Main destination: ${addrLink(d.main_destination, null, d.chain)} (${d.main_destination_count}×)</div>` : ""}</div></div>`;
      if (st.tool === "monero") { openTab("tx", { hash: st.inputs.txid, chain: "monero" }, { newTab: true }); box.innerHTML = `<div class="muted">Opened in a new tab.</div>`; }
    },
    right(el) { el.innerHTML = `<div class="rsec"><h4>About false positives</h4><div class="muted" style="font-size:12.5px">Every result says which rule fired and how sure it is. “Certain” comes from cryptography (same key). “High/strong” needs several independent signals. Treat “possible” as a lead to check by hand, not a conclusion.</div></div>`; },
  };
  return v;
};

/* ---------- binary workbench */
VIEWS.binary = tab => {
  const st = tab.st; let sum = null, funcs = [], sub = "functions", hist = [], curFn = null, strCache = {}, hexOff = 0;
  st.stars ||= [];
  const v = {
    icon: "binary",
    persist: () => ({ path: st.path, stars: st.stars, arch: st.arch }),
    mount() {
      setTitle(tab, st.path ? st.path.split("/").filter(Boolean).pop() : "Binary");
      tab.el.innerHTML = `<div class="toolbar"><div class="field q"><label>Program or library</label><input class="inp mono" id="bp-${tab.id}" value="${esc(st.path || "")}" placeholder="/System/Applications/Calculator.app" spellcheck="false" autocomplete="off"></div>
        <button class="btn primary" id="bo-${tab.id}">Open</button>
        <div class="examples" style="margin-left:4px">Try: <button data-p="/bin/ls">ls</button><button data-p="/System/Applications/Calculator.app">Calculator</button><button data-p="/usr/bin/ssh">ssh</button><button data-p="/usr/bin/curl">curl</button></div></div>
        <div class="bin-body" style="flex:1;min-height:0;display:flex;flex-direction:column"></div>`;
      const inp = $(`#bp-${tab.id}`);
      const go = () => { st.path = inp.value.trim(); if (st.path) { tab.key = tabKey("binary", st); v.load(); } };
      inp.onkeydown = e => { if (e.key === "Enter") go(); };
      $(`#bo-${tab.id}`).onclick = go;
      tab.el.querySelector(".toolbar").addEventListener("click", e => { const b = e.target.closest("[data-p]"); if (b) { inp.value = b.dataset.p; go(); } });
      if (st.path) v.load(); else $(".bin-body", tab.el).innerHTML = `<div class="empty" style="margin-top:8vh"><h2>Take a program apart</h2><p>Open any executable, library or .app on this Mac. You'll get its functions, strings, imports, disassembly with clickable calls, raw hex and cross-references.<br>Read-only: nothing is modified.</p></div>`;
    },
    async load() {
      const body = $(".bin-body", tab.el); body.innerHTML = loading("Reading binary…"); setTitle(tab, st.path.split("/").filter(Boolean).pop(), true);
      try {
        sum = await api("bin", "summary", { path: st.path, arch: st.arch });
        funcs = await api("bin", "functions", { path: st.path, arch: sum.arch });
      } catch (e) {
        setTitle(tab, st.path.split("/").filter(Boolean).pop());
        body.innerHTML = `<div style="padding:14px 18px 0"><div class="callout info"><div><b>Can't disassemble this file with the macOS toolchain</b><div class="muted" style="font-size:12.5px">${esc(e.message)}. Showing static malware triage instead (the file is read, never run).</div></div></div></div><div class="bin-sub" style="flex:1;min-height:0;display:flex;flex-direction:column"></div>`;
        renderTriage($(".bin-sub", body), st.path, tab); return;
      }
      setTitle(tab, sum.name); saveTabs();
      if (!funcs.length && (sub === "functions" || sub === "classes")) sub = "triage";   // scripts, documents, data files
      const sig = sum.signature || {};
      body.innerHTML = `<div style="padding:14px 18px 0;display:flex;flex-direction:column;gap:10px"><div class="hd"><div style="min-width:0"><h1>${esc(sum.name)}</h1><div class="sub"><span>${esc(sum.type.split(":")[0].slice(0, 80))}</span>
          ${sum.archs.length > 1 ? `<select class="sel" id="ba-${tab.id}" style="padding:2px 8px">${sum.archs.map(a => `<option ${a === sum.arch ? "selected" : ""}>${esc(a)}</option>`).join("")}</select>` : `<span class="pill plain">${esc(sum.arch || "")}</span>`}
          <span>${(sum.size / 1024).toFixed(0)} KB</span><span>${sum.function_count.toLocaleString()} functions (${sum.named_function_count} named)</span><span>${sum.import_count} imports</span>
          <span class="${sig.unsigned ? "neg" : ""}">${sig.unsigned ? "unsigned" : esc((sig.authority || [])[0] || sig.identifier || "")}</span></div></div>
          <div class="acts"><button class="btn" id="bsave-${tab.id}">${ICONS.save} Save to vault</button></div></div>
        <div class="subtabs" id="bt-${tab.id}">${Object.entries({ functions: "Functions", classes: "Classes", strings: "Strings", imports: "Imports", xrefs: "Cross-refs", hex: "Hex", triage: "Malware triage", info: "Info" }).map(([k, l]) => `<button data-bsub="${k}" class="${sub === k ? "on" : ""}">${l}</button>`).join("")}</div></div>
        <div class="bin-sub" style="flex:1;min-height:0;display:flex;flex-direction:column"></div>`;
      $(`#ba-${tab.id}`)?.addEventListener("change", e => { st.arch = e.target.value; strCache = {}; v.load(); });
      $(`#bt-${tab.id}`).onclick = e => { const b = e.target.closest("[data-bsub]"); if (!b) return; sub = b.dataset.bsub; $$(`#bt-${tab.id} button`).forEach(x => x.classList.toggle("on", x === b)); v.renderSub(); };
      $(`#bsave-${tab.id}`).onclick = async () => { try { const r = await api("vault", "save_binary", { summary: sum, functions_of_interest: st.stars }); await refreshTree(); toast("Saved"); openNote(r.path, true); } catch (e) { toast(e.message, true); } };
      v.renderSub(); renderRight();
    },
    renderSub() {
      const box = $(".bin-sub", tab.el);
      if (sub === "functions") {
        box.innerHTML = `<div class="split"><div class="pane-l"><div style="padding:8px"><input class="inp mono" id="bf-${tab.id}" placeholder="Filter ${funcs.length.toLocaleString()} functions…" style="width:100%"></div><div class="fn-list" id="bl-${tab.id}"></div></div>
          <div class="pane-r"><div class="asm-head" id="bh-${tab.id}"></div><div class="asm" id="bd-${tab.id}"></div></div></div>`;
        const list = $(`#bl-${tab.id}`); let filtered = funcs;
        const drawList = () => { const shown = filtered.slice(0, 3000); list.innerHTML = shown.map(f => `<div class="fn${f.named ? " named" : ""}${curFn && curFn.addr === f.addr ? " on" : ""}" data-fa="${f.addr}"><span class="fa">${f.addr.replace(/^0x0*/, "")}</span><span class="fnm" title="${esc(f.name)}">${esc(f.display || f.name)}</span>${f.objc ? `<span class="faint" style="margin-left:auto">objc</span>` : ""}</div>`).join("") + (filtered.length > 3000 ? `<div class="r-empty" style="padding:8px 12px">${(filtered.length - 3000).toLocaleString()} more: narrow the filter.</div>` : ""); };
        $(`#bf-${tab.id}`).oninput = e => { const q = e.target.value.toLowerCase(); filtered = q ? funcs.filter(f => f.name.toLowerCase().includes(q) || (f.display || "").toLowerCase().includes(q) || f.addr.includes(q)) : funcs; drawList(); };
        list.onclick = e => { const f = e.target.closest("[data-fa]"); if (f) v.disasm({ address: f.dataset.fa }); };
        drawList(); v.disasm(curFn ? { address: curFn.addr } : {}, true);
      }
      if (sub === "strings") {
        box.innerHTML = `<div style="padding:10px 18px;display:flex;gap:8px;flex-wrap:wrap;align-items:center"><input class="inp mono" id="bsf-${tab.id}" placeholder="Filter strings (regex)…" style="flex:1;min-width:200px">
          <div class="seg" id="bsp-${tab.id}">${["all", "urls", "paths", "errors", "crypto", "format", "keys"].map(p => `<button data-pr="${p}" class="${p === "all" ? "on" : ""}">${p}</button>`).join("")}</div></div><div class="view-scroll" id="bsl-${tab.id}" style="padding:0 18px 20px"></div>`;
        let preset = null, ft;
        const load = async () => { const q = $(`#bsf-${tab.id}`).value; const k = (preset || "") + "|" + q; const l = $(`#bsl-${tab.id}`); l.innerHTML = loading("…");
          try { const r = strCache[k] ||= await api("bin", "strings", { path: st.path, filter: q || null, preset, limit: 2500 });
            l.innerHTML = `<div class="muted" style="font-size:12px;margin-bottom:6px">${r.total.toLocaleString()} strings${r.total > 2500 ? ", first 2,500 shown" : ""}. Click one to find the code that uses it.</div><div class="tbl-wrap"><table class="tbl"><thead><tr><th class="r">Offset</th><th>String</th><th></th></tr></thead><tbody>${r.items.map(s => `<tr class="click" data-str="${esc(s.text)}"><td class="r mono muted">${s.offset.toString(16)}</td><td class="mono" style="overflow-wrap:anywhere">${esc(s.text)}</td><td><button class="btn sm ghost" data-hex="${s.offset}">hex</button></td></tr>`).join("")}</tbody></table></div>`;
          } catch (e) { l.innerHTML = errBox(e); } };
        $(`#bsf-${tab.id}`).oninput = () => { clearTimeout(ft); ft = setTimeout(load, 250); };
        $(`#bsp-${tab.id}`).onclick = e => { const b = e.target.closest("[data-pr]"); if (!b) return; preset = b.dataset.pr === "all" ? null : b.dataset.pr; $$(`#bsp-${tab.id} button`).forEach(x => x.classList.toggle("on", x === b)); load(); };
        $(`#bsl-${tab.id}`).onclick = e => { const h = e.target.closest("[data-hex]"); if (h) { e.stopPropagation(); hexOff = +h.dataset.hex & ~15; v.go("hex"); return; } const s = e.target.closest("[data-str]"); if (s) v.xrefs(s.dataset.str.slice(0, 60)); };
        load();
      }
      if (sub === "classes") { renderClasses(box, st.path, sum.arch, tab, v); return; }
      if (sub === "triage") { renderTriage(box, st.path, tab); return; }
      if (sub === "imports") {
        box.innerHTML = loading("…");
        api("bin", "imports", { path: st.path, arch: sum.arch }).then(im => { box.innerHTML = `<div class="view-scroll" style="padding:12px 18px"><div class="muted" style="font-size:12px;margin-bottom:8px">${im.length} imported symbols. Click one to see every call site.</div><div style="columns:3 240px;font-family:var(--mono);font-size:12.5px">${im.map(s => `<div class="addr" data-imp="${esc(s)}" style="display:block;padding:2px 0">${esc(s)}</div>`).join("")}</div></div>`;
          box.onclick = e => { const i = e.target.closest("[data-imp]"); if (i) v.xrefs("symbol stub for: " + i.dataset.imp); }; }).catch(e => box.innerHTML = errBox(e));
      }
      if (sub === "xrefs") {
        box.innerHTML = `<div style="padding:10px 18px;display:flex;gap:8px"><input class="inp mono" id="bx-${tab.id}" placeholder="Name, string text, address or constant" style="flex:1" value="${esc(st.xq || "")}"><button class="btn primary" id="bxg-${tab.id}">Find</button></div><div class="view-scroll" id="bxr-${tab.id}" style="padding:0 18px 20px"></div>`;
        const go = () => v.xrefs($(`#bx-${tab.id}`).value.trim(), true);
        $(`#bx-${tab.id}`).onkeydown = e => { if (e.key === "Enter") go(); }; $(`#bxg-${tab.id}`).onclick = go;
        if (st.xq) v.xrefs(st.xq, true);
      }
      if (sub === "hex") {
        box.innerHTML = `<div style="padding:10px 18px;display:flex;gap:8px;align-items:center"><span class="lbl">Offset</span><input class="inp mono" id="bho-${tab.id}" style="width:150px" value="0x${hexOff.toString(16)}"><button class="btn sm" data-hx="-512">◀ 512</button><button class="btn sm" data-hx="512">512 ▶</button><span class="muted" style="font-size:12px">file size ${sum.size.toLocaleString()} bytes</span></div><div class="hex view-scroll" id="bhx-${tab.id}"></div>`;
        const load = async () => { try { const r = await api("bin", "hexdump", { path: st.path, offset: hexOff, length: 1024 });
          $(`#bhx-${tab.id}`).innerHTML = r.rows.map(row => `<div class="r"><span class="o">${row.offset.toString(16).padStart(8, "0")}</span><span class="h">${row.hex.match(/../g).map((b, i) => (b === "00" ? `<span class="z">00</span>` : b) + (i === 7 ? " " : "")).join(" ")}</span><span class="c">${esc(row.ascii)}</span></div>`).join(""); } catch (e) { $(`#bhx-${tab.id}`).innerHTML = errBox(e); } };
        $(`#bho-${tab.id}`).onkeydown = e => { if (e.key === "Enter") { const t = e.target.value.trim(); hexOff = t.startsWith("0x") ? parseInt(t, 16) : parseInt(t, 10) || 0; load(); } };
        box.onclick = e => { const b = e.target.closest("[data-hx]"); if (b) { hexOff = Math.max(0, hexOff + +b.dataset.hx); $(`#bho-${tab.id}`).value = "0x" + hexOff.toString(16); load(); } };
        load();
      }
      if (sub === "info") {
        const sig = sum.signature || {};
        box.innerHTML = `<div class="view-scroll"><div class="page" style="padding-top:12px"><div class="grid2"><div class="card"><h3>Identity</h3><dl class="kv"><dt>Path</dt><dd class="mono">${esc(sum.path)}</dd><dt>Type</dt><dd>${esc(sum.type)}</dd><dt>SHA-256</dt><dd class="mono" style="font-size:11.5px">${esc(sum.sha256)} <button class="ib" data-copy="${esc(sum.sha256)}">${ICONS.copy}</button></dd><dt>Entry point</dt><dd class="mono">${esc(sum.entry || "—")}</dd></dl></div>
          <div class="card"><h3>Code signature</h3><dl class="kv">${sig.unsigned ? `<dt>Status</dt><dd class="neg">Not signed</dd>` : `<dt>Identifier</dt><dd>${esc(sig.identifier || "—")}</dd><dt>Team</dt><dd>${esc(sig.teamidentifier || "—")}</dd><dt>Chain</dt><dd>${(sig.authority || []).map(esc).join(" → ") || "—"}</dd><dt>Runtime</dt><dd>${esc(sig.runtime_version || "—")}</dd>`}</dl></div></div>
          <div class="card"><h3>Linked libraries <span class="muted">${sum.libraries.length}</span></h3><div class="mono" style="font-size:12px;columns:2 320px">${sum.libraries.map(l => `<div>${esc(l)}</div>`).join("")}</div></div>
          <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Section</th><th class="r">Size</th><th>Address</th><th>Kind</th></tr></thead><tbody>${sum.sections.map(s => `<tr><td class="mono">${esc(s.name)}</td><td class="r">${s.size.toLocaleString()}</td><td class="mono">${esc(s.addr)}</td><td>${esc(s.kind)}</td></tr>`).join("")}</tbody></table></div></div></div>`;
      }
    },
    current: () => ({ path: st.path, fn: curFn, arch: sum?.arch, name: sum?.name }),
    go(s) { sub = s; $$(`#bt-${tab.id} button`).forEach(x => x.classList.toggle("on", x.dataset.bsub === s)); v.renderSub(); },
    async xrefs(q, here) {
      st.xq = q; if (!here) { v.go("xrefs"); return; }
      const r = $(`#bxr-${tab.id}`); $(`#bx-${tab.id}`).value = q; r.innerHTML = loading("Searching the disassembly…");
      try { const d = await api("bin", "xrefs", { path: st.path, needle: q, arch: sum.arch });
        r.innerHTML = `<div class="muted" style="font-size:12px;margin-bottom:6px">${d.total} references${d.total >= 500 ? " (first 500)" : ""}. Click to open the function.</div><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Function</th><th>Address</th><th>Instruction</th></tr></thead><tbody>${d.items.map(x => `<tr class="click" data-xa="${x.addr}"><td class="mono">${esc(x.function || "")}</td><td class="mono muted">${esc(x.addr)}</td><td class="mono">${esc(x.text)}</td></tr>`).join("")}</tbody></table></div>`;
        r.onclick = e => { const t = e.target.closest("[data-xa]"); if (t) { v.go("functions"); setTimeout(() => v.disasm({ address: t.dataset.xa, highlight: t.dataset.xa }), 30); } };
      } catch (e) { r.innerHTML = errBox(e); }
    },
    async disasm(q, noHist) {
      const d = $(`#bd-${tab.id}`), h = $(`#bh-${tab.id}`); if (!d) return; d.innerHTML = loading("Disassembling…");
      let r; try { r = await api("bin", "disassemble", { path: st.path, symbol: q.symbol, address: q.address, arch: sum.arch }); } catch (e) { d.innerHTML = errBox(e); return; }
      if (curFn && !noHist && curFn.addr !== r.function.addr) hist.push(curFn);
      curFn = r.function;
      const starred = st.stars.some(s => s.addr === curFn.addr);
      h.innerHTML = `${hist.length ? `<button class="ib" id="bback-${tab.id}" title="Back">${ICONS.back}</button>` : ""}<b title="${esc(curFn.name)}">${esc(curFn.display || curFn.name)}</b><span class="mono">${esc(curFn.addr)}</span><span>${r.lines.length} instructions${r.truncated ? " (cut)" : ""}</span><span class="grow"></span>
        <button class="btn sm" id="bai-${tab.id}" title="Send this function (code, strings, calls, callers) to your AI">✦ Explain with AI</button><button class="btn sm ghost" id="bxr2-${tab.id}">Who calls this?</button><button class="ib" id="bstar-${tab.id}" title="${starred ? "Remove from" : "Add to"} functions of interest" style="color:${starred ? "var(--warn)" : ""}">${ICONS.star}</button>`;
      $(`#bback-${tab.id}`)?.addEventListener("click", () => { const p = hist.pop(); v.disasm({ address: p.addr }, true); });
      $(`#bxr2-${tab.id}`).onclick = () => v.xrefs(curFn.addr);
      $(`#bai-${tab.id}`).onclick = () => explainFunction(st.path, curFn, sum.arch);
      $(`#bstar-${tab.id}`).onclick = async () => { if (starred) st.stars = st.stars.filter(s => s.addr !== curFn.addr); else { const note = await promptInline("What does this function do? (optional)", ""); st.stars.push({ addr: curFn.addr, name: curFn.name, note: note || "" }); } saveTabs(); v.disasm({ address: curFn.addr }, true); renderRight(); };
      const hl = q.highlight;
      d.innerHTML = r.lines.map(l => `<div class="l${hl && l.addr === hl ? " hl" : ""}" id="${tab.id}-${l.addr}"><span class="a">${l.addr.replace(/^0x0*/, "")}</span><span>${asmHtml(l)}</span></div>`).join("");
      d.onclick = e => { const k = e.target.closest("[data-jump]"); if (k) v.disasm({ address: k.dataset.jump }); const n = e.target.closest("[data-jsym]"); if (n) v.disasm({ symbol: n.dataset.jsym }); };
      if (hl) document.getElementById(`${tab.id}-${hl}`)?.scrollIntoView({ block: "center" });
      $$(`#bl-${tab.id} .fn`).forEach(f => f.classList.toggle("on", f.dataset.fa === curFn.addr));
    },
    right(el) {
      if (!sum) { el.innerHTML = `<div class="rsec"><h4>What this does</h4><div class="muted" style="font-size:12.5px">Reads a compiled program with the system toolchain: identity and signature, functions (even in stripped binaries, from LC_FUNCTION_STARTS), strings, imports, disassembly and cross-references. It never modifies the file.</div></div>`; return; }
      el.innerHTML = `<div class="rsec"><h4>Functions of interest <span class="cnt">${st.stars.length}</span></h4><div class="rlist">${st.stars.map(s => `<div class="ritem" data-sa="${s.addr}"><div class="rt mono">${esc(s.name)}</div><div class="rc">${esc(s.note || s.addr)}</div></div>`).join("") || `<div class="r-empty">Star a function in the disassembly to keep it here. Starred functions go into the vault note.</div>`}</div></div>
        <div class="rsec"><h4>Workflow</h4><div class="muted" style="font-size:12.5px">1. Search <b>Strings</b> for text you see in the app.<br>2. Click it to find the code that uses it.<br>3. Follow calls in the disassembly (click blue targets).<br>4. Star what matters and save to the vault.</div></div>`;
      el.onclick = e => { const s = e.target.closest("[data-sa]"); if (s) { v.go("functions"); setTimeout(() => v.disasm({ address: s.dataset.sa }), 30); } };
    },
  };
  return v;
};
function asmHtml(l) {
  const t = l.text; const m = t.match(/^(\S+)\s*(.*)$/); if (!m) return esc(t);
  const mn = m[1]; let rest = m[2]; let comment = "";
  const ci = rest.search(/\s[;#]{1,2}\s/); if (ci >= 0) { comment = rest.slice(ci); rest = rest.slice(0, ci); }
  const isCall = /^(bl|blr|call|callq|blraa|blrab)$/.test(mn), isBr = /^(b|b\..+|cb.+|tb.+|j.+|br|ret|retq|retab)$/.test(mn);
  let ops = esc(rest).replace(/\b(0x[0-9a-fA-F]+)\b/g, (x) => isCall || isBr ? `<span class="lk" data-jump="${x}">${x}</span>` : `<span class="im">${x}</span>`)
    .replace(/(#-?\d+)\b/g, '<span class="im">$1</span>').replace(/(%?\b(?:[xwqsdvh]\d{1,2}|sp|fp|lr|xzr|wzr|r[a-d]x|r[sd]i|r[sb]p|r\d{1,2}[dwb]?|e[a-d]x|e[sd]i|rip)\b)/g, '<span class="rg">$1</span>');
  let cm = esc(comment);
  if (comment) cm = cm.replace(/symbol stub for: (\S+)/, (_, n) => `symbol stub for: <span class="lk" data-jsym="${n}" title="${n}">${l.demangled ? esc(l.demangled) : n}</span>`);
  const target = l.target ? ` <span class="cm">; ${esc(l.target)}</span>` : "";
  return `<span class="m${isCall ? " call" : isBr ? " br" : ""}">${esc(mn)}</span> ${ops}${cm ? `<span class="cm">${cm}</span>` : ""}${target}`;
}

/* ---------- settings */
VIEWS.settings = tab => ({
  icon: "settings",
  async mount() {
    setTitle(tab, "Settings");
    const i = S.info = await api("sys", "info").catch(() => S.info);
    const theme = store.get("theme", "system");
    tab.el.innerHTML = `<div class="view-scroll"><div class="page narrow">
      <div class="hd"><div><h1>Settings</h1><div class="sub">Unwind ${esc(i.version || "")} · runs only on this Mac at 127.0.0.1</div></div></div>
      <div class="card"><h3>Appearance</h3><div class="seg" id="theme-seg">${["system", "dark", "light"].map(t => `<button data-t="${t}" class="${t === theme ? "on" : ""}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div></div>
      <div class="card"><h3>Etherscan API key <span class="pill ${i.settings?.etherscan_key_set ? "t-good" : "t-muted"}">${i.settings?.etherscan_key_set ? "set" : "not set"}</span></h3>
        <p class="muted" style="margin:0 0 10px;font-size:13px">Base, Arbitrum, Polygon, BNB Chain, Linea, Scroll, Gnosis, Sonic and ~10 more chains need one free key from etherscan.io (one key covers all of them). It's stored in <span class="mono">${esc(i.settings?.settings_path || "")}</span> with owner-only permissions and only sent to Etherscan.</p>
        <form id="key-form" style="display:flex;gap:8px"><input class="inp mono" type="password" name="k" placeholder="Paste your Etherscan API key" autocomplete="off" style="flex:1"><button class="btn primary">Save key</button></form></div>
      <div class="card"><h3>Connect your coding agent</h3><p class="muted" style="margin:0 0 10px;font-size:13px">The same tools (binaries, 40+ chains, forensics, vault) are available to Claude Code or any MCP client. Run this once in a terminal:</p>
        <pre class="mono" style="background:var(--bg-3);padding:10px 12px;border-radius:8px;overflow:auto;margin:0 0 8px;white-space:pre-wrap;overflow-wrap:anywhere">${esc(i.claude_code_command || "")}</pre><button class="btn sm" data-copy="${esc(i.claude_code_command || "")}">${ICONS.copy} Copy command</button>
        <p class="muted" style="margin:14px 0 6px;font-size:13px">Other MCP clients (Cursor, Claude Desktop…) use this JSON:</p>
        <pre class="mono" style="background:var(--bg-3);padding:10px 12px;border-radius:8px;overflow:auto;margin:0 0 8px">${esc(JSON.stringify(i.mcp_json || {}, null, 2))}</pre><button class="btn sm" data-copy="${esc(JSON.stringify(i.mcp_json || {}, null, 2))}">${ICONS.copy} Copy JSON</button>
        <p class="muted" style="margin:14px 0 6px;font-size:13px">Then ask it things like:</p>
        ${["Use unwind to trace where the money from bc1q… went, 3 hops, and save the case to my vault.", "Use unwind to open Calculator.app, find the code behind the % button and explain it.", "Use unwind to check whether 0x… has touched a mixer and which other chains it's active on.", "Use unwind to match amounts leaving bitcoin:bc1q… with arrivals at ethereum:0x… within 48 hours."].map(p => `<div class="ritem" data-copy="${esc(p)}" title="Click to copy"><div class="rc" style="-webkit-line-clamp:3">› ${esc(p)}</div></div>`).join("")}</div>
      <div class="card"><h3>Vault</h3><dl class="kv"><dt>Folder</dt><dd class="mono">${esc(i.vault || "")}</dd></dl><p class="muted" style="margin:8px 0 0;font-size:13px">Plain Markdown with [[wikilinks]]. You can open this folder in Obsidian as a vault. To use another folder, start Unwind with <span class="mono">UNWIND_VAULT=/path ./unwind</span>.</p></div>
      <div class="card"><h3>Chains <span class="muted">${S.chains.filter(c => c.available).length} of ${S.chains.length} ready</span></h3><div class="pills">${S.chains.map(c => `<span class="chain-chip" style="${c.available ? "" : "opacity:.45"}" title="${esc(c.family)}${c.needs_key ? " · needs Etherscan key" : ""}"><i style="background:${c.color}"></i>${esc(c.name)}</span>`).join("")}</div></div>
    </div></div>`;
    $("#theme-seg", tab.el).onclick = e => { const b = e.target.closest("[data-t]"); if (!b) return; setTheme(b.dataset.t); $$("#theme-seg button", tab.el).forEach(x => x.classList.toggle("on", x === b)); };
    $("#key-form", tab.el).onsubmit = async e => { e.preventDefault(); const k = e.target.k.value.trim(); if (!k) return; try { await api("chain", "save_settings", { etherscan_key: k }); toast("Key saved. More chains are now available."); await boot(true); tab.mount(); } catch (er) { toast(er.message, true); } };
  },
  right(el) { el.innerHTML = `<div class="rsec"><h4>Privacy</h4><div class="muted" style="font-size:12.5px">Lookups go straight from this Mac to public explorers (Blockstream, Blockscout, Routescan, Solana/Tron/XRP/TON public APIs, xmrchain, CoinGecko for prices). Nothing goes through a third-party server of ours. The local server only accepts requests that carry this page's token.</div></div>`; },
});

/* ---------------------------------------------------------------- boot */
async function boot(reloadOnly) {
  try {
    const [chains, flags, info] = await Promise.all([api("chain", "chains"), api("chain", "flag_info"), api("sys", "info")]);
    S.chains = chains; S.chainMap = Object.fromEntries(chains.map(c => [c.id, c])); S.flagInfo = flags; S.info = info;
  } catch (e) { toast(e.message, true, 8000); }
  if (reloadOnly) { renderStatus(); return; }
  const th = store.get("theme", "system"); if (th !== "system") document.documentElement.setAttribute("data-theme", th);
  applyLayout();
  await refreshTree();
  const saved = store.get("tabs", { list: [], active: 0 });
  if (saved.list?.length) { saved.list.forEach(t => { try { openTab(t.type, t.st, { newTab: true, forceNew: false }); } catch (e) { console.error(e); } }); const t = S.tabs[saved.active] || S.tabs[0]; if (t) activate(t.id); }
  else { const w = S.tree.files.find(f => f.name === "Welcome"); if (w) openNote(w.path, true); openTab("home", {}, { newTab: true }); }
}
boot();
