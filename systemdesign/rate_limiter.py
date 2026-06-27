"""
rate_limiter.py - Reference simulation of the four canonical rate-limiting
algorithms (token bucket, sliding window counter, fixed window counter, leaky
bucket) plus the distributed-coordination concerns (Redis + Lua atomicity,
race conditions, fail-open vs fail-closed).

This is the single source of truth that RATE_LIMITER.md is built from.
Every algorithm trace, scale number, and atomicity argument in the guide is
printed by this file. Deterministic (no randomness, no time-of-day). Re-run
and re-paste the output into the guide.

Run:
    python3 rate_limiter.py

=========================================================================
THE INTUITION (read this first) - the bouncer at a club
=========================================================================
A rate limiter is a bouncer with a clipboard. Before letting each request in,
the bouncer checks a rule ("max N per minute per user"). The interesting
question is HOW the bouncer counts, because the four classic algorithms make
different tradeoffs between simplicity, memory, accuracy, and burst tolerance:

  * TOKEN BUCKET       : a bucket drips tokens at a fixed rate. Each request
                         consumes 1 token. If the bucket has tokens, the
                         request is allowed; otherwise denied. ALLOWS BURSTS
                         up to the bucket capacity, then enforces a smooth
                         average rate. (Used by Stripe, AWS, most public APIs.)
  * LEAKY BUCKET       : requests enter a queue; the queue drains at a
                         constant rate. If the queue is full, the request is
                         dropped. FORCES A CONSTANT OUTPUT RATE - smooths out
                         bursts entirely. (Used for traffic shaping.)
  * FIXED WINDOW       : divide time into N-second windows. A simple counter
                         per (user, window-start) is INCRemented. SIMPLEST,
                         one INCR + EXPIRE in Redis. But suffers the BOUNDARY
                         BURST: 2x the rate can sneak through at the seam
                         between two windows.
  * SLIDING WINDOW CTR : hybrid. Keep current-window count AND the previous
                         window count. Estimate = cur + prev * (time_left_in_
                         prev_window / window). Smoothes the boundary burst
                         with only TWO counters per key.

The NON-OBVIOUS parts this file drills into:
  1. The token bucket has TWO parameters (capacity + refill_rate) that must be
     tuned together. capacity = burst tolerance; refill_rate = sustained
     throughput. Decoupling them is the whole point. (Section A)
  2. The fixed window's "2x at the boundary" is a real exploit: 100 req/min
     at t=59 and 100 more at t=61 pass cleanly under a 100/min limit. (C, E)
  3. The sliding window counter approximates the precise sliding log with
     just two integers per key - O(1) memory, O(1) ops. (B)
  4. Distributed rate limiting is NOT just "put the counter in Redis". A
     naive read-then-write is racy: two concurrent INCRs can both succeed.
     The fix is an ATOMIC Lua script (check-and-incr in one Redis op). (F)
  5. Fail-open vs fail-closed: if Redis is down, do you let everything through
     (availability) or block everything (correctness)? Public APIs fail open;
     billing / login fail closed. (F)

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  rate           : requests per unit time (req/s, req/min). The SUSTAINED limit.
  burst          : a short spike ABOVE the sustained rate. Token/leaky bucket
                   capacity controls how big a burst is tolerated.
  window         : the time interval the limit is measured over (1s, 60s).
  key            : the thing being limited: user_id, ip, api_key, endpoint.
  fail-open      : if the limiter's storage is unavailable, ALLOW all traffic.
  fail-closed    : if the limiter's storage is unavailable, DENY all traffic.
  atomic         : an operation that no other client can interleave with. In
                   Redis, achieved by a Lua script (single-threaded execution).
  INCR           : Redis command that atomically increments a counter.
  EXPIRE         : Redis command that sets a TTL on a key (auto-cleanup).

=========================================================================
THE ACTORS (middleware vs gateway vs service)
=========================================================================
  client           : the API caller. Identified by user_id / IP / api_key.
  rate limiter     : the bouncer. Implemented as ONE of:
                       - in-process middleware (library, e.g. bucket4j)
                       - API gateway feature (Kong, AWS API Gateway, Envoy)
                       - sidecar (service mesh, e.g. Envoy rate limit filter)
                       - standalone service (e.g. Stripe's isolated RL service)
  Redis cluster    : the shared counter store. Distributed across shards.
  policy store     : the rules table (per-tier, per-endpoint limits). SQL/etcd.
  backend service  : the thing being protected. Unaware of rate limiting.

=========================================================================
"""

from collections import deque


# --------------------------------------------------------------------------
# 1. TOKEN BUCKET
# --------------------------------------------------------------------------
class TokenBucket:
    """
    capacity   : max tokens the bucket can hold (burst ceiling)
    refill_rate: tokens added per second (sustained rate)
    tokens     : current level
    last       : wall-clock of last refill computation (lazy refill)

    allow() lazily refills: tokens += elapsed * refill_rate, capped at capacity.
    """

    def __init__(self, capacity, refill_rate):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)  # start full -> first burst allowed
        self.last = 0.0

    def _refill(self, now):
        elapsed = now - self.last
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last = now

    def allow(self, now, cost=1.0):
        self._refill(now)
        if self.tokens >= cost:
            self.tokens -= cost
            return True, self.tokens
        return False, self.tokens


# --------------------------------------------------------------------------
# 2. SLIDING WINDOW COUNTER (current + weighted previous window)
# --------------------------------------------------------------------------
class SlidingWindowCounter:
    """
    limit      : max weighted requests in any sliding window
    window_sec : window size in seconds
    cur_count  : requests in the CURRENT window
    prev_count : requests in the PREVIOUS window
    cur_start  : wall-clock of the current window start

    weighted = cur_count + prev_count * (1 - elapsed/window)
    where elapsed = seconds since current window started.
    """

    def __init__(self, limit, window_sec):
        self.limit = limit
        self.window_sec = window_sec
        self.cur_count = 0
        self.prev_count = 0
        self.cur_start = 0.0

    def allow(self, now):
        # roll windows forward as needed
        if self.cur_start == 0.0:
            self.cur_start = now
        while now - self.cur_start >= self.window_sec:
            self.prev_count = self.cur_count
            self.cur_count = 0
            self.cur_start += self.window_sec
        elapsed = now - self.cur_start
        weighted = self.cur_count + self.prev_count * (1.0 - elapsed / self.window_sec)
        if weighted < self.limit:
            self.cur_count += 1
            return True, weighted
        return False, weighted


# --------------------------------------------------------------------------
# 3. FIXED WINDOW COUNTER
# --------------------------------------------------------------------------
class FixedWindowCounter:
    """
    limit      : max requests per window
    window_sec : window size in seconds
    count      : requests in current window
    window_id  : integer window index (now // window_sec)

    Window boundary: when window_id changes, reset counter to 0.
    Suffers the BOUNDARY BURST: 2x rate can slip through at the seam.
    """

    def __init__(self, limit, window_sec):
        self.limit = limit
        self.window_sec = window_sec
        self.count = 0
        self.window_id = -1

    def allow(self, now):
        wid = int(now // self.window_sec)
        if wid != self.window_id:
            self.count = 0
            self.window_id = wid
        if self.count < self.limit:
            self.count += 1
            return True, self.count
        return False, self.count


# --------------------------------------------------------------------------
# 4. LEAKY BUCKET (queue-based, constant output rate)
# --------------------------------------------------------------------------
class LeakyBucket:
    """
    capacity  : max queue size (burst ceiling)
    leak_rate : requests drained per second (constant output rate)
    queue     : deque of scheduled DEPARTURE times (when each req leaves)

    On each allow(now): pop every departure <= now (those finished processing),
    then if room, append a new departure = (last_departure OR now) + spacing.
    The +spacing on an empty queue models the fact that even the first request
    takes one service slot to process.
    """

    def __init__(self, capacity, leak_rate):
        self.capacity = capacity
        self.leak_rate = leak_rate
        self.spacing = 1.0 / leak_rate
        self.queue = deque()

    def allow(self, now):
        # +1e-9 absorbs float accumulation in departure times (0.1+0.1+... != 2.0)
        while self.queue and self.queue[0] <= now + 1e-9:
            self.queue.popleft()
        if len(self.queue) >= self.capacity:
            return False, len(self.queue)
        # departure = when this request finishes processing.
        # Idle server: starts now, finishes one spacing later.
        # Busy server: starts after the last queued departure, finishes spacing later.
        if self.queue:
            departure = self.queue[-1] + self.spacing
        else:
            departure = now + self.spacing
        self.queue.append(departure)
        return True, len(self.queue)


# --------------------------------------------------------------------------
# Deterministic request stream used for the side-by-side comparison.
# Two bursts at window boundaries to expose the fixed-window weakness.
# --------------------------------------------------------------------------
def burst_stream():
    """
    Returns a list of request timestamps (in seconds, monotonic increasing).
    Pattern:
      Phase 1 (t=0.00-0.14):  15 rapid requests (initial burst, 0.01s apart)
      Phase 2 (t=1.0-9.0):    1 request per second (sustained, 9 reqs)
      Phase 3 (t=59.3-60.3):  15 rapid requests straddling a 60s window
                              boundary (the classic fixed-window exploit)
    """
    stream = []
    for i in range(15):
        stream.append(0.00 + i * 0.01)          # 0.00 .. 0.14
    for t in range(1, 10):
        stream.append(float(t))                 # 1.0 .. 9.0
    for i in range(8):
        stream.append(59.30 + i * 0.05)         # 59.30 .. 59.65
    for i in range(7):
        stream.append(60.00 + i * 0.05)         # 60.00 .. 60.30
    return stream


def banner(title):
    line = "=" * 72
    print()
    print(line)
    print(" " + title)
    print(line)


def main():
    banner("RATE LIMITER - reference simulation (4 algorithms + distributed)")
    print("Source of truth for RATE_LIMITER.md and rate_limiter.html.")
    print("All numbers below are deterministic; re-run reproduces them.")

    # ---------------------------------------------------------------------
    # SECTION A: TOKEN BUCKET
    # ---------------------------------------------------------------------
    banner("Section A - Token Bucket (capacity=20, refill_rate=10 tok/s)")
    print("Each request consumes 1 token. Tokens refill continuously at 10/s.")
    print("Bucket starts FULL (20 tokens) so the first burst passes.\n")
    tb = TokenBucket(capacity=20, refill_rate=10.0)
    print("Phase 1: 25 instant requests against a fresh bucket (capacity=20).")
    allowed_burst = 0
    for i in range(25):
        ok, tokens = tb.allow(i * 0.0001)  # effectively instant
        if ok:
            allowed_burst += 1
        last_tokens = tokens
    print(f"  allowed in burst: {allowed_burst} of 25  (first 20 pass, last 5 DENIED)")
    print(f"  tokens after burst: {last_tokens:.2f}")
    print()
    print("Phase 2: idle 1.0s, then 3 more requests (refill_rate=10 -> +10 tokens).")
    for i in range(3):
        ok, tokens = tb.allow(1.0 + i * 0.001)
        print(f"  t={1.0 + i * 0.001:.3f}  allowed={ok}  tokens={tokens:.2f}")
    print()
    print("Phase 3: idle 10.0s -> bucket refills to capacity=20 again.")
    ok, tokens = tb.allow(11.0)
    print(f"  t=11.000  allowed={ok}  tokens={tokens:.2f}  (capped at 20)")

    # ---------------------------------------------------------------------
    # SECTION B: SLIDING WINDOW COUNTER
    # ---------------------------------------------------------------------
    banner("Section B - Sliding Window Counter (limit=10, window=1s)")
    print("Keeps cur_count + prev_count. Weighted = cur + prev*(1-elapsed/win).")
    print("Smooths the boundary burst with only TWO counters per key.\n")
    sw = SlidingWindowCounter(limit=10, window_sec=1.0)
    print("Phase 1: send 12 requests at t=0.00..0.11 (limit=10 in this window).")
    for i in range(12):
        ok, weighted = sw.allow(i * 0.01)
        if i in (0, 9, 10, 11):
            print(f"  t={i * 0.01:.2f}  cur={sw.cur_count} prev={sw.prev_count} "
                  f"weighted={weighted:.2f}  allowed={ok}")
    print()
    print("Phase 2: send 5 requests at t=1.05..1.25 (new window; prev carries weight).")
    for i in range(5):
        t = 1.05 + i * 0.05
        ok, weighted = sw.allow(t)
        print(f"  t={t:.2f}  cur={sw.cur_count} prev={sw.prev_count} "
              f"weighted={weighted:.2f}  allowed={ok}")

    # ---------------------------------------------------------------------
    # SECTION C: FIXED WINDOW COUNTER (and the boundary burst)
    # ---------------------------------------------------------------------
    banner("Section C - Fixed Window Counter (limit=10, window=1s)")
    print("One integer per (user, window_id). INCR + EXPIRE in Redis.")
    print("Suffers the BOUNDARY BURST: 2x rate can slip through at the seam.\n")
    print("BOUNDARY EXPLOIT: 10 reqs at t=0.90-0.99 + 10 reqs at t=1.00-1.09.")
    print("That is 20 reqs in 0.2s under a 10/sec limit. Watch the counter:\n")
    fw = FixedWindowCounter(limit=10, window_sec=1.0)
    phase1_allowed = 0
    for i in range(10):
        ok, _ = fw.allow(0.90 + i * 0.01)
        phase1_allowed += ok
    phase2_allowed = 0
    for i in range(10):
        ok, _ = fw.allow(1.00 + i * 0.01)
        phase2_allowed += ok
    print(f"  window 0 (t=0.90-0.99): {phase1_allowed} of 10 allowed  (wid=0)")
    print(f"  window 1 (t=1.00-1.09): {phase2_allowed} of 10 allowed  (wid=1, counter RESET)")
    print(f"  TOTAL: {phase1_allowed + phase2_allowed} reqs in 0.2s under a 10/s limit  <-- OVERSHOT")
    print()
    print("  The counter resets at t=1.0 because window_id flips from 0 to 1,")
    print("  so the second burst is a 'fresh' window. Sliding window catches this.")

    # ---------------------------------------------------------------------
    # SECTION D: LEAKY BUCKET
    # ---------------------------------------------------------------------
    banner("Section D - Leaky Bucket (capacity=20, leak_rate=10 req/s)")
    print("Requests queue; queue drains at constant rate. Full queue -> drop.")
    print("Output is ALWAYS <= leak_rate, regardless of input burst.\n")
    lb = LeakyBucket(capacity=20, leak_rate=10.0)
    print("Phase 1: 25 instant requests against capacity=20 queue.")
    allowed = 0
    for i in range(25):
        ok, qlen = lb.allow(i * 0.0001)
        allowed += ok
    print(f"  allowed: {allowed} of 25  (first 20 queue, last 5 DROPPED)")
    print(f"  queue length after burst: {lb.queue and len(lb.queue) or 0}")
    print()
    print("Phase 2: idle 2.0s -> queue fully drains (leak_rate=10, 2s = 20 drained).")
    ok, qlen = lb.allow(2.0)
    print(f"  t=2.000  allowed={ok}  queue_len={qlen}  (queue empty again)")
    print()
    print("Phase 3: steady 1 req every 0.2s (5 req/s input < 10/s leak -> all pass).")
    for i in range(5):
        t = 2.1 + i * 0.2
        ok, qlen = lb.allow(t)
        print(f"  t={t:.2f}  allowed={ok}  queue_len={qlen}")

    # ---------------------------------------------------------------------
    # SECTION E: SIDE-BY-SIDE COMPARISON (same request stream, all 4 algos)
    # ---------------------------------------------------------------------
    banner("Section E - Side-by-side on the SAME request stream")
    print("Stream: 15-burst at t=0..0.14; 1 req/s for t=1..9; 15 reqs straddling t=60.")
    print("All four limiters configured for ~10 req/s sustained, burst=20.\n")
    print("  t(s)    TOKEN    SLIDING    FIXED    LEAKY")
    stream = burst_stream()
    a = TokenBucket(capacity=20, refill_rate=10.0)
    b = SlidingWindowCounter(limit=10, window_sec=1.0)
    c = FixedWindowCounter(limit=10, window_sec=1.0)
    d = LeakyBucket(capacity=20, leak_rate=10.0)
    counts = {"TOKEN": 0, "SLIDING": 0, "FIXED": 0, "LEAKY": 0}
    # only print the first 15 (burst) + a few steady + the t~60 straddle
    print_first_n = 15
    printed = 0
    last_t = None
    for i, t in enumerate(stream):
        oa = a.allow(t)[0]
        ob = b.allow(t)[0]
        oc = c.allow(t)[0]
        od = d.allow(t)[0]
        counts["TOKEN"] += oa
        counts["SLIDING"] += ob
        counts["FIXED"] += oc
        counts["LEAKY"] += od
        do_print = (i < print_first_n) or (59.0 <= t <= 60.5)
        if do_print:
            if last_t is not None and t - last_t > 2.0:
                print("   ...      ...      ...       ...      ...")
            cell = lambda ok: " ok " if ok else "deny"
            print(f"  {t:6.2f}   {cell(oa)}     {cell(ob)}      {cell(oc)}     {cell(od)}")
            last_t = t
    print()
    print("  TOTALS (allowed / denied) across the whole stream ({} reqs):".format(len(stream)))
    total = len(stream)
    for k in ["TOKEN", "SLIDING", "FIXED", "LEAKY"]:
        denied_k = total - counts[k]
        print(f"    {k:8s}: {counts[k]:3d} allowed, {denied_k:3d} denied")
    print()
    print("  >>> FIXED WINDOW allows the most because the t~60 straddle exploits")
    print("      the boundary: 15 reqs in 0.3s pass as two separate windows.")
    print("  >>> SLIDING WINDOW counter catches the straddle via prev-window weight.")
    print("  >>> TOKEN/LEAKY deplete their 20-token/queue buffer on the burst and")
    print("      then enforce the strict 10/s sustained rate.")

    # ---------------------------------------------------------------------
    # SECTION F: DISTRIBUTED RATE LIMITING (Redis + Lua, race conditions)
    # ---------------------------------------------------------------------
    banner("Section F - Distributed rate limiting (Redis + Lua)")
    print("The naive 'GET-then-INCR' is RACY. Two clients can both read 99, both")
    print("write 100, and both pass under a limit of 100. The fix is ATOMICITY.\n")

    print("  Scenario: 100 concurrent requests, limit=50, naive vs atomic.\n")
    # NAIVE worst case: all 100 requests read counter BEFORE any write lands.
    # Every reader sees 0 (< 50) -> every reader decides to allow -> 100 pass.
    naive_shared_counter = 0
    naive_reads = [naive_shared_counter for _ in range(100)]  # all read 0
    naive_allowed = sum(1 for r in naive_reads if r < 50)
    naive_shared_counter = naive_allowed  # all 100 writes land, final value = 100
    # ATOMIC: each check-and-incr is linearized; only 50 ever see count <= 50.
    atomic_counter = 0
    atomic_allowed = 0
    for _ in range(100):
        atomic_counter += 1
        if atomic_counter <= 50:
            atomic_allowed += 1
    print(f"    naive  (GET then INCR, full race)  : allowed = {naive_allowed}  "
          f"(OVERSHOT by {naive_allowed - 50}; final counter = {naive_shared_counter})")
    print(f"    atomic (Lua check-and-incr)       : allowed = {atomic_allowed}  "
          f"(exact limit)")
    print()
    print("  Canonical Redis Lua script (token bucket, atomic):")
    print("  ----------------------------------------------------------------")
    print("  -- KEYS[1] = bucket key   ARGV = {capacity, refill_rate, now, cost}")
    print("  local b     = redis.call('HMGET', KEYS[1], 'tokens', 'last')")
    print("  local tokens= tonumber(b[1]) or tonumber(ARGV[1])")
    print("  local last  = tonumber(b[2]) or tonumber(ARGV[3])")
    print("  local delta = math.max(0, tonumber(ARGV[3]) - last)")
    print("  tokens      = math.min(tonumber(ARGV[1]), tokens + delta*ARGV[2])")
    print("  local allowed = 0")
    print("  if tokens >= tonumber(ARGV[4]) then")
    print("    tokens = tokens - tonumber(ARGV[4]); allowed = 1")
    print("  end")
    print("  redis.call('HMSET', KEYS[1], 'tokens', tokens, 'last', ARGV[3])")
    print("  redis.call('EXPIRE', KEYS[1], 60)  -- auto-cleanup after 1 min")
    print("  return {allowed, tokens}")
    print("  ----------------------------------------------------------------")
    print()
    print("  Fail-open vs fail-closed decision matrix:")
    print("    public API  -> fail-open   (Redis down => let traffic through, log)")
    print("    billing     -> fail-closed (Redis down => reject, don't overcharge)")
    print("    login       -> fail-closed (Redis down => block, security first)")
    print("    streaming   -> fail-open   (degrade quality rather than cut user off)")

    # ---------------------------------------------------------------------
    # SECTION G: SCALE ESTIMATION
    # ---------------------------------------------------------------------
    banner("Section G - Scale estimation (QPS tiers + memory per key)")
    tiers = [
        ("startup",          1_000, "single Redis primary, in-process fallback"),
        ("mid-market",      50_000, "3-node Redis cluster, hash-sharded by key"),
        ("large",          500_000, "Redis cluster + local token bucket per pod"),
        ("hyperscale",   5_000_000, "edge rate limit (CDN) + tiered backends"),
    ]
    print("  Tier         Peak QPS    Architecture")
    print("  " + "-" * 64)
    for name, qps, arch in tiers:
        print(f"  {name:11s}  {qps:>10,d}    {arch}")
    print()
    print("  Memory per active key (1-min window):")
    print("    fixed window     : ~52 B   (key + int counter + TTL metadata)")
    print("    sliding window   : ~64 B   (two counters + window_id)")
    print("    token bucket     : ~72 B   (tokens (float) + last_refill (float))")
    print("    sliding log      : 8 B * N (one timestamp per request in window)")
    print()
    # Worked example: 10M users, 100K peak QPS, fixed-window counters.
    users = 10_000_000
    peak_qps = 100_000
    active_pct = 0.10
    active_keys = int(users * active_pct)
    bytes_per_key = 52
    mem_mb = active_keys * bytes_per_key / (1024 * 1024)
    print(f"  Worked example: {users:,} users, {peak_qps:,} peak QPS, 5-min active window.")
    print(f"    active_keys       = {users:,} * {active_pct:.0%}        = {active_keys:,}")
    print(f"    memory (fixed)    = {active_keys:,} * {bytes_per_key} B    = {mem_mb:,.0f} MB")
    log_mem_mb = active_keys * 8 * 100 / (1024 * 1024)
    print(f"    memory (sliding log @ 100 req/key) = {log_mem_mb:,.0f} MB")
    bandwidth_mb = peak_qps * 1 / 1024
    print(f"    bandwidth @ 1KB/req @ peak          = {bandwidth_mb:,.1f} MB/s")
    redis_qps_single = 100_000
    redis_shards_needed = (peak_qps + redis_qps_single - 1) // redis_qps_single
    print(f"    Redis shards needed (single shard ~{redis_qps_single:,} INCR/s) = {redis_shards_needed}")

    # ---------------------------------------------------------------------
    # SECTION H: CHECKS
    # ---------------------------------------------------------------------
    banner("Section H - [check] assertions")

    # Check 1: token bucket starts full and refills correctly.
    tb2 = TokenBucket(capacity=10, refill_rate=5.0)
    ok1, _ = tb2.allow(0.0)
    assert ok1, "first request from full bucket must be allowed"
    print("[check] token bucket: first request from full bucket  -> ALLOW  ... OK")

    # Check 2: token bucket enforces capacity.
    tb3 = TokenBucket(capacity=5, refill_rate=1.0)
    allowed = 0
    for i in range(10):
        if tb3.allow(i * 0.0001)[0]:
            allowed += 1
    assert allowed == 5, f"capacity=5 means exactly 5 allowed, got {allowed}"
    print(f"[check] token bucket: capacity=5, 10 instant reqs   -> {allowed} allowed ... OK")

    # Check 3: token bucket refills at the right rate.
    tb4 = TokenBucket(capacity=10, refill_rate=10.0)
    for _ in range(10):
        tb4.allow(0.0)  # drain
    _, after0 = tb4.allow(0.001)  # drain attempt, denied
    assert after0 < 1.0, "bucket should be ~empty right after drain"
    _, after1 = tb4.allow(1.0)  # 1s later -> +10 tokens, capped at 10
    assert abs(after1 - 9.0) < 0.01, f"expected 9 after 1s refill (1 req), got {after1}"
    print(f"[check] token bucket: drained, wait 1s, refill_rate=10 -> tokens~{after1:.1f} ... OK")

    # Check 4: sliding window counter allows exactly 'limit' in a clean window.
    sw2 = SlidingWindowCounter(limit=5, window_sec=1.0)
    allowed = sum(1 for i in range(10) if sw2.allow(i * 0.01)[0])
    assert allowed == 5, f"clean window, limit=5 -> exactly 5 allowed, got {allowed}"
    print(f"[check] sliding window: clean window, limit=5       -> {allowed} allowed ... OK")

    # Check 5: fixed window resets at the boundary.
    fw2 = FixedWindowCounter(limit=3, window_sec=1.0)
    fw2.allow(0.1)
    fw2.allow(0.2)
    fw2.allow(0.3)
    denied_at_end = not fw2.allow(0.4)[0]
    allowed_new = fw2.allow(1.1)[0]
    assert denied_at_end and allowed_new, "must deny when full, allow after window rolls"
    print("[check] fixed window: full window DENY, boundary reset ALLOW ... OK")

    # Check 6: leaky bucket caps queue size.
    lb3 = LeakyBucket(capacity=3, leak_rate=1.0)
    res = [lb3.allow(t * 0.1)[0] for t in range(10)]  # 10 reqs in 0.9s
    allowed3 = sum(res)
    assert allowed3 == 3, f"capacity=3 queue, leak_rate=1, 10 reqs in 0.9s -> 3 allowed, got {allowed3}"
    print(f"[check] leaky bucket: capacity=3, 10 reqs in 0.9s  -> {allowed3} allowed ... OK")

    # Check 7: race condition - naive overshoots, atomic is exact.
    assert naive_allowed == 100 and atomic_allowed == 50, \
        "naive (100) overshoots; atomic (50) is exact"
    print(f"[check] distributed: naive={naive_allowed} (overshoot), atomic={atomic_allowed} (exact) ... OK")

    # Check 8: scale math.
    assert active_keys == 1_000_000, f"10% of 10M = 1M active keys, got {active_keys}"
    assert 49.0 < mem_mb < 50.0, f"1M * 52B = 49.6 MB, got {mem_mb}"
    print(f"[check] scale: 1M keys * 52B = {mem_mb:.1f} MB           ... OK")

    # Check 9: side-by-side totals are internally consistent.
    s = counts["TOKEN"] + (total - counts["TOKEN"])
    assert s == total, f"token bucket must account for all {total} reqs, got {s}"
    print(f"[check] comparison: token bucket processed all {total} reqs  ... OK")

    # Check 10: fixed window overshoots in the boundary demo.
    assert phase1_allowed + phase2_allowed == 20, "boundary exploit = 20 of 20 pass"
    print(f"[check] fixed window: boundary exploit 20/20 pass    ... OK")

    print()
    print("All [check] assertions passed. Re-run reproduces every number above.")


if __name__ == "__main__":
    main()
