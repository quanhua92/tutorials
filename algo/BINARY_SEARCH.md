# BINARY_SEARCH — Binary Search in Action

> The whole algorithm: **compare the middle, keep one half, discard the other.**
> Sortedness is what makes the discard safe. Every number in this guide is
> printed by [`binary_search.py`](./binary_search.py) and re-checked live by
> [`binary_search.html`](./binary_search.html).

[check: OK] — `binary_search.html` recomputes the search path in JS on the same
array and matches `binary_search.py` Section F (`key=23 → index 11, path [7, 11]`).

---

## 0. The intuition — the phone book trick

You are looking for a name in a **sorted** phone book. Flip to the middle page
and compare: if your name comes **before** the middle, rip the back half off;
if **after**, rip the front half off. Each step cuts the pile in **half**. After
`k` steps only `n / 2^k` pages remain, so you need at most

```
log2(n)  steps
```

to find any name. That is the entire algorithm. The sortedness is what lets you
*discard* half the search space per probe — without it, the middle tells you
nothing about where the target lives.

Four shapes share one loop:

| variant         | returns the index of…                         | when you use it                    |
|-----------------|-----------------------------------------------|------------------------------------|
| exact search    | `key`, or `-1`                                | "is it there?"                     |
| `lower_bound`   | first `i` with `arr[i] >= key` (left insert)  | insert keeping sort; dedupe-prefix |
| `upper_bound`   | first `i` with `arr[i] >  key` (right insert) | insert after equals                |
| search-on-answer| smallest `x` with `P(x)` true                 | `P` monotone (e.g. min capacity)   |

---

## 1. The core loop — compare middle, discard half

The reference array (`n=16`, sorted, distinct):

```
idx:   0   1   2   3   4   5   6   7   8   9  10  11  12  13  14  15
val:   1   3   5   7   9  11  13  15  17  19  21  23  25  27  29  31
```

Worst-case probes for `n=16` is `floor(log2(16)) + 1 = 5`.

### Searching a present key (`key=23`)

| step | live window `[lo..hi]` | `mid` | `arr[mid]` | verdict                |
|------|------------------------|-------|------------|------------------------|
| 0    | `[0..15]`              | 7     | 15         | `15 < 23` → keep right |
| 1    | `[8..15]`              | 11    | 23         | `23 == 23` → **FOUND** |

Result: **index 11**, in **2 probes** (worst-case bound 5). Two comparisons pinned
a 16-element array.

### Searching an absent key (`key=24`)

| step | live window `[lo..hi]` | `mid` | `arr[mid]` | verdict                |
|------|------------------------|-------|------------|------------------------|
| 0    | `[0..15]`              | 7     | 15         | `15 < 24` → keep right |
| 1    | `[8..15]`              | 11    | 23         | `23 < 24` → keep right |
| 2    | `[12..15]`             | 13    | 27         | `27 > 24` → keep left  |
| 3    | `[12..12]`             | 12    | 25         | `25 > 24` → keep left  |
| —    | `lo=13 > hi=12`        | —     | —          | window empty → **ABSENT** |

Result: **index -1**, in **4 probes**. The loop terminates when `lo > hi`: the
live window is empty, so the key cannot be present.

**The invariant.** At every step: *if the key is in `arr`, it is in
`arr[lo..hi]`.* Discarding the wrong half would break this — that is exactly
what bugs do.

---

## 2. The probe calculation & the overflow bug

The midpoint must be computed as

```
mid = lo + (hi - lo) // 2          # SAFE
```

**not** `(lo + hi) // 2`. Both are mathematically equal, but `(lo + hi)` can
**overflow** in fixed-width integer languages (C, Java `int`). Python ints are
arbitrary precision so the bug is invisible here, but writing the safe form is a
habit that survives language switches.

```
(lo + hi) // 2        # DANGEROUS: lo + hi may overflow
lo + (hi - lo) // 2   # SAFE: each term stays inside [lo, hi]
```

On the full window `[lo=0, hi=15]` both give `7` — equal here (`[check] OK`).

### The overflow, made concrete (32-bit simulation)

With `INT_MAX = 2^31 - 1` and two valid indices `lo = hi = 2^31 - 1`:

```
(lo + hi) truncated to int32  = -2          # NEGATIVE → crash / bad index
lo + (hi - lo) // 2           = 2147483647  # correct
```

This is the bug behind nearly every "subtle binary search" report — including
one that lived in Java's `Arrays.binarySearch` for years (Joshua Bloch, 2006).
**Always use `lo + (hi - lo) // 2`.**

---

## 3. Lower / upper bound — the insertion points

Same discard-half loop, different *keep* rule and *stop* test. Bounds use a
**half-open** window `[lo, hi)` with `while lo < hi` and `hi = mid` (not
`mid - 1`): `lo` always stays a candidate answer.

Reference array **with duplicates** (`n=16`):

```
idx:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
val:  1  2  2  2  3  3  4  4  4  4  5  6  7  8  8  9
```

| key | `lower_bound` (first `≥`) | `upper_bound` (first `>`) | equal range | count |
|-----|---------------------------|---------------------------|-------------|-------|
| 0   | 0                         | 0                         | empty       | 0     |
| 2   | 1                         | 4                         | [1, 4)      | 3     |
| 4   | 6                         | 10                        | [6, 10)     | 4     |
| 8   | 13                        | 15                        | [13, 15)    | 2     |
| 9   | 15                        | 16                        | [15, 16)    | 1     |
| 10  | 16                        | 16                        | empty       | 0     |

- **key=4**: indices 6,7,8,9 are all `4`, so `lower_bound=6`, `upper_bound=10`,
  `count=4`. The half-open range `[lower, upper)` is *exactly* the run of
  values equal to `key`.
- **key=10** is larger than everything → both bounds `= 16` (would append).
- **key=0** is smaller than everything → both bounds `= 0`, `count=0`.

`[check] OK` — `lower_bound`/`upper_bound` match a brute-force scan for all keys
0..11. Exact `binary_search` is just `lower_bound` when `arr[lower_bound]==key`.

---

## 4. Binary search on the answer (monotone predicate)

When a predicate `P(x)` is **monotone** — `false…false, true…true` — you can
binary-search the *threshold* instead of scanning it. This turns an
`O(answer_range)` scan into `O(log(answer_range))` predicate evaluations.

**Problem** (LeetCode 1011, "Capacity To Ship Packages Within D Days"): ship
`weights` **in order** within `days` days; each day's total load ≤ the ship
**capacity**. Find the **min** capacity.

```
weights = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
days    = 5
sum = 55    max = 10    →  search range [max, sum] = [10, 55]
```

The predicate `can_ship(cap)` is monotone: once a capacity works, every larger
capacity also works. So the answer space is `false…false,true…true` — binary
search the threshold with `lower_bound` logic.

| capacity | days needed | `can_ship`? | decision         |
|----------|-------------|-------------|------------------|
| 10–14    | 6–7         | no          | must go higher   |
| **15**   | **5**       | **yes**     | **answer found** |
| 16–20    | 4–5         | yes         | keep lowering    |
| 21–27    | 3           | yes         | keep lowering    |
| 28–54    | 2           | yes         | keep lowering    |
| 55       | 1           | yes         | keep lowering    |

**Min capacity = 15.** The optimal day-by-day plan:

```
day 1: [1, 2, 3, 4, 5]  (load 15)
day 2: [6, 7]           (load 13)
day 3: [8]              (load  8)
day 4: [9]              (load  9)
day 5: [10]             (load 10)
→ 5 days ≤ 5 required: OK
```

`[check] OK` — `min capacity == 15` (gold value for `binary_search.html`).
Capacity 14 needs 6 days (fails); 15 needs exactly 5. **Complexity:**
`O(log(sum - max)) * O(n)` — each predicate eval is one `O(n)` sweep, and we do
`log(45) ≈ 6` of them.

> **Pattern.** Anytime the question is "find the **minimum/maximum** value such
> that [condition]", check if the condition is monotone. If yes, this is binary
> search on the answer. Common instances: min capacity, min max-pair-sum, kth
> smallest in sorted matrices, split-array-largest-sum, aggressive-cows.

---

## 5. The off-by-one pitfall — inclusive vs half-open bounds

Two boundary conventions look almost identical but mix to **different** loop
tests. Mixing them is the #1 source of infinite loops and missed-endpoint bugs.

| convention            | init          | test          | update                       |
|-----------------------|---------------|---------------|------------------------------|
| A — **inclusive**      | `hi = n - 1`  | `while lo <= hi` | `lo = mid + 1`, `hi = mid - 1` |
| B — **half-open**      | `hi = n`      | `while lo <  hi` | `lo = mid + 1`, `hi = mid`     |

**Rule of thumb:** pick ONE convention per function and never mix the test with
the update. The cardinal sins:

- **half-open test `lo < hi`** with **inclusive update `hi = mid - 1`** → skips
  `arr[mid - 1]`, can miss the answer.
- **inclusive test `lo <= hi`** with **half-open update `hi = mid`** → when
  `lo == hi` the window never shrinks → **INFINITE LOOP**.

### Reproducing the infinite loop (absent key=2, broken mix)

`while lo <= hi` with `hi = mid` (should be `hi = mid - 1`), searching `key=2`
(absent from `ARR`):

```
spin 1: lo=0 hi=15 mid=7  arr[mid]=15
spin 2: lo=0 hi=7  mid=3  arr[mid]=7
spin 3: lo=0 hi=3  mid=1  arr[mid]=3
spin 4: lo=0 hi=1  mid=0  arr[mid]=1
spin 5: lo=1 hi=1  mid=1  arr[mid]=3     # arr[1]=3 > 2, hi=mid=1 (no move!)
spin 6: lo=1 hi=1  mid=1  arr[mid]=3     # STALL
spin 7: lo=1 hi=1  mid=1  arr[mid]=3     # STALL
... HIT THE 100-iteration safety cap -> would loop FOREVER.
```

The contrast — the **correct** inclusive version handles absent keys cleanly:

```
binary_search(ARR, 2) = -1   (path [7, 3, 1, 0])
```

**FIX:** with `while lo <= hi`, *always* use `hi = mid - 1` and `lo = mid + 1`.
With `while lo < hi`, *always* use `hi = mid`. The loop **test** and the bound
**update** must come from the **same** convention.

---

## 6. Complexity summary

| measure                       | value                              |
|-------------------------------|------------------------------------|
| exact search, worst case      | `O(log n)` probes (`≤ floor(log2 n)+1`) |
| `lower/upper_bound`           | `O(log n)`                         |
| search-on-answer              | `O(log R) * cost(P)`, `R` = answer range |
| space                         | `O(1)` (iterative)                 |
| requirement                   | **sorted** input                   |

**Why `O(log n)`:** each probe halves the live window. After `k` probes the
window is at most `ceil(n / 2^k)`; it empties (`< 1`) once `2^k > n`, i.e.
`k > log2 n`.

---

## 7. Gold values (pinned, reproducible)

```
Array: [1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31]
search key=23 -> index 11, path [7, 11], probes 2
lower_bound(arr_dup, 4) = 6   upper_bound = 10   count = 4
ship_within_days([1..10], days=5) = 15
[check] all GOLD values reproduce from the implementations:  OK
```

---

## References

- Knuth, *The Art of Computer Programming* Vol 3, §6.2.1 (searching an ordered table).
- CLRS (3rd ed.), Exercise 2.3-5 and the binary-search pitfalls discussion.
- Bentley, *Programming Pearls* (1986), Column 4 — the famous "90% of
  programmers write it wrong" binary-search anecdote.
- Bloch, "Extra, Extra — Read All About It: Nearly All Binary Searches and
  Mergesorts are Broken" (2006) — the `mid = (lo+hi)/2` overflow in Java.

> Next: [`interpolation_search.html`](./interpolation_search.html) — when data is
> uniform, you can do *better* than `O(log n)` by *estimating* where the key is.
