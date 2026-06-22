"""
profiling_optimization.py — Phase 4 bundle #24.

GOAL (one line): show, by running real profiles and timers, that measuring
beats guessing — cProfile finds the hot function, timeit measures a snippet,
lru_cache memoizes by args, and algorithmic (Big-O) wins dominate over
micro-optimization every time.

This is the GROUND TRUTH for PROFILING_OPTIMIZATION.md. Every number, table,
and profile dump in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Timing digits are ILLUSTRATIVE (they vary per run / machine / load). We assert
only STRUCTURAL and RELATIVE facts (the optimized version is faster; lru_cache
shrinks the call count; the profile lists the expected functions) — never
absolute microseconds.

Run:
    uv run python profiling_optimization.py
"""

from __future__ import annotations

import cProfile
import dis
import io
import pstats
import timeit
from functools import lru_cache
from pstats import SortKey

BANNER = "=" * 70
_ILLUSTRATIVE = "(varies per run)"


# ----------------------------------------------------------------------------
# pretty printers (house style)
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


# ----------------------------------------------------------------------------
# the workload: naive recursive fibonacci (exponential call count)
# ----------------------------------------------------------------------------

_naive_calls = 0


def fib_naive(n: int) -> int:
    """Naive recursive fibonacci — O(2^n) calls. THE profiling workload."""
    global _naive_calls
    _naive_calls += 1
    if n < 2:
        return n
    return fib_naive(n - 1) + fib_naive(n - 2)


@lru_cache(maxsize=None)
def fib_cached(n: int) -> int:
    """Memoized fibonacci — O(n) calls thanks to @lru_cache."""
    if n < 2:
        return n
    return fib_cached(n - 1) + fib_cached(n - 2)


# A module-level GLOBAL (NOT a closure cell) so loop_global accesses it via
# LOAD_GLOBAL rather than LOAD_DEREF. Used in Section G.
_GVAR = 1


# ----------------------------------------------------------------------------
# Section A — the "measure don't guess" law
# ----------------------------------------------------------------------------

def section_a_measure_dont_guess() -> None:
    banner("A — The 'measure don't guess' law")
    print("Knuth (1974): 'We should forget about small efficiencies, say about")
    print("97% of the time: premature optimization is the root of all evil. Yet")
    print("we should not pass up our opportunities in that critical 3%.'")
    print()
    print("THE LAW: profile BEFORE optimizing. Intuition about WHERE time goes")
    print("is usually wrong. The disciplined loop is:")
    print()
    print("    profile -> find hot function -> optimize -> RE-MEASURE")
    print()
    print("Workload for this bundle: naive recursive fib(20). Before reading the")
    print("profile in Section B, GUESS how many calls fib_naive(20) makes. The")
    print("answer is printed below — almost nobody intuits the blow-up.")
    print()
    global _naive_calls
    _naive_calls = 0
    fib_naive(20)
    print(f"fib_naive(20) made {_naive_calls} function calls to compute ONE value.")
    print("That exponential call count IS the hotspot — and only a profile")
    print("makes it obvious. Guessing would have you optimize the wrong thing.")
    print()
    check("fib_naive(20) makes over 20_000 calls (exponential blow-up)",
          _naive_calls > 20_000)


# ----------------------------------------------------------------------------
# Section B — cProfile a workload + pstats top functions
# ----------------------------------------------------------------------------

def section_b_cprofile_workload() -> None:
    banner("B — cProfile a workload + pstats top functions")
    print("cProfile is a DETERMINISTIC profiler: it instruments every function")
    print("call/return and records precise timings. We profile fib_naive(20) and")
    print("print the top functions two ways — by CUMULATIVE time (call-tree")
    print("cost) and by TOTTIME (time inside the function itself).")
    print()
    pr = cProfile.Profile()
    pr.enable()
    fib_naive(20)
    pr.disable()

    print("--- top 8 by CUMULATIVE time (incl. subcalls) ---")
    s = io.StringIO()
    pstats.Stats(pr, stream=s).strip_dirs().sort_stats(
        SortKey.CUMULATIVE).print_stats(8)
    print(s.getvalue())

    print("--- top 8 by TOTTIME (time IN this function) ---")
    s2 = io.StringIO()
    pstats.Stats(pr, stream=s2).strip_dirs().sort_stats(
        SortKey.TIME).print_stats(8)
    print(s2.getvalue())

    ps = pstats.Stats(pr).strip_dirs()
    fib_key = [k for k in ps.stats if "fib_naive" in k[2]]
    ncalls = ps.stats[fib_key[0]][1] if fib_key else 0
    print(f"pstats reports fib_naive ncalls = {ncalls}")
    print()
    check("'fib_naive' appears in the profiled function set", bool(fib_key))
    check("profiled ncalls is large (>20_000, the exponential cost)",
          ncalls > 20_000)


# ----------------------------------------------------------------------------
# Section C — reading pstats columns: ncalls / tottime / cumtime
# ----------------------------------------------------------------------------

def section_c_reading_pstats_columns() -> None:
    banner("C — Reading pstats columns: ncalls / tottime / cumtime")
    print("Every pstats row has five timing columns. The two that matter most:")
    print()
    print(f"{'column':<10}{'meaning'}")
    print("-" * 68)
    print(f"{'ncalls':<10}times the function was called (total/primitive if recursive)")
    print(f"{'tottime':<10}time IN the function, EXCLUDING subcalls")
    print(f"{'percall':<10}tottime / ncalls")
    print(f"{'cumtime':<10}time in the function PLUS all subcalls it made")
    print(f"{'percall':<10}cumtime / primitive calls")
    print()
    print("RULE: optimize the high-TOTTIME function (where the CPU burns).")
    print("CUMTIME shows the call-tree cost (which entry point to attack).")
    print()
    pr = cProfile.Profile()
    pr.enable()
    fib_naive(15)
    pr.disable()
    ps = pstats.Stats(pr).strip_dirs()
    fib_key = [k for k in ps.stats if "fib_naive" in k[2]][0]
    cc, nc, tt, ct, _callers = ps.stats[fib_key]
    print("For fib_naive(15) from the profile:")
    print(f"  primitive calls (cc) = {cc}")
    print(f"  total calls (nc)     = {nc}")
    print(f"  tottime              = {tt:.6f} s  {_ILLUSTRATIVE}")
    print(f"  cumtime              = {ct:.6f} s  {_ILLUSTRATIVE}")
    print(f"  cumtime >= tottime  -> {ct >= tt}  (the excess is recursive subcalls)")
    print()
    check("total calls (nc) >= primitive calls (cc) always", nc >= cc)
    check("cumtime >= tottime always holds", ct >= tt)
    check("fib_naive(15) total calls is large (recursion)", nc > 1000)


# ----------------------------------------------------------------------------
# Section D — timeit: set membership O(1) beats list membership O(n)
# ----------------------------------------------------------------------------

def section_d_timeit_set_vs_list() -> None:
    banner("D — timeit: set membership O(1) beats list membership O(n)")
    print("timeit measures a tiny snippet many times with minimal overhead")
    print("(default timer = time.perf_counter; GC is suspended during timing).")
    print("We search for a MISSING needle (-1) in a list vs a set of 100_000")
    print("ints. List membership scans all n elements (O(n)); set membership is")
    print("a hash lookup (O(1)). Per docs, take min() of repeat() — the minimum")
    print("is the only meaningful number (higher values are noise/interference).")
    print()
    setup = "lst = list(range(100_000)); st = set(lst); needle = -1"
    n_list, n_set = 30, 200_000
    t_list_per = min(timeit.repeat(
        "needle in lst", setup=setup, number=n_list, repeat=5)) / n_list
    t_set_per = min(timeit.repeat(
        "needle in st", setup=setup, number=n_set, repeat=5)) / n_set
    ratio = t_list_per / t_set_per if t_set_per else float("inf")
    print(f"list 'needle in lst': best per-op = {t_list_per*1e6:8.2f} us  {_ILLUSTRATIVE}")
    print(f"set  'needle in st':  best per-op = {t_set_per*1e9:8.1f} ns  {_ILLUSTRATIVE}")
    print(f"list is ~{ratio:.0f}x slower than set for a missing element")
    print()
    check("set membership faster than list membership for large n",
          t_set_per < t_list_per)
    check("the set-vs-list gap is large (ratio > 10x)", ratio > 10)


# ----------------------------------------------------------------------------
# Section E — lru_cache: exponential fib -> linear (call-count proof)
# ----------------------------------------------------------------------------

def section_e_lru_cache() -> None:
    banner("E — lru_cache: exponential fib -> linear (call-count proof)")
    print("@lru_cache memoizes by arguments: each distinct arg tuple is computed")
    print("once; later calls are O(1) dict lookups. We reset the manual counter,")
    print("run naive fib(20); then run cached fib(20) on a fresh cache and read")
    print("cache_info() -> (hits, misses, maxsize, currsize).")
    print()
    global _naive_calls
    _naive_calls = 0
    naive_result = fib_naive(20)
    naive_count = _naive_calls

    fib_cached.cache_clear()
    cached_result = fib_cached(20)
    info = fib_cached.cache_info()
    cached_total = info.hits + info.misses

    print(f"fib_naive(20)  = {naive_result}   calls = {naive_count}")
    print(f"fib_cached(20) = {cached_result}  cache_info = {info}")
    print(f"naive made {naive_count} calls; cached made {cached_total} calls "
          f"({info.misses} misses + {info.hits} hits).")
    print()
    check("both versions compute the same fib(20)",
          naive_result == cached_result == 6765)
    check("cached total calls (hits+misses) << naive count",
          cached_total < naive_count)
    check("cached misses == 21 (fib(0)..fib(20) computed once each)",
          info.misses == 21)
    check("cache currsize == 21 (one entry per distinct arg)",
          info.currsize == 21)


# ----------------------------------------------------------------------------
# Section F — algorithmic wins: O(n) formula beats O(n^2) loop
# ----------------------------------------------------------------------------

def section_f_algorithmic_wins() -> None:
    banner("F — Algorithmic wins: O(n) formula beats O(n^2) loop")
    print("Big-O dominates constant factors. Counting unordered pairs in")
    print("range(n): an O(n^2) double loop vs the O(n) closed form n*(n-1)//2.")
    print("Both give the same answer; the formula is vastly faster for large n.")
    print("This is WHY algorithms matter more than micro-optimizing a bad one.")
    print()
    n = 4000

    def count_pairs_on2(m: int) -> int:
        c = 0
        for i in range(m):
            for j in range(i + 1, m):
                c += 1
        return c

    def count_pairs_formula(m: int) -> int:
        return m * (m - 1) // 2

    loop_result = count_pairs_on2(n)
    formula_result = count_pairs_formula(n)
    t_loop = min(timeit.repeat(lambda: count_pairs_on2(n), number=1, repeat=3))
    t_formula = min(timeit.repeat(
        lambda: count_pairs_formula(n), number=10_000, repeat=3)) / 10_000
    print(f"n = {n}: O(n^2) loop     count = {loop_result}   "
          f"best = {t_loop*1e3:.2f} ms  {_ILLUSTRATIVE}")
    print(f"n = {n}: O(n)   formula  count = {formula_result}   "
          f"best = {t_formula*1e9:.1f} ns  {_ILLUSTRATIVE}")
    print()
    check("O(n^2) loop and O(n) formula agree on the count",
          loop_result == formula_result)
    check("the O(n) formula is faster than the O(n^2) loop",
          t_formula < t_loop)


# ----------------------------------------------------------------------------
# Section G — micro-optimization pitfalls: locals, readability, premature opt
# ----------------------------------------------------------------------------

def section_g_micro_optimization_pitfalls() -> None:
    banner("G — Micro-optimization pitfalls: locals, readability, premature opt")
    print("'Locals are faster than globals' — TRUE, but only in HOT loops. A")
    print("global is LOAD_GLOBAL (dict lookup by name each access); a local is")
    print("LOAD_FAST (array slot). The bytecode (dis) reveals why; the timing")
    print("shows the payoff. The speedup is real but SMALL — apply it ONLY to a")
    print("measured hotspot, never at the cost of readability.")
    print()

    def loop_global(k: int) -> int:
        acc = 0
        for _ in range(k):
            acc += _GVAR  # LOAD_GLOBAL every iteration (module global)
        return acc

    def loop_local(k: int) -> int:
        g_local = _GVAR  # bind the global to a local ONCE -> LOAD_FAST in loop
        acc = 0
        for _ in range(k):
            acc += g_local  # LOAD_FAST every iteration
        return acc

    # Programmatic bytecode check (deterministic, version-stable).
    g_ops = [ins for ins in dis.get_instructions(loop_global)
             if ins.opname == "LOAD_GLOBAL" and ins.argval == "_GVAR"]
    l_ops = [ins for ins in dis.get_instructions(loop_local)
             if ins.opname.startswith("LOAD_FAST")
             and "g_local" in ins.argrepr]
    print("--- loop_global: how _GVAR is accessed inside the loop ---")
    for ins in g_ops:
        print(f"    {ins.opname:<20} {ins.argrepr}")
    print("--- loop_local: how g_local is accessed inside the loop ---")
    for ins in l_ops:
        print(f"    {ins.opname:<20} {ins.argrepr}")
    print()

    k = 200_000
    t_g = min(timeit.repeat(lambda: loop_global(k), number=3, repeat=3)) / 3
    t_l = min(timeit.repeat(lambda: loop_local(k), number=3, repeat=3)) / 3
    print(f"loop_global({k}): best/iter = {t_g*1e3:.2f} ms  {_ILLUSTRATIVE}")
    print(f"loop_local({k}):  best/iter = {t_l*1e3:.2f} ms  {_ILLUSTRATIVE}")
    print()
    check("loop_global and loop_local return the same value",
          loop_global(k) == loop_local(k))
    check("loop_global accesses _GVAR via LOAD_GLOBAL", bool(g_ops))
    check("loop_local accesses g_local via LOAD_FAST", bool(l_ops))
    print("LESSON: profile first. Bind globals to locals ONLY inside a measured")
    print("hot loop — readability beats a guessed micro-win the other 97% of the time.")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("profiling_optimization.py — Phase 4 bundle #24.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Timing digits are ILLUSTRATIVE (vary per run); we assert\n"
          "only structural / relative facts. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_measure_dont_guess()
    section_b_cprofile_workload()
    section_c_reading_pstats_columns()
    section_d_timeit_set_vs_list()
    section_e_lru_cache()
    section_f_algorithmic_wins()
    section_g_micro_optimization_pitfalls()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
