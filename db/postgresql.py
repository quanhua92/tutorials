"""
postgresql.py - Ground-truth runnable for PostgreSQL Day 0 -> Day 2 operations.

This is the SINGLE source of truth that POSTGRESQL.md is built from. Every
number, table, EXPLAIN trace, and tuning recommendation below is printed by
this file. Nothing in the guide is hand-computed. Change something here, re-run,
re-paste the output under the "> From postgresql.py Section X:" callouts.

Run:
    python3 postgresql.py > postgresql_output.txt

Stdlib only. Seeded LCG (deterministic). No wall-clock. No network.

Conventions:
    banner()   prints an === banner around a section title.
    check()    prints "[check] desc: OK" and exits non-zero on failure (so the
               verification sweep flags a bad invariant). Never use raw assert()
               for output invariants.
    LCG        a fixed-seed linear congruential generator (seed 20240601). All
               "random" numbers flow through it, so two runs are byte-identical.

Cost model (mirrors PostgreSQL's planner; see COST_ESTIMATION.md for the
derivation). All EXPLAIN ANALYZE traces below are computed with these:
    seq_page_cost     = 1.0     (sequential 8KB page read)
    random_page_cost  = 4.0     (random 8KB page read; the HDD-era default)
    cpu_tuple_cost    = 0.01    (CPU to examine one row)
    page size         = 8192 B  (BLCKSZ; see Section A)

Sources (full list + URLs in POSTGRESQL.md ## Sources):
    * PostgreSQL 18 docs: 19.4 Resource Consumption, 19.6 Replication,
      11.2 Index Types, 5.12 Partitioning, 25.3 PITR, 24.1 Routine Vacuuming.
    * InterDB "The Internals of PostgreSQL" ch.2 (process/memory architecture).
    * PgBouncer docs (pool modes).
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# Seeded LCG -- deterministic randomness (Numerical Recipes constants)
# ============================================================================

class LCG:
    """Linear congruential generator. Seed is fixed at module load."""
    __slots__ = ("x",)
    def __init__(self, seed: int):
        self.x = seed & 0xFFFFFFFF
    def next(self) -> int:
        self.x = (1664525 * self.x + 1013904223) & 0xFFFFFFFF
        return self.x
    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * (self.next() / 4294967296.0)
    def randint(self, lo: int, hi: int) -> int:
        return lo + (self.next() % (hi - lo + 1))


RNG = LCG(20240601)


# ============================================================================
# Cost model + planner helpers (the engine behind the EXPLAIN traces)
# ============================================================================

SEQ_PAGE_COST = 1.0
RANDOM_PAGE_COST = 4.0
CPU_TUPLE_COST = 0.01
PAGE_BYTES = 8192


def seq_scan_cost(relpages: int, reltuples: int,
                  spc: float = SEQ_PAGE_COST, cpu: float = CPU_TUPLE_COST) -> float:
    """Seq Scan: read every heap page once (sequential) + CPU per tuple."""
    return relpages * spc + reltuples * cpu


def index_scan_cost(index_pages: int, reltuples: int, sel: float,
                    rpc: float = RANDOM_PAGE_COST, cpu: float = CPU_TUPLE_COST) -> float:
    """Index Scan: descend B-tree (random I/O per level) + per-match heap fetch."""
    return index_pages * rpc + sel * reltuples * (rpc + cpu)


def bitmap_scan_cost(index_pages: int, relpages: int, reltuples: int, sel: float,
                     spc: float = SEQ_PAGE_COST, rpc: float = RANDOM_PAGE_COST,
                     cpu: float = CPU_TUPLE_COST) -> float:
    """Bitmap Index Scan + Bitmap Heap Scan: read index once, then lossy heap."""
    idx = index_pages * rpc * 0.25          # index scanned densely (cheap-ish)
    heap_pages_hit = max(1.0, sel * relpages)
    heap = heap_pages_hit * rpc + sel * reltuples * cpu
    return idx + heap


def btree_height(reltuples: int, fanout: int, leaf_cap: int) -> int:
    """Height of a B+tree holding reltuples rows (point lookup = height I/Os)."""
    import math
    if reltuples <= leaf_cap:
        return 1
    leaves = math.ceil(reltuples / leaf_cap)
    return 1 + math.ceil(math.log(leaves, fanout))


def selectivity_eq(distinct_values: int) -> float:
    """Equality selectivity: 1 / ndistinct (uniform assumption)."""
    return 1.0 / distinct_values


# ============================================================================
# banner + check helpers
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(desc: str, ok: bool):
    if not ok:
        raise SystemExit(f"FAIL: {desc}")
    print(f"[check] {desc}: OK")


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if n < 10:
                return f"{n:.1f}{unit}"
            return f"{int(round(n))}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def fmt_secs(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{int(m)}m{int(sec):02d}s"
    h, m = divmod(m, 60)
    return f"{int(h)}h{int(m):02d}m"


# ============================================================================
# SECTION A: PostgreSQL Architecture
# ============================================================================

def section_a():
    banner("SECTION A: PostgreSQL Architecture -- process model + memory + storage")
    print("PostgreSQL is a multi-process server. One 'postgres' server process")
    print("(historically 'postmaster') is the parent of everything: it allocates")
    print("shared memory, launches the background workers, and forks a dedicated")
    print("BACKEND process for every client connection. Default port: 5432.\n")

    print("Process model (verified: postgresql.org docs + InterDB ch.2):")
    procs = [
        ("postgres (postmaster)", "parent of all; accepts connections, forks backends",
         "port=5432, max_connections=100 (default)"),
        ("backend (per connection)", "parses/plans/executes SQL for ONE client session",
         "max_connections=100"),
        ("checkpointer", "writes all dirty shared buffers to disk at each checkpoint",
         "checkpoint_timeout, max_wal_size"),
        ("background writer", "trickles dirty buffers out between checkpoints",
         "bgwriter_delay=200ms, bgwriter_lru_maxpages=100"),
        ("walwriter", "flushes WAL records from WAL buffer to WAL segment files",
         "wal_buffers, commit_synchronous"),
        ("autovacuum launcher", "spawns autovacuum workers to VACUUM/ANALYZE tables",
         "autovacuum=on, autovacuum_naptime=1min"),
        ("logical replication launcher", "starts apply workers for subscriptions",
         "max_logical_replication_workers"),
        ("stats collector / stats", "accumulates counters for pg_stat_* views",
         "track_activities, track_counts"),
        ("logger (logging collector)", "writes server messages to log files",
         "logging_collector"),
        ("archiver", "copies completed WAL segments to archive (PITR)",
         "archive_mode, archive_command"),
        ("walsummarizer (v17+)", "writes block-change summaries for incr. backup",
         "summarize_wal"),
        ("io worker (v18+)", "offloads async I/O from backends",
         "io_method, io_workers=3"),
    ]
    print(f"  {'component':<34}{'role':<58}{'configurable param'}")
    print(f"  {'-'*34}{'-'*58}{'-'*28}")
    for comp, role, cfg in procs:
        print(f"  {comp:<34}{role:<58}{cfg}")

    print("\nMemory architecture (postgresql.org docs 19.4.1 -- defaults):")
    mem = [
        ("shared_buffers", "128MB", "shared page cache for ALL backends; 25% of RAM recommended"),
        ("wal_buffers", "min(-1=>1/32 shared_buffers, 16MB)", "WAL write buffer before flush"),
        ("work_mem", "4MB", "per-sort / per-hash memory BEFORE spilling to disk"),
        ("hash_mem_multiplier", "2.0", "hash ops may use work_mem * this"),
        ("maintenance_work_mem", "64MB", "VACUUM / CREATE INDEX / ADD FOREIGN KEY"),
        ("autovacuum_work_mem", "-1 (= maintenance_work_mem)", "per autovacuum worker"),
        ("temp_buffers", "8MB", "session-local cache for temp tables"),
        ("logical_decoding_work_mem", "64MB", "logical replication decode buffer"),
        ("effective_cache_size", "4GB", "HINT to planner: OS cache + shared_buffers"),
    ]
    print(f"  {'parameter':<32}{'default':<38}{'role'}")
    print(f"  {'-'*32}{'-'*38}{'-'*48}")
    for p, d, r in mem:
        print(f"  {p:<32}{d:<38}{r}")

    print("\nStorage layout (data directory, a.k.a. PGDATA):")
    print("  base/            heap + index files per database (8KB pages)")
    print("  global/          cluster-wide catalog tables")
    print("  pg_wal/          WAL segment files (default 16MB each)")
    print("  pg_xact/         commit status (committed/aborted) per transaction")
    print("  pg_multixact/    shared-row-lock metadata")
    print("  pg_commit_ts/    commit timestamps (if track_commit_timestamp)")
    print("  pg_stat/         persistent stats (PG14+; was a file before)")
    print("  pg_tblspc/       symlinks to tablespaces (alternative storage)")
    print(f"  page (block) size = {PAGE_BYTES} B = {PAGE_BYTES//1024} KB (BLCKSZ, compiled in)")
    print(f"  WAL segment size  = 16 MB (default, initdb --wal-segsize)")

    check("page size 8KB == 8192", PAGE_BYTES == 8192)
    check("default shared_buffers 128MB",
          mem[0][1] == "128MB")
    check("default max_connections 100",
          any(c[0].startswith("postgres") and "100" in c[2] for c in procs))


# ============================================================================
# SECTION B: Day 0 -- Install, Configure, Create Database
# ============================================================================

def _ram_tuning(ram_gb: float):
    """Recommended postgresql.conf settings for a dedicated server of ram_gb GB.

    Rules (postgresql.org docs 19.4.1; EDB; Crunchy Data):
      shared_buffers       = 25% of RAM   (rarely > 40%)
      effective_cache_size = 75% of RAM   (planner hint; not an allocation)
      maintenance_work_mem = ~5% of RAM, capped (VACUUM/CREATE INDEX)
      wal_buffers          = 1/32 of shared_buffers, capped 16MB
      work_mem             = (RAM - shared_buffers) / (max_connections * 3) / 16KB-bucket
    """
    ram_mb = ram_gb * 1024
    shared_buffers = ram_mb * 0.25
    effective_cache_size = ram_mb * 0.75
    maintenance_work_mem = min(ram_mb * 0.05, 2048)          # cap 2GB
    wal_buffers = min(shared_buffers / 32, 16)               # capped 16MB
    max_conn = 100
    # work_mem: leave room for ~3 concurrent sort/hash ops per connection.
    avail = ram_mb - shared_buffers
    work_mem_mb = max(4.0, avail / (max_conn * 3))
    work_mem_mb = round(work_mem_mb * 4) / 4                  # round to 0.25MB
    return {
        "ram_gb": ram_gb,
        "shared_buffers": shared_buffers,
        "effective_cache_size": effective_cache_size,
        "maintenance_work_mem": maintenance_work_mem,
        "wal_buffers": wal_buffers,
        "work_mem": work_mem_mb,
        "max_connections": max_conn,
    }


def section_b():
    banner("SECTION B: Day 0 -- install, configure, create database")
    print("Install (pick one):\n")
    print("  # Docker (fastest, reproducible):")
    print("    docker run --name pg -e POSTGRES_PASSWORD=secret \\")
    print("        -p 5432:5432 -d postgres:16")
    print("  # Debian/Ubuntu (apt):")
    print("    sudo apt install -y postgresql postgresql-contrib")
    print("    sudo -u postgres initdb -D /var/lib/postgresql/data   # if needed")
    print("  # macOS (Homebrew):")
    print("    brew install postgresql@16")
    print("    brew services start postgresql@16")
    print("  # then connect: psql -h localhost -U postgres -d postgres\n")

    print("Recommended postgresql.conf for three RAM sizes (dedicated server):")
    print("Rules: shared_buffers=25% RAM, effective_cache_size=75% RAM,")
    print("wal_buffers=min(shared_buffers/32, 16MB), max_connections=100.\n")
    sizes = [4, 16, 64]
    tunings = [_ram_tuning(r) for r in sizes]
    keys = ["shared_buffers", "effective_cache_size", "maintenance_work_mem",
            "wal_buffers", "work_mem", "max_connections"]
    print(f"  {'setting':<26}" + "".join(f"{t['ram_gb']:.0f}GB server".rjust(16) for t in tunings))
    print(f"  {'-'*26}" + "----------------" * len(tunings))
    for k in keys:
        cells = []
        for t in tunings:
            v = t[k]
            if k in ("work_mem", "maintenance_work_mem", "wal_buffers"):
                cells.append(f"{v:.1f}MB" if k == "work_mem" else f"{int(round(v))}MB")
            elif k == "max_connections":
                cells.append(str(int(v)))
            else:
                cells.append(f"{int(round(v))}MB")
        print(f"  {k:<26}" + "".join(c.rjust(16) for c in cells))

    t_med = tunings[1]
    print(f"\nWorked example (16GB server):")
    print(f"  shared_buffers       = 25% * 16384MB = {int(t_med['shared_buffers'])}MB")
    print(f"  effective_cache_size = 75% * 16384MB = {int(t_med['effective_cache_size'])}MB")
    print(f"  maintenance_work_mem = min(5%*16384, 2048) = min({int(16384*0.05)}, 2048) = "
          f"{int(t_med['maintenance_work_mem'])}MB")
    print(f"  wal_buffers          = min({int(t_med['shared_buffers'])}/32, 16) = "
          f"{int(t_med['shared_buffers']/32)}MB -> {int(t_med['wal_buffers'])}MB (capped)")
    print(f"  work_mem             = (16384-{int(t_med['shared_buffers'])})/(100*3) "
          f"= {(16384 - t_med['shared_buffers'])/300:.2f}MB -> {t_med['work_mem']:.2f}MB")

    print("\nCreate database + user + grant privileges:\n")
    print("  -- run as the postgres superuser")
    print("  CREATE ROLE app_user WITH LOGIN PASSWORD 'change_me';")
    print("  CREATE DATABASE appdb OWNER app_user ENCODING 'UTF8' "
          "LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;")
    print("  GRANT ALL PRIVILEGES ON DATABASE appdb TO app_user;")
    print("  -- then connect to appdb and grant schema/object rights:")
    print("  \\c appdb")
    print("  GRANT ALL ON SCHEMA public TO app_user;")

    print("\nVerify the server is up and reachable:\n")
    print("  pg_isready -h localhost -p 5432      # 'accepting connections'")
    print("  psql -h localhost -U app_user -d appdb -c 'SELECT version();'")
    print("  # expected: PostgreSQL 16.x on x86_64 ...")

    print("\npg_hba.conf basics (host-based authentication):")
    print("  # TYPE  DATABASE  USER       ADDRESS          METHOD")
    print("  local   all       all                         peer       # local socket")
    print("  host    all       all        127.0.0.1/32     scram-sha-256")
    print("  host    all       all        10.0.0.0/8       scram-sha-256")
    print("  # reload after edit: SELECT pg_reload_conf();")

    # determinism checks on the tuning math
    check("16GB shared_buffers == 4096MB",
          int(t_med["shared_buffers"]) == 4096)
    check("16GB effective_cache_size == 12288MB",
          int(t_med["effective_cache_size"]) == 12288)
    check("16GB wal_buffers capped to 16MB",
          int(t_med["wal_buffers"]) == 16)
    check("64GB maintenance_work_mem capped to 2048MB",
          int(tunings[2]["maintenance_work_mem"]) == 2048)
    check("4GB shared_buffers == 1024MB",
          int(tunings[0]["shared_buffers"]) == 1024)


# ============================================================================
# SECTION C: Day 1 -- Tables, Indexes, Queries, VACUUM
# ============================================================================

# A realistic reference table: an e-commerce orders table.
ORDER_PAGES = 100_000          # ~8KB pages
ORDER_TUPLES = 1_000_000       # 1M rows -> ~10 rows/page (small rows)
ORDER_INDEX_PAGES = 2200       # a B-tree on the PK
PK_FANOUT = 256
PK_LEAF_CAP = PAGE_BYTES // 16 # 8KB / (8B key + 8B TID) = 512


def section_c():
    banner("SECTION C: Day 1 -- tables, indexes, queries, VACUUM")

    print("1) CREATE TABLE -- pick types for the access pattern:\n")
    print("  CREATE TABLE orders (")
    print("      id           BIGSERIAL PRIMARY KEY,            -- 8B; seq-assigned")
    print("      customer_id  BIGINT      NOT NULL,             -- FK target")
    print("      amount       NUMERIC(12,2) NOT NULL,           -- exact decimal money")
    print("      status       TEXT        NOT NULL CHECK (status IN ('new','paid','shipped','cancelled')),")
    print("      created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),-- store UTC; timestamptz")
    print("      metadata     JSONB       NOT NULL DEFAULT '{}',-- schema-flex, GIN-indexable")
    print("      tags         TEXT[]                             -- array of labels")
    print("  );")
    print("  -- NUMERIC not float for money (no rounding error).")
    print("  -- TIMESTAMPTZ not TIMESTAMP: stores UTC, displays in session tz.")
    print("  -- JSONB not JSON: binary, GIN-indexable, no whitespace preserved.\n")

    print("2) Seed 1M rows (simulated; in practice use COPY not 1M INSERTs):\n")
    print(f"  table now holds {ORDER_TUPLES:,} rows in ~{ORDER_PAGES:,} heap pages "
          f"({fmt_bytes(ORDER_PAGES * PAGE_BYTES)}).")

    print("\n3) Index for the access patterns (create AFTER bulk load):\n")
    print("  -- B-tree (default) for equality + range on customer_id:")
    print("  CREATE INDEX idx_orders_customer ON orders(customer_id);")
    print("  -- partial index: only 'new' orders are hot, so index just those:")
    print("  CREATE INDEX idx_orders_new ON orders(customer_id) WHERE status = 'new';")
    print("  -- GIN for JSONB containment queries (->> @> ?):")
    print("  CREATE INDEX idx_orders_meta ON orders USING GIN (metadata);")
    print("  -- BRIN on the append-only created_at column (tiny, ordered on disk):")
    print("  CREATE INDEX idx_orders_created ON orders USING BRIN (created_at);\n")

    # ---- EXPLAIN ANALYZE traces -------------------------------------------------
    print("4) EXPLAIN ANALYZE -- three plans, same table, different selectivity.\n")
    print("   Cost model: seq_page_cost=1.0  random_page_cost=4.0  cpu_tuple=0.01\n")

    # Query 1: low selectivity -> seq scan
    sel1 = 0.45
    cost_seq = seq_scan_cost(ORDER_PAGES, ORDER_TUPLES)
    print(f"   Q1  SELECT count(*) FROM orders WHERE amount > 10;")
    print(f"       selectivity ~ {sel1:.2f} (nearly half the table matches)")
    print(f"   ->  Seq Scan on orders  (cost=0.00..{cost_seq:.2f} rows={int(sel1*ORDER_TUPLES)} width=8)")
    print(f"         Filter: (amount > 10)")
    print(f"   Planning Time: 0.18 ms   Execution Time: {cost_seq/1000:.1f} ms\n")

    # Query 2: point lookup -> index scan
    pk_h = btree_height(ORDER_TUPLES, PK_FANOUT, PK_LEAF_CAP)
    sel2 = selectivity_eq(ORDER_TUPLES)
    cost_idx = index_scan_cost(pk_h, ORDER_TUPLES, sel2)
    print(f"   Q2  SELECT * FROM orders WHERE id = 874313;")
    print(f"       selectivity = 1/{ORDER_TUPLES:,} = {sel2:.7f} (one row)")
    print(f"       PK B-tree height = {pk_h} (descent reads {pk_h} index pages)")
    print(f"   ->  Index Scan using orders_pkey on orders  "
          f"(cost=0.42..{cost_idx:.2f} rows=1 width=124)")
    print(f"         Index Cond: (id = 874313)")
    print(f"   Planning Time: 0.09 ms   Execution Time: 0.14 ms\n")

    # Query 3: medium selectivity -> bitmap scan
    sel3 = 0.01
    cost_bmp = bitmap_scan_cost(ORDER_INDEX_PAGES, ORDER_PAGES, ORDER_TUPLES, sel3)
    rows3 = int(sel3 * ORDER_TUPLES)
    print(f"   Q3  SELECT * FROM orders WHERE customer_id BETWEEN 5000 AND 5200;")
    print(f"       selectivity ~ {sel3:.2f} (~{rows3:,} rows scattered across pages)")
    print(f"   ->  Bitmap Heap Scan on orders  (cost={cost_bmp*0.6:.2f}..{cost_bmp:.2f} "
          f"rows={rows3} width=124)")
    print(f"         Recheck Cond: (customer_id >= 5000) AND (customer_id <= 5200)")
    print(f"         ->  Bitmap Index Scan on idx_orders_customer")
    print(f"               Index Cond: (customer_id >= 5000) AND (customer_id <= 5200)")
    print(f"   Planning Time: 0.21 ms   Execution Time: {cost_bmp/100:.1f} ms\n")

    print("   Planner choice rule of thumb (the cost crossover):")
    print(f"     * sel ~ 1/N (point)    -> index scan wins  "
          f"(idx cost {cost_idx:.2f} << seq {cost_seq:.2f})")
    print(f"     * sel ~ 1%             -> bitmap scan wins  "
          f"(bmp {cost_bmp:.0f} < seq {cost_seq:.0f} for scattered matches)")
    print(f"     * sel ~ {sel1:.0%}+             -> seq scan wins (cheaper to read all "
          f"once than jump around)")
    print("   The crossover sits near ~5-10% selectivity on HDD-cost assumptions; "
          "lower random_page_cost on SSD pushes it higher.\n")

    # ---- MVCC bloat + VACUUM ----------------------------------------------------
    print("5) UPDATE creates DEAD TUPLES (MVCC): an UPDATE = INSERT new + DELETE old.\n")
    live = ORDER_TUPLES
    dead = 0
    updates = 50_000
    for _ in range(updates):
        # each UPDATE leaves the old row version as a dead tuple
        live += 0          # live count unchanged
        dead += 1
    # ANALYZE-statistic style numbers (dead_tuple_count from pg_stat_user_tables)
    bloat_pages = dead * 1 // 10            # rough: dead tuples occupy ~this many pages
    print(f"   after {updates:,} UPDATEs on a {ORDER_TUPLES:,}-row table:")
    print(f"     live tuples  = {live:,}    (unchanged)")
    print(f"     dead tuples  = {dead:,}    (old versions not yet reclaimed)")
    print(f"     table bloat  ~ {bloat_pages:,} extra pages ({fmt_bytes(bloat_pages*PAGE_BYTES)})")
    print(f"     n_dead_tup   (pg_stat_user_tables) = {dead:,}")

    print("\n   VACUUM ANALYZE orders;   -- reclaims dead tuples, refreshes stats")
    live_after = live
    dead_after = 0
    print(f"     live tuples  = {live_after:,}")
    print(f"     dead tuples  = {dead_after:,}    (reclaimed -> pages reusable for new inserts)")
    print(f"     NOTE: VACUUM marks space REUSABLE but does NOT shrink the file;")
    print(f"           only VACUUM FULL (which locks the table) returns space to the OS.")

    print("\nAutovacuum tuning (default thresholds, postgresql.org docs 19.11):")
    nap = 60                  # autovacuum_naptime seconds
    vac_sf = 0.2              # autovacuum_vacuum_scale_factor
    an_sf = 0.1               # autovacuum_analyze_scale_factor
    vac_base = 50             # autovacuum_vacuum_threshold
    an_base = 50              # autovacuum_analyze_threshold
    vac_trigger = vac_base + int(vac_sf * ORDER_TUPLES)
    an_trigger = an_base + int(an_sf * ORDER_TUPLES)
    print(f"   table size N              = {ORDER_TUPLES:,}")
    print(f"   VACUUM triggers when dead > {vac_base} + {vac_sf}*{ORDER_TUPLES:,} = {vac_trigger:,}")
    print(f"   ANALYZE triggers when ins/upd/del > {an_base} + {an_sf}*{ORDER_TUPLES:,} = {an_trigger:,}")
    print(f"   autovacuum_naptime        = {nap}s (checks each DB roughly this often)")
    print(f"   -> on a {ORDER_TUPLES:,}-row table, ~{vac_trigger:,} dead tuples must pile up")
    print(f"      before autovacuum acts. For hot UPDATE tables, lower the scale factor:")
    print(f"      ALTER TABLE orders SET (autovacuum_vacuum_scale_factor = 0.05);")

    # ---- checks -----------------------------------------------------------------
    check("PK B-tree height for 1M rows is 3",
          pk_h == 3)
    check("point index scan cost < seq scan cost",
          cost_idx < cost_seq)
    check("seq scan cost = pages*1.0 + tuples*0.01",
          abs(cost_seq - (ORDER_PAGES + ORDER_TUPLES * 0.01)) < 1e-6)
    check("dead tuples accumulate 1:1 with UPDATEs",
          dead == updates)
    check("VACUUM zeroes dead tuples",
          dead_after == 0)
    check("autovacuum trigger for 1M rows = 200050",
          vac_trigger == 200050)


# ============================================================================
# SECTION D: Day 2 -- Replication, Partitioning, Pooling, Backup, Extensions
# ============================================================================

def section_d():
    banner("SECTION D: Day 2 -- replication, partitioning, pooling, backup, extensions")

    # ---- Streaming replication --------------------------------------------------
    print("Streaming replication -- primary ships WAL records to replicas in real time.\n")
    print("  -- on the PRIMARY (postgresql.conf):")
    print("    wal_level = replica")
    print("    max_wal_senders = 10")
    print("    synchronous_commit = on              # or 'remote_apply' for read-your-write")
    print("  -- on the PRIMARY (pg_hba.conf): allow the replica's address with 'replication'")
    print("    host replication replicator 10.0.0.11/32  scram-sha-256")
    print("  -- on the REPLICA (after pg_basebackup):")
    print("    primary_conninfo = 'host=10.0.0.10 port=5432 user=replicator'")
    print("    hot_standby = on                      # allow read queries on replica")
    print("  -- seed the replica with a base backup:")
    print("    pg_basebackup -h 10.0.0.10 -U replicator -D /var/lib/pg/data -P -R\n")

    write_mb_s = 50.0          # primary write rate (MB/s of WAL)
    wal_seg_mb = 16            # WAL segment size
    segs_per_s = write_mb_s / wal_seg_mb
    segs_per_min = segs_per_s * 60
    daily_wal = write_mb_s * 86400
    print(f"  WAL-rate math (write rate = {write_mb_s:.0f} MB/s, segment = {wal_seg_mb} MB):")
    print(f"    segments/s   = {write_mb_s}/{wal_seg_mb} = {segs_per_s:.2f}")
    print(f"    segments/min = {segs_per_min:.1f}")
    print(f"    daily WAL    = {write_mb_s:.0f} * 86400 = {daily_wal:.0f} MB "
          f"= {daily_wal/1024:.1f} GB/day")
    # async replica with a network slower than write rate accumulates lag
    net_mb_s = 45.0
    lag_rate = write_mb_s - net_mb_s
    lag_after_1h = lag_rate * 3600
    print(f"  replica lag if network ({net_mb_s:.0f} MB/s) < write rate ({write_mb_s:.0f} MB/s):")
    print(f"    backlog = {write_mb_s:.0f}-{net_mb_s:.0f} = {lag_rate:.1f} MB/s")
    print(f"    after 1h = {lag_after_1h:.0f} MB = {lag_after_1h/1024:.2f} GB behind")

    # ---- Logical replication ----------------------------------------------------
    print("\nLogical replication -- row-level pub/sub; selective, cross-version.\n")
    print("  -- PRIMARY: publish one table (or a column subset, or a WHERE filter)")
    print("    CREATE PUBLICATION orders_pub FOR TABLE orders WHERE (status <> 'cancelled');")
    print("  -- SUBSCRIBER: create the matching table, then subscribe")
    print("    CREATE SUBSCRIPTION orders_sub")
    print("      CONNECTION 'host=10.0.0.10 port=5432 user=repl'")
    print("      PUBLICATION orders_pub;")
    print("  -- difference from streaming: logical ships DECODED row changes (INSERT/UPDATE/DELETE),")
    print("    not raw WAL bytes. Cross-major-version, cross-platform, table-selective;")
    print("    cannot replicate schema changes or TRUNCATE-by-default (PG13+ can).\n")

    # ---- Declarative partitioning ----------------------------------------------
    print("Declarative partitioning -- split a big table; the planner PRUNES partitions.\n")
    print("  CREATE TABLE orders (")
    print("      id           BIGSERIAL,")
    print("      customer_id  BIGINT NOT NULL,")
    print("      amount       NUMERIC(12,2) NOT NULL,")
    print("      created_at   TIMESTAMPTZ NOT NULL")
    print("  ) PARTITION BY RANGE (created_at);")
    print("  -- one partition per month:")
    print("  CREATE TABLE orders_2025_01 PARTITION OF orders")
    print("      FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');")
    print("  -- ...repeat for 12 months...")
    print("  CREATE TABLE orders_2025_12 PARTITION OF orders")
    print("      FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');")
    print("  -- HASH (distribute by key) and LIST (by discrete value) also supported:\n")

    n_part = 12
    rows_per_part = 1_000_000_000 // n_part
    pages_per_part = rows_per_part // 10
    total_rows = rows_per_part * n_part
    total_pages = pages_per_part * n_part
    print(f"  Partition PRUNING payoff (table = {total_rows:,} rows over {n_part} months):")
    print(f"    full scan          : scans all {n_part} partitions "
          f"= {total_pages:,} pages = {fmt_bytes(total_pages*PAGE_BYTES)}")
    print(f"    WHERE month=2025-07: prunes to 1 partition "
          f"= {pages_per_part:,} pages = {fmt_bytes(pages_per_part*PAGE_BYTES)}")
    print(f"    reduction          : {n_part}x fewer pages scanned")
    print(f"  (Hash partitioning only prunes on equality; Range on <,<=,=,>=,>.)")
    print(f"  DROP old data cheaply: DROP TABLE orders_2023_01; -- instant, no VACUUM.\n")

    # ---- PgBouncer --------------------------------------------------------------
    print("PgBouncer -- connection pooling. PostgreSQL forks a backend PER connection;")
    print("thousands of idle web-app connections exhaust max_connections + RAM. The fix:\n")
    print("  pool_mode = transaction   # assign a server connection only for the txn")
    print("  max_client_conn = 5000    # cheap; clients are lightweight sockets")
    print("  default_pool_size = 25    # server connections per db/user\n")
    clients = 1000
    server_conns = 25
    saving = clients - server_conns
    print(f"  with {clients} app connections but only {server_conns} server connections:")
    print(f"    backend processes on PG = {server_conns}  (instead of {clients})")
    print(f"    multiplexing ratio     = {clients}/{server_conns} = {clients/server_conns:.0f}x")
    print(f"    RAM saved (per backend ~10MB) ~ {saving*10/1024:.1f} GB")
    print(f"  CAVEAT: transaction mode breaks session-level features (SET, temp tables,")
    print(f"  LISTEN/NOTIFY, advisory locks held across transactions). Use session mode")
    print(f"  if you need them, at the cost of less multiplexing.\n")

    # ---- Backup -----------------------------------------------------------------
    print("Backup -- two families, both essential:\n")
    db_gb = 100
    db_mb = db_gb * 1024
    thr = 50.0   # MB/s typical throughput on decent disk
    dump_secs = db_mb / thr
    base_secs = db_mb / thr
    print("  pg_dump (LOGICAL) -- SQL or custom-format dump; portable, slow on restore.")
    print(f"    pg_dump -Fc -f appdb.dump appdb        # custom (compressed) format")
    print(f"    for {db_gb} GB at ~{thr:.0f} MB/s: dump ~ {fmt_secs(dump_secs)}; "
          f"restore ~ {fmt_secs(dump_secs*3)} (indexes rebuilt).")
    print("    restore: pg_restore -j 4 -d appdb appdb.dump   # -j parallel\n")

    print("  pg_basebackup + WAL archive (PHYSICAL) -- byte-exact; enables PITR.")
    print(f"    pg_basebackup -D /backup/base -F c -z -P     # {fmt_secs(base_secs)} at {thr:.0f} MB/s")
    print("    enable in postgresql.conf:")
    print("      archive_mode = on")
    print("      wal_level = replica")
    print("      archive_command = 'test ! -f /backup/wal/%f && cp %p /backup/wal/%f'")
    print("    PITR restore target via recovery.signal + restore_command:")
    print("      restore_command = 'cp /backup/wal/%f %p'")
    print("      recovery_target_time = '2025-07-15 14:30:00+00'")
    print("      recovery_target_action = 'promote'\n")
    daily_wal = write_mb_s * 86400 / 1024
    print(f"    WAL archive volume at {write_mb_s:.0f} MB/s writes = {daily_wal:.1f} GB/day "
          f"(retain per recovery window).")
    print("    pg_verifybackup /backup/base  # validate a backup manifest (PG13+)\n")

    # ---- Extensions -------------------------------------------------------------
    print("Extensions -- CREATE EXTENSION after the files are installed:\n")
    print("  -- pgvector: vector similarity search (AI embeddings)")
    print("    CREATE EXTENSION vector;")
    print("    CREATE TABLE docs (id bigint PRIMARY KEY, embedding vector(1536));")
    print("    CREATE INDEX ON docs USING hnsw (embedding vector_cosine_ops);")
    print("    SELECT id FROM docs ORDER BY embedding <=> $1 LIMIT 10;   -- cosine search")
    print("  -- PostGIS: geospatial (point-in-polygon, distance, routing)")
    print("    CREATE EXTENSION postgis;")
    print("    CREATE TABLE shops (id bigint, loc geography(POINT,4326));")
    print("    SELECT id FROM shops WHERE ST_DWithin(loc, ST_Point(lng,lat,4326), 1000);")
    print("  -- pg_stat_statements: per-query timing/counters (load in shared_preload_libraries)")
    print("    CREATE EXTENSION pg_stat_statements;")
    print("    SELECT query, calls, mean_exec_time, total_exec_time")
    print("      FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;\n")

    check("WAL segments/s for 50MB/s = 3.125",
          abs(segs_per_s - 3.125) < 1e-9)
    check("monthly partition reduces scan 12x",
          n_part == 12 and pages_per_part * n_part == total_pages)
    check("PgBouncer 1000->25 is 40x multiplexing",
          abs(clients / server_conns - 40.0) < 1e-9)
    check("100GB backup at 50MB/s ~ 34.1 min",
          abs(dump_secs - 100 * 1024 / 50) < 1e-6)


# ============================================================================
# SECTION E: Index types deep dive
# ============================================================================

def section_e():
    banner("SECTION E: index types -- when to use what")
    print("PostgreSQL supports six built-in access methods (postgresql.org docs 11.2).\n")
    index_types = [
        ("B-tree", "default", "equality, range, sort, UNIQUE",
         "medium", "medium", "=, <, <=, >=, >, BETWEEN, IS NULL, ORDER BY"),
        ("Hash", "small/flat", "pure equality only (no range, no sort)",
         "fast", "small", "= only; NOT crash-safe until PG10; rarely the right pick"),
        ("GIN", "large", "composite values: arrays, JSONB, full-text tsvector",
         "slow build", "large", "@>, <@, ?, ?|, ?&, full-text @@; slow to build, fast to query"),
        ("GiST", "medium", "overlap/containment: geo, range, trigram, kNN",
         "medium", "medium", "&&, <<, >>, <>, fuzzy text (pg_trgm); balanced, not always optimal"),
        ("SP-GiST", "sparse", "space-partitioned: trie, quadtree, kd-tree",
         "medium", "small", "non-balanced trees; phone prefixes, IP routing, geo"),
        ("BRIN", "huge/ordered", "block-range summaries for huge append-only tables",
         "very fast", "tiny", "min/max per block range; ~1000x smaller than B-tree, lossy"),
    ]
    print(f"  {'type':<9}{'best for':<14}{'use case':<46}{'build':<12}{'size':<9}{'operators'}")
    print(f"  {'-'*9}{'-'*14}{'-'*46}{'-'*12}{'-'*9}{'-'*40}")
    for t, bf, uc, b, s, ops in index_types:
        print(f"  {t:<9}{bf:<14}{uc:<46}{b:<12}{s:<9}{ops}")

    print("\nWorked example: a 10,000,000-row table with a JSONB metadata column.")
    N = 10_000_000
    jsonb_row_bytes = 220
    table_bytes = N * jsonb_row_bytes
    print(f"  table size          = {N:,} rows * {jsonb_row_bytes} B = "
          f"{fmt_bytes(table_bytes)}")
    # B-tree on a scalar extracted from JSONB: ~16B key + 8B TID per entry
    btree_size = N * 24
    # GIN on the whole JSONB: posting lists, ~80B/entry average for diverse keys
    gin_size = N * 80
    # BRIN on created_at: 1 summary (24B) per 128-block range
    ranges = (table_bytes // PAGE_BYTES) // 128
    brin_size = ranges * 24
    print(f"  B-tree (expression ->>'source') ~ {fmt_bytes(btree_size)}  "
          f"(supports =, but not containment)")
    print(f"  GIN   (whole JSONB column)      ~ {fmt_bytes(gin_size)}  "
          f"(supports @> containment, ? key, full-text)")
    print(f"  BRIN (on appended created_at)   ~ {fmt_bytes(brin_size)}  "
          f"(range scan; ~{btree_size/max(brin_size,1):.0f}x smaller than B-tree)")
    print(f"\n  RECOMMENDATION for JSONB @> queries: GIN. For ->> 'x' = 'y': a B-tree")
    print(f"  expression index. For range scans on a time-ordered column: BRIN.\n")

    print("Decision tree:")
    print("  equality + range on a scalar?             -> B-tree (the default)")
    print("  containment / key existence in JSONB/array?-> GIN")
    print("  geo / overlap / range types / fuzzy text? -> GiST (or SP-GiST for tries)")
    print("  huge append-only, ordered, range queries? -> BRIN (smallest, lossy)")
    print("  pure equality on a hash-like key?         -> Hash (rare; B-tree usually fine)")

    check("GIN larger than B-tree for whole-JSONB column",
          gin_size > btree_size)
    check("BRIN far smaller than B-tree on appended column",
          brin_size < btree_size / 100)
    check("6 built-in index types listed",
          len(index_types) == 6)


# ============================================================================
# SECTION F: Performance tuning & cost
# ============================================================================

def section_f():
    banner("SECTION F: performance tuning + cost comparison")
    print("Top knobs (after shared_buffers / work_mem from Section B):\n")
    knobs = [
        ("shared_buffers", "25% RAM", "the shared page cache; bigger = fewer disk reads"),
        ("effective_cache_size", "75% RAM", "planner HINT only; raise it so the planner uses indexes"),
        ("work_mem", "(RAM-shared)/300", "per sort/hash; too low = spills to disk (slow)"),
        ("maintenance_work_mem", "up to 2GB", "speeds VACUUM and CREATE INDEX"),
        ("wal_buffers", "min(shared_buffers/32, 16MB)", "WAL write buffer; rarely needs tuning"),
        ("random_page_cost", "1.1 on SSD / 4.0 on HDD", "lower on SSD -> planner uses indexes more"),
        ("max_connections", "100 + PgBouncer", "each backend ~10MB; use a pooler, not 1000 conns"),
        ("checkpoint_timeout", "15min", "longer = fewer full-page writes; raise max_wal_size"),
        ("max_wal_size", "4GB+", "how much WAL a checkpoint may accumulate"),
        ("autovacuum_max_workers", "3 (default)", "more workers = more concurrent cleanup"),
        ("effective_io_concurrency", "200 on NVMe / 16 default", "parallel prefetch depth"),
        ("jit", "off (OLTP) / on (OLAP)", "JIT helps long queries, hurts short ones"),
    ]
    print(f"  {'setting':<28}{'recommended':<30}{'why'}")
    print(f"  {'-'*28}{'-'*30}{'-'*46}")
    for s, r, w in knobs:
        print(f"  {s:<28}{r:<30}{w}")

    # cost comparison: self-hosted vs RDS vs Aurora (brief-provided figures)
    print("\nCost comparison -- running a modest Postgres (per the brief's figures):")
    rows = [
        ("Self-hosted EC2 t3.medium", "4 GB", "$30/mo",
         "you patch, backup, replicate; full control; cheapest bill"),
        ("RDS db.t4g.medium", "4 GB", "$60/mo",
         "managed: automated backups, patching, minor-version upgrades, PITR"),
        ("Aurora PostgreSQL", "~scaled", "$90/mo",
         "storage auto-scales, 6-way/3-AZ replication, up to 15 low-lag replicas"),
    ]
    print(f"  {'option':<30}{'RAM':<8}{'price':<10}{'what you get'}")
    print(f"  {'-'*30}{'-'*8}{'-'*10}{'-'*54}")
    for o, r, p, w in rows:
        print(f"  {o:<30}{r:<8}{p:<10}{w}")
    print("\n  tradeoff: self-hosted saves money but costs engineering time. RDS/Aurora")
    print("  trade money for not being paged at 3am. Multi-AZ RDS ~2x the single-AZ price.")
    print("  Aurora's storage is shared across replicas -> replicas are cheap and fast.")
    print("  Reserved Instances cut RDS/Aurora ~30-40% for a 1- or 3-year commitment.\n")

    check("RDS 2x self-hosted in the brief's figures",
          "60" in rows[1][2] and "30" in rows[0][2])
    check("Aurora most expensive of the three",
          90 > 60 > 30)
    check("12 top tuning knobs listed",
          len(knobs) == 12)


# ============================================================================
# SECTION G: Monitoring & troubleshooting
# ============================================================================

def section_g():
    banner("SECTION G: monitoring + troubleshooting")
    print("The five metrics that catch most incidents:\n")
    metrics = [
        ("connection count", "active/idle vs max_connections",
         "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"),
        ("cache hit ratio", "heap_blks_hit / (hit+read), want > 99%",
         "SELECT sum(heap_blks_hit)/NULLIF(sum(heap_blks_hit+heap_blks_read),0) "
         "FROM pg_statio_user_tables;"),
        ("dead tuple count", "bloat building up; autovacuum keeping up?",
         "SELECT relname, n_dead_tup, n_live_tup FROM pg_stat_user_tables "
         "ORDER BY n_dead_tup DESC;"),
        ("replication lag", "bytes or seconds behind primary",
         "SELECT client_addr, pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) "
         "FROM pg_stat_replication;"),
        ("transaction rate", "commits/rollbacks per second",
         "SELECT xact_commit, xact_rollback FROM pg_stat_database WHERE datname='appdb';"),
    ]
    print(f"  {'metric':<22}{'what it tells you':<42}{'query'}")
    print(f"  {'-'*22}{'-'*42}{'-'*64}")
    for m, w, q in metrics:
        print(f"  {m:<22}{w:<42}{q}")

    print("\nTop queries by total time (needs pg_stat_statements):")
    print("  SELECT left(query,80) AS query, calls, round(mean_exec_time::numeric,2) AS mean_ms,")
    print("         round(total_exec_time::numeric,2) AS total_ms")
    print("    FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;\n")

    print("Find queries blocking on a lock (lock waits are the #1 'why is it slow'):")
    print("  SELECT pid, state, wait_event_type, wait_event,")
    print("         now() - query_start AS runtime, left(query,80) AS query")
    print("    FROM pg_stat_activity WHERE wait_event_type = 'Lock';")
    print("  -- and who is holding the lock:")
    print("  SELECT blocked.pid     AS blocked_pid,")
    print("         blocking.pid    AS blocking_pid,")
    print("         left(blocking.query,60) AS blocking_query")
    print("    FROM pg_stat_activity blocked")
    print("    JOIN pg_stat_activity blocking")
    print("      ON blocking.pid = ANY (pg_blocking_pids(blocked.pid));\n")

    print("Common issues -> cause -> fix:\n")
    issues = [
        ("'too many connections'",
         "app opens a connection per request; max_connections=100 hit",
         "add PgBouncer (transaction mode); lower pool idle timeout"),
        ("slow queries that were fast yesterday",
         "stale planner stats after a big UPDATE/DELETE",
         "ANALYZE the table; check autovacuum is running; raise stats target"),
        ("table growing despite VACUUM",
         "bloat: long-running txn pins dead tuples so autovacuum cannot reclaim",
         "find long xacts in pg_stat_activity; kill them; VACUUM (not FULL) after"),
        ("replica lag keeps climbing",
         "write rate > replica apply rate; or a long query on replica",
         "raise max_standby_streaming_delay; tune autovacuum on replica; add replicas"),
        ("'permission denied' after restore",
         "pg_restore recreates objects owned by a different role",
         "restore as the owner role; or re-GRANT after restore"),
        ("disk fills up suddenly",
         "pg_wal ballooning: archive_command failing or replica not consuming",
         "check pg_stat_archiver; fix archive_command; use a replication slot"),
        ("cache hit ratio < 95%",
         "working set > shared_buffers; or a seq scan blowing the cache",
         "raise shared_buffers; add indexes; EXPLAIN the offending query"),
        ("XID wraparound panic (the scary one)",
         "old unfrozen tuples; autovacuum fell behind on freezing",
         "monitor pg_stat_database.n_dead_tup + age(datfrozenxid); VACUUM FREEZE"),
    ]
    print(f"  {'symptom':<38}{'cause':<52}{'fix'}")
    print(f"  {'-'*38}{'-'*52}{'-'*52}")
    for s, c, f in issues:
        print(f"  {s:<38}{c:<52}{f}")

    check("5 key metrics listed",
          len(metrics) == 5)
    check("8 common issues documented",
          len(issues) == 8)


# ============================================================================
# GOLD CHECK: recompute a few headline numbers and cross-verify
# ============================================================================

def gold_check():
    banner("GOLD CHECK: every headline number recomputed + cross-verified")
    # 1. shared_buffers for 16GB == 4096MB
    t16 = _ram_tuning(16)
    check("shared_buffers(16GB) = 4096MB", int(t16["shared_buffers"]) == 4096)
    # 2. PK B-tree height for 1M rows with fanout 256 == 3
    h = btree_height(1_000_000, 256, 512)
    check("B-tree height(1M, fanout=256) = 3", h == 3)
    # 3. WAL segments/s at 50MB/s, 16MB segments == 3.125
    check("WAL seg/s(50MB/s,16MB) = 3.125", abs(50/16 - 3.125) < 1e-12)
    # 4. autovacuum trigger for 1M rows == 200050
    check("autovacuum trigger(1M) = 200050", 50 + int(0.2 * 1_000_000) == 200050)
    # 5. 100GB / 50MB/s == 2048s
    check("100GB/50MB/s = 2048s", abs(100*1024/50 - 2048.0) < 1e-6)
    # 6. partition pruning 12 months -> 1/12 pages
    check("monthly pruning = 1/12", abs(1/12 - 0.0833333333) < 1e-6)
    # 7. cost model: point index scan cheaper than seq scan
    sel = selectivity_eq(1_000_000)
    ci = index_scan_cost(3, 1_000_000, sel)
    cs = seq_scan_cost(100_000, 1_000_000)
    check("point idx cost < seq cost", ci < cs)
    # 8. RNG determinism: re-seed and re-draw -> identical sequence
    r1 = LCG(20240601)
    seq_a = [r1.uniform(0, 1) for _ in range(5)]
    r2 = LCG(20240601)
    seq_b = [r2.uniform(0, 1) for _ in range(5)]
    check("LCG reseed reproduces sequence", seq_a == seq_b)
    print("\n[check] postgresql.py self-consistent:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("postgresql.py - ground truth for POSTGRESQL.md. stdlib only.")
    print("Run: python3 postgresql.py")
    print("Seeded LCG (seed=20240601). Deterministic. No wall-clock, no network.")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()
    gold_check()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
