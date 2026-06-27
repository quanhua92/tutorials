#!/usr/bin/env python3
"""database_schema_design.py -- relational schema design, ground-truth implementation.

Pure Python stdlib (no third-party deps). Every section prints a ``===`` banner,
shows a before/after schema, and ends with ``[check] OK``. The GOLD CHECK section
produces a value recomputed by ``database_schema_design.html`` in JavaScript for
cross-language parity.

Topics
    01. ER modeling         -- extract entities + relationships (the design framework)
    02. 1NF                  -- atomic values; no repeating groups / comma lists
    03. 2NF                  -- no partial-key dependencies (composite keys only)
    04. 3NF                  -- no transitive dependencies (product_name <- product_id)
    05. BCNF                 -- every determinant is a candidate key
    06. Denormalization      -- deliberate redundancy for read latency (price snapshot,
                                materialized view) + the read/write tradeoff
    07. Indexing strategy    -- B-tree, composite leftmost-prefix, covering (INCLUDE),
                                partial index, the ~5% selectivity rule

The GOLD CHECK computes ``btree_depth(rows=1e9, fanout=200)`` -- the B-tree height
for a one-billion-row table; ``database_schema_design.html`` recomputes it in JS.

Companion files: DATABASE_SCHEMA_DESIGN.md, database_schema_design.html,
database_schema_design_output.txt
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

# =========================================================================== #
#  Helpers
# =========================================================================== #
def banner(title: str) -> None:
    """Print a ``===`` banner, as required by HOW_TO_RESEARCH.md."""
    line = "=" * 72
    print(f"\n{line}\n=== {title}\n{line}")


def check(label: str) -> None:
    print(f"  [check] OK   {label}")


def print_table(title: str, cols: Sequence[str],
                rows: Sequence[Dict[str, Any]]) -> None:
    """Render a small aligned table to stdout."""
    print(f"  {title}")
    if not rows:
        print("    (no rows)")
        return
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    gap = "  "
    print("    " + gap.join(c.ljust(widths[c]) for c in cols))
    print("    " + gap.join("-" * widths[c] for c in cols))
    for r in rows:
        print("    " + gap.join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


# =========================================================================== #
#  01. ER MODELING -- entities + relationships (the design framework)
# =========================================================================== #
@dataclass(frozen=True)
class Column:
    name: str
    kind: str          # "PK", "FK", "data"
    notes: str = ""


@dataclass(frozen=True)
class Entity:
    name: str
    columns: List[Column]


@dataclass(frozen=True)
class Relationship:
    frm: str
    to: str
    cardinality: str    # "1:N", "N:1", "M:N", "1:1"
    fk: str             # the foreign-key column / junction table
    on_delete: str      # CASCADE / RESTRICT / SET NULL
    note: str


ENTITIES: List[Entity] = [
    Entity("users", [
        Column("id", "PK", "uuid surrogate"),
        Column("email", "data", "UNIQUE natural key"),
    ]),
    Entity("orders", [
        Column("id", "PK", "uuid surrogate"),
        Column("user_id", "FK", "REFERENCES users(id) ON DELETE RESTRICT"),
        Column("status", "data", "CHECK IN (pending,paid,shipped,cancelled)"),
    ]),
    Entity("order_items", [
        Column("id", "PK", "bigserial"),
        Column("order_id", "FK", "REFERENCES orders(id) ON DELETE CASCADE"),
        Column("product_id", "FK", "REFERENCES products(id) ON DELETE RESTRICT"),
        Column("quantity", "data", "CHECK > 0"),
    ]),
    Entity("products", [
        Column("id", "PK", "uuid surrogate"),
        Column("name", "data", ""),
        Column("price_cents", "data", "NUMERIC; never FLOAT for money"),
    ]),
]

RELATIONSHIPS: List[Relationship] = [
    Relationship("users", "orders", "1:N", "orders.user_id",
                 "RESTRICT", "never auto-delete a user because of an order"),
    Relationship("orders", "order_items", "1:N", "order_items.order_id",
                 "CASCADE", "items are OWNED by the order; delete together"),
    Relationship("products", "order_items", "1:N", "order_items.product_id",
                 "RESTRICT", "never lose history of a sold product"),
    Relationship("orders", "payments", "1:1", "payments.order_id UNIQUE",
                 "RESTRICT", "one payment per order"),
    Relationship("orders", "order_items", "M:N", "order_items (junction)",
                 "CASCADE", "order_items resolves orders <-> products M:N"),
]


def section_er_modeling() -> None:
    banner("01. ER MODELING -- entities and relationships")
    print("  Step 1 of the framework: circle the NOUNS in the requirements ->")
    print("  each strong noun becomes a table; each relationship becomes a FK or junction.")
    print("  ENTITIES:")
    for e in ENTITIES:
        cols = ", ".join(f"{c.name}:{c.kind}" for c in e.columns)
        print(f"    {e.name:<14} ({cols})")
    print("  RELATIONSHIPS (cardinality, foreign key, ON DELETE):")
    for r in RELATIONSHIPS:
        print(f"    {r.frm:<9} {r.cardinality:<4} {r.to:<12} "
              f"fk={r.fk:<28} ON DELETE {r.on_delete:<8} {r.note}")
    check("1:N -> FK on N side; M:N -> junction table; 1:1 -> FK + UNIQUE")


# =========================================================================== #
#  02. 1NF -- atomic values, no repeating groups
# =========================================================================== #
def section_1nf() -> None:
    banner("02. 1NF -- atomic values (no repeating groups / comma lists)")
    print('  RULE: every cell holds ONE atomic value. No "Widget,Gizmo" lists.')
    unf = [
        {"order_id": 1001, "customer": "Acme", "items": "Widget,Gizmo", "total": 70},
        {"order_id": 1002, "customer": "Globex", "items": "Widget", "total": 25},
        {"order_id": 1003, "customer": "Initech", "items": "Gizmo,Doohickey", "total": 45},
    ]
    print_table("BEFORE -- UNNORMALIZED (items is a multi-valued cell):",
                ["order_id", "customer", "items", "total"], unf)
    print('  VIOLATION: the "items" column holds several products in one cell ->')
    print('  you cannot query "who bought a Widget?" or index products.')

    nf1 = [
        {"order_id": 1001, "customer": "Acme", "item": "Widget", "total": 70},
        {"order_id": 1001, "customer": "Acme", "item": "Gizmo", "total": 70},
        {"order_id": 1002, "customer": "Globex", "item": "Widget", "total": 25},
        {"order_id": 1003, "customer": "Initech", "item": "Gizmo", "total": 45},
        {"order_id": 1003, "customer": "Initech", "item": "Doohickey", "total": 45},
    ]
    print_table("AFTER 1NF -- one row per (order, item); composite PK = (order_id, item):",
                ["order_id", "customer", "item", "total"], nf1)
    check("1NF: split the comma list into one atomic row per item")


# =========================================================================== #
#  03. 2NF -- no partial-key dependencies (composite keys only)
# =========================================================================== #
def section_2nf() -> None:
    banner("03. 2NF -- no partial-key dependencies (needs a COMPOSITE key)")
    print("  RULE: every non-key column depends on the WHOLE primary key, not a subset.")
    before = [
        {"student": "s1", "course": "DB", "course_loc": "Room A", "fee": 500},
        {"student": "s1", "course": "OS", "course_loc": "Room B", "fee": 600},
        {"student": "s2", "course": "DB", "course_loc": "Room A", "fee": 500},
    ]
    print_table("BEFORE -- 1NF table, PK = (student, course):",
                ["student", "course", "course_loc", "fee"], before)
    print("  VIOLATION: course_loc and fee depend on COURSE alone (part of the key),")
    print("  so 'Room A' / 500 is duplicated for every student taking DB.")
    print("  Update anomaly: move DB to Room C -> touch every enrolled row.")

    courses = [
        {"course": "DB", "course_loc": "Room A", "fee": 500},
        {"course": "OS", "course_loc": "Room B", "fee": 600},
    ]
    enrollments = [
        {"student": "s1", "course": "DB"},
        {"student": "s1", "course": "OS"},
        {"student": "s2", "course": "DB"},
    ]
    print_table("AFTER 2NF -- courses(course PK) holds course_loc + fee:",
                ["course", "course_loc", "fee"], courses)
    print_table("AFTER 2NF -- enrollments(student FK, course FK, PK(student, course)):",
                ["student", "course"], enrollments)
    check("2NF: move columns that depend on part of a composite key to their own table")


# =========================================================================== #
#  04. 3NF -- no transitive dependencies
# =========================================================================== #
def section_3nf() -> None:
    banner("04. 3NF -- no transitive dependencies (the classic product example)")
    print("  RULE: no non-key column depends on ANOTHER non-key column.")
    before = [
        {"order_id": "o1", "product_id": "p1", "product_name": "Widget", "price": 25, "qty": 2},
        {"order_id": "o1", "product_id": "p2", "product_name": "Gizmo", "price": 20, "qty": 1},
        {"order_id": "o2", "product_id": "p1", "product_name": "Widget", "price": 25, "qty": 1},
    ]
    print_table("BEFORE -- order_items, PK = (order_id, product_id):",
                ["order_id", "product_id", "product_name", "price", "qty"], before)
    print("  VIOLATION: product_name and price depend on PRODUCT_ID (a non-key),")
    print("  not on order_id. Rename 'Widget' -> you must edit every line that sold it.")
    print("  Transitive chain: (order_id,product_id) -> product_id -> product_name.")

    products = [
        {"product_id": "p1", "name": "Widget", "price": 25},
        {"product_id": "p2", "name": "Gizmo", "price": 20},
    ]
    order_items = [
        {"order_id": "o1", "product_id": "p1", "qty": 2},
        {"order_id": "o1", "product_id": "p2", "qty": 1},
        {"order_id": "o2", "product_id": "p1", "qty": 1},
    ]
    print_table("AFTER 3NF -- products(product_id PK, name, price):",
                ["product_id", "name", "price"], products)
    print_table("AFTER 3NF -- order_items(order_id FK, product_id FK, qty):",
                ["order_id", "product_id", "qty"], order_items)
    check("3NF: extract products; order_items references product_id only")


# =========================================================================== #
#  05. BCNF -- every determinant is a candidate key
# =========================================================================== #
@dataclass(frozen=True)
class FD:
    lhs: tuple
    rhs: str


def section_bcnf() -> None:
    banner("05. BCNF -- every determinant is a candidate key")
    print("  RULE: for every non-trivial FD X -> Y, X must be a SUPERKEY.")
    print("  BCNF is stricter than 3NF; the textbook case is fine under 3NF but breaks BCNF.")
    before = [
        {"student": "s1", "course": "DB", "professor": "Dijkstra"},
        {"student": "s2", "course": "DB", "professor": "Dijkstra"},
        {"student": "s1", "course": "OS", "professor": "Tanenbaum"},
        {"student": "s3", "course": "OS", "professor": "Tanenbaum"},
    ]
    print_table("BEFORE -- advising(student, course, professor):",
                ["student", "course", "professor"], before)
    fds = [FD(("student", "course"), "professor"), FD(("professor",), "course")]
    print("  FUNCTIONAL DEPENDENCIES:")
    for fd in fds:
        print(f"    {','.join(fd.lhs):<18} -> {fd.rhs}")
    print("  KEY = (student, course). But professor -> course, and 'professor' is NOT a")
    print("  superkey (one professor teaches many students). That violates BCNF.")
    print("  (It does NOT violate 3NF: 'course' is prime -- part of a candidate key.)")

    takes = [
        {"student": "s1", "professor": "Dijkstra"},
        {"student": "s2", "professor": "Dijkstra"},
        {"student": "s1", "professor": "Tanenbaum"},
        {"student": "s3", "professor": "Tanenbaum"},
    ]
    teaches = [
        {"professor": "Dijkstra", "course": "DB"},
        {"professor": "Tanenbaum", "course": "OS"},
    ]
    print_table("AFTER BCNF -- takes(student, professor) PK(student, professor):",
                ["student", "professor"], takes)
    print_table("           teaches(professor PK, course):",
                ["professor", "course"], teaches)
    check("BCNF: split so the lone determinant (professor) becomes its own key")


# =========================================================================== #
#  06. DENORMALIZATION -- deliberate redundancy for read latency
# =========================================================================== #
def section_denormalization() -> None:
    banner("06. DENORMALIZATION -- deliberate redundancy (read vs write tradeoff)")
    print("  Start from 3NF. Then identify the 1-3 HOT read paths where a join costs too")
    print("  much and denormalize THOSE explicitly, with a documented invariant.")
    print("  Example 1 -- price snapshot: product.price changes over time, but a past")
    print("  order's total must NOT recompute. So order_items keeps unit_price_at_order.")
    print("    This is NOT a 3NF violation: the snapshot is a fact about THIS order,")
    print("    not about THIS product.")

    order_items = [
        {"order_id": "o1", "product_id": "p1", "qty": 2, "unit_price_at_order": 25},
        {"order_id": "o2", "product_id": "p1", "qty": 1, "unit_price_at_order": 30},
    ]
    print_table("order_items with deliberate price snapshot:",
                ["order_id", "product_id", "qty", "unit_price_at_order"], order_items)
    print("    o1 paid 25 (old price), o2 paid 30 (new price) -- history is frozen.")

    print("  Example 2 -- read-path denormalization: the order-detail page renders")
    print("  50,000x/sec. Joining 4 tables per request is wasteful -> materialized view.")
    joins = 4
    per_join_ms = 4
    normalized_read_ms = joins * per_join_ms
    denorm_read_ms = 2
    write_amp = joins  # each insert must also refresh the materialized view / counter
    print(f"    normalized read  = {joins} joins x {per_join_ms}ms = {normalized_read_ms}ms")
    print(f"    denormalized read = 1 lookup           = {denorm_read_ms}ms")
    print(f"    write cost: denormalization needs ~{write_amp}x writes to stay consistent")
    speedup = normalized_read_ms / denorm_read_ms
    print(f"    read speedup = {normalized_read_ms}/{denorm_read_ms} = {speedup:.1f}x  "
          f"(trades write amplification for read latency)")
    print("  Invariant to document: 'order_summary is a cache of orders+users+items;")
    print("  refreshed by a trigger; reconciled by a nightly job if it drifts.'")
    check("denormalize only hot paths; always pair it with a reconciliation plan")


# =========================================================================== #
#  07. INDEXING STRATEGY -- B-tree, composite, covering, the 5% rule
# =========================================================================== #
def leftmost_usable(index_cols: Sequence[str],
                    filter_cols: set) -> List[str]:
    """Composite-index leftmost-prefix rule.

    Walk the index left to right; a column is usable while the query has a
    predicate on it AND every earlier index column was also constrained.
    The first unconstrained column breaks the prefix -- the rest are skipped.
    """
    usable: List[str] = []
    for ic in index_cols:
        if ic in filter_cols:
            usable.append(ic)
        else:
            break
    return usable


def planner_uses_index(rows_matched: int, total_rows: int) -> bool:
    """PostgreSQL heuristic: the planner picks the index when the predicate
    matches < ~5% of the table; otherwise a sequential scan wins."""
    if total_rows <= 0:
        return False
    return (rows_matched / total_rows) < 0.05


def section_indexing() -> None:
    banner("07. INDEXING STRATEGY -- composite, covering, the 5% selectivity rule")
    print('  RULE: index from the QUERY MIX, not the column list. Every index costs')
    print("  ~10-30% write throughput -- it is a budget, not a checklist.")
    index_cols = ["user_id", "status", "created_at"]
    print(f"  COMPOSITE INDEX on ({', '.join(index_cols)})  -- leftmost prefix rules all:")
    queries = [
        ("WHERE user_id = ?",                          {"user_id"}),
        ("WHERE user_id = ? AND status = ?",           {"user_id", "status"}),
        ("WHERE user_id = ? AND status = ? AND created_at > ?",
                                                         {"user_id", "status", "created_at"}),
        ("WHERE status = ?",                           {"status"}),
        ("WHERE user_id = ? AND created_at > ?",       {"user_id", "created_at"}),
    ]
    for q, fc in queries:
        usable = leftmost_usable(index_cols, fc)
        verdict = "INDEX USED" if usable else "FULL SCAN"
        print(f"    {q:<48} -> usable=[{','.join(usable)}]  {verdict}")
    print("  Note the last query: created_at is skipped because 'status' (the middle")
    print("  column) is not constrained -> the prefix breaks at user_id.")
    check("leftmost-prefix: a composite index serves any leftmost subset of its columns")

    print()
    print("  COVERING INDEX (PostgreSQL INCLUDE): embed hot SELECT columns in the leaf")
    print("  so the query never reads the heap row (index-only scan, Heap Fetches: 0).")
    print("    CREATE INDEX idx_orders_cover ON orders (user_id, created_at)")
    print("      INCLUDE (status, total_cents);")
    print()
    print("  PARTIAL INDEX: index only the hot subset (<1% of rows) -> tiny + fast writes.")
    print("    CREATE INDEX idx_tickets_active ON tickets (spot_id) WHERE status = 'active';")
    print()

    print("  THE 5% SELECTIVITY RULE -- when NOT to index:")
    cases = [
        ("vehicle_plate point lookup", 1, 1_000_000_000),
        ("status = 'active' subset",    10_000_000, 1_000_000_000),
        ("gender = 'F' (half the table)", 500_000_000, 1_000_000_000),
    ]
    for name, matched, total in cases:
        uses = planner_uses_index(matched, total)
        pct = matched / total * 100
        verdict = "INDEX HELPS" if uses else "PLANNER FULL-SCANS"
        print(f"    {name:<34} match={pct:.2f}%  -> {verdict}")
    print("  Low-cardinality columns (gender, 3-value status) almost never earn an index.")
    check("index when selectivity < ~5%; skip on low-cardinality / tiny tables")


# =========================================================================== #
#  GOLD CHECK -- B-tree depth for 1B rows (recomputed by the HTML in JS)
# =========================================================================== #
def btree_depth(rows: int, fanout: int) -> float:
    """B-tree height = log_fanout(rows). Depth 3-4 for a 1B-row table is the
    staff-level 'a B-tree point lookup is 3-4 cached disk seeks' fact."""
    return math.log(rows) / math.log(fanout)


def section_gold_check() -> None:
    banner("GOLD CHECK  (recomputed by database_schema_design.html in JS)")
    rows, fanout = 1_000_000_000, 200
    depth = btree_depth(rows, fanout)
    seeks = math.ceil(depth)
    gold = f"{depth:.1f}"
    print(f"  btree_depth(rows={rows:,}, fanout={fanout})")
    print(f"    height = log({rows:,}) / log({fanout}) = {depth:.4f}")
    print(f"    rounded = {gold}  ->  ceil = {seeks} disk seeks for ANY point lookup")
    print("  [check] OK")


# =========================================================================== #
#  Main
# =========================================================================== #
if __name__ == "__main__":
    print("#" * 72)
    print("# DATABASE SCHEMA DESIGN -- ER modeling, normalization (1NF->BCNF),")
    print("# denormalization, indexing strategy (pure stdlib)")
    print("#" * 72)
    section_er_modeling()
    section_1nf()
    section_2nf()
    section_3nf()
    section_bcnf()
    section_denormalization()
    section_indexing()
    section_gold_check()
    print("\n[check] OK -- all 7 topics + gold check demoed")
