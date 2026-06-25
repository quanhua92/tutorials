"""
cost_estimation.py - Reference implementation of the query-optimizer cost
estimation model used by PostgreSQL: how statistics (pg_statistic) feed
cardinality (selectivity) estimates, which feed plan costs, which feed plan
enumeration.

This is the single source of truth that COST_ESTIMATION.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 cost_estimation.py

============================================================================
THE INTUITION (read this first) - the travel agent pricing a holiday
============================================================================
A query has many ways it COULD run (a "plan"): scan the whole table, or jump
through an index, or hash-join two tables, or sort-merge them... The OPTIMIZER
is a travel agent that must quote a price for EVERY option and book the
cheapest. Its currency is the COST UNIT, defined as the price of one sequential
page fetch (= 1.0). Everything else is priced relative to that:

  * reading the NEXT page in order        = 1.0    (seq_page_cost)   cheap
  * jumping to a RANDOM page              = 4.0    (random_page_cost) 4x dear
  * inspecting one tuple (CPU)            = 0.01   (cpu_tuple_cost)
  * comparing one index entry (CPU)       = 0.005  (cpu_index_cost)

To quote a price the agent must first GUESS HOW MANY ROWS the query returns
(the CARDINALITY). It cannot count them (that IS running the query). Instead it
reads a small SAMPLE the database keeps for every column: the STATISTICS, stored
in the catalog table pg_statistic (view pg_stats). Statistics are rebuilt by
ANALYZE. Four numbers per column do almost all the work:

  * most_common_vals / most_common_freqs (MCV) : the frequent values + their
    fractions. WHERE x = <hot value> -> use its frequency directly.
  * histogram_bounds                        : equal-depth buckets over the
    LESS-common values. WHERE x > c -> count buckets to the right of c.
  * n_distinct                              : number of distinct values.
    WHERE x = <rare value> -> 1 / n_distinct.
  * correlation                             : how physically sorted the column
    is on disk (-1..1). Decides whether an index scan reads pages in order
    (cheap, seq) or scattered (dear, random).

Pipeline (the whole tutorial in one line):
    ANALYZE -> pg_statistic -> selectivity -> cardinality -> plan cost
            -> enumerate plans -> pick min cost.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   cost unit     : the price of ONE sequential page fetch. Everything is in
                   these units. seq_page_cost == 1.0 by definition.
   startup cost  : cost spent before the FIRST output row (e.g. sort/spool).
   run cost      : cost to deliver ALL rows. TOTAL = startup + run.
   cardinality   : the estimated number of rows a step produces. The single
                   most important (and most error-prone) input to costing.
   selectivity   : fraction of rows a predicate keeps, in [0,1].
                   cardinality = selectivity * N.
   pg_statistic  : the catalog table holding per-column statistics. The user
                   view is pg_stats. ANALYZE refreshes it.
   MCV           : most-common-values + their frequencies. Hot values.
   histogram     : equal-depth bucket edges over the non-MCV values. Range
                   estimates read it. Default ~100 buckets (statistics_target).
   n_distinct    : distinct value count. Drives the "rare equality" estimate.
   correlation   : physical clustering of the column (-1..1). 1 = perfectly
                   sorted on disk, 0 = random order. Decides seq vs random I/O
                   pricing for an index scan. THE key index-scan dial.
   Mackert-Lohman: the formula estimating how many DISTINCT heap pages an index
                   scan touches when matches are scattered (with replacement).
   seqscan       : read every page of the table in order. Cost is fixed: it
                   does NOT depend on the predicate (always scans all).
   index scan    : traverse the index, then fetch matching heap tuples. Cost
                   SHRINKS as selectivity drops (fewer matches to fetch).
   join sel.     : for an equality join on key k, selectivity =
                   1 / max(ndistinct_k_left, ndistinct_k_right).
   DP (Selinger) : dynamic programming over subsets to find the cheapest join
                   order. Scales O(3^n); brute force is O(n!).

============================================================================
THE LINEAGE (sources)
============================================================================
   System R / Selinger (1979, "Access Path Selection...") : the cost model +
     DP join enumeration. Still the backbone of every relational optimizer.
   PostgreSQL optimizer : src/backend/optimizer/path/costsize.c (cost_seqscan,
     cost_index, cost_nestloop, cost_hashjoin, cost_mergejoin) +
     src/backend/utils/adt/selfuncs.c (eqsel, scalargtsel, the selectivity
     functions). The constants live in postgresql.conf.
   Ioannidis (1996, "The History of Optimizer") ; Selinger 1979 : cardinality
     estimation review.
   Mackert & Lohman (1986, "Index Caching...") : the pages_fetched formula for
     scattered index access (R random probes into P pages).

KEY FORMULAS (all asserted/printed in the sections below):
   cardinality            = selectivity * N
   eqsel(x=v)  in MCV     = freq(v)
   eqsel(x=v)  not in MCV = (1 - sum(mcv_freq) - nullfrac) / (ndistinct - n_mcv)
   rangesel(x > c)        = mcv_part(c) + hist_frac(c) * (1 - sum(mcv) - nullfrac)
   seqscan cost           = seq_page_cost * P + cpu_tuple_cost * N
   index scan cost        = io(correlation, pages) + cpu_index_cost*R + cpu_tuple_cost*R
   pages_scattered(R,P)   = P if R>=P else P*(1-(1-1/P)**R)        (Mackert-Lohman)
   pages_clustered(R,tpp) = ceil(R/tpp)
   nested loop cost       = outer + outer_rows * inner_per_row
   hash join cost         = build + probe           (build = smaller side)
   join selectivity       = 1 / max(ndistinct_left, ndistinct_right)
   DP                     : cheapest-plan(subset) = min over splits

Conventions:
   N              = 10,000 rows in the example table t (column x)
   TUPLES_PER_PAGE= 100      -> t occupies 100 heap pages
   statistics     : 100 nulls, 5 MCV values, 30-value uniform tail
   NBUCKETS       = 10  (reduced from the default 100 for readability)
"""

from __future__ import annotations

import math
from collections import Counter

BANNER = "=" * 72

# ============================================================================
# COST CONSTANTS (PostgreSQL defaults, in cost units; seq_page_cost = 1.0)
# ============================================================================
SEQ_PAGE_COST = 1.0      # one sequential page fetch (the unit)
RANDOM_PAGE_COST = 4.0   # one random page fetch (4x a sequential one)
CPU_TUPLE_COST = 0.01    # inspect one heap tuple
CPU_INDEX_COST = 0.005   # compare one index entry
TUPLES_PER_PAGE = 100    # rows per heap page -> table t = 100 pages

# ============================================================================
# THE EXAMPLE TABLE  (deterministic; ANALYZE would produce identical stats)
# ============================================================================
N_ROWS = 10000
NULL_COUNT = 100                      # -> nullfrac = 0.01
MCV_VALUES = [5, 10, 20, 1, 99]       # the "hot" values
MCV_COUNTS = [1500, 1000, 600, 500, 300]   # sum 3900
TAIL_FIRST = 100                      # tail = values 100..129, 30 distinct
TAIL_LAST = 129
TAIL_COUNT_EACH = 200                 # 30 * 200 = 6000
NBUCKETS = 10


def build_table():
    """Materialize the example table t(column x). Deterministic so ANALYZE-like
    statistics reproduce exactly on every run and in cost_estimation.html."""
    rows = [None] * NULL_COUNT
    for v, c in zip(MCV_VALUES, MCV_COUNTS):
        rows.extend([v] * c)
    for v in range(TAIL_FIRST, TAIL_LAST + 1):
        rows.extend([v] * TAIL_COUNT_EACH)
    return rows


class Stats:
    """The pg_statistic content for one column (the fields ANALYZE writes)."""

    def __init__(self, n_rows, null_count, mcv_values, mcv_counts,
                 tail_first, tail_last, tail_each, nbuckets):
        self.n_rows = n_rows
        self.nullfrac = null_count / n_rows
        non_null = n_rows - null_count
        # MCV frequencies are fractions of TOTAL rows (nulls in the denominator)
        self.mcv_values = list(mcv_values)
        self.mcv_freqs = [c / n_rows for c in mcv_counts]
        # distinct count over NON-NULL values
        self.n_mcv = len(mcv_values)
        n_tail = tail_last - tail_first + 1
        self.ndistinct = self.n_mcv + n_tail
        # histogram over the non-MCV values only (equal-depth buckets)
        tail_rows = []
        for v in range(tail_first, tail_last + 1):
            tail_rows.extend([v] * tail_each)
        tail_rows.sort()
        bucket = len(tail_rows) // nbuckets
        bounds = [tail_rows[k * bucket] for k in range(nbuckets)]
        bounds.append(tail_rows[-1])
        self.histogram_bounds = bounds
        self.tail_mass = 1.0 - sum(self.mcv_freqs) - self.nullfrac
        self.nbuckets = nbuckets

    def actual_count(self, pred):
        """Ground-truth row count for a predicate (used to score estimates)."""
        rows = build_table()
        return sum(1 for x in rows if x is not None and pred(x))


# ============================================================================
# SELECTIVITY ESTIMATORS (mirror PostgreSQL selfuncs.c: eqsel, scalargtsel)
# ============================================================================
def eqsel(st: Stats, val) -> float:
    """Selectivity of `x = val`.

    * If val is a most-common value -> use its stored frequency (exact-ish).
    * Otherwise -> spread the remaining non-null, non-MCV probability mass
      evenly across the remaining distinct values (uniformity assumption).
    This is the standard eqsel fallback (selfuncs.c, eqsel_internal).
    """
    for v, f in zip(st.mcv_values, st.mcv_freqs):
        if v == val:
            return f
    ndistinct_non_mcv = st.ndistinct - st.n_mcv
    return st.tail_mass / ndistinct_non_mcv


def rangesel_gt(st: Stats, val) -> float:
    """Selectivity of `x > val`, combining the MCV and the histogram.

      selectivity = (MCV rows with value > val)
                  + (histogram fraction to the right of val) * tail_mass

    The histogram fraction uses linear interpolation within the bucket that
    contains val (selfuncs.c, scalargtsel).
    """
    mcv_part = sum(f for v, f in zip(st.mcv_values, st.mcv_freqs) if v > val)
    b = st.histogram_bounds
    nb = st.nbuckets
    if val <= b[0]:
        hist_frac = 1.0
    elif val >= b[-1]:
        hist_frac = 0.0
    else:
        k = 0
        while not (b[k] <= val < b[k + 1]):
            k += 1
        width = b[k + 1] - b[k]
        in_bucket = (b[k + 1] - val) / width if width else 0.0
        hist_frac = (nb - k - 1 + in_bucket) / nb
    return mcv_part + hist_frac * st.tail_mass


# ============================================================================
# COST MODELS (mirror PostgreSQL costsize.c, simplified for teaching)
# ============================================================================
def cost_seqscan(n_rows: int, n_pages: int) -> float:
    """SeqScan: read every page in order, inspect every tuple.

    cost = seq_page_cost * pages + cpu_tuple_cost * rows
    Note: independent of any predicate - it always scans the whole table.
    """
    return SEQ_PAGE_COST * n_pages + CPU_TUPLE_COST * n_rows


def pages_scattered(n_result: int, n_pages: int) -> float:
    """Expected distinct heap pages touched by `n_result` scattered probes
    into `n_pages` pages (Mackert-Lohman). Caps at n_pages (you can't touch
    more pages than exist)."""
    if n_result >= n_pages:
        return float(n_pages)
    return n_pages * (1.0 - (1.0 - 1.0 / n_pages) ** n_result)


def pages_clustered(n_result: int, tpp: int = TUPLES_PER_PAGE) -> int:
    """Pages touched when matches are physically clustered (correlation ~ 1):
    matches pack onto consecutive pages, ~tpp per page."""
    return max(1, math.ceil(n_result / tpp))


def cost_indexscan(n_result: int, n_pages: int, correlation: float) -> float:
    """Index Scan: traverse the index, fetch matching heap tuples.

    The I/O cost blends by CORRELATION:
      correlation 1 (clustered)  -> matches are sequential -> seq_page_cost
      correlation 0 (scattered)  -> matches are random     -> random_page_cost
    CPU cost: one index comparison + one tuple inspect per matching row.
    """
    p_clust = pages_clustered(n_result)
    p_scatt = pages_scattered(n_result, n_pages)
    io = (correlation * SEQ_PAGE_COST * p_clust
          + (1.0 - correlation) * RANDOM_PAGE_COST * p_scatt)
    cpu = (CPU_INDEX_COST + CPU_TUPLE_COST) * n_result
    return io + cpu


def join_selectivity(nd_left: int, nd_right: int) -> float:
    """Selectivity of an equality join: 1 / max(ndistinct_left, ndistinct_right).
    (Assumes the keys line up, like a foreign key.)"""
    return 1.0 / max(nd_left, nd_right)


def cost_hashjoin(n_build_rows, n_probe_rows, n_result_rows,
                  build_scan_cost, probe_scan_cost) -> float:
    """Hash join: scan the smaller side and build a hash table, then scan the
    larger side and probe. CPU = build-insert + probe-compare + output."""
    build = build_scan_cost + CPU_TUPLE_COST * n_build_rows        # insert
    probe = probe_scan_cost + CPU_TUPLE_COST * n_probe_rows        # compare
    out = CPU_TUPLE_COST * n_result_rows                           # emit
    return build + probe + out


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_freq(f: float) -> str:
    return f"{f:.4f}"


# ============================================================================
# SECTION A: statistics (the pg_statistic structure for column x)
# ============================================================================
def section_a():
    banner("SECTION A: statistics - the pg_statistic structure for t(x)")
    rows = build_table()
    st = Stats(N_ROWS, NULL_COUNT, MCV_VALUES, MCV_COUNTS,
               TAIL_FIRST, TAIL_LAST, TAIL_COUNT_EACH, NBUCKETS)
    print(f"Table t: N = {N_ROWS:,} rows, column x (integer). "
          f"Tuples/page = {TUPLES_PER_PAGE} -> {N_ROWS // TUPLES_PER_PAGE} "
          "heap pages.\n")
    # verify the table is exactly as designed (self-consistency)
    assert len(rows) == N_ROWS
    assert rows.count(None) == NULL_COUNT
    assert len(set(v for v in rows if v is not None)) == st.ndistinct

    print("ANALYZE samples t and writes, for column x (catalog pg_statistic):\n")
    print("  starelid | staattnum | stainherit | stanullfrac | stakindN ...")
    print("  (per-column slot statistics). For x the slots are:\n")
    print(f"  stanullfrac   = {fmt_freq(st.nullfrac)}   "
          f"({NULL_COUNT} nulls / {N_ROWS} rows)")
    print(f"  stadistinct   = {st.ndistinct}   "
          f"(positive = absolute distinct-value count)\n")
    print("  [slot 1] most_common_vals / most_common_freqs (MCV):")
    print("     value |  count | frequency (count/N)")
    print("     ------+--------+------------------")
    for v, f in zip(st.mcv_values, st.mcv_freqs):
        print(f"     {v:>5} | {int(round(f*N_ROWS)):>6} | {fmt_freq(f)}")
    print(f"     ------+--------+------------------")
    print(f"     sum MCV freq = {fmt_freq(sum(st.mcv_freqs))}   "
          f"(covers {int(round(sum(st.mcv_freqs)*N_ROWS)):,} rows)")
    print()
    print(f"  [slot 2] histogram_bounds ({st.nbuckets} equal-depth buckets over "
          "the non-MCV values):")
    print(f"     {st.histogram_bounds}")
    print(f"     each bucket holds ~{TAIL_COUNT_EACH * (st.ndistinct - st.n_mcv) // st.nbuckets} "
          f"rows; bounds are the bucket edges (values where the row count "
          f"splits).")
    print(f"     histogram covers the non-MCV, non-null rows = "
          f"{fmt_freq(st.tail_mass)} of the table.\n")
    print("  [slot 3] correlation = rho in [-1, 1] (physical clustering).")
    print("     rho = 1 -> column is sorted on disk (index scans read pages")
    print("            in order, priced at seq_page_cost).")
    print("     rho = 0 -> random order (index scans jump around, priced at")
    print("            random_page_cost). The KEY index-scan dial (Section C).\n")
    print("CHECK: nullfrac + sum(MCV) + tail_mass should be ~1.0:")
    print(f"   {fmt_freq(st.nullfrac)} + {fmt_freq(sum(st.mcv_freqs))} + "
          f"{fmt_freq(st.tail_mass)} = "
          f"{fmt_freq(st.nullfrac + sum(st.mcv_freqs) + st.tail_mass)}")
    assert abs(st.nullfrac + sum(st.mcv_freqs) + st.tail_mass - 1.0) < 1e-9
    print("\n[check] probability masses sum to 1.0: OK")


# ============================================================================
# SECTION B: selectivity estimation (eqsel + rangesel)
# ============================================================================
def section_b():
    banner("SECTION B: selectivity estimation (eqsel, rangesel)")
    st = Stats(N_ROWS, NULL_COUNT, MCV_VALUES, MCV_COUNTS,
               TAIL_FIRST, TAIL_LAST, TAIL_COUNT_EACH, NBUCKETS)
    print("Rule: cardinality = selectivity * N.\n")

    print("(1) WHERE x = 5  -> 5 IS a most-common value -> use its frequency.")
    sel = eqsel(st, 5)
    est = sel * N_ROWS
    act = st.actual_count(lambda x: x == 5)
    print(f"    eqsel(x=5) = mcv_freq(5) = {fmt_freq(sel)}")
    print(f"    estimated rows = {fmt_freq(sel)} * {N_ROWS} = {est:.0f}")
    print(f"    actual rows    = {act}")
    print(f"    [check] estimate == actual: {'OK' if est == act else 'FAIL'}\n")

    print("(2) WHERE x = 100 -> 100 is NOT in MCV -> spread the remaining")
    print("    non-null, non-MCV mass evenly across the remaining distinct values.")
    sel = eqsel(st, 100)
    est = sel * N_ROWS
    act = st.actual_count(lambda x: x == 100)
    mass = st.tail_mass
    nd_nm = st.ndistinct - st.n_mcv
    print(f"    remaining mass = 1 - sum(mcv) - nullfrac "
          f"= 1 - {fmt_freq(sum(st.mcv_freqs))} - {fmt_freq(st.nullfrac)} "
          f"= {fmt_freq(mass)}")
    print(f"    remaining distinct = ndistinct - n_mcv = {st.ndistinct} - "
          f"{st.n_mcv} = {nd_nm}")
    print(f"    eqsel(x=100) = {fmt_freq(mass)} / {nd_nm} = {fmt_freq(sel)}")
    print(f"    estimated rows = {fmt_freq(sel)} * {N_ROWS} = {est:.0f}")
    print(f"    actual rows    = {act}  (value 100 appears {TAIL_COUNT_EACH}x)")
    print(f"    [check] estimate == actual: {'OK' if est == act else 'FAIL'}\n")

    print("(3) WHERE x = 537 -> not in MCV, not even in the table -> same")
    print("    rare-equality formula (the optimizer cannot tell 'absent' from 'rare').")
    sel = eqsel(st, 537)
    est = sel * N_ROWS
    act = st.actual_count(lambda x: x == 537)
    print(f"    eqsel(x=537) = {fmt_freq(mass)} / {nd_nm} = {fmt_freq(sel)}")
    print(f"    estimated rows = {est:.1f}   actual rows = {act}")
    print(f"    -> estimate is nonzero even though no row matches. This is the")
    print(f"       classic source of cardinality mis-estimation (a value unknown")
    print(f"       to ANALYZE is assumed 'as common as the average rare value').\n")

    print("(4) WHERE x > 115 -> use the histogram. 115 is a bucket edge.")
    sel = rangesel_gt(st, 115)
    est = sel * N_ROWS
    act = st.actual_count(lambda x: x > 115)
    b = st.histogram_bounds
    # 115 == bounds[5]; bucket 5 = [115,118) is fully > 115 by interpolation
    print(f"    histogram_bounds = {b}")
    print(f"    115 sits at bucket edge b[5]. Buckets fully to the right: "
          f"buckets 6..{st.nbuckets-1} = {st.nbuckets-1-5} buckets.")
    print(f"    bucket 5 [115,118): fraction > 115 = (118-115)/(118-115) = 1.0")
    print(f"    hist_frac = (4 full + 1.0) / {st.nbuckets} = 0.5")
    print(f"    mcv_part  = sum(MCV freqs for MCV > 115) = 0 "
          f"(MCV = {MCV_VALUES}, all < 115)")
    print(f"    rangesel(x>115) = 0 + 0.5 * {fmt_freq(st.tail_mass)} "
          f"= {fmt_freq(sel)}")
    print(f"    estimated rows = {fmt_freq(sel)} * {N_ROWS} = {est:.0f}")
    print(f"    actual rows    = {act}  (values 116..129 = "
          f"{TAIL_LAST - 115} values * {TAIL_COUNT_EACH})")
    print(f"    -> the estimate ({est:.0f}) slightly OVERSHOOTS actual ({act}):")
    print(f"       linear interpolation prices bucket 5 as fully matched, but the")
    print(f"       {TAIL_COUNT_EACH} rows equal to the edge value 115 should not be.")
    print(f"       Histograms are an APPROXIMATION; MCV-equality is exact.\n")

    print("(5) WHERE x > 100 -> whole histogram lies to the right.")
    sel = rangesel_gt(st, 100)
    est = sel * N_ROWS
    act = st.actual_count(lambda x: x > 100)
    print(f"    100 <= bounds[0] -> hist_frac = 1.0, mcv_part = 0")
    print(f"    rangesel(x>100) = 1.0 * {fmt_freq(st.tail_mass)} "
          f"= {fmt_freq(sel)}")
    print(f"    estimated rows = {est:.0f}   actual rows = {act}")
    print(f"    -> again an approximation (the {TAIL_COUNT_EACH} rows equal to")
    print(f"       100 are excluded by '>', but the edge bucket counts them in).")


# ============================================================================
# SECTION C: the cost model (seqscan vs index scan; the correlation dial)
# ============================================================================
def section_c():
    banner("SECTION C: the cost model - seqscan vs index scan")
    n_pages = N_ROWS // TUPLES_PER_PAGE     # 100
    print(f"Cost constants (cost units; seq_page_cost = 1.0 by definition):")
    print(f"  seq_page_cost   = {SEQ_PAGE_COST}")
    print(f"  random_page_cost= {RANDOM_PAGE_COST}   (a random fetch is "
          f"{RANDOM_PAGE_COST:.0f}x a sequential one)")
    print(f"  cpu_tuple_cost  = {CPU_TUPLE_COST}")
    print(f"  cpu_index_cost  = {CPU_INDEX_COST}\n")

    print(f"(1) SeqScan of t ({N_ROWS:,} rows, {n_pages} pages):")
    seq = cost_seqscan(N_ROWS, n_pages)
    print(f"    cost = seq_page_cost * P + cpu_tuple_cost * N")
    print(f"         = {SEQ_PAGE_COST} * {n_pages} + {CPU_TUPLE_COST} * {N_ROWS}")
    print(f"         = {SEQ_PAGE_COST*n_pages:.0f} + {CPU_TUPLE_COST*N_ROWS:.0f} "
          f"= {seq:.1f}\n")
    print(f"    This is FIXED regardless of the predicate: a seqscan always reads")
    print(f"    every page. So the seqscan cost is the bar every index scan must")
    print(f"    beat.\n")

    print(f"(2) Index Scan for WHERE x = 5 (R = 1500 matching rows), rho = 0:")
    R = 1500
    ps = pages_scattered(R, n_pages)
    ci0 = cost_indexscan(R, n_pages, 0.0)
    print(f"    matches scattered -> pages_scattered = P*(1-(1-1/P)^R)")
    print(f"        = {n_pages}*(1-(1-1/{n_pages})^{R}) = {ps:.1f} pages "
          f"(>= P -> capped at {n_pages})")
    print(f"    io = random_page_cost * {ps:.0f} = {RANDOM_PAGE_COST*ps:.0f}")
    print(f"    cpu = (cpu_index_cost + cpu_tuple_cost) * R "
          f"= {(CPU_INDEX_COST+CPU_TUPLE_COST)} * {R} = "
          f"{(CPU_INDEX_COST+CPU_TUPLE_COST)*R:.1f}")
    print(f"    index scan cost (rho=0) = {ci0:.1f}   vs seqscan {seq:.1f} -> "
          f"{'INDEX' if ci0 < seq else 'SEQSCAN'} wins (15% selectivity is too "
          f"coarse for an uncorrelated index)\n")

    print(f"(3) Same query, but the index is clustered (rho = 1):")
    pc = pages_clustered(R)
    ci1 = cost_indexscan(R, n_pages, 1.0)
    print(f"    matches clustered -> pages_clustered = ceil(R/tpp) "
          f"= ceil({R}/{TUPLES_PER_PAGE}) = {pc} pages")
    print(f"    io = seq_page_cost * {pc} = {SEQ_PAGE_COST*pc:.0f}  (sequential!)")
    print(f"    index scan cost (rho=1) = {ci1:.1f}   vs seqscan {seq:.1f} -> "
          f"{'INDEX' if ci1 < seq else 'SEQSCAN'} wins")
    print(f"    -> correlation flips the verdict: a clustered index makes 1500")
    print(f"       matches cheap (1 sequential page each); a scattered one pays 4x.\n")

    print(f"(4) Break-even: at what R does the UNCORRELATED index beat seqscan?")
    print(f"    cost_indexscan(R, rho=0) < {seq:.0f}\n")
    print(f"    | selectivity | R (rows) | pages_scattered | index cost | winner  |")
    print(f"    |-------------|----------|-----------------|------------|---------|")
    for frac in [0.0001, 0.001, 0.005, 0.007, 0.01, 0.05, 0.15, 1.0]:
        r = max(1, int(round(frac * N_ROWS)))
        ps2 = pages_scattered(r, n_pages)
        c = cost_indexscan(r, n_pages, 0.0)
        win = "index" if c < seq else "SEQSCAN"
        print(f"    | {frac:>11.4f} | {r:>8} | {ps2:>15.1f} | {c:>10.1f} | "
              f"{win:<7} |")
    # find the largest R where uncorrelated index still wins
    be = 0
    for r in range(1, n_pages + 5):
        if cost_indexscan(r, n_pages, 0.0) < seq:
            be = r
    print(f"\n    -> uncorrelated index wins for R <= ~{be} "
          f"(selectivity ~{be/N_ROWS:.3f}, ~{be/N_ROWS*100:.1f}%).")
    print(f"    -> a CLUSTERED index (rho=1) wins until R ~= "
          f"{int(0.8*N_ROWS)} (80%+); correlation is the single biggest")
    print(f"       lever on index-scan cost. (The 'index wins below 5%' rule of")
    print(f"       thumb assumes partial correlation.)")
    # gold asserts
    assert cost_seqscan(N_ROWS, n_pages) == 200.0
    assert cost_indexscan(1500, n_pages, 0.0) == 422.5
    assert cost_indexscan(1500, n_pages, 1.0) == 37.5
    print("\n[check] seqscan=200.0, indexscan(1500,rho=0)=422.5, "
          "indexscan(1500,rho=1)=37.5: OK")


# ============================================================================
# SECTION D: join cost (nested loop vs hash vs merge)
# ============================================================================
def section_d():
    banner("SECTION D: join cost - nested loop vs hash vs merge")
    # Two tables: ORDERS (big) joins CUSTOMERS (small) on customer_id.
    n_o, pp_o = 10000, 100      # orders: 10000 rows, 100 pages
    n_c, pp_c = 1000, 10        # customers: 1000 rows, 10 pages
    nd_key = 1000               # customer_id distinct on both sides (FK)
    scan_o = cost_seqscan(n_o, pp_o)     # 200
    scan_c = cost_seqscan(n_c, pp_c)     # 20
    j_sel = join_selectivity(nd_key, nd_key)          # 1/1000
    j_rows = round(n_o * n_c * j_sel)                 # 10000
    # inner per-row probe cost: point index lookup on customers(id) = 1 match
    probe = RANDOM_PAGE_COST + CPU_INDEX_COST + CPU_TUPLE_COST   # ~4.015

    print(f"Join: ORDERS({n_o:,} rows, {pp_o} pages) "
          f"⋈ CUSTOMERS({n_c:,} rows, {pp_c} pages) on customer_id.\n")
    print(f"  seqscan(orders)   = {scan_o:.1f}")
    print(f"  seqscan(customers)= {scan_c:.1f}")
    print(f"  join selectivity  = 1/max({nd_key},{nd_key}) = {j_sel}")
    print(f"  join cardinality  = {n_o}*{n_c}*{j_sel} = {j_rows:,} rows\n")
    print(f"  point index probe on customers = random_page_cost + cpu_index + "
          f"cpu_tuple = {probe:.3f}\n")

    print("(1) NESTED LOOP  cost = outer + outer_rows * inner_per_row")
    nl_big = scan_o + n_o * probe
    nl_small = scan_c + n_c * probe
    print(f"    ORDERS outer: {scan_o:.0f} + {n_o} * {probe:.3f} = {nl_big:.0f}")
    print(f"    CUSTOMERS outer: {scan_c:.0f} + {n_c} * {probe:.3f} = "
          f"{nl_small:.0f}   <- put the SMALL table outside\n")
    print(f"    best nested loop = {min(nl_big, nl_small):.0f} "
          f"(CUSTOMERS outer). NL cost scales with outer_rows * inner_probe, so")
    print(f"    it blows up on a big outer table.\n")

    print("(2) HASH JOIN  cost = build(smaller) + probe(larger) + output")
    hj = cost_hashjoin(n_c, n_o, j_rows, scan_c, scan_o)
    build = scan_c + CPU_TUPLE_COST * n_c
    probe_ = scan_o + CPU_TUPLE_COST * n_o
    out = CPU_TUPLE_COST * j_rows
    print(f"    build (customers): {scan_c:.0f} + {CPU_TUPLE_COST}*{n_c} "
          f"= {build:.0f}")
    print(f"    probe (orders)  : {scan_o:.0f} + {CPU_TUPLE_COST}*{n_o} "
          f"= {probe_:.0f}")
    print(f"    output          : {CPU_TUPLE_COST}*{j_rows} = {out:.0f}")
    print(f"    hash join = {build:.0f} + {probe_:.0f} + {out:.0f} = {hj:.0f}")
    print(f"    -> each side is scanned ONCE. Cost does NOT multiply. This is why")
    print(f"       hash join destroys nested loop on large inputs.\n")

    print("(3) MERGE JOIN  cost = sort(both) + merge   (if inputs not pre-sorted)")
    def sort_cost(n, pp):
        # external sort: ~1.5*N*log2(N) comparisons + 2 passes over the pages
        return (CPU_TUPLE_COST * n * math.log2(max(2, n)) * 1.5
                + 2 * SEQ_PAGE_COST * pp)
    so = sort_cost(n_o, pp_o)
    sc = sort_cost(n_c, pp_c)
    merge = scan_o + scan_c + CPU_TUPLE_COST * (n_o + n_c + j_rows)
    mj = so + sc + merge
    print(f"    sort(orders)   = {so:.0f}")
    print(f"    sort(customers)= {sc:.0f}")
    print(f"    merge step     = {merge:.0f}")
    print(f"    merge join (with explicit sort) = {mj:.0f}")
    print(f"    -> if both sides already have sorted indexes, skip the sorts and")
    print(f"       merge join drops to ~{merge:.0f} (competitive with hash).\n")

    print("COMPARISON (lower is cheaper):")
    print(f"  | plan                         |   cost | winner?           |")
    print(f"  |------------------------------|--------|-------------------|")
    print(f"  | nested loop (orders outer)   | {nl_big:>6.0f} | (terrible)        |")
    print(f"  | nested loop (customers outer)| {nl_small:>6.0f} |                   |")
    print(f"  | merge join (with sort)       | {mj:>6.0f} |                   |")
    print(f"  | hash join                    | {hj:>6.0f} | WINNER            |")
    print(f"\n  Hash join wins: both sides scanned once, no per-row random probe,")
    print(f"  no sort. (PostgreSQL also has a 'parallel' / 'hybrid' hash join.)")
    assert hj < mj < nl_small
    print("\n[check] hash join < merge+sort < best nested loop: OK")


# ============================================================================
# SECTION E: plan enumeration (DP over join orders)
# ============================================================================
def section_e():
    banner("SECTION E: plan enumeration - DP over join orders (Selinger)")
    # Three tables: A(10000) - B(1000) - C(100), chain join A-B-C.
    sizes = {"A": 10000, "B": 1000, "C": 100}
    pages = {t: sizes[t] // TUPLES_PER_PAGE for t in sizes}      # 100,10,1
    scan = {t: cost_seqscan(sizes[t], pages[t]) for t in sizes}  # 200,20,2
    # join graph (predicates): A-B on key with ndistinct 10000, B-C with 1000.
    preds = {frozenset("AB"): 10000, frozenset("BC"): 1000}
    # AC has no predicate -> cartesian

    def j_sel(s):
        return preds.get(s)  # None means cartesian

    def join_card(s1, s2):
        key = frozenset(s1) | frozenset(s2)
        p = j_sel(frozenset(set(s1) & set(s2))) if set(s1) & set(s2) else None
        # use the predicate between the two sides if present
        inter = set(s1) & set(s2)
        p = None
        for k in preds:
            if (set(k) & set(s1)) and (set(k) & set(s2)):
                p = preds[k]
        if p is None:
            return sizes_lookup(s1) * sizes_lookup(s2)   # cartesian
        return round(sizes_lookup(s1) * sizes_lookup(s2) / p)

    def sizes_lookup(s):
        return math.prod(sizes[t] for t in s)

    def hashjoin_cost(left_cost, left_card, right_cost, right_card,
                      result_card, pred_nd):
        """Cost of hash-joining two already-costed sub-results."""
        build = left_cost + CPU_TUPLE_COST * left_card
        probe = right_cost + CPU_TUPLE_COST * right_card
        out = CPU_TUPLE_COST * result_card
        return build + probe + out

    print("Three tables, chain join  A(10000) -- B(1000) -- C(100):")
    print(f"  base scan costs: A={scan['A']:.0f}, B={scan['B']:.0f}, "
          f"C={scan['C']:.0f}")
    print(f"  predicates: A-B (ndistinct 10000), B-C (ndistinct 1000); "
          f"A-C has NO predicate (cartesian).\n")

    # ---- BRUTE FORCE: all 3! = 6 left-deep orderings ----
    import itertools
    print("(1) BRUTE FORCE: evaluate all 3! = 6 left-deep orderings.\n")
    print("  | order      | step 1            | step 2            |  total cost |")
    print("  |------------|-------------------|-------------------|-------------|")
    brute = {}
    for order in itertools.permutations("ABC"):
        t1, t2, t3 = order
        # step 1: join t1,t2
        c1_cost = hashjoin_cost(scan[t1], sizes[t1], scan[t2], sizes[t2],
                                join_card(t1, t2), preds.get(frozenset(t1 + t2)))
        c1_card = join_card(t1, t2)
        cartesian1 = frozenset(t1 + t2) not in preds
        # step 2: join (t1t2) with t3
        between = set(t1 + t2) & set(t3)
        p2 = None
        for k in preds:
            if (set(k) & set(t1 + t2)) and (set(k) & set(t3)):
                p2 = preds[k]
        c2_card = round(c1_card * sizes[t3] / p2) if p2 else c1_card * sizes[t3]
        c2_cost = hashjoin_cost(c1_cost, c1_card, scan[t3], sizes[t3],
                                c2_card, p2)
        tag = "CARTESIAN" if (cartesian1 or p2 is None) else ""
        brute[order] = c2_cost
        print(f"  | {t1}->{t2}->{t3}       | ({t1}⋈{t2}) "
              f"{'x' if cartesian1 else '='} {c1_card:<7} ({c1_cost:>5.0f})| "
              f"(⋈{t3}) = {c2_card:<7} ({c2_cost:>5.0f})| {tag:<11} |")
    best_bf = min(brute, key=brute.get)
    print(f"\n  cheapest brute-force order: {best_bf[0]}->{best_bf[1]}->"
          f"{best_bf[2]}  cost = {brute[best_bf]:.0f}\n")

    # ---- DP over subsets (Selinger) ----
    print("(2) DYNAMIC PROGRAMMING over subsets (what real optimizers do):\n")
    print("  Level 1 (base relations):")
    print(f"    {{A}} = {scan['A']:.0f}  (10000 rows)")
    print(f"    {{B}} = {scan['B']:.0f}  (1000 rows)")
    print(f"    {{C}} = {scan['C']:.0f}  (100 rows)\n")

    # level 2
    pairs = [("AB", "A", "B"), ("BC", "B", "C"), ("AC", "A", "C")]
    best = {  # subset-string -> (cost, card)
        "A": (scan["A"], 10000), "B": (scan["B"], 1000), "C": (scan["C"], 100),
    }
    print("  Level 2 (pairs):")
    for pair, a, b in pairs:
        p = preds.get(frozenset(pair))
        card = round(sizes[a] * sizes[b] / p) if p else sizes[a] * sizes[b]
        cost = hashjoin_cost(scan[a], sizes[a], scan[b], sizes[b], card, p)
        best[pair] = (cost, card)
        tag = "" if p else "  <- CARTESIAN (no predicate), pruned later"
        print(f"    {{{a},{b}}} = {cost:.0f}  ({card:,} rows){tag}")
    print()

    # level 3: {A,B,C} = min over the three 2+1 splits
    print("  Level 3 ({A,B,C}) - try each 2-subset joined with the leftover:")
    splits = [("AB", "C"), ("AC", "B"), ("BC", "A")]
    dp3 = {}
    for two, one in splits:
        # predicate between the two-subset and `one`
        p = None
        for k in preds:
            if (set(k) & set(two)) and (set(k) & set(one)):
                p = preds[k]
        c2, card2 = best[two]
        card3 = round(card2 * sizes[one] / p) if p else card2 * sizes[one]
        cost3 = hashjoin_cost(c2, card2, scan[one], sizes[one], card3, p)
        dp3[(two, one)] = (cost3, card3)
        tag = "" if p else "  <- cartesian, dominated"
        print(f"    ({{{two}}}) join {one}: {c2:.0f} -> {cost3:.0f}  "
              f"({card3:,} rows){tag}")
    best_split = min(dp3, key=lambda k: dp3[k][0])
    print(f"\n  DP cheapest: ({{{best_split[0]}}}) join {best_split[1]}  "
          f"cost = {dp3[best_split][0]:.0f}\n")

    print("(3) WHY DP? It scales far better than brute force:")
    print("  | tables n | brute force (n!) | DP subsets (~3^n) |")
    print("  |----------|------------------|-------------------|")
    for n in [3, 5, 8, 10, 15]:
        print(f"  | {n:>8} | {math.factorial(n):>16,} | "
              f"{3**n:>17,} |")
    print("\n  At n=10 brute force is 3.6M orderings; DP is ~59K subsets. At n=15")
    print("  brute force is hopeless; DP still finishes. PostgreSQL also caps DP")
    print("  with geqo_threshold (default 12): above it, switches to a genetic")
    print("  search. DP also prunes cartesian sub-joins (no predicate) early.\n")

    # gold: DP result matches brute-force best
    assert abs(dp3[best_split][0] - brute[best_bf]) < 1e-6
    assert best_split == ("BC", "A") or best_split == ("CB", "A") \
        or set(best_split[0]) == {"B", "C"}
    print(f"[check] DP cheapest ({dp3[best_split][0]:.0f}) == brute-force "
          f"cheapest ({brute[best_bf]:.0f}): OK")


# ============================================================================
# main
# ============================================================================
def main():
    print("cost_estimation.py - reference impl. All numbers feed "
          "COST_ESTIMATION.md.")
    print(f"N = {N_ROWS:,} rows ; seq_page_cost = {SEQ_PAGE_COST} ; "
          f"pure Python stdlib.\n")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()

    banner("GOLD-CHECK SUMMARY (pinned for cost_estimation.html)")
    st = Stats(N_ROWS, NULL_COUNT, MCV_VALUES, MCV_COUNTS,
               TAIL_FIRST, TAIL_LAST, TAIL_COUNT_EACH, NBUCKETS)
    g_eq5 = eqsel(st, 5) * N_ROWS
    g_eq100 = eqsel(st, 100) * N_ROWS
    g_seq = cost_seqscan(N_ROWS, N_ROWS // TUPLES_PER_PAGE)
    g_idx0 = cost_indexscan(1500, N_ROWS // TUPLES_PER_PAGE, 0.0)
    g_idx1 = cost_indexscan(1500, N_ROWS // TUPLES_PER_PAGE, 1.0)
    print(f"  eqsel(x=5)*N   = {g_eq5:.0f}   (actual {st.actual_count(lambda x: x==5)})")
    print(f"  eqsel(x=100)*N = {g_eq100:.0f}  (actual {st.actual_count(lambda x: x==100)})")
    print(f"  seqscan(t)     = {g_seq:.1f}")
    print(f"  indexscan(R=1500, rho=0) = {g_idx0:.1f}")
    print(f"  indexscan(R=1500, rho=1) = {g_idx1:.1f}")
    assert g_eq5 == 1500 and g_eq100 == 200
    assert g_seq == 200.0 and g_idx0 == 422.5 and g_idx1 == 37.5
    print("\n[check] all GOLD values reproduce: OK")

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
