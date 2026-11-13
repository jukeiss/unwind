"""
vault - an Obsidian-compatible Markdown vault for Unwind investigations.

Every wallet, transaction, trace (case) and binary becomes a plain .md note
with YAML frontmatter and [[wikilinks]]. Open the same folder in Obsidian and
it all works there too: graph, backlinks, tags.

Auto-generated parts of a note live between markers:
    <!-- unwind:auto:<section> --> ... <!-- /unwind:auto:<section> -->
Refreshing a wallet only rewrites those blocks; anything you write outside
them is kept.
"""
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone

ROOT = os.environ.get("UNWIND_VAULT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "vault")
_lock = threading.Lock()

WIKI = re.compile(r"\[\[([^\]\|#\\]+)(?:#[^\]\|\\]*)?(?:\\?\|([^\]]+))?\]\]")
TAG = re.compile(r"(?:^|\s)#([A-Za-z][\w/\-]*)")
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)


def _nocode(body):
    """Links and tags inside code don't count (same as Obsidian)."""
    return CODE.sub(" ", body)


# ------------------------------------------------------------------ paths

def _root():
    os.makedirs(ROOT, exist_ok=True)
    return ROOT


def _safe(rel):
    rel = (rel or "").strip().lstrip("/").replace("\\", "/")
    if not rel:
        raise ValueError("path is required")
    full = os.path.realpath(os.path.join(_root(), rel))
    if not full.startswith(os.path.realpath(_root()) + os.sep):
        raise ValueError("path is outside the vault")
    return full


def _rel(full):
    return os.path.relpath(full, _root()).replace(os.sep, "/")


def _clean_name(s):
    s = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", s or "").strip()
    return re.sub(r"\s+", " ", s)[:120] or "Untitled"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ frontmatter

def parse_frontmatter(text):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    block, body = text[4:end], text[end + 4:].lstrip("\n")
    fm, key = {}, None
    for line in block.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z0-9_\-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val == "":
                fm[key] = []
            elif val.startswith("[") and val.endswith("]"):
                fm[key] = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
            else:
                fm[key] = _scalar(val)
        elif key and re.match(r"^\s*-\s+", line):
            if not isinstance(fm.get(key), list):
                fm[key] = []
            fm[key].append(_scalar(re.sub(r"^\s*-\s+", "", line)))
    return fm, body


def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v in ("true", "false"):
        return v == "true"
    if re.fullmatch(r"-?\d+", v) and len(v) < 16:
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    return v


def dump_frontmatter(fm):
    lines = ["---"]
    for k, v in fm.items():
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, (list, tuple)):
            lines.append(f"{k}:")
            lines += [f"  - {_q(x)}" for x in v]
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, float):
            lines.append(f"{k}: {round(v, 8)}")
        else:
            lines.append(f"{k}: {_q(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _q(v):
    s = str(v)
    if re.search(r"[:#\[\]{},&*!|>'\"%@`]|^\s|\s$|^-", s) or s in ("true", "false") or re.fullmatch(r"-?\d+(\.\d+)?", s):
        return json.dumps(s, ensure_ascii=False)
    return s


# ------------------------------------------------------------------ index

_index = {"t": 0, "notes": {}}


def _scan():
    notes = {}
    for dp, dn, fn in os.walk(_root()):
        dn[:] = [d for d in dn if not d.startswith(".")]
        for f in fn:
            if not f.endswith(".md"):
                continue
            full = os.path.join(dp, f)
            try:
                st = os.stat(full)
                with open(full, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            fm, body = parse_frontmatter(text)
            links = [m.group(1).strip() for m in WIKI.finditer(_nocode(body))]
            tags = sorted(set(TAG.findall(_nocode(body))) | set(x for x in (fm.get("tags") or []) if isinstance(x, str)))
            rel = _rel(full)
            notes[rel] = {"path": rel, "name": f[:-3], "fm": fm, "links": links, "tags": tags,
                          "mtime": st.st_mtime, "size": st.st_size}
    return notes


def index(force=False):
    with _lock:
        if force or time.time() - _index["t"] > 2:
            _index["notes"] = _scan()
            _index["t"] = time.time()
        return _index["notes"]


def _resolve(name, notes=None):
    """Resolve a [[link]] target to a note path, Obsidian-style (by basename, or relative path)."""
    notes = notes or index()
    n = name.strip()
    if n.endswith(".md"):
        n = n[:-3]
    if n + ".md" in notes:
        return n + ".md"
    low = n.lower()
    hits = [p for p, x in notes.items() if x["name"].lower() == low]
    if hits:
        return sorted(hits, key=len)[0]
    for p, x in notes.items():           # aliases
        al = x["fm"].get("aliases") or []
        if isinstance(al, str):
            al = [al]
        if any(str(a).lower() == low for a in al):
            return p
    return None


# ------------------------------------------------------------------ CRUD

def info():
    notes = index(True)
    by = {}
    for x in notes.values():
        t = x["fm"].get("type") or "note"
        by[t] = by.get(t, 0) + 1
    return {"path": _root(), "notes": len(notes), "by_type": by}


def tree():
    notes = index()
    folders = set()
    for dp, dn, fn in os.walk(_root()):
        dn[:] = [d for d in dn if not d.startswith(".")]
        if dp != _root():
            folders.add(_rel(dp))
    files = [{"path": p, "name": x["name"], "type": x["fm"].get("type") or "note",
              "label": x["fm"].get("label") or (x["fm"].get("aliases") or [None])[0] if isinstance(x["fm"].get("aliases"), list) else x["fm"].get("label"),
              "flags": x["fm"].get("flags") or [], "mtime": x["mtime"]}
             for p, x in notes.items()]
    files.sort(key=lambda f: f["path"].lower())
    return {"root": _root(), "folders": sorted(folders, key=str.lower), "files": files}


def read(path):
    full = _safe(path)
    if not os.path.exists(full):
        raise ValueError(f"note not found: {path}")
    with open(full, encoding="utf-8", errors="replace") as f:
        text = f.read()
    fm, body = parse_frontmatter(text)
    notes = index()
    rel = _rel(full)
    me = notes.get(rel) or {"name": os.path.basename(rel)[:-3]}
    outgoing = []
    for m in WIKI.finditer(_nocode(body)):
        tgt = m.group(1).strip()
        outgoing.append({"target": tgt, "alias": m.group(2), "path": _resolve(tgt, notes)})
    back = []
    for p, x in notes.items():
        if p == rel:
            continue
        if any(_resolve(l, notes) == rel for l in x["links"]):
            back.append({"path": p, "name": x["name"], "label": x["fm"].get("label"),
                         "type": x["fm"].get("type") or "note", "context": _context(p, me["name"])})
    # unlinked mentions (Obsidian-style): notes that mention the name/label without linking
    needles = {me["name"].lower()}
    if fm.get("label"):
        needles.add(str(fm["label"]).lower())
    mentions = []
    linked = {b["path"] for b in back}
    for p, x in notes.items():
        if p == rel or p in linked:
            continue
        try:
            with open(_safe(p), encoding="utf-8", errors="replace") as fh:
                t = fh.read().lower()
        except OSError:
            continue
        if any(n and len(n) > 3 and n in t for n in needles):
            mentions.append({"path": p, "name": x["name"]})
    return {"path": rel, "name": me["name"], "content": text, "frontmatter": fm,
            "outgoing": outgoing, "backlinks": back, "mentions": mentions[:30],
            "tags": sorted(set(TAG.findall(body)) | set(fm.get("tags") or [])), "mtime": os.path.getmtime(full)}


def _context(path, name):
    try:
        with open(_safe(path), encoding="utf-8", errors="replace") as f:
            for line in f:
                if "[[" in line and name.lower() in line.lower():
                    return line.strip()[:200]
    except OSError:
        pass
    return None


_TBL_LINK = re.compile(r"\[\[([^\]|\\]+)\|([^\]]+)\]\]")


def table_safe(text):
    """In table rows, write [[a|b]] as [[a\\|b]] so the pipe doesn't split the column (Obsidian's convention)."""
    return "\n".join(_TBL_LINK.sub(r"[[\1\\|\2]]", l) if l.lstrip().startswith("|") else l for l in text.split("\n"))


def write(path, content, create_only=False):
    content = table_safe(content)
    full = _safe(path if path.endswith(".md") else path + ".md")
    if create_only and os.path.exists(full):
        raise ValueError("a note with that name already exists")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    tmp = full + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, full)
    index(True)
    return {"path": _rel(full), "saved": _now()}


def create(folder="", title="Untitled", content=None):
    base = _clean_name(title)
    rel = (folder.strip("/") + "/" if folder else "") + base
    n, cand = 1, rel
    while os.path.exists(_safe(cand + ".md")):
        n += 1
        cand = f"{rel} {n}"
    body = content if content is not None else f"# {base}\n\n"
    return write(cand + ".md", body, create_only=True)


def mkdir(path):
    full = _safe(path)
    os.makedirs(full, exist_ok=True)
    return {"path": _rel(full)}


def delete(path):
    """Moves the note to .trash inside the vault (recoverable), like Obsidian's default."""
    full = _safe(path)
    if not os.path.exists(full):
        raise ValueError("not found")
    trash = os.path.join(_root(), ".trash")
    os.makedirs(trash, exist_ok=True)
    dest = os.path.join(trash, f"{int(time.time())}-{os.path.basename(full)}")
    shutil.move(full, dest)
    index(True)
    return {"trashed": _rel(dest)}


def rename(path, new_name):
    """Rename/move a note and update [[links]] that point at it."""
    full = _safe(path)
    if not os.path.exists(full):
        raise ValueError("not found")
    old_name = os.path.basename(full)[:-3]
    new_rel = new_name if "/" in new_name else os.path.join(os.path.dirname(_rel(full)), new_name)
    new_rel = new_rel if new_rel.endswith(".md") else new_rel + ".md"
    new_full = _safe(new_rel)
    if os.path.exists(new_full):
        raise ValueError("a note with that name already exists")
    os.makedirs(os.path.dirname(new_full), exist_ok=True)
    shutil.move(full, new_full)
    new_base = os.path.basename(new_full)[:-3]
    changed = 0
    if new_base != old_name:
        rx = re.compile(r"\[\[" + re.escape(old_name) + r"(?=[\]\|#])")
        for p in index(True):
            fp = _safe(p)
            with open(fp, encoding="utf-8") as f:
                t = f.read()
            t2 = rx.sub("[[" + new_base, t)
            if t2 != t:
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(t2)
                changed += 1
    index(True)
    return {"path": _rel(new_full), "links_updated": changed}


def search(query, limit=60):
    q = (query or "").strip()
    if not q:
        return {"query": q, "results": []}
    tag = q[1:].lower() if q.startswith("#") else None
    rx = re.compile(re.escape(q), re.I)
    res = []
    for p, x in index().items():
        if tag:
            if any(t.lower().startswith(tag) for t in x["tags"]) or tag in [str(f) for f in x["fm"].get("flags") or []]:
                res.append({"path": p, "name": x["name"], "hits": [], "score": 2})
            continue
        score, hits = 0, []
        if rx.search(x["name"]) or rx.search(str(x["fm"].get("label") or "")):
            score += 5
        try:
            with open(_safe(p), encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if rx.search(line):
                        score += 1
                        if len(hits) < 4:
                            hits.append({"line": i, "text": line.strip()[:220]})
        except OSError:
            continue
        if score:
            res.append({"path": p, "name": x["name"], "label": x["fm"].get("label"),
                        "type": x["fm"].get("type") or "note", "hits": hits, "score": score})
    res.sort(key=lambda r: -r["score"])
    return {"query": q, "results": res[:limit]}


def graph(include_orphans=True, include_unresolved=True):
    notes = index()
    nodes, edges, seen = [], [], set()
    for p, x in notes.items():
        fm = x["fm"]
        label = fm.get("label") or (_short(x["name"]) if fm.get("type") == "address" else x["name"])
        nodes.append({"id": p, "name": x["name"], "label": label,
                      "type": fm.get("type") or "note", "chain": fm.get("chain") or (fm.get("chains") or [None])[0]
                      if isinstance(fm.get("chains"), list) else fm.get("chain"),
                      "flags": fm.get("flags") or [], "tags": x["tags"]})
    for p, x in notes.items():
        for l in x["links"]:
            tgt = _resolve(l, notes)
            if not tgt:
                if not include_unresolved:
                    continue
                tgt = "?" + l
                if tgt not in seen:
                    seen.add(tgt)
                    nodes.append({"id": tgt, "name": l, "label": l, "type": "unresolved", "flags": [], "tags": []})
            if tgt != p:
                edges.append({"source": p, "target": tgt})
    if not include_orphans:
        linked = {e["source"] for e in edges} | {e["target"] for e in edges}
        nodes = [n for n in nodes if n["id"] in linked]
    return {"nodes": nodes, "edges": edges}


def labels():
    """{address_lowercase: label} for every address note ("" when it has no name). Used to label traces."""
    out = {}
    for x in index().values():
        a = x["fm"].get("address")
        if a and x["fm"].get("type") == "address":
            lab = str(x["fm"].get("label") or "")
            out[str(a).lower()] = "" if lab.lower() == str(a).lower() else lab
    return out


# ------------------------------------------------------------------ writers

def _fmt_amt(v, sym=""):
    if v is None:
        return "–"
    a = abs(v)
    s = f"{v:,.0f}" if a >= 1000 else f"{v:,.2f}" if a >= 1 else f"{v:.6f}".rstrip("0").rstrip(".") if a else "0"
    return f"{s} {sym}".strip()


def _usd(v):
    if v is None:
        return ""
    return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"


def _short(a):
    return a if len(a) <= 14 else f"{a[:6]}…{a[-4:]}"


def _link(addr, label=None):
    return f"[[{addr}|{label}]]" if label else f"[[{addr}]]"


def _replace_block(text, section, block):
    start, end = f"<!-- unwind:auto:{section} -->", f"<!-- /unwind:auto:{section} -->"
    new = f"{start}\n{block.rstrip()}\n{end}"
    if start in text and end in text:
        a, b = text.index(start), text.index(end) + len(end)
        return text[:a] + new + text[b:]
    marker = "\n## Notes"
    if marker in text:
        i = text.index(marker)
        return text[:i].rstrip() + "\n\n" + new + "\n" + text[i:]
    return text.rstrip() + "\n\n" + new + "\n"


def _address_path(address):
    notes = index()
    for p, x in notes.items():
        if x["fm"].get("type") == "address" and str(x["fm"].get("address", "")).lower() == address.lower():
            return p
    return f"Wallets/{_clean_name(address)}.md"


def _upsert_address(address, chain, chain_name, label=None, flags=None, block=None, extra_fm=None):
    rel = _address_path(address)
    full = _safe(rel)
    if os.path.exists(full):
        with open(full, encoding="utf-8") as f:
            text = f.read()
    else:
        title = label or _short(address)
        text = (f"# {title}\n\n"
                f"## Notes\n\n_Your notes about this wallet. Unwind never edits this section._\n")
    fm, body = parse_frontmatter(text)
    chains = fm.get("chains") or []
    if isinstance(chains, str):
        chains = [chains]
    if chain not in chains:
        chains.append(chain)
    fl = list(dict.fromkeys([*(fm.get("flags") or []), *(flags or [])]))
    fm.update({"type": "address", "address": address, "chains": chains})
    if label and (not fm.get("label") or fm.get("label_source") == "unwind"):
        fm["label"], fm["label_source"] = label, "unwind"
        fm["aliases"] = [label]
    fm["flags"] = fl
    fm["tags"] = sorted(set((fm.get("tags") or []) + ["wallet"] + [f"flag/{f}" for f in (flags or [])]))
    fm["updated"] = _now()
    if extra_fm:
        fm.update({k: v for k, v in extra_fm.items() if v is not None})
    if block is not None:
        body = _replace_block(body, chain, block)
    write(rel, dump_frontmatter(fm) + body)
    return rel


def set_label(address, label, chain=None):
    """Give an address your own name. It then shows up in every trace and wallet view."""
    label = (label or "").strip()
    rel = _address_path(address)
    full = _safe(rel)
    if os.path.exists(full):
        with open(full, encoding="utf-8") as f:
            fm, body = parse_frontmatter(f.read())
    else:
        fm, body = {}, f"# {label or _short(address)}\n\n## Notes\n\n"
    chains = fm.get("chains") or []
    if isinstance(chains, str):
        chains = [chains]
    if chain and chain not in chains:
        chains.append(chain)
    fm.update({"type": "address", "address": address, "chains": chains, "updated": _now()})
    if label:
        fm.update({"label": label, "label_source": "you", "aliases": [label]})
    else:
        for k in ("label", "label_source", "aliases"):
            fm.pop(k, None)
    fm["tags"] = sorted(set((fm.get("tags") or []) + ["wallet"]))
    write(rel, dump_frontmatter(fm) + body)
    return {"path": rel, "label": label}


def save_wallet(wallet, activity=None, exposure=None, links=None):
    """Create or refresh the note for a wallet. Your own text outside the auto blocks is kept."""
    w = wallet
    sym, cname = w.get("symbol", ""), w.get("chain_name", w.get("chain"))
    flags = w.get("flags") or []
    lines = [f"> [!info] {cname} · " + (", ".join(flags) if flags else "no flags"),
             f"> Refreshed {_now()} UTC · [explorer]({w.get('explorer_url')})", "",
             "| | |", "|---|---|",
             f"| Address | `{w['address']}` |",
             f"| Balance | {_fmt_amt(w.get('balance'), sym)} {_usd(w.get('balance_usd'))} |"]
    if w.get("tokens_usd"):
        lines.append(f"| Tokens | {_usd(w['tokens_usd'])} across {len(w.get('tokens') or [])} tokens |")
    if w.get("tx_count") is not None:
        lines.append(f"| Transactions | {w['tx_count']:,} |")
    if w.get("address_type"):
        lines.append(f"| Type | {w['address_type']} |")
    if w.get("total_received") is not None:
        lines.append(f"| Received / sent | {_fmt_amt(w['total_received'], sym)} / {_fmt_amt(w.get('total_sent'), sym)} |")
    if w.get("note"):
        lines += ["", f"> [!warning] {w['note']}"]
    if exposure:
        risk = exposure.get("risk")
        lines += ["", f"> [!{'danger' if risk == 'high' else 'warning' if risk == 'medium' else 'success'}] "
                      f"Mixer exposure: {exposure.get('verdict')}"]
        for m in (exposure.get("mixer_hits") or [])[:8]:
            lines.append(f"> - {m.get('direction')} {m.get('mixer')} · `{(m.get('hash') or '')[:14]}…` {m.get('time') or ''}")
        for cj in (exposure.get("coinjoins") or [])[:8]:
            lines.append(f"> - CoinJoin ({cj.get('type')}) · `{cj['txid'][:14]}…` block {cj.get('height')}")
        if exposure.get("first_seen"):
            fs = exposure["first_seen"]
            lines.append(f"> First seen {fs.get('time')} (block {fs.get('height')})")
        if exposure.get("funded_by"):
            lines.append("> Funded by " + ", ".join(_link(a, _short(a)) if a and a != "block reward" else str(a)
                                                     for a in exposure["funded_by"][:3]))
    if links and links.get("links"):
        lines += ["", "**Same owner**"]
        for l in links["links"][:20]:
            if l["address"].lower() == w["address"].lower():
                lines.append(f"- {l['chain_name']}: same address ({l['certainty']})")
            else:
                lines.append(f"- {l['chain_name']}: {_link(l['address'], _short(l['address']))} — {l['relation']} ({l['certainty']})")
    if w.get("tokens"):
        lines += ["", "**Top tokens**", "", "| Token | Amount | USD |", "|---|---:|---:|"]
        for t in w["tokens"][:12]:
            lines.append(f"| {t.get('symbol')} | {_fmt_amt(t.get('amount'))} | {_usd(t.get('usd'))} |")
    if activity and activity.get("items"):
        agg = {}
        for x in activity["items"]:
            cp = x.get("counterparty")
            if not cp or x.get("kind") == "call" or cp == w["address"]:
                continue
            g = agg.setdefault(cp, {"in": 0.0, "out": 0.0, "n": 0, "label": x.get("counterparty_label"), "change": False})
            g["in" if x["direction"] == "in" else "out"] += x.get("usd") or 0
            g["n"] += 1
            g["change"] = g["change"] or bool(x.get("change"))
        top = sorted(agg.items(), key=lambda kv: -(kv[1]["in"] + kv[1]["out"]))[:15]
        if top:
            lines += ["", "**Counterparties** (recent activity)"]
            for cp, g in top:
                arrow = "⇄" if g["in"] and g["out"] else ("→" if g["out"] else "←")
                tag = " · change" if g["change"] else ""
                lines.append(f"- {arrow} {_link(cp, g['label'] or _short(cp))} {_usd(g['in'] + g['out'])} · {g['n']} transfers{tag}")
    rel = _upsert_address(w["address"], w["chain"], cname, label=w.get("label") or w.get("ens"), flags=flags,
                          block=f"### {cname}\n" + "\n".join(lines),
                          extra_fm={f"balance_{w['chain']}": f"{_fmt_amt(w.get('balance'), sym)}",
                                    "usd": round(w["portfolio_usd"], 2) if w.get("portfolio_usd") else None})
    return {"path": rel}


def save_trace(trace, title=None, notes_per_node=True):
    """Write a case note for a trace, plus a note for every wallet in it, all linked."""
    t = trace
    sym = t.get("symbol", "")
    root = next(n for n in t["nodes"] if n.get("root"))
    title = _clean_name(title or f"Trace {root.get('label') or _short(root['address'])} {t['direction']} {_today()}")
    byid = {n["id"]: n for n in t["nodes"]}

    def nm(n):
        return _link(n["address"], n.get("label") or _short(n["address"]))

    if notes_per_node:
        outs = {}
        for e in t["edges"]:
            outs.setdefault(e["source"], []).append(e)
            outs.setdefault(e["target"], []).append(e)
        for n in t["nodes"]:
            if n["address"] == "coinbase":
                continue
            flows = []
            for e in outs.get(n["id"], [])[:20]:
                other = byid.get(e["target"] if e["source"] == n["id"] else e["source"])
                if not other:
                    continue
                arrow = "→" if e["source"] == n["id"] else "←"
                assets = ", ".join(f"{_fmt_amt(v, k)}" for k, v in list(e["assets"].items())[:3])
                tag = " · change (same owner)" if e.get("change") else ""
                flows.append(f"- {arrow} {nm(other)} {assets} {_usd(e['usd'])} · {e['count']} transfers{tag}")
            block = (f"### {t['chain_name']}\n"
                     f"Seen in [[{title}]] · hop {n['hop']} · {n.get('kind')}"
                     + (f" · balance {_fmt_amt(n.get('balance'), sym)} {_usd(n.get('balance_usd'))}" if n.get("balance") is not None else "")
                     + "\n\n" + ("\n".join(flows) or "_no flows recorded_"))
            _upsert_address(n["address"], t["chain"], t["chain_name"], label=n.get("label"),
                            flags=[f for f in n.get("flags") or [] if f != "vault"], block=block)

    hops = {}
    for n in t["nodes"]:
        hops.setdefault(n["hop"], []).append(n)
    L = [f"# {title}", "",
         f"> [!abstract] {t['chain_name']} · following money **{t['direction']}** · {t['hops']} hops · "
         f"{len(t['nodes'])} wallets · {len(t['edges'])} flows",
         f"> Started from {nm(root)} on {_now()} UTC", ""]
    if "mixer_exposure" in (root.get("flags") or []):
        L += [f"> [!danger] A mixer appears {root.get('mixer_hops')} hop(s) away.", ""]
    if t.get("peel_hint"):
        L += [f"> [!warning] {t['change_edges']} change hops followed: possible peel chain. "
              f"Run a peel-chain check on the change addresses.", ""]
    if t.get("endpoints"):
        L += ["## Where the money ends up", "", "| Wallet | Kind | Hop | Flow | Flags |", "|---|---|---:|---:|---|"]
        for e in t["endpoints"][:15]:
            L.append(f"| {_link(e['address'], e.get('label') or _short(e['address']))} | {e['kind']} | {e['hop']} | "
                     f"{_usd(e['usd'])} | {', '.join(e.get('flags') or [])} |")
        L.append("")
    L += ["## Hops", ""]
    for h in sorted(hops):
        L.append(f"### Hop {h}")
        for n in sorted(hops[h], key=lambda n: -(n.get("in_usd", 0) + n.get("out_usd", 0))):
            fl = f" `{' '.join(n.get('flags') or [])}`" if n.get("flags") else ""
            L.append(f"- {nm(n)} — {n.get('kind')}{fl} · in {_usd(n.get('in_usd'))} · out {_usd(n.get('out_usd'))}")
        L.append("")
    L += ["## Flows", "", "| From | To | Amount | USD | Transfers | First | Last |", "|---|---|---|---:|---:|---|---|"]
    for e in sorted(t["edges"], key=lambda e: -e["usd"])[:60]:
        s, d = byid.get(e["source"]), byid.get(e["target"])
        if not s or not d:
            continue
        assets = ", ".join(f"{_fmt_amt(v, k)}" for k, v in list(e["assets"].items())[:2])
        L.append(f"| {nm(s)} | {nm(d)}{' (change)' if e.get('change') else ''} | {assets} | {_usd(e['usd'])} | "
                 f"{e['count']} | {(e.get('first') or '')[:10]} | {(e.get('last') or '')[:10]} |")
    L += ["", "## Notes", "", "_Your conclusions. Unwind never edits this section._", ""]
    fm = {"type": "case", "chain": t["chain"], "root": root["address"], "direction": t["direction"],
          "hops": t["hops"], "wallets": len(t["nodes"]), "created": _now(), "tags": ["case", "trace"]}
    rel = f"Cases/{title}.md"
    write(rel, dump_frontmatter(fm) + "\n".join(L))
    return {"path": rel, "wallet_notes": len(t["nodes"]) if notes_per_node else 0}


def save_tx(tx, title=None):
    h = tx.get("hash")
    sym = tx.get("symbol", "")
    L = [f"# Tx {_short(h)}", "", f"> [!info] {tx.get('chain')} · {tx.get('time') or ''} · block {tx.get('block') or '–'} "
                                  f"· [explorer]({tx.get('explorer_url')})", ""]
    if tx.get("inputs") and isinstance(tx["inputs"], list):
        L += ["**Inputs**"] + [f"- {_link(i['address'], _short(i['address'])) if i['address'] != 'coinbase' else 'coinbase'} "
                               f"{_fmt_amt(i['amount'], sym)}" for i in tx["inputs"][:30]] + [""]
        L += ["**Outputs**"] + [f"- {_link(o['address'], _short(o['address'])) if o.get('address') else '?'} "
                                f"{_fmt_amt(o['amount'], sym)} · coin `{o.get('coin_id', '')}`" for o in tx.get("outputs", [])[:30]] + [""]
    if tx.get("from"):
        L.append(f"- From {_link(tx['from'], tx.get('from_label') or _short(tx['from']))}")
    if tx.get("to"):
        L.append(f"- To {_link(tx['to'], tx.get('to_label') or _short(tx['to']))}")
    if tx.get("value") is not None:
        L.append(f"- Value {_fmt_amt(tx['value'], sym)} {_usd(tx.get('value_usd'))}")
    for tt in tx.get("token_transfers") or []:
        L.append(f"- {tt.get('asset')} {_fmt_amt(tt.get('amount'))} {_link(tt['from'], tt.get('from_label') or _short(tt['from'])) if tt.get('from') else ''}"
                 f" → {_link(tt['to'], tt.get('to_label') or _short(tt['to'])) if tt.get('to') else ''}")
    if tx.get("coinjoin", {}).get("coinjoin"):
        L += ["", f"> [!warning] CoinJoin: {tx['coinjoin']['type']} — {tx['coinjoin']['rule']}"]
    if tx.get("change"):
        ch = tx["change"]
        L += ["", f"> [!note] Likely change: {_link(ch['address'], _short(ch['address']))} ({ch['confidence']}) — "
                  + "; ".join(ch["reasons"])]
    for fp in tx.get("fingerprints") or []:
        L.append(f"- **{fp['signal']}** ({fp['strength']}): {fp['meaning']}")
    if tx.get("limits"):
        L += ["", f"> [!quote] {tx['limits']}"]
    L += ["", "## Notes", ""]
    fm = {"type": "tx", "chain": tx.get("chain"), "hash": h, "time": tx.get("time"), "tags": ["tx"]}
    rel = f"Transactions/{_clean_name(title or h)}.md"
    write(rel, dump_frontmatter(fm) + "\n".join(L))
    return {"path": rel}


def save_binary(summary, functions_of_interest=None, title=None):
    s = summary
    name = _clean_name(title or s.get("name") or "binary")
    rel = f"Binaries/{name}.md"
    full = _safe(rel)
    sig = s.get("signature") or {}
    block = ["| | |", "|---|---|", f"| Path | `{s.get('path')}` |", f"| Type | {s.get('type')} |",
             f"| Architectures | {', '.join(s.get('archs') or []) or '–'} (analysing {s.get('arch') or '–'}) |",
             f"| Size | {s.get('size', 0):,} bytes |", f"| SHA-256 | `{s.get('sha256')}` |",
             f"| Signed by | {' → '.join(sig.get('authority') or []) or ('unsigned' if sig.get('unsigned') else '–')} |",
             f"| Identifier | {sig.get('identifier') or '–'} |", f"| Entry point | `{s.get('entry') or '–'}` |",
             f"| Functions | {s.get('function_count')} ({s.get('named_function_count')} named) |",
             f"| Imports | {s.get('import_count')} |", ""]
    if s.get("libraries"):
        block += ["**Linked libraries**"] + [f"- `{l}`" for l in s["libraries"][:30]] + [""]
    if functions_of_interest:
        block += ["**Functions of interest**"] + [f"- `{f.get('addr')}` {f.get('name')} — {f.get('note', '')}"
                                                  for f in functions_of_interest] + [""]
    if os.path.exists(full):
        with open(full, encoding="utf-8") as f:
            text = f.read()
        fm, body = parse_frontmatter(text)
    else:
        fm, body = {}, f"# {name}\n\n## Notes\n\n_What you've worked out about this program._\n"
    fm.update({"type": "binary", "path": s.get("path"), "sha256": s.get("sha256"), "arch": s.get("arch"),
               "updated": _now(), "tags": sorted(set((fm.get("tags") or []) + ["binary"]))})
    body = _replace_block(body, "binary", "\n".join(block))
    write(rel, dump_frontmatter(fm) + body)
    return {"path": rel}


def save_report(kind, data, title):
    """Generic: store any analysis result (peel chain, cluster, matches, coin, links) as a note."""
    title = _clean_name(title)
    L = [f"# {title}", "", f"> [!abstract] {kind} · {_now()} UTC", ""]

    def addr(a):
        return _link(a, _short(a)) if isinstance(a, str) and len(a) > 20 and " " not in a else str(a)

    if kind == "peel":
        L += [f"**{'Peel chain' if data['is_peel_chain'] else 'Not a peel chain'}** ({data['confidence']}) · "
              f"{data['length']} steps · peeled {_fmt_amt(data['total_peeled'], data.get('symbol', ''))} "
              f"{_usd(data.get('total_peeled_usd'))} · stopped: {data['stopped_because']}", "",
              "| Step | Tx | Peeled | Change | Change address |", "|---:|---|---|---:|---|"]
        for h in data["hops"]:
            L.append(f"| {h['step']} | `{h['txid'][:12]}…` | " + ", ".join(f"{addr(p['address'])} {_fmt_amt(p['value'])}" for p in h["peeled"][:3])
                     + f" | {_fmt_amt(h['change'])} | {addr(h['change_address'])} ({h['change_confidence']}) |")
    elif kind == "cluster":
        L += [f"{data['size']} addresses · method: {data['method']} · CoinJoins skipped: {data['coinjoins_skipped']}", ""]
        L += [f"- {addr(m['address'])} — {m['reason']}" for m in data["addresses"]]
    elif kind == "matches":
        L += [data.get("method", ""), "", "| Confidence | From | To | Amount | Gap | Why |", "|---|---|---|---|---:|---|"]
        for m in data["matches"][:80]:
            L.append(f"| {m['confidence']} | {addr(m['from_wallet'])} ({m['from_chain']}) | {addr(m['to_wallet'])} ({m['to_chain']}) | "
                     f"{_fmt_amt(m['out_amount'], m['out_asset'])} → {_fmt_amt(m['in_amount'], m['in_asset'])} | {m['gap_hours']}h | "
                     f"{'; '.join(m['why'])} |")
    elif kind == "links":
        L += [f"- {l['chain_name']}: {addr(l['address'])} — {l['relation']} (**{l['certainty']}**)" for l in data["links"]]
        L += [f"> {n}" for n in data.get("notes") or []]
    elif kind == "coin":
        b = data.get("block") or {}
        L += [f"Coin `{data['id']}` · {_fmt_amt(data['value'], data.get('symbol', ''))} {_usd(data.get('usd'))} · "
              f"held by {addr(data.get('address'))}",
              f"- Created in block {data['created']['height']} ({data['created']['time']}), {data['created'].get('age')} ago",
              f"- That block was mined by **{b.get('pool') or 'unknown pool'}**" + (f" (tag `{b.get('coinbase_tag')}`)" if b.get('coinbase_tag') else ""),
              f"- Origin: {data['origin']}",
              f"- Spent: {('in `' + data['spent']['txid'][:16] + '…` at ' + str(data['spent'].get('time'))) if data.get('spent') else 'no (unspent)'}", "",
              "**Ancestry**"]
        for a in data.get("ancestry") or []:
            L.append(f"- step {a['step']}: {a['kind']} · block {a.get('height')} · {addr(a.get('address')) if a.get('address') else ''}"
                     + (f" · mined by {a['block'].get('pool')}" if a.get("block") else ""))
    else:
        L += ["```json", json.dumps(data, indent=2, default=str)[:20000], "```"]
    L += ["", "## Notes", ""]
    rel = f"Reports/{title}.md"
    write(rel, dump_frontmatter({"type": "report", "kind": kind, "created": _now(), "tags": ["report", kind]}) + "\n".join(L))
    return {"path": rel}


def ensure_welcome():
    if index():
        return
    write("Welcome.md", WELCOME)


WELCOME = """---
type: note
tags:
  - help
---
# Welcome to Unwind

Unwind is a workbench for **following money** and **taking programs apart**. Everything you find lands here as plain Markdown notes linked with `[[wikilinks]]`, so this vault opens in Obsidian too.

## Follow money
- Paste any address, ENS name or transaction hash into **Trace** (⌘K → "Trace").
- Supported: Bitcoin, Litecoin, Ethereum and 30+ EVM chains, Solana, Tron, XRP, TON. Monero transactions can be inspected (addresses can't: the chain hides them).
- **Save to vault** writes a case note plus a note per wallet. Open **Graph view** to see how cases share wallets.

## Read a program
- Open **Binary** and give it a path, e.g. `/System/Applications/Calculator.app`.
- Functions, strings, disassembly with clickable calls, hex, cross-references.

## Shortcuts
- ⌘K command palette · ⌘O quick switcher · ⌘E toggle edit/preview · ⌘G graph

## Notes
Write anything here. Try linking a wallet like [[1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa|the genesis address]].
"""


API = {
    "info": info, "tree": tree, "read": read, "write": write, "create": create, "mkdir": mkdir,
    "delete": delete, "rename": rename, "search": search, "graph": graph, "labels": labels,
    "save_wallet": save_wallet, "save_trace": save_trace, "save_tx": save_tx,
    "save_binary": save_binary, "save_report": save_report, "set_label": set_label,
}
