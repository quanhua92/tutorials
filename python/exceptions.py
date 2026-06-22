"""
exceptions.py — Bundle #8 (Phase 1).

GOAL (one line): show, by printing every value, the full lifecycle of a
try/except/else/finally statement, the exception class hierarchy, exception
chaining, custom exceptions, and the EAFP vs LBYL philosophy.

This is the GROUND TRUTH for EXCEPTIONS.md. Every number, table, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

Run:
    uv run python exceptions.py
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
# Section A — try/except/else/finally phase ordering (incl. return-in-try)
# ----------------------------------------------------------------------------

def section_a_phase_ordering() -> None:
    banner("A — try/except/else/finally phase ordering")
    print("A try statement has up to four clauses. The rules (Language")
    print("Reference 8.4): the try suite runs first; if it raises, the first")
    print("matching except runs; else runs ONLY when try left with no")
    print("exception (and no return/break/continue); finally ALWAYS runs,")
    print("even on return/break/continue or an unhandled exception.\n")

    def case_no_exception() -> list[str]:
        phases: list[str] = []
        try:
            phases.append("try")
        except ValueError:
            phases.append("except")
        else:
            phases.append("else")
        finally:
            phases.append("finally")
        return phases

    def case_caught() -> list[str]:
        phases: list[str] = []
        try:
            phases.append("try")
            raise ValueError("boom")
        except ValueError:
            phases.append("except")
        else:
            phases.append("else")
        finally:
            phases.append("finally")
        return phases

    print(f"{'scenario':<34}{'phase order'}")
    print("-" * 60)
    print(f"{'no exception raised':<34}{' -> '.join(case_no_exception())}")
    print(f"{'ValueError raised and caught':<34}{' -> '.join(case_caught())}")
    print()

    check("else runs only when no exception",
          case_no_exception() == ["try", "else", "finally"])
    check("else is skipped when an exception is caught",
          case_caught() == ["try", "except", "finally"])

    # finally ALWAYS runs — even when try contains a return.
    print("finally runs even when try contains a return:\n")

    def finally_runs_on_return() -> str:
        try:
            return "from-try"
        finally:
            print("  (finally ran before the return took effect)")

    result = finally_runs_on_return()
    print(f"  caller received: {result!r}")
    print()
    check("finally runs even when try returns", result == "from-try")

    # A return IN finally overrides try's return value.
    print("A return INSIDE finally overrides try's return value:\n")

    def return_in_finally() -> str:
        try:
            return "from-try"
        finally:
            return "from-finally"

    overridden = return_in_finally()
    print(f"  caller received: {overridden!r}  (try said 'from-try')")
    print()
    check("return in finally overrides return in try",
          overridden == "from-finally")


# ----------------------------------------------------------------------------
# Section B — catching specifics & the bare-except trap
# ----------------------------------------------------------------------------

def section_b_catching_specifics() -> None:
    banner("B — Catching specifics & the bare-except trap")
    print("Match a specific type, a tuple of types, or Exception (broad). A")
    print("class in an except clause matches the class AND its subclasses.")
    print("The trap: bare `except:` (identical to `except BaseException`) also")
    print("catches SystemExit and KeyboardInterrupt — which you usually want")
    print("to let propagate. We simulate a Ctrl-C with a BaseException")
    print("subclass so the demo stays deterministic.\n")

    class FakeInterrupt(BaseException):
        """Stands in for KeyboardInterrupt without actually interrupting."""

    try:
        raise ValueError("bad value")
    except ValueError as e:
        print(f"  except ValueError caught: {e!r}")
    check("except ValueError catches a ValueError", True)

    try:
        raise KeyError("missing")
    except (KeyError, IndexError) as e:
        print(f"  except (KeyError, IndexError) caught: {type(e).__name__}")
    check("except (KeyError, IndexError) catches a KeyError", True)

    caught_by_exception = False
    try:
        try:
            raise FakeInterrupt()
        except Exception:
            caught_by_exception = True
    except FakeInterrupt:
        print("  FakeInterrupt was NOT caught by `except Exception`")
    check("except Exception does NOT catch a BaseException subclass",
          not caught_by_exception)

    trapped = False
    try:
        raise FakeInterrupt()
    except BaseException:  # noqa: BLE001 - intentionally showing the trap
        trapped = True
    print("  `except BaseException` DID catch the fake interrupt (the trap)")
    check("bare-except equivalent catches BaseException subclasses", trapped)
    print()
    print("  => Prefer `except Exception:` for a broad catch; reserve bare")
    print("     `except:` / `except BaseException` for top-level log-and-reraise.")


# ----------------------------------------------------------------------------
# Section C — the exception hierarchy: BaseException vs Exception
# ----------------------------------------------------------------------------

def section_c_hierarchy() -> None:
    banner("C — The exception hierarchy: BaseException vs Exception")
    print("Every exception subclasses BaseException. Exception is the base of")
    print("all NON-system-exiting exceptions. KeyboardInterrupt, SystemExit")
    print("and GeneratorExit branch directly off BaseException — on purpose,")
    print("so `except Exception` can't swallow a Ctrl-C or sys.exit().\n")

    print(f"{'expression':<42}{'result'}")
    print("-" * 56)
    rows = [
        ("issubclass(ValueError, Exception)", issubclass(ValueError, Exception)),
        ("issubclass(Exception, BaseException)", issubclass(Exception, BaseException)),
        ("issubclass(ValueError, BaseException)", issubclass(ValueError, BaseException)),
        ("issubclass(KeyboardInterrupt, Exception)", issubclass(KeyboardInterrupt, Exception)),
        ("issubclass(KeyboardInterrupt, BaseException)", issubclass(KeyboardInterrupt, BaseException)),
        ("issubclass(SystemExit, Exception)", issubclass(SystemExit, Exception)),
        ("issubclass(SystemExit, BaseException)", issubclass(SystemExit, BaseException)),
        ("issubclass(ZeroDivisionError, ArithmeticError)", issubclass(ZeroDivisionError, ArithmeticError)),
        ("issubclass(KeyError, LookupError)", issubclass(KeyError, LookupError)),
        ("issubclass(ZeroDivisionError, Exception)", issubclass(ZeroDivisionError, Exception)),
    ]
    for label, value in rows:
        print(f"{label:<42}{value}")
    print()

    check("ValueError is an Exception", issubclass(ValueError, Exception))
    check("Exception is a BaseException", issubclass(Exception, BaseException))
    check("KeyboardInterrupt is NOT an Exception (it is BaseException)",
          not issubclass(KeyboardInterrupt, Exception)
          and issubclass(KeyboardInterrupt, BaseException))
    check("SystemExit is NOT an Exception (it is BaseException)",
          not issubclass(SystemExit, Exception)
          and issubclass(SystemExit, BaseException))
    check("ZeroDivisionError -> ArithmeticError -> Exception chain",
          issubclass(ZeroDivisionError, ArithmeticError)
          and issubclass(ArithmeticError, Exception))

    print(f"  ValueError.__mro__        = {ValueError.__mro__}")
    print(f"  KeyboardInterrupt.__mro__ = {KeyboardInterrupt.__mro__}")
    print(f"  SystemExit.__mro__        = {SystemExit.__mro__}")


# ----------------------------------------------------------------------------
# Section D — exception chaining (__cause__/__context__) & re-raise
# ----------------------------------------------------------------------------

def section_d_chaining_and_reraise() -> None:
    banner("D — Exception chaining (__cause__/__context__) & re-raise")
    print("Explicit chaining: `raise B from A` sets B.__cause__ = A. Implicit")
    print("chaining: raising ANY new exception inside an except/finally block")
    print("sets new.__context__ to the exception being handled. Bare `raise`")
    print("re-raises the active exception unchanged.\n")

    original = ValueError("the root cause")
    try:
        raise RuntimeError("the surface error") from original
    except RuntimeError as e:
        print("  raised: RuntimeError from ValueError")
        print(f"    e.__cause__           = {e.__cause__!r}")
        print(f"    e.__context__         = {e.__context__!r}")
        print(f"    e.__suppress_context__ = {e.__suppress_context__}")
    check("'raise ... from' sets __cause__", True)

    explicit_cause: object = None
    explicit_suppress: object = None
    try:
        raise RuntimeError("x") from original
    except RuntimeError as e:
        explicit_cause = e.__cause__
        explicit_suppress = e.__suppress_context__
    check("explicit __cause__ is the original exception",
          explicit_cause is original)
    check("'from' also sets __suppress_context__ = True",
          explicit_suppress is True)

    implicit_context: object = None
    implicit_cause: object = None
    try:
        try:
            raise KeyError("missing key")
        except KeyError:
            raise RuntimeError("while handling the KeyError")
    except RuntimeError as e:
        implicit_context = e.__context__
        implicit_cause = e.__cause__
    print()
    print("  raised: RuntimeError inside a KeyError handler (no 'from')")
    print(f"    e.__cause__   = {implicit_cause!r}")
    print(f"    e.__context__ = {implicit_context!r}")
    check("implicit chaining sets __context__ to the handled exception",
          isinstance(implicit_context, KeyError))
    check("__cause__ is None when no explicit 'from'", implicit_cause is None)

    re_raised: object = None
    try:
        try:
            raise ValueError("original message")
        except ValueError:
            raise
    except ValueError as e:
        re_raised = e
    print()
    print(f"  bare `raise` re-raised: {re_raised!r}")
    check("bare raise re-raises the active exception",
          isinstance(re_raised, ValueError)
          and str(re_raised) == "original message")


# ----------------------------------------------------------------------------
# Section E — custom exception hierarchy
# ----------------------------------------------------------------------------

def section_e_custom_exceptions() -> None:
    banner("E — Custom exception hierarchy")
    print("Derive app exceptions from Exception (NOT BaseException). A custom")
    print("error can have subclasses, multiple inheritance, and a custom")
    print("__str__ for friendlier messages.\n")

    class AppError(Exception):
        """Base for all application errors."""

    class ValidationError(AppError, ValueError):
        def __init__(self, field: str, reason: str) -> None:
            self.field = field
            self.reason = reason
            super().__init__(f"{field}: {reason}")

        def __str__(self) -> str:
            return f"[{self.field}] invalid: {self.reason}"

    err = ValidationError("email", "missing @")
    print("  ValidationError('email', 'missing @'):")
    print(f"    type(err).__mro__ = {type(err).__mro__}")
    print(f"    str(err)          = {str(err)!r}")
    print(f"    err.args          = {err.args}")
    print(f"    err.field         = {err.field!r}")
    print(f"    err.reason        = {err.reason!r}")
    print()

    check("ValidationError is an AppError", isinstance(err, AppError))
    check("ValidationError is a ValueError (multiple inheritance)",
          isinstance(err, ValueError))
    check("ValidationError is an Exception", isinstance(err, Exception))
    check("custom __str__ is used",
          str(err) == "[email] invalid: missing @")

    caught_as_app: object = None
    try:
        raise ValidationError("email", "missing @")
    except AppError as e:
        caught_as_app = e
    check("except AppError catches the subclass", isinstance(caught_as_app, AppError))

    caught_as_value: object = None
    try:
        raise ValidationError("age", "negative")
    except ValueError as e:
        caught_as_value = e
    check("except ValueError also catches it (2nd base class)",
          isinstance(caught_as_value, ValidationError))
    print(f"  caught as AppError:   {caught_as_app}")
    print(f"  caught as ValueError: {caught_as_value}")


# ----------------------------------------------------------------------------
# Section F — EAFP (try first) vs LBYL (check first)
# ----------------------------------------------------------------------------

def section_f_eafp_vs_lbyl() -> None:
    banner("F — EAFP (try first) vs LBYL (check first)")
    print("EAFP = 'Easier to Ask Forgiveness than Permission' (try the op,")
    print("catch the error). LBYL = 'Look Before You Leap' (check first).")
    print("EAFP is idiomatic Python and avoids TOCTOU races: between an LBYL")
    print("check and the use, the state can change.\n")

    d = {"a": 1}

    def eafp(key: str) -> str:
        try:
            return f"EAFP got {d[key]!r}"
        except KeyError:
            return "EAFP: key absent"

    def lbyl(key: str) -> str:
        if key in d:
            return f"LBYL got {d[key]!r}"
        return "LBYL: key absent"

    print(f"  d = {d}")
    print(f"  eafp('a') = {eafp('a')}")
    print(f"  eafp('x') = {eafp('x')}")
    print(f"  lbyl('a') = {lbyl('a')}")
    print(f"  lbyl('x') = {lbyl('x')}")
    print()
    check("EAFP returns the value when key present", eafp("a") == "EAFP got 1")
    check("EAFP handles absent key via except KeyError",
          eafp("x") == "EAFP: key absent")
    check("LBYL matches EAFP for present key", lbyl("a") == "LBYL got 1")
    check("LBYL matches EAFP for absent key", lbyl("x") == "LBYL: key absent")

    print("  finally is manual cleanup; `with` (context managers) is the")
    print("  structured way to guarantee cleanup.")
    print("  -> see CONTEXT_MANAGERS (Phase 3) for the with-statement protocol.")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("exceptions.py — Phase 1 bundle #8.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_phase_ordering()
    section_b_catching_specifics()
    section_c_hierarchy()
    section_d_chaining_and_reraise()
    section_e_custom_exceptions()
    section_f_eafp_vs_lbyl()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
