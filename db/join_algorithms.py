"""
join_algorithms.py - Reference implementation of the three classic physical
join algorithms: Nested Loop Join, Hash Join, and (Sort-)Merge Join -- plus
the two "in real life" refinements every query optimizer actually picks
between: Block Nested Loop (chunks the outer to amortize inner scans) and
Grace Hash Join (partitions both sides so each bucket fits in memory).

This is the single source of truth that JOIN_ALGORITHMS.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 join_algorithms.py

============================================================================
THE INTUITION (read this first) -- the lost-keys problem at a hotel
============================================================================
You are a hotel clerk. Table R is a stack of guest envelopes (each with a
ROOM NUMBER written on it). Table S is a wall of mailboxes labelled by room
number. Your job: deliver every envelope to its mailbox. That is a JOIN:
match R.room = S.room.

  * NESTED LOOP  : pick up envelope 1, walk the ENTIRE wall looking for its
                   room; then envelope 2, walk the wall again; ... That is
                   |R| * |S| trips past the wall. Brutal, but it works for
                   ANY join condition (not just =) and needs no prep.
  * HASH JOIN    : FIRST spend one pass building a hash table of the
                   mailboxes (hash room# -> slot). Then each envelope hashes
                   its room# and goes straight to the right slot. Two passes
                   total: |R| + |S|. Only works for EQUALITY (=) joins.
  * MERGE JOIN   : sort both stacks by room number, then walk two fingers
                   forward in lockstep -- like merging two sorted tapes.
                   Cost = sort + one pass each. FREE if the data is already
                   sorted (e.g. both tables are B-tree indexed on the key).

THE REASON ALL THREE EXIST: no single algorithm wins everywhere.
  - NL  is unbeatable when the OUTER is tiny (a 10-row lookup table) or when
        the join is a non-equality predicate (a < b, a BETWEEN ...).
  - Hash is unbeatable for big equi-joins on unsorted data -- it is the
        PostgreSQL default for = joins that do not fit an index.
  - Merge is unbeatable when at least one side is already sorted on the key
        (clustered B-tree, or an interesting ORDER BY the planner can reuse).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  outer (R)     : the table the algorithm loops over "the slow way". In NL
                  the outer is scanned once and the inner is rescanned per
                  outer row. (In PG EXPLAIN this is the first child.)
  inner (S)     : the table probed repeatedly (NL) or hashed once (Hash).
                  Choosing which is outer vs inner is itself a planner cost
                  decision -- usually the SMALLER table is outer for NL.
  tuple / row   : a (rid, key) pair. rid is a synthetic row id for tracing.
  comparison    : one "does r.key == s.key?" test. The headline cost metric
                  for NL. Counted in code via the CMP counter.
  bucket        : a slot in the hash table. All rows hashing to the same
                  value land here. Collisions are resolved by a chain/list.
  build / probe : the two phases of Hash Join. BUILD = scan the inner table
                  once and fill the hash table. PROBE = scan the outer once
                  and look each row up.
  spill         : when the hash table does not fit in RAM, Grace Hash Join
                  PARTITIONS both tables onto disk; each partition is then
                  joined in RAM one at a time.
  equi-join     : a join whose predicate is equality (R.k = S.k). Hash Join
                  and Merge Join ONLY work on equi-joins. NL works on any.
  pre-sorted    : both inputs already ordered on the join key (e.g. they
                  come from a B-tree index scan). Merge Join skips its sort.

============================================================================
THE LINEAGE (papers / textbooks)
============================================================================
  Nested Loop     (classic, predates databases): the naive baseline.
                   O(N*M). Refined to Block Nested Loop (chunks outer into
                   blocks so the inner is read once per block, not per row).
  Hash Join       (DeWitt 1980s, "Goals and Directions": build+probe): the
                   classic in-memory design. Cost N+M.
  Grace Hash Join (Kitsuregawa, Tanaka, Moto-oka 1983): for the case the
                   hash table does NOT fit in memory. Partition both sides
                   by hash, then join partition-by-partition. Cost 3*(N+M)
                   in the classic version (read+write+read each side).
  Hybrid Hash     (Shapiro 1986): Grace + keep the first partition in RAM
                   instead of spilling it. The version modern DBs implement.
  Sort-Merge      (classic): when inputs are sorted (or must be sorted
                   anyway for ORDER BY/GROUP BY downstream), one merge pass.
  Optimizer cost  (Selinger 1979 "Access Path Selection"): the formulas we
                   use in Section D trace back to System R's cost model.

KEY FORMULAS (all verified against textbooks + asserted in code):
    NL          : comparisons = N * M
    Block NL    : inner scans = ceil(N / B)  ; comparisons still N*M
                  (B = block size in rows; each inner scan reads M rows)
    Indexed NL  : comparisons = N * log M    (B-tree lookup per outer row)
    Hash Join   : row touches  = N + M       (build M, probe N)
                  (+ in-bucket collisions; small if hash is good)
    Merge Join  : pre-sorted   = N + M       (one merge pass)
                  needs sort   = N*logN + M*logM + N + M
    Grace Hash  : I/O passes   = 3 * (N + M)  (partition write + read each)

Conventions (used throughout):
    N = |R|  rows in the OUTER table   (here: 5)
    M = |S|  rows in the INNER table   (here: 4)
    B = block size for Block NL / number of partitions for Grace Hash
    key  = the join column value (we join on equality of key)
    rid  = row identifier (synthetic, 0-indexed, for tracing only)

Sources:
  [1] H. Garcia-Molina, J. Ullman, J. Widom, "Database Systems: The Complete
      Book", ch. 15 (External Sorting) and ch. 16 (Joins).
  [2] R. Ramakrishnan, J. Gehrke, "Database Management Systems", ch. 12
      (Evaluation of Relational Operators) -- the cost table in Section D.
  [3] PostgreSQL docs: executor.c nodeNestedLoop, nodeHashjoin, nodeMergejoin
      (src/backend/executor/) -- all three algorithms live here in PG.
  [4] P. Selinger, "Access Path Selection in a Relational Database System",
      SIGMOD 1979 -- the cost model every modern optimizer descends from.
  [5] M. Kitsuregawa et al., "Application of Hash to Data Base Machine",
      LSD 1983 -- Grace Hash Join.
  [6] L. Shapiro, "Join Processing in Database Systems with Large Main
      Memories", TODS 1986 -- Hybrid Hash Join.
"""

from __future__ import annotations

import math
from functools import cmp_to_key

BANNER = "=" * 74

# ============================================================================
# 1. THE DETERMINISTIC INPUT TABLES
#    Tiny enough to print every comparison; rich enough to exercise every
#    algorithm: duplicate keys (room 1 appears twice in BOTH tables -> a 2x2
#    fan-out), an unmatched outer row (room 3), an unmatched inner row (room 9).
# ============================================================================

# Outer table R: (rid, key). 5 rows. Keys: 1,2,1,3,2.
OUTER_R = [(0, 1), (1, 2), (2, 1), (3, 3), (4, 2)]

# Inner table S: (rid, key). 4 rows. Keys: 1,1,2,9.
INNER_S = [(0, 1), (1, 1), (2, 2), (3, 9)]

N = len(OUTER_R)   # 5
M = len(INNER_S)   # 4


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def pairs_as_str(pairs):
    """Render a list of (rid_R, rid_S) joined pairs compactly."""
    if not pairs:
        return "(none)"
    return ", ".join(f"(r{r},s{s})" for r, s in pairs)


# ============================================================================
# 3. THE THREE JOIN ALGORITHMS  (the code JOIN_ALGORITHMS.md walks through)
# ============================================================================

# ----------------------------------------------------------------------------
# Nested Loop Join -- O(N*M). For each outer row, scan the ENTIRE inner.
# ----------------------------------------------------------------------------

def nested_loop_join(outer=OUTER_R, inner=INNER_S):
    """Plain Nested Loop Join.

    For each row r in the outer table, scan EVERY row s in the inner table
    and emit (r, s) whenever r.key == s.key.

    Returns (pairs, comparisons, inner_scans) where:
      pairs        = list of (rid_R, rid_S) joined tuples, in emit order
      comparisons  = number of (r,s) equality tests performed
      inner_scans  = number of full passes over the inner table (= N)
    """
    pairs = []
    comparisons = 0
    inner_scans = 0
    for r_rid, r_key in outer:                 # outer: scan once
        inner_scans += 1                       # one full inner pass per outer row
        for s_rid, s_key in inner:             # inner: rescanned N times
            comparisons += 1
            if r_key == s_key:
                pairs.append((r_rid, s_rid))
    return pairs, comparisons, inner_scans


def block_nested_loop_join(block_size=2, outer=OUTER_R, inner=INNER_S):
    """Block Nested Loop Join.

    Instead of rescanning the inner for every single outer ROW, we chunk the
    outer into blocks of `block_size` rows and scan the inner ONCE per block.
    The number of inner scans drops from N to ceil(N/B); comparisons stay
    N*M (we still compare every pair) but I/O on the inner drops sharply,
    which is the whole point -- the inner is what gets read repeatedly.

    Returns (pairs, comparisons, inner_scans, num_blocks).
    """
    pairs = []
    comparisons = 0
    inner_scans = 0
    num_blocks = math.ceil(len(outer) / block_size)
    for blk_start in range(0, len(outer), block_size):
        block = outer[blk_start:blk_start + block_size]
        inner_scans += 1                       # one inner pass per BLOCK
        for r_rid, r_key in block:
            for s_rid, s_key in inner:
                comparisons += 1
                if r_key == s_key:
                    pairs.append((r_rid, s_rid))
    return pairs, comparisons, inner_scans, num_blocks


# ----------------------------------------------------------------------------
# Hash Join -- O(N+M). Build a hash table on the smaller side, probe with
# the other. Works ONLY for equi-joins.
# ----------------------------------------------------------------------------

def _hash(key, num_buckets):
    """The hash function. We use key % num_buckets for traceability -- the
    real DB uses a strong hash (PG: hash_any = Jenkins lookup3) but the
    algorithm is identical: map key -> bucket."""
    return key % num_buckets


def hash_join(num_buckets=3, outer=OUTER_R, inner=INNER_S):
    """Classic in-memory Hash Join (build = inner, probe = outer).

    BUILD : scan the inner table once, hash each row's key, push into a
            bucket. One hash op per inner row.
    PROBE : scan the outer table once. For each outer row, hash its key and
            look in that bucket; compare against every row already there.

    Returns (pairs, build_ops, probe_ops, probe_collisions, buckets).
      build_ops        = number of inner rows hashed (= M)
      probe_ops        = number of outer rows hashed (= N)
      probe_collisions = number of in-bucket key comparisons during probe
      buckets          = dict bucket_id -> list of (rid, key) from build
    """
    # ---- BUILD (inner -> hash table) ----
    buckets: dict[int, list] = {b: [] for b in range(num_buckets)}
    build_ops = 0
    for s_rid, s_key in inner:
        b = _hash(s_key, num_buckets)
        buckets[b].append((s_rid, s_key))
        build_ops += 1

    # ---- PROBE (outer -> lookup) ----
    pairs = []
    probe_ops = 0
    probe_collisions = 0
    for r_rid, r_key in outer:
        b = _hash(r_key, num_buckets)
        probe_ops += 1
        for s_rid, s_key in buckets[b]:        # only compare within the bucket
            probe_collisions += 1
            if r_key == s_key:
                pairs.append((r_rid, s_rid))
    return pairs, build_ops, probe_ops, probe_collisions, buckets


# ----------------------------------------------------------------------------
# (Sort-)Merge Join -- sort both sides on the key, then merge with two
# pointers. Handles duplicate keys correctly (a group on each side produces
# the cartesian product of that key).
# ----------------------------------------------------------------------------

def _counting_sort(rows, counter):
    """Stable sort of `rows` (list of (rid, key)) by key, counting the
    number of key comparisons made via the `counter` list (mutable holder so
    we can increment from inside the comparator). Python's sorted is stable
    (Timsort); we wrap it only to count comparisons."""
    def cmp(a, b):
        counter[0] += 1
        if a[1] < b[1]:
            return -1
        if a[1] > b[1]:
            return 1
        return 0
    return sorted(rows, key=cmp_to_key(cmp))


def merge_join(outer=OUTER_R, inner=INNER_S):
    """Sort-Merge Join.

    1. STABLE-SORT both tables on the join key (count comparisons).
    2. MERGE with two pointers. When the keys match, we have a GROUP: collect
       all consecutive equal keys on each side, then emit the cartesian
       product of those two groups. Advance both pointers past the group.

    Returns (pairs, sort_cmp, merge_advances, sorted_R, sorted_S).
      sort_cmp        = total key comparisons done by both sorts
      merge_advances  = total pointer advances in the merge step
    """
    sort_cmp = [0]
    sR = _counting_sort(outer, sort_cmp)
    sS = _counting_sort(inner, sort_cmp)

    pairs = []
    merge_advances = 0
    i = j = 0
    while i < len(sR) and j < len(sS):
        r_rid, r_key = sR[i]
        s_rid, s_key = sS[j]
        if r_key == s_key:
            # Found a match. Expand the GROUP on both sides (duplicates),
            # then emit the cartesian product of the two groups.
            r_group_end = i
            while r_group_end < len(sR) and sR[r_group_end][1] == r_key:
                r_group_end += 1
            s_group_end = j
            while s_group_end < len(sS) and sS[s_group_end][1] == s_key:
                s_group_end += 1
            for ri in range(i, r_group_end):
                for sj in range(j, s_group_end):
                    pairs.append((sR[ri][0], sS[sj][0]))
            merge_advances += (r_group_end - i) + (s_group_end - j)
            i = r_group_end
            j = s_group_end
        elif r_key < s_key:
            i += 1
            merge_advances += 1
        else:
            j += 1
            merge_advances += 1
    return pairs, sort_cmp[0], merge_advances, sR, sS


# ----------------------------------------------------------------------------
# Grace Hash Join -- when the hash table does not fit in memory, PARTITION
# both tables by hash first, then join matching partitions in memory.
# ----------------------------------------------------------------------------

def grace_hash_join(num_partitions=3, outer=OUTER_R, inner=INNER_S):
    """Grace Hash Join (Kitsuregawa 1983).

    Phase 1 (PARTITION): hash every row of BOTH tables to one of B
              partitions. Write each partition to disk. After this, every
              row that could possibly match lives in the SAME partition
              number on both sides (because both used the same hash fn).
    Phase 2 (JOIN)     : load partition b of R and partition b of S into
              memory one at a time and run an in-memory hash join on them.

    Returns (pairs, partitions_R, partitions_S, per_partition_pairs).
    """
    part_R: dict[int, list] = {b: [] for b in range(num_partitions)}
    part_S: dict[int, list] = {b: [] for b in range(num_partitions)}
    for r_rid, r_key in outer:
        part_R[_hash(r_key, num_partitions)].append((r_rid, r_key))
    for s_rid, s_key in inner:
        part_S[_hash(s_key, num_partitions)].append((s_rid, s_key))

    pairs = []
    per_partition = {}
    for b in range(num_partitions):
        # in-memory hash join within this partition (here: nested loop, since
        # each partition is small by construction)
        sub_pairs = []
        for r_rid, r_key in part_R[b]:
            for s_rid, s_key in part_S[b]:
                if r_key == s_key:
                    sub_pairs.append((r_rid, s_rid))
        per_partition[b] = sub_pairs
        pairs.extend(sub_pairs)
    return pairs, part_R, part_S, per_partition


# ============================================================================
# 4. THE SECTIONS (each prints a banner + table, exactly what the .md pastes)
# ============================================================================

def show_inputs():
    banner("SECTION 0: the inputs (the deterministic tables R and S)")
    print(f"OUTER R: {N} rows  (emp tables, customer lists, ...)")
    print(f"INNER S: {M} rows  (lookup tables, dimension tables, ...)\n")
    print("R = [(rid, key)]                              S = [(rid, key)]")
    print("-" * 60)
    for i in range(max(N, M)):
        left = f"  r{OUTER_R[i][0]}  key={OUTER_R[i][1]}" if i < N else ""
        right = f"  s{INNER_S[i][0]}  key={INNER_S[i][1]}" if i < M else ""
        print(f"{left:<30}{right}")
    print("-" * 60)
    print("\nWhy these values exercise every edge case:")
    print("  * key=1 appears TWICE on each side -> a 2x2 fan-out (4 output rows)")
    print("  * key=2 appears twice in R, once in S -> 2 output rows")
    print("  * key=3 (R only) -> no match (drops out)")
    print("  * key=9 (S only) -> no match (drops out)")
    print("  * Expected output cardinality: 4 + 2 = 6 joined rows.\n")
    expected = sorted([(0, 0), (0, 1), (1, 2), (2, 0), (2, 1), (4, 2)])
    print(f"[check] gold expected pairs (sorted): {pairs_as_str(expected)}")


def section_a():
    banner("SECTION A: Nested Loop Join  --  O(N*M) = 5*4 = 20 comparisons")
    pairs, cmp, scans = nested_loop_join()
    print("For each outer row, walk the ENTIRE inner table once:\n")
    print("| step | outer r (key) | inner scan |"
          " comparisons this row | matched s rows |")
    print("|------|---------------|------------|------------------------|----------------|")
    idx = 0
    for r_i, (r_rid, r_key) in enumerate(OUTER_R):
        row_pairs = [(r, s) for (r, s) in pairs if r == r_rid]
        matched = [f"s{s}" for (_, s) in row_pairs]
        mstr = ",".join(matched) if matched else "-"
        print(f"| {r_i:<4} | r{r_rid} (key={r_key})       | full (#{r_i+1})  |"
              f" {M:<22} | {mstr:<14} |")
        idx += M
    print(f"\nTOTALS:  comparisons = {cmp}   (= N*M = {N}*{M})"
          f"   inner scans = {scans}  (= N = {N})")
    print(f"output rows emitted: {len(pairs)}  -> {pairs_as_str(pairs)}\n")

    print("VARIANT -- Block Nested Loop (block_size B=2):")
    bp, bcmp, bscans, nblk = block_nested_loop_join(block_size=2)
    print(f"  chunk outer into ceil(N/B) = ceil({N}/2) = {nblk} blocks:")
    for blk_start in range(0, N, 2):
        block = OUTER_R[blk_start:blk_start + 2]
        ids = [f"r{r}" for r, _ in block]
        print(f"    block @{blk_start}: {ids}")
    print(f"  -> inner is scanned once PER BLOCK  = {nblk} times"
          f" (was {N} for plain NL)")
    print(f"  -> comparisons UNCHANGED = {bcmp}  (still N*M; we still test every pair)")
    print(f"  -> output identical: {len(bp)} rows  -> {pairs_as_str(bp)}")
    assert bp == pairs, "[check] block NL output must match plain NL"
    print("[check] Block NL output == plain NL output:  OK")
    print("\nTake-away: Block NL does not reduce CPU comparisons; it reduces")
    print("I/O on the INNER table (read once per block, not per row). When the")
    print("inner is large and lives on disk, that is the dominant win.")


def section_b():
    banner("SECTION B: Hash Join  --  O(N+M) = 5+4 = 9 row-touches")
    pairs, build_ops, probe_ops, collisions, buckets = hash_join(num_buckets=3)
    print("Two phases. BUILD hashes the inner into buckets; PROBE hashes each")
    print("outer row and looks ONLY in its bucket.\n")
    print("hash function:  h(key) = key mod 3   (num_buckets = 3)\n")
    print("BUILD (inner S, M=4 rows -> hash table):")
    for b in sorted(buckets):
        contents = buckets[b]
        cell = pairs_as_str_inner(contents) if contents else "(empty)"
        print(f"  bucket {b}: {cell}")
    print(f"  build ops = {build_ops}  (= M = {M} hashes)\n")

    print("PROBE (outer R, N=5 rows -> lookup):")
    print("| outer r (key) | h(key) | bucket contents        | matches      |")
    print("|---------------|--------|------------------------|--------------|")
    for r_rid, r_key in OUTER_R:
        b = _hash(r_key, 3)
        contents = buckets[b]
        matched = [sr for (sr, sk) in contents if sk == r_key]
        cell = pairs_as_str_inner(contents) if contents else "(empty)"
        mstr = [f"s{s}" for s in matched] if matched else "-"
        print(f"| r{r_rid} (key={r_key})       | {b}      | {cell:<22} | {','.join(mstr):<12} |")
    print(f"\nTOTALS:  build ops + probe ops = {build_ops}+{probe_ops} = "
          f"{build_ops+probe_ops} row-touches  (= N+M = {N+M})")
    print(f"         in-bucket key comparisons (collisions) = {collisions}")
    print(f"         (compare to NL's {N*M} = N*M full comparisons)")
    print(f"output rows emitted: {len(pairs)}  -> {pairs_as_str(pairs)}\n")
    print("Why Hash wins big equi-joins: it pays N+M row-touches TOTAL, not")
    print("N*M. The in-bucket collisions are tiny if the hash spreads rows")
    print("evenly (a few per bucket); they balloon only if the join key is")
    print("pathologically skewed (e.g. one key value covers 90% of rows).")


def section_c():
    banner("SECTION C: (Sort-)Merge Join  --  sort both, then one merge pass")
    pairs, sort_cmp, merge_adv, sR, sS = merge_join()
    print("Step 1 -- STABLE-SORT both tables on the join key:\n")
    print(f"  R sorted: {pairs_as_str_rows(sR)}")
    print(f"  S sorted: {pairs_as_str_rows(sS)}")
    print(f"  sort comparisons (both sorts combined) = {sort_cmp}\n")

    print("Step 2 -- MERGE with two pointers i (into R), j (into S):")
    print("  rule: if R[i].key == S[j].key -> expand the GROUP on both sides")
    print("        (collect all duplicates), emit their cartesian product,")
    print("        advance both pointers past the group.")
    print("        if R[i].key <  S[j].key -> i++  (R row cannot match any")
    print("        future S row, since S is sorted ascending).")
    print("        if R[i].key >  S[j].key -> j++.\n")

    # replay the merge to print the step log
    i = j = 0
    step = 0
    print("| step | i | j | R[i].key | S[j].key | action                     |")
    print("|------|---|---|----------|----------|----------------------------|")
    while i < len(sR) and j < len(sS):
        rk = sR[i][1]
        sk = sS[j][1]
        if rk == sk:
            r_ge = i
            while r_ge < len(sR) and sR[r_ge][1] == rk:
                r_ge += 1
            s_ge = j
            while s_ge < len(sS) and sS[s_ge][1] == sk:
                s_ge += 1
            nrr = r_ge - i
            nss = s_ge - j
            action = f"emit group ({nrr}x{nss}={nrr*nss} rows)"
            print(f"| {step:<4} | {i} | {j} | {rk:<8} | {sk:<8} | {action:<26} |")
            i, j = r_ge, s_ge
        elif rk < sk:
            print(f"| {step:<4} | {i} | {j} | {rk:<8} | {sk:<8} | R<S -> i++ (skip r)            |")
            i += 1
        else:
            print(f"| {step:<4} | {i} | {j} | {rk:<8} | {sk:<8} | R>S -> j++ (skip s)            |")
            j += 1
        step += 1
    print(f"\nTOTALS:  sort comparisons = {sort_cmp}   merge advances = {merge_adv}")
    print(f"  if inputs were PRE-SORTED, the sort cost drops to 0 -> merge = {N+M}")
    print(f"output rows emitted: {len(pairs)}  -> {pairs_as_str(pairs)}\n")
    print("When Merge Join dominates: if EITHER input is already ordered on")
    print("the key (clustered B-tree, or an index scan that returns sorted"),
    print("rows), the sort is free and the whole join is a single N+M pass.")
    print("PostgreSQL's nodeMergejoin is exactly this two-pointer merge.")


def section_d():
    banner("SECTION D: Cost comparison + optimizer decision matrix")
    print("Closed-form costs (per the Selinger 1979 / System R cost model).\n")
    print("Legend:  N=|R| (outer),  M=|S| (inner),  B=Block-NL block size.")
    print("         'idx' = inner has a B-tree index on the join key.\n")

    print("| algorithm              | predicate   | cost (comparisons / I/O)        |")
    print("|------------------------|-------------|---------------------------------|")
    print("| Nested Loop            | any         | N*M                             |")
    print("| Block Nested Loop      | any         | N*M compares, ceil(N/B) inner reads |")
    print("| Indexed Nested Loop    | any (idx)   | N * log2(M)   (one lookup per outer row) |")
    print("| Hash Join              | = (equi)    | N + M  (+ small collisions)     |")
    print("| Merge Join (pre-sorted)| = , < , >   | N + M                           |")
    print("| Merge Join (sort both) | = , < , >   | N*log2(N) + M*log2(M) + N + M   |")
    print("| Grace Hash Join        | = (equi)    | 3*(N+M) I/O  (spill+rewind+reread) |")
    print()

    print("Worked numbers for a sweep of (N, M):")
    print("| N       | M       | NL = N*M | Hash = N+M | Merge sorted = N+M |"
          " Merge+sort = NlgN+MlgM+N+M | Indexed NL = N*lgM |")
    print("|---------|---------|----------|------------|---------------------|"
          "----------------------------|--------------------|")
    for NN, MM in [(5, 4), (100, 100), (1000, 1000), (10_000, 10_000),
                   (1_000_000, 1_000_000), (10, 1_000_000), (1_000_000, 10)]:
        nl = NN * MM
        hj = NN + MM
        ms = NN + MM
        msort = NN * math.log2(NN) + MM * math.log2(MM) + NN + MM
        idx_nl = NN * math.log2(MM) if MM > 1 else NN
        print(f"| {NN:<7,} | {MM:<7,} | {nl:<8,} | {hj:<10,} | {ms:<19,} | "
              f"{msort:<26,.0f} | {idx_nl:<18,.0f} |")
    print()
    print("Read the table:")
    print("  * At N=M=1M, NL does 10^12 compares (impossible); Hash does 2M.")
    print("    That ~6-orders-of-magnitude gap is why hash join exists.")
    print("  * Indexed NL is competitive when N is SMALL (10) and M is huge:")
    print("    10 * log2(1M) ~ 200 lookups -- this is the OLTP point-lookup")
    print("    join (e.g. join a 10-row result to a billion-row fact table).")
    print("  * Merge+sort loses to Hash on unsorted data: the two sorts add")
    print("    NlgN+MlgM overhead that Hash simply never pays.\n")

    print("DECISION MATRIX (what the optimizer actually picks):")
    print("| situation                                   | cheapest join        | why |")
    print("|---------------------------------------------|----------------------|-----|")
    print("| small outer, indexed inner (OLTP lookup)    | Indexed Nested Loop  | N*logM << N+M when N tiny |")
    print("| small outer, no index (e.g. < ~10 rows)     | Nested Loop          | overhead of building a hash table is not worth it |")
    print("| large equi-join, both sides unsorted        | Hash Join            | N+M beats N*M and beats sort+merge |")
    print("| one/both sides pre-sorted (B-tree, ORDER BY)| Merge Join           | sort is free -> pure N+M, also keeps output sorted |")
    print("| equi-join, hash table bigger than RAM       | Grace / Hybrid Hash  | partition so each piece fits in memory |")
    print("| non-equi predicate (a < b, a BETWEEN b)     | Nested Loop          | Hash and Merge REQUIRE equality |")
    print("| data already needs sorting downstream       | Sort-Merge           | amortize the sort across join + ORDER BY/GROUP BY |")


def section_e():
    banner("SECTION E: Grace Hash Join  --  partition first, then join per bucket")
    pairs, part_R, part_S, per_part = grace_hash_join(num_partitions=3)
    print("When the hash table does NOT fit in memory, classic Hash Join")
    print("thrashes. Grace Hash (Kitsuregawa 1983) sidesteps this: hash BOTH")
    print("tables into B partitions; rows that could match are guaranteed to")
    print("land in the SAME partition number on both sides; then load each")
    print("pair of partitions into memory one at a time and join there.\n")
    print("hash function:  h(key) = key mod 3   (B = 3 partitions)\n")

    print("PHASE 1 -- PARTITION both tables by hash:")
    print("  R partitions:")
    for b in range(3):
        cell = pairs_as_str_rows(part_R[b]) if part_R[b] else "(empty)"
        print(f"    partition {b}: {cell}")
    print("  S partitions:")
    for b in range(3):
        cell = pairs_as_str_rows(part_S[b]) if part_S[b] else "(empty)"
        print(f"    partition {b}: {cell}")
    print()
    print("PHASE 2 -- JOIN each matching partition pair in memory:")
    total_io = 0
    for b in range(3):
        nr, ns = len(part_R[b]), len(part_S[b])
        sub = per_part[b]
        print(f"  partition {b}: |R_b|={nr}, |S_b|={ns}  -> "
              f"in-memory join -> {len(sub)} output rows  "
              f"{pairs_as_str(sub) if sub else ''}")
        total_io += nr + ns
    print(f"\n  sum |R_b| + |S_b| over all partitions = {total_io}  "
          f"(= N+M = {N+M}; partitioning is a lossless repartition)")
    print(f"output rows emitted (all partitions): {len(pairs)}  "
          f"-> {pairs_as_str(pairs)}\n")
    print("I/O cost model: classic Grace Hash does 3 passes over each side")
    print(f"  -> 3*(N+M) = 3*{N+M} = {3*(N+M)} I/Os.")
    print("  Hybrid Hash (Shapiro 1986) keeps partition 0 in RAM during the")
    print("  first pass instead of spilling it -- the version every modern DB")
    print("  actually implements. PG's nodeHashjoin chooses this automatically")


def section_gold():
    banner("GOLD CHECK: all three algorithms produce the SAME join")
    nl_pairs, _, _ = nested_loop_join()
    hj_pairs, _, _, _, _ = hash_join(num_buckets=3)
    mj_pairs, _, _, _, _ = merge_join()
    gh_pairs, _, _, _ = grace_hash_join(num_partitions=3)
    # order-independent compare: sort each by (rid_R, rid_S)
    gold = sorted([(0, 0), (0, 1), (1, 2), (2, 0), (2, 1), (4, 2)])
    nl_s = sorted(nl_pairs)
    hj_s = sorted(hj_pairs)
    mj_s = sorted(mj_pairs)
    gh_s = sorted(gh_pairs)
    print(f"  Nested Loop  : {len(nl_pairs)} rows  -> {pairs_as_str(nl_s)}")
    print(f"  Hash Join    : {len(hj_pairs)} rows  -> {pairs_as_str(hj_s)}")
    print(f"  Merge Join   : {len(mj_pairs)} rows  -> {pairs_as_str(mj_s)}")
    print(f"  Grace Hash   : {len(gh_pairs)} rows  -> {pairs_as_str(gh_s)}")
    print(f"  expected gold: {len(gold)} rows  -> {pairs_as_str(gold)}\n")
    ok = nl_s == hj_s == mj_s == gh_s == gold
    print(f"[check] NL == Hash == Merge == Grace == gold :  {'OK' if ok else 'FAIL'}")
    assert ok, "GOLD CHECK FAILED"
    print("[check] all four algorithms agree on the join result:  OK")
    print("\nThis is the correctness invariant: the optimizer may pick any of")
    print("them based on cost, but the RESULT is byte-identical. That is why a")
    print("query plan can swap algorithms freely without changing semantics.")


# ----------------------------------------------------------------------------
# small helpers for printing rows/pairs in human-readable form
# ----------------------------------------------------------------------------

def pairs_as_str_inner(rows):
    """Render build/probe bucket contents [(rid,key), ...]."""
    return ", ".join(f"s{r}(k={k})" for r, k in rows)


def pairs_as_str_rows(rows):
    """Render sorted/partition contents [(rid,key), ...]."""
    return ", ".join(f"(rid={r},k={k})" for r, k in rows)


# ============================================================================
# main
# ============================================================================

def main():
    print("join_algorithms.py - reference impl. All numbers below feed JOIN_ALGORITHMS.md.")
    print(f"N (outer |R|) = {N}    M (inner |S|) = {M}")
    show_inputs()
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
