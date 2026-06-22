"""
decorators_deep.py — Bundle #14 (Phase 2).

GOAL (one line): show, by printing every value, that a decorator is a
higher-order function, that `@deco` is sugar for `f = deco(f)`, and that the
whole mechanism rests on closures — including the late-binding trap that bites
when you forget closures capture VARIABLES, not values.

This is the GROUND TRUTH for DECORATORS_DEEP.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python decorators_deep.py
"""

from __future__ import annotations

import time
from functools import WRAPPER_ASSIGNMENTS, lru_cache, partial, wraps

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
# a reusable logging decorator (used by Section A)
# ----------------------------------------------------------------------------

def log_calls(func):
    """Tiny logging decorator: prints each call's args and return value."""
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        print(f"    log: {func.__name__}(*{args}, **{kwargs}) -> {result!r}")
        return result
    return wrapper


# ----------------------------------------------------------------------------
# Section A — desugaring: @deco is sugar for f = deco(f)
# ----------------------------------------------------------------------------

def section_a_desugaring() -> None:
    banner("A — Desugaring: @deco is sugar for f = deco(f)")
    print("A decorator is a HIGHER-ORDER function: it takes a function and\n"
          "returns a (usually wrapped) function. The '@' syntax is PURE sugar.\n"
          "These two are identical:\n"
          "    @log_calls                  def _mul(a, b): ...\n"
          "    def add(a, b): ...          mul = log_calls(_mul)\n"
          "(PEP 318; language reference 8.7: 'the result must be a callable\n"
          "invoked with the function object as the only argument; the returned\n"
          "value is bound to the function name'.)\n")

    @log_calls
    def add(a, b):
        return a + b

    # The EXACT manual desugar: define the core, then rebind the name.
    def _mul_core(a, b):
        return a * b
    mul = log_calls(_mul_core)

    print("calling add(2, 3):")
    r_add = add(2, 3)
    print("calling mul(2, 4):")
    r_mul = mul(2, 4)
    print()
    print(f"{'expression':<28}{'result'}")
    print("-" * 44)
    print(f"{'add(2, 3)':<28}{r_add}")
    print(f"{'mul(2, 4)':<28}{r_mul}")
    print()

    check("@log_calls add(2,3) returns the original result 5", r_add == 5)
    check("manual desugar mul=log_calls(_mul_core) returns 8", r_mul == 8)
    check("both forms produce the SAME kind of wrapper object",
          type(add).__name__ == type(mul).__name__ == "function")


# ----------------------------------------------------------------------------
# Section B — closures recap + functools.wraps
# ----------------------------------------------------------------------------

def section_b_closures_and_wraps() -> None:
    banner("B — Closures recap (wrapper remembers func) + functools.wraps")
    print("A decorator's wrapper is an inner function that CLOSES OVER 'func'.\n"
          "After the outer returns, the wrapper still holds func alive in a\n"
          "__closure__ cell. WITHOUT @wraps the wrapper steals the original's\n"
          "identity (__name__ becomes 'wrapper'); WITH @wraps the name, doc,\n"
          "and __wrapped__ are preserved.\n")

    def plain(func):                       # NO @wraps
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper

    def nice(func):                        # WITH @wraps
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper

    @plain
    def original_plain():
        """the plain docstring."""
        return 42

    @nice
    def original_nice():
        """the nice docstring."""
        return 42

    print(f"{'expression':<44}{'result'}")
    print("-" * 62)
    print(f"{"original_plain.__code__.co_freevars":<44}"
          f"{original_plain.__code__.co_freevars}")
    print(f"{'WRAPPER_ASSIGNMENTS (what @wraps copies)':<44}"
          f"{WRAPPER_ASSIGNMENTS}")
    print(f"{'original_plain.__name__  (NO wraps)':<44}"
          f"{original_plain.__name__!r}")
    print(f"{'original_nice.__name__   (WITH wraps)':<44}"
          f"{original_nice.__name__!r}")
    print(f"{'original_nice.__doc__    (WITH wraps)':<44}"
          f"{original_nice.__doc__!r}")
    print(f"{'original_nice.__wrapped__ is the original':<44}"
          f"{original_nice.__wrapped__.__name__ == 'original_nice'}")
    print()

    check("the wrapper closes over 'func' (a free variable)",
          "func" in original_plain.__code__.co_freevars)
    check("WITHOUT @wraps the name is stolen -> 'wrapper'",
          original_plain.__name__ == "wrapper")
    check("WITH @wraps __name__ is preserved -> 'original_nice'",
          original_nice.__name__ == "original_nice")
    check("WITH @wraps __doc__ is preserved", original_nice.__doc__
          == "the nice docstring.")
    check("WITH @wraps __wrapped__ points back at the original",
          original_nice.__wrapped__.__name__ == "original_nice")


# ----------------------------------------------------------------------------
# Section C — a timing decorator (wall-clock measurement)
# ----------------------------------------------------------------------------

def timed(func):
    """Measure wall-clock time of each call; store it as wrapper.last_elapsed."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        wrapper.last_elapsed = time.perf_counter() - start
        return result
    wrapper.last_elapsed = 0.0
    return wrapper


def section_c_timing() -> None:
    banner("C — A timing decorator: measuring wall time per call")
    print("The wrapper records time.perf_counter() before/after the call.\n"
          "The RESULT is fully deterministic; the elapsed value is a measured\n"
          "float (we assert its TYPE and sign, never a hardcoded number).\n")

    @timed
    def slow_sum(n):
        total = 0
        for i in range(n):
            total += i
        return total

    r_small = slow_sum(10)
    e_small = slow_sum.last_elapsed
    r_big = slow_sum(1_000_000)
    e_big = slow_sum.last_elapsed

    print(f"{'expression':<44}{'result'}")
    print("-" * 66)
    print(f"{'slow_sum(10)':<44}{r_small}")
    print(f"{'slow_sum.last_elapsed is a float':<44}"
          f"{isinstance(e_small, float)}")
    print(f"{'slow_sum.last_elapsed > 0.0':<44}{e_small > 0.0}")
    print(f"{'slow_sum(1_000_000)':<44}{r_big}")
    print(f"{'bigger loop measured a LARGER elapsed':<44}{e_big > e_small}")
    print()

    check("slow_sum(10) == 45 (sum 0..9)", r_small == 45)
    check("slow_sum(1_000_000) == 499999500000 (sum 0..999999)",
          r_big == 499999500000)
    check("last_elapsed is a float", isinstance(e_big, float))
    check("the decorator measured a non-negative elapsed", e_big >= 0.0)
    check("1M-iteration loop took longer than a 10-iteration loop",
          e_big > e_small)


# ----------------------------------------------------------------------------
# Section D — parametrized decorator: THREE levels of nesting
# ----------------------------------------------------------------------------

def repeat(n=1):
    """Factory: @repeat(n=3) -> returns a decorator -> returns a wrapper.

    Three nested scopes:
        repeat   (factory)      captures n
        decorator               captures func
        wrapper                 runs func n times
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = None
            for _ in range(n):
                result = func(*args, **kwargs)
            return result
        return wrapper
    return decorator


def section_d_parametrized() -> None:
    banner("D — Parametrized decorator: @repeat(n=3), THREE nesting levels")
    print("@repeat(n=3) is NOT repeat applied to the function — it is repeat\n"
          "CALLED with n=3, which RETURNS the real decorator. That needs three\n"
          "nested scopes (factory -> decorator -> wrapper). Note the ambiguity:\n"
          "@deco      => f = deco(f)           (deco receives the function)\n"
          "@deco()    => f = deco()(f)          (deco receives nothing; returns\n"
          "                                     a decorator that receives f)\n")

    calls: list[str] = []

    @repeat(n=3)
    def announce(msg):
        calls.append(msg)
        return msg

    r = announce("hi")
    print(f"{'expression':<46}{'result'}")
    print("-" * 70)
    print(f"{'repeat.__code__.co_varnames (factory params)':<46}"
          f"{repeat.__code__.co_varnames}")
    print(f"{'announce(\"hi\") return value':<42}{r!r}")
    print(f"{'body actually ran (len(calls))':<42}{len(calls)}")
    print(f"{'calls list':<42}{calls}")
    print()

    check("@repeat(n=3) ran the body exactly 3 times", len(calls) == 3)
    check("@repeat(n=3) returns the LAST call's result", r == "hi")
    check("repeat is a factory taking parameter n",
          "n" in repeat.__code__.co_varnames)


# ----------------------------------------------------------------------------
# Section E — a class decorator
# ----------------------------------------------------------------------------

def section_e_class_decorator() -> None:
    banner("E — Class decorators: modifying the class object itself")
    print("A decorator on a 'class' statement receives the CLASS object (not an\n"
          "instance) and returns the class — usually with extra attributes added.\n"
          "Desugar is identical to functions: @add_helpers class C: ... means\n"
          "C = add_helpers(C) (language reference 8.8).\n")

    def add_helpers(cls):
        def describe(self):
            return f"{cls.__name__} instance with {self.__dict__!r}"
        cls.describe = describe
        return cls

    @add_helpers
    class Point:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    p = Point(1, 2)
    print(f"{'expression':<40}{'result'}")
    print("-" * 64)
    print(f"{'hasattr(Point, \"describe\")':<40}{hasattr(Point, 'describe')}")
    print(f"{'\"describe\" in Point.__dict__':<40}{'describe' in Point.__dict__}")
    print(f"{'p.describe()':<40}{p.describe()}")
    print()

    check("the class decorator ADDED 'describe' to the class",
          "describe" in Point.__dict__)
    check("the added method is callable on an instance", hasattr(p, "describe"))
    check("the original __init__ still runs (p.x == 1)", p.x == 1)


# ----------------------------------------------------------------------------
# Section F — stacking order: bottom-up application, nested call
# ----------------------------------------------------------------------------

def section_f_stacking() -> None:
    banner("F — Stacking: @a / @b applies BOTTOM-UP (f = a(b(f)))")
    print("The decorator NEAREST the function is applied first. So\n"
          "    @a\n"
          "    @b\n"
          "    def f(): ...\n"
          "desugars to f = a(b(f)). At CALL time the wrappers nest: a enters,\n"
          "calls b, b enters, calls the body, then they unwind inside-out.\n")

    order: list[str] = []

    def make(name):
        def deco(func):
            def wrapper(*args, **kwargs):
                order.append(f"{name}-in")
                result = func(*args, **kwargs)
                order.append(f"{name}-out")
                return result
            return wrapper
        return deco

    a = make("a")
    b = make("b")

    @a
    @b
    def greet():
        order.append("body")
        return "hi"

    r = greet()
    print(f"{'expression':<34}{'result'}")
    print("-" * 58)
    print(f"{'greet() return value':<34}{r!r}")
    print(f"{'call order (a wraps b wraps body)':<34}{order}")
    print()

    check("at call time the outer wrapper (a) enters FIRST",
          order[0] == "a-in")
    check("call order is a-in, b-in, body, b-out, a-out",
          order == ["a-in", "b-in", "body", "b-out", "a-out"])
    check("the wrapped function still returns 'hi'", r == "hi")


# ----------------------------------------------------------------------------
# Section G — the late-binding-closure trap + the fix
# ----------------------------------------------------------------------------

def section_g_late_binding() -> None:
    banner("G — The late-binding-closure trap (closures bind VARIABLES)")
    print("Closures capture the VARIABLE (a cell pointing at the name), not a\n"
          "frozen VALUE. A list comprehension's loop variable keeps changing, so\n"
          "every lambda built in the loop sees the loop's FINAL value when\n"
          "called later. Fix: bind each value eagerly via a default arg\n"
          "(lambda i=i: i) or functools.partial.\n")

    late = [lambda: i for i in range(3)]           # noqa: B023 (the trap, on purpose)
    fixed = [lambda i=i: i for i in range(3)]      # default binds i at def-time
    via_partial = [partial(lambda i: i, i) for i in range(3)]

    print(f"{'expression':<40}{'result'}")
    print("-" * 64)
    print(f"{'late[0](), late[1](), late[2]()':<40}"
          f"{(late[0](), late[1](), late[2]())}")
    print(f"{'fixed[0](), fixed[1](), fixed[2]()':<40}"
          f"{(fixed[0](), fixed[1](), fixed[2]())}")
    print(f"{'via_partial[0](), [1](), [2]()':<40}"
          f"{(via_partial[0](), via_partial[1](), via_partial[2]())}")
    print()

    check("TRAP: all late lambdas return the loop's FINAL value (2)",
          late[0]() == late[1]() == late[2]() == 2)
    check("FIX (default arg): each lambda returns its own value 0,1,2",
          (fixed[0](), fixed[1](), fixed[2]()) == (0, 1, 2))
    check("FIX (functools.partial): same correct values 0,1,2",
          (via_partial[0](), via_partial[1](), via_partial[2]()) == (0, 1, 2))


# ----------------------------------------------------------------------------
# Section H — functools.lru_cache: memoization + the unhashable pitfall
# ----------------------------------------------------------------------------

def section_h_lru_cache() -> None:
    banner("H — functools.lru_cache: memoization via a cached decorator")
    print("lru_cache(maxsize=None) (a.k.a. functools.cache) memoizes: the FIRST\n"
          "call with given args runs the body; later calls with the SAME args\n"
          "return the cached result (a 'hit') without re-running the body.\n"
          "cache_info() reports (hits, misses, maxsize, currsize).\n")

    body_runs = [0]

    @lru_cache(maxsize=None)
    def fib(n):
        body_runs[0] += 1
        if n < 2:
            return n
        return fib(n - 1) + fib(n - 2)

    first = fib(10)               # builds the cache: 11 misses (fib 0..10)
    info_after_first = fib.cache_info()
    second = fib(10)              # pure cache hit: body does NOT run again
    info_after_second = fib.cache_info()

    # The unhashable-args pitfall: lru_cache keys on the args, so a list (which
    # is unhashable) cannot be cached and raises TypeError.
    raised: str | None = None
    try:
        fib([1, 2])
    except TypeError as exc:
        raised = type(exc).__name__

    print(f"{'expression':<42}{'result'}")
    print("-" * 66)
    print(f"{'fib(10)':<42}{first}")
    print(f"{'body_runs after first fib(10)':<42}{body_runs[0]}")
    print(f"{'cache_info() after first fib(10)':<42}{info_after_first}")
    print(f"{'fib(10) again (== 55)':<42}{second}")
    print(f"{'body_runs after second fib(10)':<42}{body_runs[0]}")
    print(f"{'cache_info() after second fib(10)':<42}{info_after_second}")
    print(f"{'fib([1,2]) raises':<42}{raised}")
    print()

    check("fib(10) == 55", first == 55)
    check("with cache, fib(10) runs the body only 11 times (fib 0..10)",
          body_runs[0] == 11)
    check("the second fib(10) is a cache HIT (body did not run again)",
          body_runs[0] == 11 and info_after_second.hits == info_after_first.hits + 1)
    check("currsize == 11 (one entry per distinct arg)", info_after_first.currsize == 11)
    check("unhashable args (a list) raise TypeError", raised == "TypeError")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("decorators_deep.py — Phase 2 bundle #14.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_desugaring()
    section_b_closures_and_wraps()
    section_c_timing()
    section_d_parametrized()
    section_e_class_decorator()
    section_f_stacking()
    section_g_late_binding()
    section_h_lru_cache()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
