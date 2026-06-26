# Selection Sort — A Visual, Worked-Example Guide

> **Companion code:** [`selection_sort.py`](./selection_sort.py). **Every number
> in this guide is printed by `uv run python selection_sort.py`** — change the
> code, re-run, re-paste. Nothing here is hand-computed.
>
> **Sibling guide:** [`MERGE_SORT.md`](./MERGE_SORT.md) — the Θ(n log n)
> divide-and-conquer foil. Cross-references are marked 🔗 throughout.
>
> **Live animation:** [`selection_sort.html`](./selection_sort.html) — open in a
> browser, step through the passes.
>
> **Source material:** Knuth, TAOCP Vol 3 §5.2.3; CLRS §2.1.

---

## 0. TL;DR — the whole algorithm in one picture

### Read this first — the bookshelf with the shortest books

You don't need any math to get the idea. Picture a bookshelf of **n** books you
must order shortest → tallest, with one empty "scratch" slot in your hand.

**Selection sort runs `n−1` rounds. In each round:**

1. **SCAN** the books from position `i` to the end, remembering the **shortest**
   one and *where it is*. (Pure reads — no shifting.)
2. **SWAP** that shortest book into position `i`. (Exactly **one** swap, done.)

That's it. The scan is a linear read; the swap is a single exchange. So
selection sort makes the **fewest swaps of any comparison sort: at most `n−1`**.
That is its reason to exist.

The price: you **always** scan the entire unsorted tail, even if the shelf is
already sorted. There is **no early exit**. So it is **Θ(n²) in comparisons in
the best, average, *and* worst case** — it literally cannot tell it's done early.

```
the slider selection sort sits on:
  FEWEST SWAPS (≤ n−1)      ←── selection sort's win
  MOST   COMPARISONS (Θ(n²)) ──→ selection sort's loss, always
```

| | value | why |
|---|---|---|
| comparisons | `n(n−1)/2` **always** | every pass re-scans the whole tail |
| swaps | `≤ n−1` | one per pass (minimum of any comparison sort) |
| best = avg = worst | **Θ(n²)** | no fast path; order of input irrelevant |
| stable | **NO** | the swap can leapfrog an equal key |
| auxiliary space | **O(1)** | in-place; one temp variable |

---

## 1. The algorithm, pass by pass

Worked on `[64, 25, 12, 22, 11]` (n = 5 → **4 passes**). The **sorted prefix**
grows by one each pass and is never touched again.

> Every line below is printed by `selection_sort.py` Section A.

```
Input  : [64, 25, 12, 22, 11]
Sorted : [11, 12, 22, 25, 64]

-- pass i=0: scan window [0..4] (4 comparisons) --
   before : [64, 25, 12, 22, 11]   min found: value 11 at index 4  -> SWAP
   after  : [11, 25, 12, 22, 64]

-- pass i=1: scan window [1..4] (3 comparisons) --
   before : [11, 25, 12, 22, 64]   min found: value 12 at index 2  -> SWAP
   after  : [11, 12, 25, 22, 64]

-- pass i=2: scan window [2..4] (2 comparisons) --
   before : [11, 12, 25, 22, 64]   min found: value 22 at index 3  -> SWAP
   after  : [11, 12, 22, 25, 64]

-- pass i=3: scan window [3..4] (1 comparison)  --
   before : [11, 12, 22, 25, 64]   min found: value 25 at index 3  -> self-swap (skipped)
   after  : [11, 12, 22, 25, 64]
```

After pass `i = n−2`, position `n−1` is automatically correct (the lone largest
element), so we stop. **Notice pass 3 found the min already at index 3 — a
self-swap, skipped.** That's why *actual* swaps (3) can be less than the
`n−1 = 4` maximum.

### The reference implementation

```python
def selection_sort(arr):
    a = list(arr)
    n = len(a)
    for i in range(n - 1):              # n-1 passes
        min_idx = i                     # assume the min is at the boundary
        for j in range(i + 1, n):       # scan the unsorted tail
            if a[j] < a[min_idx]:
                min_idx = j
        if min_idx != i:                # skip the self-swap (min already home)
            a[i], a[min_idx] = a[min_idx], a[i]
    return a
```

The `if min_idx != i` guard is what keeps swaps at the **minimum**. Remove it
and you do exactly `n−1` swaps including no-ops.

---

## 2. Comparison & swap counts — the two invariants

> Printed by `selection_sort.py` Section B.

**Comparisons per pass = `n − 1 − i`** (the window shrinks by one each pass):

| pass `i` | window size | comparisons |
|----------|-------------|-------------|
| 0 | 5 | 4 |
| 1 | 4 | 3 |
| 2 | 3 | 2 |
| 3 | 2 | 1 |
| **total** | | **10** |

`n(n−1)/2 = 5·4/2 = 10` ✓ — **identical on every input**, because the scan never
short-circuits.

**Swaps:**

| | count |
|---|---|
| real swaps (element actually moved) | **3** |
| self-swaps (min was already at `i`) | 1 |
| max possible (`n−1`) | 4 |

> `[check] real_swaps ≤ n−1: OK (3 ≤ 4)`

**This is selection sort's selling point.** Bubble sort and insertion sort can
make Θ(n²) *swaps*; selection sort makes **Θ(n)**. On write-limited hardware
(flash, EEPROM) — where a write costs orders of magnitude more than a read —
that gap dominates and selection sort wins despite its Θ(n²) comparisons.

---

## 3. Complexity analysis — BEST = AVERAGE = WORST = Θ(n²)

> Printed by `selection_sort.py` Section C.

The inner scan **always** walks the whole unsorted tail and compares every
element against the running min. The array's current order is **irrelevant** to
how many comparisons get made — even a fully sorted input is scanned end to end
every pass.

| case | comparisons | real swaps | sorted? |
|------|-------------|------------|---------|
| best (already sorted) | 10 | 0 | ✓ |
| average (random) | 10 | 4 | ✓ |
| worst (reverse sorted) | 10 | 2 | ✓ |

All three use **exactly** `n(n−1)/2 = 10` comparisons. There is no fast path.

| case | comparisons | swaps | time |
|------|-------------|-------|------|
| best | `n(n−1)/2` | `0 … n−1` | **Θ(n²)** |
| average | `n(n−1)/2` | `≈ n/2` | **Θ(n²)** |
| worst | `n(n−1)/2` | `n−1` | **Θ(n²)** |

auxiliary space: **O(1)** (in-place, one temp var).

🔗 **Contrast:** insertion sort is O(n) on already-sorted input (best case).
Selection sort has no such mercy — it pays full Θ(n²) no matter what.

---

## 4. Stability — NOT stable by default (the swap leapfrogs)

> Printed by `selection_sort.py` Section D.

A sort is **stable** if equal keys keep their original relative order.
Selection sort's swap can **break** this. Tag equal keys with their original
index so we can watch order scramble:

```
Input (tag, value): [('2a', 2), ('2b', 2), ('1', 1)]
  pass 0: [('1', 1), ('2b', 2), ('2a', 2)]   (min at index 2, swapped=True)
  pass 1: [('1', 1), ('2b', 2), ('2a', 2)]   (min at index 1, swapped=False)

Result: [('1', 1), ('2b', 2), ('2a', 2)]
The two 2's ended up as ['2b', '2a']; a stable sort would keep ['2a', '2b'].
[check] stable?  False  ->  selection sort is NOT stable
```

**Why it breaks:** at pass 0 the min is `'1'` at index 2. The swap is
`arr[0] ↔ arr[2]`, i.e. `'2a'` and `'1'` exchange places. That **flings `'2a'`
from position 0 to position 2 — jumping past `'2b'`** which had been behind it.
Now `'2b'` precedes `'2a'`: relative order reversed.

**The fix (and its cost):** instead of *swapping*, *insert* the min by shifting
the prefix right (O(n) writes per pass). That restores stability but turns the
O(n) swap count into O(n²) writes — exactly what we chose selection sort to
avoid. **Trade-off.**

> Takeaway: plain selection sort is **NOT** stable. Need stability? Use
> 🔗 [`MERGE_SORT.md`](./MERGE_SORT.md) (stable, Θ(n log n)) or insertion sort.

---

## 5. When to use selection sort (and when NOT to)

**USE it when:**
- **Writes are expensive** (flash/EEPROM): ≤ `n−1` swaps is the minimum of any
  comparison sort. On write-limited hardware this beats everything.
- **n is small** (`n ≲ 20`): tiny constant factor, no recursion, no auxiliary
  buffer. The inner scan is just *compare + branch* — often the fastest simple
  sort to benchmark.
- **You need predictable timing**: always Θ(n²), no surprises.
- **As a building block**: heapsort is *"selection sort with a heap for the
  scan"*, turning Θ(n²) into Θ(n log n).

**DO NOT use it when:**
- **n is large**: Θ(n²) comparisons dominate. Use 🔗 merge sort (Θ(n log n),
  stable) or quicksort (Θ(n log n) avg).
- **The input is nearly sorted**: insertion sort is O(n) on it; selection sort
  is still Θ(n²). **No adaptivity.**
- **You need stability**: use merge sort or insertion sort.

---

## Appendix — GOLD (pinned values, verified by `selection_sort.py` and recomputed live in `selection_sort.html`)

```
array              = [64, 25, 12, 22, 11]
GOLD sorted        = [11, 12, 22, 25, 64]
GOLD comparisons   = 10      (= n(n-1)/2)
GOLD real swaps    = 3       (≤ n-1 = 4)
```

Open [`selection_sort.html`](./selection_sort.html) — the page re-runs the
identical algorithm in JS and shows the green `[check: OK]` badge confirming it
matches the `.py` GOLD exactly.
