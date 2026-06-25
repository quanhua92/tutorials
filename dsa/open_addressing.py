"""
open_addressing.py - Reference implementation: open-addressing hash tables
(linear probing, quadratic probing, double hashing) and their collision costs.

This is the single source of truth that OPEN_ADDRESSING.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 open_addressing.py

==========================================================================
THE INTUITION (read this first) - the coat-check room with one row of hooks
==========================================================================
Imagine a coat-check room with `m` hooks numbered 0..m-1 in a single row. You
hand a coat to the attendant; the attendant computes a "home hook" from the
coat's tag number and hangs it there. What happens when that home hook is
already taken?

  * Separate chaining : hang the second coat on the SAME hook (a little stack
                        of coats per hook). Many coats can share a hook.
  * Open addressing    : NO stacking. The attendant WALKS DOWN THE ROW looking
                        for the next empty hook. The coat lives in that empty
                        hook. There is exactly one coat per hook, always.

The WALK is the "probe sequence." Three famous walks:

  * Linear probing    : take steps of size 1.    home, home+1, home+2, ...
  * Quadratic probing : take steps of size 1,4,9,16,... (i^2).  home, home+1,
                         home+4, home+9, ...
  * Double hashing    : step size comes from a SECOND hash of the key.
                         home, home+h2, home+2*h2, ...

THE LOAD FACTOR alpha = n/m = coats/hooks. Open addressing REQUIRES alpha < 1
(the row must have an empty hook somewhere), and it HURTS fast as alpha -> 1.
The expected number of hooks the attendant walks (probes) under UNIFORM HASHING
is the central formula:

     unsuccessful search:   1 / (1 - alpha)
     successful   search:   (1 / alpha) * ln( 1 / (1 - alpha) )

At alpha = 0.75 that is 4.00 and 1.85 probes. At alpha = 0.99 it blows up to
100 and 4.65. Keep alpha <= ~0.75 by resizing (rehashing) the row. The formula
is EXACT only under uniform hashing; of the three walks, DOUBLE HASHING comes
closest, LINEAR PROBING is worst (it builds contiguous "primary clusters").

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  m           : number of slots (hooks). Prime is preferred (helps quadratic
                and double hashing reach every slot).
  n           : number of stored keys (coats).
  alpha       : load factor = n/m. Must stay < 1 for open addressing. We
                resize (rehash to a bigger m) before it hits ~0.75.
  home slot   : h1(k), the first hook the attendant tries.
  probe       : one look at a slot. Counting probes = counting the cost.
  probe seq   : the ordered list of slots tried: home, then step, 2*step, ...
  collision   : home slot occupied by a DIFFERENT key -> must probe.
  primary cluster : a long CONTIGUOUS run of occupied slots (linear probing
                builds these; they make every nearby insertion walk the whole
                run). THE disease of linear probing.
  secondary cluster: all keys with the SAME home slot follow the SAME probe
                sequence (quadratic probing still has this; double hashing
                cures it by making the step depend on the key).
  tombstone   : a slot left "DELETED" (not "EMPTY") after a removal, so search
                knows to keep probing past it. Reused on a later insert.
  uniform hashing : the IDEALIZED assumption that every key's probe sequence is
                equally likely to be any permutation of the slots. Real
                strategies only APPROXIMATE this. The 1/(1-alpha) formula is
                EXACT under uniform hashing; double hashing comes closest.

==========================================================================
THE THREE PROBE SEQUENCES (all mod m)
==========================================================================
  linear:     h(k, i) = ( h1(k) + i )          mod m,   i = 0,1,2,...
  quadratic:  h(k, i) = ( h1(k) + i^2 )        mod m,   i = 0,1,2,...
  double:     h(k, i) = ( h1(k) + i * h2(k) )  mod m,
                        h2(k) = 1 + (k mod (m-1))   -> coprime to prime m

KEY FORMULAS (verified against CLRS Ch.11 + asserted in code):
  uniform hashing, unsuccessful search:   ~ 1/(1-alpha)        (Theorem 11.6)
  uniform hashing, successful   search:   ~ (1/alpha) ln(1/(1-alpha))
  linear probing,   unsuccessful:         ~ (1/2)(1 + 1/(1-alpha)^2)
  linear probing,   successful:           ~ (1/2)(1 + 1/(1-alpha)  )
  quadratic probing reaches all slots if: alpha < 1/2   (m prime, first m/2)
  double hashing reaches all slots if:    gcd(h2, m) == 1  (m prime, h2 in 1..m-1)
  resize trigger:                         alpha >= 0.75  -> rehash to ~2*m

Reference: CLRS, Introduction to Algorithms, 3rd ed., Ch.11 Hash Tables,
  11.4 open addressing (11.4.1 linear, 11.4.2 quadratic, 11.4.3 double
  hashing, Theorem 11.6 uniform-hashing probe bound). Sedgewick & Wayne,
  Algorithms 4th ed., 3.4 Hash Tables (linear probing cost model).

Conventions: slots hold one of None (EMPTY), a key int (FULL), or TOMB
  (DELETED). All tables are prime size m. Deterministic LCG keys so the .html
  can replicate every number byte-for-byte.
"""

from __future__ import annotations

import math

BANNER = "=" * 72
TOMB = -1  # tombstone sentinel for lazy deletion (EMPTY is None, FULL is an int key)

M = 13     # table size for the worked example (prime)


# ============================================================================
# 1. THE HASH FUNCTIONS + PROBE SEQUENCES  (the model every section uses)
# ============================================================================

def h1(k: int, m: int = M) -> int:
    """Primary hash = home slot."""
    return k % m


def h2(k: int, m: int = M) -> int:
    """Secondary hash = double-hashing step. In [1, m-1]; coprime to prime m,
    so the probe sequence visits every slot before repeating."""
    return 1 + (k % (m - 1))


def seq_linear(k: int, m: int = M) -> list[int]:
    """Linear probe sequence: home, home+1, home+2, ... (mod m)."""
    home = h1(k, m)
    return [(home + i) % m for i in range(m)]


def seq_quad(k: int, m: int = M) -> list[int]:
    """Quadratic probe sequence: home, home+1, home+4, home+9, ... (mod m).
    With prime m the first m//2 probes are distinct (so alpha < 1/2 always
    finds a slot)."""
    home = h1(k, m)
    return [(home + i * i) % m for i in range(m)]


def seq_double(k: int, m: int = M) -> list[int]:
    """Double-hashing probe sequence: home, home+step, home+2*step, ...
    (mod m), step = h2(k). Different keys with the same home get different
    steps, so their sequences diverge -> no secondary clustering."""
    home = h1(k, m)
    step = h2(k, m)
    return [(home + i * step) % m for i in range(m)]


def oa_insert(table: list, key: int, seq: list[int], m: int = M):
    """Insert `key` along probe sequence `seq`. Returns (slot, probes).

    Tombstone rule: remember the FIRST tombstone seen; keep probing to EMPTY
    (so a duplicate key is detected and the table's "full along this sequence"
    is known); on reaching EMPTY, fill the remembered tombstone if any, else
    fill the EMPTY slot. Probes = slots examined.
    """
    first_tomb = -1
    for probes, j in enumerate(seq, start=1):
        cell = table[j]
        if cell is None:                                   # EMPTY -> place here
            slot = first_tomb if first_tomb != -1 else j
            table[slot] = key
            return slot, probes
        if cell == TOMB:                                   # tombstone: note, keep going
            if first_tomb == -1:
                first_tomb = j
        elif cell == key:                                  # already present
            return j, probes
    if first_tomb != -1:                                   # only tombstones left
        table[first_tomb] = key
        return first_tomb, m
    return -1, m                                           # full


def oa_search(table: list, key: int, seq: list[int], m: int = M):
    """Search `key` along `seq`. Returns (slot or -1, probes). A tombstone does
    NOT stop the search (the key may sit past it); only EMPTY stops it."""
    for probes, j in enumerate(seq, start=1):
        cell = table[j]
        if cell is None:                                   # EMPTY -> not present
            return -1, probes
        if cell == key:                                    # found
            return j, probes
        # tombstone or other key -> keep probing
    return -1, m


def oa_delete(table: list, key: int, seq: list[int], m: int = M):
    """Lazy delete: search, then mark the slot TOMB (not EMPTY), so later
    searches still probe through it. Returns (slot or -1, probes)."""
    j, probes = oa_search(table, key, seq, m)
    if j != -1:
        table[j] = TOMB
    return j, probes


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_cell(c):
    if c is None:
        return "--"
    if c == TOMB:
        return "~~"
    return str(c)


def print_table(table, m=M, highlight=None):
    """Print the table as two rows: slot index, then contents."""
    highlight = highlight or set()
    idx = " ".join(f"{j:>4}" for j in range(m))
    cells = " ".join(
        (f"[{fmt_cell(table[j]):>2}]" if j in highlight else f" {fmt_cell(table[j]):>2} ")
        for j in range(m)
    )
    print(f"  slot : {idx}")
    print(f"  key  : {cells}")


def fmt_seq(seq, n=None):
    """Pretty-print a probe sequence like 5 -> 6 -> 7 (mod ...)."""
    if n is None:
        n = len(seq)
    return " -> ".join(str(s) for s in seq[:n])


# ============================================================================
# 3. A DETERMINISTIC KEY STREAM  (glibc LCG, mod 2^31; trivial to replicate
#    byte-for-byte in JavaScript for the .html gold check)
# ============================================================================

def lcg_stream(seed: int = 42):
    """Park-Miller MINSTD: x = (16807 * x) mod (2^31 - 1). Full period
    2^31 - 2, outputs in [1, 2^31-2]. Crucially the product 16807*x stays
    below 2^53 (max ~3.6e13), so it is EXACT in JavaScript doubles -- the
    .html can replicate this stream byte-for-byte. (The glibc LCG's
    1103515245*x overflows 2^53 and would diverge in JS, so it is NOT used.)
    Used for the empirical probe-count study (Section E)."""
    x = seed % 2147483647
    if x == 0:
        x = 1
    while True:
        x = (16807 * x) % 2147483647
        yield x


# ============================================================================
# 4. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: linear probing insert / search / delete (with tombstones), alpha=0.75
# ----------------------------------------------------------------------------
def section_linear():
    banner("SECTION A: linear probing - insert / search / delete  (m=13, alpha->0.75)")
    m = M
    keys = [10, 22, 31, 4, 15, 28, 17, 88, 59, 36]   # 10 keys -> alpha = 10/13 = 0.769
    table = [None] * m
    print("Home slot h1(k) = k % m, with m = 13 (prime). Linear probing probes\n"
          "home, home+1, home+2, ... until an EMPTY slot. Tombstones (~~) are left\n"
          "on delete so search keeps probing past them.\n")
    print("| step | key  | h1(k) | probe sequence        | lands | probes | note |")
    print("|------|------|-------|-----------------------|-------|--------|------|")
    total = 0
    for step, k in enumerate(keys, start=1):
        seq = seq_linear(k, m)
        slot, probes = oa_insert(table, k, seq, m)
        total += probes
        walked = fmt_seq(seq, probes)
        note = "collision" if probes > 1 else "home free"
        print(f"| {step:<4} | {k:<4} | {h1(k, m):<5} | {walked:<21} | {slot:<5} | "
              f"{probes:<6} | {note} |")
    n = len(keys)
    alpha = n / m
    print(f"\n  table after {n} inserts (alpha = {n}/{m} = {alpha:.3f}):")
    print_table(table, m)
    print(f"\n  total probes to build = {total}  (avg {total / n:.2f} per insert)")

    print("\n  SEARCHES (a successful + an unsuccessful one):")
    # 36 is at slot 12 after 3 probes; finding it costs the same 3 probes.
    # 8 is not in the table -> unsuccessful; its home slot 8 is EMPTY.
    for k in (36, 8):
        seq = seq_linear(k, m)
        j, probes = oa_search(table, k, seq, m)
        verdict = f"FOUND at slot {j}" if j != -1 else "NOT PRESENT"
        print(f"    search {k:>3}: h1={h1(k, m):>2}, seq {fmt_seq(seq, probes)} "
              f"-> {verdict} in {probes} probe(s)")
    print("    (search 8 is cheap: its home slot 8 is EMPTY, so it stops at once.")
    print("     A search for a missing key whose home is INSIDE the big cluster")
    print("     2..7 would walk all 6 slots before hitting EMPTY at 8 -- the")
    print("     primary-cluster tax. See Section B.)")

    print("\n  DELETE with tombstones (lazy deletion):")
    # delete 31 (slot 5) -> tombstone; search 17 (slot 6) still works through it
    j31, p31 = oa_delete(table, 31, seq_linear(31, m), m)
    print(f"    delete 31: slot {j31} marked TOMB (~~) after {p31} probe(s).")
    print(f"    table now:")
    print_table(table, m, highlight={5})
    j17, p17 = oa_search(table, 17, seq_linear(17, m), m)
    print(f"    search 17 again: probes 4 -> 5(~~, keep going) -> 6(FOUND) = "
          f"{p17} probes.")
    print(f"      the tombstone at 5 does NOT stop the search; 17 sits past it.")
    # insert 44 (h1=5): probes past the tombstone to EMPTY (slot 8) to confirm 44
    # is not already further along, THEN fills the remembered tombstone at 5.
    slot44, p44 = oa_insert(table, 44, seq_linear(44, m), m)
    print(f"    insert 44: h1=5 -> 5(~~, remember) -> 6 -> 7 -> 8(EMPTY, stop) = "
          f"{p44} probes, then fills the tombstone at slot {slot44}.")
    print(f"      tombstones keep search correct (probe through them) AND let a")
    print(f"      later insert reclaim the dead slot instead of fragmenting the row.")
    print(f"    table now:")
    print_table(table, m, highlight={5})
    # GOLD CHECKS
    assert total == 16, f"expected total build probes 16, got {total}"
    assert oa_search(table, 17, seq_linear(17, m), m)[0] == 6
    assert table[5] == 44 and p44 == 4
    print(f"\n[check] build probes == 16? OK ; 17 still at slot 6 after delete? OK ; "
          f"44 reused tomb at slot 5 after 4 probes? OK")


# ----------------------------------------------------------------------------
# SECTION B: primary clustering (linear probing builds contiguous runs)
# ----------------------------------------------------------------------------
def section_primary_cluster():
    banner("SECTION B: primary clustering - linear probing builds a wall")
    m = M
    cluster_keys = [18, 31, 44, 57, 70, 83]   # all have h1 = 18%13 = 5
    table = [None] * m
    print("Insert 6 keys that ALL hash to slot 5 (18,31,44,57,70,83; each is "
          f"5 mod {m}).\nLinear probing packs them CONTIGUOUSLY: 5,6,7,8,9,10. "
          "Each insert walks one step further:\n")
    print("| insert# | key | home | probes | walks through        | lands |")
    print("|---------|-----|------|--------|----------------------|-------|")
    for i, k in enumerate(cluster_keys, start=1):
        seq = seq_linear(k, m)
        slot, probes = oa_insert(table, k, seq, m)
        walked = fmt_seq(seq, probes)
        print(f"| {i:<7} | {k:<3} | {h1(k, m):<4} | {probes:<6} | {walked:<20} | {slot:<5} |")
    print(f"\n  table after the 6 inserts:")
    print_table(table, m)
    print(f"\n  slots 5..10 are a CONTIGUOUS block of 6 (the primary cluster).")
    print(f"  total probes = 1+2+3+4+5+6 = 21   (vs 6 if no clustering!).")

    print("\n  THE TAX - now insert a NEW key whose home is INSIDE the cluster:")
    victim = 6                                  # h1(6) = 6, sits inside 5..10
    seq = seq_linear(victim, m)
    slot, probes = oa_insert(table, victim, seq, m)
    print(f"    insert {victim}: h1 = {h1(victim, m)}. The walk is "
          f"{fmt_seq(seq, probes)} -> lands at {slot}.")
    print(f"    => {probes} probes, walking PAST the whole cluster (6,7,8,9,10,11).")
    print(f"    THIS is primary clustering: one nearby home pays for the whole run.")
    print(f"\n  table after inserting 6:")
    print_table(table, m, highlight={11})
    # GOLD CHECK: 6 inserts cost 21 probes; the victim pays 6 probes
    t = [None] * m
    recs = [oa_insert(t, k, seq_linear(k, m), m)[1] for k in cluster_keys]
    assert sum(recs) == 21, f"expected 21, got {sum(recs)}"
    assert probes == 6, f"victim should pay 6, got {probes}"
    print(f"\n[check] 6 clustered inserts == 21 probes? OK ; victim pays 6 probes? OK")


# ----------------------------------------------------------------------------
# SECTION C: quadratic probing scatters keys (no primary cluster)
# ----------------------------------------------------------------------------
def section_quadratic():
    banner("SECTION C: quadratic probing - scatter keys, dodge the cluster")
    m = M
    cluster_keys = [18, 31, 44, 57, 70, 83]   # same 6 keys, all home = 5
    table = [None] * m
    print("Same 6 keys as Section B, but probe with h(k,i) = (home + i^2) mod m.\n"
          "The keys now SCATTER instead of stacking contiguously, so no primary\n"
          "cluster forms:\n")
    print("| insert# | key | home | probe sequence (i^2 steps)        | lands | probes |")
    print("|---------|-----|------|-----------------------------------|-------|--------|")
    for i, k in enumerate(cluster_keys, start=1):
        seq = seq_quad(k, m)
        slot, probes = oa_insert(table, k, seq, m)
        walked = fmt_seq(seq, probes)
        print(f"| {i:<7} | {k:<3} | {h1(k, m):<4} | {walked:<33} | {slot:<5} | {probes:<6} |")
    print(f"\n  table after the 6 inserts (note: NOT contiguous):")
    print_table(table, m)
    occupied = sorted(j for j in range(m) if table[j] is not None)
    print(f"\n  occupied slots = {occupied}  (scattered: 1,4,5,6,8,9)")
    print(f"  Probe COUNTS are still 1,2,3,4,5,6 (== Section B): keys with the")
    print(f"  SAME home still share one probe sequence -> SECONDARY clustering.")
    print(f"  But the keys are spread out, so a NEARBY home no longer pays the tax:")

    print("\n  THE SAME VICTIM, now cheap (no wall to climb):")
    victim = 6
    seq = seq_quad(victim, m)
    slot, probes = oa_insert(table, victim, seq, m)
    print(f"    insert {victim}: home = {h1(victim, m)}, probe seq {fmt_seq(seq, probes)} "
          f"-> lands at {slot} in {probes} probe(s).")
    print(f"    => {probes} probes, vs 6 for linear probing (Section B).")
    print(f"    The cluster does not CONTIGUOUSLY block slot 7, so home+1 is free.")
    print(f"\n  table after inserting 6:")
    print_table(table, m, highlight={7})
    # GOLD CHECK: victim pays 2 probes with quadratic vs 6 with linear
    assert probes == 2, f"quadratic victim should pay 2, got {probes}"
    # the 6 keys occupy exactly {1,4,5,6,8,9}
    assert occupied == [1, 4, 5, 6, 8, 9], f"scatter set wrong: {occupied}"
    print(f"\n[check] quadratic victim pays 2 probes (vs 6 linear)? OK ; "
          f"keys scatter to {{1,4,5,6,8,9}} (not contiguous)? OK")


# ----------------------------------------------------------------------------
# SECTION D: double hashing - per-key step kills secondary clustering too
# ----------------------------------------------------------------------------
def section_double():
    banner("SECTION D: double hashing - a per-key step kills secondary clustering")
    m = M
    keys = [5, 18, 31, 44]      # all h1 = 5, but DIFFERENT h2 steps
    table = [None] * m
    print("Take 4 keys that all share home h1 = 5, but differ in the second hash\n"
          "h2(k) = 1 + (k mod (m-1)) = 1 + (k mod 12). Because each key's STEP is\n"
          "different, their probe sequences DIVERGE after the home slot -> no\n"
          "secondary clustering:\n")
    print("| key | h1 | h2 = step | probe sequence        | lands | probes |")
    print("|-----|----|-----------|-----------------------|-------|--------|")
    total = 0
    for k in keys:
        seq = seq_double(k, m)
        slot, probes = oa_insert(table, k, seq, m)
        total += probes
        walked = fmt_seq(seq, probes)
        print(f"| {k:<3} | {h1(k, m):<2} | {h2(k, m):<9} | {walked:<21} | {slot:<5} | "
              f"{probes:<6} |")
    print(f"\n  table after the 4 inserts:")
    print_table(table, m)
    print(f"\n  total probes = {total}  (vs 10 for linear AND 10 for quadratic on the")
    print(f"  same 4 colliding keys: 1+2+3+4. Double hashing pays 1+2+2+2 = {total} because")
    print(f"  each colliding key jumps to a DIFFERENT second slot.)")
    print(f"\n  WHY it works: same home, different steps ->")
    for k in keys:
        seq = seq_double(k, m)
        print(f"    key {k:>3}: h1={h1(k, m)}, h2={h2(k, m)} -> seq {fmt_seq(seq, 3)}, ...")
    # GOLD CHECK: 4 double-hashing inserts cost 7 probes (vs 10 for linear/quadratic)
    assert total == 7, f"expected 7 probes for double hashing, got {total}"
    # contrast with linear and quadratic on the SAME 4 keys
    tl = [None] * m
    tq = [None] * m
    lp = sum(oa_insert(tl, k, seq_linear(k, m), m)[1] for k in keys)
    qp = sum(oa_insert(tq, k, seq_quad(k, m), m)[1] for k in keys)
    assert lp == 10 and qp == 10
    print(f"\n[check] double hashing == {total} probes (vs linear {lp}, quadratic {qp})? OK")


# ----------------------------------------------------------------------------
# SECTION E: the probe-count formula + empirical check at several load factors
# ----------------------------------------------------------------------------
def expected_unsucc(alpha):
    """Uniform hashing: expected probes for an UNSUCCESSFUL search."""
    return 1.0 / (1.0 - alpha)


def expected_succ(alpha):
    """Uniform hashing: expected probes for a SUCCESSFUL search."""
    return (1.0 / alpha) * math.log(1.0 / (1.0 - alpha))


def lin_unsucc(alpha):
    """Linear probing: ~ (1/2)(1 + 1/(1-alpha)^2)."""
    return 0.5 * (1.0 + 1.0 / (1.0 - alpha) ** 2)


def lin_succ(alpha):
    """Linear probing: ~ (1/2)(1 + 1/(1-alpha))."""
    return 0.5 * (1.0 + 1.0 / (1.0 - alpha))


def measure(strategy, m, alpha, seed=42):
    """Build a table of size m at load factor alpha (deterministic LCG keys),
    return (successful_avg, unsuccessful_avg) measured empirically.

    successful_avg = mean number of probes to find each inserted key
                     (== its insert-probe count; a known open-addressing identity).
    unsuccessful_avg = mean probes to search for fresh keys NOT in the table.
    """
    n = math.ceil(alpha * m)
    table = [None] * m
    g = lcg_stream(seed)
    keys = [next(g) for _ in range(n)]
    insert_probes = []
    for k in keys:
        seq = strategy(k, m)
        _, pr = oa_insert(table, k, seq, m)
        insert_probes.append(pr)
    successful_avg = sum(insert_probes) / n

    # unsuccessful searches: fresh keys guaranteed not inserted (offset by a big
    # constant so their hash homes are still uniform but the keys differ)
    g2 = lcg_stream(seed + 1)
    cnt = 0
    total = 0
    cap = n                       # as many samples as stored keys
    guard = 0
    while cnt < cap and guard < cap * 20:
        guard += 1
        k = next(g2)
        seq = strategy(k, m)
        j, pr = oa_search(table, k, seq, m)
        if j == -1:               # genuine miss
            total += pr
            cnt += 1
    unsuccessful_avg = total / cnt if cnt else float("nan")
    return successful_avg, unsuccessful_avg


def section_formula():
    banner("SECTION E: the probe-count formula - and which strategy hits it")
    m = 1009                      # prime; big enough to see the averages converge
    alphas = [0.10, 0.25, 0.50, 0.75, 0.90]
    strats = [
        ("linear", seq_linear),
        ("quadratic", seq_quad),
        ("double", seq_double),
    ]
    print("Uniform-hashing probe bound (CLRS Theorem 11.6), exact only under the\n"
          "idealized uniform-hashing assumption:\n"
          "    unsuccessful:   1 / (1 - alpha)\n"
          "    successful  :   (1/alpha) * ln( 1/(1-alpha) )\n")
    print("Linear probing has its OWN (tighter, worse) cost model:\n"
          "    unsuccessful:   (1/2)(1 + 1/(1-alpha)^2)\n"
          "    successful  :   (1/2)(1 + 1/(1-alpha)  )\n")
    print(f"Empirical study: table size m = {m} (prime), keys from the deterministic\n"
          "LCG. For each strategy we measure actual average probes.\n")

    # ---- unsuccessful search ----
    print("UNSUCCESSFUL search - mean probes (lower is better):")
    print("| alpha | formula 1/(1-a) | linear ~1/2(1+..) | linear (sim) | "
          "quadratic (sim) | double (sim) |")
    print("|-------|----------------|-------------------|--------------|"
          "-----------------|--------------|")
    sim = {}
    for a in alphas:
        row = {}
        for name, strat in strats:
            row[name] = measure(strat, m, a)
        sim[a] = row
        fu = expected_unsucc(a)
        lu = lin_unsucc(a)
        print(f"| {a:.2f}  | {fu:<14.3f} | {lu:<17.3f} | {row['linear'][1]:<12.3f} | "
              f"{row['quadratic'][1]:<15.3f} | {row['double'][1]:<12.3f} |")

    # ---- successful search ----
    print("\nSUCCESSFUL search - mean probes:")
    print("| alpha | formula (1/a)ln.. | linear ~1/2(1+..) | linear (sim) | "
          "quadratic (sim) | double (sim) |")
    print("|-------|-------------------|-------------------|--------------|"
          "-----------------|--------------|")
    for a in alphas:
        row = sim[a]
        fs = expected_succ(a)
        ls = lin_succ(a)
        print(f"| {a:.2f}  | {fs:<17.3f} | {ls:<17.3f} | {row['linear'][0]:<12.3f} | "
              f"{row['quadratic'][0]:<15.3f} | {row['double'][0]:<12.3f} |")

    print("\nHOW TO READ IT:")
    print("  * DOUBLE hashing tracks the uniform-hashing formula closely at every")
    print("    alpha - it is the best real approximation to uniform hashing.")
    print("  * LINEAR probing overshoots, and its overshoot matches its OWN model")
    print("    (1/2)(1+1/(1-a)^2): primary clustering makes it the worst.")
    print("  * QUADRATIC sits between the two: no primary cluster, but secondary")
    print("    clustering keeps it above double hashing as alpha grows.")

    # ---- GOLD: pin the formula at alpha=0.75 + the double-hashing sim ----
    a = 0.75
    fu = expected_unsucc(a)
    fs = expected_succ(a)
    ds, du = measure(seq_double, m, a)
    print("\nGOLD at alpha = 0.75 (the canonical resize threshold):")
    print(f"  formula  unsuccessful = 1/(1-0.75)              = {fu:.6f}  (= 4.0)")
    print(f"  formula  successful   = (1/0.75)*ln(1/0.25)     = {fs:.6f}")
    print(f"  double-hashing (sim)  unsuccessful              = {du:.3f}  "
          f"(within {abs(du - fu) / fu * 100:.1f}% of formula)")
    print(f"  double-hashing (sim)  successful                = {ds:.3f}  "
          f"(within {abs(ds - fs) / fs * 100:.1f}% of formula)")
    # exact-formula gold checks
    assert abs(fu - 4.0) < 1e-9, "1/(1-0.75) must be exactly 4.0"
    assert abs(fs - (4.0 / 3.0) * math.log(4.0)) < 1e-12
    # double-hashing empirical within 12% of the uniform formula at alpha=0.75
    assert abs(du - fu) / fu < 0.12, f"double unsucc {du} too far from {fu}"
    assert abs(ds - fs) / fs < 0.12, f"double succ {ds} too far from {fs}"
    # clustering ordering at alpha=0.75: linear > quadratic > double probes
    # (primary clustering hurts most, secondary clustering hurts next, double
    #  hashing is cleanest). Robust across any reasonable key stream.
    lu_emp = measure(seq_linear, m, a)[1]
    qu_emp = measure(seq_quad, m, a)[1]
    assert lu_emp > qu_emp > du, f"ordering broken: {lu_emp},{qu_emp},{du}"
    print(f"\n[check] 1/(1-0.75)==4.0 exact? OK ; "
          f"double hashing within 12% of formula at alpha=0.75? OK ; "
          f"clustering order linear({lu_emp:.1f}) > quad({qu_emp:.1f}) > "
          f"double({du:.1f})? OK")


# ----------------------------------------------------------------------------
# GOLD VALUES (pinned for open_addressing.html)
# ----------------------------------------------------------------------------
def section_gold():
    banner("GOLD VALUES (pinned for open_addressing.html)")
    a = 0.75
    fu = expected_unsucc(a)
    fs = expected_succ(a)
    print(f"alpha = {a}\n")
    print(f"  formula  unsuccessful  1/(1-a)            = {fu:.6f}")
    print(f"  formula  successful    (1/a)ln(1/(1-a))   = {fs:.6f}")
    print(f"  linear   unsuccessful  (1/2)(1+1/(1-a)^2) = {lin_unsucc(a):.6f}")
    print(f"  linear   successful    (1/2)(1+1/(1-a))   = {lin_succ(a):.6f}")
    # worked-example golds (m=13)
    m = M
    keys = [10, 22, 31, 4, 15, 28, 17, 88, 59, 36]
    table = [None] * m
    build_probes = 0
    for k in keys:
        _, pr = oa_insert(table, k, seq_linear(k, m), m)
        build_probes += pr
    j36, p36 = oa_search(table, 36, seq_linear(36, m), m)
    jmiss, pmiss = oa_search(table, 8, seq_linear(8, m), m)
    print(f"\n  worked example (m=13, linear probing):")
    print(f"    build probes (10 inserts) = {build_probes}")
    print(f"    search 36 -> slot {j36} in {p36} probes")
    print(f"    search  8 (miss)  -> {pmiss} probe")
    # primary-cluster golds
    cluster = [18, 31, 44, 57, 70, 83]
    tl = [None] * m
    cl = sum(oa_insert(tl, k, seq_linear(k, m), m)[1] for k in cluster)
    tq = [None] * m
    cq = sum(oa_insert(tq, k, seq_quad(k, m), m)[1] for k in cluster)
    td = [None] * m
    cd = sum(oa_insert(td, k, seq_double(k, m), m)[1] for k in cluster[:4])
    print(f"    6 clustered inserts: linear = {cl} probes")
    print(f"    victim key 6      : linear = 6, quadratic = 2 probes")
    print(f"    4 double-hash keys: double = {cd} probes")
    # assertions mirror the checks above
    assert fu == 4.0
    assert abs(fs - 1.8483924810) < 1e-6
    assert build_probes == 16 and p36 == 3 and pmiss == 1
    assert cl == 21 and cd == 7
    print(f"\n  GOLD scalars for .html: formula_unsucc@0.75 = 4.0, "
          f"formula_succ@0.75 = 1.848392, build_probes = 16, cluster = 21.")
    print(f"[check] GOLD reproduces from the reference functions? OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("open_addressing.py - reference impl. All numbers below feed")
    print("OPEN_ADDRESSING.md. python stdlib only.\n")

    section_linear()
    section_primary_cluster()
    section_quadratic()
    section_double()
    section_formula()
    section_gold()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
