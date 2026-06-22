"""
generators_iterators.py — Bundle #5 (Phase 1).

GOAL (one line): show, by printing every value, that the iterator protocol
(__iter__/__next__ + StopIteration) is what every `for` loop runs on, that
generators are functions whose frame SUSPENDS at each `yield`, and that this
makes them lazy, memory-cheap, and single-use — which itertools exploits to
build infinite pipelines in O(1) memory.

This is the GROUND TRUTH for GENERATORS_ITERATORS.md. Every value, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python generators_iterators.py
"""

from __future__ import annotations

import sys
import types
from itertools import accumulate, chain, count, islice, product, takewhile

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers
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
# Section A — iterable vs iterator: the protocol Python's `for` runs on
# ----------------------------------------------------------------------------

def section_a_iterable_vs_iterator() -> None:
    banner("A — Iterable vs iterator: the protocol Python's `for` runs on")
    print("Every `for x in xs` first calls iter(xs) to get an ITERATOR, then")
    print("calls next() on it until StopIteration. iter() works on any")
    print("ITERABLE (list/str/dict/range/file...); next() works ONLY on")
    print("iterators. A list is iterable but NOT an iterator: it has no")
    print("__next__ method.\n")

    lst = [1, 2, 3]
    it = iter(lst)
    print("lst = [1, 2, 3]")
    print(f"type(lst).__name__           = {type(lst).__name__}")
    print(f"hasattr(lst, '__iter__')     = {hasattr(lst, '__iter__')}")
    print(f"hasattr(lst, '__next__')     = {hasattr(lst, '__next__')}   <- no __next__: NOT an iterator")
    print("it = iter(lst)")
    print(f"type(it).__name__            = {type(it).__name__}")
    print(f"iter(it) is it               = {iter(it) is it}   <- an iterator's __iter__ returns SELF")
    print(f"next(it)                     = {next(it)}")
    print(f"next(it)                     = {next(it)}")
    print(f"next(it)                     = {next(it)}")
    try:
        next(it)
    except StopIteration:
        print("next(it)                     -> StopIteration (iterator exhausted)")
    print()

    # next() on a non-iterator raises TypeError, not StopIteration.
    try:
        next([1, 2, 3])
    except TypeError as exc:
        print(f"next([1, 2, 3])              -> TypeError: {exc}")
    print()

    # The clean identity check on a single object: an iterator's __iter__
    # returns ITSELF (so iter(it) is it). A list_iterator is an iterator.
    one_iter = iter([10, 20])
    check("iter(it) is it for an iterator (protocol: __iter__ returns self)",
          iter(one_iter) is one_iter)
    check("a list has __iter__ (it is iterable)", hasattr(lst, "__iter__"))
    check("a list has NO __next__ (it is NOT an iterator)",
          not hasattr(lst, "__next__"))


# ----------------------------------------------------------------------------
# Section B — a hand-rolled iterator: __iter__ + __next__ (Countdown)
# ----------------------------------------------------------------------------

class Countdown:
    """A minimal iterator: __iter__ returns self, __next__ counts down to 1
    then raises StopIteration. No magic — this is exactly what iter([...])
    returns under the hood."""

    def __init__(self, start: int) -> None:
        self.n = start

    def __iter__(self) -> "Countdown":
        return self  # the protocol: an iterator's __iter__ returns ITSELF

    def __next__(self) -> int:
        if self.n <= 0:
            raise StopIteration  # the only signal for "no more items"
        self.n -= 1
        return self.n + 1  # the value BEFORE the decrement


def section_b_hand_rolled_class() -> None:
    banner("B — A hand-rolled iterator: __iter__ + __next__ (Countdown)")
    print("The whole protocol is two methods. __iter__ returns the iterator")
    print("(for an iterator, it returns self). __next__ returns the next")
    print("value, or raises StopIteration to say 'done'. This is exactly")
    print("what iter([1,2,3]) returns under the hood — no magic.\n")

    print("class Countdown:")
    print("    def __iter__(self): return self")
    print("    def __next__(self):")
    print("        if self.n <= 0: raise StopIteration")
    print("        self.n -= 1; return self.n + 1\n")

    cd = Countdown(3)
    print("cd = Countdown(3)")
    print(f"iter(cd) is cd        = {iter(cd) is cd}")
    sequence = [v for v in Countdown(3)]
    print(f"for v in Countdown(3): seq = {sequence}")

    # Walk it by hand to show the StopIteration explicitly.
    cd2 = Countdown(2)
    manual: list = [next(cd2), next(cd2)]
    try:
        next(cd2)
    except StopIteration:
        manual.append("StopIteration")
    print(f"manual walk of Countdown(2): next, next, next -> {manual}\n")

    check("Countdown(3) yields 3, 2, 1 then stops", sequence == [3, 2, 1])
    check("iter(cd) is cd (an iterator's __iter__ returns self)",
          iter(Countdown(0)) is not None)  # existence; real identity below
    cd3 = Countdown(1)
    check("iter(cd) is cd for a Countdown instance", iter(cd3) is cd3)
    check("manual walk ends in StopIteration",
          manual == [2, 1, "StopIteration"])


# ----------------------------------------------------------------------------
# Section C — `yield` makes a function into a generator (frame suspends)
# ----------------------------------------------------------------------------

def two_yields() -> types.GeneratorType:
    """A generator FUNCTION: contains `yield`. Calling it does NOT run the
    body — it returns a fresh generator object. The body runs lazily, one
    yield at a time, with its frame SUSPENDED between calls."""
    print("    [body: running up to first yield]")
    yield 1
    print("    [body: resumed between yields; local state preserved]")
    yield 2
    print("    [body: resumed after second yield; about to fall off the end]")


def running_total(start: int) -> types.GeneratorType:
    """Frame-suspension demo: `total` persists across yields because the
    frame (its locals + instruction pointer) is kept alive by the generator
    object between next() calls."""
    total = start
    while True:
        yield total
        total += 1  # this increment survives across next() calls


def section_c_yield_and_frame_suspension() -> None:
    banner("C — `yield` makes a function into a generator (frame suspends)")
    print("A function containing `yield` is a GENERATOR FUNCTION. CALLING it")
    print("does NOT execute the body — it returns a fresh GENERATOR object.")
    print("Each next() runs the body until the next `yield`, then SUSPENDS")
    print("the frame (locals + instruction pointer are kept alive). Calling")
    print("next() again RESUMES exactly where it left off.\n")

    print("Calling two_yields() returns a generator; body has NOT run yet:")
    g = two_yields()
    print(f"type(g).__name__               = {type(g).__name__}")
    print(f"g.gi_frame is not None         = {g.gi_frame is not None}  (frame exists, suspended)")
    print()
    print("Driving it with next() — watch the body prints interleave:")
    print("calling next(g)...")
    v1 = next(g)
    print(f"  -> {v1}")
    print("calling next(g)...")
    v2 = next(g)
    print(f"  -> {v2}")
    print("calling next(g)...")
    try:
        next(g)
    except StopIteration:
        print("  -> StopIteration (body ran off the end)")
    print()

    print("Frame-suspension demo: local var `total` persists across yields.")
    rt = running_total(10)
    print("rt = running_total(10)   # total starts at 10")
    r1, r2, r3 = next(rt), next(rt), next(rt)
    print(f"next(rt) -> {r1}")
    print(f"next(rt) -> {r2}")
    print(f"next(rt) -> {r3}   (10 -> 11 -> 12: SAME frame, local persisted)\n")

    check("calling a generator function returns a generator object",
          type(two_yields()) is types.GeneratorType)
    check("an exhausted generator's frame is None (gi_frame cleared)",
          g.gi_frame is None)  # g was driven to StopIteration above
    fresh = two_yields()
    check("a fresh generator's frame is live before first next()",
          fresh.gi_frame is not None)
    # Use a quiet generator for the list() check so we don't re-print the
    # body banners here (two_yields prints as a side effect of suspension).
    def _quiet() -> types.GeneratorType:
        yield 1
        yield 2
    check("next() walks the yields in order", list(_quiet()) == [1, 2])
    check("a single generator's local var accumulates across next() calls",
          [r1, r2, r3] == [10, 11, 12])


# ----------------------------------------------------------------------------
# Section D — iterators are single-use: exhaustion is permanent
# ----------------------------------------------------------------------------

def _small_gen() -> types.GeneratorType:
    yield "a"
    yield "b"


def section_d_single_use_exhaustion() -> None:
    banner("D — Iterators are single-use: exhaustion is permanent")
    print("An iterator is CONSUMED by iteration. Once exhausted, every")
    print("further next() raises StopIteration and list(it) returns []. This")
    print("is true of generator expressions, generator functions, map/filter")
    print("objects, zip objects, file objects, and EVERY itertools output.")
    print("A LIST survives repeated iteration; an ITERATOR does not.\n")

    # A generator expression: list() twice -> second is empty.
    g = (x * x for x in range(3))
    first_pass = list(g)
    second_pass = list(g)
    print("g = (x*x for x in range(3))")
    print(f"list(g) (1st pass) = {first_pass}")
    print(f"list(g) (2nd pass) = {second_pass}   <- EMPTY: g was consumed\n")

    # A generator FUNCTION: calling it twice makes TWO distinct generators.
    g_a = _small_gen()
    g_b = _small_gen()
    ga_first = list(g_a)
    gb_first = list(g_b)
    ga_second = list(g_a)
    print("def small_gen(): yield 'a'; yield 'b'")
    print("g_a = small_gen(); g_b = small_gen()")
    print(f"g_a is g_b        = {g_a is g_b}   <- two DISTINCT generator objects")
    print(f"list(g_a)         = {ga_first}")
    print(f"list(g_b)         = {gb_first}   <- each call makes a fresh generator")
    print(f"list(g_a) again   = {ga_second}   <- but each generator is single-use\n")

    # Contrast: a list survives repeated iteration.
    lst = [1, 2]
    print("lst = [1, 2]")
    print(f"list(lst) x3      = {[list(lst), list(lst), list(lst)]}")
    print("  (a list is an ITERABLE: iter() mints a fresh iterator each time)\n")

    check("generator expression is single-use: list() twice -> 2nd empty",
          first_pass == [0, 1, 4] and second_pass == [])
    check("two calls to a generator function -> two distinct objects",
          g_a is not g_b)
    check("each fresh generator yields its values on the first pass",
          ga_first == ["a", "b"] and gb_first == ["a", "b"])
    check("a generator is exhausted after one full pass", ga_second == [])
    check("a list survives repeated iteration",
          list(lst) == [1, 2] and list(lst) == [1, 2])


# ----------------------------------------------------------------------------
# Section E — `yield from` delegates to a sub-generator (PEP 380)
# ----------------------------------------------------------------------------

def _sub_gen() -> types.GeneratorType:
    yield "x"
    yield "y"


def _delegating_gen() -> types.GeneratorType:
    yield "start"
    yield from _sub_gen()        # PEP 380: delegate to a sub-generator
    yield from ["a", "b"]        # also works on ANY iterable
    yield "end"


def _returning_sub() -> types.GeneratorType:
    yield 1
    yield 2
    return "SUB_RESULT"          # captured by `yield from` as its value


def _outer() -> types.GeneratorType:
    sent = yield from _returning_sub()
    yield f"got: {sent}"


def section_e_yield_from() -> None:
    banner("E — `yield from` delegates to a sub-generator (PEP 380)")
    print("`yield from sub` makes the outer generator transparently delegate")
    print("to `sub`: each value the sub yields is re-yielded by the outer,")
    print("and when the sub raises StopIteration, control returns to the")
    print("outer. `sub` can be any iterable (another generator, a list, a")
    print("string, a range...).\n")

    result = list(_delegating_gen())
    print("def sub_gen(): yield 'x'; yield 'y'")
    print("def delegating_gen():")
    print("    yield 'start'")
    print("    yield from sub_gen()       # delegate to a sub-generator")
    print("    yield from ['a', 'b']      # works on any iterable")
    print("    yield 'end'\n")
    print(f"list(delegating_gen()) = {result}\n")

    # yield from also forwards the sub-generator's return value.
    print("`yield from` ALSO captures the sub-generator's return value:")
    print("def returning_sub(): yield 1; yield 2; return 'SUB_RESULT'")
    print("def outer(): sent = yield from returning_sub(); yield f'got: {sent}'")
    print(f"list(outer())         = {list(_outer())}\n")

    check("yield from flattens sub-generator values into the outer stream",
          result == ["start", "x", "y", "a", "b", "end"])
    check("yield from forwards the sub-generator's return value",
          list(_outer()) == [1, 2, "got: SUB_RESULT"])


# ----------------------------------------------------------------------------
# Section F — infinite generators + islice: lazy pipelines in O(1) memory
# ----------------------------------------------------------------------------

def naturals() -> types.GeneratorType:
    """An INFINITE generator. Because the frame suspends at each yield, this
    uses O(1) memory regardless of how many values you eventually pull."""
    i = 0
    while True:
        yield i
        i += 1


def section_f_infinite_and_islice() -> None:
    banner("F — Infinite generators + islice: lazy pipelines in O(1) memory")
    print("A generator with `while True: yield ...` never stops on its own.")
    print("That's SAFE because it's lazy — it only produces a value when")
    print("next() asks for one, so the infinite stream costs O(1) memory.")
    print("itertools.islice(it, n) is the standard way to take the first N")
    print("items of any (possibly infinite) iterator.\n")

    print("def naturals():")
    print("    i = 0")
    print("    while True: yield i; i += 1\n")
    print(f"list(islice(naturals(), 5))      = "
          f"{list(islice(naturals(), 5))}")
    print(f"list(islice(naturals(), 10, 13)) = "
          f"{list(islice(naturals(), 10, 13))}   (start/stop, like slicing)")
    print()

    # Memory proof: an infinite generator is a fixed-size object.
    inf = naturals()
    size_before = sys.getsizeof(inf)
    next(inf)
    next(inf)
    next(inf)
    size_after = sys.getsizeof(inf)
    print(f"sys.getsizeof(naturals()) before pulls = {size_before} bytes")
    print(f"sys.getsizeof(naturals()) after 3 pulls = {size_after} bytes")
    print("  (fixed — pulling 1 or 1e9 values does not grow the object)\n")

    check("infinite generator + islice(_, 5) -> [0,1,2,3,4]",
          list(islice(naturals(), 5)) == [0, 1, 2, 3, 4])
    check("islice supports start/stop like sequence slicing",
          list(islice(naturals(), 10, 13)) == [10, 11, 12])
    check("the generator object size is constant regardless of pulls",
          size_before == size_after)


# ----------------------------------------------------------------------------
# Section G — itertools greatest hits
# ----------------------------------------------------------------------------

def section_g_itertools_hits() -> None:
    banner("G — itertools greatest hits: count, chain, takewhile, accumulate, product")
    print("itertools is the stdlib's iterator algebra. EVERY function returns")
    print("a LAZY iterator — chaining/accumulating over a million items costs")
    print("O(1) memory until you materialize them with list(). Below: one")
    print("demo of each, plus a composed lazy pipeline.\n")

    print(f"{'tool':<12}{'expression':<48}{'result'}")
    print("-" * 82)
    rows = [
        ("count",      "islice(count(10), 5)",                       list(islice(count(10), 5))),
        ("chain",      "chain('AB', 'CD')",                          list(chain("AB", "CD"))),
        ("takewhile",  "takewhile(lambda x: x<3, [1,2,3,4,1])",     list(takewhile(lambda x: x < 3, [1, 2, 3, 4, 1]))),
        ("accumulate", "accumulate([1,2,3,4])",                      list(accumulate([1, 2, 3, 4]))),
        ("accumulate", "accumulate([1,2,3,4], initial=10)",          list(accumulate([1, 2, 3, 4], initial=10))),
        ("product",    "product('AB', 'xy')",                        list(product("AB", "xy"))),
    ]
    for tool, expr, result in rows:
        print(f"{tool:<12}{expr:<48}{result}")
    print()

    # Composing lazy iterators into a pipeline — no intermediate list built.
    pipeline = list(islice(
        (x * x for x in takewhile(lambda n: n < 100, count(7))),
        5,
    ))
    print("Lazy pipeline (no intermediate list is ever materialized):")
    print("  list(islice( (x*x for x in takewhile(lambda n: n<100, count(7))), 5 ))")
    print(f"  = {pipeline}\n")

    check("count(10) is an infinite arithmetic stream",
          list(islice(count(10), 5)) == [10, 11, 12, 13, 14])
    check("chain concatenates iterables lazily",
          list(chain("AB", "CD")) == ["A", "B", "C", "D"])
    check("takewhile stops at the first False (and consumes that item)",
          list(takewhile(lambda x: x < 3, [1, 2, 3, 4, 1])) == [1, 2])
    check("accumulate gives running totals",
          list(accumulate([1, 2, 3, 4])) == [1, 3, 6, 10])
    check("accumulate with initial= prepends the start value",
          list(accumulate([1, 2, 3, 4], initial=10)) == [10, 11, 13, 16, 20])
    check("product is the cartesian product",
          list(product("AB", "xy")) == [("A", "x"), ("A", "y"),
                                        ("B", "x"), ("B", "y")])
    check("lazy pipeline composition works end-to-end",
          pipeline == [49, 64, 81, 100, 121])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("generators_iterators.py — Phase 1 bundle #5.\n"
          "Every value below is computed by this file; the .md guide pastes\n"
          "it verbatim. Nothing is hand-computed.\n"
          f"Python {sys.version.split()[0]} on this machine.")
    section_a_iterable_vs_iterator()
    section_b_hand_rolled_class()
    section_c_yield_and_frame_suspension()
    section_d_single_use_exhaustion()
    section_e_yield_from()
    section_f_infinite_and_islice()
    section_g_itertools_hits()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
