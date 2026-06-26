"""Two Pointers pattern — ground-truth implementations.

Three variants, three problems:

  1. Opposite-end converging pointers  → P167 Two Sum II — Input Array Is Sorted
  2. Greedy area (move the shorter side) → P011 Container With Most Water
  3. Nested two pointers (outer fix)     → P015 3Sum

Every number printed below is produced by running this file; nothing is
hand-computed.  Capture with:

    python3 two_pointers.py > two_pointers_output.txt 2>/dev/null
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Variant 1 — Opposite-end converging pointers
# ---------------------------------------------------------------------------

def two_sum_ii(numbers: list[int], target: int) -> list[int]:
    """P167: Two Sum II on a 1-indexed sorted array.

    Invariant: every pair outside ``[left, right]`` has been eliminated.
    Each step removes exactly one candidate, so the whole scan is O(n).
    """
    left, right = 0, len(numbers) - 1
    while left < right:
        current = numbers[left] + numbers[right]
        if current == target:
            return [left + 1, right + 1]          # 1-indexed
        if current < target:
            left += 1
        else:
            right -= 1
    return []


def two_sum_ii_traced(numbers: list[int], target: int) -> list[int]:
    """Same logic as two_sum_ii but prints each pointer move."""
    left, right = 0, len(numbers) - 1
    step = 0
    print(f"  array = {numbers}   target = {target}")
    print(f"  {'step':>4}  {'L':>2}  {'R':>2}  {'num[L]':>6}  {'num[R]':>6}"
          f"  {'sum':>5}  {'action':<16}  eliminated")
    print("  " + "-" * 78)
    while left < right:
        step += 1
        cur = numbers[left] + numbers[right]
        if cur == target:
            print(f"  {step:>4}  {left:>2}  {right:>2}  {numbers[left]:>6}"
                  f"  {numbers[right]:>6}  {cur:>5}  {'MATCH':<16}"
                  f"  → indices [{left + 1}, {right + 1}]")
            return [left + 1, right + 1]
        if cur < target:
            print(f"  {step:>4}  {left:>2}  {right:>2}  {numbers[left]:>6}"
                  f"  {numbers[right]:>6}  {cur:>5}  {'L += 1 (too small)':<16}"
                  f"  col({left}) ⊗ all col(>{left})")
            left += 1
        else:
            print(f"  {step:>4}  {left:>2}  {right:>2}  {numbers[left]:>6}"
                  f"  {numbers[right]:>6}  {cur:>5}  {'R -= 1 (too big)':<16}"
                  f"  col({right}) ⊗ all col(<{right})")
            right -= 1
    return []


# ---------------------------------------------------------------------------
# Variant 2 — Greedy area (move the shorter side)
# ---------------------------------------------------------------------------

def max_area(height: list[int]) -> int:
    """P011: Container With Most Water.

    Area = min(h[L], h[R]) * (R - L).  Width always shrinks, so the only
    chance to beat the current best is to move the SHORTER pointer inward —
    a taller partner could offset the lost width.  Moving the taller side
    can never help: width drops and the height is still capped by the
    shorter line.  This is a proof, not a heuristic.
    """
    left, right = 0, len(height) - 1
    best = 0
    while left < right:
        h = min(height[left], height[right])
        w = right - left
        area = h * w
        if area > best:
            best = area
        if height[left] < height[right]:
            left += 1
        else:
            right -= 1
    return best


def max_area_traced(height: list[int]) -> int:
    """Traced version: logs area, best, and the elimination reason."""
    left, right = 0, len(height) - 1
    best = 0
    step = 0
    print(f"  array = {height}")
    print(f"  {'step':>4}  {'L':>2}  {'R':>2}  {'hL':>3}  {'hR':>3}"
          f"  {'h':>3}  {'w':>2}  {'area':>5}  {'best':>5}  move")
    print("  " + "-" * 70)
    while left < right:
        step += 1
        h = min(height[left], height[right])
        w = right - left
        area = h * w
        if area > best:
            best = area
        if height[left] < height[right]:
            move = f"L += 1 (hL shorter)"
            print(f"  {step:>4}  {left:>2}  {right:>2}  {height[left]:>3}"
                  f"  {height[right]:>3}  {h:>3}  {w:>2}  {area:>5}  {best:>5}  {move}")
            left += 1
        else:
            move = f"R -= 1 (hR shorter)"
            print(f"  {step:>4}  {left:>2}  {right:>2}  {height[left]:>3}"
                  f"  {height[right]:>3}  {h:>3}  {w:>2}  {area:>5}  {best:>5}  {move}")
            right -= 1
    print(f"\n  >> max_area = {best}")
    return best


# ---------------------------------------------------------------------------
# Variant 3 — Nested two pointers (outer fix + inner converging)
# ---------------------------------------------------------------------------

def three_sum(nums: list[int]) -> list[list[int]]:
    """P015: 3Sum — all unique triplets summing to 0.

    Sort, fix index ``i``, run converging two pointers on ``i+1..n-1`` for
    target ``-nums[i]``.  Three-level deduplication keeps triplets unique.
    Time O(n^2), space O(1) extra (ignoring the output).
    """
    nums = sorted(nums)
    n = len(nums)
    out: list[list[int]] = []
    for i in range(n - 2):
        if i > 0 and nums[i] == nums[i - 1]:       # dedup outer
            continue
        left, right = i + 1, n - 1
        while left < right:
            total = nums[i] + nums[left] + nums[right]
            if total == 0:
                out.append([nums[i], nums[left], nums[right]])
                left += 1
                right -= 1
                while left < right and nums[left] == nums[left - 1]:    # dedup L
                    left += 1
                while left < right and nums[right] == nums[right + 1]:  # dedup R
                    right -= 1
            elif total < 0:
                left += 1
            else:
                right -= 1
    return out


def three_sum_traced(nums: list[int]) -> list[list[int]]:
    """Traced version: logs the outer fix and every inner move."""
    nums = sorted(nums)
    n = len(nums)
    out: list[list[int]] = []
    print(f"  sorted = {nums}")
    for i in range(n - 2):
        if i > 0 and nums[i] == nums[i - 1]:
            print(f"  i={i} nums[i]={nums[i]} (dup of i-1, skip)")
            continue
        target = -nums[i]
        print(f"\n  fix i={i} nums[i]={nums[i]}  inner target = {target}")
        left, right = i + 1, n - 1
        while left < right:
            total = nums[i] + nums[left] + nums[right]
            if total == 0:
                tri = [nums[i], nums[left], nums[right]]
                out.append(tri)
                print(f"      L={left} R={right} → triplet {tri}  (record)")
                left += 1
                right -= 1
                while left < right and nums[left] == nums[left - 1]:
                    print(f"      skip dup L={left} val={nums[left]}")
                    left += 1
                while left < right and nums[right] == nums[right + 1]:
                    print(f"      skip dup R={right} val={nums[right]}")
                    right -= 1
            elif total < 0:
                print(f"      L={left} R={right} sum={total} < 0  → L += 1")
                left += 1
            else:
                print(f"      L={left} R={right} sum={total} > 0  → R -= 1")
                right -= 1
    print(f"\n  >> triplets = {out}")
    return out


# ---------------------------------------------------------------------------
# Section drivers
# ---------------------------------------------------------------------------

def section_two_sum_ii() -> None:
    print("=" * 72)
    print("=== P167 Two Sum II — opposite-end converging pointers")
    print("=" * 72)
    nums = [2, 7, 11, 15]
    res = two_sum_ii_traced(nums, 9)
    assert res == [1, 2], f"expected [1, 2], got {res}"
    print(f"\n  >> two_sum_ii({nums}, 9) = {res}   [check] OK")

    # extra case from LeetCode
    r2 = two_sum_ii([2, 3, 4], 6)
    assert r2 == [1, 3], r2
    print(f"  >> two_sum_ii([2, 3, 4], 6) = {r2}   [check] OK")


def section_max_area() -> None:
    print()
    print("=" * 72)
    print("=== P011 Container With Most Water — greedy area")
    print("=" * 72)
    height = [1, 8, 6, 2, 5, 4, 8, 3, 7]
    res = max_area_traced(height)
    assert res == 49, f"expected 49, got {res}"
    print(f"  [check] max_area == 49 OK")

    r2 = max_area([1, 1])
    assert r2 == 1, r2
    print(f"  >> max_area([1, 1]) = {r2}   [check] OK")


def section_three_sum() -> None:
    print()
    print("=" * 72)
    print("=== P015 3Sum — nested two pointers + 3-level dedup")
    print("=" * 72)
    nums = [-1, 0, 1, 2, -1, -4]
    res = three_sum_traced(nums)
    expected = [[-1, -1, 2], [-1, 0, 1]]
    assert res == expected, f"expected {expected}, got {res}"
    print(f"  [check] three_sum == {expected} OK")

    r2 = three_sum([0, 0, 0, 0])
    assert r2 == [[0, 0, 0]], r2
    print(f"  >> three_sum([0,0,0,0]) = {r2}   [check] OK")


if __name__ == "__main__":
    section_two_sum_ii()
    section_max_area()
    section_three_sum()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
