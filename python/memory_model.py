"""
memory_model.py — Phase 3 bundle #16.

GOAL (one line): show, by printing every value, that a Python variable is a
LABEL on a PyObject (not a box), that `is` compares object identity, that
reference counting governs an object's lifetime, and that mutability + aliasing
is the root of most surprising bugs.

This is the GROUND TRUTH for MEMORY_MODEL.md. Every number, table, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

Stdlib only (sys, copy). id() values change per run, so we assert RELATIONSHIPS
(a is b, refcount deltas), never absolute id() integers.

Run:
    uv run python memory_model.py
"""

from __future__ import annotations

import copy
import sys

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


def _fresh_int(text: str) -> int:
    """Build an int from a string at runtime so two calls return DISTINCT
    objects for any value outside the [-5, 256] small-int cache (bypasses both
    co_consts folding and the cache). Mirrors types_and_truthiness.py."""
    return int(text)


# ----------------------------------------------------------------------------
# Section A — names are labels on objects, not boxes
# ----------------------------------------------------------------------------

def section_a_names_are_labels() -> None:
    banner("A — Names are labels on objects, not boxes")
    print("A Python variable is NOT a box that holds a value. It is a NAME (a")
    print("label) tied to a PyObject. Assignment `b = a` makes b a SECOND label")
    print("on the SAME object a points at — so mutating through b is visible via")
    print("a. This is aliasing, and it is the root of most surprise.\n")

    a = [1, 2, 3]
    b = a            # b is a NEW LABEL on the SAME object as a — no copy made
    b.append(4)      # mutate the shared object through b
    print("a = [1,2,3]")
    print("b = a              # second label on the same object")
    print("b.append(4)        # mutates the ONE object both names see")
    print(f"a is now: {a}")
    print(f"b is now: {b}")
    print(f"a is b: {a is b}")
    print()

    check("a is b after `b = a` (two labels, one object)", a is b)
    check("a == [1,2,3,4] after b.append(4) (same object mutated)",
          a == [1, 2, 3, 4])
    check("b == [1,2,3,4] (alias sees the mutation too)", b == [1, 2, 3, 4])


# ----------------------------------------------------------------------------
# Section B — id() and is: identity vs equality
# ----------------------------------------------------------------------------

def section_b_id_and_is() -> None:
    banner("B — id() and is: identity vs equality")
    print("id(obj) is the object's identity (its address in CPython). `is` asks")
    print("'do two names point at the SAME object?' — it is exactly id(x) ==")
    print("id(y), and it NEVER calls __eq__. `==` asks 'same VALUE?' and calls")
    print("__eq__. Two equal lists are == but NOT is.\n")

    a = [1, 2]
    b = [1, 2]
    c = a            # alias -> same object
    print("a = [1,2];  b = [1,2];  c = a")
    print(f"id(a) = {id(a)}  (varies per run)")
    print(f"id(b) = {id(b)}  (varies per run)")
    print(f"id(c) = {id(c)}  (== id(a): same object)")
    print(f"{'expression':<16}{'result'}")
    print("-" * 34)
    print(f"{'a == b':<16}{a == b}   (equal contents)")
    print(f"{'a is b':<16}{a is b}   (distinct objects)")
    print(f"{'a is c':<16}{a is c}   (c is an alias of a)")
    print()

    check("a == b is True (equal values)", a == b)
    check("a is b is False (two equal lists are distinct objects)", a is not b)
    check("a is c is True (c is an alias of a, same id)", a is c)


# ----------------------------------------------------------------------------
# Section C — reference counting: sys.getrefcount
# ----------------------------------------------------------------------------

def section_c_reference_counting() -> None:
    banner("C — Reference counting: sys.getrefcount")
    print("Every PyObject has a refcount = the number of names/containers")
    print("pointing at it. When the refcount hits 0 the object is freed at once.")
    print("sys.getrefcount(x) returns the count + 1: the +1 is the temporary")
    print("reference created by passing x as the argument. We assert the DELTA")
    print("(alias -> +1, del -> back to base), which is deterministic.\n")

    x = ["only-via-x"]   # fresh, unique object; only `x` references it
    base = sys.getrefcount(x)
    print("x = ['only-via-x']")
    print(f"base  getrefcount(x) = {base}   (= 1 name 'x' + 1 arg artifact)")
    y = x                # add a second label
    after_alias = sys.getrefcount(x)
    print(f"y = x  -> getrefcount(x) = {after_alias}   (delta {after_alias - base})")
    z = x                # add a third label
    after_z = sys.getrefcount(x)
    print(f"z = x  -> getrefcount(x) = {after_z}   (delta {after_z - base})")
    del y, z             # remove the labels
    after_del = sys.getrefcount(x)
    print(f"del y, z -> getrefcount(x) = {after_del}   (back to base)")
    print()

    check("base refcount is 2 (the name + the getrefcount arg artifact)",
          base == 2)
    check("one alias adds exactly 1 (after_alias - base == 1)",
          after_alias - base == 1)
    check("a second alias adds another 1 (after_z - base == 2)",
          after_z - base == 2)
    check("deleting both aliases restores base (after_del == base)",
          after_del == base)


# ----------------------------------------------------------------------------
# Section D — mutability + aliasing: the function-call trap
# ----------------------------------------------------------------------------

def section_d_mutability_aliasing_in_functions() -> None:
    banner("D — Mutability + aliasing: the function-call trap")
    print("Passing a mutable object to a function passes a LABEL on it. The")
    print("function's parameter is an ALIAS: mutating it mutates the caller's")
    print("object. The same aliasing rule creates the mutable-default trap: the")
    print("default `[]` is evaluated ONCE at def-time and shared by every call.\n")

    def append_42(lst: list[int]) -> list[int]:
        lst.append(42)
        return lst

    a = [1, 2, 3]
    b = append_42(a)    # passes a label on a's object; mutates it in place
    print("a = [1,2,3];  b = append_42(a)")
    print(f"a after call: {a}   (caller's object was mutated)")
    print(f"b is a: {b is a}    (function returned the same object)")
    print()

    check("append_42 mutated the caller's list (a == [1,2,3,42])",
          a == [1, 2, 3, 42])
    check("return value is the same object (b is a)", b is a)

    def with_default(items: list[int] = []) -> list[int]:  # noqa: B006
        items.append(1)
        return items

    r1 = with_default()
    r2 = with_default()
    r3 = with_default()
    print("with_default(items=[]) called 3x with NO argument:")
    print(f"  r1 = {r1}")
    print(f"  r2 = {r2}")
    print(f"  r3 = {r3}")
    print(f"  r1 is r2: {r1 is r2}  (default [] is ONE object, eval'd once)")
    print(f"  with_default.__defaults__ = {with_default.__defaults__}")
    print()

    check("mutable default is shared across calls (r1 is r2)", r1 is r2)
    check("after 3 calls the shared default == [1,1,1]",
          with_default.__defaults__[0] == [1, 1, 1])


# ----------------------------------------------------------------------------
# Section E — immutable container, mutable contents
# ----------------------------------------------------------------------------

def section_e_immutable_container_mutable_contents() -> None:
    banner("E — Immutable container, mutable contents")
    print("A tuple is immutable: you cannot REASSIGN its slots. But immutability")
    print("is SHALLOW — if a slot HOLDS a mutable object, you can mutate that")
    print("object through the tuple. The tuple's id() and length never change;")
    print("only the pointed-at object's contents do.\n")

    t: tuple[int | list[int], ...] = (1, [2, 3])
    inner_id_before = id(t[1])
    print(f"t = (1, [2,3]);  id(t[1]) = {inner_id_before}  (varies per run)")

    raised = False
    err_msg = ""
    try:
        t[0] = 99   # tuple slot reassignment -> TypeError
    except TypeError as exc:
        raised = True
        err_msg = str(exc)
    print(f"t[0] = 99  ->  {'TypeError: ' + err_msg if raised else 'no error'}")

    t[1].append(4)   # mutating the inner list THROUGH the tuple works
    inner_id_after = id(t[1])
    print(f"t[1].append(4)  ->  t = {t}")
    print(f"id(t[1]) after append = {inner_id_after}  "
          f"(== before: {inner_id_after == inner_id_before}, same object)")
    print()

    check("tuple slot reassignment raises TypeError", raised)
    check("inner list mutation works (t == (1, [2,3,4]))", t == (1, [2, 3, 4]))
    check("the inner object is the SAME object (id unchanged)",
          inner_id_after == inner_id_before)
    check("the tuple length is unchanged (len(t) == 2)", len(t) == 2)


# ----------------------------------------------------------------------------
# Section F — copy.copy (shallow) vs copy.deepcopy (recursive)
# ----------------------------------------------------------------------------

def section_f_shallow_vs_deepcopy() -> None:
    banner("F — copy.copy (shallow) vs copy.deepcopy (recursive)")
    print("copy.copy(obj) makes a NEW outer object whose SLOTS still point at the")
    print("SAME inner objects as the original (shared). copy.deepcopy(obj) makes")
    print("a fully independent clone — it recurses, copying every mutable inside.")
    print("Shallow shares inner mutables; deep shares nothing.\n")

    orig = [[1, 2], [3, 4]]
    shallow = copy.copy(orig)
    deep = copy.deepcopy(orig)
    print(f"orig    = {orig}")
    print("shallow = copy.copy(orig)      (new outer; SHARED inner lists)")
    print("deep    = copy.deepcopy(orig)  (new outer; NEW inner lists)")
    print()
    print(f"{'relationship':<30}{'result'}")
    print("-" * 46)
    print(f"{'orig is shallow':<30}{orig is shallow}   (new outer object)")
    print(f"{'orig is deep':<30}{orig is deep}   (new outer object)")
    print(f"{'orig[0] is shallow[0]':<30}{orig[0] is shallow[0]}   (SHARED inner)")
    print(f"{'orig[0] is deep[0]':<30}{orig[0] is deep[0]}   (independent inner)")
    print()

    shallow[0].append(99)   # shared inner -> leaks into orig
    print(f"shallow[0].append(99) -> orig[0] = {orig[0]}   (shared: LEAKED)")
    print(f"                      -> deep[0]  = {deep[0]}   (independent)")
    deep[1].append(77)      # deep's own inner -> does NOT leak into orig
    print(f"deep[1].append(77)    -> orig[1] = {orig[1]}   (independent)")
    print()

    check("shallow copy is a distinct OUTER object (orig is not shallow)",
          orig is not shallow)
    check("deepcopy is a distinct OUTER object (orig is not deep)",
          orig is not deep)
    check("shallow copy SHARES inner lists (orig[0] is shallow[0])",
          orig[0] is shallow[0])
    check("deepcopy makes independent inner lists (orig[0] is not deep[0])",
          orig[0] is not deep[0])
    check("shallow mutation leaked into orig (orig[0] == [1,2,99])",
          orig[0] == [1, 2, 99])
    check("deepcopy mutation did NOT leak (orig[1] == [3,4])",
          orig[1] == [3, 4])


# ----------------------------------------------------------------------------
# Section G — interning: the small-int cache and string literals
# ----------------------------------------------------------------------------

def section_g_interning() -> None:
    banner("G — Interning: the small-int cache and string literals")
    print("CPython pre-allocates ONE int object for every value in [-5, 256]; any")
    print("occurrence of such a value is a reference to that shared singleton, so")
    print("`256 is 256` is True. Past the cache, identity is NOT guaranteed — we")
    print("build 257 via int('257') at runtime so it is reliably distinct. CPython")
    print("also interns identifier-like string literals; sys.intern() does it")
    print("explicitly. (Full small-int demo: types_and_truthiness Section E.)\n")

    a = -5
    b = -5
    print(f"a = -5; b = -5;          a is b: {a is b}   (lower cache bound)")
    a = 256
    b = 256
    print(f"a = 256; b = 256;        a is b: {a is b}   (upper cache bound)")
    big1 = _fresh_int("257")
    big2 = _fresh_int("257")
    print(f"int('257') is int('257'): {big1 is big2}   (OUT of cache -> distinct)")
    print()

    check("int('-5') is int('-5') (lower small-int cache bound shared)",
          _fresh_int("-5") is _fresh_int("-5"))
    check("int('256') is int('256') (upper small-int cache bound shared)",
          _fresh_int("256") is _fresh_int("256"))
    check("int('257') is NOT int('257') (out of cache)",
          _fresh_int("257") is not _fresh_int("257"))

    lit1 = "interned"
    lit2 = "interned"
    built = "".join(["inter", "ned"])  # constructed at runtime -> not auto-interned
    print('lit1 = "interned";  lit2 = "interned"')
    print('built = "".join(["inter","ned"])   (runtime-built)')
    print(f"lit1 == lit2            : {lit1 == lit2}")
    print(f"lit1 is lit2            : {lit1 is lit2}   (identifier-like literal)")
    print(f"built == lit1           : {built == lit1}")
    print(f"built is lit1           : {built is lit1}   (runtime-built, distinct)")
    print(f"sys.intern(built) is lit1: {sys.intern(built) is lit1}   (explicit intern)")
    print()

    check("equal string literals compare equal (lit1 == lit2)", lit1 == lit2)
    check("runtime-built string equals the literal (built == lit1)",
          built == lit1)
    check("sys.intern() makes them identical (sys.intern(built) is lit1)",
          sys.intern(built) is lit1)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("memory_model.py — Phase 3 bundle #16.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {sys.version.split()[0]} on this machine.")
    section_a_names_are_labels()
    section_b_id_and_is()
    section_c_reference_counting()
    section_d_mutability_aliasing_in_functions()
    section_e_immutable_container_mutable_contents()
    section_f_shallow_vs_deepcopy()
    section_g_interning()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
