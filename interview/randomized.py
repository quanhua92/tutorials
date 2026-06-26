"""
randomized.py - Reference implementation of the Randomized pattern for:
  * Rejection sampling Rand7 -> Rand10   (P470 Implement Rand10 Using Rand7)
  * Virtual Fisher-Yates sampling         (P519 Random Flip Matrix)

This is the SINGLE SOURCE OF TRUTH for RANDOMIZED.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 randomized.py > randomized_output.txt

Pure Python stdlib only. Deterministic (a fixed-seed LCG drives every "random"
value so the .html can reproduce it byte-for-byte).

============================================================================
THE INTUITION (read this first) - convert / shrink
============================================================================
Randomized problems fall into two buckets: generating a NEW uniform distribution
from an existing one, or sampling items WITHOUT replacement. Two flavors cover
the canonical set:

  1. REJECTION SAMPLING (P470 Rand10 from Rand7). Call rand7() twice to lay out
     a uniform 7x7 = 49-cell grid: idx = (row-1)*7 + col gives 1..49, each with
     probability 1/49. To get a uniform 1..10 you need a region whose size is a
     MULTIPLE of 10: the largest such is 40 = 4*10. Accept idx in 1..40 (map
     with (idx-1)%10+1, so each of 1..10 appears exactly 4 times); REJECT
     41..49 and re-roll. Acceptance = 40/49 ~ 81.6%. The trap: NEVER use
     (rand7()+rand7())%10 -- the sum is triangular, biased toward the middle.
     Always use the 2D grid formula (row-1)*Y + col.

  2. VIRTUAL FISHER-YATES (P519 Random Flip Matrix). Sample a zero-cell uniformly
     from an m x n matrix without replacement. A real Fisher-Yates shuffle swaps
     the drawn card with the LAST card, then shrinks the deck by one -- O(1) per
     draw, O(n) space for the array. But m,n up to 10^4 means m*n up to 10^8
     cells: you cannot build that array. The trick: only REMEMBER the swaps in a
     dictionary. To read index k, return mapping.get(k, k). After drawing r, set
     mapping[r] = value-of-last; then delete mapping[last] ONLY IF r != last (or
     you erase the entry you just wrote). Decrement total. This gives O(1) draw,
     O(k) space where k = number of flips so far.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  rejection       sample from an easy distribution (the 49-cell grid), then throw
  sampling        away samples in the overhang (cells 41..49). Unbiased because
                  every accepted cell is equally likely to be PROPOSED.
  acceptance      fraction of proposals kept = 40/49 ~ 0.8163 for Rand7->Rand10.
  rate            expected proposals per Rand10 = 49/40 ~ 1.225; each costs 2
                  Rand7 calls, so ~2.45 Rand7 calls per Rand10.
  uniform         every outcome equally likely. The grid formula (row-1)*Y+col
                  is uniform because each (row,col) pair has probability 1/Y^2.
  multiple-of-    the acceptance cutoff MUST be a multiple of the target. 40 =
  target rule     4*10; accepting up to 42 makes 1 and 2 appear 5/42 while 3..10
                  appear 4/42 -- biased. 49 itself is not a multiple of 10.
  Fisher-Yates    shuffle by swapping the drawn element with the last, then
  shuffle         shrinking the range. O(n) time, O(1) extra space, in place.
  virtual         never materialize the full array -- store only the SWAPS in a
  Fisher-Yates    dict. mapping.get(k, k) reads k (or its swapped-in value).
  reservoir       sample k items uniformly from a stream of unknown length using
  sampling        O(k) space. Related idea: keep item i with prob k/i. P519 is
                  sampling-without-replacement done with virtual Fisher-Yates.

============================================================================
THE SKELETON (both variants share the "stay uniform" mindset)
============================================================================
    # 1. P470: roll a uniform 1..49 grid, accept up to 40 (a multiple of 10)
    def rand10():
        while True:
            row, col = rand7(), rand7()
            idx = (row - 1) * 7 + col        # uniform 1..49
            if idx <= 40:
                return (idx - 1) % 10 + 1    # uniform 1..10
            # else reject 41..49, re-roll

    # 2. P519: virtual Fisher-Yates -- dict remembers only the swaps
    class Solution:
        def __init__(self, m, n):
            self.m, self.n = m, n
            self.total = m * n
            self.mapping = {}
        def flip(self):
            r = randint(0, self.total - 1)
            res = self.mapping.get(r, r)
            last = self.total - 1
            self.mapping[r] = self.mapping.get(last, last)
            if last != r:
                self.mapping.pop(last, None)
            self.total -= 1
            return [res // self.n, res % self.n]
        def reset(self):
            self.total = self.m * self.n
            self.mapping = {}
"""

from __future__ import annotations


# ============================================================================
# DETERMINISTIC PRNG - same LCG in randomized.py and randomized.html (gold-check)
# ============================================================================
def lcg_stream(seed: int = 42):
    """Numerical-Recipes LCG: a=1664525, c=1013904223, m=2^32.

    Yields floats in [0, 1). Reproduced EXACTLY in the .html so every rejection
    trace and every Fisher-Yates swap match byte-for-byte.
    """
    state = seed & 0xFFFFFFFF
    while True:
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        yield state / 4294967296.0


def rand7(rng):
    """Uniform integer in [1, 7] from the LCG stream (the given API)."""
    return int(next(rng) * 7) + 1


# ============================================================================
# TEMPLATE 1 - REJECTION SAMPLING (P470 Implement Rand10 Using Rand7)
# ============================================================================
def rand10(rng):
    """Uniform integer in [1, 10] built only from rand7() calls.

    Two rand7() calls tile a 7x7 = 49-cell uniform grid. Accept the first 40
    cells (a multiple of 10 -> each value 1..10 appears exactly 4 times) and
    reject the 9-cell overhang 41..49, re-rolling. Acceptance = 40/49.

    Time:  O(1) expected (49/40 ~ 1.225 proposals, each 2 rand7 calls)
    Space: O(1)
    """
    while True:
        row = rand7(rng)
        col = rand7(rng)
        idx = (row - 1) * 7 + col          # uniform 1..49
        if idx <= 40:                       # accept: 40 = 4 * 10
            return (idx - 1) % 10 + 1       # uniform 1..10
        # reject 41..49, loop to re-roll


def trace_rejection(proposals: int, seed: int = 42):
    """Record the first `proposals` grid rolls: row, col, flat idx, accept, and
    (if accepted) the resulting Rand10 value. Each proposal consumes 2 rand7."""
    rng = lcg_stream(seed)
    rows = []
    for k in range(1, proposals + 1):
        row = rand7(rng)
        col = rand7(rng)
        idx = (row - 1) * 7 + col
        accept = idx <= 40
        rows.append({
            "proposal": k,
            "row": row,
            "col": col,
            "idx": idx,
            "accept": accept,
            "value": (idx - 1) % 10 + 1 if accept else None,
        })
    return rows


def acceptance_stats(seed: int, trials: int):
    """Empirical acceptance rate of the cutoff over `trials` grid proposals."""
    rng = lcg_stream(seed)
    accepted = 0
    values = {}
    for _ in range(trials):
        idx = (rand7(rng) - 1) * 7 + rand7(rng)
        if idx <= 40:
            accepted += 1
            v = (idx - 1) % 10 + 1
            values[v] = values.get(v, 0) + 1
    return accepted, trials, accepted / trials, values


def build_grid():
    """The full 7x7 grid: each cell's flat idx, accept/reject, and mapped value."""
    grid = []
    for row in range(1, 8):
        line = []
        for col in range(1, 8):
            idx = (row - 1) * 7 + col
            accept = idx <= 40
            line.append({
                "row": row, "col": col, "idx": idx, "accept": accept,
                "value": (idx - 1) % 10 + 1 if accept else None,
            })
        grid.append(line)
    return grid


# ============================================================================
# TEMPLATE 2 - VIRTUAL FISHER-YATES (P519 Random Flip Matrix)
# ============================================================================
class RandomFlipMatrix:
    """Uniformly sample zero-cells of an m x n matrix without replacement.

    Uses virtual Fisher-Yates: a dict remembers only the swaps. Reading index k
    returns mapping.get(k, k). After drawing r, swap it with the value of the
    last live index, then shrink `total`. reset() restores the full deck.
    """

    def __init__(self, m: int, n: int, seed: int = 42):
        self.m = m
        self.n = n
        self.total = m * n
        self.mapping: dict[int, int] = {}
        self._rng = lcg_stream(seed)

    def flip(self) -> list[int]:
        r = int(next(self._rng) * self.total)        # 0..total-1
        res = self.mapping.get(r, r)
        last = self.total - 1
        last_val = self.mapping.get(last, last)
        self.mapping[r] = last_val                     # the swap
        if last != r:                                  # guard: don't erase r
            self.mapping.pop(last, None)
        self.total -= 1
        return [res // self.n, res % self.n]

    def reset(self) -> None:
        self.total = self.m * self.n
        self.mapping = {}
        self._rng = lcg_stream(42)


def trace_flips(m: int, n: int, num_flips: int, seed: int = 42):
    """Step-by-step trace of `num_flips` calls: the drawn index r, the resolved
    value, the last index/val, the resulting mapping, and the (row, col) output.
    Each row mirrors one `flip()` call."""
    obj = RandomFlipMatrix(m, n, seed=seed)
    rows = []
    for k in range(num_flips):
        total_before = obj.total
        r = int(next(obj._rng) * obj.total)
        res = obj.mapping.get(r, r)
        last = obj.total - 1
        last_val = obj.mapping.get(last, last)
        obj.mapping[r] = last_val
        if last != r:
            obj.mapping.pop(last, None)
        obj.total -= 1
        rows.append({
            "step": k + 1,
            "total_before": total_before,
            "r": r,
            "res": res,
            "last_idx": last,
            "last_val": last_val,
            "swapped": last != r,
            "mapping_after": dict(obj.mapping),
            "total_after": obj.total,
            "row": res // n,
            "col": res % n,
        })
    return rows


# ============================================================================
# SECTION A - P470 IMPLEMENT RAND10 USING RAND7 (worked example)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P470 Implement Rand10() Using Rand7  (rejection sampling)")
    print("=" * 72)
    print()
    print("Two rand7() calls tile a uniform 7x7 = 49-cell grid:")
    print("    idx = (row - 1) * 7 + col   ->   uniform in 1..49")
    print("Each (row, col) pair has probability 1/49, so every cell is equally")
    print("likely. To get a uniform 1..10 we accept a region whose size is a")
    print("MULTIPLE of 10: the largest such region inside 49 is 40 = 4*10.")
    print("Accept idx in 1..40 (each value 1..10 appears EXACTLY 4 times),")
    print("REJECT the 9-cell overhang 41..49, and re-roll.")
    print()
    print("The trap: (rand7()+rand7())%10 is a triangular sum, biased toward")
    print("the middle. Always use the grid formula (row-1)*7 + col.")
    print()

    grid = build_grid()
    print("--- the full 7x7 grid (idx | mapped value), accept <= 40 ---")
    print("       col=1   col=2   col=3   col=4   col=5   col=6   col=7")
    for rline in grid:
        cells = []
        for c in rline:
            tag = f"{c['idx']:>2}" if c["accept"] else f"{c['idx']:>2}*"
            cells.append(tag)
        print("  row={} | {:>5}   {:>5}   {:>5}   {:>5}   {:>5}   {:>5}   {:>5}".format(
            rline[0]["row"], *cells))
    print("  (* = rejected overhang 41..49; accept iff idx <= 40)")
    print()

    print("--- accept-zone values: each of 1..10 appears exactly 4 times ---")
    counts = {}
    for rline in grid:
        for c in rline:
            if c["accept"]:
                counts[c["value"]] = counts.get(c["value"], 0) + 1
    for v in range(1, 11):
        bar = "#" * counts[v]
        print(f"  value {v:>2}: {counts[v]} cells  {bar}")
    print(f"  total accepted cells = {sum(counts.values())} = 4 * 10  OK")
    print()

    rows = trace_rejection(12, seed=42)
    print("--- first 12 grid proposals (seed=42) ---")
    print("  proposal | rand7 row | rand7 col | idx  | decision")
    print("  ---------+-----------+-----------+------+-------------------------")
    for r in rows:
        if r["accept"]:
            decision = f"ACCEPT -> Rand10 = {r['value']}"
        else:
            decision = "reject (overhang), re-roll"
        print(f"    {r['proposal']:>2}     |     {r['row']}     |     {r['col']}     "
              f"| {r['idx']:>2}  | {decision}")
    print()

    acc, tot, rate, values = acceptance_stats(42, 100000)
    print(f"--- empirical acceptance over {tot} proposals (seed=42) ---")
    print(f"  accepted = {acc} / {tot} = {rate:.4f}")
    print(f"  theory   = 40/49 = {40/49:.4f}")
    print(f"  relative error = {abs(rate - 40/49) / (40/49) * 100:.2f}%")
    print()
    print("  value distribution among accepted (should be ~uniform, 1/10 each):")
    for v in range(1, 11):
        frac = values.get(v, 0) / acc
        print(f"    value {v:>2}: {values.get(v, 0):>6} ({frac*100:.2f}%)")
    print()

    print("--- expected cost ---")
    print(f"  acceptance = 40/49 ~ {40/49:.4f}")
    print(f"  expected proposals per Rand10 = 49/40 ~ {49/40:.4f}")
    print(f"  each proposal = 2 rand7 calls  ->  ~{2*49/40:.3f} rand7 per Rand10")
    print()


# ============================================================================
# SECTION B - P519 RANDOM FLIP MATRIX (worked example)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P519 Random Flip Matrix  (virtual Fisher-Yates)")
    print("=" * 72)
    print()
    print("Uniformly sample a zero-cell of an m x n matrix without replacement.")
    print("A real Fisher-Yates swap (drawn <-> last, then shrink) is O(1) per")
    print("draw but needs the full m*n array -- impossible for m,n up to 10^4.")
    print("The trick: store ONLY the swaps in a dict. To read index k return")
    print("mapping.get(k, k). After drawing r, set mapping[r] = value-of-last,")
    print("then delete mapping[last] ONLY IF r != last (else you erase the swap")
    print("you just wrote). Decrement total.")
    print()
    print("Decode flat index to (row, col):  row = res // n,  col = res % n")
    print()

    print("--- worked example: m=2, n=3 (6 cells), 4 flips (seed=42) ---")
    rows = trace_flips(2, 3, 4, seed=42)
    print("  step | total |  r  | res | last | last_val | swap? | -> (row,col)")
    print("  -----+-------+-----+-----+------+----------+-------+------------")
    for r in rows:
        sw = "yes" if r["swapped"] else "no (r==last)"
        print(f"   {r['step']}   |   {r['total_before']}   "
              f"| {r['r']:>3} | {r['res']:>3} | {r['last_idx']:>4} "
              f"|   {r['last_val']:>3}    | {sw:<5} | -> [{r['row']}, {r['col']}]")
    print()
    print("  mapping after each step (only swaps are stored):")
    for r in rows:
        print(f"    after flip {r['step']}: total={r['total_after']}, "
              f"mapping={r['mapping_after']}")
    print()

    print("--- the r==last edge case explained ---")
    print("  When the random index r equals total-1 (the last live cell), the")
    print("  swap mapping[r]=last_val would record mapping[last]=last (a no-op")
    print("  value). If you then blindly `del mapping[last]` you DELETE the entry")
    print("  just written, so a future read of r returns r again -> a DUPLICATE")
    print("  draw. The guard `if last != r: del mapping[last]` prevents this.")
    print()

    print("--- larger grid: m=3, n=3 (9 cells), all 9 flips exhausted (seed=42) ---")
    rows9 = trace_flips(3, 3, 9, seed=42)
    drawn = []
    for r in rows9:
        drawn.append((r["row"], r["col"]))
    print("  flip order (row, col): " + " -> ".join(f"({rw},{cl})" for rw, cl in drawn))
    print(f"  unique cells drawn = {len(set(drawn))} / 9  "
          f"({'all distinct OK' if len(set(drawn)) == 9 else 'DUPLICATE BUG'})")
    print()

    print("--- reset restores the full deck ---")
    obj = RandomFlipMatrix(2, 2, seed=1)
    f1 = obj.flip()
    f2 = obj.flip()
    obj.reset()
    total_after_reset = obj.total
    print(f"  m=2,n=2: flip -> {f1}, flip -> {f2}, reset -> total={total_after_reset}, "
          f"mapping={obj.mapping}")
    print(f"  (total back to {obj.m}*{obj.n}={obj.m*obj.n}, mapping cleared)")
    print()


# ============================================================================
# SECTION C - COMPLEXITY, GOTCHAS, PROBLEM TABLE
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - Complexity, killer gotchas, problem table")
    print("=" * 72)
    print()
    print("Complexity")
    print("----------")
    print("  Problem                                Time              Space")
    print("  -------------------------------------- ----------------- ------")
    print("  P470 Rand10 from Rand7 (rejection)     O(1) expected     O(1)")
    print("     ~49/40 = 1.225 proposals per draw, 2 rand7 each")
    print("  P519 Random Flip Matrix (virtual FY)   O(1) per flip     O(k)")
    print("     k = number of flips so far; reset() is O(1)")
    print("  Real Fisher-Yates shuffle              O(n)              O(n)")
    print("  Reservoir sampling (stream, k items)   O(n)              O(k)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. NEVER ADD TWO ROLLS. (rand7()+rand7())%10 is a TRIANGULAR sum")
    print("     heavily biased toward the middle (a 7+7=14 most likely). Always")
    print("     use the 2D grid formula (row-1)*Y + col, which is uniform.")
    print("  2. CUTOFF MUST BE A MULTIPLE OF THE TARGET. For Rand7->Rand10 the")
    print("     cutoff is 40 = 4*10, NOT 42 or 49. Accepting up to 42 makes")
    print("     values 1,2 appear 5/42 while 3..10 appear 4/42. The cutoff is")
    print("     the largest multiple of the target that is <= Y*Y.")
    print("  3. THE r==last ERASURE BUG. In virtual Fisher-Yates, deleting")
    print("     mapping[last] unconditionally will erase the swap you JUST wrote")
    print("     when r happened to equal last, causing a duplicate draw. Always")
    print("     guard with `if last != r: del mapping[last]`.")
    print("  4. DECODE 1D->2D WITH cols, NOT rows. row = x // n, col = x % n")
    print("     where n = number of COLUMNS. Using rows for the modulo scrambles")
    print("     the mapping. (Equivalently: row major, stride = n.)")
    print("  5. SEED FOR DETERMINISM. Judges re-instantiate your object; using")
    print("     a fixed seed makes traces reproducible (and lets the .html match")
    print("     the .py byte-for-byte). On LeetCode use the system random.")
    print("  6. ACCEPTANCE vs ITERATIONS. Rejection sampling is Las Vegas: it")
    print("     always returns the right answer, only the RUNTIME is random.")
    print("     Expected iterations = 1/acceptance = 49/40 ~ 1.225 here.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                          Diff    Key trick")
    print("  -------------------------------- ------- -----------------------------------------")
    print("  P470 Rand10() Using Rand7        Medium  7x7 grid -> 1..49; accept <=40 (mult of 10); (idx-1)%10+1")
    print("  P519 Random Flip Matrix          Medium  Virtual Fisher-Yates; dict swap-with-last; r==last guard")
    print("  P384 Shuffle an Array            Medium  Real Fisher-Yates: swap drawn with last, shrink")
    print("  P382 Linked List Random Node     Medium  Reservoir sampling k=1: keep node i w.p. 1/i")
    print("  P398 Random Pick Index           Medium  Reservoir k=1 over matching indices")
    print("  P528 Random Pick with Weight     Medium  Prefix sums + binary search; randint(1,total)")
    print("  P497 Random Point in Rectangles  Medium  Weighted rect pick; prefix counts + bisect")


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()

    # ---- assertions (mirror LeetCode correctness) ----
    # P470: every Rand10 output is in 1..10
    rng = lcg_stream(42)
    seen = set()
    for _ in range(10000):
        v = rand10(rng)
        assert 1 <= v <= 10
        seen.add(v)
    assert seen == set(range(1, 11)), f"missing values: {set(range(1,11)) - seen}"

    # P470: acceptance within 1% of 40/49 over 100000 trials
    _acc, _tot, _rate, _vals = acceptance_stats(42, 100000)
    assert abs(_rate - 40/49) < 0.01

    # P470: each value appears within 5% of 1/10 among accepts
    for v in range(1, 11):
        assert abs(_vals[v] / _acc - 0.1) < 0.05

    # P470: grid math -- exactly 40 accept cells, each value appears 4 times
    g = build_grid()
    accept_cells = [c for line in g for c in line if c["accept"]]
    assert len(accept_cells) == 40
    from collections import Counter
    vc = Counter(c["value"] for c in accept_cells)
    assert all(vc[i] == 4 for i in range(1, 11))

    # P519: a full exhaustion draws every cell exactly once
    rows = trace_flips(3, 4, 12, seed=42)
    drawn = [(r["row"], r["col"]) for r in rows]
    assert len(set(drawn)) == 12, "duplicate draw detected"
    assert set(drawn) == {(i, j) for i in range(3) for j in range(4)}

    # P519: r==last guard correctness -- never raise, never duplicate
    for seed in range(20):
        rr = trace_flips(2, 3, 6, seed=seed)
        dd = [(r["row"], r["col"]) for r in rr]
        assert len(set(dd)) == 6, f"duplicate for seed {seed}"

    # P519: reset restores the deck
    obj = RandomFlipMatrix(2, 2, seed=1)
    obj.flip(); obj.flip()
    obj.reset()
    assert obj.total == 4 and obj.mapping == {}

    print("=" * 72)
    print("[check] rand10 / random_flip_matrix ... OK")
    print("=" * 72)
