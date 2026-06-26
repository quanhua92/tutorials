"""Binary Search — ground-truth implementations.

Four problems covering the three core templates:

  1. Standard binary search (exact match)      → P704 Binary Search
  2. Rotated array minimum (predicate search)  → P153 Find Minimum in Rotated Sorted Array
  3. Binary search on answer (minimize value)  → P875 Koko Eating Bananas
  4. Binary search on answer (minimize value)  → P410 Split Array Largest Sum

Every number printed below is produced by running this file; nothing is
hand-computed.  Capture with:

    python3 binary_search.py > binary_search_output.txt 2>/dev/null
"""

from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Variant 1 — Standard binary search (exact match)
# ---------------------------------------------------------------------------

def search(nums: list[int], target: int) -> int:
    """P704: Classic binary search on a sorted (ascending) array.

    Template A: ``while lo <= hi`` with ``lo = mid + 1`` / ``hi = mid - 1``.
    Each comparison discards half the remaining search space, so the whole
    scan is O(log n).
    """
    lo, hi = 0, len(nums) - 1
    while lo <= hi:
        mid = lo + (hi - lo) // 2
        if nums[mid] == target:
            return mid
        elif nums[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1


def search_traced(nums: list[int], target: int) -> int:
    """Traced version: logs lo/mid/hi each iteration."""
    lo, hi = 0, len(nums) - 1
    step = 0
    print(f"  array = {nums}   target = {target}")
    print(f"  {'step':>4}  {'lo':>2}  {'hi':>2}  {'mid':>3}  {'nums[mid]':>9}  action")
    print("  " + "-" * 66)
    while lo <= hi:
        step += 1
        mid = lo + (hi - lo) // 2
        if nums[mid] == target:
            print(f"  {step:>4}  {lo:>2}  {hi:>2}  {mid:>3}  {nums[mid]:>9}"
                  f"  nums[mid] == target → FOUND at index {mid}")
            return mid
        elif nums[mid] < target:
            print(f"  {step:>4}  {lo:>2}  {hi:>2}  {mid:>3}  {nums[mid]:>9}"
                  f"  nums[mid] < target → lo = mid + 1 = {mid + 1}")
            lo = mid + 1
        else:
            print(f"  {step:>4}  {lo:>2}  {hi:>2}  {mid:>3}  {nums[mid]:>9}"
                  f"  nums[mid] > target → hi = mid - 1 = {mid - 1}")
            hi = mid - 1
    print(f"  {step + 1:>4}  {lo:>2}  {hi:>2}  {'—':>3}  {'—':>9}  lo > hi → NOT FOUND")
    return -1


# ---------------------------------------------------------------------------
# Variant 2 — Rotated array minimum (predicate search)
# ---------------------------------------------------------------------------

def find_min_rotated(nums: list[int]) -> int:
    """P153: Find the minimum element in a rotated sorted array (unique values).

    Template B: ``while lo < hi`` with ``hi = mid``. The predicate is
    ``nums[mid] > nums[right]`` — if true, the pivot (minimum) lies strictly
    to the right of ``mid``; otherwise it lies at or to the left of ``mid``.
    """
    lo, hi = 0, len(nums) - 1
    while lo < hi:
        mid = lo + (hi - lo) // 2
        if nums[mid] > nums[hi]:
            lo = mid + 1
        else:
            hi = mid
    return nums[lo]


def find_min_rotated_traced(nums: list[int]) -> int:
    """Traced version: logs lo/mid/hi and the pivot decision each step."""
    lo, hi = 0, len(nums) - 1
    step = 0
    print(f"  array = {nums}")
    print(f"  {'step':>4}  {'lo':>2}  {'hi':>2}  {'mid':>3}  {'nums[mid]':>9}"
          f"  {'nums[hi]':>8}  action")
    print("  " + "-" * 72)
    while lo < hi:
        step += 1
        mid = lo + (hi - lo) // 2
        if nums[mid] > nums[hi]:
            print(f"  {step:>4}  {lo:>2}  {hi:>2}  {mid:>3}  {nums[mid]:>9}"
                  f"  {nums[hi]:>8}  nums[mid] > nums[hi] → lo = mid + 1 = {mid + 1}")
            lo = mid + 1
        else:
            print(f"  {step:>4}  {lo:>2}  {hi:>2}  {mid:>3}  {nums[mid]:>9}"
                  f"  {nums[hi]:>8}  nums[mid] ≤ nums[hi] → hi = mid = {mid}")
            hi = mid
    print(f"  {step + 1:>4}  {lo:>2}  {hi:>2}  {'—':>3}  {'—':>9}  {'—':>8}"
          f"  lo == hi → min = nums[{lo}] = {nums[lo]}")
    return nums[lo]


# ---------------------------------------------------------------------------
# Variant 3 — Binary search on answer (minimize the feasible value)
# ---------------------------------------------------------------------------

def can_eat_all(piles: list[int], speed: int, h: int) -> bool:
    """Feasibility predicate for P875: can Koko finish in ≤ h hours at *speed*?"""
    return sum(math.ceil(p / speed) for p in piles) <= h


def min_eating_speed(piles: list[int], h: int) -> int:
    """P875: Minimum integer eating speed to finish all piles within *h* hours.

    Answer space ``[1, max(piles)]`` is monotonic: a higher speed never costs
    more hours, so once *speed* is feasible every larger speed is too. We
    search for the leftmost (smallest) feasible speed.
    """
    lo, hi = 1, max(piles)
    while lo < hi:
        mid = lo + (hi - lo) // 2
        if can_eat_all(piles, mid, h):
            hi = mid
        else:
            lo = mid + 1
    return lo


def min_eating_speed_traced(piles: list[int], h: int) -> int:
    """Traced version: logs each candidate speed, its hour cost, and the move."""
    lo, hi = 1, max(piles)
    step = 0
    print(f"  piles = {piles}   h = {h}")
    print(f"  answer range: speed ∈ [1, {hi}]   (max pile = {hi})")
    print(f"  {'step':>4}  {'lo':>2}  {'hi':>2}  {'mid':>3}  {'hours(mid)':>10}"
          f"  {'≤ h?':>4}  action")
    print("  " + "-" * 66)
    while lo < hi:
        step += 1
        mid = lo + (hi - lo) // 2
        cost = sum(math.ceil(p / mid) for p in piles)
        feasible = cost <= h
        if feasible:
            print(f"  {step:>4}  {lo:>2}  {hi:>2}  {mid:>3}  {cost:>10}"
                  f"  {'yes':>4}  feasible → hi = mid = {mid}")
            hi = mid
        else:
            print(f"  {step:>4}  {lo:>2}  {hi:>2}  {mid:>3}  {cost:>10}"
                  f"  {'no':>4}  too slow → lo = mid + 1 = {mid + 1}")
            lo = mid + 1
    print(f"  {step + 1:>4}  {lo:>2}  {hi:>2}  {'—':>3}  {'—':>10}"
          f"  {'—':>4}  lo == hi → min speed = {lo}")
    return lo


# ---------------------------------------------------------------------------
# Variant 4 — Binary search on answer (split array, minimize largest sum)
# ---------------------------------------------------------------------------

def count_splits(nums: list[int], cap: int) -> int:
    """Greedy feasibility for P410: minimum subarrays whose sum each ≤ *cap*."""
    splits = 1
    cur = 0
    for x in nums:
        if cur + x > cap:
            splits += 1
            cur = x
        else:
            cur += x
    return splits


def split_array(nums: list[int], m: int) -> int:
    """P410: Split *nums* into *m* contiguous subarrays minimizing the largest sum.

    Answer space ``[max(nums), sum(nums)]`` is monotonic: a larger capacity
    never needs more subarrays. We search for the smallest capacity that still
    fits into ≤ m subarrays.
    """
    lo, hi = max(nums), sum(nums)
    while lo < hi:
        mid = lo + (hi - lo) // 2
        if count_splits(nums, mid) <= m:
            hi = mid
        else:
            lo = mid + 1
    return lo


def split_array_traced(nums: list[int], m: int) -> int:
    """Traced version: logs each candidate capacity, its split count, and the move."""
    lo, hi = max(nums), sum(nums)
    step = 0
    print(f"  nums = {nums}   m = {m}")
    print(f"  answer range: capacity ∈ [{lo}, {hi}]   (max = {lo}, sum = {hi})")
    print(f"  {'step':>4}  {'lo':>2}  {'hi':>2}  {'mid':>3}  {'splits(mid)':>11}"
          f"  {'≤ m?':>4}  action")
    print("  " + "-" * 66)
    while lo < hi:
        step += 1
        mid = lo + (hi - lo) // 2
        need = count_splits(nums, mid)
        feasible = need <= m
        if feasible:
            print(f"  {step:>4}  {lo:>2}  {hi:>2}  {mid:>3}  {need:>11}"
                  f"  {'yes':>4}  feasible → hi = mid = {mid}")
            hi = mid
        else:
            print(f"  {step:>4}  {lo:>2}  {hi:>2}  {mid:>3}  {need:>11}"
                  f"  {'no':>4}  too many → lo = mid + 1 = {mid + 1}")
            lo = mid + 1
    print(f"  {step + 1:>4}  {lo:>2}  {hi:>2}  {'—':>3}  {'—':>11}"
          f"  {'—':>4}  lo == hi → min largest sum = {lo}")
    return lo


# ---------------------------------------------------------------------------
# Section drivers
# ---------------------------------------------------------------------------

def section_search() -> None:
    print("=" * 72)
    print("=== P704 Binary Search — standard exact-match search")
    print("=" * 72)
    nums = [-1, 0, 3, 5, 9, 12]
    res = search_traced(nums, 9)
    assert res == 4, f"expected 4, got {res}"
    print(f"\n  >> search({nums}, 9) = {res}   [check] OK")

    r2 = search(nums, 2)
    assert r2 == -1, r2
    print(f"  >> search({nums}, 2) = {r2}   [check] OK")


def section_find_min_rotated() -> None:
    print()
    print("=" * 72)
    print("=== P153 Find Minimum in Rotated Sorted Array — predicate search")
    print("=" * 72)
    nums = [3, 4, 5, 1, 2]
    res = find_min_rotated_traced(nums)
    assert res == 1, f"expected 1, got {res}"
    print(f"\n  >> find_min_rotated({nums}) = {res}   [check] OK")

    r2 = find_min_rotated([11, 13, 15, 17])
    assert r2 == 11, r2
    print(f"  >> find_min_rotated([11, 13, 15, 17]) = {r2}   [check] OK")


def section_koko() -> None:
    print()
    print("=" * 72)
    print("=== P875 Koko Eating Bananas — binary search on answer (speed)")
    print("=" * 72)
    piles = [3, 6, 7, 11]
    res = min_eating_speed_traced(piles, 8)
    assert res == 4, f"expected 4, got {res}"
    print(f"\n  >> min_eating_speed({piles}, 8) = {res}   [check] OK")

    r2 = min_eating_speed([30, 11, 23, 4, 20], 5)
    assert r2 == 30, r2
    print(f"  >> min_eating_speed([30, 11, 23, 4, 20], 5) = {r2}   [check] OK")


def section_split_array() -> None:
    print()
    print("=" * 72)
    print("=== P410 Split Array Largest Sum — binary search on answer (capacity)")
    print("=" * 72)
    nums = [7, 2, 5, 10, 8]
    res = split_array_traced(nums, 2)
    assert res == 18, f"expected 18, got {res}"
    print(f"\n  >> split_array({nums}, 2) = {res}   [check] OK")

    r2 = split_array([1, 2, 3, 4, 5], 2)
    assert r2 == 9, r2
    print(f"  >> split_array([1, 2, 3, 4, 5], 2) = {r2}   [check] OK")


if __name__ == "__main__":
    section_search()
    section_find_min_rotated()
    section_koko()
    section_split_array()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
