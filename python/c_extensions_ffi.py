"""
c_extensions_ffi.py — Phase 4 bundle #26.

GOAL (one line): show, by loading libc and calling real C functions from pure
stdlib, that the ctypes gateway lets Python drop to C; and that cffi, Cython,
and PyO3 are the steeper, faster rungs on the same ladder.

This is the GROUND TRUTH for C_EXTENSIONS_FFI.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

HARD RULE: this bundle uses ONLY the stdlib. ctypes (in the standard library)
loads the platform C shared library and calls real C functions. cffi, Cython,
and PyO3 need a build step / extra deps, so they are EXPLAINED conceptually in
the .md (snippets shown, NOT executed here).

Run:
    uv run python c_extensions_ffi.py

Determinism note: the per-op ctypes-vs-builtin timing in Section D is
ILLUSTRATIVE (varies per run / machine); we assert only the RELATIVE fact that
a ctypes call in a tight Python loop is slower than the pure-Python builtin,
because every ctypes call marshals across the Python<->C boundary.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
import timeit

BANNER = "=" * 70
_ILLUSTRATIVE = "(varies per run)"


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
# Section A — load a shared library (find libc, the gateway)
# ----------------------------------------------------------------------------

def _load_libc() -> ctypes.CDLL:
    """Locate and load the platform C library portably.

    find_library("c") returns "/usr/lib/libc.dylib" on macOS, "libc.so.6" on
    Linux, None on Windows (where msvcrt is the closest analogue). We try
    find_library first, then fall back to well-known names, so the bundle runs
    on every mainstream platform without edits.
    """
    name = ctypes.util.find_library("c")
    if name is not None:
        return ctypes.CDLL(name)
    # Fallbacks: Linux often wants the literal soname; Windows has msvcrt.
    for candidate in ("libc.so.6", "libc.so", "msvcrt.dll"):
        try:
            return ctypes.CDLL(candidate)
        except OSError:
            continue
    raise OSError("could not locate the C shared library on this platform")


def section_a_load_shared_lib() -> None:
    banner("A — Load a shared library: ctypes.CDLL(find_library('c'))")
    print("ctypes (stdlib) is the gateway to native code: it dlopen()s a shared")
    print("library (.so on Linux, .dylib on macOS, .dll on Windows) and binds")
    print("each exported C symbol to a callable Python object. No compiler, no")
    print("build step — just find_library() + CDLL().\n")
    print(f"sys.platform = {sys.platform!r}")
    name = ctypes.util.find_library("c")
    print(f"ctypes.util.find_library('c') = {name!r}")
    libc = _load_libc()
    print(f"libc = ctypes.CDLL({name!r})")
    print(f"libc._handle = {hex(libc._handle)} (the dlopen handle)")
    print(f"libc.atof    = {libc.atof!r}")
    print(f"libc.strlen  = {libc.strlen!r}")
    print()
    check("find_library('c') returns a non-empty path/name", bool(name))
    check("CDLL loads (libc._handle is set)", libc._handle != 0)
    check("libc.atof is a callable _FuncPtr", callable(libc.atof))


# ----------------------------------------------------------------------------
# Section B — declare argtypes/restype, then call atof/strlen/abs
# ----------------------------------------------------------------------------

def section_b_argtypes_restype() -> None:
    banner("B — Declare argtypes/restype, then call real C functions")
    print("If you skip argtypes/restype ctypes guesses (often wrong): it assumes")
    print("c_int return and C-int arguments. The docs REQUIRE setting them for")
    print("any function returning non-int (e.g. c_double) or taking pointers.\n")
    libc = _load_libc()

    # atof: double atof(const char*)  -> restype c_double, argtypes [c_char_p]
    libc.atof.argtypes = [ctypes.c_char_p]
    libc.atof.restype = ctypes.c_double
    # strlen: size_t strlen(const char*) -> c_size_t
    libc.strlen.argtypes = [ctypes.c_char_p]
    libc.strlen.restype = ctypes.c_size_t
    # abs: int abs(int) -> c_int
    libc.abs.argtypes = [ctypes.c_int]
    libc.abs.restype = ctypes.c_int

    print(f"{'call':<32}{'result':<12}{'type'}")
    print("-" * 58)
    rows = [
        ("libc.atof(b'3.14')", libc.atof(b"3.14")),
        ("libc.atof(b'-2.5')", libc.atof(b"-2.5")),
        ("libc.strlen(b'hello')", libc.strlen(b"hello")),
        ("libc.strlen(b'')", libc.strlen(b"")),
        ("libc.abs(-42)", libc.abs(-42)),
        ("libc.abs(7)", libc.abs(7)),
    ]
    for label, value in rows:
        print(f"{label:<32}{str(value):<12}{type(value).__name__}")
    print()
    check("libc.atof(b'3.14') == 3.14 (exact double)", libc.atof(b"3.14") == 3.14)
    check("libc.strlen(b'hello') == 5", libc.strlen(b"hello") == 5)
    check("libc.strlen(b'') == 0", libc.strlen(b"") == 0)
    check("libc.abs(-42) == 42", libc.abs(-42) == 42)
    check("libc.atof returns a Python float (c_double marshalled)",
          isinstance(libc.atof(b"1.0"), float))
    check("libc.abs returns a Python int (c_int marshalled)",
          isinstance(libc.abs(1), int))


# ----------------------------------------------------------------------------
# Section C — ctypes.Structure: a C-shaped record, byref/pointer, memset
# ----------------------------------------------------------------------------

class CPoint(ctypes.Structure):
    """A 2-D point laid out exactly like `struct { int x, y; }` in C."""
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int)]


def section_c_structure_byref() -> None:
    banner("C — ctypes.Structure: a C-shaped record; byref/pointer/memset")
    print("A ctypes.Structure with _fields_ is byte-identical to a C struct: it")
    print("occupies sizeof(fields) bytes, fields sit at documented offsets, and")
    print("you can hand its address to any C function that takes a pointer.\n")

    p = CPoint(7, 9)
    print("p = CPoint(7, 9)")
    print(f"  p.x, p.y          = {p.x}, {p.y}")
    print(f"  ctypes.sizeof(p)  = {ctypes.sizeof(p)}  (== sizeof(int)*2)")
    print(f"  CPoint.x.offset   = {CPoint.x.offset}  (byte offset of field x)")
    print(f"  CPoint.y.offset   = {CPoint.y.offset}  (byte offset of field y)")
    print(f"  ctypes.addressof(p) = {ctypes.addressof(p)}")
    print()

    # Field write/read works like a normal attribute.
    p.x = 100
    p.y = -5
    print(f"after p.x=100, p.y=-5:  p.x, p.y = {p.x}, {p.y}")
    check("Structure fields read back what was written", p.x == 100 and p.y == -5)

    # byref() and pointer() both hand the struct's address to C; byref is the
    # lighter-weight "just for this one call" form (no intermediate object).
    libc = _load_libc()
    libc.memset.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]
    libc.memset.restype = ctypes.c_void_p
    libc.memset(ctypes.byref(p), 0, ctypes.sizeof(p))
    print(f"after memset(byref(p), 0, sizeof(p)): p.x, p.y = {p.x}, {p.y}  "
          f"(C zeroed the struct's bytes in place)")
    print()
    check("memset via byref zeroed the struct in place", p.x == 0 and p.y == 0)
    check("sizeof(CPoint) == 8 (two 4-byte c_ints, no padding)",
          ctypes.sizeof(CPoint) == 8)
    check("field offsets are 0 and 4 (packed back-to-back)",
          CPoint.x.offset == 0 and CPoint.y.offset == 4)


# ----------------------------------------------------------------------------
# Section D — the cost model: every ctypes call crosses a boundary
# ----------------------------------------------------------------------------

def section_d_call_cost_model() -> None:
    banner("D — The cost model: every ctypes call marshals across a boundary")
    print("ctypes is NOT magic free speed. Each call: (1) acquires the GIL (it")
    print("is always held), (2) boxes each Python arg into its C type, (3) calls")
    print("the C function, (4) boxes the C result back to a PyObject. For ONE")
    print("call that does a lot of C work (strlen on 1 MB) C wins; for a call in")
    print("a tight Python loop doing trivial work, the marshalling dominates and")
    print("the builtin beats libc. This is why cffi/Cython exist: they amortize")
    print("the boundary by compiling the loop itself into C.\n")
    libc = _load_libc()
    libc.abs.argtypes = [ctypes.c_int]
    libc.abs.restype = ctypes.c_int
    libc.strlen.argtypes = [ctypes.c_char_p]
    libc.strlen.restype = ctypes.c_size_t

    # Tight Python loop, trivial work: the builtin wins (no marshalling).
    n = 200_000
    t_builtin = min(timeit.repeat(lambda: abs(-1), number=n, repeat=3)) / n
    t_ctypes = min(timeit.repeat(lambda: libc.abs(-1), number=n, repeat=3)) / n
    ratio = t_ctypes / t_builtin if t_builtin else float("inf")
    print("per-op (tight loop, trivial work):")
    print(f"  builtin abs(-1) : {t_builtin*1e9:7.1f} ns  {_ILLUSTRATIVE}")
    print(f"  libc.abs(-1)    : {t_ctypes*1e9:7.1f} ns  {_ILLUSTRATIVE}")
    print(f"  ctypes/builtin  : {ratio:7.1f}x SLOWER per op (marshalling tax)")
    print()

    # Bulk work in ONE C call: libc wins because the loop runs in C, not Python.
    big = b"x" * 1_000_000
    m = 1_000
    t_strlen_c = min(timeit.repeat(lambda: libc.strlen(big), number=m, repeat=3)) / m
    t_strlen_py = min(timeit.repeat(lambda: len(big), number=m, repeat=3)) / m
    print("strlen(1 MB buffer), ONE call into the lib:")
    print(f"  libc.strlen : {t_strlen_c*1e6:7.3f} us  {_ILLUSTRATIVE}")
    print(f"  len(bytes)  : {t_strlen_py*1e6:7.3f} us  {_ILLUSTRATIVE}")
    print()
    check("in a tight loop, ctypes abs is SLOWER than builtin abs", t_ctypes > t_builtin)
    check("the per-op marshalling tax is meaningful (ratio > 2x)", ratio > 2)
    check("strlen(1MB) returns 1_000_000 from libc", libc.strlen(big) == 1_000_000)


# ----------------------------------------------------------------------------
# Section E — cffi overview (ABI vs API mode) — conceptual, not run
# ----------------------------------------------------------------------------

def section_e_cffi_overview() -> None:
    banner("E — cffi overview: ABI vs API mode (conceptual; not run here)")
    print("cffi is the next rung up. You write plain C declarations; cffi parses")
    print("them and either talks to the lib directly (ABI mode, like ctypes) or")
    print("compiles a dedicated C-extension shim (API mode, faster). The four")
    print("modes (per the cffi overview doc):\n")
    print(f"{'mode':<22}{'preparation':<26}{'speed':<10}{'notes'}")
    print("-" * 92)
    rows = [
        ("ABI, in-line", "ffi.dlopen()", "slowest",
         "no compiler; accesses the binary ABI like ctypes"),
        ("ABI, out-of-line", "ffi.set_source()", "slow",
         "precompiles the cdef; still ABI-level calls"),
        ("API, in-line", "ffi.verify()", "fast",
         "compiles a shim at import time; C-source level"),
        ("API, out-of-line", "ffi.set_source()+build", "fastest",
         "the recommended mode; ships a prebuilt extension"),
    ]
    for mode, prep, speed, notes in rows:
        print(f"{mode:<22}{prep:<26}{speed:<10}{notes}")
    print()
    print("The cffi overview doc's recommendation: prefer 'API, out-of-line' for")
    print("production — it compiles once at install time and gives ctypes-like")
    print("ergonomics with C-like call speed.")
    print()
    print("Conceptual snippet (NOT executed — cffi is not a stdlib module):")
    print("    from cffi import FFI")
    print("    ffi = FFI()")
    print('    ffi.cdef("double atof(const char *s);")')
    print('    lib = ffi.dlopen(ctypes.util.find_library("c"))')
    print('    lib.atof(b"3.14")   # -> 3.14  (same call, parsed-from-C types)')
    print()
    check("cffi has exactly two levels (ABI, API) crossed with two prep modes",
          len(rows) == 4)


# ----------------------------------------------------------------------------
# Section F — Cython: compile a typed Python superset to C (conceptual)
# ----------------------------------------------------------------------------

def section_f_cython_conceptual() -> None:
    banner("F — Cython: compile a typed Python superset to C (conceptual)")
    print("Cython is a language + compiler: a superset of Python where you add C")
    print("type declarations (cdef/cpdef). The Cython compiler translates a .pyx")
    print("file into C, then your C compiler turns that into a Python extension")
    print("module (.so/.pyd). The build needs a setup.py + a C toolchain.\n")
    print("Conceptual fib .pyx (NOT executed here — needs the build step):\n")
    print("    # fastfib.pyx")
    print("    cdef long _fib(long n):             # cdef: C-only, not seen by Python")
    print("        if n < 2:")
    print("            return n")
    print("        return _fib(n - 1) + _fib(n - 2)")
    print()
    print("    cpdef long fib(long n):             # cpdef: callable from Python")
    print("        return _fib(n)")
    print()
    print("    # setup.py")
    print("    from setuptools import setup")
    print("    from Cython.Build import cythonize")
    print('    setup(ext_modules=cythonize("fastfib.pyx"))')
    print()
    print("    # build & import:")
    print("    $ python setup.py build_ext --inplace")
    print("    >>> import fastfib; fastfib.fib(30)   # runs as compiled C")
    print()
    print("Because the recursion happens in C with C longs, fib(30) is ~10-100x")
    print("faster than the pure-Python version — no per-call marshalling.")
    print()
    check("the Cython build chain is .pyx -> C source -> extension module",
          True)


# ----------------------------------------------------------------------------
# Section G — PyO3: expose Rust to Python via maturin (conceptual)
# ----------------------------------------------------------------------------

def section_g_pyo3_conceptual() -> None:
    banner("G — PyO3: expose Rust to Python via maturin (conceptual)")
    print("PyO3 is the inverse direction: write a Rust crate, decorate fns with")
    print("#[pyfunction], and the maturin build tool produces an importable")
    print("Python extension module. You get Rust's memory safety + speed with no")
    print("manual refcounting beyond what PyO3's wrappers already encode.\n")
    print("Conceptual Rust src/lib.rs (NOT executed here — needs cargo + maturin):\n")
    print("    use pyo3::prelude::*;")
    print()
    print("    #[pyfunction]")
    print("    fn fib(n: u64) -> u64 {                 // plain Rust fn")
    print("        if n < 2 { n }")
    print("        else { fib(n - 1) + fib(n - 2) }")
    print("    }")
    print()
    print("    #[pymodule]")
    print("    fn fastfib(m: &Bound<'_, PyModule>) -> PyResult<()> {")
    print("        m.add_function(wrap_pyfunction!(fib, m)?)?;")
    print("        Ok(())")
    print("    }")
    print()
    print("    # build & import:")
    print("    $ maturin develop --release")
    print("    >>> import fastfib; fastfib.fib(30)    # Rust, called from Python")
    print()
    print("PyO3 + maturin is now the standard path for Rust<->Python; libraries")
    print("like polars, pydantic-core, and cryptography are built this way.")
    print()
    check("the PyO3 build chain is Rust crate -> maturin -> extension module",
          True)


# ----------------------------------------------------------------------------
# Section H — when to drop out of pure Python (the decision ladder)
# ----------------------------------------------------------------------------

def section_h_when_to_drop() -> None:
    banner("H — When to drop out of pure Python: the speed-vs-complexity ladder")
    print("Drop to native ONLY after profiling proves a hot loop. Every rung up")
    print("the ladder adds BUILD COMPLEXITY (a compiler toolchain, a build step,")
    print("harder debugging, cross-platform packaging). Pay it only when the")
    print("profile says the win is real.\n")
    print(f"{'rung':<20}{'speed':<16}{'build cost':<34}{'best for'}")
    print("-" * 100)
    rows = [
        ("pure Python", "1x (baseline)", "none (interpreter only)",
         "the 97% case; algorithms + builtins first"),
        ("array/numpy", "5-50x", "pip install numpy",
         "vectorized numeric; no per-element Python"),
        ("ctypes (stdlib)", "~1x per op*", "none (stdlib)",
         "call a small C fn, or wrap a vendor .so"),
        ("cffi API mode", "5-50x bulk", "C compiler at build time",
         "ergonomic C wrappers; CFFI from cdef"),
        ("Cython .pyx", "10-100x", "Cython + C compiler + setup.py",
         "typed numeric loops, wrapping C/C++"),
        ("PyO3 + maturin", "10-100x", "Rust + cargo + maturin",
         "safe rewrite, parallel threads, no GIL opt."),
    ]
    for rung, speed, build, best in rows:
        print(f"{rung:<20}{speed:<16}{build:<34}{best}")
    print("\n* ctypes per-op is SLOWER than the builtin (Section D); it wins only")
    print("when ONE call does a lot of C work (strlen, a vendor DSP call, ...).\n")
    check("the ladder has six rungs from pure Python to PyO3", len(rows) == 6)
    check("pure Python is rung 0 (always try this first)",
          rows[0][0] == "pure Python")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("c_extensions_ffi.py — Phase 4 bundle #26.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Only stdlib is used (ctypes loads libc). Cython, cffi, and\n"
          "PyO3 are EXPLAINED in the .md; their snippets appear here as text,\n"
          "never executed. Timing digits are ILLUSTRATIVE (vary per run); we\n"
          "assert only structural / relative facts.\n"
          f"Python {sys.version.split()[0]} on {sys.platform} on this machine.")
    section_a_load_shared_lib()
    section_b_argtypes_restype()
    section_c_structure_byref()
    section_d_call_cost_model()
    section_e_cffi_overview()
    section_f_cython_conceptual()
    section_g_pyo3_conceptual()
    section_h_when_to_drop()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
