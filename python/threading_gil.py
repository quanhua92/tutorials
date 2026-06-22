"""
threading_gil.py — Phase 3 bundle #19.

GOAL (one line): show, by printing every value, how Python threads share
memory, why the GIL stops CPU-bound threads from parallelizing while still
letting I/O-bound threads overlap, and how Lock / RLock / Queue make shared
state safe.

This is the GROUND TRUTH for THREADING_GIL.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Stdlib only (threading, queue, time, sys, sysconfig). Threading timing is
inherently nondeterministic, so we assert STRUCTURAL invariants (a race
loses updates; a Lock yields the exact count; a Queue transfers every item;
I/O threads overlap) and report wall-clock figures as illustrative, never as
pass/fail exact values.

Run:
    uv run python threading_gil.py
"""

from __future__ import annotations

import queue
import sys
import sysconfig
import threading
import time

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers (house style — mirrors types_and_truthiness.py)
# ----------------------------------------------------------------------------

def banner(title: str) -> None:
    """Print a clearly delimited section divider (the house style)."""
    print("\n" + BANNER)
    print(f"SECTION {title}")
    print(BANNER)


def check(description: str, condition: bool) -> None:
    """Assert an invariant and print a uniform [check] ... OK line."""
    assert condition, f"INVARIANT VIOLATED: {description}"
    print(f"[check] {description}: OK")


def _gil_enabled() -> bool:
    """Return whether the GIL is active in this running interpreter.

    On a free-threaded build (Py_GIL_DISABLED, Python 3.13+, PEP 703) the
    GIL can be off at runtime; we query sys._is_gil_enabled when available.
    Otherwise the GIL is on (every standard CPython build)."""
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        probe = getattr(sys, "_is_gil_enabled", None)
        return bool(probe()) if callable(probe) else False
    return True


# ----------------------------------------------------------------------------
# Section A — Thread basics: start(), join(), and a shared result
# ----------------------------------------------------------------------------

def section_a_thread_basics() -> None:
    banner("A — Thread basics: start(), join(), and a shared result")
    print("A thread is a separate flow of control sharing the SAME memory as")
    print("its creator. threading.Thread(target=fn) wraps a callable; .start()")
    print("schedules it on a new OS thread; .join() blocks the caller until it")
    print("finishes. The worker writes into a dict the main thread reads AFTER")
    print("join() — that is how results flow back through SHARED memory.\n")

    shared: dict[str, str] = {}

    def worker(name: str, delay: float) -> None:
        time.sleep(delay)
        shared["worker"] = f"hello from {name}"

    print("main thread: creating worker thread ...")
    t = threading.Thread(target=worker, args=("alpha", 0.01),
                         name="worker-alpha")
    print(f"  thread object: name={t.name!r}, daemon={t.daemon}, "
          f"alive(before start)={t.is_alive()}")
    t.start()
    print(f"  after start(): alive={t.is_alive()}, ident={t.ident}")
    t.join()
    print(f"  after join():  alive={t.is_alive()}, ident={t.ident}")
    print(f"  shared['worker'] = {shared['worker']!r}")
    print()

    check("worker ran and wrote into shared memory ('worker' in shared)",
          "worker" in shared)
    check("the worker's result is visible to main after join()",
          shared["worker"] == "hello from alpha")
    check("a joined thread is no longer alive (not t.is_alive())",
          not t.is_alive())
    check("main thread is threading.main_thread()",
          threading.current_thread() is threading.main_thread())


# ----------------------------------------------------------------------------
# Section B — The GIL: CPU-bound threads do NOT parallelize; I/O-bound do
# ----------------------------------------------------------------------------

def _burn(n: int) -> int:
    """Pure-Python CPU work: returns a deterministic sum so the loop body
    cannot be elided. Holds the GIL the whole time (no I/O inside)."""
    s = 0
    for i in range(n):
        s += i & 0xFF
    return s


def section_b_gil_cpu_and_io() -> None:
    banner("B — The GIL: CPU-bound threads do NOT parallelize; I/O-bound do")
    gil = _gil_enabled()
    print("The Global Interpreter Lock (GIL) is a mutex guaranteeing that only")
    print("ONE thread executes Python bytecode at a time. Pure-Python CPU work")
    print("holds the GIL continuously (released only every few ms for a switch)")
    print("so splitting it across threads cannot use extra cores. I/O calls")
    print("(time.sleep, socket, file) RELEASE the GIL while waiting, so I/O")
    print("threads DO overlap.\n")
    print(f"This interpreter: GIL enabled = {gil}")
    print("(On a free-threaded / PEP 703 build, GIL enabled = False.)\n")

    # --- CPU-bound: 1 thread vs 4 threads doing the same TOTAL work. Each
    #     thread writes its OWN list slot so there is no shared write race. ---
    total = 2_000_000
    per_thread = total // 4

    t0 = time.perf_counter()
    s_single = _burn(total)
    t_single = time.perf_counter() - t0

    results = [0] * 4

    def chunk(idx: int) -> None:
        results[idx] = _burn(per_thread)

    threads = [threading.Thread(target=chunk, args=(i,)) for i in range(4)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    t_multi = time.perf_counter() - t0
    acc = sum(results)

    print(f"CPU-bound work (pure-Python loop), total iterations = {total:,}:")
    print(f"  1 thread  : sum={s_single}, elapsed={t_single:.4f}s")
    print(f"  4 threads : sum={acc}, elapsed={t_multi:.4f}s "
          f"(each thread = {per_thread:,} iters)")
    print("  -> under the GIL, 4 threads take about the SAME wall time as")
    print("     1 thread (work is serialized, not parallelized).")
    print("     (Wall times are illustrative; they vary by machine/load.)\n")

    check("CPU work produced the correct sum (1 thread)",
          s_single == sum(i & 0xFF for i in range(total)))
    check("CPU work produced the correct sum (4 threads, separate slots)",
          acc == sum(i & 0xFF for i in range(per_thread)) * 4)
    if gil:
        check("GIL on: 4 CPU threads are NOT 2x faster "
              "(t_multi >= t_single/2)",
              t_multi >= t_single * 0.5)
    else:
        print("[check] (free-threaded build: CPU timing assertion skipped —")
        print("         a no-GIL interpreter CAN parallelize CPU work.)\n")

    # --- I/O-bound: 4 threads each sleeping; they overlap because sleep
    #     RELEASES the GIL while waiting. Each sets its OWN flag (no race). ---
    sleep_each = 0.1
    done = [False] * 4

    def sleeper(idx: int) -> None:
        time.sleep(sleep_each)
        done[idx] = True

    threads = [threading.Thread(target=sleeper, args=(i,)) for i in range(4)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    t_io = time.perf_counter() - t0
    serial = sleep_each * 4

    print(f"I/O-bound work: 4 threads each time.sleep({sleep_each}):")
    print(f"  serial would be ~{serial:.2f}s; actual elapsed = {t_io:.4f}s")
    print("  -> sleep RELEASES the GIL while waiting, so the 4 waits overlap")
    print("     and finish in ~one sleep, not four. (Illustrative timing.)\n")

    check("all 4 I/O threads completed (all flags set)", all(done))
    check("I/O threads overlapped (elapsed < serial*0.75 = 0.30s)",
          t_io < serial * 0.75)


# ----------------------------------------------------------------------------
# Section C — The race: a shared counter WITHOUT a lock loses updates
# ----------------------------------------------------------------------------

def _race(counter: list[int], iters: int) -> None:
    """Increment a shared counter WITHOUT a lock, using an explicit
    read-modify-write. On modern CPython a bare `counter += 1` rarely loses
    updates (the GIL hands off at clean bytecode boundaries), so the bug is
    *latent* and hard to reproduce. Inserting time.sleep(0) — which RELEASES
    the GIL — between the READ and the WRITE models any real code path that
    yields mid-update (an I/O call, a C function) and makes the lost update
    reliably observable."""
    for _ in range(iters):
        current = counter[0]      # READ
        time.sleep(0)             # release the GIL -> another thread can run
        counter[0] = current + 1  # WRITE (may clobber a concurrent increment)


def section_c_the_race() -> None:
    banner("C — The race: a shared counter WITHOUT a lock loses updates")
    n_threads = 4
    iters = 50_000
    expected = n_threads * iters
    print(f"{n_threads} threads x {iters:,} read-modify-writes each; "
          f"expected total = {expected:,}.\n")
    print("A read-modify-write is NOT atomic: it is READ the value, compute")
    print("value+1, WRITE it back. If the GIL switches threads between the")
    print("READ and the WRITE, two threads read the SAME value and one WRITE")
    print("clobbers the other -> a LOST update.\n")
    print("Expert gotcha: on modern CPython a bare `counter += 1` rarely loses")
    print("updates in practice — the GIL hands off at clean bytecode boundaries,")
    print("so the bug is *latent* (real but hard to trigger). We insert")
    print("time.sleep(0) between the read and the write: it RELEASES the GIL,")
    print("modeling any real code path that yields mid-update (I/O, a C call),")
    print("and makes the lost update reliably observable.\n")

    counter = [0]
    threads = [threading.Thread(target=_race, args=(counter, iters))
               for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lost = expected - counter[0]
    print(f"  expected = {expected:,}")
    print(f"  actual   = {counter[0]:,}")
    print(f"  lost     = {lost:,} updates")
    print("  (exact loss VARIES per run — illustrative; the FACT that count <")
    print("   expected is the deterministic, structural point.)")
    print()

    check("race lost updates (counter < expected)", counter[0] < expected)
    check("the counter is non-negative", counter[0] >= 0)


# ----------------------------------------------------------------------------
# Section D — A Lock fixes the race: the count is exactly correct
# ----------------------------------------------------------------------------

def _locked_inc(counter: list[int], lock: threading.Lock,
                iters: int) -> None:
    """SAME read-modify-write + time.sleep(0) as _race, but wrapped in a Lock.
    The critical section is now atomic w.r.t. other threads, so no update is
    lost — the only difference from _race is the `with lock:`."""
    for _ in range(iters):
        with lock:
            current = counter[0]      # READ
            time.sleep(0)             # releases the GIL, but NOT the Lock
            counter[0] = current + 1  # WRITE


def section_d_lock_fixes_it() -> None:
    banner("D — A Lock fixes the race: the count is exactly correct")
    n_threads = 4
    iters = 50_000
    expected = n_threads * iters
    print("threading.Lock is a mutex. `with lock:` makes the read-modify-write")
    print("ATOMIC with respect to other threads holding the SAME lock: only one")
    print("thread can be inside the critical section at a time, so no update is")
    print("lost. The code below is IDENTICAL to Section C (same read, same")
    print("time.sleep(0), same write) — the ONLY addition is `with lock:`.\n")

    counter = [0]
    lock = threading.Lock()
    threads = [threading.Thread(target=_locked_inc,
                                args=(counter, lock, iters))
               for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"  expected = {expected:,}")
    print(f"  actual   = {counter[0]:,}")
    print()

    check("Lock gives the exact expected count (counter == expected)",
          counter[0] == expected)


# ----------------------------------------------------------------------------
# Section E — RLock (reentrant): a thread may acquire the SAME lock twice
# ----------------------------------------------------------------------------

def section_e_rlock_reentrancy() -> None:
    banner("E — RLock (reentrant): a thread may acquire the same lock twice")
    print("A plain Lock DEADLOCKS if the owning thread calls acquire() again")
    print("(it blocks forever waiting for itself). threading.RLock tracks an")
    print("'owning thread' + a recursion level: the SAME thread can acquire")
    print("it N times and must release it N times. This lets a function that")
    print("already holds the lock call another function that acquires it too")
    print("— recursion and re-entrancy without self-deadlock.\n")

    # --- plain Lock: a second acquire by the same thread would deadlock ---
    plain = threading.Lock()
    plain.acquire()
    second_plain = plain.acquire(blocking=False)  # blocks forever if True
    plain.release()
    print("plain Lock:  acquire() -> True;  2nd acquire(blocking=False) -> "
          f"{second_plain}  (would DEADLOCK if blocking)")
    print()

    check("a plain Lock CANNOT be re-acquired by its owner (2nd -> False)",
          second_plain is False)

    # --- RLock: the same thread re-acquires fine ---
    rlock = threading.RLock()
    first = rlock.acquire()       # level 1
    second = rlock.acquire()      # level 2 (same thread -> ok, no block)
    rlock.release()               # back to level 1
    still_owned = rlock.acquire(blocking=False)  # still owner -> True
    rlock.release()               # level 1
    rlock.release()               # level 0 -> unlocked
    reacquired = rlock.acquire(blocking=False)   # free to take again
    rlock.release()
    print("RLock:       acquire() -> True;  2nd acquire() -> True "
          "(same thread);")
    print(f"             after 1 release, acquire(blocking=False) -> "
          f"{still_owned} (still owner);")
    print(f"             after full release, acquire(blocking=False) -> "
          f"{reacquired} (free to take again)")
    print()

    check("RLock first acquire returns True", first is True)
    check("RLock re-acquire by the SAME thread returns True (no deadlock)",
          second is True)
    check("RLock still owned after one release of two", still_owned is True)
    check("RLock re-acquirable after full release", reacquired is True)

    # --- recursive function using RLock: nested acquire at each level ---
    def factorial(n: int, lk: threading.RLock) -> int:
        with lk:                       # safe to re-acquire on each recursion
            if n <= 1:
                return 1
            return n * factorial(n - 1, lk)

    rlock2 = threading.RLock()
    fact5 = factorial(5, rlock2)
    print(f"recursive factorial(5) under an RLock = {fact5}  "
          "(acquired 5 nested times, no self-deadlock)")
    print()

    check("recursive function under RLock returns the right value "
          "(factorial(5)==120)", fact5 == 120)


# ----------------------------------------------------------------------------
# Section F — Queue: a thread-safe channel (no explicit lock needed)
# ----------------------------------------------------------------------------

def section_f_queue_producer_consumer() -> None:
    banner("F — Queue: a thread-safe channel (no explicit lock needed)")
    print("queue.Queue implements ALL the locking internally, so producer and")
    print("consumer threads can put()/get() freely without a single Lock in")
    print("your code. put() blocks when full; get() blocks when empty; join()")
    print("blocks until every item is task_done()'d. This is the idiomatic")
    print("way to hand work between threads.\n")

    q: queue.Queue[int] = queue.Queue()
    produced = list(range(20))
    consumed: list[int] = []

    def producer() -> None:
        for item in produced:
            q.put(item)
        q.put(None)              # sentinel: "no more work"

    def consumer() -> None:
        while True:
            item = q.get()
            if item is None:
                q.task_done()
                break
            consumed.append(item * 10)
            q.task_done()

    p = threading.Thread(target=producer)
    c = threading.Thread(target=consumer)
    p.start()
    c.start()
    q.join()                     # all submitted tasks processed
    p.join()
    c.join()
    expected = [i * 10 for i in produced]
    print(f"produced {len(produced)} items; consumed {len(consumed)}.")
    print(f"first 5 consumed: {consumed[:5]}")
    print(f"consumed == [i*10 for i in range(20)]: {consumed == expected}")
    print()

    check("Queue transferred all 20 items", len(consumed) == 20)
    check("Queue preserved content (consumed == [i*10 for i in range(20)])",
          consumed == expected)
    check("queue is empty after the pipeline drained", q.empty())


# ----------------------------------------------------------------------------
# Section G — Where the GIL is released; PEP 703 (free-threaded future)
# ----------------------------------------------------------------------------

def section_g_where_gil_released() -> None:
    banner("G — Where the GIL is released; PEP 703 (free-threaded future)")
    gil = _gil_enabled()
    print("The GIL is released around BLOCKING operations so other threads can")
    print("run Python bytecode while one thread waits:")
    print("  - I/O:  time.sleep, socket.recv, file.read, select, ...")
    print("  - some C extensions doing heavy CPU work (numpy, zlib, hashing)")
    print("    explicitly drop the GIL for the duration of the C call.")
    print("This is WHY I/O-bound threading works (Section B) and why CPU-bound")
    print("pure-Python threading does not (the GIL returns between bytecodes).")
    print()
    print("The GIL exists because CPython manages memory with reference")
    print("COUNTING (see MEMORY_MODEL): every PyObject has a refcount, and")
    print("making every refcount bump atomic was historically too slow, so a")
    print("single interpreter lock serializes bytecode and keeps refcounts")
    print("safe. (Free-threaded builds make those refcount ops atomic instead.)")
    print()

    cfg = sysconfig.get_config_var("Py_GIL_DISABLED")
    print(f"sysconfig Py_GIL_DISABLED = {cfg!r}  "
          "(0/None = standard GIL build; 1 = free-threaded)")
    print(f"runtime GIL enabled        = {gil}")
    print("PEP 703 (Python 3.13+) makes a free-threaded / no-GIL build an")
    print("option (--disable-gil); on it, threads CAN run bytecode in parallel.")
    print("Until free-threading is the default, use multiprocessing for real")
    print("CPU parallelism (see MULTIPROCESSING) and asyncio for massive I/O")
    print("concurrency on one thread (see ASYNCIO).")
    print()

    check("GIL-status probe returns a bool", isinstance(gil, bool))
    check("a standard (non-free-threaded) build has the GIL on",
          (not cfg and gil) or bool(cfg))


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("threading_gil.py — Phase 3 bundle #19.\n"
          "Every value below is computed by this file; the .md guide pastes "
          "it\nverbatim. Nothing is hand-computed. Threading timing is\n"
          "nondeterministic, so [check] asserts are on STRUCTURAL invariants;\n"
          "wall-clock figures are illustrative and vary by machine/run.\n"
          f"Python {sys.version.split()[0]} on this machine. "
          f"GIL enabled = {_gil_enabled()}.")
    section_a_thread_basics()
    section_b_gil_cpu_and_io()
    section_c_the_race()
    section_d_lock_fixes_it()
    section_e_rlock_reentrancy()
    section_f_queue_producer_consumer()
    section_g_where_gil_released()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
