#!/usr/bin/env python3
"""
sql_window_functions.py - SQL window functions on sqlite3 (GROUND TRUTH).

Pure Python stdlib only (sqlite3). Every value printed below feeds
SQL_WINDOW_FUNCTIONS.md and is recomputed identically in
sql_window_functions.html (gold-checked).

A window function annotates EVERY input row with window-level information
WITHOUT collapsing them (unlike GROUP BY). Three OVER() knobs:
    PARTITION BY  -> the group
    ORDER BY      -> the sequence within the group
    ROWS BETWEEN  -> the frame (how many rows contribute)

Sections:
    1. ROW_NUMBER         - unique 1..N per partition (dedup, top-N filter)
    2. RANK vs DENSE_RANK - tie handling (skip vs no-skip)
    3. LAG / LEAD         - period-over-period, day-over-day change
    4. SUM() OVER         - running total (cumulative, frame clause)
    5. AVG() OVER         - 3-row moving average (frame clause)
    6. NTILE              - percentile / quartile bucketing
    7. FIRST_VALUE / LAST_VALUE - first/last per partition (frame pitfall)
    8. GOLD values pinned for sql_window_functions.html
"""

import sqlite3

LINE = "=" * 74

# ---------------------------------------------------------------------------
# schema + seed data
# Two tables:
#   sales : reps per region with amounts -> ties to show RANK vs DENSE_RANK
#   daily : 7 days of revenue for one region -> running total + moving avg
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE sales (
    region TEXT,
    rep    TEXT,
    amount INTEGER
);
INSERT INTO sales VALUES
    ('East','alice',100),
    ('East','bob',  100),
    ('East','carol', 80),
    ('East','dave',  60),
    ('West','eve',   120),
    ('West','frank',  90),
    ('West','grace',  90),
    ('West','heidi',  50);

CREATE TABLE daily (
    dt      TEXT,
    region  TEXT,
    revenue INTEGER
);
INSERT INTO daily VALUES
    ('2024-01-01','North',100),
    ('2024-01-02','North',150),
    ('2024-01-03','North',120),
    ('2024-01-04','North',200),
    ('2024-01-05','North',180),
    ('2024-01-06','North', 90),
    ('2024-01-07','North',110);
"""


def build_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def gold_list(rows):
    """Join the last column (window value) of matching rows into 'a,b,c'."""
    return ",".join(str(r[-1]) for r in rows)


# ---------------------------------------------------------------------------
# SECTION 1 - ROW_NUMBER
# ---------------------------------------------------------------------------

def section_row_number(conn, gold):
    banner("SECTION 1: ROW_NUMBER() - unique rank per partition")
    print("ROW_NUMBER() assigns 1,2,3,... with NO ties -- the tie-break is")
    print("arbitrary (here forced deterministic by adding 'rep' to ORDER BY).")
    print("Use it for deduplication ('latest row per user') and for")
    print("top-N-per-group: wrap in a CTE, then WHERE rn <= N.\n")
    rows = conn.execute("""
        SELECT region, rep, amount,
               ROW_NUMBER() OVER (PARTITION BY region
                                  ORDER BY amount DESC, rep) AS rn
        FROM sales
        ORDER BY region, rn
    """).fetchall()
    print("  %-6s %-7s %7s   %4s" % ("region", "rep", "amount", "*rn"))
    for r in rows:
        print("  %-6s %-7s %7d   *%d" % (r[0], r[1], r[2], r[3]))
    print()
    print("  >>> West: eve is #1 (120). frank & grace TIE at 90, but ROW_NUMBER")
    print("      breaks it arbitrarily -> frank=2, grace=3. No duplicate ranks.\n")
    east = [r for r in rows if r[0] == "East"]
    west = [r for r in rows if r[0] == "West"]
    ok = (gold_list(east) == "1,2,3,4" and gold_list(west) == "1,2,3,4"
          and west[0][1] == "eve" and west[3][1] == "heidi")
    gold.append(("row_number_east", gold_list(east)))
    gold.append(("row_number_west", gold_list(west)))
    print("[check] East rn 1..4, West rn 1..4 (eve=1, heidi=4)? "
          + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - RANK vs DENSE_RANK
# ---------------------------------------------------------------------------

def section_rank(conn, gold):
    banner("SECTION 2: RANK() vs DENSE_RANK() - tie handling")
    print("On a tie both give the SAME number, but differ AFTER the tie:")
    print("  RANK       -> skips ranks   (1,1,3,4)  'tied for 1st, next is 3rd'")
    print("  DENSE_RANK -> no skip       (1,1,2,3)  correct for 'Nth highest'")
    print("ROW_NUMBER (sec 1) -> unique   (1,2,3,4)  correct for dedup / exact N.\n")
    rows = conn.execute("""
        SELECT region, rep, amount,
               RANK()       OVER (PARTITION BY region ORDER BY amount DESC) AS rk,
               DENSE_RANK() OVER (PARTITION BY region ORDER BY amount DESC) AS dr
        FROM sales
        ORDER BY region, rk, rep
    """).fetchall()
    print("  %-6s %-7s %7s   %5s   %5s" % ("region", "rep", "amount", "*rank", "*dense"))
    for r in rows:
        print("  %-6s %-7s %7d   *%d     *%d" % (r[0], r[1], r[2], r[3], r[4]))
    print()
    east = [r for r in rows if r[0] == "East"]
    west = [r for r in rows if r[0] == "West"]
    print("  >>> East amounts [100,100,80,60]:")
    print("        RANK       = 1,1,3,4   (jumps 1 -> 3, rank '2' does not exist)")
    print("        DENSE_RANK = 1,1,2,3   (no gap, so '2nd highest' always works)")
    print("  >>> 'second-highest salary' trap: RANK fails when two people share")
    print("      the top value (rank 2 is missing). DENSE_RANK always works.\n")
    rk_e = ",".join(str(r[3]) for r in east)
    dr_e = ",".join(str(r[4]) for r in east)
    rk_w = ",".join(str(r[3]) for r in west)
    dr_w = ",".join(str(r[4]) for r in west)
    ok = (rk_e == "1,1,3,4" and dr_e == "1,1,2,3"
          and rk_w == "1,2,2,4" and dr_w == "1,2,2,3")
    gold.append(("rank_east", rk_e))
    gold.append(("rank_west", rk_w))
    gold.append(("dense_rank_east", dr_e))
    gold.append(("dense_rank_west", dr_w))
    print("[check] East RANK 1,1,3,4 / DENSE 1,1,2,3, West RANK 1,2,2,4 / "
          "DENSE 1,2,2,3? " + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - LAG / LEAD
# ---------------------------------------------------------------------------

def section_lag_lead(conn, gold):
    banner("SECTION 3: LAG() / LEAD() - period-over-period")
    print("LAG(col,n,default)  peeks n rows BACK  in the partition.")
    print("LEAD(col,n,default) peeks n rows AHEAD.")
    print("The first row per partition has no predecessor -> LAG returns NULL")
    print("(handle with COALESCE or the 3-arg form). Classic use: day-over-day.\n")
    rows = conn.execute("""
        SELECT dt, revenue,
               LAG(revenue, 1, NULL)  OVER (ORDER BY dt) AS prev_rev,
               LEAD(revenue, 1, NULL) OVER (ORDER BY dt) AS next_rev
        FROM daily
        ORDER BY dt
    """).fetchall()
    print("  %-12s %7s   %8s   %8s   %8s"
          % ("dt", "revenue", "*lag", "*lead", "*dod_chg"))
    out = []
    for r in rows:
        prev, nxt = r[2], r[3]
        dod = r[1] - prev if prev is not None else None
        dod_s = "%+d" % dod if dod is not None else "-"
        prev_s = "%d" % prev if prev is not None else "NULL"
        nxt_s = "%d" % nxt if nxt is not None else "NULL"
        print("  %-12s %7d   *%-8s *%-8s   *%-8s" % (r[0], r[1], prev_s, nxt_s, dod_s))
        out.append((r[0], r[1], prev, nxt, dod))
    print()
    print("  >>> day-over-day change = revenue - LAG(revenue). 01 has no prior")
    print("      day -> NULL (shown as '-'). 02 jumps +50; 06 drops -90.\n")
    by = {o[0]: o for o in out}
    ok = (by["2024-01-02"][2] == 100 and by["2024-01-02"][3] == 120
          and by["2024-01-02"][4] == 50 and by["2024-01-01"][2] is None
          and by["2024-01-07"][3] is None)
    gold.append(("lag_02", str(by["2024-01-02"][2])))
    gold.append(("lead_02", str(by["2024-01-02"][3])))
    gold.append(("dod_02", str(by["2024-01-02"][4])))
    print("[check] 02 lag=100 lead=120 dod=+50, 01 lag=NULL, 07 lead=NULL? "
          + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - SUM() OVER  (running total)
# ---------------------------------------------------------------------------

def section_running_total(conn, gold):
    banner("SECTION 4: SUM() OVER - running total (cumulative)")
    print("Aggregate + an explicit FRAME clause = rolling computation.")
    print("  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW")
    print("      -> sum of everything from the partition start to THIS row.")
    print("Rule: for time series ALWAYS use ROWS (not RANGE) -- RANGE with ties")
    print("or gaps can include unexpected rows.\n")
    rows = conn.execute("""
        SELECT dt, revenue,
               SUM(revenue) OVER (ORDER BY dt
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running
        FROM daily
        ORDER BY dt
    """).fetchall()
    print("  %-12s %7s   %9s" % ("dt", "revenue", "*running_total"))
    for r in rows:
        print("  %-12s %7d   *%9d" % (r[0], r[1], r[2]))
    print()
    print("  >>> running total accumulates: 100,250,370,570,750,840,950.")
    print("      The window GROWS by one row each step -> every prior row")
    print("      contributes to the current sum.\n")
    final = rows[-1][2]
    ok = (rows[0][2] == 100 and final == 950
          and rows[2][2] == 370 and rows[4][2] == 750)
    gold.append(("running_total_07", str(final)))
    gold.append(("running_total_03", str(rows[2][2])))
    print("[check] running total starts 100, day3=370, ends 950? "
          + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - AVG() OVER  (moving average)
# ---------------------------------------------------------------------------

def section_moving_average(conn, gold):
    banner("SECTION 5: AVG() OVER - 3-row moving average")
    print("A NARROW frame = a rolling/smoothed metric.")
    print("  ROWS BETWEEN 2 PRECEDING AND CURRENT ROW  -> 3-row moving average.")
    print("At the partition edges fewer rows fall in the window, so early values")
    print("use 1 or 2 rows (not 3) -- the average is still exact, just shorter.\n")
    rows = conn.execute("""
        SELECT dt, revenue,
               AVG(revenue) OVER (ORDER BY dt
                   ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS ma3
        FROM daily
        ORDER BY dt
    """).fetchall()
    print("  %-12s %7s   %11s" % ("dt", "revenue", "*ma3"))
    for r in rows:
        print("  %-12s %7d   *%11.2f" % (r[0], r[1], r[2]))
    print()
    print("  >>> day3 window = days(1,2,3): (100+150+120)/3 = 123.33.")
    print("      day5 window = days(3,4,5): (120+200+180)/3 = 166.67.")
    print("      The frame SLIDES, always 3 rows wide once past the start.\n")
    d = {r[0]: r[2] for r in rows}
    ok = (abs(d["2024-01-03"] - 123.33) < 0.01
          and abs(d["2024-01-05"] - 166.67) < 0.01
          and abs(d["2024-01-01"] - 100.0) < 1e-9)
    gold.append(("moving_avg_03", "%.2f" % d["2024-01-03"]))
    gold.append(("moving_avg_05", "%.2f" % d["2024-01-05"]))
    print("[check] ma3 day1=100.00, day3=123.33, day5=166.67? "
          + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - NTILE
# ---------------------------------------------------------------------------

def section_ntile(conn, gold):
    banner("SECTION 6: NTILE(n) - percentile / quartile bucketing")
    print("NTILE(n) splits an ordered partition into n roughly-equal buckets.")
    print("NTILE(4)=quartiles, NTILE(10)=deciles, NTILE(100)=percentiles.")
    print("When rows do not divide evenly, EARLIER buckets get the extra row")
    print("(4 rows / NTILE(3) = 2,1,1). Popular for ML feature engineering")
    print("(revenue deciles, risk tiers, rank-based normalization).\n")
    rows = conn.execute("""
        SELECT region, rep, amount,
               NTILE(3) OVER (PARTITION BY region ORDER BY amount DESC, rep) AS bucket
        FROM sales
        ORDER BY region, bucket, rep
    """).fetchall()
    print("  %-6s %-7s %7s   %7s" % ("region", "rep", "amount", "*ntile3"))
    for r in rows:
        print("  %-6s %-7s %7d   *%d" % (r[0], r[1], r[2], r[3]))
    print()
    east = [r for r in rows if r[0] == "East"]
    west = [r for r in rows if r[0] == "West"]
    print("  >>> 4 rows into NTILE(3) -> bucket sizes 2,1,1 (extra row to bucket 1).")
    print("        East: alice,bob -> bucket 1; carol -> 2; dave -> 3.\n")
    ne = ",".join(str(r[3]) for r in east)
    nw = ",".join(str(r[3]) for r in west)
    ok = (ne == "1,1,2,3" and nw == "1,1,2,3")
    gold.append(("ntile3_east", ne))
    gold.append(("ntile3_west", nw))
    print("[check] East 1,1,2,3 and West 1,1,2,3 (bucket sizes 2,1,1)? "
          + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - FIRST_VALUE / LAST_VALUE
# ---------------------------------------------------------------------------

def section_first_last(conn, gold):
    banner("SECTION 7: FIRST_VALUE() / LAST_VALUE() - edges of the frame")
    print("FIRST_VALUE = the value at the FIRST row of the ordered partition.")
    print("LAST_VALUE  = the value at the LAST row of the FRAME -- NOT the")
    print("partition! With the default frame (RANGE UNBOUNDED PRECEDING TO")
    print("CURRENT ROW) LAST_VALUE equals the current row at each step. To get")
    print("the partition's true last value you MUST widen the frame:")
    print("  ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING.\n")
    rows = conn.execute("""
        SELECT region, rep, amount,
               FIRST_VALUE(amount) OVER (PARTITION BY region
                   ORDER BY amount DESC, rep) AS fv,
               LAST_VALUE(amount)  OVER (PARTITION BY region
                   ORDER BY amount DESC, rep
                   ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS lv
        FROM sales
        ORDER BY region, amount DESC, rep
    """).fetchall()
    print("  %-6s %-7s %7s   %12s   %12s"
          % ("region", "rep", "amount", "*first_value", "*last_value"))
    for r in rows:
        print("  %-6s %-7s %7d   *%12d   *%12d" % (r[0], r[1], r[2], r[3], r[4]))
    print()
    print("  >>> FIRST_VALUE per region = the TOP amount (East 100, West 120).")
    print("      LAST_VALUE  per region = the BOTTOM amount (East 60, West 50).")
    print("  >>> The LAST_VALUE default-frame bug is the #1 interview gotcha:")
    print("      without the explicit UNBOUNDED FOLLOWING, it tracks the current")
    print("      row instead of the partition's last row.\n")
    east = [r for r in rows if r[0] == "East"]
    west = [r for r in rows if r[0] == "West"]
    fv_e, lv_e = east[0][3], east[0][4]
    fv_w, lv_w = west[0][3], west[0][4]
    ok = (fv_e == 100 and lv_e == 60 and fv_w == 120 and lv_w == 50
          and all(r[3] == fv_e for r in east) and all(r[4] == lv_e for r in east))
    gold.append(("first_value_east", str(fv_e)))
    gold.append(("last_value_east", str(lv_e)))
    gold.append(("first_value_west", str(fv_w)))
    gold.append(("last_value_west", str(lv_w)))
    print("[check] East first=100/last=60, West first=120/last=50 (constant per "
          "region)? " + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 8 - GOLD
# ---------------------------------------------------------------------------

def section_gold(gold):
    banner("SECTION 8: GOLD values (pinned for sql_window_functions.html)")
    for k, v in gold:
        print("  %-22s = %s" % (k, v))
    print()
    checks = True
    d = dict(gold)
    checks &= d["row_number_east"] == "1,2,3,4"
    checks &= d["rank_east"] == "1,1,3,4"
    checks &= d["dense_rank_east"] == "1,1,2,3"
    checks &= d["rank_west"] == "1,2,2,4"
    checks &= d["dense_rank_west"] == "1,2,2,3"
    checks &= d["lag_02"] == "100"
    checks &= d["lead_02"] == "120"
    checks &= d["dod_02"] == "50"
    checks &= d["running_total_07"] == "950"
    checks &= d["moving_avg_03"] == "123.33"
    checks &= d["moving_avg_05"] == "166.67"
    checks &= d["ntile3_east"] == "1,1,2,3"
    checks &= d["first_value_east"] == "100"
    checks &= d["last_value_east"] == "60"
    print("[check] GOLD reproduces ROW_NUMBER/RANK/DENSE_RANK/LAG/LEAD/"
          "SUM/AVG/NTILE/FIRST/LAST? " + ("OK" if checks else "FAIL"))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print("# sql_window_functions.py - SQL window functions on sqlite3")
    print("# Pure Python stdlib only. Numbers below feed SQL_WINDOW_FUNCTIONS.md")
    print("# and sql_window_functions.html (gold-checked).")
    print("# OVER() = PARTITION BY ... ORDER BY ... ROWS BETWEEN ...")

    conn = build_db()
    gold = []
    section_row_number(conn, gold)
    section_rank(conn, gold)
    section_lag_lead(conn, gold)
    section_running_total(conn, gold)
    section_moving_average(conn, gold)
    section_ntile(conn, gold)
    section_first_last(conn, gold)
    conn.close()

    section_gold(gold)

    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
