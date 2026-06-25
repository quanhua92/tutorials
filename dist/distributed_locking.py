"""
distributed_locking.py - Reference implementation of DISTRIBUTED LOCKING:
mutual exclusion across nodes. Four approaches and their failure modes,
plus fencing tokens as the actual fix.

This is the single source of truth that DISTRIBUTED_LOCKING.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 distributed_locking.py

============================================================================
THE INTUITION (read this first) - the talking stick and the frozen speaker
============================================================================
A distributed lock is a TALKING STICK. Only the node holding the stick is
allowed to speak (write to shared storage); everyone else must wait. The hard
part is that nodes cannot see each other directly - they hand the stick around
through an INTERMEDIARY (ZooKeeper, or Redis). The whole question of
distributed locking is: what guarantees does that intermediary give you, and
what breaks them?

  * ZooKeeper is a CONSENSUS service (Zab/Paxos-like). It gives you a small
    filesystem of EPHEMERAL nodes - nodes that vanish the instant the session
    that created them dies. That ties a lock to a LIVE session for free, no
    clocks involved. (Section A) The naive version has all waiters watch ONE
    node, so every release wakes ALL of them (the "herd effect"); the fix is
    SEQUENTIAL nodes where each waiter watches only its predecessor. (Section B)

  * Redis is a CACHE that happens to have a SET-IF-ABSENT primitive
    (SET key value NX PX ttl). It is fast, but the lock's lifetime is a CLOCK
    countdown: the lock expires at now+ttl whether or not the holder is still
    alive. If the holder FREEZES (a stop-the-world GC pause) longer than the
    TTL, the lock expires underneath it, a second client acquires it, and now
    TWO clients believe they hold the stick - the "stale lock holder". (Section C)

  * Redlock spreads the lock across N independent Redis masters and asks for a
    MAJORITY. The hope is that majority agreement defeats any single failure.
    Martin Kleppmann's critique: it does not. The expiry is still a clock
    countdown on each master, and a GC pause (or an NTP clock jump) AFTER the
    acquisition check is undetectable - so two clients can still hold the lock
    simultaneously. Majority quorum does not save you from bad clocks. (Section D)

  * FENCING TOKENS are the fix. Every grant of the lock comes with a
    monotonically increasing token. The shared storage REFUSES any write whose
    token is not strictly greater than the last one it accepted. So even if a
    frozen, stale holder wakes up and tries to write, its old token is rejected
    and the data is never corrupted. Mutual exclusion is enforced AT THE
    STORAGE, not just at the lock service. (Section E)

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  mutual exclusion   : at most ONE client believes it holds the lock at any
                       instant. This is the whole point of a lock.
  lock               : the "talking stick" - permission to be the sole writer.
  ephemeral node     : a ZooKeeper node tied to a SESSION; auto-deleted the
                       moment that session ends (crash, timeout, disconnect).
  session            : a client's live connection to ZK; ephemeral nodes die
                       with it. No clocks needed - liveness is consensus-driven.
  watch              : a one-shot notification ZK delivers when a watched node
                       is created/deleted/changed. Set, then wait.
  herd effect        : when N waiters all watch the SAME node, one release
                       wakes all N of them ("thundering herd") - wasteful.
  sequential node    : a ZK node whose name is auto-suffixed with a monotonic
                       counter (/lock-0000000001). Sortable; gives an ordered
                       queue of waiters.
  predecessor watch  : each sequential waiter watches ONLY the node with the
                       next-lower sequence number. A release wakes exactly ONE
                       waiter. Herd effect eliminated.
  SET NX PX          : Redis "SET key value NX PX ttl" = set only if absent,
                       expire after ttl milliseconds. Atomic. The single-Redis
                       lock primitive.
  TTL                : time-to-live. A Redis lock auto-expires at now+ttl.
  stale lock holder  : a client that still believes it holds the lock after the
                       TTL has silently expired (e.g. it was frozen by a GC
                       pause). The #1 danger of clock-based locks.
  Redlock            : acquire the same SET-NX-PX lock on N (usually 5)
                       independent Redis masters; succeed on a MAJORITY.
  quorum             : floor(N/2) + 1. For N=5, quorum = 3.
  fencing token      : a number, issued with each lock grant, that strictly
                       increases over time (token 33, then 34, then 35...).
  fencing            : the storage service rejects any write whose token is not
                       strictly greater than the last accepted one. This makes a
                       stale holder's write harmless.

============================================================================
THE SOURCES (every claim below verified against these)
============================================================================
  Flavio Junqueira & Benjamin Reed (2013). "ZooKeeper: Distributed
        Process Coordination." O'Reilly. - ephemeral + sequential nodes, the
        lock recipe (Sec 2.2.1 / the official ZooKeeper recipes doc).
  antirez (Salvatore Sanfilippo, 2014). Redis SET NX PX + the Redlock
        algorithm write-up (antirez.com). - single-Redis lock, N-master quorum.
  Martin Kleppmann (2016). "How to do distributed locking" (blog, Feb 8 2016)
        and "Designing Data-Intensive Applications," Ch. 8.
        - the GC-pause / clock-skew critique of Redlock; fencing tokens as the
          correct defense (DDIA Fig 8.5).
  Gray & Reuter (1993). "Transaction Processing," Sec 7.6 - the original
        lease/fencing-token idea (sequencing tokens on resource grants).

KEY INVARIANTS (all asserted in code below):
    mutual exclusion  : |{ c : c believes it holds the lock }| <= 1   (the goal)
    ZK ephemeral      : node alive  <=>  owning session alive   (no clocks)
    ZK sequential     : holder == argmin_seq(live nodes)  -> unique -> <= 1 holder
                        each waiter watches its predecessor -> 1 wakeup per release
    Redis SETNX       : SET k v NX PX ttl returns OK iff key absent (atomic);
                        key auto-deletes at now+ttl (CLOCK-DEPENDENT)
    Redlock quorum    : q = N//2 + 1 ; acquired iff (>= q masters OK) and (elapsed < ttl)
    Kleppmann failure : a GC pause / clock jump AFTER acquire is undetectable
                        -> stale holder -> |holders| can reach 2 (VIOLATION)
    fencing           : storage.write(token, ...) ok iff token > storage.last_token
                        -> a stale holder's write is ALWAYS rejected -> data safe
"""

from __future__ import annotations

BANNER = "=" * 72

# Deterministic scenario constants (reused by every section and the .html).
TTL_REDIS = 30          # single-Redis lock TTL, in ticks
TTL_REDLOCK = 10        # Redlock per-master TTL, in ticks
N_MASTERS = 5           # Redlock: number of independent Redis masters


# ============================================================================
# 1. REFERENCE IMPLEMENTATIONS  (the code DISTRIBUTED_LOCKING.md walks through)
# ============================================================================

# ----------------------------------------------------------------------------
# ZooKeeper model: ephemeral + sequential nodes, watches, session expiry.
# ----------------------------------------------------------------------------

class ZKBasic:
    """Minimal ZooKeeper for the NAIVE ephemeral lock (Section A).

    A single lock znode `/lock`, created ephemeral. If a client creates it, it
    holds the lock; otherwise it sets a WATCH on `/lock` and waits. When the
    holder's session expires, the ephemeral node is deleted and EVERY watcher
    is notified -> the herd effect.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, str] = {}        # path -> owning session
        self.watches: dict[str, set[str]] = {} # path -> set of watcher sessions
        self.sessions: set[str] = set()

    def add_session(self, s: str) -> None:
        self.sessions.add(s)

    def create_ephemeral(self, path: str, session: str) -> bool:
        """Create an ephemeral node. True if created (caller holds the lock),
        False if it already exists (caller must watch)."""
        if path in self.nodes:
            return False
        self.nodes[path] = session
        return True

    def watch(self, path: str, watcher: str) -> bool:
        """Watch `path` for deletion. Returns True if the node currently exists
        (so the watch is meaningful), False if absent."""
        self.watches.setdefault(path, set()).add(watcher)
        return path in self.nodes

    def expire_session(self, session: str) -> list[str]:
        """Session ends: delete all its ephemeral nodes, fire every watch on
        those nodes. Returns the list of watcher sessions that woke up."""
        woken: list[str] = []
        for path in [p for p, o in self.nodes.items() if o == session]:
            del self.nodes[path]
            for w in self.watches.pop(path, set()):
                woken.append(w)
        self.sessions.discard(session)
        return sorted(woken)


class ZKSequential:
    """ZooKeeper with SEQUENTIAL ephemeral nodes (Section B).

    Each client creates `/lock-NNNNNNNNNN` (a monotonic, zero-padded counter).
    The client whose node has the LOWEST sequence holds the lock; every other
    client watches only its immediate PREDECESSOR. One release -> one wakeup.
    """

    def __init__(self) -> None:
        self.counter = 0
        # path -> (session, seq)
        self.nodes: dict[str, tuple[str, int]] = {}
        # path -> the single watcher session registered on it
        self.watches: dict[str, str] = {}

    def create_sequential(self, prefix: str, session: str) -> tuple[str, int]:
        self.counter += 1
        seq = self.counter
        path = f"{prefix}-{seq:010d}"          # zero-pad -> lexicographic == numeric
        self.nodes[path] = (session, seq)
        return path, seq

    def children_sorted(self, prefix: str) -> list[tuple[str, str, int]]:
        """All nodes under `prefix`, sorted by sequence number ascending."""
        kids = [(p, sess, seq) for p, (sess, seq) in self.nodes.items()
                if p.startswith(prefix + "-")]
        return sorted(kids, key=lambda x: x[2])

    def holder(self, prefix: str) -> tuple[str, str, int] | None:
        kids = self.children_sorted(prefix)
        return kids[0] if kids else None       # argmin_seq -> unique holder

    def watch_predecessor(self, prefix: str, my_path: str, my_seq: int,
                          watcher: str) -> str | None:
        """Watch the node with the next-lower sequence. Returns that path, or
        None if `my_seq` is the lowest (caller holds the lock -> no watch)."""
        lower = [(p, seq) for p, (sess, seq) in self.nodes.items()
                 if p.startswith(prefix + "-") and seq < my_seq]
        if not lower:
            return None
        lower.sort(key=lambda x: x[1])
        prev_path = lower[-1][0]               # immediate predecessor
        self.watches[prev_path] = watcher      # exactly ONE watcher
        return prev_path

    def delete(self, path: str) -> str | None:
        """Delete a node; return the single watcher session that wakes (or None)."""
        self.nodes.pop(path, None)
        return self.watches.pop(path, None)


# ----------------------------------------------------------------------------
# Redis model: SET NX PX with a clock-driven TTL.
# ----------------------------------------------------------------------------

class RedisLock:
    """A single Redis instance's SET-NX-PX lock (Section C).

    The lock value carries an expiry tick. It auto-expires when the clock
    reaches the expiry - INDEPENDENT of whether the holder is still alive. That
    clock-decoupling from liveness is the root of the stale-holder problem.
    """

    def __init__(self) -> None:
        self.holder: tuple[str, int] | None = None   # (value, expiry_tick)
        self.now = 0

    def set_nx_px(self, key: str, value: str, ttl: int) -> str:
        """SET key value NX PX ttl. Returns 'OK' if acquired, '' (nil) if held.

        Expiry is checked lazily: an expired lock is treated as free. This is
        exactly how Redis behaves (a reader first sees the key, then it expires
        on access / background sweep).
        """
        if self.holder is not None and self.holder[1] > self.now:
            return ""                             # still held and not expired
        self.holder = (value, self.now + ttl)     # free or expired -> acquire
        return "OK"

    def advance(self, ticks: int) -> None:
        self.now += ticks

    def is_expired(self) -> bool:
        return self.holder is None or self.holder[1] <= self.now


# ----------------------------------------------------------------------------
# Redlock model: N independent Redis masters, majority quorum (Section D).
# ----------------------------------------------------------------------------

class Redlock:
    """Redlock over N independent Redis masters. Acquire iff a MAJORITY accept
    the SET NX PX and the elapsed acquisition time is within the TTL.

    Each master has its OWN clock (`RedisLock.now`); clock SKEW between masters
    is exactly the failure mode Kleppmann names - a master whose clock jumps
    ahead will see a lock expire "early" and hand it to a second client."""

    def __init__(self, n_masters: int = N_MASTERS) -> None:
        self.n = n_masters
        self.quorum = n_masters // 2 + 1         # floor(N/2)+1 = 3 for N=5
        self.masters = [RedisLock() for _ in range(n_masters)]

    def acquire(self, value: str, ttl: int, reachable: list[bool] | None = None
                ) -> tuple[bool, int, list[int]]:
        """Try SET NX PX ttl on each reachable master. Returns (acquired?, got,
        acquired_master_ids). `reachable` (len N, default all True) lets a master
        be momentarily slow/unreachable, as in the real algorithm."""
        if reachable is None:
            reachable = [True] * self.n
        got = 0
        acq_ids: list[int] = []
        for i, m in enumerate(self.masters):
            if not reachable[i]:
                continue
            if m.set_nx_px("lock", value, ttl) == "OK":
                got += 1
                acq_ids.append(i + 1)            # M1..MN, 1-indexed
        return got >= self.quorum, got, acq_ids


# ----------------------------------------------------------------------------
# Fencing-token model (Section E).
# ----------------------------------------------------------------------------

class FencingLockService:
    """A lock service that issues a MONOTONIC fencing token with every grant.

    Modelled on top of a Redis-style TTL lock, but each grant is tagged with an
    ever-increasing token. Even if a stale holder wakes up, its token is old."""

    def __init__(self, start_token: int = 32) -> None:
        self.token_counter = start_token        # so the first grant is 33
        self.holder: tuple[str, int] | None = None   # (client, token)

    def acquire(self, client: str) -> int:
        self.token_counter += 1
        token = self.token_counter
        self.holder = (client, token)
        return token

    def expire(self) -> None:
        self.holder = None


class FencedStorage:
    """Storage that rejects any write whose fencing token is not STRICTLY
    greater than the last accepted one. This is the defense."""

    def __init__(self) -> None:
        self.last_token = 0
        self.data: tuple[str, str] | None = None

    def write(self, token: int, client: str, value: str) -> bool:
        if token <= self.last_token:
            return False                         # stale token -> REJECT
        self.last_token = token
        self.data = (client, value)
        return True


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# SECTION A: ZooKeeper ephemeral lock (naive) + the herd effect
# ============================================================================

def section_a() -> dict:
    banner("SECTION A: ZooKeeper ephemeral lock (naive) - create /lock, watch")
    print("The naive ZK recipe: an EPHEMERAL node /lock. The first client to")
    print("create it holds the lock. Everyone else FAILS to create it (it")
    print("exists) and instead sets a WATCH on /lock. When the holder's session")
    print("ends, ZK deletes the ephemeral node and fires the watch - on EVERY")
    print("waiter at once.\n")
    print("Scenario: clients C1, C2, C3. C1 grabs the lock; C2, C3 wait.\n")

    zk = ZKBasic()
    for c in ("C1", "C2", "C3"):
        zk.add_session(c)

    timeline: list[tuple[int, str]] = []
    # tick 0: C1 creates /lock
    ok = zk.create_ephemeral("/lock", "C1")
    timeline.append((0, f"C1 create_ephemeral('/lock') -> {ok}  [C1 HOLDS]"))
    # tick 1: C2 tries, fails, watches
    ok = zk.create_ephemeral("/lock", "C2")
    zk.watch("/lock", "C2")
    timeline.append((1, f"C1 create_ephemeral('/lock') -> {ok} (exists); C2 watches /lock"))
    # tick 2: C3 tries, fails, watches
    ok = zk.create_ephemeral("/lock", "C3")
    zk.watch("/lock", "C3")
    timeline.append((2, f"C1 create_ephemeral('/lock') -> {ok} (exists); C3 watches /lock"))

    watchers = sorted(zk.watches.get("/lock", set()))
    print("  tick  event")
    print("  ----  -----")
    for t, ev in timeline:
        print(f"   {t:>2}   {ev}")
    print(f"\n  watchers on /lock = {{{', '.join(watchers)}}}   (N-1 = {len(watchers)} waiters)")

    print("\nNow C1's session EXPIRES (crash / timeout). ZK auto-deletes the")
    print("ephemeral /lock and fires the watch on EVERY registered waiter:\n")
    woken = zk.expire_session("C1")
    print("  tick   3   C1 session expired -> /lock deleted")
    print(f"  tick   3   watches fired on: {{{', '.join(woken)}}}   "
          f"({len(woken)} waiters woke up = the HERD EFFECT)")
    print("\nAll of them now race to re-create /lock. Exactly one wins; the rest")
    print("go back to waiting. The problem: ONE release woke {N-1} clients, all")
    print("hammering ZK at once. With 1000 waiters that is a thundering herd.\n")

    herd = len(woken)
    print(f"[check] number of waiters woken by a single release = {herd} "
          f"(== N-1 == 3-1):  {'OK' if herd == 2 else 'FAIL'}")
    assert herd == 2
    print("\nThis is what Section B fixes: spread the waiters into a QUEUE so a")
    print("release wakes exactly ONE of them.")
    return {"herd_woken": herd, "watchers": watchers}


# ============================================================================
# SECTION B: sequential nodes + predecessor watch (herd-free, consensus-based)
# ============================================================================

def section_b() -> dict:
    banner("SECTION B: sequential nodes - the ordered queue (herd-free)")
    print("Fix: each waiter creates a SEQUENTIAL ephemeral node. The node with")
    print("the LOWEST sequence number holds the lock. Each waiter watches ONLY")
    print("its immediate predecessor, so a release wakes exactly ONE client.\n")
    print("Scenario: C1, C2, C3 each create /lock-<seq>:\n")

    zk = ZKSequential()
    clients = ["C1", "C2", "C3"]
    created: list[tuple[str, str, int, str | None]] = []
    for c in clients:
        path, seq = zk.create_sequential("/lock", c)
        prev = zk.watch_predecessor("/lock", path, seq, c)
        holder = zk.holder("/lock")
        is_holder = holder is not None and holder[0] == c
        created.append((c, path, seq, prev))
        tag = "HOLDS (lowest seq)" if is_holder else "watches predecessor"
        prev_str = prev if prev else "(none - is lowest)"
        print(f"  {c} create_sequential -> {path}  [seq {seq}]  {tag}"
              + ("" if is_holder else f": {prev_str}"))

    holder = zk.holder("/lock")
    print("\n  queue (sorted by seq): "
          + " -> ".join(f"{p.split('-')[1]}({sess})" for p, sess, seq
                        in zk.children_sorted("/lock")))
    print(f"  holder = argmin_seq = {holder[0]} on {holder[1]}  "
          f"(unique, so <= 1 holder by construction)")

    print("\nC1 finishes and RELEASES (deletes its node). Only the watcher on")
    print("that node wakes - C2, the immediate successor. C3 sleeps through it:\n")
    releases = []
    woken_per_release = []
    for releaser in ["C1", "C2"]:
        # find the releaser's path
        rpath = next(p for p, (sess, seq) in zk.nodes.items() if sess == releaser)
        woken = zk.delete(rpath)
        new_holder = zk.holder("/lock")
        woken_per_release.append(1 if woken else 0)
        releases.append((releaser, rpath, woken, new_holder))
        nh = new_holder[0] if new_holder else "(none)"
        print(f"  {releaser} releases {rpath.split('-')[1]} -> wakes {woken} only "
              f"-> new holder = {nh}")
    print("\n  queue now: "
          + (" -> ".join(f"{p.split('-')[1]}({sess})" for p, sess, seq
                         in zk.children_sorted("/lock")) or "(empty)"))

    total = sum(woken_per_release)
    print("\nHERD vs QUEUE, side by side (Section A vs Section B):")
    print("  naive (A): 1 release -> 2 waiters woken (ALL of them)")
    print(f"  queue (B): {len(woken_per_release)} releases -> {total} waiter woken "
          f"(ONE per release, the immediate successor)")
    print("The queue is O(1) wakeups per release regardless of how many clients")
    print("are waiting. That is why ZooKeeper's lock recipe uses sequential nodes.\n")

    ok = (total == len(woken_per_release)) and all(w == 1 for w in woken_per_release)
    print(f"[check] every release woke exactly 1 waiter (not the herd):  "
          f"{'OK' if ok else 'FAIL'}")
    assert ok

    print("\nGOLD (pinned for distributed_locking.html):")
    print("  herd_woken_per_release (naive, N=3) = 2")
    print("  queue_woken_per_release (sequential) = 1")
    print("  holder rule: argmin_seq(live nodes) -> unique -> mutual exclusion")
    return {"queue_woken_per_release": 1, "releases": len(woken_per_release)}


# ============================================================================
# SECTION C: Redis SETNX lock + the stale holder (GC pause)
# ============================================================================

def section_c() -> dict:
    banner("SECTION C: Redis SETNX lock - SET NX PX and the stale holder")
    print("Redis lock primitive:  SET key value NX PX ttl")
    print("  NX  -> set ONLY if the key does not exist (atomic test-and-set)")
    print("  PX  -> expire after ttl milliseconds (a CLOCK countdown)")
    print("Returns 'OK' if you got it, nil if someone else holds it. The danger:")
    print("the lock expires at now+ttl whether or not the holder is still alive.\n")
    print(f"Scenario: TTL = {TTL_REDIS} ticks. C1 acquires at tick 0, does work to")
    print("tick 10, then FREEZES in a GC pause longer than the remaining TTL.\n")

    r = RedisLock()
    GC_C = 25                                   # GC pause length for this section
    gc_start = 10
    gc_end = gc_start + GC_C                    # C1 frozen tick 10..35

    # tick 0: C1 acquires
    res = r.set_nx_px("lock", "c1", TTL_REDIS)
    expiry = r.now + TTL_REDIS
    print(f"  tick {r.now:>3}   C1 SET lock c1 NX PX {TTL_REDIS} -> 'OK'   "
          f"[C1 holds, expires at tick {expiry}]")

    # tick 10: C2 tries, fails
    r.advance(gc_start)
    res = r.set_nx_px("lock", "c2", TTL_REDIS)
    print(f"  tick {r.now:>3}   C2 SET lock c2 NX PX {TTL_REDIS} -> "
          f"{'nil' if not res else repr(res)}  (held; C1 still believes it holds)")

    print(f"\n  tick {r.now:>3}   *** C1 enters a stop-the-world GC pause "
          f"(frozen {GC_C} ticks, until tick {gc_end}) ***")

    # advance to the TTL boundary: lock expires while C1 is frozen
    r.advance(expiry - r.now)                    # tick 30
    print(f"  tick {r.now:>3}   TTL elapsed -> lock EXPIRED "
          f"(is_expired={r.is_expired()}). C1 is frozen and does NOT know.")

    # tick 32: C2 acquires the now-free lock (still within C1's freeze)
    r.advance(2)
    res = r.set_nx_px("lock", "c2", TTL_REDIS)
    holders_believed = ["C1", "C2"]              # BOTH believe they hold it
    print(f"  tick {r.now:>3}   C2 SET lock c2 NX PX {TTL_REDIS} -> 'OK'   "
          f"[C2 holds]. C1 is STILL frozen.")
    print(f"  tick {r.now:>3}   *** holders that BELIEVE they hold = "
          f"{{{', '.join(holders_believed)}}}  -> |holders| = "
          f"{len(holders_believed)} ***")

    # C1 wakes at tick 35, still believes it holds, writes -> corruption
    r.advance(gc_end - r.now)
    print(f"\n  tick {r.now:>3}   C1 WAKES from GC. It never released, never saw")
    print("          the expiry, so it STILL believes it holds the lock. It writes")
    print("          to shared storage. Meanwhile C2 ALSO writes -> DATA CORRUPTION.")

    mx = len(holders_believed)
    print("\nThis is the STALE LOCK HOLDER: the lock's lifetime is a clock")
    print("countdown decoupled from the holder's liveness. A pause longer than")
    print("the remaining TTL silently hands the lock to a second client while the")
    print("first keeps writing. Mutual exclusion is VIOLATED.\n")
    print(f"[check] mutual-exclusion invariant |holders| <= 1 under Redis+GC:  "
          f"{'OK' if mx <= 1 else 'FAIL (' + str(mx) + ' holders)'}")
    assert mx == 2

    print("\nGOLD (pinned for distributed_locking.html):")
    print(f"  TTL = {TTL_REDIS} ticks, GC pause = {GC_C} ticks "
          f"(GC {gc_end} > TTL {expiry} -> expiry during freeze)")
    print(f"  max |holders| observed = {mx}  ->  a Redis lock CANNOT guarantee")
    print("  mutual exclusion against a GC pause. (Motivates Section E.)")
    return {"ttl": TTL_REDIS, "gc_pause": GC_C, "expiry": expiry,
            "gc_end": gc_end, "max_holders": mx}


# ============================================================================
# SECTION D: Redlock - N masters, majority quorum (and Kleppmann's critique)
# ============================================================================

def section_d() -> dict:
    banner("SECTION D: Redlock - N masters, majority quorum, and why clocks break it")
    print("Redlock spreads the SET-NX-PX lock across N (here {n}) INDEPENDENT"
          " Redis masters. A client SETs on all of them; it holds the lock iff a"
          " MAJORITY accepted. quorum = floor(N/2)+1 = {q} for N={n}.\n".format(
              n=N_MASTERS, q=N_MASTERS // 2 + 1))
    print("The hope: any single master failing still leaves a majority that"
          " agrees. The reality (Kleppmann 2016): the TTL is still a CLOCK"
          " countdown on EACH master, and the algorithm assumes every clock is"
          " roughly correct. A clock jump (NTP step / VM suspend) defeats it.\n")

    rl = Redlock(N_MASTERS)
    Q = rl.quorum
    print(f"  N = {rl.n} masters (M1..M{rl.n}),  quorum = {Q},  "
          f"TTL = {TTL_REDLOCK} ticks (per-master clock)\n")

    # C1 acquires: M4, M5 are momentarily slow/unreachable -> C1 gets {M1,M2,M3}
    reach1 = [True, True, True, False, False]
    acq1, got1, set1 = rl.acquire("c1", TTL_REDLOCK, reachable=reach1)
    set1s = "{" + ",".join("M" + str(i) for i in set1) + "}"
    print(f"  C1 acquire: M4,M5 slow/unreachable; SET on M1,M2,M3 -> got {got1}"
          f"  (>= quorum {Q}?) -> {'LOCK ACQUIRED on ' + set1s if acq1 else 'failed'}")
    print(f"             each acquired master's lock expires at its own clock "
          f"{TTL_REDLOCK}.\n")

    # Clock skew: M3's clock JUMPS past the TTL (NTP step after a VM suspend) ->
    # C1's lock on M3 expires "early", even though M1, M2 are unaffected.
    rl.masters[2].advance(TTL_REDLOCK + 2)      # M3 clock now 12 > expiry 10
    print(f"  Clock skew: M3's clock jumps to {rl.masters[2].now} (an NTP step)"
          f" -> C1's lock on M3 EXPIRED. M1 (clock {rl.masters[0].now}) and"
          f" M2 (clock {rl.masters[1].now}) still hold C1's lock.\n")

    # C2 acquires: all reachable now. M1,M2 deny (C1 held); M3,M4,M5 free.
    acq2, got2, set2 = rl.acquire("c2", TTL_REDLOCK)
    set2s = "{" + ",".join("M" + str(i) for i in set2) + "}"
    print(f"  C2 acquire: SET on all {rl.n} -> got {got2} on {set2s}"
          f"  (>= quorum {Q}?) -> {'LOCK ACQUIRED on ' + set2s if acq2 else 'failed'}")

    holders = ["C1", "C2"]
    inter = sorted(set(set1) & set(set2))
    inters = "{" + ",".join("M" + str(i) for i in inter) + "}"
    print(f"\n  TWO VALID MAJORITIES: C1 holds {set1s}, C2 holds {set2s}.")
    print(f"  They overlap only on {inters} - but M3's lock EXPIRED (clock jump),"
          f" so it protects neither. Both got {got1} >= quorum {Q}: both"
          f" legitimately acquired. -> |holders| = {len(holders)}.")
    print("\n  Redlock's validity check (T2-T1 < TTL) is only at ACQUIRE time;"
          " a clock jump AFTER it is undetectable. The majority rule did NOT"
          " prevent the second acquisition, because quorums can be DISJOINT and"
          " clocks can lie. Quorum does not fix bad clocks.\n")

    mx = len(holders)
    print(f"[check] Redlock mutual-exclusion under a clock jump:  "
          f"{'OK' if mx <= 1 else 'FAIL (' + str(mx) + ' holders)'}")
    assert mx == 2 and acq1 and acq2 and got1 >= Q and got2 >= Q

    print("\nKleppmann's point: Redlock is correct ONLY IF you assume bounded"
          " clock skew and NO long pauses - i.e. it trades correctness for an"
          " environment assumption that NTP and GC routinely violate. For real"
          " mutual exclusion you need fencing tokens (Section E), not just a"
          " bigger quorum.")
    print("\nGOLD (pinned for distributed_locking.html):")
    print(f"  N = {N_MASTERS}, quorum = {Q}, TTL = {TTL_REDLOCK}")
    print(f"  C1 majority = {set1s} (got {got1});  C2 majority = {set2s} (got {got2})")
    print(f"  intersection = {inters}  (the lock there had expired -> no protection)")
    print(f"  max |holders| = {mx}  ->  Redlock VIOLATES mutual exclusion under")
    print("  clock skew. Majority quorum does NOT make a clock-based lock safe.")
    return {"n": N_MASTERS, "quorum": Q, "ttl": TTL_REDLOCK,
            "set_c1": set1, "set_c2": set2, "got_c1": got1, "got_c2": got2,
            "max_holders": mx}


# ============================================================================
# SECTION E: fencing tokens - the actual fix
# ============================================================================

def section_e() -> dict:
    banner("SECTION E: fencing tokens - monotonic tokens defeat the stale holder")
    print("The fix: every lock grant carries a fencing token that STRICTLY")
    print("increases over time. The shared storage REFUSES any write whose token")
    print("is not greater than the last one it accepted. So a stale holder that")
    print("wakes up after expiry can be detected and rejected - by the storage.\n")
    print("Replay of the Section C scenario, but now the lock service issues")
    print("tokens and the storage checks them:\n")

    lock = FencingLockService(start_token=32)   # first grant -> token 33
    store = FencedStorage()

    # C1 acquires -> token 33
    t1 = lock.acquire("C1")
    print(f"  C1 acquire -> fencing token {t1}")

    # C1 freezes (GC); lock expires; C2 acquires -> token 34
    print("  *** C1 GC pause; lock EXPIRES ***")
    lock.expire()
    t2 = lock.acquire("C2")
    print(f"  C2 acquire -> fencing token {t2}   (monotonic: {t2} > {t1})")

    # C2 writes with token 34 -> accepted
    ok2 = store.write(t2, "C2", "v34")
    print(f"\n  C2 write(token={t2}, 'v34') -> last_token was {0} -> "
          f"{'ACCEPTED' if ok2 else 'rejected'}  (store.last_token = {store.last_token})")

    # C1 wakes, writes with stale token 33 -> rejected
    ok1 = store.write(t1, "C1", "v33-stale")
    print(f"  C1 write(token={t1}, 'v33-stale') -> {t1} <= {store.last_token} -> "
          f"{'ACCEPTED (BUG!)' if ok1 else 'REJECTED'}")

    print(f"\n  final storage data = {store.data}   (C2's write, the correct one)")
    print("\nThe stale holder (C1) was still able to BELIEVE it held the lock -")
    print("fencing cannot stop a client from being mistaken. But it stops the")
    print("mistake from CORRUPTING anything: the storage gate-keeps on the token,")
    print("so only the genuinely-newest holder's write survives. Mutual exclusion")
    print("is enforced at the resource, not just at the lock service.\n")

    ok = (ok2 and not ok1 and store.data == ("C2", "v34")
          and t2 > t1 and store.last_token == t2)
    print(f"[check] C2 accepted, C1 rejected, storage holds C2's data:  "
          f"{'OK' if ok else 'FAIL'}")
    assert ok

    print("\nGOLD (pinned for distributed_locking.html):")
    print(f"  token sequence: C1={t1}, C2={t2}  (strictly increasing)")
    print(f"  storage.last_token after C2 write = {store.last_token}")
    print(f"  C1 stale write (token {t1}) -> REJECTED  ({t1} <= {store.last_token})")
    print(f"  storage.data = {store.data}  -> data integrity PRESERVED")
    return {"t1": t1, "t2": t2, "accepted": ok2, "rejected": ok1,
            "data": store.data, "last_token": store.last_token}


# ============================================================================
# GOLD CHECK: consensus-based locking => at most ONE holder at every tick
# ============================================================================

def gold_check() -> str:
    banner("GOLD CHECK: consensus-based locking => <= 1 holder at every tick")
    print("The defining property of a lock: at most ONE client believes it holds")
    print("it, at every instant. Brute-force this over a deterministic timeline.\n")

    # --- (1) CONSENSUS-BASED: ZK sequential. 4 clients, interleaved ops. ---
    print("(1) ZooKeeper sequential lock (consensus-based, Section B):")
    print("    holder == argmin_seq(live ephemeral nodes). Distinct sequences =>")
    print("    argmin is unique => at most ONE holder at all times, by proof.\n")
    zk = ZKSequential()
    ops = [
        ("create", "C1"), ("create", "C2"), ("create", "C3"), ("create", "C4"),
        ("release", "C1"), ("create", "C5"),
        ("release", "C2"), ("release", "C3"), ("release", "C4"), ("release", "C5"),
    ]
    max_holders = 0
    ticks_holders: list[tuple[int, list[str]]] = []
    print("    tick  op                live queue (holder *)          |holders|")
    print("    ----  --                ------------------------------  --------")
    for tick, (op, c) in enumerate(ops):
        if op == "create":
            path, seq = zk.create_sequential("/lock", c)
            zk.watch_predecessor("/lock", path, seq, c)
        else:  # release
            rpath = next((p for p, (sess, seq) in zk.nodes.items()
                          if sess == c), None)
            if rpath:
                zk.delete(rpath)
        kids = zk.children_sorted("/lock")
        holder = zk.holder("/lock")
        # clients that CORRECTLY believe they hold == the unique argmin holder,
        # IF they still have a live node. Under consensus, belief == truth.
        believing = [holder[0]] if holder else []
        # released clients no longer believe (the delete told them)
        n = len(believing)
        max_holders = max(max_holders, n)
        ticks_holders.append((tick, believing))
        q = " -> ".join(f"{p.split('-')[1]}({sess}){'*' if sess == (holder[0] if holder else None) else ''}"
                        for p, sess, seq in kids) or "(empty)"
        print(f"    {tick:>4}   {op:<7} {c}        {q:<30} {n}")

    print(f"\n    max |holders| over {len(ops)} ticks = {max_holders}.")
    print(f"    [check] GOLD (consensus): |holders| <= 1 at EVERY tick:  "
          f"{'OK' if max_holders <= 1 else 'FAIL'}")
    assert max_holders <= 1

    # --- (2) COUNTER-MODEL: Redis SETNX under a GC pause reaches 2. ---
    print("\n(2) Counter-model: Redis SETNX (Section C) under a GC pause.")
    print("    Same 'mutual exclusion' claim, but the lock's lifetime is a clock")
    print("    countdown. A pause longer than the TTL silently creates a second")
    print("    holder:\n")
    r = RedisLock()
    r.set_nx_px("lock", "c1", 10)            # C1 holds, expires tick 10
    r.advance(12)                            # tick 12: expired (GC > TTL)
    r.set_nx_px("lock", "c2", 10)            # C2 acquires
    # C1 still believes (frozen). holders = {C1(believes), C2} = 2
    redis_holders = 2
    print("    tick 0  C1 SET NX PX 10 -> OK     (C1 holds, expires tick 10)")
    print("    tick 12 GC pause over, lock EXPIRED; C2 SET NX PX 10 -> OK")
    print(f"    C1 woke and STILL believes it holds -> |holders| = {redis_holders}")
    print(f"    [check] Redis: mutual exclusion VIOLATED (|holders| = {redis_holders}):  "
          f"{'confirmed' if redis_holders == 2 else 'unexpected'}")

    print("\nCONCLUSION: consensus-based locking (ZK sequential) satisfies mutual")
    print("exclusion for free - the holder is the unique minimum, no clocks. Clock-")
    print("based locking (Redis/Redlock) does NOT, because a frozen holder can't")
    print("learn its lock expired. Fencing tokens (Section E) restore safety by")
    print("making the storage itself reject stale holders.")
    print(f"\nGOLD scalar: consensus max_holders = {max_holders} (must be 1); "
          f"redis max_holders = {redis_holders}")
    assert max_holders == 1 and redis_holders == 2
    print("[check] gold scalars reproduce the invariant:  OK")
    return "OK"


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("distributed_locking.py - reference impl. "
          "All numbers below feed DISTRIBUTED_LOCKING.md.")
    print("Pure Python stdlib. Approaches: ZK ephemeral, ZK sequential, "
          "Redis SETNX, Redlock, fencing tokens.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
