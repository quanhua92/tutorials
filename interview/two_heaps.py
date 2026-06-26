"""Two Heaps — ground-truth implementations.

Three problems covering the two-heap family:

  1. Running median of a stream            -> P295 Find Median from Data Stream
  2. Median of every sliding window        -> P480 Sliding Window Median
  3. K-way merge of tweet timelines        -> P355 Design Twitter

Every number printed below is produced by running this file; nothing is
hand-computed.  Capture with:

    python3 two_heaps.py > two_heaps_output.txt 2>/dev/null

The shared building block: Python's ``heapq`` is a *min*-heap, so every
"max-heap" in this file is simulated by **negating the values**. That single
trick is what makes both halves of the median structure, and the newest-first
tweet ordering, fall out of the same library.
"""

from __future__ import annotations

import collections
import heapq
import itertools


# ---------------------------------------------------------------------------
# Helpers — pretty-print a heap as its values (peek-first)
# ---------------------------------------------------------------------------

def _small_values_mf(mf) -> list:
    return sorted([-v for v in mf.small], reverse=True) if mf.small else []


def _large_values_mf(mf) -> list:
    return sorted(mf.large) if mf.large else []


def _fmt(values: list) -> str:
    return "[" + ", ".join(str(v) for v in values) + "]" if values else "[]"


# ===========================================================================
# Variant 1 — P295 Find Median from Data Stream
# ===========================================================================

class MedianFinder:
    """P295: maintain a running median via two balanced heaps.

    - ``small`` is a **max-heap** (negated) holding the smaller half.
    - ``large`` is a **min-heap** holding the larger half.

    Invariant: ``len(small) == len(large)`` (even total) or
    ``len(small) == len(large) + 1`` (odd total).  The canonical 3-step
    insert — *push to small, move top to large, rebalance if large grew* —
    enforces it automatically, with no ``if`` on the incoming value.
    """

    def __init__(self) -> None:
        self.small: list[int] = []  # max-heap (negated values)
        self.large: list[int] = []  # min-heap
        self.last_op: dict | None = None  # observational trace, see _record

    def add_num(self, num: int) -> None:
        heapq.heappush(self.small, -num)            # 1. always enter via small
        moved = -heapq.heappop(self.small)          # 2. funnel top of small up
        heapq.heappush(self.large, moved)
        rebalanced = None
        if len(self.large) > len(self.small):       # 3. large overgrew: pay back
            rebalanced = heapq.heappop(self.large)
            heapq.heappush(self.small, -rebalanced)
        self.last_op = {"added": num, "moved": moved, "rebalanced": rebalanced}

    def find_median(self) -> float:
        if len(self.small) > len(self.large):
            return float(-self.small[0])
        return (-self.small[0] + self.large[0]) / 2.0


def section_p295() -> None:
    print("=" * 72)
    print("=== P295 Find Median from Data Stream — running median")
    print("=" * 72)
    stream = [1, 5, 2, 8, 3]
    print(f"  stream = {stream}")
    print()
    print("  add  moved(small->large)  rebalance?            small       "
          "large       median")
    print("  " + "-" * 68)
    mf = MedianFinder()
    medians: list[float] = []
    for x in stream:
        mf.add_num(x)
        medians.append(mf.find_median())
        op = mf.last_op
        reb = ("yes: %d large->small" % op["rebalanced"]
               if op["rebalanced"] is not None else "no")
        sm = _fmt(_small_values_mf(mf))
        lg = _fmt(_large_values_mf(mf))
        print(f"  {x:>3}  {op['moved']:>17}    {reb:<20}  {sm:<10}  "
              f"{lg:<10}  {mf.find_median():>5}")
    print(f"\n  >> running medians = {[float(m) for m in medians]}")
    assert medians == [1.0, 3.0, 2.0, 3.5, 3.0], medians
    print(f"  >> median_finder([1,5,2,8,3]) = {medians}   [check] OK")

    # LeetCode sample: addNum(1), addNum(2), findMedian -> 1.5, addNum(3),
    # findMedian -> 2.0
    mf2 = MedianFinder()
    mf2.add_num(1)
    mf2.add_num(2)
    assert mf2.find_median() == 1.5, mf2.find_median()
    mf2.add_num(3)
    assert mf2.find_median() == 2.0, mf2.find_median()
    print(f"  >> [1] -> [1,2] -> median 1.5;  +3 -> median 2.0   [check] OK")


# ===========================================================================
# Variant 2 — P480 Sliding Window Median (lazy deletion)
# ===========================================================================

class _DualHeap:
    """Two balanced heaps with **lazy deletion** — the P480 engine.

    Python's ``heapq`` has no O(log n) arbitrary delete, so when a value
    leaves the sliding window we do NOT hunt it down.  We record its value in
    ``delayed`` and decrement the *logical* size counter; the stale entry is
    popped off the top only when it surfaces.  Because the median only ever
    reads the **tops**, pruning just the tops is enough.

    Keyed by **value** (not ``(val, idx)``): the median is a property of the
    *multiset*, so we never need to know *which* copy expired — only that one
    fewer copy of that value is logically present.  This sidesteps the
    "is this 3 in small or large?" ambiguity that breaks index-keyed
    classifiers whenever the boundary value is duplicated.
    """

    def __init__(self) -> None:
        self.small: list[int] = []   # max-heap: stores -val
        self.large: list[int] = []   # min-heap: stores val
        self.delayed: collections.Counter = collections.Counter()
        self.ssz = 0  # logical size of small (lower half)
        self.lsz = 0  # logical size of large (upper half)

    def _prune(self, heap: list[int]) -> None:
        is_small = heap is self.small
        while heap:
            val = -heap[0] if is_small else heap[0]
            if self.delayed[val] > 0:
                self.delayed[val] -= 1
                if self.delayed[val] == 0:
                    del self.delayed[val]
                heapq.heappop(heap)
            else:
                break

    def _rebalance(self) -> None:
        if self.ssz > self.lsz + 1:                # small too fat -> large
            v = -heapq.heappop(self.small)
            heapq.heappush(self.large, v)
            self.ssz -= 1
            self.lsz += 1
            self._prune(self.small)
        elif self.lsz > self.ssz:                  # large too fat -> small
            v = heapq.heappop(self.large)
            heapq.heappush(self.small, -v)
            self.lsz -= 1
            self.ssz += 1
            self._prune(self.large)

    def add(self, val: int) -> None:
        if not self.small or val <= -self.small[0]:
            heapq.heappush(self.small, -val)
            self.ssz += 1
        else:
            heapq.heappush(self.large, val)
            self.lsz += 1
        self._prune(self.small)
        self._prune(self.large)
        self._rebalance()

    def remove(self, val: int) -> None:
        # decide logically which half it lived in, WITHOUT searching the heap
        if self.small and val <= -self.small[0]:
            self.ssz -= 1
        else:
            self.lsz -= 1
        self.delayed[val] += 1
        self._prune(self.small)
        self._prune(self.large)
        self._rebalance()

    def median(self, k: int) -> float:
        if k % 2 == 1:
            return float(-self.small[0])
        return (-self.small[0] + self.large[0]) / 2.0


def median_sliding_window(nums: list[int], k: int) -> list[float]:
    """P480: median of each sliding window of size *k*."""
    if not nums or k <= 0 or k > len(nums):
        return []
    dh = _DualHeap()
    out: list[float] = []
    for i, v in enumerate(nums):
        dh.add(v)
        if i >= k:
            dh.remove(nums[i - k])
        if i >= k - 1:
            out.append(dh.median(k))
    return out


def median_sliding_window_traced(nums: list[int], k: int) -> list[dict]:
    """Traced version: one snapshot per emitted median.

    The ``small``/``large`` columns show the *logical* split of the window
    (lower half vs upper half) derived from the size counters — identical to
    what the heaps hold once every lazy deletion has surfaced.
    """
    dh = _DualHeap()
    snaps: list[dict] = []
    for i, v in enumerate(nums):
        dh.add(v)
        removed = None
        if i >= k:
            removed = nums[i - k]
            dh.remove(nums[i - k])
        if i >= k - 1:
            window_sorted = sorted(nums[i - k + 1:i + 1])
            small_disp = list(reversed(window_sorted[:dh.ssz]))  # max first
            large_disp = window_sorted[dh.ssz:dh.ssz + dh.lsz]   # min first
            snaps.append({
                "i": i,
                "window": nums[i - k + 1:i + 1],
                "added": v,
                "removed": removed,
                "small": small_disp,
                "large": large_disp,
                "median": dh.median(k),
            })
    return snaps


def section_p480() -> None:
    print()
    print("=" * 72)
    print("=== P480 Sliding Window Median — lazy deletion + rebalancing")
    print("=" * 72)
    nums = [1, 3, -1, -3, 5, 3, 6, 7]
    k = 3
    snaps = median_sliding_window_traced(nums, k)
    print(f"  nums = {nums}   k = {k}")
    print()
    print("  win  window          added  removed  small        "
          "large        median")
    print("  " + "-" * 68)
    for s in snaps:
        win = "%d:%d" % (s["i"] - k + 1, s["i"])
        rm = "-" if s["removed"] is None else str(s["removed"])
        print(f"  {win:>4}  {_fmt(s['window']):<14}  {s['added']:>5}  "
              f"{rm:>7}  {_fmt(s['small']):<11}  {_fmt(s['large']):<11}  "
              f"{s['median']:>5}")
    result = median_sliding_window(nums, k)
    print(f"\n  >> medianSlidingWindow({nums}, {k})")
    print(f"     = {result}")
    assert result == [1.0, -1.0, -1.0, 3.0, 5.0, 6.0], result
    print(f"  >> expected [1.0, -1.0, -1.0, 3.0, 5.0, 6.0]   [check] OK")

    # Even k + duplicates + negatives regression
    r2 = median_sliding_window([1, 2, 3, 4, 2, 3, 1, 4, 1], 3)
    assert r2 == [2.0, 3.0, 3.0, 3.0, 2.0, 3.0, 1.0], r2
    r3 = median_sliding_window([1, 4, 2, 3], 4)
    assert r3 == [2.5], r3
    print(f"  >> window([1,2,3,4,2,3,1,4,1], 3) = {r2}   [check] OK")
    print(f"  >> window([1,4,2,3], 4) = {r3}   [check] OK")


# ===========================================================================
# Variant 3 — P355 Design Twitter (negate timestamp -> max-heap merge)
# ===========================================================================

class Twitter:
    """P355: simplified Twitter.

    The two-heap building block (negate a value to flip a min-heap into a
    max-heap) reappears here for the news feed.  Each followee's timeline is
    already newest-last in a list; we seed a min-heap with each followee's
    NEWEST tweet keyed by ``(-time, ...)`` so the globally-newest tweet is on
    top.  Popping it and re-pushing that followee's NEXT-newest yields a
    k-way merge of sorted lists in O(k log F) for F followees.
    """

    def __init__(self) -> None:
        self._timer = itertools.count(step=1)
        self.tweets: dict[int, list[tuple[int, int]]] = (
            collections.defaultdict(list))
        self.following: dict[int, set[int]] = collections.defaultdict(set)

    def post_tweet(self, user_id: int, tweet_id: int) -> None:
        self.tweets[user_id].append((next(self._timer), tweet_id))

    def follow(self, follower_id: int, followee_id: int) -> None:
        self.following[follower_id].add(followee_id)

    def unfollow(self, follower_id: int, followee_id: int) -> None:
        self.following[follower_id].discard(followee_id)

    def get_news_feed(self, user_id: int) -> list[int]:
        followees = self.following[user_id] | {user_id}
        heap: list[tuple[int, int, int, int]] = []  # (-time, tid, uid, idx)
        for uid in followees:
            tl = self.tweets[uid]
            if tl:
                t, tid = tl[-1]
                heapq.heappush(heap, (-t, tid, uid, len(tl) - 1))
        feed: list[int] = []
        while heap and len(feed) < 10:
            _, tid, uid, idx = heapq.heappop(heap)
            feed.append(tid)
            if idx > 0:
                t2, tid2 = self.tweets[uid][idx - 1]
                heapq.heappush(heap, (-t2, tid2, uid, idx - 1))
        return feed

    # ---- traced get_news_feed (returns feed + list of ops) ----
    def get_news_feed_traced(self, user_id: int) -> tuple[list[int], list[dict]]:
        followees = self.following[user_id] | {user_id}
        heap: list[tuple[int, int, int, int]] = []
        seed_desc: list[str] = []
        for uid in followees:
            tl = self.tweets[uid]
            if tl:
                t, tid = tl[-1]
                heapq.heappush(heap, (-t, tid, uid, len(tl) - 1))
                seed_desc.append("user%d newest = (t=%d, id=%d)"
                                 % (uid, t, tid))
        feed: list[int] = []
        ops: list[dict] = [{"phase": "seed", "heap_top": (
            -heap[0][0], heap[0][1], heap[0][2]) if heap else None,
            "note": "seed heap = " + ", ".join(seed_desc)}]
        while heap and len(feed) < 10:
            nt, tid, uid, idx = heapq.heappop(heap)
            feed.append(tid)
            op = {"phase": "pop", "popped": (tid, -nt, uid)}
            if idx > 0:
                t2, tid2 = self.tweets[uid][idx - 1]
                heapq.heappush(heap, (-t2, tid2, uid, idx - 1))
                op["pushed"] = (tid2, t2, uid)
                op["note"] = ("emit id=%d (t=%d, user%d); push next user%d "
                              "id=%d (t=%d)" % (tid, -nt, uid, uid, tid2, t2))
            else:
                op["note"] = ("emit id=%d (t=%d, user%d); timeline exhausted"
                              % (tid, -nt, uid))
            ops.append(op)
        return feed, ops


def section_p355() -> None:
    print()
    print("=" * 72)
    print("=== P355 Design Twitter — negated-timestamp max-heap merge")
    print("=" * 72)
    tw = Twitter()
    # user 1 posts an interleaved timeline; user 2 a separate one
    for tid in (5, 3, 1):
        tw.post_tweet(1, tid)            # times 1,2,3 -> [(1,5),(2,3),(3,1)]
    for tid in (10, 7):
        tw.post_tweet(2, tid)            # times 4,5   -> [(4,10),(5,7)]
    tw.follow(1, 2)
    print("  user1 tweets (id, time): " +
          ", ".join("id=%d t=%d" % (t, i) for i, t in tw.tweets[1][::-1]))
    print("  user2 tweets (id, time): " +
          ", ".join("id=%d t=%d" % (t, i) for i, t in tw.tweets[2][::-1]))
    print("  user1 follows user2")
    print()
    feed, ops = tw.get_news_feed_traced(1)
    print("  step  action")
    print("  " + "-" * 68)
    for n, op in enumerate(ops):
        print(f"  {n:>3}  {op['note']}")
    print(f"\n  >> getNewsFeed(1) = {feed}")
    assert feed == [7, 10, 1, 3, 5], feed
    print(f"  >> expected [7, 10, 1, 3, 5]   [check] OK")

    # LeetCode P355 driver
    tw2 = Twitter()
    tw2.post_tweet(1, 5)
    assert tw2.get_news_feed(1) == [5]
    tw2.follow(1, 2)
    tw2.post_tweet(2, 6)
    assert tw2.get_news_feed(1) == [6, 5]
    tw2.unfollow(1, 2)
    assert tw2.get_news_feed(1) == [5]
    print(f"  >> LeetCode driver: [5] / [6,5] / [5]   [check] OK")


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    section_p295()
    section_p480()
    section_p355()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
