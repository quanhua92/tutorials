"""
classes_basics.py — Bundle #9 (Phase 2).

GOAL (one line): show, by printing every value, that a class is itself an
object (an instance of `type`), that each instance owns a private `__dict__`,
that class-vs-instance attributes resolve through a fixed lookup chain, that
methods bind `self` via the descriptor protocol, and that a mutable class
attribute is SHARED state (the classic bug) — then how `@dataclass` removes
the boilerplate safely.

This is the GROUND TRUTH for CLASSES_BASICS.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python classes_basics.py
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

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
# The reference class used across sections B, C, D.
# ----------------------------------------------------------------------------

class Point:
    """A 2-D point. `species`/`dimensions` are CLASS attrs (shared);
    `x`/`y` are INSTANCE attrs (per-object, set in __init__)."""

    species = "point"      # class attribute — shared by every instance
    dimensions = 2         # class attribute — shared, read-only intent

    def __init__(self, x: int, y: int) -> None:
        self.x = x         # instance attribute — written into self.__dict__
        self.y = y         # instance attribute

    def move(self, dx: int, dy: int) -> None:
        self.x += dx
        self.y += dy

    def __repr__(self) -> str:
        return f"Point(x={self.x}, y={self.y})"


# Defined at MODULE level (not nested) so the dataclass-generated __repr__
# uses the clean __qualname__ "Pt" / "FPt" / "WithTags" rather than the
# enclosing-function qualname. This keeps the output byte-stable.

@dataclass
class Pt:
    x: int
    y: int


@dataclass(frozen=True)
class FPt:
    x: int
    y: int


@dataclass
class WithTags:
    name: str
    tags: list[int] = field(default_factory=list)


# ----------------------------------------------------------------------------
# Section A — class creation: `type(Point)` is `type`; Point is an object
# ----------------------------------------------------------------------------

def section_a_class_creation() -> None:
    banner("A — Class creation: a class is an object, an instance of `type`")
    print("A `class` statement, when it executes, builds a CLASS OBJECT. That")
    print("object is itself an instance of `type` (the metaclass). So Point is")
    print("a value like any other: it has a type, an id, attributes, and a")
    print("__dict__. The class __dict__ is a read-only mappingproxy that holds")
    print("the methods and class-level attributes.\n")

    print(f"{'expression':<42}{'result'}")
    print("-" * 66)
    rows = [
        ("Point", Point),
        ("type(Point)", type(Point)),
        ("type(Point) is type", type(Point) is type),
        ("isinstance(Point, type)", isinstance(Point, type)),
        ("Point.__name__", Point.__name__),
        ("Point.__mro__", Point.__mro__),
        ("type(Point.__dict__).__name__", type(Point.__dict__).__name__),
        ("'move' in Point.__dict__", "move" in Point.__dict__),
        ("'species' in Point.__dict__", "species" in Point.__dict__),
    ]
    for label, value in rows:
        print(f"{label:<42}{value!r}")
    print()

    check("type(Point) is type (the class-of-the-class)", type(Point) is type)
    check("Point is an instance of type", isinstance(Point, type))
    check("Point.__name__ == 'Point'", Point.__name__ == "Point")
    check("methods live in the CLASS __dict__ ('move' in Point.__dict__)",
          "move" in Point.__dict__)
    check("the class __dict__ is a read-only mappingproxy",
          type(Point.__dict__).__name__ == "mappingproxy")


# ----------------------------------------------------------------------------
# Section B — __init__ sets instance state; each instance owns its __dict__
# ----------------------------------------------------------------------------

def section_b_init_and_instance_dict() -> None:
    banner("B — __init__ writes the INSTANCE __dict__; instances are independent")
    print("Calling Point(1, 2) runs two steps: (1) Point.__new__ creates a fresh")
    print("empty instance, (2) Point.__init__(that_instance, 1, 2) runs and writes")
    print("self.x / self.y into the instance's OWN __dict__. Each instance gets a")
    print("distinct, writable dict, so mutating one never touches another.\n")

    p1 = Point(1, 2)
    p2 = Point(3, 4)

    print(f"{'p1 = Point(1, 2);  p2 = Point(3, 4)':<42}")
    print(f"{'p1.x':<22}{p1.x!r:<8}{'p2.x':<10}{p2.x!r}")
    print(f"{'p1.__dict__':<32}{p1.__dict__!r}")
    print(f"{'p2.__dict__':<32}{p2.__dict__!r}")
    print(f"{'type(p1.__dict__).__name__':<32}"
          f"{type(p1.__dict__).__name__!r}")
    print(f"{'p1.__dict__ is not p2.__dict__':<32}"
          f"{p1.__dict__ is not p2.__dict__}")
    print()

    check("p1.__dict__ == {'x': 1, 'y': 2}",
          p1.__dict__ == {"x": 1, "y": 2})
    check("p2.__dict__ == {'x': 3, 'y': 4}",
          p2.__dict__ == {"x": 3, "y": 4})
    check("each instance owns a distinct dict object",
          p1.__dict__ is not p2.__dict__)

    # Mutate p1 only -> p2 is untouched.
    p1.x = 10
    print("p1.x = 10   # writes p1's INSTANCE dict; p2 is unaffected\n")
    print(f"{'p1.x':<22}{p1.x!r}")
    print(f"{'p2.x':<22}{p2.x!r}")
    print(f"{'x in p1.__dict__':<22}{'x' in p1.__dict__!r}")
    print()
    check("mutating p1.x leaves p2.x unchanged", p1.x == 10 and p2.x == 3)


# ----------------------------------------------------------------------------
# Section C — class attr vs instance attr; lookup order & shadowing
# ----------------------------------------------------------------------------

def section_c_class_vs_instance_attr() -> None:
    banner("C — Class attr vs instance attr: lookup order & shadowing")
    print("Attribute lookup walks a fixed chain: INSTANCE __dict__ first, then")
    print("the CLASS __dict__, then base classes. A class attr (e.g. `species`)")
    print("is NOT copied into each instance — it lives once on the class and is")
    print("found on the second step. Assigning p.species = ... creates an INSTANCE")
    print("attr that SHADOWS the class attr for that one instance only.\n")

    p1 = Point(1, 2)
    p2 = Point(3, 4)

    print(f"{'Point.species':<30}{Point.species!r}")
    print(f"{'p1.species (read from class)':<30}{p1.species!r}")
    print(f"{'p2.species (read from class)':<30}{p2.species!r}")
    print(f"{'species in p1.__dict__':<30}{'species' in p1.__dict__!r}")
    print(f"{'species in Point.__dict__':<30}{'species' in Point.__dict__!r}")
    print()

    check("species is NOT stored on the instance", "species" not in p1.__dict__)
    check("species IS stored on the class", "species" in Point.__dict__)
    check("both instances see the same class value",
          p1.species == p2.species == Point.species)

    # Now SHADOW: assignment creates an instance attribute.
    p1.species = "rogue"
    print('p1.species = "rogue"   # creates an INSTANCE attr, shadows the class\n')
    print(f"{'p1.species (now the instance attr)':<42}{p1.species!r}")
    print(f"{'Point.species (class attr untouched)':<42}{Point.species!r}")
    print(f"{'p2.species (other instance untouched)':<42}{p2.species!r}")
    print(f"{'species in p1.__dict__':<42}{'species' in p1.__dict__!r}")
    print()
    check("assignment created an instance attr (shadow)",
          "species" in p1.__dict__)
    check("the class attr itself is unchanged", Point.species == "point")
    check("other instances are unaffected", p2.species == "point")
    check("instance lookup wins over class lookup (shadow)",
          p1.species == "rogue")


# ----------------------------------------------------------------------------
# Section D — methods & self: bound vs unbound (the descriptor protocol)
# ----------------------------------------------------------------------------

def section_d_methods_and_self() -> None:
    banner("D — Methods & self: bound vs unbound (descriptor binding)")
    print("A `def` inside a class is a plain FUNCTION object stored in the class")
    print("__dict__. Reading Point.move returns that raw function; reading p.move")
    print("INVOKES the function's __get__ (it is a descriptor), which packs the")
    print("instance into a bound method object. Calling p.move(2, 3) is exactly")
    print("Point.move(p, 2, 3): the instance is passed as the first arg (self).\n")

    p = Point(0, 0)
    print(f"{'type(Point.move).__name__':<30}{type(Point.move).__name__!r}")
    print(f"{'type(p.move).__name__':<30}{type(p.move).__name__!r}")
    print(f"{'p.move.__self__ is p':<30}{p.move.__self__ is p}")
    print(f"{'p.move.__func__ is Point.move':<30}"
          f"{p.move.__func__ is Point.move}")
    print()

    check("Point.move is a plain function object",
          type(Point.move).__name__ == "function")
    check("p.move is a bound method object",
          type(p.move).__name__ == "method")
    check("the bound method remembers its instance", p.move.__self__ is p)
    check("the bound method wraps the original function",
          p.move.__func__ is Point.move)

    # The two call forms are equivalent: same mutation of `p`.
    p.move(2, 3)
    after_bound = (p.x, p.y)
    Point.move(p, 2, 3)         # identical: passes p explicitly as self
    after_unbound = (p.x, p.y)
    print(f"p = Point(0, 0);  p.move(2, 3)        -> {p!r}  (after={after_bound})")
    print(f"Point.move(p, 2, 3)  (same thing)     -> {p!r}  (after={after_unbound})")
    print()
    check("p.move(2,3) moved p by (2,3)", after_bound == (2, 3))
    check("Point.move(p,2,3) is the equivalent call (moves p again)",
          after_unbound == (4, 6))


# ----------------------------------------------------------------------------
# Section E — the mutable-class-attribute shared-list trap
# ----------------------------------------------------------------------------

def section_e_mutable_class_attr_trap() -> None:
    banner("E — The mutable-class-attribute trap: a shared list")
    print("A mutable CLASS attribute (list/dict/set) is created ONCE, on the")
    print("class. self.tags.append(...) does NOT create an instance attr — it")
    print("looks up `tags` (found on the class) and mutates THAT shared object.")
    print("Result: every instance shares one list. The fix is to build a fresh")
    print("list per instance inside __init__.\n")

    class Buggy:
        tags: list[str] = []          # the trap: one list shared by ALL instances

        def add(self, tag: str) -> None:
            self.tags.append(tag)     # mutates the CLASS-level list

    b1 = Buggy()
    b2 = Buggy()
    b1.add("x")
    b2.add("y")

    print("class Buggy:  tags = []   # class-level, shared\n"
          "b1 = Buggy(); b2 = Buggy();  b1.add('x');  b2.add('y')\n")
    print(f"{'b1.tags':<22}{b1.tags!r}")
    print(f"{'b2.tags':<22}{b2.tags!r}")
    print(f"{'b1.tags is b2.tags':<22}{b1.tags is b2.tags}")
    print(f"{'b1.tags is Buggy.tags':<22}{b1.tags is Buggy.tags}")
    print()
    check("the class-level list is shared across instances",
          b1.tags is b2.tags is Buggy.tags)
    check("b2 leaked b1's append (cross-contamination)",
          b1.tags == ["x", "y"] and b2.tags == ["x", "y"])

    # The fix: each instance builds its own list in __init__.

    class Fixed:
        def __init__(self) -> None:
            self.tags: list[str] = []   # instance attr: a fresh list per object

        def add(self, tag: str) -> None:
            self.tags.append(tag)

    f1 = Fixed()
    f2 = Fixed()
    f1.add("x")
    f2.add("y")

    print("class Fixed:  def __init__(self): self.tags = []  # per-instance\n"
          "f1 = Fixed(); f2 = Fixed();  f1.add('x');  f2.add('y')\n")
    print(f"{'f1.tags':<26}{f1.tags!r}")
    print(f"{'f2.tags':<26}{f2.tags!r}")
    print(f"{'f1.tags is not f2.tags':<26}{f1.tags is not f2.tags}")
    print()
    check("instance-level lists are independent", f1.tags is not f2.tags)
    check("no leakage: f1.tags == ['x'] and f2.tags == ['y']",
          f1.tags == ["x"] and f2.tags == ["y"])


# ----------------------------------------------------------------------------
# Section F — @dataclass: auto __init__/__repr__/__eq__, frozen, default_factory
# ----------------------------------------------------------------------------

def section_f_dataclasses() -> None:
    banner("F — @dataclass: auto __init__/__repr__/__eq__, frozen, default_factory")
    print("@dataclass reads the annotated class attributes and GENERATES the")
    print("dunder methods for you: __init__ (from the fields in order), __repr__")
    print("(Name(f1=..., f2=...)), and __eq__ (field-by-field tuple comparison).")
    print("frozen=True makes instances immutable; field(default_factory=list) is")
    print("the dataclass fix for the shared-mutable-default trap.\n")

    print("@dataclass\n"
          "class Pt:\n"
          "    x: int\n"
          "    y: int\n")
    print(f"{'Pt(1, 2)':<24}{Pt(1, 2)!r}")
    print(f"{'repr(Pt(1, 2))':<24}{repr(Pt(1, 2))!r}")
    print(f"{'Pt(1, 2) == Pt(1, 2)':<24}{Pt(1, 2) == Pt(1, 2)}")
    print(f"{'Pt(1, 2) is Pt(1, 2)':<24}{Pt(1, 2) is Pt(1, 2)}")
    print()
    check("dataclass auto-generates __repr__",
          repr(Pt(1, 2)) == "Pt(x=1, y=2)")
    check("dataclass auto-generates __eq__ (value equality)",
          Pt(1, 2) == Pt(1, 2))
    check("equal values are still distinct objects (is is False)",
          Pt(1, 2) is not Pt(1, 2))

    # frozen=True: immutable + hashable; setattr is blocked.
    fp = FPt(1, 2)
    try:
        fp.x = 99
        frozen_raised = False
        frozen_exc_name = "(no exception)"
        is_attr_error = False
    except dataclasses.FrozenInstanceError as exc:
        frozen_raised = True
        frozen_exc_name = type(exc).__name__
        is_attr_error = isinstance(exc, AttributeError)

    print("\n@dataclass(frozen=True)\n"
          "class FPt:\n"
          "    x: int\n"
          "    y: int\n")
    print(f"{'FPt(1, 2) == FPt(1, 2)':<36}{FPt(1, 2) == FPt(1, 2)}")
    print(f"{'hash(FPt(1, 2)) == hash(FPt(1, 2))':<36}"
          f"{hash(FPt(1, 2)) == hash(FPt(1, 2))}")
    print(f"{'fp.x = 99  -> raises':<36}{frozen_exc_name!r}")
    print(f"{'isinstance(exc, AttributeError)':<36}{is_attr_error}")
    print()
    check("frozen=True blocks setattr (FrozenInstanceError)", frozen_raised)
    check("frozen instances are hashable (hash does not raise)",
          hash(fp) == hash(FPt(1, 2)))

    # field(default_factory=...) — the dataclass fix for mutable defaults.
    w1 = WithTags("a")
    w2 = WithTags("b")
    w1.tags.append(1)
    w2.tags.append(2)

    print("\n@dataclass\n"
          "class WithTags:\n"
          "    name: str\n"
          "    tags: list = field(default_factory=list)\n"
          "w1 = WithTags('a'); w2 = WithTags('b')\n"
          "w1.tags.append(1); w2.tags.append(2)\n")
    print(f"{'w1.tags':<26}{w1.tags!r}")
    print(f"{'w2.tags':<26}{w2.tags!r}")
    print(f"{'w1.tags is not w2.tags':<26}{w1.tags is not w2.tags}")
    print()
    check("default_factory builds an independent list per instance",
          w1.tags is not w2.tags)
    check("no shared-default leakage: w1.tags == [1] and w2.tags == [2]",
          w1.tags == [1] and w2.tags == [2])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("classes_basics.py — Phase 2 bundle #9.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_class_creation()
    section_b_init_and_instance_dict()
    section_c_class_vs_instance_attr()
    section_d_methods_and_self()
    section_e_mutable_class_attr_trap()
    section_f_dataclasses()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
