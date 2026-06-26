# TIM_SORT — Timsort in Action

> Mergesort that refuses to throw away the order you already had. Best case **O(n)**, stable, and the default sort of Python, Java (objects), V8, and Rust's stable path.

This guide walks through [`tim_sort.py`](./tim_sort.py). Every table, number, and trace below is **printed by that file** — re-run `uv run python tim_sort.py` to regenerate [`tim_sort_output.txt`](./tim_sort_output.txt). Nothing here is hand-computed. For the animated step view, open [`tim_sort.html`](./tim_sort.html).

---

## 0. The one-paragraph mental model

Real-world data is rarely a perfectly shuffled mess — it has **streaks** of already-sorted elements (a partly-sorted log, a list someone appended to, a table sorted on one column). Mergesort and quicksort *ignore* that structure and pay n·log n every time. **Timsort hunts for that existing order and exploits it.** Four ideas, in one breath:

1. **Run detection** — scan left-to-right, grab every maximal *ascending* or *strictly-descending* run (descending runs are reversed in place). If the input is already sorted, timsort finds **one** run covering everything → **O(n)**, done.
2. **Minrun** — runs shorter than `minrun` are too tiny to be worth merging; extend them to `minrun` with **binary insertion sort**. `minrun` is chosen so the run count is ~a power of two → a *balanced* merge tree.
3. **Merge stack** — push runs on a stack and keep an **invariant** (`A > B + C` and `B > C`) so merges stay balanced and shallow → worst case **O(n log n)**.
4. **Galloping** — during a merge, if one side "wins" `MIN_GALLOP` (7) times in a row, its elements are *clustered*: instead of comparing one-by-one, **gallop** (exponential + binary search) to grab a whole run of them at once → near O(n) for imbalanced data.

## 1. The lineage

| idea | source |
|------|--------|
| Timsort | Tim Peters, `listsort.txt` (2002), shipped CPython 2.3 |
| Binary insertion sort | standard — extends short runs to `minrun` |
| Java port | 2007, `Arrays.sort(Object[])` (Joshua Bloch) |
| Rust | stable `slice::sort` is a timsort variant |

## 2. Key formulas (asserted in code)

```
minrun(n)       : shift n right until < 64; OR in any dropped low bit
                  -> result in [32, 64]  (CPython MAX_MINRUN = 64)
count_run(a,lo) : ascend if a[lo] <= a[lo+1]   (<= keeps STABILITY)
                  strictly descend otherwise (a[lo] > a[lo+1] > ...),
                  then reverse. Return (start, end, was_descending).
merge invariant : for the top-3 runs A,B,C (A deepest):
                    len(A) > len(B) + len(C)   and   len(B) > len(C)
gallop_search   : exponential jump (1,3,7,15,…) to bracket, then binary
                  search within the bracket. O(log k) for a run of k.
complexity      : worst O(n log n)  [balanced merges]
                  best  O(n)        [one long run, no merges]
```

> **Note on the [16,32] vs [32,64] range you may see online.** CPython uses `MAX_MINRUN = MIN_MERGE = 64` → minrun ∈ **[32, 64]**. Java's TimSort uses `MIN_MERGE = 32` → minrun ∈ [16, 32]. Same algorithm, different constant. This bundle follows CPython (the origin).

---

## 3. Section A — minrun: the [32,64] dial that balances the merge tree

For `n < 64`, timsort is just one binary-insertion-sort over the whole array (no runs, no merges). For `n ≥ 64`, `compute_minrun` shifts `n` right until it is `< 64`, OR-ing in any dropped low bit:

| n | minrun | runs ≈ n/minrun | nearest pow2 |
|------|--------|-----------------|--------------|
| 64 | 32 | 2 | 2 |
| 100 | 50 | 2 | 2 |
| 128 | 32 | 4 | 4 |
| 1000 | 63 | 16 | 16 |
| 1024 | 32 | 32 | 32 |
| 10000 | 40 | 250 | 128 |
| 10⁶ | 62 | 16130 | 8192 |

Minrun keeps the run count at or just above a power of two → the merge tree is **balanced (shallow)**, bounding depth at O(log n) and total work at O(n log n). The [32,64] window balances "insertion sort is still cheap" vs "enough runs to balance".

```
[check] minrun in [32,64] for all tested n >= 64? True
```

## 4. Section B — run detection (and reversing descenders)

Input `[5, 4, 3, 2, 8, 9, 1, 0, 7, 6]`:

| run | slice | kind | after |
|-----|-------|------|-------|
| 0 | [0:4] = 5,4,3,2 | descending → **REVERSED** | 2,3,4,5 |
| 1 | [4:6] = 8,9 | ascending | 8,9 |
| 2 | [6:8] = 1,0 | descending → **REVERSED** | 0,1 |
| 3 | [8:10] = 7,6 | descending → **REVERSED** | 6,7 |

**Why strict `>` on the descending side:** equal elements must keep input order. If a descending run used `>=`, two equal elements would swap on reversal and **stability is lost**. `>` keeps equals in original order.

The best case: an already-sorted input collapses to a single run.

```
already-sorted [0..9] -> ONE run of length 10: True
[check] sorted input -> single run (best case O(n))? True
```

## 5. Section C — binary insertion sort pads short runs to minrun

A natural run shorter than `minrun` is extended by inserting the next few elements via **binary search** for the slot (O(k log k) for k new elements, cheap constants, **stable** because we use the leftmost slot). `radix`... `binary_insertion_sort` demo: slice `[2,5,9,7,1,8,3,6]` with prefix `[2,5,9]` sorted → `[1,2,3,5,6,7,8,9]`.

```
[check] extended slice == sorted()? True
```

## 6. Section D — merge invariant + galloping

**(1) Best case** — mostly-sorted "real-world" input (seed=7, n=32): timsort finds **1 run, ~0 merges** → cost ≈ O(n).

**(2) Merge + gallop** — constructed input `run A = [60..91]` (left, all ≥ 60) + `run B = [1..32]` (right, all < 60). Two runs detected, then the merge-stack invariant collapses them:

```
natural runs detected = 2:
  run 0: start=0   natural=32  -> len=32  (ascending)
  run 1: start=32  natural=32  -> len=32  (ascending)
Merge stack evolution:
  step 0: (0,32)
  step 1: (0,32), (32,32)
  step 2: (0,64)            <- A and B merged (invariant: 32 <= 32 -> merge)
GALLOPING fired 1 time(s) (MIN_GALLOP=7)
result == sorted()? True
[check] timsort == sorted() on constructed input? True
```

**What galloping did here:** during the merge, B's values (1..32) are all smaller than A's first value (60), so B "won" ≥ 7 comparisons in a row. The merge then switched to galloping mode and copied **all of B in one shot** via exponential+binary search, instead of 32 one-by-one comparisons. For clustered/imbalanced data this turns merges toward O(n).

> **The merge invariant** (for the top three runs `A, B, C`, A deepest): `len(A) > len(B) + len(C)` **and** `len(B) > len(C)`. When violated, merge the shorter of `A, C` with `B`. This guarantees the largest run is never merged until smaller ones are, keeping depth O(log n).

## 7. Section E — complexity, comparison, and the gold check

| algorithm | best | worst | space | stable? | best for |
|-----------|------|-------|-------|---------|----------|
| **timsort** | **O(n)** | O(n log n) | O(n) | YES | Python/Java/Rust stable |
| mergesort | O(n log n) | O(n log n) | O(n) | YES | guaranteed, simple |
| quicksort | O(n log n) | O(n²) | O(log n) | NO | fast avg, in-place |
| heapsort | O(n log n) | O(n log n) | O(1) | NO | in-place, worst-case ok |

**The one-line pitch:** timsort is mergesort that doesn't throw away the order you already had.

**Gold** on a seeded input (`random.Random(42)`, n=64, max=999):

```
input[:8]  = [654, 114, 25, 759, 281, 250, 228, 142]
timsort result == sorted()? True
minrun = 32, num runs = 2, num merges = 3
```

The HTML recomputes on the identical seeded input and gold-checks:

| scalar | gold value |
|--------|------------|
| minrun | 32 |
| num_runs | 2 |
| sorted[0] | 6 |
| sorted[-1] | 980 |

```
[check] gold scalars reproduce from input: OK
```

> **Correctness:** `tim_sort` is fuzz-tested against Python's `sorted()` on **20,000** random inputs (uniform, heavy-duplicate, clustered/gallop-triggering, descending runs, near-sorted) and **3,000** stability probes (tagged tuples) — 0 mismatches.

---

## 8. Files in this bundle

| file | role |
|------|------|
| [`tim_sort.py`](./tim_sort.py) | the single source of truth — run it to regenerate every number above |
| [`tim_sort_output.txt`](./tim_sort_output.txt) | captured stdout of `uv run python tim_sort.py` |
| [`tim_sort.html`](./tim_sort.html) | step-through animation + live gold check |
| [`TIM_SORT.md`](./TIM_SORT.md) | this guide |

← [all tutorials](../index.html)
