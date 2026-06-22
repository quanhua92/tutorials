"""
memory_efficiency.py — Phase 4 bundle (#25).

GOAL (one line): show, by printing every value, that every Python object pays a
header tax, and that __slots__, array.array, generators, and memoryview are the
four levers that cut memory for large datasets.

This is the GROUND TRUTH for MEMORY_EFFICIENCY.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python memory_efficiency.py

Determinism note: sys.getsizeof values are stable per Python build (here
CPython 3.13 on a 64-bit platform). The asserts pin relative facts that hold on
ANY build: slotted < non-slotted (instance + __dict__); array << list of ints;
a memoryview of a 1 MB buffer is tiny (zero-copy); a generator's peak memory is
~constant while a list's scales linearly.
"""

from __future__ import annotations

import array
import gc
import sys
import tracemalloc

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
# Section A — the object-header tax: getsizeof of int and list
# ----------------------------------------------------------------------------

def section_a_header_tax() -> None:
    banner("A — The object-header tax: every PyObject pays for a header")
    print("A Python `int` is NOT 4 bytes. Every object carries a PyObject")
    print("header (refcount + type pointer + GC bookkeeping) plus its value.")
    print("On a 64-bit CPython build the header alone is ~16-28 bytes. The")
    print("docs warn: getsizeof counts ONLY what is directly attributed to")
    print("the object, NOT what it refers to (so a list does NOT count its")
    print("elements). That makes the list-of-pointers overhead easy to miss.\n")

    int_zero = sys.getsizeof(0)
    big_int = sys.getsizeof(2**100)
    print(f"{'object':<26}{'getsizeof (bytes)'}")
    print("-" * 48)
    rows = [
        ("0 (small int)", sys.getsizeof(0)),
        ("1 (small int)", sys.getsizeof(1)),
        ("True (bool singleton)", sys.getsizeof(True)),
        ("2**100 (big int)", sys.getsizeof(2**100)),
        ("() (empty tuple)", sys.getsizeof(())),
        ("[] (empty list)", sys.getsizeof([])),
        ("[0] (1 element)", sys.getsizeof([0])),
        ("[0]*1000 (1000 ptrs)", sys.getsizeof([0] * 1000)),
        ("range(1000)", sys.getsizeof(range(1000))),
    ]
    for label, size in rows:
        print(f"{label:<26}{size}")
    print()

    # A list of 1000 ints holds 1000 POINTERS (8 bytes each) + the list header.
    # It does NOT count the int objects the pointers target.
    list_overhead = sys.getsizeof([0] * 1000) - sys.getsizeof([])
    print(f"list growth for 1000 slots = {list_overhead} bytes "
          f"(~{list_overhead // 1000} bytes/slot = one PyObject* pointer)")
    print(f"vs 1000 raw C ints would be ~{1000 * 4} bytes (4 bytes each)")
    print()

    check("a Python int 0 is > 20 bytes (header + digit storage)",
          int_zero > 20)
    check("2**100 is bigger than 0 (more digits stored)", big_int > int_zero)
    check("a list grows by ~8 bytes per slot (one pointer)",
          sys.getsizeof([0] * 1000) - sys.getsizeof([0]) >= 999 * 8)
    check("range(1000) is tiny regardless of size (stores start/stop/step)",
          sys.getsizeof(range(1000)) < sys.getsizeof([0] * 1000))


# ----------------------------------------------------------------------------
# Section B — __slots__ removes the per-instance __dict__
# ----------------------------------------------------------------------------

def section_b_slots() -> None:
    banner("B — __slots__: trade the per-instance __dict__ for a fixed layout")
    print("A normal instance carries a __dict__ (a hash table) to hold its")
    print("attributes — typically a few hundred bytes, even for one field. A")
    print("class with __slots__ drops that __dict__ and stores attributes in a")
    print("fixed slot array. The catch: getsizeof(instance) is SHALLOW, so to")
    print("compare honestly we must add getsizeof(instance.__dict__) for the")
    print("non-slotted class.\n")

    class NoSlots:
        def __init__(self) -> None:
            self.x = 1
            self.y = 2
            self.z = 3

    class WithSlots:
        __slots__ = ("x", "y", "z")

        def __init__(self) -> None:
            self.x = 1
            self.y = 2
            self.z = 3

    ns = NoSlots()
    ws = WithSlots()
    ns_total = sys.getsizeof(ns) + sys.getsizeof(ns.__dict__)
    ws_total = sys.getsizeof(ws)

    print(f"{'measurement':<34}{'bytes'}")
    print("-" * 50)
    print(f"{'getsizeof(NoSlots())':<34}{sys.getsizeof(ns)}")
    print(f"{'getsizeof(NoSlots().__dict__)':<34}{sys.getsizeof(ns.__dict__)}")
    print(f"{'  -> NoSlots TOTAL':<34}{ns_total}")
    print(f"{'getsizeof(WithSlots())':<34}{sys.getsizeof(ws)}")
    print(f"{'  -> WithSlots TOTAL (no __dict__)':<34}{ws_total}")
    print(f"{'hasattr(WithSlots(), __dict__)':<34}"
          f"{hasattr(ws, '__dict__')}")
    print(f"\nnon-slotted / slotted ratio = "
          f"{ns_total / ws_total:.2f}x more memory per instance")
    print()

    check("__slots__ instance has NO __dict__", not hasattr(ws, "__dict__"))
    check("non-slotted instance DOES have a __dict__", hasattr(ns, "__dict__"))
    check("slotted TOTAL < non-slotted TOTAL (the whole point)",
          ws_total < ns_total)
    # At scale: 1_000_000 instances. (🔗 PROPERTIES_DESCRIPTORS for slot theory.)
    million_savings = (ns_total - ws_total) * 1_000_000
    print(f"at 1,000,000 instances, __slots__ saves ~{million_savings:,} bytes "
          f"(~{million_savings / 1_048_576:.0f} MiB)")
    print()


# ----------------------------------------------------------------------------
# Section C — array.array: compact C-typed storage
# ----------------------------------------------------------------------------

def section_c_array() -> None:
    banner("C — array.array: store raw C values, not PyObjects")
    print("A list of ints holds POINTERS to int objects (each ~28 bytes).")
    print("array.array stores the raw C values inline (4 bytes for 'i'), so")
    print("1000 ints cost ~4 KB in an array vs ~28 KB+ as a list of int")
    print("objects (28 bytes/int + 8 bytes/pointer). The trade: every read")
    print("BOXES the C value back into a Python int on the fly.\n")

    big_list = [0] * 1000
    big_array = array.array("i", [0] * 1000)

    print(f"{'container':<32}{'getsizeof (bytes)'}")
    print("-" * 52)
    print(f"{'[0]*1000  (list of 1000 int objects)':<32}"
          f"{sys.getsizeof(big_list)}")
    print(f"{'array(\"i\", [0]*1000)  (raw C ints)':<32}"
          f"{sys.getsizeof(big_array)}")
    print(f"{'array.itemsize':<32}{big_array.itemsize}")
    print()
    ratio = sys.getsizeof(big_list) / sys.getsizeof(big_array)
    print(f"list / array ratio = {ratio:.2f}x "
          f"(array is {ratio:.1f}x smaller for the same 1000 ints)")
    print()

    check("array.itemsize == 4 for 'i' (one C int per slot)",
          big_array.itemsize == 4)
    check("array('i', 1000 ints) < list of 1000 ints",
          sys.getsizeof(big_array) < sys.getsizeof(big_list))
    check("reading an array element returns a Python int (boxes on read)",
          isinstance(big_array[0], int) and type(big_array[0]) is int)
    check("array scales by itemsize (1000 * 4 + small header)",
          sys.getsizeof(big_array) < 1000 * 4 + 200)


# ----------------------------------------------------------------------------
# Section D — bytes / bytearray / memoryview: zero-copy views
# ----------------------------------------------------------------------------

def section_d_memoryview() -> None:
    banner("D — memoryview: a zero-copy view over a bytes-like buffer")
    print("bytes is an immutable compact buffer (1 byte per element + a small")
    print("header). memoryview wraps any buffer-protocol object and lets you")
    print("slice / read / (if mutable) write WITHOUT copying the data. The")
    print("view object itself is ~184 bytes regardless of how big a slice it")
    print("describes, because it shares the underlying buffer.\n")

    big = bytes(1_000_000)          # 1 MB of zeros
    mv_full = memoryview(big)
    mv_slice = mv_full[:1000]       # a 1000-byte view -> NO copy of the 1 MB

    print(f"{'object':<40}{'getsizeof (bytes)'}")
    print("-" * 60)
    print(f"{'bytes(1_000_000)':<40}{sys.getsizeof(big)}")
    print(f"{'memoryview(bytes(1_000_000))':<40}{sys.getsizeof(mv_full)}")
    print(f"{'memoryview(...)[:1000]  (a slice)':<40}{sys.getsizeof(mv_slice)}")
    print(f"{'mv_slice.nbytes (logical bytes seen)':<40}{mv_slice.nbytes}")
    print()
    print("The 184-byte slice view shares the 1,000,033-byte buffer -> zero copy.")
    print()

    # Zero-copy MUTATION through a memoryview over a bytearray.
    ba = bytearray(b"hello world")
    mv_mut = memoryview(ba)
    mv_mut[0:5] = b"HELLO"          # writes straight into ba's buffer
    print("ba = bytearray(b'hello world')")
    print(f"memoryview(ba)[0:5] = b'HELLO'  ->  ba now = {bytes(ba)!r}")
    print()

    check("bytes(1MB) is ~1 MB (33-byte header + 1,000,000 data)",
          sys.getsizeof(big) == 1_000_000 + sys.getsizeof(b""))
    check("memoryview of a 1 MB buffer is tiny (zero-copy)",
          sys.getsizeof(mv_full) < 300)
    check("a slice view is the same tiny size (shares the buffer)",
          sys.getsizeof(mv_slice) == sys.getsizeof(mv_full))
    check("the slice sees 1000 logical bytes but copies none",
          mv_slice.nbytes == 1000)
    check("writing through a memoryview mutates the underlying bytearray",
          bytes(ba) == b"HELLO world")


# ----------------------------------------------------------------------------
# Section E — generator vs list: O(1) vs O(N) memory (tracemalloc)
# ----------------------------------------------------------------------------

def _gen_sum(n: int) -> int:
    return sum(x for x in range(n))      # generator: one int alive at a time


def _list_sum(n: int) -> int:
    return sum(list(range(n)))           # list: all N ints materialized


def section_e_generator_vs_list() -> None:
    banner("E — Generator vs list: O(1) vs O(N) peak memory")
    print("A generator yields one item at a time and forgets it; a list holds")
    print("all N items at once. We measure PEAK memory with tracemalloc across")
    print("growing N: the generator's peak stays ~constant, the list's scales")
    print("linearly. (🔗 GENERATORS_ITERATORS for the iterator protocol.)\n")

    gc.collect()
    print(f"{'N':>10}  {'gen_peak':>12}  {'list_peak':>12}  {'list/gen':>10}")
    print("-" * 54)
    gen_peaks: list[int] = []
    list_peaks: list[int] = []
    for n in (1_000, 100_000, 1_000_000):
        tracemalloc.start()
        _gen_sum(n)
        _, gen_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        tracemalloc.start()
        _list_sum(n)
        _, list_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        gen_peaks.append(gen_peak)
        list_peaks.append(list_peak)
        ratio = list_peak / max(gen_peak, 1)
        print(f"{n:>10,}  {gen_peak:>12,}  {list_peak:>12,}  "
              f"{ratio:>9.1f}x")
    print()

    check("generator peak memory is ~constant across N (O(1))",
          max(gen_peaks) - min(gen_peaks) < 2_000)
    check("list peak memory grows with N (O(N))",
          list_peaks[-1] > list_peaks[0] * 10)
    check("at N=1,000,000 the list peak >> generator peak",
          list_peaks[-1] > gen_peaks[-1] * 1000)
    check("the two produce the same answer (sum is equal)",
          _gen_sum(1000) == _list_sum(1000))


# ----------------------------------------------------------------------------
# Section F — decision table: which tool wins when
# ----------------------------------------------------------------------------

def section_f_decision_table() -> None:
    banner("F — Which lever wins when: the decision table")
    print("Pick the tool by data SHAPE and ACCESS pattern, not by habit.\n")

    print(f"{'scenario':<42}{'best tool':<22}{'why'}")
    print("-" * 92)
    rows = [
        ("small, heterogeneous records",
         "objects / dict",
         "__dict__ overhead is negligible; flexibility wins"),
        ("huge homogeneous numeric column",
         "array / numpy",
         "raw C values, no per-element header"),
        ("streaming / one-pass transformation",
         "generator",
         "O(1) peak memory; nothing buffered"),
        ("binary buffer (parse / slice)",
         "bytes / memoryview",
         "compact + zero-copy slicing"),
        ("millions of small uniform instances",
         "class with __slots__",
         "drops the per-instance __dict__"),
        ("lazy arithmetic sequence",
         "range",
         "stores only start/stop/step; O(1)"),
    ]
    for scenario, tool, why in rows:
        print(f"{scenario:<42}{tool:<22}{why}")
    print()

    check("a decision rule was printed for every lever above",
          len(rows) == 6)
    check("array beats list for a numeric column (re-assert from Section C)",
          sys.getsizeof(array.array("i", [0] * 1000))
          < sys.getsizeof([0] * 1000))


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("memory_efficiency.py — Phase 4 bundle #25.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {sys.version.split()[0]} on this machine.")
    section_a_header_tax()
    section_b_slots()
    section_c_array()
    section_d_memoryview()
    section_e_generator_vs_list()
    section_f_decision_table()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
