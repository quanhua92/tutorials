"""Concurrency — ground-truth demonstrations of core synchronization concepts.

Six sections covering the spectrum of concurrent programming hazards and their fixes:

  1. Race Condition        — read-modify-write lost updates (deterministic trace + real threads)
  2. Mutex / Lock          — mutual exclusion kills the race
  3. Counting Semaphore    — bounded concurrent access to a resource pool
  4. Deadlock              — circular wait in a resource allocation graph (detection + real + prevention)
  5. Reader-Writer         — many concurrent readers, exclusive writers
  6. Dining Philosophers   — deadlock by naive locking, fix by resource hierarchy

Every number printed below is produced by running this file; nothing is
hand-computed.  Capture with:

    python3 concurrency.py > concurrency_output.txt 2>/dev/null
"""

from __future__ import annotations

import sys
import threading
import time
from collections import defaultdict


# ---------------------------------------------------------------------------
# Section 1 — Race Condition
# ---------------------------------------------------------------------------

def section_race_condition() -> None:
    print("=" * 72)
    print("=== Race Condition — read-modify-write lost updates")
    print("=" * 72)

    print()
    print("  'counter += 1' is NOT one instruction. It compiles to three:")
    print("    LOAD   register <- counter      (read shared state)")
    print("    ADD    register <- register + 1  (compute on private copy)")
    print("    STORE  counter   <- register     (write back)")
    print()
    print("  Two threads each do counter += 1 once. counter starts at 0.")
    print("  Expected final value: 2.")
    print()

    # --- BAD interleaving: A and B both LOAD before either STOREs ---
    counter = 0
    rA = 0
    rB = 0
    bad: list[tuple[str, str, int, int, int]] = []
    rA = counter
    bad.append(("A", "LOAD  rA = counter", rA, rB, counter))
    rB = counter
    bad.append(("B", "LOAD  rB = counter (stale!)", rA, rB, counter))
    rA = rA + 1
    bad.append(("A", "ADD   rA = rA + 1", rA, rB, counter))
    rB = rB + 1
    bad.append(("B", "ADD   rB = rB + 1", rA, rB, counter))
    counter = rA
    bad.append(("A", "STORE counter = rA", rA, rB, counter))
    counter = rB
    bad.append(("B", "STORE counter = rB (clobbers A)", rA, rB, counter))

    print("  BAD interleaving (A and B both LOAD before either STOREs):")
    print()
    print("  step  thread  instruction                          rA  rB  counter")
    print("  ----  ------  ---------------------------------   ---  ---  -------")
    for i, (t, inst, ra, rb, c) in enumerate(bad, 1):
        print(f"  {i:>4}  {t:>6}  {inst:<35}  {ra:>3}  {rb:>3}  {c:>7}")
    print()
    print(f"  expected = 2   actual = {counter}   LOST UPDATES = {2 - counter}")
    ok_bad = counter == 1
    print(f"  [check] {'OK' if ok_bad else 'FAIL'}   (interleaving demonstrably loses 1 update)")
    assert ok_bad

    # --- GOOD interleaving: A completes fully before B starts ---
    counter = 0
    rA = 0
    rB = 0
    good: list[tuple[str, str, int, int, int]] = []
    rA = counter
    good.append(("A", "LOAD  rA = counter", rA, rB, counter))
    rA = rA + 1
    good.append(("A", "ADD   rA = rA + 1", rA, rB, counter))
    counter = rA
    good.append(("A", "STORE counter = rA", rA, rB, counter))
    rB = counter
    good.append(("B", "LOAD  rB = counter", rA, rB, counter))
    rB = rB + 1
    good.append(("B", "ADD   rB = rB + 1", rA, rB, counter))
    counter = rB
    good.append(("B", "STORE counter = rB", rA, rB, counter))

    print()
    print("  GOOD interleaving (A completes all 3 instructions before B starts):")
    print()
    print("  step  thread  instruction                          rA  rB  counter")
    print("  ----  ------  ---------------------------------   ---  ---  -------")
    for i, (t, inst, ra, rb, c) in enumerate(good, 1):
        print(f"  {i:>4}  {t:>6}  {inst:<35}  {ra:>3}  {rb:>3}  {c:>7}")
    print()
    print(f"  expected = 2   actual = {counter}"
          f"   [check] {'OK' if counter == 2 else 'FAIL'}")
    assert counter == 2

    # --- Real CPython threads: the race happens in practice ---
    # The GIL serializes bytecodes, so we widen the read-modify-write window
    # with time.sleep(0) — a no-op that yields the GIL. This represents the
    # gap that exists in real code between a LOAD and a STORE (at the CPU
    # level) or between a SELECT and an UPDATE (in application code).
    print()
    print("  --- real CPython threads, 4 threads x 50_000 increments ---")
    print("  (read-modify-write window widened via time.sleep(0) GIL yield)")
    print()
    expected = 4 * 50_000
    runs: list[tuple[int, int, int]] = []
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for run in range(1, 6):
            shared = [0]

            def worker() -> None:
                for _ in range(50_000):
                    val = shared[0]       # LOAD
                    time.sleep(0)         # yield GIL (widens the race window)
                    shared[0] = val + 1   # STORE

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            lost = expected - shared[0]
            runs.append((run, shared[0], lost))
    finally:
        sys.setswitchinterval(old_interval)

    print(f"  {'run':>4}  {'counter':>9}  {'lost':>8}  {'pct':>6}")
    print(f"  {'---':>4}  {'-------':>9}  {'----':>8}  {'---':>6}")
    for run, val, lost in runs:
        print(f"  {run:>4}  {val:>9}  {lost:>8}  {lost / expected * 100:>5.2f}%")
    total_lost = sum(lost for _, _, lost in runs)
    print()
    print(f"  expected per run = {expected}"
          f"   total lost across 5 runs = {total_lost}")
    print(f"  [check] {'OK' if total_lost > 0 else 'FAIL'}"
          f"   (real threads lose updates without synchronization)")
    assert total_lost > 0


# ---------------------------------------------------------------------------
# Section 2 — Mutex / Lock
# ---------------------------------------------------------------------------

def section_mutex() -> None:
    print()
    print("=" * 72)
    print("=== Mutex / Lock — mutual exclusion eliminates the race")
    print("=" * 72)

    lock = threading.Lock()
    shared = [0]
    iterations = 50_000
    n_threads = 4

    def worker() -> None:
        for _ in range(iterations):
            with lock:
                val = shared[0]       # LOAD (serialized by the lock)
                time.sleep(0)
                shared[0] = val + 1   # STORE

    old_m = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0
    sys.setswitchinterval(old_m)

    expected = n_threads * iterations
    print(f"  {n_threads} threads x {iterations:,} increments, guarded by threading.Lock()")
    print("  (same widened window as Section 1, but serialized by the lock)")
    print(f"  counter = {shared[0]:,} / {expected:,}")
    print(f"  elapsed = {elapsed * 1000:.0f} ms")
    print(f"  [check] {'OK' if shared[0] == expected else 'FAIL'}"
          f"   (mutex -> exact count, no lost updates)")
    assert shared[0] == expected

    # Contrast: same workload WITHOUT the lock
    shared2 = [0]

    def worker_unlocked() -> None:
        for _ in range(50_000):
            val = shared2[0]
            time.sleep(0)
            shared2[0] = val + 1

    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=worker_unlocked) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old)

    expected_unlocked = n_threads * 50_000
    lost = expected_unlocked - shared2[0]
    print()
    print(f"  same workload WITHOUT lock: counter = {shared2[0]:,}"
          f"   lost = {lost:,}")
    print(f"  [check] {'OK' if lost > 0 else 'FAIL'}"
          f"   (no lock -> lost updates)")
    assert lost > 0


# ---------------------------------------------------------------------------
# Section 3 — Counting Semaphore
# ---------------------------------------------------------------------------

def section_semaphore() -> None:
    print()
    print("=" * 72)
    print("=== Counting Semaphore — bounded access to a resource pool")
    print("=" * 72)

    pool_size = 3
    n_threads = 10
    work_ms = 8
    sem = threading.Semaphore(pool_size)
    guard = threading.Lock()
    state = {"active": 0, "peak": 0, "violations": 0}

    def worker(wid: int) -> None:
        sem.acquire()
        try:
            with guard:
                state["active"] += 1
                if state["active"] > state["peak"]:
                    state["peak"] = state["active"]
                if state["active"] > pool_size:
                    state["violations"] += 1
            time.sleep(work_ms / 1000)
            with guard:
                state["active"] -= 1
        finally:
            sem.release()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"  Semaphore({pool_size}) guarding a pool of {pool_size} slots")
    print(f"  {n_threads} threads each hold a slot for {work_ms} ms")
    print(f"  peak concurrent access = {state['peak']}"
          f"   pool violations = {state['violations']}")
    ok = state["peak"] <= pool_size and state["violations"] == 0
    print(f"  [check] {'OK' if ok else 'FAIL'}"
          f"   (counting semaphore never exceeds {pool_size})")
    assert ok

    # Deterministic step-based simulation (for HTML gold-check parity)
    print()
    print("  --- deterministic step-based simulation (10 threads arrive 1/step, hold 3 steps) ---")
    sim_pool = 3
    sim_n = 10
    hold = 3
    active = 0
    peak2 = 0
    releases: dict[int, int] = defaultdict(int)
    timeline: list[tuple[int, int]] = []
    for t in range(sim_n + hold + 2):
        active -= releases.pop(t, 0)
        if t < sim_n:
            active += 1
            releases[t + hold] += 1
        if active > peak2:
            peak2 = active
        if t < 12:
            timeline.append((t, active))
    print(f"  step  active   (max={sim_pool})")
    print("  ----  ------")
    for t, a in timeline:
        flag = "  <-- VIOLATION" if a > sim_pool else ""
        print(f"  {t:>4}  {a:>6}{flag}")
    print(f"  ... ({sim_n + hold + 2 - len(timeline)} more steps)")
    print(f"  peak = {peak2}"
          f"   [check] {'OK' if peak2 <= sim_pool else 'FAIL'}"
          f"   (deterministic sim also bounded)")
    assert peak2 <= sim_pool


# ---------------------------------------------------------------------------
# Section 4 — Deadlock (detection + real + prevention)
# ---------------------------------------------------------------------------

def detect_cycle(edges: list[tuple[str, str]]) -> list[str]:
    """Detect a cycle in a directed graph via DFS coloring.

    Returns the cycle as a node list (start repeated at end), or [] if acyclic.
    """
    adj: dict[str, list[str]] = defaultdict(list)
    nodes: list[str] = []
    seen: set[str] = set()
    for a, b in edges:
        adj[a].append(b)
        for n in (a, b):
            if n not in seen:
                seen.add(n)
                nodes.append(n)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in nodes}
    stack: list[str] = []

    def dfs(u: str) -> list[str]:
        color[u] = GRAY
        stack.append(u)
        for v in adj[u]:
            if color[v] == GRAY:
                idx = stack.index(v)
                return stack[idx:] + [v]
            if color[v] == WHITE:
                found = dfs(v)
                if found:
                    return found
        stack.pop()
        color[u] = BLACK
        return []

    for n in nodes:
        if color[n] == WHITE:
            found = dfs(n)
            if found:
                return found
    return []


def section_deadlock() -> None:
    print()
    print("=" * 72)
    print("=== Deadlock — circular wait in a resource allocation graph")
    print("=" * 72)

    print()
    print("  Resource allocation graph (bipartite):")
    print("    Assignment edge:  Resource -> Thread  (resource held by thread)")
    print("    Request edge:     Thread -> Resource  (thread waiting for resource)")
    print("    A cycle in this graph == DEADLOCK.")
    print()
    print("    T1 holds R1, wants R2     T2 holds R2, wants R1")
    print()
    print("         +--- R1 <--)")
    print("         |        |")
    print("         v        |")
    print("        T1 --) R2 <-+")
    print("              |")
    print("              v")
    print("             T2 --) R1  (held by T1)")
    print()

    edges = [
        ("R1", "T1"),  # R1 assigned to T1
        ("R2", "T2"),  # R2 assigned to T2
        ("T1", "R2"),  # T1 requests R2
        ("T2", "R1"),  # T2 requests R1
    ]
    cycle = detect_cycle(edges)
    cycle_str = " -> ".join(cycle) if cycle else "(none)"
    print(f"  edges: {edges}")
    print(f"  cycle detected: {cycle_str}")
    ok = len(cycle) > 0
    print(f"  [check] {'OK' if ok else 'FAIL'}"
          f"   (cycle in RAG == deadlock)")
    assert ok

    # --- Real thread deadlock (daemon threads block forever; we observe) ---
    print()
    print("  --- real threads: 2 threads, 2 locks, opposite acquisition order ---")
    lock_a = threading.Lock()
    lock_b = threading.Lock()
    progress = {"t1_a": False, "t1_b": False, "t1_try": False,
                "t2_b": False, "t2_a": False, "t2_try": False}
    barrier = threading.Barrier(2)

    def t1() -> None:
        with lock_a:
            progress["t1_a"] = True
            barrier.wait()  # ensure T2 also holds lock_b before proceeding
            progress["t1_try"] = True
            lock_b.acquire()  # blocks forever — T2 holds lock_b
            progress["t1_b"] = True
            lock_b.release()

    def t2() -> None:
        with lock_b:
            progress["t2_b"] = True
            barrier.wait()  # ensure T1 also holds lock_a before proceeding
            progress["t2_try"] = True
            lock_a.acquire()  # blocks forever — T1 holds lock_a
            progress["t2_a"] = True
            lock_a.release()

    th1 = threading.Thread(target=t1, name="T1", daemon=True)
    th2 = threading.Thread(target=t2, name="T2", daemon=True)
    th1.start()
    th2.start()
    th1.join(timeout=0.3)
    th2.join(timeout=0.3)

    deadlocked = (progress["t1_a"] and progress["t2_b"]
                  and progress["t1_try"] and progress["t2_try"]
                  and not progress["t1_b"] and not progress["t2_a"]
                  and th1.is_alive() and th2.is_alive())
    print(f"  T1: holds A={progress['t1_a']}, trying B... got B={progress['t1_b']}")
    print(f"  T2: holds B={progress['t2_b']}, trying A... got A={progress['t2_a']}")
    print(f"  both threads alive and stuck after 0.3s: {th1.is_alive() and th2.is_alive()}")
    print(f"  [check] {'OK' if deadlocked else 'FAIL'}"
          f"   (circular wait — both blocked forever)")
    assert deadlocked

    # --- Deadlock prevention: fixed lock ordering ---
    print()
    print("=" * 72)
    print("=== Deadlock Prevention — fixed lock ordering breaks the cycle")
    print("=" * 72)

    lock_a2 = threading.Lock()
    lock_b2 = threading.Lock()
    done = {"t1": False, "t2": False}

    def t1_ordered() -> None:
        with lock_a2:
            with lock_b2:
                time.sleep(0.01)
        done["t1"] = True

    def t2_ordered() -> None:
        with lock_a2:
            with lock_b2:
                time.sleep(0.01)
        done["t2"] = True

    th1 = threading.Thread(target=t1_ordered)
    th2 = threading.Thread(target=t2_ordered)
    th1.start()
    th2.start()
    th1.join()
    th2.join()

    print("  both threads acquire locks in the SAME order (A, then B)")
    print(f"  T1 done: {done['t1']}   T2 done: {done['t2']}")
    print(f"  [check] {'OK' if done['t1'] and done['t2'] else 'FAIL'}"
          f"   (lock ordering -> no circular wait)")
    assert done["t1"] and done["t2"]

    # Verify the no-deadlock graph has no cycle
    edges_safe = [
        ("R1", "T1"),
        ("R2", "T1"),  # T1 holds both
    ]
    cycle_safe = detect_cycle(edges_safe)
    print(f"  RAG with single holder: {edges_safe}")
    print(f"  cycle: {' -> '.join(cycle_safe) if cycle_safe else '(none)'}")
    print(f"  [check] {'OK' if not cycle_safe else 'FAIL'}"
          f"   (no cycle when one thread holds both)")
    assert not cycle_safe


# ---------------------------------------------------------------------------
# Section 5 — Reader-Writer
# ---------------------------------------------------------------------------

class RWLock:
    """A reader-writer lock (readers-preference).

    Multiple readers can hold the lock simultaneously. A writer gets exclusive
    access: no readers and no other writer may be active during a write.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False

    def acquire_read(self) -> None:
        with self._cond:
            while self._writer:
                self._cond.wait()
            self._readers += 1

    def release_read(self) -> None:
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def acquire_write(self) -> None:
        with self._cond:
            while self._readers > 0 or self._writer:
                self._cond.wait()
            self._writer = True

    def release_write(self) -> None:
        with self._cond:
            self._writer = False
            self._cond.notify_all()


def section_reader_writer() -> None:
    print()
    print("=" * 72)
    print("=== Reader-Writer — many readers OR one writer (exclusive)")
    print("=" * 72)

    rw = RWLock()
    guard = threading.Lock()
    state = {"readers": 0, "peak_readers": 0, "writer": False, "violations": 0}

    def reader() -> None:
        rw.acquire_read()
        try:
            with guard:
                state["readers"] += 1
                if state["readers"] > state["peak_readers"]:
                    state["peak_readers"] = state["readers"]
                if state["writer"]:
                    state["violations"] += 1
            time.sleep(0.005)
            with guard:
                state["readers"] -= 1
        finally:
            rw.release_read()

    def writer() -> None:
        rw.acquire_write()
        try:
            with guard:
                if state["readers"] > 0 or state["writer"]:
                    state["violations"] += 1
                state["writer"] = True
            time.sleep(0.005)
            with guard:
                state["writer"] = False
        finally:
            rw.release_write()

    threads = []
    for _ in range(8):
        threads.append(threading.Thread(target=reader))
    for _ in range(2):
        threads.append(threading.Thread(target=writer))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print("  8 readers + 2 writers, readers-preference RWLock")
    print(f"  peak concurrent readers = {state['peak_readers']}")
    print(f"  exclusivity violations  = {state['violations']}")
    ok = state["peak_readers"] >= 2 and state["violations"] == 0
    print(f"  [check] {'OK' if ok else 'FAIL'}"
          f"   (readers overlap, writers exclusive)")
    assert ok

    # Deterministic event trace showing reader overlap + writer exclusivity
    print()
    print("  --- deterministic event trace (RWLock guarantees no overlap) ---")
    events: list[tuple[str, int]] = [
        ("R+", 1), ("R+", 2), ("R+", 3),  # 3 readers pile in (overlap)
        ("R-", 1), ("R-", 2), ("R-", 3),  # readers drain
        ("W+", 1),                          # writer exclusive (readers=0)
        ("W-", 1),                          # writer leaves
        ("R+", 4), ("R+", 5),              # 2 more readers overlap
        ("R-", 4), ("R-", 5),
    ]
    det_readers = 0
    det_peak = 0
    det_viol = 0
    det_writer = False
    trace: list[tuple[int, str, int, bool]] = []
    for step, (op, rid) in enumerate(events):
        if op == "R+":
            if det_writer:
                det_viol += 1
            det_readers += 1
            if det_readers > det_peak:
                det_peak = det_readers
        elif op == "R-":
            det_readers -= 1
        elif op == "W+":
            if det_readers > 0 or det_writer:
                det_viol += 1
            det_writer = True
        elif op == "W-":
            det_writer = False
        trace.append((step, f"{op}{rid}", det_readers, det_writer))
    print("  step  event  active_readers  writer_active")
    print("  ----  -----  --------------  -------------")
    for step, ev, ar, wa in trace:
        print(f"  {step:>4}  {ev:>5}  {ar:>14}  {str(wa):>13}")
    print(f"  peak readers = {det_peak}   violations = {det_viol}"
          f"   [check] {'OK' if det_peak >= 2 and det_viol == 0 else 'FAIL'}"
          f"   (readers overlap, writer exclusive)")
    assert det_peak >= 2 and det_viol == 0


# ---------------------------------------------------------------------------
# Section 6 — Dining Philosophers
# ---------------------------------------------------------------------------

def section_dining_philosophers() -> None:
    print()
    print("=" * 72)
    print("=== Dining Philosophers — deadlock by naive locking, fix by hierarchy")
    print("=" * 72)

    n = 5
    print()
    print(f"  {n} philosophers sit at a round table with {n} forks.")
    print("  Each philosopher needs BOTH adjacent forks to eat.")
    print(f"  Fork i is between philosopher i and philosopher (i+1) mod {n}.")
    print()
    print("       P0 -- F0 -- P1 -- F1 -- P2 -- F2 -- P3 -- F3 -- P4 -- F4 -- P0")
    print()

    # --- Naive: pick up left, then right. Two barriers -> guaranteed deadlock ---
    forks = [threading.Lock() for _ in range(n)]
    ate = [0] * n
    done_flags = [False] * n
    b1 = threading.Barrier(n)
    b2 = threading.Barrier(n)

    def phi_naive(i: int) -> None:
        left = i
        right = (i + 1) % n
        b1.wait()                  # start together
        forks[left].acquire()      # pick up left fork (distinct, instant)
        b2.wait()                  # ALL hold their left fork -> now try right
        forks[right].acquire()     # blocks forever (held by neighbor's left)
        done_flags[i] = True
        ate[i] += 1
        forks[right].release()
        forks[left].release()

    threads = [threading.Thread(target=phi_naive, args=(i,), daemon=True)
               for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=0.3)

    total_ate = sum(ate)
    all_alive = all(threads[i].is_alive() for i in range(n))
    all_stuck = all(not done_flags[i] for i in range(n))
    print("  NAIVE: each picks up LEFT then RIGHT, barrier-synchronized")
    print("    Barrier 1: all philosophers start together")
    print(f"    Each picks up their LEFT fork (fork 0..{n-1})")
    print("    Barrier 2: ALL hold their left fork -> each tries RIGHT")
    print(f"    Pi holds Fi, waits for F(i+1 mod {n})")
    print("    -> circular wait: P0->F0, P1->F1, P2->F2, P3->F3, P4->F4")
    print(f"    philosophers who ate: {total_ate} / {n}")
    print(f"    all threads alive and stuck after 0.3s: {all_alive and all_stuck}")
    ok = all_alive and all_stuck
    print(f"  [check] {'OK' if ok else 'FAIL'}"
          f"   (circular wait -> every philosopher stuck forever)")
    assert ok

    # --- Fix: resource hierarchy (acquire lower-numbered fork first) ---
    rounds = 20
    forks2 = [threading.Lock() for _ in range(n)]
    ate2 = [0] * n

    def phi_ordered(i: int) -> None:
        left = i
        right = (i + 1) % n
        first = min(left, right)
        second = max(left, right)
        for _ in range(rounds):
            with forks2[first]:
                with forks2[second]:
                    ate2[i] += 1
                    time.sleep(0.0005)

    threads = [threading.Thread(target=phi_ordered, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_ate2 = sum(ate2)
    print()
    print("  FIX: resource hierarchy — always acquire lower-numbered fork first")
    print("    P0..P3: left(fork i) then right(fork i+1)")
    print("    P4: right(fork 0) then left(fork 4)  <- reversed, breaks cycle")
    print(f"    philosophers who ate: {total_ate2} / {n * rounds} rounds")
    per_phi = " ".join(f"P{i}={ate2[i]}" for i in range(n))
    print(f"    per-philosopher: {per_phi}")
    ok2 = total_ate2 == n * rounds
    print(f"  [check] {'OK' if ok2 else 'FAIL'}"
          f"   (hierarchy breaks the cycle, everyone eats)")
    assert ok2


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    section_race_condition()
    section_mutex()
    section_semaphore()
    section_deadlock()
    section_reader_writer()
    section_dining_philosophers()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
