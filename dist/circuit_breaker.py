"""
circuit_breaker.py - Reference implementation of the CIRCUIT BREAKER pattern
for microservice resilience: a tiny finite-state machine (CLOSED -> OPEN ->
HALF_OPEN) that turns a cascading failure into a fast, local error.

This is the single source of truth that CIRCUIT_BREAKER.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 circuit_breaker.py

============================================================================
THE INTUITION (read this first) - the electric fuse in your fuse box
============================================================================
A circuit breaker is the software twin of the fuse in your fuse box. Normally
current flows (requests pass through to the downstream service). If there is a
short circuit downstream (the service starts failing or hanging), the fuse
BLOWS: it stops passing current, fast, to stop the fault from spreading along
the wiring and burning down the house (cascading the failure to every caller).

Three states, exactly three:

  * CLOSED   : "everything is fine." Requests go through to the downstream
               service. We keep a running count of CONSECUTIVE failures. The
               instant that count reaches `failure_threshold`, we TRIP: the
               breaker flips to OPEN. (CLOSED = the fuse is intact.)

  * OPEN     : "the downstream is on fire; do not call it." Every request is
               REJECTED immediately, in the caller's own thread, without ever
               touching the network or a worker thread. This is the fast-fail.
               The breaker stays OPEN for `reset_timeout` seconds (a cooling-off
               period), then flips to HALF_OPEN to probe whether the downstream
               has recovered. (OPEN = the fuse has blown; current is cut.)

  * HALF_OPEN: "maybe it is better now - let a FEW requests through to test."
               We allow at most `half_open_max` PROBE requests to actually call
               the downstream. If ALL of them succeed, we declare recovery and
               flip back to CLOSED. If ANY one fails, we flip straight back to
               OPEN and restart the cooling-off clock. (HALF_OPEN = we are
               cautiously tipping the fuse back in, one finger on it.)

THE REASON IT EXISTS: without a breaker, a slow or failing downstream does not
fail in isolation. Each call to it holds one of your worker threads for the
full (long) latency. Your thread pool drains, the next caller queues, YOUR
service now looks slow to ITS callers, their thread pools drain, and the
failure CASCADES upstream until the whole system is down - even though only one
leaf service was actually broken. The breaker breaks that chain at the first
hop: once tripped, calls return in ~1ms instead of waiting seconds, so your
threads stay free, YOUR service stays responsive (it returns errors fast), and
the cascade never starts. The downstream also gets a chance to recover because
nobody is hammering it. That is the whole point.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  downstream     : the remote service we call (a database, another microservice,
                   an API). The thing that can fail or stall.
  failure        : a call to the downstream that returned an error, threw, or
                   timed out. In this file: outcome == "fail".
  consecutive
  failures       : failures in a row, with NO success in between. A single
                   success resets the counter to 0 (CLOSED) - the breaker
                   forgets ancient history.
  trip           : the CLOSED -> OPEN transition. Happens the moment
                   `consecutive_failures` reaches `failure_threshold`.
  fast-fail      : rejecting a request in the OPEN state immediately, WITHOUT
                   calling the downstream. Returns an error to the caller in
                   ~constant time (no network, no worker thread held).
  reset timeout  : how long the breaker stays OPEN before allowing a probe.
                   Longer = gentler on the downstream, slower to recover.
  probe          : a real call to the downstream allowed through in HALF_OPEN,
                   to test recovery. Limited to `half_open_max` of them.
  cascade        : a failure in one service propagating upstream by exhausting
                   resources (threads, connections) in its callers, and theirs,
                   until the whole system is affected.
  thread
  exhaustion     : all worker threads in a pool busy waiting on a slow
                   downstream, so new work cannot be picked up. The direct
                   mechanism of a cascade.

============================================================================
THE SOURCES (every decision below verified against these)
============================================================================
  * Michael T. Nygard, "Release It!: Design and Deploy Production-Ready
    Software" (Pragmatic Bookshelf, 2007), Chapter 5 "Stability Patterns" -
    "Circuit Breaker". The pattern's origin. Defines the three states and the
    threshold / timeout / probe knobs exactly as implemented here.
  * Martin Fowler, "CircuitBreaker" (martinfowler.com, 2014) - the canonical
    one-page description; same CLOSED/OPEN/HALF_OPEN machine.
  * Netflix Hystrix (wiki "How it Works") - popularized the pattern at scale.
    Defaults informing the discussion: `circuitBreaker.requestVolumeThreshold`
    (rolling-window volume before the breaker can trip), `errorThresholdPercentage`
    (trip when error rate exceeds it), `sleepWindowInMilliseconds` (reset
    timeout), and HALF_OPEN allowing a single trial request.
  * Resilience4j `CircuitBreaker` (successor to Hystrix) - same machine;
    `failureRateThreshold`, `waitDurationInOpenState`, `permittedNumberOfCalls
    InHalfOpenState`.

KEY RULES (all asserted in code below):
    CLOSED   -> OPEN      : consecutive_failures >= failure_threshold
    OPEN     -> HALF_OPEN : (now - opened_at) >= reset_timeout   (checked on
                            the next request, never on a timer - lazy transition)
    HALF_OPEN -> CLOSED   : half_open_successes == half_open_max
                             (i.e. `half_open_max` consecutive successful probes)
    HALF_OPEN -> OPEN     : any single probe failure  (restart cooling-off)
    OPEN     reject       : request is NOT forwarded; returns immediately.
                            Uses NO downstream worker thread (the cascade
                            prevention hinge).

============================================================================
THE DETERMINISTIC SCENARIO (reused by every section and by the .html)
============================================================================
All traces below are HARD-CODED (no RNG), so circuit_breaker.html can replay
them byte-for-byte and gold-check the identical state sequence.

  * CANONICAL_TRACE : 18 timestamped requests that exercise EVERY transition
                      (CLOSED->OPEN, OPEN->HALF_OPEN, HALF_OPEN->CLOSED,
                      HALF_OPEN->OPEN). Drives Sections A, B, C and the GOLD.
                      Default config: threshold=3, reset_timeout=5.0s,
                      half_open_max=2.
  * CASCADE_STREAM  : 16 evenly-spaced requests against a downstream that is
                      degraded (2000ms, failing). Drives Section D's thread-
                      pool simulation, with and without a breaker.
  * FLAP_TRACE      : a short failure burst followed by recovery. Drives
                      Section E's config trade-off (sensitive / balanced /
                      tolerant).
"""

from __future__ import annotations

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# The deterministic scenario. Single source of truth for every section.
# ----------------------------------------------------------------------------
DEFAULT_THRESHOLD = 3            # consecutive failures that trip CLOSED -> OPEN
DEFAULT_RESET_TIMEOUT = 5.0      # seconds OPEN before HALF_OPEN (cooling-off)
DEFAULT_HALF_OPEN_MAX = 2        # successful probes required to CLOSE again

# CANONICAL_TRACE: 18 (time_s, downstream_outcome) events. "ok"/"fail" is the
# result IF the call is actually made; in OPEN the request is rejected and the
# outcome never reaches the downstream. Default config trips at event 4,
# half-opens at event 7, etc. - see Section A/B/C and the GOLD check.
CANONICAL_TRACE = [
    (1.0,  "ok"),     # 0
    (2.0,  "ok"),     # 1
    (3.0,  "fail"),   # 2   consec_failures = 1
    (4.0,  "fail"),   # 3   consec_failures = 2
    (5.0,  "fail"),   # 4   consec_failures = 3  -> TRIP to OPEN @ t=5.0
    (6.0,  "ok"),     # 5   OPEN (6-5=1 < 5)     -> REJECT (fast-fail)
    (7.0,  "fail"),   # 6   OPEN (7-5=2 < 5)     -> REJECT
    (20.0, "ok"),     # 7   20-5=15 >= 5         -> HALF_OPEN, probe ok (1/2)
    (21.0, "ok"),     # 8   probe ok (2/2)       -> CLOSE
    (22.0, "ok"),     # 9   CLOSED
    (23.0, "fail"),   # 10  consec_failures = 1
    (24.0, "fail"),   # 11  consec_failures = 2
    (25.0, "fail"),   # 12  consec_failures = 3  -> TRIP to OPEN @ t=25.0
    (26.0, "ok"),     # 13  OPEN (26-25=1 < 5)   -> REJECT
    (40.0, "fail"),   # 14  40-25=15 >= 5        -> HALF_OPEN, probe FAIL -> OPEN @40
    (41.0, "ok"),     # 15  OPEN (41-40=1 < 5)   -> REJECT
    (50.0, "ok"),     # 16  50-40=10 >= 5        -> HALF_OPEN, probe ok (1/2)
    (51.0, "ok"),     # 17  probe ok (2/2)       -> CLOSE
]

# CASCADE_STREAM: 16 requests, 200ms apart, against a DEGRADED downstream
# (each call takes 2000ms and fails). Used by Section D to show a 4-thread pool
# saturating WITHOUT a breaker vs staying free WITH one. Times in MILLISECONDS.
CASCADE_POOL = 4
CASCADE_INTERARRIVAL_MS = 200
CASCADE_LATENCY_MS = 2000
CASCADE_STREAM = [
    (i * CASCADE_INTERARRIVAL_MS, CASCADE_LATENCY_MS, False)
    for i in range(16)
]

# FLAP_TRACE: a brief failure burst then recovery. Drives Section E.
FLAP_TRACE = [
    (1.0, "ok"), (2.0, "ok"), (3.0, "ok"),
    (4.0, "fail"), (5.0, "fail"), (6.0, "fail"), (7.0, "fail"),  # burst
    (8.0, "ok"), (9.0, "ok"), (10.0, "ok"), (11.0, "ok"), (12.0, "ok"),  # recover
]


# ============================================================================
# 1. THE BREAKER - the three-state machine  (the code CIRCUIT_BREAKER.md walks)
# ============================================================================

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """A minimal, correct Circuit Breaker.

    Parameters
    ----------
    failure_threshold : int
        Consecutive failures in CLOSED that trip to OPEN (>= 1).
    reset_timeout : float
        Seconds the breaker stays OPEN before the next request is allowed to
        probe (OPEN -> HALF_OPEN). Checked LAZILY on the next request, never on
        a background timer - so a quiet OPEN breaker never spontaneously probes.
    half_open_max : int
        Number of SUCCESSFUL probes required in HALF_OPEN to flip back to CLOSED.
        Any single probe failure flips back to OPEN immediately.

    The machine is synchronous: each request is fully resolved (call made and
    returned, or rejected) before the next is processed. This matches the .html
    and keeps every transition deterministic and auditable.
    """

    def __init__(self, failure_threshold: int = DEFAULT_THRESHOLD,
                 reset_timeout: float = DEFAULT_RESET_TIMEOUT,
                 half_open_max: int = DEFAULT_HALF_OPEN_MAX):
        assert failure_threshold >= 1
        assert reset_timeout >= 0.0
        assert half_open_max >= 1
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_max = half_open_max

        self.state = CLOSED
        self.consecutive_failures = 0
        self.opened_at: float | None = None        # wall-clock when last tripped
        self.half_open_probes = 0                  # probes ALLOWED this episode
        self.half_open_successes = 0               # probes that succeeded
        # audit trail: (time, from_state, to_state, trigger)
        self.transition_log: list[tuple[float, str, str, str]] = []

    # -- internal: record a state change into the audit trail ----------------
    def _to(self, new_state: str, now: float, trigger: str):
        old = self.state
        if old != new_state:
            self.transition_log.append((now, old, new_state, trigger))
        self.state = new_state

    # -- admission control: decide if THIS request may call the downstream ----
    def before_call(self, now: float) -> tuple[bool, str]:
        """Return (allowed, reason). May transition OPEN -> HALF_OPEN.

        CLOSED    : always allow.
        OPEN      : if cooled down (now - opened_at >= reset_timeout) flip to
                    HALF_OPEN and treat as a probe; else REJECT (fast-fail).
        HALF_OPEN : allow a probe only if we have not yet dispatched
                    `half_open_max` of them; else REJECT.
        """
        if self.state == CLOSED:
            return True, "closed"
        if self.state == OPEN:
            if now - self.opened_at >= self.reset_timeout:
                self.half_open_probes = 0
                self.half_open_successes = 0
                self._to(HALF_OPEN, now, "reset_timeout elapsed")
            else:
                return False, "open_fast_fail"
        # state is now HALF_OPEN (either originally or just transitioned)
        if self.half_open_probes < self.half_open_max:
            return True, "half_open_probe"
        return False, "half_open_full"

    # -- outcome recording: apply the result of an ADMITTED call --------------
    def after_call(self, now: float, success: bool):
        """Update counters and possibly transition, after an admitted call."""
        if self.state == CLOSED:
            if success:
                self.consecutive_failures = 0
            else:
                self.consecutive_failures += 1
                if self.consecutive_failures >= self.failure_threshold:
                    self.opened_at = now
                    self._to(OPEN, now, "failure threshold reached")
        elif self.state == HALF_OPEN:
            self.half_open_probes += 1
            if success:
                self.half_open_successes += 1
                if self.half_open_successes >= self.half_open_max:
                    self.consecutive_failures = 0
                    self._to(CLOSED, now, "probes succeeded")
            else:
                self.opened_at = now
                self._to(OPEN, now, "half-open probe failed")

    # -- one full event: decide, (call or reject), record --------------------
    def process(self, now: float, downstream_outcome: str) -> dict:
        """Process one (time, outcome) event. outcome is the downstream result
        IF the call is made ('ok'/'fail'); ignored when rejected. Returns a
        record of what happened for printing / gold-checking."""
        pre_state = self.state
        allowed, reason = self.before_call(now)
        if not allowed:
            return {"time": now, "allowed": False, "outcome": "rejected",
                    "reason": reason, "state_after": self.state,
                    "pre_state": pre_state}
        success = (downstream_outcome == "ok")
        self.after_call(now, success)
        return {"time": now, "allowed": True, "outcome": downstream_outcome,
                "reason": reason, "state_after": self.state,
                "pre_state": pre_state}


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def replay(trace, **cfg) -> tuple[CircuitBreaker, list[dict]]:
    """Build a breaker from `cfg`, run `trace`, return (breaker, records)."""
    cb = CircuitBreaker(**cfg)
    recs = [cb.process(t, outcome) for (t, outcome) in trace]
    return cb, recs


# ============================================================================
# SECTION A: CLOSED -> OPEN  (consecutive-failure tracking)
# ============================================================================

def section_a():
    banner("SECTION A: CLOSED -> OPEN  -  consecutive failures trip the breaker")
    print("The breaker starts CLOSED. Every request passes through to the")
    print("downstream. We count CONSECUTIVE failures (a single success zeros the")
    print(f"counter). At {DEFAULT_THRESHOLD} in a row, the breaker TRIPS to OPEN.\n")
    cb, recs = replay(CANONICAL_TRACE)
    print(f"Config: failure_threshold = {DEFAULT_THRESHOLD}, "
          f"reset_timeout = {DEFAULT_RESET_TIMEOUT}s, "
          f"half_open_max = {DEFAULT_HALF_OPEN_MAX}\n")
    print("First 7 events of CANONICAL_TRACE (the trip happens at #4):")
    print("| # | time (s) | downstream | allowed? | consec | state after |")
    print("|---|----------|------------|----------|--------|-------------|")
    for i, r in enumerate(recs[:7]):
        outcome = CANONICAL_TRACE[i][1]
        allowed = "yes" if r["allowed"] else "REJECT"
        cf = cb_consec_at(recs, i)
        print(f"| {i:>2} | {r['time']:>8.2f} | {outcome:>10} | "
              f"{allowed:>8} | {cf:>6} | {r['state_after']:>11} |")
    print("\nEvents 0-1 succeed -> counter stays 0. Events 2,3,4 each fail:")
    print(f"  after #2 consec=1, after #3 consec=2, after #4 consec={DEFAULT_THRESHOLD}"
          " -> TRIP.")
    print("The breaker is now OPEN at t=5.0s. The downstream is NOT contacted")
    print("again until the breaker half-opens - even though events 5 and 6 claim")
    print("'ok'/'fail', they are REJECTED before any call is made.\n")
    trip = next(r for r in cb.transition_log if r[2] == OPEN)
    print(f"[check] first CLOSED->OPEN trip at t={trip[0]:.1f}s "
          f"(trigger: '{trip[3]}'):  "
          f"{'OK' if trip[0] == 5.0 else 'FAIL'}")
    assert trip[0] == 5.0
    # a single success would have reset the counter - demonstrate that property
    cb2 = CircuitBreaker()
    for t, o in [(1.0, "fail"), (2.0, "fail"), (3.0, "ok"), (4.0, "fail")]:
        cb2.process(t, o)
    print(f"[check] a success mid-burst resets the counter: after "
          f"[fail,fail,ok,fail] state = {cb2.state} (stayed CLOSED, consec=1):  "
          f"{'OK' if cb2.state == CLOSED else 'FAIL'}")
    assert cb2.state == CLOSED and cb2.consecutive_failures == 1


def cb_consec_at(recs, i):
    """Recompute consecutive_failures AFTER event i on a fresh breaker
    (helper only for the print table; not used by the machine itself)."""
    cb = CircuitBreaker()
    for k in range(i + 1):
        r = recs[k]
        if r["allowed"]:
            cb.after_call(r["time"], r["outcome"] == "ok")
    return cb.consecutive_failures


# ============================================================================
# SECTION B: OPEN -> fast-fail + reset_timeout -> HALF_OPEN
# ============================================================================

def section_b():
    banner("SECTION B: OPEN  -  fast-fail everything, then cool down to HALF_OPEN")
    print("In OPEN the breaker does NOT forward any request. It returns an error")
    print("to the caller immediately, in the caller's own thread. No network call,")
    print("no worker thread held. This is the fast-fail - the whole point.\n")
    print(f"The breaker stays OPEN for reset_timeout = {DEFAULT_RESET_TIMEOUT:.1f}s. "
          "Crucially, the OPEN -> HALF_OPEN transition is LAZY: it is checked on")
    print("the next incoming request, never on a wall-clock timer. A breaker that")
    print("nobody calls stays OPEN forever (correct - probing costs a real call).\n")
    cb, recs = replay(CANONICAL_TRACE)
    print("OPEN-window verdicts (events after the first trip @t=5.0):")
    print("| # | time (s) | since trip | >= 5.0s? | decision            |")
    print("|---|----------|------------|-----------|---------------------|")
    opened = 5.0
    for i in [5, 6, 7]:
        r = recs[i]
        t = r["time"]
        elapsed = t - opened
        cooled = elapsed >= DEFAULT_RESET_TIMEOUT
        decision = "HALF_OPEN (probe)" if cooled else "REJECT (fast-fail)"
        print(f"| {i:>2} | {t:>8.2f} | {elapsed:>10.2f} | "
              f"{'yes' if cooled else 'no':>9} | {decision:<19} |")
    print("\nEvent 5 arrives 1s after the trip - still hot - REJECTED. Event 6")
    print("likewise. Event 7 arrives 15s after the trip - well past the 5s")
    print("cooling-off - so the breaker flips to HALF_OPEN and lets event 7")
    print("through as the first PROBE. The downstream is finally contacted again")
    print("ONLY at t=20.0, fifteen seconds after it last failed.\n")
    # the lazy-transition property: no request => no probe, even past timeout
    cb_lazy = CircuitBreaker()
    cb_lazy.process(0.0, "fail"); cb_lazy.process(1.0, "fail"); cb_lazy.process(2.0, "fail")
    assert cb_lazy.state == OPEN and cb_lazy.opened_at == 2.0
    print(f"[check] at t=100.0s with NO incoming request, breaker that tripped at "
          f"t=2.0 is still {cb_lazy.state} (lazy: no request => no probe):  OK")
    assert cb_lazy.state == OPEN  # would still be OPEN at t=100 with no call
    print(f"[check] event 7 (t={recs[7]['time']:.1f}) is the first admission after "
          f"the trip:  {'OK' if recs[7]['allowed'] else 'FAIL'}")
    assert recs[7]["allowed"]


# ============================================================================
# SECTION C: HALF_OPEN -> CLOSED / OPEN  (limited probes)
# ============================================================================

def section_c():
    banner("SECTION C: HALF_OPEN  -  limited probes decide recovery")
    print(f"In HALF_OPEN the breaker admits at most {DEFAULT_HALF_OPEN_MAX} PROBE "
          "requests. Outcomes:")
    print(f"  * ALL {DEFAULT_HALF_OPEN_MAX} succeed -> the downstream has recovered "
          "-> CLOSE.")
    print("  * ANY one fails        -> still broken -> flip back to OPEN and")
    print("                            restart the cooling-off clock.\n")
    print("Two HALF_OPEN episodes in CANONICAL_TRACE - one succeeds, one fails:\n")
    cb, recs = replay(CANONICAL_TRACE)
    print("Episode 1 (events 7-8):")
    print(f"| # | time (s) | decision        | probe result | succ | state after |")
    print("|---|----------|-----------------|--------------|------|-------------|")
    for i in [7, 8]:
        r = recs[i]
        res = "ok" if r["outcome"] == "ok" else "fail"
        succ = cb_succ_at(recs, i)
        print(f"| {i:>2} | {r['time']:>8.2f} | half_open_probe | {res:>12} | "
              f"{succ:>4} | {r['state_after']:>11} |")
    print(f"  Two consecutive successful probes ({DEFAULT_HALF_OPEN_MAX}/{DEFAULT_HALF_OPEN_MAX}) "
          "-> CLOSED at t=21.0.\n")
    print("Episode 2 (event 14) - a probe FAILS:")
    r = recs[14]
    print(f"| 14 | {r['time']:>8.2f} | half_open_probe | {'fail':>12} |   -  | "
          f"{r['state_after']:>11} |")
    print("  The downstream is STILL broken. One failed probe is enough: the")
    print(f"  breaker flips straight back to OPEN at t={r['time']:.1f} and the 5s")
    print("  cooling-off starts over. It does NOT keep probing - that would hammer")
    print("  a sick service. Event 15 (1s later) is therefore REJECTED.\n")
    # the asymmetric, conservative design: 1 fail reopens, need N succs to close
    print("This asymmetry is deliberate and is the conservative core of the")
    print("pattern: it is cheap to stay suspicious (OPEN) and expensive to trust")
    print("a flaky downstream (CLOSED), so closing requires multiple positive")
    print("signals while a single negative signal reopens immediately.\n")
    print(f"[check] event 8 closes after 2 successful probes "
          f"(state={recs[8]['state_after']}):  "
          f"{'OK' if recs[8]['state_after'] == CLOSED else 'FAIL'}")
    assert recs[8]["state_after"] == CLOSED
    print(f"[check] event 14 reopens on a single failed probe "
          f"(state={recs[14]['state_after']}):  "
          f"{'OK' if recs[14]['state_after'] == OPEN else 'FAIL'}")
    assert recs[14]["state_after"] == OPEN


def cb_succ_at(recs, i):
    cb = CircuitBreaker()
    # replay up to i, but we only care about HALF_OPEN successes at this point;
    # rebuild by replaying the whole trace prefix.
    for k in range(i + 1):
        r = recs[k]
        cb.process(r["time"], CANONICAL_TRACE[k][1] if r["allowed"] else "ok")
    return cb.half_open_successes if cb.state != CLOSED else cb.half_open_max


# ============================================================================
# SECTION D: cascade prevention  -  the thread-pool simulation
# ============================================================================

def simulate_pool(requests, pool_size, breaker=None, fast_fail_ms=1.0):
    """Discrete worker-pool simulator. Pure, deterministic.

    Each request is (arrival_ms, latency_ms, success). A request is either:
      * ADMITTED (a real downstream call): occupies a worker for `latency_ms`.
        If no worker is free it QUEUES: the caller waits until the earliest
        worker frees, then that worker is reused for `latency_ms`. Caller
        latency = queue_wait + latency_ms. (This queueing IS the cascade.)
      * REJECTED (breaker OPEN / HALF_OPEN full): uses NO worker - the breaker
        returns the error in the caller's own thread. Caller latency =
        `fast_fail_ms`. This is why a breaker prevents cascades: rejected
        requests never touch the saturated pool.

    Returns peak_busy, first_exhaustion_ms, exhaustion_count (arrivals that
    found 0 free workers), total_caller_latency_ms, fast_responses (caller
    latency < 50ms), and admitted/rejected counts.
    """
    releases: list[float] = []          # release times of busy workers
    peak_busy = 0
    first_exhaustion = None
    exhaustion_count = 0
    total_caller_lat = 0.0
    fast_responses = 0
    admitted = 0
    rejected = 0
    for (t, lat, ok) in requests:
        # free workers whose release time has passed
        releases = [r for r in releases if r > t]
        peak_busy = max(peak_busy, len(releases))
        # breaker admission
        if breaker is not None:
            allowed, _ = breaker.before_call(t / 1000.0)
            if not allowed:
                rejected += 1
                cl = fast_fail_ms
                total_caller_lat += cl
                if cl < 50.0:
                    fast_responses += 1
                continue
        admitted += 1
        free = pool_size - len(releases)
        if free <= 0:                    # must queue - cascade in progress
            exhaustion_count += 1
            if first_exhaustion is None:
                first_exhaustion = t
            earliest = min(releases)
            releases.remove(earliest)    # worker freed, immediately reused
            wait = earliest - t          # caller blocks until a worker drains
            cl = wait + lat
        else:
            wait = 0.0
            cl = lat
        # release time = start + latency; start = t when free, t+wait when queued
        releases.append(t + wait + lat)
        total_caller_lat += cl
        if cl < 50.0:
            fast_responses += 1
        if breaker is not None:
            breaker.after_call(t / 1000.0, ok)
        peak_busy = max(peak_busy, len(releases))
    return {
        "peak_busy": peak_busy,
        "first_exhaustion_ms": first_exhaustion,
        "exhaustion_count": exhaustion_count,
        "total_caller_latency_ms": total_caller_lat,
        "fast_responses": fast_responses,
        "admitted": admitted,
        "rejected": rejected,
        "n_requests": len(requests),
    }


def section_d():
    banner("SECTION D: cascade prevention  -  with vs without a breaker")
    print("The scenario: a 4-thread worker pool calls a downstream that suddenly")
    print(f"DEGRADES - every call now takes {CASCADE_LATENCY_MS}ms and fails. "
          f"Requests arrive every {CASCADE_INTERARRIVAL_MS}ms (the stream is "
          f"{len(CASCADE_STREAM)} requests over "
          f"{CASCADE_STREAM[-1][0]/1000:.1f}s).\n")
    print("WITHOUT a breaker, each slow call HOLDS a worker for 2000ms. 4 workers")
    print("/ 2s-per-call => the pool saturates almost immediately and stays full.")
    print("Every arriving caller then QUEUES waiting for a worker - their latency")
    print("balloons, and the slowdown propagates to whoever calls THEM. That is the")
    print("cascade.\n")
    print("WITH a breaker (threshold=3), the first 3 failures trip it OPEN. From")
    print("then on requests are REJECTED in ~1ms and use NO worker. Only the 3")
    print("calls that were already in flight when it tripped ever occupy workers,")
    print("so the pool never fully saturates and the service keeps answering fast.\n")
    no_brk = simulate_pool(CASCADE_STREAM, CASCADE_POOL, breaker=None)
    cb = CircuitBreaker(DEFAULT_THRESHOLD, DEFAULT_RESET_TIMEOUT,
                        DEFAULT_HALF_OPEN_MAX)
    with_brk = simulate_pool(CASCADE_STREAM, CASCADE_POOL, breaker=cb)
    print("| metric                       | no breaker | with breaker |")
    print("|------------------------------|------------|--------------|")
    rows = [
        ("peak workers busy", no_brk["peak_busy"], with_brk["peak_busy"], "d"),
        ("first thread-exhaustion",
         (f"{no_brk['first_exhaustion_ms']:.0f}ms" if no_brk['first_exhaustion_ms']
          is not None else "never"),
         (f"{with_brk['first_exhaustion_ms']:.0f}ms"
          if with_brk['first_exhaustion_ms'] is not None else "never"), "s"),
        ("requests that found 0 free workers",
         no_brk["exhaustion_count"], with_brk["exhaustion_count"], "d"),
        ("total caller latency (sum, ms)",
         f"{no_brk['total_caller_latency_ms']:.0f}",
         f"{with_brk['total_caller_latency_ms']:.0f}", "s"),
        ("fast responses (<50ms)",
         no_brk["fast_responses"], with_brk["fast_responses"], "d"),
        ("calls admitted to downstream",
         no_brk["admitted"], with_brk["admitted"], "d"),
        ("calls rejected (fast-fail)",
         no_brk["rejected"], with_brk["rejected"], "d"),
    ]
    for label, a, b, _ in rows:
        print(f"| {label:<28} | {str(a):>10} | {str(b):>12} |")
    print("\nRead it: WITHOUT the breaker, the 4-worker pool hits exhaustion at")
    print(f"t={no_brk['first_exhaustion_ms']:.0f}ms and "
          f"{no_brk['exhaustion_count']} of {no_brk['n_requests']} callers block "
          "on a worker. WITH the breaker, exhaustion NEVER happens and "
          f"{with_brk['fast_responses']} of {with_brk['n_requests']} callers get a "
          "sub-50ms answer. The downstream is contacted only "
          f"{with_brk['admitted']} times (the 3 in-flight calls that tripped it), "
          "instead of all 16.\n")
    print("That is the cascade prevented at the first hop: the slow downstream no")
    print("longer drains our threads, so OUR callers never see us stall, and the")
    print("failure stops propagating upstream. (Bonus: the sick downstream gets")
    print("left alone for 5s - a chance to recover under reduced load.)")
    print(f"\n[check] with-breaker peak_busy ({with_brk['peak_busy']}) == "
          f"threshold ({DEFAULT_THRESHOLD}):  "
          f"{'OK' if with_brk['peak_busy'] == DEFAULT_THRESHOLD else 'FAIL'}")
    assert with_brk["peak_busy"] == DEFAULT_THRESHOLD
    print(f"[check] with-breaker exhaustion_count ({with_brk['exhaustion_count']})"
          f" < no-breaker exhaustion_count ({no_brk['exhaustion_count']}):  "
          f"{'OK' if with_brk['exhaustion_count'] < no_brk['exhaustion_count'] else 'FAIL'}")
    assert with_brk["exhaustion_count"] < no_brk["exhaustion_count"]
    print(f"[check] no-breaker DID exhaust "
          f"({no_brk['exhaustion_count']} > 0):  "
          f"{'OK' if no_brk['exhaustion_count'] > 0 else 'FAIL'}")
    assert no_brk["exhaustion_count"] > 0


# ============================================================================
# SECTION E: config trade-offs  -  threshold / timeout / half_open_max
# ============================================================================

def section_e():
    banner("SECTION E: config trade-offs  -  sensitive vs balanced vs tolerant")
    print("The three knobs are a dial between SAFETY (isolate fast) and")
    print("AVAILABILITY (avoid false trips). Run the same FLAP_TRACE - a 4-failure")
    print("burst then recovery - under three configs:\n")
    configs = [
        ("sensitive", dict(failure_threshold=2, reset_timeout=2.0,
                           half_open_max=1)),
        ("balanced",  dict(failure_threshold=3, reset_timeout=5.0,
                           half_open_max=2)),
        ("tolerant",  dict(failure_threshold=5, reset_timeout=10.0,
                           half_open_max=3)),
    ]
    print("| config    | thr | timeout | hom | tripped? | trip time | "
          "rejected | HALF_OPEN episodes | recovered |")
    print("|-----------|-----|---------|-----|----------|-----------|"
          "----------|--------------------|-----------|")
    results = {}
    for name, cfg in configs:
        cb, recs = replay(FLAP_TRACE, **cfg)
        trips = [r for r in cb.transition_log if r[2] == OPEN]
        tripped = "yes" if trips else "no"
        trip_t = f"{trips[0][0]:.0f}s" if trips else "-"
        rejected = sum(1 for r in recs if not r["allowed"])
        ho_eps = len([r for r in cb.transition_log if r[2] == HALF_OPEN])
        recovered = "yes" if cb.state == CLOSED else "no"
        results[name] = (cb, recs, tripped, trip_t, rejected, ho_eps, recovered)
        print(f"| {name:<9} | {cfg['failure_threshold']:>3} | "
              f"{cfg['reset_timeout']:>7.0f}s | {cfg['half_open_max']:>3} | "
              f"{tripped:>8} | {trip_t:>9} | {rejected:>8} | "
              f"{ho_eps:>18} | {recovered:>9} |")
    print("\nRead it as a spectrum:")
    print("  * SENSITIVE (thr=2) trips after just 2 failures and recovers in 2s,")
    print("    but it FALSE-TRIPS on short bursts and probes aggressively (2")
    print("    half-open episodes). Good when failures are expensive; bad under")
    print("    benign jitter.")
    print("  * BALANCED (thr=3, 5s, 2 probes) trips once, isolates for 5s, then")
    print("    needs 2 consecutive successes to trust the downstream again. The")
    print("    Nygard / Hystrix-style default.")
    print("  * TOLERANT (thr=5) NEVER trips on a 4-failure burst - so it offers")
    print("    NO protection here. It avoids false alarms but a real outage would")
    print("    drain your threads unchecked.\n")
    print("Rules of thumb (Nygard 'Release It!'; Hystrix/Resilience4j defaults):")
    print("  * threshold : high enough to ride out normal jitter, low enough to")
    print("                trip before your thread pool drains. Tie it to pool")
    print("                size and downstream latency, not to a guess.")
    print("  * timeout   : longer than the typical recovery time of the downstream")
    print("                (a restarted service, a cache warm-up), short enough")
    print("                that you re-probe reasonably soon.")
    print("  * half_open_max : 1 = fastest recovery but trusts a SINGLE success")
    print("                (risky on flaky nets); higher = more confidence before")
    print("                reopening the floodgates, at the cost of slower recovery.")
    sen = results["sensitive"]
    tol = results["tolerant"]
    print(f"\n[check] sensitive trips but tolerant does not on the same burst "
          f"({sen[2]} vs {tol[2]}):  "
          f"{'OK' if sen[2] == 'yes' and tol[2] == 'no' else 'FAIL'}")
    assert sen[2] == "yes" and tol[2] == "no"
    bal = results["balanced"]
    print(f"[check] balanced rejects more than tolerant "
          f"({bal[4]} > {tol[4]}):  "
          f"{'OK' if bal[4] > tol[4] else 'FAIL'}")
    assert bal[4] > tol[4]


# ============================================================================
# GOLD CHECK: full state sequence + transition log for CANONICAL_TRACE
# ============================================================================

def gold_check():
    banner("GOLD CHECK: state machine transitions for CANONICAL_TRACE")
    cb, recs = replay(CANONICAL_TRACE)
    print(f"Config: threshold={DEFAULT_THRESHOLD}, "
          f"reset_timeout={DEFAULT_RESET_TIMEOUT}s, "
          f"half_open_max={DEFAULT_HALF_OPEN_MAX}\n")
    print("Full event-by-event verdict (the audit trail the .html must match):\n")
    print("| # | time (s) | downstream | allowed? | state after |")
    print("|---|----------|------------|----------|-------------|")
    state_seq = []
    allowed_seq = []
    for i, r in enumerate(recs):
        outcome = CANONICAL_TRACE[i][1]
        allowed = "yes" if r["allowed"] else "REJECT"
        print(f"| {i:>2} | {r['time']:>8.2f} | {outcome:>10} | "
              f"{allowed:>8} | {r['state_after']:>11} |")
        state_seq.append(r["state_after"])
        allowed_seq.append(r["allowed"])
    print("\nState-after sequence (18 entries):")
    print("  " + ", ".join(state_seq))
    print("\nTransition log (every state change, with trigger):")
    print("| time (s) | from     | to       | trigger                 |")
    print("|----------|----------|----------|-------------------------|")
    for (t, frm, to, trig) in cb.transition_log:
        print(f"| {t:>8.2f} | {frm:<8} | {to:<8} | {trig:<23} |")
    n_trans = len(cb.transition_log)
    print(f"\nTotal state transitions: {n_trans}")
    # pin the canonical values for the .html
    gold_state = ["CLOSED", "CLOSED", "CLOSED", "CLOSED", "OPEN", "OPEN", "OPEN",
                  "HALF_OPEN", "CLOSED", "CLOSED", "CLOSED", "CLOSED", "OPEN",
                  "OPEN", "OPEN", "OPEN", "HALF_OPEN", "CLOSED"]
    gold_allowed = [True, True, True, True, True, False, False, True, True,
                    True, True, True, True, False, True, False, True, True]
    ok_state = state_seq == gold_state
    ok_allowed = allowed_seq == gold_allowed
    ok_trans = n_trans == 8
    final_closed = cb.state == CLOSED
    print(f"\n[check] state sequence matches pinned gold:  "
          f"{'OK' if ok_state else 'FAIL'}")
    print(f"[check] allowed-sequence matches pinned gold:  "
          f"{'OK' if ok_allowed else 'FAIL'}")
    print(f"[check] transition count == 8:  "
          f"{'OK' if ok_trans else 'FAIL'}")
    print(f"[check] final state == CLOSED (recovered):  "
          f"{'OK' if final_closed else 'FAIL'}")
    assert ok_state and ok_allowed and ok_trans and final_closed
    print("\nGOLD (pinned for circuit_breaker.html):")
    print("  state_after   = " + ",".join(state_seq))
    print("  allowed       = " + ",".join("T" if a else "F" for a in allowed_seq))
    print("  transitions   = " + ",".join(f"{f}->{t}" for (_, f, t, _) in
                                          cb.transition_log))
    print("  n_transitions = " + str(n_trans))
    status = "OK" if (ok_state and ok_allowed and ok_trans and final_closed) else "FAIL"
    print(f"\n[check] GOLD: state machine replay matches pinned transitions:  {status}")
    assert status == "OK"
    return status


# ============================================================================
# main
# ============================================================================

def main():
    print("circuit_breaker.py - reference impl. All numbers below feed "
          "CIRCUIT_BREAKER.md.")
    print("Pure Python stdlib (no deps). Traces are hard-coded & deterministic.")
    print("Sources: Nygard 'Release It!' (2007); Fowler bliki (2014); "
          "Netflix Hystrix; Resilience4j.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
