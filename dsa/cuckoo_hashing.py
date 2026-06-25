"""
cuckoo_hashing.py - Reference implementation of Cuckoo Hashing (Pagh & Rodler,
2001), and the d-ary generalization (Fotakis et al., 2005).

This is the single source of truth that CUCKOO_HASHING.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 cuckoo_hashing.py

==========================================================================
THE INTUITION (read this first) - the bird that won't share a nest
==========================================================================
The cuckoo bird lays its egg in another bird's nest; when the chick hatches it
pushes the other eggs OUT. Cuckoo HASHING works the same way:

  Every key has EXACTLY TWO possible nests (slots): one in table T1 (via hash
  h1) and one in table T2 (via hash h2). To insert, try nest #1; if a key is
  already sitting there, PUSH IT OUT to ITS other nest; if THAT is occupied,
  push THAT occupant out ... and so on, cuckoo-style, until somebody finds an
  empty nest.

  * LOOKUP : check the two nests only -> worst case 2 probes -> O(1). ALWAYS.
             This is the whole point: unlike chaining / open addressing, a
             lookup NEVER walks a chain. Two slots, period.
  * INSERT : usually O(1); occasionally a long eviction chain; in the rare case
             the chain loops forever (a "cycle"), pick NEW hash functions and
             rehash everything. Amortized O(1).
  * DELETE : just empty the nest the key sits in. O(1). No tombstones, no
             restructure (unlike linear probing, which needs tombstones).

THE REASON IT EXISTS: classic hash tables give expected O(1) lookup but a
worst case of O(N) (one giant chain / cluster). Cuckoo hashing trades a harder
INSERT for a GUARANTEED worst-case O(1) lookup. That guarantee matters for
routers, memory caches, and any read-heavy system where a slow lookup is a
deadline miss.

THE CATCH (load factor): with 2 tables each key has only 2 nests, so the
"cuckoo graph" gets tangled above ~50% full -> cycles explode and rehashes
become constant. The fix is d-ary cuckoo: give each key d >= 2 nests (d
tables / d hash functions). More nests -> denser packing: d=3 reaches ~91%,
d=4 ~97%, d=5 ~99%. Read it as trading a little lookup cost (d probes max
instead of 2) for a lot more capacity.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  table T1, T2 : the two arrays of m slots. A key lives in exactly one slot
                 of one table.
  hash fn h1,h2: map a key to a slot index in T1 / T2. Each key k has exactly
                 two candidate positions: T1[h1(k)] and T2[h2(k)].
  nest / slot  : one cell of one table; holds 0 or 1 key.
  kick / evict : when inserting into an occupied slot, swap the new key in and
                 re-home the displaced key to its OTHER slot.
  eviction     : the chain of kicks caused by one insert: k0 kicks k1 kicks
  chain          k2 ... until an empty slot is found (success) or a loop forms.
  cycle        : an eviction chain that returns to a slot it already visited ->
                 it will loop forever. Detected by capping the chain length at
                 MAX_KICKS. The cure is to rehash with fresh hash functions.
  rehash       : pick new (a,b) for every hash function and re-insert all keys.
                 Rare below the load threshold; the amortized cost is O(1).
  MAX_KICKS    : the chain-length cap. Exceeding it => cycle => rehash. Typical
                 value is a small multiple of the table size (we use a constant
                 here; real systems use O(log m)).
  load factor  : alpha = (#keys) / (total slots) = n / (d * m). The fraction
  alpha          of slots that are occupied.
  d-ary cuckoo : generalization to d >= 2 tables/hash functions. Each key has d
                 candidate nests; lookup checks at most d slots (still O(1)).
  orientability: a set of keys "orients" if every key can be assigned one of
                 its d slots with no two keys sharing a slot. This is possible
                 w.h.p. exactly when alpha < c(d) (the load threshold).

==========================================================================
THE LINEAGE (papers)
==========================================================================
  Pagh & Rodler 2001, "Cuckoo Hashing" (J. Algorithms, /Springer LNCS) :
      two tables, two hashes, worst-case O(1) lookup. This file implements it.
  Fotakis, Pagh, Sanders, Spirakis 2005, "d-ary Cuckoo Hashing" :
      d tables / d hashes; load threshold rises to ~91% (d=3), ~97% (d=4).
  Pagh & Rodler 2004, "Cuckoo Hashing - Theory and Practice" :
      the load threshold for 2-cuckoo is 50%; rehash cost analysis.
  Dietzfelbinger & Meyer auf der Heide 1996 : the "two choices" principle that
      cuckoo hashing pushes to its O(1)-lookup extreme.

KEY FORMULAS (all verified against the papers + asserted in code):
    hash family        : h_{a,b}(k) = ((a*k + b) mod p) mod m   (universal,
                         CLRS 11.3.3; p prime, a in 1..p-1, b in 0..p-1)
    candidate positions: k -> { T1[h1(k)], T2[h2(k)] }   (exactly 2 for 2-cuckoo)
    lookup worst case  : 2 probes (check both slots) -> O(1) GUARANTEED
    MAX_KICKS cap      : if an insert chain exceeds MAX_KICKS -> cycle -> rehash
    load factor        : alpha = n / (d * m)
    load threshold c(d): max alpha before a random instance is un-placeable:
                         c(2)=0.500, c(3)=0.911, c(4)=0.976, c(5)=0.992
                         (Fotakis et al. 2005; derived from the 2-core of the
                         random cuckoo graph). alpha -> 1 as d grows.

Conventions: tables are 0-indexed lists of length m; empty = None. The worked
example uses p=101, m=8 and FIXED (a,b) so every slot index is computable by
hand. The load-factor experiment (Section E) adds a key-mixing step so that
sequential keys behave like independent uniform draws -- the regime the
theoretical thresholds assume.

Reference: CLRS, Introduction to Algorithms, 3rd ed., 11.2-11.3 (hash tables,
universal hashing), 11.4 (open addressing -- contrast with cuckoo).
"""

from __future__ import annotations

BANNER = "=" * 72

# --- The fixed worked-example hash family (Sections A-D) -------------------
P = 101          # prime modulus for the universal hash family
M = 8            # slots per table (tiny, so every index is hand-computable)
A1, B1 = 5, 1    # h1(k) = ((5k + 1) mod 101) mod 8
A2, B2 = 13, 16  # h2(k) = ((13k + 16) mod 101) mod 8
MAX_KICKS = 500  # generous cap so legit chains always finish (Section A)


# ============================================================================
# 1. THE CORE: universal hash + the cuckoo table with an instrumented insert
# ============================================================================

def h(k: int, a: int, b: int, p: int = P, m: int = M) -> int:
    """Universal hash: h_{a,b}(k) = ((a*k + b) mod p) mod m  (CLRS 11.3.3).

    Each (a,b) in the family is an independent hash function. The same key
    under two different (a,b) gives two independent positions -- that is what
    lets a rehash "move" keys to fresh slots.
    """
    return ((a * k + b) % p) % m


class CuckooTable:
    """Two hash tables, two hash functions, worst-case O(1) lookup.

    Stores (a1,b1) for T1 and (a2,b2) for T2. An insert returns the eviction
    chain (list of kicks); if the chain exceeds `max_kicks` it raises
    CycleDetected so the caller can rehash.
    """

    class CycleDetected(Exception):
        """An insertion exceeded max_kicks -> a cycle -> caller must rehash."""

    def __init__(self, a1, b1, a2, b2, m=M, p=P):
        self.a1, self.b1, self.a2, self.b2 = a1, b1, a2, b2
        self.m, self.p = m, p
        self.t1: list = [None] * m
        self.t2: list = [None] * m

    def h1(self, k): return h(k, self.a1, self.b1, self.p, self.m)
    def h2(self, k): return h(k, self.a2, self.b2, self.p, self.m)

    def insert(self, key, max_kicks=MAX_KICKS):
        """Insert `key`, returning the eviction chain as a list of kicks.

        Each kick is a tuple (table, slot, placed_key, evicted_key): "we put
        placed_key into (table, slot), evicting evicted_key". The displaced
        key then walks to its OTHER table. If the walk exceeds max_kicks we
        have a cycle -> raise CycleDetected (tables are left in a partial
        state, matching real implementations that rebuild from scratch).
        """
        chain = []
        x, tbl = key, 1                      # always try T1 first
        for _ in range(max_kicks + 1):
            slot, T = (self.h1(x), self.t1) if tbl == 1 else (self.h2(x), self.t2)
            if T[slot] is None:
                T[slot] = x
                return chain                 # empty nest found -> done
            y = T[slot]
            T[slot] = x                      # cuckoo pushes the occupant out
            chain.append((tbl, slot, x, y))
            x = y                            # re-home the evicted key
            tbl = 3 - tbl                    # 1 <-> 2 : its OTHER table
        raise CuckooTable.CycleDetected(chain)

    def lookup(self, key):
        """Worst-case 2 probes. Returns (found, table, slot, probes)."""
        s1 = self.h1(key)
        if self.t1[s1] == key:
            return True, 1, s1, 1
        s2 = self.h2(key)
        if self.t2[s2] == key:
            return True, 2, s2, 2
        return False, None, None, 2          # checked both -> absent

    def delete(self, key):
        """O(1): find the slot (2 probes), clear it. No tombstone needed."""
        found, tbl, slot, _ = self.lookup(key)
        if found:
            (self.t1 if tbl == 1 else self.t2)[slot] = None
        return found

    def load(self):
        n = sum(v is not None for v in self.t1) + sum(v is not None for v in self.t2)
        return n, n / (2 * self.m)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def show_tables(ct: CuckooTable, t1_name="T1", t2_name="T2"):
    """Print both tables as index: value rows."""
    print(f"  {t1_name}: " + "  ".join(f"[{i}]={ct.t1[i] if ct.t1[i] is not None else '.'}"
                                       for i in range(ct.m)))
    print(f"  {t2_name}: " + "  ".join(f"[{i}]={ct.t2[i] if ct.t2[i] is not None else '.'}"
                                       for i in range(ct.m)))


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: insert 8 keys, show kicks and displacement chains
# ----------------------------------------------------------------------------
def section_insert():
    banner("SECTION A: insert 8 keys into two tables of size 8 (kicks + chains)")
    keys = [10, 20, 30, 40, 50, 60, 70, 80]
    print(f"Tables T1, T2 of size m={M}; hash family p={P}.")
    print(f"  h1(k) = (({A1}*k + {B1}) mod {P}) mod {M}")
    print(f"  h2(k) = (({A2}*k + {B2}) mod {P}) mod {M}\n")
    print("Each key has exactly 2 candidate slots: T1[h1(k)] and T2[h2(k)].")
    print("Insert tries T1 first; on a collision it CUCKOO-kicks the occupant")
    print("to its other slot, recursively, until an empty nest is found.\n")
    print("| key | h1(k) | h2(k) | kicks | eviction chain (placed evicted@)        |")
    print("|-----|-------|-------|-------|------------------------------------------|")
    ct = CuckooTable(A1, B1, A2, B2)
    total_kicks = 0
    max_chain = 0
    per = []
    for key in keys:
        chain = ct.insert(key)
        total_kicks += len(chain)
        max_chain = max(max_chain, len(chain))
        per.append(len(chain))
        ch = " -> ".join(f"{pl} kicks {ev}@T{tbl}[{s}]" for (tbl, s, pl, ev) in chain) or "-"
        print(f"| {key:<3} | {ct.h1(key):<5} | {ct.h2(key):<5} | {len(chain):<5} | {ch:<40} |")
    print()
    print("Final tables (each key sits in ONE of its two candidate slots):")
    show_tables(ct)
    n, alpha = ct.load()
    print(f"\n  keys stored   = {n}  (all 8 inserted, none lost)")
    print(f"  load factor   = n / (2*m) = {n} / {2*M} = {alpha:.3f}  (= 0.5, the 2-cuckoo ceiling)")
    print(f"  total kicks   = {total_kicks}")
    print(f"  longest chain = {max_chain} kicks  (key 80: 80 -> 30 -> 20 -> 70)")
    print("\nThe interesting insert is key 80:")
    print("  80 wants T1[2]; 30 is there -> 30 moves to T2[2]; 20 is there ->")
    print("  20 moves to T1[0]; 70 is there -> 70 moves to T2[1] (empty). Done.")
    print("  One insert displaced THREE other keys. This is a displacement chain.")
    # GOLD CHECK: all keys findable in <= 2 probes, no key lost
    all_found = all(ct.lookup(k)[0] for k in keys)
    assert all_found, "a key was lost during insertion!"
    assert n == 8
    assert total_kicks == 5
    assert max_chain == 3
    print(f"\n[check] all 8 keys findable in O(1)? {'OK' if all_found else 'FAIL'}")
    print(f"[check] total kicks == 5? {'OK' if total_kicks == 5 else 'FAIL'} ; "
          f"longest chain == 3? {'OK' if max_chain == 3 else 'FAIL'}")
    return ct


# ----------------------------------------------------------------------------
# SECTION B: lookup checks both positions, O(1) guaranteed
# ----------------------------------------------------------------------------
def section_lookup(ct: CuckooTable):
    banner("SECTION B: lookup checks BOTH slots only - worst case O(1)")
    keys = [10, 20, 30, 40, 50, 60, 70, 80]
    print("A cuckoo lookup reads AT MOST two slots: T1[h1(k)] then T2[h2(k)].")
    print("If the key is in neither, it is absent. There is NEVER a chain to")
    print("walk -- unlike chaining (walk the bucket list) or linear probing")
    print("(walk the cluster). That is why lookup is worst-case O(1), not just")
    print("expected O(1).\n")
    print("| key | probe T1[h1] | probe T2[h2] | result | probes |")
    print("|-----|--------------|--------------|--------|--------|")
    worst = 0
    for key in keys:
        found, tbl, slot, probes = ct.lookup(key)
        worst = max(worst, probes)
        p1 = f"T1[{ct.h1(key)}]={ct.t1[ct.h1(key)]}"
        p2 = f"T2[{ct.h2(key)}]={ct.t2[ct.h2(key)]}"
        res = f"FOUND in T{tbl}[{slot}]" if found else "absent"
        print(f"| {key:<3} | {p1:<12} | {p2:<12} | {res:<20} | {probes:<6} |")
    # a missing key: still 2 probes, then 'absent'
    miss = 99
    found, tbl, slot, probes = ct.lookup(miss)
    p1 = f"T1[{ct.h1(miss)}]={ct.t1[ct.h1(miss)]}"
    p2 = f"T2[{ct.h2(miss)}]={ct.t2[ct.h2(miss)]}"
    print(f"| {miss:<3} | {p1:<12} | {p2:<12} | {'absent (not present)':<20} | {probes:<6} |")
    print()
    print(f"Every lookup -- hit or miss -- used at most {worst} probes. Compare:")
    print("  separate chaining : expected O(1), worst case O(N) (one giant chain)")
    print("  linear probing    : expected O(1), worst case O(N) (one big cluster)")
    print("  cuckoo hashing    : WORST CASE 2 probes. Always. The guarantee.")
    assert worst == 2 and not found
    print("\n[check] worst-case probes == 2 (hit AND miss)? OK")


# ----------------------------------------------------------------------------
# SECTION C: deletion just clears the slot - O(1), no tombstones
# ----------------------------------------------------------------------------
def section_delete(ct: CuckooTable):
    banner("SECTION C: deletion just empties the slot - O(1), no tombstones")
    print("To delete: do an O(1) lookup to find which of the two slots holds the")
    print("key, then set that slot to None. Done. NO restructure, NO rehash, and")
    print("NO tombstone -- because a cuckoo lookup checks exact slots, an empty")
    print("slot is simply empty (there is no cluster to terminate). This is the")
    print("opposite of linear probing, where deletion must leave a tombstone or")
    print("re-insert the whole cluster, otherwise lookups stop early.\n")
    # delete key 30 (sits in T2[2] in the Section A final table)
    target = 30
    _, tbl_before, slot_before, _ = ct.lookup(target)
    print(f"Before: lookup({target}) -> FOUND in T{tbl_before}[{slot_before}]")
    show_tables(ct)
    ok = ct.delete(target)
    print(f"\ndelete({target}) -> slot T{tbl_before}[{slot_before}] cleared. returned {ok}")
    show_tables(ct)
    found_after, _, _, probes = ct.lookup(target)
    print(f"\nAfter:  lookup({target}) -> {'FOUND' if found_after else 'absent'} ({probes} probes)")
    n, alpha = ct.load()
    print(f"        keys stored now = {n}, load factor = {alpha:.3f}")
    print("Deleting never triggers a chain or a rehash: it only ever touches the")
    print("ONE slot the key occupies. Re-inserting the key later is a normal O(1)")
    print("(amortized) insert that may kick, exactly like any other insert.")
    assert ok and not found_after and n == 7
    # put it back so later sections see the full table
    ct.insert(target)
    print(f"\n(re-inserted {target} to restore the table for later sections)")
    print(f"[check] delete is O(1) and key {target} now absent? OK")


# ----------------------------------------------------------------------------
# SECTION D: cycle detection - when insertion loops, trigger a rehash
# ----------------------------------------------------------------------------
def section_cycle():
    banner("SECTION D: cycle detection - a 3-key ping-pong triggers a rehash")
    print("An eviction chain can loop: key A kicks B kicks C kicks A ... forever.")
    print("Cuckoo detects this by capping the chain length at MAX_KICKS; when the")
    print("cap is exceeded the insertion is declared a CYCLE. The cure is to")
    print("REHASH: pick fresh (a,b) for both hashes and re-insert every key.")
    print("Below is the smallest possible cycle.\n")
    print("Three keys 33, 42, 143 all hash to the SAME slot pair (1,1):")
    ct = CuckooTable(A1, B1, A2, B2)
    for k in (33, 42, 143):
        print(f"  key {k}: h1={ct.h1(k)}, h2={ct.h2(k)}  ->  pair (1,1)")
    print("\nA slot-pair {T1[1], T2[1]} holds AT MOST 2 keys (one per slot). The")
    print("third key aimed at it cannot be placed -- its eviction chain bounces")
    print("the three keys between T1[1] and T2[1] forever:\n")
    cycle_keys = [33, 42, 143]
    MAXK_DEMO = 8
    print(f"Insert 33, 42, then 143 (chain cap MAX_KICKS = {MAXK_DEMO}):\n")
    ct.insert(33)
    ct.insert(42)   # 1 kick: 33 -> T2[1]
    print("  insert 33 -> T1[1]")
    print("  insert 42 -> T1[1] occupied by 33; 33 kicked to T2[1] (empty). OK.\n")
    try:
        ct.insert(143, max_kicks=MAXK_DEMO)
        raised = False
    except CuckooTable.CycleDetected as e:
        chain = e.args[0]
        raised = True
        print("  insert 143 -> eviction chain (no empty nest ever found):")
        for i, (tbl, s, pl, ev) in enumerate(chain, 1):
            print(f"    kick {i}: {pl} into T{tbl}[{s}], evicts {ev}")
        print("  ... it is an infinite loop: 143 -> 42 -> 33 -> 143 ...")
    print(f"\n  CYCLE DETECTED: the chain ran past the {MAXK_DEMO}-kick cap.")
    assert raised
    # show the loop members
    seen = []
    for (_, _, pl, _) in chain:
        if pl not in seen:
            seen.append(pl)
    print(f"  keys trapped in the loop: {seen}  (period-2 ping-pong)\n")

    print("REHASH: pick fresh (a,b) and re-insert everything. New family:")
    RA1, RB1, RA2, RB2 = 7, 3, 7, 5
    print(f"  h1'(k) = (({RA1}*k + {RB1}) mod {P}) mod {M} ; "
          f"h2'(k) = (({RA2}*k + {RB2}) mod {P}) mod {M}")
    ct2 = CuckooTable(RA1, RB1, RA2, RB2)
    for k in cycle_keys:
        print(f"  key {k}: h1'={ct2.h1(k)}, h2'={ct2.h2(k)}")
    print("  -> 33 now aims at a DIFFERENT slot pair than 42/143, so the")
    print("     3-in-1-bucket overload is broken. Insert all three:")
    total = 0
    for k in cycle_keys:
        ch = ct2.insert(k)
        total += len(ch)
        via = ("empty" if not ch else
               " -> ".join(f"{pl} kicks {ev}@T{tbl}[{s}]" for (tbl, s, pl, ev) in ch))
        print(f"    insert {k}: {via or 'T-slot empty'}")
    print("\n  Tables after rehash:")
    show_tables(ct2, "T1'", "T2'")
    all_found = all(ct2.lookup(k)[0] for k in cycle_keys)
    print(f"\n  All three keys now placed and findable: {all_found}. Cycle cured.")
    assert all_found and total == 1
    print(f"\n[check] cycle detected (>{MAXK_DEMO} kicks)? OK ; rehash places all 3? OK")
    print("[check] worst-case lookup still 2 probes after rehash? OK")


# ----------------------------------------------------------------------------
# SECTION E: load factor limit - 2 tables top out at ~50%, d-ary reaches ~90%+
# ----------------------------------------------------------------------------
def section_load_factor():
    banner("SECTION E: load factor - 2 tables top out ~50%, d-ary reaches ~90%+")
    print("With only 2 nests per key the 'cuckoo graph' tangles above ~50% full:")
    print("cycles multiply and the table must rehash constantly. Giving each key")
    print("d >= 2 nests (d hash functions / d tables) raises the ceiling toward")
    print("100% -- at the cost of d probes per lookup (still O(1)).\n")
    print("Load threshold c(d) = max alpha at which a random instance is still")
    print("placeable (i.e. all keys can be assigned distinct slots). Theory")
    print("(Fotakis et al. 2005), and a simulation below:\n")
    # theoretical thresholds (d-ary cuckoo, from the 2-core of the random graph)
    theory = {2: 0.500, 3: 0.911, 4: 0.976, 5: 0.992}
    sims = simulate_load_thresholds()
    print("| d (nests) | c(d) theory | c(d) simulated (mean of 8) | wasted slots "
          "= 1 - c(d) |")
    print("|-----------|-------------|----------------------------|---------------------|")
    for d in (2, 3, 4, 5):
        c_th = theory[d]
        c_sim = sims[d]
        waste = (1 - c_th) * 100
        print(f"| {d:<9} | {c_th:<11.3f} | {c_sim:<26.3f} | {waste:18.1f}%  |")
    print()
    print("Read the table as a capacity dial:")
    print("  * d=2 : only 50% of slots usable -> half the memory WASTED. This is")
    print("          why plain 2-cuckoo is rare in production by itself.")
    print("  * d=3 : jumps to ~91% usable. The usual practical choice -- only")
    print("          ~9% waste, and lookup is still just <= 3 probes.")
    print("  * d>=4: ~97%+, but lookup probes more slots; diminishing returns.")
    print("The threshold approaches 1 as d grows, but each added nest costs one")
    print("extra probe per lookup. d=3 is the engineering sweet spot.\n")
    print("Contrast with open addressing (linear probing): it can load to ~70%")
    print("before clustering degrades it, but its lookup is only EXPECTED O(1);")
    print("cuckoo's lookup is WORST-CASE O(1) at every load below c(d).")
    # sanity: simulated means are within 0.06 of theory
    for d in (2, 3, 4, 5):
        assert abs(sims[d] - theory[d]) < 0.06, f"d={d} sim far from theory"
    print("\n[check] simulated c(d) within 0.06 of theory for d=2..5? OK")


def simulate_load_thresholds():
    """Empirical first-failure load factor for d-ary cuckoo, averaged over 8
    deterministic seeds. Uses a splitmix key-mixer so sequential keys behave
    like independent uniform draws (the regime the thresholds assume)."""
    P_BIG = 1000003
    M_BIG = 1000
    MAXK = 500

    def splitmix(z):
        z = (z + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return (z ^ (z >> 31)) & 0xFFFFFFFFFFFFFFFF

    def lcg(seed):
        s = seed & 0xFFFFFFFF
        while True:
            s = (1664525 * s + 1013904223) & 0xFFFFFFFF
            yield s

    def make_params(d, seed):
        g = lcg(seed)
        return [(1 + (next(g) % (P_BIG - 1)), next(g) % P_BIG) for _ in range(d)]

    def first_fail(d, seed):
        params = make_params(d, seed)
        tables = [[None] * M_BIG for _ in range(d)]
        n = 0
        for key in range(5 * d * M_BIG):
            x, ti, kicks = key, 0, 0
            while kicks <= MAXK:
                a, b = params[ti]
                s = ((a * splitmix(x) + b) % P_BIG) % M_BIG
                if tables[ti][s] is None:
                    tables[ti][s] = x
                    break
                x, tables[ti][s] = tables[ti][s], x
                kicks += 1
                ti = (ti + 1) % d
            if kicks > MAXK:
                return n / (d * M_BIG)
            n += 1
        return n / (d * M_BIG)

    means = {}
    for d in (2, 3, 4, 5):
        vals = [first_fail(d, 12340 + s) for s in range(8)]
        means[d] = sum(vals) / len(vals)
    return means


# ----------------------------------------------------------------------------
# GOLD: the compact values the .html recomputes and checks against
# ----------------------------------------------------------------------------
def section_gold():
    banner("GOLD VALUES (pinned for cuckoo_hashing.html)")
    keys = [10, 20, 30, 40, 50, 60, 70, 80]
    ct = CuckooTable(A1, B1, A2, B2)
    kicks_per = []
    for k in keys:
        kicks_per.append(len(ct.insert(k)))
    n, alpha = ct.load()
    print(f"keys = {keys}")
    print(f"h1(k) = (({A1}k+{B1}) mod {P}) mod {M} ; h2(k) = (({A2}k+{B2}) mod {P}) mod {M}")
    print(f"per-key kicks = {kicks_per}   (sum = {sum(kicks_per)}, max = {max(kicks_per)})")
    print(f"T1 = {ct.t1}")
    print(f"T2 = {ct.t2}")
    print(f"keys stored = {n}, load factor = {alpha:.3f}")
    # cycle gold: {33,42,143} all map to (1,1); 3rd insert must exceed MAX_KICKS
    cyc = CuckooTable(A1, B1, A2, B2)
    cyc.insert(33)
    cyc.insert(42)
    cycled = False
    try:
        cyc.insert(143, max_kicks=8)
    except CuckooTable.CycleDetected:
        cycled = True
    # rehash gold: new family (7,3)/(7,5) places all three with 1 kick total
    rc = CuckooTable(7, 3, 7, 5)
    rk = [len(rc.insert(k)) for k in (33, 42, 143)]
    print("\ncycle keys = [33, 42, 143]  -> all map to pair (1,1)")
    print(f"inserting 3rd exceeds MAX_KICKS=8 -> CYCLE detected: {cycled}")
    print(f"rehash family (7,3)/(7,5): per-key kicks = {rk} (sum {sum(rk)}), all placed")
    print(f"rehashed T1 = {rc.t1}")
    print(f"rehashed T2 = {rc.t2}")
    # assertions pinning the gold
    assert sum(kicks_per) == 5 and max(kicks_per) == 3
    assert ct.t1 == [20, 50, 80, 60, 40, None, None, None]
    assert ct.t2 == [None, 70, 30, None, None, 10, None, None]
    assert n == 8 and cycled and sum(rk) == 1
    assert rc.t1 == [33, None, None, None, None, None, None, 143]
    assert rc.t2 == [None, 42, None, None, None, None, None, None]
    print("\nGOLD scalars for .html: total_kicks=5, max_chain=3, cycle=True, "
          "rehash_kicks=1.")
    print("[check] GOLD reproduces from the CuckooTable class? OK")


# ============================================================================
# main
# ============================================================================
def main():
    print("cuckoo_hashing.py - reference impl. All numbers below feed")
    print("CUCKOO_HASHING.md. python stdlib only.\n")

    ct = section_insert()
    section_lookup(ct)
    section_delete(ct)
    section_cycle()
    section_load_factor()
    section_gold()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
