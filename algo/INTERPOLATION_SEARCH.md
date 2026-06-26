# INTERPOLATION_SEARCH — Interpolation Search in Action

> Binary search always probes the **middle**. Interpolation search probes
> **where the key is expected to be**, by linear interpolation between the
> endpoints. On uniform data that is `O(log log n)`; on clustered data it
> collapses to `O(n)`. Every number here is printed by
> [`interpolation_search.py`](./interpolation_search.py) and re-checked live by
> [`interpolation_search.html`](./interpolation_search.html).

[check: OK] — `interpolation_search.html` recomputes both algorithms in JS on
the same arrays and matches `interpolation_search.py` Section F (uniform `110 →
path [10]`; clustered `14 → 15` interpolation probes vs `4` binary).

---

## 0. The intuition — the dictionary, not the phone book

Binary search always flips to the MIDDLE page. That is optimal when you know
**nothing** about where the word lives. But you do not look up *"xylophone"* by
opening the dictionary to **M** and halving from there — you open near the
**back**, because you know the alphabet. Interpolation search does exactly that:
it uses the **values** at the ends of the live window to **estimate** where the
key sits, then probes there.

| algorithm             | probe rule                                   | cost shape         |
|-----------------------|----------------------------------------------|--------------------|
| binary search         | the MIDDLE index                             | `O(log n)` always  |
| interpolation search  | where a straight line predicts the key       | `O(log log n)` avg, `O(n)` worst |

The estimate (linear interpolation between the endpoints):

```
pos = lo + (key - arr[lo]) / (arr[hi] - arr[lo]) * (hi - lo)
```

Geometrically: draw a straight line from `(lo, arr[lo])` to `(hi, arr[hi])` and
read off the x-position whose y-value equals `key`. If the data is **uniform**,
that line **is** the data, so `pos` lands **on** the key in one shot.

---

## 1. The probe formula — estimating where the key is

The single line that distinguishes interpolation from binary search:

```
pos = lo + (key - arr[lo]) * (hi - lo) // (arr[hi] - arr[lo])
```

Think of it as: how far along the **value** range `[arr[lo], arr[hi]]` is the
key, applied to the **index** range `[lo, hi]`.

Reference array (uniform, `n=16`, step 10):

```
idx:   0   1   2   3   4   5   6   7   8   9  10  11  12  13  14  15
val:  10  20  30  40  50  60  70  80  90 100 110 120 130 140 150 160
```

Estimate `pos` for `key=110` on the full window `[lo=0, hi=15]`:

```
fraction = (key - arr[lo]) / (arr[hi] - arr[lo])
         = (110 - 10) / (160 - 10)  = 100 / 150  = 0.6667
pos = lo + fraction * (hi - lo)
    = 0 + 0.6667 * 15  = 10
arr[10] = 110 == key=110  ->  ONE-SHOT HIT
```

`[check] OK` — one-probe hit: `pos=10`, `arr[10]=110`. Binary search on the same
key takes 4 probes.

---

## 2. Why it works on uniform data — the line IS the data

For a perfectly uniform array `arr[i] = a + b*i`, the interpolation line through
**any** two points `(i, arr[i])` coincides with the data. So the estimated `pos`
for any in-range key lands **exactly** on the index that holds it.

| key | linear est. `pos` | true index | `arr[pos]` | one-shot? |
|-----|-------------------|------------|------------|-----------|
| 10  | 0                 | 0          | 10         | yes       |
| 40  | 3                 | 3          | 40         | yes       |
| 90  | 8                 | 8          | 90         | yes       |
| 110 | 10                | 10         | 110        | yes       |
| 160 | 15                | 15         | 160        | yes       |

5/5 in-range keys are hit in a single probe. This is why interpolation search
averages `O(log log n)` — rarely more than ~2-3 probes — on uniform data.

---

## 3. Complexity on uniform data — `O(log log n)` vs `O(log n)`

Same key (`110`), uniform array, both algorithms:

```
interpolation search : path [10]      -> index 10   (1 probe)
binary search        : path [7,11,9,10] -> index 10   (4 probes)
```

Interpolation wins 4-to-1 here. The expected probe count is `O(log log n)`;
binary search is `O(log n)`:

| n            | `log2 n` (binary) | `log2 log2 n` (interp) |
|--------------|-------------------|------------------------|
| 16           | 4.0               | 2.0                    |
| 256          | 8.0               | 3.0                    |
| 4,096        | 12.0              | 3.6                    |
| 65,536       | 16.0              | 4.0                    |
| 1,048,576    | 20.0              | 4.3                    |
| 4,294,967,296| 32.0              | 5.0                    |

For a **billion** elements, binary search needs ~30 probes but interpolation
search averages ~5. That gap is the whole point.

`[check] OK` — interpolation beats binary on uniform `key=110`: `1 < 4`.

> **Why doubly-logarithmic?** On uniform data, each probe's error is
> proportional to the *current window*, and the window shrinks by a factor
> each step — so the residual gap shrinks *doubly* exponentially, reaching 0 in
> `O(log log n)` steps. (Knuth, TAOCP Vol 3, §6.2.2.)

---

## 4. The degradation — clustered data collapses to `O(n)`

Now a **clustered** array: 15 values packed tightly (`0..14`) plus one huge
outlier (`1,000,000`). The interpolation line is dragged by the outlier, so the
estimated `pos` for a small key lands near `0` every time, and the search
**crawls** one index per probe.

```
idx:   0  1  2  3  4  5  6  7  8  9  10  11  12  13  14        15
val:   0  1  2  3  4  5  6  7  8  9  10  11  12  13  14  1,000,000
```

Search `key=14` (present at index 14), step by step:

```
step  0: window [lo=0, hi=15]  pos= 0  arr[pos]= 0  < key -> lo=pos+1
step  1: window [lo=1, hi=15]  pos= 1  arr[pos]= 1  < key -> lo=pos+1
step  2: window [lo=2, hi=15]  pos= 2  arr[pos]= 2  < key -> lo=pos+1
  ...
step 13: window [lo=13,hi=15]  pos=13  arr[pos]=13  < key -> lo=pos+1
step 14: window [lo=14,hi=15]  pos=14  arr[pos]=14  == key -> FOUND

interpolation: 15 probes -> index 14
binary       :  4 probes -> index 14   (path [7, 11, 13, 14])
```

Interpolation is **3.8x slower** than binary search here. The outlier makes
`(arr[hi] - arr[lo]) ~ 1,000,000` while `(key - arr[lo]) ~ 14`, so the fraction
is `~0.000014` and `pos` floors to `lo` every time — the window shrinks by ONE
index per step, i.e. `O(n)`.

`[check] OK` — interpolation degrades (`>=` binary probes) on clustered `key=14`:
`15 >= 4`.

**Worst case** (adversarial / exponential data): interpolation search is `O(n)`;
binary search stays `O(log n)`. Use interpolation **only** when the data is
known to be (approximately) uniform.

---

## 5. When to use which — the decision table

| data shape            | interpolation avg | binary worst | pick        |
|-----------------------|-------------------|--------------|-------------|
| uniform / linear      | `O(log log n)`    | `O(log n)`   | INTERPOLATE |
| clustered / skewed    | up to `O(n)`      | `O(log n)`   | BINARY      |
| unknown / adversarial | up to `O(n)`      | `O(log n)`   | BINARY      |
| small `n` (< ~50)     | ~same             | `O(log n)`   | BINARY      |

Side-by-side probe counts across **both** arrays and several keys:

| array     | key       | interpolation probes | binary probes | winner |
|-----------|-----------|----------------------|---------------|--------|
| uniform   | 110       | 1                    | 4             | interp |
| uniform   | 75        | 1                    | 4             | interp |
| uniform   | 10        | 1                    | 4             | interp |
| clustered | 14        | 15                   | 4             | binary |
| clustered | 1,000,000 | 1                    | 5             | interp |

Interpolation dominates on the uniform array (including the absent key `75`,
which exits in 1 probe because the estimate places it outside the endpoint
range — the `arr[lo] <= key <= arr[hi]` guard trips immediately). On the
clustered array it loses badly for the small key (crawls) and ties/wins for the
outlier itself (the endpoint `arr[hi]` makes the estimate exact).

> **Practical note.** Real systems rarely ship plain interpolation search,
> because uniformity is hard to guarantee. The common middle ground is a
> **hybrid**: interpolate for the first probe(s), then fall back to binary search
> if the estimate isn't converging — getting the upside on uniform data without
> the `O(n)` cliff on clustered data.

---

## 6. Complexity summary

| measure                       | value                                            |
|-------------------------------|--------------------------------------------------|
| average probes (uniform)      | `O(log log n)`                                   |
| worst case (clustered)        | `O(n)`                                           |
| binary search (any data)      | `O(log n)`                                       |
| space                         | `O(1)` (iterative)                               |
| requirements                  | **sorted** input **and** ~uniform value distribution |

---

## 7. Gold values (pinned, reproducible)

```
Uniform array: [10, 20, ..., 160]
interpolation_search(key=110) -> index 10, path [10], 1 probe
binary_search(key=110)        -> index 10, path [7, 11, 9, 10], 4 probes

Clustered array: [0, 1, ..., 14, 1000000]
interpolation_search(key=14) -> index 14, 15 probes
binary_search(key=14)        -> 4 probes (path [7, 11, 13, 14])
[check] all GOLD values reproduce from the implementations:  OK
```

---

## References

- Peterson, W.W. (1957), "Addressing for random-access storage", *IBM J. Res.
  Dev.* — the original interpolation search idea.
- Knuth, *TAOCP* Vol 3, §6.2.1 / §6.2.2 — the `O(log log n)` average analysis
  for uniform keys, and the `O(n)` worst case.
- Gonnet & Rogers (1991), "An empirical exploration of the average-case analysis
  of interpolation search" — practical probe counts.

> Previous: [`binary_search.html`](./binary_search.html) — the always-`O(log n)`
> baseline that interpolation search tries to beat.
