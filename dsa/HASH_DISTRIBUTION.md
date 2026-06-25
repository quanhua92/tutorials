# Hash Function Quality — Distribution, Avalanche, Collisions

> A *concept bundle*. This guide is built entirely from `hash_distribution.py` — every number
> lives under a `> From hash_distribution.py Section X:` callout and was printed by that file, not
> hand-computed. The interactive companion `hash_distribution.html` recomputes the same formulas in
> your browser and carries `[check: OK]` badges that audit against this `.py`.
>
> 🔗 Source files: [`hash_distribution.py`](./hash_distribution.py) · [`hash_distribution.html`](./hash_distribution.html) · captured [`hash_distribution_output.txt`](./hash_distribution_output.txt)

---

## 0. The one-sentence story

A hash table is **M buckets**; a hash function `H` decides which bucket each key lands in via
`bucket = H(key) mod M`. A *good* `H` does three things at once — **spreads evenly** (every bucket
gets `~N/M` keys), **scrambles bits** (flipping one input bit flips ~half the output bits — the
*avalanche* effect), and **collides at the predicted rate** (the *birthday paradox*). This bundle
measures all three and compares four hash functions, from naive to excellent.

```mermaid
flowchart LR
    K["key (32-bit)"] --> H["hash function H"]
    H --> HV["32-bit hash value"]
    HV --> MOD["mod M"]
    MOD --> B["bucket 0..M-1"]
    style H fill:#1f6f3b,color:#fff
    style B fill:#3a2f12,color:#ffd966
```

The four contestants:

| hash | idea | mixing | typical use |
|---|---|---|---|
| **`mod_prime`** | `key % prime` | **none** — strawman | what NOT to do |
| **`knuth_mult`** | `key * (2³²/φ) mod 2³²` | linear (good high bits) | integer keys, read HIGH bits |
| **`fnv1a`** | per-byte `xor` then `*prime` | moderate | checksums, simple tables |
| **`murmur3`** | `multiply + rotate + final mix` | **excellent** | the industry default (Redis, Rust `HashMap`, …) |

All four return an unsigned 32-bit integer; the bucket is then `H(key) mod M` (with `knuth_mult`
taking the **high** bits when `M` is a power of two — see §1).

---

## 1. The four hash functions

> From `hash_distribution.py` — the reference implementations (pure Python stdlib):

```python
PRIME = 1000003                 # a large prime
KNUTH = 2654435761              # floor(2^32 / phi), the golden ratio

def hash_mod_prime(key):        # NO mixing: just reduce mod a prime
    return (key % PRIME) & MASK32

def hash_knuth_mult(key):       # key * golden-ratio, full 32-bit word
    return (key * KNUTH) & MASK32

def fnv1a_32(key):              # xor each byte, then multiply by the FNV prime
    h = 0x811C9DC5
    for b in (key & MASK32).to_bytes(4, "little"):
        h ^= b
        h = (h * 0x01000193) & MASK32
    return h

def murmur3_32(key, seed=0):    # scramble block, then fmix32 finalizer
    ...                          # multiply-rotate-multiply, then a 3-step final avalanche
```

**Why `knuth_mult` reads the HIGH bits.** The product `key * KNUTH` is well-mixed in its *high*
bits but its *low* bits depend only on the low bits of `key`. So for a power-of-two bucket count
`M = 2ᵏ`, we take `H(key) >> (32 - k)` (the good bits) rather than `H(key) mod M` (the weak bits).
This is exactly what `bucket_of()` does:

```python
def bucket_of(h_func, key, M):
    h = h_func(key)
    if h_func is hash_knuth_mult and (M & (M - 1)) == 0:   # M is a power of two
        bits = M.bit_length() - 1
        return h >> (32 - bits)                            # take HIGH bits
    return h % M
```

> **Determinism.** All keys come from a fixed-seed LCG (`s = 1664525·s + 1013904223 mod 2³²`),
> implemented **byte-for-byte identically** in `hash_distribution.py` and `hash_distribution.html`,
> so the two sides always see the same inputs.

---

## 2. Distribution — 1000 keys into 16 buckets (Section A)

The first question: do 1000 random keys fill all 16 buckets near the **uniform line of 62.5**?

> From `hash_distribution.py` Section A:

```
N = 1000 keys, M = 16 buckets, expected per bucket = 62.5

| bucket |   mod_prime |  knuth_mult |       fnv1a |     murmur3 |
|----------------------------------------------------------------|
|      0 |          60 |          51 |          62 |          58 |
|      1 |          55 |          56 |          56 |          61 |
|      2 |          66 |          63 |          57 |          53 |
|      3 |          60 |          74 |          58 |          65 |
|      4 |          54 |          58 |          60 |          52 |
|      5 |          76 |          63 |          62 |          69 |
|      6 |          61 |          61 |          63 |          64 |
|      7 |          74 |          53 |          60 |          66 |
|      8 |          54 |          71 |          59 |          71 |
|      9 |          60 |          68 |          59 |          59 |
|     10 |          64 |          64 |          61 |          72 |
|     11 |          68 |          79 |          72 |          52 |
|     12 |          67 |          66 |          72 |          59 |
|     13 |          66 |          48 |          70 |          75 |
|     14 |          60 |          59 |          70 |          64 |
|     15 |          55 |          66 |          59 |          60 |
|----------------------------------------------------------------|
|    min |          54 |          48 |          56 |          52 |
|    max |          76 |          79 |          72 |          75 |
|  range |          22 |          31 |          16 |          23 |
```

**Read it:** on *random* keys every hash lands near 62.5 — the differences only show up on
**structured** input (§5). The spread (`max − min`) is small for all four; chi-squared (§4) scores
the flatness numerically. 🔗 Try this live with the key-source toggle in
[`hash_distribution.html`](./hash_distribution.html) Panel ①.

---

## 3. The avalanche effect (Section B)

The **Strict Avalanche Criterion (SAC)**: flipping *any single input bit* should flip ~half of the
32 output bits. Ideal ratio = **0.500** (16/32). We average over 2000 base keys × 32 bit-flips.

> From `hash_distribution.py` Section B:

```
| hash       | avg bits flipped | avalanche ratio | verdict        |
|------------|------------------|-----------------|----------------|
| mod_prime  |            5.212 |          0.1629 | weak           |
| knuth_mult |            8.653 |          0.2704 | weak           |
| fnv1a      |           12.770 |          0.3991 | fair           |
| murmur3    |           16.000 |          0.5000 | excellent      |
```

**Why each scores what it scores:**

- **`mod_prime` (0.163)** — its output is `key % PRIME`, which stays in `[0, 1 000 003) ≈ [0, 2²⁰)`.
  The **top ~12 output bits are always zero**, so they can never flip. It wastes a third of the
  output space.
- **`knuth_mult` (0.270)** — it is **linear**. Flipping input bit `i` changes the product by exactly
  `2ⁱ · KNUTH (mod 2³²)`; for **high `i`** that shift gets truncated, so a high input bit flips only
  ~1–3 output bits. *(Its **distribution** is still good — see §2/§4. "Good spread" ≠ "good avalanche".)*
- **`fnv1a` (0.399)** — 4 bytes of input is not quite enough for its `xor`-`multiply` loop to fully
  randomize the word. It improves with longer inputs.
- **`murmur3` (0.500)** — hits the ideal because its `fmix32` finalizer (`xor-shift-multiply`,
  repeated 3×) **exists solely to guarantee avalanche**. This is the whole reason that final step is
  there.

> 🔗 `hash_distribution.html` Panel ② lets you click any input bit and watch the output bits flip.

---

## 4. The birthday paradox (Section C)

With **N** keys thrown into **M** buckets, the chance that *at least two* share a bucket climbs fast:

```
P(≥1 collision) ≈ 1 − e^(−N²/2M)          (Poisson approximation)
exact          = 1 − Π_{i=0}^{N−1} (1 − i/M)
expected colliding pairs ≈ N²/2M
50% threshold at N ≈ 1.177·√M
```

> From `hash_distribution.py` Section C(a) — how many keys give a 50% chance, per M:

```
| M (buckets) | sqrt(M) | N at 50% (exact) | N ~= 1.177*sqrt(M) |
|-------------|---------|-------------------|---------------------|
|          16 |    4.00 |                 5 |                4.71 |
|         100 |   10.00 |                13 |               11.77 |
|         365 |   19.10 |                23 |               22.49 |
|       1,000 |   31.62 |                38 |               37.22 |
|      10,000 |  100.00 |               119 |              117.70 |
|      65,536 |  256.00 |               302 |              301.31 |
|   1,000,003 | 1000.00 |              1178 |             1177.00 |
```

> From `hash_distribution.py` Section C(b) — for M = 16 buckets, P vs N:

```
| N  | exact P(collision) | approx 1-exp(-N^2/2M) | expected colls N^2/2M |
|----|--------------------|-----------------------|------------------------|
|  2 |             0.0625 |                0.1175 |                   0.12 |
|  4 |             0.3335 |                0.3935 |                   0.50 |
|  5 |             0.5001 |                0.5422 |                   0.78 |
|  6 |             0.6563 |                0.6753 |                   1.12 |
|  8 |             0.8792 |                0.8647 |                   2.00 |
| 10 |             0.9736 |                0.9561 |                   3.12 |
| 16 |             1.0000 |                0.9997 |                   8.00 |
| 20 |             1.0000 |                1.0000 |                  12.50 |
| 32 |             1.0000 |                1.0000 |                  32.00 |
| 50 |             1.0000 |                1.0000 |                  78.12 |
```

**Read it:** at **N = 6** you already have a **~50/50** shot of a collision in just 16 buckets.
The classic "23 people → 50% shared birthday" is the `M = 365` row. The Poisson approximation
`1 − e^(−N²/2M)` tracks the exact product formula tightly once N is more than a handful — which is
why it is the formula used everywhere in practice. 🔗 Play with the N/M sliders in
[`hash_distribution.html`](./hash_distribution.html) Panel ③.

---

## 5. Chi-squared — scoring flatness (Section D)

**χ² = Σ (observed − N/M)² / (N/M)**, with `N/M = 62.5`. A perfect fill scores 0; the *mean* of χ²
with 15 degrees of freedom is **15**, and a uniform-random hash lands roughly in **[5, 25]** on any
single trial.

> From `hash_distribution.py` Section D:

```
| hash       | chi-squared | vs mean(15) |
|------------|-------------|-------------|
| mod_prime  |      10.816 | low-ish     |
| knuth_mult |      16.704 | at the mean |
| fnv1a      |       7.008 | low-ish     |
| murmur3    |      11.968 | low-ish     |
```

On *random* input all four score near the mean — nobody is broken yet. Chi-squared only separates
the good from the bad once the input has **structure** (§6).

---

## 6. Structured input — where naive modulo collapses (Section E) ✅ gold check

This is the crux. Feed **structured keys**: an arithmetic sequence whose step equals the prime used
by `mod_prime` (`step = 1 000 003`). For those keys `key % PRIME == 0` **for every key**, so
`mod_prime` sends all 1000 to **one** bucket. The real hashes mix the bits, so the structure
vanishes.

> From `hash_distribution.py` Section E — three key sources, M = 16, birthday `N²/2M = 31 250`:

```
--- random keys (baseline) ---
| hash       | chi-squared | max bucket | collisions |
| mod_prime  |        10.8 |         76 |      31088 |
| knuth_mult |        16.7 |         79 |      31272 |
| fnv1a      |         7.0 |         72 |      30969 |
| murmur3    |        12.0 |         75 |      31124 |

--- step = 1000003 (adversarial) ---
| hash       | chi-squared | max bucket | collisions |
| mod_prime  |     15000.0 |       1000 |     499500 |   <-- ALL 1000 in ONE bucket
| knuth_mult |         0.7 |         65 |      30773 |
| fnv1a      |         4.8 |         69 |      30899 |
| murmur3    |        17.2 |         74 |      31286 |

--- sequential 0..999 ---
| hash       | chi-squared | max bucket | collisions |
| mod_prime  |         0.1 |         63 |      30752 |
| knuth_mult |         0.2 |         63 |      30755 |
| fnv1a      |         0.1 |         63 |      30752 |
| murmur3    |        26.8 |         82 |      31588 |
```

**The lesson:** `mod_prime` has **no mixing** — whatever structure the input has leaks straight into
the buckets. Sequential input happens to suit it (it cycles evenly), but the moment the input aligns
with the modulus it **catastrophically collapses** (χ² = 15 000, all 1000 keys in one bucket,
499 500 colliding pairs). A hash with real mixing is **robust to any input pattern**.

### ✅ Gold check — collisions match the birthday prediction

On **random** keys, a good hash's collision count should match the birthday formula
`N²/(2M) = 31 250`. The observed colliding pairs (Σ `C(count_b, 2)`):

> From `hash_distribution.py` Section E (gold check):

```
| hash       | observed collisions | birthday N^2/2M | ratio (ideal ~1.0) | match |
|------------|---------------------|------------------|---------------------|-------|
| mod_prime  |               31088 |          31250.0 |               0.995 | OK    |
| knuth_mult |               31272 |          31250.0 |               1.001 | OK    |
| fnv1a      |               30969 |          31250.0 |               0.991 | OK    |
| murmur3    |               31124 |          31250.0 |               0.996 | OK    |

[check] good hashes (knuth/fnv1a/murmur3) collision count within 20% of birthday N^2/2M = 31250.0: OK
```

All four land within **1%** of the birthday prediction on random input — confirming that even the
weak hashes *distribute* correctly; their weakness is **avalanche** and **robustness to structure**,
not raw collision rate on benign data. The birthday formula is a reliable predictor for any
hash that actually fills its buckets.

---

## 7. Summary — which property matters when

| hash | distribution (χ²) | avalanche | robust to structure | verdict |
|---|---|---|---|---|
| `mod_prime`  | ok on random | **0.163 weak** | **collapses** | never use as a hash |
| `knuth_mult` | good | 0.270 weak | robust | fine for integer keys (read high bits) |
| `fnv1a`      | good | 0.399 fair | robust | good general-purpose, short inputs |
| `murmur3`    | good | **0.500 ideal** | robust | the safe default |

**Three takeaways:**

1. **Distribution alone is not enough.** `mod_prime` spreads evenly on random data yet collapses on
   structured input. Always ask "what does my hash do on *adversarial* input?"
2. **Avalanche is what kills structure.** The finalizer (`fmix32`) is the single most important
   part of `murmur3` — without it, multiplying and rotating alone don't reach SAC.
3. **The birthday paradox sets your load factor.** With `M` buckets you expect `~N²/(2M)`
   colliding pairs; to keep collisions rare, size `M` so that `N²/(2M)` stays small — i.e. resize
   the table as `N` grows (this is exactly why hash tables **rehash** at a load-factor threshold).

---

### References

- Knuth, *The Art of Computer Programming Vol. 3*, §6.4 — multiplicative hashing, the golden ratio.
- Appleby, *MurmurHash3* (2008) — the `multiply-rotate-finalize` design benchmarked here.
- Fowler–Noll–Vo, *FNV-1a* — the `xor`-`multiply` non-cryptographic hash.
- The birthday problem: `P(≥1 collision) = 1 − Π(1 − i/M)`; Poisson form `1 − e^(−N²/2M)`.

> 🔗 Next: open [`hash_distribution.html`](./hash_distribution.html) to flip bits and drag the
> birthday sliders yourself. &nbsp;|&nbsp; Back to [`../index.html`](../index.html).
