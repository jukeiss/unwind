"""
chaintrace - multi-chain wallet lookup and fund tracing for Unwind.

Chains are adapters over public data sources:

  esplora     Bitcoin, Litecoin, Bitcoin testnet             (no key)
  blockscout  Ethereum, Optimism, Celo, zkSync, Unichain, Soneium, Ink,
              Hemi, Rootstock, Mode, Lisk, Plume, Fuse, Metal, testnets (no key)
  routescan   Avalanche, Blast, Mantle                       (no key)
  etherscan   Base, Arbitrum, Polygon, BNB Chain, Linea, Scroll, Gnosis,
              Sonic, Berachain, Taiko, Abstract, World Chain, ... (free key)
  solana, tron, xrp, ton                                     (no key)

Every adapter returns the same normalised shapes, so wallet pages, flags,
multi-hop traces and the vault work identically on every chain.
"""
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

UA = "Mozilla/5.0 (compatible; unwind/0.2; local research tool)"
TTL = 90
SETTINGS_PATH = os.path.expanduser("~/.config/unwind/settings.json")

_cache = {}
_cache_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=10)


# ================================================================== settings

def settings():
    try:
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(**kw):
    s = settings()
    s.update({k: v for k, v in kw.items() if v is not None})
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(s, f, indent=2)
    os.chmod(SETTINGS_PATH, 0o600)
    return {"saved": True, "etherscan_key_set": bool(s.get("etherscan_key"))}


def _ekey():
    return os.environ.get("ETHERSCAN_API_KEY") or settings().get("etherscan_key")


# ================================================================== http

def _get(url, ttl=TTL, timeout=25, tries=3, post=None):
    ck = url + (json.dumps(post, sort_keys=True) if post is not None else "")
    now = time.time()
    with _cache_lock:
        hit = _cache.get(ck)
        if hit and now - hit[0] < ttl:
            return hit[1]
    last = None
    for attempt in range(tries):
        body = json.dumps(post).encode() if post is not None else None
        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": UA, "Accept": "application/json",
            **({"Content-Type": "application/json"} if body else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = raw.strip()
            with _cache_lock:
                _cache[ck] = (time.time(), data)
                if len(_cache) > 5000:
                    for k in list(_cache)[:1000]:
                        _cache.pop(k, None)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (400, 404, 422):
                return None
            last = f"HTTP {e.code} from {urllib.parse.urlparse(url).netloc}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(1.0 * (attempt + 1))
                continue
            break
        except Exception as e:
            last = f"{type(e).__name__} talking to {urllib.parse.urlparse(url).netloc}"
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(last or "request failed")


def _safe(fn, default=None):
    try:
        r = fn()
        return default if r is None else r
    except Exception:
        return default


# ================================================================== utils

def _iso(ts):
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        if ts > 1e12:
            ts /= 1000
        return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")
    return ts


def _ts(iso):
    if not iso:
        return 0
    if isinstance(iso, (int, float)):
        return iso / 1000 if iso > 1e12 else iso
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


STABLES = {"USDT", "USDC", "DAI", "USDE", "FDUSD", "PYUSD", "TUSD", "USDS", "USDC.E", "USDT0", "USD₮", "USD₮0",
           "BUSD", "LUSD", "GUSD", "USDP", "FRAX", "CRVUSD", "GHO", "RLUSD", "USDB", "USDG"}


def _stable_rate(sym):
    return 1.0 if (sym or "").upper() in STABLES else None


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58_XRP = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"


def b58decode(s, alphabet=B58):
    n = 0
    for ch in s:
        i = alphabet.find(ch)
        if i < 0:
            return None
        n = n * 58 + i
    full = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip(alphabet[0]))
    return b"\x00" * pad + full


def b58encode(b, alphabet=B58):
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = alphabet[r] + out
    pad = len(b) - len(b.lstrip(b"\x00"))
    return alphabet[0] * pad + out


def b58check(s, alphabet=B58):
    """Return the version byte(s)+payload if checksum is valid, else None."""
    raw = b58decode(s, alphabet)
    if not raw or len(raw) < 5:
        return None
    body, chk = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] != chk:
        return None
    return body


def tron_hex_to_b58(h):
    try:
        b = bytes.fromhex(h[2:] if h.startswith("0x") else h)
    except ValueError:
        return h
    if len(b) == 20:
        b = b"\x41" + b
    return b58encode(b + hashlib.sha256(hashlib.sha256(b).digest()).digest()[:4])


# ================================================================== prices

COINGECKO = "https://api.coingecko.com/api/v3/simple/price"
_price_lock = threading.Lock()
_prices = {"t": 0, "data": {}}


def cg_price(cg_id):
    if not cg_id:
        return None
    with _price_lock:
        fresh = time.time() - _prices["t"] < 300
        if fresh and cg_id in _prices["data"]:
            return _prices["data"][cg_id]
    ids = sorted({a.cg for a in REG.values() if a.cg})
    try:
        d = _get(f"{COINGECKO}?ids={','.join(ids)}&vs_currencies=usd", ttl=300, timeout=12, tries=2) or {}
        with _price_lock:
            _prices["data"] = {k: v.get("usd") for k, v in d.items() if isinstance(v, dict)}
            _prices["t"] = time.time()
    except Exception:
        pass
    return _prices["data"].get(cg_id)


# ================================================================== base adapter

class Chain:
    family = "?"
    kind = "account"          # "utxo" or "account"
    testnet = False
    needs_key = False
    cg = None
    decimals = 18

    def __init__(self, id, name, symbol, explorer, cg=None, testnet=False, color=None):
        self.id, self.name, self.symbol, self.explorer = id, name, symbol, explorer
        self.cg, self.testnet, self.color = cg, testnet, color

    # dict-style access kept for older call sites
    def __getitem__(self, k):
        return {"api": getattr(self, "api", None), "explorer": self.explorer, "kind": self.kind,
                "symbol": self.symbol, "name": self.name}[k]

    @property
    def available(self):
        return not self.needs_key or bool(_ekey())

    def price(self):
        return None if self.testnet else cg_price(self.cg)

    def addr_url(self, a):
        return f"{self.explorer}/address/{a}"

    def tx_url(self, h):
        return f"{self.explorer}/tx/{h}"

    def info(self):
        return {"id": self.id, "name": self.name, "symbol": self.symbol, "family": self.family,
                "kind": self.kind, "testnet": self.testnet, "needs_key": self.needs_key,
                "available": self.available, "color": self.color}

    # adapters implement: lite(a), wallet(a), page(a, cursor), tx(h), exists(a)
    def exists(self, a):
        return 0

    def page(self, a, cursor=None):
        """One page of history: {"items": [transfers...], "cursor": next or None}."""
        raise NotImplementedError

    def transfers(self, a, limit=50):
        """Newest transfers, reading as many pages as needed to reach `limit`."""
        items, cur, n = [], None, 0
        while True:
            r = self.page(a, cur)
            items += r["items"]
            cur, n = r.get("cursor"), n + 1
            if not cur or len(items) >= limit or n >= 80:
                break
        return items

    def _t(self, **kw):
        """Build a normalised transfer."""
        base = {"chain": self.id, "kind": "native", "asset": self.symbol, "amount": 0.0, "usd": None,
                "status": "ok", "fee": None, "spam": False, "change": False}
        base.update(kw)
        return base


# ================================================================== esplora (UTXO)

class Esplora(Chain):
    family = "esplora"
    kind = "utxo"
    decimals = 8

    def __init__(self, id, name, symbol, api, explorer, cg=None, testnet=False, color=None, known=None):
        super().__init__(id, name, symbol, explorer, cg, testnet, color)
        self.api = api
        self.known = known or {}

    def price(self):
        if self.testnet:
            return None
        if self.id == "bitcoin":
            d = _safe(lambda: _get("https://mempool.space/api/v1/prices", ttl=300, timeout=10, tries=2))
            if d and d.get("USD"):
                return float(d["USD"])
        return cg_price(self.cg)

    def addr_type(self, a):
        if a[:4] in ("bc1p", "tb1p") or a.startswith("ltc1p"):
            return "Taproot (P2TR)"
        if re.match(r"^(bc1q|tb1q|ltc1q)", a):
            return "SegWit (P2WPKH/P2WSH)"
        if a[0] in "3M2":
            return "Script hash (P2SH)"
        if a[0] in "1Lmn":
            return "Legacy (P2PKH)"
        return "Unknown"

    def lite(self, a):
        if a == "coinbase":
            return {"kind": "service", "label": "Block reward"}
        d = _get(f"{self.api}/address/{a}", timeout=12, tries=2) or {}
        cs, ms = d.get("chain_stats", {}), d.get("mempool_stats", {})
        bal = (cs.get("funded_txo_sum", 0) - cs.get("spent_txo_sum", 0)
               + ms.get("funded_txo_sum", 0) - ms.get("spent_txo_sum", 0)) / 1e8
        n = cs.get("tx_count", 0) + ms.get("tx_count", 0)
        lab = self.known.get(a)
        return {"balance": bal, "tx_count": n, "label": lab,
                "kind": "service" if n > 2000 and not lab else "wallet",
                "total_received": cs.get("funded_txo_sum", 0) / 1e8,
                "total_sent": cs.get("spent_txo_sum", 0) / 1e8}

    def wallet(self, a):
        w = self.lite(a)
        w.update({"tokens": [], "token_transfer_count": 0, "address_type": self.addr_type(a), "tags": []})
        if w["tx_count"] > 2000 and not w.get("label"):
            w["note"] = "Very high transaction count: likely an exchange or service wallet."
        return w

    def raw_txs(self, a, limit):
        txs, url = [], f"{self.api}/address/{a}/txs"
        while len(txs) < limit:
            page = _get(url) or []
            if not page:
                break
            txs.extend(page)
            conf = [t for t in page if t.get("status", {}).get("confirmed")]
            if len(page) < 25 or not conf:
                break
            url = f"{self.api}/address/{a}/txs/chain/{conf[-1]['txid']}"
        return txs[:limit]

    def page(self, a, cursor=None):
        import heuristics
        txs = _get(f"{self.api}/address/{a}/txs" + (f"/chain/{cursor}" if cursor else "")) or []
        if not isinstance(txs, list):
            txs = []
        conf = [t for t in txs if t.get("status", {}).get("confirmed")]
        nxt = conf[-1]["txid"] if len(conf) >= 25 else None
        price = self.price()
        out = []
        for t in txs:
            st = t.get("status", {})
            ts = st.get("block_time") or time.time()
            ins = [((v.get("prevout") or {}).get("scriptpubkey_address"), (v.get("prevout") or {}).get("value", 0))
                   for v in t.get("vin", [])]
            outs = [(o.get("scriptpubkey_address"), o.get("value", 0)) for o in t.get("vout", [])]
            a_in = sum(v for x, v in ins if x == a)
            a_out = sum(v for x, v in outs if x == a)
            base = dict(hash=t["txid"], time=_iso(ts), status="confirmed" if st.get("confirmed") else "pending",
                        fee=t.get("fee", 0) / 1e8)
            if a_in > 0:
                ch = _safe(lambda: heuristics.change_output(t, chain=self.id))
                recips = [(x, v) for x, v in outs if x and x != a]
                if not recips:
                    out.append(self._t(**base, direction="self", from_=a, to=a, counterparty=a))
                for x, v in recips:
                    amt = v / 1e8
                    is_ch = bool(ch and ch["address"] == x)
                    out.append(self._t(**base, direction="out", amount=amt, usd=amt * price if price else None,
                                       **{"from": a}, to=x, counterparty=x,
                                       counterparty_label=self.known.get(x) or ("likely change" if is_ch else None),
                                       counterparty_kind="change" if is_ch else None, change=is_ch,
                                       change_confidence=ch["confidence"] if is_ch else None))
            else:
                total_in = sum(v for _, v in ins) or 1
                senders = {}
                for x, v in ins:
                    if x and x != a:
                        senders[x] = senders.get(x, 0) + v
                if not senders:
                    amt = a_out / 1e8
                    out.append(self._t(**base, direction="in", amount=amt, usd=amt * price if price else None,
                                       **{"from": "coinbase"}, to=a, counterparty="coinbase",
                                       counterparty_label="Block reward", counterparty_kind="service", mined=True))
                for x, v in senders.items():
                    amt = a_out * (v / total_in) / 1e8
                    out.append(self._t(**base, direction="in", amount=amt, usd=amt * price if price else None,
                                       **{"from": x}, to=a, counterparty=x,
                                       counterparty_label=self.known.get(x)))
        for x in out:
            if "from_" in x:
                x["from"] = x.pop("from_")
        return {"items": out, "cursor": nxt}

    def tx(self, h):
        import forensics
        t = _get(f"{self.api}/tx/{h}")
        if not t:
            raise ValueError("transaction not found on " + self.name)
        price = self.price()
        ins = [{"address": (v.get("prevout") or {}).get("scriptpubkey_address") or "coinbase",
                "amount": ((v.get("prevout") or {}).get("value") or 0) / 1e8,
                "coin_id": f"{v.get('txid')}:{v.get('vout')}" if not v.get("is_coinbase") else None}
               for v in t.get("vin", [])]
        outs = [{"address": o.get("scriptpubkey_address") or o.get("scriptpubkey_type"),
                 "amount": o.get("value", 0) / 1e8, "coin_id": f"{h}:{i}"} for i, o in enumerate(t.get("vout", []))]
        tot = sum(o["amount"] for o in outs)
        st = t.get("status", {})
        import heuristics
        ch = _safe(lambda: heuristics.change_output(t, chain=self.id))
        return {"hash": h, "chain": self.id, "time": _iso(st.get("block_time")),
                "status": "confirmed" if st.get("confirmed") else "pending",
                "block": st.get("block_height"), "fee": t.get("fee", 0) / 1e8, "symbol": self.symbol,
                "inputs": ins, "outputs": outs, "total": tot, "total_usd": tot * price if price else None,
                "weight": t.get("weight"), "coinjoin": forensics.coinjoin(t), "change": ch,
                "explorer_url": self.tx_url(h)}


# ================================================================== blockscout (EVM)

_SPAM_TEXT = re.compile(r"https?:|www\.|t\.me|\.(com|io|org|net|xyz|app|site|lat|top|vip|cc|gg)\b|claim|visit|reward|"
                        r"airdrop|voucher|bonus|gift|redeem|\$\s*\d|[^\x20-\x7e]", re.I)


def looks_spam(symbol, name, amount, priced, direction):
    """Unpriced airdropped tokens with bait names or absurd amounts. Outgoing transfers are never called spam."""
    if priced or direction != "in":
        return False
    text = f"{symbol or ''} {name or ''}"
    if _SPAM_TEXT.search(text):
        return True
    if amount and amount >= 1e9:
        return True
    return False


def _party(p):
    if not p:
        return None
    label = p.get("ens_domain_name") or p.get("name")
    tags = []
    for t in (p.get("metadata") or {}).get("tags") or []:
        if t.get("name"):
            tags.append(t["name"])
    for t in p.get("public_tags") or []:
        if isinstance(t, dict) and t.get("label"):
            tags.append(t["label"])
    if not label and tags:
        label = tags[0]
    is_contract = bool(p.get("is_contract")) and p.get("proxy_type") != "eip7702"
    kind = "contract" if is_contract else "wallet"
    if any(SERVICE_RX.search(x) for x in [label or ""] + tags):
        kind = "service"
    return {"address": p.get("hash"), "label": label, "tags": tags[:6], "kind": kind,
            "scam": bool(p.get("is_scam"))}


class Blockscout(Chain):
    family = "blockscout"

    def __init__(self, id, name, symbol, host, cg=None, testnet=False, color=None):
        super().__init__(id, name, symbol, f"https://{host}", cg, testnet, color)
        self.api = f"https://{host}/api/v2"

    def price(self):
        if self.testnet:
            return None
        d = _safe(lambda: _get(self.api + "/stats", ttl=300, timeout=10, tries=2))
        p = _f(d.get("coin_price")) if isinstance(d, dict) else None
        return p if p else cg_price(self.cg)

    def exists(self, a):
        d = _get(f"{self.api}/addresses/{a}", timeout=6, tries=1, ttl=600)
        if not isinstance(d, dict):
            return 0
        # Blockscout answers for any well-formed address; only count chains with real history
        bal = int(d.get("coin_balance") or 0) > 0
        moved = bool(d.get("block_number_balance_updated_at")) or bool(d.get("creation_transaction_hash"))
        if not (bal or moved):
            return 0
        s = 1 + (1 if bal else 0) + (1 if d.get("has_token_transfers") or d.get("has_tokens") else 0)
        return s

    def lite(self, a):
        d = _get(f"{self.api}/addresses/{a}", timeout=12, tries=2) or {}
        p = _party(d) or {}
        return {"balance": int(d.get("coin_balance") or 0) / 1e18, "label": p.get("label"),
                "tags": p.get("tags"), "kind": p.get("kind"), "ens": d.get("ens_domain_name"),
                "smart_wallet": d.get("proxy_type") == "eip7702", "scam": bool(d.get("is_scam"))}

    def wallet(self, a):
        f_cnt = _pool.submit(_safe, lambda: _get(f"{self.api}/addresses/{a}/counters", timeout=8, tries=1, ttl=900), {})
        f_tb = _pool.submit(_safe, lambda: _get(f"{self.api}/addresses/{a}/token-balances", timeout=12, tries=2), [])
        w = self.lite(a)
        cnt, tb = f_cnt.result() or {}, f_tb.result() or []
        tokens = []
        for t in tb if isinstance(tb, list) else []:
            tok = t.get("token") or {}
            if tok.get("type") != "ERC-20" or tok.get("reputation") not in (None, "ok"):
                continue
            dec = int(tok.get("decimals") or 0)
            amt = int(t.get("value") or 0) / (10 ** dec) if dec else (_f(t.get("value")) or 0)
            rate = _f(tok.get("exchange_rate")) or _stable_rate(tok.get("symbol"))
            tokens.append({"symbol": tok.get("symbol"), "name": tok.get("name"),
                           "contract": tok.get("address_hash") or tok.get("address"),
                           "amount": amt, "usd": amt * rate if rate else None})
        tokens.sort(key=lambda t: -(t["usd"] or 0))
        w.update({"tokens": tokens[:50], "tx_count": int(cnt.get("transactions_count") or 0),
                  "token_transfer_count": int(cnt.get("token_transfers_count") or 0)})
        return w

    def _pages(self, url, limit):
        items, params = [], None
        while len(items) < limit:
            d = _get(url + ("?" + urllib.parse.urlencode(params) if params else ""))
            if not isinstance(d, dict):
                break
            items.extend(d.get("items") or [])
            params = d.get("next_page_params")
            if not params:
                break
        return items[:limit]

    def page(self, a, cursor=None):
        """Three streams (transactions, token transfers, internal transfers), one page of each."""
        price = self.price()
        me = a.lower()
        cur = cursor or {"t": {}, "k": {}, "i": {}}
        urls = {"t": f"{self.api}/addresses/{a}/transactions", "k": f"{self.api}/addresses/{a}/token-transfers",
                "i": f"{self.api}/addresses/{a}/internal-transactions"}

        def fetch(key):
            p = cur.get(key)
            if p is None:
                return key, [], None
            d = _safe(lambda: _get(urls[key] + ("?" + urllib.parse.urlencode(p) if p else "")), {})
            if not isinstance(d, dict):
                return key, [], None
            return key, d.get("items") or [], d.get("next_page_params")

        with ThreadPoolExecutor(max_workers=3) as ex:
            got = {k: (items, nxt) for k, items, nxt in ex.map(fetch, ["t", "k", "i"])}
        out = []
        for t in got["t"][0]:
            frm = _party(t.get("from")) or {}
            to = _party(t.get("to")) or _party(t.get("created_contract")) or {}
            created = (t.get("created_contract") or {}).get("hash")
            amt = int(t.get("value") or 0) / 1e18
            rate = _f(t.get("exchange_rate")) or price
            fa, ta = (frm.get("address") or "").lower(), (to.get("address") or "").lower()
            d = "self" if fa == ta == me else ("out" if fa == me else "in")
            cp = to if d == "out" else frm
            out.append(self._t(hash=t.get("hash"), time=t.get("timestamp"), kind="native" if amt else "call",
                               method=t.get("method"), status=t.get("status") or t.get("result"),
                               direction=d, amount=amt, usd=amt * rate if rate else None,
                               **{"from": frm.get("address")}, to=to.get("address"),
                               counterparty=cp.get("address"), counterparty_label=cp.get("label"),
                               counterparty_kind=cp.get("kind"), created_contract=created,
                               created_name=(t.get("created_contract") or {}).get("name"),
                               fee=int(((t.get("fee") or {}).get("value")) or 0) / 1e18 if fa == me else None))
        for t in got["k"][0]:
            tok, total = t.get("token") or {}, t.get("total") or {}
            frm, to = _party(t.get("from")) or {}, _party(t.get("to")) or {}
            nft = (tok.get("type") or "") in ("ERC-721", "ERC-1155", "ERC-404")
            dec, raw = total.get("decimals") or tok.get("decimals"), total.get("value")
            amt = 1.0 if raw is None else (int(raw) / (10 ** int(dec)) if dec else float(raw))
            rate = _f(tok.get("exchange_rate")) or _stable_rate(tok.get("symbol"))
            fa, ta = (frm.get("address") or "").lower(), (to.get("address") or "").lower()
            d = "self" if fa == ta == me else ("out" if fa == me else "in")
            cp = to if d == "out" else frm
            spam = (tok.get("reputation") not in (None, "ok") or frm.get("scam") or to.get("scam")
                    or looks_spam(tok.get("symbol"), tok.get("name"), amt, rate is not None, d))
            out.append(self._t(hash=t.get("transaction_hash"), time=t.get("timestamp"),
                               asset=(tok.get("symbol") or "?") + (" NFT" if nft else ""),
                               token_name=tok.get("name"),
                               token_contract=tok.get("address_hash") or tok.get("address"),
                               kind="nft" if nft else "token", token_id=total.get("token_id"),
                               image=((total.get("token_instance") or {}).get("image_url")) if nft else tok.get("icon_url"),
                               direction=d, amount=amt, usd=amt * rate if (rate and not nft) else None,
                               **{"from": frm.get("address")}, to=to.get("address"),
                               counterparty=cp.get("address"), counterparty_label=cp.get("label"),
                               counterparty_kind=cp.get("kind"), spam=bool(spam), ttype=t.get("type")))
        for t in got["i"][0]:
            amt = int(t.get("value") or 0) / 1e18
            if not amt:
                continue
            frm, to = _party(t.get("from")) or {}, _party(t.get("to")) or {}
            fa, ta = (frm.get("address") or "").lower(), (to.get("address") or "").lower()
            if me not in (fa, ta):
                continue
            d = "out" if fa == me else "in"
            cp = to if d == "out" else frm
            out.append(self._t(hash=t.get("transaction_hash"), time=t.get("timestamp"), kind="native", internal=True,
                               direction=d, amount=amt, usd=amt * price if price else None,
                               **{"from": frm.get("address")}, to=to.get("address"),
                               counterparty=cp.get("address"), counterparty_label=cp.get("label"),
                               counterparty_kind=cp.get("kind")))
        nxt = {k: got[k][1] for k in "tki"}
        return {"items": out, "cursor": nxt if any(v is not None for v in nxt.values()) else None}

    def tx(self, h):
        t = _get(f"{self.api}/transactions/{h}")
        if not t:
            raise ValueError("transaction not found on " + self.name)
        tt = _get(f"{self.api}/transactions/{h}/token-transfers") or {}
        price = self.price()
        val = int(t.get("value") or 0) / 1e18
        transfers = []
        for x in (tt.get("items") or []) if isinstance(tt, dict) else []:
            tok, total = x.get("token") or {}, x.get("total") or {}
            dec, raw = total.get("decimals") or tok.get("decimals"), total.get("value")
            amt = (int(raw) / (10 ** int(dec)) if dec else float(raw)) if raw is not None else 1
            rate = _f(tok.get("exchange_rate")) or _stable_rate(tok.get("symbol"))
            pf, pt = _party(x.get("from")) or {}, _party(x.get("to")) or {}
            transfers.append({"from": pf.get("address"), "from_label": pf.get("label"),
                              "to": pt.get("address"), "to_label": pt.get("label"),
                              "asset": tok.get("symbol"), "amount": amt, "usd": amt * rate if rate else None})
        frm, to = _party(t.get("from")) or {}, _party(t.get("to")) or {}
        return {"hash": h, "chain": self.id, "time": t.get("timestamp"), "status": t.get("status"),
                "block": t.get("block_number"), "method": t.get("method"),
                "from": frm.get("address"), "from_label": frm.get("label"),
                "to": to.get("address"), "to_label": to.get("label"),
                "value": val, "value_usd": val * price if price else None, "symbol": self.symbol,
                "fee": int(((t.get("fee") or {}).get("value")) or 0) / 1e18,
                "token_transfers": transfers, "explorer_url": self.tx_url(h)}


# ================================================================== etherscan-compatible (EVM)

class EtherscanLike(Chain):
    family = "etherscan"

    def __init__(self, id, name, symbol, chainid, explorer, cg=None, provider="etherscan", testnet=False, color=None):
        super().__init__(id, name, symbol, explorer, cg, testnet, color)
        self.chainid, self.provider = chainid, provider
        self.needs_key = provider == "etherscan"

    def _url(self, **q):
        if self.provider == "routescan":
            base = f"https://api.routescan.io/v2/network/mainnet/evm/{self.chainid}/etherscan/api"
        else:
            base = f"https://api.etherscan.io/v2/api?chainid={self.chainid}&apikey={_ekey() or ''}"
        return base + ("&" if "?" in base else "?") + urllib.parse.urlencode(q)

    def _call(self, timeout=15, tries=2, ttl=TTL, **q):
        if self.needs_key and not _ekey():
            raise RuntimeError(f"{self.name} needs a free Etherscan API key (add it in Settings)")
        d = _get(self._url(**q), timeout=timeout, tries=tries, ttl=ttl)
        if not isinstance(d, dict):
            return None
        if str(d.get("status")) == "0" and d.get("message") not in ("No transactions found", "OK"):
            msg = d.get("result") if isinstance(d.get("result"), str) else d.get("message")
            if msg and "rate limit" in str(msg).lower():
                time.sleep(1.1)
                d = _get(self._url(**q), timeout=timeout, tries=1, ttl=0) or {}
            elif msg and "no transactions" not in str(msg).lower():
                raise RuntimeError(f"{self.name}: {msg}")
        return d.get("result")

    def exists(self, a):
        r = self._call(timeout=6, tries=1, ttl=600, module="account", action="txlist", address=a,
                       page=1, offset=1, sort="desc")
        return 2 if isinstance(r, list) and r else 0

    def _is_contract(self, a):
        code = _safe(lambda: self._call(module="proxy", action="eth_getCode", address=a, tag="latest", ttl=3600))
        if not isinstance(code, str):
            return None
        if code in ("0x", ""):
            return False
        return not code.startswith("0xef0100")   # EIP-7702 delegation = still a wallet

    def lite(self, a):
        bal = self._call(module="account", action="balance", address=a, tag="latest")
        isc = self._is_contract(a)
        return {"balance": int(bal or 0) / 10 ** self.decimals,
                "kind": "contract" if isc else "wallet", "label": None, "tags": []}

    def wallet(self, a):
        w = self.lite(a)
        # token holdings: aggregate recent ERC-20 transfers (free endpoints don't list balances)
        txs = _safe(lambda: self._call(module="account", action="tokentx", address=a, page=1, offset=200, sort="desc"), [])
        bals = {}
        for t in txs if isinstance(txs, list) else []:
            sym, dec = t.get("tokenSymbol"), int(t.get("tokenDecimal") or 0)
            amt = int(t.get("value") or 0) / (10 ** dec) if dec else 0
            sgn = 1 if (t.get("to") or "").lower() == a.lower() else -1
            k = t.get("contractAddress")
            b = bals.setdefault(k, {"symbol": sym, "contract": k, "amount": 0.0})
            b["amount"] += sgn * amt
        tokens = []
        for b in bals.values():
            if b["amount"] > 1e-9:
                r = _stable_rate(b["symbol"])
                b["usd"] = b["amount"] * r if r else None
                b["approx"] = True
                tokens.append(b)
        tokens.sort(key=lambda t: -(t.get("usd") or 0))
        w.update({"tokens": tokens[:40], "tx_count": None, "token_transfer_count": None,
                  "note": "Token balances are estimated from the last 200 token transfers."
                          if tokens else None})
        return w

    PAGE = 100
    STREAMS = ("txlist", "tokentx", "txlistinternal", "tokennfttx", "token1155tx")

    def page(self, a, cursor=None):
        """Five streams (txs, tokens, internal, NFTs, ERC-1155), one page of each still running."""
        price = self.price()
        me = a.lower()
        cur = cursor or {"p": 1, "open": list(self.STREAMS)}
        pg = cur["p"]

        def fetch(action):
            r = _safe(lambda: self._call(module="account", action=action, address=a, page=pg,
                                         offset=self.PAGE, sort="desc"), [])
            return action, r if isinstance(r, list) else []

        with ThreadPoolExecutor(max_workers=2) as ex:
            got = dict(ex.map(fetch, cur["open"]))
        out = []
        for t in got.get("txlist", []):
            amt = int(t.get("value") or 0) / 1e18
            fa, ta = (t.get("from") or "").lower(), (t.get("to") or t.get("contractAddress") or "").lower()
            d = "self" if fa == ta == me else ("out" if fa == me else "in")
            created = t.get("contractAddress") if not t.get("to") and t.get("contractAddress") else None
            out.append(self._t(hash=t.get("hash"), time=_iso(int(t.get("timeStamp") or 0)),
                               kind="native" if amt else "call",
                               method=(t.get("functionName") or "").split("(")[0] or t.get("methodId"),
                               status="error" if t.get("isError") == "1" else "ok",
                               direction=d, amount=amt, usd=amt * price if price else None,
                               **{"from": t.get("from")}, to=t.get("to") or t.get("contractAddress"),
                               counterparty=t.get("to") if d == "out" else t.get("from"), created_contract=created,
                               fee=int(t.get("gasUsed") or 0) * int(t.get("gasPrice") or 0) / 1e18 if fa == me else None))
        for t in got.get("txlistinternal", []):
            amt = int(t.get("value") or 0) / 1e18
            if not amt:
                continue
            fa, ta = (t.get("from") or "").lower(), (t.get("to") or "").lower()
            d = "out" if fa == me else "in"
            out.append(self._t(hash=t.get("hash"), time=_iso(int(t.get("timeStamp") or 0)), kind="native", internal=True,
                               direction=d, amount=amt, usd=amt * price if price else None,
                               **{"from": t.get("from")}, to=t.get("to"),
                               counterparty=t.get("to") if d == "out" else t.get("from")))
        for t in got.get("tokentx", []):
            dec = int(t.get("tokenDecimal") or 0)
            amt = int(t.get("value") or 0) / (10 ** dec) if dec else 0
            fa, ta = (t.get("from") or "").lower(), (t.get("to") or "").lower()
            d = "self" if fa == ta == me else ("out" if fa == me else "in")
            r = _stable_rate(t.get("tokenSymbol"))
            spam = looks_spam(t.get("tokenSymbol"), t.get("tokenName"), amt, r is not None, d)
            out.append(self._t(hash=t.get("hash"), time=_iso(int(t.get("timeStamp") or 0)), kind="token", spam=spam,
                               asset=t.get("tokenSymbol") or "?", token_name=t.get("tokenName"),
                               token_contract=t.get("contractAddress"),
                               direction=d, amount=amt, usd=amt * r if r else None,
                               **{"from": t.get("from")}, to=t.get("to"),
                               counterparty=t.get("to") if d == "out" else t.get("from")))
        for action in ("tokennfttx", "token1155tx"):
            for t in got.get(action, []):
                fa, ta = (t.get("from") or "").lower(), (t.get("to") or "").lower()
                d = "self" if fa == ta == me else ("out" if fa == me else "in")
                out.append(self._t(hash=t.get("hash"), time=_iso(int(t.get("timeStamp") or 0)), kind="nft",
                                   asset=(t.get("tokenSymbol") or t.get("tokenName") or "?") + " NFT",
                                   token_name=t.get("tokenName"), token_contract=t.get("contractAddress"),
                                   token_id=t.get("tokenID"), amount=float(t.get("tokenValue") or 1),
                                   direction=d, **{"from": t.get("from")}, to=t.get("to"),
                                   counterparty=t.get("to") if d == "out" else t.get("from"),
                                   spam=looks_spam(t.get("tokenSymbol"), t.get("tokenName"), 1, False, d)))
        still = [k for k in cur["open"] if len(got.get(k, [])) >= self.PAGE]
        nxt = {"p": pg + 1, "open": still} if still and pg < 99 else None
        return {"items": out, "cursor": nxt}

    def tx(self, h):
        t = self._call(module="proxy", action="eth_getTransactionByHash", txhash=h)
        if not isinstance(t, dict):
            raise ValueError("transaction not found on " + self.name)
        val = int(t.get("value") or "0x0", 16) / 1e18
        price = self.price()
        return {"hash": h, "chain": self.id, "block": int(t.get("blockNumber") or "0x0", 16),
                "from": t.get("from"), "to": t.get("to"), "value": val,
                "value_usd": val * price if price else None, "symbol": self.symbol,
                "token_transfers": [], "explorer_url": self.tx_url(h)}


# ================================================================== solana

SOL_MINTS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "So11111111111111111111111111111111111111112": "wSOL",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "JUP",
    "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo": "PYUSD",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": "mSOL",
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": "JitoSOL",
}
SOL_PROGRAMS = {
    "11111111111111111111111111111111": "System Program",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "Token Program",
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter Aggregator",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca Whirlpool",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium AMM",
}


class Solana(Chain):
    family = "solana"
    decimals = 9
    PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
    _gate = threading.Lock()
    _last = [0.0]

    def __init__(self):
        super().__init__("solana", "Solana", "SOL", "https://solscan.io", cg="solana", color="#9b7bff")

    @property
    def rpc(self):
        """Your own RPC (Helius, QuickNode, …) from Settings if set; otherwise the rate-limited public one."""
        return os.environ.get("SOLANA_RPC_URL") or settings().get("solana_rpc") or self.PUBLIC_RPC

    def addr_url(self, a):
        return f"{self.explorer}/account/{a}"

    def _rpc(self, method, params, ttl=TTL, timeout=20):
        url = self.rpc
        public = url == self.PUBLIC_RPC
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        ck = url + json.dumps(body, sort_keys=True)
        with _cache_lock:
            hit = _cache.get(ck)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
        wait = 2.0
        for attempt in range(6):
            if public:   # the public endpoint allows only a few requests per second per IP
                with self._gate:
                    gap = 0.45 - (time.time() - self._last[0])
                    if gap > 0:
                        time.sleep(gap)
                    self._last[0] = time.time()
            try:
                d = _get(url, post=body, ttl=0, timeout=timeout, tries=1)
            except RuntimeError as e:
                if "429" in str(e) and attempt < 5:
                    time.sleep(wait)
                    wait = min(wait * 2, 20)
                    continue
                raise
            if not isinstance(d, dict):
                return None
            err = d.get("error")
            if err and (err.get("code") in (429, -32429) or "rate" in str(err.get("message", "")).lower()) and attempt < 5:
                time.sleep(wait)
                wait = min(wait * 2, 20)
                continue
            if err:
                raise RuntimeError(f"Solana RPC: {err.get('message')}")
            with _cache_lock:
                _cache[ck] = (time.time(), d.get("result"))
            return d.get("result")
        raise RuntimeError("Solana's public RPC is rate-limiting this computer. Wait a minute, or add a free "
                           "Helius/QuickNode RPC URL in Settings.")

    def exists(self, a):
        r = self._rpc("getBalance", [a], ttl=600, timeout=8)
        return 1 if r is not None else 0

    def lite(self, a):
        bal = (self._rpc("getBalance", [a]) or {}).get("value", 0) / 1e9
        acc = _safe(lambda: self._rpc("getAccountInfo", [a, {"encoding": "base64"}]), {}) or {}
        v = acc.get("value") or {}
        kind = "contract" if v.get("executable") else "wallet"
        lab = SOL_PROGRAMS.get(a)
        if lab and SERVICE_RX.search(lab):
            kind = "service"
        return {"balance": bal, "kind": kind, "label": lab, "tags": []}

    def wallet(self, a):
        w = self.lite(a)
        tokens = []
        for prog in ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"):
            r = _safe(lambda: self._rpc("getTokenAccountsByOwner",
                                        [a, {"programId": prog}, {"encoding": "jsonParsed"}]), {}) or {}
            for acc in r.get("value") or []:
                info = (((acc.get("account") or {}).get("data") or {}).get("parsed") or {}).get("info") or {}
                ta = info.get("tokenAmount") or {}
                amt = _f(ta.get("uiAmount")) or 0
                if amt <= 0:
                    continue
                mint = info.get("mint")
                sym = SOL_MINTS.get(mint, mint[:4] + "…" + mint[-4:] if mint else "?")
                r_ = _stable_rate(sym)
                tokens.append({"symbol": sym, "contract": mint, "amount": amt, "usd": amt * r_ if r_ else None})
        tokens.sort(key=lambda t: -(t["usd"] or 0))
        sigs = _safe(lambda: self._rpc("getSignaturesForAddress", [a, {"limit": 1000}]), None)
        if sigs is None:   # couldn't load history: say unknown rather than "0 transactions"
            w.update({"tokens": tokens[:50], "tx_count": None, "tx_count_note": "unavailable",
                      "token_transfer_count": None})
        else:
            w.update({"tokens": tokens[:50], "tx_count": len(sigs) if len(sigs) < 1000 else None,
                      "tx_count_note": "1000+" if len(sigs) >= 1000 else None, "token_transfer_count": None})
        return w

    def page(self, a, cursor=None):
        price = self.price()
        opts = {"limit": 40}
        if cursor:
            opts["before"] = cursor
        sigs = self._rpc("getSignaturesForAddress", [a, opts]) or []
        nxt = sigs[-1]["signature"] if len(sigs) >= 40 else None

        def get(s):
            return s, _safe(lambda: self._rpc("getTransaction", [s["signature"], {
                "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}], ttl=3600))

        with ThreadPoolExecutor(max_workers=4) as ex:
            loaded = list(ex.map(get, sigs))
        out = []
        for s, t in loaded:
            if not t:
                continue
            meta = t.get("meta") or {}
            keys = [k.get("pubkey") if isinstance(k, dict) else k
                    for k in (((t.get("transaction") or {}).get("message") or {}).get("accountKeys") or [])]
            ts = _iso(t.get("blockTime"))
            fee = (meta.get("fee") or 0) / 1e9
            status = "error" if meta.get("err") else "ok"
            pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
            deltas = {keys[i]: (post[i] - pre[i]) / 1e9 for i in range(min(len(keys), len(pre), len(post)))}
            mine = deltas.get(a, 0)
            if keys and keys[0] == a:
                mine += fee      # don't count the fee as a transfer
            if abs(mine) > 1e-6:
                d = "in" if mine > 0 else "out"
                opp = sorted(((k, v) for k, v in deltas.items() if k != a and (v < 0 if d == "in" else v > 0)),
                             key=lambda kv: -abs(kv[1]))
                cp = opp[0][0] if opp else None
                amt = abs(mine)
                out.append(self._t(hash=s["signature"], time=ts, direction=d, amount=amt,
                                   usd=amt * price if price else None, status=status, fee=fee,
                                   **{"from": a if d == "out" else cp}, to=cp if d == "out" else a,
                                   counterparty=cp, counterparty_label=SOL_PROGRAMS.get(cp or "")))
            # SPL tokens by owner balance change
            tb = {}
            for side, rows in (("pre", meta.get("preTokenBalances") or []), ("post", meta.get("postTokenBalances") or [])):
                for r in rows:
                    k = (r.get("owner"), r.get("mint"))
                    v = _f((r.get("uiTokenAmount") or {}).get("uiAmount")) or 0
                    tb.setdefault(k, [0, 0])[0 if side == "pre" else 1] += v
            mints = {m for (o, m) in tb if o == a}
            for m in mints:
                pv, qv = tb[(a, m)]
                dlt = qv - pv
                if abs(dlt) < 1e-12:
                    continue
                d = "in" if dlt > 0 else "out"
                opp = sorted(((o, q - p) for (o, mm), (p, q) in tb.items() if mm == m and o != a
                              and ((q - p) < 0 if d == "in" else (q - p) > 0)), key=lambda kv: -abs(kv[1]))
                cp = opp[0][0] if opp else None
                sym = SOL_MINTS.get(m, m[:4] + "…" + m[-4:])
                r_ = _stable_rate(sym)
                amt = abs(dlt)
                out.append(self._t(hash=s["signature"], time=ts, kind="token", asset=sym, token_contract=m,
                                   direction=d, amount=amt, usd=amt * r_ if r_ else None, status=status,
                                   **{"from": a if d == "out" else cp}, to=cp if d == "out" else a,
                                   counterparty=cp))
            if not mints and abs(mine) <= 1e-6:
                prog = next((SOL_PROGRAMS.get(k) for k in keys if k in SOL_PROGRAMS and k != "11111111111111111111111111111111"), None)
                out.append(self._t(hash=s["signature"], time=ts, kind="call", direction="out", amount=0,
                                   status=status, fee=fee, method=prog, **{"from": a}, to=None, counterparty=None))
        return {"items": out, "cursor": nxt}

    def tx(self, h):
        t = self._rpc("getTransaction", [h, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}], ttl=3600)
        if not t:
            raise ValueError("transaction not found on Solana")
        meta = t.get("meta") or {}
        keys = [k.get("pubkey") if isinstance(k, dict) else k
                for k in (((t.get("transaction") or {}).get("message") or {}).get("accountKeys") or [])]
        pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
        changes = [{"address": keys[i], "change": (post[i] - pre[i]) / 1e9}
                   for i in range(min(len(keys), len(pre), len(post))) if post[i] != pre[i]]
        return {"hash": h, "chain": "solana", "time": _iso(t.get("blockTime")), "block": t.get("slot"),
                "status": "error" if meta.get("err") else "ok", "fee": (meta.get("fee") or 0) / 1e9,
                "symbol": "SOL", "balance_changes": changes, "programs": [SOL_PROGRAMS.get(k, k) for k in keys if k in SOL_PROGRAMS],
                "explorer_url": self.tx_url(h)}


# ================================================================== tron

TRON_TOKENS = {"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": "USDT", "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8": "USDC"}


class Tron(Chain):
    family = "tron"
    decimals = 6
    api = "https://api.trongrid.io"

    def __init__(self):
        super().__init__("tron", "Tron", "TRX", "https://tronscan.org/#", cg="tron", color="#ff5a5a")

    def addr_url(self, a):
        return f"{self.explorer}/address/{a}"

    def tx_url(self, h):
        return f"{self.explorer}/transaction/{h}"

    def _acct(self, a):
        d = _get(f"{self.api}/v1/accounts/{a}", timeout=12, tries=2) or {}
        return (d.get("data") or [{}])[0] if isinstance(d, dict) else {}

    def exists(self, a):
        return 1 if self._acct(a) else 0

    def lite(self, a):
        acc = self._acct(a)
        is_contract = acc.get("type") == "Contract"
        return {"balance": (acc.get("balance") or 0) / 1e6, "kind": "contract" if is_contract else "wallet",
                "label": acc.get("account_name"), "tags": [],
                "created": _iso(acc.get("create_time")) if acc.get("create_time") else None}

    def wallet(self, a):
        acc = self._acct(a)
        w = self.lite(a)
        tokens = []
        for row in acc.get("trc20") or []:
            for contract, raw in row.items():
                sym = TRON_TOKENS.get(contract)
                dec = 6 if sym in ("USDT", "USDC") else None
                if dec is None:
                    continue
                amt = int(raw) / 10 ** dec
                if amt > 0:
                    tokens.append({"symbol": sym, "contract": contract, "amount": amt, "usd": amt})
        tokens.sort(key=lambda t: -(t["usd"] or 0))
        w.update({"tokens": tokens, "tx_count": None, "token_transfer_count": None})
        return w

    def page(self, a, cursor=None):
        price = self.price()
        cur = cursor or {"t": "", "k": ""}

        def fetch(key, path):
            fp = cur.get(key)
            if fp is None:
                return {}
            q = f"limit=100&only_confirmed=true" + (f"&fingerprint={urllib.parse.quote(fp)}" if fp else "")
            return _safe(lambda: _get(f"{self.api}/v1/accounts/{a}/{path}?{q}"), {}) or {}

        r1, r2 = fetch("t", "transactions"), fetch("k", "transactions/trc20")
        nxt = {"t": (r1.get("meta") or {}).get("fingerprint") if r1 else None,
               "k": (r2.get("meta") or {}).get("fingerprint") if r2 else None}
        out = []
        for t in r1.get("data") or []:
            c = ((t.get("raw_data") or {}).get("contract") or [{}])[0]
            v = ((c.get("parameter") or {}).get("value") or {})
            ts = _iso((t.get("raw_data") or {}).get("timestamp") or t.get("block_timestamp"))
            if c.get("type") == "TransferContract":
                frm, to = tron_hex_to_b58(v.get("owner_address", "")), tron_hex_to_b58(v.get("to_address", ""))
                amt = (v.get("amount") or 0) / 1e6
                d = "out" if frm == a else "in"
                out.append(self._t(hash=t.get("txID"), time=ts, direction=d, amount=amt,
                                   usd=amt * price if price else None, **{"from": frm}, to=to,
                                   counterparty=to if d == "out" else frm,
                                   fee=(t.get("net_fee") or 0) / 1e6))
            else:
                out.append(self._t(hash=t.get("txID"), time=ts, kind="call", direction="out", amount=0,
                                   method=c.get("type"), **{"from": a}, to=None, counterparty=None))
        for t in r2.get("data") or []:
            ti = t.get("token_info") or {}
            dec = int(ti.get("decimals") or 0)
            amt = int(t.get("value") or 0) / 10 ** dec if dec else 0
            d = "out" if t.get("from") == a else "in"
            r = _stable_rate(ti.get("symbol"))
            out.append(self._t(hash=t.get("transaction_id"), time=_iso(t.get("block_timestamp")), kind="token",
                               asset=ti.get("symbol") or "?", token_contract=ti.get("address"),
                               direction=d, amount=amt, usd=amt * r if r else None,
                               **{"from": t.get("from")}, to=t.get("to"),
                               counterparty=t.get("to") if d == "out" else t.get("from")))
        return {"items": out, "cursor": nxt if any(nxt.values()) else None}

    def tx(self, h):
        t = _get(f"{self.api}/wallet/gettransactionbyid", post={"value": h}, ttl=3600)
        if not t:
            raise ValueError("transaction not found on Tron")
        c = ((t.get("raw_data") or {}).get("contract") or [{}])[0]
        v = ((c.get("parameter") or {}).get("value") or {})
        return {"hash": h, "chain": "tron", "type": c.get("type"), "time": _iso((t.get("raw_data") or {}).get("timestamp")),
                "from": tron_hex_to_b58(v.get("owner_address", "")) if v.get("owner_address") else None,
                "to": tron_hex_to_b58(v.get("to_address", "")) if v.get("to_address") else None,
                "value": (v.get("amount") or 0) / 1e6, "symbol": "TRX", "explorer_url": self.tx_url(h)}


# ================================================================== XRP Ledger

class XRP(Chain):
    family = "xrpl"
    decimals = 6
    rpc = "https://xrplcluster.com/"
    RIPPLE_EPOCH = 946684800

    def __init__(self):
        super().__init__("xrp", "XRP Ledger", "XRP", "https://livenet.xrpl.org", cg="ripple", color="#5aa9ff")

    def addr_url(self, a):
        return f"{self.explorer}/accounts/{a}"

    def tx_url(self, h):
        return f"{self.explorer}/transactions/{h}"

    def _rpc(self, method, params, ttl=TTL):
        d = _get(self.rpc, post={"method": method, "params": [params]}, ttl=ttl, timeout=20, tries=3)
        r = (d or {}).get("result") if isinstance(d, dict) else None
        if r and r.get("status") == "error":
            if r.get("error") == "actNotFound":
                return None
            raise RuntimeError(f"XRPL: {r.get('error_message') or r.get('error')}")
        return r

    def exists(self, a):
        return 1 if self._rpc("account_info", {"account": a, "ledger_index": "validated"}, ttl=600) else 0

    def lite(self, a):
        r = self._rpc("account_info", {"account": a, "ledger_index": "validated"}) or {}
        ad = r.get("account_data") or {}
        return {"balance": int(ad.get("Balance") or 0) / 1e6, "kind": "wallet", "label": None, "tags": [],
                "sequence": ad.get("Sequence"), "requires_dest_tag": bool((ad.get("Flags") or 0) & 0x00020000)}

    def wallet(self, a):
        w = self.lite(a)
        lines = _safe(lambda: self._rpc("account_lines", {"account": a, "ledger_index": "validated"}), {}) or {}
        tokens = []
        for l in lines.get("lines") or []:
            amt = _f(l.get("balance")) or 0
            if amt > 0:
                cur = l.get("currency")
                if len(cur or "") == 40:
                    cur = bytes.fromhex(cur).rstrip(b"\x00").decode("ascii", "replace")
                r_ = _stable_rate(cur)
                tokens.append({"symbol": cur, "contract": l.get("account"), "amount": amt,
                               "usd": amt * r_ if r_ else None})
        if w.get("requires_dest_tag"):
            w["note"] = "Requires a destination tag on incoming payments: typical of exchanges and custodians."
        w.update({"tokens": tokens, "tx_count": None, "token_transfer_count": None})
        return w

    def page(self, a, cursor=None):
        price = self.price()
        q = {"account": a, "limit": 200, "ledger_index_min": -1, "ledger_index_max": -1, "forward": False}
        if cursor:
            q["marker"] = cursor
        r = self._rpc("account_tx", q) or {}
        out = []
        for row in r.get("transactions") or []:
            t = row.get("tx") or row.get("tx_json") or {}
            meta = row.get("meta") or {}
            h = t.get("hash") or row.get("hash")
            ts = _iso((t.get("date") or row.get("close_time_iso") or 0) + self.RIPPLE_EPOCH) \
                if isinstance(t.get("date"), int) else row.get("close_time_iso")
            if t.get("TransactionType") != "Payment":
                out.append(self._t(hash=h, time=ts, kind="call", direction="out" if t.get("Account") == a else "in",
                                   method=t.get("TransactionType"), amount=0, **{"from": t.get("Account")},
                                   to=None, counterparty=None,
                                   status="ok" if meta.get("TransactionResult") == "tesSUCCESS" else meta.get("TransactionResult")))
                continue
            amt_raw = meta.get("delivered_amount") or t.get("DeliverMax") or t.get("Amount")
            if isinstance(amt_raw, dict):
                asset, amt = amt_raw.get("currency"), _f(amt_raw.get("value")) or 0
                if len(asset or "") == 40:
                    asset = bytes.fromhex(asset).rstrip(b"\x00").decode("ascii", "replace")
                kind, r_ = "token", _stable_rate(asset)
                usd = amt * r_ if r_ else None
            else:
                asset, amt, kind = "XRP", int(amt_raw or 0) / 1e6, "native"
                usd = amt * price if price else None
            frm, to = t.get("Account"), t.get("Destination")
            d = "self" if frm == to == a else ("out" if frm == a else "in")
            out.append(self._t(hash=h, time=ts, kind=kind, asset=asset, direction=d, amount=amt, usd=usd,
                               **{"from": frm}, to=to, counterparty=to if d == "out" else frm,
                               destination_tag=t.get("DestinationTag"),
                               fee=int(t.get("Fee") or 0) / 1e6,
                               status="ok" if meta.get("TransactionResult") == "tesSUCCESS" else meta.get("TransactionResult")))
        return {"items": out, "cursor": r.get("marker")}

    def tx(self, h):
        r = self._rpc("tx", {"transaction": h}, ttl=3600)
        if not r:
            raise ValueError("transaction not found on the XRP Ledger")
        t = r.get("tx_json") or r
        return {"hash": h, "chain": "xrp", "type": t.get("TransactionType"), "from": t.get("Account"),
                "to": t.get("Destination"), "destination_tag": t.get("DestinationTag"),
                "amount": t.get("Amount") or t.get("DeliverMax"), "symbol": "XRP",
                "result": (r.get("meta") or {}).get("TransactionResult"), "explorer_url": self.tx_url(h)}


# ================================================================== TON

class TON(Chain):
    family = "ton"
    decimals = 9
    api = "https://toncenter.com/api/v3"

    def __init__(self):
        super().__init__("ton", "TON", "TON", "https://tonviewer.com", cg="the-open-network", color="#3fa6ff")

    def addr_url(self, a):
        return f"{self.explorer}/{a}"

    def tx_url(self, h):
        return f"{self.explorer}/transaction/{h}"

    def _q(self, path, ttl=TTL):
        return _get(f"{self.api}/{path}", ttl=ttl, timeout=20, tries=3)   # toncenter: ~1 req/s without key

    def exists(self, a):
        d = _safe(lambda: self._q(f"account?address={urllib.parse.quote(a)}", ttl=600))
        return 1 if d else 0

    def lite(self, a):
        d = self._q(f"account?address={urllib.parse.quote(a)}") or {}
        return {"balance": int(d.get("balance") or 0) / 1e9, "kind": "wallet", "label": None, "tags": [],
                "status": d.get("status")}

    def wallet(self, a):
        w = self.lite(a)
        jw = _safe(lambda: self._q(f"jetton/wallets?owner_address={urllib.parse.quote(a)}&limit=50"), {}) or {}
        meta = jw.get("metadata") or {}
        tokens = []
        for j in jw.get("jetton_wallets") or []:
            master = j.get("jetton")
            info = ((meta.get(master) or {}).get("token_info") or [{}])[0]
            dec = int((info.get("extra") or {}).get("decimals") or 9)
            amt = int(j.get("balance") or 0) / 10 ** dec
            if amt <= 0:
                continue
            sym = info.get("symbol") or (master or "?")[:8]
            r_ = _stable_rate(sym)
            tokens.append({"symbol": sym, "contract": master, "amount": amt, "usd": amt * r_ if r_ else None})
        tokens.sort(key=lambda t: -(t["usd"] or 0))
        w.update({"tokens": tokens, "tx_count": None, "token_transfer_count": None})
        return w

    def page(self, a, cursor=None):
        price = self.price()
        off = int(cursor or 0)
        d = self._q(f"transactions?account={urllib.parse.quote(a)}&limit=50&offset={off}&sort=desc") or {}
        book = d.get("address_book") or {}

        def friendly(raw):
            return (book.get(raw) or {}).get("user_friendly") or raw

        me_raw = None
        for raw, v in book.items():
            if v.get("user_friendly") == a:
                me_raw = raw
        out = []
        for t in d.get("transactions") or []:
            ts = _iso(t.get("now"))
            h = t.get("hash")
            acct = t.get("account")
            msgs = []
            im = t.get("in_msg") or {}
            if im.get("source") and int(im.get("value") or 0) > 0:
                msgs.append(("in", im))
            for om in t.get("out_msgs") or []:
                if int(om.get("value") or 0) > 0:
                    msgs.append(("out", om))
            for d_, m in msgs:
                amt = int(m.get("value") or 0) / 1e9
                cp_raw = m.get("source") if d_ == "in" else m.get("destination")
                cp = friendly(cp_raw)
                out.append(self._t(hash=h, time=ts, direction=d_, amount=amt, usd=amt * price if price else None,
                                   **{"from": cp if d_ == "in" else a}, to=a if d_ == "in" else cp,
                                   counterparty=cp, fee=int(t.get("total_fees") or 0) / 1e9))
        n = len(d.get("transactions") or [])
        return {"items": out, "cursor": off + n if n >= 50 else None}

    def tx(self, h):
        d = self._q(f"transactions?hash={urllib.parse.quote(h)}") or {}
        t = (d.get("transactions") or [None])[0]
        if not t:
            raise ValueError("transaction not found on TON")
        return {"hash": h, "chain": "ton", "time": _iso(t.get("now")), "account": t.get("account"),
                "fee": int(t.get("total_fees") or 0) / 1e9, "symbol": "TON", "explorer_url": self.tx_url(h)}


# ================================================================== Monero

class Monero(Chain):
    """
    Monero hides senders, receivers and amounts, so there is no address lookup.
    What is public per transaction: size, fee, input/output counts, ring
    members, key images and the extra field. We report those as wallet-software
    fingerprints and say plainly that they don't identify anyone.
    """
    family = "monero"
    decimals = 12
    api = "https://xmrchain.net/api"

    def __init__(self):
        super().__init__("monero", "Monero", "XMR", "https://xmrchain.net", cg="monero", color="#ff6600")

    def tx_url(self, h):
        return f"{self.explorer}/tx/{h}"

    def addr_url(self, a):
        return self.explorer

    def _nope(self, *_a, **_k):
        raise ValueError("Monero addresses can't be looked up: the chain hides who received what. "
                         "Paste a Monero transaction hash to inspect it, or use amount matching on the "
                         "transparent chains before and after a swap.")

    lite = wallet = transfers = _nope

    def tx(self, h):
        d = _get(f"{self.api}/transaction/{h}", ttl=3600)
        t = (d or {}).get("data") if isinstance(d, dict) else None
        if not t or not t.get("tx_hash"):
            raise ValueError("transaction not found on Monero")
        ins, outs = t.get("inputs") or [], t.get("outputs") or []
        fee = (t.get("tx_fee") or 0) / 1e12
        size = t.get("tx_size") or 0
        height = t.get("block_height") or t.get("current_height")
        extra = t.get("extra") or ""
        fp = []   # (signal, meaning, strength)
        if t.get("coinbase"):
            fp.append(("coinbase", "Block reward" + (" split to many miners: looks like a P2Pool payout"
                                                     if len(outs) > 10 else ""), "certain"))
        else:
            if (t.get("tx_fee") or 0) % 10000 != 0:
                fp.append(("unquantized fee", "Official wallets round fees; this one doesn't. "
                                              "Points to custom wallet software.", "strong"))
            if len(outs) == 2 and not t.get("payment_id8") and not t.get("payment_id"):
                fp.append(("no dummy payment ID", "Standard wallets add an encrypted payment ID to 2-output "
                                                  "transactions. This one has none.", "medium"))
            if len(outs) > 2:
                fp.append((f"{len(outs)} outputs", "More than 2 outputs: a batch payment, typical of exchanges, "
                                                   "pools and payout services.", "medium"))
            if len(outs) == 1:
                fp.append(("1 output", "Single-output transactions are unusual for normal wallets.", "medium"))
            if len(ins) >= 10:
                fp.append((f"{len(ins)} inputs", "Many inputs merged: a sweep or consolidation. Merging inputs "
                                                 "can link their histories.", "medium"))
            if extra and not extra.startswith("01"):
                fp.append(("non-standard extra", "The tx_extra field isn't in the order official wallets "
                                                 "write it.", "medium"))
            if "04" in extra[66:70]:
                fp.append(("additional tx keys", "Has per-output keys: sending to subaddresses.", "info"))
        rings = []
        for i in ins:
            ms = i.get("mixins") or []
            blocks = [m.get("block_no") for m in ms if m.get("block_no")]
            if blocks and height:
                rings.append({"key_image": i.get("key_image"), "ring_size": len(ms),
                              "newest_age_blocks": height - max(blocks),
                              "oldest_age_blocks": height - min(blocks)})
        price = self.price()
        return {"hash": h, "chain": "monero", "symbol": "XMR", "time": _iso(t.get("timestamp")),
                "block": t.get("block_height"), "confirmations": t.get("confirmations"),
                "coinbase": t.get("coinbase"), "inputs": len(ins), "outputs": len(outs),
                "ring_size": (t.get("mixin") or 0), "fee": fee, "fee_usd": fee * price if price else None,
                "fee_per_kb": fee / (size / 1024) if size else None, "size": size,
                "rct_type": t.get("rct_type"), "version": t.get("tx_version"),
                "amounts_visible": bool(t.get("coinbase")),
                "coinbase_total": sum((o.get("amount") or 0) for o in outs) / 1e12 if t.get("coinbase") else None,
                "fingerprints": [{"signal": a, "meaning": b, "strength": c} for a, b, c in fp],
                "rings": rings,
                "limits": "Senders, receivers and amounts are hidden. Ring ages are shown for "
                          "reference only: the 'newest member is the real spend' rule stopped being "
                          "reliable after 2017 and is not used for any conclusion here.",
                "explorer_url": self.tx_url(h)}


# ================================================================== registry

REG = {}


def _reg(a):
    REG[a.id] = a
    return a


KNOWN_BTC = {"1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa": "Genesis block (Satoshi)",
             "12cbQLTFMXRnSzktFkuoG3eHoMeFtpTu3S": "Hal Finney (block 170)"}

_reg(Esplora("bitcoin", "Bitcoin", "BTC", "https://blockstream.info/api", "https://mempool.space",
             cg="bitcoin", color="#f7931a", known=KNOWN_BTC))
_reg(Esplora("litecoin", "Litecoin", "LTC", "https://litecoinspace.org/api", "https://litecoinspace.org",
             cg="litecoin", color="#a6b4c8"))
_reg(Esplora("bitcoin-testnet", "Bitcoin Testnet", "tBTC", "https://blockstream.info/testnet/api",
             "https://mempool.space/testnet", testnet=True, color="#c98a3a"))

for _id, _n, _s, _h, _cg, _col in [
    ("ethereum", "Ethereum", "ETH", "eth.blockscout.com", "ethereum", "#8a92b2"),
    ("optimism", "Optimism", "ETH", "explorer.optimism.io", "ethereum", "#ff0420"),
    ("zksync", "zkSync Era", "ETH", "zksync.blockscout.com", "ethereum", "#8c8dfc"),
    ("unichain", "Unichain", "ETH", "unichain.blockscout.com", "ethereum", "#f50db4"),
    ("soneium", "Soneium", "ETH", "soneium.blockscout.com", "ethereum", "#cfcfcf"),
    ("ink", "Ink", "ETH", "explorer.inkonchain.com", "ethereum", "#7132f5"),
    ("hemi", "Hemi", "ETH", "explorer.hemi.xyz", "ethereum", "#ff6c15"),
    ("metal", "Metal L2", "ETH", "explorer.metall2.com", "ethereum", "#9aa5b1"),
    ("mode", "Mode", "ETH", "explorer.mode.network", "ethereum", "#dffe00"),
    ("lisk", "Lisk", "ETH", "blockscout.lisk.com", "ethereum", "#4070f4"),
    ("celo", "Celo", "CELO", "celo.blockscout.com", "celo", "#fcff52"),
    ("rootstock", "Rootstock", "RBTC", "rootstock.blockscout.com", "rootstock", "#ff9100"),
    ("plume", "Plume", "PLUME", "explorer.plume.org", "plume", "#ff3d00"),
    ("fuse", "Fuse", "FUSE", "explorer.fuse.io", "fuse-network-token", "#b4f9ba"),
]:
    _reg(Blockscout(_id, _n, _s, _h, _cg, color=_col))
_reg(Blockscout("sepolia", "Sepolia", "sETH", "eth-sepolia.blockscout.com", testnet=True, color="#6b7280"))
_reg(Blockscout("base-sepolia", "Base Sepolia", "sETH", "base-sepolia.blockscout.com", testnet=True, color="#6b7280"))

for _id, _n, _s, _cid, _ex, _cg, _col in [
    ("avalanche", "Avalanche C-Chain", "AVAX", 43114, "https://snowtrace.io", "avalanche-2", "#e84142"),
    ("blast", "Blast", "ETH", 81457, "https://blastscan.io", "ethereum", "#fcfc03"),
    ("mantle", "Mantle", "MNT", 5000, "https://mantlescan.xyz", "mantle", "#65b3ae"),
]:
    _reg(EtherscanLike(_id, _n, _s, _cid, _ex, _cg, provider="routescan", color=_col))

for _id, _n, _s, _cid, _ex, _cg, _col in [
    ("base", "Base", "ETH", 8453, "https://basescan.org", "ethereum", "#0052ff"),
    ("arbitrum", "Arbitrum One", "ETH", 42161, "https://arbiscan.io", "ethereum", "#28a0f0"),
    ("polygon", "Polygon", "POL", 137, "https://polygonscan.com", "polygon-ecosystem-token", "#8247e5"),
    ("bsc", "BNB Chain", "BNB", 56, "https://bscscan.com", "binancecoin", "#f0b90b"),
    ("linea", "Linea", "ETH", 59144, "https://lineascan.build", "ethereum", "#61dfff"),
    ("scroll", "Scroll", "ETH", 534352, "https://scrollscan.com", "ethereum", "#ffeeda"),
    ("gnosis", "Gnosis", "XDAI", 100, "https://gnosisscan.io", "xdai", "#3e6957"),
    ("sonic", "Sonic", "S", 146, "https://sonicscan.org", "sonic-3", "#1969ff"),
    ("berachain", "Berachain", "BERA", 80094, "https://berascan.com", "berachain-bera", "#814625"),
    ("taiko", "Taiko", "ETH", 167000, "https://taikoscan.io", "ethereum", "#e81899"),
    ("abstract", "Abstract", "ETH", 2741, "https://abscan.org", "ethereum", "#03d26f"),
    ("worldchain", "World Chain", "ETH", 480, "https://worldscan.org", "ethereum", "#cccccc"),
    ("opbnb", "opBNB", "BNB", 204, "https://opbnb.bscscan.com", "binancecoin", "#f0b90b"),
    ("moonbeam", "Moonbeam", "GLMR", 1284, "https://moonscan.io", "moonbeam", "#e1147b"),
    ("apechain", "ApeChain", "APE", 33139, "https://apescan.io", "apecoin", "#0054fa"),
    ("sei", "Sei EVM", "SEI", 1329, "https://seiscan.io", "sei-network", "#9e1f19"),
    ("arbitrum-nova", "Arbitrum Nova", "ETH", 42170, "https://nova.arbiscan.io", "ethereum", "#ef8220"),
    ("fraxtal", "Fraxtal", "FRAX", 252, "https://fraxscan.com", "frax-share", "#888888"),
]:
    _reg(EtherscanLike(_id, _n, _s, _cid, _ex, _cg, provider="etherscan", color=_col))

_reg(Solana())
_reg(Tron())
_reg(XRP())
_reg(TON())
_reg(Monero())

EVM_CHAINS = [k for k, v in REG.items() if v.family in ("blockscout", "etherscan")]
CHAINS = REG          # legacy name used by forensics/heuristics


def get_chain(cid):
    if cid not in REG:
        raise ValueError(f"unknown chain '{cid}'. Use one of: {', '.join(REG)}")
    return REG[cid]


def native_price(chain):
    return _safe(lambda: get_chain(chain).price())


def chains():
    return [a.info() for a in REG.values()]


# ================================================================== detection

BTC_ADDR = re.compile(r"^(bc1[02-9ac-hj-np-z]{11,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")
EVM_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
BTC_TX = re.compile(r"^[0-9a-fA-F]{64}$")
EVM_TX = re.compile(r"^0x[0-9a-fA-F]{64}$")
TON_ADDR = re.compile(r"^(?:[EUk0][QfF][A-Za-z0-9_\-]{46}|-?[01]:[0-9a-fA-F]{64})$")


XMR_ADDR = re.compile(r"^[48][1-9A-HJ-NP-Za-km-z]{94}([1-9A-HJ-NP-Za-km-z]{11})?$")


def classify_address(q):
    """Return a list of candidate chains for an address string (best first)."""
    if EVM_ADDR.match(q):
        return ["evm"]
    if XMR_ADDR.match(q):
        return ["monero"]
    low = q.lower()
    if low.startswith("bc1"):
        return ["bitcoin"]
    if low.startswith("tb1"):
        return ["bitcoin-testnet"]
    if low.startswith("ltc1"):
        return ["litecoin"]
    if TON_ADDR.match(q):
        return ["ton"]
    if q.startswith("r") and 25 <= len(q) <= 35:
        body = b58check(q, B58_XRP)
        if body and body[0] == 0:
            return ["xrp"]
    body = b58check(q)
    if body:
        v = body[0]
        if v == 0x41 and q.startswith("T"):
            return ["tron"]
        if v in (0x00,):
            return ["bitcoin"]
        if v == 0x05:
            return ["bitcoin", "litecoin"]
        if v in (0x30, 0x32):
            return ["litecoin"]
        if v in (0x6f, 0xc4):
            return ["bitcoin-testnet"]
    raw = b58decode(q)
    if raw is not None and len(raw) == 32 and 32 <= len(q) <= 44:
        return ["solana"]
    return []


def detect(query, chain="auto"):
    """Work out what a pasted string is: address, ENS name, or transaction hash, and on which chain."""
    q = (query or "").strip()
    if not q:
        raise ValueError("enter an address, ENS name or transaction hash")
    want = chain if chain and chain != "auto" else None
    if want and want not in REG:
        raise ValueError(f"unknown chain '{want}'")

    if EVM_TX.match(q):
        return {"type": "tx", "chain": want if want in EVM_CHAINS else "ethereum", "value": q.lower()}
    if BTC_TX.match(q):
        default = "bitcoin"
        if want:
            default = want
        return {"type": "tx", "chain": default, "value": q if default in ("xrp", "tron") else q.lower()}
    cands = classify_address(q)
    if cands:
        if cands == ["evm"]:
            return {"type": "address", "chain": want if want in EVM_CHAINS else "auto", "value": q}
        c = want if want in cands else cands[0]
        return {"type": "address", "chain": c, "value": q, "candidates": cands}
    # solana signatures: base58, 64 bytes
    raw = b58decode(q)
    if raw is not None and len(raw) == 64:
        return {"type": "tx", "chain": "solana", "value": q}
    if re.fullmatch(r"[A-Za-z0-9+/_\-]{43}=?", q) and want == "ton":
        return {"type": "tx", "chain": "ton", "value": q}
    if "." in q and " " not in q:
        d = _get(REG["ethereum"].api + "/search?q=" + urllib.parse.quote(q))
        for it in (d or {}).get("items", []) if isinstance(d, dict) else []:
            ens = (it.get("ens_info") or {}).get("name")
            if ens and ens.lower() == q.lower() and it.get("address_hash"):
                return {"type": "address", "chain": want if want in EVM_CHAINS else "auto",
                        "value": it["address_hash"], "ens": ens}
        raise ValueError(f"could not resolve name '{q}'")
    raise ValueError("that doesn't look like an address, ENS name or transaction hash on a supported chain")


def _pick_chain(address, chain):
    if chain and chain != "auto":
        return chain, None
    cands = classify_address(address)
    if cands and cands != ["evm"]:
        return cands[0], None
    probe = [c for c in EVM_CHAINS if REG[c].available and not REG[c].testnet]

    def one(c):
        try:
            return c, REG[c].exists(address)
        except Exception:
            return c, 0

    with ThreadPoolExecutor(max_workers=12) as ex:
        scores = dict(ex.map(one, probe))
    order = {c: i for i, c in enumerate(EVM_CHAINS)}
    active = sorted(((c, s) for c, s in scores.items() if s), key=lambda x: (-x[1], order[x[0]]))
    best = active[0][0] if active else "ethereum"
    return best, [{"chain": c, "name": REG[c].name, "score": s} for c, s in active]


# ================================================================== flags

SERVICE_RX = re.compile(
    r"binance|coinbase|kraken|okx|okex|bybit|kucoin|gemini|bitfinex|huobi|\bhtx\b|gate\.io|"
    r"crypto\.com|bitstamp|bitget|mexc|upbit|bithumb|robinhood|exchange|hot wallet|deposit|"
    r"tornado|bridge|router|uniswap|1inch|paraswap|cow protocol|wormhole|stargate|jupiter|raydium|orca", re.I)
MIXER_RX = re.compile(r"tornado|mixer|wasabi|samourai|whirlpool|coinjoin|railgun|sinbad|blender|chipmixer", re.I)
BRIDGE_RX = re.compile(r"bridge|wormhole|stargate|hop protocol|across|synapse|portal|layerzero", re.I)
EXCHANGE_RX = re.compile(r"binance|coinbase|kraken|okx|okex|bybit|kucoin|gemini|bitfinex|huobi|\bhtx\b|"
                         r"gate\.io|crypto\.com|bitstamp|bitget|mexc|upbit|bithumb|robinhood|exchange|hot wallet", re.I)
DEX_RX = re.compile(r"uniswap|router|1inch|\b0x\b|paraswap|cow protocol|sushiswap|curve|balancer|settler|"
                    r"aggregator|jupiter|raydium|orca|whirlpool program", re.I)

FLAG_INFO = {
    "whale":          ("Whale", "accent", "Holds $1M or more"),
    "large":          ("Large", "accent", "Holds $100k to $1M"),
    "small":          ("Small", "muted", "Holds under $100"),
    "empty":          ("Empty", "muted", "Holds under $1"),
    "known":          ("Known", "good", "Has a public name, ENS or explorer tag"),
    "exchange":       ("Exchange", "info", "Looks like a centralized exchange wallet"),
    "dex":            ("DEX / router", "info", "Swap router or aggregator"),
    "bridge":         ("Bridge", "info", "Cross-chain bridge"),
    "mixer":          ("Mixer", "danger", "Privacy mixer: funds lose their trail here"),
    "mixer_exposure": ("Mixer nearby", "danger", "A mixer appears within the traced hops"),
    "coinjoin":       ("CoinJoin", "warn", "Took part in CoinJoin transactions"),
    "contract":       ("Contract", "info", "A smart contract or program, not a person's wallet"),
    "smart_wallet":   ("Smart wallet", "info", "EOA with EIP-7702 delegated code"),
    "service":        ("Service", "info", "High-volume wallet run by a service"),
    "change":         ("Change", "muted", "Likely change back to the same owner"),
    "deposit":        ("Deposit addr", "info", "Forwards what it receives (exchange deposit pattern)"),
    "dest_tag":       ("Dest. tag", "info", "Requires destination tags (exchange/custodian)"),
    "fresh":          ("Fresh", "warn", "Fewer than 10 transactions"),
    "busy":           ("High activity", "info", "More than 10,000 transactions"),
    "scam":           ("Scam flag", "danger", "Flagged as a scam by the explorer"),
    "genesis":        ("Historic", "good", "Historically notable address"),
    "mined":          ("Mined coins", "good", "Received newly mined block rewards"),
    "vault":          ("In your vault", "good", "You have a note for this address"),
    "testnet":        ("Testnet", "muted", "Test network: coins have no value"),
}


def flags(w):
    out = []
    label = " ".join(filter(None, [w.get("label") or "", w.get("ens") or ""] + list(w.get("tags") or [])))
    usd = w.get("portfolio_usd")
    if usd is None:
        usd = w.get("balance_usd")
    kind = w.get("kind")
    if w.get("scam"):
        out.append("scam")
    if label and MIXER_RX.search(label):
        out.append("mixer")
    if label and EXCHANGE_RX.search(label):
        out.append("exchange")
    elif label and BRIDGE_RX.search(label):
        out.append("bridge")
    elif label and DEX_RX.search(label):
        out.append("dex")
    elif kind == "service":
        out.append("service")
    if kind == "change":
        out.append("change")
    is_infra = kind in ("contract", "service") or any(f in out for f in ("dex", "bridge", "exchange", "mixer"))
    if usd is not None and (not is_infra or usd >= 100_000):
        if usd >= 1_000_000:
            out.append("whale")
        elif usd >= 100_000:
            out.append("large")
        elif usd < 1:
            out.append("empty")
        elif usd < 100:
            out.append("small")
    if label:
        out.append("known")
    if w.get("address") in KNOWN_BTC:
        out.append("genesis")
    if kind == "contract" and not any(f in out for f in ("dex", "bridge", "mixer", "exchange")):
        out.append("contract")
    if w.get("smart_wallet"):
        out.append("smart_wallet")
    if w.get("requires_dest_tag"):
        out.append("dest_tag")
    if w.get("mined"):
        out.append("mined")
    n = w.get("tx_count")
    if n is not None:
        if n > 10_000 and "exchange" not in out and "service" not in out:
            out.append("busy")
        elif n < 10:
            out.append("fresh")
    if w.get("testnet"):
        out.append("testnet")
    return out


# ================================================================== public API

def wallet(address, chain="auto"):
    d = detect(address, chain)
    if d["type"] != "address":
        raise ValueError("that is a transaction hash; open it as a transaction instead")
    a = d["value"]
    cid, active = _pick_chain(a, d["chain"])
    c = get_chain(cid)
    if not c.available:
        raise RuntimeError(f"{c.name} needs a free Etherscan API key. Add it in Settings.")
    w = c.wallet(a)
    price = c.price()
    w.update({"address": a, "chain": cid, "chain_name": c.name, "symbol": c.symbol, "family": c.family,
              "price_usd": price, "active_chains": active, "candidates": d.get("candidates"),
              "explorer_url": c.addr_url(a), "testnet": c.testnet})
    if d.get("ens") and not w.get("ens"):
        w["ens"] = d["ens"]
    if not w.get("label") and w.get("ens"):
        w["label"] = w["ens"]
    w["balance_usd"] = w["balance"] * price if (price is not None and w.get("balance") is not None) else None
    tok_usd = sum((t.get("usd") or 0) for t in w.get("tokens") or [])
    w["tokens_usd"] = tok_usd
    w["portfolio_usd"] = (w["balance_usd"] or 0) + tok_usd if (w["balance_usd"] is not None or tok_usd) else None
    w["flags"] = flags(w)
    return w


def activity(address, chain="auto", limit=50, include_tokens=True, include_spam=False):
    d = detect(address, chain)
    a = d["value"]
    cid, _ = _pick_chain(a, d["chain"])
    c = get_chain(cid)
    items = c.transfers(a, int(limit))
    if not include_tokens:
        items = [i for i in items if i.get("kind") != "token"]
    if not include_spam:
        items = [i for i in items if not i.get("spam")]
    items.sort(key=lambda i: _ts(i.get("time")), reverse=True)
    return {"address": a, "chain": cid, "chain_name": c.name, "symbol": c.symbol,
            "explorer": c.explorer, "count": len(items), "items": items}


def tx(hash, chain="auto"):
    d = detect(hash, chain)
    if d["type"] != "tx":
        raise ValueError("not a transaction hash")
    if (not chain or chain == "auto") and BTC_TX.match(hash.strip()):
        # bare 64-hex hashes are used by several chains: try each until one knows it
        h = hash.strip()
        for cid, val in (("bitcoin", h.lower()), ("monero", h.lower()), ("litecoin", h.lower()),
                         ("tron", h.lower()), ("xrp", h.upper()), ("bitcoin-testnet", h.lower())):
            try:
                return REG[cid].tx(val)
            except Exception:
                continue
        raise ValueError("no supported chain knows this transaction hash")
    c = get_chain(d["chain"])
    return c.tx(d["value"])


def trace(address, chain="auto", hops=2, direction="out", per_hop=5, min_usd=0.0,
          max_nodes=40, limit=100, labels=None, follow_change=True):
    """
    Follow funds hop by hop on any supported chain.

    direction: "out" (where money went), "in" (where it came from) or "both".
    Each hop keeps the `per_hop` biggest counterparties of every frontier wallet.
    Contracts, exchanges, mixers and other services are shown but not expanded.
    On UTXO chains, change outputs are detected and followed as the same owner,
    which makes peel chains visible as long runs of change edges.
    """
    d = detect(address, chain)
    if d["type"] != "address":
        raise ValueError("trace needs an address")
    root = d["value"]
    cid, active = _pick_chain(root, d["chain"])
    c = get_chain(cid)
    if not c.available:
        raise RuntimeError(f"{c.name} needs a free Etherscan API key. Add it in Settings.")
    hops = max(1, min(int(hops), 6))
    per_hop = max(1, min(int(per_hop), 12))
    max_nodes = max(5, min(int(max_nodes), 200))
    min_usd = float(min_usd or 0)
    labels = {k.lower(): v for k, v in (labels or {}).items()}
    cs = c.kind == "utxo" or c.family in ("solana", "xrp", "ton")      # case-sensitive address formats
    norm = (lambda a: a) if cs and c.family != "ton" else (lambda a: (a or "").lower())
    if c.family == "tron":
        norm = lambda a: a  # noqa: E731

    rootw = _safe(lambda: c.lite(root), {}) or {}
    rootw["address"] = root
    rootw["kind"] = rootw.get("kind") or "wallet"
    if d.get("ens"):
        rootw["ens"] = d["ens"]
    price = c.price()
    nodes = {norm(root): {"id": norm(root), "address": root, "hop": 0, "chain": cid, "root": True,
                          "label": labels.get(norm(root).lower()) or rootw.get("label") or rootw.get("ens"),
                          "kind": rootw["kind"], "balance": rootw.get("balance"),
                          "balance_usd": rootw["balance"] * price if (price and rootw.get("balance") is not None) else None,
                          "tx_count": rootw.get("tx_count"), "in_usd": 0.0, "out_usd": 0.0}}
    edges, log = {}, []
    frontier = [root]

    def acts(a):
        try:
            return a, [x for x in c.transfers(a, limit if a == root else min(limit, 50)) if not x.get("spam")]
        except Exception as e:
            return a, e

    for h in range(1, hops + 1):
        if not frontier:
            break
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = dict(ex.map(acts, frontier))
        nxt = []
        for a in frontier:
            items = results.get(a)
            if isinstance(items, Exception):
                log.append(f"hop {h}: couldn't load {a[:10]}… ({items})")
                continue
            agg, me = {}, norm(a)
            for x in items:
                if x["direction"] == "self" or not x.get("counterparty") or x.get("kind") in ("call", "nft"):
                    continue
                if direction != "both" and x["direction"] != direction:
                    continue
                usd = x.get("usd")
                if min_usd and (usd is None or usd < min_usd) and not x.get("change"):
                    continue
                cp = norm(x["counterparty"])
                if cp == me:
                    continue
                g = agg.setdefault(cp, {"address": x["counterparty"], "usd": 0.0, "count": 0, "assets": {},
                                        "label": x.get("counterparty_label"),
                                        "kind": x.get("counterparty_kind") or "wallet",
                                        "dirs": set(), "first": x["time"], "last": x["time"], "txs": [],
                                        "change": False, "mined": False})
                g["usd"] += usd or 0
                g["count"] += 1
                g["assets"][x["asset"]] = g["assets"].get(x["asset"], 0) + (x.get("amount") or 0)
                g["dirs"].add(x["direction"])
                g["change"] = g["change"] or bool(x.get("change"))
                g["mined"] = g["mined"] or bool(x.get("mined"))
                if _ts(x["time"]) < _ts(g["first"]):
                    g["first"] = x["time"]
                if _ts(x["time"]) > _ts(g["last"]):
                    g["last"] = x["time"]
                if len(g["txs"]) < 5 and x["hash"] not in g["txs"]:
                    g["txs"].append(x["hash"])
            ranked = sorted(agg.values(), key=lambda g: (-(g["usd"]), -g["count"]))
            top = ranked[:per_hop]
            if follow_change:   # always keep the change output: that's where a peel chain continues
                top += [g for g in ranked[per_hop:] if g["change"]][:1]
            for g in top:
                cid_ = norm(g["address"])
                if cid_ not in nodes:
                    if len(nodes) >= max_nodes:
                        log.append(f"stopped at {max_nodes} wallets")
                        break
                    lab = labels.get(cid_.lower()) or g["label"]
                    kind = g["kind"]
                    if lab and SERVICE_RX.search(lab) and kind != "change":
                        kind = "service"
                    if g["address"] == "coinbase":
                        kind = "service"
                    nodes[cid_] = {"id": cid_, "address": g["address"], "hop": h, "chain": cid,
                                   "label": None if lab == "likely change" else lab, "kind": kind,
                                   "in_usd": 0.0, "out_usd": 0.0, "change_of": me if g["change"] else None}
                    if kind in ("wallet", "change"):
                        nxt.append(g["address"])
                for dname in g["dirs"]:
                    src, dst = (me, cid_) if dname == "out" else (cid_, me)
                    ek = f"{src}>{dst}"
                    e = edges.setdefault(ek, {"id": ek, "source": src, "target": dst, "usd": 0.0, "count": 0,
                                              "assets": {}, "first": g["first"], "last": g["last"],
                                              "txs": [], "hop": h, "change": False, "mined": False})
                    split = len(g["dirs"])
                    e["usd"] += g["usd"] / split
                    e["count"] += max(1, g["count"] // split)
                    for k, v in g["assets"].items():
                        e["assets"][k] = e["assets"].get(k, 0) + v / split
                    e["txs"] = (e["txs"] + g["txs"])[:5]
                    e["change"] = e["change"] or (g["change"] and dname == "out")
                    e["mined"] = e["mined"] or g["mined"]
        if c.kind == "utxo" and nxt:     # don't expand obvious services
            with ThreadPoolExecutor(max_workers=6) as ex:
                lites = dict(zip(nxt, ex.map(lambda a: _safe(lambda: c.lite(a), {}), nxt)))
            keep = []
            for a in nxt:
                if (lites.get(a) or {}).get("tx_count", 0) > 2000:
                    nodes[norm(a)]["kind"] = "service"
                else:
                    keep.append(a)
            nxt = keep
        frontier = nxt
        log.append(f"hop {h}: {len(nodes)} wallets, {len(edges)} flows")

    for e in edges.values():
        if e["source"] in nodes:
            nodes[e["source"]]["out_usd"] += e["usd"]
        if e["target"] in nodes:
            nodes[e["target"]]["in_usd"] += e["usd"]

    todo = [n for n in nodes.values() if not n.get("root")][:150]
    with ThreadPoolExecutor(max_workers=6 if c.family not in ("ton",) else 1) as ex:
        lites = list(ex.map(lambda n: _safe(lambda: c.lite(n["address"]), {}) or {}, todo))
    for n, lt in zip(todo, lites):
        for k in ("balance", "tx_count", "tags", "smart_wallet", "scam", "requires_dest_tag"):
            if lt.get(k) is not None:
                n[k] = lt[k]
        if n.get("balance") is not None and price:
            n["balance_usd"] = n["balance"] * price
        if not n.get("label") and lt.get("label"):
            n["label"] = lt["label"]
        if lt.get("kind") in ("service", "contract") and n["kind"] in ("wallet", "change"):
            n["kind"] = lt["kind"]
    mined_in = {e["target"] for e in edges.values() if e.get("mined")}
    for n in nodes.values():
        n["in_vault"] = n["id"].lower() in labels
        n["testnet"] = c.testnet
        if n.get("root"):
            n.update({k: rootw.get(k) for k in ("tags", "smart_wallet", "scam", "ens")})
            n["mined"] = n["id"] in mined_in
        n["flags"] = flags(n) + (["vault"] if n["in_vault"] else [])
        if any(f in n["flags"] for f in ("exchange", "mixer", "bridge")) and n["kind"] == "wallet":
            n["kind"] = "service"
    mixers = sorted((n for n in nodes.values() if "mixer" in n["flags"]), key=lambda n: n["hop"])
    r = nodes[norm(root)]
    if mixers:
        r["flags"].insert(0, "mixer_exposure")
        r["mixer_hops"] = mixers[0]["hop"]

    # peel-chain hint: a run of change edges
    change_edges = [e for e in edges.values() if e.get("change")]
    ends = []
    for n in nodes.values():
        if n.get("root"):
            continue
        flow = n["in_usd"] if direction != "in" else n["out_usd"]
        if n["kind"] in ("service", "contract") or n["hop"] == hops:
            ends.append({"address": n["address"], "label": n.get("label"), "kind": n["kind"],
                         "hop": n["hop"], "usd": flow, "flags": n.get("flags", [])})
    ends.sort(key=lambda x: -x["usd"])
    return {"root": root, "chain": cid, "chain_name": c.name, "symbol": c.symbol, "family": c.family,
            "direction": direction, "hops": hops, "active_chains": active, "price_usd": price,
            "nodes": list(nodes.values()), "edges": list(edges.values()),
            "endpoints": ends[:20], "change_edges": len(change_edges),
            "peel_hint": len(change_edges) >= 3,
            "log": log, "explorer": c.explorer,
            "addr_url": c.addr_url("{a}"), "tx_url": c.tx_url("{h}")}


API = {
    "detect": detect,
    "wallet": wallet,
    "activity": activity,
    "tx": tx,
    "trace": trace,
    "chains": chains,
    "flag_info": lambda: {k: {"label": a, "tone": b, "hint": c} for k, (a, b, c) in FLAG_INFO.items()},
    "settings": lambda: {"etherscan_key_set": bool(_ekey()), "solana_rpc_set": bool(settings().get("solana_rpc")),
                         "settings_path": SETTINGS_PATH},
    "save_settings": lambda etherscan_key=None, solana_rpc=None: save_settings(
        etherscan_key=(etherscan_key or "").strip() or None, solana_rpc=(solana_rpc or "").strip() or None),
}
