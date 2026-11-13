"""
heuristics - chain-analysis algorithms for Unwind.

Bitcoin
  change_output(tx)    Which output is the sender's change? Scores each output
                       with the standard heuristics and explains its choice:
                         - address reuse (output goes back to an input address)
                         - script-type match (same type as the inputs)
                         - round-number payment (the payment is round, change isn't)
                         - unnecessary input / optimal change
                         - fresh address (first use), when known
  peel_chain(start)    Follows change outputs forward and reports a peel chain:
                       a large balance shedding small payments hop after hop.
  cluster(address)     Groups addresses one entity likely controls, using
                       common-input-ownership plus high-confidence change.
                       CoinJoins are skipped because they break that rule.

EVM
  sweeps(address)      Detects deposit-address behaviour: incoming funds
                       forwarded almost entirely to one destination soon after.

These are probabilistic. Every result says which rules fired and how sure it is.
"""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import chaintrace as ct

def _api(chain):
    c = ct.get_chain(chain or "bitcoin")
    if c.kind != "utxo":
        raise ValueError(f"{c.name} is not a UTXO chain; this analysis works on Bitcoin, Litecoin and testnet")
    return c.api


def _utxo_chain(address_or_tx, chain=None):
    if chain and chain != "auto":
        return chain
    cands = ct.classify_address((address_or_tx or "").strip())
    for c in cands:
        if c in ct.REG and ct.REG[c].kind == "utxo":
            return c
    return "bitcoin"


def _tx(txid, chain="bitcoin"):
    t = ct._get(f"{_api(chain)}/tx/{txid}", ttl=3600)
    if not t:
        raise ValueError(f"transaction {txid[:12]}… not found")
    return t


def _is_coinjoin(t):
    # local import to avoid a cycle (forensics imports chaintrace too)
    import forensics
    return forensics.coinjoin(t).get("coinjoin", False)


def _roundness(sats):
    """0 = not round, 1 = somewhat round, 2 = very round."""
    if sats <= 0:
        return 0
    if sats % 1_000_000 == 0:      # 0.01 BTC steps
        return 2
    if sats % 100_000 == 0:        # 0.001 BTC steps
        return 2
    if sats % 10_000 == 0:
        return 1
    return 0


# ------------------------------------------------------------------ change

def change_output(t, fresh=None, chain="bitcoin"):
    """
    Guess the change output of a Bitcoin transaction.
    `t` is an Esplora tx dict or txid. `fresh` optionally maps address -> bool (first use).
    Returns None when there is no defensible guess.
    """
    if isinstance(t, str):
        t = _tx(t, chain)
    vin, vout = t.get("vin", []), t.get("vout", [])
    if not vin or any(v.get("is_coinbase") for v in vin):
        return None
    outs = [(i, o) for i, o in enumerate(vout) if o.get("scriptpubkey_address")]
    if len(outs) < 2 or len(outs) > 6:
        return None
    if _is_coinjoin(t):
        return None
    ins = [(v.get("prevout") or {}) for v in vin]
    in_addrs = {p.get("scriptpubkey_address") for p in ins}
    in_types = {p.get("scriptpubkey_type") for p in ins}
    in_vals = [p.get("value", 0) for p in ins]
    total_in, min_in = sum(in_vals), min(in_vals) if in_vals else 0
    fee = t.get("fee", 0)

    scored = []
    for i, o in outs:
        s, why = 0, []
        addr, val, typ = o["scriptpubkey_address"], o.get("value", 0), o.get("scriptpubkey_type")
        others = [x for j, x in outs if j != i]
        if addr in in_addrs:
            s += 3
            why.append("goes back to an input address (address reuse)")
        if len(in_types) == 1 and typ in in_types and any(x.get("scriptpubkey_type") != typ for x in others):
            s += 1
            why.append(f"same script type as the inputs ({typ})")
        if _roundness(val) == 0 and others and all(_roundness(x.get("value", 0)) >= 1 for x in others):
            s += 1
            why.append("the other output is a round amount, this one isn't")
        payment = sum(x.get("value", 0) for x in others)
        if len(in_vals) > 1:
            consistent = total_in - min_in < payment + fee           # every input was needed
            alt_ok = total_in - min_in < val + fee                    # if THIS were the payment
            if consistent and not alt_ok:
                s += 1
                why.append("treating the other output as the payment means no input was unnecessary")
        if fresh and fresh.get(addr):
            s += 1
            why.append("first time this address is used")
        scored.append((s, i, addr, val, why))

    scored.sort(key=lambda x: -x[0])
    best = scored[0]
    if best[0] < 1 or (len(scored) > 1 and scored[1][0] == best[0]):
        return None
    conf = "high" if best[0] >= 3 else ("medium" if best[0] == 2 else "low")
    return {"index": best[1], "address": best[2], "value": best[3] / 1e8,
            "score": best[0], "confidence": conf, "reasons": best[4]}


# ------------------------------------------------------------------ peel chain

def peel_chain(start, steps=25, chain=None):
    """
    Follow a peel chain from a txid, or from an address's latest spend.
    A peel chain is a run of transactions with one or two inputs and two
    outputs, where a small payment is "peeled" off and the large change moves on.
    """
    start = (start or "").strip()
    chain = _utxo_chain(start, chain)
    api = _api(chain)
    is_addr = bool(ct.classify_address(start)) and ct.REG.get(ct.classify_address(start)[0]) is not None
    if is_addr:
        txs = ct._get(f"{api}/address/{start}/txs") or []
        spends = [t for t in txs if any((v.get("prevout") or {}).get("scriptpubkey_address") == start
                                         for v in t.get("vin", []))]
        if not spends:
            raise ValueError("this address has no outgoing transactions to start from")
        cur = spends[-1] if len(spends) > 1 else spends[0]   # oldest of the recent page
    elif ct.BTC_TX.match(start):
        cur = _tx(start.lower(), chain)
    else:
        raise ValueError("start must be a Bitcoin/Litecoin address or transaction id")

    price = ct.native_price(chain)
    hops, stop = [], "reached step limit"
    start_val = None
    for n in range(int(steps)):
        vin, vout = cur.get("vin", []), cur.get("vout", [])
        if len(vin) > 3:
            stop = f"merged {len(vin)} inputs (pattern broke)"
            break
        if not (2 <= len(vout) <= 3):
            stop = f"{len(vout)} outputs (pattern broke)"
            break
        ch = change_output(cur, chain=chain)
        if not ch:
            stop = "no clear change output"
            break
        peels = [{"address": o.get("scriptpubkey_address"), "value": o.get("value", 0) / 1e8}
                 for i, o in enumerate(vout) if i != ch["index"]]
        peel_total = sum(p["value"] for p in peels)
        st = cur.get("status", {})
        if start_val is None:
            start_val = ch["value"] + peel_total
        hops.append({"step": n + 1, "txid": cur["txid"], "time": ct._iso(st.get("block_time")),
                     "height": st.get("block_height"), "peeled": peels, "peel_total": peel_total,
                     "change": ch["value"], "change_address": ch["address"],
                     "change_confidence": ch["confidence"], "ratio": (ch["value"] / peel_total) if peel_total else None})
        sp = ct._get(f"{api}/tx/{cur['txid']}/outspend/{ch['index']}", ttl=120) or {}
        if not sp.get("spent"):
            stop = "change is still unspent (end of chain)"
            break
        try:
            cur = _tx(sp["txid"], chain)
        except Exception:
            stop = "could not load next transaction"
            break

    ratios = sorted(h["ratio"] for h in hops if h["ratio"])
    median = ratios[len(ratios) // 2] if ratios else 0
    is_peel = len(hops) >= 3 and median >= 2
    dest = Counter()
    for h in hops:
        for p in h["peeled"]:
            dest[p["address"]] += p["value"]
    peeled = sum(h["peel_total"] for h in hops)
    return {"start": start, "chain": chain, "symbol": ct.REG[chain].symbol, "is_peel_chain": is_peel, "length": len(hops),
            "confidence": "high" if is_peel and len(hops) >= 6 else ("medium" if is_peel else "low"),
            "start_value": start_val, "end_value": hops[-1]["change"] if hops else None,
            "total_peeled": peeled, "total_peeled_usd": peeled * price if price else None,
            "median_change_to_peel": median, "stopped_because": stop,
            "top_destinations": [{"address": a, "value": v} for a, v in dest.most_common(10)],
            "hops": hops}


# ------------------------------------------------------------------ clustering

def cluster(address, max_addresses=150, max_scan=30, use_change=True, chain=None):
    """
    Common-input-ownership clustering: addresses spent together in one
    (non-CoinJoin) transaction are very likely controlled by the same wallet.
    Optionally also links high-confidence change outputs.
    """
    address = (address or "").strip()
    chain = _utxo_chain(address, chain)
    api = _api(chain)
    members = {address: {"address": address, "reason": "start", "via": None, "depth": 0}}
    queue, scanned, skipped_cj, txs_seen = [address], 0, 0, set()

    def load(a):
        try:
            return a, ct._get(f"{api}/address/{a}/txs") or []
        except Exception:
            return a, []

    while queue and scanned < max_scan and len(members) < max_addresses:
        batch, queue = queue[:6], queue[6:]
        with ThreadPoolExecutor(max_workers=6) as ex:
            loaded = list(ex.map(load, batch))
        scanned += len(batch)
        for a, txs in loaded:
            depth = members[a]["depth"] + 1
            for t in txs:
                if t["txid"] in txs_seen:
                    continue
                ins = [(v.get("prevout") or {}).get("scriptpubkey_address") for v in t.get("vin", [])]
                if a not in ins:
                    continue
                txs_seen.add(t["txid"])
                if _is_coinjoin(t):
                    skipped_cj += 1
                    continue
                for x in ins:
                    if x and x not in members and len(members) < max_addresses:
                        members[x] = {"address": x, "reason": "co-spent input", "via": t["txid"], "depth": depth}
                        queue.append(x)
                if use_change:
                    ch = change_output(t, chain=chain)
                    if ch and ch["confidence"] in ("high", "medium") and ch["address"] not in members:
                        members[ch["address"]] = {"address": ch["address"], "reason": f"change ({ch['confidence']})",
                                                  "via": t["txid"], "depth": depth}
                        queue.append(ch["address"])
    return {"address": address, "chain": chain, "size": len(members), "addresses": list(members.values()),
            "scanned_addresses": scanned, "transactions_used": len(txs_seen),
            "coinjoins_skipped": skipped_cj,
            "truncated": bool(queue) or len(members) >= max_addresses,
            "method": "common-input-ownership" + (" + change detection" if use_change else "")}


# ------------------------------------------------------------------ EVM sweeps

def sweeps(address, chain="auto", window_hours=48):
    """Does this address forward what it receives to one place? (deposit-address pattern)"""
    act = ct.activity(address, chain, limit=150)
    items = [x for x in act["items"] if x.get("kind") in ("native", "token") and x.get("amount")]
    ins = [x for x in items if x["direction"] == "in"]
    outs = [x for x in items if x["direction"] == "out"]
    if not ins:
        return {"address": act["address"], "chain": act["chain"], "pattern": "no incoming transfers"}
    matched, dest = 0, Counter()
    win = window_hours * 3600
    for i in ins:
        ti = ct._ts(i["time"])
        for o in outs:
            to = ct._ts(o["time"])
            if o["asset"] == i["asset"] and 0 <= to - ti <= win and o["amount"] >= i["amount"] * 0.9:
                matched += 1
                dest[o["counterparty"]] += 1
                break
    share = matched / len(ins)
    top = dest.most_common(1)[0] if dest else (None, 0)
    concentrated = top[1] >= max(2, matched * 0.7)
    is_dep = share >= 0.7 and concentrated and len(ins) >= 3
    return {"address": act["address"], "chain": act["chain"],
            "pattern": "deposit / forwarding address" if is_dep else
                       ("partial forwarding" if share >= 0.4 else "holds what it receives"),
            "forwarded_share": round(share, 2), "incoming_checked": len(ins),
            "main_destination": top[0], "main_destination_count": top[1],
            "is_deposit_address": is_dep,
            "explanation": f"{matched} of {len(ins)} incoming transfers were sent on within "
                           f"{window_hours}h for at least 90% of the amount"}


API = {"change": change_output, "peel": peel_chain, "cluster": cluster, "sweeps": sweeps}
