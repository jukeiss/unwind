#!/usr/bin/env python3
"""
Unwind - local app server.

    python3 app.py            # starts on http://127.0.0.1:7878 and opens your browser
    python3 app.py --port 9000 --no-open

Binds to 127.0.0.1 only. Every API call needs the per-launch token that is
embedded in the page, and the Host header must be localhost, so other
websites open in your browser can't drive it.
"""
import argparse
import json
import mimetypes
import os
import secrets
import socket
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ai           # noqa: E402
import chaintrace   # noqa: E402
import connectors   # noqa: E402
import correlate    # noqa: E402
import dissect      # noqa: E402
import forensics    # noqa: E402
import heuristics   # noqa: E402
import keys         # noqa: E402
import malware      # noqa: E402
import history      # noqa: E402
import vault        # noqa: E402

VERSION = "0.3.0"
TOKEN = secrets.token_urlsafe(24)
UI = os.path.join(HERE, "ui")


def _wallet(address, chain="auto", **kw):
    w = chaintrace.wallet(address, chain)
    labels = vault.labels()
    if w["address"].lower() in labels:
        w["flags"].append("vault")
        w["vault_label"] = labels[w["address"].lower()]
        w["vault_path"] = vault._address_path(w["address"])
    return w


def _trace(address, **kw):
    kw.setdefault("labels", vault.labels())
    return chaintrace.trace(address, **kw)


def _save_wallet(address, chain="auto", with_exposure=True, with_links=True):
    w = chaintrace.wallet(address, chain)
    act = exp = lk = None
    try:
        act = chaintrace.activity(w["address"], w["chain"], limit=60)
    except Exception:
        pass
    if with_exposure:
        try:
            exp = forensics.exposure(w["address"], w["chain"])
        except Exception:
            pass
    if with_links:
        try:
            lk = correlate.links(w["address"], w["chain"])
        except Exception:
            pass
    return vault.save_wallet(w, act, exp, lk)


def _info():
    py = sys.executable or "python3"
    mcp = os.path.join(HERE, "unwind_mcp.py")
    return {
        "version": VERSION, "app_dir": HERE, "vault": vault._root(), "python": py,
        "mcp_server": mcp,
        "claude_code_command": f'claude mcp add unwind -- "{py}" "{mcp}"',
        "mcp_json": {"mcpServers": {"unwind": {"command": py, "args": [mcp]}}},
        "chains": len(chaintrace.REG),
        "settings": chaintrace.API["settings"](),
    }


MODULES = {
    "bin": dissect.API,
    "chain": {**chaintrace.API, "wallet": _wallet, "trace": _trace},
    "forensics": forensics.API,
    "heur": heuristics.API,
    "corr": correlate.API,
    "hist": history.API,
    "ai": ai.API,
    "keys": keys.API,
    "conn": connectors.API,
    "mal": malware.API,
    "vault": {**vault.API, "save_wallet": lambda address, chain="auto": _save_wallet(address, chain)},
    "sys": {"info": _info},
}


class Handler(BaseHTTPRequestHandler):
    server_version = "unwind/" + VERSION

    def log_message(self, fmt, *args):
        if os.environ.get("UNWIND_DEBUG"):
            sys.stderr.write("  " + fmt % args + "\n")

    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, "forbidden", "text/plain")
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(os.path.join(UI, "index.html"), encoding="utf-8") as f:
                html = f.read().replace("__UNWIND_TOKEN__", TOKEN)
            return self._send(200, html, "text/html; charset=utf-8")
        rel = os.path.normpath(path.lstrip("/"))
        full = os.path.realpath(os.path.join(UI, rel))
        if not full.startswith(os.path.realpath(UI) + os.sep) or not os.path.isfile(full):
            return self._send(404, "not found", "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype)

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Unwind-Token") != TOKEN:
            return self._send(403, json.dumps({"ok": False, "error": "forbidden"}))
        parts = self.path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "api":
            return self._send(404, json.dumps({"ok": False, "error": "unknown endpoint"}))
        mod, fn = MODULES.get(parts[1]), None
        if mod:
            fn = mod.get(parts[2])
        if not fn:
            return self._send(404, json.dumps({"ok": False, "error": f"unknown function {parts[1]}.{parts[2]}"}))
        try:
            n = int(self.headers.get("Content-Length") or 0)
            args = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
            data = fn(**args)
            return self._send(200, json.dumps({"ok": True, "data": data}, default=str))
        except TypeError as e:
            return self._send(200, json.dumps({"ok": False, "error": f"bad arguments: {e}"}))
        except Exception as e:
            if os.environ.get("UNWIND_DEBUG"):
                traceback.print_exc()
            return self._send(200, json.dumps({"ok": False, "error": str(e) or type(e).__name__}))


def free_port(start):
    for p in range(start, start + 50):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise SystemExit("no free port found")


def main():
    ap = argparse.ArgumentParser(description="Unwind local app")
    ap.add_argument("--port", type=int, default=7878)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    vault.ensure_welcome()
    port = free_port(a.port)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  Unwind {VERSION}\n  → {url}\n  vault: {vault._root()}\n  Ctrl+C to stop\n", flush=True)
    if not a.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")


if __name__ == "__main__":
    main()
