"""
vectorized_execution.py - Reference implementation of vectorized (columnar)
query execution versus the classic row-at-a-time Volcano model.

This is the single source of truth that VECTORIZED_EXECUTION.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 vectorized_execution.py

============================================================================
THE INTUITION (read this first) -- the bucket brigade vs the conveyor belt
============================================================================
Imagine a warehouse packing station. Orders (rows) arrive and must be checked
(> 5?), then two labels computed (a+b, a*b), then boxed.

  * Volcano (row-at-a-time): one worker grabs ONE order, walks it past the
    check desk, the add desk, the multiply desk, the box desk -- 4 handoffs
    per order. With 8 orders that is 20 handoffs (function calls). Every
    handoff is overhead: a virtual call, a branch, a cache miss jumping
    between desks. The CPU spends more time CHANGING TASK than doing work.

  * Vectorized (column batches): the check desk takes a whole TRAY of 8
    orders at once (1 call), marks which pass, and hands the tray -- actually
    just a small list of WHICH positions passed (a "selection vector") -- to
    the add desk (1 call), which processes all 8 (or all survivors) in one
    tight loop. 4 calls total, not 20. And that tight loop over a contiguous
    tray is exactly what the CPU's SIMD units and cache prefetcher love.

THE REASON VECTORIZED EXISTS: modern CPUs do billions of operations per
second, but ONLY if you feed them a long, predictable stream of the SAME
operation on contiguous memory. The Volcano model feeds them one value, then
changes operation, then one value, then changes operation -- it is "instruction
thrashing". Vectorized execution re-batches the work so each operator eats a
whole vector of identical-typed values at once, letting the compiler emit one
SIMD instruction that does 8 (or 16) additions for the price of one.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  Volcano model   : the classic iterator model (Graefe 1994). Every operator
                    exposes next() which returns ONE tuple. Pulling the plan
                    to completion is a cascade of per-tuple next() calls.
  tuple / row     : one record, all its columns interleaved in memory.
  vector / batch  : a chunk of ONE column's values, laid out contiguously.
                    Real engines use 1024-4096 values per vector.
  operator        : a pipeline stage: Scan, Filter (Select), Project, Aggregate.
  selection vector: a compact list of ROW INDICES that survived a filter.
                    Passed downstream instead of copying the actual data.
  late            : deferring the read of a column until AFTER the filter has
  materialization   pruned rows, so you only fetch it for the survivors.
  SIMD            : Single Instruction, Multiple Data. One CPU instruction
                    (e.g. AVX2 `vpadps`/`vpaddd`) operates on a whole register
                    of 8 float32 / 8 int32 lanes at once (256 bits).
  cache line      : the 64-byte unit the CPU loads from memory at a time.

============================================================================
THE LINEAGE (papers / systems)
============================================================================
  Volcano (Graefe 1994)            : the iterator model. next() returns one
    "Volcano-An Extensible and     tuple. Elegant, composable, but one
     Parallel Query Evaluation      virtual call PER TUPLE = the bottleneck.
     System", IEEE Data Eng. Bull.
  Vectorized / X100 (Boncz et al.  : instead of next()->1 tuple, each operator
    2005, "MonetDB/X100:            processes a VECTOR of ~1024 values per
     Hyper-Pipelining Query         call. Tight loops -> compiler auto-
     Execution", CIDR)              vectorizes to SIMD. The foundational paper.
  Selection vectors (Zukowski      : filters emit a list of indices, not
    et al. 2005, BIRTE;             copied data. Branchless, compact, and
    Polychroniou et al. 2014)       SIMD-friendly ("vectorized selection").
  Late materialization (Abadi      : don't read a column until the filter has
    et al. 2007, ICDE,              pruned rows. For SELECT a+b WHERE a>5 you
    "Materialization Strategies     fetch 'b' only for the matching rows.
     in a Column-Oriented DBMS")
  Modern systems                   : ClickHouse (vectorized engine, batches of
                                     thousands), DuckDB (morsel-driven
                                     vectorized, Raasveldt & Muhleisen 2019),
                                     HyPer, Peloton, VectorWise.

KEY FORMULAS (all verified against the papers + asserted in code):
    Volcano calls/operator   = N                 (one next() per tuple)
    Vectorized calls/op      = ceil(N / batch)   (one call per vector)
    SIMD lanes               = register_bits / element_bits
                               AVX2 int32: 256/32 = 8 ; AVX-512: 16 ; NEON: 4
    SIMD instructions        = ceil(N / lanes)   vs N scalar instructions
    SIMD speedup (instr)     = N / ceil(N/lanes) ~= lanes
    Cache utilization        = useful_bytes / bytes_loaded_from_memory
    Selection-vector bytes   = n_pass * bytes_per_index   (uint16/uint32)
    Materialized bytes       = n_pass * n_cols * bytes_per_value
    Late-materialization I/O = N (predicate col) + selectivity*N (each other col)
                               vs early: n_cols * N

The N=8 worked example below is DETERMINISTIC (fixed inputs) and byte-for-byte
identical to the inputs recomputed in vectorized_execution.html.

Sources:
  [1] G. Graefe, 1994, "Volcano-An Extensible and Parallel Query Evaluation
      System", IEEE Data Engineering Bulletin. -- the iterator model.
  [2] P. Boncz, M. Zukowski, N. Nes, 2005, "MonetDB/X100: Hyper-Pipelining
      Query Execution", CIDR. -- the vectorized model.
  [3] M. Zukowski et al., 2005, "MonetDB/X100: Data Partitioning and Pipeline",
      BIRTE. -- selection vectors / vectorized selection.
  [4] D. Abadi, D. Myers, D. DeWitt, S. Madden, 2007, "Materialization
      Strategies in a Column-Oriented DBMS", ICDE. -- late materialization.
  [5] H. Pirk et al., 2014, "CPU Cache Optimization for Database Workloads".
  [6] ClickHouse docs; DuckDB (Raasveldt & Muhleisen 2019, SIGMOD Demo).
"""

from __future__ import annotations

import math

# ============================================================================
# 0. CONSTANTS -- the tiny deterministic worked example
# ============================================================================

# The table t has 8 rows, two columns a and b. Query (used in every section):
#     SELECT a + b, a * b  FROM t  WHERE a > 5
A = [3, 7, 2, 8, 6, 1, 9, 5]            # column a (int32 values)
B = [10, 20, 30, 40, 50, 60, 70, 80]    # column b (int32 values)
N = len(A)                              # 8 rows
THRESHOLD = 5                            # filter predicate: a > 5

# Machine parameters used throughout (standard x86-64).
CACHE_LINE_BYTES = 64
INT32_BYTES = 4
TABLE_COLUMNS = ["a", "b", "c", "d"]    # a wider table for cache analysis
ROW_BYTES_WIDE = len(TABLE_COLUMNS) * INT32_BYTES   # 16 bytes/row

# SIMD register widths (bits) by ISA.
SIMD_ISAS = [
    ("scalar", 32),     # one int32 lane, no SIMD (the baseline)
    ("NEON", 128),      # ARM:   128/32 = 4 int32 lanes
    ("AVX2", 256),      # x86:   256/32 = 8 int32 lanes
    ("AVX-512", 512),   # x86:   512/32 = 16 int32 lanes
]

BANNER = "=" * 72


# ============================================================================
# 1. THE TWO EXECUTION MODELS  (this is the code the guide walks through)
# ============================================================================

def volcano_execute(a: list[int], b: list[int], threshold: int):
    """Volcano (iterator) model: process ONE tuple at a time.

    Emulates the pull-based next() pipeline. Each predicate evaluation, each
    arithmetic op, and each emit is a SEPARATE function call on a single row.
    Returns (results, call_counts) where call_counts records per-operator
    invocations -- the quantity that makes Volcano slow (virtual-call +
    branch overhead, repeated N times instead of once per batch).
    """
    calls = {"filter": 0, "add": 0, "multiply": 0, "project": 0}
    results = []
    for i in range(len(a)):
        calls["filter"] += 1                 # Filter.next(): evaluate predicate
        if a[i] > threshold:
            calls["add"] += 1                # compute a+b for this tuple
            s = a[i] + b[i]
            calls["multiply"] += 1           # compute a*b for this tuple
            p = a[i] * b[i]
            calls["project"] += 1            # Project.next(): emit the tuple
            results.append((s, p))
    return results, calls


def make_selection_vector(a: list[int], threshold: int) -> list[int]:
    """Vectorized Filter: scan the whole column once, return the INDICES of
    the values that pass. This is the selection vector -- compact metadata,
    not copied data. One call, one tight loop, branchless-friendly.
    """
    return [i for i in range(len(a)) if a[i] > threshold]


def vectorized_execute(a: list[int], b: list[int], threshold: int):
    """Vectorized (column-batch) model: process a VECTOR of values per call.

    Each operator is invoked ONCE and loops internally over the batch (or over
    the selection vector of survivors). Returns (results, call_counts, sel).
    """
    calls = {"filter": 0, "add": 0, "multiply": 0, "project": 0}
    sel = make_selection_vector(a, threshold)   # 1 filter call -> indices
    calls["filter"] += 1
    calls["add"] += 1                           # 1 add call over the survivors
    sums = [a[i] + b[i] for i in sel]
    calls["multiply"] += 1                       # 1 multiply call
    prods = [a[i] * b[i] for i in sel]
    calls["project"] += 1                        # 1 project call
    results = list(zip(sums, prods))
    return results, calls, sel


# --- the analysis formulas (ground truth for every number in the guide) ------

def simd_lanes(register_bits: int, element_bits: int = INT32_BYTES * 8) -> int:
    """How many int32 lanes fit in one SIMD register."""
    return register_bits // element_bits


def simd_instructions(n: int, register_bits: int, element_bits: int = 32) -> int:
    """Number of SIMD instructions to process n values: ceil(n / lanes)."""
    lanes = simd_lanes(register_bits, element_bits)
    return math.ceil(n / lanes)


def cache_lines_for(bytes_needed: int) -> int:
    """Cache lines (64 B each) the CPU must load to read bytes_needed."""
    return math.ceil(bytes_needed / CACHE_LINE_BYTES)


def selectivity(a: list[int], threshold: int) -> float:
    """Fraction of rows passing the predicate."""
    return sum(1 for x in a if x > threshold) / len(a)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_vec(v, width: int = 2) -> str:
    return "[" + ", ".join(f"{x:{width}d}" for x in v) + "]"


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the Volcano (row-at-a-time) model
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: Volcano model -- one row at a time  (count every call)")
    print(f"Table t: {N} rows.  Query: SELECT a+b, a*b FROM t WHERE a > {THRESHOLD}")
    print(f"  a = {fmt_vec(A)}")
    print(f"  b = {fmt_vec(B)}\n")
    print("Volcano pull pipeline:  Scan.next() -> Filter.next() -> Add -> "
          "Multiply -> Project.next()")
    print("Each operator's next() returns ONE tuple. Walk all 8 rows:\n")

    results, calls = volcano_execute(A, B, THRESHOLD)

    print(f"  {'row':>3}  {'a':>2}  {'b':>2}  {'a>5?':>5}   "
          f"{'calls this row':<28}  {'emit'}")
    print(f"  {'---':>3}  {'--':>2}  {'--':>2}  {'-----':>5}   "
          f"{'-' * 28}  {'----'}")
    c = {"filter": 0, "add": 0, "multiply": 0, "project": 0}
    for i in range(N):
        c["filter"] += 1
        if A[i] > THRESHOLD:
            c["add"] += 1
            c["multiply"] += 1
            c["project"] += 1
            row_calls = "filter, add, multiply, project"
            emit = f"({A[i]+B[i]}, {A[i]*B[i]})"
        else:
            row_calls = "filter  (rejected)"
            emit = "-"
        passed = "pass" if A[i] > THRESHOLD else "drop"
        print(f"  {i:>3}  {A[i]:>2}  {B[i]:>2}  {passed:>5}   "
              f"{row_calls:<28}  {emit}")

    total = sum(calls.values())
    print(f"\n  call counts: filter={calls['filter']}, add={calls['add']}, "
          f"multiply={calls['multiply']}, project={calls['project']}")
    print(f"  TOTAL per-tuple operator calls = {calls['filter']}+"
          f"{calls['add']}+{calls['multiply']}+{calls['project']} = {total}\n")

    n_pass = sum(1 for x in A if x > THRESHOLD)
    print(f"  -> filter evaluates the predicate {N} times (once per input row).")
    print(f"  -> {n_pass}/{N} rows pass; each survivor then costs add+multiply+"
          f"project = 3 more calls ({n_pass}*3 = {n_pass*3}).")
    print(f"  -> {total} calls, each doing work on a SINGLE value. Every call is")
    print("     overhead: a virtual dispatch + a branch + a cache jump between")
    print("     columns. THIS per-tuple call overhead is what Volcano pays.\n")
    print(f"  (If selectivity were 100%, it would be 4 ops x {N} rows = "
          f"{4*N} calls. The filter trims downstream work, but every survivor")
    print(f"   still costs 4 calls, and the filter itself always costs {N}.)")
    assert results == [(27, 140), (48, 320), (56, 300), (79, 630)]
    return results, calls


# ----------------------------------------------------------------------------
# SECTION B: the Vectorized (column-batch) model
# ----------------------------------------------------------------------------

def section_b(volcano_results):
    banner("SECTION B: Vectorized model -- one batch of column values per call")
    print(f"Same query, same {N} rows -- but each operator eats the WHOLE column")
    print(f"vector (batch = {N}) in one call:\n")

    results, calls, sel = vectorized_execute(A, B, THRESHOLD)

    print("  STEP 1  Filter (1 call):  scan column a once, emit a SELECTION")
    print("          VECTOR of surviving indices:")
    print(f"            a       = {fmt_vec(A)}")
    mark = [" " + ("v" if A[i] > THRESHOLD else ".") + " " for i in range(N)]
    print(f"            a>{THRESHOLD}?  = [{''.join(mark)}]")
    print(f"            sel_vec = {sel}   (len {len(sel)})\n")

    print("  STEP 2  Add (1 call):     compute a+b, but ONLY at sel indices")
    sums = [A[i] + B[i] for i in sel]
    print(f"            a[sel]  = {fmt_vec([A[i] for i in sel])}")
    print(f"            b[sel]  = {fmt_vec([B[i] for i in sel])}")
    print(f"            a+b     = {fmt_vec(sums)}\n")

    print("  STEP 3  Multiply (1 call): compute a*b at sel indices")
    prods = [A[i] * B[i] for i in sel]
    print(f"            a*b     = {fmt_vec(prods)}\n")

    print("  STEP 4  Project (1 call):  zip the two output columns into tuples")
    print(f"            result  = {results}\n")

    total = sum(calls.values())
    print(f"  call counts: filter={calls['filter']}, add={calls['add']}, "
          f"multiply={calls['multiply']}, project={calls['project']}")
    print(f"  TOTAL batch operator calls = {total}\n")

    print("  PER-OPERATOR view (the 'N / batch' rule):")
    print(f"    {'operator':<10} {'Volcano calls':>14} {'Vectorized calls':>17} "
          f"{'reduction':>10}")
    for op in ["filter", "add", "multiply", "project"]:
        v_calls = N if op == "filter" else len(sel)
        print(f"    {op:<10} {v_calls:>14} {1:>17} {v_calls:>9}x")
    print(f"\n  Volcano invokes each operator once PER TUPLE (N={N} times for the")
    print(f"  filter). Vectorized invokes it once PER BATCH = N/batch = "
          f"{N}/{N} = 1 time. Each of those calls is a tight loop over")
    print("  contiguous memory -> SIMD-friendly + cache-friendly (Sections C,D).\n")

    match = results == volcano_results
    print(f"  [check] vectorized result == volcano result?  {match}")
    print(f"          both = {results}")
    assert match, "vectorized and volcano must agree!"
    return results, calls, sel


# ----------------------------------------------------------------------------
# SECTION C: SIMD analysis -- one AVX2 instruction for 8 int32 adds
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: SIMD -- one instruction processes a whole vector lane")
    print("A scalar ADD does 1 int32. A SIMD ADD does as many as fit in one")
    print(f"register. int32 = {INT32_BYTES*8} bits. lanes = register_bits / "
          f"{INT32_BYTES*8}.\n")

    print(f"  {'ISA':<9} {'register':>9} {'int32 lanes':>12} "
          f"{'ADD instrs for {n} values':>26} {'speedup vs scalar':>18}".format(n=N))
    print(f"  {'-'*9} {'-'*9} {'-'*12} {'-'*26} {'-'*18}")
    scalar_instr = None
    for name, bits in SIMD_ISAS:
        lanes = simd_lanes(bits)
        instrs = simd_instructions(N, bits)
        if name == "scalar":
            scalar_instr = instrs
            speedup = "1.0x (baseline)"
        else:
            speedup = f"{scalar_instr / instrs:.1f}x"
        print(f"  {name:<9} {bits:>7}b {lanes:>12} {instrs:>26} {speedup:>18}")
    print()

    print(f"Our batch of {N} int32 values packs into ONE AVX2 register:")
    reg_width = 8
    print(f"  AVX2 register = 256 bits = {reg_width} x int32 (4 bytes each)")
    print("    [ a0 | a1 | a2 | a3 | a4 | a5 | a6 | a7 ]   <- 8 lanes, one register")
    print("  + [ b0 | b1 | b2 | b3 | b4 | b5 | b6 | b7 ]")
    print("  = [s0  | s1  | s2  | s3  | s4  | s5  | s6  | s7 ]   <- 1 `vpaddd` instr\n")

    scalar = N
    avx2 = simd_instructions(N, 256)
    print(f"  scalar path: {scalar} separate ADD instructions (one per value).")
    print(f"  AVX2  path: {avx2} ADD instruction (`vpaddd`) -> {scalar}/{avx2} = "
          f"{scalar/avx2:.0f}x fewer instructions.\n")

    # scale to a realistic vector size
    big = 2048
    print(f"At a realistic vector size of {big} values:")
    print(f"  {'ISA':<9} {'lanes':>6} {'instructions':>13} {'speedup':>9}")
    for name, bits in SIMD_ISAS:
        if name == "scalar":
            continue
        lanes = simd_lanes(bits)
        instrs = simd_instructions(big, bits)
        sp = big / instrs
        print(f"  {name:<9} {lanes:>6} {instrs:>13} {sp:>8.1f}x")
    print("\n  Caveat: this is INSTRUCTION-COUNT speedup. Real wall-clock speedup")
    print(f"  is lower (memory-bandwidth bound, data dependencies) but the {N}x")
    print("  instruction reduction is real and compounds with the cache win (D)")
    print("  and the call-count win (A/B). Together they are why ClickHouse and")
    print("  DuckDB process billions of rows/second on one core.\n")
    avx2_speedup = scalar / avx2
    assert avx2_speedup == 8.0
    print(f"[check] AVX2 instruction speedup for {N} int32 = {avx2_speedup:.0f}x:  OK")
    return avx2_speedup


# ----------------------------------------------------------------------------
# SECTION D: cache efficiency -- contiguous column reads vs strided rows
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: cache efficiency -- columnar reads are prefetcher-friendly")
    print(f"Cache line = {CACHE_LINE_BYTES} bytes. The CPU loads memory in these")
    print("chunks. Useful bytes = the column values you actually need.\n")
    print(f"Wider table for this analysis: columns {TABLE_COLUMNS}, each int32 "
          f"({INT32_BYTES} B). Row = {ROW_BYTES_WIDE} B.\n")

    print(f"To process column 'a' for {N} rows:\n")
    print(f"  {'layout':<22} {'bytes loaded':>13} {'cache lines':>11} "
          f"{'useful (a)':>11} {'utilization':>12}")
    print(f"  {'-'*22} {'-'*13} {'-'*11} {'-'*11} {'-'*12}")

    # row store: must load every full row to reach column a
    row_loaded = N * ROW_BYTES_WIDE
    row_lines = cache_lines_for(row_loaded)
    row_useful = N * INT32_BYTES
    row_util = row_useful / row_loaded
    print(f"  {'row store (a,b,c,d)':<22} {row_loaded:>13} {row_lines:>11} "
          f"{row_useful:>11} {pct(row_util):>12}")

    # column store: column a is contiguous
    col_loaded = cache_lines_for(N * INT32_BYTES) * CACHE_LINE_BYTES
    col_lines = cache_lines_for(N * INT32_BYTES)
    col_useful = N * INT32_BYTES
    col_util = col_useful / col_loaded
    print(f"  {'column store':<22} {col_loaded:>13} {col_lines:>11} "
          f"{col_useful:>11} {pct(col_util):>12}")
    print()

    print("  row store loads b, c, d for every row even though the query only")
    print(f"  needs column a. {row_loaded} bytes loaded, {row_useful} useful "
          f"-> {pct(row_util)} utilization, {row_loaded-row_useful} bytes WASTED.")
    print(f"  column store reads a0..a{N-1} contiguously; the loaded cache line is")
    print("  ALL column-a data (the trailing bytes belong to the next batch of")
    print("  'a', which the prefetcher streams in anyway). ~100% relevant.\n")

    # scale to realistic vector
    big = 2048
    print(f"At vector size {big} (scan column 'a' over {big} rows):")
    rb = big * ROW_BYTES_WIDE
    cb = big * INT32_BYTES
    print(f"  row store    : {rb:>7,} bytes = {cache_lines_for(rb):>4} cache lines, "
          f"useful {cb:>6,} -> {pct(cb/rb)} utilization")
    print(f"  column store : {cb:>7,} bytes = {cache_lines_for(cb):>4} cache lines, "
          f"useful {cb:>6,} -> 100% utilization")
    ratio = rb / cb
    print(f"\n  -> column store touches {rb/cb:.0f}x FEWER bytes for a single-column")
    print(f"     scan ({rb:,} -> {cb:,}). That is {len(TABLE_COLUMNS)}x = the number")
    print("     of columns you skip. More columns in the row = bigger win.\n")
    assert ratio == len(TABLE_COLUMNS)
    print(f"[check] row/column byte ratio == #columns ({len(TABLE_COLUMNS)}):  OK")
    return ratio


# ----------------------------------------------------------------------------
# SECTION E: selection vectors -- pass indices, not copied data
# ----------------------------------------------------------------------------

def section_e(sel):
    banner("SECTION E: selection vectors -- pass indices, not copied data")
    print("After Filter, two ways to hand survivors to Add/Multiply:\n")
    print("  (1) MATERIALIZE: compact the surviving column values into new arrays.")
    print("  (2) SELECTION VECTOR: keep the ORIGINAL arrays, pass a list of INDICES.\n")

    n_pass = len(sel)
    print(f"Filter a > {THRESHOLD} on {N} rows -> {n_pass} survivors, sel = {sel}\n")

    print("The tiny worked example (2 output columns a, b; int32):")
    mat_bytes = n_pass * 2 * INT32_BYTES
    sel_bytes_u16 = n_pass * 2            # uint16 indices
    sel_bytes_u32 = n_pass * INT32_BYTES  # uint32 indices
    print(f"  materialize a,b : copy {n_pass} values x 2 cols x {INT32_BYTES} B "
          f"= {mat_bytes} bytes")
    print(f"  selection vector: {n_pass} indices x 2 B (uint16) = {sel_bytes_u16} bytes"
          f"   -> {mat_bytes/sel_bytes_u16:.0f}x less data movement")
    print(f"  selection vector: {n_pass} indices x {INT32_BYTES} B (uint32) "
          f"= {sel_bytes_u32} bytes   -> {mat_bytes/sel_bytes_u32:.0f}x less\n")

    big = 2048
    big_pass = big // 2
    print(f"At vector size {big}, selectivity 50% -> {big_pass} survivors:")
    mat_big = big_pass * 2 * INT32_BYTES
    sel_big_u16 = big_pass * 2
    print(f"  materialize a,b : {mat_big:>6,} bytes copied")
    print(f"  selection vector: {sel_big_u16:>6,} bytes (uint16)  -> "
          f"{mat_big/sel_big_u16:.0f}x less\n")

    print("Why indices beat copies:")
    print("  - the filter writes a small, dense buffer of positions (branchless:")
    print("    on match, append the index; no per-value branch mispredict cost).")
    print("  - downstream ops GATHER from the originals only at those indices, so")
    print("    you never touch/compute on rejected values.")
    print("  - the SAME sel vector flows through the whole pipeline (Add, Multiply,")
    print("    Project all reuse it) -- one filter, many consumers.\n")
    print("  Real engines (DuckDB, ClickHouse) use uint16 sel vectors for batches")
    print("  up to 65536, and uint32 beyond. Batch sizes are typically 1024-2048.\n")
    assert mat_bytes / sel_bytes_u16 == 4.0
    print("[check] materialize/selvec byte ratio (tiny, uint16) == 4x:  OK")


# ----------------------------------------------------------------------------
# SECTION F: late materialization -- fetch column b only for survivors
# ----------------------------------------------------------------------------

def section_f(sel):
    banner("SECTION F: late materialization -- defer the read of column b")
    print("Query: SELECT a+b, a*b FROM t WHERE a > 5  (needs column a AND b).\n")
    print("  EARLY materialization: read ALL of column a AND ALL of column b,")
    print("    THEN filter. You fetched b for rows that the filter later rejects.\n")
    print("  LATE materialization: read column a, filter -> sel, THEN read column b")
    print("    ONLY at the surviving indices. b is never fetched for rejected rows.\n")

    n_pass = len(sel)
    sel_frac = selectivity(A, THRESHOLD)
    print(f"Our {N} rows, selectivity = {n_pass}/{N} = {pct(sel_frac)}:\n")
    early_vals = N + N                  # full column a + full column b
    late_vals = N + n_pass             # full column a + b only at sel
    print(f"  {'strategy':<16} {'column a':>10} {'column b':>10} {'total values':>13} "
          f"{'bytes':>7}")
    print(f"  {'-'*16} {'-'*10} {'-'*10} {'-'*13} {'-'*7}")
    print(f"  {'early mat.':<16} {N:>10} {N:>10} {early_vals:>13} "
          f"{early_vals*INT32_BYTES:>7}")
    print(f"  {'late mat.':<16} {N:>10} {n_pass:>10} {late_vals:>13} "
          f"{late_vals*INT32_BYTES:>7}")
    saved = early_vals - late_vals
    print(f"\n  late materialization reads {late_vals} values vs early's "
          f"{early_vals} -> saves {saved} values = {pct(saved/early_vals)} of I/O.\n")

    # scale: wider table, lower selectivity
    print("Where it shines -- a wide table (10 columns), low selectivity:")
    ncols = 10
    for s in [0.5, 0.1, 0.01]:
        early = ncols                       # read all 10 full columns
        late = 1 + (ncols - 1) * s          # 1 predicate col + sel*(9 others)
        print(f"  selectivity {pct(s):>5}: early {early:.1f} col-equiv, "
              f"late {late:.2f} col-equiv -> {(early-late)/early*100:>5.1f}% I/O saved")
    print()
    print("The lower the selectivity, the bigger the win: you read a TINY fraction")
    print("of the non-predicate columns. This is impossible in a row store, where")
    print("reading one column means reading them all (the whole row is one unit).\n")
    assert late_vals == 12 and early_vals == 16
    print(f"[check] late reads 12 values vs early 16 (saves {saved} = 25%):  OK")


# ============================================================================
# 4. GOLD CHECK -- Volcano and Vectorized produce IDENTICAL results
# ============================================================================

def gold_check():
    banner("GOLD CHECK -- Volcano and Vectorized agree on the result set")
    vol_results, vol_calls = volcano_execute(A, B, THRESHOLD)
    vec_results, vec_calls, sel = vectorized_execute(A, B, THRESHOLD)

    print(f"  Volcano    result = {vol_results}")
    print(f"  Vectorized result = {vec_results}")
    match = vol_results == vec_results
    print(f"\n  [check] result sets identical?  {match}\n")

    vol_total = sum(vol_calls.values())
    vec_total = sum(vec_calls.values())
    print(f"  Volcano    total calls = {vol_total}")
    print(f"  Vectorized total calls = {vec_total}")
    print(f"  call-count reduction   = {vol_total}/{vec_total} = "
          f"{vol_total/vec_total:.1f}x fewer\n")

    print("  Pinned facts (recomputed in vectorized_execution.html):")
    print(f"    selection vector   = {sel}")
    print(f"    a[sel]             = {fmt_vec([A[i] for i in sel])}")
    print(f"    b[sel]             = {fmt_vec([B[i] for i in sel])}")
    print(f"    a+b[sel]           = {fmt_vec([A[i]+B[i] for i in sel])}")
    print(f"    a*b[sel]           = {fmt_vec([A[i]*B[i] for i in sel])}")
    print(f"    result set         = {vec_results}")

    assert match, "results must match"
    assert sel == [1, 3, 4, 6]
    assert vec_results == [(27, 140), (48, 320), (56, 300), (79, 630)]
    assert vol_total == 20 and vec_total == 4
    print(f"\n[check] GOLD: identical results, sel=[1,3,4,6], "
          f"{vol_total}->{vec_total} calls:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("vectorized_execution.py - reference impl. All numbers below feed "
          "VECTORIZED_EXECUTION.md.")
    print(f"N={N}  A={A}  B={B}  query: SELECT a+b, a*b FROM t WHERE a>{THRESHOLD}")

    vol_results, _ = section_a()
    _, _, sel = section_b(vol_results)
    section_c()
    section_d()
    section_e(sel)
    section_f(sel)
    gold_check()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
