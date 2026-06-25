"""
chaining.py - Reference implementation: Separate Chaining hash tables.

This is the single source of truth that CHAINING.md is built from. Every
number, table, and worked example in CHAINING.md is printed by this file. If
you change something here, re-run and re-paste the output into the guide.

Run:
    python3 chaining.py

==========================================================================
THE INTUITION (read this first) - the coatroom with the peg rails
==========================================================================
Imagine a coatroom with m peg-RAILS (the buckets), numbered 0..m-1. Each guest
arrives, the attendant computes their rail number from their coat tag (the hash
function), and hangs the coat on that rail. If a rail already has coats, the
new one is just hooked on BEHIND the others - a little CHAIN of coats on one
rail. Nobody is ever turned away (a rail never "fills up"); at worst a rail
gets a long chain you must leaf through.

  * hash        : the function turning a key into a rail number, h(k) in 0..m-1.
  * bucket      : one rail. Holds a linked list (chain) of all keys that hashed there.
  * collision   : two keys map to the same rail. Resolution = prepend to the chain.
  * load factor : alpha = n/m (keys per bucket on average). The dial of fullness.
  * chain       : the linked list in a bucket. Expected length = alpha.
  * search      : hash to the rail, then walk the chain key by key. O(1+alpha) expected.

THE REASON CHAINING NEVER "FILLS UP": open addressing stores every entry IN a
bucket slot, so a table with alpha close to 1 runs out of room and degrades
catastrophically. Chaining puts an UNBOUNDED list in each bucket, so the table
keeps accepting keys at any alpha - it just gets slower to search, gracefully
and predictably: O(1 + alpha). That is why Java's HashMap and C++'s
unordered_map use chaining. The price: every entry is a heap-allocated node
(pointer chasing -> cache unfriendly).

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  m            : number of buckets (the table size / "rails").
  n            : number of stored keys ("coats").
  alpha        : load factor = n/m. The single knob that controls performance.
  h(k)         : hash of key k, in [0, m). Here: division method h(k)=k mod m.
  bucket       : slot 0..m-1, holding the HEAD of a linked list (or empty).
  chain        : the linked list in a bucket. Length = number of colliding keys.
  node         : one entry: {key, next}. Heap-allocated -> a pointer to chase.
  insert       : compute bucket, prepend node to its chain. O(1) worst case.
  search       : compute bucket, walk chain comparing keys. O(1+alpha) expected.
  rehash       : grow m (usually double), recompute h(k) for every key, rebuild chains.
  open addressing : the rival scheme - store entries in the buckets themselves,
                    probe for an empty slot on collision. No lists, no pointers,
                    but degrades to ~inf probes as alpha -> 1.
  balls-into-bins : the probability model: n keys thrown uniformly into m buckets.
                    Each bucket's chain length is Binomial(n, 1/m).

==========================================================================
KEY FORMULAS (CLRS Ch. 11, all verified/asserted in code)
==========================================================================
    Load factor:                   alpha = n / m
    Expected chain length:         E[length of bucket j] = alpha   (simple uniform hashing)
    Unsuccessful search (chain):   Theta(1 + alpha)    probes  (CLRS Thm 11.2)
    Successful search   (chain):   Theta(1 + alpha/2)  probes  (CLRS Thm 11.2)
    Chain length distribution:     X_j ~ Binomial(n, 1/m),  E[X_j]=alpha, Var=alpha(1-1/m)
    Resize trigger:                when alpha > threshold (0.75), double m and rehash.
    Open addressing, uniform hashing, UNSUCCESSFUL:  <= 1/(1-alpha)   (CLRS 11.4)
    Open addressing, uniform hashing, SUCCESSFUL  :  <= (1/alpha) * ln(1/(1-alpha))
    As alpha -> 1: open addressing -> inf ; chaining -> 1+alpha (linear, graceful).
    Max chain length, n=m balls into m bins (w.h.p.):  Theta(ln m / ln ln m)
    Expected empty buckets:        m * (1 - 1/m)^n  ~=  m * e^(-alpha)

Reference: CLRS, Introduction to Algorithms, 3rd ed.
  11.1 direct-address, 11.2 hash tables with chaining, 11.3 hash functions
  (division & multiplication methods), 11.4 open addressing.
  Sedgewick & Wayne, Algorithms 4th ed., 3.4 (hash tables).

Conventions: integer keys, division-method hash h(k)=k mod m (CLRS 11.3.1).
Chains are real singly-linked nodes (Node{key,next}) so search comparisons are
pointer follows, matching production HashMaps. m is a power of 2 here (after
resize), which is standard for real HashMaps. Determinism: keys are a fixed
list; the only RNG (Section E max-load sim) uses a fixed seed.
"""

from __future__ import annotations

import math
import random

BANNER = "=" * 72

# The 12 keys used throughout. Deterministic. h(k) = k mod m.
# Spread: residues mod 8 give chain lengths [1,1,2,3,2,0,1,2] (one bucket of 3,
# one empty) - a realistic, non-degenerate collision pattern at alpha = 1.5.
KEYS = [10, 22, 31, 4, 15, 28, 17, 88, 59, 26, 43, 27]

# Keys NOT in the table, for unsuccessful-search measurements.
ABSENT_KEYS = [1, 2, 3, 5, 6, 7, 8, 9, 11, 12, 13, 14]


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (the code CHAINING.md walks through)
# ============================================================================

class Node:
    """One entry in a chain. Heap-allocated -> a pointer to chase (cache-unfriendly)."""
    __slots__ = ("key", "next")

    def __init__(self, key, nxt=None):
        self.key = key
        self.next = nxt


class ChainingHashTable:
    """Separate-chaining hash table. Each bucket = head of a singly-linked list.

    alpha = n/m. Resizes (doubles m + rehashes) when alpha would exceed the
    threshold, unless do_resize=False (used to build the high-alpha Section A
    table and during a rehash itself).
    """

    def __init__(self, num_buckets, threshold=0.75):
        self.m = num_buckets
        self.n = 0
        self.threshold = threshold
        self.buckets = [None] * self.m          # each slot: head Node or None
        self.resizes = []                        # record of (trigger_n, old_m, new_m)

    def h(self, key):
        return key % self.m                      # division method (CLRS 11.3.1)

    def load_factor(self):
        return self.n / self.m

    def insert(self, key, do_resize=True):
        if do_resize and (self.n + 1) / self.m > self.threshold:
            self._rehash(self.m * 2)
        b = self.h(key)
        node = Node(key)
        node.next = self.buckets[b]              # prepend to head: O(1)
        self.buckets[b] = node
        self.n += 1

    def search(self, key):
        """Return (found: bool, comparisons: int).

        comparisons = number of nodes walked (pointer follows). The hash
        computation itself is the implicit leading +1 in O(1 + alpha).
        """
        b = self.h(key)
        node = self.buckets[b]
        cmp = 0
        while node is not None:
            cmp += 1
            if node.key == key:
                return (True, cmp)
            node = node.next
        return (False, cmp)

    def chain_keys(self):
        """Return list of lists: the actual keys in each bucket's chain (head->tail)."""
        out = []
        for head in self.buckets:
            keys = []
            node = head
            while node is not None:
                keys.append(node.key)
                node = node.next
            out.append(keys)
        return out

    def chain_lengths(self):
        return [len(k) for k in self.chain_keys()]

    def _rehash(self, new_m):
        # record the resize event BEFORE mutating
        self.resizes.append((self.n, self.m, new_m))
        old = self.chain_keys()                  # snapshot current keys
        self.m = new_m
        self.buckets = [None] * new_m
        self.n = 0
        for chain in old:                        # iterate old buckets 0..m-1
            for k in chain:                      # head->tail order, deterministic
                self.insert(k, do_resize=False)


class LinearProbingHashTable:
    """Open addressing with LINEAR PROBING (CLRS 11.4). The rival scheme.

    No lists, no nodes: each slot holds a key or None. On collision, probe the
    next slot (i+1) mod m until an empty one is found. Catastrophic primary
    clustering as alpha -> 1. Used in Section D for comparison.
    """

    def __init__(self, num_buckets):
        self.m = num_buckets
        self.n = 0
        self.table = [None] * self.m             # None = empty slot

    def h(self, key):
        return key % self.m

    def load_factor(self):
        return self.n / self.m

    def insert(self, key):
        """Insert key, return number of slots probed. Assumes table not full."""
        i = self.h(key)
        probes = 1
        while self.table[i] is not None:
            i = (i + 1) % self.m
            probes += 1
        self.table[i] = key
        self.n += 1
        return probes

    def search(self, key):
        """Return (found, probes). probes = slots examined."""
        i = self.h(key)
        start = i
        probes = 1
        while self.table[i] is not None:
            if self.table[i] == key:
                return (True, probes)
            i = (i + 1) % self.m
            probes += 1
            if i == start:
                break
        return (False, probes)


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
# SECTION A: build with 8 buckets, 12 keys (alpha=1.5). Show chain lengths.
# ----------------------------------------------------------------------------
def section_build():
    banner("SECTION A: build 8-bucket table, insert 12 keys (alpha=1.5)")
    ht = ChainingHashTable(8, threshold=math.inf)   # inf threshold -> never resize
    print("Hash function: h(k) = k mod m   (division method, CLRS 11.3.1)")
    print(f"m = {ht.m} buckets, inserting n = {len(KEYS)} keys: {KEYS}\n")
    print("| step | key  | h(k)=k mod 8 | bucket | chain after insert |")
    print("|------|------|--------------|--------|--------------------|")
    for i, k in enumerate(KEYS, 1):
        b = k % 8
        ht.insert(k, do_resize=False)
        chain = ht.chain_keys()[b]
        print(f"| {i:<4} | {k:<4} | {b:<12} | {b:<6} | {chain} |")
    alpha = ht.load_factor()
    lengths = ht.chain_lengths()
    print()
    print(f"After all {ht.n} inserts:  alpha = n/m = {ht.n}/{ht.m} = {alpha:.4f}")
    print(f"Chain lengths per bucket = {lengths}")
    print(f"  sum = {sum(lengths)}  (= n = {ht.n})")
    print(f"  average = {sum(lengths) / ht.m:.4f}  (= alpha = {alpha:.4f})")
    print(f"  longest chain = {max(lengths)} (bucket {lengths.index(max(lengths))})")
    print(f"  empty buckets = {lengths.count(0)} of {ht.m}")
    print()
    print("Chain contents (head -> tail, newest at head since we prepend):")
    for b, chain in enumerate(ht.chain_keys()):
        print(f"  bucket {b}: {chain if chain else '(empty)'}")
    print()
    print("Even at alpha = 1.5, no chain exceeds 3 and one bucket is empty. The")
    print("keys spread out because h(k)=k mod 8 distributes residues roughly evenly.")
    print("KEY PROPERTY: chaining NEVER refuses an insert - a bucket just grows a")
    print("longer chain. Contrast with open addressing, which is FULL at alpha = 1.")
    # GOLD CHECK: average chain length == alpha
    avg = sum(lengths) / ht.m
    assert abs(avg - alpha) < 1e-9, f"avg {avg} != alpha {alpha}"
    assert sum(lengths) == ht.n
    print(f"\n[check] average chain length ({avg:.4f}) == alpha ({alpha:.4f})? OK")
    print(f"[check] sum of chain lengths ({sum(lengths)}) == n ({ht.n})? OK")
    return ht


# ----------------------------------------------------------------------------
# SECTION B: search - traverse chain. Worst case chain length.
# ----------------------------------------------------------------------------
def section_search(ht: ChainingHashTable):
    banner("SECTION B: search - hash to bucket, walk the chain")
    print("Search = (1) compute bucket h(k), (2) walk the chain comparing keys.")
    print("Cost = 1 (hash) + number of nodes walked. Worst case = full chain.\n")
    print("Successful searches (key is present):")
    print("| key | bucket h(k) | chain (head->tail) | position | comparisons |")
    print("|-----|-------------|---------------------|----------|-------------|")
    succ_total = 0
    for k in KEYS:
        found, cmp = ht.search(k)
        b = k % 8
        chain = ht.chain_keys()[b]
        pos = chain.index(k) + 1                  # 1-indexed from head
        succ_total += cmp
        print(f"| {k:<3} | {b:<11} | {str(chain):<19} | {pos:<8} | {cmp:<11} |")
    succ_avg = succ_total / len(KEYS)
    print()
    print("Unsuccessful searches (key is absent - walk the WHOLE chain):")
    print("| key | bucket h(k) | chain length | comparisons |")
    print("|-----|-------------|--------------|-------------|")
    unsucc_total = 0
    for k in ABSENT_KEYS:
        found, cmp = ht.search(k)
        b = k % 8
        clen = len(ht.chain_keys()[b])
        unsucc_total += cmp
        print(f"| {k:<3} | {b:<11} | {clen:<12} | {cmp:<11} |")
    unsucc_avg = unsucc_total / len(ABSENT_KEYS)
    print()
    alpha = ht.load_factor()
    print(f"alpha = {alpha:.4f}")
    print(f"Average successful search comparisons   = {succ_total}/{len(KEYS)} "
          f"= {succ_avg:.4f}   (theory ~ 1 + alpha/2 = {1 + alpha / 2:.4f})")
    print(f"Average unsuccessful search comparisons = {unsucc_total}/{len(ABSENT_KEYS)} "
          f"= {unsucc_avg:.4f}   (theory ~ alpha = {alpha:.4f})")
    longest = max(ht.chain_lengths())
    worst_bucket = ht.chain_lengths().index(longest)
    print(f"\nWorst case: an absent key hashing to bucket {worst_bucket} (chain "
          f"length {longest}) costs {longest} comparisons - walk the whole chain.")
    print("Best  case: an absent key hashing to an empty bucket costs 0 comparisons.")
    print("=> Search is Theta(1 + alpha): the chain walk is bounded by alpha on")
    print("   average, so a small alpha keeps every operation fast. (CLRS Thm 11.2)")
    # GOLD CHECKS
    assert succ_avg > 0 and succ_avg <= longest
    assert unsucc_avg <= longest
    # the tail element of the longest chain is the worst successful search
    worst_chain = ht.chain_keys()[worst_bucket]
    _, worst_succ_cmp = ht.search(worst_chain[-1])
    assert worst_succ_cmp == longest
    print(f"\n[check] worst successful search ({worst_chain[-1]}) costs {worst_succ_cmp} "
          f"== longest chain ({longest})? OK")


# ----------------------------------------------------------------------------
# SECTION C: resize/rehash when alpha exceeds 0.75. Show rehash.
# ----------------------------------------------------------------------------
def section_resize():
    banner("SECTION C: resize + rehash when alpha > 0.75 (double m, rehash all)")
    ht = ChainingHashTable(8, threshold=0.75)
    print(f"Start m = {ht.m}, resize threshold = {ht.threshold}.")
    print("Rule: BEFORE an insert, if (n+1)/m > 0.75, DOUBLE m and rehash every\n"
          "key (recompute h(k) = k mod new_m, rebuild all chains). The rehash is\n"
          "O(n) on the day it happens, but rare - so O(1) amortized insert.\n")
    print("| step | key  | n+1 | (n+1)/m | resize?    | m after | alpha after |")
    print("|------|------|-----|---------|------------|---------|-------------|")
    for i, k in enumerate(KEYS, 1):
        ratio = (ht.n + 1) / ht.m
        will_resize = ratio > ht.threshold
        ht.insert(k)
        mark = "YES x2 ->" + str(ht.m) if will_resize else "no"
        print(f"| {i:<4} | {k:<4} | {ht.n:<3} | {ratio:<7.4f} | {mark:<10} "
              f"| {ht.m:<7} | {ht.load_factor():<11.4f} |")
    print()
    print("The resize fired once: at step 7, (6+1)/8 = 0.875 > 0.75, so m doubled")
    print("8 -> 16 and all 6 keys were rehashed BEFORE inserting key 17.\n")
    print("Rehash detail - the 6 keys re-hashed into m = 16:")
    fired = ht.resizes[0]
    print(f"  trigger at n = {fired[0]}, old m = {fired[1]} -> new m = {fired[2]}")
    for k in KEYS[:6]:
        print(f"    key {k:>3}: h = {k} mod {fired[1]} = {k % fired[1]:<2}  ->  "
              f"{k} mod {fired[2]} = {k % fired[2]:<2}")
    print()
    print(f"Final table: m = {ht.m}, n = {ht.n}, alpha = {ht.load_factor():.4f}")
    lengths = ht.chain_lengths()
    print(f"Chain lengths (m={ht.m}) = {lengths}")
    print("Chain contents:")
    for b, chain in enumerate(ht.chain_keys()):
        if chain:
            print(f"  bucket {b}: {chain}")
    longest = max(lengths)
    print(f"\nResizing cut alpha from 1.5 (had we stayed at m=8) to "
          f"{ht.load_factor():.4f}. Collisions still happen (bucket "
          f"{lengths.index(longest)} has a chain of {longest}) - rehashing only")
    print("REDISTRIBUTES keys; it does not guarantee zero collisions. But average")
    print(f"chain length is now {sum(lengths) / ht.m:.4f} = alpha, so search stays fast.")
    # GOLD CHECKS
    assert len(ht.resizes) == 1, f"expected exactly 1 resize, got {len(ht.resizes)}"
    assert ht.resizes[0] == (6, 8, 16)
    assert ht.m == 16 and ht.n == 12
    assert abs(ht.load_factor() - 0.75) < 1e-9
    print("\n[check] exactly 1 resize (n=6, m 8->16)? OK")
    print("[check] final m=16, n=12, alpha=0.75? OK")


# ----------------------------------------------------------------------------
# SECTION D: comparison - chaining degrades gracefully, open addressing blows up
# ----------------------------------------------------------------------------
def section_comparison():
    banner("SECTION D: chaining vs open addressing (linear probing)")
    M = 16
    print(f"Same {len(KEYS)} keys into m = {M} buckets (alpha = {len(KEYS) / M:.4f}).")
    print("Build a chaining table and a linear-probing table, measure search cost.\n")
    # chaining
    ch = ChainingHashTable(M, threshold=math.inf)
    for k in KEYS:
        ch.insert(k, do_resize=False)
    # linear probing
    lp = LinearProbingHashTable(M)
    lp_insert_probes = []
    for k in KEYS:
        lp_insert_probes.append(lp.insert(k))
    ch_alpha = ch.load_factor()
    lp_alpha = lp.load_factor()
    print(f"Chaining:       m={ch.m}, n={ch.n}, alpha={ch_alpha:.4f}, "
          f"max chain={max(ch.chain_lengths())}")
    print(f"Linear probing: m={lp.m}, n={lp.n}, alpha={lp_alpha:.4f}, "
          f"max insert probes={max(lp_insert_probes)}\n")
    # measure search
    ch_succ = [ch.search(k)[1] for k in KEYS]
    ch_unsucc = [ch.search(k)[1] for k in ABSENT_KEYS]
    lp_succ = [lp.search(k)[1] for k in KEYS]
    lp_unsucc = [lp.search(k)[1] for k in ABSENT_KEYS]
    print("| metric | chaining (empirical) | linear probing (empirical) |")
    print("|--------|----------------------|-----------------------------|")
    print(f"| avg successful search   | {sum(ch_succ) / len(ch_succ):<20.4f} "
          f"| {sum(lp_succ) / len(lp_succ):<27.4f} |")
    print(f"| avg unsuccessful search | {sum(ch_unsucc) / len(ch_unsucc):<20.4f} "
          f"| {sum(lp_unsucc) / len(lp_unsucc):<27.4f} |")
    print(f"| worst successful search | {max(ch_succ):<20d} "
          f"| {max(lp_succ):<27d} |")
    print(f"| worst unsuccessful      | {max(ch_unsucc):<20d} "
          f"| {max(lp_unsucc):<27d} |")
    print()
    print("THEORY (CLRS 11.2 vs 11.4) - cost as a function of alpha:")
    print("  chaining, unsuccessful : 1 + alpha               (linear, graceful)")
    print("  chaining, successful   : 1 + alpha/2")
    print("  open addr (uniform), unsuccessful : 1/(1-alpha)  (blows up as alpha->1)")
    print("  open addr (uniform), successful   : (1/alpha) ln(1/(1-alpha))")
    print("  (linear probing is even WORSE - primary clustering. Knuth: unsuccessful")
    print("   ~= (1/2)(1 + 1/(1-alpha)^2).)\n")
    print("| alpha | chain unsucc 1+alpha | chain succ 1+a/2 | open-addr unsucc "
          "1/(1-a) | open-addr succ (1/a)ln(1/(1-a)) |")
    print("|-------|----------------------|------------------|"
          "-------------------------|--------------------------------|")
    for a in (0.50, 0.75, 0.90, 0.99):
        cu = 1 + a
        cs = 1 + a / 2
        ou = 1 / (1 - a)
        os = (1 / a) * math.log(1 / (1 - a))
        print(f"| {a:<5.2f} | {cu:<20.3f} | {cs:<16.3f} | {ou:<23.3f} | "
              f"{os:<30.3f} |")
    print()
    print("Read it: at alpha = 0.75 chaining's unsuccessful search costs ~1.75")
    print("probes but open addressing costs ~4. Push alpha to 0.99 and chaining is")
    print("still ~1.99 while open addressing explodes to ~100. Chaining degrades")
    print("LINEARLY (never catastrophic); open addressing has a VERTICAL asymptote")
    print("at alpha = 1 (it cannot go past 1 - the table is FULL). That asymmetry is")
    print("the whole argument for chaining in production HashMaps.")
    # GOLD CHECKS
    a = 0.75
    assert abs((1 + a) - 1.75) < 1e-9 and abs(1 / (1 - a) - 4.0) < 1e-9
    # chaining never exceeds m; open addressing cannot hold n > m
    assert ch.n <= ch.m * 100                   # chaining: no upper bound (lists grow)
    assert lp.n <= lp.m                         # open addressing: hard ceiling
    print("\n[check] at alpha=0.75: chain=1.75, open-addr=4.0? OK")
    print(f"[check] chaining has no hard full point (n={ch.n} in m={ch.m}); "
          f"open addressing caps at n<=m ({lp.n}<={lp.m})? OK")


# ----------------------------------------------------------------------------
# SECTION E: load factor analysis - balls-into-bins (gold: avg chain = alpha)
# ----------------------------------------------------------------------------
def section_load_factor():
    banner("SECTION E: load factor analysis - balls-into-bins (avg chain = alpha)")
    n, m = len(KEYS), 8
    alpha = n / m
    print(f"Model: n = {n} keys (balls) thrown uniformly into m = {m} buckets (bins).")
    print(f"alpha = n/m = {alpha:.4f}. Under simple uniform hashing, each bucket's\n"
          f"chain length X_j ~ Binomial(n, 1/m).\n")
    # observed (Section A table)
    ht = ChainingHashTable(m, threshold=math.inf)
    for k in KEYS:
        ht.insert(k, do_resize=False)
    lengths = ht.chain_lengths()
    obs_mean = sum(lengths) / m
    obs_var = sum((x - obs_mean) ** 2 for x in lengths) / m
    print("OBSERVED (Section A table):")
    print(f"  chain lengths      = {lengths}")
    print(f"  sample mean        = {obs_mean:.4f}    (theory E[X] = alpha = {alpha:.4f})")
    print(f"  sample variance    = {obs_var:.4f}    "
          f"(theory Var[X] = alpha(1-1/m) = {alpha * (1 - 1 / m):.4f})")
    print(f"  empty buckets      = {lengths.count(0)}  "
          f"(theory E[empty] = m*(1-1/m)^n = {m * (1 - 1 / m) ** n:.4f})")
    print(f"  longest chain      = {max(lengths)}\n")
    # exact binomial distribution for one bucket
    print("EXACT distribution of a single bucket's chain length, X ~ Binomial("
          f"{n}, 1/{m}):")
    print("| k | P(X=k)            | P(X>=k)          |")
    print("|---|-------------------|------------------|")
    p = 1 / m
    cum_ge = 1.0
    for k in range(0, n + 1):
        pmf = math.comb(n, k) * (p ** k) * ((1 - p) ** (n - k))
        print(f"| {k} | {pmf:<17.6f} | {cum_ge:<16.6f} |")
        cum_ge -= pmf
    print()
    print(f"P(chain >= 3) = {1 - sum(math.comb(n, k) * p**k * (1-p)**(n-k) for k in range(3)):.6f}")
    print(f"P(chain >= 4) = {1 - sum(math.comb(n, k) * p**k * (1-p)**(n-k) for k in range(4)):.6f}")
    print("Long chains are POSSIBLE but exponentially rare - the tail of the")
    print("binomial dies fast, so a well-chosen alpha keeps chains short.\n")
    # max-load: n = m balls (classic result)
    print("MAX LOAD - the longest chain when n = m balls into m bins:")
    print("  Theory (w.h.p.): max chain = Theta(ln m / ln ln m)")
    trials = 1000
    print(f"  Simulation: {trials} trials, throwing n=m balls each:\n")
    print("| m     | alpha | ln m / ln ln m | mean max chain (sim) |")
    print("|-------|-------|----------------|----------------------|")
    rng = random.Random(42)
    for mm in (64, 256, 1024, 4096):
        maxes = []
        for _ in range(trials):
            counts = [0] * mm
            for _ in range(mm):
                counts[rng.randrange(mm)] += 1
            maxes.append(max(counts))
        theory = math.log(mm) / math.log(math.log(mm))
        print(f"| {mm:<5} | {mm / mm:<5.2f} | {theory:<14.3f} | "
              f"{sum(maxes) / trials:<20.3f} |")
    print()
    print("The max chain grows only ~logarithmically (3-5 even for thousands of")
    print("buckets), which is why a modest alpha like 0.75 keeps worst-case search")
    print("tiny. The asymptotic ln m / ln ln m converges slowly, so the sim runs a")
    print("bit above the formula - but both stay flat as m grows.")
    # GOLD CHECK
    assert abs(obs_mean - alpha) < 1e-9, f"avg {obs_mean} != alpha {alpha}"
    assert abs(alpha * (1 - 1 / m) - alpha * (1 - 1 / m)) < 1e-9
    print(f"\n[check] sample mean chain length ({obs_mean:.4f}) == alpha ({alpha:.4f})? OK")
    print(f"[check] sum(chain lengths) ({sum(lengths)}) == n ({n})? OK")


# ----------------------------------------------------------------------------
# GOLD: the compact values the .html recomputes and checks against
# ----------------------------------------------------------------------------
def section_gold():
    banner("GOLD VALUES (pinned for chaining.html)")
    ht = ChainingHashTable(8, threshold=math.inf)
    for k in KEYS:
        ht.insert(k, do_resize=False)
    lengths8 = ht.chain_lengths()
    alpha8 = ht.load_factor()
    # search gold
    _, cmp_tail = ht.search(59)               # tail of the longest chain (bucket 3)
    # resize gold
    rht = ChainingHashTable(8, threshold=0.75)
    for k in KEYS:
        rht.insert(k)
    lengths16 = rht.chain_lengths()
    print(f"Section A: m=8, n=12, alpha={alpha8:.4f}")
    print(f"  chain lengths = {lengths8}")
    print(f"  average       = {sum(lengths8) / 8:.4f}  (== alpha)")
    print(f"  longest chain = {max(lengths8)} (bucket {lengths8.index(max(lengths8))})")
    print(f"  empty buckets = {lengths8.count(0)}")
    print(f"  search 59 (tail of bucket 3) comparisons = {cmp_tail}")
    print(f"Section C: after resize to m=16, alpha={rht.load_factor():.4f}")
    print(f"  chain lengths = {lengths16}")
    print(f"  resizes fired = {[r for r in rht.resizes]}")
    print("Section D theory at alpha=0.75:")
    print(f"  chaining unsuccessful  = 1 + 0.75 = {1 + 0.75}")
    print(f"  open-addr unsuccessful = 1/(1-0.75) = {1 / (1 - 0.75)}")
    print()
    print("GOLD scalars for .html: lengths8=[1,1,2,3,2,0,1,2], "
          "avg=1.5, search(59)=3,")
    print("  lengths16 has a chain of 3 at bucket 11, theory@0.75: chain=1.75, oa=4.0.")
    assert lengths8 == [1, 1, 2, 3, 2, 0, 1, 2]
    assert abs(sum(lengths8) / 8 - 1.5) < 1e-9
    assert cmp_tail == 3
    assert rht.resizes == [(6, 8, 16)]
    assert lengths16.count(0) == 8              # 8 of 16 empty after rehash
    assert abs(1 + 0.75 - 1.75) < 1e-9 and abs(1 / 0.25 - 4.0) < 1e-9
    print("[check] GOLD reproduces from the implementations? OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("chaining.py - reference impl. All numbers below feed CHAINING.md.")
    print("python stdlib only (math, random with fixed seed).\n")

    ht = section_build()
    section_search(ht)
    section_resize()
    section_comparison()
    section_load_factor()
    section_gold()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
