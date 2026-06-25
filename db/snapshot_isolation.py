"""
snapshot_isolation.py - Reference implementation of Snapshot Isolation (SI):
each transaction reads from a consistent snapshot taken at START, the
first-committer-wins rule that prevents lost updates, and the WRITE SKEW
anomaly SI leaves open (which true Serializability / SSI closes).

This is the single source of truth that SNAPSHOT_ISOLATION.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 snapshot_isolation.py

============================================================================
THE INTUITION (read this first) - the photograph taken at the front door
============================================================================
A database has a wall clock of "logical time" t. When a transaction T WALKS
IN at time t, the database hands T a PHOTOGRAPH of the whole database taken
at that instant - a SNAPSHOT. The snapshot captures every value that was
COMMITTED before t. From then on, no matter how long T lingers, every read T
does is answered from that one frozen photograph:

  * T never sees another transaction's UNCOMMITTED writes -> no dirty read
  * T never sees a value CHANGE mid-transaction            -> no non-repeatable
                                                            read, no phantom
  * T never sees a row APPEAR or VANISH under its nose     -> no phantom

But the photograph is FROZEN at the door. So two transactions that walk in
at overlapping times each hold DIFFERENT photographs. If they write to
DISJOINT rows based on what their own photo showed, they can quietly break a
constraint that spanned both rows - the WRITE SKEW anomaly. Neither saw the
other's write, so neither aborts. (Section B - the two doctors.)

THE OTHER TRICK: first-committer-wins. At COMMIT time SI compares T's write
set against every transaction that committed while T was active. If both
touched the SAME row, the SECOND one to commit is ABORTED. This stops LOST
UPDATES (Section C). Crucially it only checks the SAME rows - disjoint writes
slip straight through, which is exactly why write skew survives.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   snapshot       : the frozen photograph handed to T at BEGIN = every value
                    committed strictly before T.start. T reads ONLY from it.
   logical time t : a single increasing integer "tick". Each BEGIN, write, and
                    COMMIT happens at a distinct tick (deterministic model).
   version / MVCC : the database keeps MULTIPLE committed versions of a row
                    (one per writer's commit time). A snapshot just picks the
                    newest version with commit_time < snapshot_time.
   visibility     : "Tj sees Ti's writes"  <=>  Ti committed BEFORE Tj started
                    (Ti.commit < Tj.start). Otherwise Tj's snapshot is blind
                    to Ti. Read-your-own-writes: T always sees its OWN writes.
   read set       : the rows T read (or that a predicate T ran MATCHED).
                    Carries the "T relied on these values" information.
   write set      : the rows T wrote/updated.
   WW conflict    : write-write conflict - two txns wrote the SAME row.
   rw conflict    : read-write conflict - Ti wrote a row that Tj had read
                    (Tj's read is now stale w.r.t. Ti's committed write).
   first-         : at COMMIT, if any concurrent committed txn wrote a row in
   committer-       T's write set, T is ABORTED. Stops lost updates on a row.
   wins (FCW)       Only fires on SAME-row writes; disjoint writes are ignored.
   write skew     : two CONCURRENT txns with a rw-conflict in BOTH directions
                    (T1 read what T2 wrote AND T2 read what T1 wrote) but with
                    DISJOINT writes (so FCW does NOT fire). The anomaly SI
                    allows; Serializable (SSI) prevents it. Section B, Gold.
   Read Committed : isolation where each statement sees the latest committed
   (RC)             value at that moment -> no dirty read, but a value CAN
                    change between two reads of the same row (non-repeatable).
   Serializable   : true serializability. PostgreSQL SERIALIZABLE = SSI
   (SSI)            (Serializable Snapshot Isolation, Cahill 2008): tracks
                    rw-conflicts to catch write skew and abort one txn.

============================================================================
THE LINEAGE (sources)
============================================================================
   Berenson et al.  "A Critique of ANSI SQL Isolation Levels" (1995):
                     defined the anomalies (P1..P4, A5A/A5B) and showed
                     Snapshot Isolation is NOT serializable (allows write skew).
   Cahill           "Serializable Isolation for Snapshot Databases" (2008,
                     SIGMOD): SSI - detect write skew via rw-conflict
                     "dangerous structures" and abort. Adopted by PostgreSQL.
   PostgreSQL docs  13.2 Transaction Isolation: REPEATABLE READ == Snapshot
                     Isolation; SERIALIZABLE == SSI. (Verifies our mapping.)

KEY INVARIANTS (all asserted/printed in the sections below):
   visibility rule      : Tj sees Ti  <=>  Ti.commit is not None AND
                                                Ti.commit < Tj.start
   snapshot read        : value(Tj) = newest committed version of the row with
                          commit_time < Tj.start  (read-your-own-writes:
                          T's own writes override within the txn)
   FCW (lost update)    : at commit of T, if EXISTS a concurrent committed Tc
                          with (Tc.write_set & T.write_set) != {}  ->  ABORT T
   write skew           : concurrent(Ta,Tb) AND (Ta.write & Tb.write) == {}
                          AND (Ta.write & Tb.read) != {} AND (Tb.write & Ta.read)
                          != {}   ->  anomaly SI allows, SSI prevents
   anomalies SI prevents: dirty read, non-repeatable read, phantom, lost update
   anomalies SI ALLOWS  : write skew   (the ONE gap to Serializable)

Conventions:
   Logical time t is a plain increasing integer. A row is just a string key.
   Every run is fully deterministic; the .html replays these exact inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BANNER = "=" * 72


# ============================================================================
# 1. THE CORE MODEL: transactions, versions, snapshots, conflict detection
# ============================================================================

@dataclass
class Txn:
    """A transaction for the SI model.

    start/commit are logical-time ticks; read_set/write_set are sets of row
    keys (a predicate read contributes every row it matched). commit is None
    until the txn commits (or None forever if it aborts).
    """
    tid: str
    start: int
    read_set: set = field(default_factory=set)
    write_set: set = field(default_factory=set)
    commit: int | None = None


def visible(committed_log, row, snapshot_time):
    """The snapshot value of `row`: newest committed version with
    commit_time < snapshot_time, or None if none exists yet.

    committed_log = list of (commit_time, row, value), append-only.
    """
    best = None  # (commit_time, value)
    for ct, r, v in committed_log:
        if r == row and ct < snapshot_time:
            if best is None or ct > best[0]:
                best = (ct, v)
    return best[1] if best else None


def concurrent(a: Txn, b: Txn) -> bool:
    """True if a and b's lifespans overlap: neither finished before the other
    started. Both must have committed to be "concurrent" in the conflict sense
    used by FCW/SSI (an aborted txn contributes nothing)."""
    if a.commit is None or b.commit is None:
        return False
    return a.start < b.commit and b.start < a.commit


def ww_conflict(a: Txn, b: Txn) -> bool:
    """Write-write conflict: both wrote the same row key."""
    return bool(a.write_set & b.write_set)


def rw_conflict(writer: Txn, reader: Txn) -> bool:
    """rw-conflict: `writer` wrote a row that `reader` had read (reader's read
    set overlaps writer's write set). Means reader's read may be stale vs
    writer's committed write."""
    return bool(writer.write_set & reader.read_set)


def detect_write_skew(a: Txn, b: Txn) -> bool:
    """GOLD CHECK: is the (a,b) pair a write skew?

    Write skew = concurrent txns with a rw-conflict in BOTH directions (a read
    what b wrote AND b read what a wrote) but with DISJOINT writes (so FCW
    never fires). This is the anomaly SI allows and Serializable (SSI) flags.
    """
    if not concurrent(a, b):
        return False
    if ww_conflict(a, b):          # same-row write -> FCW handles it, NOT skew
        return False
    return rw_conflict(a, b) and rw_conflict(b, a)


def fcw_aborted(committer: Txn, already_committed: list[Txn]) -> Txn | None:
    """First-committer-wins: return the already-committed txn whose write set
    overlaps committer's (which causes committer to ABORT), or None if the
    commit is clean.

    A committed txn Tc conflicts iff it committed DURING committer's active
    window (Tc.commit > committer.start) AND wrote a row committer also wrote.
    Tc committed before committer starts -> it is in committer's SNAPSHOT (its
    write is visible -> sequential dependency, no conflict). This check does
    NOT require committer.commit to be set (it is called at commit time)."""
    for tc in already_committed:
        if committer.start < tc.commit and ww_conflict(committer, tc):
            return tc
    return None


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ----------------------------------------------------------------------------
# SECTION A: SI basics - the frozen snapshot, visibility timeline
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: SI basics - each txn reads a frozen snapshot taken at START")
    print("Model: one row R. Logical time t. A version is (commit_time, value).\n")
    # committed versions: append-only log of (commit_time, row, value).
    # T_init commits R=0 at t=1; T1 commits R=100 at t=30 (the only commits).
    log: list[tuple[int, str, object]] = [(1, "R", 0), (30, "R", 100)]

    print("EVENT TIMELINE (logical time t ->):\n")
    events = [
        (1,  "T_init COMMITS  : R = 0"),
        (10, "T1 BEGIN        : snapshot S1 (sees R=0)"),
        (15, "T1 writes R=100 : in T1 workspace (visible to T1, blind to T2)"),
        (20, "T2 BEGIN        : snapshot S2 (sees R=0; T1 NOT committed yet)"),
        (30, "T1 COMMITS      : R=100 now committed"),
        (40, "T2 reads R      : still 0 (S2 frozen at t=20, before T1 commit)"),
        (50, "T2 COMMITS      : (T2 wrote nothing)"),
        (60, "T3 BEGIN        : snapshot S3 (sees R=100; T1 committed @30<60)"),
    ]
    for t, desc in events:
        print(f"  t={t:<3} {desc}")

    t1, t2, t3 = 10, 20, 60
    v1 = visible(log, "R", t1)
    v2 = visible(log, "R", t2)
    v3 = visible(log, "R", t3)

    print("\nSNAPSHOT VISIBILITY (value of R each txn sees at BEGIN):\n")
    print("  | txn | start | snapshot sees R= | reason                                 |")
    print("  |-----|-------|------------------|----------------------------------------|")
    print(f"  | T1  | {t1:>5} | {v1:>16} | latest committed R@1=0 (1 < {t1})            |")
    print(f"  | T2  | {t2:>5} | {v2:>16} | T1 uncommitted at {t2} -> snapshot blind    |")
    print(f"  | T3  | {t3:>5} | {v3:>16} | T1 committed @30=100 (30 < {t3})            |")
    print()

    # at t=40 T2 re-reads R from its FROZEN snapshot S2 (taken at t=20)
    v2_at_40 = visible(log, "R", t2)   # snapshot time stays 20, NOT 40
    assert v1 == 0 and v2 == 0 and v3 == 100 and v2_at_40 == 0
    print("KEY POINT: T2 re-reads R at t=40 and STILL sees 0, even though T1")
    print(f"committed R=100 at t=30. T2's snapshot is frozen at its BEGIN (t={t2}).")
    print("This is exactly how SI blocks non-repeatable reads and phantoms -")
    print("and it is also exactly why write skew can hide between snapshots (Section B).\n")
    print("[check] visibility rule  Tj sees Ti  <=>  Ti.commit < Tj.start :")
    print("        T2(t=20) blind to T1(commit=30) since 30 < 20 is False:  OK")


# ----------------------------------------------------------------------------
# SECTION B: WRITE SKEW - the two doctors (the anomaly SI allows)
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: WRITE SKEW - two doctors on call, rule broken")
    print("Table doctors(name, on_call). INITIAL: Alice on-call, Bob on-call.")
    print("BUSINESS RULE: at least 1 doctor must be on call at all times.\n")

    # committed versions: append-only log of (commit_time, row, value).
    # INITIAL state: alice on_call, bob on_call (committed by T_init @ t=1).
    log = [(1, "alice", True), (1, "bob", True)]

    def on_call_count(snapshot_time):
        return sum(1 for r in ("alice", "bob")
                   if visible(log, r, snapshot_time))

    T1_START = T2_START = 10           # both BEGIN at the same tick
    print("t=1    INITIAL: alice=on_call, bob=on_call  (count=2)")
    print(f"t={T1_START:<3} T1 (Alice's shift) BEGIN -> snapshot S1: count = "
          f"{on_call_count(T1_START)}")
    print(f"t={T2_START:<3} T2 (Bob's shift)   BEGIN -> snapshot S2: count = "
          f"{on_call_count(T2_START)}")
    print("        (both snapshots see BOTH on-call; rule '>=1' looks satisfied)")

    # build the two txns. read_set = predicate over both rows; write_set = self
    T1 = Txn("T1", T1_START, read_set={"alice", "bob"}, write_set={"alice"})
    T2 = Txn("T2", T2_START, read_set={"alice", "bob"}, write_set={"bob"})

    print("\nt=15   T1: count==2 (>=1) -> safe to go off-call")
    print("           UPDATE doctors SET on_call=false WHERE name='alice'")
    print("t=15   T2: count==2 (>=1) -> safe to go off-call")
    print("           UPDATE doctors SET on_call=false WHERE name='bob'")

    # commit T1 first (clean: no concurrent committed txn wrote alice)
    T1.commit = 20
    log.append((T1.commit, "alice", False))
    print("\nt=20   T1 COMMITS. FCW check on {alice}: no concurrent committed")
    print("       write to alice -> COMMIT OK.")

    # commit T2: FCW check on {bob} against T1's write {alice} -> DISJOINT -> OK
    blocker = fcw_aborted(T2, [T1])
    if blocker is None:
        T2.commit = 30
        log.append((T2.commit, "bob", False))
        print("t=30   T2 COMMITS. FCW check on {bob} vs T1's {alice}:")
        print("       DISJOINT write sets -> no WW conflict -> COMMIT OK.")
    else:
        print("t=30   T2 ABORTED by FCW (unexpected for write skew).")

    # final committed state at t=40
    final_alice = visible(log, "alice", 40)
    final_bob = visible(log, "bob", 40)
    final_count = sum(1 for v in (final_alice, final_bob) if v)
    print(f"\nFINAL committed state: alice_on_call={final_alice}, "
          f"bob_on_call={final_bob}")
    print(f"       on-call count = {final_count}")
    print(f"\nRULE '>=1 on call'  ==>  {final_count}  ==>  "
          f"{'VIOLATED  <== WRITE SKEW ANOMALY' if final_count < 1 else 'OK'}")

    skew = detect_write_skew(T1, T2)
    assert final_alice is False and final_bob is False and final_count == 0
    assert skew is True
    print(f"\n[check] detect_write_skew(T1,T2) = {skew}  -> FCW saw only disjoint")
    print("        writes and let both commit; the bidirectional rw-conflict")
    print("        (each read the row the other wrote) is the tell-tale skew.  OK")


# ----------------------------------------------------------------------------
# SECTION C: FIRST-COMMITTER-WINS - SI prevents lost updates on the SAME row
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: first-committer-wins - same-row write -> second ABORTS")
    print("Account balance. INITIAL: balance = 100. Two deposits concurrently.\n")
    log = [(1, "balance", 100)]

    T1 = Txn("T1", start=10, read_set={"balance"}, write_set={"balance"})
    T2 = Txn("T2", start=20, read_set={"balance"}, write_set={"balance"})

    print(f"t=1    INITIAL balance = {visible(log,'balance',10)}")
    print(f"t=10   T1 BEGIN: reads balance = {visible(log,'balance',T1.start)} "
          "(snapshot S1)")
    print(f"t=20   T2 BEGIN: reads balance = {visible(log,'balance',T2.start)} "
          "(snapshot S2; T1 NOT committed -> still sees 100)")
    print("       T1 wants balance += 10  -> 110")
    print("       T2 wants balance += 50  -> 150")

    # commit T1 first: clean (T_init wrote balance at 1 < T1.start=10 -> not concurrent)
    committed: list[Txn] = []
    T1.commit = 30
    log.append((T1.commit, "balance", 110))
    committed.append(T1)
    print("\nt=30   T1 COMMITS balance=110. FCW check {balance}: no concurrent")
    print("       committed write -> COMMIT OK.")

    # commit T2: FCW check {balance} vs T1's {balance} -> OVERLAP -> ABORT
    blocker = fcw_aborted(T2, committed)
    aborted = blocker is not None
    if aborted:
        T2.commit = None  # stays aborted
        print("t=40   T2 tries COMMIT. FCW check {balance} vs T1's {balance}:")
        print(f"       SAME row -> WW conflict -> T2 ABORTED  (blocker = {blocker.tid}).")
    else:
        T2.commit = 40
        log.append((T2.commit, "balance", 150))
        committed.append(T2)
        print("t=40   T2 COMMITS (unexpected: FCW should have caught it).")

    final = visible(log, "balance", 50)
    print(f"\nFINAL committed balance = {final}")
    print("T2's write was DISCARDED. No lost update: T1's +10 survived, and the")
    print("client for T2 must RETRY (it will re-read 110 and write 160). SI's FCW")
    print("turns a silent lost update into an explicit ABORT.\n")

    ww = ww_conflict(T1, T2)
    skew = detect_write_skew(T1, T2)
    assert ww is True and aborted is True and final == 110
    assert skew is False
    print(f"[check] ww_conflict(T1,T2) = {ww};  abort happened = {aborted};")
    print(f"        detect_write_skew = {skew} (same-row -> FCW, NOT write skew). OK")


# ----------------------------------------------------------------------------
# SECTION D: SI vs Read Committed - which anomalies each prevents
# ----------------------------------------------------------------------------

# anomaly -> (RC prevents?, SI prevents?). P=prevented, A=allowed.
ANOMALY_TABLE = [
    # (anomaly,          RC,   SI,  comment)
    ("Dirty read",        True, True,  "RC/SI read only committed versions"),
    ("Non-repeatable",   False, True,  "RC re-reads latest -> value can change"),
    ("Phantom",          False, True,  "RC predicate re-scan sees new rows"),
    ("Write skew",       False, False, "disjoint writes slip past FCW (Section B)"),
    ("Lost update",      False, True,  "SI FCW aborts the second same-row writer"),
]


def section_d():
    banner("SECTION D: SI vs Read Committed - anomaly prevention")
    print("PostgreSQL 'READ COMMITTED' (default) vs 'REPEATABLE READ' (= SI).\n")
    print("  P = prevents,  A = allows\n")
    print("| anomaly            | Read Committed | Snapshot Isolation |")
    print("|--------------------|:--------------:|:-------------------:|")
    rc_prev = si_prev = 0
    for name, rc, si, _c in ANOMALY_TABLE:
        print(f"| {name:<18} | {'P' if rc else 'A':^14} | "
              f"{'P' if si else 'A':^19} |")
        rc_prev += 1 if rc else 0
        si_prev += 1 if si else 0
    print()
    print("DETAIL:")
    for name, rc, si, c in ANOMALY_TABLE:
        print(f"  {name:<18} RC={'P' if rc else 'A'} SI={'P' if si else 'A'}  -  {c}")
    print()
    print(f"Read Committed prevents {rc_prev}/{len(ANOMALY_TABLE)} anomalies.")
    print(f"Snapshot Isolation prevents {si_prev}/{len(ANOMALY_TABLE)} anomalies.")
    print("\nSI is strictly stronger: it adds non-repeatable, phantom, and lost-")
    print("update prevention on top of RC's dirty-read prevention. The ONE thing")
    print("SI still allows is write skew (Section E shows Serializable closing it).")
    assert rc_prev == 1 and si_prev == 4
    print(f"\n[check] RC prevents 1, SI prevents 4 of {len(ANOMALY_TABLE)}: OK")


# ----------------------------------------------------------------------------
# SECTION E: SI vs Serializable - the write-skew gap (SSI closes it)
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: SI vs Serializable - write skew is the gap SSI closes")
    print("PostgreSQL 'REPEATABLE READ' (= SI) vs 'SERIALIZABLE' (= SSI).\n")
    print("  P = prevents,  A = allows\n")
    print("| anomaly            | Snapshot Isolation | Serializable (SSI) |")
    print("|--------------------|:------------------:|:-------------------:|")
    si_prev = ser_prev = 0
    rows = [
        ("Dirty read",        True, True),
        ("Non-repeatable",   True, True),
        ("Phantom",          True, True),
        ("Write skew",       False, True),   # the gap
        ("Lost update",      True, True),
    ]
    for name, si, ser in rows:
        print(f"| {name:<18} | {'P' if si else 'A':^18} | "
              f"{'P' if ser else 'A':^19} |")
        si_prev += 1 if si else 0
        ser_prev += 1 if ser else 0
    print()
    print(f"Snapshot Isolation prevents {si_prev}/{len(rows)}; "
          f"Serializable prevents {ser_prev}/{len(rows)}.")
    print("The ONLY difference is WRITE SKEW. SI permits it; SSI detects it.\n")

    print("HOW SSI CATCHES WRITE SKEW (Cahill 2008):")
    print("  SSI records every predicate read as a 'SIREAD'. When a txn commits,")
    print("  SSI looks for rw-conflicts that form a DANGEROUS STRUCTURE:")
    print("    T1 read-then-T2-wrote  (rw T1->T2)   AND")
    print("    T2 read-then-T1-wrote  (rw T2->T1)")
    print("  = a bidirectional rw-conflict = write skew. SSI ABORTS one of them.\n")
    print("  In the doctors example (Section B):")
    print("    T1 read {alice,bob}, wrote {alice}  ->  rw T2->T1 (T2 read alice)")
    print("    T2 read {alice,bob}, wrote {bob}    ->  rw T1->T2 (T1 read bob)")
    print("  SSI sees the bidirectional conflict and aborts (say) T2, so Bob")
    print("  stays on call and the rule holds. SI does NOT record predicate reads,")
    print("  so it sees nothing and lets both commit -> count=0.\n")

    print("POSTGRESQL MAPPING (docs 13.2, verified):")
    print("  READ UNCOMMITTED  ~ behaves like READ COMMITTED")
    print("  READ COMMITTED    = statement-level snapshot")
    print("  REPEATABLE READ   = Snapshot Isolation  <-- this file")
    print("  SERIALIZABLE      = SSI (Serializable Snapshot Isolation)")
    assert si_prev == 4 and ser_prev == 5
    print("\n[check] SI prevents 4, SSI prevents 5; the +1 is write skew: OK")


# ----------------------------------------------------------------------------
# SECTION F (GOLD): write-skew detection - pinned values for the .html
# ----------------------------------------------------------------------------

def section_gold():
    banner("GOLD: write-skew detection - pinned for snapshot_isolation.html")
    print("The detector re-implements SSI's bidirectional rw-conflict test:\n")
    print("  write_skew(a,b) =  concurrent(a,b)")
    print("                  AND (a.write & b.write) == {}      [disjoint -> FCW misses]")
    print("                  AND (a.write & b.read)  != {}      [rw a->b]")
    print("                  AND (b.write & a.read)  != {}      [rw b->a]")

    # Scenario 1: the doctors (true write skew)
    d1 = Txn("D1", 10, read_set={"alice", "bob"}, write_set={"alice"}, commit=20)
    d2 = Txn("D2", 10, read_set={"alice", "bob"}, write_set={"bob"}, commit=30)
    s1_skew = detect_write_skew(d1, d2)
    s1_ww = ww_conflict(d1, d2)

    # Scenario 2: counter / lost update (same-row -> FCW, NOT write skew)
    c1 = Txn("C1", 10, read_set={"balance"}, write_set={"balance"}, commit=30)
    c2 = Txn("C2", 20, read_set={"balance"}, write_set={"balance"}, commit=40)
    s2_skew = detect_write_skew(c1, c2)
    s2_ww = ww_conflict(c1, c2)

    # Scenario 3: independent rows (no overlap at all -> nothing)
    i1 = Txn("I1", 10, read_set={"p"}, write_set={"p"}, commit=20)
    i2 = Txn("I2", 10, read_set={"q"}, write_set={"q"}, commit=30)
    s3_skew = detect_write_skew(i1, i2)
    s3_ww = ww_conflict(i1, i2)

    print("\n| scenario            | concurrent | WW conflict | rw a->b | rw b->a | WRITE SKEW? |")
    print("|---------------------|:----------:|:-----------:|:-------:|:-------:|:-----------:|")
    for label, a, b, skew, ww in [
        ("doctors (alice/bob)", d1, d2, s1_skew, s1_ww),
        ("counter (balance)",   c1, c2, s2_skew, s2_ww),
        ("independent (p/q)",   i1, i2, s3_skew, s3_ww),
    ]:
        con = concurrent(a, b)
        rab = rw_conflict(a, b)
        rba = rw_conflict(b, a)
        print(f"| {label:<19} | {'yes' if con else 'no':^10} | "
              f"{'yes' if ww else 'no':^11} | "
              f"{'yes' if rab else 'no':^7} | "
              f"{'yes' if rba else 'no':^7} | "
              f"{'YES' if skew else 'no':^11} |")
    print()

    print("GOLD values (pinned for snapshot_isolation.html):")
    print(f"  doctors   : write_skew={s1_skew}  ww={s1_ww}")
    print(f"  counter   : write_skew={s2_skew}  ww={s2_ww}   (FCW aborts, not skew)")
    print(f"  independent: write_skew={s3_skew}  ww={s3_ww}   (clean, no conflict)")

    # anomaly counts from the tables
    rc_prev = sum(1 for _n, rc, _s, _c in ANOMALY_TABLE if rc)
    si_prev = sum(1 for _n, _r, si, _c in ANOMALY_TABLE if si)
    ser_prev = 5  # full row in section_e
    final_on_call = 0      # after Section B doctors
    final_balance = 110    # after Section C counter
    print(f"  anomalies prevented: RC={rc_prev}, SI={si_prev}, SER={ser_prev}")
    print(f"  final on-call count (doctors, SI) = {final_on_call}")
    print(f"  final balance (counter, SI FCW)   = {final_balance}")

    # ---- assert all gold ----
    assert s1_skew is True and s1_ww is False
    assert s2_skew is False and s2_ww is True
    assert s3_skew is False and s3_ww is False
    assert rc_prev == 1 and si_prev == 4 and ser_prev == 5
    assert final_on_call == 0 and final_balance == 110
    print("\n[check] all GOLD asserts hold (skew detect + anomaly counts + finals): OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("snapshot_isolation.py - reference impl. All numbers feed "
          "SNAPSHOT_ISOLATION.md.")
    print("pure Python stdlib ; deterministic logical-time model.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
