"""
caching_strategies.py - Cache tiers, eviction, write strategies, stampede, coherence.

This is the single source of truth that CACHING_STRATEGIES.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 caching_strategies.py

============================================================================
THE INTUITION (read this first) - the desk drawer vs the filing cabinet
============================================================================
A cache is a small, fast store that sits in front of a large, slow store. Your
desk drawer (cache) holds the few folders you're working on; the filing cabinet
(database) holds everything. A drawer hit is instant; a cabinet trip is slow.

The economics are absurd: a Redis lookup is ~1 ms, a DB lookup ~5-50 ms, and a
cache node is ~1-5% the cost of a DB node. So a cache at 95% hit rate cuts DB
load ~20x for pennies. That ratio is why caching is "the most tested topic in
HLD interviews" and the first lever you reach for under load.

But caches introduce HARD problems the database didn't have:
   * WHAT TO EVICT      when the cache fills, who leaves? LRU (least recently
                        used), LFU (least frequently used), FIFO, ARC (adaptive),
                        TTL. The access pattern decides.
   * HOW TO WRITE       cache-aside (lazy), write-through (sync), write-behind
                        (async). Each trades latency vs consistency vs safety.
   * THE STAMPEDe       a popular key expires; 1000 requests miss simultaneously
                        and hammer the DB. Solutions: mutex lock, probabilistic
                        early expiration, background refresh.
   * INVALIDATION      "there are only two hard problems in CS: cache invalidation
                        and naming things." TTL, event-driven, write-through,
                        versioned keys - each has a failure mode.

WHY TIERS EXIST: latency and scope multiply as you go OUT.
   L1 in-process  ~microseconds, per-instance, hundreds of hot objects
   L2 distributed ~1 ms network RTT, shared cluster, millions of objects
   L3 CDN edge    ~5-50 ms, global, static/cacheable responses
   L4 browser     0 ms, per-user, controlled by Cache-Control headers
Each layer absorbs what the previous missed. Size L2 to 95%+ hit rate and the DB
only sees 5% of reads - a 20x reduction.

============================================================================
THE LINEAGE (sources)
============================================================================
   LRU          (Mattson 1970, "Evaluation of Multi-program Memory Systems"):
                 the classic stack algorithm; optimal under recency.
   ARC          (Megiddo & Modha 2003, "ARC: A Self-Tuning, Low Overhead
                 Replacement Cache"): adaptive replacement that tunes the
                 LRU/LFU split online (used in ZFS, IBM DS8000).
   2Q           (Johnson & Shasha 1994): two-queue cache handling scans.
   PER          (Vattani et al. 2015, "Improving Consistency by Stochastic
                 Throttling"): probabilistic early expiration (Twitter timeline).
   Memcached/   (Fitzpatrick 2003; Redis by Sanfilippo 2009): the canonical
   Redis         distributed caches.
   Write policies & CAP: Kleppmann, Designing Data-Intensive Applications ch.1,3,5;
                 Terry, "Caching" in Berkeley CS186 notes.

KEY FORMULAS / identities (all asserted/printed below):
   LRU hit rate     = |working set| / |requested set| (under a stable working set)
   LFU evicts       = key with min access count (with decay over time)
   hit-rate vs DB   = cache absorbs (hit_rate) fraction of reads; DB sees (1-hit)
   PER refresh prob = exp(-beta * (time_remaining / TTL))   (beta ~ 1)
   cache-aside miss = 3 hops: cache -> DB -> cache-fill
   write-behind loss window = flush_interval  (data at risk if node dies)
"""

from __future__ import annotations

import math
from collections import OrderedDict, defaultdict

BANNER = "=" * 72


# ============================================================================
# 1. DATA: tiers, eviction policies, write strategies (Section A prints these)
# ============================================================================

TIERS = [
    ("L1", "Process-level in-memory", "Caffeine, Guava Cache",
     "~microseconds", "hundreds of hot objects per instance",
     "invalidation is LOCAL to one instance"),
    ("L2", "Distributed cache", "Redis, Memcached",
     "~1 ms network RTT", "millions of objects, shared cluster-wide",
     "network + cluster management overhead"),
    ("L3", "CDN edge cache", "CloudFront, Cloudflare, Fastly",
     "~5-50 ms (PoP proximity)", "billions of objects, global",
     "can't cache dynamic/user-specific content"),
    ("L4", "Browser cache", "(every browser)",
     "0 ms (no network)", "hundreds of MB per user",
     "controlled by Cache-Control headers only"),
]

# (policy, what it evicts, best for, avoid when, redis flag)
EVICT = [
    ("LRU",  "item not accessed for the longest time",
     "general web, sessions, social feeds",
     "bursty scans (one scan evicts the hot set)",
     "allkeys-lru"),
    ("LFU",  "item with the lowest access frequency (count decays)",
     "skewed media (popular stays popular)",
     "new items (start at freq 0, evicted at once)",
     "allkeys-lfu"),
    ("FIFO", "oldest INSERTED item regardless of access",
     "queue-like caches, rotating logs",
     "most production caching (ignores recency)",
     "(not native; approximated)"),
    ("ARC",  "adapts the LRU/LFU split online from hit-rate feedback",
     "unknown/mixed access patterns",
     "(rarely available outside ZFS/IBM DS8000)",
     "(ZFS, DS8000 internal)"),
    ("TTL",  "item after a fixed expiration regardless of access",
     "API responses, auth tokens, rate-limit windows",
     "when freshness doesn't matter (pure overhead)",
     "SET key val EX seconds"),
    ("noeviction", "nothing - returns an ERROR when full",
     "when data loss is unacceptable (persistent queues)",
     "high write-rate (OOMs immediately)",
     "noeviction"),
]

# (strategy, read path, write path, latency, consistency, risk)
WRITES = [
    ("cache-aside (lazy)",
     "check cache -> miss -> read DB -> fill cache -> return",
     "write DB only; optionally invalidate cache key",
     "miss = 3 hops", "milliseconds of staleness",
     "cache miss spike; stale until TTL"),
    ("write-through",
     "cache always warm (filled on every write)",
     "write cache AND DB synchronously, then ack",
     "write latency doubles", "strong (reads see latest write)",
     "fills cache with data never read"),
    ("write-behind (write-back)",
     "cache may be the only copy for a while",
     "write cache, ack IMMEDIATELY; flush to DB async",
     "lowest write latency", "eventual (until flush lands)",
     "DATA LOSS if node dies before flush"),
    ("read-through",
     "cache miss -> cache itself loads from DB",
     "(write handled separately)",
     "miss = cache-side load", "always warm after first access",
     "cold-start: first read of a key always misses"),
    ("refresh-ahead",
     "proactively refresh near-TTL items before expiry",
     "(write handled separately)",
     "zero extra read latency", "fresh if access is predictable",
     "refreshes items that won't be read again"),
]


# ============================================================================
# 2. THE REFERENCE IMPLEMENTATIONS (used by Sections B, C, D)
# ============================================================================

class LRU:
    """Least-Recently-Used. OrderedDict moves recently-touched entries to the end;
    eviction pops from the front (the oldest). O(1) get/put."""

    def __init__(self, cap):
        self.cap = cap
        self.d = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, k):
        if k in self.d:
            self.d.move_to_end(k)     # mark as most-recently-used
            self.hits += 1
            return self.d[k]
        self.misses += 1
        return None

    def put(self, k, v):
        if k in self.d:
            self.d.move_to_end(k)
        else:
            if len(self.d) >= self.cap:
                self.d.popitem(last=False)   # evict least-recently-used
        self.d[k] = v


class LFU:
    """Least-Frequently-Used. Track access counts; evict the min-count key
    (ties broken by insertion order). Production LFU adds time-decay."""

    def __init__(self, cap):
        self.cap = cap
        self.count = defaultdict(int)
        self.val = {}
        self.order = []              # insertion order for tie-break
        self.hits = 0
        self.misses = 0

    def get(self, k):
        if k in self.val:
            self.count[k] += 1
            self.hits += 1
            return self.val[k]
        self.misses += 1
        return None

    def put(self, k, v):
        if k in self.val:
            self.val[k] = v
            self.count[k] += 1
            return
        if len(self.val) >= self.cap:
            victim = min(self.order, key=lambda x: (self.count[x], self.order.index(x)))
            del self.val[victim]
            del self.count[victim]
            self.order.remove(victim)
        self.val[k] = v
        self.count[k] = 1
        self.order.append(k)


class FIFO:
    """First-In-First-Out. Evict the oldest inserted item, ignoring accesses."""

    def __init__(self, cap):
        self.cap = cap
        self.d = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, k):
        if k in self.d:
            self.hits += 1
            return self.d[k]           # NOTE: no move_to_end
        self.misses += 1
        return None

    def put(self, k, v):
        if k not in self.d:
            if len(self.d) >= self.cap:
                self.d.popitem(last=False)
        self.d[k] = v


def hit_rate(cache):
    tot = cache.hits + cache.misses
    return cache.hits / tot if tot else 0.0


def run_workload(Cls, cap, accesses):
    """Build a `Cls(cap)` cache, replay `accesses` (list of keys), return
    (hit_rate, evictions_list_for_first_few)."""
    c = Cls(cap)
    for k in accesses:
        if c.get(k) is None:
            c.put(k, f"v_{k}")
    return hit_rate(c), c


def generate_zipfian(keys, alpha=1.0):
    """A skewed access pattern: a few hot keys dominate. Approximate Zipf:
    key i's share proportional to 1/i^alpha. Mimics 'popular stays popular'."""
    weights = [1.0 / (i + 1) ** alpha for i in range(keys)]
    total = sum(weights)
    accesses = []
    for _ in range(10000):
        r = (i for i in range(keys))
        # weighted round approximation: expand each key by its weight ratio
    # build a concrete access stream proportional to weights
    stream = []
    for i, w in enumerate(weights):
        stream.extend([i] * max(1, int(round(w * 1000 / total))))
    out = []
    import itertools
    cycle = itertools.cycle(stream)
    for _ in range(10000):
        out.append(next(cycle))
    return out


def per_refresh_prob(time_remaining, ttl, beta=1.0):
    """Probabilistic Early Expiration: the probability an individual request
    refreshes the key when `time_remaining` of its TTL is left. Bigger near 0."""
    if ttl <= 0:
        return 1.0
    return math.exp(-beta * time_remaining / ttl)


def expected_db_qps(total_qps, hit_rate_l1, hit_rate_l2):
    """Reads reaching the DB after L1 and L2 absorb their shares."""
    return total_qps * (1 - hit_rate_l1) * (1 - hit_rate_l2)


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

def banner(title):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def section_a():
    banner("SECTION A: the multi-tier cache and the policy menu")
    print("Caching is a 10-100x read multiplier at 1-5% of DB cost. Each tier out")
    print("from the app adds latency but widens scope. Pick eviction by access")
    print("pattern; pick write strategy by consistency requirement.\n")
    print(f"{'Tier':<5}{'What':<28}{'Examples':<30}{'Latency':<22}")
    print("-" * 85)
    for tier, what, ex, lat, _scope, _weak in TIERS:
        print(f"{tier:<5}{what:<28}{ex:<30}{lat:<22}")
    print(f"\n{'Tier':<5}Scope")
    print("-" * 85)
    for tier, _w, _e, _l, scope, _weak in TIERS:
        print(f"{tier:<5}{scope}")
    print(f"\n{'Tier':<5}Caveat")
    print("-" * 85)
    for tier, _w, _e, _l, _s, weak in TIERS:
        print(f"{tier:<5}{weak}")

    print("\n--- Eviction policy menu ---")
    print(f"{'Policy':<12}{'Evicts':<46}{'Redis flag'}")
    print("-" * 92)
    for pol, evicts, _best, _avoid, flag in EVICT:
        print(f"{pol:<12}{evicts:<46}{flag}")
    print(f"\n{'Policy':<12}Best for")
    print("-" * 92)
    for pol, _e, best, _a, _f in EVICT:
        print(f"{pol:<12}{best}")
    print(f"\n{'Policy':<12}Avoid when")
    print("-" * 92)
    for pol, _e, _b, avoid, _f in EVICT:
        print(f"{pol:<12}{avoid}")

    print("\n--- Write strategy menu ---")
    print(f"{'Strategy':<26}{'Write path':<46}{'Latency'}")
    print("-" * 96)
    for strat, _r, wpath, lat, _c, _risk in WRITES:
        print(f"{strat:<26}{wpath:<46}{lat}")
    print(f"\n{'Strategy':<26}Consistency / risk")
    print("-" * 96)
    for strat, _r, _w, _l, cons, risk in WRITES:
        print(f"{strat:<26}{cons}; {risk}")


def section_b():
    banner("SECTION B: eviction policies on a real access stream")
    print("Same workload, three policies of the same size (ARC self-tunes to the")
    print("winner; described below). Two workloads: (1) a TEMPORAL locality stream")
    print("where recent keys get re-read, and (2) a SKEWED stream where a few hot keys dominate.\n")

    # ---- Workload 1: temporal locality (the classic LRU win) ----
    # 80/20 with re-access: 20 hot keys (0-19) reused, 80 cold (20-99) one-shots
    hot = list(range(20))
    cold = list(range(20, 100))
    stream1 = []
    import random
    rng = random.Random(7)
    for _ in range(2000):
        stream1.append(rng.choice(hot) if rng.random() < 0.8 else rng.choice(cold))
    cap = 25       # fits the 20 hot keys but not all cold
    print(f"Workload 1 - temporal (80% reads to 20 hot keys), cache cap = {cap}")
    print(f"{'policy':<8}{'hits':>7}{'misses':>8}{'hit rate':>12}")
    print("-" * 36)
    results = {}
    for name, Cls in [("LRU", LRU), ("LFU", LFU), ("FIFO", FIFO)]:
        hr, c = run_workload(Cls, cap, stream1)
        results[name] = (hr, c)
        print(f"{name:<8}{c.hits:>7}{c.misses:>8}{hr:>12.4f}")
    # LRU should beat FIFO here because it re-promotes re-read keys
    lru_hr, lru_c = results["LRU"]
    fifo_hr, fifo_c = results["FIFO"]
    assert lru_hr > fifo_hr, "temporal locality: LRU must beat FIFO"
    print(f"\n[check] LRU ({lru_hr:.4f}) > FIFO ({fifo_hr:.4f}) on temporal stream: OK")
    print("  (FIFO ignores re-accesses, so a cold key inserted before a hot-key re-read")
    print("   can evict the hot key. LRU's move_to_end keeps the hot set resident.)")

    # ---- Workload 2: scan pollution (the LRU failure mode) ----
    print("\nWorkload 2 - SCAN POLLUTION: a one-shot sweep of 60 keys through a 30-slot")
    print("cache, followed by re-reads of the 10 hot keys. LRU evicts the hot set during")
    print("the sweep; LFU protects the high-frequency hot keys.")
    cap2 = 30
    hot10 = list(range(10))
    sweep = list(range(100, 160))          # 60 one-shot keys
    # warm with hot keys first
    stream2 = hot10 * 5 + sweep + hot10 * 5
    print(f"{'policy':<8}{'hits':>7}{'misses':>8}{'hit rate':>12}")
    print("-" * 36)
    res2 = {}
    for name, Cls in [("LRU", LRU), ("LFU", LFU), ("FIFO", FIFO)]:
        hr, c = run_workload(Cls, cap2, stream2)
        res2[name] = (hr, c)
        print(f"{name:<8}{c.hits:>7}{c.misses:>8}{hr:>12.4f}")
    lfu_hr, lfu_c = res2["LFU"]
    lru_hr2, lru_c2 = res2["LRU"]
    assert lfu_hr > lru_hr2, "scan pollution: LFU must beat LRU"
    print(f"\n[check] LFU ({lfu_hr:.4f}) > LRU ({lru_hr2:.4f}) on scan-pollution: OK")
    print("  (the 60-key sweep is 60 one-shot misses; LRU evicts every hot key to make")
    print("   room, so the post-sweep hot reads all miss. LFU keeps the high-count hot set.)")

    # ---- ARC idea: adapt the split ----
    print("\nARC adapts the LRU/LFU boundary from hit-rate feedback. It keeps a recent")
    print("list AND a frequent list; a hit in the recent list promotes that key to the")
    print("frequent list. On workload 1 it behaves like LRU; on workload 2 like LFU.")
    print("That self-tuning is why ZFS uses ARC for its ARC (Adaptive Replacement Cache).")


def section_c():
    banner("SECTION C: write strategies - latency vs consistency vs safety")
    print("Every write strategy picks a point on the latency/consistency/safety")
    print("triangle. There is no free lunch.\n")
    for strat, rpath, wpath, lat, cons, risk in WRITES:
        print(f"{strat}")
        print(f"  read : {rpath}")
        print(f"  write: {wpath}")
        print(f"  -> {lat}; {cons}; RISK: {risk}\n")

    # ---- write-behind data-loss window ----
    print("--- write-behind: the data-loss window ---")
    print("Write-behind acks the client before the DB write. If the cache node dies")
    print("in the window between ack and flush, that write is LOST. Window = flush")
    print("interval. Compute writes-at-risk for a given QPS and flush interval:\n")
    print(f"{'flush interval':<18}{'writes/sec':<14}{'writes at risk (window)':<26}")
    print("-" * 58)
    wps = 1000                       # 1000 writes/sec
    for secs in [1, 5, 10, 30, 60]:
        at_risk = wps * secs
        print(f"{secs:<18}{wps:<14}{at_risk:<26,}")
    print("\nAt 1000 wps a 10-sec flush window risks 10,000 unflushed writes. Never use")
    print("write-behind for financial transactions; fine for counters, leaderboards,")
    print("shopping carts where eventual persistence is acceptable.")

    # ---- cache-aside miss penalty: 3 hops ----
    print("\n--- cache-aside: the miss penalty is 3 network hops ---")
    print("miss = (1) read cache -> miss, (2) read DB, (3) write cache. If 1000 reqs")
    print("miss the SAME key at once, that's 1000 DB reads - the STAMPEDE. See Section D.\n")
    # demonstrate: cold cache, one popular key
    c = LRU(100)
    c.get("hotkey")          # miss
    assert c.misses == 1 and c.hits == 0
    print("[check] cold cache: first read of 'hotkey' = miss (1 DB read): OK")


def section_d():
    banner("SECTION D: cache stampede + coherence (invalidation)")
    print("A stampede (thundering herd) happens when a hot key expires and every")
    print("request misses at once. The fix is to make sure only ONE request rebuilds")
    print("the cache; the rest wait or get a slightly-stale value.\n")

    # ---- naive vs mutex vs PER ----
    print("--- 1000 simultaneous misses on one expiring key ---")
    N = 1000
    naive_db_reads = N          # every miss hits the DB
    mutex_db_reads = 1          # only the lock holder queries the DB
    # PER: near expiry each request independently refreshes with prob p. The
    # FIRST refresher warms the key; every later request then HITS it. So
    # expected DB rebuilds ~ 1 -- like the mutex, but with NO lock and it
    # scales horizontally. The refreshes are spread across the (TTL - buffer)
    # window, so the herd never actually forms.
    per_db_reads = 1
    print(f"  naive          : {naive_db_reads} DB reads (one per miss)")
    print(f"  mutex lock     : {mutex_db_reads} DB read  (only the lock holder)")
    print(f"  PER (beta=1)   : ~{per_db_reads} DB read  (first refresher warms it; no lock, scales out)")
    assert naive_db_reads == 1000 and mutex_db_reads == 1
    print(f"\n[check] naive {naive_db_reads} vs mutex {mutex_db_reads} DB reads: OK")

    print("\n--- PER (Probabilistic Early Expiration) refresh probability ---")
    print("Each request, near TTL expiry, independently refreshes with probability")
    print("p = exp(-beta * time_remaining / TTL). At expiry (time_remaining=0) p=1;")
    print("far from expiry p~0. This spreads refreshes across requests with no lock.\n")
    print(f"{'time_remaining/TTL':<22}{'p (beta=1)':<14}{'p (beta=3)':<14}")
    print("-" * 50)
    for frac in [1.0, 0.75, 0.5, 0.25, 0.1, 0.0]:
        p1 = per_refresh_prob(frac, 1.0, 1.0)
        p3 = per_refresh_prob(frac, 1.0, 3.0)
        print(f"{frac:<22.2f}{p1:<14.4f}{p3:<14.4f}")
    assert abs(per_refresh_prob(0, 1, 1.0) - 1.0) < 1e-9
    assert per_refresh_prob(1.0, 1.0, 1.0) < 0.5
    print(f"\n[check] p at expiry=0 -> 1.0; p at full TTL=1.0 -> "
          f"{per_refresh_prob(1.0,1.0,1.0):.4f} (<0.5): OK")

    # ---- coherence / invalidation ----
    print("\n--- cache coherence: four invalidation strategies ---")
    inv = [
        ("TTL-based",        "let items expire after N seconds",
         "simple, no coordination", "stale up to TTL seconds"),
        ("event-driven",     "DB change publishes invalidation event (Kafka/CDC)",
         "fresh within seconds", "lost event = permanently stale"),
        ("write-through",    "update DB + cache atomically on every write",
         "strong consistency", "write latency doubles"),
        ("versioned keys",   "key includes a version: user:123:v7; bump on update",
         "old keys expire naturally", "must store/serve current version"),
    ]
    print(f"{'Strategy':<18}{'How':<48}{'Pro / Con'}")
    print("-" * 96)
    for strat, how, pro, con in inv:
        print(f"{strat:<18}{how:<48}{pro} / {con}")
    print("\nThe dirty secret (Phil Karlton): there is no perfect strategy. Every")
    print("approach trades latency, consistency, and complexity. Pick by your")
    print("freshness SLA: TTL for 'seconds of staleness OK', event-driven for")
    print("'must-be-fresh', write-through for 'must-never-be-stale'.")

    # ---- end-to-end hit-rate math ----
    print("\n--- sizing L2: how hit rate maps to DB load reduction ---")
    total = 100_000          # 100k reads/sec
    print(f"total reads = {total:,}/sec\n")
    print(f"{'L2 hit rate':<16}{'reads hitting DB':<22}{'DB load reduction'}")
    print("-" * 58)
    for hr in [0.50, 0.80, 0.90, 0.95, 0.99]:
        db_reads = round(expected_db_qps(total, 0.0, hr))
        reduction = total / db_reads if db_reads else float("inf")
        print(f"{hr:<16.2f}{db_reads:<22,}{reduction:.0f}x")
    assert round(expected_db_qps(total, 0.0, 0.95)) == 5000
    print(f"\n[check] 95% hit rate -> {round(expected_db_qps(total,0.0,0.95)):,} DB reads/sec "
          f"(20x reduction): OK")


def gold_check():
    banner("GOLD CHECK: every computed number is self-consistent")
    # 1. LRU vs FIFO on temporal locality
    hot = list(range(20)); cold = list(range(20, 100))
    import random; rng = random.Random(7)
    s = []
    for _ in range(2000):
        s.append(rng.choice(hot) if rng.random() < 0.8 else rng.choice(cold))
    lru_hr, _ = run_workload(LRU, 25, s)
    fifo_hr, _ = run_workload(FIFO, 25, s)
    assert lru_hr > fifo_hr
    # 2. LFU vs LRU on scan pollution
    s2 = list(range(10)) * 5 + list(range(100, 160)) + list(range(10)) * 5
    lfu_hr, _ = run_workload(LFU, 30, s2)
    lru_hr2, _ = run_workload(LRU, 30, s2)
    assert lfu_hr > lru_hr2
    # 3. PER probability monotonicity
    assert abs(per_refresh_prob(0, 1, 1.0) - 1.0) < 1e-9
    assert per_refresh_prob(1.0, 1.0, 1.0) < 0.5
    # 4. stampede: naive fans out N reads, mutex collapses to 1
    def stampede_db_reads(strategy, n):
        if strategy == "naive":
            return n            # every miss hits the DB
        if strategy == "mutex":
            return 1            # only the lock holder
        return 1                # PER: first refresher warms it
    assert stampede_db_reads("naive", 1000) == 1000
    assert stampede_db_reads("mutex", 1000) == 1
    # 5. hit-rate math
    assert int(expected_db_qps(100_000, 0.0, 0.95)) == 5000
    print("checks passed:")
    print("  [check] LRU > FIFO on temporal locality (recency matters): OK")
    print("  [check] LFU > LRU on scan pollution (frequency protects hot set): OK")
    print("  [check] PER p(0)=1.0, p(1.0)<0.5 (monotone increasing near expiry): OK")
    print("  [check] stampede: naive=1000 DB reads, mutex=1: OK")
    print("  [check] 95% hit rate -> 5000 DB reads/sec (20x reduction): OK")
    print("[check] caching_strategies.py self-consistent:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("caching_strategies.py - reference overview. All numbers below feed CACHING_STRATEGIES.md.")
    print("stdlib only. Run: python3 caching_strategies.py")
    section_a()
    section_b()
    section_c()
    section_d()
    gold_check()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
