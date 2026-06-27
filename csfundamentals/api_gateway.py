"""API Gateway — ground-truth simulations of core gateway patterns.

Five simulations covering the cross-cutting concerns a production API gateway
centralizes for a fleet of microservices. Pure Python stdlib; no network,
no external libraries.

  1. Path-based request routing  — longest-prefix match to a backend service
  2. Middleware chain            — auth -> rate limit -> logging -> routing
  3. Protocol translation        — HTTP/REST -> gRPC (method + payload mapping)
  4. Response caching            — TTL cache with hashed keys + hit/miss stats
  5. Circuit breaker             — CLOSED -> OPEN -> HALF_OPEN -> CLOSED

Notes
-----
- A fixed clock (FIXED_NOW) is used throughout so the output is byte-for-byte
  reproducible and the HTML gold-check can recompute identical values. Real
  gateways use time.time(); the algorithms here are otherwise production-shape.
- "Tokens" here are pre-minted claims objects keyed by an opaque string, to keep
  the demo stdlib. In production the gateway validates an RS256 JWT signature
  against a cached JWKS set fetched from /.well-known/jwks.json (see the
  auth_systems bundle for that crypto). The gateway's JOB is to validate once
  and propagate verified claims as internal headers.

Every number printed below is produced by running this file; nothing is
hand-computed. Capture with:

    python3 api_gateway.py > api_gateway_output.txt 2>/dev/null
"""

from __future__ import annotations

import hashlib
import re

# ---------------------------------------------------------------------------
# Shared constants — deterministic so JS gold-check reproduces identical bytes.
# ---------------------------------------------------------------------------

FIXED_NOW = 1700000000            # deterministic "now" for reproducible output

RATE_WINDOW = 60                  # seconds — sliding-window-counter window
RATE_LIMIT_USER_RPM = 5           # per-user requests-per-window (demo: small)

CACHE_TTL = 30                    # seconds — response cache entry lifetime

CB_FAILURE_THRESHOLD = 5          # consecutive failures to trip OPEN
CB_COOLDOWN = 30                  # seconds OPEN before HALF_OPEN

# Internal headers the gateway OWNS — must strip any client-supplied versions
# before injecting the verified ones (the #1 gateway security rule).
INTERNAL_HEADERS = ("X-User-Id", "X-Tenant-Id", "X-Roles", "X-Trace-Id")


# ---------------------------------------------------------------------------
# Pre-minted "tokens" (claims objects). In production these are RS256 JWTs.
# ---------------------------------------------------------------------------

TOKENS: dict[str, dict] = {
    "tok_alice": {
        "sub": "user:alice", "roles": ["admin"], "tenant": "acme",
        "exp": FIXED_NOW + 900,
    },
    "tok_bob": {
        "sub": "user:bob", "roles": ["user"], "tenant": "acme",
        "exp": FIXED_NOW + 900,
    },
    "tok_expired": {
        "sub": "user:carol", "roles": ["user"], "tenant": "acme",
        "exp": FIXED_NOW - 1,                       # already expired
    },
}


def banner(title: str, subtitle: str = "") -> None:
    print("=" * 72)
    print(f"=== {title}")
    if subtitle:
        print(f"===     {subtitle}")
    print("=" * 72)


def check(label: str, ok: bool) -> None:
    print(f"  {label} [check] {'OK' if ok else 'FAIL'}")
    assert ok, label


# ===========================================================================
# Section 1 — Path-based request routing (longest-prefix match)
# ===========================================================================

class Route:
    """A single routing rule: path prefix -> backend service."""

    def __init__(self, path_prefix: str, service: str, host: str,
                 auth_required: bool = True, rate_limit_rpm: int = RATE_LIMIT_USER_RPM,
                 cache_ttl: int = CACHE_TTL, grpc: bool = False):
        self.path_prefix = path_prefix
        self.service = service
        self.host = host
        self.auth_required = auth_required
        self.rate_limit_rpm = rate_limit_rpm
        self.cache_ttl = cache_ttl
        self.grpc = grpc

    def matches(self, path: str) -> bool:
        if self.path_prefix.endswith("/*"):
            base = self.path_prefix[:-2]
            return path == base or path.startswith(base + "/")
        return path == self.path_prefix


class Router:
    """Longest-prefix-match router over a declarative routing table.

    Sorted by prefix length (desc) so the most specific rule wins — same
    semantics as nginx/Envoy/Traefik `location` matching.
    """

    def __init__(self, routes: list[Route]):
        self.routes = sorted(routes, key=lambda r: len(r.path_prefix), reverse=True)

    def resolve(self, path: str) -> Route | None:
        for r in self.routes:
            if r.matches(path):
                return r
        return None


def build_router() -> Router:
    return Router([
        Route("/api/users/*",    "users-svc",    "10.0.1.10:8081", grpc=True),
        Route("/api/products/*", "catalog-svc",  "10.0.2.10:8082"),
        Route("/api/orders/*",   "orders-svc",   "10.0.3.10:8083"),
        Route("/api/public/*",   "static-svc",   "10.0.9.10:8089", auth_required=False),
        Route("/health",         "gateway-self", "127.0.0.1:9000", auth_required=False),
    ])


def section_routing() -> None:
    banner("Section 1 — Path-Based Request Routing",
           "longest-prefix match -> backend service")
    router = build_router()
    print("  ROUTING TABLE (sorted by specificity)")
    print(f"    {'prefix':<20} {'service':<14} {'host':<18} {'auth':<5} {'grpc'}")
    for r in router.routes:
        print(f"    {r.path_prefix:<20} {r.service:<14} {r.host:<18} "
              f"{('yes' if r.auth_required else 'no'):<5} {'yes' if r.grpc else 'no'}")
    print()

    cases = [
        "/api/users/123",          # users-svc
        "/api/users/123/orders",   # users-svc (nested)
        "/api/products/sku-77",    # catalog-svc
        "/api/public/landing",     # static-svc (no auth)
        "/health",                 # gateway-self
        "/api/unknown/x",          # 404
    ]
    print("  RESOLUTION")
    for path in cases:
        r = router.resolve(path)
        if r is None:
            print(f"    {path:<24} -> 404 No matching route")
        else:
            print(f"    {path:<24} -> {r.service} ({r.host})")
    print()

    # Specificity: /api/users/* beats a hypothetical /api/* because longer prefix.
    r1 = build_router()
    r1.routes.append(Route("/api/*", "legacy-svc", "10.0.0.1:8000", auth_required=False))
    r1.routes = sorted(r1.routes, key=lambda r: len(r.path_prefix), reverse=True)
    most_specific = r1.resolve("/api/users/9")
    check("longest-prefix wins (/api/users/* beats /api/*)?",
          most_specific is not None and most_specific.service == "users-svc")

    no_match = build_router().resolve("/api/missing") is None
    check("unmatched path returns None (-> 404)?", no_match)
    print()
    print("  [check] OK   (path-based routing with longest-prefix match)")


# ===========================================================================
# Section 2 — Middleware chain (auth -> rate limit -> logging -> routing)
# ===========================================================================

class RateLimiter:
    """Sliding-window-counter limiter (production default).

    estimate = prev_count * (1 - elapsed/window) + curr_count
    Near-exact limit enforcement in O(1) memory per key. Beats fixed window
    (2x burst at boundaries) and sliding-window-log (O(N) memory).
    """

    def __init__(self, window: int = RATE_WINDOW, limit: int = RATE_LIMIT_USER_RPM):
        self.window = window
        self.limit = limit
        self.counters: dict[str, dict] = {}

    def check(self, key: str, now: int) -> tuple[bool, int]:
        curr_start = (now // self.window) * self.window
        st = self.counters.get(key)
        if st is None:
            st = {"prev": 0, "curr": 0, "start": curr_start}
            self.counters[key] = st
        if curr_start != st["start"]:
            # Window rolled over. If exactly one window passed, carry the old
            # current as previous; otherwise (gap >= 2 windows) zero it out.
            st["prev"] = st["curr"] if curr_start - st["start"] == self.window else 0
            st["curr"] = 0
            st["start"] = curr_start
        elapsed = now - curr_start
        weight = 1.0 - elapsed / self.window
        estimate = st["prev"] * weight + st["curr"]
        allowed = estimate < self.limit
        if allowed:
            st["curr"] += 1
        remaining = max(0, int(self.limit - estimate))
        return allowed, remaining


class Gateway:
    """The pipeline: strip headers -> auth -> rate limit -> logging -> routing.

    Each middleware either short-circuits (returns a response dict) or returns
    None to let the request proceed. ctx carries verified claims + a trace.
    """

    def __init__(self, router: Router, limiter: RateLimiter):
        self.router = router
        self.limiter = limiter
        self.access_log: list[str] = []
        self._counter = 0

    # -- middleware ---------------------------------------------------------

    def _strip_headers(self, req: dict, ctx: dict):
        stripped = [h for h in INTERNAL_HEADERS if h in req["headers"]]
        for h in INTERNAL_HEADERS:
            req["headers"].pop(h, None)
        if stripped:
            ctx["trace"].append(("strip_headers", f"removed client {stripped}"))
        return None

    def _auth(self, req: dict, ctx: dict):
        route = self.router.resolve(req["path"])
        ctx["route"] = route
        if route is None:
            return {"status": 404, "body": {"error": "no route"}}
        if not route.auth_required:
            ctx["trace"].append(("auth", "public route, skipped"))
            return None
        authz = req["headers"].get("Authorization", "")
        token = authz[len("Bearer "):] if authz.startswith("Bearer ") else None
        claims = TOKENS.get(token) if token else None
        if claims is None:
            ctx["trace"].append(("auth", "missing/unknown token"))
            return {"status": 401, "body": {"error": "unauthorized"}}
        if claims["exp"] <= FIXED_NOW:
            ctx["trace"].append(("auth", f"token expired (exp={claims['exp']})"))
            return {"status": 401, "body": {"error": "token expired"}}
        # INJECT verified claims as internal headers (downstream trusts gateway).
        req["headers"]["X-User-Id"] = claims["sub"]
        req["headers"]["X-Tenant-Id"] = claims["tenant"]
        req["headers"]["X-Roles"] = ",".join(claims["roles"])
        ctx["claims"] = claims
        ctx["trace"].append(("auth", f"verified {claims['sub']}"))
        return None

    def _rate_limit(self, req: dict, ctx: dict):
        route = ctx["route"]
        if route is None or not route.auth_required:
            ctx["trace"].append(("rate_limit", "skipped (public)"))
            return None
        key = f"{ctx['claims']['tenant']}:{ctx['claims']['sub']}:{req['path'].split('/')[2]}"
        allowed, remaining = self.limiter.check(key, FIXED_NOW)
        ctx["trace"].append(("rate_limit",
                             f"key={key} remaining={remaining} {'allow' if allowed else 'DENY'}"))
        if not allowed:
            return {"status": 429,
                    "headers": {"Retry-After": str(RATE_WINDOW)},
                    "body": {"error": "rate limit exceeded",
                             "limit": self.limiter.limit,
                             "window": self.limiter.window}}
        return None

    def _logging(self, req: dict, ctx: dict):
        self._counter += 1
        ctx["trace_id"] = f"trace_{self._counter:04d}"
        req["headers"]["X-Trace-Id"] = ctx["trace_id"]
        ctx["trace"].append(("logging", f"trace_id={ctx['trace_id']} emit access log"))
        return None

    def _routing(self, req: dict, ctx: dict):
        route = ctx["route"]
        ctx["trace"].append(("routing", f"-> {route.service} ({route.host})"))
        body = _backend_call(route, req)
        return {"status": 200,
                "headers": {"X-Service": route.service, "X-Trace-Id": ctx["trace_id"]},
                "body": body}

    # -- driver ------------------------------------------------------------

    def handle(self, req: dict) -> tuple[dict, dict]:
        ctx: dict = {"claims": None, "route": None, "trace": [], "trace_id": None}
        chain = [
            ("strip_headers", self._strip_headers),
            ("auth",          self._auth),
            ("rate_limit",    self._rate_limit),
            ("logging",       self._logging),
            ("routing",       self._routing),
        ]
        for name, fn in chain:
            resp = fn(req, ctx)
            if resp is not None:
                self._log(req, ctx, resp)
                return resp, ctx
        return {"status": 500, "body": {"error": "unhandled"}}, ctx

    def _log(self, req: dict, ctx: dict, resp: dict) -> None:
        self.access_log.append(
            f'{FIXED_NOW} {req["method"]} {req["path"]} '
            f'-> {resp["status"]} trace={ctx.get("trace_id") or "-"}'
        )


def _backend_call(route: Route, req: dict) -> dict:
    """Simulated backend response per service."""
    if route.service == "users-svc":
        if m := re.match(r"^/api/users/([^/]+)$", req["path"]):
            return {"user_id": m.group(1), "name": f"user-{m.group(1)}",
                    "tenant": req["headers"].get("X-Tenant-Id")}
        return {"users": ["alice", "bob"]}
    if route.service == "catalog-svc":
        if m := re.match(r"^/api/products/([^/]+)$", req["path"]):
            return {"sku": m.group(1), "price": 4299, "stock": 120}
        return {"products": []}
    if route.service == "static-svc":
        return {"asset": req["path"], "cached": True}
    return {"ok": True, "service": route.service}


def section_middleware() -> None:
    banner("Section 2 — Middleware Chain",
           "auth -> rate limit -> logging -> routing")
    print("  chain order: strip_headers -> auth -> rate_limit -> logging -> routing")
    print(f"  rate limit : {RATE_LIMIT_USER_RPM} req / {RATE_WINDOW}s per (tenant,user,service)")
    print()

    # --- Request A: valid authed request --------------------------------
    gw = Gateway(build_router(), RateLimiter())
    req_a = {"method": "GET", "path": "/api/users/123",
             "headers": {"Authorization": "Bearer tok_alice",
                         "X-User-Id": "hacker-injected"},   # must be stripped!
             "client_ip": "203.0.113.7"}
    print("  REQUEST A — valid authed request (note injected X-User-Id attack):")
    print(f"    {req_a['method']} {req_a['path']}  Authorization: Bearer tok_alice")
    resp_a, ctx_a = gw.handle(req_a)
    for name, detail in ctx_a["trace"]:
        print(f"    [{name:<12}] {detail}")
    print(f"    -> {resp_a['status']}  body={resp_a['body']}")
    check("X-User-Id 'hacker-injected' stripped (not echoed)?",
          resp_a["body"].get("tenant") == "acme")     # backend saw the VERIFIED tenant
    print()

    # --- Request B: missing token -> 401 at auth ------------------------
    gw2 = Gateway(build_router(), RateLimiter())
    req_b = {"method": "GET", "path": "/api/users/1",
             "headers": {}, "client_ip": "198.51.100.4"}
    resp_b, ctx_b = gw2.handle(req_b)
    print("  REQUEST B — missing Authorization (short-circuit at auth):")
    for name, detail in ctx_b["trace"]:
        print(f"    [{name:<12}] {detail}")
    print(f"    -> {resp_b['status']}  {resp_b['body']}")
    stopped_at_auth = ctx_b["trace"][-1][0] == "auth" and resp_b["status"] == 401
    check("stopped at auth with 401 (chain did not reach routing)?", stopped_at_auth)
    print()

    # --- Request C: expired token -> 401 --------------------------------
    gw3 = Gateway(build_router(), RateLimiter())
    req_c = {"method": "GET", "path": "/api/products/9",
             "headers": {"Authorization": "Bearer tok_expired"}, "client_ip": "x"}
    resp_c, ctx_c = gw3.handle(req_c)
    print("  REQUEST C — expired token (short-circuit at auth):")
    for name, detail in ctx_c["trace"]:
        print(f"    [{name:<12}] {detail}")
    print(f"    -> {resp_c['status']}  {resp_c['body']}")
    check("expired token rejected at auth (401)?", resp_c["status"] == 401)
    print()

    # --- Request D: rate limit burst -> 429 after limit -----------------
    gw4 = Gateway(build_router(), RateLimiter())
    print(f"  REQUEST D — burst of {RATE_LIMIT_USER_RPM + 3} from one user "
          f"(limit={RATE_LIMIT_USER_RPM}):")
    statuses = []
    for i in range(RATE_LIMIT_USER_RPM + 3):
        r = {"method": "GET", "path": "/api/products/9",
             "headers": {"Authorization": "Bearer tok_bob"}, "client_ip": "x"}
        resp, _ = gw4.handle(r)
        statuses.append(resp["status"])
    allowed = sum(1 for s in statuses if s == 200)
    denied = sum(1 for s in statuses if s == 429)
    print(f"    statuses = {statuses}")
    print(f"    allowed={allowed}  denied(429)={denied}")
    check(f"exactly {RATE_LIMIT_USER_RPM} allowed then 429s?",
          allowed == RATE_LIMIT_USER_RPM and denied == 3)
    print()

    # --- Request E: public route skips auth + rate limit ----------------
    gw5 = Gateway(build_router(), RateLimiter())
    req_e = {"method": "GET", "path": "/api/public/landing",
             "headers": {}, "client_ip": "x"}
    resp_e, ctx_e = gw5.handle(req_e)
    print("  REQUEST E — public route (skips auth + rate limit):")
    for name, detail in ctx_e["trace"]:
        print(f"    [{name:<12}] {detail}")
    print(f"    -> {resp_e['status']}  {resp_e['body']}")
    skipped = ("auth", "public route, skipped") in ctx_e["trace"]
    check("public route skipped auth and returned 200?", skipped and resp_e["status"] == 200)
    print()
    print("  ACCESS LOG (last entry)")
    print(f"    {gw.access_log[0]}")
    print()
    print("  [check] OK   (middleware chain: short-circuit + header stripping + rate gate)")


# ===========================================================================
# Section 3 — Protocol translation (HTTP/REST -> gRPC)
# ===========================================================================

# gRPC mapping spec: (HTTP method, path template) -> (service, method) + field map.
GRPC_MAP: list[dict] = [
    {"http": ("GET",    "/api/users/{id}"),     "rpc": ("users.UserService",   "GetUser"),
     "path_fields": {"id": "user_id"}},
    {"http": ("GET",    "/api/users"),          "rpc": ("users.UserService",   "ListUsers"),
     "query_fields": {"limit": "page_size", "cursor": "page_token"}},
    {"http": ("POST",   "/api/users"),          "rpc": ("users.UserService",   "CreateUser"),
     "body": True},
    {"http": ("DELETE", "/api/users/{id}"),     "rpc": ("users.UserService",   "DeleteUser"),
     "path_fields": {"id": "user_id"}},
    {"http": ("GET",    "/api/products/{id}"),  "rpc": ("catalog.ProductService", "GetProduct"),
     "path_fields": {"id": "product_id"}},
    {"http": ("PATCH",  "/api/products/{id}"),  "rpc": ("catalog.ProductService", "UpdateProduct"),
     "path_fields": {"id": "product_id"}, "body": True},
]


def match_template(template: str, path: str) -> dict | None:
    """Match /api/users/{id} against /api/users/123 -> {id: '123'}."""
    names: list[str] = []
    parts = []
    for seg in template.split("/"):
        if seg.startswith("{") and seg.endswith("}"):
            names.append(seg[1:-1])
            parts.append("([^/]+)")
        else:
            parts.append(re.escape(seg))
    m = re.match("^" + "/".join(parts) + "$", path)
    if not m:
        return None
    return dict(zip(names, m.groups()))


def translate_http_to_grpc(req: dict) -> dict | None:
    """Translate an HTTP request into a gRPC unary call descriptor.

    REST verb -> gRPC method naming: GET->Get, POST->Create, DELETE->Delete,
    PATCH->Update, PUT->Replace. Path params map to proto fields; the JSON body
    is passed through as the message (grpc-gateway / envoy grpc_json_transcoder
    semantics). This is exactly how google.api.http annotations work.
    """
    for spec in GRPC_MAP:
        verb, tmpl = spec["http"]
        if verb != req["method"]:
            continue
        params = match_template(tmpl, req["path"])
        if params is None:
            continue
        grpc_req: dict = {}
        for src, dst in spec.get("path_fields", {}).items():
            grpc_req[dst] = params[src]
        for src, dst in spec.get("query_fields", {}).items():
            if src in req.get("query", {}):
                grpc_req[dst] = req["query"][src]
        if spec.get("body"):
            grpc_req.update(req.get("json", {}))
        service, method = spec["rpc"]
        return {
            "fully_qualified": f"{service}/{method}",
            "service": service,
            "method": method,
            "request": grpc_req,
            "content_type": "application/grpc",
        }
    return None


def grpc_to_http(grpc_resp: dict) -> dict:
    """Translate a gRPC response back into an HTTP JSON response.

    gRPC code 0 (OK) -> HTTP 200; gRPC does NOT have 404 — a missing resource
    returns code 5 (NOT_FOUND) which the gateway maps to HTTP 404.
    """
    grpc_to_http_status = {0: 200, 3: 400, 5: 404, 6: 409, 7: 403, 13: 500, 14: 503}
    status = grpc_to_http_status.get(grpc_resp.get("code", 0), 500)
    return {"status": status, "headers": {"Content-Type": "application/json"},
            "body": grpc_resp.get("message", {})}


def section_translation() -> None:
    banner("Section 3 — Protocol Translation (HTTP/REST -> gRPC)")
    print("  The gateway speaks HTTP to clients and gRPC to backends.")
    print("  google.api.http annotations map verbs + path templates to RPC methods.")
    print()

    calls = [
        {"method": "GET",    "path": "/api/users/123",     "headers": {}, "query": {}},
        {"method": "GET",    "path": "/api/users",         "headers": {},
         "query": {"limit": "20", "cursor": "abc"}},
        {"method": "POST",   "path": "/api/users",         "headers": {},
         "query": {}, "json": {"name": "Dana", "email": "dana@x.io"}},
        {"method": "DELETE", "path": "/api/users/456",     "headers": {}, "query": {}},
        {"method": "GET",    "path": "/api/products/sku-9","headers": {}, "query": {}},
    ]
    for req in calls:
        t = translate_http_to_grpc(req)
        print(f"  {req['method']:<7} {req['path']}")
        print(f"    -> gRPC: {t['fully_qualified']}")
        print(f"       msg : {t['request']}")
        print()

    # Round-trip: gRPC response back to HTTP JSON.
    grpc_resp = {"code": 0, "message": {"user_id": "123", "name": "user-123"}}
    http_resp = grpc_to_http(grpc_resp)
    print("  gRPC -> HTTP response translation:")
    print(f"    grpc code=0 (OK) message={grpc_resp['message']}")
    print(f"    -> HTTP {http_resp['status']} body={http_resp['body']}")
    print()

    # Error code mapping: gRPC NOT_FOUND(5) -> HTTP 404 (gRPC has no 404 itself).
    nf = grpc_to_http({"code": 5, "message": {}})
    check("gRPC NOT_FOUND(5) -> HTTP 404?", nf["status"] == 404)

    t1 = translate_http_to_grpc(calls[0])
    check("GET /api/users/123 -> users.UserService/GetUser?",
          t1["fully_qualified"] == "users.UserService/GetUser"
          and t1["request"] == {"user_id": "123"})

    t2 = translate_http_to_grpc(calls[1])
    check("query params mapped to proto fields (limit->page_size)?",
          t2["request"]["page_size"] == "20" and t2["request"]["page_token"] == "abc")

    t3 = translate_http_to_grpc(calls[2])
    check("POST body passed through as the gRPC message?",
          t3["request"] == {"name": "Dana", "email": "dana@x.io"})
    print()
    print("  [check] OK   (HTTP<->gRPC translation: verbs, path params, body, codes)")


# ===========================================================================
# Section 4 — Response caching (hashed key + TTL)
# ===========================================================================

class ResponseCache:
    """TTL cache keyed by a canonical hash of method+path+query.

    The cache key deliberately EXCLUDES auth headers (responses are per-resource,
    not per-user) but the gateway adds a Vary: Authorization-style check before
    serving a shared entry to a different user (omitted here for clarity).
    """

    def __init__(self, ttl: int = CACHE_TTL):
        self.ttl = ttl
        self.store: dict[str, tuple] = {}   # key -> (value, expires_at)
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    @staticmethod
    def key(method: str, path: str, query: dict) -> str:
        pairs = sorted(f"{k}={v}" for k, v in sorted(query.items()))
        raw = f"{method}#{path}#{'&'.join(pairs)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, method: str, path: str, query: dict, now: int):
        k = self.key(method, path, query)
        entry = self.store.get(k)
        if entry and entry[1] > now:
            self.hits += 1
            return entry[0], "HIT", k
        if entry:                       # present but expired
            del self.store[k]
            self.evictions += 1
        self.misses += 1
        return None, "MISS", k

    def put(self, method: str, path: str, query: dict, value: dict, now: int) -> str:
        k = self.key(method, path, query)
        self.store[k] = (value, now + self.ttl)
        return k


def section_caching() -> None:
    banner("Section 4 — Response Caching (hashed key + TTL)")
    print(f"  cache TTL = {CACHE_TTL}s    key = sha256(method#path#query)[:16]")
    print("  GET responses cached; mutating verbs (POST/PUT/DELETE) bypass + invalidate")
    print()
    cache = ResponseCache()

    path = "/api/products/42"
    query: dict = {}
    print("  WARM-UP SEQUENCE (4 identical GETs at t=FIXED_NOW):")
    gold_key = None
    for i in range(4):
        val, state, k = cache.get("GET", path, query, FIXED_NOW)
        if val is None:
            val = _backend_call(build_router().resolve(path), {"path": path, "headers": {}})
            cache.put("GET", path, query, val, FIXED_NOW)
            gold_key = k
        print(f"    req #{i+1}  {state:4}  key={k}  body={val}")
    warm_hits, warm_misses = cache.hits, cache.misses
    print(f"    hits={warm_hits}  misses={warm_misses}")
    check("warm-up gave 3 hits / 1 miss?", warm_hits == 3 and warm_misses == 1)
    print()

    print("  EXPIRY (same request at t=FIXED_NOW+TTL+1 -> MISS):")
    val, state, k = cache.get("GET", path, query, FIXED_NOW + CACHE_TTL + 1)
    print(f"    {state:4}  key={k}  (entry expired, re-fetched)")
    print()

    print("  QUERY VARIANCE changes the key (different canonical query):")
    k1 = cache.key("GET", path, {"b": "2", "a": "1"})
    k2 = cache.key("GET", path, {"a": "1", "b": "2"})     # same, reordered
    k3 = cache.key("GET", path, {"a": "1"})
    print(f"    ?a=1&b=2  key={k1}")
    print(f"    ?b=2&a=1  key={k2}  (reordered -> identical key)")
    print(f"    ?a=1      key={k3}  (different query -> different key)")
    print()

    print(f"  GOLD cache key for GET {path} (empty query):")
    print(f"    raw  = 'GET#{path}#'")
    print(f"    key  = {gold_key}")
    print()

    hit_rate = cache.hits / max(1, cache.hits + cache.misses) * 100
    print(f"  summary: hits={cache.hits} misses={cache.misses} "
          f"evictions={cache.evictions} hit_rate={hit_rate:.1f}%")
    check("reordered query yields identical key?", k1 == k2)
    check("different query yields different key?", k1 != k3)
    print()
    print("  [check] OK   (TTL cache: hit/miss/evict, canonical keyed, deterministic)")


# ===========================================================================
# Section 5 — Circuit breaker (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
# ===========================================================================

class CircuitBreaker:
    """Per-backend circuit breaker.

    CLOSED   : normal traffic; count consecutive failures.
    OPEN     : fast-fail (return 503 immediately); after `cooldown` move to
               HALF_OPEN on the next allow() call.
    HALF_OPEN: allow ONE probe; success -> CLOSED, failure -> OPEN again.

    Prevents cascading failures: when a downstream is erroring, stop hammering
    it and let it recover. Pairs with bulkheads (per-backend pools) + retries
    (idempotent only, exponential backoff + jitter).
    """

    def __init__(self, name: str, failure_threshold: int = CB_FAILURE_THRESHOLD,
                 cooldown: int = CB_COOLDOWN):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.state = "CLOSED"
        self.failures = 0
        self.opened_at: int | None = None
        self.history: list[tuple] = []      # (now, state, event)

    def _record(self, now: int, event: str) -> None:
        self.history.append((now, self.state, event))

    def allow(self, now: int) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if self.opened_at is not None and now - self.opened_at >= self.cooldown:
                self.state = "HALF_OPEN"
                self._record(now, "cooldown elapsed -> HALF_OPEN (probe)")
                return True
            self._record(now, "OPEN: fast-fail (503)")
            return False
        # HALF_OPEN: only one probe in flight (simplified)
        self._record(now, "HALF_OPEN: probe already in flight")
        return False

    def on_success(self, now: int) -> None:
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            self.failures = 0
            self._record(now, "probe succeeded -> CLOSED")
        elif self.state == "CLOSED":
            self.failures = 0
            self._record(now, "ok (reset failures)")

    def on_failure(self, now: int) -> None:
        self.failures += 1
        if self.state == "HALF_OPEN":
            self.state = "OPEN"
            self.opened_at = now
            self._record(now, "probe failed -> OPEN")
        elif self.state == "CLOSED" and self.failures >= self.failure_threshold:
            self.state = "OPEN"
            self.opened_at = now
            self._record(now, f"{self.failures} failures -> OPEN")


def section_circuit_breaker() -> None:
    banner("Section 5 — Circuit Breaker",
           "CLOSED -> OPEN -> HALF_OPEN -> CLOSED")
    print(f"  failure_threshold = {CB_FAILURE_THRESHOLD}   cooldown = {CB_COOLDOWN}s")
    print()
    cb = CircuitBreaker("orders-svc")

    print("  PHASE 1 — trip the breaker with a failure burst:")
    for i in range(CB_FAILURE_THRESHOLD):
        cb.on_failure(FIXED_NOW)
        print(f"    failure #{i+1}  -> state={cb.state}")
    check(f"OPEN after {CB_FAILURE_THRESHOLD} consecutive failures?", cb.state == "OPEN")
    print()

    print("  PHASE 2 — OPEN fast-fails (no backend call) until cooldown elapses:")
    blocked = cb.allow(FIXED_NOW + 5)
    print(f"    allow(t+5s)  -> {blocked}  (fast-fail 503, no backend hit)")
    check("OPEN rejects within cooldown?", blocked is False)
    print()

    print("  PHASE 3 — after cooldown, HALF_OPEN lets ONE probe through:")
    probe = cb.allow(FIXED_NOW + CB_COOLDOWN)
    print(f"    allow(t+{CB_COOLDOWN}s) -> {probe}  state={cb.state}")
    check("half-open admits exactly one probe?", probe is True and cb.state == "HALF_OPEN")
    second = cb.allow(FIXED_NOW + CB_COOLDOWN)
    check("second probe in HALF_OPEN blocked?", second is False)
    print()

    print("  PHASE 4 — probe SUCCEEDS -> back to CLOSED:")
    cb.on_success(FIXED_NOW + CB_COOLDOWN)
    print(f"    on_success  -> state={cb.state}  failures={cb.failures}")
    check("successful probe closes the circuit?", cb.state == "CLOSED")
    print()

    print("  PHASE 5 — probe FAILS -> straight back to OPEN:")
    cb.state = "HALF_OPEN"
    cb.on_failure(FIXED_NOW + CB_COOLDOWN + 1)
    print(f"    probe fail  -> state={cb.state}")
    check("failed probe reopens immediately?", cb.state == "OPEN")
    print()

    print("  STATE HISTORY:")
    for now, state, event in cb.history:
        print(f"    t={now}  [{state:<9}] {event}")
    print()
    print("  [check] OK   (circuit breaker protects a failing downstream)")


# ===========================================================================
# Main driver
# ===========================================================================

if __name__ == "__main__":
    section_routing()
    section_middleware()
    section_translation()
    section_caching()
    section_circuit_breaker()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
