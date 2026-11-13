"""
keys - import, export and check every API key Unwind can use.

Paste a .env file, shell exports, a JSON object, or bare keys (recognised by their
prefix) and each key is filed in the right place. Keys are stored in
~/.config/unwind/settings.json (owner-only permissions) and also read from
environment variables, so `export DEEPSEEK_API_KEY=...` works too.
"""
import json
import os
import re

import chaintrace as ct

# provider id -> accepted environment variable names (first one is canonical)
AI_ENV = {
    "anthropic": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "nanogpt": ["NANOGPT_API_KEY", "NANO_GPT_API_KEY", "NANOGPT_KEY"],
    "zhipu": ["ZHIPUAI_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY", "BIGMODEL_API_KEY"],
    "zai": ["ZAI_API_KEY", "Z_AI_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_AI_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"],
    "xai": ["XAI_API_KEY", "GROK_API_KEY"],
    "moonshot": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
    "qwen": ["DASHSCOPE_API_KEY", "QWEN_API_KEY"],
    "together": ["TOGETHER_API_KEY"],
    "fireworks": ["FIREWORKS_API_KEY"],
    "perplexity": ["PERPLEXITY_API_KEY", "PPLX_API_KEY"],
    "cerebras": ["CEREBRAS_API_KEY"],
    "siliconflow": ["SILICONFLOW_API_KEY"],
}
OTHER_ENV = {
    "etherscan": ["ETHERSCAN_API_KEY"],
    "helius": ["HELIUS_API_KEY"],
    "solana_rpc": ["SOLANA_RPC_URL", "SOLANA_RPC"],
    "virustotal": ["VIRUSTOTAL_API_KEY", "VT_API_KEY"],
    "malwarebazaar": ["MALWAREBAZAAR_API_KEY", "ABUSECH_API_KEY", "ABUSE_CH_API_KEY"],
}
LABELS = {"etherscan": "Etherscan", "helius": "Helius (Solana)", "solana_rpc": "Solana RPC URL",
          "virustotal": "VirusTotal", "malwarebazaar": "MalwareBazaar"}
# bare keys recognised by prefix (only prefixes that belong to exactly one service)
PREFIX = [("sk-ant-", "anthropic"), ("sk-or-", "openrouter"), ("gsk_", "groq"), ("xai-", "xai"),
          ("AIza", "gemini"), ("pplx-", "perplexity"), ("csk-", "cerebras")]
NAME_TO_TARGET = {n: ("ai", p) for p, ns in AI_ENV.items() for n in ns}
NAME_TO_TARGET.update({n: ("other", k) for k, ns in OTHER_ENV.items() for n in ns})


def mask(v):
    v = str(v or "")
    return "" if not v else (v[:4] + "…" + v[-4:]) if len(v) > 12 else "•" * len(v)


def parse(text):
    """Return (pairs, bare): pairs = [(NAME, value)], bare = [value] for unlabelled keys."""
    text = (text or "").strip()
    pairs, bare = [], []
    if text.startswith("{"):
        try:
            d = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"That looks like JSON but doesn't parse: {e}")

        def walk(o, prefix=""):
            for k, v in o.items():
                if isinstance(v, dict):
                    walk(v, f"{prefix}{k}_")
                elif isinstance(v, str) and v.strip():
                    pairs.append(((prefix + k).upper().replace("-", "_").replace(".", "_"), v.strip()))
        walk(d)
        return pairs, bare
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(?:export\s+|set\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*[=:]\s*(.*)$", line)
        if m:
            val = m.group(2).strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            val = re.sub(r"\s+#.*$", "", val).strip()
            if val:
                pairs.append((m.group(1).upper(), val))
        elif re.fullmatch(r"\S{16,}", line):
            bare.append(line)
    return pairs, bare


def _apply(target, key, value):
    import ai
    import malware
    if target == "ai":
        ai.save_provider(key, key=value)
    elif key == "etherscan":
        ct.save_settings(etherscan_key=value)
    elif key == "helius":
        ct.save_settings(solana_rpc=f"https://mainnet.helius-rpc.com/?api-key={value}")
    elif key == "solana_rpc":
        ct.save_settings(solana_rpc=value)
    elif key in ("virustotal", "malwarebazaar"):
        malware.save_intel(**{key: value})


def import_keys(text, dry_run=False):
    """File every recognised key from pasted text. Values are never sent back to the page."""
    import ai
    pairs, bare = parse(text)
    done, unknown, seen = [], [], set()
    for name, value in pairs:
        t = NAME_TO_TARGET.get(name)
        if not t:
            # a few common aliases written with a different suffix
            alt = re.sub(r"_(KEY|TOKEN|SECRET)$", "_API_KEY", name)
            t = NAME_TO_TARGET.get(alt)
        if not t:
            unknown.append(name)
            continue
        if t in seen:
            continue
        seen.add(t)
        label = ai.PMAP[t[1]][1] if t[0] == "ai" else LABELS[t[1]]
        if not dry_run:
            _apply(t[0], t[1], value)
        done.append({"name": name, "service": label, "value": mask(value)})
    for value in bare:
        p = next((pid for pre, pid in PREFIX if value.startswith(pre)), None)
        if not p:
            unknown.append(mask(value) + " (unlabelled)")
            continue
        if ("ai", p) in seen:
            continue
        seen.add(("ai", p))
        if not dry_run:
            _apply("ai", p, value)
        done.append({"name": "(recognised by prefix)", "service": ai.PMAP[p][1], "value": mask(value)})
    return {"imported": done, "unknown": unknown, "dry_run": dry_run,
            "note": None if done else "No keys recognised. Use names like DEEPSEEK_API_KEY=... (one per line)."}


def status():
    """Which keys are set, and where they come from (settings file or environment)."""
    import ai
    import malware
    s = ct.settings()
    saved_ai = (s.get("ai") or {}).get("providers") or {}
    intel = s.get("intel") or {}
    rows = []
    for pid, names in AI_ENV.items():
        env = next((n for n in names if os.environ.get(n)), None)
        rows.append({"id": pid, "service": ai.PMAP[pid][1], "group": "AI",
                     "set": bool(env or (saved_ai.get(pid) or {}).get("key")),
                     "source": "environment" if env else ("settings" if (saved_ai.get(pid) or {}).get("key") else None),
                     "env": names[0]})
    other = {"etherscan": bool(s.get("etherscan_key")), "helius": "helius-rpc" in str(s.get("solana_rpc") or ""),
             "solana_rpc": bool(s.get("solana_rpc")), "virustotal": bool(intel.get("virustotal")),
             "malwarebazaar": bool(intel.get("malwarebazaar"))}
    for k, names in OTHER_ENV.items():
        env = next((n for n in names if os.environ.get(n)), None)
        rows.append({"id": k, "service": LABELS[k], "group": "Data", "set": bool(env or other[k]),
                     "source": "environment" if env else ("settings" if other[k] else None), "env": names[0]})
    return {"keys": rows, "settings_path": ct.SETTINGS_PATH}


def export_env(include_secrets=False):
    """A .env file of what's configured. Secrets are masked unless include_secrets is true."""
    s = ct.settings()
    saved_ai = (s.get("ai") or {}).get("providers") or {}
    intel = s.get("intel") or {}
    out = ["# Unwind keys. Keep this file private.", ""]
    for pid, names in AI_ENV.items():
        v = (saved_ai.get(pid) or {}).get("key")
        if v:
            out.append(f"{names[0]}={v if include_secrets else mask(v)}")
    vals = {"etherscan": s.get("etherscan_key"), "solana_rpc": s.get("solana_rpc"),
            "virustotal": intel.get("virustotal"), "malwarebazaar": intel.get("malwarebazaar")}
    for k, v in vals.items():
        if v:
            out.append(f"{OTHER_ENV[k][0]}={v if include_secrets else mask(v)}")
    return {"text": "\n".join(out) + "\n", "masked": not include_secrets}


def env_key(provider):
    """First environment variable that holds a key for an AI provider (used by ai.py)."""
    for n in AI_ENV.get(provider, []):
        if os.environ.get(n):
            return os.environ[n]
    return None


API = {"import": import_keys, "status": status, "export": export_env}
