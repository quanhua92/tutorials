"""
multiprocessing_basics.py — Bundle #20 (Phase 3).

GOAL (one line): show, by printing every value, how multiprocessing sidesteps
the GIL with separate OS processes that get true parallelism — at the cost of
no shared memory and picklable args.

This is the GROUND TRUTH for MULTIPROCESSING_BASICS.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python multiprocessing_basics.py
"""

from __future__ import annotations

import multiprocessing as mp
import os

BANNER = "=" * 70

# -- module-level state (spawn-safe: children re-import this module) --------

_GLOBAL_COUNTER = 0        # Section D: child mutates, parent must NOT see it.
_MARKER = "import-time"    # Section F: spawn resets (re-import); fork copies.


# -- workers (MUST live at module scope so `spawn` can import them) ----------

def _worker_compute(q, n):
    """Square *n* and put (n*n, child pid) on the queue (Section A)."""
    q.put((n * n, os.getpid()))


def _cpu_partial(start, stop, q):
    """Sum range(start, stop); put (partial_sum, pid) on the queue (Section B)."""
    total = 0
    for i in range(start, stop):
        total += i
    q.put((total, os.getpid()))


def _square(x):
    """Trivial pure function for Pool.map (Sections C and G)."""
    return x * x


def _mutate_global():
    """Set the module global — invisible to the parent (Section D)."""
    global _GLOBAL_COUNTER  # noqa: PLW0603
    _GLOBAL_COUNTER = 999


def _increment_shared(counter, lock, times):
    """Increment a shared Value under a Lock, *times* times (Section E)."""
    with lock:
        for _ in range(times):
            counter.value += 1


def _read_marker(q):
    """Put _MARKER on the queue — shows fork-vs-spawn difference (Section F)."""
    q.put(_MARKER)


# -- pretty printers (house style) -------------------------------------------

def banner(title: str) -> None:
    """Print a clearly delimited section divider (the house style)."""
    print("\n" + BANNER)
    print(f"SECTION {title}")
    print(BANNER)


def check(description: str, condition: bool) -> None:
    """Assert an invariant and print a uniform [check] ... OK line."""
    assert condition, f"INVARIANT VIOLATED: {description}"
    print(f"[check] {description}: OK")


# -- sections ----------------------------------------------------------------

def section_a_process_basics() -> None:
    banner("A — Process basics: start/join; result via Queue")
    print("multiprocessing.Process(target, args) starts a NEW OS process.")
    print("start() launches it; join() waits for it. A child's RETURN value")
    print("does NOT cross the process boundary — use a Queue to get data back.\n")

    parent_pid = os.getpid()
    q: mp.Queue = mp.Queue()
    p = mp.Process(target=_worker_compute, args=(q, 7))
    p.start()
    result, child_pid = q.get()
    p.join()

    print(f"parent pid:   {parent_pid}")
    print(f"child pid:    {child_pid}")
    print(f"child computed 7*7 = {result}  (received via Queue)")
    check("worker ran and returned 7*7 == 49 via Queue", result == 49)
    check("child pid differs from parent pid", child_pid != parent_pid)
    check("process exited cleanly (exitcode == 0)", p.exitcode == 0)


def section_b_real_parallelism() -> None:
    banner("B — Real parallelism: N processes, distinct pids, correct sum")
    print("Each process is a separate OS process with its OWN Python interpreter")
    print("and its OWN GIL. Four processes doing pure-Python CPU work run on up")
    print("to four cores simultaneously — true parallelism, unlike threads.\n")

    CHUNK = 500_000
    N_PROC = 4
    TOTAL = CHUNK * N_PROC

    serial_sum = sum(range(TOTAL))

    q: mp.Queue = mp.Queue()
    procs = []
    for i in range(N_PROC):
        lo, hi = i * CHUNK, (i + 1) * CHUNK
        p = mp.Process(target=_cpu_partial, args=(lo, hi, q))
        p.start()
        procs.append(p)
    results = [q.get() for _ in range(N_PROC)]
    for p in procs:
        p.join()

    partial_sums = sorted(r[0] for r in results)
    pids = sorted(r[1] for r in results)
    parallel_sum = sum(partial_sums)

    print(f"serial sum of range({TOTAL}):       {serial_sum}")
    print(f"parallel sum ({N_PROC} chunks of {CHUNK}):   {parallel_sum}")
    print(f"partial sums (sorted): {partial_sums}")
    print(f"distinct child pids: {len(set(pids))} of {N_PROC}")
    check("parallel sum equals serial sum", parallel_sum == serial_sum)
    check("each process had a distinct pid", len(set(pids)) == N_PROC)
    check("no child pid equals parent pid", os.getpid() not in set(pids))


def section_c_pool_map() -> None:
    banner("C — Pool.map: parallel work, results in input order")
    print("Pool manages a set of worker processes. Pool.map(f, iterable)")
    print("distributes work across the pool but returns results IN INPUT ORDER")
    print("(unlike imap_unordered).\n")

    inputs = list(range(10))
    with mp.Pool(4) as pool:
        parallel = pool.map(_square, inputs)
    serial = [_square(x) for x in inputs]

    print(f"inputs:           {inputs}")
    print(f"Pool.map result:  {parallel}")
    print(f"serial listcomp:  {serial}")
    check("Pool.map results equal serial computation", parallel == serial)
    check("Pool.map preserves input order even though work is parallel",
          parallel == [0, 1, 4, 9, 16, 25, 36, 49, 64, 81])


def section_d_no_shared_memory() -> None:
    banner("D — No shared memory by default: child's global change is invisible")
    print("Each process has its OWN address space. A child that mutates a module")
    print("global changes ITS COPY only — the parent never sees the change.\n")

    print(f"_GLOBAL_COUNTER before child: {_GLOBAL_COUNTER}")
    p = mp.Process(target=_mutate_global)
    p.start()
    p.join()
    print(f"_GLOBAL_COUNTER after child "
          f"(child set its copy to 999): {_GLOBAL_COUNTER}")
    check("parent still sees 0 (separate address space)",
          _GLOBAL_COUNTER == 0)
    check("child exited cleanly (exitcode == 0)", p.exitcode == 0)


def section_e_shared_value_lock() -> None:
    banner("E — Shared Value + Lock: a real cross-process counter")
    print("mp.Value wraps a ctypes value in SHARED MEMORY so all processes see")
    print("the same cell. But counter.value += 1 is a read-MODIFY-write: you")
    print("still need a Lock to avoid lost updates.\n")

    counter = mp.Value("i", 0)
    lock = mp.Lock()
    N_PROC = 4
    PER_PROC = 25_000
    expected = N_PROC * PER_PROC

    procs = [
        mp.Process(target=_increment_shared, args=(counter, lock, PER_PROC))
        for _ in range(N_PROC)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    print(f"{N_PROC} processes x {PER_PROC} increments each "
          f"-> expected total: {expected}")
    print(f"shared counter.value after: {counter.value}")
    check("shared Value+Lock reaches expected total",
          counter.value == expected)


def section_f_start_methods() -> None:
    banner("F — Start methods: spawn (re-import) vs fork (copy parent)")
    print("Three start methods exist. spawn starts a FRESH interpreter and")
    print("re-imports the module (safe, pickles args, slower). fork calls")
    print("os.fork() and copies the parent's memory (fast, POSIX only, unsafe")
    print("with threads). forkserver uses a clean helper server.\n")

    global _MARKER  # noqa: PLW0603
    _MARKER = "set-by-parent-at-runtime"

    all_methods = mp.get_all_start_methods()
    default = mp.get_start_method()
    print(f"available start methods: {all_methods}")
    print(f"default on this platform: {default!r}")
    print()

    # spawn child: re-imports module -> _MARKER resets to import-time value.
    ctx_s = mp.get_context("spawn")
    q_s = ctx_s.SimpleQueue()
    p_s = ctx_s.Process(target=_read_marker, args=(q_s,))
    p_s.start()
    spawn_val = q_s.get()
    p_s.join()

    # fork child: copies parent memory -> _MARKER keeps runtime value.
    ctx_f = mp.get_context("fork")
    q_f = ctx_f.SimpleQueue()
    p_f = ctx_f.Process(target=_read_marker, args=(q_f,))
    p_f.start()
    fork_val = q_f.get()
    p_f.join()

    print(f"spawn child saw _MARKER = {spawn_val!r}  "
          f"(re-imported module -> reset)")
    print(f"fork child saw _MARKER  = {fork_val!r}  "
          f"(copied parent memory -> kept)")
    check("spawn child sees import-time value (re-import resets global)",
          spawn_val == "import-time")
    check("fork child sees parent's runtime value (memory copy)",
          fork_val == "set-by-parent-at-runtime")


def section_g_pickle_requirement() -> None:
    banner("G — The pickle requirement: lambdas cannot cross the boundary")
    print("Every argument AND the target function must be picklable: spawn")
    print("serializes them with pickle to ship them to the child. A lambda")
    print("has no importable qualified name, so pickle cannot locate it.\n")

    error_name = "(no error)"
    try:
        with mp.Pool(2) as pool:
            pool.map(lambda x: x * x, [1, 2, 3])
    except Exception as exc:  # noqa: BLE001
        error_name = type(exc).__name__

    print(f"Pool.map(lambda x: x*x, ...) raised: {error_name}")
    check("lambda to Pool fails (cannot cross process boundary)",
          error_name in ("PicklingError", "AttributeError"))


# -- main --------------------------------------------------------------------

def main() -> None:
    print("multiprocessing_basics.py — Phase 3 bundle #20.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine. "
          f"Default start method: {mp.get_start_method()!r}.")
    section_a_process_basics()
    section_b_real_parallelism()
    section_c_pool_map()
    section_d_no_shared_memory()
    section_e_shared_value_lock()
    section_f_start_methods()
    section_g_pickle_requirement()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
