# RADIX_SORT — Radix Sort in Action

> The sort that ignores the comparison-sort lower bound by sorting one **digit** at a time.

This guide walks through [`radix_sort.py`](./radix_sort.py). Every table, number, and trace below is **printed by that file** — re-run `uv run python radix_sort.py` to regenerate [`radix_sort_output.txt`](./radix_sort_output.txt). Nothing here is hand-computed. For the animated step view, open [`radix_sort.html`](./radix_sort.html).

---

## 0. The one-paragraph mental model

Sort a deck of number-cards one **column** at a time. Make 10 piles (buckets `0..9`), deal every card onto the pile matching that digit, scoop the piles back up in order `0→9`. Do that for the **units** digit, then **tens**, then **hundreds**… and after the last pass the deck is sorted. That is **LSD radix sort**. It never asks "is 45 < 75?" — it only asks "what is this digit?" — so the comparison-sort lower bound of Ω(n log n) **does not apply**.

## 1. The lineage

| idea | source |
|------|--------|
| Radix sort | Herman 1961 (computer impl); concept = mechanical card sorters, Hollerith 1890 census |
| Counting sort (the subroutine) | CLRS §8.2 |
| LSD radix sort (this guide) | CLRS §8.3 |
| MSD radix sort | CLRS §8.3 (most-significant first, recursive — not covered here) |

## 2. Key formulas (asserted in code)

```
digit(x, place) = (x // place) % radix      # the digit at weight `place`
one counting pass  = O(n + radix), STABLE
radix total        = O(d · (n + radix))  =  O(d·n)  when radix ≪ n
d                  = floor(log_radix(max)) + 1     # number of passes
```

`radix` = the base = number of buckets (10 here). `d` = digit-count of the max element. **Stability is mandatory**: each per-digit pass must preserve the order the lower-digit passes built.

---

## 3. Section A — the subroutine: counting sort, and why it MUST be stable

Radix sort is just **counting sort run `d` times**, once per digit. Counting sort on one digit (`radix_sort.py:counting_sort_by_digit`):

1. **COUNT** how many cards land in each bucket.
2. **PREFIX-SUM** the counts → each bucket now says "my cards go to output slots `[start .. start+count)`".
3. **DEAL** the input **right-to-left**, placing each card at the (decremented) bucket slot. Right-to-left is *what makes it stable*: the last-seen equal card lands in the last slot of its run.

**Why stability is the whole game.** After the units pass, two cards with the same unit digit keep their input order. The tens pass then only reorders cards whose *tens* digit differs, carrying the units order upward untouched. If counting sort were *unstable*, a higher-digit pass could demote a correctly-placed lower digit, and ties would come out in arbitrary order. The `.py` proves stability on a pair of duplicate-unit elements:

```
[check] counting sort stable on duplicate-unit pairs? True
```

## 4. Section B — the digit-pass trace (the classic example)

Input `[170, 45, 75, 90, 802, 24, 2, 66]`, `max = 802` → `d = 3` passes. Watch the buckets fill each pass (from `radix_sort_output.txt`):

**Pass 1 — units digit (place = 1):**

| bucket | elements |
|--------|----------|
| 0 | 170, 90 |
| 2 | 802, 2 |
| 4 | 24 |
| 5 | 45, 75 |
| 6 | 66 |

→ `[170, 90, 802, 2, 24, 45, 75, 66]` (now sorted by units digit).

**Pass 2 — tens digit (place = 10):** buckets `0:[802,2], 2:[24], 4:[45], 6:[66], 7:[170,75], 9:[90]`
→ `[802, 2, 24, 45, 66, 170, 75, 90]` (sorted by last two digits).

**Pass 3 — hundreds digit (place = 100):** buckets `0:[2,24,45,66,75,90], 1:[170], 8:[802]`
→ `[2, 24, 45, 66, 75, 90, 170, 802]` ✓ fully sorted.

```
[check] matches Python sorted()? True
```

> **Read the passes bottom-up.** The least-significant pass does the *least* deciding; the most-significant pass acts *last* and "wins" ties — exactly like the last key in a tuple sort deciding final order when earlier keys tie.

## 5. Section C — complexity: beating the n·log n barrier

Per pass: `O(n)` to count + `O(radix)` prefix sums + `O(n)` to deal = **O(n + radix)**. Total: **T(n) = d · (n + radix)**.

The crucial point: `d` is a property of the **data** (the digit-width of the keys), not of `n`. For 32-bit integers in base 2¹⁶, `d = 2`. So radix-sorting 1,000,000 32-bit ints is **2 counting passes**, while a comparison sort needs ~20M comparisons:

| radix | d (passes for 32-bit) | digit-ops for n=10⁶ | vs comparison bound (n·log₂n ≈ 19.9M) |
|-------|----------------------|----------------------|----------------------------------------|
| 10 | 10 | 10,000,000 | 0.50× |
| 256 | 4 | 4,000,000 | 0.20× |
| 2¹⁶ | 2 | 2,000,000 | **0.10×** |

Base 2¹⁶ does ~10% of the comparison-sort lower bound's work. **That is why radix wins for fixed-width integer keys.**

- **Space:** O(n + radix) extra per pass (count array + output buffer). Radix is **not** in-place — the trade-off vs heapsort.
- **Stable:** yes (inherited from counting sort).
- **Not a comparison sort**, so Ω(n log n) does **not** apply.

## 6. Section D — when to pick radix vs the comparison sorts

| algorithm | best | worst | space | stable? | best for |
|-----------|------|-------|-------|---------|----------|
| **radix sort** | O(d·(n+b)) | O(d·(n+b)) | O(n+b) | YES (stable) | int/string keys |
| counting sort | O(n+k) | O(n+k) | O(n+k) | YES (stable) | small int range k |
| quicksort | O(n log n) | O(n²) | O(log n) | NO (in-place) | general, comparison |
| mergesort | O(n log n) | O(n log n) | O(n) | YES (stable) | general, stable |
| heapsort | O(n log n) | O(n log n) | O(1) | NO (in-place) | general, guaranteed |

**Pick radix** when keys are fixed-width integers/strings, `n` is large, and you can afford the O(n) extra memory. **Pick quicksort/heap** when keys are arbitrary comparable objects (no digit decomposition) or memory is tight.

> **Pitfall:** this implementation handles **non-negative** integers. For signed ints or floats, map them to unsigned first (flip the sign bit for floats) — see CLRS §8.3.

## 7. Section E — the gold check (pin for `radix_sort.html`)

On a **seeded** input (`random.Random(42)`, n=12, max=9999):

```
seeded input:  [1824, 409, 4506, 4012, 3657, 2286, 1679, 8935, 1424, 9674, 6912, 520]
radix result : [409, 520, 1424, 1679, 1824, 2286, 3657, 4012, 4506, 6912, 8935, 9674]
[check] radix == sorted()? True
```

The HTML recomputes the sort on the **identical** seeded input and gold-checks three pinned scalars:

| scalar | gold value |
|--------|------------|
| `sorted[0]` | 409 |
| `sorted[-1]` | 9674 |
| pass-1 `bucket[0]` size | 1 |

```
[check] gold scalars reproduce from input: OK
```

---

## 8. Files in this bundle

| file | role |
|------|------|
| [`radix_sort.py`](./radix_sort.py) | the single source of truth — run it to regenerate every number above |
| [`radix_sort_output.txt`](./radix_sort_output.txt) | captured stdout of `uv run python radix_sort.py` |
| [`radix_sort.html`](./radix_sort.html) | step-through animation + live gold check |
| [`RADIX_SORT.md`](./RADIX_SORT.md) | this guide |

← [all tutorials](../index.html)
