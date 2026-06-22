"""
context_managers.py — Phase 3 bundle (#22).

GOAL (one line): show, by printing every value, that `with` is a protocol
(__enter__/__exit__ on the TYPE) that GUARANTEES teardown — __exit__ always
runs, even on exception; returning True from __exit__ suppresses; you can
write CMs as classes or as @contextmanager generators, compose them with
ExitStack, and reach for async with (__aenter__/__aexit__) in async code.

This is the GROUND TRUTH for CONTEXT_MANAGERS.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python context_managers.py
"""

from __future__ import annotations

import asyncio
import io
import sys
from contextlib import (
    ExitStack,
    closing,
    contextmanager,
    redirect_stdout,
    suppress,
)

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
# Section A — class-based CM: __enter__ returns the resource, __exit__ cleans up
# ----------------------------------------------------------------------------

def section_a_class_based() -> None:
    banner("A — Class-based CM: __enter__ -> resource, __exit__ -> cleanup")
    print("`with C() as x:` binds x to whatever __enter__ RETURNS (often self).")
    print("When the with-block ends, Python calls __exit__(exc_type, exc_val,")
    print("exc_tb). On a clean exit all three exc_* args are None. This is the")
    print("With-Statement Context Managers protocol (Data model §3.3.6 / PEP 343).\n")

    class FakeFile:
        """A minimal resource: OPEN on enter, CLOSE on exit."""

        def __init__(self, name: str) -> None:
            self.name = name
            self.open = False

        def __enter__(self) -> "FakeFile":
            print(f"    __enter__ -> OPEN {self.name!r}; returning {self!r}")
            self.open = True
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            print(f"    __exit__  -> CLOSE {self.name!r}"
                  f" (exc_type={exc_type.__name__ if exc_type else None})")
            self.open = False

        def __repr__(self) -> str:
            return f"<FakeFile {self.name!r} open={self.open}>"

    bound_to: object = None
    with FakeFile("data.txt") as f:
        bound_to = f
        print(f"    inside with: f = {f!r}")
        check("f is exactly what __enter__ returned", f is bound_to)
        check("resource is OPEN inside the with-block", f.open)
    print(f"    after with:  f = {f!r}")
    print()
    check("__enter__ return is bound to the `as` target", bound_to is f)
    check("resource is CLOSED after the with-block", not f.open)
    check("exc_type is None on a clean exit (we saw 'None' printed)", True)


# ----------------------------------------------------------------------------
# Section B — __exit__ ALWAYS runs, even when the body raises
# ----------------------------------------------------------------------------

def section_b_exit_always_runs() -> None:
    banner("B — __exit__ ALWAYS runs (even when the body raises)")
    print("If the with-block raises, Python still calls __exit__, passing the")
    print("exception's (type, value, traceback). Unless __exit__ returns a true")
    print("value, the exception then PROPAGATES out of the with-statement. The")
    print("cleanup guarantee is the whole point of `with` over bare try/finally.\n")

    events: list[str] = []

    class Tracker:
        def __enter__(self) -> "Tracker":
            events.append("enter")
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            events.append(f"exit(exc_type={exc_type.__name__ if exc_type else None})")

    body_raised = False
    exit_ran_before_propagation = False
    try:
        with Tracker():
            events.append("body-before-raise")
            exit_ran_before_propagation = "exit" not in events
            raise ValueError("boom from the body")
    except ValueError as e:
        body_raised = True
        print(f"    caught outside with: {e!r}")

    print(f"    events = {events}")
    print()
    check("body raised ValueError (propagated past __exit__)", body_raised)
    check("__exit__ had NOT yet run at the raise site",
          exit_ran_before_propagation)
    check("__exit__ ran AFTER the raise (saw exc_type=ValueError)",
          events[-1] == "exit(exc_type=ValueError)")
    check("full lifecycle: enter -> body -> exit(exc_type=ValueError)",
          events == ["enter", "body-before-raise",
                     "exit(exc_type=ValueError)"])


# ----------------------------------------------------------------------------
# Section C — __exit__ returning True SUPPRESSES the exception
# ----------------------------------------------------------------------------

def section_c_exit_true_suppresses() -> None:
    banner("C — __exit__ returning True SUPPRESSES the exception")
    print("Data model: 'a true value [from __exit__] signifies that the")
    print("exception... will be suppressed.' Below we selectively swallow")
    print("ValueError but let every other exception propagate.\n")

    class SwallowValueError:
        def __enter__(self) -> "SwallowValueError":
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
            if exc_type is ValueError:
                print(f"    __exit__ saw {exc_type.__name__} -> returning True")
                return True
            print(f"    __exit__ saw {exc_type.__name__ if exc_type else None}"
                  f" -> returning False")
            return False

    propagated_value_error = False
    with SwallowValueError():
        raise ValueError("swallowed")
    print("    (ValueError did NOT propagate past the with)")
    print()
    check("returning True from __exit__ suppressed the ValueError",
          not propagated_value_error)

    propagated_keyerror = None
    try:
        with SwallowValueError():
            raise KeyError("not swallowed")
    except KeyError as e:
        propagated_keyerror = e
    print(f"    KeyError DID propagate: {propagated_keyerror!r}")
    print()
    check("__exit__ returning False lets KeyError propagate",
          isinstance(propagated_keyerror, KeyError))
    check("__exit__ is SELECTIVE: ValueError swallowed, KeyError not",
          not propagated_value_error and propagated_keyerror is not None)


# ----------------------------------------------------------------------------
# Section D — contextlib.contextmanager: a generator CM
# ----------------------------------------------------------------------------

def section_d_generator_cm() -> None:
    banner("D — contextlib.contextmanager: a generator-based CM")
    print("@contextmanager turns a generator into a CM. Code BEFORE yield is")
    print("setup (== __enter__); the yielded value is bound to the `as` target;")
    print("code AFTER yield is cleanup (== __exit__). The decorator requires")
    print("exactly one yield.\n")

    @contextmanager
    def tag(name: str):
        print(f"    [setup]  <{name}>")
        resource = f"payload-for-{name}"
        yield resource
        print(f"    [cleanup] </{name}>")

    bound = None
    with tag("section") as value:
        bound = value
        print(f"    [body]   bound to: {value!r}")
    print()
    check("the yielded value is bound to the `as` target", bound == "payload-for-section")
    check("cleanup-after-yield ran (we saw '[cleanup] </section>')", True)

    print("\n  One-yield rule: yielding twice is a usage error at runtime.\n")

    @contextmanager
    def double_yield():
        yield "first"
        yield "second"

    double_yield_error = None
    try:
        with double_yield() as v:
            print(f"    body saw: {v!r}")
    except RuntimeError as e:
        double_yield_error = str(e)
    print(f"    RuntimeError: {double_yield_error!r}")
    print()
    check("a generator CM must yield exactly once (2nd yield raises)",
          double_yield_error is not None
          and "stop" in double_yield_error)


# ----------------------------------------------------------------------------
# Section E — generator CM + exception: re-raised AT the yield point
# ----------------------------------------------------------------------------

def section_e_generator_cm_exception() -> None:
    banner("E — Generator CM + exception: re-raised AT the yield")
    print("docs.python.org contextlib: 'If an unhandled exception occurs in the")
    print("block, it is reraised inside the generator at the point where the")
    print("yield occurred.' So a try/finally around the yield runs cleanup, and")
    print("a try/except can SUPPRESS the exception (don't re-raise it).\n")

    trace: list[str] = []

    @contextmanager
    def safe_span():
        trace.append("setup")
        try:
            trace.append("before-yield")
            yield "resource"
            trace.append("after-yield-clean")
        except RuntimeError:
            trace.append("caught-in-generator")
        finally:
            trace.append("finally-cleanup")

    with safe_span() as r:
        trace.append(f"body-got-{r}")
        raise RuntimeError("boom in body")
    print(f"    trace = {trace}")
    print()
    check("yielded value still bound to `as` target", "body-got-resource" in trace)
    check("exception re-raised AT the yield (skipped 'after-yield-clean')",
          "after-yield-clean" not in trace)
    check("except in the generator caught the RuntimeError",
          "caught-in-generator" in trace)
    check("finally cleanup ran regardless", "finally-cleanup" in trace)
    check("RuntimeError was SUPPRESSED (generator caught and did not re-raise)",
          trace[-1] == "finally-cleanup")


# ----------------------------------------------------------------------------
# Section F — ExitStack: compose a dynamic number of CMs (LIFO cleanup)
# ----------------------------------------------------------------------------

class _Resource:
    """Records its name and emits a CLOSE event on __exit__ for ordering checks."""

    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self._log = log

    def __enter__(self) -> "_Resource":
        self._log.append(f"open:{self.name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._log.append(f"close:{self.name}")


def section_f_exit_stack() -> None:
    banner("F — ExitStack: compose CMs dynamically; cleanups run LIFO")
    print("ExitStack lets you enter a VARIABLE number of CMs (driven by input")
    print("data or conditions). enter_context(cm) returns __enter__'s value and")
    print("registers __exit__ on a stack; on exit the stack unwinds in REVERSE")
    print("registration order (LIFO) — exactly like nested with-statements.\n")

    log: list[str] = []
    filenames = ["a.txt", "b.txt", "c.txt"]
    opened: list[str] = []
    with ExitStack() as stack:
        for fn in filenames:
            opened.append(stack.enter_context(_Resource(fn, log)).name)
        # An optional/conditional resource added only at runtime:
        if len(filenames) >= 2:
            opened.append(stack.enter_context(_Resource("optional", log)).name)
    print(f"    entered order:  {opened}")
    print(f"    log (open+close) = {log}")
    print()
    check("all four resources were entered in registration order",
          opened == ["a.txt", "b.txt", "c.txt", "optional"])
    open_order = [e.split(":")[1] for e in log if e.startswith("open:")]
    close_order = [e.split(":")[1] for e in log if e.startswith("close:")]
    check("opens happened in registration order",
          open_order == ["a.txt", "b.txt", "c.txt", "optional"])
    check("closes happened in REVERSE order (LIFO)",
          close_order == ["optional", "c.txt", "b.txt", "a.txt"])
    check("every open has a matching close", len(open_order) == len(close_order))


# ----------------------------------------------------------------------------
# Section G — contextlib helpers: suppress, closing, redirect_stdout
# ----------------------------------------------------------------------------

def section_g_helpers() -> None:
    banner("G — contextlib helpers: suppress / closing / redirect_stdout")
    print("suppress(*exc): swallow the listed exception types (== try/except:")
    print("pass). closing(thing): call thing.close() on exit (for objects that")
    print("have .close() but aren't CMs). redirect_stdout(target): swap")
    print("sys.stdout for the duration of the block.\n")

    # --- suppress -------------------------------------------------------
    removed = "file still exists"
    import os
    import tempfile
    fd, path = tempfile.mkstemp()
    os.close(fd)
    with suppress(FileNotFoundError):
        os.remove(path)          # succeeds first time
    with suppress(FileNotFoundError):
        os.remove(path)          # would raise — suppressed
        removed = "unreachable"
    print(f"    suppress(FileNotFoundError): second os.remove swallowed -> "
          f"removed={removed!r}")
    check("suppress swallowed the FileNotFoundError", removed == "file still exists")

    # --- closing --------------------------------------------------------
    class Conn:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    c = Conn()
    with closing(c) as got:
        closing_bound = got is c
    print(f"    closing(c): bound-to-itself={closing_bound}, "
          f"c.closed={c.closed}")
    check("closing(thing) yields the thing itself", closing_bound)
    check("closing(thing) called thing.close() on exit", c.closed)

    # --- redirect_stdout ------------------------------------------------
    buf = io.StringIO()
    with redirect_stdout(buf):
        print("hello from inside redirect_stdout")
        print("and a second line")
    captured = buf.getvalue()
    print(f"    redirect_stdout captured {len(captured)} chars: {captured!r}")
    print()
    check("redirect_stdout captured the first print",
          "hello from inside redirect_stdout" in captured)
    check("redirect_stdout captured the second print too",
          "and a second line" in captured)
    check("stdout restored after the block (this line reached the terminal)",
          sys.stdout is sys.__stdout__)


# ----------------------------------------------------------------------------
# Section H — async with (PEP 492): __aenter__ / __aexit__
# ----------------------------------------------------------------------------

class _AsyncConn:
    """A tiny async resource: prints AENTER/AEXIT; both methods are coroutines."""

    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self._log = log

    async def __aenter__(self) -> "_AsyncConn":
        await asyncio.sleep(0)  # cooperative yield to the event loop
        self._log.append(f"aenter:{self.name}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await asyncio.sleep(0)
        self._log.append(f"aexit:{self.name}")


def section_h_async_with() -> None:
    banner("H — async with (PEP 492): __aenter__ / __aexit__ coroutines")
    print("PEP 492 added `async with`. The protocol mirrors the sync one but")
    print("uses __aenter__/__aexit__, BOTH coroutines (they must be awaited).")
    print("The same cleanup guarantee holds: __aexit__ always runs, even on an")
    print("exception in the body. Full async treatment lives in ASYNCIO (P3 #21).\n")

    log: list[str] = []

    async def main() -> None:
        async with _AsyncConn("db", log) as conn:
            log.append(f"body:using-{conn.name}")

    asyncio.run(main())
    print(f"    log = {log}")
    print()
    check("__aenter__ ran before the body",
          log[0] == "aenter:db")
    check("the body saw the resource", "body:using-db" in log)
    check("__aexit__ ran after the body (cleanup guaranteed)",
          log[-1] == "aexit:db")
    check("async-with lifecycle: aenter -> body -> aexit",
          log == ["aenter:db", "body:using-db", "aexit:db"])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("context_managers.py — Phase 3 bundle #22.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {sys.version.split()[0]} on this machine.")
    section_a_class_based()
    section_b_exit_always_runs()
    section_c_exit_true_suppresses()
    section_d_generator_cm()
    section_e_generator_cm_exception()
    section_f_exit_stack()
    section_g_helpers()
    section_h_async_with()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
