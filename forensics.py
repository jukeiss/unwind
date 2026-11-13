"""
forensics - coin-level and exposure analysis for Unwind.

  coins(address)      Bitcoin UTXOs as coin IDs (txid:vout) with block, time,
                      age, and origin (mined / CoinJoin output / normal).
  coin(id)            One coin in depth: the block that created it, the pool
                      that mined that block, where it was spent, and its
                      ancestry a few transactions back.
  exposure(address)   Mixer / CoinJoin contact, first seen, first funder,
                      contract creator.
  coinjoin(tx)        Heuristic CoinJoin detector for a Bitcoin transaction.

Heuristics are heuristics: CoinJoin detection and pool tags are strong
signals, not proof. Results say which rule fired.
"""
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import chaintrace as ct

def _api(chain):
    c = ct.get_chain(chain or "bitcoin")
    if c.kind != "utxo":
        raise ValueError(f"{c.name} has no coins/UTXOs; coin views work on Bitcoin, Litecoin and testnet")
    return c.api


def _chain_for(x, chain=None):
    if chain and chain != "auto":
        return chain
    for c in ct.classify_address((x or "").strip()):
        if c in ct.REG and ct.REG[c].kind == "utxo":
            return c
    return "bitcoin"

# Well-known Tornado Cash pools/router on Ethereum (public, sanctioned 2022, delisted 2025).
KNOWN_MIXERS_EVM = {
    "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc": "Tornado Cash 0.1 ETH",
    "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936": "Tornado Cash 1 ETH",
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf": "Tornado Cash 10 ETH",
    "0xa160cdab225685da1d56aa342ad8841c3b53f291": "Tornado Cash 100 ETH",
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b": "Tornado Cash Router",
}

POOL_TAGS = [
    ("Foundry USA", r"foundry"), ("AntPool", r"antpool|ant pool"), ("F2Pool", r"f2pool|七彩神仙鱼|discus fish"),
    ("ViaBTC", r"viabtc"), ("Binance Pool", r"binance"), ("MARA Pool", r"mara|marathon"),
    ("Luxor", r"luxor"), ("SpiderPool", r"spiderpool"), ("SECPOOL", r"secpool"),
    ("Braiins Pool", r"braiins|slush"), ("Poolin", r"poolin"), ("BTC.com", r"btc\.com"),
    ("OCEAN", r"ocean"), ("SBI Crypto", r"sbicrypto|sbi crypto"), ("Titan", r"titan"),
    ("ULTIMUSPOOL", r"ultimus"), ("Carbon Negative", r"carbon"), ("Mining Squared", r"bsquared|mining squared"),
    ("WhitePool", r"whitepool"), ("BTC M4", r"btcm4"), ("KuCoin Pool", r"kucoin"),
    ("Huobi Pool", r"huobi"), ("OKX Pool", r"okex|okx|okkong"), ("1THash", r"1thash"),
    ("Bitfury", r"bitfury"), ("BTCC", r"btcc"), ("GHash.IO", r"ghash"), ("Eligius", r"eligius"),
    ("Satoshi (early era)", r"^$"),
]
WHIRLPOOL_DENOMS = {100_000, 1_000_000, 5_000_000, 50_000_000}


def _parse_coin_id(cid):
    m = re.fullmatch(r"\s*([0-9a-fA-F]{64})[:#/](\d+)\s*", cid or "")
    if not m:
        raise ValueError("coin id must look like <txid>:<output index>")
    return m.group(1).lower(), int(m.group(2))


def _tx(txid, chain="bitcoin"):
    t = ct._get(f"{_api(chain)}/tx/{txid}", ttl=3600)
    if not t:
        raise ValueError(f"transaction {txid[:12]}… not found")
    return t


def _price(chain="bitcoin"):
    return ct.native_price(chain)


def _iso(ts):
    return ct._iso(ts)


def _age(ts):
    if not ts:
        return None
    s = time.time() - ts
    d = s / 86400
    if d < 1:
        return f"{int(s // 3600)}h"
    if d < 60:
        return f"{int(d)}d"
    if d < 730:
        return f"{d / 30.4:.0f}mo"
    return f"{d / 365.25:.1f}y"


# ------------------------------------------------------------------ coinjoin

def coinjoin(t, chain="bitcoin"):
    """Heuristic CoinJoin detection. `t` is an Esplora tx dict or a txid."""
    if isinstance(t, str):
        t = _tx(t, chain)
    vin, vout = t.get("vin", []), t.get("vout", [])
    if any(v.get("is_coinbase") for v in vin):
        return {"coinjoin": False}
    vals = [o.get("value", 0) for o in vout if o.get("value")]
    cnt = Counter(vals)
    if not cnt:
        return {"coinjoin": False}
    denom, n_eq = cnt.most_common(1)[0]
    in_addrs = {(v.get("prevout") or {}).get("scriptpubkey_address") for v in vin}
    res = {"coinjoin": False, "inputs": len(vin), "outputs": len(vout),
           "equal_outputs": n_eq, "denomination": denom / 1e8}
    if len(vin) == 5 and len(vout) == 5 and n_eq == 5 and denom in WHIRLPOOL_DENOMS:
        res.update(coinjoin=True, type="Whirlpool (Samourai)", rule="5 inputs, 5 equal outputs at a Whirlpool pool size")
    elif len(vin) >= 50 and len(vout) >= 50 and sum(1 for v, c in cnt.items() if c >= 3) >= 5:
        res.update(coinjoin=True, type="Wasabi-style", rule="50+ inputs/outputs with many equal-value groups")
    elif n_eq >= 3 and len(in_addrs) >= 3 and n_eq >= len(vout) * 0.3 and len(vout) >= 4:
        res.update(coinjoin=True, type="JoinMarket / generic CoinJoin",
                   rule=f"{n_eq} equal outputs of {denom / 1e8:g} BTC from {len(in_addrs)} input addresses")
    return res


# ------------------------------------------------------------------ mining

def _block(h, chain="bitcoin"):
    return ct._get(f"{_api(chain)}/block/{h}", ttl=86400)


def _pool_from_coinbase(t):
    vin0 = (t.get("vin") or [{}])[0]
    hexs = vin0.get("scriptsig") or ""
    try:
        raw = bytes.fromhex(hexs)
    except ValueError:
        raw = b""
    text = "".join(chr(b) if 32 <= b < 127 else " " for b in raw)
    runs = [r for r in re.split(r"\s{1,}", text) if len(r) >= 3]
    tag = " ".join(runs)[:80]
    for name, rx in POOL_TAGS:
        if rx != r"^$" and re.search(rx, tag, re.I):
            return name, tag
    return None, tag


def mined_info(block_hash, chain="bitcoin"):
    """Which block, when, and which pool mined it (from the coinbase tag)."""
    b = _block(block_hash, chain)
    if not b:
        return None
    cbid = ct._get(f"{_api(chain)}/block/{block_hash}/txid/0", ttl=86400)
    if isinstance(cbid, (bytes, bytearray)):
        cbid = cbid.decode()
    pool, tag = (None, "")
    if cbid:
        try:
            pool, tag = _pool_from_coinbase(_tx(cbid if isinstance(cbid, str) else str(cbid), chain))
        except Exception:
            pass
    if not pool and b.get("height", 10**9) < 100_000:
        pool = "Solo / early miner"
    return {"height": b.get("height"), "hash": block_hash, "time": _iso(b.get("timestamp")),
            "tx_count": b.get("tx_count"), "pool": pool, "coinbase_tag": tag,
            "explorer_url": f"{ct.REG[chain].explorer}/block/{block_hash}"}


# ------------------------------------------------------------------ coins

def _origin(t):
    vin = t.get("vin", [])
    if any(v.get("is_coinbase") for v in vin):
        return "mined"
    cj = coinjoin(t)
    if cj.get("coinjoin"):
        return "coinjoin"
    return "transfer"


def coins(address, limit=60, chain=None):
    """Unspent coins held by a Bitcoin/Litecoin address, each with its coin id and origin."""
    address = (address or "").strip()
    chain = _chain_for(address, chain)
    utxos = ct._get(f"{_api(chain)}/address/{address}/utxo") or []
    if not isinstance(utxos, list):
        utxos = []
    utxos.sort(key=lambda u: -(u.get("value", 0)))
    price = _price(chain)
    picked = utxos[:int(limit)]

    def enrich(u):
        try:
            t = _tx(u["txid"], chain)
            return _origin(t), coinjoin(t)
        except Exception:
            return None, {}

    with ThreadPoolExecutor(max_workers=6) as ex:
        extra = list(ex.map(enrich, picked[:30]))
    out = []
    for i, u in enumerate(picked):
        st = u.get("status", {})
        ts = st.get("block_time")
        o, cj = extra[i] if i < len(extra) else (None, {})
        v = u.get("value", 0) / 1e8
        out.append({"id": f"{u['txid']}:{u['vout']}", "txid": u["txid"], "vout": u["vout"],
                    "value": v, "usd": v * price if price else None,
                    "height": st.get("block_height"), "time": _iso(ts), "age": _age(ts),
                    "confirmed": st.get("confirmed", False), "origin": o,
                    "coinjoin_type": cj.get("type") if cj.get("coinjoin") else None})
    total = sum(u.get("value", 0) for u in utxos) / 1e8
    return {"address": address, "chain": chain, "symbol": ct.REG[chain].symbol,
            "count": len(utxos), "shown": len(out), "total": total,
            "total_usd": total * price if price else None, "coins": out}


def coin(id, depth=3, chain="bitcoin"):
    """Everything about one coin (txid:vout): creation, mining, spend, ancestry."""
    txid, vout = _parse_coin_id(id)
    chain = chain if chain and chain != "auto" else "bitcoin"
    api = _api(chain)
    t = _tx(txid, chain)
    if vout >= len(t.get("vout", [])):
        raise ValueError(f"transaction has only {len(t.get('vout', []))} outputs")
    o = t["vout"][vout]
    st = t.get("status", {})
    price = _price(chain)
    v = o.get("value", 0) / 1e8
    res = {"id": f"{txid}:{vout}", "chain": chain, "symbol": ct.REG[chain].symbol, "value": v, "usd": v * price if price else None,
           "address": o.get("scriptpubkey_address"), "script_type": o.get("scriptpubkey_type"),
           "created": {"txid": txid, "height": st.get("block_height"), "time": _iso(st.get("block_time")),
                       "age": _age(st.get("block_time")), "confirmed": st.get("confirmed", False)},
           "origin": _origin(t), "coinjoin": coinjoin(t),
           "explorer_url": f"{ct.REG[chain].explorer}/tx/{txid}#vout={vout}"}

    if st.get("block_hash"):
        res["block"] = mined_info(st["block_hash"], chain)

    sp = ct._get(f"{api}/tx/{txid}/outspend/{vout}", ttl=120) or {}
    if sp.get("spent"):
        sst = sp.get("status", {})
        res["spent"] = {"txid": sp.get("txid"), "input_index": sp.get("vin"),
                        "height": sst.get("block_height"), "time": _iso(sst.get("block_time"))}
        try:
            stx = _tx(sp["txid"], chain)
            res["spent"]["coinjoin"] = coinjoin(stx)
            res["spent"]["to"] = [{"address": x.get("scriptpubkey_address"), "value": x.get("value", 0) / 1e8}
                                  for x in stx.get("vout", [])[:12]]
        except Exception:
            pass
    else:
        res["spent"] = None

    # ancestry: walk back through the largest input each step
    anc = []
    cur = t
    for step in range(int(depth)):
        vin = cur.get("vin", [])
        if not vin or any(x.get("is_coinbase") for x in vin):
            if vin and vin[0].get("is_coinbase"):
                cst = cur.get("status", {})
                blk = mined_info(cst["block_hash"], chain) if cst.get("block_hash") else None
                if anc and anc[-1].get("txid") == cur.get("txid"):
                    anc[-1]["block"] = blk          # parent step already listed: just add mining info
                    break
                anc.append({"step": step + 1, "kind": "mined", "txid": cur.get("txid"),
                              "height": cst.get("block_height"), "time": _iso(cst.get("block_time")),
                              "block": mined_info(cst["block_hash"], chain) if cst.get("block_hash") else None})
            break
        big = max(vin, key=lambda x: (x.get("prevout") or {}).get("value", 0))
        try:
            parent = _tx(big["txid"], chain)
        except Exception:
            break
        pst = parent.get("status", {})
        po = (big.get("prevout") or {})
        anc.append({"step": step + 1, "kind": _origin(parent), "txid": parent["txid"],
                      "coin_id": f"{big['txid']}:{big['vout']}", "value": po.get("value", 0) / 1e8,
                      "address": po.get("scriptpubkey_address"), "inputs": len(cur.get("vin", [])),
                      "height": pst.get("block_height"), "time": _iso(pst.get("block_time")),
                      "coinjoin": coinjoin(parent)})
        cur = parent
    res["ancestry"] = anc
    res["mixer_exposure"] = (res["coinjoin"].get("coinjoin")
                             or any(a.get("kind") == "coinjoin" for a in anc))
    return res


# ------------------------------------------------------------------ exposure

def exposure(address, chain="auto"):
    """Mixer / CoinJoin contact plus origin facts for a wallet."""
    d = ct.detect(address, chain)
    address = d["value"]
    chain, _ = ct._pick_chain(address, d["chain"])
    c = ct.CHAINS[chain]
    out = {"address": address, "chain": chain, "mixer_hits": [], "coinjoins": []}

    if c.family == "monero":
        raise ValueError("Monero hides who sent what, so exposure can't be measured for a Monero address")
    if c.kind == "utxo":
        txs, url = [], f"{c.api}/address/{address}/txs"
        for _ in range(4):
            page = ct._get(url) or []
            if not isinstance(page, list):
                break
            if not page:
                break
            txs.extend(page)
            conf = [t for t in page if t.get("status", {}).get("confirmed")]
            if len(page) < 25 or not conf:
                break
            url = f"{c.api}/address/{address}/txs/chain/{conf[-1]['txid']}"
        for t in txs:
            cj = coinjoin(t)
            if cj.get("coinjoin"):
                st = t.get("status", {})
                out["coinjoins"].append({"txid": t["txid"], "type": cj["type"], "rule": cj["rule"],
                                         "time": _iso(st.get("block_time")), "height": st.get("block_height")})
        a = ct._get(f"{c.api}/address/{address}") or {}
        n = a.get("chain_stats", {}).get("tx_count", 0)
        if txs and len(txs) >= n:
            first = min(txs, key=lambda t: t.get("status", {}).get("block_height") or 10**9)
            fst = first.get("status", {})
            out["first_seen"] = {"txid": first["txid"], "height": fst.get("block_height"),
                                 "time": _iso(fst.get("block_time"))}
            if fst.get("block_hash") and any(v.get("is_coinbase") for v in first.get("vin", [])):
                out["first_seen"]["mined"] = mined_info(fst["block_hash"], chain)
            senders = [(v.get("prevout") or {}).get("scriptpubkey_address") for v in first.get("vin", [])]
            senders = [s for s in senders if s and s != address]
            out["funded_by"] = senders[:5] or (["block reward"] if any(v.get("is_coinbase") for v in first.get("vin", [])) else [])
        else:
            out["first_seen"] = None
            out["first_seen_note"] = f"Too many transactions ({n}) to scan to the first one."
        out["scanned_txs"] = len(txs)
    else:
        act = ct.activity(address, chain, limit=100, include_spam=False)["items"]
        for x in act:
            cp = (x.get("counterparty") or "").lower()
            lab = x.get("counterparty_label") or ""
            hit = KNOWN_MIXERS_EVM.get(cp) or (lab if ct.re.search(r"tornado|mixer|railgun|sinbad|blender", lab, ct.re.I) else None)
            if hit:
                out["mixer_hits"].append({"mixer": hit, "address": x["counterparty"], "direction": x["direction"],
                                          "amount": x["amount"], "asset": x["asset"], "usd": x.get("usd"),
                                          "hash": x["hash"], "time": x["time"]})
        out["scanned_txs"] = len(act)
        # first transaction, oldest first (Etherscan-compatible txlist)
        first = None
        try:
            if c.family == "blockscout":
                base = c.api.replace("/api/v2", "/api")
                r = ct._get(f"{base}?module=account&action=txlist&address={address}&sort=asc&page=1&offset=1",
                            ttl=3600, timeout=15, tries=2) or {}
                first = (r.get("result") or [None])[0] if isinstance(r, dict) and isinstance(r.get("result"), list) else None
            elif c.family == "etherscan":
                r = c._call(module="account", action="txlist", address=address, sort="asc", page=1, offset=1, ttl=3600)
                first = r[0] if isinstance(r, list) and r else None
        except Exception:
            first = None
        if first:
            out["first_seen"] = {"txid": first.get("hash"), "height": int(first.get("blockNumber") or 0),
                                 "time": _iso(int(first.get("timeStamp") or 0))}
            if (first.get("to") or "").lower() == address.lower():
                out["funded_by"] = [first.get("from")]
                fl = KNOWN_MIXERS_EVM.get((first.get("from") or "").lower())
                if fl:
                    out["mixer_hits"].insert(0, {"mixer": fl, "address": first.get("from"), "direction": "in",
                                                 "note": "first funding came from a mixer",
                                                 "hash": first.get("hash"), "time": out["first_seen"]["time"]})
        a = (ct._get(f"{c.api}/addresses/{address}") or {}) if c.family == "blockscout" else {}
        if isinstance(a, dict) and a.get("creator_address_hash"):
            out["creator"] = {"address": a["creator_address_hash"], "txid": a.get("creation_transaction_hash")}

    hits = len(out["mixer_hits"]) + len(out["coinjoins"])
    out["verdict"] = ("direct mixer contact" if out["mixer_hits"] else
                      "took part in CoinJoins" if out["coinjoins"] else "no mixer contact found in scanned history")
    out["risk"] = "high" if out["mixer_hits"] else ("medium" if out["coinjoins"] else "low")
    out["hits"] = hits
    return out


API = {"coins": coins, "coin": coin, "exposure": exposure, "coinjoin": coinjoin, "mined": mined_info}
