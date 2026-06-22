"""
comprehensions.py — Bundle #4 (Phase 1).

GOAL (one line): show, by printing every value, how the four comprehension
forms (list, dict, set, generator) are declarative, scoped, composable
expressions — and exactly when they beat a for-loop and when they hurt
readability.

This is the GROUND TRUTH for COMPREHENSIONS.md. Every value, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python comprehensions.py
"""

from __future__ import annotations

import sys
import types

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
# Section A — the four forms: list, dict, set, generator
# ----------------------------------------------------------------------------

def section_a_four_forms() -> None:
    banner("A — The four forms: list, dict, set, generator")
    print("A comprehension is one expression + one or more 'for' clauses.")
    print("The brackets decide the result type:")
    print("  []      -> list          (eager, ordered, allows duplicates)")
    print("  {k:v}   -> dict          (eager, insertion-ordered, unique keys)")
    print("  {x}     -> set           (eager, dedups)")
    print("  ()      -> generator     (LAZY iterator object)\n")

    squares_list = [x * x for x in range(5)]
    ascii_dict = {c: ord(c) for c in "abc"}
    mod_set = {n % 3 for n in range(10)}
    squares_gen = (x * x for x in range(5))

    print(f"{'expression':<32}{'value':<30}{'type'}")
    print("-" * 72)
    rows = [
        ("[x*x for x in range(5)]", squares_list, "list"),
        ("{c: ord(c) for c in 'abc'}", ascii_dict, "dict"),
        ("{n%3 for n in range(10)}", mod_set, "set"),
        ("(x*x for x in range(5))", "<generator object>", "generator"),
    ]
    for label, value, tname in rows:
        print(f"{label:<32}{str(value):<30}{tname}")
    print()

    check("list comprehension builds a list", type(squares_list) is list)
    check("dict comprehension builds a dict", type(ascii_dict) is dict)
    check("dict comprehension values: {c: ord(c) for c in 'abc'}",
          ascii_dict == {'a': 97, 'b': 98, 'c': 99})
    check("set comprehension builds a set", type(mod_set) is set)
    check("set comprehension dedups: {n%3 for n in range(10)} == {0,1,2}",
          mod_set == {0, 1, 2})
    check("generator expression has type 'generator'",
          type(squares_gen) is types.GeneratorType)
    fresh_gen = (x for x in range(3))
    check("genexpr is its own iterator: iter(g) is g",
          iter(fresh_gen) is fresh_gen)


# ----------------------------------------------------------------------------
# Section B — Py3 scope isolation: the loop variable does NOT leak
# ----------------------------------------------------------------------------

def _scope_probe() -> dict:
    """Run a list comprehension with loop variable 'k' inside this function.
    In Py3 'k' is scoped to the comprehension, so it must NOT appear in this
    function's locals() afterwards. (In Py2 it WOULD have leaked as k == 2.)"""
    result = [k for k in range(3)]
    return {"result": result, "k_leaked": "k" in locals()}


def section_b_scope_isolation() -> None:
    banner("B — Py3 scope isolation: the loop variable does NOT leak")
    print("In Python 2, a list comprehension's loop variable LEAKED into the")
    print("enclosing scope (after [i for i in range(3)], i == 2). Python 3")
    print("gave every comprehension its own scope (equivalent to wrapping a")
    print("generator expression), so the loop variable is invisible after.\n")

    probe = _scope_probe()
    print(f"_scope_probe() ran: [k for k in range(3)] -> {probe['result']}")
    print(f"After the comprehension, 'k' in locals() -> {probe['k_leaked']}")
    print("  (False = the loop variable stayed inside the comprehension)")
    print()
    print("In Py2 the same code would have left k == 2 polluting the enclosing")
    print("scope. The Py3 fix removes a whole class of 'stale loop variable'")
    print("bugs at the cost of one extra frame per comprehension.\n")

    check("comprehension loop var does NOT leak into enclosing locals",
          probe["k_leaked"] is False)
    check("the comprehension still produces the expected list",
          probe["result"] == [0, 1, 2])


# ----------------------------------------------------------------------------
# Section C — filtering vs conditional expressions
# ----------------------------------------------------------------------------

def section_c_filter_and_conditional() -> None:
    banner("C — Filtering vs conditional expressions (two different 'if's)")
    print("'if' can appear in TWO places in a comprehension, with different")
    print("meanings:")
    print("  1. At the END (filter):     [n for n in src if cond]")
    print("       keeps only items where cond is truthy.")
    print("  2. In the VALUE (ternary):  [a if cond else b for ...]")
    print("       transforms each item via a conditional expression.")
    print("They compose but they are NOT the same operator.\n")

    evens = [n for n in range(10) if n % 2 == 0]
    labels = ["even" if n % 2 == 0 else "odd" for n in range(6)]
    composed = [n * 10 for n in range(10) if n % 2 == 0]

    print(f"{'expression':<50}{'value'}")
    print("-" * 74)
    rows = [
        ("[n for n in range(10) if n % 2 == 0]", evens),
        ("['even' if n%2==0 else 'odd' for n in range(6)]", labels),
        ("[n*10 for n in range(10) if n % 2 == 0]", composed),
    ]
    for label, value in rows:
        print(f"{label:<50}{value}")
    print()

    check("filter at end keeps only evens from 0..9",
          evens == [0, 2, 4, 6, 8])
    check("conditional expression labels each item",
          labels == ["even", "odd", "even", "odd", "even", "odd"])
    check("filter + transform compose into one expression",
          composed == [0, 20, 40, 60, 80])


# ----------------------------------------------------------------------------
# Section D — nested / double-for + matrix flatten
# ----------------------------------------------------------------------------

def section_d_nested_double_for() -> None:
    banner("D — Nested / double-for comprehensions & matrix flatten")
    print("Multiple 'for' clauses read left-to-right as NESTED loops:")
    print("the LEFTMOST 'for' is the OUTERMOST loop (it advances slowest).")
    print("The value expression is evaluated once per innermost iteration.\n")

    products = [i * j for i in range(3) for j in range(3)]
    matrix = [[1, 2], [3, 4]]
    flat = [cell for row in matrix for cell in row]

    print(f"{'expression':<54}{'value'}")
    print("-" * 74)
    rows = [
        ("[i*j for i in range(3) for j in range(3)]", products),
        ("[[1,2],[3,4]] flattened via double-for", flat),
    ]
    for label, value in rows:
        print(f"{label:<54}{value}")
    print()

    # The equivalent nested loops, proving the leftmost-is-outermost rule.
    equiv: list[int] = []
    for i in range(3):
        for j in range(3):
            equiv.append(i * j)
    print("Equivalent plain nested loops:")
    print("  for i in range(3):")
    print("      for j in range(3): equiv.append(i*j)")
    print(f"  -> {equiv}\n")

    check("double-for: leftmost for is outermost (slowest) loop",
          products == [0, 0, 0, 0, 1, 2, 0, 2, 4])
    check("matrix flatten via double-for",
          flat == [1, 2, 3, 4])
    check("double-for comprehension == equivalent nested loops",
          products == equiv)


# ----------------------------------------------------------------------------
# Section E — generator expressions: lazy, single-use iterators
# ----------------------------------------------------------------------------

def section_e_genexpr_lazy() -> None:
    banner("E — Generator expressions: lazy & single-use (PEP 289)")
    print("A generator expression uses PARENS, not brackets. It does NOT")
    print("build a list — it returns a generator OBJECT that computes each")
    print("value on demand via next(). It is SINGLE-USE: once exhausted, it")
    print("stays empty forever. Memory cost is O(1) regardless of how many")
    print("items it will eventually yield.\n")

    g = (x * x for x in range(5))
    print("g = (x*x for x in range(5))")
    print(f"type(g).__name__    = {type(g).__name__}")
    print(f"iter(g) is g        = {iter(g) is g}   (a genexpr IS its own iterator)")
    first = next(g)
    second = next(g)
    rest = list(g)
    empty = list(g)
    print(f"next(g)             = {first}    # 0*0, computed lazily")
    print(f"next(g)             = {second}    # 1*1, computed lazily")
    print(f"list(g) (rest)      = {rest}   # consumed the remaining 3")
    print(f"list(g) again       = {empty}   # EMPTY: the generator is exhausted")
    print()

    # Memory contrast: same source, very different sizes.
    big_list = [x for x in range(1000)]
    big_gen = (x for x in range(1000))
    print(f"sys.getsizeof([x for x in range(1000)]) = {sys.getsizeof(big_list)} bytes")
    print(f"sys.getsizeof((x for x in range(1000))) = {sys.getsizeof(big_gen)} bytes")
    print("  (the generator's size is FIXED; the list grows with its length)")
    print()

    # PEP 289 detail: the OUTERMOST iterable is evaluated EAGERLY at create
    # time; only the body is deferred. So errors in the source iterable
    # surface at the comprehension site, not at first next().
    log: list[str] = []

    def make_iter(label: str) -> types.GeneratorType:
        log.append(f"make_iter({label}) called")
        return iter([1, 2, 3])

    log.append("before create")
    g2 = (v for v in make_iter("outer"))   # outermost iter -> EAGER
    log.append("after create, before consume")
    list(g2)                                 # body runs now
    log.append("after consume")
    print(f"PEP 289 — outermost iterable is eager: {log}\n")

    check("genexpr has type 'generator'", type(g).__name__ == "generator")
    g_test = (v for v in range(3))
    check("genexpr is single-use: list() twice -> second empty",
          list(g_test) == [0, 1, 2] and list(g_test) == [])
    check("genexpr uses less memory than the equivalent list",
          sys.getsizeof(big_gen) < sys.getsizeof(big_list))
    check("PEP 289: outermost iterable evaluated at create time",
          log == ["before create", "make_iter(outer) called",
                  "after create, before consume", "after consume"])


# ----------------------------------------------------------------------------
# Section F — readability guardrail: when NOT to use a comprehension
# ----------------------------------------------------------------------------

def section_f_readability_guardrail() -> None:
    banner("F — Readability guardrail: when to STOP using a comprehension")
    print("Comprehensions shine for simple map / filter / flatten. Past one")
    print("line, two for-clauses, or a nested ternary, they HURT readability.")
    print("Rule of thumb: if a reader cannot state the result without")
    print("re-reading, use a for-loop.\n")

    data = list(range(-3, 4))  # [-3, -2, -1, 0, 1, 2, 3]

    # DON'T: nested ternary + filter crammed into one comprehension.
    bad = [(n, "neg" if n < 0 else "zero" if n == 0 else "pos")
           for n in data if n % 2 != 0 or n == 0]

    # DO: the equivalent for-loop — same result, far easier to read & debug.
    good: list[tuple[int, str]] = []
    for n in data:
        if n % 2 != 0 or n == 0:
            if n < 0:
                label = "neg"
            elif n == 0:
                label = "zero"
            else:
                label = "pos"
            good.append((n, label))

    print("data = list(range(-3, 4))   # [-3, -2, -1, 0, 1, 2, 3]\n")
    print("DON'T (nested ternary + filter packed into one comp):")
    print("  bad = [(n, 'neg' if n<0 else 'zero' if n==0 else 'pos')")
    print("         for n in data if n%2 != 0 or n == 0]")
    print(f"  bad  = {bad}\n")
    print("DO (equivalent for-loop — same result, readable):")
    print(f"  good = {good}\n")

    check("both forms produce identical results", bad == good)
    check("the result matches the hand-derived expectation",
          good == [(-3, "neg"), (-1, "neg"), (0, "zero"),
                   (1, "pos"), (3, "pos")])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("comprehensions.py — Phase 1 bundle #4.\n"
          "Every value below is computed by this file; the .md guide pastes\n"
          "it verbatim. Nothing is hand-computed.\n"
          f"Python {sys.version.split()[0]} on this machine.")
    section_a_four_forms()
    section_b_scope_isolation()
    section_c_filter_and_conditional()
    section_d_nested_double_for()
    section_e_genexpr_lazy()
    section_f_readability_guardrail()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
