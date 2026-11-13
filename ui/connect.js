/* Import / export keys, custom API connectors, and the first-run setup checklist. */
"use strict";

function download(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* ---------------------------------------------------------------- settings: keys + connectors */
(() => {
  const base = VIEWS.settings;
  VIEWS.settings = tab => {
    const v = base(tab);
    const mount = v.mount;
    v.mount = async (...a) => { await mount.apply(v, a); await injectSettings(tab); };
    return v;
  };
})();

async function injectSettings(tab) {
  const page = $(".page", tab.el); if (!page) return;
  let ks, cs;
  try { [ks, cs] = await Promise.all([api("keys", "status"), api("conn", "list")]); } catch (e) { return; }
  const keyCard = document.createElement("div");
  keyCard.className = "card"; keyCard.id = "keys-card";
  const groups = ["AI", "Data"];
  keyCard.innerHTML = `<h3>Import your API keys</h3>
    <p class="muted" style="margin:0 0 10px;font-size:13px">Paste a <span class="mono">.env</span> file, shell exports, a JSON object or bare keys, or drop a file here. Unwind recognises names like <span class="mono">DEEPSEEK_API_KEY</span>, <span class="mono">NANOGPT_API_KEY</span>, <span class="mono">GLM_API_KEY</span>, <span class="mono">ETHERSCAN_API_KEY</span>, <span class="mono">HELIUS_API_KEY</span>, <span class="mono">VIRUSTOTAL_API_KEY</span>, and keys that start with <span class="mono">sk-ant-</span>, <span class="mono">sk-or-</span>, <span class="mono">gsk_</span>, <span class="mono">AIza</span>…</p>
    <div class="dropzone" id="kdrop"><textarea class="inp mono" id="kpaste" rows="5" spellcheck="false" placeholder="DEEPSEEK_API_KEY=sk-...&#10;ETHERSCAN_API_KEY=...&#10;HELIUS_API_KEY=...&#10;&#10;or drop a .env / .json file here"></textarea></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;align-items:center"><button class="btn primary" id="kimport">Import keys</button><label class="btn ghost" style="cursor:pointer">Choose file…<input type="file" id="kfile" accept=".env,.txt,.json,text/plain,application/json" hidden></label>
      <span class="grow"></span><button class="btn sm ghost" id="kexport" title="Values masked, safe to share">Export .env (masked)</button><button class="btn sm ghost" id="kexport2" title="Real values: keep this file private">Export with secrets</button></div>
    <div id="kresult" style="margin-top:8px"></div>
    <div class="kgrid">${groups.map(g => `<div><div class="lbl" style="margin:12px 0 6px">${g === "AI" ? "AI models" : "Data & intelligence"}</div>${ks.keys.filter(k => k.group === g).map(k => `<div class="krow"><span class="kdot ${k.set ? "on" : ""}"></span><span>${esc(k.service)}</span><span class="mono faint">${esc(k.env)}</span><span class="faint">${k.set ? esc(k.source) : ""}</span></div>`).join("")}</div>`).join("")}</div>`;
  const connCard = document.createElement("div");
  connCard.className = "card"; connCard.id = "conn-card";
  connCard.innerHTML = connHtml(cs.connectors);
  const aiCard = $$(".card", page).find(c => /AI models/.test(c.querySelector("h3")?.textContent || ""));
  page.insertBefore(keyCard, aiCard || page.children[2]);
  (aiCard ? aiCard.nextSibling : null) ? page.insertBefore(connCard, aiCard.nextSibling) : page.appendChild(connCard);

  const doImport = async text => {
    const out = $("#kresult");
    if (!text.trim()) { toast("Paste some keys first", true); return; }
    try {
      const r = await api("keys", "import", { text });
      out.innerHTML = r.imported.length ? `<div class="callout good"><div><b>Imported ${r.imported.length}</b>: ${r.imported.map(x => `${esc(x.service)} <span class="mono faint">${esc(x.value)}</span>`).join(", ")}${r.unknown.length ? `<div class="faint" style="font-size:12px">Not recognised: ${r.unknown.map(esc).join(", ")}</div>` : ""}</div></div>`
        : `<div class="callout warn">${esc(r.note || "No keys recognised.")}${r.unknown.length ? ` Not recognised: ${r.unknown.map(esc).join(", ")}` : ""}</div>`;
      $("#kpaste").value = "";
      if (r.imported.length) { AI.info = null; AI.el = null; await boot(true); setTimeout(() => tab.mount(), 1200); }
    } catch (e) { out.innerHTML = errBox(e); }
  };
  $("#kimport").onclick = () => doImport($("#kpaste").value);
  $("#kfile").onchange = async e => { const f = e.target.files[0]; if (f) doImport(await f.text()); };
  const dz = $("#kdrop");
  dz.ondragover = e => { e.preventDefault(); dz.classList.add("over"); };
  dz.ondragleave = () => dz.classList.remove("over");
  dz.ondrop = async e => { e.preventDefault(); dz.classList.remove("over"); const f = e.dataTransfer.files[0]; if (f) doImport(await f.text()); };
  $("#kexport").onclick = async () => { const r = await api("keys", "export", { include_secrets: false }); download("unwind-keys.masked.env", r.text); };
  $("#kexport2").onclick = async () => {
    if (!(await confirmInline("Download a file with your real API keys? Keep it private.", "Download"))) return;
    const r = await api("keys", "export", { include_secrets: true }); download("unwind-keys.env", r.text);
  };
  wireConnectors(connCard, tab);
}

/* ---------------------------------------------------------------- connectors */
function connHtml(list) {
  return `<h3>Your own APIs <span class="muted">${list.length}</span></h3>
    <p class="muted" style="margin:0 0 10px;font-size:13px">Plug in any REST API (a block explorer, a threat-intel feed, your company's API…). Its endpoints become a tool the AI can call, and you can try them here. Read-only by default: only GET calls run unless you allow changes.</p>
    ${list.length ? `<div class="plist">${list.map(c => `<div class="crow" data-c="${esc(c.id)}">
      <div class="pname"><b>${esc(c.name)}</b> ${c.allow_writes ? `<span class="pill t-warn">changes allowed</span>` : `<span class="pill t-good">read-only</span>`} ${c.auth.type !== "none" ? `<span class="pill ${c.auth.value_set ? "t-good" : "t-warn"}">${c.auth.value_set ? "key set" : "needs key"}</span>` : ""}
        <div class="faint mono">${esc(c.base_url)} · ${c.endpoints.length} endpoints · AI tool <b>api_${esc(c.id)}</b></div></div>
      <div class="pacts"><button class="btn sm ghost" data-ca="eps">Endpoints</button><button class="btn sm ghost" data-ca="test">Test</button><button class="btn sm ghost" data-ca="edit">Edit</button><button class="btn sm ghost" data-ca="del">Remove</button></div>
      <div class="cbody" hidden></div></div>`).join("")}</div>` : `<div class="faint" style="margin-bottom:8px">No APIs connected yet.</div>`}
    <details class="cadd" style="margin-top:12px" ${list.length ? "" : "open"}><summary class="btn sm">+ Connect an API</summary>
      <div class="seg" id="cmode" style="margin:10px 0"><button data-m="openapi" class="on">Import OpenAPI / Swagger</button><button data-m="manual">Enter by hand</button></div>
      <form id="cform" class="cform">
        <div class="field"><label>Name</label><input class="inp" name="name" placeholder="e.g. Arkham, Chainabuse, my-api" required></div>
        <div class="field m-openapi"><label>Spec URL <span class="faint">(or paste the JSON below)</span></label><input class="inp mono" name="spec_url" placeholder="https://api.example.com/openapi.json"></div>
        <div class="field m-openapi"><label>Spec JSON</label><textarea class="inp mono" name="spec_text" rows="3" placeholder='{"openapi": "3.0.0", ...}'></textarea></div>
        <div class="field"><label>Base URL <span class="faint m-openapi">(optional: taken from the spec)</span></label><input class="inp mono" name="base_url" placeholder="https://api.example.com/v1"></div>
        <div class="field m-manual" hidden><label>Endpoints <span class="faint">one per line: METHOD /path/{param}?query1,query2 description</span></label><textarea class="inp mono" name="eps" rows="4" placeholder="GET /address/{address}?chain Look up an address&#10;GET /search?q,limit Search entities"></textarea></div>
        <div class="field m-manual" hidden><label>Description <span class="faint">(tells the AI what this API is for)</span></label><input class="inp" name="description" placeholder="Entity labels for crypto addresses"></div>
        <div class="cauth"><div class="field"><label>Auth</label><select class="sel" name="auth_type"><option value="">from spec / none</option><option value="none">none</option><option value="bearer">Bearer token</option><option value="header">Header</option><option value="query">Query parameter</option></select></div>
          <div class="field"><label>Header / param name</label><input class="inp mono" name="auth_name" placeholder="X-API-Key"></div>
          <div class="field" style="flex:1"><label>Key</label><input class="inp mono" type="password" name="auth_value" autocomplete="off" placeholder="paste your key (stored privately)"></div></div>
        <label class="chk"><input type="checkbox" name="allow_writes"> Allow changes (POST/PUT/PATCH/DELETE). Leave off unless you need it.</label>
        <div style="display:flex;gap:8px;align-items:center"><button class="btn primary" type="submit">Connect</button><span class="faint" id="cmsg"></span></div>
      </form></details>`;
}

function parseManual(text) {
  return text.split("\n").map(l => l.trim()).filter(Boolean).map(l => {
    const m = l.match(/^(GET|POST|PUT|PATCH|DELETE|HEAD)\s+(\S+)\s*(.*)$/i); if (!m) return null;
    const [p, q] = m[2].split("?");
    const params = [...p.matchAll(/\{([^}]+)\}/g)].map(x => ({ name: x[1], in: "path", required: true }))
      .concat((q || "").split(",").filter(Boolean).map(n => ({ name: n.trim(), in: "query", required: false })));
    if (!/^(GET|HEAD)$/i.test(m[1])) params.push({ name: "body", in: "body", required: false, type: "object" });
    return { method: m[1].toUpperCase(), path: p, summary: m[3], params, id: `${m[1]}_${p}` };
  }).filter(Boolean);
}

function wireConnectors(card, tab) {
  let mode = "openapi";
  const form = $("#cform", card);
  const setMode = m => { mode = m; $$("#cmode button", card).forEach(b => b.classList.toggle("on", b.dataset.m === m)); $$(".m-openapi", card).forEach(x => x.hidden = m !== "openapi"); $$(".m-manual", card).forEach(x => x.hidden = m !== "manual"); };
  $("#cmode", card).onclick = e => { const b = e.target.closest("[data-m]"); if (b) setMode(b.dataset.m); };
  form.onsubmit = async e => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(form)); const msg = $("#cmsg", card); msg.textContent = "Connecting…";
    try {
      let r;
      if (mode === "openapi") r = await api("conn", "import_openapi", { name: f.name, spec_url: f.spec_url || null, spec_text: f.spec_text || null, base_url: f.base_url || null, auth_type: f.auth_type || null, auth_name: f.auth_name || null, auth_value: f.auth_value || null, allow_writes: !!f.allow_writes });
      else {
        const endpoints = parseManual(f.eps || "");
        if (!endpoints.length) throw new Error("Add at least one endpoint line, like: GET /address/{address} Look up an address");
        r = await api("conn", "save", { name: f.name, base_url: f.base_url, description: f.description, auth_type: f.auth_type || "none", auth_name: f.auth_name, auth_value: f.auth_value || null, allow_writes: !!f.allow_writes, endpoints });
      }
      toast(`Connected ${r.name}: ${r.endpoints.length} endpoints${r.truncated ? " (first 80)" : ""}. The AI can use it as api_${r.id}.`);
      AI.el = null; tab.mount();
    } catch (er) { msg.innerHTML = `<span class="neg">${esc(er.message)}</span>`; }
  };
  card.addEventListener("click", async e => {
    const a = e.target.closest("[data-ca]"); if (!a) return;
    const row = a.closest("[data-c]"), id = row.dataset.c, body = $(".cbody", row);
    const all = (await api("conn", "list")).connectors; const c = all.find(x => x.id === id);
    if (a.dataset.ca === "del") { if (await confirmInline(`Remove the ${c.name} connector and its saved key?`, "Remove")) { await api("conn", "delete", { id }); tab.mount(); } return; }
    if (a.dataset.ca === "test") { body.hidden = false; body.innerHTML = loading("Calling…"); try { const r = await api("conn", "test", { id }); body.innerHTML = r.ok === null ? `<div class="muted">${esc(r.note)}</div>` : `<div class="callout ${r.ok ? "good" : "warn"}"><div><b>${r.ok ? "Works" : "Got HTTP " + r.status}</b> calling <span class="mono">${esc(r.endpoint)}</span><div class="mono faint" style="font-size:11.5px">${esc(r.preview)}</div></div></div>`; } catch (er) { body.innerHTML = errBox(er); } return; }
    if (a.dataset.ca === "edit") {
      const val = await promptInline(`New key for ${c.name} (leave blank to keep the current one)`, "");
      if (val === null) return;
      await api("conn", "save", { name: c.name, base_url: c.base_url, description: c.description, auth_type: c.auth.type === "none" && val ? "bearer" : c.auth.type, auth_name: c.auth.name, auth_value: val || null, allow_writes: c.allow_writes, endpoints: c.endpoints });
      toast("Saved"); tab.mount(); return;
    }
    if (a.dataset.ca === "eps") {
      if (!body.hidden && body.dataset.v === "eps") { body.hidden = true; return; }
      body.hidden = false; body.dataset.v = "eps";
      body.innerHTML = `<div class="tbl-wrap" style="margin-top:8px"><table class="tbl"><tbody>${c.endpoints.map(ep => `<tr><td class="nw"><span class="pill ${/GET|HEAD/.test(ep.method) ? "t-info" : "t-warn"}">${ep.method}</span></td><td class="mono" style="font-size:12px">${esc(ep.path)}<div class="faint" style="font-family:var(--font)">${esc(ep.summary || "")}</div></td><td class="mono faint" style="font-size:11.5px">${ep.params.map(p => esc(p.name) + (p.required ? "*" : "")).join(", ")}</td><td><button class="btn sm ghost" data-try="${esc(ep.id)}">Try</button></td></tr>`).join("")}</tbody></table></div><div class="tryout"></div>`;
      body.onclick = async ev => {
        const t = ev.target.closest("[data-try]"); if (!t) return;
        const ep = c.endpoints.find(x => x.id === t.dataset.try);
        const tmpl = Object.fromEntries(ep.params.filter(p => p.in !== "body").map(p => [p.name, ""]));
        const raw = await promptInline(`Parameters for ${ep.id} as JSON`, JSON.stringify(tmpl));
        if (raw === null) return;
        let params; try { params = JSON.parse(raw || "{}"); Object.keys(params).forEach(k => params[k] === "" && delete params[k]); } catch { toast("That isn't valid JSON", true); return; }
        const out = $(".tryout", body); out.innerHTML = loading("Calling…");
        try { const r = await api("conn", "call", { connector: id, endpoint: ep.id, params }); out.innerHTML = `<div class="faint mono" style="font-size:11.5px;margin-top:8px">HTTP ${r.status} · ${esc(r.url)}</div><pre class="mono codebox" style="max-height:320px">${esc(typeof r.result === "string" ? r.result : JSON.stringify(r.result, null, 2)).slice(0, 20000)}</pre>`; }
        catch (er) { out.innerHTML = errBox(er); }
      };
    }
  });
}

/* ---------------------------------------------------------------- home: setup checklist */
(() => {
  const base = VIEWS.home;
  VIEWS.home = tab => {
    const v = base(tab);
    const mount = v.mount;
    v.mount = (...a) => { mount.apply(v, a); setupChecklist(tab); };
    return v;
  };
})();
async function setupChecklist(tab) {
  let ks, prov, intel;
  try { [ks, prov, intel] = await Promise.all([api("keys", "status"), api("ai", "providers"), api("mal", "intel_status")]); } catch { return; }
  const k = Object.fromEntries(ks.keys.map(x => [x.id, x.set]));
  const items = [
    ["An AI model connected", prov.providers.some(p => p.ready), "Claude, DeepSeek, NanoGPT, GLM, OpenAI, Ollama…"],
    ["Etherscan key", k.etherscan, "unlocks Base, Arbitrum, Polygon, BNB and ~15 more chains"],
    ["Fast Solana (Helius or other RPC)", k.solana_rpc || k.helius, "the public endpoint is slow"],
    ["VirusTotal / MalwareBazaar", k.virustotal || k.malwarebazaar, "hash-only reputation for malware triage"],
    ["YARA installed", intel.yara, "brew install yara"],
  ];
  const done = items.filter(i => i[1]).length;
  if (done === items.length) return;
  const card = document.createElement("div");
  card.className = "card setup";
  card.innerHTML = `<div style="display:flex;align-items:center;gap:10px"><h3 style="margin:0">Set up Unwind <span class="muted">${done}/${items.length}</span></h3><span class="grow"></span><button class="btn sm primary" id="go-keys">Import keys</button><button class="btn sm ghost" id="go-set">Settings</button></div>
    <div class="steps-list">${items.map(([t, ok, hint]) => `<div class="krow"><span class="kdot ${ok ? "on" : ""}"></span><span>${esc(t)}</span><span class="faint">${ok ? "done" : esc(hint)}</span></div>`).join("")}</div>
    <div class="faint" style="font-size:12px;margin-top:6px">Everything works without keys. These make it faster and unlock more.</div>`;
  const page = $(".page", tab.el); if (!page) return;
  page.insertBefore(card, page.children[3] || null);
  $("#go-set", card).onclick = () => openTab("settings");
  $("#go-keys", card).onclick = () => { const t = openTab("settings"); setTimeout(() => $("#kpaste")?.focus(), 900); };
}

COMMANDS.push(
  { label: "Import API keys (.env, JSON or pasted keys)", icon: "settings", run: () => { openTab("settings"); setTimeout(() => $("#kpaste")?.focus(), 900); } },
  { label: "Connect your own API (OpenAPI / REST)", icon: "settings", run: () => { openTab("settings"); setTimeout(() => { const d = $(".cadd"); if (d) { d.open = true; d.scrollIntoView({ block: "center" }); } }, 900); } },
);
