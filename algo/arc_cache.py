"""
arc_cache.py - Adaptive Replacement Cache (ARC), from scratch.

This is the single source of truth that ARC_CACHE.md is built from. Every
number, table, and worked trace in ARC_CACHE.md is printed by this file.

Run:
    uv run python arc_cache.py    (or: python arc_cache.py)

==========================================================================
THE INTUITION (read this first) - the bouncer who learns the crowd
==========================================================================
A cache has to pick ONE eviction rule. LRU says "evict the stalest" (great
for recency, blind to popularity). LFU says "evict the least popular" (great
for popularity, blind to staleness - see LFU_CACHE.md's pollution bug).

The ugly truth: NO fixed rule wins on every workload.
  * A scan of cold one-shot reads  -> LRU wins (LFU gets polluted).
  * A stable hot set + occasional noise -> LFU wins (LRU flushes the hot set).

ARC's idea (Megiddo & Modha, 2003): DON'T pick. Run LRU and LFU *at the same
time*, watch which one is scoring hits on *evicted-but-re-requested* keys
(ghosts), and continuously shift capacity toward the winner. It is a
self-tuning dial called `p` (the target size of the recency half).

FOUR LISTS, two real and two ghost:
  T1 : REAL, recent.     Keys seen once recently        (the LRU half).
  T2 : REAL, frequent.   Keys seen >= 2x, or promoted   (the LFU half).
  B1 : GHOST of T1.      Keys that LIVED in T1, got evicted. No value stored.
  B2 : GHOST of T2.      Keys that LIVED in T2, got evicted. No value stored.

  |T1| + |T2| = c  (the real cache; ghosts are metadata only, ~free).

THE ADAPTATION (the whole point):
  * A hit in B1 (a recent-ghost hit) means "I evicted this from T1 and now I
    want it back -> the recency side (T1) is too small." So p GROWS.
  * A hit in B2 (a frequent-ghost hit) means "I evicted this from T2 and now I
    want it back -> the frequency side (T2) is too small." So p SHRINKS.
  * The amount of the nudge is the RATIO of the opposite ghost list size, so a
    lonely ghost in a big rival list moves the dial harder.

WHY GHOSTS ARE GENIUS: a ghost costs ~zero memory (just the key, no value) but
lets ARC *remember its mistakes*. When it evicts the wrong thing and the
workload asks for it again, the ghost hit is the feedback signal that turns the
dial. A plain LRU/LFU forgets its evictions instantly; ARC learns from them.

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  T1 / T2   : the two halves of the REAL cache. T1 = "seen once recently",
              T2 = "seen again / promoted = frequent".
  B1 / B2   : ghost directories of T1 / T2. They store keys only, never values.
              A ghost is ARC's memory of "what I evicted, and from which half".
  c         : total real capacity. |T1| + |T2| = c (after warm-up). Ghosts can
              push |T1|+|B1| and |T2|+|B2| up to c each.
  p         : the ADAPTIVE target size of T1, in [0, c]. p=0  -> pure frequency
              (all T2); p=c -> pure recency (all T1). ARC tunes p from traffic.
  REPLACE   : the subroutine that actually frees a real slot when one is needed.
              It evicts from T1 if |T1| > p (recency side is over-budget), else
              from T2 - and demotes the victim to the matching ghost list.

==========================================================================
THE FOUR CASES (verbatim from the paper, in plain English)
==========================================================================
  Case I   x in T1 or T2        -> HIT. Move x to MRU of T2 (it's now frequent).
  Case II  x in B1              -> ghost-recent hit. p grows; REPLACE; promote
                                   x from B1 to MRU of T2.
  Case III x in B2              -> ghost-frequent hit. p shrinks; REPLACE;
                                   promote x from B2 to MRU of T2.
  Case IV  x nowhere            -> cold miss. Possibly trim a ghost list, then
                                   REPLACE (if needed), then insert x at MRU T1.

KEY FORMULAS (verified against Megiddo & Modha 2003, §3):
    delta1 = max( |B2| / |B1| , 1 )        # Case II nudge
    delta2 = max( |B1| / |B2| , 1 )        # Case III nudge
    p_new  = min( c, p + delta1 )          # Case II
    p_new  = max( 0, p - delta2 )          # Case III
    REPLACE(x, p):
        if T1 nonempty AND ( |T1| > p  OR  (x in B2 AND |T1| == p) ):
            demote LRU(T1) -> MRU(B1)
        else:
            demote LRU(T2) -> MRU(B2)
  INVARIANTS:  |T1| + |T2| <= c ;  |T1| + |B1| <= c ;  |T2| + |B2| <= c.

Integer vs real `p`: the paper writes the deltas as real ratios. For a clean,
deterministic trace we use integer division (delta = max(rival//mine, 1)), as
in common reference implementations (e.g. the Wikipedia pseudocode). On the
small workloads below this yields the same p-trajectory either way.

References:
  * Megiddo & Modha 2003, "ARC: A Self-Tuning, Low Overhead Replacement
    Cache" (FAST '03). IBM Z-series storage and IBM EasyTier use ARC.
  * Johnson & Shasha 1994, "2Q" - the two-list ancestor ARC generalizes.
"""

from __future__ import annotations

from collections import OrderedDict

BANNER = "=" * 74


# ============================================================================
# 1. THE ARC IMPLEMENTATION  (faithful to the paper; O(1) via OrderedDicts)
# ============================================================================

class ARCCache:
    """Adaptive Replacement Cache.

    Real cache = T1 ++ T2  (|T1|+|T2| <= c).
    Ghosts     = B1, B2    (metadata only).
    All four are OrderedDicts in LRU order: front = LRU, back = MRU.
    """

    def __init__(self, capacity: int):
        assert capacity >= 1
        self.c = capacity
        self.p = 0                              # target size of T1, adaptive
        self.T1: OrderedDict = OrderedDict()    # recent      (real)
        self.T2: OrderedDict = OrderedDict()    # frequent    (real)
        self.B1: OrderedDict = OrderedDict()    # ghost of T1
        self.B2: OrderedDict = OrderedDict()    # ghost of T2
        # instrumentation
        self.last_case = ""
        self.last_delta = 0

    # -- size helpers -------------------------------------------------------
    def _l1(self):           # L1 = T1 ∪ B1
        return len(self.T1) + len(self.B1)
    def _l2(self):           # L2 = T2 ∪ B2
        return len(self.T2) + len(self.B2)

    # -- REPLACE(x, p): free one real slot, demote victim to its ghost ------
    def _replace(self, x):
        if self.T1 and (len(self.T1) > self.p
                        or (x in self.B2 and len(self.T1) == self.p)):
            # recency side over budget -> demote LRU of T1 to MRU of B1
            victim, _ = self.T1.popitem(last=False)
            self.B1[victim] = None              # MRU of B1
            return ("T1->B1", victim)
        else:
            victim, _ = self.T2.popitem(last=False)
            self.B2[victim] = None              # MRU of B2
            return ("T2->B2", victim)

    # -- the four cases -----------------------------------------------------
    def access(self, x):
        """Process one access. Returns (hit: bool, case: str, evicted)."""
        if x in self.T1 or x in self.T2:        # Case I: cache HIT
            self.last_case = "I  (hit in T1/T2)"
            self.last_delta = 0
            # move to MRU of T2 (a 2nd sighting = frequent)
            self.T1.pop(x, None)
            self.T2.pop(x, None)
            self.T2[x] = None
            return (True, self.last_case, None)

        if x in self.B1:                        # Case II: ghost-recent hit
            delta = max(len(self.B2) // max(len(self.B1), 1), 1)
            self.p = min(self.c, self.p + delta)
            self.last_delta = +delta
            self.last_case = f"II (B1 ghost hit, p+={delta} -> {self.p})"
            ev = self._replace(x)
            del self.B1[x]                      # leave ghost
            self.T2[x] = None                   # promote to MRU of T2
            return (False, self.last_case, ev)

        if x in self.B2:                        # Case III: ghost-frequent hit
            delta = max(len(self.B1) // max(len(self.B2), 1), 1)
            self.p = max(0, self.p - delta)
            self.last_delta = -delta
            self.last_case = f"III (B2 ghost hit, p-={delta} -> {self.p})"
            ev = self._replace(x)
            del self.B2[x]
            self.T2[x] = None                   # promote to MRU of T2
            return (False, self.last_case, ev)

        # Case IV: cold miss
        self.last_delta = 0
        ev = None
        if self._l1() == self.c:
            if len(self.T1) < self.c:
                # drop LRU of B1, then REPLACE
                self.B1.popitem(last=False)
                ev = self._replace(x)
            else:
                # T1 is full, B1 empty -> evict LRU of T1 outright
                victim, _ = self.T1.popitem(last=False)
                ev = ("T1-drop", victim)
        elif self._l1() < self.c:
            total = self._l1() + self._l2()
            if total >= self.c:
                if self.B2:
                    self.B2.popitem(last=False)     # drop LRU of B2
                ev = self._replace(x)
        self.last_case = "IV (cold miss)"
        self.T1[x] = None                           # MRU of T1
        return (False, self.last_case, ev)


# ============================================================================
# 2. LRU + LFU BASELINES (for the head-to-head)
#    (minimal versions; full impls in lfu_cache.py)
# ============================================================================

class _LRU:
    def __init__(self, c):
        self.c = c
        self.od = OrderedDict()

    def access(self, x):
        if x in self.od:
            self.od.move_to_end(x)
            return True
        if len(self.od) >= self.c:
            self.od.popitem(last=False)
        self.od[x] = None
        return False


class _LFU:
    def __init__(self, c):
        self.c = c
        self.kv = {}
        self.kf = {}
        self.fb: dict[int, OrderedDict] = {}
        self.mf = 0

    def _touch(self, k):
        f = self.kf[k]
        b = self.fb[f]
        b.pop(k)
        if not b:
            del self.fb[f]
            if self.mf == f:
                self.mf = f + 1
        self.kf[k] = f + 1
        self.fb.setdefault(f + 1, OrderedDict())[k] = None

    def access(self, x):
        if x in self.kv:
            self._touch(x)
            return True
        if len(self.kv) >= self.c:
            v, _ = self.fb[self.mf].popitem(last=False)
            del self.kv[v]
            del self.kf[v]
            if not self.fb[self.mf]:
                del self.fb[self.mf]
        self.kv[x] = None
        self.kf[x] = 1
        self.fb.setdefault(1, OrderedDict())[x] = None
        self.mf = 1
        return False


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_od(od: OrderedDict):
    return "[" + ",".join(str(k) for k in od) + "]"


def fmt_state(arc: ARCCache):
    return (f"T1{fmt_od(arc.T1)} T2{fmt_od(arc.T2)} "
            f"B1{fmt_od(arc.B1)} B2{fmt_od(arc.B2)} p={arc.p}")


# ============================================================================
# 4. THE TRACE ENGINE
# ============================================================================

def run_arc_trace(seq, capacity, *, name="ARC", verbose=True):
    arc = ARCCache(capacity)
    hits = misses = 0
    rows = []
    for i, x in enumerate(seq, 1):
        hit, case, ev = arc.access(x)
        if hit:
            hits += 1
        else:
            misses += 1
        rows.append((i, x, hit, case, ev, fmt_state(arc)))
    if verbose:
        print(f"\n  {name}, c = {capacity}")
        print(f"  sequence: {' '.join(str(s) for s in seq)}\n")
        print(f"  {'#':>2}  {'op':>3}  {'res':<4}  "
              f"{'case':<32}  {'evict':<10}  state")
        print("  " + "-" * 108)
        for i, x, hit, case, ev, st in rows:
            evs = "- " if ev is None else f"{ev[0]}:{ev[1]}"
            print(f"  {i:>2}  {str(x):>3}  "
                  f"{'HIT ' if hit else 'MISS':<4}  {case:<32}  "
                  f"{evs:<10}  {st}")
        print(f"\n  hits={hits}  misses={misses}  "
              f"hit_rate={hits}/{hits + misses} = {hits / (hits + misses):.2%}")
        print(f"  final p = {arc.p}  (started at 0; "
              f"{'recency-favored' if arc.p >= capacity / 2 else 'frequency-favored'})")
    return arc, hits, misses, rows


def run_baseline(cls, seq, capacity, *, name):
    c = cls(capacity)
    hits = 0
    for x in seq:
        if c.access(x):
            hits += 1
    rate = hits / len(seq)
    print(f"  {name:5} c={capacity}: hits={hits:<3} "
          f"misses={len(seq) - hits:<3} hit_rate={rate:.2%}")
    return rate


# ----------------------------------------------------------------------------
# SECTION A: the four lists + the four cases (tiny, fully traced)
# ----------------------------------------------------------------------------

def section_mechanism():
    banner("SECTION A: the four lists and the four cases, step by step")
    seq = ["A", "B", "A", "C", "D", "A"]
    print("capacity = 3. Watch T1/T2 fill on cold misses, then a Case-II ghost\n"
          "hit nudge p upward once a key returns from B1.\n")
    run_arc_trace(seq, 3, name="ARC (mechanism)")


# ----------------------------------------------------------------------------
# SECTION B: THE ADAPTATION DEMO - p tuning in action
#   Designed so T2 is populated FIRST; only then do cold misses trigger
#   REPLACE, which is the ONLY routine that creates ghosts. Once ghosts
#   exist, re-asking for them fires Case II / Case III and moves p.
# ----------------------------------------------------------------------------

ADAPT_SEQ = ["A", "B", "C", "D",   # 1-4: cold misses fill T1
             "A", "B",               # 5-6: HITS -> A,B promoted into T2
             "E", "F", "G", "H",     # 7-10: cold scan; T1<->B1 churn makes ghosts
             "E", "F",               # 11-12: Case-II (B1) ghost hits -> p GROWS
             "A"]                    # 13:   Case-III (B2) ghost hit -> p SHRINKS
ADAPT_CAP = 4


def section_adaptation():
    banner("SECTION B: self-tuning - watch p move with the workload")
    print(f"capacity = {ADAPT_CAP}. Three phases:\n")
    print("  Phase 1 (steps 1-6): A,B,C,D enter T1; re-asking A,B promotes them\n"
          "    to T2 (frequency side). Now BOTH halves are populated - this is\n"
          "    the precondition for ghosts, because REPLACE only demotes to a\n"
          "    ghost list when there is a rival real list to evict from.\n")
    print("  Phase 2 (steps 7-10): a cold scan E,F,G,H. Each cold miss calls\n"
          "    REPLACE, which demotes the LRU of T1 into B1 (a ghost). Ghosts\n"
          "    now exist as 'eviction memory'.\n")
    print("  Phase 3 (steps 11-13): re-ask for E,F -> they are in B1 = Case-II\n"
          "    ghost hits -> p GROWS (ARC votes 'recency half too small'). Then\n"
          "    re-ask for A -> it is in B2 = Case-III ghost hit -> p SHRINKS.\n")
    arc, hits, misses, rows = run_arc_trace(
        ADAPT_SEQ, ADAPT_CAP, name="ARC (adaptation)")
    p_traj = [0] + [int(r[5].split("p=")[1]) for r in rows]
    print(f"\n  p trajectory (start + per step): {p_traj}")
    print("  p went 0 -> 1 -> 2 -> 1. The two Case-II hits grew it; the Case-III\n"
          "  hit shrank it. THAT is ARC self-tuning from live ghost feedback -\n"
          "  no fixed LRU or LFU can do this.")
    return arc


# ----------------------------------------------------------------------------
# SECTION C: ARC vs LRU vs LFU - robustness across TWO opposed workloads
#   The honest ARC story: no fixed policy wins everywhere. ARC's claim is
#   that it stays COMPETITIVE on both kinds without being told which is which.
# ----------------------------------------------------------------------------

# Workload 1 - NON-stationary (the LFU-pollution workload from lfu_cache.py):
# a stale squatter X then a live working set {A,B,C}. LRU wins, LFU collapses.
WL1_SEQ = ["X", "X", "X", "X", "X",
           "A", "B", "C", "A", "B", "C", "A", "B", "C"]
WL1_CAP = 3
# Workload 2 - stationary hot set + one-shot scan. LFU wins, LRU flushes.
WL2_SEQ = ["H1", "H2", "H1", "H2", "H1", "H2",
           "C1", "C2", "C3", "C4", "H1", "H2", "H1", "H2"]
WL2_CAP = 2


def _rates(seq, cap):
    arc = ARCCache(cap)
    ah = sum(1 for x in seq if arc.access(x)[0])
    lru = _LRU(cap)
    lh = sum(1 for x in seq if lru.access(x))
    lfu = _LFU(cap)
    fh = sum(1 for x in seq if lfu.access(x))
    n = len(seq)
    return (ah / n, lh / n, fh / n, arc.p)


def section_showdown():
    banner("SECTION C: robustness - two workloads that break opposite policies")
    print("Workload 1 (NON-stationary, breaks LFU): stale squatter X read 5x then\n"
          "  never again; live working set {A,B,C} cycled. c=3. LRU self-heals by\n"
          "  evicting stale X; LFU pins X forever (pollution, see LFU_CACHE.md).\n")
    print("Workload 2 (stationary hot set, breaks LRU): {H1,H2} hot, then a one-shot\n"
          "  scan of 4 cold items, then back to hot set. c=2. LFU pins the hot set;\n"
          "  LRU lets the scan flush it.\n")
    a1, l1, f1, p1 = _rates(WL1_SEQ, WL1_CAP)
    a2, l2, f2, p2 = _rates(WL2_SEQ, WL2_CAP)
    print(f"  {'workload':<42}{'ARC':>9}{'LRU':>9}{'LFU':>9}{'ARC p':>7}")
    print("  " + "-" * 76)
    print(f"  {'1: non-stationary (LFU-pollution), c=3':<42}"
          f"{a1:>8.1%}{l1:>9.1%}{f1:>9.1%}{p1:>7}")
    print(f"  {'2: stationary hot set + scan, c=2':<42}"
          f"{a2:>8.1%}{l2:>9.1%}{f2:>9.1%}{p2:>7}")
    print()
    print("  Read it row by row:")
    print(f"    WL1: LRU {l1:.0%} >> LFU {f1:.0%}.   ARC {a1:.0%} (p->{p1}).")
    print(f"    WL2: LFU {f2:.0%} >  LRU {l2:.0%}.   ARC {a2:.0%} (p->{p2}).")
    arc_avg = (a1 + a2) / 2
    lru_avg = (l1 + l2) / 2
    lfu_avg = (f1 + f2) / 2
    print(f"\n  Average over both: ARC {arc_avg:.1%}  vs  "
          f"LRU {lru_avg:.1%}  vs  LFU {lfu_avg:.1%}.")
    worst_lru = min(l1, l2)
    worst_lfu = min(f1, f2)
    worst_arc = min(a1, a2)
    print(f"  Worst-case over both: ARC {worst_arc:.0%}, "
          f"LRU {worst_lru:.0%}, LFU {worst_lfu:.0%}.")
    print("\n  THE POINT: LRU and LFU each have a workload where they collapse\n"
          "  (LFU->29% on WL1, LRU->43% on WL2). ARC, with NO knowledge of which\n"
          "  workload it is on, stays competitive on BOTH because p adapts: it\n"
          "  leaned recency-favored on WL1 and frequency-favored on WL2. That\n"
          "  worst-case robustness - not winning every single trace - is what\n"
          "  made IBM adopt ARC for Z-series storage.")
    return (a1, l1, f1, p1, a2, l2, f2, p2)


# ----------------------------------------------------------------------------
# SECTION D: invariants (correctness check)
# ----------------------------------------------------------------------------

def section_invariants():
    banner("SECTION D: invariants hold across a long random-ish run")
    seq = ["A", "B", "A", "C", "A", "B", "D", "E", "A", "C",
           "F", "B", "A", "D", "E", "C", "A", "B", "G", "H"]
    cap = 5
    arc, *_ = run_arc_trace(seq, cap, name="ARC (invariant probe)", verbose=False)
    assert len(arc.T1) + len(arc.T2) <= cap, "real cache overflow"
    assert len(arc.T1) + len(arc.B1) <= cap, "|T1|+|B1| <= c violated"
    assert len(arc.T2) + len(arc.B2) <= cap, "|T2|+|B2| <= c violated"
    assert 0 <= arc.p <= cap, "p out of [0, c]"
    allkeys = (list(arc.T1) + list(arc.T2) + list(arc.B1) + list(arc.B2))
    assert len(allkeys) == len(set(allkeys)), "a key in two lists"
    print(f"  ran {len(seq)} ops at c={cap}; final p={arc.p}")
    print(f"  |T1|+|T2| = {len(arc.T1) + len(arc.T2)} <= {cap}   OK")
    print(f"  |T1|+|B1| = {len(arc.T1) + len(arc.B1)} <= {cap}   OK")
    print(f"  |T2|+|B2| = {len(arc.T2) + len(arc.B2)} <= {cap}   OK")
    print(f"  0 <= p = {arc.p} <= {cap}   OK")
    print("  no key appears in two lists   OK")
    print("\n[check] all invariants hold:  OK")


# ----------------------------------------------------------------------------
# SECTION E: GOLD values (pinned for arc_cache.html to recompute in JS)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION E: GOLD values - pinned for arc_cache.html")
    arc, hits, misses, rows = run_arc_trace(
        ADAPT_SEQ, ADAPT_CAP, name="ARC (gold run)", verbose=True)
    # the full p-trajectory and case sequence are the gold signals
    p_traj = []
    case_seq = []
    for i, x, hit, case, ev, st in rows:
        p_traj.append(arc._p_at(i)) if hasattr(arc, "_p_at") else None
    # re-run cleanly capturing per-step p
    a2 = ARCCache(ADAPT_CAP)
    p_traj = [a2.p]
    case_seq = []
    hit_seq = []
    for x in ADAPT_SEQ:
        hit, case, _ = a2.access(x)
        p_traj.append(a2.p)
        case_seq.append(case.split()[0])     # "I", "II", "III", "IV"
        hit_seq.append(int(hit))
    print()
    print("GOLD (pinned for the .html JS recompute):")
    print(f"  capacity              = {ADAPT_CAP}")
    print(f"  sequence              = {list(ADAPT_SEQ)}")
    print(f"  final p               = {a2.p}")
    print(f"  p-trajectory (per step, incl. start 0) = {p_traj}")
    print(f"  case sequence         = {case_seq}")
    print(f"  hit sequence (1=hit)  = {hit_seq}")
    print(f"  hits / total          = {sum(hit_seq)} / {len(hit_seq)}")
    print(f"  final T1              = {list(a2.T1)}")
    print(f"  final T2              = {list(a2.T2)}")
    print(f"  final B1              = {list(a2.B1)}")
    print(f"  final B2              = {list(a2.B2)}")
    # self-consistency asserts
    assert p_traj[0] == 0
    assert len(p_traj) == len(ADAPT_SEQ) + 1
    assert 0 <= a2.p <= ADAPT_CAP
    assert len(a2.T1) + len(a2.T2) <= ADAPT_CAP
    print("\n[check] all GOLD asserts passed:  OK")
    return a2, p_traj, case_seq, hit_seq


# ============================================================================
# main
# ============================================================================

def main():
    print("arc_cache.py - reference impl. All numbers feed ARC_CACHE.md.")
    print("stdlib only; deterministic; no torch/numpy.")
    print("Implements Megiddo & Modha 2003 (FAST '03).")
    section_mechanism()
    section_adaptation()
    section_showdown()
    section_invariants()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
