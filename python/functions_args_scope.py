"""
functions_args_scope.py — Bundle #6 (Phase 1).

GOAL (one line): show, by printing every value, how Python passes arguments,
when default values are evaluated (def-time, not call-time), how the LEGB rule
resolves names, and why an assignment anywhere in a body turns a name local for
the WHOLE body (the UnboundLocalError trap).

This is the GROUND TRUTH for FUNCTIONS_ARGS_SCOPE.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python functions_args_scope.py
"""

from __future__ import annotations

import time

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers (house style, copied from the style anchor)
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
# Section A — argument kinds: positional/keyword, *args, **kwargs, /, *, unpacking
# ----------------------------------------------------------------------------

def section_a_argument_kinds() -> None:
    banner("A — Argument kinds: positional, *args, **kwargs, /, and *")
    print("A parameter list has up to five slots in a fixed order:\n"
          "    def f(pos_only, /, normal, *args, kw_only, **kwargs)\n"
          "*args packs the leftover POSITIONAL args into a TUPLE; **kwargs\n"
          "packs the leftover KEYWORD args into a DICT. A bare '*' forces the\n"
          "params after it to be keyword-only; a bare '/' forces the params\n"
          "before it to be positional-only.\n")

    def kinds(a, b, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return {
            "a": a,
            "b": b,
            "args": args,
            "args is tuple": isinstance(args, tuple),
            "kwargs": kwargs,
            "kwargs is dict": isinstance(kwargs, dict),
        }

    r = kinds(1, 2, 3, 4, x=5, y=6)
    print(f"{'call':<34}{'value'}")
    print("-" * 62)
    print(f"{'kinds(1,2,3,4,x=5,y=6)':<34}{r['a']}, {r['b']}")
    print(f"{'  args (leftover positional)':<34}{r['args']}")
    print(f"{'  isinstance(args, tuple)':<34}{r['args is tuple']}")
    print(f"{'  kwargs (leftover keyword)':<34}{r['kwargs']}")
    print(f"{'  isinstance(kwargs, dict)':<34}{r['kwargs is dict']}")
    print()

    # Keyword-only args: everything after a bare '*' must be passed by keyword.
    def kw_only(a, *, k):
        return (a, k)

    # Positional-only args: everything before a bare '/' must be passed by
    # position (its name is NOT externally usable).
    def pos_only(a, /, b):
        return (a, b)

    print(f"{'signature':<28}{'call':<22}{'result'}")
    print("-" * 64)
    print(f"{'def kw_only(a, *, k)':<28}{'kw_only(1, k=2)':<22}{kw_only(1, k=2)}")
    print(f"{'def pos_only(a, /, b)':<28}{'pos_only(1, 2)':<22}{pos_only(1, 2)}")
    print()

    # Unpacking at the CALL site: * expands an iterable to positional args,
    # ** expands a mapping to keyword args.
    def add3(a, b, c):
        return a + b + c

    unpacked = add3(*[1, 2], **{"c": 3})
    print(f"add3(*[1, 2], **{{'c': 3}}) = {unpacked}")
    print()

    bare = kinds(0, 0)
    check("args is a tuple", isinstance(bare["args"], tuple))
    check("kwargs is a dict", isinstance(bare["kwargs"], dict))
    check("bare '*' makes following params keyword-only", kw_only(1, k=2) == (1, 2))
    check("bare '/' makes preceding params positional-only", pos_only(1, 2) == (1, 2))
    check("call-site * and ** unpack into positional and keyword args",
          add3(*[1, 2], **{"c": 3}) == 6)


# ----------------------------------------------------------------------------
# Section B — the mutable-default trap (default evaluated ONCE, at def-time)
# ----------------------------------------------------------------------------

def section_b_mutable_default_trap() -> None:
    banner("B — The mutable-default trap: the default is built ONCE")
    print("Default values are evaluated exactly ONCE — when the 'def' runs —\n"
          "and the SAME object is reused on every call that omits that arg.\n"
          "For an immutable default (int/str/None) you never notice; for a\n"
          "MUTABLE default (list/dict/set) every call mutates the one shared\n"
          "object. The fix is `acc=None` + rebuild inside the body.\n")

    def append_trap(x, acc=[]):  # noqa: ANN001 (the trap, on purpose)
        acc.append(x)
        return acc

    default_id_before = id(append_trap.__defaults__[0])
    r1 = append_trap(1)              # acc defaults to the shared list -> [1]
    snap1 = list(r1)                 # snapshot the value BEFORE the next call
    r2 = append_trap(2)              # SAME shared list, now [1, 2]
    snap2 = list(r2)
    default_id_after = id(append_trap.__defaults__[0])

    print(f"{'expression':<40}{'result'}")
    print("-" * 62)
    print(f"{'append_trap(1)  -> snapshot':<40}{snap1}")
    print(f"{'append_trap(2)  -> snapshot':<40}{snap2}")
    print(f"{'r1 is r2 (same shared list)':<40}{r1 is r2}")
    print(f"{'id(default) before == after':<40}"
          f"{default_id_before == default_id_after}")
    print(f"{'append_trap.__defaults__[0]':<40}{append_trap.__defaults__[0]}")
    print()

    # The canonical fix: sentinel None, rebuild a fresh collection per call.
    def append_safe(x, acc=None):  # noqa: ANN001
        if acc is None:
            acc = []
        acc.append(x)
        return acc

    s1 = append_safe(1)             # fresh list -> [1]
    s2 = append_safe(2)             # a DIFFERENT fresh list -> [2]
    print(f"{'append_safe(1)  [None sentinel]':<40}{s1}")
    print(f"{'append_safe(2)  [None sentinel]':<40}{s2}")
    print(f"{'s1 is s2 (fresh list each call)':<40}{s1 is s2}")
    print()

    check("trap accumulates: append_trap(1) == [1]", snap1 == [1])
    check("trap accumulates: append_trap(2) == [1, 2]", snap2 == [1, 2])
    check("both calls returned the SAME list object", r1 is r2)
    check("the default object's id() is stable across calls",
          default_id_before == default_id_after)
    check("the None-sentinel fix gives a fresh list each call", s1 == [1]
          and s2 == [2] and s1 is not s2)


# ----------------------------------------------------------------------------
# Section C — default evaluated at def-time (time.time frozen once)
# ----------------------------------------------------------------------------

def section_c_def_time_evaluation() -> None:
    banner("C — Defaults are evaluated at def-time, not call-time")
    print("Because the default expression runs once when 'def' executes (not\n"
          "each call), a default of `time.time()` captures a single timestamp\n"
          "frozen at definition time. Two calls separated by a sleep return\n"
          "the SAME value — proving call-time evaluation does NOT happen.\n")

    def stamped(t=time.time()):  # noqa: ANN001
        return t

    t1 = stamped()                  # uses the default (frozen at def-time)
    time.sleep(0.05)                # wall clock advances 50ms
    t2 = stamped()                  # STILL the same frozen default
    advanced = time.time() - t1     # how far the real clock has moved

    print(f"{'expression':<46}{'result'}")
    print("-" * 62)
    print(f"{'t1 - stamped.__defaults__[0]':<46}{t1 - stamped.__defaults__[0]}")
    print(f"{'t2 - t1  (despite a 0.05s sleep)':<46}{t2 - t1}")
    print(f"{'t1 is t2  (literally the same float object)':<46}{t1 is t2}")
    print(f"{'time.time() - t1 > 0.04  (real clock moved)':<46}"
          f"{advanced > 0.04}")
    print()

    check("the returned value equals the frozen default exactly",
          t1 - stamped.__defaults__[0] == 0.0)
    check("t2 == t1 despite the sleep (no call-time evaluation)", t2 == t1)
    check("the default is literally the same float object", t1 is t2)
    check("the real wall clock HAS advanced past the frozen default",
          advanced > 0.04)


# ----------------------------------------------------------------------------
# Section D — LEGB resolution + nonlocal/global
# ----------------------------------------------------------------------------

legb_global = "G (global)"   # Global scope


def section_d_legb() -> None:
    banner("D — LEGB resolution: Local, Enclosing, Global, Built-in")
    print("Name lookup walks four scopes in fixed order — Local -> Enclosing\n"
          "-> Global -> Built-in — and stops at the FIRST hit. Reading a name\n"
          "needs no declaration. WRITING (assignment) defaults to Local; to\n"
          "rebind an Enclosing name use 'nonlocal', to rebind a Global name\n"
          "use 'global'.\n")

    enclosing = "E (enclosing)"   # Enclosing scope (of inner)

    def inner() -> list[str]:
        local = "L (local)"      # Local scope
        # Each name resolves at the FIRST scope that has it: LEGB order.
        return [local, enclosing, legb_global, len.__name__]

    legb_result = inner()

    # nonlocal: inner rebinds the ENCLOSING variable (mutation survives).
    def make_counter() -> object:
        count = 0                # Enclosing variable

        def step() -> int:
            nonlocal count       # <-- without this, count += 1 -> UnboundLocalError
            count += 1
            return count

        return step

    counter = make_counter()
    counter_vals = (counter(), counter(), counter())

    # global: function rebinds the GLOBAL variable.
    def bump_global() -> int:
        global legb_global_n  # noqa: PLW0603 (demo only)
        legb_global_n += 1
        return legb_global_n

    # set up here so the global demo is self-contained & deterministic
    global legb_global_n  # noqa: PLW0603
    legb_global_n = 0
    global_vals = (bump_global(), bump_global())

    print(f"{'expression':<36}{'result'}")
    print("-" * 62)
    print(f"{'inner() reads [L, E, G, B]':<36}{legb_result}")
    print(f"{'counter() x3  (nonlocal rebind)':<36}{counter_vals}")
    print(f"{'bump_global() x2  (global rebind)':<36}{global_vals}")
    print()

    check("LEGB: local read wins over enclosing/global", legb_result[0]
          == "L (local)")
    check("LEGB: enclosing read resolves before global", legb_result[1]
          == "E (enclosing)")
    check("LEGB: global read resolves before built-in", legb_result[2]
          == "G (global)")
    check("LEGB: built-in (len) is the last fallback", legb_result[3] == "len")
    check("nonlocal lets inner rebind the enclosing counter", counter_vals
          == (1, 2, 3))
    check("global lets a function rebind a module-level name", global_vals
          == (1, 2))


# ----------------------------------------------------------------------------
# Section E — the assignment-makes-local rule (UnboundLocalError)
# ----------------------------------------------------------------------------

unbound_x = 99   # a global that the function below will SHADOW


def section_e_assignment_makes_local() -> None:
    banner("E — Assignment makes a name local for the WHOLE body")
    print("If a name is assigned ANYWHERE in a function body, the compiler\n"
          "treats it as local for the ENTIRE body — even lines BEFORE the\n"
          "assignment. So `print(x); x = 1` raises UnboundLocalError on the\n"
          "print(), although a global x exists. Reads-only stay global.\n")

    def reads_only() -> int:
        # No assignment to unbound_x here -> it is resolved as GLOBAL.
        return unbound_x

    def reads_then_writes() -> None:
        print(unbound_x)   # noqa: F823  # <-- the LESSON: raises UnboundLocalError
        unbound_x = 1      # noqa: F841  # this assignment makes 'unbound_x' local body-wide

    print(f"{'expression':<40}{'result'}")
    print("-" * 62)
    print(f"{'reads_only()  (no assignment -> global)':<40}{reads_only()}")
    raised: str | None = None
    message: str | None = None
    try:
        reads_then_writes()
    except UnboundLocalError as exc:
        raised = type(exc).__name__
        message = str(exc)
    print(f"{'reads_then_writes() raises':<40}{raised}")
    print(f"{'  message':<40}{message!r}")
    print()

    check("a read-only function sees the global", reads_only() == 99)
    check("print(x) before x=1 raises UnboundLocalError", raised
          == "UnboundLocalError")
    check("the error names the shadowed variable", message is not None
          and "unbound_x" in message)


# ----------------------------------------------------------------------------
# Section F — closures: capturing enclosing bindings (-> decorators)
# ----------------------------------------------------------------------------

def section_f_closures() -> None:
    banner("F — Closures: an inner function captures enclosing bindings")
    print("A closure is an inner function that remembers the variables of its\n"
          "ENCLOSING scope — even after the outer function has returned. The\n"
          "captured ('free') variables live in __closure__ cells; each call to\n"
          "the outer builds a NEW set of cells, so two closures are\n"
          "independent.\n")

    def make_adder(n: int):   # 'n' is the ENCLOSING binding captured below
        def adder(x: int) -> int:
            return x + n      # 'n' here is a FREE variable
        return adder

    add10 = make_adder(10)
    add20 = make_adder(20)

    print(f"{'expression':<40}{'result'}")
    print("-" * 62)
    print(f"{'add10(5)':<40}{add10(5)}")
    print(f"{'add20(5)':<40}{add20(5)}")
    print(f"{'add10.__code__.co_freevars':<40}{add10.__code__.co_freevars}")
    print(f"{'add10.__closure__[0].cell_contents':<40}"
          f"{add10.__closure__[0].cell_contents}")
    print(f"{'add20.__closure__[0].cell_contents':<40}"
          f"{add20.__closure__[0].cell_contents}")
    print()

    # Expert gotcha: closures capture VARIABLES (by reference to the cell), not
    # VALUES frozen at definition. A loop variable keeps changing, so every
    # closure built in the loop sees the loop's FINAL value when called later.
    late = [lambda: i for i in range(3)]   # all capture the SAME 'i'
    fixed = [lambda i=i: i for i in range(3)]  # default binds i at def-time

    print(f"{'late[0]() / late[1]() / late[2]()':<40}"
          f"{late[0](), late[1](), late[2]()}")
    print(f"{'fixed[0]() / fixed[1]() / fixed[2]()':<40}"
          f"{fixed[0](), fixed[1](), fixed[2]()}")  # noqa: B023
    print()

    check("add10(5) == 15 (captured n == 10)", add10(5) == 15)
    check("add20(5) == 25 (captured n == 20)", add20(5) == 25)
    check("each adder has its OWN captured n", add10.__closure__[0]
          .cell_contents == 10 and add20.__closure__[0].cell_contents == 20)
    check("'n' is a free variable of adder", "n" in add10.__code__.co_freevars)
    check("late-binding closures all see the loop's final value (2)",
          late[0]() == late[1]() == late[2]() == 2)
    check("default-arg binding freezes each value at def-time",
          (fixed[0](), fixed[1](), fixed[2]()) == (0, 1, 2))


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("functions_args_scope.py — Phase 1 bundle #6.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_argument_kinds()
    section_b_mutable_default_trap()
    section_c_def_time_evaluation()
    section_d_legb()
    section_e_assignment_makes_local()
    section_f_closures()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
