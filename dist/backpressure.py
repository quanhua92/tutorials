"""
backpressure.py - Reference implementation of backpressure / flow control in a
producer -> queue -> consumer pipeline.

This is the SINGLE SOURCE OF TRUTH that BACKPRESSURE.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 backpressure.py

(Pure Python stdlib only. No external deps. Deterministic inputs.)

============================================================================
THE INTUITION (read this first) -- the funnel and the bucket brigade
============================================================================
Imagine a fast tap (the PRODUCER) pouring water into a bucket with a small hole
in the bottom (the CONSUMER). If the tap runs faster than the hole drains, the
water level rises without bound -- eventually the bucket overflows (OOM).

  * WITHOUT backpressure : the bucket is bottomless. Water level = (in - out) * t.
                           It grows FOREVER. After an hour the floor is flooded.
  * WITH backpressure    : the bucket has a wall. When water hits the wall the
                           tap is told "stop / slow down" (or the surplus spills
                           and is dropped). The level STAYS at the wall. You lose
                           some water (rejected requests) but the floor is dry.

Backpressure is the general name for any mechanism that propagates "I am full /
slow" signal UPSTREAM so the producer cannot outrun the consumer. There are four
families, and this file builds one tiny model of each:

  (A) UNBOUNDED QUEUE  : no signal at all. The backlog grows linearly -> OOM.
  (B) BOUNDED QUEUE    : a wall. When full, REJECT the surplus (HTTP 503 / drop
                         / circuit-break). Throughput = consumer rate.
  (C) REACTIVE STREAMS : the consumer pulls. It requests N items, the producer
                         sends exactly N, no more. "Demand" is the credit.
  (D) TOKEN BUCKET     : the producer must buy a token per request; tokens refill
                         at r/s up to a burst cap R. Smooth rate limiting.
  (E) LOAD SHEDDING    : when overloaded, drop the UNIMPORTANT work (analytics,
                         batch) and protect the IMPORTANT work (payments).

WHY IT MATTERS: without backpressure, one slow downstream service makes its
upstream queue grow until RAM exhausts -> OOM, GC death-spiral, thread pool
starvation, and CASCADING TIMEOUTS that take down services that were never even
slow. Backpressure contains the blast radius of a slow downstream.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  producer    : upstream service that emits work (requests, events, messages).
  consumer    : downstream service that does the work. Often the slow one.
  queue /     : the buffer between them. Its depth is THE number we watch.
  backlog
  backpressure: any signal/mechanism that stops the producer from outrunning the
                consumer. "Pushing back" on the upstream.
  unbounded   : a queue with no size limit. depth -> infinity if producer > consumer.
  bounded     : a queue with a hard cap K. Surplus is rejected/dropped at the cap.
  reject /    : refusing a request when the system is full. HTTP 503 is the web
  shed          form; circuit-breaking is the RPC form; drop is the network form.
  reactive    : a pull-based protocol. The consumer grants "demand" (credits);
  stream /       the producer may emit at most `demand` items. Project Reactor,
  request-N      RxJava, Java 9 Flow, Reactive Streams spec.
  demand /    : outstanding permits. Producer emits one -> demand -= 1. Consumer
  credits        requests N -> demand += N. In-flight items <= demand cap.
  token bucket: a bucket of capacity R tokens, refilled at r tokens/s. Each
                request costs 1 token; no token -> reject. Allows a burst of R.
  leaky bucket: the cousin: a queue that drips OUT at exactly r/s (no bursts).
  load        : priority-aware dropping. Under overload, shed LOW priority
  shedding      (analytics, batch, prefetch) to keep HIGH priority (payments,
                user-facing) healthy. A.K.A. "bulkhead + graceful degradation".
  Little's Law: L = lambda * W. Average in-flight (L) = throughput (lambda) *
                latency (W). Backpressure CAPS L, so it caps lambda*W.
  cascading   : a slow service times out its callers; they retry; the retries
  failure       make the slow service slower; everyone dies. Backpressure stops it.

============================================================================
THE PAPERS / BOOKS (the lineage)
============================================================================
  Little (1961) "A Proof for the Queuing Formula L = lambda W"
      Operations Research 9(3):383-387. The queueing identity L=lambda*W.
  Reactive Manifesto (2014) / Reactive Streams spec (2015, v1.0)
      The request-N demand-pull contract (Java 9 Flow.*, Project Reactor, RxJava).
  Turner (1986) "New Directions in Communications (or Which Way to the
      Information Age?)" IEEE TCOM. Token bucket / leaky bucket for traffic shaping.
  Bennett (Netflix, 2012) "Hystrix" -> the bulkhead pattern: isolate failures,
      shed load at boundaries. Now Resilience4j.
  Beyer et al (2016) "Site Reliability Engineering" (Google), esp. the
      "Cascading Failures" & "Handling Overload" chapters. Load shedding as SRE.
  Kleppmann (2017) "Designing Data-Intensive Applications", Ch.1 (reliability)
      & Ch.11 (stream processing, backpressure).

KEY RESULTS (all verified + asserted in code):
    unbounded growth   : depth(t) = (P - C) * t   for P > C  (linear, unbounded).
    time to fill cap   : t_fill = K / (P - C)     (fluid model).
    bounded steady     : depth <= K forever; throughput = C; rejected = P - C per s.
    request-N invariant: in-flight items <= N (demand cap). Producer gated by consumer.
    token bucket       : burst = R; sustained throughput = min(P, r).
    Little's Law       : L = lambda * W  ->  capping L caps lambda*W (backpressure).

Conventions in this file:
  P       = producer rate (req/s). Here: 100.
  C       = consumer rate (req/s). Here: 50.  (C < P => overload, the whole point)
  K       = bounded queue capacity.   Here: 1000.
  N       = reactive demand batch.    Here: 10.
  R, r    = token bucket capacity / refill (20 tokens, 50 tokens/s).
  tick    = 1 second. Sim is produce-then-consume per tick (deterministic).
"""

from __future__ import annotations

BANNER = "=" * 72

# ---------------------------------------------------------------------------
# Model parameters (deterministic; the .html recomputes with the SAME values)
# ---------------------------------------------------------------------------
P = 100            # producer rate (req/s)
C = 50             # consumer rate (req/s)  -- C < P, so the system is overloaded
K = 1000           # bounded queue capacity
N = 10             # reactive-streams demand batch (request-N)
R = 20             # token bucket capacity (burst tokens)
r = 50             # token bucket refill rate (tokens/s)
BYTES_PER_ITEM = 1024   # ~1 KB per queued request (payload + metadata)
SIM_TICKS = 3600        # 1 hour, for the gold capstone


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 1. THE CORE MODEL  (the code BACKPRESSURE.md walks through)
#    Continuous FLUID / queueing approximation (Kleinrock). Closed-form & exact,
#    so the .html recomputes byte-identical numbers. net = P - C > 0 = overload.
# ============================================================================

NET = P - C          # net queue growth rate when producer outruns consumer


def fluid_depth(t: float, cap: float = float("inf")) -> float:
    """Queue depth at time t. Grows at NET until it hits the cap, then flat.

    UNBOUNDED (cap=inf): depth(t) = (P - C) * t  -> linear, unbounded.
    BOUNDED   (cap=K)  : depth(t) = min(K, (P - C) * t)  -> saturates at K.
    """
    return min(cap, NET * t)


def fluid_stats(t: float, cap: float) -> dict:
    """Closed-form fluid stats over [0, t] for a queue of capacity `cap`.

    The consumer is the bottleneck, so GOODPUT (work actually done) = C * t in
    BOTH regimes. The difference is purely what happens to the surplus:
    unbounded HOARDS it (depth -> inf), bounded REJECTS it at the wall.
    """
    sent = P * t
    depth = fluid_depth(t, cap)
    processed = C * t                     # consumer-bound goodput
    rejected = sent - processed - depth   # what the wall turned away
    return {"depth": depth, "processed": processed, "rejected": rejected,
            "sent": sent}


def reactive_cycle(n: int, cycles: int) -> tuple[list[tuple[str, int, int]], int]:
    """Simulate a request-N reactive stream for `cycles` pull cycles.

    Each cycle: consumer requests N (demand += N); producer emits until demand
    hits 0 (each emit -> demand-1, in_flight+1); consumer processes the batch
    (in_flight -> 0). Returns the (phase, demand, in_flight) trace and the peak
    in-flight count. Invariant: in_flight <= N always.
    """
    demand = 0
    in_flight = 0
    max_in_flight = 0
    trace: list[tuple[str, int, int]] = []
    for _ in range(cycles):
        demand += n
        trace.append(("consumer requests N", demand, in_flight))
        emits = 0
        while demand > 0:
            demand -= 1
            in_flight += 1
            emits += 1
            if in_flight > max_in_flight:
                max_in_flight = in_flight
        trace.append((f"producer emits {emits}", demand, in_flight))
        in_flight = 0
        trace.append(("consumer processes batch", demand, in_flight))
    return trace, max_in_flight


def token_bucket_burst(requests: int, tokens: int) -> tuple[int, int, int]:
    """A burst of `requests` hits a bucket with `tokens` tokens (capacity R).

    Each request costs 1 token. Returns (admitted, tokens_after, rejected).
    Shows the burst cap: at most R requests pass instantly from a full bucket.
    """
    admitted = min(requests, tokens)
    return admitted, tokens - admitted, requests - admitted


def load_shed(budget: int, arrivals: dict[str, int],
              priority_order: list[str]) -> dict[str, dict]:
    """Priority load shedding. `budget` = services/s (the consumer rate).

    Serve classes in `priority_order` (HIGH first). Each class gets
    min(its_arrivals, remaining_budget); the surplus is SHED. Returns per-class
    {arrivals, served, shed, loss_rate} and totals.
    """
    remaining = budget
    out: dict[str, dict] = {}
    for cls in priority_order:
        a = arrivals[cls]
        served = min(a, remaining)
        remaining -= served
        shed = a - served
        out[cls] = {
            "arrivals": a,
            "served": served,
            "shed": shed,
            "loss_rate": shed / a if a else 0.0,
        }
    out["__total__"] = {
        "arrivals": sum(arrivals.values()),
        "served": budget - remaining,
        "shed": sum(v["shed"] for k, v in out.items() if k != "__total__"),
    }
    return out


# ============================================================================
# 2. THE SIMULATION SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: UNBOUNDED QUEUE -- the backlog grows linearly forever
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: UNBOUNDED QUEUE  -- depth(t) = (P - C) * t  (linear -> OOM)")
    net = P - C
    print(f"Producer P = {P} req/s, consumer C = {C} req/s. The consumer is")
    print(f"the bottleneck, so the queue grows at the NET rate (P - C) = {net}/s.\n")
    print("With NO backpressure the queue is bottomless. Its depth at time t is:")
    print(f"    depth(t) = (P - C) * t = {net} * t\n")
    print("Growth curve (closed form) -- watch it run away:\n")
    print("| elapsed     | queue depth | memory @ 1 KB/item |")
    print("|-------------|--------------|---------------------|")
    for label, t in [("1 s", 1), ("10 s", 10), ("1 min", 60),
                     ("10 min", 600), ("1 hour", 3600)]:
        d = net * t
        mib = d * BYTES_PER_ITEM / 2 ** 20
        print(f"| {label:<11} | {d:<12,} | {mib:<10.1f} MiB     |")
    print()
    print(f"After 1 HOUR the backlog is {net * 3600:,} items"
          f" = {net * 3600 * BYTES_PER_ITEM / 2 ** 20:.0f} MiB of heap -- and it")
    print("never stops growing. Long before that you hit OOM, the GC thrashes on")
    print("a 100k+ object heap, thread pools block on the queue's lock, and the")
    print("caller's timeouts fire -- a CASCADING FAILURE that takes down services")
    print("that were never even slow.\n")
    print("Little's Law (L = lambda * W) says in-flight L grows with latency W.")
    print("Here latency grows without bound (requests age in the queue forever),")
    print("so L grows without bound. No finite RAM survives an unbounded queue.\n")
    print(f"GOLD: unbounded growth rate = (P - C) = {net} items/s; "
          f"depth at 1 h = {net * 3600:,}.")
    assert net * 3600 == 180_000
    print(f"[check] depth(3600) = (P - C) * 3600 = {net} * 3600 = "
          f"{net * 3600:,}:  OK")


# ----------------------------------------------------------------------------
# SECTION B: BOUNDED QUEUE -- cap K, reject the surplus, throughput = C
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: BOUNDED QUEUE  -- cap K, reject surplus, throughput = C")
    net = P - C
    t_fill = K / net
    print(f"Give the queue a hard cap K = {K}. The fluid model says the backlog")
    print("grows at (P - C) until it hits the wall, then the surplus is rejected:\n")
    print("    depth(t)   = min(K, (P - C) * t)        saturates at K")
    print("    goodput    = C                          (consumer-bound, always)")
    print("    reject rate= P - C    once saturated\n")
    print(f"  - below the wall: producer sends {P} req/s, all fit, none rejected.")
    print(f"  - at the wall:    consumer frees C = {C} slots/s, producer refills")
    print(f"    those {C} and the other (P - C) = {net} are REJECTED"
          " (HTTP 503 / drop / circuit-break).\n")
    print(f"FILL PHASE (depth < K): grows at (P - C) = {net}/s until the wall.")
    print("Time to fill (fluid model):")
    print(f"    t_fill = K / (P - C) = {K} / {net} = {t_fill:.0f} s\n")
    print(f"SATURATED PHASE (depth = K): steady depth <= K = {K} (BOUNDED), "
          f"goodput = C = {C}/s,\nreject (P - C) = {net}/s "
          f"({net / P:.0%} of arrivals).\n")
    print("Timeline (fluid model, 1 s steps):")
    print("| t (s) | queue depth | admitted/s | rejected/s | cumulative rejected |")
    print("|-------|-------------|------------|------------|---------------------|")
    for t in (1, 5, 10, 15, 20, 21, 30, 45, 60):
        depth = int(fluid_depth(t, K))
        if t <= int(t_fill):           # still filling: all P admitted
            adm, rej = P, 0
        else:                          # saturated: only C admitted
            adm, rej = C, P - C
        cum = max(0, (t - int(t_fill)) * (P - C))
        mark = " <- wall saturated" if t == int(t_fill) else (
            " <- first rejection" if t == int(t_fill) + 1 else "")
        print(f"| {t:<5} | {depth:<11,} | {adm:<10} | {rej:<10} | "
              f"{cum:<19,} |{mark}")
    print()
    print(f"The queue saturated at t = {int(t_fill)} s, then STAYED at depth = "
          f"{K} forever. Goodput\ncollapsed to exactly C = {C}/s -- which is all")
    print(f"the consumer could ever do anyway. The rejected {net}/s were going to")
    print("die of timeout regardless; rejecting them EARLY (at the boundary)")
    print("fails fast and frees the caller to retry elsewhere instead of waiting")
    print("an age for a slot that will never come.\n")
    sat = fluid_stats(60, K)
    assert sat["depth"] == K
    assert sat["processed"] == C * 60
    assert sat["rejected"] == P * 60 - C * 60 - K
    print(f"GOLD: steady depth <= K = {K}; goodput = C = {C}/s; "
          f"reject rate = (P-C)/P = {net / P:.0%}.")
    print(f"[check] depth(60)=={K}, processed(60)==C*60=={C * 60}, "
          f"rejected(60)=={sat['rejected']}:  OK")


# ----------------------------------------------------------------------------
# SECTION C: REACTIVE STREAMS -- consumer pulls, request-N demand gating
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: REACTIVE STREAMS  -- request-N, in-flight <= N  (natural BP)")
    print("Instead of the producer PUSHING (and hoping the queue holds), let the")
    print("consumer PULL. The consumer maintains DEMAND (credits): it requests N")
    print("items, the producer may emit AT MOST N, then it must wait for the next")
    print("request. The producer can NEVER outrun the consumer -- it is physically")
    print("gated by outstanding demand.\n")
    print("Reactive Streams / Project Reactor / RxJava / Java 9 Flow all use this")
    print(f"contract. Here N = {N}.\n")
    trace, max_if = reactive_cycle(N, 2)
    print("Two pull cycles (phase, demand, in_flight):")
    print("| phase                      | demand | in_flight |")
    print("|----------------------------|--------|-----------|")
    for phase, d, ifl in trace:
        print(f"| {phase:<26} | {d:<6} | {ifl:<9} |")
    print()
    print(f"Each cycle: demand goes {N} -> 0, in_flight goes 0 -> {N} -> 0. The")
    print("producer emitted EXACTLY what the consumer asked for. Crucially:")
    print(f"\n    MAX in-flight items = demand cap N = {max_if}.\n")
    print("Throughput = the consumer's processing rate: it requests another N as")
    print("soon as it finishes a batch, so it self-clocks at the speed it can")
    print("digest. There is NO unbounded buffer to overflow -- backpressure is a")
    print("property of the protocol, not a band-aid.\n")
    print("Little's Law again: L = lambda * W. The demand cap N bounds L, so the")
    print("consumer can trade throughput (lambda) against latency (W) by tuning N")
    print("-- bigger N = more pipeline parallelism (higher throughput, more memory)")
    print("smaller N = tighter bound (lower memory, maybe lower throughput).\n")
    assert max_if == N
    print(f"GOLD: max in-flight == demand cap N == {N}; producer gated by demand.")
    print(f"[check] max_in_flight ({max_if}) == N ({N}):  OK")


# ----------------------------------------------------------------------------
# SECTION D: TOKEN BUCKET -- rate limiting, burst cap R, sustained rate r
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: TOKEN BUCKET  -- burst cap R, sustained rate r  (rate limit)")
    print("A token bucket holds up to R tokens, refilled at r tokens/s. Each")
    print("request CONSUMES 1 token; if the bucket is empty the request is")
    print(f"REJECTED. Two dials: capacity R = {R} (burst size) and refill r = {r}/s")
    print("(long-term average allowed rate).\n")
    print("BURST behaviour -- a sudden spike hitting a FULL bucket (tokens = R):")
    print("| requests in burst | tokens before | admitted | tokens after | rejected |")
    print("|-------------------|---------------|----------|--------------|----------|")
    for reqs in (5, 10, 15, 20, 25, 50):
        adm, after, rej = token_bucket_burst(reqs, R)
        print(f"| {reqs:<17} | {R:<13} | {adm:<8} | {after:<12} | {rej:<8} |")
    print(f"\nAt most R = {R} requests pass from a single burst; the rest are")
    print("rejected instantly. That is the burst cap: it absorbs short spikes")
    print("without dropping, but caps the spike height.\n")
    print(f"SUSTAINED behaviour -- a steady stream at P = {P}/s hitting a bucket")
    print(f"refilling at r = {r}/s. The bucket cannot sustain more than r/s, so:")
    print(f"    sustained throughput = min(P, r) = min({P}, {r}) = {min(P, r)}/s")
    print(f"    sustained reject rate = (P - r)/P = ({P} - {r})/{P} = "
          f"{(P - r) / P:.0%}\n")
    print("Token bucket vs the others:")
    print("| mechanism     | what it bounds            | burst?        |")
    print("|---------------|---------------------------|---------------|")
    print(f"| bounded queue | buffer depth K = {K:<6}    | buffers first |")
    print(f"| token bucket  | RATE r = {r}/s, burst {R:<3}  | burst {R} then {r}/s |")
    print("| reactive      | in-flight N = 10          | pull-gated    |")
    print("| leaky bucket  | OUTPUT rate r/s exactly   | NO burst      |")
    print()
    print("Leaky bucket is the strict cousin: it is a queue that drips OUT at")
    print("exactly r/s, smoothing all bursts into a flat rate. Token bucket lets")
    print("short bursts through (up to R); leaky bucket does not. APIs (Stripe,")
    print("GitHub) usually pick token bucket so honest clients are not punished")
    print("for a quick spike.\n")
    assert token_bucket_burst(R, R) == (R, 0, 0)
    assert min(P, r) == r
    print(f"GOLD: burst cap = R = {R}; sustained throughput = min(P, r) = {r}/s; "
          f"reject rate = (P - r)/P = {(P - r) / P:.0%}.")
    print(f"[check] burst({R}) admits exactly {R}, drains bucket to 0; "
          f"sustained = {r}/s:  OK")


# ----------------------------------------------------------------------------
# SECTION E: LOAD SHEDDING -- priority-aware dropping, protect the critical path
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: LOAD SHEDDING  -- drop LOW priority, protect HIGH")
    print("When the system MUST drop work, drop the UNIMPORTANT work. Tag each")
    print("request with a priority; under overload, serve HIGH first and SHED the")
    print("LOW surplus. This keeps the critical path (payments, user-facing) green")
    print("while gracefully degrading the rest (analytics, batch, prefetch).\n")
    budget = C                       # the consumer can do C = 50 services/s
    arrivals = {"HIGH (payments)": 20, "MEDIUM (API)": 40, "LOW (analytics)": 40}
    order = ["HIGH (payments)", "MEDIUM (API)", "LOW (analytics)"]
    print(f"Service budget = consumer rate = {budget}/s. Arrivals total "
          f"{sum(arrivals.values())}/s (overloaded {sum(arrivals.values())}/{budget}).")
    print("Policy: serve in priority order HIGH -> MEDIUM -> LOW; shed the rest.\n")
    res = load_shed(budget, arrivals, order)
    print("| class               | arrivals/s | served/s | shed/s | loss rate |")
    print("|---------------------|------------|----------|--------|-----------|")
    for cls in order:
        rr = res[cls]
        print(f"| {cls:<19} | {rr['arrivals']:<10} | {rr['served']:<8} | "
              f"{rr['shed']:<6} | {rr['loss_rate']:<9.1%} |")
    tot = res["__total__"]
    print(f"| {'TOTAL':<19} | {tot['arrivals']:<10} | {tot['served']:<8} | "
          f"{tot['shed']:<6} | {tot['shed'] / tot['arrivals']:<9.1%} |")
    print()
    print("WITHOUT priority (FIFO / random drop under overload), every class")
    print(f"loses the same fraction (~{tot['shed'] / tot['arrivals']:.0%}) -- so the")
    print("PAYMENTS class would also be shed, exactly when it matters most.")
    print("WITH priority load shedding the loss is GRADUATED: HIGH (payments)")
    print("loses nothing, MEDIUM (API) loses a slice, and only LOW (analytics)")
    print(f"is fully shed. Same total goodput (consumer-bound at {budget}/s),")
    print("radically smaller BLAST RADIUS -- the critical path stays green while")
    print("the cheap work degrades.\n")
    high, med, low = res["HIGH (payments)"], res["MEDIUM (API)"], res["LOW (analytics)"]
    assert high["shed"] == 0 and high["served"] == 20
    assert med["served"] == 30 and med["shed"] == 10
    assert low["served"] == 0 and low["shed"] == 40
    assert tot["served"] == budget
    print(f"GOLD: HIGH served = {high['served']} (loss {high['loss_rate']:.0%}); "
          f"MEDIUM loss {med['loss_rate']:.0%}; LOW served = {low['served']} "
          f"(loss {low['loss_rate']:.0%}); total served = {tot['served']} = consumer.")
    print(f"[check] HIGH loss == 0, MEDIUM loss > 0, LOW loss == 100%, "
          f"total served == {budget}:  OK")


# ============================================================================
# 3. GOLD CHECK  (capstone: bounded vs unbounded over 1 hour, pinned for .html)
# ============================================================================

def gold_check():
    banner("GOLD CHECK  (bounded vs unbounded over 1 hour -- pinned for backpressure.html)")
    print("Capstone: run BOTH regimes -- unbounded (no backpressure) and bounded")
    print(f"(cap K = {K}) -- for a full hour ({SIM_TICKS} s) at P = {P}, "
          f"C = {C}, using the closed-form fluid model. The headline invariant:")
    print("backpressure keeps the queue BOUNDED while the unbounded queue grows")
    print("linearly -- for the SAME goodput (both process exactly what the")
    print("consumer can handle).\n")
    T = SIM_TICKS
    u = fluid_stats(T, float("inf"))
    b = fluid_stats(T, K)
    ratio = u["depth"] / b["depth"]
    print(f"  {'metric':<22}{'unbounded':>14}{'bounded (K=' + str(K) + ')':>20}")
    print(f"  {'-' * 56}")
    print(f"  {'max queue depth':<22}{int(u['depth']):>14,}{int(b['depth']):>20,}")
    print(f"  {'depth at 1 hour':<22}{int(u['depth']):>14,}{int(b['depth']):>20,}")
    print(f"  {'processed (goodput)':<22}{int(u['processed']):>14,}"
          f"{int(b['processed']):>20,}")
    print(f"  {'rejected':<22}{int(u['rejected']):>14,}{int(b['rejected']):>20,}")
    print(f"  {'depth ratio':<22}{ratio:>13.0f}x{'':>20}")
    print()
    print("READ THIS TABLE: the two columns process the SAME number of requests")
    print(f"(goodput = C * 1h = {int(C * T):,} in BOTH) because the consumer is")
    print("the bottleneck either way. The ONLY difference is memory and honesty:")
    print(f"  - unbounded hoards {int(u['depth']):,} items in RAM (OOM, GC thrash,")
    print("    then cascading timeouts) and tells callers NOTHING.")
    print(f"  - bounded caps RAM at <= {K} items and FAILS FAST on the "
          f"{int(b['rejected']):,} it cannot serve, so callers retry elsewhere")
    print("    instead of waiting.\n")
    print("That is the whole deal backpressure makes: trade rejections for bounded")
    print("memory and fast failure. Same useful goodput; survivable overload.\n")
    # assertions pinning the gold values
    assert u["depth"] == 180_000
    assert u["rejected"] == 0
    assert u["processed"] == C * T
    assert b["depth"] == K
    assert b["processed"] == C * T
    assert b["rejected"] == 179_000
    assert ratio == 180
    print("GOLD scalars (pinned for backpressure.html):")
    print(f"  unbounded_depth_1h    = {int(u['depth'])}")
    print(f"  unbounded_rejected    = {int(u['rejected'])}")
    print(f"  bounded_depth_1h      = {int(b['depth'])}")
    print(f"  bounded_rejected_1h   = {int(b['rejected'])}")
    print(f"  goodput_both          = {int(b['processed'])}   (C * 1h, IDENTICAL)")
    print(f"  depth_ratio           = {ratio:.0f}x")
    print(f"  time_to_fill          = {int(K / NET)} s   (K / (P - C))")
    print(f"\n[check] bounded depth <= {K} while unbounded -> {int(u['depth']):,}; "
          f"goodput identical; ratio {ratio:.0f}x:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("backpressure.py - reference impl. All numbers below feed BACKPRESSURE.md.")
    print(f"python stdlib only. Deterministic. (P={P}, C={C}, K={K}, N={N}, "
          f"R={R}, r={r})")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
