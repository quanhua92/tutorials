#!/usr/bin/env python3
"""
distributed_tracing.py — Ground truth for DISTRIBUTED_TRACING.md / .html.

Simulates, with real math and a seeded RNG (pure stdlib):
  A. Span data model (trace_id / span_id / parent_span_id / operation / ...)
  B. Context propagation formats (W3C Trace Context, B3, Jaeger) + round-trips
  C. Trace reconstruction from distributed spans (parent_span_id -> tree)
  D. Head-based sampling (probabilistic, decided at ingest, propagates)
  E. Tail-based sampling (decided at collector AFTER seeing the full trace)
  F. Sampling rate math (1% sampling -> how many error traces lost?)
  G. Trace-to-log correlation (inject trace_id into structured JSON logs)
  H. Critical path analysis (the chain of spans that sets end-to-end latency)

Every value printed here is the single source of truth for the bundle.
"""
import json
import random

RNG = random.Random(42)  # seeded -> reproducible _output.txt

BANNER = "=" * 68


def banner(t):
    print(f"\n{BANNER}\n{t}\n{BANNER}")


def check(desc, ok):
    if not ok:
        raise SystemExit(f"FAIL: {desc}")
    print(f"[check] {desc}: OK")


# ---------------------------------------------------------------------------
# Span data model
# ---------------------------------------------------------------------------
class Span:
    """A single unit of work. A trace is a tree of spans linked by parent_span_id."""

    __slots__ = (
        "trace_id", "span_id", "parent_span_id", "operation", "service",
        "start_ms", "duration_ms", "status", "kind", "attributes",
    )

    def __init__(self, trace_id, span_id, parent_span_id, operation, service,
                 start_ms, duration_ms, status="OK", kind="internal", attributes=None):
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id          # None for the root span
        self.operation = operation
        self.service = service
        self.start_ms = start_ms
        self.duration_ms = duration_ms
        self.status = status                          # "OK" | "ERROR"
        self.kind = kind                              # server/client/internal
        self.attributes = attributes or {}

    def end_ms(self):
        return self.start_ms + self.duration_ms

    def short(self):
        return self.span_id[:8]


# ---------------------------------------------------------------------------
# ID generation (W3C-compliant sizes)
# ---------------------------------------------------------------------------
def gen_trace_id():
    # W3C trace-id: 16 bytes = 32 lowercase hex chars
    return "".join(f"{RNG.getrandbits(8):02x}" for _ in range(16))


def gen_span_id():
    # W3C parent-id / span-id: 8 bytes = 16 lowercase hex chars
    return "".join(f"{RNG.getrandbits(8):02x}" for _ in range(8))


# ---------------------------------------------------------------------------
# Context propagation formats
# ---------------------------------------------------------------------------
# W3C Trace Context  ->  traceparent: <version>-<trace-id>-<span-id>-<flags>
#   version   = "00"            (8-bit, current spec; "ff" reserved/invalid)
#   trace-id  = 32 hex chars    (16 bytes; constant for the whole trace)
#   parent-id = 16 hex chars    (8 bytes; the CURRENT span's id on this hop)
#   flags     = 2 hex chars     (8-bit; LSB = sampled: 01 yes / 00 no)
W3C_EXAMPLE = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def encode_w3c(trace_id, span_id, sampled):
    return f"00-{trace_id}-{span_id}-{'01' if sampled else '00'}"


def decode_w3c(traceparent):
    version, trace_id, parent_id, flags = traceparent.split("-")
    if version != "00":
        raise ValueError(f"unsupported traceparent version: {version}")
    return {
        "version": version,
        "trace_id": trace_id,
        "span_id": parent_id,
        "sampled": (int(flags, 16) & 0x01) == 1,
    }


# B3 (Zipkin)  ->  multi-header OR single-header forms
#   X-B3-TraceId: <trace-id>     (32 hex)
#   X-B3-SpanId:  <span-id>      (16 hex)
#   X-B3-ParentSpanId: <parent>  (16 hex, omitted at root)
#   X-B3-Sampled: 1 | 0
#   single header: b3: <trace-id>-<span-id>-<sampling-state>
def encode_b3_headers(trace_id, span_id, parent_span_id, sampled):
    h = {
        "X-B3-TraceId": trace_id,
        "X-B3-SpanId": span_id,
        "X-B3-Sampled": "1" if sampled else "0",
    }
    if parent_span_id:
        h["X-B3-ParentSpanId"] = parent_span_id
    return h


def encode_b3_single(trace_id, span_id, sampled):
    return f"b3: {trace_id}-{span_id}-{'1' if sampled else '0'}"


# Jaeger  ->  uber-trace-id: <trace-id>:<span-id>:<parent-span-id>:<flags>
#   flags = 2-hex bitfield; bit0 = sampled, bit1 = debug
def encode_jaeger(trace_id, span_id, parent_span_id, sampled):
    parent = parent_span_id if parent_span_id else "0"
    flags = "03" if sampled else "00"  # set sampled(1) + debug(2)=3 when sampled
    return f"uber-trace-id: {trace_id}:{span_id}:{parent}:{flags}"


def decode_jaeger(header):
    body = header[len("uber-trace-id: "):]
    trace_id, span_id, parent_span_id, flags = body.split(":")
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "sampled": (int(flags, 16) & 0x01) == 1,
    }


# ---------------------------------------------------------------------------
# A deterministic multi-service checkout trace
# ---------------------------------------------------------------------------
def build_checkout_trace(trace_id, error=False):
    """E-commerce checkout: gateway -> {auth, cart->db, payment->stripe, inventory}.

    Timings are fixed (ms, relative to gateway start) so the trace is fully
    reproducible. When error=True the payment/stripe call FAILS.
    """
    s = []
    g = gen_span_id()
    s.append(Span(trace_id, g, None, "GET /checkout", "gateway",
                  start_ms=0, duration_ms=250, kind="server",
                  attributes={"http.method": "GET",
                              "http.status_code": 500 if error else 200}))
    auth = gen_span_id()
    s.append(Span(trace_id, auth, g, "verify_token", "auth",
                  start_ms=5, duration_ms=15, kind="client"))
    cart = gen_span_id()
    s.append(Span(trace_id, cart, g, "get_cart", "cart",
                  start_ms=25, duration_ms=35, kind="client"))
    db = gen_span_id()
    s.append(Span(trace_id, db, cart, "SELECT cart_items", "db",
                  start_ms=30, duration_ms=25, kind="client",
                  attributes={"db.system": "postgres", "db.statement": "SELECT"}))
    pay = gen_span_id()
    pay_status = "ERROR" if error else "OK"
    s.append(Span(trace_id, pay, g, "charge_card", "payment",
                  start_ms=65, duration_ms=170, kind="client", status=pay_status))
    stripe = gen_span_id()
    stripe_attrs = {"http.url": "https://api.stripe.com/v1/charges"}
    if error:
        stripe_attrs["error.type"] = "card_declined"
    s.append(Span(trace_id, stripe, pay, "POST /v1/charges", "stripe",
                  start_ms=70, duration_ms=160, kind="client",
                  status=pay_status, attributes=stripe_attrs))
    inv = gen_span_id()
    s.append(Span(trace_id, inv, g, "reserve_items", "inventory",
                  start_ms=236, duration_ms=9, kind="client"))
    return s, g


# ---------------------------------------------------------------------------
# Trace reconstruction (parent_span_id -> tree)
# ---------------------------------------------------------------------------
def build_tree(spans):
    by_id = {sp.span_id: sp for sp in spans}
    children = {}
    root = None
    for sp in spans:
        if sp.parent_span_id is None:
            root = sp
        else:
            children.setdefault(sp.parent_span_id, []).append(sp)
    for k in children:
        children[k].sort(key=lambda c: (c.start_ms, c.span_id))
    return root, children


def render_tree(root, children, out, depth=0, last=True, prefix=""):
    branch = "" if depth == 0 else ("\u2514\u2500 " if last else "\u251c\u2500 ")
    line = (f"{prefix}{branch}{root.service}.{root.operation}  "
            f"[{root.duration_ms}ms, {root.status}]  span={root.short()}")
    out.append(line)
    kids = children.get(root.span_id, [])
    for i, k in enumerate(kids):
        is_last = i == len(kids) - 1
        new_prefix = prefix + ("    " if depth == 0 else ("\u2502   " if not last else "    "))
        render_tree(k, children, out, depth + 1, is_last, new_prefix)


# ---------------------------------------------------------------------------
# Samplers
# ---------------------------------------------------------------------------
def head_sample_decision(trace_id, rate):
    """TraceIdRatio-based: deterministic by trace-id.  Same trace-id -> same
    decision on EVERY service, so the call chain is kept or dropped as a unit."""
    tid_int = int(trace_id, 16)                      # 128-bit value
    threshold = int(rate * (1 << 128))               # fraction of the id space
    return tid_int < threshold


def tail_sample_decision(spans, slow_ms=150):
    """Decided at the collector AFTER the full trace is assembled.
    Keep if ANY span errored OR the trace exceeded the latency threshold."""
    has_error = any(sp.status == "ERROR" for sp in spans)
    wall = max(sp.end_ms() for sp in spans) - min(sp.start_ms for sp in spans)
    return has_error or wall >= slow_ms


def capture_probability(rate, occurrences):
    """P(capture >=1 trace in K independent occurrences) = 1 - (1-rate)^K."""
    return 1 - (1 - rate) ** occurrences


def occurrences_for_confidence(rate, confidence):
    """How many times must an event occur to be >=confidence sure we capture it."""
    import math
    return math.ceil(math.log(1 - confidence) / math.log(1 - rate))


# ---------------------------------------------------------------------------
# Structured logs with trace context
# ---------------------------------------------------------------------------
def make_log(trace_id, span_id, service, level, msg, ts_ms):
    return {
        "ts_ms": ts_ms, "level": level, "service": service,
        "trace_id": trace_id, "span_id": span_id, "msg": msg,
    }


# ---------------------------------------------------------------------------
# Critical path
# ---------------------------------------------------------------------------
def critical_path(root, children):
    """The chain of spans that sets end-to-end latency.  Heuristic: from the
    root, descend into the child with the largest duration (the bottleneck).
    That is the synchronous call the parent waited on the longest."""
    path = [root]
    node = root
    while True:
        kids = children.get(node.span_id, [])
        if not kids:
            break
        node = max(kids, key=lambda c: (c.duration_ms, c.span_id))
        path.append(node)
    return path


# ===========================================================================
# Sections
# ===========================================================================
def section_a_span_model():
    banner("A: Span data model")
    tid = gen_trace_id()
    spans, root_id = build_checkout_trace(tid)
    print(f"  trace_id = {tid}  ({len(tid)} hex chars = {len(tid)//2} bytes)")
    print(f"  {len(spans)} spans across services: "
          + ",".join(sorted({sp.service for sp in spans})))
    print()
    hdr = f"  {'service':<10} {'operation':<18} {'span':<9} {'parent':<9} {'start':>5} {'dur':>4} {'end':>5} {'status':<6}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for sp in sorted(spans, key=lambda s: (s.start_ms, s.span_id)):
        parent = sp.parent_span_id[:8] if sp.parent_span_id else "(root)"
        print(f"  {sp.service:<10} {sp.operation:<18} {sp.short():<9} "
              f"{parent:<9} {sp.start_ms:>5} {sp.duration_ms:>4} {sp.end_ms():>5} {sp.status:<6}")
    check("trace_id is 32 hex chars", len(tid) == 32)
    check("all spans share the trace_id", all(sp.trace_id == tid for sp in spans))
    check("exactly one root span (parent_span_id is None)",
          sum(1 for sp in spans if sp.parent_span_id is None) == 1)
    return tid, spans, root_id


def section_b_propagation(tid, spans, root_id):
    banner("B: Context propagation formats")
    root = next(sp for sp in spans if sp.span_id == root_id)
    child = next(sp for sp in spans if sp.parent_span_id == root_id)  # first child
    print("  Gateway -> Auth hop (sampled=True):")
    print("    outgoing W3C traceparent:")
    print("      " + encode_w3c(tid, child.span_id, True))
    print("    outgoing B3 headers:")
    for k, v in encode_b3_headers(tid, child.span_id, root_id, True).items():
        print(f"      {k}: {v}")
    print("    outgoing B3 single-header:")
    print("      " + encode_b3_single(tid, child.span_id, True))
    print("    outgoing Jaeger uber-trace-id:")
    print("      " + encode_jaeger(tid, child.span_id, root_id, True))

    print()
    print("  W3C decode of the documented example:")
    print(f"    {W3C_EXAMPLE}")
    dec = decode_w3c(W3C_EXAMPLE)
    for k, v in dec.items():
        print(f"      {k:<9} = {v}")

    # Round-trip checks
    rt = encode_w3c(tid, child.span_id, True)
    check("W3C encode->decode round-trips trace_id", decode_w3c(rt)["trace_id"] == tid)
    check("W3C decode sampled bit (01 -> True)", dec["sampled"] is True)
    check("B3 single-header carries trace-id", encode_b3_single(tid, child.span_id, True).split(" ")[1].split("-")[0] == tid)
    jh = encode_jaeger(tid, child.span_id, root_id, True)
    check("Jaeger round-trips trace_id", decode_jaeger(jh)["trace_id"] == tid)
    check("Jaeger sampled bit (flags & 1)", decode_jaeger(jh)["sampled"] is True)
    check("W3C trace_id field == 32 hex", len(dec["trace_id"]) == 32)
    check("W3C span_id field == 16 hex", len(dec["span_id"]) == 16)


def section_c_reconstruction(tid, spans, root_id):
    banner("C: Trace reconstruction from distributed spans")
    print("  Spans arrive at the collector out of order and from different")
    print("  services. They are grouped by trace_id, then assembled into a tree")
    print("  using parent_span_id:\n")
    root, children = build_tree(spans)
    out = []
    render_tree(root, children, out)
    for line in out:
        print("  " + line)
    # reorder spans to prove reconstruction is order-independent
    shuffled = sorted(spans, key=lambda s: s.span_id)
    root2, children2 = build_tree(shuffled)
    out2 = []
    render_tree(root2, children2, out2)
    check("reconstruction is order-independent", out == out2)
    check("tree has a single root", root.span_id == root_id)
    n_children = sum(len(v) for v in children.values())
    check(f"parent_span_id edges == {len(spans) - 1}", n_children == len(spans) - 1)


def section_d_head_sampling():
    banner("D: Head-based sampling (decided at ingest, propagates)")
    print("  Decision made ONCE at the entry service using TraceIdRatio.")
    print("  Encoded into trace-flags; every downstream service obeys it, so a")
    print("  trace is kept or dropped as a whole unit.\n")
    rates = [1.0, 0.10, 0.01]
    for r in rates:
        kept = head_sample_decision
        d = {t: head_sample_decision(t, r) for t in DEMO_TRACE_IDS}
        n = sum(d.values())
        print(f"  rate={r*100:>5.1f}%  -> kept {n}/{len(d)} of demo trace-ids")
    # prove propagation: same trace-id -> same decision everywhere
    t_probe = DEMO_TRACE_IDS[0]
    decisions = {t_probe: [head_sample_decision(t_probe, 0.01) for _ in range(5)]}
    vals = decisions[t_probe]
    check("same trace-id yields identical decision at every hop", len(set(vals)) == 1)
    check("rate=100% keeps everything", all(head_sample_decision(t, 1.0) for t in DEMO_TRACE_IDS))
    check("rate=0% keeps nothing", not any(head_sample_decision(t, 0.0) for t in DEMO_TRACE_IDS))


def section_e_tail_sampling(ok_spans, err_spans):
    banner("E: Tail-based sampling (decided at collector after full trace)")
    print("  The collector buffers ALL spans, groups by trace_id, rebuilds the")
    print("  trace, THEN decides. It can keep every trace that errored or was")
    print("  slow -- exactly what head sampling CANNOT do.\n")
    for label, sps in [("OK   trace", ok_spans), ("ERROR trace", err_spans)]:
        kept = tail_sample_decision(sps, slow_ms=150)
        wall = max(sp.end_ms() for sp in sps) - min(sp.start_ms for sp in sps)
        has_err = any(sp.status == "ERROR" for sp in sps)
        print(f"  {label}: wall={wall}ms error={has_err} -> keep={kept}")
    check("tail keeps the error trace", tail_sample_decision(err_spans, slow_ms=150) is True)
    check("tail may drop a fast clean trace (slow_ms=9999)",
          tail_sample_decision(ok_spans, slow_ms=9999) is False)


def section_f_math():
    banner("F: Sampling rate math -- how many error traces are LOST?")
    # Empirical batch
    batch = []
    for i in range(2000):
        t = gen_trace_id()
        batch.append((t, i % 500 == 0))            # 4 errors in 2000
    n_err = sum(1 for _, e in batch if e)
    print(f"  Empirical batch: {len(batch)} traces, {n_err} with errors\n")
    print(f"  {'rate':>7} {'kept':>6} {'err_kept':>9} {'err_lost':>9}")
    for r in [1.0, 0.10, 0.01]:
        kept_ids = {t for t, _ in batch if head_sample_decision(t, r)}
        ek = sum(1 for t, e in batch if e and t in kept_ids)
        print(f"  {r*100:>6.1f}% {len(kept_ids):>6} {ek:>9} {n_err - ek:>9}")
    print("\n  Closed form: P(capture >=1 in K occurrences) = 1 - (1-rate)^K")
    for k in [1, 10, 50, 100, 459]:
        p = capture_probability(0.01, k)
        print(f"    rate=1%  K={k:>3}  ->  P={p*100:>7.3f}%")
    pinned = capture_probability(0.01, 100)
    print(f"\n  PINNED gold value: P(1%, K=100) = {pinned:.10f}")
    k99 = occurrences_for_confidence(0.01, 0.99)
    print(f"  Occurrences needed for 99% capture at 1% rate: K = {k99}")
    check("P(1%,100) == 1 - 0.99**100", abs(pinned - (1 - 0.99 ** 100)) < 1e-12)
    check("at 1% you need >=458 occurrences for 99% capture", k99 == 459)
    check("1% sampling drops ~99% of traces", abs(capture_probability(0.01, 1) - 0.01) < 1e-12)


def section_g_logs(tid, spans, root_id):
    banner("G: Trace-to-log correlation (trace_id injected into structured logs)")
    logs = []
    by_id = {sp.span_id: sp for sp in spans}
    for sp in sorted(spans, key=lambda s: s.start_ms):
        msg = f"handling {sp.operation}"
        lvl = "ERROR" if sp.status == "ERROR" else "INFO"
        logs.append(make_log(tid, sp.span_id, sp.service, lvl, msg, sp.start_ms))
    print(f"  {len(logs)} structured JSON log lines carrying trace_id={tid[:8]}...\n")
    for lg in logs:
        print("  " + json.dumps(lg, sort_keys=True))
    print("\n  Query: pull every log for THIS request by trace_id:")
    hit = [lg for lg in logs if lg["trace_id"] == tid]
    print(f"    -> {len(hit)}/{len(logs)} logs matched")
    check("every log carries the trace_id", all(lg["trace_id"] == tid for lg in logs))
    check("error span produced an ERROR-level log",
          any(lg["level"] == "ERROR" for lg in logs) if any(s.status == "ERROR" for s in spans) else True)


def section_h_critical_path(tid, spans, root_id):
    banner("H: Critical path analysis")
    root, children = build_tree(spans)
    path = critical_path(root, children)
    print("  The critical path is the chain of spans whose sequential duration")
    print("  sets the end-to-end latency. Found by descending into the child with")
    print("  the largest duration at each step (the bottleneck call):\n")
    total = 0
    for i, sp in enumerate(path):
        total += sp.duration_ms
        arrow = "  -> " if i else "      "
        print(f"  {arrow}{sp.service}.{sp.operation}  [{sp.duration_ms}ms]  {sp.short()}")
    print(f"\n  chain length: {len(path)} spans")
    print(f"  sum of durations on path: {total}ms")
    print(f"  root span wall-clock:      {root.duration_ms}ms")
    print("  (sum >= wall because the path's spans are nested, not additive;")
    print("   the leaf duration is what the root actually waited on.)")
    check("critical path starts at the root", path[0].span_id == root_id)
    check("critical path reaches a leaf (no children)",
          path[-1].span_id not in children)
    # In this trace, payment(170ms) is the heaviest child of gateway, and
    # stripe(160ms) is the heaviest child of payment.
    names = [f"{sp.service}.{sp.operation}" for sp in path]
    check("bottleneck chain is gateway->payment->stripe",
          names == ["gateway.GET /checkout", "payment.charge_card", "stripe.POST /v1/charges"])


def main():
    banner("DISTRIBUTED TRACING -- span model, propagation, sampling, logs, critical path")
    global DEMO_TRACE_IDS
    DEMO_TRACE_IDS = [gen_trace_id() for _ in range(12)]

    tid, spans, root_id = section_a_span_model()
    section_b_propagation(tid, spans, root_id)
    section_c_reconstruction(tid, spans, root_id)
    section_d_head_sampling()

    # build a fresh ERROR trace for the tail-sampling contrast
    err_tid = gen_trace_id()
    err_spans, _ = build_checkout_trace(err_tid, error=True)
    ok_spans = spans
    section_e_tail_sampling(ok_spans, err_spans)
    section_f_math()
    section_g_logs(tid, spans, root_id)
    section_h_critical_path(tid, spans, root_id)

    banner("DONE")


if __name__ == "__main__":
    main()
