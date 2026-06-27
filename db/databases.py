"""
databases.py - Overview of database types, ACID, indexing, and query optimization.

This is the single source of truth that DATABASES.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 databases.py

============================================================================
THE INTUITION (read this first) - the filing cabinet and its card catalog
============================================================================
A database is a system that stores rows AND lets you find them fast. The naive
version - write every row into one big file and scan it on every query - is
O(N) per read and fine for a hundred rows. Real databases add three things on
top of "a file of rows":

   * INDEXES      = a card catalog. Instead of scanning every row, you look the
                    key up in a sorted/hashed side-structure and jump straight
                    to the row. The cost is paid on writes (update the catalog)
                    and on disk (the catalog takes space).
   * TRANSACTIONS = a group of row changes that either ALL happen or NONE
                    happen. ACID is the contract a transaction gives you:
                    Atomic (all-or-nothing), Consistent (state-to-state valid),
                    Isolated (concurrent txns don't interfere), Durable
                    (committed survives a crash). The mechanism is a write-ahead
                    log (WAL): every change is fsync'd to the log BEFORE the
                    data page, so crash recovery can replay or roll it back.
   * A COST MODEL = the query planner. Given SQL it estimates the cost of
                    several physical plans (seq scan vs index scan vs hash join)
                    and picks the cheapest. Cost = predicted I/O pages + CPU
                    tuples, calibrated to the hardware.

WHY DIFFERENT FAMILIES EXIST: the row-layout + B-tree + WAL recipe (PostgreSQL,
MySQL) is a great *generalist*. But specific workloads break it:
   * Wide, read-mostly analytics -> COLUMNAR stores (ClickHouse, BigQuery):
     lay columns contiguously so a SUM over one column scans only that column.
   * Massive write throughput    -> LSM-tree stores (Cassandra, RocksDB): turn
     random writes into sequential ones by buffering in a MemTable.
   * Graph traversal             -> GRAPH stores (Neo4j): edges are first-class
     pointers so "friends-of-friends" is pointer-chasing, not a 3-way JOIN.
   * Timestamped events          -> TIME-SERIES stores (InfluxDB, Timescale):
     partition by time so old data is compressed/dropped cheaply.
   * Flexible/evolving schemas   -> DOCUMENT stores (MongoDB): self-describing
     JSON-like records, no ALTER TABLE to add a field.

Each family trades one strength for another. CAP theorem adds: across multiple
nodes you keep at most two of {Consistency, Availability, Partition tolerance} -
and since partitions are unavoidable, the real choice is C-vs-A.

============================================================================
THE LINEAGE (sources)
============================================================================
   ACID       (Haerder & Reuter 1983, "Principles of Transaction-Oriented
               Database Recovery"): the acronym and the WAL/recovery model.
   ARIES      (Mohan et al. 1992, "ARIES: A Transaction Recovery Method
               Supporting Fine-Granularity Locking..."): the
               analysis/redo/undo algorithm PostgreSQL/MySQL/DB2 implement.
   Cost model (Selinger 1979, "Access Path Selection in a Relational DBMS"):
               the dynamic-programming join optimizer every RDBMS descends from.
   CAP        (Brewer 2000; Gilbert & Lynch 2002): consistency/availability/
               partition-tolerance tradeoff.
   Books:     Silberschatz, Korth, Sudarshan - Database System Concepts;
               Kleppmann - Designing Data-Intensive Applications.

KEY FORMULAS (all asserted/printed in the sections below):
   seq scan cost          = N_pages * seq_page_cost + N_tuples * cpu_tuple
   index scan cost        = N_index_pages * random_page_cost
                            + sel * N_tuples * (random_page_cost + cpu_tuple)
   B-tree point lookup    = ceil(log_fanout(N_tuples))      (pages)
   full scan              = N_pages                         (pages)
   selectivity (equality) = 1 / distinct_values             (uniform)
   selectivity (range)    = (hi - lo) / (max - min)
"""

from __future__ import annotations

import math

BANNER = "=" * 72


# ============================================================================
# 1. DATA: the five database families (Section A prints this as a table)
# ============================================================================

# Each family: (family, data_model, examples, strengths, weak_for)
DB_TYPES = [
    ("Relational",
     "tables of typed rows; schema-first; SQL",
     "PostgreSQL, MySQL, Oracle, SQLite",
     "ACID transactions, ad-hoc SQL, mature tooling",
     "rigid schema, horizontal scaling is hard"),
    ("Document (NoSQL)",
     "self-describing JSON/BSON docs; flexible schema",
     "MongoDB, CouchDB, DynamoDB",
     "evolving schemas, nested data, horizontal scale",
     "no joins across docs, weaker transactions"),
    ("Columnar",
     "columns stored contiguously, not rows",
     "ClickHouse, BigQuery, Redshift, Snowflake",
     "fast aggregates over few columns, high compression",
     "slow point lookups, poor single-row updates"),
    ("Graph",
     "nodes + edges as first-class pointers",
     "Neo4j, Dgraph, TigerGraph",
     "multi-hop traversal in O(hops) not O(JOIN^hops)",
     "sharding is hard, not for tabular analytics"),
    ("Time-series",
     "append-only events keyed by timestamp",
     "InfluxDB, TimescaleDB, Prometheus",
     "huge write rates, cheap downsample/retention",
     "not general-purpose; updates/deletes are rare"),
    ("Key-value (NoSQL)",
     "opaque blob keyed by id; O(1) get/put",
     "Redis, Memcached, Riak, etcd",
     "microsecond reads, extreme QPS, simple",
     "no queries, no range scans (KV is blob-only)"),
]

# ACID: each letter, its guarantee, the mechanism that delivers it, a failure
# it prevents.
ACID = [
    ("Atomicity",
     "a txn is all-or-nothing",
     "WAL + rollback of uncommitted txns on recovery (ARIES undo)",
     "partial transfer: debit without credit"),
    ("Consistency",
     "txn moves DB from one valid state to another",
     "constraints + triggers checked at commit; reject violators",
     "account balance going negative"),
    ("Isolation",
     "concurrent txns don't observe each other's uncommitted writes",
     "2PL / MVCC snapshots / SSI; isolation levels tune the trade-off",
     "lost update: two txns read 0, both write 1, counter stuck at 1"),
    ("Durability",
     "a committed txn survives a crash/power loss",
     "WAL fsync before COMMIT returns; redo on recovery (ARIES redo)",
     "ATM says 'deposited' then a power cut loses it"),
]


# ============================================================================
# 2. THE REFERENCE IMPLEMENTATIONS (used by Sections B, C, D)
# ============================================================================

class WALStore:
    """A toy write-ahead-log storage engine.

    Every change is appended to `wal` as a record. The "data pages" are only
    materialised from committed records. Crash recovery works by replaying a
    prefix of the WAL: REDO committed writes, and crucially NOT applying writes
    of txns that never committed before the crash (their changes are undone).

    This is the ARIES model stripped to its essence: REDO committed, DROP
    uncommitted. Real engines also keep LSNs (log sequence numbers) and undo
    in-place page changes, but the survivor set is identical.
    """

    def __init__(self):
        self.wal = []           # ordered list of records
        self.data = {}          # key -> value, materialised from committed

    def begin(self, txn):
        self.wal.append(("BEGIN", txn))

    def write(self, txn, key, val):
        self.wal.append(("WRITE", txn, key, val))

    def commit(self, txn):
        self.wal.append(("COMMIT", txn))

    def abort(self, txn):
        self.wal.append(("ABORT", txn))

    def apply_committed(self):
        """Normal forward path: materialise pages from committed writes only."""
        committed = {r[1] for r in self.wal if r[0] == "COMMIT"}
        for r in self.wal:
            if r[0] == "WRITE" and r[1] in committed:
                self.data[r[2]] = r[3]
        return self.data

    def recover(self, survive_n):
        """Crash simulation: only the first `survive_n` WAL records persist.

        Returns (recovered_data, committed_txns). A WRITE survives iff its txn
        committed INSIDE the survived prefix (durability = commit must be on
        disk before we promise it).
        """
        prefix = self.wal[:survive_n]
        committed = {r[1] for r in prefix if r[0] == "COMMIT"}
        data = {}
        for r in prefix:
            if r[0] == "WRITE" and r[1] in committed:
                data[r[2]] = r[3]
        return data, committed


def schedule_counter(schedule):
    """Replay a read/write/lock schedule over a single shared counter.

    Each step is (txn, op) where op in {"R","W","lock","unlock"} and for R/W the
    value read/written is tracked. Returns the final counter value.

    The "lost update" anomaly: both txns READ the same base value, both WRITE
    base+1, the second WRITE clobbers the first -> one increment is lost.
    """
    counter = 0
    val_read = {}      # txn -> value it most recently read
    locked = None
    pending = {}       # txn -> blocked until lock free
    for txn, op in schedule:
        if op == "lock":
            if locked is None:
                locked = txn
            else:
                pending[txn] = True      # would block; we mark but keep stepping
        elif op == "unlock":
            if locked == txn:
                locked = None
        elif op == "R":
            val_read[txn] = counter
        elif op == "W":
            counter = val_read[txn] + 1
    return counter


# ============================================================================
# 3. COST MODELS (Sections C and D)
# ============================================================================

def btree_lookup_pages(n_tuples, fanout):
    """Height of a B+tree indexing n_tuples = pages read on a point lookup."""
    if n_tuples <= 1:
        return 1
    return math.ceil(math.log(n_tuples, fanout))


def full_scan_pages(n_pages):
    return n_pages


def selectivity_eq(distinct):
    """Equality selectivity under uniform distribution = 1/distinct."""
    return 1.0 / distinct


def selectivity_range(lo, hi, mn, mx):
    """Range selectivity = fraction of the domain covered."""
    span = mx - mn
    if span <= 0:
        return 1.0
    return (hi - lo) / span


def seq_scan_cost(n_pages, n_tuples,
                  seq_page_cost=1.0, cpu_tuple=0.01):
    return n_pages * seq_page_cost + n_tuples * cpu_tuple


def index_scan_cost(n_index_pages, n_tuples, sel,
                    random_page_cost=4.0, cpu_tuple=0.01):
    """Cost of using an index: read index pages + fetch matching heap rows
    one-by-one (random I/O each) + CPU per tuple."""
    return (n_index_pages * random_page_cost
            + sel * n_tuples * random_page_cost
            + sel * n_tuples * cpu_tuple)


# ============================================================================
# 4. THE SECTIONS
# ============================================================================

def banner(title):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def section_a():
    banner("SECTION A: the five database families")
    print("Pick a family by matching the WORKLOAD to its strengths. There is no")
    print("'best' database - only the right tool for an access pattern.\n")
    hdr = f"{'Family':<20}{'Data model':<42}{'Examples':<34}"
    print(hdr)
    print("-" * len(hdr))
    for fam, model, ex, _strong, _weak in DB_TYPES:
        print(f"{fam:<20}{model:<42}{ex:<34}")
    print()
    print(f"{'Family':<20}Strengths")
    print("-" * 72)
    for fam, _m, _ex, strong, weak in DB_TYPES:
        print(f"{fam:<20}{strong}")
    print(f"\n{'Family':<20}Weak for")
    print("-" * 72)
    for fam, _m, _ex, _s, weak in DB_TYPES:
        print(f"{fam:<20}{weak}")
    print("\nDecision shortcut: if you need ACID + SQL + joins -> relational. If")
    print("you need 100K+ writes/sec -> LSM-tree (Cassandra/RocksDB). If you need")
    print("SUM over billions of rows on a few columns -> columnar. If you need")
    print("multi-hop relationships -> graph. If you need microsecond point reads")
    print("-> key-value (Redis). See DATABASES.md Section 1 for the decision tree.")


def section_b():
    banner("SECTION B: ACID - what each letter guarantees, and a WAL demo")
    print("ACID is the contract a transaction gives you. Each letter is delivered")
    print("by a concrete mechanism, and exists to prevent a concrete failure.\n")
    print(f"{'Letter':<14}{'Guarantee':<38}{'Mechanism'}")
    print("-" * 72)
    for letter, guar, mech, _fail in ACID:
        print(f"{letter:<14}{guar:<38}{mech}")
    print(f"\n{'Letter':<14}Failure it prevents")
    print("-" * 72)
    for letter, _g, _m, fail in ACID:
        print(f"{letter:<14}{fail}")

    # ---- Atomicity + Durability via WAL crash recovery ----
    print("\n--- Atomicity + Durability demo: a crash between commits ---")
    s = WALStore()
    s.begin("T1"); s.write("T1", "x", 100); s.commit("T1")          # commits first
    s.begin("T2"); s.write("T2", "x", 200)                          # in-flight, NO commit
    s.begin("T3"); s.write("T3", "y", 7); s.commit("T3")            # commits
    s.begin("T4"); s.write("T4", "z", 9)                            # in-flight, NO commit
    print(f"WAL records written ({len(s.wal)} total):")
    for i, r in enumerate(s.wal):
        print(f"  [{i}] {r}")
    # normal forward path: every committed write materialises
    full = dict(s.apply_committed())
    print(f"\nno crash  -> data = {full}")
    # crash that keeps records [0..7] (T1 + T3 committed; T2 + T4 never commit,
    # so their writes are DROPPED even though they appear earlier in the log)
    data, committed = s.recover(8)
    print(f"crash after record 8 (T2,T4 never committed) -> data = {data}")
    print(f"  committed txns surviving = {sorted(committed)}")
    assert full == {"x": 100, "y": 7}, "normal path materialised committed only"
    assert data == {"x": 100, "y": 7}, "recovery kept T1,T3, dropped T2,T4"
    assert "T2" not in committed and "T4" not in committed
    print("[check] T1 + T3 (committed) survived; T2 + T4 (in-flight) dropped: OK")

    # crash that loses T3's COMMIT: its WRITE (idx 6) is in the log but the
    # COMMIT (idx 7) is not -> ARIES UNDOes it
    data2, committed2 = s.recover(7)
    print(f"crash after record 7 (T3's COMMIT lost, its WRITE undone) -> data = {data2}")
    assert data2 == {"x": 100}, "only T1 had committed in the prefix"
    print("[check] T3's write existed in WAL but without a commit it is undone: OK")

    # ---- Isolation: the lost-update anomaly under READ_UNCOMMITTED ----
    print("\n--- Isolation demo: the lost-update anomaly vs 2PL ---")
    print("Counter starts at 0. Two txns each try to increment it by 1. Correct")
    print("final value is 2. Under READ_UNCOMMITTED (no locking) a lost update")
    print("drops one increment; under 2PL (lock the row) both increments land.\n")
    no_lock = [
        ("T1", "R"), ("T2", "R"),    # both read 0
        ("T1", "W"), ("T2", "W"),     # both write read+1 = 1; second clobbers first
    ]
    twopl = [
        ("T1", "lock"), ("T1", "R"), ("T1", "W"), ("T1", "unlock"),
        ("T2", "lock"), ("T2", "R"), ("T2", "W"), ("T2", "unlock"),
    ]
    bad = schedule_counter(no_lock)
    good = schedule_counter(twopl)
    print(f"  no locking (READ_UNCOMMITTED) schedule -> final counter = {bad}  (LOST UPDATE)")
    print(f"  2PL (lock-read-write-unlock) schedule -> final counter = {good}  (CORRECT)")
    assert bad == 1, "lost update: two increments collapsed to one"
    assert good == 2, "2PL serialises the increments correctly"
    print("[check] no-lock gives 1 (lost update), 2PL gives 2 (correct): OK")

    # ---- Consistency: a constraint violation is rejected ----
    print("\n--- Consistency demo: a CHECK constraint rejects a bad write ---")
    balance = 50
    constraint_ok = balance >= 0
    print(f"  starting balance = {balance}; invariant balance >= 0")
    # a withdraw of 100 would violate -> txn must abort
    proposed = balance - 100
    if proposed < 0:
        print(f"  proposed txn: balance - 100 = {proposed} -> REJECTED (violates constraint)")
        decision = "ABORT"
    else:
        balance = proposed
        decision = "COMMIT"
    assert decision == "ABORT"
    print(f"  decision: {decision}; balance stays {balance}; DB remains consistent")
    print("[check] constraint-violating txn is aborted, balance unchanged: OK")


def section_c():
    banner("SECTION C: indexing - turn O(N) scans into O(log N) or O(1) jumps")
    print("An index is a side-structure that maps a key to its row. Three families:")
    print("  B+tree  - sorted; great for ranges and ORDER BY. O(log_fanout N) lookup.")
    print("  Hash    - unordered; O(1) exact-match only, no ranges.")
    print("  (no idx)- a full table scan is O(N_pages). Cheapest if you read most rows.\n")
    fanout = 256
    print(f"Using fanout = {fanout} (4 KB page, 8 B key + 8 B ptr, ~256 children/node)\n")
    print(f"{'N rows':>12}{'pages (full scan)':>22}{'B+tree point lookup':>24}{'hash point lookup':>22}")
    print("-" * 80)
    rows = [1_000, 10_000, 100_000, 1_000_000, 10_000_000, 100_000_000]
    # assume ~200 bytes/row => pages = rows / 20
    for n in rows:
        n_pages = math.ceil(n / 20)
        bt = btree_lookup_pages(n, fanout)
        print(f"{n:>12,}{n_pages:>22,}{bt:>24}{1:>22}")
    print("\nThe gap widens with N: at 100M rows a full scan reads 5,000,000 pages;")
    print("a B+tree lookup reads 4. That ~1,000,000x is why every OLTP database")
    print("indexes primary and hot foreign keys.")
    # spot-check the formula
    assert btree_lookup_pages(1_000_000, fanout) == 3, "1M rows ~ 3 levels at fanout 256"
    assert btree_lookup_pages(100_000_000, fanout) == 4
    print(f"\n[check] 1M rows -> {btree_lookup_pages(1_000_000, fanout)} levels; "
          f"100M rows -> {btree_lookup_pages(100_000_000, fanout)} levels: OK")

    print("\n--- When an index actually helps: selectivity ---")
    print("The planner uses an index only when it filters OUT most rows. The metric")
    print("is selectivity = fraction of rows a predicate returns. Lower is better.\n")
    print(f"{'predicate':<32}{'distinct':>10}{'selectivity':>14}{'verdict':>22}")
    print("-" * 78)
    cases = [
        ("user_id = 12345 (PK)",        10_000_000, "use index (unique)"),
        ("country = 'US'",              250,        "maybe (depends)"),
        ("status = 'active'",           4,          "seq scan cheaper"),
        ("created_at range, 1 day",     None,       None),
    ]
    for label, d, verdict in cases:
        if d is not None:
            sel = selectivity_eq(d)
            print(f"{label:<32}{d:>10,}{sel:>14.6f}{verdict:>22}")
    sel_range = selectivity_range(0, 86_400, 0, 31_536_000)
    print(f"{'created_at range, 1 day':<32}{'-':>10}{sel_range:>14.6f}{'use index (range)':>22}")
    assert selectivity_eq(10_000_000) < 0.01
    assert selectivity_eq(4) > 0.1
    print(f"\n[check] PK selectivity {selectivity_eq(10_000_000):.7f} < 0.01 (use idx); "
          f"4-value enum {selectivity_eq(4):.3f} > 0.1 (skip idx): OK")


def section_d():
    banner("SECTION D: query optimization - the planner picks the cheapest plan")
    print("You write declarative SQL. The planner enumerates physical plans, "
          "estimates each one's COST (predicted I/O + CPU), and runs the cheapest.")
    print("Cost units are arbitrary but consistent - the planner only needs a")
    print("correct RANKING, not absolute time. Defaults (PostgreSQL):")
    print("  seq_page_cost=1.0  random_page_cost=4.0  cpu_tuple=0.01\n")
    spc, rpc, cpu = 1.0, 4.0, 0.01
    N = 1_000_000
    pages = math.ceil(N / 20)         # 200 B/row
    distinct = 1_000_000              # near-unique column
    n_index_pages = 3                 # B+tree height for 1M rows
    print(f"table: N = {N:,} rows, {pages:,} pages (200 B/row)")
    print(f"WHERE clause on a near-unique column (distinct = {distinct:,})\n")

    print(f"{'plan':<18}{'selectivity':>14}{'rows fetched':>16}{'cost':>12}")
    print("-" * 60)
    sel = selectivity_eq(distinct)
    seq = seq_scan_cost(pages, N, spc, cpu)
    idx = index_scan_cost(n_index_pages, N, sel, rpc, cpu)
    print(f"{'seq scan':<18}{1.0:>14.6f}{N:>16,}{seq:>12.2f}")
    print(f"{'index scan':<18}{sel:>14.6f}{int(sel*N)+1:>16,}{idx:>12.2f}")
    chosen = "seq scan" if seq <= idx else "index scan"
    print(f"\nplanner picks: {chosen.upper()}")
    if chosen == "index scan":
        print(f"  (index saves {seq-idx:.2f} cost units = "
              f"{(seq-idx)/seq*100:.1f}% cheaper than seq scan)")
    assert idx < seq, "for a near-unique predicate the index must win"
    print(f"[check] index scan ({idx:.2f}) < seq scan ({seq:.2f}): OK")

    # now a LOW-selectivity predicate (a 4-value enum): index should LOSE
    print("\n--- same table, but WHERE status = 'active' (only 4 distinct values) ---")
    distinct_lo = 4
    sel_lo = selectivity_eq(distinct_lo)
    seq_lo = seq_scan_cost(pages, N, spc, cpu)              # same - scans whole table
    idx_lo = index_scan_cost(n_index_pages, N, sel_lo, rpc, cpu)
    print(f"{'plan':<18}{'selectivity':>14}{'rows fetched':>16}{'cost':>12}")
    print("-" * 60)
    print(f"{'seq scan':<18}{1.0:>14.6f}{N:>16,}{seq_lo:>12.2f}")
    print(f"{'index scan':<18}{sel_lo:>14.6f}{int(sel_lo*N):>16,}{idx_lo:>12.2f}")
    chosen_lo = "seq scan" if seq_lo <= idx_lo else "index scan"
    print(f"\nplanner picks: {chosen_lo.upper()}")
    print("  (the index would fetch 250,000 rows via RANDOM I/O - far slower than")
    print("   one sequential sweep. This is why you don't index low-cardinality")
    print("   columns that aren't part of a composite.)")
    assert seq_lo < idx_lo, "for a 25%-selective predicate seq scan must win"
    print(f"[check] seq scan ({seq_lo:.2f}) < index scan ({idx_lo:.2f}): OK")

    # the crossover point
    print("\n--- break-even: at what selectivity does the index stop winning? ---")
    # solve index_scan_cost == seq_scan_cost for sel
    # n_index_pages*rpc + sel*N*(rpc+cpu) == pages*spc + N*cpu
    num = (pages * spc + N * cpu) - (n_index_pages * rpc)
    den = N * (rpc + cpu)
    crossover = num / den
    print(f"index wins while selectivity < {crossover:.4f} "
          f"(~{crossover*100:.2f}% of rows)")
    # verify by computing both costs AT the crossover
    idx_at = index_scan_cost(n_index_pages, N, crossover, rpc, cpu)
    seq_at = seq_scan_cost(pages, N, spc, cpu)
    assert abs(idx_at - seq_at) / seq_at < 1e-6, "crossover equality"
    print(f"[check] at crossover sel={crossover:.4f}: index {idx_at:.2f} == "
          f"seq {seq_at:.2f} (within 1e-6): OK")


def gold_check():
    banner("GOLD CHECK: every computed number is self-consistent")
    fanout = 256
    # 1. B-tree height formula
    assert btree_lookup_pages(1, fanout) == 1
    assert btree_lookup_pages(1_000_000, fanout) == 3
    assert btree_lookup_pages(100_000_000, fanout) == 4
    # 2. selectivity identities
    assert abs(selectivity_eq(10) - 0.1) < 1e-9
    assert abs(selectivity_range(10, 20, 0, 100) - 0.1) < 1e-9
    # 3. WAL recovery: committed survives, uncommitted drops
    s = WALStore()
    s.begin("A"); s.write("A", "k", 1); s.commit("A")
    s.begin("B"); s.write("B", "k", 2)               # never commits
    d, c = s.recover(len(s.wal))
    assert d == {"k": 1} and c == {"A"}
    # 4. lost update vs 2PL
    assert schedule_counter([("T1", "R"), ("T2", "R"),
                             ("T1", "W"), ("T2", "W")]) == 1
    assert schedule_counter([("T1", "lock"), ("T1", "R"), ("T1", "W"),
                             ("T1", "unlock"),
                             ("T2", "lock"), ("T2", "R"), ("T2", "W"),
                             ("T2", "unlock")]) == 2
    # 5. cost model: index wins for high-selectivity, loses for low
    pages = math.ceil(1_000_000 / 20)
    assert index_scan_cost(3, 1_000_000, selectivity_eq(1_000_000)) < \
           seq_scan_cost(pages, 1_000_000)
    assert seq_scan_cost(pages, 1_000_000) < \
           index_scan_cost(3, 1_000_000, selectivity_eq(4))
    print("checks passed:")
    print("  [check] B+tree height: 1 row=1, 1M=3, 100M=4 (fanout 256): OK")
    print("  [check] selectivity_eq(10)=0.1, selectivity_range(10,20,0,100)=0.1: OK")
    print("  [check] WAL recovery keeps committed 'A', drops uncommitted 'B': OK")
    print("  [check] lost-update schedule -> 1; 2PL schedule -> 2: OK")
    print("  [check] index wins for PK selectivity, loses for 4-value enum: OK")
    print("[check] databases.py self-consistent:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("databases.py - reference overview. All numbers below feed DATABASES.md.")
    print("stdlib only. Run: python3 databases.py")
    section_a()
    section_b()
    section_c()
    section_d()
    gold_check()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
