"""
gc_weakrefs.py — Phase 3 bundle #17.

GOAL (one line): show, by printing every value, that CPython frees objects by
reference counting, that a separate cyclic garbage collector breaks reference
cycles refcounting alone cannot free, and that weak references let you hold a
handle without keeping the referent alive.

This is the GROUND TRUTH for GC_WEAKREFS.md. Every number, table, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

Run:
    uv run python gc_weakrefs.py

All collections are FORCED via gc.collect() so the output is deterministic and
byte-reproducible (we never rely on the automatic collector's timing).
"""

from __future__ import annotations

import gc
import sys
import tracemalloc
import weakref

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers (house style, copied from the style anchor)
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
# Section A — refcounting frees on the last strong-ref delete
# ----------------------------------------------------------------------------

class Tracked:
    """A tiny object whose life cycle we can observe through a weakref."""

    pass


def section_a_refcount_frees_immediately() -> None:
    banner("A — Refcounting: deleting the last strong ref frees immediately")
    print("CPython is refcount-FIRST. Every object carries an ob_refcnt; when")
    print("the count hits 0 the object is freed *at that instant* (no pause,")
    print("no sweep). We watch the death through a weakref.ref handle, which")
    print("returns the object while alive and None once it is gone.\n")

    obj = Tracked()
    ref = weakref.ref(obj)
    print(f"sys.getrefcount(obj) (live, 2 refs: 'obj' + getrefcount arg): "
          f"{sys.getrefcount(obj)}")
    print(f"ref() is obj  (weakref resolves while alive): {ref() is obj}")
    print("del obj  -> ob_refcnt drops to 0 -> CPython frees it now")
    del obj
    print(f"ref() after del  (the weakref no longer resolves): {ref()}")
    print()

    check("weakref returns the object while it is alive",
          _make_alive_weakref_resolves())
    check("after del, the weakref returns None (object was freed)",
          _make_dead_weakref_returns_none())


def _make_alive_weakref_resolves() -> bool:
    o = Tracked()
    r = weakref.ref(o)
    return r() is o  # `o` alive -> r() resolves to the same object


def _make_dead_weakref_returns_none() -> bool:
    o = Tracked()
    r = weakref.ref(o)
    del o
    return r() is None  # `o` dead -> r() returns None


# ----------------------------------------------------------------------------
# Section B — a reference cycle is NOT freed by refcounting alone
# ----------------------------------------------------------------------------

class Cycle:
    """Holds one attribute so we can build `a.x = b; b.x = a`."""

    pass


def section_b_cycle_needs_gc() -> None:
    banner("B — A reference cycle survives del; gc.collect() frees it")
    print("Two objects that point at each other form a CYCLE. After `del a,")
    print("del b`, neither ob_refcnt reaches 0 — each still has one reference")
    print("(from the other). Refcounting alone cannot free them. The cyclic")
    print("GC must step in. We force it deterministically with gc.collect().\n")

    a = Cycle()
    b = Cycle()
    a.x = b  # a holds a strong ref to b
    b.x = a  # b holds a strong ref to a  ->  cycle
    ra = weakref.ref(a)
    rb = weakref.ref(b)
    print(f"cycle built: a.x is b -> {a.x is b}; b.x is a -> {b.x is a}")
    print("del a, del b  (only the names go away; the objects keep each other)")
    del a
    del b
    print(f"ra() right after del  (NOT None -> still alive): "
          f"{ra() is not None}")
    print(f"rb() right after del  (NOT None -> still alive): "
          f"{rb() is not None}")
    collected = gc.collect()  # force a full collection
    print(f"gc.collect() returned (objects freed): {collected}")
    print(f"ra() after gc.collect()  (None -> freed): {ra()}")
    print(f"rb() after gc.collect()  (None -> freed): {rb()}")
    print()

    check("cycle objects survive del of both names (refcount can't break it)",
          _make_cycle_survives_del())
    check("after gc.collect(), the cycle is gone (weakrefs return None)",
          _make_cycle_freed_after_collect())


def _make_cycle_survives_del() -> bool:
    a = Cycle()
    b = Cycle()
    a.x = b
    b.x = a
    ra = weakref.ref(a)
    del a, b
    return ra() is not None


def _make_cycle_freed_after_collect() -> bool:
    a = Cycle()
    b = Cycle()
    a.x = b
    b.x = a
    ra = weakref.ref(a)
    del a, b
    gc.collect()
    return ra() is None


# ----------------------------------------------------------------------------
# Section C — gc generations (0, 1, 2), thresholds, collect()
# ----------------------------------------------------------------------------

def section_c_generations_and_thresholds() -> None:
    banner("C — gc generations, thresholds, and forced collection")
    print("The cyclic GC groups tracked objects into three GENERATIONS. New")
    print("objects enter gen 0; survivors are promoted to gen 1 then gen 2.")
    print("Younger generations are collected more often. Collection runs")
    print("automatically when (allocations - deallocations) > threshold0; you")
    print("can also force it with gc.collect(generation).\n")

    gc.collect()  # start from a clean slate
    print(f"gc.get_threshold()  (default thresholds t0, t1, t2): "
          f"{gc.get_threshold()}")
    print(f"gc.get_count()     (current counts c0, c1, c2):      "
          f"{gc.get_count()}")
    print(f"gc.isenabled()     (automatic cyclic GC on?):        {gc.isenabled()}")
    print()

    # Demonstrate promotion: force two gen-0 collections and observe c0 reset.
    before = gc.get_count()
    gc.collect(0)  # collect ONLY generation 0
    after_gen0 = gc.get_count()
    gc.collect(1)  # collect generations 0 + 1
    after_gen1 = gc.get_count()
    gc.collect(2)  # full collection (all three generations)
    after_gen2 = gc.get_count()
    print(f"counts before any forced collect:  {before}")
    print(f"after gc.collect(0) [gen 0 only]:  {after_gen0}")
    print(f"after gc.collect(1) [gen 0 + 1]:   {after_gen1}")
    print(f"after gc.collect(2) [full sweep]:  {after_gen2}")
    print()

    # gc.disable() / gc.enable() — turn the automatic cyclic GC off / on.
    # Refcounting still happens; only the CYCLIC GC is toggled.
    gc.disable()
    disabled = gc.isenabled()
    gc.enable()
    reenabled = gc.isenabled()
    print(f"gc.disable(); gc.isenabled() -> {disabled}")
    print(f"gc.enable();  gc.isenabled() -> {reenabled}")
    print()

    check("gc.get_threshold() returns a 3-tuple (t0, t1, t2)",
          isinstance(gc.get_threshold(), tuple) and len(gc.get_threshold()) == 3)
    check("gc.collect(0) resets the gen-0 count to a small value",
          after_gen0[0] < before[0])
    check("gc.disable() turns the automatic collector off",
          disabled is False)
    check("gc.enable() turns it back on", reenabled is True)


# ----------------------------------------------------------------------------
# Section D — weakref.ref: a handle that does not keep the object alive
# ----------------------------------------------------------------------------

def section_d_weakref_ref() -> None:
    banner("D — weakref.ref: a soft pointer that does not add to the refcount")
    print("weakref.ref(obj) returns a *callable* handle. Calling it returns")
    print("obj while obj is alive, and None once obj has been collected. The")
    print("weakref itself does NOT increment obj's ob_refcnt — that is the")
    print("whole point: you can hold a handle without keeping the object alive.\n")

    obj = Tracked()
    before = sys.getrefcount(obj)  # baseline (obj + the getrefcount arg)
    ref = weakref.ref(obj)
    after = sys.getrefcount(obj)
    print(f"sys.getrefcount(obj) before weakref: {before}")
    print(f"sys.getrefcount(obj) after  weakref: {after}")
    print("(unchanged -> the weakref did NOT add a strong reference)")
    print(f"ref() is obj  (handle resolves while alive): {ref() is obj}")
    del obj
    print(f"ref() after del obj  (handle resolves to None): {ref()}")
    print()

    check("creating a weakref does not change the strong refcount",
          before == after)
    check("weakref resolves to the object while it is alive",
          _make_weakref_alive_resolves())


def _make_weakref_alive_resolves() -> bool:
    o = Tracked()
    r = weakref.ref(o)
    alive = r() is o
    del o
    return alive


# ----------------------------------------------------------------------------
# Section E — WeakValueDictionary: a cache that auto-evicts dead values
# ----------------------------------------------------------------------------

class Image:
    """Stand-in for a large, weak-referenceable cached value."""

    pass


def section_e_weakvaluedictionary() -> None:
    banner("E — WeakValueDictionary: values auto-evict when their last strong "
           "ref dies")
    print("A WeakValueDictionary holds weak refs to its VALUES. When the last")
    print("strong ref to a value disappears (and the cyclic GC notices), the")
    print("entry is silently dropped. Perfect for caches keyed by something")
    print("else — the cache never keeps a big object alive on its own.\n")

    cache: weakref.WeakValueDictionary[str, Image] = weakref.WeakValueDictionary()
    img = Image()
    cache["thumbnail"] = img
    print(f"cache['thumbnail'] = img; 'thumbnail' in cache -> "
          f"{'thumbnail' in cache}")
    print(f"cache['thumbnail'] is img -> {cache['thumbnail'] is img}")
    print("del img  (the only strong ref)")
    del img
    gc.collect()  # ensure the value is reaped & the entry evicted
    still_there = "thumbnail" in cache
    print(f"gc.collect(); 'thumbnail' in cache -> {still_there}")
    print()

    # WeakSet behaves the same way for unordered membership.
    bucket: weakref.WeakSet[Image] = weakref.WeakSet()
    one = Image()
    bucket.add(one)
    in_set_before = one in bucket
    del one
    gc.collect()
    in_set_after = len(bucket) == 0
    print(f"bucket.add(one); 'one in bucket' before del -> {in_set_before}")
    print(f"del one + gc.collect(); bucket empty -> {in_set_after}")
    print()

    check("WeakValueDictionary entry present while strong ref exists",
          _make_wvd_present_while_alive())
    check("WeakValueDictionary entry vanishes after value is collected",
          not _make_wvd_present_while_dead())
    check("WeakSet drops the element once its strong ref dies",
          in_set_after)


def _make_wvd_present_while_alive() -> bool:
    cache: weakref.WeakValueDictionary[str, Image] = weakref.WeakValueDictionary()
    img = Image()
    cache["k"] = img
    present = "k" in cache
    del img
    return present


def _make_wvd_present_while_dead() -> bool:
    cache: weakref.WeakValueDictionary[str, Image] = weakref.WeakValueDictionary()
    img = Image()
    cache["k"] = img
    del img
    gc.collect()
    return "k" in cache  # True would mean the entry is STILL there -> bug


# ----------------------------------------------------------------------------
# Section F — __del__ pitfalls vs weakref.finalize
# ----------------------------------------------------------------------------

class WithDel:
    """Demonstrates the discouraged __del__ path."""

    def __del__(self) -> None:
        # Side effect we can observe. (PEP 442 made this safe inside cycles,
        # but it is still discouraged for resource cleanup.)
        pass


def section_f_del_pitfalls_and_finalize() -> None:
    banner("F — __del__ pitfalls and the weakref.finalize alternative")
    print("Before PEP 442, an object with __del__ inside a reference cycle was")
    print("UNCOLLECTABLE and leaked into gc.garbage. PEP 442 (Python 3.4+) made")
    print("__del__ safe in cycles by calling finalizers *before* breaking the")
    print("cycle and re-checking reachability. Even so, __del__ is fragile")
    print("(exception swallowing, interpreter-shutdown ordering, resurrection")
    print("hazards). For resource cleanup, prefer a context manager or")
    print("weakref.finalize.\n")

    # weakref.finalize registers a callback to fire when obj is collected.
    fired: list[str] = []

    victim = Tracked()
    fin = weakref.finalize(victim, fired.append, "victim finalized")
    print(f"fin.alive before del -> {fin.alive}")
    del victim
    print(f"fin.alive after  del -> {fin.alive}")
    print(f"callback fired with: {fired}")
    print()

    # Demonstrating that a __del__ object in a cycle IS collectible today
    # (PEP 442). We watch through a weakref.
    a = WithDel()
    b = WithDel()
    a.x = b
    b.x = a
    ra = weakref.ref(a)
    del a, b
    gc.collect()
    pep442_collectible = ra() is None
    print(f"WithDel object in a cycle, freed after gc.collect() -> "
          f"{pep442_collectible}")
    print("(pre-PEP-442 this leaked into gc.garbage; PEP 442 fixed it)")
    print()

    check("weakref.finalize callback fires exactly once on collection",
          fired == ["victim finalized"])
    check("after firing, fin.alive is False", not fin.alive)
    check("PEP 442: __del__ objects in a cycle ARE collectible now",
          pep442_collectible)


# ----------------------------------------------------------------------------
# Section G — tracemalloc: where did the memory go?
# ----------------------------------------------------------------------------

def section_g_tracemalloc() -> None:
    banner("G — tracemalloc: snapshot where allocations come from")
    print("tracemalloc traces Python-level memory blocks. You take a snapshot")
    print("before and after a workload, then compare to see which lines of")
    print("code allocated (or freed) the most memory.\n")

    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()

    # A tiny workload: allocate a list of fresh strings.
    payload = [f"row-{i}-payload" for i in range(50_000)]
    snap_after = tracemalloc.take_snapshot()

    top = snap_after.compare_to(snap_before, "lineno")[:3]
    print("workload: 50_000 fresh str objects in a list")
    print(f"len(payload) -> {len(payload)}")
    print(f"payload[0] -> {payload[0]!r}")
    print("\ntop 3 allocation diffs (compare_to(snap_before, 'lineno')):")
    for stat in top:
        frame = stat.traceback[0]
        print(f"  {frame.filename.rsplit('/', 1)[-1]}:{frame.lineno} "
              f"size_diff={stat.size_diff} count_diff={stat.count_diff}")

    current, peak = tracemalloc.get_traced_memory()
    print(f"\ntracemalloc.get_traced_memory() -> "
          f"current={current}, peak={peak}")
    tracemalloc.stop()
    del payload
    print()

    check("tracemalloc recorded allocations from this file",
          any("gc_weakrefs.py" in str(s.traceback[0].filename) for s in top))
    check("the workload allocated non-zero memory (current > 0)",
          current > 0)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("gc_weakrefs.py — Phase 3 bundle #17.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {sys.version.split()[0]} on this machine.")
    section_a_refcount_frees_immediately()
    section_b_cycle_needs_gc()
    section_c_generations_and_thresholds()
    section_d_weakref_ref()
    section_e_weakvaluedictionary()
    section_f_del_pitfalls_and_finalize()
    section_g_tracemalloc()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
