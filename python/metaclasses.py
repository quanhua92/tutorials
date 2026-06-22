"""
metaclasses.py — Bundle #13 (Phase 2).

GOAL (one line): show, by printing every value, that a metaclass is just the
class of a class, that `type` builds classes, that `__init_subclass__` solves
the common 90% of customization needs, and that you rarely need a real custom
metaclass.

This is the GROUND TRUTH for METACLASSES.md. Every value, table, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

Run:
    uv run python metaclasses.py
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
# Section A — type is the metaclass; the 3-arg type() builds classes
# ----------------------------------------------------------------------------

def section_a_type_is_the_metaclass() -> None:
    banner("A — type is the metaclass; type(name, bases, dict) builds a class")
    print("Every class is an INSTANCE of its metaclass. The default metaclass")
    print("is `type`, so `type(Foo) is type`. The 3-arg form type(name, bases,")
    print("dict) is the dynamic form of the `class` statement — it builds a new")
    print("class object at runtime from a name, a bases tuple, and a namespace.\n")

    class Foo:
        x = 1

    print(f"{'expression':<34}{'result'}")
    print("-" * 52)
    for label, value in [
        ("type(Foo)", type(Foo)),
        ("type(Foo) is type", type(Foo) is type),
        ("isinstance(Foo, type)", isinstance(Foo, type)),
        ("type(int) is type", type(int) is type),
        ("type(type) is type", type(type) is type),
    ]:
        print(f"{label:<34}{value}")
    print()

    # 3-arg type(): build a class at runtime, same as a `class` statement.
    Bar = type("Bar", (), {"a": 1})
    print("Bar = type('Bar', (), {'a': 1})   # 3-arg type() builds a class\n")
    print(f"{'expression':<30}{'result'}")
    print("-" * 48)
    for label, value in [
        ("type(Bar) is type", type(Bar) is type),
        ("Bar.__name__", Bar.__name__),
        ("Bar.__bases__", Bar.__bases__),
        ("Bar.a", Bar.a),
        ("Bar().a", Bar().a),
        ("isinstance(Bar(), object)", isinstance(Bar(), object)),
    ]:
        print(f"{label:<30}{value!r}")
    print()

    check("type(Foo) is type (the default metaclass)", type(Foo) is type)
    check("type(type) is type (type is its own metaclass)",
          type(type) is type)
    check("type('Bar', (), {'a': 1})().a == 1", Bar().a == 1)
    check("the 3-arg type() returns a class (instance of type)",
          isinstance(Bar, type))


# ----------------------------------------------------------------------------
# Section B — __init_subclass__: the 90% solution (plugin registry)
# ----------------------------------------------------------------------------

def section_b_init_subclass_registry() -> None:
    banner("B — __init_subclass__: the 90% solution (plugin registry)")
    print("__init_subclass__ runs in the PARENT whenever a SUBCLASS is defined.")
    print("It receives the new subclass as `cls`. This is the common, simple way")
    print("to react to subclassing — and it replaces most metaclass use cases.\n")

    class Plugin:
        registry: dict[str, type] = {}

        def __init_subclass__(cls, **kwargs: object) -> None:
            super().__init_subclass__(**kwargs)
            Plugin.registry[cls.__name__] = cls

    print("class Plugin:")
    print("    registry = {}")
    print("    def __init_subclass__(cls, **kwargs):")
    print("        super().__init_subclass__(**kwargs)")
    print("        Plugin.registry[cls.__name__] = cls\n")
    print("Defining subclasses now — the parent hook fires at definition time:\n")

    class CSVLoader(Plugin):
        pass

    class JSONLoader(Plugin):
        pass

    print("class CSVLoader(Plugin):  pass   # __init_subclass__ fires")
    print("class JSONLoader(Plugin): pass   # __init_subclass__ fires\n")

    print(f"{'expression':<46}{'result'}")
    print("-" * 64)
    for label, value in [
        ("list(Plugin.registry)", list(Plugin.registry)),
        ("Plugin.registry['CSVLoader'] is CSVLoader",
         Plugin.registry["CSVLoader"] is CSVLoader),
        ("Plugin.registry['JSONLoader'] is JSONLoader",
         Plugin.registry["JSONLoader"] is JSONLoader),
        ("type(CSVLoader) is type", type(CSVLoader) is type),
    ]:
        print(f"{label:<46}{value}")
    print()

    check("registry contains both subclasses after class defs",
          set(Plugin.registry) == {"CSVLoader", "JSONLoader"})
    check("registry maps names to the actual class objects",
          Plugin.registry["CSVLoader"] is CSVLoader)
    check("no custom metaclass involved (type(CSVLoader) is type)",
          type(CSVLoader) is type)


# ----------------------------------------------------------------------------
# Section C — a custom metaclass rewrites the namespace at def time
# ----------------------------------------------------------------------------

def section_c_custom_metaclass() -> None:
    banner("C — A custom metaclass rewrites the namespace at definition time")
    print("A metaclass is a subclass of `type`. Its __new__ runs when a `class`")
    print("statement executes (NOT at instantiation) and may rewrite the class")
    print("namespace before the class object is created. Here: auto-uppercase")
    print("every non-dunder method name.\n")

    class UpperMeta(type):
        def __new__(mcs, name, bases, ns):
            new_ns = {}
            for key, val in ns.items():
                if callable(val) and not key.startswith("__"):
                    new_ns[key.upper()] = val
                else:
                    new_ns[key] = val
            print(f"  UpperMeta.__new__ running for {name!r}; "
                  f"rewriting namespace")
            return super().__new__(mcs, name, bases, new_ns)

    print("class UpperMeta(type):")
    print("    def __new__(mcs, name, bases, ns):")
    print("        # uppercase every non-dunder callable name\n")

    class Greeter(metaclass=UpperMeta):
        def greet(self) -> str:
            return "hi"

        def wave(self) -> str:
            return "wave"
    print()

    print(f"{'expression':<34}{'result'}")
    print("-" * 52)
    for label, value in [
        ("type(Greeter).__name__", type(Greeter).__name__),
        ("type(Greeter) is UpperMeta", type(Greeter) is UpperMeta),
        ("'GREET' in Greeter.__dict__", "GREET" in Greeter.__dict__),
        ("'WAVE' in Greeter.__dict__", "WAVE" in Greeter.__dict__),
        ("'greet' in Greeter.__dict__", "greet" in Greeter.__dict__),
        ("Greeter().GREET()", Greeter().GREET()),
    ]:
        print(f"{label:<34}{value!r}")
    print()

    check("Greeter's metaclass is UpperMeta", type(Greeter) is UpperMeta)
    check("method names were uppercased at definition time",
          "GREET" in Greeter.__dict__ and "WAVE" in Greeter.__dict__)
    check("original lowercase names are gone", "greet" not in Greeter.__dict__)
    check("the uppercased method still works", Greeter().GREET() == "hi")


# ----------------------------------------------------------------------------
# Section D — __new__ vs __init__ (the singleton trick + the skip rule)
# ----------------------------------------------------------------------------

def section_d_new_vs_init() -> None:
    banner("D — __new__ creates, __init__ initializes (singleton + skip rule)")
    print("__new__ creates and returns the instance; __init__ initializes it.")
    print("RULE: if __new__ returns an instance of a DIFFERENT class, __init__")
    print("is NOT called. This enables the singleton/cache trick — but beware:")
    print("a same-class singleton still re-runs __init__ on every call.\n")

    class Singleton:
        _instance: object = None
        init_calls = 0

        def __new__(cls):
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

        def __init__(self):
            Singleton.init_calls += 1

    s1 = Singleton()
    s2 = Singleton()
    print("s1 = Singleton(); s2 = Singleton()   # same-class singleton\n")
    print(f"{'expression':<26}{'result'}")
    print("-" * 44)
    for label, value in [
        ("s1 is s2", s1 is s2),
        ("Singleton.init_calls", Singleton.init_calls),
    ]:
        print(f"{label:<26}{value!r}")
    print()

    check("singleton returns the SAME object (s1 is s2)", s1 is s2)
    check("BUT __init__ ran twice (init_calls == 2) — the gotcha",
          Singleton.init_calls == 2)

    class Other:
        pass

    class Factory:
        init_calls = 0

        def __new__(cls):
            return Other()  # an instance of a DIFFERENT class

        def __init__(self):
            Factory.init_calls += 1

    obj = Factory()
    print("class Factory:\n    def __new__(cls): return Other()   "
          "# different class\nobj = Factory()\n")
    print(f"{'expression':<30}{'result'}")
    print("-" * 48)
    for label, value in [
        ("isinstance(obj, Factory)", isinstance(obj, Factory)),
        ("isinstance(obj, Other)", isinstance(obj, Other)),
        ("Factory.init_calls", Factory.init_calls),
    ]:
        print(f"{label:<30}{value!r}")
    print()

    check("Factory() returns an Other (not a Factory)", isinstance(obj, Other))
    check("__init__ was SKIPPED (init_calls == 0)", Factory.init_calls == 0)


# ----------------------------------------------------------------------------
# Section E — __class_getitem__: class-level parametrization (Vec[int])
# ----------------------------------------------------------------------------

def section_e_class_getitem() -> None:
    banner("E — __class_getitem__: class-level parametrization (Vec[int])")
    print("Writing `SomeClass[arg]` calls the CLASSMETHOD __class_getitem__,")
    print("NOT __getitem__ (which is for instances). This is how list[int] works")
    print("without instantiating list. It returns whatever you choose — the")
    print("builtins return a GenericAlias; your class can return anything.\n")

    class Vec:
        def __class_getitem__(cls, item):
            return ("Vec", item)

    print("class Vec:\n    def __class_getitem__(cls, item):\n"
          "        return ('Vec', item)\n")
    print(f"{'expression':<28}{'result'}")
    print("-" * 46)
    for label, value in [
        ("Vec[int]", Vec[int]),
        ("Vec[str]", Vec[str]),
        ("type(Vec[int]).__name__", type(Vec[int]).__name__),
    ]:
        print(f"{label:<28}{value!r}")
    print()

    import types
    alias = list[int]
    print(f"list[int]                              {alias!r}")
    print(f"type(list[int]).__name__               {type(alias).__name__!r}")
    print(f"isinstance(list[int], types.GenericAlias) "
          f"{isinstance(alias, types.GenericAlias)}")
    print()

    check("Vec[int] returns our custom tuple", Vec[int] == ("Vec", int))
    check("Vec[int] does NOT instantiate Vec",
          not isinstance(Vec[int], Vec))
    check("list[int] is a GenericAlias (no instantiation)",
          isinstance(list[int], types.GenericAlias))
    check("__class_getitem__ is stored on the class (auto classmethod)",
          "__class_getitem__" in Vec.__dict__)


# ----------------------------------------------------------------------------
# Section F — when do you ACTUALLY need a metaclass?
# ----------------------------------------------------------------------------

def section_f_when_metaclass() -> None:
    banner("F — When do you ACTUALLY need a metaclass?")
    print("Rule of thumb: reach for __init_subclass__ first. A real metaclass")
    print("is only needed when you must customize class creation BEFORE or")
    print("AROUND type.__new__ — __prepare__, __instancecheck__, or modifying")
    print("ALL classes in a hierarchy at the namespace level.\n")

    rows = [
        ("auto-register subclasses", "__init_subclass__",
         "simple hook in parent"),
        ("validate subclass kwargs", "__init_subclass__",
         "raise in the parent hook"),
        ("inject/rewrite methods at def time", "metaclass __new__",
         "UpperMeta (Section C)"),
        ("custom namespace (ordered, etc.)", "metaclass __prepare__",
         "PEP 3115; rare"),
        ("customize isinstance/issubclass", "metaclass __instancecheck__",
         "abc.ABCMeta"),
        ("enforce rules on EVERY class in a lib", "metaclass",
         "EnumMeta, ABCMeta"),
    ]
    print(f"{'task':<38}{'use':<28}{'note'}")
    print("-" * 90)
    for task, use, note in rows:
        print(f"{task:<38}{use:<28}{note}")
    print()

    import abc
    import enum
    print(f"type(abc.ABC).__name__             {type(abc.ABC).__name__!r}")
    print(f"type(enum.Enum).__name__           {type(enum.Enum).__name__!r}")
    print(f"issubclass(type(abc.ABC), type)    "
          f"{issubclass(type(abc.ABC), type)}")
    print()

    check("abc.ABC's metaclass is a subclass of type",
          issubclass(type(abc.ABC), type))
    check("enum.Enum's metaclass is a subclass of type",
          issubclass(type(enum.Enum), type))


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("metaclasses.py — Phase 2 bundle #13.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_type_is_the_metaclass()
    section_b_init_subclass_registry()
    section_c_custom_metaclass()
    section_d_new_vs_init()
    section_e_class_getitem()
    section_f_when_metaclass()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
