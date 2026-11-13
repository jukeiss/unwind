/* Unwind AI: assistant panel, "Explain with AI", and the Connections settings page. */
"use strict";

const AI = {
  msgs: store.get("ai.msgs", []),
  busy: false, info: null, provider: store.get("ai.provider", null), model: store.get("ai.model", ""),
  withContext: store.get("ai.ctx", true), el: null,
};
let rpane = store.get("rpane", "info");

/* ---------------------------------------------------------------- right sidebar with tabs */
renderRight = function () {
  const rb = $("#right-body");
  const t = cur();
  rb.innerHTML = "";
  const head = document.createElement("div");
  head.className = "rtabs";
  head.innerHTML = `<button data-rp="info" class="${rpane === "info" ? "on" : ""}">Details</button><button data-rp="ai" class="${rpane === "ai" ? "on" : ""}">✦ Assistant</button>`;
  head.onclick = e => { const b = e.target.closest("[data-rp]"); if (!b) return; rpane = b.dataset.rp; store.set("rpane", rpane); renderRight(); };
  rb.appendChild(head);
  if (rpane === "ai") { rb.appendChild(aiPanel()); scrollChat(); return; }
  const box = document.createElement("div");
  box.className = "rinner";
  rb.appendChild(box);
  if (t?.right) t.right(box); else box.innerHTML = `<div class="r-empty" style="padding:12px">Nothing to show for this tab.</div>`;
  if (t?.type === "note" && t.outline) t.outline(box);
};

function openAssistant(prefill, send) {
  layout.right = true; applyLayout();
  rpane = "ai"; store.set("rpane", rpane); renderRight();
  const ta = $("#ai-input");
  if (prefill != null && ta) { ta.value = prefill; ta.focus(); }
  if (send) aiSend();
}

/* ---------------------------------------------------------------- assistant panel */
function aiPanel() {
  if (AI.el) { aiRefreshHead(); aiRenderMsgs(); return AI.el; }
  const el = document.createElement("div");
  el.className = "ai";
  el.innerHTML = `
    <div class="ai-head"><select class="sel" id="ai-prov" title="AI provider"></select>
      <input class="inp mono" id="ai-model" placeholder="model" spellcheck="false" autocomplete="off" title="Model id (blank = the provider's default)">
      <button class="ib" id="ai-new" title="New chat">${ICONS.plus}</button><button class="ib" id="ai-save" title="Save chat to vault">${ICONS.save}</button></div>
    <div class="ai-msgs" id="ai-msgs"></div>
    <div class="ai-foot">
      <label class="chk" title="Send a short description of the tab you're looking at"><input type="checkbox" id="ai-ctx" ${AI.withContext ? "checked" : ""}> <span id="ai-ctx-label">Include what I'm looking at</span></label>
      <div class="ai-compose"><textarea class="inp" id="ai-input" rows="3" placeholder="Ask about this wallet, function, trace or note…  (Enter to send, Shift+Enter for a new line)"></textarea>
      <button class="btn primary" id="ai-send" title="Send">${ICONS.play}</button></div>
    </div>`;
  AI.el = el;
  $("#ai-prov", el).onchange = e => { AI.provider = e.target.value; store.set("ai.provider", AI.provider); const p = AI.info?.providers.find(x => x.id === AI.provider); $("#ai-model", el).value = AI.model = p?.model || ""; store.set("ai.model", AI.model); };
  $("#ai-model", el).oninput = e => { AI.model = e.target.value.trim(); store.set("ai.model", AI.model); };
  $("#ai-ctx", el).onchange = e => { AI.withContext = e.target.checked; store.set("ai.ctx", AI.withContext); };
  $("#ai-new", el).onclick = () => { AI.msgs = []; store.set("ai.msgs", []); aiRenderMsgs(); };
  $("#ai-save", el).onclick = aiSaveChat;
  $("#ai-send", el).onclick = () => aiSend();
  $("#ai-input", el).onkeydown = e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); aiSend(); } };
  $("#ai-msgs", el).addEventListener("click", e => {
    const q = e.target.closest("[data-aiq]"); if (q) { $("#ai-input").value = q.dataset.aiq; aiSend(); }
    const go = e.target.closest("[data-go-settings]"); if (go) openTab("settings");
  });
  aiLoadProviders();
  aiRenderMsgs();
  return el;
}
async function aiLoadProviders() {
  try { AI.info = await api("ai", "providers"); } catch (e) { AI.info = { providers: [] }; }
  aiRefreshHead(); aiRenderMsgs();
}
function aiRefreshHead() {
  if (!AI.el || !AI.info) return;
  const ready = AI.info.providers.filter(p => p.ready);
  if (!AI.provider || !AI.info.providers.some(p => p.id === AI.provider)) AI.provider = AI.info.default || ready[0]?.id || null;
  $("#ai-prov", AI.el).innerHTML = (ready.length ? ready : AI.info.providers.slice(0, 1)).map(p => `<option value="${p.id}" ${p.id === AI.provider ? "selected" : ""}>${esc(p.name)}</option>`).join("");
  const p = AI.info.providers.find(x => x.id === AI.provider);
  if (!AI.model && p) AI.model = p.model || "";
  $("#ai-model", AI.el).value = AI.model;
  $("#ai-ctx-label", AI.el).textContent = ctxLabel() || "Include what I'm looking at";
}
function ctxLabel() {
  const t = cur(); if (!t) return "";
  if (t.type === "binary" && t.current?.()?.path) { const c = t.current(); return `Include: ${c.name || "binary"}${c.fn ? " → " + (c.fn.display || c.fn.name) : ""}`; }
  if (t.type === "wallet") return `Include: wallet ${short(t.st.address)}`;
  if (t.type === "trace" && t.st.query) return `Include: trace of ${short(t.st.query)}`;
  if (t.type === "note") return `Include: note ${t.st.path.split("/").pop().replace(/\.md$/, "")}`;
  if (t.type === "tx") return `Include: tx ${short(t.st.hash)}`;
  if (t.type === "lab") return `Include: lab (${t.st.tool})`;
  return "";
}
async function contextFor(t) {
  if (!t) return null;
  const st = t.st || {};
  if (t.type === "binary" && t.current?.()?.path) {
    const c = t.current();
    return `Binary: ${c.path} (arch ${c.arch || "?"}).` + (c.fn ? ` Currently viewing function ${c.fn.display || c.fn.name} at ${c.fn.addr}. Use bin_brief with this path and address for its code.` : "");
  }
  if (t.type === "wallet") return `Wallet ${st.address} on chain ${st.chain || "auto"}. Use chain_wallet / chain_history / exposure tools for details.`;
  if (t.type === "trace") return `Trace from ${st.query} on ${st.chain || "auto"}, following money ${st.direction}, ${st.hops} hops.`;
  if (t.type === "tx") return `Transaction ${st.hash} on ${st.chain || "auto"}.`;
  if (t.type === "lab") return `Forensics lab tool "${st.tool}" with inputs ${JSON.stringify(st.inputs || {})}.`;
  if (t.type === "note") {
    try { const n = await api("vault", "read", { path: st.path }); return `Vault note "${st.path}":\n\n${n.content.slice(0, 6000)}`; } catch { return `Vault note ${st.path}`; }
  }
  return null;
}
function scrollChat() { const m = $("#ai-msgs"); if (m) m.scrollTop = m.scrollHeight; }
function aiRenderMsgs() {
  if (!AI.el) return;
  const box = $("#ai-msgs", AI.el);
  const noProv = AI.info && !AI.info.providers.some(p => p.ready);
  if (!AI.msgs.length) {
    box.innerHTML = `<div class="ai-empty">
      <div class="ai-glyph">✦</div><b>Your analyst</b>
      <p>Ask in plain language. It can read binaries, trace wallets, run forensics and write notes to your vault, using the same tools you have.</p>
      ${noProv ? `<button class="btn primary" data-go-settings>Connect an AI</button><p class="faint">Claude, DeepSeek, NanoGPT, GLM, OpenAI, Gemini, OpenRouter, Ollama and more.</p>` : `
      <div class="ai-sugg">${["What does this function do?", "Where did this wallet's money come from?", "Is this file malicious? Explain the evidence.", "Summarise this trace and save it to my vault."]
        .map(q => `<button data-aiq="${esc(q)}">${esc(q)}</button>`).join("")}</div>`}
    </div>`;
    return;
  }
  box.innerHTML = AI.msgs.map((m, i) => {
    if (m.role === "user") return `<div class="msg u">${esc(m.display || m.content).replace(/\n/g, "<br>")}</div>`;
    const steps = (m.steps || []).length ? `<details class="steps"><summary>${m.steps.length} tool call${m.steps.length > 1 ? "s" : ""}</summary>${m.steps.map(s => `<div class="step ${s.ok ? "" : "bad"}"><span class="mono">${esc(s.call)}</span>${s.preview ? `<div class="faint">${esc(s.preview.slice(0, 180))}</div>` : ""}</div>`).join("")}</details>` : "";
    return `<div class="msg a">${steps}<div class="reading md-s">${MD.render(m.content || "", { resolve: n => !!resolveName(n) })}</div>${m.meta ? `<div class="meta">${esc(m.meta)}</div>` : ""}</div>`;
  }).join("") + (AI.busy ? `<div class="msg a thinking"><span class="spin"></span> Working… <span class="faint">the model may call several tools</span></div>` : "");
}
async function aiSend(text, opts = {}) {
  const ta = $("#ai-input");
  const q = (text ?? ta?.value ?? "").trim();
  if (!q || AI.busy) return;
  if (ta) ta.value = "";
  AI.msgs.push({ role: "user", content: opts.full || q, display: q });
  AI.busy = true; aiRenderMsgs(); scrollChat();
  try {
    const ctx = opts.context !== undefined ? opts.context : (AI.withContext ? await contextFor(cur()) : null);
    const r = await api("ai", "chat", { messages: AI.msgs.map(m => ({ role: m.role, content: m.content })), provider: AI.provider, model: AI.model || null, context: ctx });
    AI.msgs.push({ role: "assistant", content: r.reply, steps: r.steps, meta: `${r.provider_name} · ${r.model || ""} · ${r.seconds}s` });
  } catch (e) {
    AI.msgs.push({ role: "assistant", content: `**Couldn't get an answer.** ${e.message}`, meta: "error" });
  }
  AI.busy = false; store.set("ai.msgs", AI.msgs.slice(-60)); aiRenderMsgs(); scrollChat();
  refreshTree();
}
async function aiSaveChat() {
  if (!AI.msgs.length) { toast("Nothing to save yet"); return; }
  const first = (AI.msgs.find(m => m.role === "user")?.display || "Chat").slice(0, 60);
  const body = `# ${first}\n\n` + AI.msgs.map(m => m.role === "user" ? `> **You:** ${(m.display || m.content).replace(/\n/g, "\n> ")}` : `${m.content}\n\n<small>${m.meta || ""}</small>`).join("\n\n") + "\n";
  try { const r = await api("vault", "create", { folder: "AI", title: `${new Date().toISOString().slice(0, 10)} ${first}`, content: "---\ntype: note\ntags:\n  - ai\n---\n" + body }); await refreshTree(); toast("Saved to " + r.path); }
  catch (e) { toast(e.message, true); }
}

/* ---------------------------------------------------------------- explain a function */
async function explainFunction(path, fn, arch) {
  if (!fn) return;
  openAssistant();
  toast("Collecting the function's code, strings and calls…");
  let b;
  try { b = await api("bin", "brief", { path, address: fn.addr, arch }); } catch (e) { toast(e.message, true); return; }
  const prompt = `Explain what the function ${b.function} (${b.addr}) in ${path.split("/").pop()} does. Give it a descriptive name, describe inputs/outputs if you can infer them, and point to the instructions, strings and calls that support each claim. Flag anything security-relevant.`;
  const full = `${prompt}\n\nArchitecture: ${b.arch}. ${b.instructions} instructions${b.truncated ? " (cut)" : ""}.\nStrings used: ${JSON.stringify(b.strings)}\nCalls: ${JSON.stringify(b.calls)}\nCalled from: ${JSON.stringify(b.called_from)}\n\nDisassembly:\n${b.asm}`;
  aiSend(prompt, { full, context: `Binary ${path}` });
}

/* ---------------------------------------------------------------- settings / connections */
VIEWS.settings = tab => ({
  icon: "settings",
  async mount() {
    setTitle(tab, "Settings");
    tab.el.innerHTML = `<div class="view-scroll"><div class="page narrow">${loading("Loading settings…")}</div></div>`;
    let i, ai, intel;
    try { [i, ai, intel] = await Promise.all([api("sys", "info"), api("ai", "providers"), api("mal", "intel_status")]); S.info = i; }
    catch (e) { $(".page", tab.el).innerHTML = errBox(e); return; }
    const theme = store.get("theme", "system");
    const row = p => `<div class="prow" data-p="${p.id}">
      <div class="pname"><b>${esc(p.name)}</b>${p.local ? ` <span class="pill plain">local</span>` : ""}${ai.default === p.id ? ` <span class="pill t-accent">default</span>` : ""}${p.ready ? ` <span class="pill t-good">ready</span>` : ""}
        <div class="faint">${p.id === "custom" || p.local ? `<input class="inp mono" data-f="base_url" value="${esc(p.base_url || "")}" placeholder="https://host/v1">` : `<span class="mono">${esc(p.base_url.replace(/^https?:\/\//, ""))}</span>`}${p.key_url ? ` · <a href="${esc(p.key_url)}" target="_blank" rel="noopener noreferrer">get a key</a>` : ""}</div></div>
      ${p.local ? `<div class="muted" style="font-size:12.5px">No key needed. Start the app, then press Models.</div>` : `<input class="inp mono" type="password" data-f="key" placeholder="${p.key_set ? "•••••• saved (paste to replace)" : "Paste API key"}" autocomplete="off">`}
      <input class="inp mono" data-f="model" value="${esc(p.model || "")}" placeholder="model id" list="ml-${p.id}"><datalist id="ml-${p.id}"></datalist>
      <div class="pacts"><button class="btn sm" data-a="save">Save</button><button class="btn sm ghost" data-a="models" title="List the models your key can use">Models</button><button class="btn sm ghost" data-a="test">Test</button><button class="btn sm ghost" data-a="default" title="Make this the default">★</button></div>
      <div class="pout faint" data-out></div></div>`;
    $(".page", tab.el).innerHTML = `
      <div class="hd"><div><h1>Settings</h1><div class="sub">Unwind ${esc(i.version || "")} · everything runs on this Mac at 127.0.0.1 · keys are stored in <span class="mono">${esc(i.settings?.settings_path || "~/.config/unwind/settings.json")}</span> (owner-only) and only sent to the service they belong to</div></div></div>
      <div class="card"><h3>Appearance</h3><div class="seg" id="theme-seg">${["system", "dark", "light"].map(t => `<button data-t="${t}" class="${t === theme ? "on" : ""}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div></div>

      <div class="card"><h3>AI models ✦</h3><p class="muted" style="margin:0 0 10px;font-size:13px">Connect any of these and use it from the Assistant panel (⌘J). Claude uses Anthropic's official SDK; the others use the OpenAI-compatible API. Models that support tool calling can use Unwind's analysis tools on their own.${ai.sdk_ok ? "" : " <b>Claude SDK not installed.</b>"}</p>
        <div class="plist">${ai.providers.map(row).join("")}</div></div>

      <div class="card"><h3>Blockchain data</h3>
        <div class="field" style="margin-bottom:10px"><label>Etherscan API key <span class="pill ${i.settings?.etherscan_key_set ? "t-good" : "t-muted"}">${i.settings?.etherscan_key_set ? "set" : "not set"}</span></label>
          <div style="display:flex;gap:8px"><input class="inp mono" type="password" id="k-eth" placeholder="Unlocks Base, Arbitrum, Polygon, BNB, Linea, Scroll, Gnosis, Sonic and ~10 more" style="flex:1"><button class="btn" data-save="eth">Save</button></div>
          <span class="faint" style="font-size:12px">Free at <a href="https://etherscan.io/myapikey" target="_blank" rel="noopener noreferrer">etherscan.io/myapikey</a>. One key covers all Etherscan chains.</span></div>
        <div class="field"><label>Solana RPC URL <span class="pill ${i.settings?.solana_rpc_set ? "t-good" : "t-muted"}">${i.settings?.solana_rpc_set ? "set" : "public (slow)"}</span></label>
          <div style="display:flex;gap:8px"><input class="inp mono" type="password" id="k-sol" placeholder="https://mainnet.helius-rpc.com/?api-key=…" style="flex:1"><button class="btn" data-save="sol">Save</button></div>
          <span class="faint" style="font-size:12px">The public Solana endpoint rate-limits heavily. A free Helius or QuickNode URL makes Solana traces fast.</span></div></div>

      <div class="card"><h3>Malware intelligence</h3><p class="muted" style="margin:0 0 10px;font-size:13px">Optional. Only a file's SHA-256 hash is sent, never the file. YARA: ${intel.yara ? `<span class="pill t-good">installed</span>` : `<span class="pill t-muted">not installed</span> <span class="mono">brew install yara</span>`}. Your rules live in the vault's <span class="mono">YARA/</span> folder.</p>
        <div class="field" style="margin-bottom:10px"><label>VirusTotal API key <span class="pill ${intel.virustotal ? "t-good" : "t-muted"}">${intel.virustotal ? "set" : "not set"}</span></label><div style="display:flex;gap:8px"><input class="inp mono" type="password" id="k-vt" style="flex:1" placeholder="from virustotal.com → API key"><button class="btn" data-save="vt">Save</button></div></div>
        <div class="field"><label>MalwareBazaar API key <span class="pill ${intel.malwarebazaar ? "t-good" : "t-muted"}">${intel.malwarebazaar ? "set" : "not set"}</span></label><div style="display:flex;gap:8px"><input class="inp mono" type="password" id="k-mb" style="flex:1" placeholder="from bazaar.abuse.ch → Auth-Key"><button class="btn" data-save="mb">Save</button></div></div></div>

      <div class="card"><h3>Use Unwind from your coding agent</h3><p class="muted" style="margin:0 0 10px;font-size:13px">The same ${"35"} tools work in Claude Code, Cursor, Claude Desktop or any MCP client. Run once:</p>
        <pre class="mono codebox">${esc(i.claude_code_command || "")}</pre><button class="btn sm" data-copy="${esc(i.claude_code_command || "")}">${ICONS.copy} Copy command</button>
        <p class="muted" style="margin:14px 0 6px;font-size:13px">JSON for other MCP clients:</p>
        <pre class="mono codebox">${esc(JSON.stringify(i.mcp_json || {}, null, 2))}</pre><button class="btn sm" data-copy="${esc(JSON.stringify(i.mcp_json || {}, null, 2))}">${ICONS.copy} Copy JSON</button></div>

      <div class="card"><h3>Vault</h3><dl class="kv"><dt>Folder</dt><dd class="mono">${esc(i.vault || "")}</dd></dl><p class="muted" style="margin:8px 0 0;font-size:13px">Plain Markdown with [[wikilinks]]; opens in Obsidian too. Use another folder with <span class="mono">UNWIND_VAULT=/path ./unwind</span>.</p></div>
      <div class="card"><h3>Chains <span class="muted">${S.chains.filter(c => c.available).length} of ${S.chains.length} ready</span></h3><div class="pills">${S.chains.map(c => `<span class="chain-chip" style="${c.available ? "" : "opacity:.45"}" title="${esc(c.family)}${c.needs_key ? " · needs Etherscan key" : ""}"><i style="background:${c.color}"></i>${esc(c.name)}</span>`).join("")}</div></div>`;
    const pg = $(".page", tab.el);
    $("#theme-seg", pg).onclick = e => { const b = e.target.closest("[data-t]"); if (!b) return; setTheme(b.dataset.t); $$("#theme-seg button", pg).forEach(x => x.classList.toggle("on", x === b)); };
    pg.addEventListener("click", async e => {
      const sv = e.target.closest("[data-save]");
      if (sv) {
        const k = sv.dataset.save, val = { eth: $("#k-eth"), sol: $("#k-sol"), vt: $("#k-vt"), mb: $("#k-mb") }[k].value.trim();
        if (!val) { toast("Paste a value first", true); return; }
        try {
          if (k === "eth") await api("chain", "save_settings", { etherscan_key: val });
          if (k === "sol") await api("chain", "save_settings", { solana_rpc: val });
          if (k === "vt") await api("mal", "save_intel", { virustotal: val });
          if (k === "mb") await api("mal", "save_intel", { malwarebazaar: val });
          toast("Saved"); await boot(true); tab.mount();
        } catch (er) { toast(er.message, true); }
        return;
      }
      const a = e.target.closest("[data-a]"); if (!a) return;
      const tr = a.closest(".prow"), id = tr.dataset.p, out = $("[data-out]", tr);
      const f = n => $(`[data-f="${n}"]`, tr)?.value.trim();
      try {
        if (a.dataset.a === "save" || a.dataset.a === "default") {
          await api("ai", "save_provider", { id, key: f("key") || null, model: f("model") ?? null, base_url: f("base_url") ?? null, make_default: a.dataset.a === "default" });
          out.textContent = "Saved."; AI.info = null; AI.el = null; if (a.dataset.a === "default") { AI.provider = id; AI.model = f("model") || ""; store.set("ai.provider", id); store.set("ai.model", AI.model); tab.mount(); }
        }
        if (a.dataset.a === "models") {
          if (f("key")) await api("ai", "save_provider", { id, key: f("key"), base_url: f("base_url") ?? null });
          out.textContent = "Asking…"; const ms = await api("ai", "models", { id });
          $(`#ml-${id}`).innerHTML = ms.map(m => `<option value="${esc(m)}">`).join(""); out.textContent = `${ms.length} models. Click the model box to pick one.`;
        }
        if (a.dataset.a === "test") {
          await api("ai", "save_provider", { id, key: f("key") || null, model: f("model") ?? null, base_url: f("base_url") ?? null });
          out.textContent = "Testing…"; const r = await api("ai", "test", { id, model: f("model") || null });
          out.innerHTML = `<span class="pos">Works</span>: “${esc(r.reply)}” (${esc(r.model || "")}, ${r.seconds}s)`;
        }
      } catch (er) { out.innerHTML = `<span class="neg">${esc(er.message)}</span>`; }
    });
  },
  right(el) { el.innerHTML = `<div class="rsec"><h4>Privacy</h4><div class="muted" style="font-size:12.5px">Chain lookups go straight from this Mac to public explorers. AI chats go only to the provider you pick, including the context checkbox's description of your current tab. Malware lookups send only hashes. The local server only accepts requests carrying this page's token.</div></div>`; },
});

/* ---------------------------------------------------------------- shortcuts & commands */
document.addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") { e.preventDefault(); if (layout.right && rpane === "ai") { rpane = "info"; store.set("rpane", rpane); renderRight(); } else openAssistant(); }
});
$("#rb-ai").onclick = () => openAssistant();
COMMANDS.unshift({ label: "Ask the AI assistant", kbd: "⌘J", icon: "lab", run: () => openAssistant() });
COMMANDS.push({ label: "Connect an AI model (Claude, DeepSeek, NanoGPT, GLM…)", icon: "settings", run: () => openTab("settings") });
