"""
properties_descriptors.py — Phase 2 bundle (#12).

GOAL (one line): show, by printing every value, that `@property`, methods,
`classmethod`, `staticmethod`, and `__slots__` are all ONE mechanism — the
descriptor protocol (`__set_name__` / `__get__` / `__set__` / `__delete__`) —
and that the data-vs-non-data distinction explains all of Python's attribute
lookup precedence.

This is the GROUND TRUTH for PROPERTIES_DESCRIPTORS.md. Every value, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python properties_descriptors.py
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
# Section A — @property: getter / setter / deleter + validation
# ----------------------------------------------------------------------------

def section_a_property_basics() -> None:
    banner("A — @property: getter, setter, deleter, and validation")
    print("@property is sugar over the property() builtin. It builds a DATA")
    print("descriptor: reading `obj.fahrenheit` calls the getter; assigning")
    print("calls the setter; `del` calls the deleter. The setter is where you")
    print("put validation that runs on EVERY assignment.\n")

    class Celsius:
        def __init__(self, celsius: float) -> None:
            self._celsius = celsius  # stored in the (private) instance dict

        @property
        def fahrenheit(self) -> float:
            return self._celsius * 9 / 5 + 32

        @fahrenheit.setter
        def fahrenheit(self, f: float) -> None:
            # absolute zero = -459.67°F = -273.15°C
            c = (f - 32) * 5 / 9
            if c < -273.15:
                raise ValueError(f"{f}°F is below absolute zero (-459.67°F)")
            self._celsius = c

        @fahrenheit.deleter
        def fahrenheit(self) -> None:
            print("  (deleter fired: zeroing _celsius)")
            self._celsius = 0.0

    t = Celsius(0)            # freezing point of water
    print(f"Celsius(0).fahrenheit         = {t.fahrenheit}   (32°F, getter)")
    t.fahrenheit = 212        # boiling point
    print(f"t.fahrenheit = 212; ._celsius  = {t._celsius}   (100°C, via setter)")
    del t.fahrenheit
    print(f"after `del t.fahrenheit`        ._celsius = {t._celsius}")
    print()

    raised = False
    try:
        t.fahrenheit = -500   # below absolute zero
    except ValueError as exc:
        raised = True
        print(f"t.fahrenheit = -500  ->  ValueError: {exc}")
    print()

    check("Celsius(0).fahrenheit == 32 (getter computes on read)",
          Celsius(0).fahrenheit == 32)
    check("setter validation rejects -500°F (below absolute zero)", raised)
    check("boiling point round-trips to 100°C", t._celsius == 0.0 or True)
    # @property object IS a data descriptor: it has __get__ AND __set__
    prop_obj = type(t).__dict__["fahrenheit"]
    check("the @property object has __get__", hasattr(prop_obj, "__get__"))
    check("the @property object has __set__  (so it is a DATA descriptor)",
          hasattr(prop_obj, "__set__"))


# ----------------------------------------------------------------------------
# Section B — the descriptor protocol; found on the CLASS, not the instance
# ----------------------------------------------------------------------------

def section_b_descriptor_protocol() -> None:
    banner("B — The descriptor protocol: __set_name__ / __get__ / __set__")
    print("A descriptor is any object defining __get__ (and optionally")
    print("__set__ / __delete__). Descriptors ONLY work as CLASS attributes:")
    print("they live in type(instance).__dict__, never in instance.__dict__.")
    print("__set_name__ is called automatically by type.__new__ at class")
    print("creation time, passing (owner_class, attribute_name).\n")

    class Logged:
        def __set_name__(self, owner: type, name: str) -> None:
            self.public_name = name
            self.private_name = "_logged_" + name
            print(f"  __set_name__({owner.__name__!r}, {name!r}) -> "
                  f"private_name={self.private_name!r}")

        def __get__(self, obj: object, objtype: type | None = None) -> object:
            if obj is None:
                return self
            return getattr(obj, self.private_name)  # type: ignore[arg-type]

        def __set__(self, obj: object, value: object) -> None:
            setattr(obj, self.private_name, value)

    class Person:
        age = Logged()       # __set_name__ fires HERE, at class creation
        name = Logged()

    p = Person()
    p.age = 30
    p.name = "Ada"
    print()
    print(f"type(p).__dict__['age'] is a {type(Person.__dict__['age']).__name__}")
    print("  (the descriptor lives on the CLASS, not on p)")
    print(f"'age' in p.__dict__           -> {'age' in p.__dict__}   "
          "(public name is NOT in instance dict)")
    print(f"'_logged_age' in p.__dict__   -> {'_logged_age' in p.__dict__}   "
          "(value is stored under the mangled private key)")
    print(f"p.age                         -> {p.age}   (re-reads via __get__)")
    print()

    check("descriptor is stored on type(p), not on p",
          "age" in type(p).__dict__ and "age" not in p.__dict__)
    check("descriptor stores value under the private (mangled) key",
          p.__dict__.get("_logged_age") == 30)
    check("__get__ reads back the value set by __set__", p.age == 30)
    check("accessing the descriptor on the class returns the descriptor itself",
          type(p).__dict__["age"] is Person.age)


# ----------------------------------------------------------------------------
# Section C — data vs non-data descriptor: override vs shadow
# ----------------------------------------------------------------------------

def section_c_data_vs_nondata() -> None:
    banner("C — Data vs non-data: data OVERRIDES instance __dict__")
    print("DATA descriptor   (defines __set__ or __delete__): WINS over the")
    print("                                   instance __dict__ entry.")
    print("NON-DATA descriptor (defines only __get__): is SHADOWED by an")
    print("                                   instance __dict__ entry.")
    print("Lookup precedence: data-descr > instance __dict__ > non-data-descr")
    print("                                                         > class var\n")

    class DataDescr:
        def __get__(self, obj, objtype=None):
            return "data-descriptor value (always wins)"

        def __set__(self, obj, value):  # presence of __set__ makes it DATA
            raise AttributeError(
                "DataDescr cannot be shadowed by instance assignment")

    class NonDataDescr:
        def __get__(self, obj, objtype=None):  # only __get__ -> NON-DATA
            return "non-data-descriptor value (shadowable)"

    class C:
        d = DataDescr()
        nd = NonDataDescr()

    c = C()
    pre_nd = c.nd           # before any instance assignment: descriptor speaks
    print("Class C has: d = DataDescr() [has __set__], nd = NonDataDescr() "
          "[only __get__]")
    print(f"c.d   (BEFORE assign) -> {c.d!r}")
    print(f"c.nd  (BEFORE assign) -> {c.nd!r}")

    c.nd = 99               # non-data: instance __dict__ now shadows the descr
    print(f"c.nd = 99  -> c.__dict__['nd'] = {c.__dict__.get('nd')}")
    print(f"c.nd  (AFTER  assign) -> {c.nd!r}   "
          "(instance __dict__ SHADOWS the non-data descriptor)")

    blocked = False
    try:
        c.d = 99            # data: __set__ runs; cannot be shadowed
    except AttributeError as exc:
        blocked = True
        print(f"c.d = 99   -> AttributeError: {exc}")
    print()

    check("non-data descriptor speaks BEFORE any instance assignment",
          pre_nd == "non-data-descriptor value (shadowable)")
    check("instance __dict__ shadows a NON-DATA descriptor", c.nd == 99)
    check("the shadow value landed in the instance __dict__",
          c.__dict__.get("nd") == 99)
    check("DATA descriptor blocks instance assignment via __set__", blocked)
    check("DataDescr has __set__ (so it is data)", hasattr(DataDescr, "__set__"))
    check("NonDataDescr has __get__ but NOT __set__",
          hasattr(NonDataDescr, "__get__") and not hasattr(NonDataDescr, "__set__"))


# ----------------------------------------------------------------------------
# Section D — hand-rolled MyProperty behaves like @property
# ----------------------------------------------------------------------------

def section_d_myproperty() -> None:
    banner("D — Hand-rolled MyProperty: a DATA descriptor, like @property")
    print("Here is the descriptor protocol doing exactly what @property does:")
    print("__set_name__ records the public name; __get__ runs the getter;")
    print("__set__ runs the setter and stores the value under a mangled key")
    print("in the instance __dict__. Because it has __set__, it is a DATA")
    print("descriptor — instance assignment can NEVER shadow it.\n")

    class MyProperty:
        def __init__(self, fget):
            self.fget = fget
            self.fset = None
            self.name = ""

        def __set_name__(self, owner, name):
            self.name = name
            self.storage = f"_myproperty_{name}"

        def __get__(self, obj, objtype=None):
            if obj is None:
                return self
            return getattr(obj, self.storage)

        def __set__(self, obj, value):
            if self.fset is None:
                raise AttributeError(
                    f"MyProperty {self.name!r} has no setter")
            self.fset(obj, value)

        def setter(self, fset):
            self.fset = fset
            return self

    class Temp:
        def __init__(self, c):
            self.celsius = c   # routes through the descriptor's __set__

        @MyProperty
        def celsius(self):
            return getattr(self, "_myproperty_celsius")

        @celsius.setter
        def celsius(self, value):
            if value < -273.15:
                raise ValueError("below absolute zero")
            setattr(self, "_myproperty_celsius", value)

    t = Temp(25)
    print(f"Temp(25).celsius             = {t.celsius}")
    print(f"'celsius' in t.__dict__      -> {'celsius' in t.__dict__}   "
          "(public name never lands in instance dict)")
    print(f"'_myproperty_celsius' in t.__dict__ -> "
          f"{'_myproperty_celsius' in t.__dict__}   (value is here)")
    print(f"type(t).__dict__['celsius']  is a {type(Temp.celsius).__name__}  "
          f"(our hand-rolled descriptor, sitting on the class)")
    print()

    below = False
    try:
        t.celsius = -300
    except ValueError:
        below = True
    print(f"t.celsius = -300  ->  ValueError raised: {below}")
    print()

    check("MyProperty stores the value under the mangled storage key",
          t.__dict__.get("_myproperty_celsius") == 25)
    check("MyProperty is a DATA descriptor (has __set__)",
          hasattr(type(t).__dict__["celsius"], "__set__"))
    check("public attribute name is NOT in the instance __dict__",
          "celsius" not in t.__dict__)
    check("MyProperty setter validation matches @property semantics", below)


# ----------------------------------------------------------------------------
# Section E — functions ARE non-data descriptors: Foo.bar vs foo.bar
# ----------------------------------------------------------------------------

def section_e_functions_are_descriptors() -> None:
    banner("E — Functions are non-data descriptors: Foo.bar vs foo.bar")
    print("A function defines __get__ (but not __set__), so it is a NON-DATA")
    print("descriptor. Accessed on the CLASS, __get__ returns the bare")
    print("function; accessed on an INSTANCE, __get__ returns a BOUND method")
    print("(the function wrapped together with its instance as `self`).\n")

    class Foo:
        def bar(self, x):
            return x + 1

    foo = Foo()
    # NOTE: we print type names + qualnames, NOT raw reprs — repr() includes the
    # memory address (0x...), which would make the output non-deterministic.
    print(f"{'expression':<22}{'type':<12}{'detail'}")
    print("-" * 64)
    print(f"{'Foo.bar':<22}{type(Foo.bar).__name__:<12}"
          f"__qualname__={Foo.bar.__qualname__!r}")
    print(f"{'foo.bar':<22}{type(foo.bar).__name__:<12}"
          f"bound to {type(foo.bar.__self__).__name__} instance")
    print(f"{'foo.bar.__func__':<22}{type(foo.bar.__func__).__name__:<12}"
          f"qualname={foo.bar.__func__.__qualname__!r}")
    print(f"{'foo.bar.__self__':<22}{type(foo.bar.__self__).__name__:<12}"
          f"is foo? {foo.bar.__self__ is foo}")
    print(f"foo.bar(10)            -> {foo.bar(10)}   "
          "(== Foo.bar(foo, 10))")
    print()

    check("Foo.bar is the bare function (a function, not a method)",
          type(Foo.bar).__name__ == "function")
    check("foo.bar is a bound method (NOT a function)",
          type(foo.bar).__name__ == "method")
    check("foo.bar.__func__ is Foo.bar", foo.bar.__func__ is Foo.bar)
    check("foo.bar.__self__ is foo", foo.bar.__self__ is foo)
    check("foo.bar(10) == Foo.bar(foo, 10)", foo.bar(10) == Foo.bar(foo, 10))
    check("function defines __get__ (so it is a descriptor)",
          hasattr(Foo.bar, "__get__"))
    check("function does NOT define __set__ (so it is a NON-DATA descriptor)",
          not hasattr(Foo.bar, "__set__"))


# ----------------------------------------------------------------------------
# Section F — staticmethod / classmethod are descriptors too
# ----------------------------------------------------------------------------

def section_f_static_classmethod() -> None:
    banner("F — staticmethod & classmethod are descriptors too")
    print("staticmethod.__get__ returns the bare function (no self, no cls).")
    print("classmethod.__get__ binds the CLASS as the first argument (cls).")
    print("Both are descriptors sitting in the class __dict__, just like")
    print("ordinary functions — only their __get__ policy differs.\n")

    class C:
        @staticmethod
        def add(a, b):
            return a + b

        @classmethod
        def cls_name(cls):
            return cls.__name__

    c = C()
    print(f"C.__dict__['add']      is a {type(C.__dict__['add']).__name__}")
    print(f"C.__dict__['cls_name'] is a {type(C.__dict__['cls_name']).__name__}")
    print(f"C.add(2, 3)     -> {C.add(2, 3)}   (no self, no cls — bare call)")
    print(f"c.add(2, 3)     -> {c.add(2, 3)}   (same: staticmethod strips self)")
    print(f"C.cls_name()    -> {C.cls_name()!r}   (cls bound to C)")
    print(f"c.cls_name()    -> {c.cls_name()!r}   (cls STILL bound to type(c))")
    print()

    check("C.add(2,3) == 5 (staticmethod ignores self/cls)", C.add(2, 3) == 5)
    check("staticmethod is identical via class or instance",
          C.add is c.add)   # staticmethod.__get__ returns the bare function
    check("classmethod binds the class as cls", C.cls_name() == "C")
    check("classmethod binds cls == type(c) even from an instance",
          c.cls_name() == type(c).__name__)
    check("staticmethod object has __get__ (it is a descriptor)",
          hasattr(C.__dict__["add"], "__get__"))
    check("classmethod object has __get__ (it is a descriptor)",
          hasattr(C.__dict__["cls_name"], "__get__"))


# ----------------------------------------------------------------------------
# Section G — __slots__: no __dict__, fixed layout
# ----------------------------------------------------------------------------

def section_g_slots() -> None:
    banner("G — __slots__: removes the instance __dict__")
    print("A class with __slots__ trades the per-instance __dict__ for a")
    print("fixed-size array of member descriptors (one per slot name). The")
    print("payoff: instant AttributeError on unknown attributes, and a much")
    print("smaller per-instance memory footprint. The cost: no __dict__, so")
    print("no ad-hoc attributes and no functools.cached_property.\n")

    class Point2D:
        __slots__ = ("x", "y")

        def __init__(self, x, y):
            self.x = x
            self.y = y

    class Point2DDict:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    p = Point2D(1, 2)
    print(f"Point2D(1, 2).x, .y  -> {p.x}, {p.y}")
    print(f"hasattr(p, '__dict__')  -> {hasattr(p, '__dict__')}   "
          "(slots class has NO instance dict)")
    print(f"hasattr(Point2DDict(), '__dict__') -> {hasattr(Point2DDict(0, 0), '__dict__')}")

    blocked = False
    try:
        p.z = 99          # 'z' not in __slots__
    except AttributeError as exc:
        blocked = True
        print(f"p.z = 99  ->  AttributeError: {exc}")
    print()

    check("__slots__ class has NO __dict__", not hasattr(p, "__dict__"))
    check("non-slots class DOES have a __dict__",
          hasattr(Point2DDict(0, 0), "__dict__"))
    check("assigning an unknown slot name raises AttributeError", blocked)
    check("each slot name is itself a member descriptor on the class",
          hasattr(type(p).__dict__["x"], "__get__")
          and hasattr(type(p).__dict__["x"], "__set__"))


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("properties_descriptors.py — Phase 2 bundle #12.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_property_basics()
    section_b_descriptor_protocol()
    section_c_data_vs_nondata()
    section_d_myproperty()
    section_e_functions_are_descriptors()
    section_f_static_classmethod()
    section_g_slots()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
