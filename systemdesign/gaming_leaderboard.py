#!/usr/bin/env python3
"""
gaming_leaderboard.py - Gaming leaderboard system design simulation (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds GAMING_LEADERBOARD.md
and is recomputed identically in gaming_leaderboard.html (gold-checked).

Core model: SORTED SET (skip list + hash table) as the ranking primitive.
  - ZADD:        O(log N) insert / update
  - ZREVRANGE:   O(log N + K) top-K
  - ZREVRANK:    O(log N) rank-by-member
  - ZADD ... GT: only update if new score > existing (monotone-best, Redis 6.2+)

Sections:
  1. Sorted set internals (skip list + hash table) on a tiny demo
  2. Top-K retrieval, rank, percentile, neighbors (around-me)
  3. Global vs per-game segmentation, sharding, cross-shard top-K merge
  4. Tier-based ranking (platinum / gold / silver / bronze) at 10K-player scale
  5. Score-update frequency: GT modifier + tournament sliding window
  6. Scale estimation (10M players, RAM, QPS, event storage)
  7. GOLD values pinned for gaming_leaderboard.html
"""

import bisect
import heapq

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

LINE = "=" * 74


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1000.0:
            return "%.2f %s" % (n, unit)
        n /= 1000.0
    return "%.2f EB" % n


def fmt_int(n):
    return "{:,}".format(n)


# ---------------------------------------------------------------------------
# SortedSet - Redis ZSET analogue
# ---------------------------------------------------------------------------
# Redis ZSET = skip list (sorted by score, O(log N) ops) + hash table
# (member -> score, O(1) lookup). Here we use a sorted list of (score, member)
# tuples + a dict member -> score. bisect gives O(log N) search; insertion is
# O(N) for the list shift (Redis pays O(log N) via the real skip list), but the
# API and the DUAL-STRUCTURE idea are identical. Ties on score are broken by
# member ascending in the natural order and descending under ZREVRANGE -- which
# matches Redis exactly.


class SortedSet:
    def __init__(self):
        self._scores = {}            # member -> score  (hash table)
        self._sorted = []            # (score, member) ascending (skip-list role)

    def __len__(self):
        return len(self._scores)

    def zadd(self, member, score, gt=False):
        """ZADD. gt=True => only update if score > existing (GT modifier)."""
        if member in self._scores:
            old = self._scores[member]
            if gt:
                if score <= old:
                    return False       # GT: reject non-improving score
            elif score == old:
                return False
            idx = bisect.bisect_left(self._sorted, (old, member))
            self._sorted.pop(idx)
        self._scores[member] = score
        bisect.insort(self._sorted, (score, member))
        return True

    def score(self, member):
        return self._scores.get(member)

    def _asc_rank(self, member):
        s = self._scores[member]
        return bisect.bisect_left(self._sorted, (s, member))

    def zrevrank(self, member):
        if member not in self._scores:
            return None
        return len(self._sorted) - 1 - self._asc_rank(member)

    def zrevrange(self, start, stop):
        """Ranks start..stop inclusive (0 = top, descending). Returns [(member, score), ...]."""
        n = len(self._sorted)
        if start < 0:
            start += n
        if stop < 0:
            stop += n
        if start < 0:
            start = 0
        if stop >= n:
            stop = n - 1
        if n == 0 or start > stop:
            return []
        asc_lo = n - 1 - stop
        asc_hi = n - 1 - start
        chunk = list(reversed(self._sorted[asc_lo:asc_hi + 1]))
        return [(m, s) for (s, m) in chunk]

    def zrem(self, member):
        if member not in self._scores:
            return False
        s = self._scores.pop(member)
        idx = bisect.bisect_left(self._sorted, (s, member))
        self._sorted.pop(idx)
        return True


# ---------------------------------------------------------------------------
# SECTION 1 - Sorted set internals
# ---------------------------------------------------------------------------

def section_sorted_set():
    banner("SECTION 1: Sorted set (skip list + hash table)")
    print("Redis ZSET is a DUAL structure: a skip list (sorted by score) for")
    print("ordered ops + a hash table (member -> score) for O(1) lookups.")
    print("  ops: ZADD O(log N), ZREVRANGE O(log N + K), ZREVRANK O(log N)")
    print("  mem : ~100 bytes per entry (member + score + skip-list pointers)")
    print("  ties: equal scores are broken by member ascending (ZREVRANGE reverses)")
    print()

    lb = SortedSet()
    # deliberately include TIES to show the lexicographic tie-break
    players = [("alice", 9500), ("bob", 8700), ("carol", 9500),
               ("dave", 3000), ("eve", 8700)]
    print("Demo ZADD sequence (5 players, two ties at 9500 and 8700):")
    for m, s in players:
        lb.zadd(m, s)
        print("  ZADD leaderboard %5d %s   -> stored=%s" % (s, m, "OK"))
    print()

    print("Internal ascending view (= skip-list order):")
    print("  " + ", ".join("%s:%d" % (m, s) for (s, m) in lb._sorted))
    print()

    print("ZREVRANGE leaderboard 0 2 WITHSCORES (top 3):")
    top3 = lb.zrevrange(0, 2)
    for i, (m, s) in enumerate(top3):
        print("  #%d  %-5s %d" % (i + 1, m, s))
    print("  NOTE: carol ranks above alice on the 9500 tie because ZREVRANGE")
    print("  reverses the lexicographic order (carol > alice), matching Redis.")
    print()

    print("ZREVRANK (0 = best):")
    for m in ("alice", "bob", "carol", "dave", "eve"):
        print("  %-5s -> reverse rank %d  (score %d)" % (m, lb.zrevrank(m), lb.score(m)))
    print()

    ok = (len(lb) == 5 and
          top3[0] == ("carol", 9500) and
          top3[1] == ("alice", 9500) and
          top3[2] == ("eve", 8700) and
          lb.zrevrank("dave") == 4)
    print("[check] top-3 order + tie-break + ranks match Redis semantics? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Top-K, rank, percentile, neighbors
# ---------------------------------------------------------------------------

def section_queries():
    banner("SECTION 2: Top-K, rank, percentile, neighbors")
    lb = SortedSet()
    players = [("alice", 9500), ("bob", 8700), ("carol", 9500),
               ("dave", 3000), ("eve", 8700)]
    for m, s in players:
        lb.zadd(m, s)
    n = len(lb)

    print("Top-K with pagination (K=2 per page):")
    for page in (0, 1, 2):
        start = page * 2
        stop = start + 1
        rows = lb.zrevrange(start, stop)
        print("  page %d (ZREVRANGE %d %d): %s" %
              (page, start, stop,
               ", ".join("%s:%d" % (m, s) for (m, s) in rows) if rows else "(empty)"))
    print()

    print("Rank + percentile + neighbors for 'bob':")
    rank = lb.zrevrank("bob")
    # 'top X%' per discussion.md: percentile = (rank + 1) / total * 100
    top_pct = (rank + 1) / n * 100.0
    print("  ZREVRANK bob         = %d" % rank)
    print("  top percent         = %.1f%%   ((rank+1)/total*100; lower = better)" % top_pct)
    neighbors = lb.zrevrange(rank - 1, rank + 1)
    print("  ZREVRANGE rank-1 rank+1 (around-me): %s" %
          ", ".join("%s:%d" % (m, s) for (m, s) in neighbors))
    print("  (around-me is O(log N + K): one skip-list seek + K steps)")
    print()

    print("Rank + percentile for 'dave' (the bottom):")
    rank_d = lb.zrevrank("dave")
    top_d = (rank_d + 1) / n * 100.0
    print("  ZREVRANK dave = %d, top percent = %.1f%%" % (rank_d, top_d))
    print()

    ok = (top_pct == 80.0 and top_d == 100.0 and
          neighbors[0][0] == "eve" and neighbors[1][0] == "bob")
    print("[check] bob top 80%%, dave top 100%%, around-me correct? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Global vs per-game segmentation + cross-shard top-K merge
# ---------------------------------------------------------------------------

N_SHARDS = 100           # regional shards
SHARD_SIZE = 100_000     # players per shard


def section_sharding():
    banner("SECTION 3: Segmentation + sharding + cross-shard top-K")
    print("A single global ZSET breaks at ~100M+ players: 10 GB+ RAM on one node,")
    print("single-threaded writes, slow failover. The default pattern is")
    print("SEGMENTED leaderboards -- one ZSET per region/mode/season -- because")
    print("almost every query is within one segment.")
    print()
    print("Segment keys: leaderboard:{region}:{mode}:{season}")
    print("  e.g. leaderboard:na:solo:2024Q4")
    print()

    print("For a very large segment we hash-shard it across N nodes. A global")
    print("top-K then queries every shard for its top-K and merges: O(N * log K).")
    print("  shards (N)        = %d" % N_SHARDS)
    print("  players / shard   = %s   (=%s total)" %
          (fmt_int(SHARD_SIZE), fmt_int(N_SHARDS * SHARD_SIZE)))
    print()

    # simulate N shards, each holding K top entries; merge to global top-K
    K = 100
    shards = []
    for sh in range(8):                 # show the merge on 8 shards for clarity
        # each shard's top-K, scores descending and disjoint by shard
        shard_top = [("p%d_%d" % (sh, i), 100000 - sh * 50 - i)
                     for i in range(K)]
        shards.append(shard_top)

    # size-K max-heap fed by streaming all N*K entries => O(N*K log K)
    heap = []
    for sh in shards:
        for (m, s) in sh:
            if len(heap) < K:
                heapq.heappush(heap, (s, m))
            else:
                if s > heap[0][0]:
                    heapq.heapreplace(heap, (s, m))
    merged = sorted(heap, key=lambda t: -t[0])
    print("Cross-shard merge demo (8 shards x K=%d -> global top-K):" % K)
    print("  global #1 = %s (%d)" % (merged[0][1], merged[0][0]))
    print("  global #2 = %s (%d)" % (merged[1][1], merged[1][0]))
    print("  global #%d= %s (%d)  (last in merged top-K)" %
          (K, merged[-1][1], merged[-1][0]))
    print("  merge cost = N*K items through a size-K heap = O(N*K log K)")
    print()

    print("GOTCHA: a hierarchical global top-1000 ZSET, recomputed from segments,")
    print("removes the per-query merge for the hot top-K (cached, 1s TTL). Below")
    print("rank 1000 you fall back to the segment query.")
    print()

    ok = (merged[0][0] == 100000 and merged[0][1] == "p0_0" and
          len(merged) == K and N_SHARDS * SHARD_SIZE == 10_000_000)
    print("[check] shard-0 player-0 is global #1 and total == 10M? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Tier-based ranking
# ---------------------------------------------------------------------------

# deterministic score generator (Knuth's multiplicative constant); reproducible
# in JS: (i * 2654435761) < 2^53 for i < ~3.4M so the multiply is exact.
K_MULT = 2654435761
SCORE_MOD = 100_000

TIER_RULES = [
    ("platinum", 90000),   # >= 90000
    ("gold",     75000),   # 75000..89999
    ("silver",   50000),   # 50000..74999
    ("bronze",   0),       # < 50000
]


def score_of(player_id):
    return (player_id * K_MULT) % SCORE_MOD


def tier_of(score):
    for name, lo in TIER_RULES:
        if score >= lo:
            return name
    return "bronze"


def section_tiers():
    banner("SECTION 4: Tier-based ranking (platinum / gold / silver / bronze)")
    n = 10_000
    print("Deterministic %d-player sim: score(i) = (i * %d) %% %d" %
          (n, K_MULT, SCORE_MOD))
    print("  (Knuth multiplicative hash; deterministic, reproducible in JS.)")
    print()

    counts = {name: 0 for name, _ in TIER_RULES}
    for i in range(n):
        s = score_of(i)
        counts[tier_of(s)] += 1

    print("Tier distribution:")
    print("  %-9s %12s %9s %10s" % ("tier", "players", "share", "min score"))
    for name, lo in TIER_RULES:
        c = counts[name]
        print("  %-9s %12s %8.1f%% %10s" %
              (name, fmt_int(c), c / n * 100.0, lo if lo > 0 else "0"))
    print()

    print("Tier buckets are themselves segmented ZSETs (leaderboard:na:solo:gold),")
    print("so a player only competes within their tier -- bronze #1 and platinum")
    print("#1 are both 'first place'. Promotions between tiers run nightly.")
    print()

    plat = counts["platinum"]
    ok = (sum(counts.values()) == n and plat > 0 and plat < n)
    print("[check] tiers partition all %d players and platinum is non-empty? " %
          n + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Score update frequency: GT modifier + tournament window
# ---------------------------------------------------------------------------

def section_updates():
    banner("SECTION 5: GT modifier + tournament sliding window")
    lb = SortedSet()
    lb.zadd("alice", 9500)
    lb.zadd("bob", 8700)
    print("Monotone-best via ZADD ... GT (Redis 6.2+): a new score only replaces")
    print("the old one if it is GREATER. This kills replay / regression attacks")
    print("(a buggy submitter sending 0 cannot lower a real score).")
    print()

    print("  alice = 9500. Attempt ZADD ... GT 8000 (regression):")
    applied = lb.zadd("alice", 8000, gt=True)
    print("    applied = %s  -> alice still %d" % (applied, lb.score("alice")))
    print("  Attempt ZADD ... GT 9800 (improvement):")
    applied = lb.zadd("alice", 9800, gt=True)
    print("    applied = %s  -> alice now %d" % (applied, lb.score("alice")))
    print()

    # tournament sliding window: events with epoch-day timestamps; recompute
    # a windowed ZSET by summing events inside the window.
    print("Tournament sliding window (last 7 days):")
    print("  individual game results live in a Kafka/Redis Stream; a periodic")
    print("  recompaction job sums events inside the window into a snapshot ZSET.")
    print()
    events = [
        ("alice", 5, 1200), ("bob",  5, 900),
        ("alice", 4, 1100), ("carol", 4, 1500),
        ("bob",  3, 800),  ("carol", 3, 1400),
        ("alice", 9, 1300),  # day 9 = OUTSIDE a last-7-day window ending day 7
        ("dave",  2, 3000),
    ]
    window_lo, window_hi = 1, 7
    # per-member SUM of points inside the window (ZADD-by-max is the wrong
    # semantic for a tournament total; emulate a sum then bulk-ZADD).
    accum = {}
    for (m, day, pts) in events:
        if window_lo <= day <= window_hi:
            accum[m] = accum.get(m, 0) + pts
    windowed = SortedSet()
    for m, s in accum.items():
        windowed.zadd(m, s)
    print("  window days %d..%d, %d in-window events across %d players" %
          (window_lo, window_hi, sum(1 for (_, d, _) in events if window_lo <= d <= window_hi), len(accum)))
    print("  windowed ZSET (top-K, descending):")
    for i, (m, s) in enumerate(windowed.zrevrange(0, 9)):
        print("    #%d  %-5s %d" % (i + 1, m, s))
    print("  alice's day-9 score is EXCLUDED (outside window). dave (day 2) is in.")
    print()
    print("Recompaction cadence vs window size:")
    for win, every in (("1 hour", "1 min"), ("1 day", "10 min"), ("7 days", "nightly")):
        print("  last %-7s -> recompute every %-7s" % (win, every))
    print()

    ok = (lb.score("alice") == 9800 and
          windowed.zrevrange(0, 0)[0] == ("dave", 3000) and
          windowed.score("alice") == 2300)
    print("[check] GT rejected the regression, accepted the improvement, and the "
          "window excludes day 9? " + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - Scale estimation
# ---------------------------------------------------------------------------

def section_scale():
    banner("SECTION 6: Scale estimation")
    mau = 10_000_000
    games_per_day = 5
    updates_per_day = mau * games_per_day
    views_per_day = 100_000_000
    sps = 86_400
    bytes_per_entry = 100

    wq = updates_per_day / sps
    rq = views_per_day / sps
    ratio = views_per_day // updates_per_day

    print("Assumptions:")
    print("  monthly active players    = %s" % fmt_int(mau))
    print("  games / player / day      = %d" % games_per_day)
    print("  score updates / day       = %s" % fmt_int(updates_per_day))
    print("  leaderboard views / day   = %s" % fmt_int(views_per_day))
    print("  daily read:write ratio    = %d : 1" % ratio)
    print()

    print("QPS:")
    print("  write QPS avg             = %.1f /s" % wq)
    print("  write QPS peak (weekend)  = 100,000 /s   (tournament burst, ~173x avg)")
    print("  read  QPS avg             = %.1f /s" % rq)
    print("  read  QPS peak (finals)   = 100,000 /s   (live top-K polling)")
    print()

    ram_per_lb = mau * bytes_per_entry
    ram_per_shard = (mau / N_SHARDS) * bytes_per_entry
    print("Redis ZSET RAM (one segment, ~%d B / entry):" % bytes_per_entry)
    print("  10M-player leaderboard    = %.2f GB   (single-node ceiling ~ here)" %
          (ram_per_lb / 1e9))
    print("  per regional shard (%s ply)= %.2f MB   (%d shards -> fits one shard)" %
          (fmt_int(mau // N_SHARDS), ram_per_shard / 1e6, N_SHARDS))
    print()

    row_b = 100
    rows_day = updates_per_day
    storage_day = rows_day * row_b
    storage_year = storage_day * 365
    print("Postgres score-history storage (~%d B / event row):" % row_b)
    print("  events / year             = %s   (%.2f B)" %
          (fmt_int(rows_day * 365), rows_day * 365 / 1e9))
    print("  storage / year            = %s   (archive old seasons to S3 Parquet)" %
          fmt_bytes(storage_year))
    print()

    ok = (ratio == 2 and
          abs(ram_per_lb / 1e9 - 1.0) < 1e-9 and
          N_SHARDS == 100)
    print("[check] daily read:write == 2:1 and 10M players -> 1.00 GB RAM? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - GOLD values pinned for gaming_leaderboard.html
# ---------------------------------------------------------------------------

def section_gold():
    banner("SECTION 7: GOLD values (pinned for gaming_leaderboard.html)")

    # tiny deterministic demo leaderboard (same as Section 1)
    lb = SortedSet()
    for m, s in [("alice", 9500), ("bob", 8700), ("carol", 9500),
                 ("dave", 3000), ("eve", 8700)]:
        lb.zadd(m, s)
    top3 = lb.zrevrange(0, 2)
    top3_members = ",".join(m for (m, _) in top3)
    top3_scores = ",".join(str(s) for (_, s) in top3)
    alice_rank = lb.zrevrank("alice")
    dave_rank = lb.zrevrank("dave")
    dave_top_pct = round((dave_rank + 1) / len(lb) * 100.0, 1)

    # tier sim counts
    tier_n = 10_000
    platinum = sum(1 for i in range(tier_n) if score_of(i) >= 90000)

    # scale
    updates_per_year_b = round(10_000_000 * 5 * 365 / 1e9, 2)
    write_qps_avg = round(10_000_000 * 5 / 86_400, 1)
    read_qps_avg = round(100_000_000 / 86_400, 1)

    gold = [
        ("demo_n_players",      len(lb)),
        ("demo_top3_members",   top3_members),
        ("demo_top3_scores",    top3_scores),
        ("demo_alice_revrank",  alice_rank),
        ("demo_dave_top_pct",   dave_top_pct),
        ("tier_sim_n",          tier_n),
        ("tier_platinum_count", platinum),
        ("tier_platinum_pct",   round(platinum / tier_n * 100.0, 1)),
        ("players_total",       10_000_000),
        ("write_qps_avg",       write_qps_avg),
        ("read_qps_avg",        read_qps_avg),
        ("read_qps_peak",       100_000),
        ("ram_per_lb_gb",       1.0),
        ("events_per_year_b",   updates_per_year_b),
        ("n_shards",            N_SHARDS),
    ]
    for k, v in gold:
        print("  %-22s = %s" % (k, v))
    print()

    ok = (top3_members == "carol,alice,eve" and
          top3_scores == "9500,9500,8700" and
          alice_rank == 1 and
          dave_top_pct == 100.0 and
          platinum > 0 and
          abs(write_qps_avg - 578.7) < 1e-9 and
          abs(read_qps_avg - 1157.4) < 1e-9 and
          updates_per_year_b == 18.25)
    print("[check] GOLD reproduces from SortedSet + tier/scale formulas? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# gaming_leaderboard.py - Gaming leaderboard system design simulation")
    print("# Pure Python stdlib only. Numbers below feed GAMING_LEADERBOARD.md")
    print("# and gaming_leaderboard.html (gold-checked).")
    section_sorted_set()
    section_queries()
    section_sharding()
    section_tiers()
    section_updates()
    section_scale()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
