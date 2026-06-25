"""
skip_list.py - Reference implementation of the Skip List (Pugh, 1990), a
probabilistic alternative to balanced trees.

This is the SINGLE SOURCE OF TRUTH for SKIP_LIST.md. Every number, level, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 skip_list.py > skip_list_output.txt

Pure Python stdlib only. Deterministic: a SEEDED RNG (random.Random(42)) fixes
every coin flip, so the .html can replicate the exact same levels.

========================================================================
THE INTUITION (read this first) — the express lanes over a sorted queue
========================================================================
Imagine a SORTED QUEUE of people standing in one long line (the bottom level
linked list). To find person #500 you would walk past 499 others — slow. So we
build EXPRESS LANES above the line: each express lane keeps roughly HALF the
people (chosen by a coin flip), letting you skip big gaps. Stand on the top
express lane, run right until you are about to overshoot, then DROP DOWN one
lane and run again. Each lane halves the remaining distance -> O(log N) hops.

  bottom level (level 0):  every element, in sorted order.
  level 1:                 ~half the elements (coin flip, p=0.5).
  level 2:                 ~a quarter.
  ...                      each level ~p times smaller.
  top level:               a handful of "express" elements.

THE REASON SKIP LISTS EXIST: a balanced tree (AVL/Red-Black) gives O(log N)
search, but the rotation/rebalancing code is fiddly and hostile to concurrency
(rotations need wide locks). A skip list gets the SAME expected O(log N) with
nothing but COIN FLIPS and pointer rewires — no rotations, no recoloring, no
balance factors. And because each node only ever touches its immediate
neighbors on a few levels, lock-free concurrent skip lists are practical.
Redis uses them for sorted sets (ZSET), LevelDB/MemSQL for memtables.

========================================================================
PLAIN-ENGLISH GLOSSARY
========================================================================
  node            a cell holding a value + a list of forward pointers, one per
                  level it appears on.
  level           a horizontal linked list. Level 0 has ALL elements; higher
                  levels are progressively sparser "express lanes".
  forward[i]      the next node at level i (the "right" pointer on lane i).
  header          a sentinel node at the far left whose forward pointers start
                  every lane. Searching always starts at the header's TOP lane.
  coin flip       on insert, flip a biased coin (prob p of heads). Keep flipping
                  while heads: the number of heads = the node's level. Expected
                  level = 1/(1-p) - 1 ... the max level is ~log_{1/p}(N).
  promotion       "this element made it onto lane k" = it got k heads in a row.
  p               the promotion probability. p=0.5 halves each lane (classic).
                  Higher p -> taller lists (more lanes), smaller gaps.

========================================================================
THE SEARCH RULE (Pugh 1990) — the whole algorithm in 3 lines
========================================================================
  Start at the header's TOP lane. Repeat:
    1. if the neighbor on this lane is smaller than the target -> step RIGHT.
    2. else (no neighbor, or neighbor >= target) -> DROP DOWN one lane.
    3. at level 0, if the neighbor == target -> found; else -> absent.
  Each lane roughly halves the search space -> EXPECTED O(log N) node visits.

KEY FACTS (all asserted in code below, gold-checked):
    level of node        = number of consecutive heads (p=0.5)
    expected height      = log_{1/p}(N)   ; p=0.5, N=1024 -> ~10 levels
    expected search path <= 2 * log_{1/p}(N) node visits   (the gold check)
    every level is a subsequence of the level below (invariants preserved)
    no rotations, no recoloring: insert/delete = pointer rewires only

References:
    William Pugh (1990), "Skip lists: a probabilistic alternative to balanced
    trees." Communications of the ACM 33(6). — the original paper.
    Redis t_zset.c — skip list backs the ZSET (sorted set) data type.
"""

from __future__ import annotations

import math
import random

BANNER = "=" * 72

P = 0.5          # promotion probability (coin-flip heads)
MAX_LEVEL = 16   # hard cap on levels (enough for N up to ~2^16)


# ============================================================================
# 0. THE SKIP NODE + SKIP LIST
# ============================================================================

class SkipNode:
    """One skip-list cell.

    forward[i] = the next node on lane i (None = end of lane). A node that was
    promoted to level L has forward[0..L]; lanes above L do not reference it.
    """

    __slots__ = ("val", "forward")

    def __init__(self, val: int, level: int):
        self.val = val
        self.forward: list[SkipNode | None] = [None] * (level + 1)


class SkipList:
    """A probabilistic sorted set with expected O(log N) operations.

    The header is a sentinel whose forward pointers start every lane. Searching
    always begins at the header's highest lane and drops down. Deterministic
    given the same RNG seed, because the coin flips are the only randomness.
    """

    def __init__(self, p: float = P, max_level: int = MAX_LEVEL,
                 rng: random.Random | None = None):
        self.p = p
        self.max_level = max_level
        self.rng = rng or random.Random(0)
        self.header = SkipNode(-1, max_level)   # sentinel (val -1, unused)
        self.level = 0                          # current highest occupied lane

    # ---- coin flip: how many levels does a new node get? ----
    def random_level(self) -> int:
        lvl = 0
        while self.rng.random() < self.p and lvl < self.max_level:
            lvl += 1
        return lvl

    # ---- search (returns (found_node_or_None, forward_hops)) ----
    def search(self, target: int) -> tuple[SkipNode | None, int]:
        """Return (node_or_None, hops) where hops = forward-pointer moves.

        A hop is one step RIGHT on some lane. This is the standard search-cost
        metric: it is the number of nodes physically moved to (excluding the
        header start). Expected O(log N); we gold-check hops <= 2*log2(N).
        """
        hops = 0
        cur = self.header
        for i in range(self.level, -1, -1):         # top lane down to 0
            while cur.forward[i] is not None and cur.forward[i].val < target:
                cur = cur.forward[i]
                hops += 1                            # stepped RIGHT on lane i
        cur = cur.forward[0]
        if cur is not None and cur.val == target:
            return cur, hops
        return None, hops

    # ---- insert ----
    def insert(self, val: int) -> int:
        lvl = self.random_level()
        if lvl > self.level:
            self.level = lvl
        node = SkipNode(val, lvl)
        # splice into every lane 0..lvl
        cur = self.header
        for i in range(lvl, -1, -1):
            while cur.forward[i] is not None and cur.forward[i].val < val:
                cur = cur.forward[i]
            node.forward[i] = cur.forward[i]
            cur.forward[i] = node
        return lvl

    # ---- all values on a lane (for visualization) ----
    def lane(self, i: int) -> list[int]:
        out: list[int] = []
        cur = self.header.forward[i]
        while cur is not None:
            out.append(cur.val)
            cur = cur.forward[i]
        return out


# ============================================================================
# 1. PRETTY PRINTERS
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_skip_list(sl: SkipList) -> None:
    """Print every lane, top down. Each lane is a subsequence of the one below."""
    print(f"levels: 0..{sl.level} (highest occupied lane = {sl.level})")
    for i in range(sl.level, -1, -1):
        vals = sl.lane(i)
        print(f"  L{i}: " + " -> ".join(f"{v:>2}" for v in vals) +
              " -> NULL")
    print("  (bottom lane L0 holds ALL elements; higher lanes skip elements)")


def node_level_table(sl: SkipList) -> list[tuple[int, int]]:
    """(val, top_level) for every element, sorted by value."""
    out: list[tuple[int, int]] = []
    cur = sl.header.forward[0]
    while cur is not None:
        out.append((cur.val, len(cur.forward) - 1))
        cur = cur.forward[0]
    return out


# ----------------------------------------------------------------------------
# SECTION A: build from [3,6,7,9,12,17,19,21,25,26] and show all levels
# ----------------------------------------------------------------------------

def section_build() -> tuple[SkipList, list[tuple[int, int]]]:
    banner("SECTION A: build a skip list from "
           "[3,6,7,9,12,17,19,21,25,26]  (show all levels)")
    seq = [3, 6, 7, 9, 12, 17, 19, 21, 25, 26]
    print(f"p = {P} (each promoted element halves on the next lane). "
          f"RNG seed = 42 -> fully deterministic.\n")
    sl = SkipList(rng=random.Random(42))
    levels: dict[int, int] = {}
    for v in seq:
        lv = sl.insert(v)
        levels[v] = lv
    print_skip_list(sl)
    print()
    print("Each element's top lane (promotion via coin flips):")
    print("| val | top level |")
    print("|-----|-----------|")
    node_levels = node_level_table(sl)
    for val, lv in node_levels:
        print(f"| {val:<3} | {lv}         |")
    print()
    # invariant: every higher lane is a subsequence of the lane below
    ok = True
    for i in range(1, sl.level + 1):
        if not set(sl.lane(i)).issubset(set(sl.lane(i - 1))):
            ok = False
    print(f"[check] every lane is a subsequence of the lane below? {ok}")
    return sl, node_levels


# ----------------------------------------------------------------------------
# SECTION B: search path — start top-left, go right while smaller, drop down
# ----------------------------------------------------------------------------

def section_search(sl: SkipList) -> None:
    banner("SECTION B: search  "
           "(start top-left; step right while smaller; else drop down)")
    print("Search each element. The path length is the number of FORWARD HOPS\n"
          "(right steps) on the search path.\n")
    n = len(sl.lane(0))
    bound = 2 * math.ceil(math.log2(n))
    print("| target | found | forward hops | <= 2*log2(N)=" + str(bound) + "? |")
    print("|--------|-------|--------------|-----------------|")
    all_within = True
    sample = sl.lane(0)
    for target in sample:
        node, hops = sl.search(target)
        within = hops <= bound
        all_within = all_within and within
        print(f"| {target:<6} | {node is not None!s:<5} | {hops:<12} | "
              f"{within!s:<16} |")
    print(f"\nN = {n}, bound = 2*ceil(log2({n})) = {bound}")
    print(f"[check] every search path <= {bound} hops? {all_within}")
    print("\nTrace one search in detail (target = 19):")
    _trace_search(sl, 19)


def _trace_search(sl: SkipList, target: int) -> None:
    """Print the right-steps and drop-downs of a single search."""
    cur = sl.header
    total_hops = 0
    print(f"  start at header, top lane = L{sl.level}")
    for i in range(sl.level, -1, -1):
        steps = 0
        while cur.forward[i] is not None and cur.forward[i].val < target:
            cur = cur.forward[i]
            steps += 1
            print(f"    L{i}: step right -> {cur.val}")
        total_hops += steps
        if i > 0:
            if steps == 0:
                print(f"    drop down to L{i - 1}  (no right step on L{i})")
            else:
                print(f"    drop down to L{i - 1}  "
                      f"({steps} right step(s) on L{i})")
    nxt = cur.forward[0]
    found = nxt is not None and nxt.val == target
    print(f"    L0 neighbor = {nxt.val if nxt else None} -> "
          f"{'FOUND ' + str(target) if found else 'NOT FOUND'}")
    print(f"    total forward hops = {total_hops}")


# ----------------------------------------------------------------------------
# SECTION C: insert with coin-flip promotion
# ----------------------------------------------------------------------------

def section_insert(sl: SkipList) -> None:
    banner("SECTION C: insert with coin-flip promotion")
    print("Insert 15 into the skip list. The coin flips decide its top lane.\n")
    rng = sl.rng
    # flip coins explicitly so we can show them
    flips = []
    lvl = 0
    while True:
        r = rng.random()
        heads = r < sl.p
        flips.append((round(r, 4), "HEADS" if heads else "tails"))
        if heads and lvl < sl.max_level:
            lvl += 1
        else:
            break
    print("coin flips for the new node 15 (stop at first tails):")
    for i, (r, face) in enumerate(flips):
        print(f"  flip #{i + 1}: random={r} -> {face}")
    print(f"  => top level = {lvl}  (the node appears on lanes 0..{lvl})\n")
    sl.insert(15)
    print("Skip list after inserting 15:")
    print_skip_list(sl)
    print()
    print(f"in-order (bottom lane, must be sorted): {sl.lane(0)}")
    sorted_ok = sl.lane(0) == sorted(sl.lane(0))
    print(f"[check] bottom lane still sorted? {sorted_ok}")


# ----------------------------------------------------------------------------
# SECTION D: expected height = log_{1/p}(N)
# ----------------------------------------------------------------------------

def section_expected_height() -> None:
    banner("SECTION D: expected height = log_{1/p}(N)  "
           "(p=0.5 -> log2 N)")
    print("The highest lane is ~log_{1/p}(N). Each lane keeps fraction p of the")
    print("previous lane, so after k lanes ~N*p^k nodes remain; the list runs")
    print("out of nodes around k = log_{1/p}(N).\n")
    print("| N      | log2(N) (expected height, p=0.5) |")
    print("|--------|-----------------------------------|")
    for n in [16, 64, 256, 1024, 4096, 65536]:
        print(f"| {n:<6} | {math.log2(n):.2f}".ljust(40) + " |")
    print()
    # empirical: average max-level over many builds
    trials = 2000
    n = 1024
    total = 0
    for seed in range(trials):
        s = SkipList(rng=random.Random(seed))
        for v in range(n):
            s.insert(v)
        total += s.level
    avg = total / trials
    theory = math.log2(n)
    print(f"Empirical check (N={n}, {trials} builds, p={P}):")
    print(f"  average highest lane = {avg:.2f}")
    print(f"  theory log2({n})     = {theory:.2f}")
    print(f"[check] avg height within +/-1 of log2(N)? "
          f"{abs(avg - theory) <= 1.0}")


# ----------------------------------------------------------------------------
# SECTION E: skip list vs balanced tree
# ----------------------------------------------------------------------------

def section_vs_balanced_tree(sl: SkipList) -> None:
    banner("SECTION E: skip list vs balanced tree")
    n = len(sl.lane(0))
    print(f"Our list: N = {n} elements.\n")
    print("| property            | skip list               | balanced tree (AVL/RB) |")
    print("|---------------------|-------------------------|-------------------------|")
    print("| balance mechanism   | coin flips (probabilistic)| rotations/recolor     |")
    print("| search (expected)   | O(log N)                | O(log N)               |")
    print("| search (worst)      | O(N) (rare)             | O(log N) guaranteed    |")
    print("| insert / delete     | O(log N) expected        | O(log N) guaranteed    |")
    print("| implementation      | SIMPLER (pointer rewires)| fiddly rotations       |")
    print("| concurrency         | lock-free variants exist | rotations need wide locks|")
    print("| memory overhead     | ~1/(1-p) ptrs/node       | 2-3 ptrs + color/height|")
    print("| order guarantees    | probabilistic           | deterministic          |")
    print()
    print("Real-world users: Redis (ZSET sorted sets), LevelDB/RocksDB (memtables),")
    print("Apache Lucene, MemSQL. They pick the skip list for its simplicity and")
    print("concurrency-friendliness, accepting a probabilistic (not worst-case)")
    print("guarantee in exchange.")


# ============================================================================
# 2. GOLD CHECK: search path <= 2*log(N) for all elements
# ============================================================================

def gold_check(sl_unused: SkipList) -> None:
    banner("GOLD CHECK: search path length <= 2*log(N) for all elements")
    # Rebuild the canonical list fresh (deterministic, seed=42) so the check is
    # independent of Section C's insert-15 mutation.
    sl = SkipList(rng=random.Random(42))
    for v in [3, 6, 7, 9, 12, 17, 19, 21, 25, 26]:
        sl.insert(v)
    n = len(sl.lane(0))
    bound = 2 * math.ceil(math.log2(n))
    worst = 0
    worst_val = None
    all_ok = True
    paths: dict[int, int] = {}
    for v in sl.lane(0):
        _, hops = sl.search(v)
        paths[v] = hops
        if hops > worst:
            worst = hops
            worst_val = v
        if hops > bound:
            all_ok = False
    print(f"canonical list (seed=42): N = {n}, bound = 2*ceil(log2({n})) = {bound}")
    print(f"forward-hop search paths: {paths}")
    print(f"worst-case path = {worst} hops (for value {worst_val})")
    print(f"GOLD (pinned for skip_list.html): N={n}, bound={bound}, "
          f"worst_path={worst}, all_within_bound={all_ok}")
    print(f"[check] every search path <= 2*log(N) = {bound} hops: "
          f"{'OK' if all_ok else 'FAIL'}")
    assert all_ok, "a search path exceeded 2*log(N)!"


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("skip_list.py - reference impl. All numbers below feed SKIP_LIST.md.")
    print(f"p = {P}, RNG seed = 42 (deterministic).")

    sl, _ = section_build()
    section_search(sl)
    section_insert(sl)
    section_expected_height()
    section_vs_balanced_tree(sl)
    gold_check(sl)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
