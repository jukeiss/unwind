#!/usr/bin/env python3
"""
Unwind MCP server: gives a coding agent (Claude Code, Cursor, ...) the same
tools the app has. Speaks MCP over stdio. Pure stdlib.

    claude mcp add unwind -- python3 /path/to/unwind/unwind_mcp.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import chaintrace as ct   # noqa: E402
import correlate as co    # noqa: E402
import dissect as dx      # noqa: E402
import forensics as fx    # noqa: E402
import heuristics as hx   # noqa: E402
import malware as mw       # noqa: E402
import history as hi      # noqa: E402
import vault as vx        # noqa: E402

MAX = 80_000
S, I, N, B, A = "string", "integer", "number", "boolean", "array"


def P(**props):
    """Build a JSON schema. props: name=(type, description, required?)"""
    req = [k for k, v in props.items() if len(v) > 2 and v[2]]
    return {"type": "object",
            "properties": {k: ({"type": v[0], "description": v[1]} if v[0] != A else
                               {"type": "array", "items": {"type": "string"}, "description": v[1]})
                           for k, v in props.items()},
            "required": req}


def _functions(path, filter=None, limit=300, arch=None):
    fs = dx.functions(path, arch)
    if filter:
        rx = dx._rx(filter)
        fs = [f for f in fs if rx.search(f["name"])]
    return {"total": len(fs), "items": fs[:limit]}


def _save_wallet(address, chain="auto"):
    w = ct.wallet(address, chain)
    act = exp = lk = None
    for name, fn in (("act", lambda: ct.activity(w["address"], w["chain"], limit=60)),
                     ("exp", lambda: fx.exposure(w["address"], w["chain"])),
                     ("lk", lambda: co.links(w["address"], w["chain"]))):
        try:
            val = fn()
        except Exception:
            val = None
        if name == "act":
            act = val
        elif name == "exp":
            exp = val
        else:
            lk = val
    return vx.save_wallet(w, act, exp, lk)


def _trace_and_save(address, chain="auto", hops=2, direction="out", per_hop=5, min_usd=0, title=None):
    t = ct.trace(address, chain=chain, hops=hops, direction=direction, per_hop=per_hop, min_usd=min_usd,
                 labels=vx.labels())
    saved = vx.save_trace(t, title)
    return {"saved": saved, "summary": {"wallets": len(t["nodes"]), "flows": len(t["edges"]),
                                        "endpoints": t["endpoints"][:10], "root_flags": t["nodes"][0].get("flags")}}


TOOLS = [
    # ---- binaries
    ("bin_summary", lambda path, arch=None: dx.summary(path, arch),
     "Identify a program or library: type, architectures, signature, linked libraries, sections, entry point, "
     "function and import counts. Accepts .app bundles. Start here.",
     P(path=(S, "Path to the binary or .app", True), arch=(S, "Architecture slice, e.g. arm64e or x86_64"))),
    ("bin_functions", _functions,
     "List functions (named symbols plus LC_FUNCTION_STARTS, so stripped binaries still work), optionally filtered.",
     P(path=(S, "", True), filter=(S, "Regex on the name"), limit=(I, "Max results"), arch=(S, ""))),
    ("bin_strings", lambda path, filter=None, preset=None, min_len=5, limit=500: dx.strings(path, min_len, filter, preset, limit),
     "Printable strings with file offsets. Presets: urls, paths, errors, crypto, format, keys.",
     P(path=(S, "", True), filter=(S, "Regex"), preset=(S, "urls|paths|errors|crypto|format|keys"),
       min_len=(I, ""), limit=(I, ""))),
    ("bin_disassemble", lambda path, symbol=None, address=None, arch=None, max_lines=1500:
        dx.disassemble(path, symbol, address, arch, max_lines),
     "Disassemble one function by name or by any address inside it (default: entry point). Calls to other "
     "functions are annotated; string literals show as 'literal pool for: \"...\"'.",
     P(path=(S, "", True), symbol=(S, "Function name"), address=(S, "Hex address inside the function"),
       arch=(S, ""), max_lines=(I, ""))),
    ("bin_xrefs", lambda path, needle, arch=None: dx.xrefs(path, needle, arch),
     "Find instructions mentioning a name, string text, address or constant, with the function they're in. "
     "Search a string's text to find the code that uses it.",
     P(path=(S, "", True), needle=(S, "What to search for", True), arch=(S, ""))),
    ("bin_hexdump", lambda path, offset=0, length=256: dx.hexdump(path, offset, length),
     "Hex + ASCII of raw bytes at a file offset (decimal or 0x hex).",
     P(path=(S, "", True), offset=(S, "Offset, e.g. 4096 or 0x1000"), length=(I, "Bytes, max 8192"))),
    ("bin_imports", lambda path, arch=None: dx.imports(path, arch),
     "Imported symbols (what the program calls from system libraries).",
     P(path=(S, "", True), arch=(S, ""))),
    ("bin_objc", lambda path, filter=None: dx.objc(path, filter),
     "Objective-C / Swift classes with methods (and their code addresses), ivars and properties, recovered from "
     "metadata even in stripped binaries. Filter by class or selector name.",
     P(path=(S, "", True), filter=(S, "Regex on class or method name"))),
    ("bin_brief", lambda path, address=None, symbol=None: dx.brief(path, address, symbol),
     "Everything needed to explain one function: its disassembly, the strings it uses, the functions and system "
     "APIs it calls (demangled), and who calls it.",
     P(path=(S, "", True), address=(S, "Hex address inside the function"), symbol=(S, "Function or -[Class sel] name"))),
    ("malware_triage", lambda path: mw.analyze(path),
     "Static malware triage of a file or .app (never executed): hashes, file type, entropy/packing, signature, "
     "notarization, entitlements, quarantine flag, capabilities mapped to MITRE ATT&CK, indicators (URLs, domains, "
     "IPs, crypto wallets, webhooks, onion links), YARA hits if installed, and a risk score with reasons.",
     P(path=(S, "File or .app path", True))),
    ("malware_reputation", lambda sha256: mw.reputation(sha256),
     "Look a SHA-256 up on VirusTotal / MalwareBazaar (only the hash is sent; needs keys in Settings).",
     P(sha256=(S, "", True))),
    ("malware_report", lambda path, with_reputation=False: mw.save(mw.analyze(path),
                                                                   mw.reputation(mw.analyze(path)["hashes"]["sha256"]) if with_reputation else None),
     "Run static triage on a file and save a Markdown report into the vault (Malware/), linked to any wallet notes.",
     P(path=(S, "", True), with_reputation=(B, "Also look up the hash online"))),
    # ---- chains
    ("chain_list", lambda: ct.chains(), "Supported chains and whether each needs an Etherscan key.", P()),
    ("chain_detect", lambda query, chain="auto": ct.detect(query, chain),
     "Work out what a string is (address / ENS / tx hash) and which chain it belongs to.",
     P(query=(S, "", True), chain=(S, "Force a chain id"))),
    ("chain_wallet", lambda address, chain="auto": ct.wallet(address, chain),
     "Balance, labels, token holdings, counts and flags (whale, exchange, mixer, fresh, contract, ...) for an address "
     "on any supported chain. EVM addresses auto-pick the most active chain and list the others.",
     P(address=(S, "Address or ENS name", True), chain=(S, "Chain id or 'auto'"))),
    ("chain_activity", lambda address, chain="auto", limit=50: ct.activity(address, chain, limit),
     "Recent transfers in and out (native and tokens), newest first. On Bitcoin/Litecoin, change outputs are marked.",
     P(address=(S, "", True), chain=(S, ""), limit=(I, ""))),
    ("chain_tx", lambda hash, chain="auto": ct.tx(hash, chain),
     "Inspect a transaction on any chain. Bitcoin: inputs/outputs with coin ids, CoinJoin and change detection. "
     "Monero: wallet-software fingerprints (it can't reveal senders or amounts).",
     P(hash=(S, "", True), chain=(S, ""))),
    ("chain_trace", lambda address, chain="auto", hops=2, direction="out", per_hop=5, min_usd=0:
        ct.trace(address, chain=chain, hops=hops, direction=direction, per_hop=per_hop, min_usd=min_usd, labels=vx.labels()),
     "Follow funds hop by hop. direction: out|in|both. Stops at contracts/exchanges/mixers; follows Bitcoin change "
     "as the same owner. Returns nodes (with flags), edges and endpoints (where the money ends up).",
     P(address=(S, "", True), chain=(S, ""), hops=(I, "1-6"), direction=(S, "out|in|both"),
       per_hop=(I, "Counterparties kept per wallet per hop"), min_usd=(N, "Ignore smaller transfers"))),
    ("chain_history", lambda address, chain="auto", max_pages=10: hi.history(address, chain, max_pages),
     "A wallet's history as readable actions: bought / sold / swapped (with what), NFT buys, sells and mints, "
     "contracts and tokens it created, bridges, approvals, sends and receives, plus a summary of everything it "
     "bought, sold, minted and created, its top counterparties, active days and fees. Raise max_pages for older history.",
     P(address=(S, "", True), chain=(S, ""), max_pages=(I, "Pages to read (each ~50-300 transfers); default 10"))),
    # ---- forensics
    ("exposure", lambda address, chain="auto": fx.exposure(address, chain),
     "Mixer/CoinJoin contact, first seen, first funder, contract creator.",
     P(address=(S, "", True), chain=(S, ""))),
    ("utxo_coins", lambda address, chain=None: fx.coins(address, chain=chain),
     "Unspent coins of a Bitcoin/Litecoin address as coin ids (txid:vout) with block, age and origin (mined/CoinJoin/transfer).",
     P(address=(S, "", True), chain=(S, ""))),
    ("utxo_coin", lambda coin_id, chain="bitcoin", depth=3: fx.coin(coin_id, depth, chain),
     "One coin in depth: creating block and the pool that mined it, where it was spent, ancestry back N steps.",
     P(coin_id=(S, "txid:vout", True), chain=(S, ""), depth=(I, ""))),
    ("utxo_change", lambda txid, chain="bitcoin": hx.change_output(txid, chain=chain),
     "Which output of a transaction is the change, with the heuristics that fired and a confidence.",
     P(txid=(S, "", True), chain=(S, ""))),
    ("peel_chain", lambda start, steps=25, chain=None: hx.peel_chain(start, steps, chain),
     "Follow change outputs forward from a txid (or an address's latest spend) and decide if it's a peel chain.",
     P(start=(S, "txid or address", True), steps=(I, ""), chain=(S, ""))),
    ("cluster", lambda address, chain=None: hx.cluster(address, chain=chain),
     "Group addresses one wallet likely controls (common-input ownership + change). CoinJoins are skipped.",
     P(address=(S, "", True), chain=(S, ""))),
    ("sweeps", lambda address, chain="auto": hx.sweeps(address, chain),
     "Is this an exchange deposit address (forwards nearly everything it receives to one place)?",
     P(address=(S, "", True), chain=(S, ""))),
    ("links", lambda address, chain="auto", include_cluster=False: co.links(address, chain, include_cluster),
     "Wallets provably controlled by the same key on other chains (EVM<->all EVM, EVM<->Tron, BTC<->LTC). "
     "Optionally add likely links from clustering.",
     P(address=(S, "", True), chain=(S, ""), include_cluster=(B, ""))),
    ("match_amounts", lambda sources, targets=None, window_hours=72, tolerance_pct=0.5, include_weak=False:
        co.match_amounts(sources, targets, window_hours, tolerance_pct, include_weak=include_weak),
     "Match same-amount transfers leaving `sources` and arriving at `targets` within a time window, across chains. "
     "Round or ambiguous matches are downgraded; weak ones hidden unless include_weak. Use around swaps/mixers.",
     P(sources=(A, "['chain:address', ...]", True), targets=(A, "['chain:address', ...]"),
       window_hours=(N, ""), tolerance_pct=(N, ""), include_weak=(B, ""))),
    ("pass_through", lambda address, chain="auto": co.pass_through(address, chain),
     "Amounts that arrive and leave again nearly unchanged soon after (layering hop).",
     P(address=(S, "", True), chain=(S, ""))),
    # ---- vault
    ("vault_search", lambda query: vx.search(query), "Search notes in the Unwind vault (supports #tag).",
     P(query=(S, "", True))),
    ("vault_read", lambda path: vx.read(path), "Read a vault note with its backlinks.", P(path=(S, "", True))),
    ("vault_write", lambda path, content: vx.write(path, content),
     "Write a Markdown note to the vault (use [[wikilinks]] to link wallets, cases, binaries).",
     P(path=(S, "e.g. Cases/My case.md", True), content=(S, "", True))),
    ("vault_list", lambda: vx.tree(), "List notes and folders in the vault.", P()),
    ("vault_save_wallet", _save_wallet,
     "Look up a wallet (balance, activity, exposure, same-key links) and save/refresh its vault note.",
     P(address=(S, "", True), chain=(S, ""))),
    ("vault_save_trace", _trace_and_save,
     "Run a trace and save it as a case note plus a note per wallet, all linked.",
     P(address=(S, "", True), chain=(S, ""), hops=(I, ""), direction=(S, ""), per_hop=(I, ""),
       min_usd=(N, ""), title=(S, ""))),
]
try:                                   # the user's own APIs (Settings → Connectors)
    import connectors as _cx
    TOOLS += _cx.as_tools()
except Exception as _e:                # a broken connector file must not take the server down
    sys.stderr.write(f"connectors not loaded: {_e}\n")
TOOLMAP = {t[0]: t for t in TOOLS}


def send(o):
    sys.stdout.write(json.dumps(o, default=str) + "\n")
    sys.stdout.flush()


def handle(req):
    m, i = req.get("method"), req.get("id")
    if m == "initialize":
        return send({"jsonrpc": "2.0", "id": i, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "unwind", "version": "0.3.0"}}})
    if m == "tools/list":
        return send({"jsonrpc": "2.0", "id": i, "result": {"tools": [
            {"name": n, "description": d, "inputSchema": s} for n, _, d, s in TOOLS]}})
    if m == "tools/call":
        p = req.get("params") or {}
        t = TOOLMAP.get(p.get("name"))
        if not t:
            return send({"jsonrpc": "2.0", "id": i, "error": {"code": -32602, "message": "unknown tool"}})
        try:
            out = t[1](**(p.get("arguments") or {}))
            text = out if isinstance(out, str) else json.dumps(out, indent=1, default=str)
            if len(text) > MAX:
                text = text[:MAX] + f"\n…[truncated {len(text) - MAX} chars: narrow the query]"
            return send({"jsonrpc": "2.0", "id": i, "result": {"content": [{"type": "text", "text": text}]}})
        except Exception as e:
            return send({"jsonrpc": "2.0", "id": i, "result": {
                "content": [{"type": "text", "text": f"error: {e}"}], "isError": True}})
    if m == "ping":
        return send({"jsonrpc": "2.0", "id": i, "result": {}})
    if i is not None and not (m or "").startswith("notifications/"):
        send({"jsonrpc": "2.0", "id": i, "error": {"code": -32601, "message": f"method not found: {m}"}})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            handle(req)
        except Exception as e:
            sys.stderr.write(f"unwind mcp error: {e}\n")


if __name__ == "__main__":
    main()
