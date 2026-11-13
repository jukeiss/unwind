"""
connectors - plug any REST API into Unwind.

Add an API by hand (base URL + auth + endpoints) or import its OpenAPI / Swagger
spec. Each connector becomes:
  - a panel in Settings where you can try endpoints, and
  - one tool the AI assistant (and MCP clients) can call: api_<name>.

Connectors are read-only by default: only GET/HEAD calls run unless you tick
"allow changes" for that connector. Definitions and their keys live in
~/.config/unwind/connectors.json (owner-only permissions).
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

PATH = os.path.expanduser("~/.config/unwind/connectors.json")
MAX_ENDPOINTS = 80
MAX_OUT = 30_000
SAFE_METHODS = {"GET", "HEAD"}


def _load():
    try:
        with open(PATH) as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w") as f:
        json.dump(d, f, indent=2)
    os.chmod(PATH, 0o600)


def _slug(s):
    s = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return s[:40] or "api"


def _public(c):
    """Connector as the UI sees it: never includes the secret."""
    a = dict(c.get("auth") or {})
    a["value_set"] = bool(a.pop("value", None))
    return {**{k: v for k, v in c.items() if k != "auth"}, "auth": a}


def list_connectors():
    return {"connectors": [_public(c) for c in _load().values()], "path": PATH}


def save(name, base_url, description="", auth_type="none", auth_name="", auth_value=None,
         allow_writes=False, endpoints=None, headers=None):
    """Create or update a connector. Leave auth_value empty to keep the saved secret."""
    sid = _slug(name)
    if not re.match(r"^https?://", base_url or ""):
        raise ValueError("Base URL must start with http:// or https://")
    d = _load()
    old = d.get(sid) or {}
    auth = {"type": auth_type, "name": auth_name or {"bearer": "Authorization", "header": "X-API-Key",
                                                     "query": "api_key"}.get(auth_type, "")}
    if auth_value:
        auth["value"] = auth_value.strip()
    elif (old.get("auth") or {}).get("value") and auth_type != "none":
        auth["value"] = old["auth"]["value"]
    eps = endpoints if endpoints is not None else old.get("endpoints") or []
    clean = []
    for e in eps[:MAX_ENDPOINTS]:
        if not e.get("path"):
            continue
        clean.append({"id": _slug(e.get("id") or f"{e.get('method', 'get')}_{e['path']}"),
                      "method": (e.get("method") or "GET").upper(), "path": e["path"],
                      "summary": (e.get("summary") or "")[:200],
                      "params": [{"name": p["name"], "in": p.get("in", "query"), "required": bool(p.get("required")),
                                  "description": (p.get("description") or "")[:160], "type": p.get("type", "string")}
                                 for p in (e.get("params") or []) if p.get("name")]})
    d[sid] = {"id": sid, "name": name.strip(), "base_url": base_url.rstrip("/"), "description": description.strip(),
              "auth": auth, "allow_writes": bool(allow_writes), "endpoints": clean,
              "headers": headers or old.get("headers") or {}}
    _save(d)
    return _public(d[sid])


def delete(id):
    d = _load()
    if id not in d:
        raise ValueError("no such connector")
    d.pop(id)
    _save(d)
    return {"deleted": id}


# ------------------------------------------------------------------ OpenAPI

def _fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "unwind/0.4", "Accept": "application/json, */*"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(8_000_000).decode("utf-8", "replace")


def _parse_spec(text):
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    try:
        import yaml  # optional
        return yaml.safe_load(text)
    except ImportError:
        raise ValueError("This spec is YAML. Paste the JSON version (most API docs offer openapi.json), "
                         "or install PyYAML.")


def _resolve(spec, obj):
    """Follow a local $ref like #/components/parameters/Foo."""
    seen = 0
    while isinstance(obj, dict) and "$ref" in obj and seen < 10:
        ref = obj["$ref"]
        if not ref.startswith("#/"):
            return obj
        cur = spec
        for part in ref[2:].split("/"):
            cur = (cur or {}).get(part.replace("~1", "/").replace("~0", "~"))
        obj, seen = cur or {}, seen + 1
    return obj


def import_openapi(name, spec_url=None, spec_text=None, base_url=None, auth_type=None, auth_name=None,
                   auth_value=None, allow_writes=False):
    """Turn an OpenAPI 3 / Swagger 2 spec (URL or pasted JSON) into a connector."""
    if not spec_text and not spec_url:
        raise ValueError("Give the spec's URL or paste its JSON")
    spec = _parse_spec(spec_text or _fetch_text(spec_url))
    if not isinstance(spec, dict) or "paths" not in spec:
        raise ValueError("That doesn't look like an OpenAPI or Swagger spec (no 'paths').")
    if not base_url:
        servers = spec.get("servers") or []
        if servers and servers[0].get("url"):
            base_url = servers[0]["url"]
            if base_url.startswith("/") and spec_url:
                base_url = urllib.parse.urljoin(spec_url, base_url)
        elif spec.get("host"):
            scheme = (spec.get("schemes") or ["https"])[0]
            base_url = f"{scheme}://{spec['host']}{spec.get('basePath', '')}"
        elif spec_url:
            u = urllib.parse.urlparse(spec_url)
            base_url = f"{u.scheme}://{u.netloc}"
    if not base_url:
        raise ValueError("The spec has no server URL. Enter the base URL yourself.")
    # guess auth from securitySchemes if not given
    if not auth_type:
        schemes = (spec.get("components") or {}).get("securitySchemes") or spec.get("securityDefinitions") or {}
        for s in schemes.values():
            s = _resolve(spec, s)
            if s.get("type") == "apiKey":
                auth_type, auth_name = ("query" if s.get("in") == "query" else "header"), s.get("name")
                break
            if s.get("type") == "http" and s.get("scheme", "").lower() == "bearer":
                auth_type, auth_name = "bearer", "Authorization"
                break
        auth_type = auth_type or "none"
    eps = []
    for path, item in (spec.get("paths") or {}).items():
        item = _resolve(spec, item) or {}
        shared = [_resolve(spec, p) for p in item.get("parameters") or []]
        for method in ("get", "post", "put", "patch", "delete"):
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            params = {}
            for p in shared + [_resolve(spec, p) for p in op.get("parameters") or []]:
                if p.get("in") in ("path", "query") and p.get("name"):
                    params[(p["in"], p["name"])] = {"name": p["name"], "in": p["in"], "required": p.get("required", p["in"] == "path"),
                                                    "description": p.get("description", ""),
                                                    "type": (p.get("schema") or {}).get("type") or p.get("type") or "string"}
            if op.get("requestBody") or any(_resolve(spec, p).get("in") == "body" for p in op.get("parameters") or []):
                params[("body", "body")] = {"name": "body", "in": "body", "required": False,
                                            "description": "JSON request body", "type": "object"}
            eps.append({"id": op.get("operationId") or f"{method}_{path}", "method": method.upper(), "path": path,
                        "summary": op.get("summary") or op.get("description", "")[:160], "params": list(params.values())})
    eps.sort(key=lambda e: (e["method"] not in SAFE_METHODS, e["path"]))
    info = spec.get("info") or {}
    c = save(name or info.get("title") or "api", base_url, description=(info.get("description") or info.get("title") or "")[:400],
             auth_type=auth_type, auth_name=auth_name or "", auth_value=auth_value, allow_writes=allow_writes, endpoints=eps)
    c["imported_endpoints"] = len(eps)
    c["truncated"] = len(eps) > MAX_ENDPOINTS
    return c


# ------------------------------------------------------------------ calling

def call(connector, endpoint, params=None):
    """Call one endpoint. Path parameters are URL-encoded so they can't change the host."""
    d = _load()
    c = d.get(connector) or d.get(_slug(connector))
    if not c:
        raise ValueError(f"no connector named '{connector}'")
    e = next((x for x in c["endpoints"] if x["id"] == endpoint or x["id"] == _slug(endpoint)), None)
    if not e:
        raise ValueError(f"'{c['name']}' has no endpoint '{endpoint}'. Options: {', '.join(x['id'] for x in c['endpoints'][:30])}")
    if e["method"] not in SAFE_METHODS and not c.get("allow_writes"):
        raise PermissionError(f"{e['method']} calls are blocked for '{c['name']}' (read-only connector). "
                              "Turn on 'allow changes' in Settings → Connectors if you want this.")
    params = dict(params or {})
    path = e["path"]
    for p in e["params"]:
        if p["in"] == "path":
            if p["name"] not in params:
                raise ValueError(f"missing path parameter '{p['name']}'")
            path = path.replace("{" + p["name"] + "}", urllib.parse.quote(str(params.pop(p["name"])), safe=""))
    body = params.pop("body", None)
    query = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items() if v is not None}
    a = c.get("auth") or {}
    headers = {"User-Agent": "unwind/0.4", "Accept": "application/json, text/plain, */*", **(c.get("headers") or {})}
    if a.get("value"):
        if a["type"] == "bearer":
            headers["Authorization"] = f"Bearer {a['value']}"
        elif a["type"] == "header":
            headers[a.get("name") or "X-API-Key"] = a["value"]
        elif a["type"] == "query":
            query[a.get("name") or "api_key"] = a["value"]
    url = c["base_url"] + (path if path.startswith("/") else "/" + path)
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query, doseq=True)
    data = None
    if e["method"] not in ("GET", "HEAD") and body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=e["method"])
    shown = url if a.get("type") != "query" else url.replace(urllib.parse.quote(str(a.get("value", ""))), "•••")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read(5_000_000).decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as err:
        raw, status = err.read(200_000).decode("utf-8", "replace"), err.code
    except urllib.error.URLError as err:
        raise RuntimeError(f"Couldn't reach {urllib.parse.urlparse(url).netloc}: {err.reason}")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = raw
    text = json.dumps(result, default=str) if not isinstance(result, str) else result
    return {"status": status, "url": shown, "truncated": len(text) > MAX_OUT,
            "result": result if len(text) <= MAX_OUT else text[:MAX_OUT]}


def as_tools():
    """One AI/MCP tool per connector: api_<id>(endpoint, params)."""
    tools = []
    for c in _load().values():
        if not c.get("endpoints"):
            continue
        lines = [f"- {e['id']}: {e['method']} {e['path']}" + (f" — {e['summary']}" if e["summary"] else "")
                 + (f" (params: {', '.join(p['name'] + ('*' if p['required'] else '') for p in e['params'])})" if e["params"] else "")
                 for e in c["endpoints"][:40]]
        desc = (f"Call the user's '{c['name']}' API ({c['base_url']}). {c.get('description', '')[:300]}\n"
                f"{'Read-only: only GET endpoints work.' if not c.get('allow_writes') else 'Changes allowed.'}\nEndpoints (* = required):\n"
                + "\n".join(lines))[:3000]
        schema = {"type": "object", "properties": {
            "endpoint": {"type": "string", "enum": [e["id"] for e in c["endpoints"]], "description": "Endpoint id"},
            "params": {"type": "object", "description": "Path and query parameters by name; 'body' for a JSON body"}},
            "required": ["endpoint"]}
        cid = c["id"]
        tools.append((f"api_{cid}"[:64], lambda endpoint, params=None, _c=cid: call(_c, endpoint, params), desc, schema))
    return tools


def test(id):
    """Call the first GET endpoint with no required params, to check the URL and key."""
    c = _load().get(id)
    if not c:
        raise ValueError("no such connector")
    e = next((x for x in c["endpoints"] if x["method"] == "GET" and not any(p["required"] for p in x["params"])), None)
    if not e:
        return {"ok": None, "note": "No GET endpoint without required parameters to test with. Try one from the list."}
    r = call(id, e["id"], {})
    return {"ok": 200 <= r["status"] < 300, "endpoint": e["id"], "status": r["status"],
            "preview": (json.dumps(r["result"]) if not isinstance(r["result"], str) else r["result"])[:400]}


API = {"list": list_connectors, "save": save, "delete": delete, "import_openapi": import_openapi,
       "call": call, "test": test}
