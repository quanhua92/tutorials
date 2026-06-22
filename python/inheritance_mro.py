"""
inheritance_mro.py — Bundle #11 (Phase 2).

GOAL (one line): show, by printing every value, how Python resolves methods
through single inheritance, the diamond, and the C3 linearization — and why
some class layouts are structurally impossible.

This is the GROUND TRUTH for INHERITANCE_MRO.md. Every MRO tuple, call order,
and worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python inheritance_mro.py
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


def _mro_names(mro: tuple[type, ...]) -> str:
    """Format an __mro__ tuple as readable class names."""
    return "(" + ", ".join(c.__name__ for c in mro) + ")"


# ----------------------------------------------------------------------------
# Section A — single inheritance + method override + super().__init__()
# ----------------------------------------------------------------------------

class Animal:
    def __init__(self, name: str) -> None:
        self.name = name

    def speak(self) -> str:
        return f"{self.name} makes a sound"


class Dog(Animal):
    def __init__(self, name: str, breed: str) -> None:
        super().__init__(name)          # delegate to the parent constructor
        self.breed = breed              # then add the child's own state

    def speak(self) -> str:            # override the parent method
        return f"{self.name} the {self.breed} barks: Woof!"


def section_a_single_inheritance() -> None:
    banner("A — Single inheritance: override + super().__init__()")
    print("A subclass extends ONE parent. It may override methods and add new")
    print("attributes. super().__init__(...) delegates to the parent so the")
    print("parent's state is set up before the child adds its own.\n")

    dog = Dog("Rex", "Husky")
    print("dog = Dog('Rex', 'Husky')")
    print(f"  dog.name   = {dog.name!r}   (set by Animal.__init__ via super)")
    print(f"  dog.breed  = {dog.breed!r}  (set by Dog.__init__)")
    print(f"  dog.speak()= {dog.speak()}")
    print(f"  Dog.__mro__= {_mro_names(Dog.__mro__)}\n")

    check("super().__init__ set .name from the parent", dog.name == "Rex")
    check("the child set .breed itself", dog.breed == "Husky")
    check("the override replaced speak()", "Woof!" in dog.speak())


# ----------------------------------------------------------------------------
# Section B — isinstance / issubclass honor the MRO
# ----------------------------------------------------------------------------

def section_b_isinstance_issubclass() -> None:
    banner("B — isinstance / issubclass walk the full MRO chain")
    print("isinstance(obj, cls) is True if cls is in type(obj).__mro__.")
    print("issubclass(sub, sup) is True if sup is in sub.__mro__. Both walk")
    print("the ENTIRE chain, not just the direct parent.\n")

    dog = Dog("Rex", "Husky")
    print(f"{'expression':<30}{'result'}")
    print("-" * 42)
    for label, value in [
        ("isinstance(dog, Dog)", isinstance(dog, Dog)),
        ("isinstance(dog, Animal)", isinstance(dog, Animal)),
        ("isinstance(dog, object)", isinstance(dog, object)),
        ("issubclass(Dog, Animal)", issubclass(Dog, Animal)),
        ("issubclass(Dog, object)", issubclass(Dog, object)),
        ("issubclass(Animal, Dog)", issubclass(Animal, Dog)),
    ]:
        print(f"{label:<30}{value}")
    print()

    check("isinstance(dog, Animal) (chain up)", isinstance(dog, Animal))
    check("isinstance(dog, object) (everything is object)",
          isinstance(dog, object))
    check("issubclass(Dog, object)", issubclass(Dog, object))
    check("issubclass(Animal, Dog) is False", not issubclass(Animal, Dog))


# ----------------------------------------------------------------------------
# Section C — multiple inheritance: the diamond + __mro__
# ----------------------------------------------------------------------------

class Base:
    def whoami(self) -> str:
        return "Base"


class Left(Base):
    def whoami(self) -> str:
        return "Left"


class Right(Base):
    def whoami(self) -> str:
        return "Right"


class Diamond(Left, Right):
    pass


def section_c_diamond_mro() -> None:
    banner("C — Multiple inheritance: the diamond and __mro__")
    print("class Base; class Left(Base); class Right(Base);")
    print("class Diamond(Left, Right) — the classic diamond shape.  Method")
    print("lookup follows Diamond.__mro__, computed by C3.  Left is listed")
    print("before Right, so Diamond().whoami() finds Left first.\n")

    print(f"Diamond.__mro__    = {_mro_names(Diamond.__mro__)}")
    print(f"Diamond().whoami() = {Diamond().whoami()!r}\n")

    expected = ("Diamond", "Left", "Right", "Base", "object")
    actual = tuple(c.__name__ for c in Diamond.__mro__)
    check("Diamond.__mro__ == (Diamond, Left, Right, Base, object)",
          actual == expected)
    check("whoami() resolves to Left (leftmost parent wins)",
          Diamond().whoami() == "Left")
    check("Base appears exactly once (no duplication in MRO)",
          actual.count("Base") == 1)
    check("object is the last element of every MRO",
          Diamond.__mro__[-1] is object)


# ----------------------------------------------------------------------------
# Section D — super() walks the INSTANCE's class MRO (cooperative)
# ----------------------------------------------------------------------------

class Root:
    def greet(self) -> list[str]:
        return ["Root.greet"]


class Branch1(Root):
    def greet(self) -> list[str]:
        return ["Branch1.greet"] + super().greet()


class Branch2(Root):
    def greet(self) -> list[str]:
        return ["Branch2.greet"] + super().greet()


class Leaf(Branch1, Branch2):
    def greet(self) -> list[str]:
        return ["Leaf.greet"] + super().greet()


def section_d_super_walks_instance_mro() -> None:
    banner("D — super() walks the INSTANCE's class MRO (cooperative)")
    print("super() does NOT mean 'the parent class'. It means 'the NEXT class")
    print("after the current one in type(self).__mro__'.  In a diamond this")
    print("can be a SIBLING, not a parent.  Each level calls super() so every")
    print("class in the chain gets a turn (cooperative multiple inheritance).\n")

    print(f"Leaf.__mro__    = {_mro_names(Leaf.__mro__)}")
    print(f"Branch1.__mro__ = {_mro_names(Branch1.__mro__)}")
    print()
    print(f"Leaf().greet()    = {Leaf().greet()}")
    print("  ^ Branch1.greet's super() skips to Branch2 (sibling!), not Root")
    print(f"Branch1().greet() = {Branch1().greet()}")
    print("  ^ Branch1.greet's super() goes to Root (parent) — same code!\n")

    check("Leaf().greet() visits all four classes",
          Leaf().greet() == ["Leaf.greet", "Branch1.greet",
                             "Branch2.greet", "Root.greet"])
    check("Branch1().greet() skips Branch2 (not in Branch1.__mro__)",
          Branch1().greet() == ["Branch1.greet", "Root.greet"])
    check("Branch1's super() is Branch2 for a Leaf instance",
          Leaf.__mro__[Leaf.__mro__.index(Branch1) + 1] is Branch2)
    check("Branch1's super() is Root for a Branch1 instance",
          Branch1.__mro__[Branch1.__mro__.index(Branch1) + 1] is Root)


# ----------------------------------------------------------------------------
# Section E — C3 linearization: merge algorithm + impossible layout
# ----------------------------------------------------------------------------

class IA:
    pass


class IB:
    pass


class IX(IA, IB):
    pass


class IY(IB, IA):
    pass


def _c3_merge(seqs: list[list[str]]) -> list[str]:
    """Display version of the C3 merge — prints each step; raises TypeError."""
    result: list[str] = []
    work = [s[:] for s in seqs if s]
    while work:
        head: str | None = None
        for seq in work:
            candidate = seq[0]
            if not any(candidate in s[1:] for s in work):
                head = candidate
                break
        if head is None:
            raise TypeError(
                "Cannot create a consistent method resolution order (MRO)"
            )
        result.append(head)
        for seq in work:
            if seq and seq[0] == head:
                seq.pop(0)
        work = [s for s in work if s]
        print(f"  take {head:<10} -> {result}")
    return result


def section_e_c3_merge_and_inconsistency() -> None:
    banner("E — C3 linearization: merge algorithm + impossible layout")
    print("C3 formula:  L(C) = [C] + merge(L(P1), ..., L(Pn), [P1, ..., Pn])")
    print("Merge rule:  repeatedly take the first HEAD that is not in any TAIL")
    print("             of the input lists.  If every head is blocked, no MRO")
    print("             exists and Python raises TypeError at class creation.\n")

    print("Worked example — recompute Diamond.__mro__ from scratch:")
    print(f"    L(Left)       = {_mro_names(Left.__mro__)}")
    print(f"    L(Right)      = {_mro_names(Right.__mro__)}")
    print("    [Left, Right] (parent order)")
    print("  merge steps:")
    computed = ["Diamond"] + _c3_merge([
        [c.__name__ for c in Left.__mro__],
        [c.__name__ for c in Right.__mro__],
        ["Left", "Right"],
    ])
    actual = [c.__name__ for c in Diamond.__mro__]
    print(f"\n  _c3_merge result = {computed}")
    print(f"  Diamond.__mro__  = {_mro_names(Diamond.__mro__)}\n")

    check("our _c3_merge matches Diamond.__mro__", computed == actual)

    print("Impossible layout — IX(IA, IB) and IY(IB, IA) contradict:")
    print(f"  IX.__mro__ = {_mro_names(IX.__mro__)}   # demands IA before IB")
    print(f"  IY.__mro__ = {_mro_names(IY.__mro__)}   # demands IB before IA")
    print("  class IZ(IX, IY) -> both orderings -> deadlock.\n")

    try:
        _c3_merge([
            [c.__name__ for c in IX.__mro__],
            [c.__name__ for c in IY.__mro__],
            ["IX", "IY"],
        ])
    except TypeError as exc:
        print(f"  _c3_merge raises: {exc}")

    raised = False
    try:
        class IZ(IX, IY):  # noqa: F841
            pass
    except TypeError as exc:
        raised = True
        print(f"  Python raises:    {exc}")
    print()

    check("class IZ(IX, IY) raises TypeError (inconsistent MRO)", raised)


# ----------------------------------------------------------------------------
# Section F — a mixin combined via cooperative super()
# ----------------------------------------------------------------------------

class PlainGreeter:
    def greet(self) -> str:
        return "hello"


class UpperMixin:
    """A mixin that wraps the base greet() via cooperative super()."""

    def greet(self) -> str:
        base = super().greet()
        return f"{base} -> UPPER[{base.upper()}]"


class FancyGreeter(UpperMixin, PlainGreeter):
    pass


def section_f_mixin_cooperative() -> None:
    banner("F — A mixin combined via cooperative super()")
    print("A MIXIN is a small class designed to be combined with others. It")
    print("rarely stands alone — it calls super() and wraps the result, so it")
    print("slots into any MRO position seamlessly.\n")

    print(f"FancyGreeter.__mro__   = {_mro_names(FancyGreeter.__mro__)}")
    print(f"FancyGreeter().greet() = {FancyGreeter().greet()!r}")
    print("  ^ UpperMixin.greet calls super().greet() -> PlainGreeter.greet\n")

    check("FancyGreeter.__mro__ puts the mixin before the base",
          FancyGreeter.__mro__.index(UpperMixin)
          < FancyGreeter.__mro__.index(PlainGreeter))
    check("the mixin wraps the base output",
          "UPPER[HELLO]" in FancyGreeter().greet())


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("inheritance_mro.py — Phase 2 bundle #11.\n"
          "Every value below is computed by this file; the .md guide pastes\n"
          "it verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_single_inheritance()
    section_b_isinstance_issubclass()
    section_c_diamond_mro()
    section_d_super_walks_instance_mro()
    section_e_c3_merge_and_inconsistency()
    section_f_mixin_cooperative()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
