# Merge Sort — A Visual, Worked-Example Guide

> **Companion code:** [`merge_sort.py`](./merge_sort.py). **Every number in this
> guide is printed by `uv run python merge_sort.py`** — change the code, re-run,
> re-paste. Nothing here is hand-computed.
>
> **Sibling guide:** [`SELECTION_SORT.md`](./SELECTION_SORT.md) — the Θ(n²)
> minimum-swap foil. Cross-references are marked 🔗 throughout.
>
> **Live animation:** [`merge_sort.html`](./merge_sort.html) — open in a browser,
> watch the divide tree split, then reassemble sorted.
>
> **Source material:** Knuth, TAOCP Vol 3 §5.2.4 (von Neumann, ~1945); CLRS
> §2.3; Tim Peters, *"List Sort* (TimSort)".

---

## 0. TL;DR — the whole algorithm in one picture

### Read this first — two sorted piles of cards

You don't need any math to get the idea. You have a shuffled deck of **n**
cards. To sort it:

1. **CUT** the deck exactly in half. Recursively sort each half. (A one-card
   "half" is already sorted — that's the base case.)
2. **MERGE** the two sorted halves: look at the top card of each pile, take the
   **smaller**, put it down. On a **tie, take from the left pile first**
   (→ stable). Repeat until both piles are empty.

That's it. The magic is that **merging two already-sorted piles is linear** —
O(n) — because you never compare a card to more than one other card per output.
And because you halve the deck **log₂n** times, you do that linear merge log₂n
times: **O(n log n) total.**

```
the core identity:
  T(n) = 2·T(n/2) + Θ(n)   ──►  Θ(n log n)   (Master theorem, case 2)
         └ divide ┘  └merge┘
```

| | value | why |
|---|---|---|
| comparisons | `~ n·log₂n` | every level does ≤ n work; log₂n levels |
| best = avg = worst | **Θ(n log n)** | **no degenerate input** — the whole point |
| stable | **YES** | take-from-left rule on ties |
| auxiliary space | **Θ(n)** | the merge buffer (NOT in-place) |
| where it lives | **everywhere** | Python `list.sort`, Java `Arrays.sort(Object[])` → TimSort |

---

## 1. The algorithm — divide then merge

> Printed by `merge_sort.py` Section A.

Worked on `[64, 25, 12, 22, 11]` (n = 5 → **3 levels** of recursion, **4
merges**). Two phases repeat at every node of the recursion tree:

- **DIVIDE**: cut `arr[lo..hi]` at `mid = (lo+hi)//2` → recurse on each half.
- **MERGE**: after both halves return sorted, merge them in O(n).

Base case: a range of length ≤ 1 is already sorted (nothing to do). **All the
real work is in the MERGE step, never in the divide** (divide is just index
arithmetic).

### The reference implementation

```python
def merge(arr, lo, mid, hi):
    left  = arr[lo:mid + 1]              # copy left half
    right = arr[mid + 1:hi + 1]          # copy right half
    i = j = 0; k = lo
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:          # <= : LEFT on tie -> STABLE
            arr[k] = left[i]; i += 1
        else:
            arr[k] = right[j]; j += 1
        k += 1
    while i < len(left):  arr[k] = left[i];  i += 1; k += 1   # drain left
    while j < len(right): arr[k] = right[j]; j += 1; k += 1   # drain right

def _ms(a, lo, hi):
    if lo >= hi: return
    mid = (lo + hi) // 2
    _ms(a, lo, mid); _ms(a, mid + 1, hi)
    merge(a, lo, mid, hi)
```

The **only** line separating a stable from an unstable merge is the `<=`. Write
`<` (take right on a tie) and stability is gone. §5.

---

## 2. The divide tree — how the array gets chopped up

> Printed by `merge_sort.py` Section B.

Every node is a recursive call; leaves (length 1) are sorted.

```
depth 0: [64, 25, 12, 22, 11] [0..4]
depth 1:   [64, 25, 12] [0..2]   [22, 11] [3..4]
depth 2:     [64, 25] [0..1]   [12] leaf   [22] leaf   [11] leaf
depth 3:       [64] leaf   [25] leaf
```

Read top-down: the whole array splits into `[64,25,12]` and `[22,11]`, each of
those splits again, until every piece is a single element.

The number of splits along the longest root-to-leaf path is the tree
**height = 3 = ⌈log₂ 5⌉ = ⌈2.32⌉**. ✓

```
n = 5 leaves (one per element). An internal node has exactly 2 children,
so #merges = #internal nodes = 4.
```

---

## 3. The merge steps — where the work happens

> Printed by `merge_sort.py` Section C.

Merges run **bottom-up** (deepest first), as each pair of children returns. Rule:
compare the two fronts; take the smaller; on a tie take **left** (→ stable).
When one pile empties, copy the rest of the other.

```
-- merge 0: [0..0] + [1..1] --     [64] + [25]      -> [25, 64]     (1 comparison)
-- merge 1: [0..1] + [2..2] --     [25, 64] + [12]  -> [12, 25, 64] (1 comparison)
-- merge 2: [3..3] + [4..4] --     [22] + [11]      -> [11, 22]     (1 comparison)
-- merge 3: [0..2] + [3..4] --     [12, 25, 64] + [11, 22] -> [11, 12, 22, 25, 64]  (3 comparisons)

Total comparisons across all 4 merges: 6
Upper bound n·⌈log₂n⌉ = 5·3 = 15.  Measured 6 ≤ 15: OK
```

**Why each merge is cheap:** merge 3 looks big (3 elements + 2 elements = 5
outputs) but needs only 3 comparisons — once one pile is drained, the rest of
the other is copied *without any comparisons*.

**Each level of the tree touches every element exactly once** during its merges
→ **O(n) work per level**. With ⌈log₂n⌉ levels, total work = **O(n log n)**.
That is the Master theorem on `T(n) = 2·T(n/2) + Θ(n)`.

---

## 4. Complexity analysis — BEST = AVERAGE = WORST = Θ(n log n)

> Printed by `merge_sort.py` Section D.

Merge sort **always** divides in half and **always** merges linearly. The
input's order only changes *how many comparisons each merge makes* (best case
~ n/2 per level if already sorted, worst case ~ n per level), **not the number
of levels**. So there is **no degenerate input**.

| case | comparisons | merges | sorted? |
|------|-------------|--------|---------|
| best (already sorted) | 7 | 4 | ✓ |
| average (random) | 6 | 4 | ✓ |
| worst (reverse sorted) | 5 | 4 | ✓ |

The comparison count varies only by a constant factor (~2×) across cases; the
**n log n shape is identical**. `n·log₂n` for n=5 = 11.6.

| case | comparisons | time | space | stable |
|------|-------------|------|-------|--------|
| best | `~(n/2)·log₂n` | **Θ(n log n)** | Θ(n) | yes |
| average | `~ n·log₂n` | **Θ(n log n)** | Θ(n) | yes |
| worst | `~ n·log₂n` | **Θ(n log n)** | Θ(n) | yes |

**Space: Θ(n) auxiliary** for the merge buffer (NOT in-place).

🔗 **Contrast** [`SELECTION_SORT.md`](./SELECTION_SORT.md) §3: Θ(n²)
comparisons in **every** case, but O(1) auxiliary space, in-place. Selection
sort minimizes *writes*; merge sort minimizes *comparisons* — and pays for it
with memory.

---

## 5. Stability — YES, by construction (the take-from-left rule)

> Printed by `merge_sort.py` Section E.

A sort is **stable** if equal keys keep their original relative order. Merge
sort is stable **by construction**: the merge rule says *"on a tie, take from
the LEFT half first."* Since the left half held the elements that came
**earlier** in the input, ties always resolve in input order.

```
Input (tag, value): [('2a', 2), ('1', 1), ('2b', 2), ('3', 3)]
Output             : [('1', 1), ('2a', 2), ('2b', 2), ('3', 3)]

The two 2's ended up as ['2a', '2b']; a stable sort keeps ['2a', '2b'].
[check] stable?  True  ->  merge sort IS stable
```

The **only** way to break this is to write `<` instead of `<=` in the merge
(taking right on a tie). The implementation above uses `<=`.

🔗 Compare with [`SELECTION_SORT.md`](./SELECTION_SORT.md) §4: the swap
leapfrogs equal keys → **NOT** stable. Merge sort pays O(n) space and **gets
stability for free.**

---

## 6. When to use merge sort (and where it hides in real systems)

**USE it when:**
- **You need guaranteed O(n log n) with no bad input.** Quicksort's worst case
  is Θ(n²); merge sort's never is. Mission-critical / real-time systems often
  prefer the predictability.
- **You need stability.** It is the canonical stable O(n log n) sort.
- **Sorting linked lists:** merge is **O(1) extra space** on linked lists
  (relink pointers, no buffer), and divide is pointer-based. The one place merge
  sort beats quicksort on space.
- **External sorting** (data > RAM): write sorted runs to disk, then k-way
  merge. Merge sort's sequential access pattern is ideal for slow media;
  random-access sorts thrash.

**DO NOT use plain merge sort when:**
- **You are tight on memory:** it needs Θ(n) auxiliary space. Use heapsort
  (in-place, O(1)) or an in-place merge variant.
- **You want cache-friendly in-place sorting on arrays:** quicksort's
  partitioning is in-place and cache-friendlier; merge sort's buffer copy hurts.
  (This is why libc `qsort` is usually quicksort.)
- **n is small** (`< ~64`): insertion sort's lower overhead wins — exactly the
  hybrid trick TimSort uses.

### Where it hides

| system | sort | notes |
|--------|------|-------|
| Python `list.sort` / `sorted()` | **TimSort** | merge sort + run detection + insertion sort for short runs; best case O(n) |
| Java `Arrays.sort(Object[])` | **TimSort** | since Java 7 (stability required for objects) |
| Java `Arrays.sort(int[])` | dual-pivot quicksort | NOT merge — chose speed + in-place over stability for primitives |
| `std::stable_sort`, V8 stable sort | merge sort | stability required |

---

## Appendix — GOLD (pinned values, verified by `merge_sort.py` and recomputed live in `merge_sort.html`)

```
array               = [64, 25, 12, 22, 11]
GOLD sorted         = [11, 12, 22, 25, 64]
GOLD comparisons    = 6
GOLD num merges     = 4
GOLD merge results  = [[25, 64], [12, 25, 64], [11, 22], [11, 12, 22, 25, 64]]
```

Open [`merge_sort.html`](./merge_sort.html) — the page rebuilds the identical
divide-and-merge tree in JS and shows the green `[check: OK]` badge confirming
it matches the `.py` GOLD exactly.
