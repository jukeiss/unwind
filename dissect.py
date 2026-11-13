"""
dissect - binary reverse-engineering core for Unwind.

Reads compiled programs and libraries: identity, architecture, signature,
linked libraries, sections, functions (symbols + LC_FUNCTION_STARTS, so
stripped binaries still have functions), imports, strings, disassembly,
raw hex and cross-references. Wraps the system toolchain (file, lipo, nm,
objdump, otool, codesign, strings). Read-only: it never modifies a binary.
"""
import bisect
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading

IS_MAC = sys.platform == "darwin"
TIMEOUT = 120
CACHE_DIR = os.path.join(tempfile.gettempdir(), "unwind-cache")
_lock = threading.Lock()
_disasm_cache = {}   # key -> (addrs[], lines[], labels{addr:name})
_func_cache = {}


def have(tool):
    return shutil.which(tool) is not None


def run(cmd, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    except FileNotFoundError:
        return False, f"tool not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    if p.returncode != 0 and not p.stdout.strip():
        return False, (p.stderr or f"exit {p.returncode}").strip()
    return True, p.stdout


def resolve(path):
    if not path:
        raise ValueError("path is required")
    p = os.path.abspath(os.path.expanduser(str(path).strip().strip('"').strip("'")))
    # Allow pointing at an .app bundle: use its main executable.
    if p.endswith(".app") and os.path.isdir(p):
        exe = _app_executable(p)
        if exe:
            p = exe
    if not os.path.exists(p):
        raise ValueError(f"no such file: {p}")
    if not os.path.isfile(p):
        raise ValueError(f"not a file: {p}")
    return p


def _app_executable(app):
    plist = os.path.join(app, "Contents", "Info.plist")
    name = None
    if os.path.exists(plist):
        ok, out = run(["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleExecutable", plist])
        if ok:
            name = out.strip()
    if not name:
        name = os.path.splitext(os.path.basename(app))[0]
    exe = os.path.join(app, "Contents", "MacOS", name)
    return exe if os.path.isfile(exe) else None


def _key(p):
    st = os.stat(p)
    return hashlib.sha1(f"{p}:{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:16]


def archs(p):
    if not IS_MAC:
        return []
    ok, out = run(["lipo", "-archs", p])
    return out.split() if ok else []


def pick_arch(p, arch=None):
    a = archs(p)
    if not a:
        return None
    if arch and arch in a:
        return arch
    host = platform.machine()
    for c in (host, host + "e", "arm64", "arm64e", "x86_64"):
        if c in a:
            return c
    return a[0]


def thin(p, arch):
    """Return a single-architecture copy of p (cached), or p itself."""
    a = archs(p)
    if len(a) <= 1 or not arch:
        return p
    os.makedirs(CACHE_DIR, exist_ok=True)
    out = os.path.join(CACHE_DIR, f"{_key(p)}-{arch}")
    if not os.path.exists(out):
        ok, msg = run(["lipo", p, "-thin", arch, "-output", out])
        if not ok:
            return p
    return out


def _target(path, arch=None):
    p = resolve(path)
    a = pick_arch(p, arch)
    return p, a, thin(p, a)


# ---------------------------------------------------------------- summary

def summary(path, arch=None):
    p, a, t = _target(path, arch)
    info = {"path": p, "name": os.path.basename(p), "size": os.path.getsize(p),
            "archs": archs(p), "arch": a}
    ok, out = run(["file", "-b", p])
    info["type"] = out.strip().split("\n")[0] if ok else "unknown"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    info["sha256"] = h.hexdigest()

    if IS_MAC:
        ok, out = run(["codesign", "-dvvv", p])
        sig = {}
        if ok or out:
            txt = out
        # codesign writes to stderr
        r = subprocess.run(["codesign", "-dvvv", p], capture_output=True, text=True, errors="replace")
        txt = r.stderr + r.stdout
        for line in txt.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                if k == "Authority":
                    sig.setdefault("authority", []).append(v.strip())
                elif k in ("Identifier", "TeamIdentifier", "Format", "Signature size", "Timestamp", "Runtime Version"):
                    sig[k.lower().replace(" ", "_")] = v.strip()
            elif "not signed" in line:
                sig["unsigned"] = True
        info["signature"] = sig

        ok, out = run(["otool", "-L", t])
        libs = []
        if ok:
            for line in out.splitlines()[1:]:
                line = line.strip()
                if line:
                    libs.append(line.split(" (")[0])
        info["libraries"] = libs
        info["entry"] = _entry(t)
    else:
        info["signature"] = {}
        info["libraries"] = []
        info["entry"] = None

    info["sections"] = sections(path, arch)
    funcs = functions(path, arch)
    info["function_count"] = len(funcs)
    info["named_function_count"] = sum(1 for f in funcs if not f["name"].startswith("sub_"))
    info["import_count"] = len(imports(path, arch))
    return info


def _entry(t):
    ok, out = run(["otool", "-l", t])
    if not ok:
        return None
    text_vm, entryoff = None, None
    lines = out.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s == "segname __TEXT":
            for nxt in lines[i + 1:i + 3]:
                if nxt.strip().startswith("vmaddr"):
                    text_vm = int(nxt.split()[1], 16)
        if s == "cmd LC_MAIN":
            for nxt in lines[i + 1:i + 4]:
                if nxt.strip().startswith("entryoff"):
                    entryoff = int(nxt.split()[1])
    if text_vm is not None and entryoff is not None:
        return hex(text_vm + entryoff)
    return None


def sections(path, arch=None):
    p, a, t = _target(path, arch)
    ok, out = run(["objdump", "-h", t])
    rows = []
    if ok:
        for line in out.splitlines():
            m = re.match(r"\s*(\d+)\s+(\S+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s*(.*)", line)
            if m:
                rows.append({"name": m.group(2), "size": int(m.group(3), 16),
                             "addr": "0x" + m.group(4).lstrip("0").rjust(1, "0"), "kind": m.group(5).strip()})
    return rows


# ---------------------------------------------------------------- symbols

def _nm(t):
    ok, out = run(["nm", "-P", "-n", t])
    rows = []
    if not ok:
        return rows
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        name, typ, val = parts[0], parts[1], parts[2]
        rows.append((name, typ, val))
    return rows


def imports(path, arch=None):
    p, a, t = _target(path, arch)
    return sorted({n for n, typ, _ in _nm(t) if typ == "U"})


def functions(path, arch=None):
    """Every function we can find: named symbols plus function-starts."""
    p, a, t = _target(path, arch)
    k = (t, "funcs")
    if k in _func_cache:
        return _func_cache[k]
    named = {}
    for name, typ, val in _nm(t):
        if typ in ("T", "t") and val:
            try:
                addr = int(val, 16)
            except ValueError:
                continue
            if name in ("__mh_execute_header",):
                continue
            named.setdefault(addr, name)
    starts = set(named)
    if IS_MAC:
        ok, out = run(["objdump", "--macho", "--function-starts", t])
        if ok:
            for line in out.splitlines():
                s = line.strip().split()[0] if line.strip() else ""
                if re.fullmatch(r"[0-9a-fA-F]{6,16}", s):
                    starts.add(int(s, 16))
    entry = _entry(t) if IS_MAC else None
    entry_i = int(entry, 16) if entry else None
    objc_names = {}
    if IS_MAC:
        for c in _objc_parse(t, p):
            for m in c["methods"]:
                if m["imp"]:
                    objc_names.setdefault(m["imp"], f"{m['kind']}[{c['display']} {m['sel']}]")
        starts |= set(objc_names)
    addrs = sorted(starts)
    dem = demangle_many([named[a] for a in named])
    out = []
    for i, ad in enumerate(addrs):
        nxt = addrs[i + 1] if i + 1 < len(addrs) else None
        name = named.get(ad) or objc_names.get(ad) or f"sub_{ad:x}"
        if entry_i == ad and name.startswith("sub_"):
            name = "entry"
        disp = dem.get(name, name)
        out.append({"addr": hex(ad), "name": name, "display": disp if disp != name else None,
                    "size": (nxt - ad) if nxt else None,
                    "named": ad in named or ad in objc_names, "objc": ad in objc_names and ad not in named})
    _func_cache[k] = out
    return out


# ---------------------------------------------------------------- demangling

_dem_cache = {}


def demangle_many(names):
    """Swift ($s…, _T…) and C++ (_Z…) symbols to readable names. Returns {mangled: readable}."""
    todo = [n for n in set(names) if n and n not in _dem_cache and re.match(r"^_*(\$s|\$S|_T|\$e|Z|_Z)", n)]
    if todo and IS_MAC:
        swift = shutil.which("swift-demangle")
        cmd = [swift] if swift else ["xcrun", "swift-demangle"]
        try:
            r = subprocess.run(cmd + ["--compact"], input="\n".join(todo), capture_output=True, text=True, timeout=60)
            outs = r.stdout.split("\n")
            for n, o in zip(todo, outs):
                if o and o != n:
                    _dem_cache[n] = o.strip()
        except Exception:
            pass
        cxx = [n for n in todo if n not in _dem_cache and re.match(r"^_*_Z", n)]
        if cxx and have("c++filt"):
            try:
                r = subprocess.run(["c++filt", "-_"], input="\n".join(cxx), capture_output=True, text=True, timeout=60)
                for n, o in zip(cxx, r.stdout.split("\n")):
                    if o and o != n:
                        _dem_cache[n] = o.strip()
            except Exception:
                pass
        for n in todo:
            _dem_cache.setdefault(n, n)
    return {n: _dem_cache.get(n, n) for n in names if n}


def demangle(names):
    """API: demangle a list of symbol names."""
    if isinstance(names, str):
        names = [names]
    return demangle_many(list(names))


# ---------------------------------------------------------------- Objective-C

_objc_cache = {}


def _bad_sel(sel):
    return not sel or sel.startswith("(") or "past end" in sel


def _objc_parse(t, p=None):
    """
    Classes and methods from the Objective-C metadata (works on stripped binaries).
    objdump can't follow arm64e chained pointers to selector names, so when a slice's names are
    unreadable we borrow them from another slice of the same binary, but only if the class and
    method layout matches exactly (same source, same order). Otherwise names stay as placeholders.
    """
    if t in _objc_cache:
        return _objc_cache[t]
    classes = _objc_parse_raw(t)
    ms = [m for c in classes for m in c["methods"]]
    if p and ms and sum(1 for m in ms if _bad_sel(m["sel"])) > len(ms) / 2:
        for other in archs(p):
            ot = thin(p, other)
            if ot == t:
                continue
            oc = _objc_parse_raw(ot)
            if [len(c["methods"]) for c in oc] == [len(c["methods"]) for c in classes] and \
                    sum(1 for c in oc for m in c["methods"] if _bad_sel(m["sel"])) == 0:
                for c, c2 in zip(classes, oc):
                    if _bad_sel(c["name"]):
                        c["name"] = c2["name"]
                    for m, m2 in zip(c["methods"], c2["methods"]):
                        m["sel"] = m2["sel"]
                    c["ivars"] = c2["ivars"] or c["ivars"]
                    c["properties"] = c2["properties"] or c["properties"]
                break
    for c in classes:
        c["methods"] = [m for m in c["methods"] if not _bad_sel(m["sel"])] or \
            [dict(m, sel=f"method_{i}") for i, m in enumerate(c["methods"])]
    dem = demangle_many([c["name"] for c in classes])
    for c in classes:
        d = dem.get(c["name"], c["name"])
        c["display"] = d if d != c["name"] else c["name"]
    _objc_cache[t] = classes
    return classes


def _objc_parse_raw(t):
    ok, out = run(["objdump", "--macho", "--objc-meta-data", t], timeout=180)
    classes, byname = [], {}
    cur, meta, section, sel, sup = None, False, None, None, None
    if ok:
        for line in out.splitlines():
            if not line.strip():
                continue
            if "Meta Class" in line:
                meta = True
                continue
            if re.match(r"^[0-9a-fA-F]{8,}\s+0x", line):
                meta, cur, section, sup = False, None, None, None
                continue
            m = re.match(r"^\s{4}superclass\s+\S+\s*(\S*)", line)
            if m:
                sup = re.sub(r"^_OBJC_(META)?CLASS_\$_", "", m.group(1)) or None
                continue
            m = re.match(r"^\s{8}name\s+0x[0-9a-fA-F]+\s+(.+)$", line)
            if m:
                nm = m.group(1).strip()
                if meta and nm in byname:
                    cur = byname[nm]
                else:
                    cur = {"name": nm, "superclass": sup, "methods": [], "ivars": [], "properties": []}
                    byname[nm] = cur
                    classes.append(cur)
                continue
            m = re.match(r"^\s{8}(baseMethods|ivars|baseProperties|baseProtocols)\b", line)
            if m:
                section = m.group(1)
                continue
            if cur is None:
                continue
            m = re.match(r"^\s{12}name\s+0x[0-9a-fA-F]+\s+(.+)$", line)
            if m:
                sel = m.group(1).strip()
                if section == "ivars":
                    cur["ivars"].append(sel)
                elif section == "baseProperties":
                    cur["properties"].append(sel)
                continue
            m = re.match(r"^\s{12}imp\s+0x([0-9a-fA-F]+)(?:\s+\(0x([0-9a-fA-F]+))?", line)
            if m and section == "baseMethods" and sel:
                # relative method lists (arm64e): objdump prints the resolved address in parentheses
                imp = int(m.group(2) or m.group(1), 16)
                cur["methods"].append({"sel": sel, "imp": imp or None, "kind": "+" if meta else "-"})
                sel = None
    return classes


def objc(path, filter=None, arch=None):
    """Objective-C / Swift classes with their methods, ivars and properties."""
    p, a, t = _target(path, arch)
    if not IS_MAC:
        return {"classes": [], "total": 0}
    rx = _rx(filter)
    out = []
    for c in _objc_parse(t, p):
        if rx and not (rx.search(c["display"]) or any(rx.search(m["sel"]) for m in c["methods"])):
            continue
        out.append({"name": c["display"], "raw": c["name"], "superclass": c["superclass"],
                    "methods": [{"sel": m["sel"], "kind": m["kind"], "addr": hex(m["imp"]) if m["imp"] else None}
                                for m in c["methods"]],
                    "ivars": c["ivars"][:200], "properties": c["properties"][:200]})
    return {"total": len(out), "methods": sum(len(c["methods"]) for c in out), "classes": out[:1500]}


def symbols(path, filter=None, limit=2000, arch=None):
    p, a, t = _target(path, arch)
    rows = []
    kinds = {"T": "function", "t": "function", "U": "import", "D": "data", "d": "data",
             "B": "bss", "b": "bss", "S": "data", "s": "data", "C": "common", "I": "indirect"}
    rx = _rx(filter)
    for name, typ, val in _nm(t):
        if rx and not rx.search(name):
            continue
        rows.append({"name": name, "kind": kinds.get(typ, typ), "local": typ.islower(),
                     "addr": ("0x" + val.lstrip("0")) if val.strip("0") else None})
    return {"total": len(rows), "items": rows[:int(limit)]}


def _rx(filter):
    if not filter:
        return None
    try:
        return re.compile(filter, re.I)
    except re.error:
        return re.compile(re.escape(filter), re.I)


# ---------------------------------------------------------------- strings

STRING_PRESETS = {
    "urls": r"https?://|wss?://|ftp://",
    "paths": r"^(/|~/)[\w.\-/]+|\.(plist|json|db|sqlite|log|conf|cfg)$",
    "errors": r"error|fail|invalid|denied|unable|cannot|could not|exception",
    "crypto": r"\b(aes|rsa|sha-?\d+|hmac|md5|ecdsa|ed25519|pbkdf|bcrypt|chacha|cipher|private key|public key|base64)\b",
    "format": r"%[-+ #0]*\d*(\.\d+)?(l|ll|h|z)?[diouxXeEfgGcsp@]",
    "keys": r"(api[_-]?key|token|secret|password|bearer|authorization)",
}


def strings(path, min_len=5, filter=None, preset=None, limit=3000):
    p = resolve(path)
    ok, out = run(["strings", "-a", "-t", "x", "-n", str(int(min_len)), p])
    if not ok:
        raise RuntimeError(out)
    rx = _rx(STRING_PRESETS.get(preset) if preset else filter)
    rx2 = _rx(filter) if preset and filter else None
    items = []
    for line in out.splitlines():
        m = re.match(r"\s*([0-9a-fA-F]+)\s(.*)", line)
        if not m:
            continue
        s = m.group(2)
        if rx and not rx.search(s):
            continue
        if rx2 and not rx2.search(s):
            continue
        items.append({"offset": int(m.group(1), 16), "text": s})
    return {"total": len(items), "items": items[:int(limit)]}


# ---------------------------------------------------------------- disassembly

def _disasm(t):
    with _lock:
        if t in _disasm_cache:
            return _disasm_cache[t]
    cmd = ["objdump", "--macho", "-d", "--no-show-raw-insn", t] if IS_MAC else \
          ["objdump", "-d", "--no-show-raw-insn", "-M", "intel", t]
    ok, out = run(cmd, timeout=300)
    if not ok:
        raise RuntimeError(out)
    addrs, lines, labels = [], [], {}
    pending = None
    for line in out.splitlines():
        m = re.match(r"\s*([0-9a-fA-F]+):\s+(.*)", line)
        if m:
            ad = int(m.group(1), 16)
            if pending:
                labels[ad] = pending
                pending = None
            addrs.append(ad)
            lines.append(m.group(2).replace("\t", " ").strip())
        else:
            lm = re.match(r"^([^\s(].*):$", line.strip())
            if lm and not line.startswith("/") and "section" not in line:
                pending = lm.group(1)
    data = (addrs, lines, labels)
    with _lock:
        _disasm_cache[t] = data
    return data


def disassemble(path, symbol=None, address=None, arch=None, max_lines=3000):
    """Disassemble one function, chosen by name or by any address inside it."""
    p, a, t = _target(path, arch)
    funcs = functions(path, arch)
    addrs, lines, labels = _disasm(t)
    if not addrs:
        return {"function": None, "lines": []}
    starts = [int(f["addr"], 16) for f in funcs]
    target = None
    if symbol:
        for f in funcs:
            if f["name"] == symbol or f["name"] == "_" + symbol or f["name"].lstrip("_") == symbol.lstrip("_"):
                target = int(f["addr"], 16)
                break
        if target is None:
            raise ValueError(f"function '{symbol}' not found")
    elif address is not None:
        target = int(str(address), 16) if isinstance(address, str) else int(address)
    else:
        e = _entry(t) if IS_MAC else None
        target = int(e, 16) if e else (starts[0] if starts else addrs[0])

    i = bisect.bisect_right(starts, target) - 1
    fstart = starts[i] if i >= 0 else addrs[0]
    fend = starts[i + 1] if 0 <= i + 1 < len(starts) else None
    func = funcs[i] if i >= 0 else {"addr": hex(fstart), "name": f"sub_{fstart:x}"}
    lo = bisect.bisect_left(addrs, fstart)
    hi = bisect.bisect_left(addrs, fend) if fend else len(addrs)
    hi = min(hi, lo + int(max_lines))
    rows = [{"addr": hex(addrs[j]), "text": lines[j]} for j in range(lo, hi)]
    name_by_addr = {int(f["addr"], 16): (f.get("display") or f["name"]) for f in funcs}
    # annotate direct branch targets with function names; demangle stub names
    stubs = {}
    for r in rows:
        m = re.search(r"\b0x([0-9a-fA-F]{6,16})\b", r["text"])
        if m:
            ta = int(m.group(1), 16)
            if ta in name_by_addr and "symbol stub" not in r["text"]:
                r["target"] = name_by_addr[ta]
        sm = re.search(r"symbol stub for: (\S+)", r["text"])
        if sm:
            stubs[id(r)] = sm.group(1)
    dem = demangle_many(list(stubs.values()))
    for r in rows:
        if id(r) in stubs:
            d = dem.get(stubs[id(r)])
            if d and d != stubs[id(r)]:
                r["demangled"] = d
    fd = dict(func)
    return {"function": fd, "arch": a, "truncated": hi - lo >= int(max_lines), "lines": rows}


def brief(path, address=None, symbol=None, arch=None, max_lines=400):
    """A compact description of one function for an AI to explain: code, strings it uses, what it calls."""
    d = disassemble(path, symbol=symbol, address=address, arch=arch, max_lines=max_lines)
    f = d["function"] or {}
    lits, calls, callers = [], [], []
    for r in d["lines"]:
        m = re.search(r'literal pool for: "(.*)"', r["text"])
        if m and m.group(1) not in lits:
            lits.append(m.group(1))
        sm = re.search(r"symbol stub for: (\S+)", r["text"])
        if sm:
            nm = r.get("demangled") or sm.group(1)
            if nm not in calls:
                calls.append(nm)
        elif r.get("target") and r["target"] not in calls:
            calls.append(r["target"])
    try:
        callers = sorted({h["function"] for h in xrefs(path, f.get("addr", ""), arch, limit=60)["items"]
                          if h.get("function") and h["function"] != f.get("name")})[:20]
    except Exception:
        pass
    asm = "\n".join(f"{r['addr']}: {r['text']}" + (f"   ; {r['target']}" if r.get("target") else "")
                    + (f"   ; {r['demangled']}" if r.get("demangled") else "") for r in d["lines"])
    return {"function": f.get("display") or f.get("name"), "addr": f.get("addr"), "arch": d.get("arch"),
            "instructions": len(d["lines"]), "truncated": d["truncated"],
            "strings": lits[:60], "calls": calls[:80], "called_from": callers, "asm": asm}


def xrefs(path, needle, arch=None, limit=500):
    """Find instructions that mention a name, address or constant."""
    p, a, t = _target(path, arch)
    addrs, lines, _ = _disasm(t)
    funcs = functions(path, arch)
    starts = [int(f["addr"], 16) for f in funcs]
    n = needle.strip()
    if re.fullmatch(r"(0x)?[0-9a-fA-F]{6,16}", n):
        rx = re.compile(r"\b0x0*" + n.lower().replace("0x", "").lstrip("0") + r"\b", re.I)
    else:
        rx = re.compile(re.escape(n), re.I)
    hits = []
    for ad, text in zip(addrs, lines):
        if rx.search(text):
            i = bisect.bisect_right(starts, ad) - 1
            hits.append({"addr": hex(ad), "text": text,
                         "function": funcs[i]["name"] if i >= 0 else None})
            if len(hits) >= int(limit):
                break
    return {"needle": needle, "total": len(hits), "items": hits}


def hexdump(path, offset=0, length=512):
    p = resolve(path)
    if isinstance(offset, str):
        offset = int(offset, 16) if offset.lower().startswith("0x") else int(offset)
    offset = max(0, int(offset))
    length = max(16, min(int(length), 8192))
    with open(p, "rb") as f:
        f.seek(offset)
        data = f.read(length)
    rows = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        rows.append({"offset": offset + i, "hex": chunk.hex(),
                     "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)})
    return {"offset": offset, "size": os.path.getsize(p), "rows": rows}


API = {
    "summary": summary,
    "sections": sections,
    "functions": functions,
    "symbols": symbols,
    "imports": imports,
    "strings": strings,
    "disassemble": disassemble,
    "xrefs": xrefs,
    "hexdump": hexdump,
    "objc": objc,
    "demangle": demangle,
    "brief": brief,
}
