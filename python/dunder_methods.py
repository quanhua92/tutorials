"""
dunder_methods.py — Phase 2 bundle (#10).

GOAL (one line): show, by printing every value, that "dunder methods" are not
magic — they ARE the Python data model: every operator, built-in, and protocol
(`+`, `len()`, `str()`, `x[i]`, `for x in obj`, `bool(x)`, `with`, ...) is a
named hook on your class that the interpreter looks up on the TYPE.

This is the GROUND TRUTH for DUNDER_METHODS.md. Every value, table, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

Run:
    uv run python dunder_methods.py
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
# Section A — the model: syntax -> type(x).__dunder__
# ----------------------------------------------------------------------------

def section_a_the_model() -> None:
    banner("A — The model: every operator is a dunder lookup on the TYPE")
    print("Operators and built-ins are syntactic sugar. The interpreter does")
    print("NOT call x.__add__(y) directly; it calls type(x).__add__(x, y) — a")
    print("lookup on the TYPE, then an ordinary function call with x as the")
    print("first argument. This is why you cannot overload an operator by")
    print("stashing a function in the instance dict.\n")

    print(f"{'syntax':<16}{'becomes (CPython dispatch)'}")
    print("-" * 64)
    rows = [
        ("x + y",      "type(x).__add__(x, y)"),
        ("y + x",      "type(x).__add__ first; if NotImplemented, type(y).__radd__"),
        ("x += y",     "type(x).__iadd__(x, y); else x = x + y"),
        ("len(x)",     "type(x).__len__(x)"),
        ("bool(x)",    "type(x).__bool__(x), else type(x).__len__(x)"),
        ("repr(x)",    "type(x).__repr__(x)"),
        ("str(x)",     "type(x).__str__(x), else type(x).__repr__(x)"),
        ("x[i]",       "type(x).__getitem__(x, i)"),
        ("v in x",     "type(x).__contains__(x, v), else __iter__/__getitem__"),
        ("for v in x", "type(x).__iter__(x), else __getitem__ from 0"),
        ("x == y",     "type(x).__eq__(x, y)"),
        ("hash(x)",    "type(x).__hash__(x)"),
        ("with x:",    "type(x).__enter__(x) / type(x).__exit__(x, ...)"),
    ]
    for syn, becomes in rows:
        print(f"{syn:<16}{becomes}")
    print()

    class V:
        def __add__(self, other: object) -> str:
            return f"V.__add__({other!r})"

    v = V()
    print(f"v + 'z'                   -> {v + 'z'}")
    print(f"v.__add__('z')            -> {v.__add__('z')}  (found via type)")
    print(f"type(v).__add__(v, 'z')   -> {type(v).__add__(v, 'z')}  (operator path)")
    print()
    check("'v + z' dispatches to type(v).__add__",
          (v + "z") == type(v).__add__(v, "z"))


# ----------------------------------------------------------------------------
# Section B — __repr__ (for devs) vs __str__ (for users)
# ----------------------------------------------------------------------------

def section_b_repr_str() -> None:
    banner("B — __repr__ (official, for devs) vs __str__ (informal, for users)")
    print("repr(x) computes the 'official' string — unambiguous, and ideally a")
    print("valid Python expression that recreates an equal object. str(x) is the")
    print("'informal' pretty string. If __str__ is absent, str() falls back to")
    print("__repr__. The !r flag in f-strings forces repr.\n")

    class Point:
        def __init__(self, x: int, y: int) -> None:
            self.x, self.y = x, y

        def __repr__(self) -> str:
            return f"Point({self.x}, {self.y})"

        def __str__(self) -> str:
            return f"({self.x}, {self.y})"

        def __eq__(self, other: object) -> bool:
            return (isinstance(other, Point)
                    and (self.x, self.y) == (other.x, other.y))

    p = Point(1, 2)
    print(f"repr(p)       = {repr(p)}")
    print(f"str(p)        = {str(p)}")
    print(f"f'{{p}}'   = {p}     (plain interpolation uses __str__)")
    print(f"f'{{p!r}}' = {p!r}   (!r conversion forces __repr__)")
    recreated = eval(repr(p))
    print(f"eval(repr(p)) == p  -> {recreated == p}   (the __repr__ round-trip ideal)")
    print()
    check("repr(p) == 'Point(1, 2)'", repr(p) == "Point(1, 2)")
    check("str(p) == '(1, 2)'", str(p) == "(1, 2)")
    check("eval(repr(p)) recreates an equal Point", eval(repr(p)) == p)


# ----------------------------------------------------------------------------
# Section C — __eq__ + __hash__ contract (the unhashable trap)
# ----------------------------------------------------------------------------

def section_c_eq_hash_contract() -> None:
    banner("C — __eq__ + __hash__ contract: the unhashable trap")
    print("object.__eq__ defaults to IDENTITY (is). object.__hash__ defaults to")
    print("id(). BUT: if you define __eq__ and do NOT define __hash__, Python")
    print("silently sets __hash__ = None — your object becomes UNHASHABLE, so")
    print("set(), dict keys, and functools.lru_cache all raise TypeError.\n")

    class Plain:
        pass

    a, b = Plain(), Plain()
    print(f"Plain() == Plain() -> {a == b}   (default __eq__ is identity)")
    print(f"a == a             -> {a == a}")
    print(f"Plain is hashable  -> {isinstance(hash(a), int)}  "
          f"(default __hash__ derives from id)")
    print()
    check("default __eq__ is identity", a == a and a != b)

    class EqOnly:
        def __init__(self, n: int) -> None:
            self.n = n

        def __eq__(self, other: object) -> bool:
            return isinstance(other, EqOnly) and self.n == other.n

    print(f"EqOnly.__hash__ = {EqOnly.__hash__}   (silently set to None!)")
    try:
        hash(EqOnly(1))
        err = "(no error)"
    except TypeError as e:
        err = f"TypeError: {e}"
    print(f"hash(EqOnly(1))    -> {err}")
    try:
        s = {EqOnly(1), EqOnly(2)}
        err2 = f"(no error, len={len(s)})"
    except TypeError as e:
        err2 = f"TypeError: {e}"
    print(f"{{EqOnly(1), EqOnly(2)}} -> {err2}")
    print()

    class EqHash:
        def __init__(self, n: int) -> None:
            self.n = n

        def __eq__(self, other: object) -> bool:
            return isinstance(other, EqHash) and self.n == other.n

        def __hash__(self) -> int:
            return hash(self.n)

    s3 = {EqHash(1), EqHash(1), EqHash(2)}
    print(f"hash(EqHash(1)) = {hash(EqHash(1))}  (== hash(1))")
    print(f"{{EqHash(1), EqHash(1), EqHash(2)}} -> len={len(s3)}  (dedup works)")
    print()
    check("defining __eq__ without __hash__ makes __hash__ None",
          EqOnly.__hash__ is None)
    check("EqOnly is unhashable (hash() raises TypeError)",
          not callable(EqOnly.__hash__))
    check("equal EqHash objects have equal hash",
          hash(EqHash(1)) == hash(EqHash(1)) == hash(1))
    check("set dedupes EqHash by __eq__/__hash__", len(s3) == 2)


# ----------------------------------------------------------------------------
# Section D — __bool__ / __len__ precedence
# ----------------------------------------------------------------------------

def section_d_bool_len_precedence() -> None:
    banner("D — bool(x): __bool__ wins over __len__")
    print("When Python needs a truth value it calls PyObject_IsTrue: try")
    print("__bool__ first; if absent, fall back to __len__ (0 -> False); if")
    print("neither is defined, the object is truthy. A class with BOTH")
    print("methods uses __bool__ and ignores __len__.\n")

    class LenOnly:
        def __len__(self) -> int:
            return 0

    class BoolTrueLenZero:
        def __bool__(self) -> bool:
            return True

        def __len__(self) -> int:
            return 0

    class BoolFalseLenBig:
        def __bool__(self) -> bool:
            return False

        def __len__(self) -> int:
            return 99

    print(f"{'class':<22}{'__bool__':<10}{'__len__':<10}{'bool(obj)'}")
    print("-" * 52)
    print(f"{'LenOnly':<22}{'-':<10}{'0':<10}{bool(LenOnly())}")
    print(f"{'BoolTrueLenZero':<22}{'True':<10}{'0':<10}{bool(BoolTrueLenZero())}")
    print(f"{'BoolFalseLenBig':<22}{'False':<10}{'99':<10}{bool(BoolFalseLenBig())}")
    print()
    check("only __len__->0 makes an object falsy", not bool(LenOnly()))
    check("__bool__(True) beats __len__(0)", bool(BoolTrueLenZero()))
    check("__bool__(False) beats __len__(99)", not bool(BoolFalseLenBig()))


# ----------------------------------------------------------------------------
# Section E — emulating a container
# ----------------------------------------------------------------------------

def section_e_container() -> None:
    banner("E — Emulating a container: Grid (sparse 2D) + __getitem__ fallback")
    print("Implement __getitem__/__setitem__/__delitem__/__contains__/__len__/")
    print("__iter__ and your object behaves like a built-in collection. `in`")
    print("tries __contains__ first; `for` tries __iter__ first, then falls back")
    print("to __getitem__ starting at index 0 until IndexError.\n")

    class Grid:
        def __init__(self) -> None:
            self._cells: dict[tuple[int, int], int] = {}

        def __getitem__(self, key: tuple[int, int]) -> int:
            return self._cells.get(key, 0)

        def __setitem__(self, key: tuple[int, int], value: int) -> None:
            self._cells[key] = value

        def __delitem__(self, key: tuple[int, int]) -> None:
            del self._cells[key]

        def __contains__(self, key: object) -> bool:
            return key in self._cells

        def __len__(self) -> int:
            return len(self._cells)

        def __iter__(self):
            return iter(self._cells)

    g = Grid()
    g[1, 1] = 10
    g[2, 2] = 20
    g[0, 0] = 5
    print(f"g[1,1] = {g[1, 1]}   g[3,3] = {g[3, 3]}   (unset -> 0)")
    print(f"len(g) = {len(g)}")
    print(f"(1,1) in g -> {(1, 1) in g}   (9,9) in g -> {(9, 9) in g}")
    print(f"list(g) = {sorted(g)}   (iteration via __iter__)")
    del g[0, 0]
    print(f"del g[0,0] -> len={len(g)}, (0,0) in g -> {(0, 0) in g}")
    print()

    class SeqByIndex:
        """No __iter__: for-loops fall back to __getitem__ from 0."""

        def __getitem__(self, i: int) -> int:
            if i >= 3:
                raise IndexError
            return i * 10

    s = SeqByIndex()
    print(f"SeqByIndex has __iter__? {hasattr(s, '__iter__')}  "
          f"__getitem__? {hasattr(s, '__getitem__')}")
    print(f"list(s) = {list(s)}   (for-loop: __getitem__(0,1,2) then IndexError)")
    print()
    check("Grid supports indexing, len, in, iter, del", len(g) == 2)
    check("__contains__ drives the `in` operator", (1, 1) in g)
    check("__getitem__ fallback drives iteration",
          list(SeqByIndex()) == [0, 10, 20])


# ----------------------------------------------------------------------------
# Section F — arithmetic: __add__, __radd__, __iadd__
# ----------------------------------------------------------------------------

def section_f_arithmetic() -> None:
    banner("F — Arithmetic: __add__, __radd__ (reflected), __iadd__ (in-place)")
    print("x + y calls type(x).__add__(x, y). If that returns NotImplemented")
    print("(left operand doesn't understand the right), Python tries the")
    print("REFLECTED method: type(y).__radd__(y, x). += tries __iadd__ first;")
    print("if absent, it falls back to __add__ and rebinds the name.\n")

    class Vector:
        def __init__(self, x: int, y: int) -> None:
            self.x, self.y = x, y

        def __repr__(self) -> str:
            return f"Vector({self.x}, {self.y})"

        def __eq__(self, other: object) -> bool:
            return (isinstance(other, Vector)
                    and (self.x, self.y) == (other.x, other.y))

        def __add__(self, other: object) -> "Vector":
            if isinstance(other, Vector):
                return Vector(self.x + other.x, self.y + other.y)
            return NotImplemented

        def __radd__(self, other: object) -> "Vector":
            if isinstance(other, int):
                return Vector(self.x + other, self.y + other)
            return NotImplemented

        def __iadd__(self, other: object) -> "Vector":
            if isinstance(other, Vector):
                self.x += other.x
                self.y += other.y
                return self
            return NotImplemented

    v1, v2 = Vector(1, 2), Vector(3, 4)
    print(f"Vector(1,2) + Vector(3,4) = {v1 + v2}")
    print(f"10 + Vector(1,2)          = {10 + Vector(1, 2)}   "
          f"(int.__add__ -> NotImplemented -> Vector.__radd__)")
    vid = id(v1)
    v1 += Vector(0, 1)
    print(f"v1 += Vector(0,1)         -> v1 = {v1}, same object? {id(v1) == vid} "
          f"(__iadd__ mutates in place)")
    print()
    check("Vector(1,2) + Vector(3,4) == Vector(4,6)",
          Vector(1, 2) + Vector(3, 4) == Vector(4, 6))
    check("10 + Vector(1,2) == Vector(11,12) via __radd__",
          10 + Vector(1, 2) == Vector(11, 12))
    check("__iadd__ mutates in place (same id)", id(v1) == vid)


# ----------------------------------------------------------------------------
# Section G — context-manager preview: __enter__ / __exit__
# ----------------------------------------------------------------------------

def section_g_context_manager() -> None:
    banner("G — Context-manager preview: __enter__ / __exit__")
    print("`with x:` calls type(x).__enter__(x) on entry (the return value is")
    print("bound to the as-variable), and type(x).__exit__(x, exc_type, exc_val,")
    print("exc_tb) on exit — even if the body raises. Return True from __exit__")
    print("to suppress the exception. Full treatment in CONTEXT_MANAGERS (P3).\n")

    class Tracer:
        def __init__(self) -> None:
            self.calls: list = []

        def __enter__(self) -> "Tracer":
            self.calls.append("enter")
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
            self.calls.append(("exit", exc_type))
            return False

    t = Tracer()
    with t:
        t.calls.append("body")
    print(f"with Tracer() as t: ... -> t.calls = {t.calls}")
    print()
    check("with calls __enter__ -> body -> __exit__(None)",
          t.calls == ["enter", "body", ("exit", None)])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("dunder_methods.py — Phase 2 bundle #10.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_the_model()
    section_b_repr_str()
    section_c_eq_hash_contract()
    section_d_bool_len_precedence()
    section_e_container()
    section_f_arithmetic()
    section_g_context_manager()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
