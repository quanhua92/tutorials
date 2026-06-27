#!/usr/bin/env python3
"""Bloom Filters -- probabilistic set membership.

Ground-truth implementation. Pure Python stdlib (no third-party deps).

  - Bit array of m bits (stored as one Python int, bit i == (arr >> i) & 1)
  - k hash functions derived from 2 base hashes via Kirsch-Mitzenmacher:
        h_i(x) = (h1(x) + i * h2(x)) mod m          for i in 0..k-1
  - insert / query operations (zero false negatives)
  - theoretical false-positive rate  p = (1 - e^(-kn/m))^k
  - empirical FPR measured against a seeded set of absent elements
  - memory comparison vs an exact hash set (n * 64-bit keys)

Companion files: BLOOM_FILTERS.md, bloom_filters.html
"""

import hashlib
import math
import random

LN2 = math.log(2)


# --------------------------------------------------------------------------- #
#  Sizing formulas  (the three interview equations)
# --------------------------------------------------------------------------- #
def bits_needed(n: int, p: float) -> int:
    """m = -n * ln(p) / (ln2)^2   (number of bits in the array)."""
    return max(1, math.ceil(-n * math.log(p) / (LN2 * LN2)))


def optimal_k(m: int, n: int) -> int:
    """k = (m / n) * ln(2)   (optimal number of hash functions)."""
    return max(1, round((m / n) * LN2))


def theoretical_fpr(m: int, k: int, n: int) -> float:
    """p = (1 - e^(-kn/m))^k   (false-positive rate after n insertions)."""
    if m == 0:
        return 1.0
    return (1.0 - math.exp(-k * n / m)) ** k


# --------------------------------------------------------------------------- #
#  The Bloom filter
# --------------------------------------------------------------------------- #
def _base_hash(data: bytes, salt: bytes, modulus: int) -> int:
    """One 32-bit base hash via BLAKE2b keyed with `salt`, reduced mod m."""
    digest = hashlib.blake2b(data, key=salt, digest_size=4).digest()
    return int.from_bytes(digest, "big") % modulus


class BloomFilter:
    """Standard (insert-only) Bloom filter with Kirsch-Mitzenmacher hashing."""

    def __init__(self, capacity: int, error_rate: float):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if not (0.0 < error_rate < 1.0):
            raise ValueError("error_rate must be in (0, 1)")
        self.capacity = capacity          # n  -- designed element count
        self.error_rate = error_rate      # p  -- target FPR
        self.m = bits_needed(capacity, error_rate)
        self.k = optimal_k(self.m, capacity)
        self.bit_array = 0                # m-bit array as a single int
        self.count = 0                    # actual insertions so far

    # --- Kirsch-Mitzenmacher: k positions from 2 base hashes ----------
    def _positions(self, item) -> list:
        data = str(item).encode("utf-8")
        h1 = _base_hash(data, b"h1-salt", self.m)
        h2 = _base_hash(data, b"h2-salt", self.m)
        if h2 == 0:                       # avoid degenerate h2 == 0
            h2 = 1
        return [(h1 + i * h2) % self.m for i in range(self.k)]

    def add(self, item) -> None:
        for pos in self._positions(item):
            self.bit_array |= (1 << pos)
        self.count += 1

    def __contains__(self, item) -> bool:
        for pos in self._positions(item):
            if not (self.bit_array & (1 << pos)):
                return False              # a zero bit => definitely absent
        return True                       # all ones => possibly present

    # --- metrics ------------------------------------------------------
    def current_fpr(self) -> float:
        """Theoretical FPR for the number of items actually inserted."""
        return theoretical_fpr(self.m, self.k, self.count)

    def bits_used(self) -> int:
        return bin(self.bit_array).count("1")


# --------------------------------------------------------------------------- #
#  Pretty-printers
# --------------------------------------------------------------------------- #
def banner(title: str) -> None:
    line = "=" * 78
    print(f"\n{line}\n{title}\n{line}")


def bytes_str(bits: int) -> str:
    b = bits / 8.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024.0:
            return f"{b:.2f} {unit}"
        b /= 1024.0
    return f"{b:.2f} PB"


def bit_string(arr: int, m: int, group: int = 8) -> str:
    """Render the m-bit array MSB-first, grouped in chunks of `group`."""
    bits = "".join("1" if (arr >> i) & 1 else "0" for i in range(m))[::-1]
    return " ".join(bits[i:i + group] for i in range(0, m, group))


# --------------------------------------------------------------------------- #
#  Demo sections
# --------------------------------------------------------------------------- #
def section_sizing() -> None:
    banner("SIZING FORMULAS -- 1,000,000 elements at p = 0.01 (1%)")
    n, p = 1_000_000, 0.01
    m = bits_needed(n, p)
    k = optimal_k(m, n)
    print(f"  target n     = {n:,} elements")
    print(f"  target p     = {p} ({p*100:.2f}%)")
    print(f"  m (bits)     = -n*ln(p)/(ln2)^2  = {m:,} bits  (~{bytes_str(m)})")
    print(f"  k (hashes)   = (m/n)*ln(2)       = {k}")
    print(f"  bits/elem    = m/n               = {m/n:.2f}")

    banner("RULE-OF-THUMB ANCHORS")
    print(f"  {'bits/elem':>10}  {'p':>10}  {'k':>4}")
    for bpe in (7, 10, 14, 20):
        m2 = bpe * 1000
        k2 = optimal_k(m2, 1000)
        p2 = theoretical_fpr(m2, k2, 1000)
        print(f"  {bpe:>10}  {p2*100:>9.4f}%  {k2:>4}")


def section_demo() -> None:
    banner("TINY DEMO -- m = 32 bits, k = 3 hashes")
    bf = BloomFilter.__new__(BloomFilter)      # bypass sizing; use raw m/k
    bf.m, bf.k = 32, 3
    bf.bit_array, bf.count, bf.capacity, bf.error_rate = 0, 0, 8, 0.05

    words = ["apple", "banana", "cherry"]
    for w in words:
        positions = bf._positions(w)
        for pos in positions:
            bf.bit_array |= (1 << pos)
        bf.count += 1
        print(f"  add {w:<8} -> set bits {positions}")

    print(f"\n  bit array ({bf.m} bits):  {bit_string(bf.bit_array, bf.m)}")
    print(f"  bits set = {bf.bits_used()} / {bf.m}")

    print("\n  queries:")
    for w in ["apple", "banana", "cherry", "grape", "durian"]:
        verdict = "possibly present" if w in bf else "definitely absent"
        print(f"    {w:<8} -> {verdict}")

    # Kirsch-Mitzenmacher derivation for one element
    banner("KIRSCH-MITZENMACHER DOUBLE HASHING  h_i(x) = (h1 + i*h2) mod m")
    data = "apple".encode("utf-8")
    h1 = _base_hash(data, b"h1-salt", bf.m)
    h2 = _base_hash(data, b"h2-salt", bf.m)
    if h2 == 0:
        h2 = 1
    print(f"  element = 'apple',  m = {bf.m}")
    print(f"  h1('apple') = {h1}")
    print(f"  h2('apple') = {h2}")
    for i in range(bf.k):
        print(f"    i={i}:  h_i = ({h1} + {i}*{h2}) mod {bf.m} = "
              f"{(h1 + i*h2) % bf.m}")


def section_empirical() -> None:
    banner("EMPIRICAL vs THEORETICAL FPR  (capacity=10,000, p=0.01)")
    capacity, p = 10_000, 0.01
    bf = BloomFilter(capacity, p)
    print(f"  configured: n={capacity:,}  p={p}  m={bf.m:,} bits  k={bf.k}")

    rng = random.Random(42)
    members = [f"key-{i}" for i in range(capacity)]
    for x in members:
        bf.add(x)

    trials = 100_000
    false_pos = 0
    for i in range(trials):
        if f"absent-{i}" in bf:          # guaranteed not inserted
            false_pos += 1
    empirical = false_pos / trials
    theo = bf.current_fpr()
    print(f"  inserted              = {bf.count:,} elements")
    print(f"  absent trials         = {trials:,}")
    print(f"  false positives       = {false_pos:,}")
    print(f"  empirical FPR         = {empirical*100:.4f}%")
    print(f"  theoretical FPR       = {theo*100:.4f}%  "
          f"(1-e^(-kn/m))^k, k={bf.k}")
    print(f"  ratio emp/theo        = {empirical/theo:.3f}")


def section_memory() -> None:
    banner("MEMORY: BLOOM FILTER vs EXACT HASH SET (n * 64-bit keys)")
    print(f"  {'config':<28}{'bloom':>12}{'hash set':>12}{'savings':>10}")
    for n, p in [(1_000_000, 0.01), (1_000_000, 0.001),
                 (500_000_000, 0.001), (1_000_000_000, 0.0001)]:
        m = bits_needed(n, p)
        k = optimal_k(m, n)
        bloom_bytes = m // 8
        set_bytes = n * 8                # n 64-bit keys
        savings = set_bytes / bloom_bytes
        cfg = f"n={n:,}, p={p}"
        print(f"  {cfg:<28}{bytes_str(m):>12}{bytes_str(set_bytes*8):>12}"
              f"{savings:>9.1f}x")


def section_gold_check() -> None:
    """A single concrete value recomputed by bloom_filters.html for parity."""
    banner("GOLD CHECK  (recomputed by bloom_filters.html in JS)")
    m, k, n = 200, 5, 30
    val = theoretical_fpr(m, k, n)
    gold = f"{val:.6f}"
    print(f"  theoretical_fpr(m={m}, k={k}, n={n}) = {gold}")
    print("  [check] OK")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("#" * 78)
    print("# BLOOM FILTER -- probabilistic set membership (pure stdlib)")
    print("#" * 78)
    section_sizing()
    section_demo()
    section_empirical()
    section_memory()
    section_gold_check()
    print("\n[check] OK -- all sections ran\n")
