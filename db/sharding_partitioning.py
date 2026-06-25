"""
sharding_partitioning.py - Reference implementation of table PARTITIONING and
distributed SHARDING: the three strategies (RANGE / LIST / HASH), partition
pruning, constraint exclusion vs declarative partitioning, and Citus/Vitess-
style distributed sharding with cross-shard (gather-merge) query plans.

This is the single source of truth that SHARDING_PARTITIONING.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 sharding_partitioning.py

============================================================================
THE INTUITION (read this first) - the library with the sliding drawer stacks
============================================================================
Imagine one library catalogue drawer that has grown to 4 billion cards. Pulling
any single card is still O(log N) thanks to the index 🔗 (see BTREE.md), but
MAINTAINING the drawer is painful: a single backup locks all 4 billion rows, a
scan for "this month's orders" still walks a huge file, and one hot drawer
cannot be put on a faster machine. So you physically SAW the drawer into
several thinner drawers, each holding a contiguous SLICE of the cards:

  * RANGE  : "drawer A = Jan, drawer B = Feb, drawer C = Mar" - split by an
             ordered key (a date, a timestamp). Best for time-series and
             rolling windows; old drawers can be detached (DROP) in O(1).
  * LIST   : "drawer US, drawer EU, drawer APAC" - split by an enumerated
             value (a region, a tenant). Best for geo / multi-tenant data.
  * HASH   : "hash(card id) mod 4 -> drawer 0..3" - split by a uniform hash.
             Best for even distribution of an unordered id; you CANNOT prune
             by a range on a hash key, but the spread is perfectly even.

A PARTITION is one drawer. PARTITIONING = the act of splitting. The clever bit
is that the SAW MARKS are declared up front, so the planner can PRUNE: a query
"WHERE created_at >= '2024-03-01'" only needs to open drawer C. Pruning is the
entire reason partitioning pays off - without it you'd still scan everything.

SHARDING is partitioning's twin that lives on MULTIPLE MACHINES. Same three
strategies (almost always HASH by a shard/tenant key), but now each drawer sits
on a different NODE. A single-shard query ("WHERE tenant_id = 42") is routed to
the ONE node holding that drawer - no fan-out. A cross-shard query ("SELECT
count(*)") fans out to all nodes and GATHERs the partial results; an ordered
one does a GATHER MERGE (k-way merge of already-sorted per-node streams).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   partition key   : the column the saw cuts along (created_at, region, user_id).
   partition       : one physical piece of the logical table. Real systems store
                     each as its own file/segment. Same schema as the parent.
   RANGE           : split by contiguous intervals of an ORDERED key. [lo, hi).
   LIST            : split by an explicit set of values (one per partition).
   HASH            : split by hash(key) % modulus. Even spread, no order.
   modulus/        : the HASH parameters. Partition p owns the rows where
   remainder         hash(key) % modulus == p. Equal-width => modulus == N.
   partition       : EXCLUDING partitions that provably hold no matching rows,
   pruning           so the executor never opens them. The win of partitioning.
   plan-time       : pruning done when the SQL is planned (constants known).
   execute-time    : pruning done with the bound values of PREPARED-statement
   / runtime         parameters ($1). Only declarative partitioning does this;
                     old constraint exclusion does NOT.
   constraint      : the PRE-PostgreSQL-10 mechanism: child tables INHERIT the
   exclusion         parent, each with a CHECK constraint; the planner's generic
                     constraint solver excludes children whose CHECK contradicts
                     the WHERE. Works, but slow and plan-time only.
   declarative     : CREATE TABLE ... PARTITION BY (PostgreSQL 10+, 2017).
   partitioning      Native pruning, fast, plan + execute time, no inheritance
                     quirks. This is what you should use.
   shard           : a partition that lives on a (possibly different) NODE.
   shard key       : the column hashed to pick the shard/ node. Usually the
                     tenant_id or user_id.
   shard map /     : shard -> node assignment. Citus: each shard owns a hash
   placement         RANGE of the 2^32 hash space; placement is round-robin or
                     by replication factor.
   colocated join  : two tables sharded by the SAME key and joined on it -> the
                     join runs LOCALLY on each node, no data movement.
   gather merge    : merge N already-sorted per-node streams into one sorted
                     result. O(total_rows) work but no resort.

============================================================================
THE LINEAGE (sources)
============================================================================
   Partitioning  (Astrahan et al. 1979, System R) : early "stored tables split
              by ranges" idea.
   PostgreSQL   (PostgreSQL 8.1, 2005) : constraint exclusion + table inheritance
   inheritance    - the old way. Worked, but planner-only and clunky.
   Declarative  (PostgreSQL 10, 2017) : CREATE TABLE ... PARTITION BY. Native
   partitioning    pruning, including runtime pruning (2020, v11/pg12 era).
   Citus        (Marcus et al., Citus Data) : PostgreSQL extension that shards
              tables across nodes by a distribution column; single-shard query
              routing + cross-shard gather/gather-merge. Acquired by MS 2019.
   Vitess       (Sugu Sougoumarane et al., 2010, YouTube/PlanetScale) : MySQL
              sharding layer; Vindex hash sharding, vreplication. Used to run
              YouTube/Slack/Square. Now CNCF project.
   Spanner     (Google 2012) : interleaved/tablet-based sharding + 2PC for
              cross-shard transactions (a different, stronger model).

KEY FORMULAS (all asserted/printed in the sections below):
   HASH bucket p (equal width)   : hash(key) % modulus == remainder, modulus=N
   range prune for [lo,hi)       : keep partitions where part_lo < q_hi AND
                                    part_hi > q_lo     (interval intersection)
   list prune for IN(S)          : keep partitions where part_set & S != empty
   hash prune for key = v        : exactly ONE partition, hash(v) % N   (eq only)
   hash prune for key < v        : NONE pruned - hash is not monotonic -> all
   declarative vs constraint     : both prune at PLAN time for constants; only
                                    declarative prunes at EXECUTE time for $1
   Citus shard for key k         : shard = floor( hash(k) / 2^32 * N )
                                    = hash(k) % N for equal-width shards
   single-shard query            : 1 node touched, 0 fan-out
   cross-shard count(*)          : fan-out N, gather = SUM(per-node counts)
   cross-shard ORDER BY LIMIT    : fan-out N, gather-merge (k-way) + top-K
   colocated join                : 0 data moved - join runs per node

Conventions:
   Dates are ISO 'YYYY-MM-DD' strings, compared lexicographically (correct for
   ISO). The HASH is a 32-bit FNV-1a of str(key); documented and portable so
   the .html recomputes it byte-for-byte. Real PostgreSQL uses a type-specific
   hash, but the partition-assignment RULE (modulus/remainder) is identical.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE STABLE HASH (deterministic; the .html reimplements this verbatim)
# ============================================================================
def stable_hash(x: int) -> int:
    """32-bit FNV-1a of the ASCII bytes of str(x).

    PostgreSQL hash partitioning uses a type-specific hash function; for a
    portable, reproducible tutorial we use FNV-1a so the .html can match the
    .py exactly. Partition assignment follows PostgreSQL's rule: partition p
    holds rows where hash(key) % modulus == remainder (see satisfies_hash_
    partition(modulus, remainder) in the PostgreSQL docs).
    """
    h = 2166136261
    for b in str(x).encode("ascii"):
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h


# ============================================================================
# 2. THE PARTITION MODEL  (the code SHARDING_PARTITIONING.md walks through)
# ============================================================================
class RangePartition:
    """A RANGE partition owning the half-open key interval [lo, hi)."""

    def __init__(self, name: str, lo: str, hi: str):
        self.name, self.lo, self.hi = name, lo, hi

    def holds(self, key) -> bool:
        return self.lo <= key < self.hi

    def could_match_range(self, q_lo, q_hi) -> bool:
        """Interval intersection: does [lo,hi) overlap query [q_lo, q_hi)?
        A None bound means unbounded on that side."""
        if q_hi is not None and self.lo >= q_hi:
            return False
        if q_lo is not None and self.hi <= q_lo:
            return False
        return True

    def spec(self) -> str:
        return f"FOR VALUES FROM ('{self.lo}') TO ('{self.hi}')"


class ListPartition:
    """A LIST partition owning an explicit set of key values."""

    def __init__(self, name: str, values):
        self.name = name
        self.values = list(values)

    def holds(self, key) -> bool:
        return key in self.values

    def could_match_values(self, query_values) -> bool:
        return bool(set(self.values) & set(query_values))

    def spec(self) -> str:
        vs = ", ".join(f"'{v}'" for v in self.values)
        return f"FOR VALUES IN ({vs})"


class HashPartition:
    """A HASH partition owning remainder `r` of `hash(key) % modulus`."""

    def __init__(self, name: str, remainder: int, modulus: int):
        self.name, self.remainder, self.modulus = name, remainder, modulus

    def holds(self, key) -> bool:
        return stable_hash(key) % self.modulus == self.remainder

    def spec(self) -> str:
        return (f"FOR VALUES WITH (MODULUS {self.modulus}, "
                f"REMAINDER {self.remainder})")


class PartitionedTable:
    """A logical table split into partitions by one partition key.

    route(row)      -> the single partition a row must live in (or None/error).
    insert(row)     -> route + append to that partition.
    scan()          -> every row across all partitions.
    """

    def __init__(self, name: str, pkey: str, ptype: str, partitions):
        self.name, self.pkey, self.ptype = name, pkey, ptype
        self.partitions = list(partitions)
        self._rows = {p.name: [] for p in self.partitions}

    def route(self, row: dict) -> HashPartition | RangePartition | ListPartition:
        key = row[self.pkey]
        for p in self.partitions:
            if p.holds(key):
                return p
        raise ValueError(
            f"no partition for {self.pkey}={key!r} (need a DEFAULT/catch-all)")

    def insert(self, row: dict) -> str:
        p = self.route(row)
        self._rows[p.name].append(row)
        return p.name

    def rows_in(self, part_name: str) -> list:
        return self._rows[part_name]

    def scan(self) -> list:
        out = []
        for p in self.partitions:
            out.extend(self._rows[p.name])
        return out

    def total_rows(self) -> int:
        return sum(len(v) for v in self._rows.values())


# ----------------------------------------------------------------------------
# PRUNING - the planner's job: which partitions can the executor skip?
# ----------------------------------------------------------------------------
def prune_range(partitions, q_lo=None, q_hi=None):
    """Keep RANGE partitions whose [lo,hi) intersects [q_lo, q_hi)."""
    return [p for p in partitions
            if p.could_match_range(q_lo, q_hi)]


def prune_list(partitions, query_values):
    """Keep LIST partitions whose set overlaps the queried values."""
    return [p for p in partitions
            if p.could_match_values(query_values)]


def prune_hash_eq(partitions, value):
    """Equality on a hash key -> exactly ONE partition (hash is decisive)."""
    modulus = partitions[0].modulus
    target = stable_hash(value) % modulus
    return [p for p in partitions if p.remainder == target]


def prune_hash_range(partitions):
    """A range/inequality on a hash key -> NO pruning possible (not monotonic)."""
    return list(partitions)   # must scan them all


# ============================================================================
# 3. THE TWO PLANNERS: declarative pruning vs old constraint exclusion
# ============================================================================
def declarative_plan(table, predicate_kind, *args, runtime_value=None):
    """Modern declarative partitioning: prune at PLAN time when the predicate
    constant is known, AND at EXECUTE time for prepared-statement params ($1).

    predicate_kind: 'range' | 'list' | 'hash_eq' | 'hash_range'
    runtime_value : if the predicate is a $1 param, the bound value (exec time).
    Returns the list of partitions the executor will actually scan.
    """
    args = args if runtime_value is None else (runtime_value,)
    if predicate_kind == "range":
        return prune_range(table.partitions, *args)
    if predicate_kind == "list":
        return prune_list(table.partitions, args[0])
    if predicate_kind == "hash_eq":
        return prune_hash_eq(table.partitions, args[0])
    if predicate_kind == "hash_range":
        return prune_hash_range(table.partitions)
    raise ValueError(predicate_kind)


def constraint_exclusion_plan(table, predicate_kind, *args, is_prepared_param):
    """OLD mechanism (PG <= 9.6 inheritance style): the planner's generic
    constraint solver runs ONLY at plan time, and ONLY against KNOWN constants.
    For a PREPARED param ($1) the value is unknown at plan time, so it CANNOT
    exclude any child -> it scans ALL of them. This is the historical pain that
    motivated declarative partitioning (PG 10, 2017).
    """
    if is_prepared_param:
        return list(table.partitions)        # cannot evaluate $1 -> scan all
    # constant predicate: the solver can exclude children (same result as
    # declarative, just slower and only in this branch)
    if predicate_kind == "range":
        return prune_range(table.partitions, *args)
    if predicate_kind == "list":
        return prune_list(table.partitions, args[0])
    if predicate_kind == "hash_eq":
        return prune_hash_eq(table.partitions, args[0])
    if predicate_kind == "hash_range":
        return prune_hash_range(table.partitions)
    raise ValueError(predicate_kind)


# ============================================================================
# 4. DISTRIBUTED SHARDING  (Citus / Vitess style)
# ============================================================================
HASH_SPACE = 1 << 32   # Citus shards divide the full 32-bit hash space


class Shard:
    """A hash-range shard owning [lo, hi) of the 2^32 hash space."""

    def __init__(self, sid: int, lo: int, hi: int):
        self.sid, self.lo, self.hi = sid, lo, hi

    def owns_hash(self, h: int) -> bool:
        return self.lo <= h < self.hi

    def __repr__(self):
        return (f"S{self.sid}=[{self.lo:,}..{self.hi:,})  "
                f"({self.hi - self.lo:,} hash values)")


class ShardMap:
    """N equal-width hash shards, round-robin placed across `nodes` worker nodes.

    shard_for(key) -> the shard owning hash(key).
    node_for(key)  -> the node hosting that shard.
    """

    def __init__(self, num_shards: int, num_nodes: int):
        assert num_shards % num_nodes == 0, "even shard-per-node for clarity"
        self.num_shards = num_shards
        self.num_nodes = num_nodes
        width = HASH_SPACE // num_shards
        self.shards = [Shard(s, s * width, (s + 1) * width)
                       for s in range(num_shards)]
        # round-robin placement: shard s -> node (s % num_nodes)
        self.node_of = {s.sid: s.sid % num_nodes for s in self.shards}

    def shard_for_key(self, key) -> Shard:
        h = stable_hash(key)
        width = HASH_SPACE // self.num_shards
        return self.shards[h // width]

    def node_for_key(self, key) -> int:
        return self.node_of[self.shard_for_key(key).sid]

    def shards_on_node(self, node: int):
        return [s for s in self.shards if self.node_of[s.sid] == node]


def gather_merge_desc(streams):
    """k-way merge of DESCENDING sorted streams. Mirrors Citus Gather Merge.

    Uses a min-heap over negated keys so the largest value pops first. Each
    node's stream is ALREADY sorted (local ORDER BY ran there), so the merge is
    O(total) with NO resort - that is the whole point of Gather Merge.
    """
    import heapq
    h = []
    for ni, st in enumerate(streams):
        if st:
            heapq.heappush(h, (-st[0], ni, 0))
    out = []
    while h:
        neg, ni, i = heapq.heappop(h)
        out.append(-neg)
        if i + 1 < len(streams[ni]):
            heapq.heappush(h, (-streams[ni][i + 1], ni, i + 1))
    return out


# ============================================================================
# 5. PRETTY PRINTERS
# ============================================================================
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_row(cols, widths):
    return "| " + " | ".join(f"{str(c):<{w}}" for c, w in zip(cols, widths)) + " |"


def print_table(header, rows, widths):
    sep = "|-" + "-|-".join("-" * w for w in widths) + "- |"
    print(fmt_row(header, widths))
    print(sep)
    for r in rows:
        print(fmt_row(r, widths))


# ============================================================================
# 6. THE TINY CONCRETE SCHEMA  (deterministic; the .html mirrors it)
# ============================================================================
ORDERS_RANGE_PARTS = [
    RangePartition("p2024_01", "2024-01-01", "2024-02-01"),
    RangePartition("p2024_02", "2024-02-01", "2024-03-01"),
    RangePartition("p2024_03", "2024-03-01", "2024-04-01"),
]

USERS_LIST_PARTS = [
    ListPartition("p_us", ["US"]),
    ListPartition("p_eu", ["EU"]),
    ListPartition("p_apac", ["APAC"]),
]

EVENTS_HASH_PARTS = [
    HashPartition("ph0", 0, 4),
    HashPartition("ph1", 1, 4),
    HashPartition("ph2", 2, 4),
    HashPartition("ph3", 3, 4),
]

# deterministic seed rows
ORDERS_ROWS = [
    {"id": 1, "created_at": "2024-01-05", "amount": 100},
    {"id": 2, "created_at": "2024-01-28", "amount": 200},
    {"id": 3, "created_at": "2024-02-03", "amount": 150},
    {"id": 4, "created_at": "2024-02-25", "amount": 300},
    {"id": 5, "created_at": "2024-03-02", "amount": 250},
    {"id": 6, "created_at": "2024-03-30", "amount": 400},
]

USERS_ROWS = [
    {"user_id": 10, "region": "US", "name": "Ada"},
    {"user_id": 11, "region": "EU", "name": "Alan"},
    {"user_id": 12, "region": "APAC", "name": "Grace"},
    {"user_id": 13, "region": "US", "name": "Linus"},
    {"user_id": 14, "region": "EU", "name": "Dijkstra"},
]

EVENT_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 42, 100, 1000, 9999]


# ----------------------------------------------------------------------------
# SECTION A: RANGE partitioning
# ----------------------------------------------------------------------------
def section_a():
    banner("SECTION A: RANGE partitioning - orders split by created_at")
    tbl = PartitionedTable("orders", "created_at", "RANGE", ORDERS_RANGE_PARTS)
    print("CREATE TABLE orders (id int, created_at date, amount int)")
    print("  PARTITION BY RANGE (created_at);")
    for p in tbl.partitions:
        print(f"  CREATE TABLE {p.name} PARTITION OF orders {p.spec()};")
    print(f"\nINSERTing {len(ORDERS_ROWS)} deterministic rows; routing each:\n")
    widths = [4, 12, 8, 12]
    print_table(["id", "created_at", "amount", "-> partition"],
                [[r["id"], r["created_at"], r["amount"], tbl.insert(r)]
                 for r in ORDERS_ROWS], widths)
    print("\nPer-partition row counts:")
    for p in tbl.partitions:
        ids = [r["id"] for r in tbl.rows_in(p.name)]
        print(f"  {p.name}  ({p.spec().split('VALUES')[1].strip()}): "
              f"{len(ids)} rows -> ids {ids}")
    print(f"  TOTAL: {tbl.total_rows()} rows across {len(tbl.partitions)} partitions")
    print("\nWHY RANGE: time-series and rolling windows. Dropping a whole month")
    print("is DROP TABLE p2024_01 (O(1)), not a DELETE that vacuums later. A")
    print("indexed lookup 🔗 (BTREE.md) is still O(log n) WITHIN a partition, but")
    print("n is now ~1/3 of the whole, so caches stay hot.")


# ----------------------------------------------------------------------------
# SECTION B: LIST partitioning
# ----------------------------------------------------------------------------
def section_b():
    banner("SECTION B: LIST partitioning - users split by region")
    tbl = PartitionedTable("users", "region", "LIST", USERS_LIST_PARTS)
    print("CREATE TABLE users (user_id int, region text, name text)")
    print("  PARTITION BY LIST (region);")
    for p in tbl.partitions:
        print(f"  CREATE TABLE {p.name} PARTITION OF users {p.spec()};")
    print(f"\nINSERTing {len(USERS_ROWS)} rows; routing each:\n")
    widths = [8, 8, 10, 12]
    print_table(["user_id", "region", "name", "-> partition"],
                [[r["user_id"], r["region"], r["name"], tbl.insert(r)]
                 for r in USERS_ROWS], widths)
    print("\nPer-partition counts:")
    for p in tbl.partitions:
        ids = [r["user_id"] for r in tbl.rows_in(p.name)]
        print(f"  {p.name}  ({p.spec().split('VALUES')[1].strip()}): "
              f"{len(ids)} users -> {ids}")
    print("\nWHY LIST: multi-tenant / geo. Each region's data is physically")
    print("isolated - handy for data-residency ('EU data stays in EU'). A row")
    print("whose region matches NO list value would ERROR without a DEFAULT")
    print("partition (we omit it here to keep routing explicit).")


# ----------------------------------------------------------------------------
# SECTION C: HASH partitioning
# ----------------------------------------------------------------------------
def section_c():
    banner("SECTION C: HASH partitioning - events split by hash(user_id) % 4")
    tbl = PartitionedTable("events", "user_id", "HASH", EVENTS_HASH_PARTS)
    print("CREATE TABLE events (user_id int, payload text)")
    print("  PARTITION BY HASH (user_id);")
    for p in tbl.partitions:
        print(f"  CREATE TABLE {p.name} PARTITION OF events {p.spec()};")
    print("\nAssignment rule:  partition = hash(user_id) % modulus == remainder")
    print("hash = FNV-1a(str(user_id)) & 0xFFFFFFFF   (modulus = 4)\n")
    widths = [8, 14, 10, 14]
    print_table(["user_id", "hash(user_id)", "% 4", "-> partition"],
                [[k, f"{stable_hash(k):010d}", stable_hash(k) % 4, tbl.insert({"user_id": k})]
                 for k in EVENT_IDS], widths)
    print("\nDistribution (the whole point of HASH - even spread):")
    counts = {p.name: len(tbl.rows_in(p.name)) for p in tbl.partitions}
    mx = max(counts.values()) if counts else 1
    for p in tbl.partitions:
        c = counts[p.name]
        bar = "#" * round(c / mx * 28)
        print(f"  {p.name}  rem={p.remainder}: {c:>2} rows  {bar}")
    print(f"\nSkew check: max={mx}, min={min(counts.values())}, "
          f"max/min ratio = {mx / min(counts.values()):.2f}")
    print("\nWHY HASH: an unordered id (a uuid, a surrogate key) spreads evenly")
    print("across N partitions with no hot spot. The COST: hash is not monotonic,")
    print("so a range predicate ('user_id < 100') CANNOT be pruned (Section D).")
    print("An EQUALITY predicate ('user_id = 42') CAN - we know its hash.")


# ----------------------------------------------------------------------------
# SECTION D: PARTITION PRUNING
# ----------------------------------------------------------------------------
def section_d():
    banner("SECTION D: PARTITION PRUNING - skip partitions the WHERE rules out")
    range_tbl = PartitionedTable("orders", "created_at", "RANGE", ORDERS_RANGE_PARTS)
    list_tbl = PartitionedTable("users", "region", "LIST", USERS_LIST_PARTS)
    hash_tbl = PartitionedTable("events", "user_id", "HASH", EVENTS_HASH_PARTS)

    print("Pruning asks: 'given the WHERE, which partitions COULD hold matches?'")
    print("The executor then opens only those. Everything else stays un-touched.\n")

    # 1) RANGE + range predicate
    print("1) RANGE table, WHERE created_at >= '2024-03-01'")
    kept = prune_range(range_tbl.partitions, q_lo="2024-03-01", q_hi=None)
    show_prune(range_tbl.partitions, kept,
               lambda p: p.could_match_range("2024-03-01", None))

    # 2) LIST + equality
    print("\n2) LIST table, WHERE region = 'EU'")
    kept = prune_list(list_tbl.partitions, ["EU"])
    show_prune(list_tbl.partitions, kept, lambda p: "EU" in p.values)

    # 3) HASH + equality -> decisive
    print("\n3) HASH table, WHERE user_id = 42   (equality is decisive)")
    h42 = stable_hash(42)
    kept = prune_hash_eq(hash_tbl.partitions, 42)
    show_prune(hash_tbl.partitions, kept,
               lambda p: p.remainder == h42 % 4,
               extra=f"hash(42)={h42}, % 4 = {h42 % 4}")

    # 4) HASH + range -> NO pruning
    print("\n4) HASH table, WHERE user_id < 100   (inequality on a HASH key)")
    kept = prune_hash_range(hash_tbl.partitions)
    show_prune(hash_tbl.partitions, kept, lambda p: True,
               extra="hash is NOT monotonic -> cannot prune -> scan ALL")

    print("\nRULE OF THUMB: pruning works when the partition key's ORDER/SET is")
    print("queryable. RANGE prunes ranges; LIST prunes IN/eq; HASH prunes ONLY")
    print("equality. Plan a range scan on a hash key and you fan out everywhere.")


def show_prune(all_parts, kept, why, extra=""):
    def names(ps):
        return ", ".join(p.name for p in ps) if ps else "(none)"
    print(f"   partitions scanned: {names(kept)}   "
          f"[{len(kept)}/{len(all_parts)}]")
    if extra:
        print(f"   {extra}")
    print(f"   {'  '.join(('KEEP ' if why(p) else 'SKIP') + ' ' + p.name for p in all_parts)}")


# ----------------------------------------------------------------------------
# SECTION E: CONSTRAINT EXCLUSION vs DECLARATIVE
# ----------------------------------------------------------------------------
def section_e():
    banner("SECTION E: constraint exclusion (old) vs declarative pruning (new)")
    tbl = PartitionedTable("orders", "created_at", "RANGE", ORDERS_RANGE_PARTS)

    print("Two mechanisms, same GOAL (skip partitions). Different ENGINES:\n")
    print("  OLD (PG <= 9.6): child tables INHERIT parent, each with a CHECK:")
    print("    CREATE TABLE orders_p2024_01 (CHECK (created_at >= '2024-01-01'")
    print("                                 AND created_at <  '2024-02-01'))")
    print("      INHERITS (orders);")
    print("    planner's GENERIC constraint solver excludes children whose CHECK")
    print("    contradicts WHERE. constraint_exclusion=partition must be ON.\n")
    print("  NEW (PG >= 10, 2017): CREATE TABLE orders PARTITION BY RANGE(...);")
    print("    native partition DESCRIPTORS drive a dedicated pruner. Fast, and")
    print("    runs at PLAN time AND EXECUTE time (runtime pruning).\n")

    q = "WHERE created_at >= '2024-03-01'"
    print(f"QUERY (constant predicate): {q}\n")
    dec_const = declarative_plan(tbl, "range", "2024-03-01", None)
    ce_const = constraint_exclusion_plan(tbl, "range", "2024-03-01",
                                         is_prepared_param=False)
    _compare_plans("constant WHERE", tbl, dec_const, ce_const)

    print("\nQUERY (PREPARED param): PREPARE q AS SELECT ... WHERE created_at >= $1;")
    print("EXECUTE q('2024-03-01');   -- $1 known only at EXECUTE time\n")
    dec_rt = declarative_plan(tbl, "range", None, runtime_value="2024-03-01")
    ce_rt = constraint_exclusion_plan(tbl, "range", "2024-03-01",
                                      is_prepared_param=True)
    _compare_plans("prepared $1 (runtime)", tbl, dec_rt, ce_rt)

    print("\nTHE DIFFERENCE THAT MATTERS: with a prepared statement, the OLD")
    print("constraint-exclusion planner sees $1 as UNKNOWN at plan time and scans")
    print("ALL children every execution. Declarative pruning re-prunes at execute")
    print("time with the bound value -> still 1 partition. On a 100-partition")
    print("time-series table that is a 100x speedup for every cached plan.")


def _compare_plans(label, tbl, dec, ce):
    def names(ps):
        return ", ".join(p.name for p in ps)
    print(f"  [{label}]")
    print(f"    declarative  -> scan {names(dec)}   [{len(dec)}/{len(tbl.partitions)}]")
    print(f"    constraint   -> scan {names(ce)}   [{len(ce)}/{len(tbl.partitions)}]")
    same = len(dec) == len(ce) and {p.name for p in dec} == {p.name for p in ce}
    tag = "same set" if same else "DIFFERENT (declarative prunes, old does not)"
    print(f"    -> {tag}")


# ----------------------------------------------------------------------------
# SECTION F: DISTRIBUTED SHARDING (Citus / Vitess)
# ----------------------------------------------------------------------------
def section_f():
    banner("SECTION F: DISTRIBUTED SHARDING - Citus / Vitess across nodes")
    sm = ShardMap(num_shards=4, num_nodes=2)
    print("SHARDING = partitioning, but each partition lives on a NODE. Same HASH")
    print("strategy (almost always), now with single-shard routing + gather.\n")
    print(f"Cluster: {sm.num_shards} shards, {sm.num_nodes} worker nodes, "
          f"2^32 hash space split into equal ranges, round-robin placement.\n")
    print("Shard layout:")
    for s in sm.shards:
        print(f"  {s}  ->  node{sm.node_of[s.sid]}")
    print("\nNode placement:")
    for n in range(sm.num_nodes):
        ids = [s.sid for s in sm.shards_on_node(n)]
        print(f"  node{n}: shards {ids}")

    # 1) SINGLE-SHARD QUERY
    print("\n--- (1) SINGLE-SHARD QUERY (shard key in WHERE) ---")
    print("SELECT * FROM events WHERE user_id = 42;")
    sh = sm.shard_for_key(42)
    node = sm.node_of[sh.sid]
    h42 = stable_hash(42)
    print(f"  route: hash(42)={h42}  ->  {sh}  ->  node{node}")
    print("  plan:  Custom Scan (Citus Router Select)")
    print(f"           -> Seq Scan on events_{sh.sid}   (node{node} only)")
    print("  fan-out: 1 node touched. ZERO cross-node traffic. This is the")
    print("           95% case that makes sharded OLTP fast.")

    # 2) CROSS-SHARD count(*) -> gather (sum)
    print("\n--- (2) CROSS-SHARD aggregate  SELECT count(*) FROM events; ---")
    print("  plan:  Hash Aggregate (distributed)")
    per_node = {n: 0 for n in range(sm.num_nodes)}
    for s in sm.shards:
        per_node[sm.node_of[s.sid]] += 1   # pretend 1 row per shard for the demo
    for n in range(sm.num_nodes):
        print(f"           -> Seq Scan on node{n}  ->  partial count = {per_node[n]}")
    total = sum(per_node.values())
    print(f"         Gather (sum)  ->  {total}")
    print(f"  fan-out: ALL {sm.num_nodes} nodes. The coordinator SUMS partial")
    print("           counts. Composable: avg = sum / count, both gathered.")

    # 3) CROSS-SHARD ORDER BY LIMIT -> gather merge
    print("\n--- (3) CROSS-SHARD ORDER BY ... LIMIT  (GATHER MERGE) ---")
    print("SELECT * FROM events ORDER BY amount DESC LIMIT 3;")
    streams = [
        [100, 80, 50],    # node0 already sorted DESC
        [200, 90, 40],    # node1 already sorted DESC
    ]
    print("  Each node runs its local ORDER BY, emitting a SORTED stream:")
    for n, st in enumerate(streams):
        print(f"           node{n} stream (sorted DESC): {st}")
    merged = gather_merge_desc(streams)
    print(f"  Gather Merge (k-way merge of sorted streams) -> {merged}")
    print(f"  Top-3: {merged[:3]}")
    print("  COST: O(total) merge, NO resort. Each node kept its index 🔗")

    # 4) COLOCATED JOIN vs BROADCAST JOIN
    print("\n--- (4) JOIN across shards ---")
    print("  events JOIN users ON user_id  (both sharded by user_id): CO-LOCATED")
    print("           -> join runs LOCALLY on each node. 0 rows moved.")
    print("  events JOIN countries ON region  (countries NOT sharded by region):")
    print("           -> BROADCAST countries (send full copy to every node), then")
    print("              local hash join. Cost: 1x copy of the small table.")

    print("\nSHARDING vs PARTITIONING: same slicing math, different PHYSICS. A")
    print("partition is a file on ONE box; a shard is a file on a NODE. Once you")
    print("cross the network, query routing, gather merges, and co-located joins")
    print("become the dominant cost - and the design lever (pick the shard key so")
    print("most queries stay single-shard).")


# ----------------------------------------------------------------------------
# GOLD CHECK - the canonical routing invariant the .html replays
# ----------------------------------------------------------------------------
def gold_check():
    banner("GOLD CHECK - INSERT then QUERY must route to the SAME partition")
    print("Invariant: a row INSERTed via partition routing must be findable by a")
    print("query whose pruning keeps exactly that one partition.\n")

    # --- range gold ---
    range_tbl = PartitionedTable("orders", "created_at", "RANGE", ORDERS_RANGE_PARTS)
    gold_row = {"id": 99, "created_at": "2024-03-15", "amount": 777}
    insert_part = range_tbl.insert(gold_row)
    q_kept = prune_range(range_tbl.partitions, q_lo=gold_row["created_at"], q_hi=None)
    q_names = {p.name for p in q_kept}
    ok_range = q_names == {insert_part}
    print(f"[RANGE]   INSERT id=99 created_at=2024-03-15 -> {insert_part}")
    print(f"         SELECT ... WHERE created_at >= '2024-03-15' "
          f"prunes to {sorted(q_names)}")
    print(f"         [check] routing covers the inserted partition? "
          f"{'OK' if ok_range else 'FAIL'}\n")

    # --- hash gold (the .html pins this exact number) ---
    hash_tbl = PartitionedTable("events", "user_id", "HASH", EVENTS_HASH_PARTS)
    gold_key = 42
    insert_part = hash_tbl.insert({"user_id": gold_key})
    h = stable_hash(gold_key)
    eq_kept = prune_hash_eq(hash_tbl.partitions, gold_key)
    eq_names = {p.name for p in eq_kept}
    ok_hash = eq_names == {insert_part} and len(eq_kept) == 1
    print(f"[HASH]    INSERT user_id={gold_key} -> {insert_part}")
    print(f"         hash({gold_key}) = {h} ; {h} % 4 = {h % 4} "
          f"(remainder of {insert_part})")
    print(f"         SELECT ... WHERE user_id = {gold_key} prunes to "
          f"{sorted(eq_names)}")
    print(f"         [check] exactly one partition AND it matches the INSERT? "
          f"{'OK' if ok_hash else 'FAIL'}\n")

    # GOLD scalar pinned for the .html:  hash(42) and hash(42) % 4
    print("GOLD scalar (pinned for sharding_partitioning.html):")
    print(f"   stable_hash(42) = {h}")
    print(f"   stable_hash(42) % 4 = {h % 4}")
    print(f"   partition = ph{h % 4}")

    assert ok_range and ok_hash, "gold check failed"
    # self-consistency: routing via holds() == routing via hash%modulus
    assert HashPartition(f"ph{h % 4}", h % 4, 4).holds(gold_key)
    print("\n[check] GOLD overall: OK   "
          "(insert routing == query pruning, all types)")


# ============================================================================
# main
# ============================================================================
def main():
    print("sharding_partitioning.py - reference impl. "
          "All numbers below feed SHARDING_PARTITIONING.md.")
    print("Python stdlib only; hash = FNV-1a 32-bit (portable to JS).")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
