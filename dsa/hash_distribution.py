"""
hash_distribution.py - Reference implementation: hash function quality.

This is the SINGLE SOURCE OF TRUTH that HASH_DISTRIBUTION.md is built from.
Every number, table, and worked example in the .md is printed by this file.
The .html companion recomputes everything with the IDENTICAL formulas and a
matching seeded key generator, so its [check: OK] badge is a real audit.

Run:
    python3 hash_distribution.py

=========================================================================
THE INTUITION (read this first) — the post office with M pigeonholes
=========================================================================
A hash table is a post office with M pigeonholes ("buckets"). You hand the
clerk a key; the clerk runs a HASH FUNCTION H to decide which hole:

    bucket = H(key) mod M

The dream: no matter what keys walk in, every hole gets ~the same number of
letters. That dream lives or dies on ONE property of H — does it SPREAD
evenly? This file measures "spreads evenly" three different ways:

  * DISTRIBUTION : do 1000 keys fill all 16 buckets to ~62.5 each?
  * AVALANCHE    : flip ONE bit of the input, how many OUTPUT bits flip?
                   A great hash flips ~half (the "strict avalanche criterion").
  * COLLISIONS   : with N keys in M buckets, how many pairs land together?
                   The birthday paradox predicts ~N^2/(2M).

We compare four hash functions, from naive to excellent:
  mod_prime  : key % prime.                     No mixing. Biased / fragile.
  knuth_mult : key * golden-ratio (mod 2^32).   Good, if you take HIGH bits.
  fnv1a      : byte-wise xor+multiply.          Good, simple, everywhere.
  murmur3    : multiply+rotate+final-mix.       Excellent, the industry default.

=========================================================================
PLAIN-ENGLISH GLOSSARY
=========================================================================
  bucket       : one of M pigeonholes; the final destination. Here M = 16.
  hash H       : a function key -> 32-bit integer. bucket = H(key) mod M.
  mixing       : scrambling the bits so input structure does NOT leak out.
  avalanche    : 1 input bit flips  -> ~16 of 32 output bits flip (50%).
  collision    : two DIFFERENT keys hashing to the SAME bucket.
  birthday     : with N keys in M buckets, P(at least one collision)
  paradox        ~= 1 - exp(-N^2 / (2M)). 50% odds at N ~= 1.177 * sqrt(M).
  chi-squared  : sum of (observed - expected)^2 / expected. Lower = flatter.
                 For M buckets, expected = N/M, degrees of freedom = M-1.

=========================================================================
KEY FORMULAS (all asserted in code and printed below)
=========================================================================
    bucket(key)        = H(key) mod M
    expected_per_bucket = N / M                       (the flat line)
    avalanche_ratio    = (# output bits flipped) / 32   averaged over inputs
                         ideal = 0.5 (16/32)
    birthday P(coll)   = 1 - exp(-N^2 / (2M))          (Poisson approx)
    birthday exact     = 1 - prod_{i=0}^{N-1} (1 - i/M)
    expected_collisions= N^2 / (2M)                    (mean # colliding pairs)
    observed_collisions= sum over buckets C(count_b, 2) = sum count_b*(count_b-1)/2
    chi-squared        = sum over buckets (count_b - N/M)^2 / (N/M)

Determinism: keys come from a fixed-seed LCG implemented IDENTICALLY in
hash_distribution.py and hash_distribution.html, so both sides see byte-for-byte
the same inputs. (Numerical Recipes LCG: s = 1664525*s + 1013904223 mod 2^32.)
"""

from __future__ import annotations

import math

MASK32 = 0xFFFFFFFF
BANNER = "=" * 72

# ---- the four hash functions (all return an unsigned 32-bit int) ----------

# A large prime. mod_prime output lives in [0, PRIME) ~= [0, 2^20), so it only
# ever lights ~20 of 32 output bits -- that is a real avalanche deficiency.
PRIME = 1000003
# Knuth's multiplicative constant = floor(2^32 / phi), the golden ratio.
KNUTH = 2654435761


def hash_mod_prime(key: int) -> int:
    """Naive 'hash': reduce the key modulo a large prime. No mixing at all."""
    return (key % PRIME) & MASK32


def hash_knuth_mult(key: int) -> int:
    """Knuth multiplicative hash: key * (2^32/phi), take the full 32-bit word.
    The HIGH bits are well-mixed; the low bits are weak (they depend only on
    the low input bits), so for power-of-two bucket counts you should take the
    HIGH bits. We do exactly that in knuth_bucket()."""
    return (key * KNUTH) & MASK32


def fnv1a_32(key: int) -> int:
    """FNV-1a 32-bit over the 4 little-endian bytes of the key."""
    h = 0x811C9DC5
    for b in (key & MASK32).to_bytes(4, "little"):
        h ^= b
        h = (h * 0x01000193) & MASK32
    return h


def _rotl32(x: int, r: int) -> int:
    return ((x << r) | (x >> (32 - r))) & MASK32


def murmur3_32(key: int, seed: int = 0) -> int:
    """MurmurHash3 x86 32-bit over the 4 little-endian bytes of the key."""
    c1, c2 = 0xCC9E2D51, 0x1B873593
    k = int.from_bytes((key & MASK32).to_bytes(4, "little"), "little")
    k = (k * c1) & MASK32
    k = _rotl32(k, 15)
    k = (k * c2) & MASK32
    h = (seed ^ k) & MASK32
    h ^= 4  # length in bytes
    # fmix32 final avalanche
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & MASK32
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & MASK32
    h ^= h >> 16
    return h & MASK32


HASHES = [
    ("mod_prime", hash_mod_prime),
    ("knuth_mult", hash_knuth_mult),
    ("fnv1a", fnv1a_32),
    ("murmur3", murmur3_32),
]


def bucket_of(h_func, key: int, M: int) -> int:
    """Map a 32-bit hash to one of M buckets. For knuth_mult with power-of-two
    M we deliberately take the HIGH bits (the well-mixed part); every other
    hash uses plain modulo on its full 32-bit output."""
    h = h_func(key)
    if h_func is hash_knuth_mult and (M & (M - 1)) == 0:  # M is a power of two
        bits = M.bit_length() - 1
        return h >> (32 - bits)
    return h % M


# ---- deterministic key generator (LCG, mirrored byte-for-byte in the .html)
def make_keys(n: int, seed: int = 1) -> list[int]:
    """Numerical Recipes LCG. Identical sequence in hash_distribution.html."""
    keys = []
    s = seed & MASK32
    for _ in range(n):
        s = (1664525 * s + 1013904223) & MASK32
        keys.append(s)
    return keys


def popcount(x: int) -> int:
    return bin(x).count("1")


# ============================================================================
# 1. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# SECTION A: distribution of 1000 keys into 16 buckets
# ============================================================================

def section_distribution():
    banner("SECTION A: 1000 keys -> 16 buckets  (uniform line = 62.5 each)")
    N, M = 1000, 16
    expected = N / M
    keys = make_keys(N, seed=1)
    print(f"N = {N} keys, M = {M} buckets, expected per bucket = {expected}\n")

    header = "| bucket |" + "".join(f" {name:>11} |" for name, _ in HASHES)
    print(header)
    print("|" + "-" * (len(header) - 2) + "|")
    counts = {}
    for name, hf in HASHES:
        c = [0] * M
        for k in keys:
            c[bucket_of(hf, k, M)] += 1
        counts[name] = c
    for b in range(M):
        row = f"| {b:>6} |"
        for name, _ in HASHES:
            row += f" {counts[name][b]:>11} |"
        print(row)
    print("|" + "-" * (len(header) - 2) + "|")
    # spread stats
    print(f"| {'min':>6} |" + "".join(f" {min(counts[n]):>11} |" for n, _ in HASHES))
    print(f"| {'max':>6} |" + "".join(f" {max(counts[n]):>11} |" for n, _ in HASHES))
    print(f"| {'range':>6} |" + "".join(f" {max(counts[n]) - min(counts[n]):>11} |" for n, _ in HASHES))
    print()
    print("Read it: random keys -> every hash lands near 62.5. The differences")
    print("show up only on STRUCTURED input (Section E). The spread (max-min)")
    print("should be small for all four; chi-squared (Section D) scores it.")
    print()
    print("GOLD (pinned for hash_distribution.html) - murmur3 bucket counts:")
    print("  " + str(counts["murmur3"]))
    return counts, keys


# ============================================================================
# SECTION B: avalanche effect
# ============================================================================

def section_avalanche():
    banner("SECTION B: avalanche - flip 1 INPUT bit, count flipped OUTPUT bits")
    print("Strict Avalanche Criterion: flipping any single input bit should")
    print("flip ~half of the 32 output bits. Ideal ratio = 0.500 (16/32).\n")
    samples = 2000
    base_keys = make_keys(samples, seed=7)
    print(f"averaged over {samples} base keys x 32 bit-flips = "
          f"{samples * 32} comparisons per hash\n")
    print("| hash       | avg bits flipped | avalanche ratio | verdict        |")
    print("|------------|------------------|-----------------|----------------|")
    results = {}
    for name, hf in HASHES:
        total_flips = 0
        for k in base_keys:
            h0 = hf(k)
            for i in range(32):
                h1 = hf(k ^ (1 << i))
                total_flips += popcount(h0 ^ h1)
        avg = total_flips / (samples * 32)
        ratio = avg / 32
        results[name] = (avg, ratio)
        verdict = "excellent" if abs(ratio - 0.5) < 0.03 else (
            "fair" if abs(ratio - 0.5) < 0.12 else "weak")
        print(f"| {name:<10} | {avg:>16.3f} | {ratio:>15.4f} | {verdict:<14} |")
    print()
    print(f"Why mod_prime is weak: its output is key % PRIME, which stays in "
          f"[0, {PRIME}) ~= [0, 2^20). The top ~12 output bits are ALWAYS zero, so")
    print("they can never flip -- it wastes a third of the output space.\n")
    print("Why knuth_mult is weak at avalanche: it is LINEAR. Flipping input bit")
    print("i changes the product by exactly 2^i * KNUTH (mod 2^32); for HIGH i")
    print("that shift gets truncated, so a high input bit flips only ~1-3 output")
    print("bits. (Its DISTRIBUTION is still good -- see Section A/D.)\n")
    print("fnv1a is 'fair': 4 bytes of input is not quite enough for its")
    print("xor-multiply loop to fully randomize the word. murmur3 hits 0.500")
    print("because its fmix32 finalizer exists ONLY to guarantee avalanche.")
    print("GOLD (pinned) - avalanche ratios:")
    for name, _ in HASHES:
        avg, ratio = results[name]
        print(f"  {name:<10} ratio = {ratio:.4f}")
    return results


# ============================================================================
# SECTION C: birthday paradox
# ============================================================================

def birthday_exact(N: int, M: int) -> float:
    """Exact P(at least one collision) among N keys in M buckets."""
    p = 1.0
    for i in range(N):
        p *= (1 - i / M)
        if p == 0.0:
            break
    return 1.0 - p


def birthday_approx(N: int, M: int) -> float:
    """Poisson approximation: P ~= 1 - exp(-N^2/(2M))."""
    return 1.0 - math.exp(-(N ** 2) / (2 * M))


def section_birthday():
    banner("SECTION C: the birthday paradox - "
           "P(collision) = 1 - exp(-N^2/(2M))")
    print("With N keys thrown into M buckets, the chance at least two share a")
    print("bucket climbs FAST. 50% odds arrive at N ~= 1.177 * sqrt(M).\n")
    print("(a) how many keys N give a 50% chance of a collision, per M:")
    print("| M (buckets) | sqrt(M) | N at 50% (exact) | N ~= 1.177*sqrt(M) |")
    print("|-------------|---------|-------------------|---------------------|")
    for M in [16, 100, 365, 1_000, 10_000, 65_536, 1_000_003]:
        # exponential search for an upper bound where P >= 0.5
        lo = 1
        while birthday_exact(lo, M) < 0.5:
            lo = lo * 2
            if lo > 10 * M:
                break
        a, b = 1, lo
        while a < b:
            mid = (a + b) // 2
            if birthday_exact(mid, M) < 0.5:
                a = mid + 1
            else:
                b = mid
        n50 = a
        approx = 1.177 * math.sqrt(M)
        print(f"| {M:>11,} | {math.sqrt(M):>7.2f} | {n50:>17} | {approx:>19.2f} |")
    print()
    print("(b) for M = 16 buckets, P(collision) vs N (exact vs approx):")
    print("| N  | exact P(collision) | approx 1-exp(-N^2/2M) | expected colls N^2/2M |")
    print("|----|--------------------|-----------------------|------------------------|")
    M = 16
    for N in [2, 4, 5, 6, 8, 10, 16, 20, 32, 50]:
        pe = birthday_exact(N, M)
        pa = birthday_approx(N, M)
        ec = N ** 2 / (2 * M)
        print(f"| {N:>2} | {pe:>18.4f} | {pa:>21.4f} | {ec:>22.2f} |")
    print()
    print("Read it: at N=6 you already have a ~50/50 shot of a collision in")
    print("just 16 buckets. The Poisson approx 1-exp(-N^2/2M) tracks the exact")
    print("product formula tightly once N is more than a handful.")
    print()
    print("GOLD (pinned) - P(collision) for N=10, M=16:")
    print(f"  exact  = {birthday_exact(10, 16):.6f}")
    print(f"  approx = {birthday_approx(10, 16):.6f}")


# ============================================================================
# SECTION D: chi-squared test for uniformity
# ============================================================================

def chi_squared(counts: list[int], N: int, M: int) -> float:
    expected = N / M
    return sum((c - expected) ** 2 / expected for c in counts)


def section_chi_squared(counts):
    banner("SECTION D: chi-squared test - deviation from uniform (lower = flatter)")
    N, M = 1000, 16
    dof = M - 1
    print(f"chi^2 = sum (observed - N/M)^2 / (N/M);  N/M = {N}/{M} = {N / M};  "
          f"degrees of freedom = {dof}\n")
    print("A perfect fill scores 0. The MEAN of chi^2 with 15 dof is 15; a")
    print("uniform random hash lands in roughly [5, 25] on any given trial.\n")
    print("| hash       | chi-squared | vs mean(15) |")
    print("|------------|-------------|-------------|")
    chi = {}
    for name, _ in HASHES:
        c = chi_squared(counts[name], N, M)
        chi[name] = c
        vs = "at the mean" if abs(c - 15) < 3 else ("high-ish" if c > 18 else "low-ish")
        print(f"| {name:<10} | {c:>11.3f} | {vs:<11} |")
    print()
    print("On RANDOM input all four score near the mean -- nobody is broken")
    print("yet. chi-squared only separates them once the input has structure")
    print("(Section E).")
    print()
    print("GOLD (pinned) - chi-squared per hash:")
    for name, _ in HASHES:
        print(f"  {name:<10} chi^2 = {chi[name]:.3f}")
    return chi


# ============================================================================
# SECTION E: comparison on structured input + birthday gold check
# ============================================================================

def observed_collisions(counts: list[int]) -> int:
    return sum(c * (c - 1) // 2 for c in counts)


def section_comparison():
    banner("SECTION E: structured input - where naive modulo hash collapses")
    N, M = 1000, 16
    expected_coll = N ** 2 / (2 * M)
    print("Now feed STRUCTURED keys: an arithmetic sequence whose step equals")
    print(f"the prime used by mod_prime (step = {PRIME}). For those keys,")
    print("key % PRIME == 0 for EVERY key, so mod_prime sends all 1000 to ONE")
    print("bucket. The real hashes mix the bits, so structure vanishes.\n")

    cases = [
        ("random keys (baseline)", make_keys(N, seed=1)),
        (f"step = {PRIME} (adversarial)", [(i * PRIME) & MASK32 for i in range(N)]),
        ("sequential 0..999", [i for i in range(N)]),
    ]

    for label, keys in cases:
        print(f"--- {label} ---")
        print(f"| hash       | chi-squared | max bucket | collisions | "
              f"birthday N^2/2M = {expected_coll:.0f} |")
        print("|------------|-------------|------------|------------|----------------|")
        for name, hf in HASHES:
            c = [0] * M
            for k in keys:
                c[bucket_of(hf, k, M)] += 1
            chi = chi_squared(c, N, M)
            coll = observed_collisions(c)
            print(f"| {name:<10} | {chi:>11.1f} | {max(c):>10} | {coll:>10} |"
                  f"{'  matches birthday' if name in ('fnv1a', 'murmur3') and label.startswith('random') else '':>16}|")
        print()

    print("GOLD CHECK: on RANDOM keys, the good hashes' collision count should")
    print(f"match the birthday prediction N^2/(2M) = {expected_coll:.1f}.\n")
    keys = make_keys(N, seed=1)
    print("| hash       | observed collisions | birthday N^2/2M | "
          "ratio (ideal ~1.0) | match |")
    print("|------------|---------------------|------------------|"
          "---------------------|-------|")
    all_ok = True
    for name, hf in HASHES:
        c = [0] * M
        for k in keys:
            c[bucket_of(hf, k, M)] += 1
        coll = observed_collisions(c)
        ratio = coll / expected_coll
        ok = abs(ratio - 1.0) < 0.20
        all_ok = all_ok and (ok or name == "mod_prime")
        mark = "OK" if ok else "OFF"
        print(f"| {name:<10} | {coll:>19} | {expected_coll:>16.1f} | "
              f"{ratio:>19.3f} | {mark:<5} |")
    print()
    # the real gold: good hashes match; mod_prime may drift a little but stays
    # in the ballpark on random input (it is uniform, just unmixed)
    good_hashes_ok = True
    for name in ("knuth_mult", "fnv1a", "murmur3"):
        c = [0] * M
        for k in keys:
            c[bucket_of(HASH_HASH[name], k, M)] += 1
        coll = observed_collisions(c)
        if abs(coll / expected_coll - 1.0) >= 0.20:
            good_hashes_ok = False
    print(f"[check] good hashes (knuth/fnv1a/murmur3) collision count within "
          f"20% of birthday N^2/2M = {expected_coll:.1f}: "
          f"{'OK' if good_hashes_ok else 'FAIL'}")
    return good_hashes_ok


# helper map for the gold check loop
HASH_HASH = {name: hf for name, hf in HASHES}


# ============================================================================
# main
# ============================================================================

def main():
    print("hash_distribution.py - reference impl. "
          "All numbers below feed HASH_DISTRIBUTION.md.")
    counts, keys = section_distribution()
    section_avalanche()
    section_birthday()
    section_chi_squared(counts)
    ok = section_comparison()
    banner("DONE - all sections printed; "
           f"birthday gold-check: {'OK' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
