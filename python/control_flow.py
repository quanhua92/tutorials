"""
control_flow.py — Bundle #7 (Phase 1).

GOAL (one line): show, by printing every value, how Python's subtle control-flow
constructs actually behave — for/else, short-circuit value semantics, structural
match-case (3.10+), and the walrus assignment-expression (3.8+).

This is the GROUND TRUTH for CONTROL_FLOW.md. Every number, table, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

Run:
    uv run python control_flow.py
"""

from __future__ import annotations

from dataclasses import dataclass

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
# Section A — if / elif / else (and why there was never a switch)
# ----------------------------------------------------------------------------

def section_a_if_elif_else() -> None:
    banner("A — if / elif / else: exactly one branch runs")
    print("The if statement selects exactly one suite by evaluating each")
    print("condition top-to-bottom; the first truthy one wins, the rest are")
    print("skipped without evaluation. There is NO 'switch' in Python")
    print("pre-3.10; structural 'match' (Section D) replaces it.\n")

    def classify(n: int) -> str:
        if n > 0:
            return "positive"
        elif n < 0:
            return "negative"
        else:
            return "zero"

    print(f"{'call':<16}{'result'}")
    print("-" * 28)
    for n in (-5, 0, 42):
        print(f"{f'classify({n})':<16}{classify(n)}")
    print()

    evaluated: list[str] = []

    def side_effect(label: str, value: bool) -> bool:
        evaluated.append(label)
        return value

    if side_effect("A", False):
        pass
    elif side_effect("B", True):
        pass
    elif side_effect("C", True):
        pass

    print(f"elif chain evaluated: {evaluated}  (C skipped — B already won)")
    check("elif short-circuits: only A and B evaluated",
          evaluated == ["A", "B"])
    check("classify(42) == 'positive'", classify(42) == "positive")
    check("classify(0) == 'zero'", classify(0) == "zero")
    check("classify(-5) == 'negative'", classify(-5) == "negative")


# ----------------------------------------------------------------------------
# Section B — for/else & while/else (prime search)
# ----------------------------------------------------------------------------

def section_b_loop_else() -> None:
    banner("B — for/else & while/else: else runs IFF loop did NOT break")
    print("Counterintuitive but precise: the 'else' on a for/while runs when")
    print("the loop completes WITHOUT hitting 'break'. Classic use: prime")
    print("testing — else means 'no divisor found = prime'.\n")

    def is_prime_for(n: int) -> tuple[bool, int]:
        if n < 2:
            return False, 0
        last = 0
        for d in range(2, n):
            last = d
            if n % d == 0:
                break
        else:
            return True, last
        return False, last

    def is_prime_while(n: int) -> tuple[bool, int]:
        if n < 2:
            return False, 0
        d = 2
        while d < n:
            if n % d == 0:
                break
            d += 1
        else:
            return True, d - 1
        return False, d

    print(f"{'n':<5}{'for/else':<11}{'while/else':<13}{'note'}")
    print("-" * 54)
    for n in (2, 7, 9, 15):
        fp, fl = is_prime_for(n)
        wp, _ = is_prime_while(n)
        note = ("PRIME: else ran (no break)" if fp
                else f"composite: broke on {fl}")
        print(f"{n:<5}{str(fp):<11}{str(wp):<13}{note}")
    print()

    fp7, _ = is_prime_for(7)
    fp9, fl9 = is_prime_for(9)
    wp7, _ = is_prime_while(7)
    check("for/else: 7 is prime (else ran, loop exhausted)",
          fp7 is True)
    check("for/else: 9 composite (break hit, else skipped)",
          fp9 is False)
    check("for/else: 9 broke on divisor 3", fl9 == 3)
    check("while/else: 7 is prime (else ran)", wp7 is True)
    check("for/else == while/else for n in [2, 30)",
          all(is_prime_for(n)[0] == is_prime_while(n)[0]
              for n in range(2, 30)))


# ----------------------------------------------------------------------------
# Section C — short-circuit value semantics
# ----------------------------------------------------------------------------

def section_c_short_circuit_values() -> None:
    banner("C — and / or return the OPERAND value, not a bool")
    print("Reference §6.11: 'x and y' returns x if x is false, else y;")
    print("'x or y' returns x if x is true, else y. The result keeps its")
    print("original value and type — NOT coerced to True/False.\n")

    print(f"{'expression':<24}{'result':<14}{'type'}")
    print("-" * 48)
    rows: list[tuple[str, object]] = [
        ("0 or 'default'", 0 or "default"),
        ("'' or 0", "" or 0),
        ("'a' or 'b'", "a" or "b"),
        ("[1] or []", [1] or []),
        ("1 and 2", 1 and 2),
        ("0 and 2", 0 and 2),
        ("None and 'x'", None and "x"),
        ("'x' and 0 and 3", "x" and 0 and 3),
    ]
    for label, value in rows:
        print(f"{label:<24}{str(value):<14}{type(value).__name__}")
    print()

    log: list[str] = []

    def f(tag: str, value: object) -> object:
        log.append(tag)
        return value

    r_and = None and f("AND_RIGHT", "v")
    r_or = "truthy" or f("OR_RIGHT", "v")
    print(f"None and f(...) -> {r_and!r}  /  'truthy' or f(...) -> {r_or!r}")
    print(f"side-effect log: {log}  (neither RIGHT operand was called)")
    print()

    check("0 or 'default' == 'default' (returns right operand)",
          (0 or "default") == "default")
    check("1 and 2 == 2 (returns right operand)", (1 and 2) == 2)
    check("None and f(...) returns None (left, falsy)",
          r_and is None)
    check("'truthy' or f(...) returns 'truthy' (left, truthy)",
          r_or == "truthy")
    check("right operand NOT evaluated when left short-circuits",
          log == [])

    config = {"host": "", "port": 0}
    host = config.get("host") or "localhost"
    port = config.get("port") or 8080
    print(f"cfg.get('host') or 'localhost' -> {host!r}")
    print(f"cfg.get('port') or 8080       -> {port}")
    check("'' or 'localhost' picks default", host == "localhost")
    check("0 or 8080 picks default", port == 8080)


# ----------------------------------------------------------------------------
# Section D — match/case: structural pattern matching (PEP 634, 3.10+)
# ----------------------------------------------------------------------------

@dataclass
class Point:
    x: int
    y: int


def section_d_match_case() -> None:
    banner("D — match/case: structural pattern matching (PEP 634, 3.10+)")
    print("'match' is NOT a C switch (equality only). It does STRUCTURAL")
    print("matching: a pattern tests shape AND binds names. Patterns are")
    print("tried top-to-bottom; first match (with true guard, if any) wins.\n")

    def describe(obj: object) -> str:
        match obj:
            case 1 | 2 | 3:
                return f"small int literal: {obj}"
            case [a, b]:
                return f"two-element seq: a={a}, b={b}"
            case {"type": "ok", "data": d}:
                return f"ok-msg with data={d!r}"
            case Point(0, y):
                return f"Point on y-axis at y={y}"
            case Point(x, y) if x == y:
                return f"Point on diagonal: ({x},{y})"
            case Point(x, y):
                return f"Point at ({x},{y})"
            case _:
                return "something else"

    cases: list[object] = [
        2,
        ["hip", "hop"],
        {"type": "ok", "data": [1, 2]},
        Point(0, 5),
        Point(3, 3),
        Point(1, 9),
        "literally anything",
    ]
    print(f"{'subject':<36}{'match outcome'}")
    print("-" * 68)
    for c in cases:
        print(f"{repr(c):<36}{describe(c)}")
    print()

    check("literal OR: describe(2) starts with 'small int'",
          describe(2).startswith("small int"))
    check("sequence pattern binds a,b from ['hip','hop']",
          describe(["hip", "hop"]) == "two-element seq: a=hip, b=hop")
    check("mapping pattern binds d from ok-msg",
          describe({"type": "ok", "data": [1, 2]})
          == "ok-msg with data=[1, 2]")
    check("class pattern Point(0, y) binds y=5",
          describe(Point(0, 5)) == "Point on y-axis at y=5")
    check("class + guard: Point(3,3) on diagonal",
          describe(Point(3, 3)) == "Point on diagonal: (3,3)")
    check("wildcard _ matches 'literally anything'",
          describe("literally anything") == "something else")


# ----------------------------------------------------------------------------
# Section E — the walrus := (PEP 572, 3.8+)
# ----------------------------------------------------------------------------

def section_e_walrus() -> None:
    banner("E — the walrus := (PEP 572, 3.8+): bind AND return in one expr")
    print("An assignment expression (name := expr) evaluates expr, binds it")
    print("to name, AND returns the value as the value of the whole")
    print("expression. The name is scoped to the nearest enclosing function")
    print("scope (NOT a new block scope).\n")

    print(f"{'expression':<30}{'result':<10}{'n after'}")
    print("-" * 50)
    cond = (n := 10) > 5
    print(f"{'(n := 10) > 5':<30}{str(cond):<10}{n}")
    print()

    check("(n := 10) > 5 is True", cond is True)
    check("after `n := 10`, n == 10", n == 10)

    it = iter(["alpha", "beta", "gamma"])
    collected: list[str] = []
    while (line := next(it, "")):
        collected.append(line)
    print(f"while (line := next(it, '')): collected = {collected}")
    check("walrus-while collects all 3 lines until '' sentinel",
          collected == ["alpha", "beta", "gamma"])

    data = [1, 2, 3, 4, 5, 6]
    pairs: list[tuple[int, int]] = [
        (x, doubled)
        for x in data
        if (doubled := x * 2) > 4
    ]
    print("[(x, doubled) for x in data if (doubled := x*2) > 4]")
    print(f"  -> {pairs}")
    check("walrus in comprehension filter binds doubled",
          pairs == [(3, 6), (4, 8), (5, 10), (6, 12)])

    if (leaked := "bound by walrus in if-block"):
        pass
    print(f"\nafter if-block, `leaked` still in scope: {leaked!r}")
    check("walrus target leaks to enclosing function scope",
          leaked == "bound by walrus in if-block")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("control_flow.py — Phase 1 bundle #7.\n"
          "Every value below is computed by this file; the .md guide\n"
          "pastes it verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_if_elif_else()
    section_b_loop_else()
    section_c_short_circuit_values()
    section_d_match_case()
    section_e_walrus()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
