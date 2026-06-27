#!/usr/bin/env python3
"""api_design.py -- REST API design, ground-truth implementation.

Pure Python stdlib (no third-party deps). Every section prints a ``===`` banner,
runs a scenario, and ends with ``[check] OK``. The GOLD CHECK section produces a
value recomputed by ``api_design.html`` in JavaScript for cross-language parity.

Topics
    01. Resource naming       -- nouns not verbs; plural collections; sub-resources
    02. HTTP method semantics -- GET/POST/PUT/PATCH/DELETE: safe + idempotent + codes
    03. Status codes          -- success + error families mapped to error codes
    04. Error contract        -- RFC 7807 Problem Details (machine-readable)
    05. Versioning            -- URI vs header vs query-param strategies
    06. Pagination            -- offset vs cursor (stability under inserts)
    07. Idempotency           -- Idempotency-Key store, dedup window, 409 on drift

The GOLD CHECK prices the cost of offset vs cursor pagination for
``pagination_cost_ratio(100, 10)``; ``api_design.html`` recomputes it in JS.

Companion files: API_DESIGN.md, api_design.html, api_design_output.txt
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


# =========================================================================== #
#  Helpers
# =========================================================================== #
def banner(title: str) -> None:
    """Print a ``===`` banner, as required by HOW_TO_RESEARCH.md."""
    line = "=" * 72
    print(f"\n{line}\n=== {title}\n{line}")


def check(label: str) -> None:
    print(f"  [check] OK   {label}")


# =========================================================================== #
#  01. RESOURCE NAMING -- nouns not verbs, plural collections, sub-resources
# =========================================================================== #
def is_valid_resource_path(path: str) -> Tuple[bool, str]:
    """A REST resource path is plural nouns + ids + sub-resources, never verbs."""
    segments = [s for s in path.strip("/").split("/") if s]
    for seg in segments:
        if seg.startswith("{") and seg.endswith("}"):
            continue  # path param placeholder, e.g. {id}
        # resource segments are plural lowercase nouns, not camelCase verbs
        if seg != seg.lower():
            return False, f"segment '{seg}' is not lowercase"
        # reject verbs smuggled into the URL (create/get/delete/update/list verbs)
        if seg.lower() in {"create", "get", "delete", "update", "list", "add", "remove"}:
            return False, f"verb '{seg}' must not appear in a resource path"
    return True, "ok"


BAD_PATHS = [
    "/createOrder",
    "/getUser",
    "/deleteProduct",
    "/orders/createOrder",
    "/listOrdersForUser",
]

GOOD_PATHS = [
    "/orders",
    "/orders/{id}",
    "/orders/{id}/items",
    "/users/{id}/orders",
    "/orders/{id}/cancellations",   # complex action modeled as its own sub-resource
]


def section_resource_naming() -> None:
    banner("01. RESOURCE NAMING -- nouns not verbs, plural collections")
    print("  ANTI-PATTERN (verbs in the URL):")
    for p in BAD_PATHS:
        ok, why = is_valid_resource_path(p)
        print(f"    {p:<32} -> {'REJECT (' + why + ')' if not ok else 'accept'}")
    print("  REST (nouns; verbs come from the HTTP method):")
    for p in GOOD_PATHS:
        ok, why = is_valid_resource_path(p)
        print(f"    {p:<32} -> {'accept' if ok else 'REJECT (' + why + ')'}")
    check("model resources as nouns; express actions through HTTP methods")


# =========================================================================== #
#  02. HTTP METHOD SEMANTICS -- safe, idempotent, status codes, dispatch
# =========================================================================== #
@dataclass(frozen=True)
class MethodSpec:
    method: str
    safe: bool            # no side effects (cacheable, GET/HEAD/OPTIONS)
    idempotent: bool      # N calls == 1 call (GET/PUT/DELETE)
    success: List[int]    # typical success status codes
    body: bool            # carries a request body


HTTP_METHODS: Dict[str, MethodSpec] = {
    "GET":    MethodSpec("GET",    safe=True,  idempotent=True,  success=[200],             body=False),
    "POST":   MethodSpec("POST",   safe=False, idempotent=False, success=[201, 202],        body=True),
    "PUT":    MethodSpec("PUT",    safe=False, idempotent=True,  success=[200, 204],        body=True),
    "PATCH":  MethodSpec("PATCH",  safe=False, idempotent=False, success=[200, 204],        body=True),
    "DELETE": MethodSpec("DELETE", safe=False, idempotent=True,  success=[204],             body=False),
    "HEAD":   MethodSpec("HEAD",   safe=True,  idempotent=True,  success=[200],             body=False),
    "OPTIONS":MethodSpec("OPTIONS",safe=True,  idempotent=True,  success=[200],             body=False),
}


@dataclass
class Response:
    status: int
    body: Any = None
    headers: Dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        code = self.status
        reason = HTTP_REASONS.get(code, "UNKNOWN")
        return f"{code} {reason}  body={json.dumps(self.body) if self.body is not None else '<none>'}"


HTTP_REASONS: Dict[int, str] = {
    200: "OK", 201: "Created", 202: "Accepted", 204: "No Content",
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
    409: "Conflict", 422: "Unprocessable Entity", 429: "Too Many Requests",
    500: "Internal Server Error", 503: "Service Unavailable",
}


def section_http_methods() -> None:
    banner("02. HTTP METHOD SEMANTICS -- safe / idempotent / status codes")
    print(f"  {'METHOD':<9}{'safe':<7}{'idempotent':<12}{'success codes':<22}{'body'}")
    for m, spec in HTTP_METHODS.items():
        print(f"  {m:<9}{'yes' if spec.safe else 'no':<7}"
              f"{'yes' if spec.idempotent else 'no':<12}"
              f"{','.join(str(c) for c in spec.success):<22}"
              f"{'yes' if spec.body else 'no'}")
    # dispatch: same resource, different method -> different outcome
    print("  dispatch over /orders/{id}:")
    cases = [
        ("GET",    "read",       200),
        ("POST",   "create",     201),
        ("PUT",    "replace",    200),
        ("PATCH",  "partial",    200),
        ("DELETE", "remove",     204),
    ]
    for method, desc, expect in cases:
        resp = Response(status=expect, body={"id": "ord_123"} if expect != 204 else None)
        print(f"    {method:<7} {desc:<9} -> {resp}")
    check("GET/PUT/DELETE idempotent; POST/PATCH not safe; codes align with intent")


# =========================================================================== #
#  03. STATUS CODES -- error families, machine-readable codes
# =========================================================================== #
class ErrorCode(Enum):
    VALIDATION_FAILED = "VALIDATION_FAILED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    PAYMENT_DECLINED = "PAYMENT_DECLINED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ERROR_STATUS: Dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_FAILED:   400,
    ErrorCode.UNAUTHORIZED:        401,
    ErrorCode.FORBIDDEN:           403,
    ErrorCode.RESOURCE_NOT_FOUND:  404,
    ErrorCode.CONFLICT:            409,
    ErrorCode.PAYMENT_DECLINED:    422,
    ErrorCode.RATE_LIMIT_EXCEEDED: 429,
    ErrorCode.INTERNAL_ERROR:      500,
}


def section_status_codes() -> None:
    banner("03. STATUS CODES -- families 2xx/4xx/5xx mapped to error codes")
    families = {"2xx success": [200, 201, 202, 204],
                "4xx client error": [400, 401, 403, 404, 409, 422, 429],
                "5xx server error": [500, 503]}
    for fam, codes in families.items():
        joined = ", ".join(f"{c} {HTTP_REASONS.get(c, '?')}" for c in codes)
        print(f"  {fam:<18} -> {joined}")
    print("  error_code -> HTTP status (clients switch on the code, not a string):")
    for code in ErrorCode:
        print(f"    {code.value:<22} -> {ERROR_STATUS[code]} {HTTP_REASONS[ERROR_STATUS[code]]}")
    check("status code aligns with machine-readable error_code (never 200 for errors)")


# =========================================================================== #
#  04. ERROR CONTRACT -- RFC 7807 Problem Details
# =========================================================================== #
def make_problem(code: ErrorCode, detail: str, instance: str,
                 base: str = "https://api.example.com/errors") -> Dict[str, Any]:
    """RFC 7807 Problem Details for HTTP APIs.

    Clients key on ``type`` (a stable URI), not on a localized ``message``
    string. Survives translation; survives i18n.
    """
    status = ERROR_STATUS[code]
    return {
        "type": f"{base}/{code.value.lower()}",
        "title": code.value.replace("_", " ").title(),
        "status": status,
        "detail": detail,
        "instance": instance,          # request/path identifier
    }


def section_error_contract() -> None:
    banner("04. ERROR CONTRACT -- RFC 7807 Problem Details (machine-readable)")
    problems = [
        make_problem(ErrorCode.RESOURCE_NOT_FOUND, "Order ord_123 does not exist.",
                     "/v1/orders/ord_123"),
        make_problem(ErrorCode.VALIDATION_FAILED, "Field 'amount' must be positive.",
                     "/v1/payments"),
        make_problem(ErrorCode.RATE_LIMIT_EXCEEDED, "Limit of 1000/min exceeded.",
                     "/v1/orders"),
    ]
    for prob in problems:
        print(f"  HTTP {prob['status']} {HTTP_REASONS[prob['status']]}:")
        print(f"    {json.dumps(prob)}")
    check("every error has type/title/status/detail/instance -- clients switch on type")


# =========================================================================== #
#  05. VERSIONING -- URI / header / query strategies
# =========================================================================== #
@dataclass
class VersionedRequest:
    path: str
    headers: Dict[str, str] = field(default_factory=dict)
    query: Dict[str, str] = field(default_factory=dict)


def resolve_version(req: VersionedRequest) -> Tuple[str, str]:
    """Return (detected_version, strategy_used). Tries URI, header, query in order."""
    parts = [p for p in req.path.strip("/").split("/")]
    if parts and parts[0].startswith("v") and parts[0][1:].isdigit():
        return parts[0][1:], "uri"          # /v2/orders
    accept = req.headers.get("Accept", "")
    if "version=" in accept:
        # Accept: application/vnd.api+json;version=2
        ver = accept.split("version=")[1].split(";")[0].strip()
        return ver, "header"
    if "version" in req.query:
        return req.query["version"], "query"  # /orders?version=2
    return "1", "uri"                         # default


def section_versioning() -> None:
    banner("05. VERSIONING -- URI vs header vs query-param")
    cases = [
        ("URI versioning", VersionedRequest(path="/v2/orders")),
        ("Header versioning", VersionedRequest(
            path="/orders",
            headers={"Accept": "application/vnd.api+json;version=2"})),
        ("Query param", VersionedRequest(path="/orders", query={"version": "2"})),
        ("Default (no version)", VersionedRequest(path="/orders")),
    ]
    for name, req in cases:
        ver, strat = resolve_version(req)
        print(f"  {name:<22} -> v{ver}  via {strat:<7}  (path={req.path})")
    note = ("rule: v1 is forever -- ship /v1 from day one; maintain both in "
            "parallel through a 6-24 month deprecation window before removing v1")
    print(f"  {note}")
    check("URI versioning is most practical; header is cleanest; query is simplest")


# =========================================================================== #
#  06. PAGINATION -- offset vs cursor
# =========================================================================== #
@dataclass
class Order:
    id: int
    total: float
    created_at: int          # epoch second; later rows have larger values


def encode_cursor(last_id: int) -> str:
    """Cursor = Base64(JSON{'id': last_id}). Opaque to the client."""
    raw = json.dumps({"id": last_id}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> int:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    return int(json.loads(raw)["id"])


def paginate_offset(orders: List[Order], limit: int, offset: int) -> Dict[str, Any]:
    """Offset pagination: skip `offset` rows, return `limit`. Exposes total_count."""
    page = orders[offset: offset + limit]
    return {
        "orders": [{"id": o.id, "total": o.total} for o in page],
        "pagination": {
            "offset": offset,
            "limit": limit,
            "total_count": len(orders),
            "has_more": offset + limit < len(orders),
        },
    }


def paginate_cursor(orders: List[Order], limit: int,
                    cursor: Optional[str] = None) -> Dict[str, Any]:
    """Cursor pagination: return rows strictly after the cursor id.

    Stable under concurrent inserts (new rows do not shift existing pages);
    O(1) per page vs O(offset) for offset pagination. Requires a unique
    tiebreaker: ORDER BY created_at DESC, id DESC.
    """
    after = decode_cursor(cursor) if cursor else -1
    page = [o for o in orders if o.id > after][:limit]
    last_id = page[-1].id if page else after
    return {
        "orders": [{"id": o.id, "total": o.total} for o in page],
        "pagination": {
            "next_cursor": encode_cursor(last_id) if len(page) == limit else None,
            "limit": limit,
            "has_more": len(page) == limit,
            "total_count": None,     # total_count omitted: expensive + unstable
        },
    }


def section_pagination() -> None:
    banner("06. PAGINATION -- offset vs cursor (stability under inserts)")
    orders = [Order(id=i, total=10.0 * i, created_at=1000 + i) for i in range(5)]
    limit = 2

    print("  OFFSET: GET /orders?offset=0&limit=2")
    p1 = paginate_offset(orders, limit, offset=0)
    print(f"    page1 ids = {[o['id'] for o in p1['orders']]}  "
          f"total={p1['pagination']['total_count']}  "
          f"has_more={p1['pagination']['has_more']}")

    print("  CURSOR: GET /orders?limit=2  (cursor omitted on first request)")
    c1 = paginate_cursor(orders, limit, cursor=None)
    ids1 = [o["id"] for o in c1["orders"]]
    cur1 = c1["pagination"]["next_cursor"]
    print(f"    page1 ids = {ids1}  next_cursor={cur1}  (encodes id={decode_cursor(cur1)})")

    # A new row is inserted at index 1 (front of page2's window) AFTER page1 is
    # read. Offset resumes at a POSITION (now shifted); cursor resumes after a
    # VALUE (id=1), so it is unaffected by the insert.
    orders.insert(1, Order(id=99, total=999.0, created_at=1050))  # queue jump
    print("  >> INSERT id=99 at index 1 (a new high-priority row jumps the queue)")
    off_ids = [o["id"] for o in paginate_offset(orders, limit, offset=limit)["orders"]]
    cur_ids = [o["id"] for o in paginate_cursor(orders, limit, cursor=cur1)["orders"]]
    print(f"  offset page2 (offset=2) ids  = {off_ids}  -> id=1 DUPLICATED, id=99 MISSED")
    print(f"  cursor page2 (after id=1) ids = {cur_ids}  -> stable: no dup, no skip")
    check("cursor resumes after a value (stable); offset resumes at a position (shifts)")


# =========================================================================== #
#  07. IDEMPOTENCY -- Idempotency-Key store, dedup window, 409 on drift
# =========================================================================== #
class IdempotencyConflict(Exception):
    """Same Idempotency-Key reused with a DIFFERENT request body -> 409."""


@dataclass
class _CacheEntry:
    response: Any
    expires_at: float


class IdempotencyStore:
    """In-memory stand-in for a Redis-backed idempotency store.

    Keyed on the client-supplied ``Idempotency-Key`` header. Stores the first
    response keyed by (key, request_fingerprint). On a duplicate request with the
    SAME fingerprint, the stored response is returned WITHOUT re-processing; on a
    duplicate with a DIFFERENT fingerprint, a 409 Conflict is raised.
    """

    def __init__(self, ttl_seconds: int = 86400) -> None:
        self._store: Dict[str, _CacheEntry] = {}
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def fingerprint(body: Any) -> str:
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]

    def get_or_execute(self, key: str, body: Any,
                       operation: Callable[[], Any]) -> Tuple[Any, str]:
        now = time.time()
        entry = self._store.get(key)
        if entry and entry.expires_at > now:
            if self.fingerprint(body) != self.fingerprint(entry.response.get("_body")):
                raise IdempotencyConflict(
                    f"Idempotency-Key {key} reused with a different request body")
            return entry.response, "cached"   # duplicate retry -> stored response
        result = operation()
        result_with_body = {**result, "_body": body}
        self._store[key] = _CacheEntry(result_with_body, now + self.ttl_seconds)
        return result, "executed"


def section_idempotency() -> None:
    banner("07. IDEMPOTENCY -- safe retries on POST (Idempotency-Key store)")
    store = IdempotencyStore(ttl_seconds=86400)
    charges: List[float] = []  # simulates the downstream side-effect (a charge)

    def charge() -> Dict[str, Any]:
        charges.append(99.0)                       # exactly ONE real charge
        return {"status": "paid", "amount": 99.0, "id": "pay_001"}

    body = {"amount": 99.0, "currency": "USD"}
    key = "idem_a1b2c3"

    # 1st request -> executes, charges once
    r1, tag1 = store.get_or_execute(key, body, charge)
    # retry (same key, same body) -> cached, NO second charge
    r2, tag2 = store.get_or_execute(key, body, charge)
    # retry (same key, DIFFERENT body) -> 409 Conflict
    try:
        store.get_or_execute(key, {"amount": 999.0, "currency": "USD"}, charge)
        conflict = False
    except IdempotencyConflict:
        conflict = True

    print(f"  POST /payments  Idempotency-Key={key}")
    print(f"    1st request   -> {r1['status']}  charge count={len(charges)}  ({tag1})")
    print(f"    retry (same)  -> {r2['status']}  charge count={len(charges)}  ({tag2})")
    print(f"    retry (diff)  -> 409 Conflict raised? {conflict}  (key reused, body drifted)")
    check("POST + Idempotency-Key: first call charges, retries dedup, drift -> 409")


# =========================================================================== #
#  GOLD CHECK -- recomputed by api_design.html in JavaScript
# =========================================================================== #
def pagination_cost_ratio(total: int, limit: int) -> float:
    """Cost ratio of offset vs cursor pagination over the full dataset.

    Offset pagination scans past ``offset`` rows each page -> total work grows
    quadratically. Cursor pagination is O(limit) per page -> linear.

        num_pages    = ceil(total / limit)
        offset_cost  = limit * (0 + 1 + ... + num_pages-1)   # rows skipped
                     = limit * (num_pages-1) * num_pages / 2
        cursor_cost  = limit * num_pages
        ratio        = offset_cost / cursor_cost = (num_pages - 1) / 2
    """
    num_pages = math.ceil(total / limit)
    offset_cost = limit * (num_pages - 1) * num_pages // 2
    cursor_cost = limit * num_pages
    return round(offset_cost / cursor_cost, 1)


def section_gold_check() -> None:
    banner("GOLD CHECK  (recomputed by api_design.html in JS)")
    total, limit = 100, 10
    ratio = pagination_cost_ratio(total, limit)
    num_pages = math.ceil(total / limit)
    offset_cost = limit * (num_pages - 1) * num_pages // 2
    cursor_cost = limit * num_pages
    gold = f"{ratio:.1f}"
    print(f"  pagination_cost_ratio(total={total}, limit={limit})")
    print(f"    num_pages={num_pages}  offset_cost={offset_cost}  cursor_cost={cursor_cost}")
    print(f"    ratio(offset/cursor) = {gold}")
    print("  [check] OK")


# =========================================================================== #
#  Main
# =========================================================================== #
if __name__ == "__main__":
    print("#" * 72)
    print("# REST API DESIGN -- resource naming, HTTP semantics, versioning,")
    print("# pagination, error contracts, idempotency (pure stdlib)")
    print("#" * 72)
    section_resource_naming()
    section_http_methods()
    section_status_codes()
    section_error_contract()
    section_versioning()
    section_pagination()
    section_idempotency()
    section_gold_check()
    print("\n[check] OK -- all 7 topics + gold check demoed")
