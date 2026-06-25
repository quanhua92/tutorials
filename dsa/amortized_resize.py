"""
amortized_resize.py - Reference implementation: amortized analysis of dynamic
array resizing (the "doubling array").

This is the single source of truth that AMORTIZED_RESIZE.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 amortized_resize.py

==========================================================================
THE INTUITION (read this first) - the concert venue that keeps doubling
==========================================================================
Imagine a concert venue. You don't know how many fans will show up, so you
start with a tiny venue of capacity 1. Every time a new fan arrives and the
venue is FULL, you do the expensive thing: build a venue TWICE as big next
door and move every single fan over. That move is the "resize" - it costs
O(N) on the day it happens.

  * Most days (appends): a fan just walks in. Cheap. O(1).
  * Resize days        : move everyone. O(N). Painful - but RARE.

The magic of AMORTIZED ANALYSIS: spread the painful resize days across all
the cheap days. Even though one day can cost N, the AVERAGE cost per fan is
still constant - O(1) amortized. Why? Because each doubling moves at most N
fans, and you only double once every N arrivals (the venue goes 1->2->4->8).
Total moving over N arrivals = 1+2+4+8+... < 2N. So ~2 moves charged to each
fan, plus the 1 "walk in" = ~3 per fan. Constant.

THE REASON THIS WORKS: the resize cost is a GEOMETRIC series. With growth
factor g, the k-th resize copies g^k elements, but resizes get g times
rarer as the array grows. The series converges, so total copy work is O(N),
i.e. O(1) per append amortized - for ANY constant factor g > 1.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  capacity    : how many slots the array CURRENTLY has allocated ("venue size").
  size / num  : how many elements are actually stored ("fans present").
  full        : size == capacity. The trigger to grow.
  resize      : allocate a new array of different capacity, copy elements over.
  grow        : multiply capacity by the growth factor g when full (make room).
  shrink      : halve capacity when too empty, to reclaim wasted space.
  amortized   : "average over many operations." NOT worst-case. A single op
                can be O(N); the AVERAGE over a sequence is O(1).
  aggregate   : sum ALL actual costs over N ops, then divide by N. Simplest
  method        argument. Gives ~2 per append for doubling (the tight bound).
  accounting  : pre-pay each append $3: $1 for the write, $2 banked to fund
  method        the next resize. Show the bank never goes negative.
  potential   : define Phi = 2*num - capacity. Show Phi >= 0 always, and that
  method        the amortized cost (actual + dPhi) is <= 3 per append.
  thrashing   : add/remove/add/remove at the resize boundary -> every op is a
                resize -> O(N) per op -> O(N^2) total. Cured by a hysteresis
                gap (grow at 100%, shrink at 25%).

==========================================================================
KEY FORMULAS (all verified against CLRS Ch. 17 + asserted in code)
==========================================================================
    Doubling copies for N appends (N = 2^k):  1+2+4+...+2^(k-1) = N-1
    Total ops for N appends (N = 2^k):        copies + writes = (N-1) + N = 2N-1
    Amortized cost per append (aggregate):    (2N-1)/N -> 2   [N = power of 2]
    Accounting method charge:                 3 per append  (1 write + 2 banked)
    Potential function (insertion-only):      Phi(D) = 2*num - capacity  (Phi >= 0)
    Amortized cost via potential:             a = actual + dPhi <= 3, every append
    Growth factor g > 1, asymptotic:          copies ~ N/(g-1); amortized ops = g/(g-1)
        g=2.0  -> 2.0   (max waste 50%, fill range 0.5 - 1.0)
        g=1.5  -> 3.0   (max waste 33%, fill range 0.667 - 1.0)
        g=1.25 -> 5.0   (max waste 20%, fill range 0.8 - 1.0)
    Shrink threshold (avoid thrashing):       halve when num <= capacity/4 (25%)

Reference: CLRS, Introduction to Algorithms, 3rd ed., Chapter 17
"Amortized Analysis" (17.1 aggregate, 17.2 accounting, 17.3 potential,
17.4 dynamic tables). Also Sedgewick & Wayne, Algorithms 4th ed., 1.1.

Conventions: capacity and size are integers; growth uses math.ceil(cap*g) so
the result is always an integer >= cap+1 for any g > 1 (guarantees progress).
"""

from __future__ import annotations

import math

BANNER = "=" * 72


# ============================================================================
# 1. THE SIMULATOR  (the model every section below is built on)
# ============================================================================

def simulate_appends(n: int, growth: float = 2.0) -> list[tuple]:
    """Simulate `n` appends into a dynamic array with growth factor `growth`.

    Rule: start capacity = 1. Before each append, if the array is FULL
    (size == capacity), grow: capacity = ceil(capacity * growth), and the
    growth is paid by COPYING all `size` elements into the new array. Then
    write the new element (size += 1).

    Returns a list of per-append records:
        (i, size_after, cap_after, copies, write)
    where `copies` is the resize copy cost (0 if no resize) and `write` is 1.
    """
    cap = 1
    size = 0
    recs = []
    for i in range(1, n + 1):
        copies = 0
        if size == cap:                                  # FULL -> grow first
            new_cap = max(cap + 1, math.ceil(cap * growth))
            copies = size                                # move everyone over
            cap = new_cap
        size += 1                                        # the write
        recs.append((i, size, cap, copies, 1))
    return recs


def simulate_dyn(ops, growth=2.0, shrink_threshold=0.5):
    """Simulate a sequence of 'add'/'del' ops with BOTH grow and shrink.

    Grow  : on 'add', if full (size == cap), cap = ceil(cap*growth), copy size.
    Shrink: on 'del', after size--, if size <= cap*shrink_threshold and cap>1,
            halve the capacity (cap = cap // 2), copy the surviving `size`.

    Returns (total_copies, n_grow, n_shrink, size, cap). Used by Section E to
    expose thrashing vs the 25% hysteresis cure.
    """
    cap = 1
    size = 0
    copies = 0
    n_grow = 0
    n_shrink = 0
    for op in ops:
        if op == "add":
            if size == cap:
                copies += size
                cap = max(cap + 1, math.ceil(cap * growth))
                n_grow += 1
            size += 1
        else:                                            # "del"
            size -= 1
            if cap > 1 and size <= cap * shrink_threshold:
                cap = max(1, cap // 2)
                copies += size
                n_shrink += 1
    return copies, n_grow, n_shrink, size, cap


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: doubling strategy (aggregate method)
# ----------------------------------------------------------------------------
def section_doubling():
    banner("SECTION A: doubling strategy - append 16 into a capacity-1 array")
    N = 16
    recs = simulate_appends(N, growth=2.0)
    print("Rule: start capacity = 1; before each append, if FULL (size == cap)")
    print("DOUBLE the capacity and copy every element over. Then write the new\n"
          "element. This is the AGGREGATE METHOD: just add up every cost.\n")
    print("| append# | size | capacity | resize? | copies | write | step cost |")
    print("|---------|------|----------|---------|--------|-------|-----------|")
    total_copies = 0
    total_ops = 0
    for (i, size, cap, copies, write) in recs:
        resized = "YES x2" if copies > 0 else "no"
        step = copies + write
        total_copies += copies
        total_ops += step
        mark = "   <-- RESIZE (O(N) day)" if copies > 0 else ""
        print(f"| {i:<7} | {size:<4} | {cap:<8} | {resized:<7} | {copies:<6} | "
              f"{write:<5} | {step:<9} |{mark}")
    print()
    print(f"Capacity over time: 1, 2, 4, 4, 8, 8, 8, 8, 16, 16 x8")
    print(f"Resizes happen at append# 2,3,5,9 -> copy costs 1,2,4,8.\n")
    print(f"Total copies = 1 + 2 + 4 + 8 = {total_copies}")
    print(f"             = N - 1 = {N - 1}   (exact, because N = {N} is a power of 2)")
    print(f"Total writes = {N}")
    print(f"Total ops    = copies + writes = {total_copies} + {N} = {total_ops}")
    print(f"Amortized    = total / N      = {total_ops} / {N} = {total_ops / N:.4f}  ->  O(1)")
    print()
    print("The worst SINGLE step costs 8 (the i=9 copy of the full 8-slot array).")
    print("But resizes are RARE and get 2x rarer as the array grows (only 4 of them")
    print("for 16 appends). Spread the rare pain across all 16 appends and the")
    print("AVERAGE is ~2 - a constant, independent of N. That is amortized O(1).")
    # GOLD CHECK
    assert total_copies == N - 1, f"copies should be N-1 for power-of-2 N, got {total_copies}"
    assert total_ops == 2 * N - 1, f"total should be 2N-1, got {total_ops}"
    print(f"\n[check] copies == N-1 ({N - 1})? OK ; total ops == 2N-1 ({2 * N - 1})? OK")


# ----------------------------------------------------------------------------
# SECTION B: accounting method (charge 3, watch the bank)
# ----------------------------------------------------------------------------
def section_accounting():
    banner("SECTION B: accounting method - charge $3 per append, watch the bank")
    N = 16
    recs = simulate_appends(N, growth=2.0)
    print("Charge a flat $3 for EVERY append, cheap or expensive:\n"
          "   $1 pays the immediate write of the new element\n"
          "   $2 is BANKED as credit to fund a future resize copy.\n"
          "Actual cost of an append = (copies if resize) + 1 write.\n"
          "Bank balance = sum(charges) - sum(actual costs). The proof is that the\n"
          "bank balance NEVER goes negative.\n")
    print("| append# | actual cost | charge | d bank | bank balance | note |")
    print("|---------|-------------|--------|--------|--------------|------|")
    bank = 0
    min_bank = None
    for (i, size, cap, copies, write) in recs:
        actual = copies + write
        charge = 3
        bank = bank + charge - actual
        if min_bank is None or bank < min_bank:
            min_bank = bank
        note = "RESIZE paid from credit" if copies > 0 else "cheap: bank += $2"
        print(f"| {i:<7} | {actual:<11} | {charge:<6} | {charge - actual:+d} | "
              f"{bank:<12} | {note} |")
    print()
    print(f"Bank balance is ALWAYS >= 0 (minimum observed = ${min_bank}).")
    print(f"=> the $3 charge per append fully funds every resize.")
    print(f"=> amortized cost per append <= 3  ->  O(1).")
    print()
    print("WHY $3 is exactly enough: right before a resize that copies m elements,")
    print("the m/2 MOST-recently inserted elements each still hold their $2 of")
    print("banked credit = $m total - precisely the m copies owed. The older m/2")
    print("elements' credit already paid the PREVIOUS resize, so the bank never")
    print("runs dry. (The leftover slack is why the minimum balance is $2, not $0.)")
    assert min_bank >= 0
    print(f"\n[check] min bank balance (${min_bank}) >= 0? OK")


# ----------------------------------------------------------------------------
# SECTION C: potential method (Phi = 2*num - capacity, amortized <= 3)
# ----------------------------------------------------------------------------
def section_potential():
    banner("SECTION C: potential method - Phi = 2*num - capacity, amortized <= 3")
    N = 16
    recs = simulate_appends(N, growth=2.0)
    print("Define the potential of a table state:   Phi(D) = 2*num - capacity.")
    print("Set Phi(empty) = 0. The amortized cost of append i is then\n"
          "   a_i = actual_cost_i + Phi_i - Phi_{i-1}.\n"
          "We show (1) Phi >= 0 always so the bound is valid, and (2) a_i <= 3\n"
          "for every step, so sum(actual) <= 3*N -> O(1) amortized.\n")
    print("| append# | num | cap | Phi_prev | actual | Phi_curr |  dPhi | a=actual+dPhi |")
    print("|---------|-----|-----|----------|--------|----------|-------|---------------|")
    prev_phi = 0                                         # Phi(empty) = 0
    min_phi = prev_phi
    max_amort = 0
    for (i, size, cap, copies, write) in recs:
        actual = copies + write
        phi = 2 * size - cap
        dphi = phi - prev_phi
        amort = actual + dphi
        max_amort = max(max_amort, amort)
        if phi < min_phi:
            min_phi = phi
        print(f"| {i:<7} | {size:<3} | {cap:<3} | {prev_phi:<8} | {actual:<6} | "
              f"{phi:<8} | {dphi:+5d} | {amort:<13} |")
        prev_phi = phi
    print()
    print(f"Phi is ALWAYS >= 0 (minimum = {min_phi}, at the empty table Phi = 0).")
    print(f"Every amortized cost a_i <= {max_amort}. In fact:")
    print(f"   * cheap step  (no resize): actual = 1,  dPhi = +2  -> a = 3")
    print(f"   * resize step (copy k)   : actual = k+1, dPhi = 2-k -> a = 3")
    print(f"   (the very first append has a = 2 because Phi(empty) = 0, not -1)")
    print(f"=> sum(actual) = sum(a) - (Phi_N - Phi_0) <= 3*N - Phi_N + Phi_0 <= 3*N")
    print(f"=> O(1) amortized. The potential 'stored up' on cheap steps pays the bill")
    print(f"   on resize steps: a resize SPIKES actual cost but dPhi is large and")
    print(f"   NEGATIVE, cancelling the spike exactly.")
    assert min_phi >= 0
    assert max_amort <= 3
    print(f"\n[check] Phi >= 0 (min {min_phi})? OK ; a_i <= 3 (max {max_amort})? OK")


# ----------------------------------------------------------------------------
# SECTION D: growth factor comparison (2x vs 1.5x vs 1.25x)
# ----------------------------------------------------------------------------
def section_growth_factors():
    banner("SECTION D: growth factor - 2x vs 1.5x vs 1.25x (all O(1) amortized)")
    N = 1024
    print(f"Simulate {N} appends for each factor. Theory: copy work is a geometric\n"
          f"series summing to ~N/(g-1), so amortized ops/append = 1 + 1/(g-1) = g/(g-1).\n"
          f"Space: just after a resize the array is ~1/g full, then grows to full,\n"
          f"so the fill ratio ranges [1/g, 1.0] and max wasted space = 1 - 1/g.\n")
    print("| factor g | resizes | total copies | total ops | amortized (sim) | "
          "amortized g/(g-1) | max waste | fill range  |")
    print("|----------|---------|--------------|-----------|-----------------|"
          "-------------------|-----------|-------------|")
    for g in (2.0, 1.5, 1.25):
        recs = simulate_appends(N, growth=g)
        resizes = sum(1 for r in recs if r[3] > 0)
        copies = sum(r[3] for r in recs)
        ops = copies + N
        amort_sim = ops / N
        amort_th = g / (g - 1)
        waste = (1 - 1 / g) * 100
        filllo = 1 / g
        print(f"| {g:<8} | {resizes:<7} | {copies:<12} | {ops:<9} | "
              f"{amort_sim:<15.3f} | {amort_th:<17.3f} | {waste:6.1f}%  | "
              f"{filllo:.3f}-1.000   |")
    print()
    print("Read the table three ways:")
    print("  * Bigger g  -> FEWER resizes, but MORE wasted space on average.")
    print("    g=2.0 wastes up to 50% (half the array can sit empty).")
    print("    g=1.5 wastes up to 33%; g=1.25 only 20%.")
    print("  * Smaller g -> MORE frequent resizes, so a HIGHER amortized constant,")
    print("    but it is still a CONSTANT (g/(g-1)). O(1) for ANY g > 1.")
    print("  * g=2.0 keeps pointers/indices valid-ish in low bits and gives the")
    print("    lowest amortized constant (2). g=1.5 wastes less memory. Most")
    print("    production allocators (Java ArrayList, C++ vector, Python list) use")
    print("    ~1.5x-2x as the engineering sweet spot.")
    # sanity: each factor's sim amortized is within 0.5 of the asymptotic
    for g in (2.0, 1.5, 1.25):
        recs = simulate_appends(N, growth=g)
        amort_sim = (sum(r[3] for r in recs) + N) / N
        assert abs(amort_sim - g / (g - 1)) < 0.5, f"sim far from asymptotic for g={g}"
    print("\n[check] simulated amortized within 0.5 of g/(g-1) for all factors? OK")


# ----------------------------------------------------------------------------
# SECTION E: shrink threshold (thrashing at 50%, safe at 25%)
# ----------------------------------------------------------------------------
def section_shrink():
    banner("SECTION E: shrink threshold - halving at 25% beats 50% (no thrashing)")
    buildup = ["add"] * 16                              # grow to size=16, cap=16
    pairs = ["add", "del"] * 8                          # 8 add/remove pairs at the edge
    print("Build the array up with 16 appends (size=16, cap=16). Then hammer it\n"
          "with 8 (add, del) pairs right at the full boundary - the worst case for\n"
          "thrashing. Compare shrinking at 50% fill vs the safe 25% hysteresis.\n")
    print("| shrink at | build copies | build resizes | alternating copies | "
          "alt resizes | total copies | total ops | verdict")
    print("|-----------|--------------|---------------|--------------------|"
          "-------------|--------------|-----------|--------")
    for thr, label in ((0.5, "50% (cap/2)"), (0.25, "25% (cap/4)")):
        # build phase only (so we can report it separately)
        cb, gb, sb, sb_, cb_ = simulate_dyn(buildup, shrink_threshold=thr)
        # full run: build + alternating
        ctot, gtot, stot, size_f, cap_f = simulate_dyn(buildup + pairs, shrink_threshold=thr)
        alt_copies = ctot - cb
        alt_resizes = (gtot + stot) - (gb + sb)
        total_ops = ctot + len(buildup + pairs)
        verdict = ("THRASH: O(N)/op" if thr == 0.5
                   else "SAFE: O(1)/op")
        print(f"| {label:<9} | {cb:<12} | {gb + sb:<13} | {alt_copies:<18} | "
              f"{alt_resizes:<11} | {ctot:<12} | {total_ops:<9} | {verdict}")
    print()
    print("WHAT HAPPENS (shrink at 50%):")
    print("  size=16, cap=16 -> add: grow to cap=32, copy 16.")
    print("                 -> del: size=16 = cap/2 -> shrink to cap=16, copy 16.")
    print("  Every (add, del) pair costs 32 copies. 8 pairs = 256 copies. Each op is")
    print("  O(N) here, so N such ops cost O(N^2). This is THRASHING.\n")
    print("WHAT HAPPENS (shrink at 25%):")
    print("  size=16, cap=16 -> add: grow to cap=32, copy 16 (the only resize). Now")
    print("  cap/4 = 8.")
    print("                 -> del: size=16, way above 8 -> NO shrink.")
    print("  After that one grow, add/del oscillates between size 16 and 17 with")
    print("  cap=32: ZERO further resizes. The 25% rule leaves a HYSTERESIS GAP")
    print("  (25%..100%): a single add or del cannot cross BOTH thresholds, so the")
    print("  table never ping-pongs. CLRS 17.4 proves add+del are then both O(1).")
    # GOLD CHECK: 50% thrashes (a shrink every pair); 25% never shrinks in steady state
    cb50 = simulate_dyn(buildup, shrink_threshold=0.5)
    cf50 = simulate_dyn(buildup + pairs, shrink_threshold=0.5)
    cb25 = simulate_dyn(buildup, shrink_threshold=0.25)
    cf25 = simulate_dyn(buildup + pairs, shrink_threshold=0.25)
    alt50_copies = cf50[0] - cb50[0]
    alt25_copies = cf25[0] - cb25[0]
    alt50_shrinks = cf50[2] - cb50[2]   # shrink count in alternating phase
    alt25_shrinks = cf25[2] - cb25[2]
    assert alt50_copies == 256, f"expected 256 alt copies at 50%, got {alt50_copies}"
    assert alt50_shrinks == 8, f"expected 8 alt shrinks at 50%, got {alt50_shrinks}"
    assert alt25_shrinks == 0, f"expected 0 alt shrinks at 25%, got {alt25_shrinks}"
    print(f"\n[check] 50%: {alt50_copies} alt copies + {alt50_shrinks} shrinks (thrash)? OK")
    print(f"[check] 25%: {alt25_copies} alt copies + {alt25_shrinks} shrinks (safe)? OK")


# ----------------------------------------------------------------------------
# GOLD: the compact values the .html recomputes and checks against
# ----------------------------------------------------------------------------
def section_gold():
    banner("GOLD VALUES (pinned for amortized_resize.html)")
    N = 16
    recs = simulate_appends(N, growth=2.0)
    caps = [r[2] for r in recs]
    copies_seq = [r[3] for r in recs]
    total_copies = sum(copies_seq)
    total_ops = total_copies + N
    print(f"N = {N} appends, growth factor = 2.0 (doubling)\n")
    print(f"capacity trace  = {caps}")
    print(f"copy cost trace = {copies_seq}")
    print(f"resize steps    = append# {[r[0] for r in recs if r[3] > 0]}")
    print(f"total copies    = {total_copies}    (== N-1 = {N - 1})")
    print(f"total writes    = {N}")
    print(f"total ops       = {total_ops}   (== 2N-1 = {2 * N - 1})")
    print(f"amortized/append= {total_ops / N:.4f}  (-> 2)\n")
    print("GOLD scalar for .html: total_copies = 15, total_ops = 31.")
    assert total_copies == 15
    assert total_ops == 31
    print("[check] GOLD reproduces from simulate_appends(16, 2.0)? OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("amortized_resize.py - reference impl. All numbers below feed")
    print("AMORTIZED_RESIZE.md. python stdlib only.\n")

    section_doubling()
    section_accounting()
    section_potential()
    section_growth_factors()
    section_shrink()
    section_gold()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
