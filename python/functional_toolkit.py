"""
functional_toolkit.py — Bundle #15 (Phase 2).

GOAL (one line): show, by printing every value, that Python's pragmatic
functional toolkit (map/filter/reduce, partial, singledispatch, operator)
is lazy where it matters, replaces if/isinstance chains with dispatch
tables, and knows exactly when a comprehension or plain loop reads better.

This is the GROUND TRUTH for FUNCTIONAL_TOOLKIT.md. Every value, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python functional_toolkit.py
"""

from __future__ import annotations

import operator
import sys
from functools import partial, reduce, singledispatch

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
# Section A — map/filter return ITERATORS (lazy, single-use) in Py3
# ----------------------------------------------------------------------------

def section_a_map_filter_lazy() -> None:
    banner("A — map/filter return ITERATORS (lazy, single-use) in Py3")
    print("In Python 3, map() and filter() do NOT build a list. They return")
    print("single-use ITERATOR objects (map/filter) that compute each value")
    print("on demand. list() materializes them; a second pass is EMPTY. In")
    print("Python 2 both returned lists; reduce() was removed from builtins")
    print("entirely in 3.0 (PEP 3100) and now lives in functools.\n")

    m = map(str, [1, 2, 3])
    f = filter(None, [0, 2, 0, 4])
    # str(map(...)) embeds a memory address, so we strip it for byte-stable
    # output: "<map object at 0x...>" -> "<map object>".
    def stable(obj: object) -> str:
        s = str(obj)
        return s.split(" at ")[0] + ">" if " at 0x" in s else s

    print(f"{'expression':<32}{'value':<26}{'type'}")
    print("-" * 68)
    print(f"{'map(str, [1,2,3])':<32}{stable(m):<26}{type(m).__name__}")
    print(f"{'list(map(str, [1,2,3]))':<32}{list(map(str, [1,2,3]))!r:<26}"
          f"{type(list(map(str,[1,2,3]))).__name__}")
    print(f"{'filter(None, [0,2,0,4])':<32}{stable(f):<26}{type(f).__name__}")
    print(f"{'list(filter(None, [0,2,0,4]))':<32}{list(filter(None, [0,2,0,4]))!r:<26}"
          f"{'list'}")
    print()

    # Single-use proof: iterate a map object twice -> second pass is empty.
    m2 = map(str, [1, 2, 3])
    first_pass = list(m2)
    second_pass = list(m2)
    print("m2 = map(str, [1,2,3])")
    print(f"list(m2) (1st pass) = {first_pass}")
    print(f"list(m2) (2nd pass) = {second_pass}   <- EMPTY: iterator consumed\n")

    # The pythonic alternative: a comprehension reads the same and is eager
    # only if you wrap it in []. A genexpr is the lazy equivalent.
    print("Pythonic equivalents:")
    print("  [str(x) for x in [1,2,3]]   -> eager list  "
          f"{[str(x) for x in [1, 2, 3]]}")
    print("  (str(x) for x in [1,2,3])   -> lazy genexpr (same laziness as map)\n")

    check("map object is not a list (it is a lazy iterator)",
          type(m) is not list and hasattr(m, "__next__"))
    check("list(map(str,[1,2,3])) == ['1','2','3']",
          list(map(str, [1, 2, 3])) == ["1", "2", "3"])
    check("filter(None, ...) drops the falsy zeros",
          list(filter(None, [0, 2, 0, 4])) == [2, 4])
    check("map object is single-use: list() twice -> 2nd is []",
          first_pass == ["1", "2", "3"] and second_pass == [])
    check("the listcomp equivalent produces the same values eagerly",
          [str(x) for x in [1, 2, 3]] == list(map(str, [1, 2, 3])))


# ----------------------------------------------------------------------------
# Section B — functools.reduce: the fold-left (and why sum() usually wins)
# ----------------------------------------------------------------------------

def section_b_reduce_fold() -> None:
    banner("B — functools.reduce: the fold-left (and why sum() usually wins)")
    print("reduce(f, [a,b,c,d], init) folds LEFT: it accumulates f(init,a),")
    print("then f(_,b), f(_,c), f(_,d). The accumulator is always the LEFT")
    print("argument. An optional initializer seeds the accumulator and is")
    print("the only safe choice for an empty iterable.\n")

    total = reduce(lambda a, b: a + b, [1, 2, 3, 4])
    with_init = reduce(lambda a, b: a + b, [1, 2, 3, 4], 100)
    product = reduce(operator.mul, [1, 2, 3, 4])
    empty = reduce(lambda a, b: a + b, [], 0)
    print(f"{'expression':<46}{'result'}")
    print("-" * 60)
    print(f"{'reduce(lambda a,b: a+b, [1,2,3,4])':<46}{total}")
    print(f"{'reduce(lambda a,b: a+b, [1,2,3,4], 100)':<46}{with_init}")
    print(f"{'reduce(operator.mul, [1,2,3,4])':<46}{product}")
    print(f"{'reduce(lambda a,b: a+b, [], 0)':<46}{empty}")
    print()
    print("Step-by-step fold trace of reduce(add, [1,2,3,4]):")
    acc = 0
    print(f"  initial acc         = {acc}")
    for item in [1, 2, 3, 4]:
        acc = operator.add(acc, item)
        print(f"  add(acc, {item}) -> acc = {acc}")
    print()
    print("sum() is the builtin you'd usually use instead of reduce(add, ...).")
    print(f"  sum([1,2,3,4])      = {sum([1,2,3,4])}   <- faster, clearer")
    print(f"  sum([1,2,3,4], 100) = {sum([1,2,3,4], 100)}   <- start arg == reduce init\n")

    check("reduce(add, [1,2,3,4]) == 10", total == 10)
    check("reduce(add, [1,2,3,4], 100) == 110", with_init == 110)
    check("reduce(mul, [1,2,3,4]) == 24 (factorial-like)", product == 24)
    check("reduce(add, [], 0) == 0 (initializer protects empty iter)",
          empty == 0)
    check("sum() matches reduce(add, ...) for [1,2,3,4]",
          sum([1, 2, 3, 4]) == reduce(operator.add, [1, 2, 3, 4]))


# ----------------------------------------------------------------------------
# Section C — functools.partial: freeze args, pre-configure callbacks
# ----------------------------------------------------------------------------

def section_c_partial() -> None:
    banner("C — functools.partial: freeze args, pre-configure callbacks")
    print("partial(func, *args, **kwargs) returns a new callable with those")
    print("args/kwargs 'frozen in'. Extra args at call time are appended.")
    print("The classic use: pre-configuring a callback so the call site is")
    print("just `callback()`.\n")

    def add(a: int, b: int, c: int) -> int:
        return a + b + c

    add5 = partial(add, 5)           # freeze a=5; call as add5(b, c)
    add53 = partial(add, 5, 3)       # freeze a=5, b=3; call as add53(c)
    basetwo = partial(int, base=2)   # freeze base=2 keyword

    print(f"{'expression':<30}{'result'}")
    print("-" * 44)
    print(f"{'add5 = partial(add, 5)':<30}")
    print(f"{'add5(1, 1)':<30}{add5(1, 1)}")
    print(f"{'add53 = partial(add, 5, 3)':<30}")
    print(f"{'add53(1)':<30}{add53(1)}")
    print(f"{'basetwo = partial(int, base=2)':<30}")
    print(f"{'basetwo(\"10010\")':<30}{basetwo('10010')}")
    print()
    print(f"add5.func is add        = {add5.func is add}")
    print(f"add5.args               = {add5.args}")
    print(f"basetwo.keywords        = {basetwo.keywords}")
    print()

    check("partial(add,5)(1,1) == 7", add5(1, 1) == 7)
    check("partial(add,5,3)(1) == 9", add53(1) == 9)
    check("partial(int, base=2)('10010') == 18", basetwo("10010") == 18)
    check("partial exposes .func/.args/.keywords",
          add5.func is add and add5.args == (5,)
          and basetwo.keywords == {"base": 2})


# ----------------------------------------------------------------------------
# Section D — functools.singledispatch: dispatch on the FIRST arg's type
# ----------------------------------------------------------------------------

@singledispatch
def describe(obj: object) -> str:
    return f"object: {obj!r}"


@describe.register
def _(obj: int) -> str:
    return f"int {obj}: hex 0x{obj:x}, is_positive={obj > 0}"


@describe.register
def _(obj: str) -> str:
    return f"str of length {len(obj)!r}: {obj!r}"


@describe.register
def _(obj: list) -> str:
    return f"list of {len(obj)} items: first={obj[0]!r}" if obj else "empty list"


def section_d_singledispatch() -> None:
    banner("D — functools.singledispatch: dispatch on the FIRST arg's type")
    print("@singledispatch turns a function into a GENERIC function: the impl")
    print("that runs is chosen by the RUNTIME TYPE of the FIRST argument. You")
    print("register one impl per type. This is the open/closed alternative to")
    print("a big if/elif isinstance chain: adding a type does NOT mean editing")
    print("the dispatch function. NOTE: dispatch is on the FIRST arg ONLY; for")
    print("methods use @singledispatchmethod.\n")

    print(f"{'call':<24}{'dispatched impl runs'}")
    print("-" * 64)
    samples: list[tuple[str, object]] = [
        ("describe(5)", 5),
        ("describe('x')", "x"),
        ("describe([10,20])", [10, 20]),
        ("describe(3.14)", 3.14),
        ("describe(None)", None),
    ]
    for label, value in samples:
        print(f"{label:<24}{describe(value)}")
    print()

    print("Under the hood there is a type->impl registry:")
    print(f"  describe.registry keys = "
          f"{sorted([t.__name__ for t in describe.registry])}")
    print(f"  describe.dispatch(int) = {describe.dispatch(int).__name__}")
    print(f"  describe.dispatch(float) = {describe.dispatch(float).__name__}"
          "  (falls back to the base @object impl)")
    print()

    check("int impl runs for 5 (mentions hex)",
          "hex 0x5" in describe(5))
    check("str impl runs for 'x' (mentions length)",
          "str of length 1" in describe("x"))
    check("list impl runs for [10,20]",
          "list of 2 items" in describe([10, 20]))
    check("unregistered float falls back to base object impl",
          describe(3.14).startswith("object:"))
    check("dispatch(int) is the int-specific function, not the base",
          describe.dispatch(int) is not describe.dispatch(float))


# ----------------------------------------------------------------------------
# Section E — operator module: itemgetter/attrgetter as fast key funcs
# ----------------------------------------------------------------------------

class Person:
    def __init__(self, name: str, age: int) -> None:
        self.name = name
        self.age = age

    def __repr__(self) -> str:
        return f"Person({self.name!r}, {self.age})"


def section_e_operator_keys() -> None:
    banner("E — operator module: itemgetter/attrgetter as fast key funcs")
    print("operator exposes the intrinsic operators AS FUNCTIONS:")
    print("operator.add(x, y) == x+y, operator.mul == x*y, etc. The big win is")
    print("itemgetter/attrgetter: they build tiny C-fast callables perfect as")
    print("the `key=` argument to sorted/max/itertools.groupby.\n")

    print(f"{'expression':<42}{'result'}")
    print("-" * 56)
    print(f"{'operator.add(2, 3)':<42}{operator.add(2, 3)}")
    print(f"{'operator.mul(2, 3)':<42}{operator.mul(2, 3)}")
    print(f"{'operator.itemgetter(1)([10,20,30])':<42}"
          f"{operator.itemgetter(1)([10, 20, 30])}")
    print(f"{'operator.itemgetter(0,2)([10,20,30])':<42}"
          f"{operator.itemgetter(0, 2)([10, 20, 30])}")
    print()

    # operator.add vs a lambda: same behavior, operator is C-implemented.
    rows = [(1, 2), (10, 5), (0, 0)]
    add_lambda = lambda a, b: a + b  # noqa: E731
    print("add_lambda vs operator.add (same result, operator is C-fast):")
    for a, b in rows:
        assert add_lambda(a, b) == operator.add(a, b)
        print(f"  ({a:>2}, {b:>2}) -> lambda {add_lambda(a, b)}, "
              f"operator {operator.add(a, b)}")
    print()

    # attrgetter as a sort key.
    people = [Person("Cleo", 7), Person("Ada", 12), Person("Bo", 3)]
    by_age = sorted(people, key=operator.attrgetter("age"))
    by_name = sorted(people, key=operator.attrgetter("name"))
    print("people = [Person('Cleo',7), Person('Ada',12), Person('Bo',3)]")
    print(f"sorted(people, key=attrgetter('age'))  = {by_age}")
    print(f"sorted(people, key=attrgetter('name')) = {by_name}")
    print()

    check("operator.add(2,3) == 5", operator.add(2, 3) == 5)
    check("operator.mul(2,3) == 6", operator.mul(2, 3) == 6)
    check("itemgetter(1)([10,20,30]) == 20",
          operator.itemgetter(1)([10, 20, 30]) == 20)
    check("itemgetter(0,2)([10,20,30]) == (10, 30)",
          operator.itemgetter(0, 2)([10, 20, 30]) == (10, 30))
    check("sorted by attrgetter('age') is ascending by age",
          [p.age for p in by_age] == [3, 7, 12])
    check("operator.add behaves identically to lambda a,b: a+b",
          all(add_lambda(a, b) == operator.add(a, b) for a, b in rows))


# ----------------------------------------------------------------------------
# Section F — composing functions + when functional wins vs a loop
# ----------------------------------------------------------------------------

def compose(f, g):
    """Math-style composition: compose(f, g)(x) == f(g(x)). Higher-order."""
    def composed(x):
        return f(g(x))
    return composed


def section_f_compose_and_readability() -> None:
    banner("F — composing functions + when functional wins vs a loop")
    print("Higher-order functions take/return functions. compose(f,g)(x) is")
    print("f(g(x)); a pipeline of partials chains small steps into one call.")
    print("When does functional beat a loop? When it stays READABLE: a clean")
    print("map/filter pipeline, a one-line reduce fold. When it HURTS: a")
    print("nested reduce over a multi-step transform — the loop is clearer.\n")

    def add1(x: int) -> int:
        return x + 1

    def double(x: int) -> int:
        return x * 2

    def square(x: int) -> int:
        return x * x

    # Composition: apply right-to-left (math order).
    add1_then_double = compose(double, add1)   # double(add1(x))
    pipeline = compose(add1, compose(double, square))  # add1(double(square(x)))

    print(f"compose(double, add1)(3) = double(add1(3)) = {add1_then_double(3)}")
    print(f"compose(add1, compose(double, square))(3) "
          f"= add1(double(square(3))) = {pipeline(3)}")
    print()

    # A pipeline of partials: each stage is a partial over map/filter/sum.
    # We re-build each stage from a FRESH source so we can snapshot it
    # (map/filter objects are single-use: snapshotting exhausts them).
    src = [1, 2, 3, 4, 5]
    snap_src = list(src)
    snap_mapped = list(map(square, src))
    snap_filtered = list(filter(lambda x: x > 10, snap_mapped))
    snap_sum = sum(snap_filtered)
    print(f"Pipeline of partials on {src}:")
    print(f"  stage0 src                  {snap_src}")
    print(f"  stage1 map(square)          {snap_mapped}")
    print(f"  stage2 filter(>10)          {snap_filtered}")
    print(f"  stage3 sum                  {snap_sum}")
    print()

    # When functional HURTS: nested reduce obscures a simple transform.
    data = [1, 2, 3, 4]
    # DON'T: a reduce that also filters AND maps -> unreadable.
    obscure = reduce(
        lambda acc, x: acc + [x * x] if x % 2 == 0 else acc,
        data, [])
    # DO: the same as a comprehension reads in one glance.
    clear = [x * x for x in data if x % 2 == 0]
    print("data = [1,2,3,4]   # want squares of the evens")
    print("DON'T (reduce that maps+filters):")
    print(f"  obscure = {obscure}")
    print("DO (comprehension reads at a glance):")
    print(f"  clear   = {clear}\n")

    check("compose(double, add1)(3) == 8", add1_then_double(3) == 8)
    check("compose(add1, compose(double, square))(3) == 19",
          pipeline(3) == 19)
    check("partial-pipeline sum(map->filter->sum) of [1..5] == 16+25 = 41",
          snap_sum == 41)
    check("obscure reduce == clear comprehension",
          obscure == clear == [4, 16])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("functional_toolkit.py — Phase 2 bundle #15.\n"
          "Every value below is computed by this file; the .md guide pastes\n"
          "it verbatim. Nothing is hand-computed.\n"
          f"Python {sys.version.split()[0]} on this machine.")
    section_a_map_filter_lazy()
    section_b_reduce_fold()
    section_c_partial()
    section_d_singledispatch()
    section_e_operator_keys()
    section_f_compose_and_readability()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
