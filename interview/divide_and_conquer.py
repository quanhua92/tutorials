"""Divide & Conquer — ground-truth implementations.

Three problems covering the canonical D&C templates:

  1. Merge sort (split → recurse → merge)         → P912 Sort an Array
  2. Boyer-Moore majority voting                  → P169 Majority Element
  3. D&C merge of k sorted lists                  → P023 Merge k Sorted Lists

Every number printed below is produced by running this file; nothing is
hand-computed.  Capture with:

    python3 divide_and_conquer.py > divide_and_conquer_output.txt 2>/dev/null
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Shared helper: two-pointer merge of two already-sorted lists — the heart of
# every divide-and-conquer sorting/merging algorithm.  O(a + b).
# ---------------------------------------------------------------------------

def merge_two(a: list[int], b: list[int]) -> list[int]:
    """Merge two sorted lists into one sorted list (stable, two-pointer)."""
    result: list[int] = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            result.append(a[i])
            i += 1
        else:
            result.append(b[j])
            j += 1
    result.extend(a[i:])
    result.extend(b[j:])
    return result


# ---------------------------------------------------------------------------
# Variant 1 — P912 Sort an Array (merge sort, the canonical D&C algorithm)
# ---------------------------------------------------------------------------

def merge_sort(nums: list[int]) -> list[int]:
    """Sort an array using merge sort (divide & conquer). O(n log n), O(n)."""
    if len(nums) <= 1:
        return nums[:]
    mid = len(nums) // 2
    left = merge_sort(nums[:mid])
    right = merge_sort(nums[mid:])
    return merge_two(left, right)


def merge_sort_traced(nums: list[int], depth: int = 0) -> list[int]:
    """Traced merge sort: prints the split tree and each two-pointer merge."""
    pad = "  " * depth
    if len(nums) <= 1:
        print(f"{pad}base   {nums} -> already sorted")
        return nums[:]
    mid = len(nums) // 2
    left_in, right_in = nums[:mid], nums[mid:]
    print(f"{pad}split  {nums}  mid={mid}  -> {left_in} | {right_in}")
    left = merge_sort_traced(left_in, depth + 1)
    right = merge_sort_traced(right_in, depth + 1)
    merged = merge_two(left, right)
    print(f"{pad}merge  {left} + {right} -> {merged}")
    return merged


# ---------------------------------------------------------------------------
# Variant 2 — P169 Majority Element (Boyer-Moore voting, O(n) time O(1) space)
# ---------------------------------------------------------------------------

def majority_element(nums: list[int]) -> int:
    """Find the majority element (> n/2 occurrences). Boyer-Moore voting."""
    candidate: int = nums[0]
    count: int = 1
    for num in nums[1:]:
        if count == 0:
            candidate = num
            count = 1
        elif num == candidate:
            count += 1
        else:
            count -= 1
    return candidate


def majority_element_traced(nums: list[int]) -> int:
    """Traced Boyer-Moore: prints candidate / count as each element is scanned."""
    candidate: int = nums[0]
    count: int = 1
    print(f"  {'i':>2}  {'num':>4}  {'action':<26}  {'candidate':>9}  {'count':>5}")
    print("  " + "-" * 58)
    print(f"  {0:>2}  {nums[0]:>4}  {'start':<26}  {candidate:>9}  {count:>5}")
    for i, num in enumerate(nums[1:], start=1):
        if count == 0:
            candidate = num
            count = 1
            action = "count == 0 -> new candidate"
        elif num == candidate:
            count += 1
            action = "same -> count++"
        else:
            count -= 1
            action = "diff -> count--"
        print(f"  {i:>2}  {num:>4}  {action:<26}  {candidate:>9}  {count:>5}")
    return candidate


# ---------------------------------------------------------------------------
# Variant 3 — P023 Merge k Sorted Lists (D&C on the list-of-lists array)
# ---------------------------------------------------------------------------

def merge_k_sorted_lists(lists: list[list[int]]) -> list[int]:
    """Merge k sorted lists into one via divide & conquer. O(n log k)."""
    if not lists:
        return []
    if len(lists) == 1:
        return lists[0][:]
    mid = len(lists) // 2
    left = merge_k_sorted_lists(lists[:mid])
    right = merge_k_sorted_lists(lists[mid:])
    return merge_two(left, right)


def merge_k_sorted_lists_traced(lists: list[list[int]], depth: int = 0) -> list[int]:
    """Traced D&C merge: prints the splits of the list-of-lists and each merge."""
    pad = "  " * depth
    if not lists:
        print(f"{pad}empty -> []")
        return []
    if len(lists) == 1:
        print(f"{pad}single {lists[0]} -> {lists[0][:]}")
        return lists[0][:]
    mid = len(lists) // 2
    left_in, right_in = lists[:mid], lists[mid:]
    print(f"{pad}split  k={len(lists)} mid={mid} -> left={left_in} | right={right_in}")
    left = merge_k_sorted_lists_traced(left_in, depth + 1)
    right = merge_k_sorted_lists_traced(right_in, depth + 1)
    merged = merge_two(left, right)
    print(f"{pad}merge  {left} + {right} -> {merged}")
    return merged


# ---------------------------------------------------------------------------
# Section drivers
# ---------------------------------------------------------------------------

def section_merge_sort() -> None:
    print("=" * 72)
    print("=== P912 Sort an Array — merge sort (split -> recurse -> merge)")
    print("=" * 72)
    nums = [5, 2, 3, 1, 6, 4]
    print(f"  input = {nums}\n")
    res = merge_sort_traced(nums)
    assert res == [1, 2, 3, 4, 5, 6], f"expected sorted, got {res}"
    print(f"\n  >> merge_sort({nums}) = {res}   [check] OK")

    r2 = merge_sort([38, 27, 43, 3, 9, 82, 10])
    assert r2 == [3, 9, 10, 27, 38, 43, 82], r2
    print(f"  >> merge_sort([38, 27, 43, 3, 9, 82, 10]) = {r2}   [check] OK")


def section_majority() -> None:
    print()
    print("=" * 72)
    print("=== P169 Majority Element — Boyer-Moore voting")
    print("=" * 72)
    nums = [2, 2, 1, 1, 1, 2, 2]
    print(f"  input = {nums}   (n = {len(nums)}, majority appears > {len(nums)//2} times)\n")
    res = majority_element_traced(nums)
    assert res == 2, f"expected 2, got {res}"
    print(f"\n  >> majority_element({nums}) = {res}   [check] OK")

    r2 = majority_element([3, 2, 3])
    assert r2 == 3, r2
    print(f"  >> majority_element([3, 2, 3]) = {r2}   [check] OK")


def section_merge_k() -> None:
    print()
    print("=" * 72)
    print("=== P023 Merge k Sorted Lists — D&C on the list-of-lists")
    print("=" * 72)
    lists = [[1, 4, 5], [1, 3, 4], [2, 6]]
    print(f"  input = {lists}   (k = {len(lists)} lists)\n")
    res = merge_k_sorted_lists_traced(lists)
    assert res == [1, 1, 2, 3, 4, 4, 5, 6], f"got {res}"
    print(f"\n  >> merge_k_sorted_lists({lists}) = {res}   [check] OK")

    r2 = merge_k_sorted_lists([[1, 2, 3], [4, 5, 6, 7]])
    assert r2 == [1, 2, 3, 4, 5, 6, 7], r2
    print(f"  >> merge_k_sorted_lists([[1, 2, 3], [4, 5, 6, 7]]) = {r2}   [check] OK")


if __name__ == "__main__":
    section_merge_sort()
    section_majority()
    section_merge_k()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
