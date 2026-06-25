"""
aggregation_pipeline.py - Reference implementation of how a database engine
EXECUTES GROUP BY / HAVING / aggregate functions (COUNT, SUM, AVG, MIN, MAX),
covering both execution strategies (sort-based and hash-based) and the four
things built on top of them (HAVING, DISTINCT, work_mem spilling, parallel
partial aggregation).

This is the single source of truth that AGGREGATION_PIPELINE.md is built from.
Every table, hash bucket, and worked number in the guide is printed by this
file. If you change something here, re-run and re-paste the output.

Run:
    python3 aggregation_pipeline.py

=========================================================================
THE INTUITION (read this first) -- the tally sheet vs the pigeonholes
=========================================================================
You ask the database:

    SELECT region, COUNT(*), SUM(total)
    FROM sales
    GROUP BY region;

That GROUP BY clause is a *contract* ("give me one row per region, with the
columns folded together by region") -- it says NOTHING about how to compute it.
Two completely different machines can honour that contract:

  * SORT-BASED  : sort all rows by region (so all the North rows are together,
                 then all the South rows, ...). Now a SINGLE linear scan is
                 enough: keep a running tally for the *current* region; the
                 instant the region changes, emit the finished tally and start
                 a fresh one for the new region. One accumulator, O(1) memory
                 per group (in scan order).

  * HASH-BASED  : skip the sort. For every row, HASH its region into a number
                 and drop it into a bucket. Each bucket holds a small list of
                 (region -> running tally). Already-seen region? update its
                 tally. New region? append a fresh tally. O(distinct groups)
                 memory, no sort cost.

The answer is IDENTICAL either way. The planner just picks whichever is cheaper:

  - few distinct groups + the data is already sorted -> SORT-BASED
    (the sort is "free" if an index already gives the order).
  - many rows, not pre-sorted, and the distinct groups fit in memory -> HASH
    (avoids an O(N log N) sort entirely).

WHEN HASH OVERFLOWS (work_mem): if the distinct groups do NOT all fit in the
hash table (it exceeds work_mem), PostgreSQL does NOT give up on hashing. It
PARTITIONS the rows by a higher hash bit into BATCHES, spills the non-current
batches to a temp file on disk, and re-probes each batch separately -- so even
a 100 GB aggregation runs in bounded memory. (Section E.)

=========================================================================
PLAIN-ENGLISH GLOSSARY
=========================================================================
  GROUP BY key   : the column(s) we collapse on (here: `region`). Rows that
                   share the key form one GROUP.
  aggregate fn   : COUNT, SUM, AVG, MIN, MAX -- the per-group fold. Each has a
                   `transfunc` (fold one row) and `finalfunc` (turn the running
                   state into the output value; AVG = sum/count at the end).
  accumulator    : the per-group running state. Here {count, sum, min, max}.
                   One of these lives per distinct group.
  sort-based agg : sort the input by the GROUP BY key, then a single ordered
                   scan accumulating per group; EMIT a group when its key ends.
  hash-based agg : hash each row's group key into a bucket of accumulators;
                   no sort. New key -> new accumulator; seen key -> update.
  HAVING         : a WHERE that runs AFTER aggregation (filters whole GROUPS,
                   not rows). `HAVING SUM(total) > 1000` keeps only big groups.
  DISTINCT       : `SELECT DISTINCT region` collapses duplicate regions. The
                   engine implements it with the EXACT SAME machinery as GROUP
                   BY (a hash or sort that discards repeat keys) -- just with
                   no aggregate functions attached.
  work_mem       : the per-operation RAM budget (PostgreSQL: default 4 MB). The
                   hash table must fit in it; if it doesn't, we SPILL.
  spill / batch  : when the hash table exceeds work_mem, partition rows by a
                   hash bit into nbatches; keep batch 0 in memory, write the
                   rest to temp files; process each batch in turn.
  partial agg    : in a PARALLEL query, each worker aggregates its own slice
                   (a "partial" per region). The leader COMBINES the partials
                   per region with a `combinefunc` (sum adds, count adds,
                   min/max take the extreme). Two-phase, same answer.

=========================================================================
KEY FORMULAS (all verified in code below)
=========================================================================
  transfunc COUNT  : c + 1
  transfunc SUM    : s + total
  transfunc MIN    : min(curtotal, state)      (state starts at +inf)
  transfunc MAX    : max(curtotal, state)      (state starts at -inf)
  finalfunc AVG    : sum / count
  combinefunc COUNT: c0 + c1            (SUM likewise; MIN/MAX take extreme)
  bucket(region)   : hash(region) mod N_BUCKETS            (separate chaining)
  batch(region)    : (hash(region) >> 8) mod n_batches     (spill routing)
  GOLD CHECK       : sort_agg(region) == hash_agg(region)  for EVERY region,
                     EVERY aggregate -- strategy is invisible to the answer.
  Estimated memory : n_distinct_groups * GROUP_MEM_BYTES;  spill iff > work_mem.

Conventions:
  rows  : list of (id, region, product, total)  -- the input "sales" table.
  acc   : dict {"count","sum","min","max"}      -- one per distinct group.

The lineage (papers / docs):
  sort-based       : classic, CLRS mergesort + group-by scan. Every engine.
  hash-based       : DeWitt et al. "Implementation techniques for main memory
                     hash joins" & the hash-agg operator; PostgreSQL `HashAggregate`.
  hybrid/sort      : PostgreSQL `GroupAggregate` (sorted input, often from an
                     index scan or an explicit Sort node).
  parallel partial : PostgreSQL "Partial Aggregate" + "Final Aggregate" nodes
                     (combinefunc, since 10+). Docs: PostgreSQL §52.1 Pipeline.
=========================================================================
"""

from __future__ import annotations

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# DETERMINISTIC INPUT: 12 sales records. Seeded by hand so every run and the
# .html use byte-identical inputs. (id, region, product, total)
# ----------------------------------------------------------------------------
SALES = [
    (1,  "North", "Widget", 250),
    (2,  "South", "Gadget", 180),
    (3,  "East",  "Widget", 320),
    (4,  "West",  "Gadget", 150),
    (5,  "North", "Gadget", 410),
    (6,  "South", "Widget", 290),
    (7,  "East",  "Gadget", 280),
    (8,  "West",  "Widget", 540),
    (9,  "North", "Widget", 380),
    (10, "South", "Gadget", 175),
    (11, "East",  "Widget", 460),
    (12, "West",  "Gadget", 310),
]

N_BUCKETS = 8          # hash-table size for the hash-agg demo (Section B)
GROUP_MEM_BYTES = 80   # estimated bytes per in-memory group accumulator
WORK_MEM = 200         # demo work_mem (bytes) -- holds floor(200/80)=2 groups
HAVING_THRESHOLD = 1000  # demo HAVING SUM(total) > 1000


# ============================================================================
# 1. THE CORE PRIMITIVES
# ============================================================================

def hash_full(s: str) -> int:
    """Deterministic polynomial string hash (32-bit).

    Stable across runs and processes -- unlike Python's built-in hash() which
    is randomized by PYTHONHASHSEED. Replicated bit-for-bit in
    aggregation_pipeline.html so the JS bucket layout matches.
    """
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h


def bucket_of(region: str, n: int = N_BUCKETS) -> int:
    """In-table bucket for a group key (separate chaining)."""
    return hash_full(region) % n


def batch_of(region: str, n_batches: int) -> int:
    """Spill batch for a group key. Uses bits ABOVE the in-table bucketing
    (>> 8) so batch routing and bucket chaining are decorrelated."""
    return (hash_full(region) >> 8) % n_batches


def new_acc() -> dict:
    """Fresh per-group accumulator. state that MIN/MAX can update into."""
    return {"count": 0, "sum": 0, "min": None, "max": None}


def acc_update(acc: dict, total: int) -> None:
    """transfunc: fold ONE row's `total` into the accumulator."""
    acc["count"] += 1
    acc["sum"] += total
    acc["min"] = total if acc["min"] is None else min(acc["min"], total)
    acc["max"] = total if acc["max"] is None else max(acc["max"], total)


def acc_combine(a: dict, b: dict) -> dict:
    """combinefunc: merge two partial accumulators (parallel leader step)."""
    return {
        "count": a["count"] + b["count"],
        "sum": a["sum"] + b["sum"],
        "min": _extreme(a["min"], b["min"], min),
        "max": _extreme(a["max"], b["max"], max),
    }


def _extreme(x, y, fn):
    if x is None:
        return y
    if y is None:
        return x
    return fn(x, y)


def acc_avg(acc: dict):
    """finalfunc for AVG: sum / count."""
    return acc["sum"] / acc["count"] if acc["count"] else 0.0


# ---- the THREE execution strategies (all return the SAME shape) ------------

def aggregate_sort(rows) -> dict:
    """Sort-based GROUP BY: sort by key, single ordered scan, emit on key change."""
    out: dict[str, dict] = {}
    cur_key = None
    cur_acc = None
    for _id, region, _prod, total in sorted(rows, key=lambda r: r[1]):
        if region != cur_key:                       # key changed -> new group
            cur_key, cur_acc = region, new_acc()
            out[cur_key] = cur_acc
        acc_update(cur_acc, total)
    return out


def aggregate_hash(rows, n_buckets: int = N_BUCKETS) -> tuple[dict, list]:
    """Hash-based GROUP BY: hash key into bucket, separate chaining. Returns
    (results_dict, hash_table) where hash_table[bucket] = list of regions."""
    out: dict[str, dict] = {}
    table: list[list] = [[] for _ in range(n_buckets)]
    for _id, region, _prod, total in rows:
        b = bucket_of(region, n_buckets)
        chain = table[b]
        acc = out.get(region)
        if acc is None:                             # new group -> append to chain
            acc = new_acc()
            out[region] = acc
            chain.append(region)
        acc_update(acc, total)
    return out, table


def reference(rows) -> dict:
    """Canonical {region: acc} -- the plain dict-groupby used as GOLD."""
    out: dict[str, dict] = {}
    for _id, region, _prod, total in rows:
        acc_update(out.setdefault(region, new_acc()), total)
    return out


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_avg(acc) -> str:
    return f"{acc_avg(acc):.2f}"


def agg_table(out: dict, title: str = "Per-group result"):
    """Render a {region: acc} dict as a markdown table (verbatim-pasted into .md)."""
    print(f"\n{title}:")
    print("| region | COUNT(*) | SUM(total) | AVG(total) | MIN(total) | MAX(total) |")
    print("|--------|----------|------------|------------|------------|------------|")
    for region in sorted(out):
        a = out[region]
        print(f"| {region:<6} | {a['count']:<8} | {a['sum']:<10} | "
              f"{fmt_avg(a):<10} | {a['min']:<10} | {a['max']:<10} |")
    tot_c = sum(a["count"] for a in out.values())
    tot_s = sum(a["sum"] for a in out.values())
    print(f"| TOTAL  | {tot_c:<8} | {tot_s:<10} | {'':<10} | {'':<10} | {'':<10} |")


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: Sort-based aggregation
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: Sort-based aggregation  "
           "(sort by GROUP BY key, then a single ordered scan)")
    print("Query:  SELECT region, COUNT(*), SUM(total), AVG(total), MIN(total), MAX(total)")
    print("        FROM sales GROUP BY region")
    print()
    print("Two phases:")
    print("  1. SORT rows by the GROUP BY key (region).  (cost: O(N log N), or 0 if an")
    print("     index already yields this order -- an Index Scan / Sort node.)")
    print("  2. ONE linear scan. Keep a running accumulator for the CURRENT group;")
    print("     when the key changes, EMIT the finished group and start a new one.")
    print("     PostgreSQL calls this node GroupAggregate.\n")

    sorted_rows = sorted(SALES, key=lambda r: r[1])
    print("Phase 1 -- sorted input (stable sort by region; ties keep input order):")
    print("| step | id | region | product | total |")
    print("|------|----|--------|---------|-------|")
    for i, (rid, region, prod, total) in enumerate(sorted_rows, 1):
        print(f"| {i:<5}| {rid:<3}| {region:<7}| {prod:<8}| {total:<6}|")
    print()

    print("Phase 2 -- ordered scan, accumulator state after each row "
          "(>>> emit when key changes):")
    print("| step | id | region | total | -> action | acc.count | acc.sum |")
    print("|------|----|--------|-------|-----------|-----------|---------|")
    acc = new_acc()
    prev = None
    for i, (rid, region, _p, total) in enumerate(sorted_rows, 1):
        if prev is not None and region != prev:
            print(f"|      |    |        |       | >>> EMIT group '{prev}' done "
                  f"(count={acc['count']}, sum={acc['sum']})")
            acc = new_acc()
            action = f"start '{region}'"
        elif prev is None:
            action = f"start '{region}'"
        else:
            action = "fold row"
        acc_update(acc, total)
        print(f"| {i:<5}| {rid:<3}| {region:<7}| {total:<6}| {action:<10}| "
              f"{acc['count']:<10}| {acc['sum']:<8}|")
        prev = region
    print(f"|      |    |        |       | >>> EMIT group '{prev}' done "
          f"(count={acc['count']}, sum={acc['sum']})")

    res = aggregate_sort(SALES)
    agg_table(res, "Sort-based GROUP BY result")
    print("\nMemory: exactly ONE accumulator live at a time (plus the one being")
    print("emitted). That is the whole appeal of sort-based: O(1) state per group")
    print("in scan order, no hash table, no spill -- but you paid for the sort.")
    return res


# ----------------------------------------------------------------------------
# SECTION B: Hash-based aggregation
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: Hash-based aggregation  "
           "(hash the key, accumulate in buckets -- no sort)")
    print("Query:  same as Section A, but skip the sort.")
    print()
    print("For every row: bucket = hash(region) mod N_BUCKETS; look in that bucket's")
    print("CHAIN for the region. Seen it? update its accumulator. New? append a fresh")
    print("accumulator to the chain. PostgreSQL calls this node HashAggregate.\n")

    print(f"hash(region) = (hash * 31 + ord(c)) mod 2^32 ;  bucket = hash mod {N_BUCKETS}")
    print(f"| region | full hash   | bucket mod {N_BUCKETS} |")
    print("|--------|-------------|-------------|")
    for region in sorted({r[1] for r in SALES}):
        print(f"| {region:<6} | {hash_full(region):<11} | {bucket_of(region):<11} |")
    print(f"\nNote the COLLISION: 3 distinct regions hash to bucket 5. They are")
    print("disambiguated by a CHAIN (linked list) inside the bucket -- this is")
    print("'separate chaining'. Bucket 7 holds West alone; the rest are empty.\n")

    print("Streaming build -- one row at a time, show the bucket chain reached:")
    print("| step | id | region | total | bucket | action          | chain after |")
    print("|------|----|--------|-------|--------|-----------------|-------------|")
    table: list[list] = [[] for _ in range(N_BUCKETS)]
    out: dict[str, dict] = {}
    for _id, region, _p, total in SALES:
        b = bucket_of(region)
        if region in out:
            action = "update existing"
        else:
            action = "NEW -> append"
            table[b].append(region)
        acc_update(out.setdefault(region, new_acc()), total)
        print(f"| {_id:<5}| {_id:<3}| {region:<7}| {total:<6}| {b:<7}| {action:<16}| "
              f"b{b}={table[b]} |")

    print("\nFinal hash table (bucket -> chain -> accumulator):")
    for b in range(N_BUCKETS):
        if table[b]:
            chains = " -> ".join(
                f"{r}{{cnt={out[r]['count']},sum={out[r]['sum']}}}" for r in table[b])
            print(f"  bucket {b}: {chains}")
        else:
            print(f"  bucket {b}: (empty)")

    res, _ = aggregate_hash(SALES)
    agg_table(res, "Hash-based GROUP BY result")
    print("\nMemory: ALL distinct groups live simultaneously (one accumulator each).")
    print("If that exceeds work_mem we cannot just emit-and-forget like the sort")
    print("path -- we must SPILL. That is Section E.")
    return res


# ----------------------------------------------------------------------------
# SECTION C: HAVING -- filter whole groups AFTER aggregation
# ----------------------------------------------------------------------------

def section_c(res: dict):
    banner(f"SECTION C: HAVING  (filter GROUPS after aggregation, threshold={HAVING_THRESHOLD})")
    print("Query:  ... GROUP BY region HAVING SUM(total) > 1000")
    print()
    print("WHERE filters ROWS before grouping; HAVING filters GROUPS after. Because")
    print("it runs on finished accumulators, HAVING can reference aggregates")
    print("(SUM, COUNT, ...) -- WHERE cannot.\n")

    print("Pre-HAVING aggregates, with the predicate applied:")
    print("| region | SUM(total) | SUM > 1000 ? | kept by HAVING |")
    print("|--------|------------|--------------|----------------|")
    kept = {}
    for region in sorted(res):
        s = res[region]["sum"]
        ok = s > HAVING_THRESHOLD
        kept[region] = ok
        mark = "TRUE" if ok else "false"
        verdict = "KEEP" if ok else "drop"
        print(f"| {region:<6} | {s:<10} | {mark:<12} | {verdict:<14} |")

    print(f"\nRows in -> 12 (4 groups). Groups out after HAVING -> "
          f"{sum(kept.values())} ({[r for r in sorted(res) if kept[r]]}).")
    print("The filter is a trivial extra pass over the finished groups; it does NOT")
    print("change how aggregation was executed (sort or hash are both fine).")
    print(f"[check] HAVING is a strict > (West sum=1000 is NOT kept): "
          f"{'OK' if not kept.get('West') else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION D: DISTINCT -- same machinery as GROUP BY, no aggregate fns
# ----------------------------------------------------------------------------

def section_d(res: dict):
    banner("SECTION D: DISTINCT  "
           "(SELECT DISTINCT reuses the exact GROUP BY machinery)")
    print("Query:  SELECT DISTINCT region FROM sales")
    print()
    print("DISTINCT collapses duplicate keys to one row each. The engine implements")
    print("it with the IDENTICAL operator as GROUP BY -- a hash table (HashAggregate)")
    print("or a sort+dedupe (GroupAggregate) -- just with no aggregate functions")
    print("attached. 'GROUP BY region with no aggregates' IS 'SELECT DISTINCT region'.\n")

    seen_hash: list[list] = [[] for _ in range(N_BUCKETS)]
    distinct = []
    seen = set()
    for _id, region, _p, _t in SALES:
        b = bucket_of(region)
        if region not in seen:
            seen.add(region)
            seen_hash[b].append(region)
            distinct.append(region)
    print("Streaming DISTINCT over the 12 rows (hash dedupe):")
    print("| row | region | bucket | first time? | distinct set so far |")
    print("|-----|--------|--------|-------------|----------------------|")
    s = []
    for _id, region, _p, _t in SALES:
        b = bucket_of(region)
        first = region not in s
        if first:
            s.append(region)
        print(f"| {_id:<4}| {region:<7}| {b:<7}| {'yes' if first else 'no (dup)':<12}| {s} |")
    print(f"\nDISTINCT region -> {sorted(seen)}  ({len(seen)} distinct out of "
          f"{len(SALES)} rows)")
    print("Same bucket layout / chains as Section B's GROUP BY (the dedupe key is")
    print("identical: the region). An aggregate-free GROUP BY region would emit the")
    print("SAME 4 rows. [check] |DISTINCT region| == |GROUP BY region| == "
          f"{len(res)}: OK")


# ----------------------------------------------------------------------------
# SECTION E: Memory management -- spill to disk when work_mem overflows
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: Memory management  "
           "(hash table overflows work_mem -> partition into BATCHES, spill)")
    print(f"work_mem = {WORK_MEM} bytes ;  per-group accumulator = {GROUP_MEM_BYTES} bytes")
    print(f"-> in-memory budget = floor({WORK_MEM}/{GROUP_MEM_BYTES}) = "
          f"{WORK_MEM // GROUP_MEM_BYTES} groups at once.\n")

    full = reference(SALES)
    n_groups = len(full)
    fit = WORK_MEM // GROUP_MEM_BYTES
    print(f"Actual distinct groups = {n_groups}. "
          f"{'FITS' if n_groups <= fit else 'OVERFLOWS work_mem'} "
          f"({n_groups}*{GROUP_MEM_BYTES} = {n_groups*GROUP_MEM_BYTES} bytes "
          f"vs budget {fit*GROUP_MEM_BYTES}).")
    if n_groups <= fit:
        print("No spill needed in this config.")
    print()

    # decide nbatches so each batch's groups fit
    import math
    n_batches = 1
    while math.ceil(n_groups / n_batches) > fit:
        n_batches *= 2
    print(f"Pick n_batches = {n_batches} (so <= {fit} groups per batch). "
          f"batch(region) = (hash(region) >> 8) mod {n_batches}\n")

    print("| region | hash(region) | (>>8) mod 2 | batch |")
    print("|--------|--------------|-------------|-------|")
    routing = {}
    for region in sorted(full):
        r = batch_of(region, n_batches)
        routing[region] = r
        print(f"| {region:<6} | {hash_full(region):<12} | "
              f"{(hash_full(region) >> 8) % n_batches:<12}| {r:<5} |")
    print()

    # simulate the spill: process batch by batch
    combined: dict[str, dict] = {}
    for b in range(n_batches):
        groups_in_batch = sorted(r for r, rb in routing.items() if rb == b)
        rows_in = [row for row in SALES if routing[row[1]] == b]
        rows_spilled = len(SALES) - len(rows_in)
        print(f"BATCH {b}: groups {groups_in_batch} "
              f"({len(rows_in)} rows kept in memory, "
              f"{rows_spilled} rows of other batch(es) spilled to temp file)")
        batch_res = reference(rows_in)
        for region, acc in batch_res.items():
            if region in combined:
                combined[region] = acc_combine(combined[region], acc)
            else:
                combined[region] = acc

    agg_table(combined, "Re-assembled result after spill (union of batches)")

    ok = combined == full
    print(f"\n[check] spilled (multi-batch) result == single-pass result: "
          f"{'OK' if ok else 'FAIL'}")
    assert ok, "spill changed the answer!"
    print("KEY POINT: spilling trades disk I/O (write other batches out, read them")
    print("back per batch) for BOUNDED memory. If a single batch STILL overflows")
    print("(a 'skew' bucket), PostgreSQL raises n_batches again and repartitions.")
    return combined


# ----------------------------------------------------------------------------
# SECTION F: Parallel partial aggregation -- workers + leader combine
# ----------------------------------------------------------------------------

def section_f():
    banner("SECTION F: Parallel PARTIAL aggregation  "
           "(each worker aggregates its slice; leader COMBINES via combinefunc)")
    print("Query (parallel): SELECT region, SUM(total) FROM sales GROUP BY region")
    print()
    print("A parallel scan splits the input across workers. Each runs a PARTIAL")
    print("Aggregate on its slice (one accumulator per region it sees). The leader")
    print("runs a FINAL Aggregate that COMBINES the partials per region with the")
    print("combinefunc (sum: add; count: add; min/max: extreme).\n")

    half = len(SALES) // 2
    w0_rows = SALES[:half]
    w1_rows = SALES[half:]
    print(f"Worker partition: worker 0 = rows 1..{half} (ids "
          f"{[r[0] for r in w0_rows]}), worker 1 = rows {half+1}..{len(SALES)} "
          f"(ids {[r[0] for r in w1_rows]})\n")

    p0 = reference(w0_rows)
    p1 = reference(w1_rows)
    print("Partial aggregates:")
    print("| region | worker0 (count,sum) | worker1 (count,sum) |")
    print("|--------|---------------------|---------------------|")
    for region in sorted(set(p0) | set(p1)):
        a = p0.get(region, new_acc())
        c = p1.get(region, new_acc())
        print(f"| {region:<6} | ({a['count']},{a['sum']}){'':<10}| ({c['count']},{c['sum']}) |")

    combined: dict[str, dict] = {}
    for region in set(p0) | set(p1):
        a = p0.get(region)
        c = p1.get(region)
        if a and c:
            combined[region] = acc_combine(a, c)
        else:
            combined[region] = a or c

    agg_table(combined, "Leader-combined result")

    full = reference(SALES)
    ok = combined == full
    print(f"\n[check] combined-partials == single-worker result: {'OK' if ok else 'FAIL'}")
    assert ok, "partial combine changed the answer!"
    print("combinefunc is what makes aggregation parallelizable: SUM/COUNT/MIN/MAX")
    print("are ASSOCIATIVE (the grouping order among partials does not matter), so")
    print("two-phase (partial -> final) always equals one-phase. AVG is NOT directly")
    print("associative, so the partial state stores (count, sum) and the final does")
    print("sum/count -- never fold to an average early.")


# ============================================================================
# 4. GOLD CHECK -- the two strategies must agree, on every aggregate
# ============================================================================

def gold_check(sort_res: dict, hash_res: dict):
    banner("GOLD CHECK: sort-based == hash-based  (strategy invisible to the answer)")
    print("| region | sort (count,sum,min,max) | hash (count,sum,min,max) | match |")
    print("|--------|--------------------------|--------------------------|-------|")
    all_ok = True
    for region in sorted(set(sort_res) | set(hash_res)):
        s = sort_res.get(region, new_acc())
        h = hash_res.get(region, new_acc())
        match = s == h
        all_ok &= match
        print(f"| {region:<6} | ({s['count']},{s['sum']},{s['min']},{s['max']})"
              f"{'':<4}| ({h['count']},{h['sum']},{h['min']},{h['max']})"
              f"{'':<4}| {'OK' if match else 'FAIL':<5} |")
    print(f"\n[check] ALL aggregates match across strategies: "
          f"{'OK' if all_ok else 'FAIL'}")
    assert all_ok, "sort-based and hash-based disagree!"
    # compact scalar gold for the .html (Section B hash table, SUM per region)
    print("\nGOLD scalars (pinned for aggregation_pipeline.html) -- SUM(total) per region:")
    for region in ["North", "South", "East", "West"]:
        print(f"  SUM[{region}] = {hash_res[region]['sum']}")
    print(f"  bucket[North]={bucket_of('North')}  bucket[South]={bucket_of('South')}  "
          f"bucket[East]={bucket_of('East')}  bucket[West]={bucket_of('West')} "
          f"(mod {N_BUCKETS})")


# ============================================================================
# main
# ============================================================================

def main():
    print("aggregation_pipeline.py - reference impl. All numbers below feed")
    print("AGGREGATION_PIPELINE.md.  (pure stdlib; python3 aggregation_pipeline.py)")
    print(f"N_BUCKETS={N_BUCKETS}  GROUP_MEM={GROUP_MEM_BYTES}B  "
          f"WORK_MEM={WORK_MEM}B  HAVING>{HAVING_THRESHOLD}")

    sort_res = section_a()
    hash_res = section_b()
    section_c(hash_res)
    section_d(hash_res)
    section_e()
    section_f()
    gold_check(sort_res, hash_res)

    banner("DONE - all sections printed, all checks OK")


if __name__ == "__main__":
    main()
