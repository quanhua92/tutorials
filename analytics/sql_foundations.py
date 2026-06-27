"""
sql_foundations.py - SQL Foundations: JOINs, GROUP BY, HAVING, subqueries,
set operations, and CTEs.

This is the single source of truth for SQL_FOUNDATIONS.md. Every table and
number in the guide is printed by this file. If you change something here,
re-run and re-paste the output into the guide. Pure Python stdlib (sqlite3).

Run:
    python3 sql_foundations.py

============================================================================
THE INTUITION (read this first) - JOINs are row survival rules
============================================================================
Every JOIN answers ONE question: "when the ON key has no match on the other
side, do I keep, drop, or NULL-fill the row?" That single decision is what
separates the five join families:

    INNER   keep a row ONLY if both sides match           (drop unmatched)
    LEFT    keep every LEFT row; NULL-fill the right side (left survives)
    RIGHT   keep every RIGHT row; NULL-fill the left side (right survives)
            -- real-world rule: never write RIGHT JOIN; swap the table order
               and use LEFT JOIN. This file demonstrates exactly that.
    FULL    keep everything; NULL-fill whichever side has no match
    CROSS   cartesian product: every left row x every right row (no ON)

Set operations (UNION/INTERSECT/EXCEPT) work at the ROW level, not the join
level, but solve the same "combine two row-sets" problem and are shown below
alongside the anti-join pattern they replace.

============================================================================
THE SCHEMA (in-memory; deliberately small and asymmetric)
============================================================================
    users(id, name, country)        5 users: Alice/Bob/Carol (have orders),
                                     Dave/Eve (no orders)
    orders(id, user_id, amount)     7 orders: 6 reference real users,
                                     order 106 references user_id=9 (orphan)
    employees(id, name, manager_id) 4 rows forming a 2-level reporting tree
                                     (self-join demo)

The asymmetry (unmatched rows on BOTH sides, plus an orphan) is what makes
each join type produce a visibly different result set.
"""

import sqlite3

BANNER = "=" * 74


# ---------------------------------------------------------------------------
# schema + seed data
# ---------------------------------------------------------------------------

def build_db():
    """Create an in-memory SQLite DB with the sample tables and seed data."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE users (
            id      INTEGER PRIMARY KEY,
            name    TEXT,
            country TEXT
        );
        CREATE TABLE orders (
            id       INTEGER PRIMARY KEY,
            user_id  INTEGER,
            amount   INTEGER
        );
        CREATE TABLE employees (
            id          INTEGER PRIMARY KEY,
            name        TEXT,
            manager_id  INTEGER
        );

        INSERT INTO users VALUES
            (1, 'Alice', 'US'),
            (2, 'Bob',   'UK'),
            (3, 'Carol', 'US'),
            (4, 'Dave',  'CA'),
            (5, 'Eve',   'US');

        INSERT INTO orders VALUES
            (101, 1, 30),
            (102, 1, 70),
            (103, 2, 50),
            (107, 2, 80),
            (104, 3, 20),
            (105, 3, 40),
            (106, 9, 90);       -- user_id 9 does NOT exist in users (orphan)

        INSERT INTO employees VALUES
            (1, 'Alice', NULL),
            (2, 'Bob',   1),
            (3, 'Carol', 1),
            (4, 'Dave',  2);
        """
    )
    return conn


# ---------------------------------------------------------------------------
# pretty printers
# ---------------------------------------------------------------------------

def banner(title):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_table(headers, rows, indent="  "):
    """Boxed ASCII table. headers=list[str], rows=list[tuple]."""
    rows = [[("" if c is None else c) for c in r] for r in rows]
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def fmt(r):
        return indent + "| " + " | ".join(str(c).ljust(w) for c, w in zip(r, widths)) + " |"

    print(indent + sep)
    print(fmt(headers))
    print(indent + sep)
    for r in rows:
        print(fmt(r))
    print(indent + sep)


def run(conn, label, sql):
    """Execute SQL, print a labelled result table, return the rows."""
    cur = conn.execute(sql)
    headers = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"  {label}  ({len(rows)} rows)")
    print_table(headers, rows)
    return rows


# ---------------------------------------------------------------------------
# SECTION 0: the data we are joining
# ---------------------------------------------------------------------------

def section_data():
    banner("SECTION 0: the tables we are joining")
    conn = build_db()
    print("  Three small tables. Note the asymmetry that drives every demo:")
    print("    * users Dave(4) and Eve(5) have NO orders")
    print("    * order 106 references user_id=9, who does NOT exist (orphan)\n")
    run(conn, "users", "SELECT id, name, country FROM users ORDER BY id")
    run(conn, "orders", "SELECT id, user_id, amount FROM orders ORDER BY id")
    run(conn, "employees (self-join tree)",
         "SELECT id, name, manager_id FROM employees ORDER BY id")
    conn.close()


# ---------------------------------------------------------------------------
# SECTION 1: JOIN types with Venn-style result comparison
# ---------------------------------------------------------------------------

def section_joins():
    banner("SECTION 1: JOIN types - the row-survival rules")
    print("  Same two tables, five join families. Watch which rows survive and")
    print("  where NULLs appear. Venn reading:")
    print("    LEFT-ONLY  = users with no orders            {Dave, Eve}")
    print("    INTERSECT  = users who have matching orders  {Alice, Bob, Carol}")
    print("    RIGHT-ONLY = orders with no matching user    {order 106}\n")

    conn = build_db()

    run(conn, "INNER JOIN  (intersection only)",
        """
        SELECT u.id AS uid, u.name, o.id AS oid, o.amount
        FROM   users u
        JOIN   orders o ON o.user_id = u.id
        ORDER BY u.id, o.id
        """)
    print("  Venn: only INTERSECT lit. Unmatched users (Dave,Eve) and the")
    print("        orphan order (106) are DROPPED.\n")

    run(conn, "LEFT JOIN   (all left rows; NULL-fill right)",
        """
        SELECT u.id AS uid, u.name, o.id AS oid, o.amount
        FROM   users u
        LEFT JOIN orders o ON o.user_id = u.id
        ORDER BY u.id, o.id
        """)
    print("  Venn: LEFT-ONLY + INTERSECT lit. Dave and Eve survive with")
    print("        oid/amount = NULL. The orphan order is still dropped.\n")

    run(conn, "RIGHT JOIN  (via LEFT + swapped table order - the recommended way)",
        """
        SELECT o.id AS oid, o.user_id AS uid, u.name, o.amount
        FROM   orders o
        LEFT JOIN users u ON u.id = o.user_id
        ORDER BY o.id
        """)
    print("  Venn: INTERSECT + RIGHT-ONLY lit. Every order survives; order 106")
    print("        now appears with name = NULL. (Never write RIGHT JOIN - just")
    print("        swap the tables and use LEFT JOIN, as done here.)\n")

    run(conn, "FULL OUTER JOIN  (everything; NULLs on both sides)",
        """
        SELECT u.id AS uid, u.name, o.id AS oid, o.amount
        FROM   users u
        FULL OUTER JOIN orders o ON o.user_id = u.id
        ORDER BY u.id NULLS LAST, o.id
        """)
    print("  Venn: all three regions lit. Both unmatched sides appear: Dave/Eve")
    print("        (right cols NULL) AND order 106 (left cols NULL).\n")

    full = conn.execute("SELECT COUNT(*) FROM users CROSS JOIN orders").fetchone()[0]
    print(f"  CROSS JOIN  (cartesian product: every left x every right)")
    print(f"    5 users x 7 orders = {full} rows. No ON condition.\n")
    run(conn, "CROSS JOIN (first 6 of 35 rows shown)",
        """
        SELECT u.id AS uid, u.name, o.id AS oid, o.amount
        FROM   users u
        CROSS JOIN orders o
        ORDER BY u.id, o.id
        LIMIT 6
        """)

    run(conn, "SELF JOIN  (employees <-> their manager)",
        """
        SELECT e.name AS employee, m.name AS manager
        FROM   employees e
        LEFT JOIN employees m ON m.id = e.manager_id
        ORDER BY e.id
        """)
    print("  A table joined to itself (aliased e and m). LEFT JOIN keeps Alice,")
    print("  the root, with manager = NULL. The basis of referral/chain queries.\n")

    # summary row-count comparison (counts pulled live from the DB)
    def cnt(sql):
        return conn.execute(sql).fetchone()[0]

    n_inner = cnt("SELECT COUNT(*) FROM users u JOIN orders o ON o.user_id=u.id")
    n_left = cnt("SELECT COUNT(*) FROM users u LEFT JOIN orders o ON o.user_id=u.id")
    n_right = cnt("SELECT COUNT(*) FROM orders o LEFT JOIN users u ON u.id=o.user_id")
    n_full = cnt("SELECT COUNT(*) FROM users u FULL OUTER JOIN orders o ON o.user_id=u.id")
    n_cross = cnt("SELECT COUNT(*) FROM users CROSS JOIN orders")
    print("  Row-count comparison across join families (the Venn at a glance):\n")
    summary = [
        ("CROSS",  f"5 x 7 = {n_cross}", "every combination (no ON)"),
        ("FULL",   str(n_full),          f"{n_left} (LEFT) + orphan order 106"),
        ("LEFT",   str(n_left),          "all 5 users (Dave,Eve NULL-filled)"),
        ("RIGHT",  str(n_right),         "all 7 orders (106 NULL-filled)"),
        ("INNER",  str(n_inner),         "matched rows only"),
    ]
    print_table(["JOIN", "rows", "what survives"], [(j, r, w) for j, r, w in summary])
    conn.close()


# ---------------------------------------------------------------------------
# SECTION 2: GROUP BY + HAVING (and WHERE vs HAVING)
# ---------------------------------------------------------------------------

def section_groupby():
    banner("SECTION 2: GROUP BY + HAVING (aggregate filtering)")
    print("  Execution order: FROM > JOIN > WHERE > GROUP BY > HAVING > SELECT")
    print("  > ORDER BY > LIMIT. WHERE filters ROWS before grouping; HAVING")
    print("  filters GROUPS after aggregation. Mixing them up = wrong totals.\n")

    conn = build_db()

    run(conn, "GROUP BY: per-user order count and spend (LEFT JOIN keeps all users)",
        """
        SELECT u.name,
               COUNT(o.id)        AS n_orders,
               COALESCE(SUM(o.amount), 0) AS total
        FROM   users u
        LEFT JOIN orders o ON o.user_id = u.id
        GROUP BY u.id, u.name
        ORDER BY total DESC, u.name
        """)
    print("  COUNT(o.id) counts matched orders (0 for Dave/Eve); COALESCE turns")
    print("  the NULL SUM into 0. Note COUNT(*) would wrongly read 1 for users")
    print("  with no orders (it counts the NULL-filled row itself).\n")

    run(conn, "HAVING SUM(amount) > 70  (filter on the aggregate, not the row)",
        """
        SELECT u.name,
               COUNT(o.id)        AS n_orders,
               COALESCE(SUM(o.amount), 0) AS total
        FROM   users u
        LEFT JOIN orders o ON o.user_id = u.id
        GROUP BY u.id, u.name
        HAVING SUM(o.amount) > 70
        ORDER BY total DESC
        """)
    print("  Only Bob (130) and Alice (100) survive. Carol's 60 is filtered OUT")
    print("  after grouping - this could never be expressed in WHERE.\n")

    run(conn, "WHERE country='US' BEFORE, HAVING SUM>50 AFTER  (both together)",
        """
        SELECT u.name,
               COUNT(o.id)        AS n_orders,
               COALESCE(SUM(o.amount), 0) AS total
        FROM   users u
        LEFT JOIN orders o ON o.user_id = u.id
        WHERE  u.country = 'US'
        GROUP BY u.id, u.name
        HAVING SUM(o.amount) > 50
        ORDER BY total DESC
        """)
    print("  WHERE shrinks the input to US users (Alice, Carol, Eve) BEFORE")
    print("  grouping. HAVING then keeps only groups spending > 50: Alice and")
    print("  Carol. Eve's group (0) is dropped. Right filter, right stage.\n")
    conn.close()


# ---------------------------------------------------------------------------
# SECTION 3: subqueries (scalar, correlated, EXISTS)
# ---------------------------------------------------------------------------

def section_subqueries():
    banner("SECTION 3: subqueries - scalar, correlated, EXISTS")
    conn = build_db()

    avg = conn.execute("SELECT AVG(amount) FROM orders").fetchone()[0]
    print(f"  Average order amount = {avg:.4f} (= 380/7). Used by the scalar")
    print("  subquery below.\n")

    run(conn, "SCALAR subquery: orders priced above the average",
        """
        SELECT o.id, o.user_id, o.amount
        FROM   orders o
        WHERE  o.amount > (SELECT AVG(amount) FROM orders)
        ORDER BY o.id
        """)
    print("  The subquery returns ONE value (the average); the outer query uses")
    print("  it as a constant. Runs once.\n")

    run(conn, "CORRELATED subquery: each user's biggest order (re-runs per row)",
        """
        SELECT u.name,
               (SELECT MAX(o.amount)
                  FROM orders o
                 WHERE o.user_id = u.id) AS max_order
        FROM   users u
        ORDER BY u.id
        """)
    print("  The inner query references the OUTER u.id, so it re-executes for")
    print("  every user -> O(users x orders). In production rewrite this as a")
    print("  JOIN or window function (see Section 5 CTE pattern).\n")

    run(conn, "EXISTS: users who placed >= 1 order",
        """
        SELECT u.name
        FROM   users u
        WHERE  EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id)
        """)
    run(conn, "NOT EXISTS: users who NEVER ordered  (anti-join)",
        """
        SELECT u.name
        FROM   users u
        WHERE  NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id)
        """)
    print("  EXISTS short-circuits at the first match; NOT EXISTS is the safe")
    print("  anti-join (unlike NOT IN, which returns NOTHING if the subquery")
    print("  contains a NULL). Prefer LEFT JOIN + IS NULL / NOT EXISTS.\n")
    conn.close()


# ---------------------------------------------------------------------------
# SECTION 4: set operations (UNION, INTERSECT, EXCEPT)
# ---------------------------------------------------------------------------

def section_setops():
    banner("SECTION 4: set operations - UNION, INTERSECT, EXCEPT")
    print("  Combine row-sets by VALUE (not by join key). All SELECTs must")
    print("  return the same number/column-types. UNION dedupes; UNION ALL\n"
          "  keeps duplicates and is faster when you know they are distinct.\n")

    conn = build_db()

    run(conn, "UNION: every user_id seen anywhere (users UNION order user_ids)",
        """
        SELECT id      AS uid FROM users
        UNION
        SELECT user_id        FROM orders
        ORDER BY uid
        """)
    print("  users ids {1,2,3,4,5} UNION order user_ids {1,1,2,2,3,3,9},")
    print("  de-duplicated -> {1,2,3,4,5,9}. The orphan user_id 9 appears.\n")

    run(conn, "INTERSECT: user_ids present in BOTH tables",
        """
        SELECT id      FROM users
        INTERSECT
        SELECT user_id FROM orders
        ORDER BY id
        """)
    print("  Users that actually placed orders: {1,2,3}.\n")

    run(conn, "EXCEPT: users who never ordered (set-based anti-join)",
        """
        SELECT id FROM users
        EXCEPT
        SELECT user_id FROM orders
        ORDER BY id
        """)
    print("  {4,5} = Dave, Eve. Same answer as NOT EXISTS / LEFT JOIN + IS NULL")
    print("  - pick whichever reads cleanest.\n")
    conn.close()


# ---------------------------------------------------------------------------
# SECTION 5: CTEs (WITH clause) - the multi-step rewrite
# ---------------------------------------------------------------------------

def section_cte():
    banner("SECTION 5: CTEs (WITH) - named, testable, composable steps")
    print("  A CTE is a named subquery you can reference like a table. Chain")
    print("  several to build cohort/ranking pipelines top-down. Each step is")
    print("  independently testable; modern optimizers treat CTEs and inline")
    print("  subqueries identically, so prefer CTEs for readability.\n")

    conn = build_db()
    run(conn, "CTE chain: per-user totals -> RANK() -> ordered leaderboard",
        """
        WITH per_user AS (
            SELECT u.id, u.name,
                   COUNT(o.id)              AS n_orders,
                   COALESCE(SUM(o.amount), 0) AS total
            FROM   users u
            LEFT JOIN orders o ON o.user_id = u.id
            GROUP BY u.id, u.name
        ),
        ranked AS (
            SELECT *, RANK() OVER (ORDER BY total DESC) AS rnk
            FROM   per_user
        )
        SELECT name, n_orders, total, rnk
        FROM   ranked
        ORDER BY rnk, name
        """)
    print("  Step 1 per_user  : LEFT JOIN + GROUP BY -> one row per user with")
    print("                      totals (NULL-safe via COALESCE).")
    print("  Step 2 ranked    : window RANK() over totals (ties share a rank:")
    print("                      Dave and Eve both get rnk=4).")
    print("  Step 3 final     : project + order. This is the exact shape of a")
    print("                      cohort-retention query (4 CTEs, each testable).\n")
    conn.close()


# ---------------------------------------------------------------------------
# GOLD CHECK - recompute key facts in pure Python, assert against SQL
# ---------------------------------------------------------------------------

def gold_check():
    banner("GOLD CHECK: SQL output == independent Python recompute")

    USERS = [
        (1, "Alice", "US"), (2, "Bob", "UK"), (3, "Carol", "US"),
        (4, "Dave", "CA"), (5, "Eve", "US"),
    ]
    ORDERS = [
        (101, 1, 30), (102, 1, 70), (103, 2, 50), (107, 2, 80),
        (104, 3, 20), (105, 3, 40), (106, 9, 90),
    ]

    # pure-Python recomputations
    by_user = {}
    for uid, name, _ in USERS:
        by_user[uid] = [name, 0, 0]          # name, n_orders, total
    for _, uid, amt in ORDERS:
        if uid in by_user:
            by_user[uid][1] += 1
            by_user[uid][2] += amt

    py_per_user = {n: (cnt, tot) for (n, cnt, tot) in by_user.values()}
    py_inner_rows = sum(1 for _, uid, _ in ORDERS if uid in by_user)
    py_inner_total = sum(amt for _, uid, amt in ORDERS if uid in by_user)
    py_avg = sum(amt for _, _, amt in ORDERS) / len(ORDERS)
    py_above_avg = sum(1 for _, _, amt in ORDERS if amt > py_avg)

    conn = build_db()

    # 1. INNER join row count + total
    sql_inner = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(o.amount),0) "
        "FROM orders o JOIN users u ON u.id=o.user_id"
    ).fetchone()
    assert sql_inner[0] == py_inner_rows == 6, "INNER row count mismatch"
    assert sql_inner[1] == py_inner_total == 290, "INNER total mismatch"
    print(f"  INNER JOIN: rows={sql_inner[0]} (py {py_inner_rows}), "
          f"total={sql_inner[1]} (py {py_inner_total})  -> OK")

    # 2. per-user totals (GROUP BY) match the python dict
    sql_group = conn.execute(
        "SELECT u.name, COUNT(o.id), COALESCE(SUM(o.amount),0) "
        "FROM users u LEFT JOIN orders o ON o.user_id=u.id "
        "GROUP BY u.id, u.name"
    ).fetchall()
    for name, cnt, tot in sql_group:
        pcnt, ptot = py_per_user[name]
        assert cnt == pcnt and tot == ptot, f"per-user {name} mismatch"
    print(f"  GROUP BY per-user totals match python for all {len(sql_group)} users -> OK")

    # 3. scalar-subquery average
    sql_avg = conn.execute("SELECT AVG(amount) FROM orders").fetchone()[0]
    assert abs(sql_avg - py_avg) < 1e-9, "AVG mismatch"
    sql_above = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE amount > (SELECT AVG(amount) FROM orders)"
    ).fetchone()[0]
    assert sql_above == py_above_avg == 3, "above-avg count mismatch"
    print(f"  AVG={sql_avg:.4f} (py {py_avg:.4f}); orders above avg={sql_above} "
          f"(py {py_above_avg})  -> OK")

    # 4. anti-join (NOT EXISTS == LEFT JOIN + IS NULL == EXCEPT)
    ne = {r[0] for r in conn.execute(
        "SELECT u.name FROM users u "
        "WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id=u.id)")}
    lj = {r[0] for r in conn.execute(
        "SELECT u.name FROM users u LEFT JOIN orders o ON o.user_id=u.id "
        "WHERE o.id IS NULL")}
    ex = {r[0] for r in conn.execute(
        "SELECT u.name FROM users u WHERE u.id IN ("
        "  SELECT id FROM users EXCEPT SELECT user_id FROM orders)")}
    assert ne == lj == ex == {"Dave", "Eve"}, "anti-join mismatch"
    print(f"  Anti-join (NOT EXISTS == LEFT JOIN+IS NULL == EXCEPT) = "
          f"{sorted(ne)}  -> OK")

    conn.close()
    print("\n  [check] SQL output matches independent Python recompute on all"
          "  four checks: OK")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print("sql_foundations.py - JOINs, GROUP BY, HAVING, subqueries, set ops, CTEs.")
    print("stdlib only (sqlite3). Run: python3 sql_foundations.py")
    section_data()
    section_joins()
    section_groupby()
    section_subqueries()
    section_setops()
    section_cte()
    gold_check()
    banner("DONE - all sections printed")
    print("  [check] OK")


if __name__ == "__main__":
    main()
