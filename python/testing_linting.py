"""
testing_linting.py - Phase 4 bundle #28.

GOAL (one line): show, by running real tools on tiny inline samples, how pytest
fixtures/parametrize/monkeypatch give composable tests, how ruff lints + formats,
and how mypy type-checks - the red->green loop that keeps code correct.

This is the GROUND TRUTH for TESTING_LINTING.md. Every value below is printed by
this file: pytest is invoked programmatically (pytest.main captured), ruff and
mypy via subprocess, all on tiny sample files written to a /tmp scratch dir.
Change it -> re-run -> re-paste. Never hand-compute.

Run:
    uv run python testing_linting.py
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

BANNER = "=" * 70
SCRATCH = Path(tempfile.mkdtemp(prefix="bundle28_"))


# ----------------------------------------------------------------------------
# pretty printers + helpers
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


def _write(name: str, source: str) -> Path:
    """Write a tiny source file under the scratch dir; return its path."""
    p = SCRATCH / name
    p.write_text(source)
    return p


def _normalize(out: str) -> str:
    """Make captured output byte-reproducible: hide the random temp dir and any
    sub-second durations (pytest timing varies run-to-run)."""
    out = out.replace(str(SCRATCH), "<tmpdir>")
    out = re.sub(r"in \d+\.\d+s", "in <duration>s", out)
    return out.rstrip()


def _run_pytest(path: Path, *, extra_path: Path | None = None) -> tuple[int, str]:
    """Invoke pytest.main on a test file, capturing stdout. Return (exit, out)."""
    buf = io.StringIO()
    old = sys.stdout
    if extra_path is not None:
        sys.path.insert(0, str(extra_path))
    sys.stdout = buf
    try:
        code = pytest.main(
            ["-q", "-p", "no:cacheprovider", "--capture=no", str(path)]
        )
    finally:
        sys.stdout = old
        if extra_path is not None and str(extra_path) in sys.path:
            sys.path.remove(str(extra_path))
    return int(code), _normalize(buf.getvalue())


def _run_tool(cmd: list[str]) -> tuple[int, str]:
    """Run a subprocess (ruff/mypy); return (returncode, combined output)."""
    r = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    return r.returncode, _normalize(r.stdout + r.stderr)


# ----------------------------------------------------------------------------
# Section A - pytest basics: test functions and exit codes
# ----------------------------------------------------------------------------

def section_a_pytest_basics() -> None:
    banner("A - pytest basics: test functions and exit codes")
    print("pytest discovers functions named test_*. Each runs its asserts;")
    print("exit code 0 = all passed (ExitCode.OK), 1 = some failed")
    print("(ExitCode.TESTS_FAILED). Below: pytest.main on a passing then a")
    print("deliberately-failing test file.\n")

    passing = _write("test_pass.py",
                     "def test_add():\n    assert 1 + 1 == 2\n"
                     "def test_upper():\n    assert 'hi'.upper() == 'HI'\n")
    code, out = _run_pytest(passing)
    print(f"--- pytest on {passing.name} (2 passing tests) ---")
    print(out)
    print()
    check("2 passing tests -> exit code 0 (ExitCode.OK)", code == 0)
    check("output reports '2 passed'", "2 passed" in out)

    failing = _write("test_fail.py",
                     "def test_broken():\n    assert 1 + 1 == 3\n")
    code2, out2 = _run_pytest(failing)
    print(f"--- pytest on {failing.name} (1 deliberately failing test) ---")
    print(out2)
    print()
    check("1 failing test -> exit code 1 (ExitCode.TESTS_FAILED)", code2 == 1)
    check("output reports '1 failed'", "1 failed" in out2)


# ----------------------------------------------------------------------------
# Section B - fixtures: injection by name
# ----------------------------------------------------------------------------

def section_b_fixtures() -> None:
    banner("B - Fixtures: dependency injection by name")
    print("A @pytest.fixture function is injected into any test that lists its")
    print("NAME as a parameter - no imports, no wiring. pytest sees 'sample' in")
    print("the signature, finds the fixture, calls it, and passes the return")
    print("value in.\n")

    fix = _write("test_fix.py",
                 "import pytest\n"
                 "@pytest.fixture\n"
                 "def sample():\n    return [1, 2, 3]\n"
                 "def test_sample(sample):\n"
                 "    assert sample == [1, 2, 3]\n"
                 "    assert len(sample) == 3\n")
    code, out = _run_pytest(fix)
    print(f"--- pytest on {fix.name} ---")
    print(out)
    print()
    check("fixture 'sample' injected by name -> exit code 0", code == 0)
    check("the fixture value [1,2,3] flowed into the test",
          "1 passed" in out)


# ----------------------------------------------------------------------------
# Section C - @pytest.mark.parametrize: one test per row
# ----------------------------------------------------------------------------

def section_c_parametrize() -> None:
    banner("C - @pytest.mark.parametrize: one run per data row")
    print("@parametrize(argnames, argvalues) runs the test ONCE per row in")
    print("argvalues, injecting each row as arguments. 4 rows -> 4 test runs.\n")

    rows = [(1, 1), (2, 4), (3, 9), (4, 16)]
    src = ("import pytest\n"
           "@pytest.mark.parametrize('x,expected', "
           f"{rows!r})\n"
           "def test_square(x, expected):\n"
           "    assert x * x == expected\n")
    pm = _write("test_pm.py", src)
    code, out = _run_pytest(pm)
    print(f"--- pytest on {pm.name} ({len(rows)} param rows) ---")
    print(out)
    print()
    check("parametrized test ran once per row -> exit code 0", code == 0)
    check(f"collected count == number of param rows ({len(rows)})",
          f"{len(rows)} passed" in out)


# ----------------------------------------------------------------------------
# Section D - monkeypatch: temporary patches, auto-restored
# ----------------------------------------------------------------------------

def section_d_monkeypatch() -> None:
    banner("D - monkeypatch: temporary attribute/env patches, auto-restored")
    print("The monkeypatch fixture sets attrs/dict-items/env-vars for the test")
    print("duration, then UNDOES them at teardown. Below, test 1 patches an env")
    print("var and math.pi; test 2 asserts both are gone - proving teardown.\n")

    mp = _write("test_mp.py",
                "import os, math\n"
                "def test_patch(monkeypatch):\n"
                "    monkeypatch.setenv('BUNDLE28_FLAG', 'on')\n"
                "    monkeypatch.setattr(math, 'pi', 3.0)\n"
                "    assert os.environ['BUNDLE28_FLAG'] == 'on'\n"
                "    assert math.pi == 3.0\n"
                "def test_restored():\n"
                "    assert 'BUNDLE28_FLAG' not in os.environ\n"
                "    assert round(math.pi, 6) == 3.141593\n")
    code, out = _run_pytest(mp)
    print(f"--- pytest on {mp.name} (patch + restore) ---")
    print(out)
    print()
    check("monkeypatch took effect during test 1 -> exit code 0", code == 0)
    check("both tests passed (patch auto-restored before test 2)",
          "2 passed" in out)


# ----------------------------------------------------------------------------
# Section E - tmp_path & capsys: built-in fixtures
# ----------------------------------------------------------------------------

def section_e_tmp_path_capsys() -> None:
    banner("E - tmp_path & capsys: built-in fixtures")
    print("tmp_path yields a fresh pathlib.Path temp dir (unique per test).")
    print("capsys captures stdout/stderr written during the test via")
    print("capsys.readouterr(). Both are built-in - no plugin needed.\n")

    tp = _write("test_tp.py",
                "def test_write(tmp_path):\n"
                "    f = tmp_path / 'data.txt'\n"
                "    f.write_text('hello')\n"
                "    assert f.read_text() == 'hello'\n"
                "def test_print(capsys):\n"
                "    print('captured!')\n"
                "    out, _ = capsys.readouterr()\n"
                "    assert out == 'captured!' + chr(10)\n")
    code, out = _run_pytest(tp)
    print(f"--- pytest on {tp.name} (tmp_path + capsys) ---")
    print(out)
    print()
    check("tmp_path file round-trip + capsys capture -> exit code 0", code == 0)
    check("both built-in fixture tests passed", "2 passed" in out)


# ----------------------------------------------------------------------------
# Section F - ruff: lint + format (replaces flake8 + isort + black)
# ----------------------------------------------------------------------------

def section_f_ruff() -> None:
    banner("F - ruff: lint + format (replaces flake8 + isort + black)")
    print("ruff is ONE Rust binary that lints (rules like F401 unused import)")
    print("AND formats (Black-compatible). It replaces flake8, isort, black,")
    print("pydocstyle and more. Below: ruff check flags an unused import;\n"
          "ruff format --check flags code that needs reformatting.\n")

    bad = _write("bad.py", "import os\nx = 1\n")
    code, out = _run_tool(["ruff", "check", str(bad)])
    print(f"--- ruff check on {bad.name} (unused import) ---")
    print(out)
    print()
    check("ruff flags unused import -> exit code 1", code == 1)
    check("ruff reports rule F401 'imported but unused'",
          "F401" in out and "unused" in out)

    ugly = _write("ugly.py", "x=1\n")
    code2, out2 = _run_tool(["ruff", "format", "--check", str(ugly)])
    print(f"--- ruff format --check on {ugly.name} (needs formatting) ---")
    print(out2)
    print()
    check("ruff format flags unformatted code -> exit code 1", code2 == 1)
    check("ruff format reports 'Would reformat'", "Would reformat" in out2)


# ----------------------------------------------------------------------------
# Section G - mypy: static type checking
# ----------------------------------------------------------------------------

def section_g_mypy() -> None:
    banner("G - mypy: static type checking (catches type errors before runtime)")
    print("mypy reads your type annotations and reports type errors WITHOUT")
    print("running the code. Below: assigning a str to an int variable is an")
    print("error (exit 1); the correct annotation passes (exit 0, 'Success').\n")

    cache = SCRATCH / ".mypy_cache"
    bad = _write("bad_typed.py", 'x: int = "hello"\n')
    code, out = _run_tool(
        ["mypy", "--cache-dir", str(cache), "--no-incremental", str(bad)]
    )
    print(f"--- mypy on {bad.name} (str assigned to int) ---")
    print(out)
    print()
    check("mypy flags type error -> exit code 1", code == 1)
    check("mypy reports 'error:' (Incompatible types)", "error:" in out)

    good = _write("good_typed.py", "x: int = 42\nprint(x)\n")
    code2, out2 = _run_tool(
        ["mypy", "--cache-dir", str(cache), "--no-incremental", str(good)]
    )
    print(f"--- mypy on {good.name} (correct) ---")
    print(out2)
    print()
    check("mypy passes correctly-typed code -> exit code 0", code2 == 0)
    check("mypy reports 'Success'", "Success" in out2)


# ----------------------------------------------------------------------------
# Section H - coverage.py & the red->green->refactor loop
# ----------------------------------------------------------------------------

def section_h_coverage_red_green() -> None:
    banner("H - coverage.py & the red->green->refactor loop")
    print("coverage.py measures which lines/branches your tests EXECUTE; the")
    print("pytest-cov plugin wires it into pytest (--cov). The goal is")
    print("MEANINGFUL coverage, not 100%. The discipline that drives it is the")
    print("red->green->refactor loop, demonstrated live below:\n"
          "  1. RED   - write a test for a buggy impl; watch it fail.\n"
          "  2. GREEN - fix the impl; watch the same test pass.\n"
          "  3. REFACTOR - clean up with the test as a safety net.\n")

    impl = _write("impl.py", "def square(x):\n    return x + x  # BUG\n")
    test = _write("test_impl.py",
                  "from impl import square\n"
                  "def test_square():\n    assert square(4) == 16\n")
    red_code, red_out = _run_pytest(test, extra_path=SCRATCH)
    print(f"--- RED: {impl.name} returns x+x (square(4)==8, not 16) ---")
    print(red_out)
    print()
    check("RED: buggy impl -> test fails (exit code 1)", red_code == 1)

    impl.write_text("def square(x):\n    return x * x  # FIXED\n")
    sys.modules.pop("impl", None)
    sys.modules.pop("test_impl", None)
    green_code, green_out = _run_pytest(test, extra_path=SCRATCH)
    print(f"--- GREEN: {impl.name} fixed to x*x (square(4)==16) ---")
    print(green_out)
    print()
    check("GREEN: fixed impl -> same test passes (exit code 0)",
          green_code == 0)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("testing_linting.py - Phase 4 bundle #28.\n"
          "Every value below is computed by this file (pytest/ruff/mypy invoked"
          " on\ntiny inline samples in a /tmp scratch dir); the .md guide pastes"
          " it verbatim.\nNothing is hand-computed.\n"
          f"Python {sys.version.split()[0]} on this machine. "
          f"Scratch: {SCRATCH}")
    section_a_pytest_basics()
    section_b_fixtures()
    section_c_parametrize()
    section_d_monkeypatch()
    section_e_tmp_path_capsys()
    section_f_ruff()
    section_g_mypy()
    section_h_coverage_red_green()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
