"""Top-K Elements — ground-truth implementations.

Three problems covering the canonical bounded-heap template:

  1. Kth largest in an array  (min-heap of size k)    -> P215
  2. Top K frequent elements  (Counter + min-heap k)  -> P347
  3. K closest points         (max-heap via negation) -> P973

The unifying idea: keep a heap capped at size *k* that **evicts the element you
do NOT want**.  For the k *largest* you keep a **min-heap** (root = weakest of
the top-k, easiest to kick out).  For the k *closest/smallest* you keep a
**max-heap** (negate the key in Python) so the root = farthest, again easiest to
kick out.

Every number printed below is produced by running this file; nothing is
hand-computed.  Capture with:

    python3 top_k_elements.py > top_k_elements_output.txt 2>/dev/null
"""

from __future__ import annotations

import heapq
from collections import Counter


# ---------------------------------------------------------------------------
# Variant 1 — P215 Kth Largest Element in an Array (min-heap of size k)
# ---------------------------------------------------------------------------

def kth_largest(nums: list[int], k: int) -> int:
    """k-th largest via a min-heap of size k.  O(n log k) time, O(k) space."""
    if k < 1 or k > len(nums):
        raise ValueError(f"k={k} out of bounds for len={len(nums)}")
    min_heap: list[int] = []
    for num in nums:
        heapq.heappush(min_heap, num)
        if len(min_heap) > k:
            heapq.heappop(min_heap)          # evict the smallest of the top-k
    return min_heap[0]                       # root = k-th largest


def kth_largest_traced(nums: list[int], k: int) -> int:
    """Traced: prints the heap state after every push / evict."""
    min_heap: list[int] = []
    print(f"  goal: keep the {k} largest; the heap root is the {k}-th largest element\n")
    hdr = f"  {'i':>2}  {'num':>4}  {'action':<26}  {'heap (cap k)':<16}  evicted"
    print(hdr)
    print("  " + "-" * 70)
    for i, num in enumerate(nums):
        heapq.heappush(min_heap, num)
        action = f"push {num}"
        evicted = "-"
        if len(min_heap) > k:
            ev = heapq.heappop(min_heap)
            action = f"push {num} -> over k"
            evicted = f"pop {ev} (smallest)"
        print(f"  {i:>2}  {num:>4}  {action:<26}  {str(min_heap):<16}  {evicted}")
    print(f"\n  heap = {min_heap}   root = heap[0] = {min_heap[0]}  (k-th largest)")
    return min_heap[0]


# ---------------------------------------------------------------------------
# Variant 2 — P347 Top K Frequent Elements (Counter + bounded min-heap)
# ---------------------------------------------------------------------------

def top_k_frequent(nums: list[int], k: int) -> list[int]:
    """k most frequent via Counter + min-heap of size k on (freq, item)."""
    count: Counter = Counter(nums)
    min_heap: list[tuple[int, int]] = []     # (freq, item)
    for item, freq in count.items():
        heapq.heappush(min_heap, (freq, item))
        if len(min_heap) > k:
            heapq.heappop(min_heap)          # evict the least-frequent kept
    return [item for _, item in min_heap]


def top_k_frequent_traced(nums: list[int], k: int) -> list[int]:
    """Traced: prints the frequency map then the bounded-heap evolution."""
    count = Counter(nums)
    print(f"  frequencies: {dict(count)}\n")
    min_heap: list[tuple[int, int]] = []
    hdr = f"  {'item':>4}  {'freq':>4}  {'action':<22}  {'heap (freq,item)':<24}  evicted"
    print(hdr)
    print("  " + "-" * 72)
    for item, freq in count.items():
        heapq.heappush(min_heap, (freq, item))
        action = f"push ({freq},{item})"
        evicted = "-"
        if len(min_heap) > k:
            ef, ei = heapq.heappop(min_heap)
            action = f"push -> over k"
            evicted = f"pop ({ef},{ei}) least freq"
        print(f"  {item:>4}  {freq:>4}  {action:<22}  {str(min_heap):<24}  {evicted}")
    result = [item for _, item in min_heap]
    print(f"\n  heap = {min_heap}   result items = {sorted(result)}")
    return result


# ---------------------------------------------------------------------------
# Variant 3 — P973 K Closest Points to Origin (max-heap via negated distance)
# ---------------------------------------------------------------------------

def k_closest_points(points: list[list[int]], k: int) -> list[list[int]]:
    """k closest via a max-heap (negated squared distance) of size k.

    We store ``(-dist_sq, idx)`` so the min-heap root is the *most negative*
    (farthest) point — popping it evicts the farthest, keeping the k closest.
    Squared distance avoids the sqrt: the order is identical.
    """
    max_heap: list[tuple[int, int]] = []     # (-dist_sq, idx)
    for idx, (x, y) in enumerate(points):
        dist_sq = x * x + y * y
        heapq.heappush(max_heap, (-dist_sq, idx))
        if len(max_heap) > k:
            heapq.heappop(max_heap)          # evict the farthest kept
    return [points[idx] for _, idx in max_heap]


def _fmt_max_heap(heap, points):
    """Render a (-dist, idx) heap as a readable list of (d2, point)."""
    return "[" + ", ".join(f"({-nd},{points[idx]})" for nd, idx in heap) + "]"


def k_closest_points_traced(points: list[list[int]], k: int) -> list[list[int]]:
    """Traced: prints each point's d-squared and the size-k max-heap state."""
    print(f"  goal: keep the {k} closest; root = farthest kept (first evicted)\n")
    max_heap: list[tuple[int, int]] = []
    hdr = f"  {'i':>2}  {'point':>8}  {'d²':>4}  {'action':<20}  {'heap (d²,point)':<26}  evicted"
    print(hdr)
    print("  " + "-" * 78)
    for i, (x, y) in enumerate(points):
        d2 = x * x + y * y
        heapq.heappush(max_heap, (-d2, i))
        action = f"push {d2}"
        evicted = "-"
        if len(max_heap) > k:
            ed, ei = heapq.heappop(max_heap)
            action = f"push -> over k"
            evicted = f"pop {-ed} {points[ei]} (farthest)"
        disp = _fmt_max_heap(max_heap, points)
        print(f"  {i:>2}  [{x},{y}]{'':<4}  {d2:>4}  {action:<20}  {disp:<26}  {evicted}")
    result = sorted(
        (points[idx] for _, idx in max_heap),
        key=lambda p: p[0] * p[0] + p[1] * p[1],
    )
    print(f"\n  heap = {_fmt_max_heap(max_heap, points)}   closest = {result}")
    return result


# ---------------------------------------------------------------------------
# Section drivers
# ---------------------------------------------------------------------------

def section_kth_largest() -> None:
    print("=" * 72)
    print("=== P215 Kth Largest Element — min-heap of size k")
    print("=" * 72)
    nums = [3, 2, 1, 5, 6, 4]
    k = 2
    print(f"  input = {nums}, k = {k}  (want the 2nd-largest element)\n")
    res = kth_largest_traced(nums, k)
    assert res == 5, f"expected 5, got {res}"
    print(f"\n  >> kth_largest({nums}, {k}) = {res}   [check] OK")

    r2 = kth_largest([3, 2, 3, 1, 2, 4, 5, 5, 6], 4)
    assert r2 == 4, r2
    print(f"  >> kth_largest([3, 2, 3, 1, 2, 4, 5, 5, 6], 4) = {r2}   [check] OK")


def section_top_k_frequent() -> None:
    print()
    print("=" * 72)
    print("=== P347 Top K Frequent Elements — Counter + min-heap of size k")
    print("=" * 72)
    nums = [1, 1, 1, 2, 2, 3]
    k = 2
    print(f"  input = {nums}, k = {k}  (want the 2 most frequent)\n")
    res = top_k_frequent_traced(nums, k)
    assert sorted(res) == [1, 2], f"expected [1, 2], got {res}"
    print(f"\n  >> top_k_frequent({nums}, {k}) = {sorted(res)}   [check] OK")

    r2 = top_k_frequent([1], 1)
    assert r2 == [1], r2
    print(f"  >> top_k_frequent([1], 1) = {r2}   [check] OK")


def section_k_closest() -> None:
    print()
    print("=" * 72)
    print("=== P973 K Closest Points to Origin — max-heap (negated distance)")
    print("=" * 72)
    points = [[3, 3], [5, -1], [-2, 4]]
    k = 2
    print(f"  input = {points}, k = {k}  (want the 2 closest to origin)\n")
    res = k_closest_points_traced(points, k)
    assert res == [[3, 3], [-2, 4]], f"expected [[3,3],[-2,4]], got {res}"
    print(f"\n  >> k_closest_points({points}, {k}) = {res}   [check] OK")

    r2 = k_closest_points([[1, 3], [-2, 2]], 1)
    assert sorted(r2, key=lambda p: p[0] ** 2 + p[1] ** 2) == [[-2, 2]], r2
    print(f"  >> k_closest_points([[1, 3], [-2, 2]], 1) = {r2}   [check] OK")


if __name__ == "__main__":
    section_kth_largest()
    section_top_k_frequent()
    section_k_closest()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
