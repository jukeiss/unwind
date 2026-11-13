"""
history - a wallet's complete history, turned into readable actions.

Raw transfers (native, tokens, NFTs, internal) are grouped by transaction and
classified from the wallet's point of view:

  bought / sold / swapped     gave one asset, got another in the same tx
  nft_buy / nft_sell          NFT in for payment out, or the reverse
  mint                        new token/NFT arrived from the zero address
  create                      the wallet deployed a contract (or a token)
  bridge                      value sent to a known bridge
  approve                     token approval
  receive / send / self       plain transfers
  mined                       block reward (UTXO chains)
  airdrop                     unsolicited spam-looking token
  call                        contract interaction with no value moved

`summary()` rolls the actions up into what the wallet bought, sold, minted,
created, who it dealt with most, when it was active and what it paid in fees.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

import chaintrace as ct

ZERO = re.compile(r"^(0x0{40}|0x0{39}dead|0x000000000000000000000000000000000000dead|11111111111111111111111111111111)$", re.I)
APPROVE = re.compile(r"approve|setapprovalforall|permit", re.I)
STABLE = {"USDT", "USDC", "DAI", "USDE", "FDUSD", "PYUSD", "TUSD", "USDS", "USDC.E", "USDT0", "BUSD"}


def _val(x):
    return x.get("usd") or 0


def _fmt(x):
    if not x:
        return ""
    a = x.get("amount") or 0
    s = f"{a:.2e}" if a >= 1e12 else f"{a:,.0f}" if a >= 1000 else f"{a:,.4f}".rstrip("0").rstrip(".") if a >= 0.0001 else f"{a:.2e}"
    name = x.get("asset") or "?"
    if x.get("kind") == "nft":
        tid = x.get("token_id")
        return f"{name.replace(' NFT', '')}{' #' + str(tid)[:10] if tid else ''}"
    return f"{s} {name}"


def classify(items, address):
    """Group transfers by transaction and describe each from `address`'s side."""
    me = (address or "").lower()
    groups = defaultdict(list)
    for x in items:
        if x.get("hash"):
            groups[x["hash"]].append(x)
    actions = []
    for h, g in groups.items():
        g = [x for x in g if not (x.get("internal") and x.get("amount") == 0)]
        if not g:
            continue
        t = max((x.get("time") for x in g if x.get("time")), default=None)
        chain = g[0].get("chain")
        moves = [x for x in g if x.get("kind") in ("native", "token", "nft") and (x.get("amount") or 0) > 0
                 and x.get("direction") in ("in", "out")]
        ins = [x for x in moves if x["direction"] == "in"]
        outs = [x for x in moves if x["direction"] == "out" and not x.get("change")]
        calls = [x for x in g if x.get("kind") == "call"]
        method = next((x.get("method") for x in g if x.get("method")), None)
        fee = next((x.get("fee") for x in g if x.get("fee")), None)
        status = next((x.get("status") for x in g if x.get("status") not in (None, "ok", "confirmed")), "ok")
        created = next((x.get("created_contract") for x in g if x.get("created_contract")
                        and (x.get("from") or "").lower() == me), None)
        nft_in = [x for x in ins if x["kind"] == "nft"]
        nft_out = [x for x in outs if x["kind"] == "nft"]
        val_in = [x for x in ins if x["kind"] != "nft"]
        val_out = [x for x in outs if x["kind"] != "nft"]
        spam = bool(ins) and all(x.get("spam") for x in ins) and not outs
        a = {"hash": h, "time": t, "chain": chain, "fee": fee, "status": status, "method": method,
             "in": [_slim(x) for x in ins], "out": [_slim(x) for x in outs],
             "counterparty": None, "counterparty_label": None, "usd": None}

        def cp(xs):
            x = max(xs, key=_val) if xs else None
            if x:
                a["counterparty"], a["counterparty_label"] = x.get("counterparty"), x.get("counterparty_label")

        if created:
            made_tokens = [x for x in ins if (x.get("token_contract") or "").lower() == created.lower()]
            a.update(type="create", title=("Created token " + made_tokens[0]["asset"]) if made_tokens
                     else "Created a contract" + (f" ({g[0].get('created_name')})" if g[0].get("created_name") else ""),
                     created=created)
        elif any(x.get("mined") for x in ins):
            a.update(type="mined", title=f"Mined a block reward: {_fmt(ins[0])}", usd=sum(_val(x) for x in ins))
        elif nft_in and val_out:
            pay = max(val_out, key=_val)
            mint = all(ZERO.match(x.get("counterparty") or "") for x in nft_in)
            a.update(type="mint" if mint else "nft_buy",
                     title=(f"Minted {_fmt(nft_in[0])}" if mint else f"Bought {_fmt(nft_in[0])}")
                     + (f" (+{len(nft_in) - 1} more)" if len(nft_in) > 1 else "") + f" for {_fmt(pay)}",
                     usd=sum(_val(x) for x in val_out))
            cp(val_out)
        elif nft_out and val_in:
            got = max(val_in, key=_val)
            a.update(type="nft_sell", title=f"Sold {_fmt(nft_out[0])}" + (f" (+{len(nft_out) - 1} more)" if len(nft_out) > 1 else "")
                     + f" for {_fmt(got)}", usd=sum(_val(x) for x in val_in))
            cp(val_in)
        elif nft_in and all(ZERO.match(x.get("counterparty") or "") for x in nft_in):
            a.update(type="mint", title=f"Minted {_fmt(nft_in[0])}" + (f" (+{len(nft_in) - 1} more)" if len(nft_in) > 1 else ""))
        elif val_in and val_out and {x["asset"] for x in val_in} != {x["asset"] for x in val_out}:
            got = max(val_in, key=lambda x: (_val(x), x["amount"]))
            gave = max(val_out, key=lambda x: (_val(x), x["amount"]))
            usd = _val(got) or _val(gave) or None
            gave_stable = gave["asset"].upper() in STABLE or gave["asset"] in ("ETH", "SOL", "BNB", "BTC", "POL", "AVAX")
            got_stable = got["asset"].upper() in STABLE
            kind = "bought" if gave_stable and not got_stable else "sold" if got_stable and not gave_stable else "swap"
            verb = {"bought": "Bought", "sold": "Sold", "swap": "Swapped"}[kind]
            title = (f"Bought {_fmt(got)} with {_fmt(gave)}" if kind == "bought" else
                     f"Sold {_fmt(gave)} for {_fmt(got)}" if kind == "sold" else
                     f"{verb} {_fmt(gave)} for {_fmt(got)}")
            a.update(type=kind, title=title, usd=usd, got=_slim(got), gave=_slim(gave))
            cp(val_out)
        elif val_in and not outs:
            x = max(val_in, key=lambda x: (_val(x), x["amount"]))
            if spam:
                a.update(type="airdrop", title=f"Spam airdrop: {_fmt(x)}")
            elif ZERO.match(x.get("counterparty") or "") and x["kind"] == "token":
                a.update(type="mint", title=f"Minted {_fmt(x)}", usd=_val(x) or None)
            else:
                a.update(type="receive", title=f"Received {_fmt(x)}" + (f" + {len(val_in) - 1} more" if len(val_in) > 1 else ""),
                         usd=sum(_val(y) for y in val_in) or None)
            cp(val_in)
        elif nft_in:
            a.update(type="receive", title=f"Received {_fmt(nft_in[0])}" + (f" (+{len(nft_in) - 1} more)" if len(nft_in) > 1 else ""))
            cp(nft_in)
        elif outs and not ins:
            x = max(outs, key=lambda x: (_val(x), x["amount"]))
            lab = " ".join(filter(None, [x.get("counterparty_label") or ""]))
            if ct.BRIDGE_RX.search(lab):
                a.update(type="bridge", title=f"Bridged {_fmt(x)} via {lab}", usd=_val(x) or None)
            elif x["kind"] == "nft" and ZERO.match(x.get("counterparty") or ""):
                a.update(type="burn", title=f"Burned {_fmt(x)}")
            else:
                a.update(type="send", title=f"Sent {_fmt(x)}" + (f" + {len(outs) - 1} more" if len(outs) > 1 else ""),
                         usd=sum(_val(y) for y in outs) or None)
            cp(outs)
        elif method and APPROVE.search(method):
            a.update(type="approve", title=f"Approved {_short(calls[0].get('counterparty') or calls[0].get('to') or '')} to spend tokens")
            a["counterparty"] = calls[0].get("to") if calls else None
        elif any(x.get("direction") == "self" for x in g):
            a.update(type="self", title="Moved coins between own outputs")
        else:
            x = calls[0] if calls else g[0]
            a.update(type="call", title=f"Called {method or 'a contract'}" + (f" on {x.get('counterparty_label')}" if x.get("counterparty_label") else ""))
            a["counterparty"], a["counterparty_label"] = x.get("counterparty") or x.get("to"), x.get("counterparty_label")
        if status not in ("ok", "confirmed", "success", None):
            a["title"] = "Failed: " + a["title"]
            a["failed"] = True
        actions.append(a)
    actions.sort(key=lambda a: ct._ts(a.get("time")), reverse=True)
    return actions


def _short(a):
    return a if len(a) <= 14 else f"{a[:6]}…{a[-4:]}"


def _slim(x):
    return {k: x.get(k) for k in ("asset", "amount", "usd", "kind", "token_id", "token_contract", "token_name",
                                  "counterparty", "counterparty_label", "image")}


def summary(actions, items):
    """Roll actions up: what was bought, sold, minted, created; who they dealt with; when; fees."""
    bought, sold = defaultdict(lambda: {"amount": 0.0, "usd": 0.0, "count": 0}), defaultdict(lambda: {"amount": 0.0, "usd": 0.0, "count": 0})
    nfts, created, days = [], [], Counter()
    types = Counter(a["type"] for a in actions)
    fees = sum(a.get("fee") or 0 for a in actions)
    for a in actions:
        if a.get("time"):
            days[str(a["time"])[:10]] += 1
        if a["type"] in ("bought", "swap") and a.get("got"):
            g = bought[a["got"]["asset"]]
            g["amount"] += a["got"]["amount"] or 0
            g["usd"] += a["got"].get("usd") or 0
            g["count"] += 1
        if a["type"] in ("sold", "swap") and a.get("gave"):
            g = sold[a["gave"]["asset"]]
            g["amount"] += a["gave"]["amount"] or 0
            g["usd"] += a["gave"].get("usd") or 0
            g["count"] += 1
        if a["type"] in ("nft_buy", "mint", "nft_sell") and (a["in"] or a["out"]):
            n = next((x for x in (a["in"] + a["out"]) if x["kind"] == "nft"), None)
            if n:
                nfts.append({"type": a["type"], "name": (n.get("token_name") or n["asset"]).replace(" NFT", ""),
                             "token_id": n.get("token_id"), "contract": n.get("token_contract"),
                             "image": n.get("image"), "hash": a["hash"], "time": a["time"], "usd": a.get("usd")})
        if a["type"] == "create":
            created.append({"contract": a.get("created"), "title": a["title"], "hash": a["hash"], "time": a["time"]})
    flows = defaultdict(lambda: {"in": 0.0, "out": 0.0, "in_usd": 0.0, "out_usd": 0.0, "count": 0})
    peers = defaultdict(lambda: {"in_usd": 0.0, "out_usd": 0.0, "count": 0, "label": None})
    for x in items:
        if x.get("spam") or x.get("kind") not in ("native", "token") or not x.get("amount"):
            continue
        f = flows[x["asset"]]
        f["in" if x["direction"] == "in" else "out"] += x["amount"] if x["direction"] in ("in", "out") else 0
        f["in_usd" if x["direction"] == "in" else "out_usd"] += x.get("usd") or 0
        f["count"] += 1
        if x.get("counterparty") and not x.get("change"):
            p = peers[x["counterparty"]]
            p["in_usd" if x["direction"] == "in" else "out_usd"] += x.get("usd") or 0
            p["count"] += 1
            p["label"] = p["label"] or x.get("counterparty_label")
    times = sorted(ct._ts(a["time"]) for a in actions if a.get("time"))
    iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z") if ts else None  # noqa: E731
    top = lambda d: sorted(({"asset": k, **v} for k, v in d.items()), key=lambda r: (-r["usd"], -r["count"]))[:15]  # noqa: E731
    return {
        "actions": len(actions), "by_type": dict(types), "fees": fees,
        "first": iso(times[0]) if times else None, "last": iso(times[-1]) if times else None,
        "active_days": len(days), "days": dict(days),
        "bought": top(bought), "sold": top(sold), "nfts": nfts[:200], "created": created,
        "flows": sorted(({"asset": k, **v} for k, v in flows.items()), key=lambda r: -(r["in_usd"] + r["out_usd"]))[:20],
        "peers": sorted(({"address": k, **v} for k, v in peers.items()), key=lambda r: -(r["in_usd"] + r["out_usd"] + r["count"]))[:25],
    }


def page(address, chain="auto", cursor=None, pages=1):
    """Load the next `pages` pages of raw history. Returns items plus the cursor to continue."""
    d = ct.detect(address, chain)
    a = d["value"]
    cid, _ = ct._pick_chain(a, d["chain"])
    c = ct.get_chain(cid)
    items, cur = [], cursor
    for _ in range(max(1, min(int(pages), 20))):
        r = c.page(a, cur)
        items += r["items"]
        cur = r.get("cursor")
        if not cur:
            break
    return {"address": a, "chain": cid, "symbol": c.symbol, "items": items, "cursor": cur, "done": cur is None}


def analyze(address, items):
    """Classify a set of already-loaded transfers and summarise them."""
    acts = classify(items, address)
    return {"actions": acts, "summary": summary(acts, items)}


def history(address, chain="auto", max_pages=10):
    """Everything in one call (used by the MCP server): load up to max_pages, classify, summarise."""
    p = page(address, chain, None, max_pages)
    out = analyze(p["address"], p["items"])
    out.update({"address": p["address"], "chain": p["chain"], "complete": p["done"],
                "transfers_loaded": len(p["items"])})
    out["actions"] = out["actions"][:500]
    return out


API = {"page": page, "analyze": analyze, "history": history}
