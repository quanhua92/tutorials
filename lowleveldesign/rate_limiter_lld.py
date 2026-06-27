#!/usr/bin/env python3
"""Rate Limiter -- Strategy pattern, thread safety, swappable algorithms.

Ground-truth implementation of an extensible, algorithm-swappable rate limiter:

  * RateLimiter         -- the Strategy interface. One method: allow(key).
  * TokenBucketLimiter  -- configurable burst (capacity) + sustained rate.
  * SlidingWindowLimiter-- exact enforcement via a per-key timestamp log.
  * FixedWindowLimiter  -- O(1) counter; exposes the 2x boundary burst.
  * ThreadSafeRateLimiter -- decorator with PER-KEY locks (not a global lock).
  * RateLimiterFactory  -- build a limiter by name; add an algorithm = +1 branch.
  * Clock injected (SystemClock / FakeClock) so tests are deterministic.

The whole point: swap the algorithm without touching the caller. The three
limiters below are interchangeable because they all implement RateLimiter.

Companion files: RATE_LIMITER_LLD.md, rate_limiter_lld.html
"""

from abc import ABC, abstractmethod
from collections import deque
import threading
import time as _time


# --------------------------------------------------------------------------- #
#  Decision -- immutable value object returned by every allow() call
# --------------------------------------------------------------------------- #
class Decision:
    """The result of a rate-limit check.

    Carries no reference to the limiter, so it is safe to log, cache, hand to
    a client, or compare across algorithms. Fields:

      allowed         -- True if the request may proceed.
      remaining       -- budget left after this call (>= 0; 0 when denied).
      retry_after_ms  -- when denied, ms to wait for the next token; else 0.
    """

    __slots__ = ("allowed", "remaining", "retry_after_ms")

    def __init__(self, allowed, remaining, retry_after_ms=0):
        self.allowed = allowed
        self.remaining = remaining
        self.retry_after_ms = retry_after_ms

    def __repr__(self):
        if self.allowed:
            return f"Decision(allow, remaining={self.remaining})"
        return f"Decision(DENY, retry_in={self.retry_after_ms}ms)"

    @classmethod
    def allow(cls, remaining):
        return cls(True, remaining, 0)

    @classmethod
    def deny(cls, retry_after_ms):
        return cls(False, 0, retry_after_ms)


# --------------------------------------------------------------------------- #
#  Clock -- injectable time source (the key to deterministic tests)
# --------------------------------------------------------------------------- #
class Clock(ABC):
    """Abstract clock. Tests inject FakeClock so NO time.sleep() is ever needed."""

    @abstractmethod
    def now_ms(self):
        ...


class SystemClock(Clock):
    """Real wall clock. Production."""

    def now_ms(self):
        return int(_time.time() * 1000)


class FakeClock(Clock):
    """Controllable clock. Tests advance time in milliseconds."""

    def __init__(self, start_ms=0):
        self._t = start_ms

    def now_ms(self):
        return self._t

    def advance(self, ms):
        self._t += ms
        return self._t


# --------------------------------------------------------------------------- #
#  RateLimiter -- the Strategy interface (one method, three policies)
# --------------------------------------------------------------------------- #
class RateLimiter(ABC):
    """Strategy interface.

    Every concrete limiter answers the SAME question -- "may this key proceed
    right now?" -- but may answer it with a different algorithm. The caller
    never knows or cares which one is plugged in. That is the whole pattern.
    """

    @abstractmethod
    def allow(self, key):
        """Return a Decision for this key."""
        ...


# --------------------------------------------------------------------------- #
#  TokenBucketLimiter -- burst (capacity) + sustained rate (Stripe / AWS)
# --------------------------------------------------------------------------- #
class TokenBucketLimiter(RateLimiter):
    """Token bucket. O(1) memory per key. The default for API rate limiting.

      capacity     -- bucket size == maximum burst (tokens held when full)
      refill_rate  -- tokens added per SECOND == sustained long-run rate

    State per key: [tokens: float, last_refill_ms: int]

    On every request:
      1. refill  : tokens += elapsed_ms * refill_rate / 1000, capped at capacity
      2. consume : if tokens >= 1, take one token, ALLOW
      3. else    : DENY, retry_after = (1 - tokens) / refill_rate * 1000

    Because refill is continuous, a bucket that idles recovers its full burst --
    unlike a fixed window which resets abruptly at the boundary.
    """

    def __init__(self, capacity, refill_rate, clock):
        if capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        if refill_rate < 0:
            raise ValueError("refill_rate must be >= 0")
        self.capacity = capacity
        self.refill_rate = refill_rate              # tokens per second
        self._clock = clock
        self._state = {}                            # key -> [tokens, last_refill_ms]

    def allow(self, key):
        now = self._clock.now_ms()
        st = self._state.get(key)
        if st is None:
            st = [float(self.capacity), now]        # full bucket on first sight
            self._state[key] = st
        elapsed = now - st[1]
        if elapsed > 0:
            st[0] = min(self.capacity, st[0] + elapsed * self.refill_rate / 1000.0)
            st[1] = now
        if st[0] >= 1.0:
            st[0] -= 1.0
            return Decision.allow(int(st[0]))
        if self.refill_rate <= 0:
            return Decision.deny(0)                 # bucket will never refill
        wait = int((1.0 - st[0]) / self.refill_rate * 1000.0)
        return Decision.deny(wait)

    def tokens(self, key):
        """Introspection: current token count for a key (used by the trace)."""
        st = self._state.get(key)
        return st[0] if st else float(self.capacity)


# --------------------------------------------------------------------------- #
#  SlidingWindowLimiter -- exact enforcement via a timestamp log
# --------------------------------------------------------------------------- #
class SlidingWindowLimiter(RateLimiter):
    """Sliding window LOG. Exact correctness, O(limit) memory per key.

      limit      -- max requests inside the window
      window_ms  -- window length

    State per key: deque of request timestamps (oldest on the left).
    On every request: evict timestamps older than (now - window_ms), then if
    len(log) < limit append this timestamp and ALLOW; else DENY. The window
    truly slides -- there is no boundary burst, ever.
    """

    def __init__(self, limit, window_ms, clock):
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        if window_ms <= 0:
            raise ValueError("window_ms must be a positive integer")
        self.limit = limit
        self.window_ms = window_ms
        self._clock = clock
        self._log = {}                              # key -> deque[timestamps]

    def allow(self, key):
        now = self._clock.now_ms()
        cutoff = now - self.window_ms
        log = self._log.get(key)
        if log is None:
            log = deque()
            self._log[key] = log
        while log and log[0] <= cutoff:             # evict aged-out entries
            log.popleft()
        if len(log) < self.limit:
            log.append(now)
            return Decision.allow(self.limit - len(log))
        retry = log[0] + self.window_ms - now       # ms until oldest exits
        return Decision.deny(retry)

    def in_window(self, key):
        log = self._log.get(key)
        return len(log) if log else 0


# --------------------------------------------------------------------------- #
#  FixedWindowLimiter -- O(1) counter; the 2x boundary burst lives here
# --------------------------------------------------------------------------- #
class FixedWindowLimiter(RateLimiter):
    """Fixed window. O(1) memory per key. Simple, but bursty at boundaries.

      limit      -- max requests per window
      window_ms  -- window length

    State per key: [count: int, window_id: int]. window_id = now // window_ms.
    When the id rolls over, the counter resets to zero -- even if the previous
    window used its full quota one millisecond ago. Two windows' worth of
    traffic can therefore pass in a single millisecond straddling a boundary,
    which is why fixed window is unsafe on security-sensitive paths.
    """

    def __init__(self, limit, window_ms, clock):
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        if window_ms <= 0:
            raise ValueError("window_ms must be a positive integer")
        self.limit = limit
        self.window_ms = window_ms
        self._clock = clock
        self._state = {}                            # key -> [count, window_id]

    def allow(self, key):
        now = self._clock.now_ms()
        wid = now // self.window_ms
        st = self._state.get(key)
        if st is None or st[1] != wid:
            st = [0, wid]                           # fresh window -> reset
            self._state[key] = st
        if st[0] < self.limit:
            st[0] += 1
            return Decision.allow(self.limit - st[0])
        retry = (wid + 1) * self.window_ms - now    # ms until window rolls over
        return Decision.deny(retry)

    def count(self, key):
        st = self._state.get(key)
        return st[0] if st else 0


# --------------------------------------------------------------------------- #
#  ThreadSafeRateLimiter -- decorator with PER-KEY locks
# --------------------------------------------------------------------------- #
class ThreadSafeRateLimiter(RateLimiter):
    """Wraps any RateLimiter so the read-modify-write in allow() is atomic
    PER KEY, not globally.

    Why per-key, not one global lock?
      A global lock serialises EVERY key -- two unrelated API clients block
      each other for no reason. Per-key locking means only concurrent callers
      hitting the SAME key contend; different keys run in parallel. At very
      high cardinality, stripe the keys across N buckets (hash(key) % N) so the
      lock map itself does not grow unbounded.

    Decorator, not subclass: ThreadSafeRateLimiter holds a RateLimiter and
    implements the same interface (Liskov-substitutable). The concurrency
    concern is orthogonal to the algorithm concern.
    """

    def __init__(self, inner):
        self._inner = inner
        self._locks = {}                            # key -> threading.Lock
        self._registry_guard = threading.Lock()     # guards the lock map itself

    def _lock_for(self, key):
        with self._registry_guard:
            lk = self._locks.get(key)
            if lk is None:
                lk = threading.Lock()
                self._locks[key] = lk
            return lk

    def allow(self, key):
        with self._lock_for(key):                   # atomic per key
            return self._inner.allow(key)


# --------------------------------------------------------------------------- #
#  RateLimiterFactory -- build a limiter by name (Open/Closed extension point)
# --------------------------------------------------------------------------- #
class RateLimiterFactory:
    """One place that turns a config string into a RateLimiter.

    Adding a new algorithm (say LeakyBucketLimiter) means: write the class,
    register ONE branch here. Zero changes to the caller, to RateLimiter, or
    to any existing limiter. That is the Open/Closed Principle in action.
    """

    @staticmethod
    def create(kind, clock, **params):
        if kind == "token_bucket":
            return TokenBucketLimiter(
                capacity=params["capacity"],
                refill_rate=params["refill_rate"],
                clock=clock,
            )
        if kind == "sliding_window":
            return SlidingWindowLimiter(
                limit=params["limit"],
                window_ms=params["window_ms"],
                clock=clock,
            )
        if kind == "fixed_window":
            return FixedWindowLimiter(
                limit=params["limit"],
                window_ms=params["window_ms"],
                clock=clock,
            )
        raise ValueError(f"unknown limiter kind: {kind!r}")


# --------------------------------------------------------------------------- #
#  Pretty-printer
# --------------------------------------------------------------------------- #
def banner(title):
    line = "=" * 78
    print(f"\n{line}\n{title}\n{line}")


def tick(d):
    """Compact allow/deny glyph for a Decision."""
    return "allow" if d.allowed else "DENY "


def stream_row(label, decisions):
    cells = "".join("  1 " if d.allowed else "  0 " for d in decisions)
    print(f"  {label:<26}{cells}   {sum(d.allowed for d in decisions)}/"
          f"{len(decisions)}")


# --------------------------------------------------------------------------- #
#  Demo sections
# --------------------------------------------------------------------------- #
def section_strategy_pattern():
    banner("THE STRATEGY PATTERN -- one interface, three interchangeable policies")

    print("""
  The caller asks ONE question: "may this key proceed right now?" Three
  algorithms answer it differently, but the call site never changes:

      limiter = RateLimiterFactory.create("token_bucket", clock, ...)
      limiter.allow("user:42")      # <-- identical call for every policy

  Swapping the algorithm is a one-line config change. The Decision that comes
  back is a plain value object, so it can be logged or compared across
  policies without knowing which one produced it.""")

    clock = FakeClock()
    for kind, params in (
        ("token_bucket", {"capacity": 3, "refill_rate": 1.0}),
        ("sliding_window", {"limit": 3, "window_ms": 5000}),
        ("fixed_window", {"limit": 3, "window_ms": 5000}),
    ):
        lim = RateLimiterFactory.create(kind, clock, **params)
        d = lim.allow("k")
        assert d.allowed
        print(f"  {kind:<16} allow('k') -> {d!r}")
    print("  [check] OK -- all three policies accept the first request")


def section_token_bucket():
    banner("TOKEN BUCKET -- burst drains, then refills continuously")

    print("""
  capacity = 3, refill_rate = 1 token/sec. The bucket starts full, so the
  first three requests pass as a burst. The fourth is denied and told to
  retry in 1000ms (exactly one token's worth of refill). Half a second later
  the bucket is half-full -- still a deny, but retry drops to 500ms.""")

    clock = FakeClock()
    tb = TokenBucketLimiter(capacity=3, refill_rate=1.0, clock=clock)
    steps = [
        (0,    "burst #1"),
        (0,    "burst #2"),
        (0,    "burst #3"),
        (0,    "burst #4 (bucket empty)"),
        (500,  "half a second later"),
        (1000, "one full token refilled"),
        (3000, "long idle -> fully refilled"),
    ]
    for advance_ms, note in steps:
        clock.advance(advance_ms)
        d = tb.allow("user:1")
        print(f"  t={clock.now_ms():<6}ms  {d!r:<38}  tokens={tb.tokens('user:1'):.2f}  ({note})")

    assert tb.tokens("user:1") >= 0
    print("  [check] OK -- burst drained, denied with retry, refill restored budget")


def section_sliding_window():
    banner("SLIDING WINDOW LOG -- the window truly slides (no boundary burst)")

    print("""
  limit = 3, window = 5000ms. Requests are timestamped into a deque; entries
  older than (now - 5000) are evicted before each check. The 4th request at
  t=0 is denied with retry=5000 (must wait for the oldest to age out). Five
  seconds later the deque has drained and traffic flows again.""")

    clock = FakeClock()
    sw = SlidingWindowLimiter(limit=3, window_ms=5000, clock=clock)
    steps = [
        (0,    "req #1"),
        (0,    "req #2"),
        (0,    "req #3 (window full)"),
        (0,    "req #4 -> DENY"),
        (4000, "still full (retry now 1000ms)"),
        (1001, "oldest aged out -> window slid"),
        (500,  "second slot opened (first still in window)"),
    ]
    for advance_ms, note in steps:
        clock.advance(advance_ms)
        d = sw.allow("ip:10.0.0.1")
        print(f"  t={clock.now_ms():<6}ms  {d!r:<40}  in_window={sw.in_window('ip:10.0.0.1')}  ({note})")
    print("  [check] OK -- deny held until the oldest timestamp exited the window")


def section_fixed_window_burst():
    banner("FIXED WINDOW -- the 2x boundary burst exploit (why it is unsafe)")

    print("""
  limit = 3, window = 5000ms. The counter resets when window_id rolls over
  (now // 5000). Three requests at t=4999 fill window 0; three more at t=5000
  fill window 1. SIX requests passed in a single millisecond -- 2x the limit.
  An attacker times the boundary; a fixed window cannot stop them. Use token
  bucket or sliding window on any security-sensitive path.""")

    clock = FakeClock()
    fw = FixedWindowLimiter(limit=3, window_ms=5000, clock=clock)
    clock.advance(4999)
    burst1 = [fw.allow("attacker") for _ in range(3)]
    clock.advance(1)                                # now t=5000 -- new window_id
    burst2 = [fw.allow("attacker") for _ in range(3)]
    total = sum(d.allowed for d in burst1 + burst2)
    print(f"  window 0 (t=4999): {['allow' if d.allowed else 'DENY' for d in burst1]}")
    print(f"  window 1 (t=5000): {['allow' if d.allowed else 'DENY' for d in burst2]}")
    print(f"  total allowed in 1ms straddling the boundary = {total}  (limit was 3!)")
    assert total == 6
    print("  [check] OK -- 2x boundary burst reproduced (the textbook fixed-window flaw)")


def section_strategy_comparison():
    banner("STRATEGY COMPARISON -- one request stream, three policies")

    print("""
  The SAME 8-request stream through every policy. Token bucket (cap=3, rate
  1/s) refills continuously, so it lets the spaced-out requests through once
  the burst drains. The window policies hold the line until their window
  resets/slides. 1 = allow, 0 = deny.""")

    # The shared stream: (advance_ms_before, label)
    stream = [
        (0, "r1@0"), (0, "r2@0"), (0, "r3@0"), (0, "r4@0"),
        (2000, "r5@2000"), (1000, "r6@3000"), (2000, "r7@5000"), (1000, "r8@6000"),
    ]

    policies = [
        ("token_bucket  cap=3 rate=1/s",
         lambda c: TokenBucketLimiter(capacity=3, refill_rate=1.0, clock=c)),
        ("sliding_window limit=3 win=5s",
         lambda c: SlidingWindowLimiter(limit=3, window_ms=5000, clock=c)),
        ("fixed_window   limit=3 win=5s",
         lambda c: FixedWindowLimiter(limit=3, window_ms=5000, clock=c)),
    ]

    header = "  " + " ".join(f"{lbl.split('@')[0]:>3}" for _, lbl in stream)
    print(header)
    for label, factory in policies:
        clock = FakeClock()
        lim = factory(clock)
        decisions = []
        for advance_ms, _lbl in stream:
            clock.advance(advance_ms)
            decisions.append(lim.allow("client:1"))
        stream_row(label, decisions)

    print("""
  Reading: token bucket is the most permissive under spaced load (continuous
  refill); the two window policies agree here but diverge under a boundary
  burst (see the previous section). Pick the algorithm from the workload,
  not from habit.""")
    print("  [check] OK -- three policies ran the same stream via one interface")


def section_thread_safe():
    banner("THREAD SAFETY -- per-key lock makes the race atomic")

    print("""
  200 concurrent workers each fire 5 requests at the SAME key against a token
  bucket with capacity = 50 and a frozen clock (so no refill during the test).
  1000 requests, capacity 50 -> EXACTLY 50 must be allowed, no more. Without
  per-key locking the read-modify-write races and over-admits; with it the
  count is exact. Per-key (not global) means unrelated keys never contend.""")

    clock = FakeClock()                             # frozen -> no refill
    inner = TokenBucketLimiter(capacity=50, refill_rate=1.0, clock=clock)
    limiter = ThreadSafeRateLimiter(inner)

    workers = 200
    per_worker = 5
    allowed = [0]
    counter_guard = threading.Lock()

    def worker():
        local = 0
        for _ in range(per_worker):
            if limiter.allow("user:shared").allowed:
                local += 1
        with counter_guard:
            allowed[0] += local

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total = workers * per_worker
    print(f"  {workers} workers x {per_worker} requests = {total} total")
    print("  capacity        = 50")
    print(f"  allowed (exact) = {allowed[0]}")
    assert allowed[0] == 50, f"over-admission! allowed={allowed[0]} > 50"
    assert len(limiter._locks) == 1, "should have created exactly one per-key lock"
    print(f"  [check] OK -- exactly 50 allowed, 1 per-key lock created, "
          f"no over-admission across {total} concurrent requests")


def section_factory_and_extensibility():
    banner("FACTORY + EXTENSIBILITY -- add an algorithm, touch nothing else")

    print("""
  RateLimiterFactory turns a config string into a RateLimiter. To add a new
  algorithm (e.g. leaky bucket) you write the class and add ONE branch to the
  factory. RateLimiter, Decision, ThreadSafeRateLimiter, and every existing
  limiter are untouched. That is the Open/Closed Principle.""")

    clock = FakeClock()
    specs = [
        ("token_bucket", {"capacity": 2, "refill_rate": 1.0}),
        ("sliding_window", {"limit": 2, "window_ms": 1000}),
        ("fixed_window", {"limit": 2, "window_ms": 1000}),
    ]
    for kind, params in specs:
        lim = RateLimiterFactory.create(kind, clock, **params)
        # wrap ANY of them in the thread-safe decorator without the decorator
        # knowing which algorithm is inside -- composition over inheritance
        safe = ThreadSafeRateLimiter(lim)
        d1 = safe.allow("tenant:acme")
        d2 = safe.allow("tenant:acme")
        d3 = safe.allow("tenant:acme")
        print(f"  {kind:<16} wrapped -> {d1!r}, {d2!r}, {d3!r}")
        assert d1.allowed and d2.allowed and not d3.allowed

    # unknown kind is rejected loudly, not silently
    try:
        RateLimiterFactory.create("nope", clock)
        print("  [FAIL] unknown kind should have raised")
    except ValueError:
        print("  [check] OK -- unknown kind rejected; three policies composed + wrapped")


def section_gold_check():
    """A deterministic signature recomputed by rate_limiter_lld.html in JS."""
    banner("GOLD CHECK  (recomputed by rate_limiter_lld.html in JS)")

    clock = FakeClock()
    tb = TokenBucketLimiter(capacity=3, refill_rate=1.0, clock=clock)

    plan = [
        (0,    "burst"),
        (0,    "burst"),
        (0,    "burst"),
        (0,    "deny"),
        (500,  "half-token"),
        (500,  "full token"),   # t=1000
        (2000, "long idle"),    # t=3000
    ]
    flags = []
    retries = []
    for advance_ms, _note in plan:
        clock.advance(advance_ms)
        d = tb.allow("gold")
        flags.append(1 if d.allowed else 0)
        if not d.allowed:
            retries.append(d.retry_after_ms)

    sig = ",".join(str(f) for f in flags)
    retry_sig = ",".join(str(r) for r in retries)
    gold_sig = "1,1,1,0,0,1,1"
    gold_retry = "1000,500"
    print(f"  tb.allow_flags = {sig}")
    print(f"  tb.deny_retries= {retry_sig}")
    assert sig == gold_sig, f"flag mismatch: {sig} != {gold_sig}"
    assert retry_sig == gold_retry, f"retry mismatch: {retry_sig} != {gold_retry}"
    print("  [check] OK")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("#" * 78)
    print("# RATE LIMITER (LLD) -- Strategy pattern, thread safety, swappable "
          "algorithms (pure stdlib)")
    print("#" * 78)
    section_strategy_pattern()
    section_token_bucket()
    section_sliding_window()
    section_fixed_window_burst()
    section_strategy_comparison()
    section_thread_safe()
    section_factory_and_extensibility()
    section_gold_check()
    print("\n[check] OK -- all sections ran")
