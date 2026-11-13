"""
correlate - link wallets and match amounts across chains, with false-positive control.

  links(address)            Wallets that are provably the same key on other chains:
                              EVM address  <-> every EVM chain        (certain for wallets)
                              EVM address  <-> Tron address           (same 20-byte key hash)
                              BTC address  <-> LTC address            (same key hash / witness program)
                            Plus "likely" links from common-input clustering when asked.

  match_amounts(src, dst)   Pairs outgoing transfers from `src` wallets with incoming
                            transfers to `dst` wallets that carry the same amount within a
                            time window. Built to avoid false positives:
                              - round amounts (1000 USDT, 0.5 BTC) count as weak evidence
                              - a match is only "strong" if it is near-exact, non-round,
                                AND the only candidate on both sides
                              - ambiguous matches are reported as ambiguous, never picked
                              - weak matches are hidden unless you ask for them
                            Use it on the transparent sides of a swap, bridge or mixer
                            (e.g. BTC into a BTC->XMR swap, then XMR->BTC out the other side).

  pass_through(address)     Funds that arrive and leave again in nearly the same amount
                            shortly after: the wallet is a hop, not a destination.
"""
import math
import re
from concurrent.futures import ThreadPoolExecutor

import chaintrace as ct

# ------------------------------------------------------------------ bech32 (BIP-173 / BIP-350)

_CS = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values):
    gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _convertbits(data, frm, to, pad=True):
    acc, bits, ret, maxv = 0, 0, [], (1 << to) - 1
    for v in data:
        acc = (acc << frm) | v
        bits += frm
        while bits >= to:
            bits -= to
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (to - bits)) & maxv)
    elif not pad and (bits >= frm or ((acc << (to - bits)) & maxv)):
        return None
    return ret


def bech32_decode(addr):
    addr = addr.lower()
    pos = addr.rfind("1")
    if pos < 1:
        return None
    hrp, data = addr[:pos], [_CS.find(c) for c in addr[pos + 1:]]
    if -1 in data or len(data) < 7:
        return None
    const = _polymod(_hrp_expand(hrp) + data)
    if const not in (1, 0x2bc830a3):
        return None
    ver = data[0]
    prog = _convertbits(data[1:-6], 5, 8, False)
    if prog is None:
        return None
    return hrp, ver, bytes(prog)


def bech32_encode(hrp, ver, prog):
    const = 1 if ver == 0 else 0x2bc830a3
    data = [ver] + _convertbits(prog, 8, 5)
    poly = _polymod(_hrp_expand(hrp) + data + [0] * 6) ^ const
    chk = [(poly >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CS[d] for d in data + chk)


def _b58c(version, payload):
    import hashlib
    b = bytes([version]) + payload
    return ct.b58encode(b + hashlib.sha256(hashlib.sha256(b).digest()).digest()[:4])


# ------------------------------------------------------------------ same-key links

def _equivalents(address):
    """Addresses on other chains controlled by exactly the same key/script."""
    a = address.strip()
    out = []
    if ct.EVM_ADDR.match(a):
        out.append(("tron", _b58c(0x41, bytes.fromhex(a[2:])), "same 20-byte key hash (EVM <-> Tron)"))
        return out
    body = ct.b58check(a)
    if body and a.startswith("T") and body[0] == 0x41:
        out.append(("evm", "0x" + body[1:].hex(), "same 20-byte key hash (Tron <-> EVM)"))
        return out
    if body:
        v, h = body[0], body[1:]
        if v == 0x00:
            out.append(("litecoin", _b58c(0x30, h), "same public key hash (P2PKH)"))
        elif v == 0x30:
            out.append(("bitcoin", _b58c(0x00, h), "same public key hash (P2PKH)"))
        elif v == 0x05:
            out.append(("litecoin", _b58c(0x32, h), "same script hash (P2SH)"))
        elif v == 0x32:
            out.append(("bitcoin", _b58c(0x05, h), "same script hash (P2SH)"))
        return out
    dec = bech32_decode(a)
    if dec:
        hrp, ver, prog = dec
        if hrp == "bc":
            out.append(("litecoin", bech32_encode("ltc", ver, prog), f"same witness program (v{ver})"))
        elif hrp == "ltc":
            out.append(("bitcoin", bech32_encode("bc", ver, prog), f"same witness program (v{ver})"))
    return out


def _activity_score(chain, addr):
    try:
        c = ct.REG[chain]
        if not c.available:
            return None
        if c.kind == "utxo":
            return (c.lite(addr) or {}).get("tx_count", 0)
        return c.exists(addr)
    except Exception:
        return None


def links(address, chain="auto", include_cluster=False):
    """Wallets on other chains that the same key controls (certain), plus optional clustered ones (likely)."""
    d = ct.detect(address, chain)
    if d["type"] != "address":
        raise ValueError("links need an address")
    a = d["value"]
    res = {"address": a, "links": [], "notes": []}

    if ct.EVM_ADDR.match(a):
        home, active = ct._pick_chain(a, "auto")
        is_contract = False
        try:
            is_contract = (ct.REG[home].lite(a) or {}).get("kind") == "contract"
        except Exception:
            pass
        for x in active or []:
            res["links"].append({"chain": x["chain"], "chain_name": x["name"], "address": a,
                                 "relation": "same address on another EVM chain",
                                 "certainty": "likely" if is_contract else "certain",
                                 "why": ("Contracts can share an address across chains while being different "
                                         "deployments." if is_contract else
                                         "An EVM address is derived from one private key; the same address "
                                         "on any EVM chain is the same key.")})
        if not ct.REG["ethereum"].available:
            pass
        locked = [c.name for c in ct.REG.values() if c.family == "etherscan" and not c.available]
        if locked:
            res["notes"].append(f"{len(locked)} EVM chains weren't checked (add an Etherscan key): "
                                + ", ".join(locked[:8]) + ("…" if len(locked) > 8 else ""))

    for chain_id, eq, why in _equivalents(a):
        if chain_id == "evm":
            home, active = ct._pick_chain(eq, "auto")
            for x in active or []:
                res["links"].append({"chain": x["chain"], "chain_name": x["name"], "address": eq,
                                     "relation": why, "certainty": "certain",
                                     "why": "Tron and EVM addresses are the same 20-byte hash of one key, "
                                            "just encoded differently."})
            continue
        score = _activity_score(chain_id, eq)
        if score:
            cert = "certain" if "P2SH" not in why else "likely"
            res["links"].append({"chain": chain_id, "chain_name": ct.REG[chain_id].name, "address": eq,
                                 "relation": why, "certainty": cert,
                                 "why": ("The same private key controls both addresses." if cert == "certain" else
                                         "Same redeem script hash: same keys and script, almost always the "
                                         "same owner (multisig setups can be shared).")})
        elif score == 0:
            res["notes"].append(f"Same key on {ct.REG[chain_id].name} ({eq}) has never been used.")

    if include_cluster:
        cands = ct.classify_address(a)
        if cands and ct.REG.get(cands[0]) and ct.REG[cands[0]].kind == "utxo":
            import heuristics
            cl = heuristics.cluster(a, chain=cands[0], max_addresses=60, max_scan=15)
            for m in cl["addresses"][1:]:
                res["links"].append({"chain": cl["chain"], "chain_name": ct.REG[cl["chain"]].name,
                                     "address": m["address"],
                                     "relation": m["reason"], "certainty": "likely", "via": m["via"],
                                     "why": "Spent together with this wallet's coins in one transaction "
                                            "(common-input ownership), or its high-confidence change."})
            if cl.get("truncated"):
                res["notes"].append("Cluster was cut short; there may be more addresses.")
    res["certain"] = sum(1 for l in res["links"] if l["certainty"] == "certain")
    res["likely"] = sum(1 for l in res["links"] if l["certainty"] == "likely")
    return res


# ------------------------------------------------------------------ amount matching

_ASSET_ALIASES = {"USDT0": "USDT", "USD₮": "USDT", "USD₮0": "USDT", "USDC.E": "USDC", "WETH": "ETH",
                  "WBTC": "BTC", "BTCB": "BTC", "CBBTC": "BTC", "WSOL": "SOL", "WBNB": "BNB"}


def _norm_asset(s):
    s = (s or "").upper().replace(" NFT", "")
    return _ASSET_ALIASES.get(s, s)


def sig_digits(x):
    """Significant digits of an amount: 1000 -> 1, 0.5 -> 1, 1234.5678 -> 8."""
    if not x:
        return 0
    s = f"{abs(x):.8f}".rstrip("0").rstrip(".")      # "1000", "0.5", "1234.5678"
    digits = s.replace(".", "").lstrip("0")          # "1000", "5", "12345678"
    return len(digits.rstrip("0")) or 1


def is_round(x, asset=None):
    """Round numbers are common, so a match on them proves little."""
    if not x:
        return True
    if sig_digits(x) <= 2:
        return True
    a = _norm_asset(asset)
    if a in ("USDT", "USDC", "DAI", "USD") and abs(x - round(x)) < 1e-9 and sig_digits(x) <= 3:
        return True
    return False


def _parse_targets(items):
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append((it.get("chain") or "auto", it["address"]))
        else:
            s = str(it).strip()
            if ":" in s and s.split(":", 1)[0] in ct.REG:
                c, a = s.split(":", 1)
                out.append((c, a))
            else:
                out.append(("auto", s))
    return out


def _load(chain, address, limit):
    try:
        act = ct.activity(address, chain, limit=limit)
        return [dict(x, _wallet=act["address"], _chain=act["chain"]) for x in act["items"]
                if x.get("kind") in ("native", "token") and (x.get("amount") or 0) > 0 and not x.get("spam")]
    except Exception as e:
        return e


def match_amounts(sources, targets=None, window_hours=72, tolerance_pct=0.5, min_usd=20,
                  include_weak=False, limit=100):
    """
    Find transfers leaving `sources` and arriving at `targets` with the same amount
    inside a time window. Each result says why it matched and how unique it is.
    `sources` / `targets`: lists like ["bitcoin:bc1q...", "0xabc...", {"chain": "tron", "address": "T..."}].
    """
    src, dst = _parse_targets(sources), _parse_targets(targets or sources)
    if not src:
        raise ValueError("give at least one source wallet")
    tol = max(0.0, float(tolerance_pct)) / 100
    win = float(window_hours) * 3600
    errors = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        sl = list(ex.map(lambda t: (t, _load(t[0], t[1], limit)), src))
        dl = list(ex.map(lambda t: (t, _load(t[0], t[1], limit)), dst))
    outs, ins = [], []
    for (c, a), r in sl:
        if isinstance(r, Exception):
            errors.append(f"{a[:12]}…: {r}")
            continue
        outs += [x for x in r if x["direction"] == "out"]
    for (c, a), r in dl:
        if isinstance(r, Exception):
            errors.append(f"{a[:12]}…: {r}")
            continue
        ins += [x for x in r if x["direction"] == "in"]

    cands = []
    for o in outs:
        to = ct._ts(o["time"])
        for i in ins:
            if i["hash"] == o["hash"] and i["_chain"] == o["_chain"]:
                continue        # same transaction: that's a direct transfer, not a correlation
            if i["_wallet"].lower() == o["_wallet"].lower() and i["_chain"] == o["_chain"]:
                continue
            ti = ct._ts(i["time"])
            gap = ti - to
            if gap < -300 or gap > win:
                continue
            same = _norm_asset(o["asset"]) == _norm_asset(i["asset"])
            if same:
                base = o["amount"]
                diff = abs(i["amount"] - o["amount"]) / base if base else 1
            else:
                if not (o.get("usd") and i.get("usd")):
                    continue
                diff = abs(i["usd"] - o["usd"]) / o["usd"]
            if diff > tol:
                continue
            usd = o.get("usd") or i.get("usd")
            if min_usd and usd is not None and usd < min_usd:
                continue
            cands.append({"out": o, "in": i, "diff": diff, "gap": gap, "same_asset": same})

    per_out, per_in = {}, {}
    for m in cands:
        per_out.setdefault(id(m["out"]), []).append(m)
        per_in.setdefault(id(m["in"]), []).append(m)

    results = []
    for m in cands:
        o, i = m["out"], m["in"]
        n_o, n_i = len(per_out[id(o)]), len(per_in[id(i)])
        rnd = is_round(o["amount"], o["asset"])
        digits = sig_digits(o["amount"])
        exact = m["diff"] < 1e-9
        tight = m["diff"] < 0.001
        unique = n_o == 1 and n_i == 1
        why = []
        if exact:
            why.append("exact same amount")
        elif tight:
            why.append(f"amounts within {m['diff'] * 100:.3f}%")
        else:
            why.append(f"amounts within {m['diff'] * 100:.2f}% (allowing for fees/spread)")
        why.append("round amount: common, weak evidence" if rnd else f"distinctive amount ({digits} significant digits)")
        hrs = m["gap"] / 3600
        why.append(f"arrived {hrs * 60:.0f} min later" if hrs < 1 else f"arrived {hrs:.1f} h later")
        if not m["same_asset"]:
            why.append(f"different assets ({o['asset']} → {i['asset']}) compared in today's USD: approximate")
        if not unique:
            why.append(f"ambiguous: {n_o} possible arrivals for this departure, {n_i} departures for this arrival")
        score = (3 if exact else 2 if tight else 1) + (0 if rnd else 1) + (1 if digits >= 5 else 0) \
            + (1 if hrs < 1 else 0.5 if hrs < 6 else 0) + (1 if unique else -1) - (1 if not m["same_asset"] else 0)
        if (exact or tight) and not rnd and unique and m["same_asset"]:
            conf = "strong"
        elif unique and (not rnd or exact) and m["diff"] <= tol:
            conf = "possible"
        else:
            conf = "weak"
        results.append({
            "confidence": conf, "score": round(score, 2), "why": why,
            "from_wallet": o["_wallet"], "from_chain": o["_chain"], "out_tx": o["hash"], "out_time": o["time"],
            "out_amount": o["amount"], "out_asset": o["asset"], "out_to": o.get("counterparty"),
            "to_wallet": i["_wallet"], "to_chain": i["_chain"], "in_tx": i["hash"], "in_time": i["time"],
            "in_amount": i["amount"], "in_asset": i["asset"], "in_from": i.get("counterparty"),
            "usd": o.get("usd") or i.get("usd"), "diff_pct": round(m["diff"] * 100, 4),
            "gap_hours": round(hrs, 2), "ambiguity": {"arrivals": n_o, "departures": n_i},
        })
    order = {"strong": 0, "possible": 1, "weak": 2}
    results.sort(key=lambda r: (order[r["confidence"]], -r["score"]))
    hidden = sum(1 for r in results if r["confidence"] == "weak")
    if not include_weak:
        results = [r for r in results if r["confidence"] != "weak"]
    return {"sources": len(src), "targets": len(dst), "departures_checked": len(outs),
            "arrivals_checked": len(ins), "window_hours": window_hours, "tolerance_pct": tolerance_pct,
            "strong": sum(1 for r in results if r["confidence"] == "strong"),
            "possible": sum(1 for r in results if r["confidence"] == "possible"),
            "weak_hidden": hidden if not include_weak else 0,
            "matches": results[:200], "errors": errors,
            "method": "Same asset and amount (within tolerance) inside the time window. 'Strong' needs a "
                      "near-exact, non-round amount with exactly one candidate on each side."}


# ------------------------------------------------------------------ pass-through

def pass_through(address, chain="auto", window_hours=24, tolerance_pct=2.0, min_usd=20, limit=150):
    """Find amounts that come in and go back out nearly unchanged soon after (layering hops)."""
    d = ct.detect(address, chain)
    act = ct.activity(d["value"], d["chain"] if d["chain"] != "auto" else chain, limit=limit)
    items = [x for x in act["items"] if x.get("kind") in ("native", "token") and (x.get("amount") or 0) > 0]
    ins = [x for x in items if x["direction"] == "in"]
    outs = [x for x in items if x["direction"] == "out"]
    tol, win = float(tolerance_pct) / 100, float(window_hours) * 3600
    used, events = set(), []
    for i in sorted(ins, key=lambda x: ct._ts(x["time"])):
        ti = ct._ts(i["time"])
        best = None
        for o in outs:
            if id(o) in used or _norm_asset(o["asset"]) != _norm_asset(i["asset"]):
                continue
            gap = ct._ts(o["time"]) - ti
            if gap < 0 or gap > win:
                continue
            # what leaves is the same or slightly less (fees), never more
            ratio = o["amount"] / i["amount"] if i["amount"] else 0
            if not (1 - tol <= ratio <= 1 + 1e-6):
                continue
            if best is None or gap < best[1]:
                best = (o, gap, ratio)
        if best:
            o, gap, ratio = best
            usd = i.get("usd")
            if min_usd and usd is not None and usd < min_usd:
                continue
            used.add(id(o))
            rnd = is_round(i["amount"], i["asset"])
            events.append({"in_tx": i["hash"], "in_time": i["time"], "from": i.get("counterparty"),
                           "out_tx": o["hash"], "out_time": o["time"], "to": o.get("counterparty"),
                           "asset": i["asset"], "amount_in": i["amount"], "amount_out": o["amount"],
                           "kept_pct": round((1 - ratio) * 100, 3), "usd": usd,
                           "gap_hours": round(gap / 3600, 2),
                           "confidence": "possible" if rnd else "strong",
                           "note": "round amount" if rnd else "distinctive amount"})
    share = len(events) / len(ins) if ins else 0
    return {"address": act["address"], "chain": act["chain"], "incoming": len(ins),
            "passed_through": len(events), "share": round(share, 2),
            "verdict": ("acts as a pass-through hop" if share >= 0.6 and len(events) >= 3 else
                        "sometimes forwards funds" if events else "keeps what it receives"),
            "events": events}


API = {"links": links, "match_amounts": match_amounts, "pass_through": pass_through}
