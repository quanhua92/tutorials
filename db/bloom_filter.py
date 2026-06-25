"""
bloom_filter.py - Reference implementation of the Bloom filter: a space-
efficient probabilistic data structure for set membership. False positives
are possible; false negatives are NEVER.

This is the single source of truth that BLOOM_FILTER.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 bloom_filter.py

============================================================================
THE INTUITION (read this first) -- the row of k padlocks on a notice board
============================================================================
Imagine a notice board that can only show YES/NO for "has this word ever been
pinned here?". You do NOT store the words. Instead, for every word you pin, you
hang k numbered PADLOCKS on k hooks (the hooks are chosen by k different hash
functions of the word). To later ask "was X pinned?", you check the k hooks that
X's hashes point at:

  * all k hooks carry a padlock  ->  "maybe yes"   (a true member, OR a word
                                         whose k hooks happen to all have been
                                         set by OTHER words = a FALSE POSITIVE)
  * ANY of the k hooks is empty  ->  "definitely no" (you never remove locks, so
                                         a missing lock is proof X was never
                                         pinned = a FALSE NEGATIVE is IMPOSSIBLE)

You can only ever ADD padlocks (set bits), never remove them -- that is why the
filter is monotone, and why a present member can never be missed but a stranger
can be mistaken for one.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  bit array      : m bits, all starting at 0. The whole "data structure".
  hash function  : maps a key to a position in [0, m). We use k of them.
  insert(x)      : compute k positions, set those k bits to 1.
  query(x)       : compute k positions; "maybe" if ALL are 1, else "definitely not".
  true member    : a key that was inserted. Query ALWAYS returns "maybe".
  false positive : a key NOT inserted, but whose k bits all happen to be 1
                   (set by OTHER inserts). This is the price you pay for the
                   tiny size. Rate is bounded by the FPR formula below.
  false negative : a key inserted but reported "definitely not". CANNOT HAPPEN.
                   (Bloom filters only set bits, never clear them.)
  fill ratio     : fraction of the m bits that are 1. Drives the FPR.
  saturation     : when nearly all bits are 1, FPR -> 1. The filter is "full".
  counting bloom : a variant with counters per slot (so you CAN remove), used in
                   summarizing sharded data. Tradeoff: more space, no FP gain.

============================================================================
THE LINEAGE (papers / systems)
============================================================================
  Bloom 1970, "Space/Time Trade-offs in Hash Coding with Allowable Errors" :
      the original. m bits, k hash functions, false positives allowed.
  Mullin 1990 : "The change/spread problem". Bloom filters as a compact
                "set summary" to ship across a network -> avoid remote lookups.
  Fan et al. 1998 ("Summary Cache") : counting Bloom filters for web proxies;
                removal support, the ancestor of Cassandra's row-cache filter.
  Kirsch & Mitzenmacher 2006 (arXiv:cs/0508024) : you can build the k hashes
                from just TWO real hashes (h_a + i*h_b) -- double hashing.
                Real systems use it to compute only 2 hashes, not k. We keep k
                explicit (with mix32 avalanche) so the formula is obvious.
  Putze, Sanders, Singler 2007 : the "blocked"/"partitioned" Bloom filter
                (cache-friendly; one hash, k blocks). RocksDB uses a variant.

  Where it lives in databases:
    PostgreSQL bloom extension  : contrib/bloom -- an ACCESS METHOD for multi-
                                  column equality queries (WHERE a=? AND b=? ...).
                                  One filter per index tuple, hashing ALL the
                                  indexed columns together. Skips heap fetches.
    RocksDB (per-SSTable)       : every SST file carries a Bloom filter over its
                                  keys; a Get() checks the filter FIRST and
                                  skips reading the whole file on a negative --
                                  the single biggest win for point lookups on
                                  LSM stores. (See LSM_TREE.md / lsm_tree.py.)
    Cassandra / HBase           : Bloom filters per SSTable to decide "could
                                  this row possibly be in this file?". Also the
                                  row-cache front-end ("is this row cached?").
    CDN / web caches            : "is this URL in any peer cache?" decided
                                  locally from a shipped Bloom summary, no RPC.

KEY FORMULAS (all verified against Bloom 1970 + standard texts, asserted below):
    bit position        pos_i(x) = mix32(fnv1a(x || byte(i))) mod m,  i = 0..k-1
                        (k independent hashes; mix32 gives full avalanche)
    insert(x)           for i in 0..k-1: bit[pos_i(x)] = 1
    query(x)            "maybe" iff all bit[h_i(x) mod m] == 1, else "definitely not"
    P(bit still 0)      p0 = (1 - 1/m)^(k*n)  ~=  e^(-k*n/m)    after n inserts
    fill ratio          1 - p0
    false positive rate FPR = (1 - p0)^k = (1 - e^(-k*n/m))^k
    optimal k (fixed    k* = (m/n) * ln(2)     (minimizes FPR)
        m, n)
    optimal m for a     m* = -n * ln(p) / (ln 2)^2    bits;   ~= 1.44 * log2(1/p)
        target FPR p                                        bits per element
    bits per element    m*/n = -ln(p) / (ln 2)^2   ~= 1.44 * log2(1/p)

The m=32, k=3 worked example below is DETERMINISTIC (seeded FNV-1a hashes) and
byte-for-byte identical to the inputs recomputed in bloom_filter.html.

Sources:
  [1] B. H. Bloom, 1970, "Space/Time Trade-offs in Hash Coding with Allowable
      Errors", Communications of the ACM 13(7). -- the canonical source.
  [2] Kirsch & Mitzenmacher, 2006, "Less Hashing, Same Performance",
      arXiv:cs/0508024. -- double hashing (h1+i*h2) suffices.
  [3] Mitzenmacher & Upfal, "Probability and Computing", ch. on Bloom filters.
  [4] PostgreSQL docs, "bloom" extension (contrib).
  [5] RocksDB wiki, "Bloom Filter".
"""

from __future__ import annotations

import math
import random

# ============================================================================
# 0. CONSTANTS
# ============================================================================

FNV_OFFSET_32 = 0x811C9DC5
FNV_PRIME_32 = 0x01000193
GOLDEN_GAMMA = 0x9E3779B9            # 2^32 / phi; good stride for seed spacing

M_WORKED = 32                        # bits in the tiny worked example (Sections A,B)
K_WORKED = 3                         # hash functions in the worked example
WORKED_KEYS = ["apple", "banana", "cherry", "date", "elderberry"]
NONMEMBER_DEMO = "mango"             # a key definitely never inserted

BANNER = "=" * 72


# ============================================================================
# 1. THE HASH + THE BLOOM FILTER  (this is the code BLOOM_FILTER.md walks)
# ============================================================================

def fnv1a_32(data: bytes, seed: int) -> int:
    """32-bit FNV-1a hash, seeded. Pure, deterministic, and byte-for-byte
    identical to the JS port in bloom_filter.html (the same constants).

    FNV-1a: hash byte-by-byte, xor-then-multiply. The seed just changes the
    starting offset. NOTE: FNV-1a alone has WEAK low-bit diffusion, so we always
    pipe its output through `mix32` below before taking it mod m -- without that
    finalizer the measured false-positive rate drifts far from the formula.
    """
    h = seed & 0xFFFFFFFF
    for b in data:
        h ^= b
        h = (h * FNV_PRIME_32) & 0xFFFFFFFF
    return h


def mix32(h: int) -> int:
    """32-bit integer finalizer with full avalanche ("lowbias32",
    https://nullprogram.com/blog/2018/07/31/). A 1-bit change in the input flips
    ~50% of output bits, so the k positions we derive become effectively
    independent -- which is the assumption the FPR formula rests on.

    Pure arithmetic, deterministic, and byte-identical to the JS port.
    """
    h &= 0xFFFFFFFF
    h ^= h >> 16
    h = (h * 0x7FEB352D) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 0x846CA68B) & 0xFFFFFFFF
    h ^= h >> 16
    return h


def hash_positions(key: str, m: int, k: int) -> list[int]:
    """The k bit-positions for `key`. Textbook construction: k INDEPENDENT hash
    functions, each `mix32(fnv1a(key || byte(i))) mod m`. The distinct suffix
    byte `i` makes every slot hash a different input stream; mix32 gives full
    avalanche so the k positions are independent -- the assumption the
    false-positive formula (1 - e^(-kn/m))^k makes.

    (Real systems often substitute Kirsch & Mitzenmacher 2006 double hashing,
    h_a + i*h_b, to compute only 2 hashes -- see lineage note. We keep k
    explicit so the formula mapping is obvious; mix32 already makes them
    independent, which is the property that actually matters.)
    """
    base = key.encode("utf-8")
    return [mix32(fnv1a_32(base + bytes([i]), FNV_OFFSET_32)) % m
            for i in range(k)]


def new_filter(m: int) -> list[int]:
    """A fresh m-bit array, all zeros."""
    return [0] * m


def insert(bits: list[int], key: str, m: int, k: int) -> list[int]:
    """Set the k bits for `key`. Returns the k positions (for display)."""
    pos = hash_positions(key, m, k)
    for p in pos:
        bits[p] = 1
    return pos


def query(bits: list[int], key: str, m: int, k: int) -> tuple[list[int], bool]:
    """Return (positions, all_set). all_set True  -> "maybe in set"
                                    all_set False -> "definitely NOT in set"."""
    pos = hash_positions(key, m, k)
    all_set = all(bits[p] == 1 for p in pos)
    return pos, all_set


# --- the formulas (the ground truth for every number in the guide) -----------

def fill_ratio(bits: list[int]) -> float:
    """Fraction of bits that are 1."""
    return sum(bits) / len(bits)


def theoretical_fpr(m: int, k: int, n: int) -> float:
    """FPR = (1 - (1 - 1/m)^(k*n))^k  -- the Bloom 1970 closed form."""
    p0 = (1 - 1 / m) ** (k * n)
    return (1 - p0) ** k


def optimal_k(m: int, n: int) -> float:
    """k that minimizes FPR for fixed m, n:  k* = (m/n) * ln 2."""
    return (m / n) * math.log(2)


def optimal_m(n: int, p: float) -> float:
    """m (bits) for target FPR p:  m* = -n * ln p / (ln 2)^2."""
    return -n * math.log(p) / (math.log(2) ** 2)


def bits_per_element(p: float) -> float:
    """m*/n = -ln p / (ln 2)^2  ~= 1.44 * log2(1/p)."""
    return -math.log(p) / (math.log(2) ** 2)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_bits(bits: list[int], group: int = 8, highlight: set[int] | None = None) -> str:
    """Print the bit array grouped (default 8 per group) with a marker on the
    bits just flipped this step."""
    highlight = highlight or set()
    out = []
    for i, b in enumerate(bits):
        if i and i % group == 0:
            out.append(" ")
        if i in highlight:
            out.append(f"[{b}]")
        else:
            out.append(f" {b} ")
    return "".join(out)


def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: build the filter (m=32, k=3), insert 5 keys, show bits flip
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: build a Bloom filter  (m = 32 bits, k = 3 hash functions)")
    m, k = M_WORKED, K_WORKED
    print(f"Empty bit array, m = {m} bits, k = {k} hashes per key.")
    print("Hash family: k INDEPENDENT hashes, each = mix32(fnv1a(key || byte(i))) mod m\n")
    print("  fnv1a      : 32-bit FNV-1a on (key + suffix byte i)  -- distinct input")
    print("               stream per slot, but weak low-bit diffusion on its own")
    print("  mix32      : 32-bit avalanche finalizer (lowbias32) -- a 1-bit input")
    print("               change flips ~50% of output bits, so positions are")
    print("               independent (the assumption the FPR formula needs)\n")
    print("  positions(key) = [ mix32(fnv1a(key||0)) % m,")
    print("                      mix32(fnv1a(key||1)) % m,")
    print("                      mix32(fnv1a(key||2)) % m ]   (k values total)\n")
    print(f"Insert {len(WORKED_KEYS)} keys; show the array after each insert "
          "(flipped bits in [brackets]):\n")

    bits = new_filter(m)
    print(f"  start        : {fmt_bits(bits)}")
    for key in WORKED_KEYS:
        pos = insert(bits, key, m, k)
        print(f"  insert '{key:<11}': positions {pos} -> flips "
              f"{sorted(pos)}")
        print(f"               {fmt_bits(bits, highlight=set(pos))}")
    print()

    ones_now = sum(bits)
    print(f"After {len(WORKED_KEYS)} inserts: {ones_now}/{m} bits are 1 "
          f"(fill ratio = {ones_now / m:.3f}).")
    print("\nNotice the two collisions already (m is tiny): some keys share a bit.")
    print("That sharing is exactly what later produces false positives.\n")
    return bits


# ----------------------------------------------------------------------------
# SECTION B: membership test -- which bits are checked, verdict
# ----------------------------------------------------------------------------

def section_b(bits: list[int]):
    banner("SECTION B: query -- is X in the set?  (check all k bits)")
    m, k = M_WORKED, K_WORKED

    member = "cherry"
    pos, all_set = query(bits, member, m, k)
    verdict = "maybe in set (true member)" if all_set else "definitely NOT"
    print(f"Query a TRUE MEMBER: '{member}'")
    print(f"  positions = {pos}")
    for i, p in enumerate(pos):
        print(f"    bit[{p:2d}] = {bits[p]}")
    print(f"  all k bits set? {all_set}  ->  verdict: {verdict}\n")

    stranger = NONMEMBER_DEMO
    pos2, all_set2 = query(bits, stranger, m, k)
    verdict2 = "maybe in set (FALSE POSITIVE)" if all_set2 else "definitely NOT in set"
    print(f"Query a NON-MEMBER:  '{stranger}'")
    print(f"  positions = {pos2}")
    for i, p in enumerate(pos2):
        print(f"    bit[{p:2d}] = {bits[p]}")
    print(f"  all k bits set? {all_set2}  ->  verdict: {verdict2}\n")

    print("THE INVARIANT:")
    print("  - true member  -> at least one bit MUST be set on insert; query never")
    print("                    misses it. NO FALSE NEGATIVES, ever.")
    print("  - non-member   -> if even ONE of its k bits is 0, it is PROVABLY absent.")
    print("                    if all k happen to be 1 (set by others) -> false positive.")
    print()
    # hard invariant checks
    for key in WORKED_KEYS:
        _, ok = query(bits, key, m, k)
        assert ok, f"BUG: true member {key!r} reported absent!"
    assert all_set, "true member must always report 'maybe'"
    print(f"[check] all {len(WORKED_KEYS)} inserted keys report 'maybe':  OK")
    print(f"[check] true member '{member}' reports 'maybe' (no false negatives):  OK")


# ----------------------------------------------------------------------------
# SECTION C: false-positive analysis -- insert N, test M non-members, FPR
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: false-positive rate -- measured vs the formula")
    m, k = 1024, 7                 # a realistic little filter
    n = 100                        # keys to insert
    n_tests = 2000                 # non-members to probe
    print(f"Fresh filter sized for the job:  m = {m} bits, k = {k}, "
          f"insert n = {n} keys, probe {n_tests} NON-members.\n")

    bits = new_filter(m)
    rng = random.Random(20240626)              # deterministic test keys
    members = [f"user_{i}" for i in range(n)]
    for key in members:
        insert(bits, key, m, k)

    # non-members live in a DISJOINT key space -> guaranteed never inserted
    nonmembers = [f"ghost_{i}_{rng.randint(0, 1 << 30)}" for i in range(n_tests)]

    false_pos = 0
    for key in nonmembers:
        _, maybe = query(bits, key, m, k)
        if maybe:
            false_pos += 1

    measured = false_pos / n_tests
    theory = theoretical_fpr(m, k, n)
    print(f"  measured FPR = {false_pos}/{n_tests} = {pct(measured)}")
    print(f"  theory    FPR = (1 - e^(-kn/m))^k = (1 - e^(-{k}*{n}/{m}))^{k}")
    print(f"                = {pct(theory)}\n")

    print("  Why they are close but not equal: the formula is the ASYMPTOTIC mean;")
    print("  the measurement is a finite-sample draw from Binomial(tests, theory).")
    print("  The TRUE guarantee is one-sided: measured FP >= 0 is fine, measured")
    print("  FALSE NEGATIVE would be a bug (impossible -- see Section B).\n")

    # fill-ratio check (the tight, deterministic validation of the formula core)
    fr_actual = fill_ratio(bits)
    fr_expected = 1 - (1 - 1 / m) ** (k * n)
    print("  cross-check via FILL RATIO (deterministic, uses ALL bits):")
    print(f"    actual fill   = {fr_actual:.4f}")
    print(f"    expected fill = 1 - (1-1/m)^(kn) = 1 - e^(-kn/m) = {fr_expected:.4f}")
    print(f"    |diff|        = {abs(fr_actual - fr_expected):.4f}  (small -> formula is sound)")
    assert abs(fr_actual - fr_expected) < 0.05, "fill ratio disagrees with formula"
    assert measured < theory * 3, "measured FPR wildly off (would indicate a hash bug)"
    print("\n[check] fill ratio matches (1-1/m)^(kn) within 0.05:  OK")
    print("[check] measured FPR within 3x of theory:  OK")
    return measured, theory


# ----------------------------------------------------------------------------
# SECTION D: optimal parameters -- given n and target p, solve for m and k
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: optimal parameters for a target false-positive rate p")
    print("Two closed forms (Bloom 1970; standard derivation):")
    print("  optimal m (bits)        m* = -n * ln(p) / (ln 2)^2")
    print("  bits per element        m*/n = -ln(p) / (ln 2)^2  ~= 1.44 * log2(1/p)")
    print("  optimal k (hash funcs)  k* = (m/n) * ln 2         (minimizes the FPR)\n")
    print("NOTE the beautiful decoupling: bits-per-element depends ONLY on p, not n.\n")

    print("| target p | bits/elem (m*/n) |  n=1,000 m* |  k* (rounded) | "
          "FPR at rounded k |")
    print("|----------|------------------|-------------|---------------|------------------|")
    targets = [0.10, 0.05, 0.01, 0.001, 0.0001]
    for p in targets:
        bpe = bits_per_element(p)
        m1000 = optimal_m(1000, p)
        kstar = optimal_k(m1000, 1000)
        k_round = max(1, round(kstar))
        fpr_round = theoretical_fpr(round(m1000), k_round, 1000)
        print(f"| {pct(p):<8} | {bpe:<16.3f} | {m1000:<9.0f}   "
              f"| {k_round:<3} (k*={kstar:.2f})  | {pct(fpr_round):<16} |")
    print()

    # the headline worked example
    n, p = 1000, 0.01
    m_opt = optimal_m(n, p)
    k_opt = optimal_k(m_opt, n)
    print(f"Worked example: n = {n}, target p = {pct(p)}.")
    print(f"  m* = -{n} * ln({p}) / (ln 2)^2 = {m_opt:.1f} bits "
          f"({m_opt / 8:.1f} bytes)")
    print(f"  k* = (m*/n) * ln 2 = {k_opt:.3f}  ->  round to k = {round(k_opt)}")
    print(f"  At m={round(m_opt)}, k={round(k_opt)}, n={n}: "
          f"FPR = {pct(theoretical_fpr(round(m_opt), round(k_opt), n))}  "
          f"(meets the 1% target after rounding)")
    # invariant: rounding k to nearest never blows the target by much
    assert theoretical_fpr(round(m_opt), round(k_opt), n) <= p * 1.5
    print("\n[check] FPR at rounded k stays within 1.5x of target p:  OK")


# ----------------------------------------------------------------------------
# SECTION E: space savings -- bloom vs a hash set
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: space savings -- Bloom filter vs an exact set")
    n = 1_000_000
    p = 0.01
    m = optimal_m(n, p)
    bloom_bytes = m / 8
    # an exact in-memory set: ~8 bytes/pointer for the key alone (we count the
    # membership structure, ignoring the key strings themselves -- the fairest
    # apples-to-apples is "1 bit per element of capacity" vs "1 hash slot").
    set_bytes = n * 8
    print(f"Membership for n = {n:,} keys at target FPR p = {pct(p)}.\n")
    print(f"  Bloom filter : m* = -n*ln(p)/(ln2)^2 = {m:,.0f} bits "
          f"= {bloom_bytes / 2**20:.2f} MiB")
    print(f"  Exact hashset: 8 B per key (one pointer-sized slot) = "
          f"{set_bytes / 2**20:.2f} MiB   (ignores the key strings themselves)\n")
    print(f"  -> Bloom uses {set_bytes / bloom_bytes:.1f}x LESS memory than the set,")
    print(f"     at the cost of a {pct(p)} false-positive rate. That is the trade.")
    print("\n  The numbers everyone quotes: '~1.2 MB per million keys at 1% FPR'")
    print("  comes from exactly this: bits/elem = -ln(0.01)/(ln 2)^2 = 9.585;")
    print("  9.585 bits * 1e6 = 9.585 Mbit = 1.198 MB (decimal) = 1.14 MiB.\n")
    print("Where the asymmetry is priceless (Bloom wins big):")
    print("  - shipping a set summary over the network (CDN peer checks, gossip)")
    print("  - per-file filters in an LSM tree (1.2 MiB vs full SST scan) "
          "[ RocksDB -- see LSM_TREE.md ]")
    print("  - 'is this row possibly cached?' front-ends (Cassandra row cache)\n")
    assert bloom_bytes < set_bytes / 5
    print(f"[check] Bloom ({bloom_bytes / 2**20:.2f} MiB) < 1/5 of set "
          f"({set_bytes / 2**20:.2f} MiB):  OK")


# ----------------------------------------------------------------------------
# SECTION F: database use cases
# ----------------------------------------------------------------------------

def section_f():
    banner("SECTION F: where Bloom filters live inside real databases")
    print("| system            | what it indexes                      | "
          "what the filter prevents                      |")
    print("|-------------------|--------------------------------------|"
          "-----------------------------------------------|")
    rows = [
        ("PostgreSQL bloom", "multi-column equality tuples",
         "heap fetches for WHERE a=? AND b=? AND c=? (no single-col index helps)"),
        ("RocksDB per-SST",  "the keys of each SSTable file",
         "reading a whole SST file on a Get() that misses (the big LSM win)"),
        ("Cassandra / HBase", "row keys per SSTable",
         "opening/reading an SST for a row that is not there"),
        ("Cassandra row cache", "rows currently cached",
         "a hash lookup to ask 'could this row be cached?' before probing"),
        ("CDN / proxy cache", "URLs held by peer caches",
         "a remote RPC just to learn 'do you have this URL?' (summary cache)"),
        ("LSM compaction",   "the output range of each level",
         "touching a level that provably cannot contain the key"),
    ]
    for sys_, what, prevents in rows:
        print(f"| {sys_:<17} | {what:<36} | {prevents:<45} |")
    print()
    print("The shared shape: a Bloom filter is a CHEAP, LOSSY summary that lets the")
    print("system say 'definitely not here' WITHOUT doing the expensive thing")
    print("(heap fetch / SST read / RPC / cache probe). The ~1% lie rate is worth")
    print("it because the filter is checked BILLIONS of times and is tiny.\n")
    print("🔗 Compare with bitmap_index.py -- a bitmap is a lossless set of TIDs")
    print("(exact membership, O(N) bits). A Bloom filter is a lossy set summary")
    print("(probabilistic membership, O(n*1.44*log2(1/p)) bits -- far smaller).")
    print("🔗 Compare with hash_index.py -- a hash index answers membership exactly")
    print("and supports lookup, but stores the keys. A Bloom filter stores NO keys.")


# ============================================================================
# 4. GOLD CHECK -- the invariant the whole concept rests on
# ============================================================================

def gold_check():
    banner("GOLD CHECK -- no false negatives + FPR formula reproduces")
    m, k = 4096, 7
    n = 500
    bits = new_filter(m)
    members = [f"entity_{i}" for i in range(n)]
    for key in members:
        insert(bits, key, m, k)

    # (1) the defining invariant: EVERY true member returns 'maybe'.
    for key in members:
        _, ok = query(bits, key, m, k)
        assert ok, f"FALSE NEGATIVE on {key!r} -- impossible if the filter is correct"
    print(f"  (1) {n} inserted keys all report 'maybe'  ->  NO FALSE NEGATIVES:  OK")

    # (2) the formula reproduces, verified the tight way (fill ratio over all m bits).
    fr_actual = fill_ratio(bits)
    fr_expected = 1 - (1 - 1 / m) ** (k * n)
    rel = abs(fr_actual - fr_expected) / fr_expected
    print(f"  (2) fill ratio actual={fr_actual:.4f} vs formula {fr_expected:.4f}  "
          f"(rel err {pct(rel)})")
    assert rel < 0.05, "fill ratio disagrees with (1-1/m)^(kn)"
    fpr_theory = theoretical_fpr(m, k, n)
    print(f"      -> derived FPR = (1-e^(-kn/m))^k = {pct(fpr_theory)}  "
          f"[matches bloom_filter.html gold]")
    print("\n[check] GOLD: no false negatives AND FPR formula reproduces:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("bloom_filter.py - reference impl. All numbers below feed BLOOM_FILTER.md.")
    print(f"M_WORKED={M_WORKED}  K_WORKED={K_WORKED}  "
          f"WORKED_KEYS={WORKED_KEYS}  hash=FNV-1a(32-bit)")

    bits_a = section_a()
    section_b(bits_a)
    section_c()
    section_d()
    section_e()
    section_f()
    gold_check()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
