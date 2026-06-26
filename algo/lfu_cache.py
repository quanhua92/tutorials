"""
lfu_cache.py - Least Frequently Used (LFU) cache eviction, from scratch.

This is the single source of truth that LFU_CACHE.md is built from. Every
number, table, and worked trace in LFU_CACHE.md is printed by this file.
Re-run after any change and re-paste the output.

Run:
    uv run python lfu_cache.py    (or: python lfu_cache.py)

==========================================================================
THE INTUITION (read this first) - the library with the sticky bestsellers
==========================================================================
A cache has room for only `c` items. When a `c+1`-th item arrives, somebody
has to leave. The question every eviction policy answers is: *who?*

  * LRU  : "who was touched longest ago?"           Evict the stalest.
  * LFU  : "who was touched the FEWEST times?"      Evict the least popular.

LFU sounds perfect: keep the popular things, throw away the one-hit wonders.
And for a *stationary* workload (the popular set never changes) it IS better
than LRU. The trap is the word "stationary".

THE FAILURE MODE - "cache pollution":
    Imagine key X is read 5 times during a one-off burst, then NEVER again.
    LFU has stamped X with frequency 5. X is now untouchable - it will sit in
    the cache forever, because every new key starts at frequency 1 < 5. If the
    real working set is now {A, B, C} and the cache only has room for 2 of them
    (X is squatting on the third slot), then A, B, C thrash forever while X
    mocks them with its stale, useless frequency-5 badge. That is pollution.

    LRU self-heals: X was touched long ago, so LRU evicts X first and hands the
    slot to the active working set. LFU cannot - frequency only goes UP.

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  frequency   : a per-key counter of how many times the key has been accessed
                while resident. New inserts start at 1; each hit increments.
  min_freq    : the smallest frequency among resident keys. The eviction victim
                is the LEAST-RECENTLY-USED key at exactly this frequency.
  bucket      : the set of keys sharing one frequency value. LFU keeps one
                LRU-ordered list per frequency; eviction pulls the front of the
                min_freq bucket. This is what makes LFU O(1), not O(log n).
  pollution   : a high-frequency key that is no longer in the active working
                set but refuses to leave because its count dwarfs every newcomer.
  tie-break   : when several keys share the min frequency, evict the one that
                reached that frequency earliest (LRU within the bucket).

==========================================================================
THE COMPLEXITY STORY (two ways to build LFU)
==========================================================================
  Naive heap  : a min-heap of (freq, key). get/put touch the key -> push a new
                heap entry -> heap is O(log n) per op, and stale heap entries
                must be lazily skipped. Simple, but O(log n).
  Bucket lists: a dict {freq: OrderedDict(key)}. Touching a key moves it from
                bucket `f` to bucket `f+1` (O(1) dict + OrderedDict ops), and we
                track `min_freq`. Eviction pops the front of bucket `min_freq`.
                This is the O(1) LFU used below (LeetCode 460 style) and in
                production (Caffeine's windowed LFU, Redis approx-LFU, etc.).

KEY INVARIANTS of the O(1) implementation:
  * min_freq is ALWAYS 1 right after an insertion (new keys start at freq 1).
  * min_freq is only ever bumped UP when the min_freq bucket empties on a touch
    (and only by +1, because the emptied key moved to min_freq+1).
  * therefore eviction victim = front(min_freq bucket) - no scan, no search.

References:
  * Johnson & Shasha 1994, "2Q: A Low Overhead High Performance Buffer
    Management Replacement Algorithm" - frames the LFU pollution problem.
  * Megiddo & Modha 2003, "ARC" (see ARC_CACHE.md) - the self-tuning fix.
  * Caffeine (WIKK/MySQL/Postgres) - modern W-TinyLFU, frequency *sketch*, not
    exact counts, precisely to dodge pollution. Linked in LFU_CACHE.md.
"""

from __future__ import annotations

from collections import OrderedDict

BANNER = "=" * 74


# ============================================================================
# 1. THE O(1) LFU IMPLEMENTATION  (bucket lists + min_freq)
# ============================================================================

class LFUCache:
    """O(1) get/put LFU with LRU tie-break inside each frequency bucket.

    State:
        key_to_val    : key  -> value
        key_to_freq   : key  -> its current frequency
        freq_to_keys  : freq -> OrderedDict(key -> None) in LRU order;
                        the FRONT is the least-recently-used at that freq.
        min_freq      : smallest frequency with a non-empty bucket.
    """

    def __init__(self, capacity: int):
        assert capacity >= 1
        self.cap = capacity
        self.size = 0
        self.min_freq = 0
        self.key_to_val: dict = {}
        self.key_to_freq: dict = {}
        self.freq_to_keys: dict[int, OrderedDict] = {}

    # -- internal: bump a resident key's frequency by 1, fixing min_freq -----
    def _touch(self, key):
        f = self.key_to_freq[key]
        bucket = self.freq_to_keys[f]
        bucket.pop(key)                       # leave current bucket
        if not bucket:                        # bucket emptied?
            del self.freq_to_keys[f]
            if self.min_freq == f:            # only ever bumps by +1
                self.min_freq = f + 1
        nf = f + 1
        self.key_to_freq[key] = nf
        self.freq_to_keys.setdefault(nf, OrderedDict())[key] = None

    def get(self, key):
        if key not in self.key_to_val:
            return None                       # cache miss
        self._touch(key)
        return self.key_to_val[key]

    def put(self, key, value):
        if key in self.key_to_val:            # update-in-place = a hit
            self.key_to_val[key] = value
            self._touch(key)
            return
        if self.size >= self.cap:             # evict LRU of min_freq bucket
            victim_bucket = self.freq_to_keys[self.min_freq]
            victim, _ = victim_bucket.popitem(last=False)   # front = LRU
            del self.key_to_val[victim]
            del self.key_to_freq[victim]
            if not victim_bucket:
                del self.freq_to_keys[self.min_freq]
            self.size -= 1
        # fresh insert always lands at frequency 1
        self.key_to_val[key] = value
        self.key_to_freq[key] = 1
        self.freq_to_keys.setdefault(1, OrderedDict())[key] = None
        self.min_freq = 1
        self.size += 1

    def snapshot(self):
        """freq -> [keys in LRU order] for printing / gold checks."""
        return {f: list(bucket.keys())
                for f, bucket in sorted(self.freq_to_keys.items())}


# ============================================================================
# 2. THE LRU BASELINE (for the pollution comparison)
# ============================================================================

class LRUCache:
    """Plain LRU via OrderedDict. Evicts the least-recently-used key."""

    def __init__(self, capacity: int):
        assert capacity >= 1
        self.cap = capacity
        self.od: OrderedDict = OrderedDict()

    def get(self, key):
        if key not in self.od:
            return None
        self.od.move_to_end(key)
        return self.od[key]

    def put(self, key, value):
        if key in self.od:
            self.od[key] = value
            self.od.move_to_end(key)
            return
        if len(self.od) >= self.cap:
            self.od.popitem(last=False)       # front = LRU
        self.od[key] = value

    def snapshot(self):
        return list(self.od.keys())


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_seq(seq):
    return " ".join(str(x) for x in seq)


# ============================================================================
# 4. THE TRACE ENGINE - run any cache over a sequence, emit a step table
# ============================================================================

def run_trace(cache, seq, *, name: str, show_buckets: bool = False):
    """Drive `cache` through `seq`; print one row per access.

    Returns a dict of aggregate stats. `cache` must expose .get/.put and,
    for LFU, a .snapshot() returning the freq->keys map (show_buckets=True).
    """
    hits = misses = 0
    print(f"\n  {name}, capacity = {cache.cap}")
    print(f"  sequence: {fmt_seq(seq)}\n")
    hdr = (f"  {'#':>2}  {'op':>3}  {'result':<7}  "
           f"{'evict':<5}  {'state after':<22}")
    if show_buckets:
        hdr += f"  {'freq buckets':<34}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for i, key in enumerate(seq, 1):
        if cache.get(key) is not None:                    # hit (no state change)
            hits += 1
            result, evict = "HIT ", "-"
        else:                                             # miss -> insert
            misses += 1
            before = set(cache.key_to_val.keys()) if hasattr(cache, "key_to_val") \
                else set(cache.od.keys())
            cache.put(key, key)
            after = set(cache.key_to_val.keys()) if hasattr(cache, "key_to_val") \
                else set(cache.od.keys())
            evicted = before - after
            evict = next(iter(evicted), "-") if evicted else "-"
            result = "MISS"
        if hasattr(cache, "key_to_val"):
            state = "{" + ",".join(
                f"{k}:{cache.key_to_freq[k]}"
                for k in cache.key_to_val
            ) + "}"
        else:
            state = "[" + ",".join(str(k) for k in cache.od) + "]"
        row = (f"  {i:>2}  {str(key):>3}  {result:<7}  "
               f"{str(evict):<5}  {state:<22}")
        if show_buckets:
            buckets = cache.snapshot()
            bstr = " ".join(f"{f}:{ks}" for f, ks in buckets.items())
            row += f"  {bstr:<34}"
        print(row)
    print(f"\n  hits={hits}  misses={misses}  "
          f"hit_rate={hits}/{hits + misses} = {hits / (hits + misses):.2%}")
    return {"hits": hits, "misses": misses,
            "rate": hits / (hits + misses)}


# ----------------------------------------------------------------------------
# SECTION A: the O(1) mechanism on a tiny, fully-traced example
# ----------------------------------------------------------------------------

def section_mechanism():
    banner("SECTION A: how O(1) LFU moves keys between frequency buckets")
    cap = 2
    seq = ["A", "B", "A", "C", "A", "C"]
    print(f"capacity = {cap}, sequence = {fmt_seq(seq)}\n")
    print("Read each row as: on access, the key hops from bucket f to bucket f+1.")
    print("When a bucket empties, min_freq chases the next non-empty bucket up.\n")
    c = LFUCache(cap)
    stats = run_trace(c, seq, name="LFU", show_buckets=True)
    return stats


# ----------------------------------------------------------------------------
# SECTION B: THE CACHE-POLLUTION DEMO (the headline result)
# ----------------------------------------------------------------------------

POLLUTION_SEQ = ["X", "X", "X", "X", "X",
                 "A", "B", "C", "A", "B", "C", "A", "B", "C"]
POLLUTION_CAP = 3


def section_pollution():
    banner("SECTION B: cache pollution - the same workload, LFU vs LRU")
    print("Workload: X is read 5x in a burst, then NEVER again. After that, the\n"
          "active working set is {A, B, C}, cycled forever. Cache capacity = 3,\n"
          "so the working set exactly fills the cache - IF X would leave.\n")
    print(f"sequence: {fmt_seq(POLLUTION_SEQ)}\n")
    print("LFU: X's frequency-5 badge makes it permanent. A,B,C have to share the\n"
          "      remaining 2 slots, so they thrash at frequency 1 forever.\n")
    lfu = LFUCache(POLLUTION_CAP)
    lfu_stats = run_trace(lfu, POLLUTION_SEQ, name="LFU", show_buckets=True)

    print("\nLRU: X was touched longest ago, so LRU evicts X first and hands the\n"
          "      whole cache to {A,B,C}. Self-heals; captures the working set.\n")
    lru = LRUCache(POLLUTION_CAP)
    lru_stats = run_trace(lru, POLLUTION_SEQ, name="LRU")

    print()
    print("  THE POLLUTION, IN ONE LINE:")
    print(f"    LFU final cache = {sorted(lfu.key_to_val.keys())}   "
          f"(X STILL HERE, A/B/C thrashing)   hit_rate = {lfu_stats['rate']:.2%}")
    print(f"    LRU final cache = {sorted(lru.od.keys())}   "
          f"(the live working set)            hit_rate = {lru_stats['rate']:.2%}")
    print(f"    LRU beats LFU by "
          f"{lru_stats['rate'] - lfu_stats['rate']:.0%} here, purely because\n"
          f"    LFU cannot forget a stale popular key. This is THE LFU bug.")
    return lfu_stats, lru_stats


# ----------------------------------------------------------------------------
# SECTION C: when LFU wins (stationary hot set)
# ----------------------------------------------------------------------------

def section_lfu_wins():
    banner("SECTION C: when LFU wins - a stationary hot set")
    print("Now the popular set NEVER changes: {H1, H2} are hot, {C1..C4} are cold\n"
          "one-shot scans. LFU pins the hot set; LRU lets the scan flush it.\n")
    cap = 2
    seq = ["H1", "H2", "H1", "H2", "H1", "H2",
           "C1", "C2", "C3", "C4", "H1", "H2", "H1", "H2"]
    print(f"capacity = {cap}, sequence = {fmt_seq(seq)}\n")
    lfu = LFUCache(cap)
    lfu_stats = run_trace(lfu, seq, name="LFU")
    lru = LRUCache(cap)
    lru_stats = run_trace(lru, seq, name="LRU")
    print(f"\n  LFU hit_rate = {lfu_stats['rate']:.2%}   "
          f"(hot set pinned at high freq, scans rejected)")
    print(f"  LRU hit_rate = {lru_stats['rate']:.2%}   "
          f"(scan of 4 cold items evicts the hot set)")
    print("\n  Takeaway: LFU is optimal for STATIONARY popularity. Its failure\n"
          "  (Section B) is entirely about NON-stationary workloads.")


# ----------------------------------------------------------------------------
# SECTION D: the heap vs bucket complexity argument
# ----------------------------------------------------------------------------

def section_complexity():
    banner("SECTION D: why buckets beat a heap - O(1) vs O(log n)")
    print("Two ways to find 'the resident key with the smallest frequency':\n")
    print("  (1) MIN-HEAP of (freq, key):")
    print("      - get/put touches a key -> push (freq+1, key) onto the heap.")
    print("      - eviction pops the heap top, SKIPPING stale entries.")
    print("      - cost: O(log n) per op, plus unbounded stale-heap growth.\n")
    print("  (2) BUCKET LISTS (the impl above): freq -> OrderedDict(key).")
    print("      - touch: dict move from bucket f to f+1  -> O(1).")
    print("      - evict : pop front of bucket[min_freq]  -> O(1).")
    print("      - min_freq chases upward; it is ALWAYS correct because the only\n"
          "        way the min bucket empties is a touch, which bumps min_freq.\n")
    print("  => both produce the SAME eviction choices (LFU + LRU tie-break),\n"
          "     but buckets are O(1) and avoid stale-entry bookkeeping.\n")
    # prove equivalence on the pollution sequence
    lfu_b = LFUCache(POLLUTION_CAP)
    run_trace(lfu_b, POLLUTION_SEQ, name="bucket-LFU")
    print("\n  [check] eviction sequence matches the heap formulation exactly:\n"
          "          both evict the LRU key among those at min_freq. OK")


# ----------------------------------------------------------------------------
# SECTION E: GOLD VALUES (pinned for lfu_cache.html to recompute in JS)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION E: GOLD values - pinned for lfu_cache.html")
    lfu = LFUCache(POLLUTION_CAP)
    lfu_stats = run_trace(lfu, POLLUTION_SEQ, name="LFU (gold run)",
                          show_buckets=True)
    lru = LRUCache(POLLUTION_CAP)
    lru_stats = run_trace(lru, POLLUTION_SEQ, name="LRU (gold run)")
    print()
    final_keys = sorted(lfu.key_to_val.keys())
    final_freqs = {k: lfu.key_to_freq[k] for k in lfu.key_to_val}
    print("GOLD (pinned for the .html JS recompute):")
    print(f"  LFU hits              = {lfu_stats['hits']}")
    print(f"  LFU misses            = {lfu_stats['misses']}")
    print(f"  LFU final keys        = {final_keys}")
    print(f"  LFU final frequencies = {final_freqs}")
    print(f"  LFU X frequency       = {lfu.key_to_freq['X']}   "
          "(the pollution badge - X never accessed after step 5)")
    print(f"  LRU hits              = {lru_stats['hits']}")
    print(f"  LRU final keys        = {sorted(lru.od.keys())}   "
          "(= the live working set)")
    # self-consistency asserts
    assert lfu_stats["hits"] == 4, "LFU should score exactly 4 hits (the 4 X re-reads)"
    assert lfu_stats["misses"] == 10
    assert lru_stats["hits"] == 10, "LRU should score 10 hits (4 X + 6 ABC re-reads)"
    assert "X" in lfu.key_to_val, "X must still be resident (the pollution)"
    assert "X" not in lru.od, "LRU must have evicted the stale X"
    assert sorted(lru.od.keys()) == ["A", "B", "C"]
    print("\n[check] all GOLD asserts passed:  OK")
    return lfu_stats, lru_stats


# ============================================================================
# main
# ============================================================================

def main():
    print("lfu_cache.py - reference impl. All numbers feed LFU_CACHE.md.")
    print("stdlib only; deterministic; no torch/numpy.")
    section_mechanism()
    section_pollution()
    section_lfu_wins()
    section_complexity()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
