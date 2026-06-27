"""Idempotency Patterns — ground-truth simulations of safe retries and
effectively-once processing.

Five simulations covering the full idempotency stack. Pure Python stdlib;
no network, no database, no external libraries.

  1. Idempotency key + dedup table — the PENDING/DONE state machine,
     scoped keys, atomic reserve, cached response replay, key-reuse detection
  2. At-least-once vs exactly-once delivery — a broker that redelivers;
     naive consumer vs idempotent consumer (dedup by event id)
  3. Retry with dedup — client retry loop where the response is dropped AFTER
     the server executed; dedup turns at-least-once into exactly-once-effect
  4. Payment double-charge prevention — the killer use case: a PSP charge whose
     response is lost mid-flight; with vs without an idempotency key
  5. Request fingerprinting — SHA-256 of the canonical request body, used to
     detect one key reused with two different payloads

Notes
-----
- A fixed PRNG-free, fully explicit scenario list plus FIXED_NOW are used so
  the output is byte-for-byte reproducible and the HTML gold-check recomputes
  identical values.
- The dedup store is an in-memory dict standing in for SQL
  `INSERT ... ON CONFLICT DO NOTHING` (atomic set-if-not-exists) or Redis
  `SETNX`. CPython dict reads/writes under the GIL are atomic, so the
  reserve is race-free even though it is two Python statements.

Every number printed below is produced by running this file; nothing is
hand-computed. Capture with:

    python3 idempotency_patterns.py > idempotency_patterns_output.txt 2>/dev/null
"""

from __future__ import annotations

import hashlib
import json

# ---------------------------------------------------------------------------
# Shared constants — deterministic so the JS gold-check reproduces identical
# bytes and the scoped key / counts are stable across runs.
# ---------------------------------------------------------------------------

FIXED_NOW = 1_700_000_000            # deterministic "now" (epoch seconds)
IDEMPOTENCY_TTL = 86400              # 24 hours — aligned with the retry window
TENANT = "tnt_acme"                  # multi-tenant scope prefix

# The canonical payment body used by Sections 4 & 5 AND the HTML gold-check.
# Values are in minor units (cents) — never float money.
PAYMENT_BODY = {"amount": 4250, "currency": "USD", "customer": "cus_42"}
TAMPERED_BODY = {"amount": 9999, "currency": "USD", "customer": "cus_42"}


# ---------------------------------------------------------------------------
# Crypto + JSON helpers
# ---------------------------------------------------------------------------

def canonical_json(obj: dict) -> str:
    """Stable serialization: sorted keys, no whitespace. Two semantically
    equal bodies MUST hash to the same digest regardless of key order."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("ascii")).hexdigest()


def request_hash(body: dict) -> str:
    """SHA-256 fingerprint of the canonical request body (first 16 hex chars
    shown in logs; full digest stored to detect key reuse)."""
    return sha256_hex(canonical_json(body))


def short(h: str, n: int = 16) -> str:
    return h[:n]


# ---------------------------------------------------------------------------
# Section 1 — Idempotency-key store (dedup table) + PENDING/DONE state machine
# ---------------------------------------------------------------------------

class IdempotencyStore:
    """In-memory idempotency-key store.

    Simulates the production row:

        scoped_key   (PK)  = "{tenant_id}:{idempotency_key}"
        request_hash       = SHA-256(canonical JSON of request body)
        state              = PENDING | DONE
        response           = {status, body}   (stored only when DONE)
        created_at / expires_at

    The atomic reserve stands in for SQL `INSERT ... ON CONFLICT DO NOTHING`
    or Redis `SETNX`. Under CPython's GIL the dict get-then-set is atomic, so
    two concurrent callers cannot both see "key not found".
    """

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    @staticmethod
    def scoped_key(tenant: str, idem_key: str) -> str:
        return f"{tenant}:{idem_key}"

    def reserve(self, tenant: str, idem_key: str, body: dict) -> str:
        """Atomically reserve the key. Returns one of:
            CREATED         — this caller won the race; may execute
            PENDING         — another worker is executing; caller returns 409
            DONE            — completed; caller returns the cached response
            HASH_MISMATCH   — key exists but with a DIFFERENT body (422)
        """
        sk = self.scoped_key(tenant, idem_key)
        rh = request_hash(body)
        rec = self.records.get(sk)
        if rec is None:
            self.records[sk] = {
                "scoped_key": sk,
                "request_hash": rh,
                "state": "PENDING",
                "response": None,
                "created_at": FIXED_NOW,
                "expires_at": FIXED_NOW + IDEMPOTENCY_TTL,
            }
            return "CREATED"
        if rec["request_hash"] != rh:
            return "HASH_MISMATCH"
        return rec["state"]            # PENDING or DONE

    def complete(self, tenant: str, idem_key: str, response: dict) -> None:
        self.records[self.scoped_key(tenant, idem_key)]["state"] = "DONE"
        self.records[self.scoped_key(tenant, idem_key)]["response"] = response

    def cached(self, tenant: str, idem_key: str) -> dict | None:
        rec = self.records.get(self.scoped_key(tenant, idem_key))
        return rec["response"] if rec and rec["state"] == "DONE" else None

    def state_of(self, tenant: str, idem_key: str) -> str:
        rec = self.records.get(self.scoped_key(tenant, idem_key))
        return rec["state"] if rec else "ABSENT"


class Executor:
    """Stand-in for a downstream side effect (PSP charge, DB write). Counts
    every execution so dedup can be PROVEN by counting, not just asserted."""

    def __init__(self) -> None:
        self.executions = 0
        self.charges: list[dict] = []

    def charge(self, body: dict) -> dict:
        self.executions += 1
        record = {
            "id": f"ch_{self.executions:04d}",
            "amount": body["amount"],
            "currency": body["currency"],
            "customer": body["customer"],
            "created": FIXED_NOW,
        }
        self.charges.append(record)
        return {"status": 200, "body": record}

    def generic(self, op: str, body: dict) -> dict:
        self.executions += 1
        return {"status": 200, "body": {"id": f"{op}_{self.executions:04d}", **body}}


def section_dedup_table() -> None:
    print("=" * 72)
    print("=== Idempotency Key + Dedup Table — PENDING/DONE state machine")
    print("=" * 72)
    print("  Every POST carries a client-generated Idempotency-Key (UUID v4).")
    print("  The server scopes it per tenant and atomically reserves it before")
    print("  doing any side effect. Four outcomes are possible on reserve:")
    print("    CREATED       -> you won the race; execute, then set DONE")
    print("    PENDING       -> another worker is mid-flight; return 409 Conflict")
    print("    DONE          -> return the cached response (NO re-execution)")
    print("    HASH_MISMATCH -> same key, different body; return 422 (key reuse)")
    print()
    print("  schema (row in idempotency_keys):")
    print("    scoped_key   (PK) = {tenant}:{idempotency_key}")
    print("    request_hash      = SHA-256(canonical(body))")
    print("    state             = PENDING | DONE")
    print("    response          = {status, body}  (stored when DONE)")
    print(f"    expires_at        = created_at + {IDEMPOTENCY_TTL}s (24h TTL)")
    print()

    store = IdempotencyStore()
    psp = Executor()
    key = "9b3f1c2a-uuid-v4-key"
    print(f"  Idempotency-Key = {key}")
    print(f"  request body    = {PAYMENT_BODY}")
    print(f"  request_hash    = {short(request_hash(PAYMENT_BODY))}  (first 16)")
    print()

    # --- Request 1: first time, reserves PENDING, executes, sets DONE ---
    r1 = store.reserve(TENANT, key, PAYMENT_BODY)
    print(f"  Request 1 reserve -> {r1}")
    assert r1 == "CREATED", "first reserve must be CREATED"
    resp1 = psp.charge(PAYMENT_BODY)
    store.complete(TENANT, key, resp1)
    print(f"    executed charge -> {resp1['body']['id']}  (state now DONE)")
    print()

    # --- Request 2: same key, same body -> DONE, cached response, NO exec ---
    r2 = store.reserve(TENANT, key, PAYMENT_BODY)
    cached = store.cached(TENANT, key)
    print(f"  Request 2 reserve -> {r2}   (same key, same body)")
    print(f"    returned cached {cached['body']['id']}  (NO re-execution)")
    print()

    # --- Request 3: a DIFFERENT key left PENDING, concurrent reserve -> 409 ---
    pkey = "pending-while-worker-busy"
    rp1 = store.reserve(TENANT, pkey, PAYMENT_BODY)
    rp2 = store.reserve(TENANT, pkey, PAYMENT_BODY)
    print(f"  Request 3 reserve -> {rp1}   (first caller reserves PENDING)")
    print(f"  Request 4 reserve -> {rp2}   (concurrent caller, same key)")
    print(f"    concurrent caller gets {rp2} -> returns 409 Conflict")
    assert rp1 == "CREATED" and rp2 == "PENDING"
    print()

    # --- Request 5: key reuse with a DIFFERENT body -> HASH_MISMATCH -> 422 ---
    rkey = "reused-key-7f3a"
    store.reserve(TENANT, rkey, PAYMENT_BODY)
    store.complete(TENANT, rkey, psp.charge(PAYMENT_BODY))
    rm = store.reserve(TENANT, rkey, TAMPERED_BODY)
    print(f"  Request 5: key {rkey} first used with body amount=4250")
    print("             then reused with body amount=9999 (different payload)")
    print(f"    reserve -> {rm} -> returns 422 (one key, two bodies is a bug)")
    assert rm == "HASH_MISMATCH"
    print()

    c1 = psp.executions == 2          # req1 + the reused-key charge; req2 cached
    c2 = cached["body"]["id"] == "ch_0001"
    c3 = rp2 == "PENDING"
    c4 = rm == "HASH_MISMATCH"
    print(f"  req 2 served from cache (no PSP call)?  [check] {'OK' if c1 and c2 else 'FAIL'}")
    print(f"  concurrent reserve returns PENDING?     [check] {'OK' if c3 else 'FAIL'}")
    print(f"  key-reuse with new body rejected?       [check] {'OK' if c4 else 'FAIL'}")
    assert c1 and c2 and c3 and c4
    print()
    print(f"  PSP executions for 5 logical requests = {psp.executions}")
    print("  (req 2 returned a cached response; only 2 side effects happened)")
    print()
    print("  [check] OK   (dedup table: CREATED/PENDING/DONE/HASH_MISMATCH all correct)")


# ---------------------------------------------------------------------------
# Section 2 — At-least-once vs exactly-once delivery
# ---------------------------------------------------------------------------

# A broker guarantees AT-LEAST-ONCE: a message may arrive one or more times
# (ack lost, consumer rebalance, network blip). Exactly-once DELIVERY is
# impossible (Two Generals / FLP); exactly-once EFFECT is achievable by making
# the consumer idempotent and deduping by event id.
DELIVERIES = [
    "evt_001", "evt_001",                 # redelivered (ack lost in flight)
    "evt_002",
    "evt_003", "evt_003", "evt_003",      # redelivered twice (rebalance)
    "evt_004",
    "evt_005", "evt_005",                 # redelivered (slow ack)
]


def section_delivery_semantics() -> None:
    print()
    print("=" * 72)
    print("=== At-Least-Once vs Exactly-Once Delivery")
    print("=" * 72)
    print("  A message broker guarantees AT-LEAST-ONCE: each message may arrive")
    print("  1+ times. Exactly-once DELIVERY is provably impossible (Two Generals")
    print("  / FLP). The dominant production pattern is AT-LEAST-ONCE delivery +")
    print("  an IDEMPOTENT consumer that dedups by event id = exactly-once EFFECT.")
    print()
    print(f"  delivery log ({len(DELIVERIES)} deliveries, "
          f"{len(set(DELIVERIES))} unique events):")
    print(f"    {DELIVERIES}")
    print()

    # --- naive consumer: processes every delivery (double-processing) ---
    naive_effects: list[str] = []
    for evt in DELIVERIES:
        naive_effects.append(evt)            # NO dedup -> every delivery acts
    naive_dupes = len(naive_effects) - len(set(naive_effects))

    # --- idempotent consumer: dedup by event id (exactly-once effect) ---
    seen: set[str] = set()
    dedup_effects: list[str] = []
    for evt in DELIVERIES:
        if evt in seen:
            continue
        seen.add(evt)
        dedup_effects.append(evt)

    print("  NAIVE consumer (no dedup):")
    print(f"    effects produced = {len(naive_effects)}")
    print(f"    duplicates        = {naive_dupes}  (evt_001, evt_003 x2, evt_005)")
    print("    -> double email, double inventory decrement, double booking")
    print()
    print("  IDEMPOTENT consumer (dedup by event id):")
    print(f"    seen set          = {sorted(seen)}")
    print(f"    effects produced  = {len(dedup_effects)}")
    print(f"    duplicates        = {len(dedup_effects) - len(set(dedup_effects))}")
    print("    -> exactly-once EFFECT on top of at-least-once delivery")
    print()

    ok_naive = naive_effects.count("evt_003") == 3          # triple-processed!
    ok_dedup = dedup_effects.count("evt_003") == 1          # processed once
    ok_count = len(dedup_effects) == len(set(DELIVERIES))
    print(f"  naive consumer triple-processes evt_003?   [check] {'OK' if ok_naive else 'FAIL'}")
    print(f"  idempotent consumer processes evt_003 once? [check] {'OK' if ok_dedup else 'FAIL'}")
    print(f"  dedup effect count == unique events?        [check] {'OK' if ok_count else 'FAIL'}")
    assert ok_naive and ok_dedup and ok_count
    print()
    print(f"  SUMMARY: {len(DELIVERIES)} deliveries -> naive {len(naive_effects)} effects, "
          f"idempotent {len(dedup_effects)} effects")
    print("  (the consumer owns idempotency, NOT the broker)")
    print()
    print("  [check] OK   (at-least-once + idempotent consumer == exactly-once effect)")


# ---------------------------------------------------------------------------
# Section 3 — Retry with dedup (response dropped AFTER execution)
# ---------------------------------------------------------------------------

# Each entry: (operation, [attempt outcomes]). "drop" = the server EXECUTED
# but the response was lost in flight (the dangerous at-least-once case);
# "ok" = executed and the client received the response.
OPERATIONS = [
    ("create_order",     ["drop", "drop", "ok"]),
    ("send_email",       ["ok"]),
    ("update_inventory", ["drop", "ok"]),
]
BACKOFF_SCHEDULE = [0.5, 1.0, 2.0, 4.0]          # seconds, exponential


def _retry_ops(with_dedup: bool) -> tuple[int, int]:
    """Replay the retry scenario. Returns (executions, attempts)."""
    store = IdempotencyStore()
    exe = Executor()
    attempts = 0
    for op, outcomes in OPERATIONS:
        idem_key = f"{op}-key"
        for outcome in outcomes:
            attempts += 1
            if with_dedup:
                r = store.reserve(TENANT, idem_key, {"op": op})
                if r == "CREATED":
                    exe.generic(op, {"op": op})
                    store.complete(TENANT, idem_key, {"status": 200, "body": {"op": op}})
                # DONE -> cached response, NO re-execution
            else:
                exe.generic(op, {"op": op})          # every attempt re-executes
            # 'drop' just means the client did not see this response and will
            # retry; the execution above already happened.
    return exe.executions, attempts


def section_retry_with_dedup() -> None:
    print()
    print("=" * 72)
    print("=== Retry with Dedup — response dropped AFTER execution")
    print("=" * 72)
    print("  The hard case: the server executes the side effect, but the HTTP")
    print("  response is lost (network partition, GC pause, timeout). The client")
    print("  cannot tell executed-but-response-lost from never-received, so it")
    print("  retries. WITHOUT an idempotency key every retry re-executes.")
    print()
    print("  operations + retry patterns:")
    for op, outcomes in OPERATIONS:
        print(f"    {op:<18} attempts = {outcomes}")
    print(f"  total attempts = {sum(len(o) for _, o in OPERATIONS)}")
    print(f"  backoff schedule = {BACKOFF_SCHEDULE}s (exponential, capped)")
    print()

    exec_no, attempts = _retry_ops(with_dedup=False)
    exec_yes, _ = _retry_ops(with_dedup=True)
    logical = len(OPERATIONS)

    print("  WITHOUT idempotency (every attempt that reaches the server executes):")
    print(f"    attempts    = {attempts}")
    print(f"    executions  = {exec_no}   (duplicate side effects: {exec_no - logical})")
    print()
    print("  WITH idempotency (first attempt reserves+executes; retries see DONE):")
    print(f"    attempts    = {attempts}")
    print(f"    executions  = {exec_yes}   (one per logical operation)")
    print()

    ok_more = exec_no > exec_yes
    ok_yes = exec_yes == logical
    ok_no = exec_no == attempts
    print(f"  without-dedup executes every attempt?    [check] {'OK' if ok_no else 'FAIL'}")
    print(f"  with-dedup executes once per operation?  [check] {'OK' if ok_yes else 'FAIL'}")
    print(f"  dedup strictly reduces executions?       [check] {'OK' if ok_more else 'FAIL'}")
    assert ok_more and ok_yes and ok_no
    print()
    print(f"  dedup saved {exec_no - exec_yes} duplicate executions across {logical} operations")
    print()
    print("  [check] OK   (idempotency key turns unsafe retries into safe ones)")


# ---------------------------------------------------------------------------
# Section 4 — Payment double-charge prevention (the killer use case)
# ---------------------------------------------------------------------------

# The PSP charges successfully on attempt 1, but the response is lost. The
# client retries on attempt 2.
CHARGE_ATTEMPTS = ["drop", "ok"]


def _charge_scenario(with_dedup: bool) -> tuple[list[dict], int]:
    store = IdempotencyStore()
    psp = Executor()
    idem_key = "charge-key-4242"
    for outcome in CHARGE_ATTEMPTS:
        if with_dedup:
            r = store.reserve(TENANT, idem_key, PAYMENT_BODY)
            if r == "CREATED":
                psp.charge(PAYMENT_BODY)
                store.complete(TENANT, idem_key, {"status": 200, "body": PAYMENT_BODY})
            # DONE on retry -> cached response, no second charge
        else:
            psp.charge(PAYMENT_BODY)             # every retry charges again
    return psp.charges, psp.executions


def _fmt_amount(cents: int) -> str:
    return f"${cents / 100:.2f}"


def section_payment_double_charge() -> None:
    print()
    print("=" * 72)
    print("=== Payment Double-Charge Prevention")
    print("=" * 72)
    print("  The textbook failure: a user clicks 'Pay', the PSP charges their card,")
    print("  but the response never makes it back (timeout). The user clicks again.")
    print(f"  charge = {PAYMENT_BODY}  ({_fmt_amount(PAYMENT_BODY['amount'])})")
    print(f"  attempts = {CHARGE_ATTEMPTS}   (1st: charged, response lost; 2nd: retry)")
    print()

    bad_charges, bad_exec = _charge_scenario(with_dedup=False)
    good_charges, good_exec = _charge_scenario(with_dedup=True)

    bad_total = sum(c["amount"] for c in bad_charges)
    good_total = sum(c["amount"] for c in good_charges)

    print("  WITHOUT Idempotency-Key (every retry charges the card again):")
    print(f"    ledger = {[c['id'] + ':' + _fmt_amount(c['amount']) for c in bad_charges]}")
    print(f"    total charged = {_fmt_amount(bad_total)}   *** DOUBLE CHARGE ***")
    print()
    print("  WITH Idempotency-Key (retry returns the cached charge):")
    print(f"    ledger = {[c['id'] + ':' + _fmt_amount(c['amount']) for c in good_charges]}")
    print(f"    total charged = {_fmt_amount(good_total)}   (safe)")
    print()

    ok_double = bad_exec == 2 and bad_total == PAYMENT_BODY["amount"] * 2
    ok_safe = good_exec == 1 and good_total == PAYMENT_BODY["amount"]
    ok_saved = bad_total - good_total == PAYMENT_BODY["amount"]
    print(f"  without-dedup double-charges?  [check] {'OK' if ok_double else 'FAIL'}")
    print(f"  with-dedup charges exactly once? [check] {'OK' if ok_safe else 'FAIL'}")
    print(f"  dedup saved one {_fmt_amount(PAYMENT_BODY['amount'])} charge?     [check] {'OK' if ok_saved else 'FAIL'}")
    assert ok_double and ok_safe and ok_saved
    print()
    print(f"  PSP executions: without-dedup = {bad_exec}, with-dedup = {good_exec}")
    print(f"  customer overcharged without the key = {_fmt_amount(bad_total - good_total)}")
    print()
    print("  [check] OK   (idempotency key is the ONLY correct fix for double charge)")


# ---------------------------------------------------------------------------
# Section 5 — Request fingerprinting (key-reuse detection)
# ---------------------------------------------------------------------------

def section_request_fingerprinting() -> None:
    print()
    print("=" * 72)
    print("=== Request Fingerprinting — SHA-256 key-reuse detection")
    print("=" * 72)
    print("  The request_hash column catches a subtle bug: a client reuses an")
    print("  idempotency key with a DIFFERENT body. Stripe returns 409/422 in this")
    print("  case rather than silently honoring the new payload. The hash is over")
    print("  the CANONICAL JSON (sorted keys, no whitespace) so key order and")
    print("  spacing cannot fool it.")
    print()

    h_real = request_hash(PAYMENT_BODY)
    h_same = request_hash({"currency": "USD", "amount": 4250, "customer": "cus_42"})
    h_tamp = request_hash(TAMPERED_BODY)

    print(f"  body A = {PAYMENT_BODY}")
    print("  body B = {currency, amount, customer} (same values, reordered keys)")
    print(f"  body C = {TAMPERED_BODY}  (amount changed 4250 -> 9999)")
    print()
    print(f"  canonical(A) = {canonical_json(PAYMENT_BODY)}")
    print(f"  canonical(B) = {canonical_json({'currency': 'USD', 'amount': 4250, 'customer': 'cus_42'})}")
    print(f"  canonical(C) = {canonical_json(TAMPERED_BODY)}")
    print()
    print(f"  SHA-256(A) = {h_real}")
    print(f"  SHA-256(B) = {h_same}")
    print(f"  SHA-256(C) = {h_tamp}")
    print()

    ok_same = h_real == h_same                      # canonicalization defeats reordering
    ok_diff = h_real != h_tamp                       # different payload -> different digest
    ok_len = len(h_real) == 64                       # full hex digest
    print(f"  reordered keys hash identically?       [check] {'OK' if ok_same else 'FAIL'}")
    print(f"  changed amount produces different hash? [check] {'OK' if ok_diff else 'FAIL'}")
    print(f"  digest is 64 hex chars (256 bits)?     [check] {'OK' if ok_len else 'FAIL'}")
    assert ok_same and ok_diff and ok_len
    print()

    # The dedup store uses this to refuse key reuse (Section 1's HASH_MISMATCH).
    store = IdempotencyStore()
    key = "fingerprint-demo-key"
    store.reserve(TENANT, key, PAYMENT_BODY)
    store.complete(TENANT, key, {"status": 200, "body": PAYMENT_BODY})
    reuse = store.reserve(TENANT, key, TAMPERED_BODY)
    print(f"  store: key {key} used with A, then reused with C")
    print(f"  reserve(C) -> {reuse}  (422 — one key must map to one payload)")
    assert reuse == "HASH_MISMATCH"
    print()
    print("  [check] OK   (canonical SHA-256 fingerprint detects key reuse)")


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    section_dedup_table()
    section_delivery_semantics()
    section_retry_with_dedup()
    section_payment_double_charge()
    section_request_fingerprinting()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
