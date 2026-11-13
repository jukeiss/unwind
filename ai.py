"""
ai - connect almost any AI model to Unwind, and let it use Unwind's tools.

Providers
  Claude (Anthropic)       official `anthropic` SDK (installed in ./.deps)
  everything else          OpenAI-compatible /chat/completions over HTTP:
                           OpenAI, DeepSeek, NanoGPT, Zhipu GLM / Z.ai, OpenRouter, Google Gemini,
                           Groq, Mistral, xAI, Moonshot (Kimi), Qwen (DashScope), Together,
                           Fireworks, Perplexity, Cerebras, SiliconFlow, Ollama, LM Studio, custom

Keys live in ~/.config/unwind/settings.json (permissions 600) and are only sent
to the provider you picked. The UI never receives a key back, only "set".

The assistant runs an agent loop: the model may call Unwind's read-only analysis
tools (binaries, chains, forensics, vault) and write notes to your vault.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEPS = os.path.join(HERE, ".deps")
if os.path.isdir(DEPS) and DEPS not in sys.path:
    sys.path.insert(0, DEPS)

import chaintrace as ct  # noqa: E402

MAX_STEPS = 12
TOOL_OUTPUT_LIMIT = 14_000

# id, name, kind, base_url, suggested model, where to get a key
PROVIDERS = [
    ("anthropic", "Claude (Anthropic)", "anthropic", "https://api.anthropic.com", "claude-opus-5-5",
     "https://platform.claude.com/settings/keys"),
    ("openai", "OpenAI", "openai", "https://api.openai.com/v1", "", "https://platform.openai.com/api-keys"),
    ("deepseek", "DeepSeek", "openai", "https://api.deepseek.com/v1", "deepseek-chat", "https://platform.deepseek.com/api_keys"),
    ("nanogpt", "NanoGPT", "openai", "https://nano-gpt.com/api/v1", "", "https://nano-gpt.com/api"),
    ("zhipu", "GLM (Zhipu, China)", "openai", "https://open.bigmodel.cn/api/paas/v4", "glm-4.6", "https://open.bigmodel.cn/usercenter/apikeys"),
    ("zai", "GLM (Z.ai, international)", "openai", "https://api.z.ai/api/paas/v4", "glm-4.6", "https://z.ai/manage-apikey/apikey-list"),
    ("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1", "openrouter/auto", "https://openrouter.ai/keys"),
    ("gemini", "Google Gemini", "openai", "https://generativelanguage.googleapis.com/v1beta/openai", "", "https://aistudio.google.com/apikey"),
    ("groq", "Groq", "openai", "https://api.groq.com/openai/v1", "", "https://console.groq.com/keys"),
    ("mistral", "Mistral", "openai", "https://api.mistral.ai/v1", "mistral-large-latest", "https://console.mistral.ai/api-keys"),
    ("xai", "xAI (Grok)", "openai", "https://api.x.ai/v1", "", "https://console.x.ai"),
    ("moonshot", "Moonshot (Kimi)", "openai", "https://api.moonshot.ai/v1", "", "https://platform.moonshot.ai/console/api-keys"),
    ("qwen", "Qwen (Alibaba DashScope)", "openai", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "qwen-plus",
     "https://modelstudio.console.alibabacloud.com"),
    ("together", "Together AI", "openai", "https://api.together.xyz/v1", "", "https://api.together.ai/settings/api-keys"),
    ("fireworks", "Fireworks", "openai", "https://api.fireworks.ai/inference/v1", "", "https://fireworks.ai/account/api-keys"),
    ("perplexity", "Perplexity", "openai", "https://api.perplexity.ai", "sonar", "https://www.perplexity.ai/settings/api"),
    ("cerebras", "Cerebras", "openai", "https://api.cerebras.ai/v1", "", "https://cloud.cerebras.ai"),
    ("siliconflow", "SiliconFlow", "openai", "https://api.siliconflow.cn/v1", "", "https://cloud.siliconflow.cn/account/ak"),
    ("ollama", "Ollama (local)", "openai", "http://localhost:11434/v1", "", None),
    ("lmstudio", "LM Studio (local)", "openai", "http://localhost:1234/v1", "", None),
    ("custom", "Custom (OpenAI-compatible)", "openai", "", "", None),
]
PMAP = {p[0]: p for p in PROVIDERS}
LOCAL = {"ollama", "lmstudio"}

SYSTEM = """You are the analyst inside Unwind, a local workbench for following money on blockchains and reverse engineering programs.

You can call tools that read binaries (summary, functions, strings, disassembly, cross-references, imports, capabilities, bundle info), look up wallets and transactions on 40+ chains, trace funds, run forensics (change detection, peel chains, clustering, CoinJoin and mixer exposure, same-key links, amount matching), read wallet histories as actions, and search, read and write notes in the user's vault.

How to work:
- Use the tools to check facts instead of guessing. Chain several calls when needed.
- Be explicit about certainty. "Certain" only for cryptographic facts (same key, on-chain records). Label everything else as a lead and say which signal it rests on. Never invent names or entity labels for addresses; only repeat labels that a tool returned.
- Cite transaction hashes, addresses and function addresses so the user can click through.
- For reverse engineering: explain what code does in plain language, name functions by behaviour, and point to the strings, imports and call sites that support each claim. Help with understanding, interoperability, debugging and security research; do not produce patches or steps whose purpose is defeating license checks, DRM or other copy protection.
- Keep answers tight: findings first, then evidence. Use Markdown. When the user asks you to save something, write it to the vault with [[wikilinks]] to addresses and notes."""


# ------------------------------------------------------------------ settings

def _ai_settings():
    return ct.settings().get("ai") or {}


def _save_ai(d):
    s = ct.settings()
    s["ai"] = d
    os.makedirs(os.path.dirname(ct.SETTINGS_PATH), exist_ok=True)
    with open(ct.SETTINGS_PATH, "w") as f:
        json.dump(s, f, indent=2)
    os.chmod(ct.SETTINGS_PATH, 0o600)


def _cfg(pid):
    if pid not in PMAP:
        raise ValueError(f"unknown provider '{pid}'")
    p = PMAP[pid]
    c = (_ai_settings().get("providers") or {}).get(pid) or {}
    import keys
    return {"id": pid, "name": p[1], "kind": p[2],
            "base_url": (c.get("base_url") or p[3]).rstrip("/"),
            "model": c.get("model") or p[4],
            "key": c.get("key") or keys.env_key(pid),
            "key_url": p[5]}


def providers():
    s = _ai_settings()
    saved = s.get("providers") or {}
    out = []
    for p in PROVIDERS:
        c = _cfg(p[0])
        # local servers and custom endpoints count only once you've set them up in Settings
        ready = bool(c["key"]) or ((p[0] in LOCAL or p[0] == "custom") and p[0] in saved and bool(c["base_url"]))
        out.append({"id": p[0], "name": p[1], "kind": p[2], "base_url": c["base_url"], "model": c["model"],
                    "key_set": bool(c["key"]), "configured": p[0] in saved, "ready": ready,
                    "key_url": p[5], "local": p[0] in LOCAL})
    return {"providers": out, "default": s.get("default"),
            "sdk_ok": _anthropic_ok()}


def _anthropic_ok():
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def save_provider(id, key=None, base_url=None, model=None, make_default=False, clear_key=False):
    d = _ai_settings()
    pv = d.setdefault("providers", {}).setdefault(id, {})
    if id not in PMAP:
        raise ValueError("unknown provider")
    if clear_key:
        pv.pop("key", None)
    elif key:
        pv["key"] = key.strip()
    if base_url is not None:
        pv["base_url"] = base_url.strip()
    if model is not None:
        pv["model"] = model.strip()
    if make_default or not d.get("default"):
        d["default"] = id
    _save_ai(d)
    return {"saved": True, "default": d["default"]}


# ------------------------------------------------------------------ HTTP (OpenAI-compatible)

def _post(url, body, key, timeout=180, extra_headers=None):
    data = json.dumps(body).encode()
    h = {"Content-Type": "application/json", "User-Agent": "unwind/0.4"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    h.update(extra_headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(_friendly(e.code, msg))
    except urllib.error.URLError as e:
        raise RuntimeError(f"Couldn't reach {urllib.request.urlparse(url).netloc if hasattr(urllib.request, 'urlparse') else url}: {e.reason}")


def _friendly(code, msg):
    try:
        j = json.loads(msg)
        m = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("error") or j.get("message")
        msg = m or msg
    except Exception:
        pass
    hint = {401: "The API key was rejected. Check it in Settings → AI.",
            403: "The key doesn't have access to this model or endpoint.",
            404: "Model or endpoint not found. Pick another model (Load models in Settings).",
            429: "Rate limited or out of credits. Wait a bit or check your balance."}.get(code, "")
    return f"HTTP {code}: {str(msg)[:300]} {hint}".strip()


def models(id):
    c = _cfg(id)
    if c["kind"] == "anthropic":
        client = _anthropic_client(c)
        return sorted(m.id for m in client.models.list())
    req = urllib.request.Request(c["base_url"] + "/models", headers={
        "User-Agent": "unwind/0.4", **({"Authorization": f"Bearer {c['key']}"} if c["key"] else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(_friendly(e.code, e.read().decode("utf-8", "replace")))
    except urllib.error.URLError as e:
        raise RuntimeError(f"Couldn't reach {c['base_url']}: {e.reason}"
                           + (" (is it running?)" if id in LOCAL else ""))
    items = d.get("data") or d.get("models") or []
    return sorted({(m.get("id") or m.get("name")) for m in items if isinstance(m, dict) and (m.get("id") or m.get("name"))})


# ------------------------------------------------------------------ tools

def _tools():
    import connectors
    import unwind_mcp as um
    built = [t for t in um.TOOLS if not t[0].startswith("api_")]
    return built + connectors.as_tools()      # the user's own APIs, read fresh each time


def _run_tool(name, args):
    t = next((x for x in _tools() if x[0] == name), None)
    if not t:
        return f"error: unknown tool {name}", True
    try:
        out = t[1](**(args or {}))
        text = out if isinstance(out, str) else json.dumps(out, default=str)
        if len(text) > TOOL_OUTPUT_LIMIT:
            text = text[:TOOL_OUTPUT_LIMIT] + f"\n…[output cut at {TOOL_OUTPUT_LIMIT} chars of {len(text)}; ask for a narrower query]"
        return text, False
    except TypeError as e:
        return f"error: bad arguments for {name}: {e}", True
    except Exception as e:
        return f"error: {e}", True


def _summ(name, args):
    a = ", ".join(f"{k}={str(v)[:40]}" for k, v in (args or {}).items())
    return f"{name}({a})"


# ------------------------------------------------------------------ Claude (official SDK)

FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5-2"}


def _anthropic_client(c):
    try:
        import anthropic
    except Exception:
        raise RuntimeError("The Claude SDK isn't installed. Run: python3 -m pip install --target "
                           f"'{DEPS}' anthropic")
    if not c["key"]:
        raise RuntimeError("Add your Anthropic API key in Settings → AI.")
    return anthropic.Anthropic(api_key=c["key"], max_retries=3)


def _claude(c, model, system, history, use_tools):
    import anthropic
    client = _anthropic_client(c)
    tools = [{"name": n, "description": d, "input_schema": s} for n, _, d, s in _tools()] if use_tools else []
    msgs = [{"role": m["role"], "content": m["content"]} for m in history if m["role"] in ("user", "assistant")]
    steps = []
    kw = {}
    if model in FALLBACK_MODELS:      # on a policy decline, retry on the fallback model inside the same call
        kw.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    if re.search(r"claude-(opus|sonnet|fable|mythos|haiku)-5|claude-opus-4-[678]", model):
        kw["output_config"] = {"effort": "high"}
    for _ in range(MAX_STEPS):
        try:
            resp = client.beta.messages.create(model=model, max_tokens=16000, system=system, messages=msgs,
                                               **({"tools": tools} if tools else {}), **kw)
        except anthropic.AuthenticationError:
            raise RuntimeError("Anthropic rejected the API key. Check it in Settings → AI.")
        except anthropic.NotFoundError:
            raise RuntimeError(f"Model '{model}' not found. Pick another in Settings → AI.")
        except anthropic.RateLimitError:
            raise RuntimeError("Anthropic rate limit hit. Wait a moment and try again.")
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Anthropic API error {e.status_code}: {e.message}")
        except anthropic.APIConnectionError:
            raise RuntimeError("Couldn't reach the Anthropic API. Check your connection.")
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            return {"reply": "Claude declined this request" + (f" ({cat})." if cat else "."), "steps": steps,
                    "model": resp.model}
        text = "".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason != "tool_use":
            if resp.stop_reason == "max_tokens":
                text += "\n\n_(reply hit the length limit)_"
            return {"reply": text, "steps": steps, "model": resp.model}
        msgs.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            out, err = _run_tool(b.name, b.input if isinstance(b.input, dict) else {})
            steps.append({"tool": b.name, "call": _summ(b.name, b.input), "ok": not err, "preview": out[:300]})
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": err})
        msgs.append({"role": "user", "content": results})
    return {"reply": "Stopped after the maximum number of tool steps. Ask me to continue.", "steps": steps, "model": model}


# ------------------------------------------------------------------ OpenAI-compatible

def _openai(c, model, system, history, use_tools):
    url = c["base_url"] + "/chat/completions"
    msgs = [{"role": "system", "content": system}] + [
        {"role": m["role"], "content": m["content"]} for m in history if m["role"] in ("user", "assistant")]
    tools = [{"type": "function", "function": {"name": n, "description": d[:1000], "parameters": s}}
             for n, _, d, s in _tools()] if use_tools else []
    steps, tools_ok = [], bool(tools)
    extra = {"HTTP-Referer": "http://127.0.0.1", "X-Title": "Unwind"} if c["id"] == "openrouter" else None
    for _ in range(MAX_STEPS):
        body = {"model": model, "messages": msgs}
        if tools_ok:
            body["tools"] = tools
        try:
            d = _post(url, body, c["key"], extra_headers=extra)
        except RuntimeError as e:
            if tools_ok and re.search(r"tool|function", str(e), re.I):
                tools_ok = False          # model can't do tool calls: answer without tools
                steps.append({"tool": "note", "call": "this model doesn't support tools; answering directly",
                              "ok": False, "preview": ""})
                continue
            raise
        ch = (d.get("choices") or [{}])[0]
        m = ch.get("message") or {}
        calls = m.get("tool_calls") or []
        if not calls:
            text = m.get("content") or ""
            if isinstance(text, list):
                text = "".join(x.get("text", "") for x in text if isinstance(x, dict))
            text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S)   # strip reasoning tags some models emit
            return {"reply": text, "steps": steps, "model": d.get("model") or model}
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
        for tc in calls:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args, out, err = {}, "error: arguments were not valid JSON", True
            else:
                out, err = _run_tool(fn.get("name"), args)
            steps.append({"tool": fn.get("name"), "call": _summ(fn.get("name"), args), "ok": not err, "preview": out[:300]})
            msgs.append({"role": "tool", "tool_call_id": tc.get("id"), "content": out})
    return {"reply": "Stopped after the maximum number of tool steps. Ask me to continue.", "steps": steps, "model": model}


# ------------------------------------------------------------------ public

def chat(messages, provider=None, model=None, context=None, tools=True, system_extra=None):
    """
    messages: [{"role": "user"|"assistant", "content": str}, ...] (the conversation so far)
    context:  optional text about what the user is looking at (a function, wallet, trace…)
    """
    pid = provider or _ai_settings().get("default")
    if not pid:
        raise RuntimeError("Pick an AI provider and add a key in Settings → AI.")
    c = _cfg(pid)
    model = (model or c["model"] or "").strip()
    if not model:
        raise RuntimeError(f"Choose a model for {c['name']} in Settings → AI (Load models lists what's available).")
    if c["kind"] != "anthropic" and not c["key"] and pid not in LOCAL and pid != "custom":
        raise RuntimeError(f"Add your {c['name']} API key in Settings → AI.")
    system = SYSTEM + (f"\n\n{system_extra}" if system_extra else "")
    hist = list(messages or [])
    if context and hist and hist[-1]["role"] == "user":
        hist[-1] = {"role": "user", "content": f"{hist[-1]['content']}\n\n---\nWhat I'm looking at in Unwind:\n{context}"}
    t = time.time()
    out = _claude(c, model, system, hist, tools) if c["kind"] == "anthropic" else _openai(c, model, system, hist, tools)
    out.update({"provider": pid, "provider_name": c["name"], "seconds": round(time.time() - t, 1)})
    return out


def test(id, model=None):
    r = chat([{"role": "user", "content": "Reply with exactly: OK"}], provider=id, model=model, tools=False)
    return {"ok": True, "reply": r["reply"][:200], "model": r.get("model"), "seconds": r["seconds"]}


API = {"providers": providers, "save_provider": save_provider, "models": models, "chat": chat, "test": test}
