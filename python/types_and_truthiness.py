"""
types_and_truthiness.py — Bundle #1 (Phase 1, style anchor).

GOAL (one line): show, by printing every value, how Python's numeric tower,
truthiness rules, and the object model make `==`/`is` behave the way they do.

This is the GROUND TRUTH for TYPES_AND_TRUTHINESS.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python types_and_truthiness.py
"""

from __future__ import annotations

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
# Section A — the numeric tower: bool ⊂ int ⊂ float ⊂ complex
# ----------------------------------------------------------------------------

def section_a_numeric_tower() -> None:
    banner("A — The numeric tower: bool ⊂ int ⊂ float ⊂ complex")
    print("Python has three distinct numeric types (int, float, complex). bool")
    print("is a SUBTYPE of int. 'Subtype' means every bool IS an int, but not")
    print("every int is a bool. isinstance() walks this chain.\n")

    print(f"{'expression':<28}{'result':<8}{'type':<12}")
    print("-" * 48)
    for label, value in [
        ("isinstance(True, bool)", isinstance(True, bool)),
        ("isinstance(True, int)", isinstance(True, int)),
        ("isinstance(True, float)", isinstance(True, float)),
        ("isinstance(1, bool)", isinstance(1, bool)),
        ("isinstance(1, int)", isinstance(1, int)),
        ("issubclass(bool, int)", issubclass(bool, int)),
        ("type(True).__mro__", type(True).__mro__),
        ("type(1).__mro__", type(1).__mro__),
    ]:
        print(f"{label:<28}{str(value):<8}")
    print()

    check("bool is a subclass of int", issubclass(bool, int))
    check("isinstance(True, int) is True", isinstance(True, int))
    check("isinstance(1, bool) is False (int is NOT a bool)",
          not isinstance(1, bool))
    # The tower collapses on == because bool values equal their int counterparts.
    check("1 == True is True", 1 == True)
    check("0 == False is True", 0 == False)
    check("True == 1.0 is True (numeric coercion across the tower)",
          True == 1.0)


# ----------------------------------------------------------------------------
# Section B — truth value testing: the full falsy table
# ----------------------------------------------------------------------------

def section_b_truth_value_testing() -> None:
    banner("B — Truth value testing: bool(x) for every builtin")
    print("Rule (docs.python.org stdtypes.html#truth-value-testing): an object")
    print("is False if it is one of the builtins below, OR its class defines")
    print("__bool__() -> False, OR (no __bool__) __len__() -> 0. Everything")
    print("else is True.\n")

    falsy = [
        ("None", None),
        ("False", False),
        ("0 (int)", 0),
        ("0.0 (float)", 0.0),
        ("0j (complex)", 0j),
        ("'' (str)", ""),
        ("() (tuple)", ()),
        ("[] (list)", []),
        ("{} (dict)", {}),
        ("set() (set)", set()),
        ("range(0)", range(0)),
    ]
    truthy = [
        ("True", True),
        ("1 (int)", 1),
        ("'a' (str)", "a"),
        ("[0] (list)", [0]),
        ("range(1)", range(1)),
    ]

    print(f"{'value':<16}{'bool(x)':<10}{'truthy?'}")
    print("-" * 36)
    for name, x in falsy + truthy:
        print(f"{name:<16}{str(bool(x)):<10}"
              f"{'TRUTHY' if bool(x) else 'falsy'}")
    print()

    check("bool(None) is False", bool(None) is False)
    check("bool(0) is False", bool(0) is False)
    check("bool([]) is False", bool([]) is False)
    check("bool(set()) is False", bool(set()) is False)
    check("bool('') is False", bool("") is False)
    check("bool(range(0)) is False", bool(range(0)) is False)

    # Custom objects steer truthiness through __bool__ first, then __len__.
    class BoolFalse:
        def __bool__(self) -> bool:
            return False

    class LenZero:
        def __len__(self) -> int:
            return 0

    class LenZeroBoolTrue(LenZero):  # __bool__ wins over __len__
        def __bool__(self) -> bool:
            return True

    print(f"{'class':<28}{'__bool__':<10}{'__len__':<10}{'bool(obj)'}")
    print("-" * 58)
    print(f"{'BoolFalse':<28}{'False':<10}{'-':<10}{bool(BoolFalse())}")
    print(f"{'LenZero':<28}{'-':<10}{'0':<10}{bool(LenZero())}")
    print(f"{'LenZeroBoolTrue':<28}{'True':<10}{'0':<10}"
          f"{bool(LenZeroBoolTrue())}")
    print()
    check("object with __bool__->False is falsy", not BoolFalse())
    check("object with only __len__->0 is falsy", not LenZero())
    check("__bool__ takes precedence over __len__", bool(LenZeroBoolTrue()))


# ----------------------------------------------------------------------------
# Section C — bool is an int subclass: arithmetic with True/False
# ----------------------------------------------------------------------------

def section_c_bool_as_int() -> None:
    banner("C — bool arithmetic: True and False behave as 1 and 0")
    print("Because bool subclasses int, True == 1 and False == 0. Arithmetic")
    print("promotes the result to int (bool operators &, |, ^ keep it bool).\n")

    print(f"{'expression':<34}{'result':<10}{'type'}")
    print("-" * 56)
    rows = [
        ("True + True", True + True),
        ("True + False", True + False),
        ("True * 3", True * 3),
        ("sum([True, False, True, True])", sum([True, False, True, True])),
        ("(True + True).__class__.__name__", (True + True).__class__.__name__),
        ("(True & False).__class__.__name__", (True & False).__class__.__name__),
        ("bool(0)", bool(0)),
        ("bool(1)", bool(1)),
        ("bool(42)", bool(42)),
        ("bool(-1)", bool(-1)),
    ]
    for label, value in rows:
        tname = type(value).__name__
        print(f"{label:<34}{str(value):<10}{tname}")
    print()

    check("True + True == 2", True + True == 2)
    check("sum([True, False, True]) == 2", sum([True, False, True]) == 2)
    check("True + True has type int (not bool)",
          type(True + True) is int)
    check("True & False has type bool (bitwise keeps bool)",
          type(True & False) is bool)
    check("bool(42) is True (any nonzero int is truthy)", bool(42) is True)
    check("bool(-1) is True (negatives are truthy too)", bool(-1) is True)


# ----------------------------------------------------------------------------
# Section D — numeric precision & floor division
# ----------------------------------------------------------------------------

def section_d_numeric_precision() -> None:
    banner("D — Numeric precision & floor division (//)")
    print("Floats are IEEE 754 binary64: 53 bits of mantissa. Most decimal")
    print("fractions (like 0.1) cannot be represented exactly, so arithmetic")
    print("drifts. // is FLOOR division: it rounds toward -infinity, not 0.\n")

    print(f"{'expression':<38}{'result'}")
    print("-" * 62)
    rows = [
        ("0.1 + 0.2", 0.1 + 0.2),
        ("0.1 + 0.2 == 0.3", 0.1 + 0.2 == 0.3),
        ("0.1 + 0.2 == 0.30000000000000004", 0.1 + 0.2 == 0.30000000000000004),
        ("(0.1).as_integer_ratio()", (0.1).as_integer_ratio()),
        ("7 // 2", 7 // 2),
        ("-7 // 2", -7 // 2),
        ("7 // -2", 7 // -2),
        ("-7 // -2", -7 // -2),
        ("7 % 2", 7 % 2),
        ("-7 % 2", -7 % 2),
        ("int(2**53)", int(2**53)),
        ("int(2**53) == float(2**53)", int(2**53) == float(2**53)),
        ("int(2**53 + 1) == float(2**53 + 1)",
         int(2**53 + 1) == float(2**53 + 1)),
        ("float(2**53 + 1)", float(2**53 + 1)),
        ("float(2**53 + 2)", float(2**53 + 2)),
    ]
    for label, value in rows:
        print(f"{label:<38}{value!r}")
    print()

    check("0.1 + 0.2 == 0.30000000000000004 (binary float drift)",
          0.1 + 0.2 == 0.30000000000000004)
    check("7 // 2 == 3", 7 // 2 == 3)
    check("-7 // 2 == -4 (floor, NOT truncation toward 0)", -7 // 2 == -4)
    check("7 // -2 == -4 (floor)", 7 // -2 == -4)
    check("-7 // -2 == 3 (floor of 3.5)", -7 // -2 == 3)
    check("-7 % 2 == 1 (// and % keep divisor sign consistent)", -7 % 2 == 1)
    # At 2**53 the float mantissa runs out: 2**53+1 is NOT representable.
    check("2**53 is exactly representable as float", int(2**53) == float(2**53))
    check("2**53 + 1 is NOT representable as float (lost a bit)",
          int(2**53 + 1) != float(2**53 + 1))


# ----------------------------------------------------------------------------
# Section E — equality (==) vs identity (is); the small-int cache
# ----------------------------------------------------------------------------

def _fresh_int(text: str) -> int:
    """Construct an int from a string at runtime (bypasses co_consts folding
    and the small-int cache), so two calls return distinct objects for any
    value outside [-5, 256]."""
    return int(text)


def section_e_equality_vs_identity() -> None:
    banner("E — Equality (==) vs identity (is); the [-5, 256] int cache")
    print("== calls __eq__ and compares VALUES. `is` compares IDENTITY: do two")
    print("names point at the SAME object (same id())? `is` never calls")
    print("__eq__ and cannot be overloaded. CPython caches small ints, so two")
    print("independent occurrences of e.g. 256 are the SAME object.\n")

    # Values: two equal lists are NOT the same object (a fresh list each time).
    a = [1, 2]
    b = [1, 2]
    print(f"{'expression':<22}{'result'}")
    print("-" * 40)
    print(f"{'a = [1,2]; b = [1,2]':<22}")
    print(f"{'a == b':<22}{a == b}")
    print(f"{'a is b':<22}{a is b}")
    print(f"{'id(a) == id(b)':<22}{id(a) == id(b)}")
    print(f"{'id(a) != id(b)':<22}{id(a) != id(b)}")
    print()

    check("a == b is True (equal contents)", a == b)
    check("a is b is False (distinct list objects)", a is not b)

    # Small-int cache: [-5, 256] inclusive (docs.python.org c-api/long.html,
    # PyLong_FromLong). Values in that range are shared singletons; values
    # outside it are fresh objects every time they are constructed at runtime.
    # We build each via int(<str>) so no co_consts folding can mask the effect.
    print("CPython small-int cache covers [-5, 256] inclusive.")
    print("Below: each int is built via int(<str>) at runtime.\n")
    print(f"{'expression':<30}{'result':<8}{'note'}")
    print("-" * 66)
    for text in ("-5", "0", "100", "256", "257", "1000"):
        v1 = _fresh_int(text)
        v2 = _fresh_int(text)
        same = v1 is v2
        n = int(text)
        note = ("in cache -> shared" if same
                else "out of cache -> distinct objects")
        flag = "IN " if -5 <= n <= 256 else "OUT"
        print(f"{f'int({text!r}) is int({text!r})':<30}{str(same):<8}"
              f"[{flag}] {note}")
    print()

    check("int('-5') is int('-5') (lower cache bound shared)",
          _fresh_int("-5") is _fresh_int("-5"))
    check("int('256') is int('256') (upper cache bound shared)",
          _fresh_int("256") is _fresh_int("256"))
    check("int('257') is NOT int('257') (just past the cache)",
          _fresh_int("257") is not _fresh_int("257"))
    check("int('1000') is NOT int('1000') (well past the cache)",
          _fresh_int("1000") is not _fresh_int("1000"))

    # A taste of string interning — full theory is in MEMORY_MODEL. 🔗
    s1 = "wombat"
    s2 = "wombat"
    print('s1 = "wombat"; s2 = "wombat"')
    print(f"{'s1 == s2':<22}{s1 == s2}")
    print(f"{'s1 is s2':<22}{s1 is s2}  (often shared: CPython interns"
          " look-alike literals)")
    print()
    check("equal str literals compare equal (==)", s1 == s2)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("types_and_truthiness.py — Phase 1 bundle #1 (style anchor).\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_numeric_tower()
    section_b_truth_value_testing()
    section_c_bool_as_int()
    section_d_numeric_precision()
    section_e_equality_vs_identity()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
