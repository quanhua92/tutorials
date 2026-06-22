"""
type_hints.py — Bundle #18 (Phase 3).

GOAL (one line): show, by printing every value, that Python's type hints are
documentation for static checkers AND a runtime __annotations__ dict — gradual
typing, generics, Protocols, and @overload give real static safety without
losing Python's flexibility.

This is the GROUND TRUTH for TYPE_HINTS.md. Every annotation, __annotations__
dump, and runtime behavior in the guide is printed by this file. Change it ->
re-run -> re-paste. Never hand-compute.

Run:
    uv run python type_hints.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import (
    Callable,
    Generic,
    Optional,
    Protocol,
    TypeVar,
    Union,
    get_type_hints,
    overload,
    runtime_checkable,
)

BANNER = "=" * 70

# Module-level variable annotation (PEP 526). With `from __future__ import
# annotations` in effect, this lands in __annotations__ as the STRING "int",
# not the int type. Section B inspects this.
module_count: int = 0


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
# Section A — basic annotations + __annotations__ + not-enforced-at-runtime
# ----------------------------------------------------------------------------

def section_a_basic_annotations() -> None:
    banner("A — Basic annotations: f.__annotations__ + NOT enforced at runtime")
    print("Annotations live in f.__annotations__ as a dict. This file has")
    print("'from __future__ import annotations' (PEP 563) in effect, so each")
    print("value is the SOURCE TEXT of the annotation. typing.get_type_hints()")
    print("resolves those strings back to real type objects. Either way, the")
    print("runtime does NOT enforce them when you call f.\n")

    def f(x: int, y: str) -> bool:
        return bool(x) and bool(y)

    hints = get_type_hints(f)
    print("def f(x: int, y: str) -> bool: return bool(x) and bool(y)")
    print(f"{'expression':<40}{'result'}")
    print("-" * 70)
    print(f"{'f.__annotations__':<40}{f.__annotations__}")
    print(f"{'get_type_hints(f)':<40}{hints}")
    print(f"{'f(2, \"hello\")':<40}{f(2, 'hello')}")
    bad_call: bool = f("a", 1)  # type: ignore[arg-type]  # not enforced
    print(f"{'f(\"a\", 1) (WRONG types)':<40}{bad_call}  <- ran anyway!")
    print()

    check("f.__annotations__ stores STRINGS (PEP 563 deferred eval)",
          f.__annotations__["x"] == "int")
    check("get_type_hints(f) resolves 'x' to the real type int",
          hints["x"] is int)
    check("get_type_hints(f) resolves 'return' to the real type bool",
          hints["return"] is bool)
    check("calling f with wrong types does NOT raise at runtime",
          bad_call is True)


# ----------------------------------------------------------------------------
# Section B — variable annotations (PEP 526)
# ----------------------------------------------------------------------------

@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    debug: bool = False


def section_b_variable_annotations() -> None:
    banner("B — Variable annotations (PEP 526): name: type = value")
    print("Annotations register types in __annotations__ at MODULE and CLASS")
    print("scope. At FUNCTION scope they are pure hints — the runtime stores")
    print("nothing. An annotation alone does NOT bind a name; only the")
    print("assignment does.\n")

    def helper() -> None:
        _local_x: int = 42  # function-local; goes NOWHERE at runtime

    mod_anns = globals().get("__annotations__", {})
    print(f"{'expression':<40}{'result'}")
    print("-" * 70)
    print(f"{'module __annotations__':<40}{mod_anns}")
    print(f"{'ServerConfig.__annotations__':<40}{ServerConfig.__annotations__}")
    print(f"{'helper.__annotations__':<40}{helper.__annotations__}")
    print(f"{'ServerConfig.host (class default)':<40}{ServerConfig.host!r}")
    print()

    check("module __annotations__ records module_count as the STRING 'int'",
          mod_anns.get("module_count") == "int")
    check("ServerConfig.__annotations__ has host/port/debug (PEP 563 strings)",
          ServerConfig.__annotations__
          == {"host": "str", "port": "int", "debug": "bool"})
    check("ServerConfig.host class default is the assigned value",
          ServerConfig.host == "127.0.0.1")
    check("function-LOCAL variable annotations are NOT stored (only 'return')",
          "_local_x" not in helper.__annotations__)


# ----------------------------------------------------------------------------
# Section C — container types: list[int], dict[str, float], tuple[int, ...]
# ----------------------------------------------------------------------------

def section_c_container_types() -> None:
    banner("C — Container types: list[int], dict[str, float], tuple[int, ...]")
    print("Subscripting builtins produces a types.GenericAlias — a HINT to")
    print("the checker. At runtime, list[int] does NOT constrain what you")
    print("put in the list. tuple[T, ...] means 'variable-length, all T';")
    print("tuple[int, str] means a fixed shape of exactly two elements.\n")

    nums: list[int] = [1, 2, 3]
    scores: dict[str, float] = {"alice": 9.5, "bob": 7.0}
    fixed: tuple[int, str] = (1, "x")

    print(f"{'expression':<32}{'value'}")
    print("-" * 70)
    print(f"{'type(nums)':<32}{type(nums)}")
    print(f"{'type(scores)':<32}{type(scores)}")
    print(f"{'type(fixed)':<32}{type(fixed)}")
    print(f"{'nums (list[int])':<32}{nums}")
    print(f"{'scores (dict[str, float])':<32}{scores}")
    print(f"{'fixed (tuple[int, str])':<32}{fixed}")
    print(f"{'list[int]':<32}{list[int]}")
    print(f"{'dict[str, float]':<32}{dict[str, float]}")
    print(f"{'tuple[int, ...]':<32}{tuple[int, ...]}")
    print(f"{'list[int].__origin__':<32}"
          f"{list[int].__origin__}")  # type: ignore[attr-defined]
    print(f"{'dict[str, float].__args__':<32}"
          f"{dict[str, float].__args__}")  # type: ignore[attr-defined]
    print(f"{'tuple[int, ...].__args__':<32}"
          f"{tuple[int, ...].__args__}")  # type: ignore[attr-defined]
    print()

    # Runtime does NOT enforce — appending a string to a list[int] works.
    nums.append("not an int")  # type: ignore[arg-type]  # not enforced
    print(f"After nums.append('not an int'): nums = {nums}")
    print()

    check("nums is a plain list (annotation is just a hint)",
          type(nums) is list)
    check("list[int] is a GenericAlias, not a real class",
          type(list[int]).__name__ == "GenericAlias")
    check("list[int].__origin__ is the built-in list",
          list[int].__origin__ is list)  # type: ignore[attr-defined]
    check("dict[str, float].__args__ == (str, float)",
          dict[str, float].__args__ == (str, float))  # type: ignore[attr-defined]
    check("tuple[int, ...].__args__ == (int, Ellipsis)",
          tuple[int, ...].__args__ == (int, Ellipsis))  # type: ignore[attr-defined]
    check("appending wrong type to list[int] runs fine (no TypeError)",
          nums[-1] == "not an int")


# ----------------------------------------------------------------------------
# Section D — TypeVar + Generic: a typed Stack[T]
# ----------------------------------------------------------------------------

T = TypeVar("T")


class Stack(Generic[T]):
    """A minimal generic stack. mypy checks push/pop against T; the runtime
    only ever sees a plain Stack (type params are erased)."""

    def __init__(self) -> None:
        self._items: list[T] = []

    def push(self, item: T) -> None:
        self._items.append(item)

    def pop(self) -> T:
        return self._items.pop()


def section_d_typevar_generic() -> None:
    banner("D — TypeVar + Generic: a typed Stack[T]")
    print("TypeVar('T') is a placeholder type. Inheriting Generic[T] makes a")
    print("class parameterizable: Stack[int] declares the element type, and")
    print("mypy can check push/pop. At runtime a Stack is just a Stack —")
    print("isinstance works against the plain class, but Stack[int] raises")
    print("TypeError because parameters are erased (PEP 484).\n")

    s: Stack[int] = Stack()
    s.push(1)
    s.push(2)
    s.push(3)

    print(f"{'expression':<40}{'result'}")
    print("-" * 70)
    print(f"{'s.push(1); s.push(2); s.push(3)':<40}{list(s._items)}")
    print(f"{'s.pop()':<40}{s.pop()}")
    print(f"{'type(s)':<40}{type(s)}")
    print(f"{'isinstance(s, Stack)':<40}{isinstance(s, Stack)}")
    try:
        isinstance(s, Stack[int])  # type: ignore[misc]  # expected to raise
    except TypeError as exc:
        print(f"{'isinstance(s, Stack[int])':<40}TypeError: {exc}")
    print(f"{'Stack[int]':<40}{Stack[int]}")
    print(f"{'Stack[int].__origin__':<40}"
          f"{Stack[int].__origin__}")  # type: ignore[attr-defined]
    print(f"{'Stack.__parameters__':<40}"
          f"{Stack.__parameters__}")  # type: ignore[attr-defined]
    print()

    check("s.pop() returns the last-pushed int", s.pop() == 2)
    check("isinstance(s, Stack) works at runtime", isinstance(s, Stack))
    check("Stack[int].__origin__ is the unparameterized Stack",
          Stack[int].__origin__ is Stack)  # type: ignore[attr-defined]
    check("Stack.__parameters__ == (T,) (unsubscripted)",
          Stack.__parameters__ == (T,))  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------
# Section E — Optional / Union / Callable: composable hints
# ----------------------------------------------------------------------------

def section_e_optional_union_callable() -> None:
    banner("E — Optional / Union / Callable: composable type hints")
    print("Optional[X] is just Union[X, None]. Python 3.10 added X | Y (PEP")
    print("604). Callable[[ArgTypes], Ret] types higher-order functions. At")
    print("runtime these build hints, NOT validators.\n")

    def first_or_none(items: list[int]) -> int | None:
        return items[0] if items else None

    def format_id(uid: Union[int, str]) -> str:
        return f"id={uid}"

    def apply(cb: Callable[[int, int], int], a: int, b: int) -> int:
        return cb(a, b)

    print(f"{'expression':<38}{'result'}")
    print("-" * 70)
    print(f"{'first_or_none([])':<38}{first_or_none([])}")
    print(f"{'first_or_none([42])':<38}{first_or_none([42])}")
    print(f"{'format_id(7)':<38}{format_id(7)!r}")
    print(f"{'format_id(\"abc\")':<38}{format_id('abc')!r}")
    print(f"{'apply(lambda a,b: a+b, 3, 4)':<38}{apply(lambda a, b: a + b, 3, 4)}")
    print(f"{'int | None':<38}{int | None}")
    print(f"{'Optional[int]':<38}{Optional[int]}")
    print(f"{'Union[int, str]':<38}{Union[int, str]}")
    print(f"{'Callable[[int, int], int]':<38}{Callable[[int, int], int]}")
    print(f"{'(int | None) == Optional[int]':<38}"
          f"{(int | None) == Optional[int]}")
    print(f"{'Union[int, str] == (int | str)':<38}"
          f"{Union[int, str] == (int | str)}")
    print(f"{'type(int | None).__name__':<38}{type(int | None).__name__}")
    print(f"{'type(Optional[int]).__name__':<38}"
          f"{type(Optional[int]).__name__}")
    print()

    check("first_or_none([]) returns None", first_or_none([]) is None)
    check("first_or_none([42]) returns 42", first_or_none([42]) == 42)
    check("format_id accepts int and str equally (Union hint)",
          format_id(7) == "id=7" and format_id("abc") == "id=abc")
    check("apply passes the callable through (Callable hint)",
          apply(lambda a, b: a + b, 3, 4) == 7)
    check("int | None equals Optional[int] (PEP 604 unifies them)",
          (int | None) == Optional[int])
    check("Union[int, str] equals int | str (order-independent)",
          Union[int, str] == (int | str))
    check("X | Y syntax produces types.UnionType (PEP 604)",
          type(int | None).__name__ == "UnionType")


# ----------------------------------------------------------------------------
# Section F — Protocol: structural typing + @runtime_checkable (PEP 544)
# ----------------------------------------------------------------------------

@runtime_checkable
class SupportsClose(Protocol):
    """Anything with a no-arg close() method. Structural — no inheritance
    required. The @runtime_checkable decorator opts in to isinstance()."""

    def close(self) -> None: ...


class FileLike:
    """Has close() — therefore structurally a SupportsClose, even though it
    does NOT inherit from the Protocol."""

    def close(self) -> None:
        return None


class IntegerOnly:
    """No close() — therefore NOT a SupportsClose."""


def section_f_protocol() -> None:
    banner("F — Protocol: structural typing + @runtime_checkable (PEP 544)")
    print("A Protocol describes a SHAPE — any object with the right methods")
    print("is a structural subtype, NO inheritance required. With")
    print("@runtime_checkable, isinstance() checks the shape at runtime via")
    print("hasattr(). This is static duck typing.\n")

    print(f"{'expression':<42}{'result'}")
    print("-" * 70)
    print(f"{'isinstance(FileLike(), SupportsClose)':<42}"
          f"{isinstance(FileLike(), SupportsClose)}")
    print(f"{'isinstance(IntegerOnly(), SupportsClose)':<42}"
          f"{not isinstance(IntegerOnly(), SupportsClose)}")
    print(f"{'issubclass(FileLike, SupportsClose)':<42}"
          f"{issubclass(FileLike, SupportsClose)}")
    print(f"{'issubclass(int, SupportsClose)':<42}"
          f"{issubclass(int, SupportsClose)}")
    print(f"{'FileLike.__mro__':<42}{FileLike.__mro__}")
    print(f"{'SupportsClose.__mro__':<42}{SupportsClose.__mro__}")
    print()

    check("FileLike structurally satisfies SupportsClose (has close())",
          isinstance(FileLike(), SupportsClose))
    check("IntegerOnly does NOT satisfy SupportsClose (no close())",
          not isinstance(IntegerOnly(), SupportsClose))
    check("issubclass works for runtime_checkable protocols",
          issubclass(FileLike, SupportsClose))
    check("FileLike does NOT inherit SupportsClose (structural, not nominal)",
          SupportsClose not in FileLike.__mro__)


# ----------------------------------------------------------------------------
# Section G — @overload: many signatures for the checker, ONE real impl
# ----------------------------------------------------------------------------

@overload
def parse(value: int) -> str: ...
@overload
def parse(value: str) -> int: ...


def parse(value: int | str) -> str | int:
    """Real runtime impl. The @overload stubs above are for mypy; CPython
    discards them and keeps only this definition."""
    if isinstance(value, int):
        return str(value)
    return len(value)


def section_g_overload() -> None:
    banner("G — @overload: many signatures for the checker, ONE real impl")
    print("The @overload-decorated stubs declare every input->output mapping")
    print("for STATIC checkers. The LAST (non-decorated) def is the runtime")
    print("implementation. CPython discards the stubs; only the real impl")
    print("is callable. mypy/pyright use the stubs to narrow return types.\n")

    print(f"{'expression':<38}{'result'}")
    print("-" * 70)
    print(f"{'parse(42)':<38}{parse(42)!r}")
    print(f"{'parse(\"hello\")':<38}{parse('hello')}")
    print(f"{'type(parse(42)).__name__':<38}{type(parse(42)).__name__}")
    print(f"{'type(parse(\"hi\")).__name__':<38}{type(parse('hi')).__name__}")
    print(f"{'parse.__annotations__':<38}{parse.__annotations__}")
    print()

    check("parse(42) returns '42' (a str)",
          parse(42) == "42" and isinstance(parse(42), str))
    check("parse('hello') returns 5 (an int)",
          parse("hello") == 5 and isinstance(parse("hello"), int))
    check("parse.__annotations__ is the REAL impl's (stubs discarded)",
          parse.__annotations__
          == {"value": "int | str", "return": "str | int"})


# ----------------------------------------------------------------------------
# Section H — Runtime vs static: the gradual-typing contract
# ----------------------------------------------------------------------------

def add(a: int, b: int) -> int:
    return a + b


def section_h_runtime_vs_static() -> None:
    banner("H — Runtime vs static: the gradual-typing contract")
    print("Python is GRADUALLY typed: annotations are pure hints. CPython")
    print("stores them in __annotations__ and otherwise IGNORES them; mypy")
    print("and pyright are the ENFORCERS, run separately in CI. This lets you")
    print("add types incrementally without breaking existing code.\n")

    right: int = add(2, 3)
    wrong = add("x", "y")  # type: ignore[arg-type]  # gradual typing

    print(f"{'expression':<42}{'result'}")
    print("-" * 70)
    print(f"{'add(2, 3)':<42}{right}")
    print(f"{'add(\"x\", \"y\") (mypy rejects, runtime OK)':<42}{wrong!r}")
    print(f"{'add.__annotations__':<42}{add.__annotations__}")
    print()

    print("Two KINDS of static typing, coexisting:")
    print("  NOMINAL    : class B(A)    — B IS-A A because it SAYS so (MRO)")
    print("  STRUCTURAL : class C: ...  — C is-a SupportsClose because it HAS")
    print("                               close(), no inheritance needed")
    print()
    print("Runtime type dispatch (e.g. functools.singledispatch) is a third")
    print("axis — see FUNCTIONAL_TOOLKIT (P2 #15).")
    print()

    check("add(2, 3) == 5", right == 5)
    check("runtime accepts add('x', 'y') -> 'xy' (no TypeError)",
          wrong == "xy")
    check("annotations are stored in __annotations__ (CPython keeps them)",
          "a" in add.__annotations__ and "b" in add.__annotations__)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("type_hints.py — Phase 3 bundle #18.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {sys.version.split()[0]} on this machine.")
    section_a_basic_annotations()
    section_b_variable_annotations()
    section_c_container_types()
    section_d_typevar_generic()
    section_e_optional_union_callable()
    section_f_protocol()
    section_g_overload()
    section_h_runtime_vs_static()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
