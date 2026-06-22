"""
bytecode_internals.py — Bundle #23 (Phase 4).

GOAL (one line): show, by printing every value and every instruction, how
CPython compiles source to bytecode (code objects) and runs it on a
stack-based eval loop — and why `obj.method` in a hot loop costs a
LOAD_ATTR every single iteration.

This is the GROUND TRUTH for BYTECODE_INTERNALS.md. Every instruction
stream, every co_consts value, and every structural assertion in the guide
is printed by this file. Change it -> re-run -> re-paste. Never hand-compute.

Bytecode is a CPython implementation detail: opcodes, operands, and offsets
change between minor versions. The assertions below check STRUCTURAL facts
(opname present / absent, constant-pool membership) that are stable across
3.12-3.14; the dis.dis() dumps are captured verbatim for THIS Python.

Run:
    uv run python bytecode_internals.py
"""

from __future__ import annotations

import dis
import io
import sys
import types

BANNER = "=" * 70


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


def loop_body_opnames(fn) -> list[str]:
    """Return opnames inside the for-loop body (FOR_ITER .. JUMP_BACKWARD)."""
    ops: list[str] = []
    inside = False
    for ins in dis.get_instructions(fn):
        if ins.opname == "FOR_ITER":
            inside = True
            continue
        if inside:
            if ins.opname == "JUMP_BACKWARD":
                break
            ops.append(ins.opname)
    return ops


# ----------------------------------------------------------------------------
# Module-level demo objects + functions.
# Defined at MODULE SCOPE (not nested) so dis shows LOAD_FAST / LOAD_GLOBAL /
# LOAD_ATTR cleanly — no closure / cell variables to muddy the instruction
# stream.
# ----------------------------------------------------------------------------

G = 10  # module-level global — used to emit LOAD_GLOBAL


class Widget:
    def add(self) -> int:
        return 1


WIDGET = Widget()


def add_one(x: int) -> int:
    return x + 1


def use_local() -> int:
    x = 1
    return x + 1


def use_global() -> int:
    return G + 1


def use_builtin() -> int:
    return len([1, 2, 3])


def use_attr():
    return WIDGET.add


def hot_loop(n: int) -> int:
    total = 0
    for _ in range(n):
        total += WIDGET.add()
    return total


def hot_loop_cached(n: int) -> int:
    total = 0
    add = WIDGET.add
    for _ in range(n):
        total += add()
    return total


# ----------------------------------------------------------------------------
# Section A — source -> code object -> eval loop
# ----------------------------------------------------------------------------

def section_a_source_to_code_to_eval() -> None:
    banner("A — Source -> code object -> eval loop")
    co = compile("x + 1", "<demo>", "eval")
    print("compile('x + 1', '<demo>', 'eval') produces a CODE OBJECT:")
    print(f"  type(co)     = {type(co).__name__}")
    print(f"  co.co_consts = {co.co_consts}")
    print(f"  co.co_names  = {co.co_names}")
    result = eval(co, {"x": 41})
    print(f"  eval(co, dict(x=41)) = {result}")
    print()
    print("'eval' mode compiles a single EXPRESSION; 'exec' mode compiles")
    print("STATEMENTS (def/class/import/assignment). A .py file is compiled")
    print("to a MODULE code object, then that code object is executed by")
    print("CPython's stack-based eval loop — there is no runtime source")
    print("re-reading.\n")
    co_exec = compile("y = 2", "<demo>", "exec")
    ns: dict = {}
    exec(co_exec, ns)
    print("  compile('y = 2', '<demo>', 'exec'); exec(co_exec, {})")
    print(f"  ns['y'] = {ns['y']}")
    print()

    check("compile('eval') returns a code object", isinstance(co, types.CodeType))
    check("eval runs the compiled code object", eval(co, {"x": 41}) == 42)
    check("'eval' co_consts contains literal 1", 1 in co.co_consts)
    check("'eval' co_names contains 'x'", "x" in co.co_names)


# ----------------------------------------------------------------------------
# Section B — fn.__code__: bytecode + constant pool introspection
# ----------------------------------------------------------------------------

def section_b_code_object_introspection() -> None:
    banner("B — fn.__code__: the bytecode + constant pool of a function")
    c = add_one.__code__
    print("def add_one(x): return x + 1")
    print(f"  type(add_one.__code__)       = {type(c).__name__}")
    print(f"  add_one.__code__.co_consts   = {c.co_consts}")
    print(f"  add_one.__code__.co_varnames = {c.co_varnames}")
    print(f"  add_one.__code__.co_names    = {c.co_names}")
    print(f"  add_one.__code__.co_code     = {c.co_code!r}")
    print(f"  len(co_code)                 = {len(c.co_code)} bytes")
    print()
    print("co_consts  = tuple of literal constants used in the body.")
    print("co_varnames = tuple of local variable names (indexed by LOAD_FAST).")
    print("co_names   = tuple of global/attribute names (LOAD_GLOBAL/LOAD_ATTR).")
    print("co_code    = raw bytes of the instruction stream (2 bytes/instr).\n")

    check("fn.__code__ is a code object", isinstance(c, types.CodeType))
    check("co_consts contains None and 1",
          None in c.co_consts and 1 in c.co_consts)
    check("co_varnames lists local 'x'", c.co_varnames == ("x",))
    check("co_names is empty (no global/attr in add_one)", c.co_names == ())
    check("co_code is bytes (raw instruction stream)",
          isinstance(c.co_code, bytes))


# ----------------------------------------------------------------------------
# Section C — dis.dis(add_one): reading the instruction stream line by line
# ----------------------------------------------------------------------------

def section_c_read_bytecode_line_by_line() -> None:
    banner("C — dis.dis(add_one): reading the instruction stream")
    print("Each row = ONE bytecode instruction. Columns: source-line, opcode,")
    print("arg (numeric), arg-resolved (human). The eval loop executes these in")
    print("order, pushing/popping an operand stack.\n")
    print(">>> dis.dis(add_one)")
    dis.dis(add_one)
    print()
    ops = [i.opname for i in dis.get_instructions(add_one)]
    print(f"opnames: {ops}")
    print()

    check("LOAD_FAST present (push local 'x')", "LOAD_FAST" in ops)
    check("LOAD_CONST present (push literal 1)", "LOAD_CONST" in ops)
    check("BINARY_OP present (pop two, push result)", "BINARY_OP" in ops)
    check("RETURN_VALUE present (pop and return top)", "RETURN_VALUE" in ops)


# ----------------------------------------------------------------------------
# Section D — LOAD_FAST vs LOAD_GLOBAL vs LOAD_ATTR (lookup costs)
# ----------------------------------------------------------------------------

def section_d_lookup_costs() -> None:
    banner("D — LOAD_FAST vs LOAD_GLOBAL vs LOAD_ATTR (lookup costs)")
    print("Three different lookups map to three different opcodes:\n")
    print("  LOAD_FAST   — local var; fast-indexed array slot   (cheapest)")
    print("  LOAD_GLOBAL — module global OR builtin; dict lookup (slower)")
    print("  LOAD_ATTR   — object.attribute; type MRO + dict walk (slowest)")
    print()
    print(">>> dis.dis(use_local)   # x is a local")
    dis.dis(use_local)
    print()
    print(">>> dis.dis(use_global)  # G is a module global")
    dis.dis(use_global)
    print()
    print(">>> dis.dis(use_builtin) # len is a builtin (LOAD_GLOBAL + NULL)")
    dis.dis(use_builtin)
    print()
    print(">>> dis.dis(use_attr)    # WIDGET.add is an attribute")
    dis.dis(use_attr)
    print()

    local_ops = [i.opname for i in dis.get_instructions(use_local)]
    global_ops = [i.opname for i in dis.get_instructions(use_global)]
    builtin_ops = [i.opname for i in dis.get_instructions(use_builtin)]
    attr_ops = [i.opname for i in dis.get_instructions(use_attr)]
    all_ops = local_ops + global_ops + builtin_ops + attr_ops

    check("use_local uses LOAD_FAST (indexed array access)",
          "LOAD_FAST" in local_ops)
    check("use_global uses LOAD_GLOBAL (dict lookup)", "LOAD_GLOBAL" in global_ops)
    check("use_builtin uses LOAD_GLOBAL too (3.12+ merged builtins into it)",
          "LOAD_GLOBAL" in builtin_ops)
    check("use_attr uses LOAD_ATTR (type + dict walk)", "LOAD_ATTR" in attr_ops)
    check("no LOAD_NAME in any of the four (3.13 uses LOAD_FAST/GLOBAL/ATTR)",
          "LOAD_NAME" not in all_ops)


# ----------------------------------------------------------------------------
# Section E — obj.method per iteration: the cost + the cache-the-method fix
# ----------------------------------------------------------------------------

def section_e_hot_loop_attr_cost() -> None:
    banner("E — obj.method per iteration: cost + cache-the-method fix")
    print("hot_loop calls WIDGET.add() INSIDE the loop — each iteration emits")
    print("LOAD_GLOBAL(WIDGET) + LOAD_ATTR(add) + CALL. hot_loop_cached hoists")
    print("the attribute lookup OUT: 'add = WIDGET.add' runs ONCE, then the")
    print("loop body is just CALL on a local.\n")
    print(">>> dis.dis(hot_loop)")
    dis.dis(hot_loop)
    print()
    print(">>> dis.dis(hot_loop_cached)")
    dis.dis(hot_loop_cached)
    print()

    hot_body = loop_body_opnames(hot_loop)
    cached_body = loop_body_opnames(hot_loop_cached)
    print(f"hot_loop       loop-body ops: {hot_body}")
    print(f"hot_loop_cached loop-body ops: {cached_body}")
    print()

    check("hot_loop body contains LOAD_ATTR (attr lookup per iteration)",
          "LOAD_ATTR" in hot_body)
    check("hot_loop_cached body has NO LOAD_ATTR (hoisted out)",
          "LOAD_ATTR" not in cached_body)
    check("both loops return the same result",
          hot_loop(5) == hot_loop_cached(5) == 5)


# ----------------------------------------------------------------------------
# Section F — code objects are immutable; you replace __code__, not mutate it
# ----------------------------------------------------------------------------

def section_f_immutable_reusable() -> None:
    banner("F — Code objects are immutable; replace __code__, don't mutate")

    def original_fn() -> int:
        return 1

    def replacement_fn() -> int:
        return 999

    c = original_fn.__code__
    print("co_consts is READONLY — you cannot mutate bytecode in place:")
    mutated = False
    try:
        c.co_consts = (None, 2)
        mutated = True
        print("  (no error — unexpected!)")
    except (AttributeError, TypeError) as exc:
        print(f"  c.co_consts = (None, 2)  ->  {type(exc).__name__}: {exc}")
    print()

    print("But you CAN swap a function's entire __code__ object:")
    print(f"  original_fn() before swap: {original_fn()}")
    original_fn.__code__ = replacement_fn.__code__
    print(f"  original_fn() after swap:  {original_fn()}")
    print()

    def f1() -> int:
        return 1

    def f2() -> int:
        return 1

    print("Two functions with identical source get DISTINCT code objects")
    print("(CPython does not deduplicate code objects):")
    print(f"  f1.__code__ is f2.__code__  ->  {f1.__code__ is f2.__code__}")
    print(f"  f1.__code__ is f1.__code__  ->  {f1.__code__ is f1.__code__}")
    print()

    check("co_consts is readonly (cannot mutate in place)", not mutated)
    check("replacing __code__ changes the function's behavior",
          original_fn() == 999)
    check("two distinct functions have distinct code objects",
          f1.__code__ is not f2.__code__)
    check("a code object identity is stable across accesses",
          f1.__code__ is f1.__code__)


# ----------------------------------------------------------------------------
# Section G — the 3.11+ specializing adaptive interpreter (PEP 659)
# ----------------------------------------------------------------------------

def section_g_adaptive_interpreter() -> None:
    banner("G — The 3.11+ specializing adaptive interpreter (PEP 659)")
    print("Since CPython 3.11 (PEP 659), the interpreter QUICKENS bytecode at")
    print("runtime: after an instruction executes enough times, it is replaced")
    print("in-place by a SPECIALIZED variant tuned to the actual types/values.\n")
    print("  LOAD_ATTR   -> LOAD_ATTR_SLOT / LOAD_ATTR_MODULE / ...")
    print("  LOAD_GLOBAL -> LOAD_GLOBAL_MODULE / LOAD_GLOBAL_BUILTIN\n")
    print("Specialization lives in the interpreter's QUICKENED bytecode buffer,")
    print("NOT in the code object's co_code (which stays unspecialized).")
    print("dis.dis() shows the UNSPECIALIZED form; show_caches=True reveals the")
    print("inline-cache slots that the specializing interpreter writes to.\n")

    buf = io.StringIO()
    dis.dis(use_attr, file=buf, show_caches=True)
    dis_text = buf.getvalue()
    print(">>> dis.dis(use_attr, show_caches=True)")
    print(dis_text, end="")
    cache_count = dis_text.count("CACHE")
    print(f"({cache_count} CACHE entries follow LOAD_ATTR — specialization data)\n")

    ver = sys.version_info[:2]
    print(f"Python {ver[0]}.{ver[1]} — adaptive interpreter present.")
    print()

    check("running on CPython >= 3.11 (PEP 659 adaptive interpreter)",
          ver >= (3, 11))
    check("LOAD_ATTR is followed by CACHE entries (specialization slots)",
          cache_count > 0)
    check("dis.Bytecode accepts adaptive=True (3.11+)", _adaptive_kwarg_works())


def _adaptive_kwarg_works() -> bool:
    """Return True if dis.Bytecode accepts the adaptive= keyword (3.11+)."""
    try:
        dis.Bytecode(use_local, adaptive=True)
        return True
    except TypeError:
        return False


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("bytecode_internals.py — Phase 4 bundle #23.\n"
          "Every instruction stream below is printed by this file; the .md\n"
          "guide pastes it verbatim. Nothing is hand-computed.\n"
          f"Python {sys.version.split()[0]} on this machine.")
    section_a_source_to_code_to_eval()
    section_b_code_object_introspection()
    section_c_read_bytecode_line_by_line()
    section_d_lookup_costs()
    section_e_hot_loop_attr_cost()
    section_f_immutable_reusable()
    section_g_adaptive_interpreter()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
