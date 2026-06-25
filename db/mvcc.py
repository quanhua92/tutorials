"""
mvcc.py - Reference implementation of Multi-Version Concurrency Control
(MVCC), the mechanism PostgreSQL (and most modern databases) use so that
    readers NEVER block writers, and writers NEVER block readers.

This is the single source of truth that MVCC.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 mvcc.py

============================================================================
THE INTUITION (read this first) - the row that keeps its old drafts
============================================================================
Imagine a row in a table is a stack of DRAFTS, not an overwritten value. When
a transaction UPDATES the row, the database does NOT erase the old value in
place. Instead it:

  1. writes a NEW draft (a new "tuple version") with the new value, and
  2. stamps the OLD draft with "superseded by transaction X" (sets its t_xmax),
     but LEAVES the old draft sitting on the page.

Each draft carries two transaction IDs:
  t_xmin : the transaction that CREATED this draft (the INSERT / new-UPDATE).
  t_xmax : the transaction that SUPERSEDED this draft (the DELETE / next
           UPDATE). 0 means "still the current draft".

A transaction that wants to read the row walks the stack of drafts and picks
the ONE whose xmin/xmax match its own snapshot. Two transactions running at
the same time simply pick DIFFERENT drafts -> they never fight over the same
bytes. That is why readers never block writers and writers never block readers:
they are literally reading different drafts.

The cost: old drafts (DEAD TUPLES) pile up until VACUUM sweeps them away; and
the 32-bit transaction-ID counter can WRAP AROUND, so old drafts must be FROZEN
before their xmin gets reused.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   tuple / version  : one draft of a row. Identified by (page, offset) = TID.
                      Carries t_xmin, t_xmax, and the row data. 🔗 See
                      TUPLE_FORMAT.md / tuple_format.py for the on-disk bytes.
   t_xmin           : the transaction id (xid) that INSERTED this version.
   t_xmax           : the xid that DELETED/UPDATED this version away.
                      xmax == 0   -> version is still ALIVE (current).
                      xmax set    -> version has been superseded (a later txn
                                     replaced it); the version is dead once that
                                     later txn is visible to everyone.
   xid              : transaction id. A 32-bit counter assigned in start order.
   snapshot         : a transaction's frozen answer to "which transactions
                      count as committed for ME?". Captured once (REPEATABLE
                      READ) or per statement (READ COMMITTED).
   xmin (snapshot)  : the LOWEST in-progress xid at snapshot time. Every
                      xid < xmin is FINALIZED (committed or aborted).
   xmax (snapshot)  : the NEXT xid to be assigned. Every xid >= xmax has NOT
                      STARTED -> invisible to this snapshot.
   xip              : the in-progress list: xids in [xmin, xmax) that were
                      still RUNNING at snapshot time -> invisible.
   dead tuple       : a version that NO live snapshot can ever read again
                      (its xmax is committed-visible to all). VACUUM reclaims it.
   VACUUM           : the sweeper. Removes dead tuples, reclaims space, sets the
                      visibility-map bit, and FROZENS old xids. 🔗 See
                      FREE_SPACE_MAP.md for the sibling per-page bitmap.
   frozen xid       : a magic xmin value (FrozenTransactionId == 2) meaning
                      "this insert is permanently committed, forever visible".
                      VACUUM writes it to dodge XID wraparound.

============================================================================
THE LINEAGE (sources)
============================================================================
   MVCC (concept)     Bernstein & Goodman, "Concurrency Control in Distributed
                      Database Systems", ACM Comput. Surv. 1981/1983; and
                      Berenson et al., "A Critique of ANSI SQL Isolation
                      Levels", SIGMOD 1995 (the snapshot-isolation definitions).
   PostgreSQL MVCC    The HeapTupleSatisfiesMVCC rules in
                      src/backend/utils/time/heapam_visibility.c; the snapshot
                      struct in utils/snapshot.h (xmin/xmax/xip fields); the
                      commit log (pg_xact). PostgreSQL has been MVCC since v6.5
                      (1999) - "no overwrites, always append a new version".
   Oracle             MVCC via rollback segments since v4 (1984) - the original
                      commercial MVCC. "Statement-level / transaction-level
                      read consistency".
   Snapshot Isolation  Berenson 1995 formalized what Postgres calls REPEATABLE
                      READ: a transaction sees a consistent snapshot taken at
                      its first read, and writes conflict only on write-skew.
   VACUUM / wraparound PostgreSQL autovacuum, vacuum_freeze_min_age (default
                      50M), autovacuum_freeze_max_age (default 200M); the 32-bit
                      xid + epoch, and the Forced anti-wraparound vacuum.

KEY RULES (all asserted/printed in the sections below):
   committed_visible(xid, snap)  =  (xid < snap.xmax) and (xid not in xip)
                                    and (xid in committed)   [or xid == FROZEN]
   visible(version, snap)        =  committed_visible(xmin)
                                    and (xmax == 0 or not committed_visible(xmax))
   visibility(chain, snap)       =  the one version in the chain that satisfies
                                    `visible` (exactly one is visible)
   READ COMMITTED  : snapshot re-taken on EVERY statement  -> non-repeatable reads
   REPEATABLE READ : snapshot taken ONCE (first stmt)       -> repeatable reads
   dead(version)   =  not visible under ANY live snapshot   -> VACUUM-removable
   xid_distance(curr, old) = (curr - old) mod 2^32          ; unsafe once >= 2^31
   freeze threshold: vacuum_freeze_min_age = 50,000,000 (opportunistic)
                     autovacuum_freeze_max_age = 200,000,000 (FORCED)
                     hard cliff at 2^31 (signed comparison flips)

Conventions:
   XIDs are small deterministic integers (100, 200, 300, 500, 501, ...).
   The version chain is always listed NEWEST -> OLDEST.
   `committed` is the set of xids that have committed (the commit log).
"""

from __future__ import annotations

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# Constants (PostgreSQL-flavoured, deterministic)
# ----------------------------------------------------------------------------
XID_MOD = 1 << 32                 # the 32-bit transaction-ID space
XID_MAX = (1 << 32) - 1
XID_HALF = 1 << 31                # signed-comparison flip point
FROZEN_XID = 2                    # PostgreSQL FrozenTransactionId: forever-committed
VACUUM_FREEZE_MIN_AGE = 50_000_000      # default opportunistic freeze age
AUTOVACUUM_FREEZE_MAX_AGE = 200_000_000  # default FORCED anti-wraparound age


# ============================================================================
# 1. THE DATA MODEL + THE VISIBILITY ENGINE (this is the code MVCC.md walks)
# ============================================================================
class Version:
    """One draft of a row in the version chain.

    xmin = xid that created this version ; xmax = xid that superseded it
    (0 = still alive). payload = the user-visible row data (e.g. balance).
    """
    __slots__ = ("tag", "xmin", "xmax", "payload")

    def __init__(self, tag, xmin, xmax=0, payload=None):
        self.tag = tag
        self.xmin = xmin
        self.xmax = xmax
        self.payload = payload

    def __repr__(self):
        p = "" if self.payload is None else f", payload={self.payload!r}"
        return (f"Version(tag={self.tag!r}, xmin={self.xmin}, "
                f"xmax={self.xmax}{p})")


class Snapshot:
    """A transaction snapshot (PostgreSQL SnapshotData, simplified).

    xmin : lowest in-progress xid. Every xid < xmin is FINALIZED.
    xmax : next xid to be assigned. Every xid >= xmax has NOT STARTED.
    xip  : xids in [xmin, xmax) still IN PROGRESS at snapshot time.
    """
    __slots__ = ("xmin", "xmax", "xip")

    def __init__(self, xmin, xmax, xip=()):
        self.xmin = xmin
        self.xmax = xmax
        self.xip = set(xip)

    def __repr__(self):
        return (f"Snapshot(xmin={self.xmin}, xmax={self.xmax}, "
                f"xip={sorted(self.xip)})")


def committed_visible(xid, snap, committed):
    """Is transaction `xid` BOTH committed AND visible under `snap`?

    This is the heart of MVCC. A transaction's effects are seen by a snapshot
    iff the transaction had COMMITTED BEFORE the snapshot was taken:
      - it must have started   (xid < snap.xmax), and
      - it must not still be running at snapshot time (xid not in snap.xip), and
      - it must have committed (xid in `committed`; else aborted -> invisible).
    A FROZEN xid is always visible (forever-committed marker).
    """
    if xid == FROZEN_XID:
        return True
    if xid >= snap.xmax:
        return False
    if xid in snap.xip:
        return False
    return xid in committed


def visible_to_snapshot(ver, snap, committed):
    """HeapTupleSatisfiesMVCC (simplified). A version is VISIBLE iff its
    INSERT is visible AND its DELETE is NOT (yet) visible."""
    if not committed_visible(ver.xmin, snap, committed):
        return False                       # inserter invisible -> version absent
    if ver.xmax == 0:
        return True                        # never superseded -> alive
    if committed_visible(ver.xmax, snap, committed):
        return False                       # deleter visible -> version gone
    return True                            # deleter not yet visible -> alive


def visibility(chain, snap, committed):
    """Walk the version chain (NEWEST first) and return the one visible
    version, or None. Exactly one version in a well-formed chain is visible."""
    for ver in chain:
        if visible_to_snapshot(ver, snap, committed):
            return ver
    return None


def reason_visible(xid, snap, committed):
    """Human-readable reason for committed_visible(xid) (used in tables)."""
    if xid == FROZEN_XID:
        return "frozen=forever"
    if xid >= snap.xmax:
        return ">= xmax (not started)"
    if xid in snap.xip:
        return "in xip (in progress)"
    if xid in committed:
        return "committed & < xmax"
    return "aborted (< xmax, not in commit log)"


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 2. THE SECTIONS  (each prints a banner + table that MVCC.md pastes verbatim)
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: tuple visibility - the xmin/xmax version chain
# ----------------------------------------------------------------------------
def section_a():
    banner("SECTION A: tuple visibility - the xmin/xmax version chain")
    print("Every row version carries two transaction IDs:\n")
    print("  t_xmin : the xid that INSERTED this version (created it)")
    print("  t_xmax : the xid that SUPERSEDED this version (0 = still alive)\n")
    print("A transaction sees a version iff:")
    print("   (1) its inserter (xmin) committed and is visible to the snapshot, AND")
    print("   (2) its superseder (xmax) is 0, aborted, or NOT YET committed-visible.\n")
    print("Readers never block writers and writers never block readers: each")
    print("transaction simply picks the version whose xmin/xmax match its snapshot.\n")

    # Row 1's history:  T100 INSERT ; T200 UPDATE ; T300 UPDATE.
    # Final chain (newest -> oldest):
    chain = [
        Version("alice-v3", xmin=300, xmax=0, payload="v3"),
        Version("alice-v2", xmin=200, xmax=300, payload="v2"),
        Version("alice-v1", xmin=100, xmax=200, payload="v1"),
    ]
    committed = {100, 200, 300}            # all three eventually commit
    print("Row 1's version chain (newest -> oldest):")
    for v in chain:
        print(f"  {v}")
    print()

    # Query running as txid=250, BETWEEN T200 and T300 in the timeline.
    snap250 = Snapshot(xmin=250, xmax=251, xip=[])
    print("Query transaction = T250 (runs between T200 and T300).")
    print(f"  snapshot@250 = {snap250}")
    print("  -> every xid < 250 is finalized; 250 is the querier (sees its own")
    print("     writes specially); xids >= 251 (i.e. 300) have NOT STARTED yet,")
    print("     so T300's UPDATE is invisible to T250.\n")

    print("Visibility check per version:")
    print("  | version   | xmin | xmin visible? why            | "
          "xmax | xmax visible? why            | result   |")
    print("  |-----------|------|------------------------------|"
          "------|------------------------------|----------|")
    for v in chain:
        iv = committed_visible(v.xmin, snap250, committed)
        why_i = reason_visible(v.xmin, snap250, committed)
        if v.xmax == 0:
            xv = False
            why_d = "0 = never superseded"
        else:
            xv = committed_visible(v.xmax, snap250, committed)
            why_d = reason_visible(v.xmax, snap250, committed)
        vis = visible_to_snapshot(v, snap250, committed)
        iwhy = ("YES " if iv else "no  ") + why_i
        dwhy = (("YES " if xv else "no  ") + why_d) if v.xmax else why_d
        print(f"  | {v.tag:<9} | {v.xmin:<4} | {iwhy:<28} | "
              f"{v.xmax:<4} | {dwhy:<28} | "
              f"{'VISIBLE' if vis else 'hidden':<8} |")
    print()

    chosen = visibility(chain, snap250, committed)
    print(f"For txid=250 the visible version is: {chosen}")
    assert chosen is not None
    assert chosen.tag == "alice-v2" and chosen.xmin == 200 and chosen.xmax == 300
    print("\nWhy v2:  inserter T200 is committed and visible (200 < xmax=251);")
    print("         superseder T300 has NOT STARTED (300 >= xmax=251) so xmax is")
    print("         invisible -> the delete does not count -> v2 is alive.")
    print("[check] visibility(txid=250) -> v2 (alice-v2, xmin=200): OK")


# ----------------------------------------------------------------------------
# SECTION B: the snapshot - xmin horizon, xmax horizon, xip
# ----------------------------------------------------------------------------
def section_b():
    banner("SECTION B: the snapshot - xmin horizon, xmax horizon, xip")
    print("A snapshot is a transaction's FROZEN answer to 'which transactions")
    print("count as committed for me?'. Three fields carve the xid number line:\n")
    print("  xmin : lowest in-progress xid. Every xid < xmin is FINALIZED")
    print("         (committed or aborted) -> its fate is decided.\n")
    print("  xmax : next xid to be assigned. Every xid >= xmax has NOT STARTED")
    print("         -> its effects are invisible ('not yet').\n")
    print("  xip  : the in-progress list. xids in [xmin, xmax) still RUNNING at")
    print("         snapshot time -> invisible ('still working').\n")
    print("So 'committed and visible' = started (xid < xmax) AND not running")
    print("(not in xip) AND committed (in the commit log).\n")

    committed = {100, 150, 200, 300}       # 250 & 350 are in xip -> NOT committed
    snap = Snapshot(xmin=200, xmax=400, xip=[250, 350])
    print(f"Worked snapshot  S = {snap}")
    print(f"commit log      : committed = {sorted(committed)}")
    print("                  (250, 350 are in xip -> their writes are invisible)\n")
    print("Number line:")
    print("   ... 100  150  [200=xmin ... 250,350 in xip ... 400=xmax]  500 ...\n")

    probes = [
        Version("p1", 100, 0),     # old insert, alive -> VISIBLE
        Version("p2", 250, 0),     # inserted by in-progress 250 -> hidden
        Version("p3", 350, 0),     # inserted by in-progress 350 -> hidden
        Version("p4", 500, 0),     # not-started insert -> hidden
        Version("p5", 150, 250),   # old insert, deleted by in-progress 250 -> VISIBLE
        Version("p6", 200, 300),   # old insert, deleted by committed 300 -> hidden
    ]
    print("Probe versions and decide visibility:\n")
    print("  | tuple | xmin | xmin visible? why            | "
          "xmax | xmax visible? why            | visible? |")
    print("  |-------|------|------------------------------|"
          "------|------------------------------|----------|")
    for v in probes:
        iv = committed_visible(v.xmin, snap, committed)
        why_i = reason_visible(v.xmin, snap, committed)
        if v.xmax == 0:
            xv = False
            why_d = "0 = never superseded"
        else:
            xv = committed_visible(v.xmax, snap, committed)
            why_d = reason_visible(v.xmax, snap, committed)
        vis = visible_to_snapshot(v, snap, committed)
        iwhy = ("YES " if iv else "no  ") + why_i
        dwhy = (("YES " if xv else "no  ") + why_d) if v.xmax else why_d
        print(f"  | {v.tag:<5} | {v.xmin:<4} | {iwhy:<28} | "
              f"{v.xmax:<4} | {dwhy:<28} | "
              f"{'YES' if vis else 'no':<8} |")
    print()

    vis_count = sum(1 for v in probes if visible_to_snapshot(v, snap, committed))
    vis_tags = [v.tag for v in probes if visible_to_snapshot(v, snap, committed)]
    print(f"-> {vis_count} of {len(probes)} probes visible: {vis_tags}")
    print("   p1 : plain live old row.")
    print("   p5 : inserted long ago, but its DELETER (250) is still in progress,")
    print("        so the delete does not count yet -> the row is still visible.")
    assert vis_count == 2 and set(vis_tags) == {"p1", "p5"}
    print("\n[check] exactly 2 visible (p1, p5): OK")


# ----------------------------------------------------------------------------
# SECTION C: READ COMMITTED - non-repeatable read (fresh snapshot per stmt)
# ----------------------------------------------------------------------------
def section_c():
    banner("SECTION C: READ COMMITTED - non-repeatable read (snapshot per stmt)")
    print("Isolation level READ COMMITTED takes a FRESH snapshot for EVERY")
    print("statement. A re-read inside the SAME transaction can therefore see a")
    print("DIFFERENT value if another transaction committed in between. That is a")
    print("non-repeatable read - allowed under READ COMMITTED.\n")
    print("Setup: accounts(id=1, balance). Row 1 starts as v1(balance=100),")
    print("inserted long ago by T100 (committed).\n")

    # ---- statement 1 (T1, before T2 touches the row) ----
    committed_1 = {100}
    S1 = Snapshot(xmin=500, xmax=501, xip=[])   # t1: only 100 committed; T500 querier
    chain_1 = [Version("v1", 100, 0, payload=100)]
    r1 = visibility(chain_1, S1, committed_1)

    # ---- T2 updates + commits between the two reads ----
    committed_2 = {100, 501}                    # t3: T501 committed
    S2 = Snapshot(xmin=500, xmax=502, xip=[])   # t4: fresh snapshot; 501 now visible
    chain_2 = [Version("v2", 501, 0, payload=200),
               Version("v1", 100, 501, payload=100)]
    r2 = visibility(chain_2, S2, committed_2)

    print("Timeline:")
    print("  t0  T500 BEGIN")
    print("  t1  T500 SELECT balance WHERE id=1   (fresh snapshot S1)")
    print("  t2  T501 BEGIN")
    print("  t3  T501 UPDATE balance=200 WHERE id=1;  COMMIT  (writes v2,")
    print("       stamps v1.xmax=501)")
    print("  t4  T500 SELECT balance WHERE id=1   (fresh snapshot S2)\n")

    print(f"  S1 = {S1}    (at t1 only 100 committed; 501 not started)")
    print(f"  S2 = {S2}    (at t4 501 has started AND committed -> visible)\n")
    print(f"  read @ t1 : visibility(chain, S1) -> {r1.tag}, balance = {r1.payload}")
    print(f"  read @ t4 : visibility(chain, S2) -> {r2.tag}, balance = {r2.payload}\n")
    print(f"T500 read balance=100 at t1, then balance={r2.payload} at t4 -> a")
    print("NON-REPEATABLE READ. Same transaction, same row, two different values,")
    print("because READ COMMITTED re-took the snapshot and T501 slipped in.\n")
    assert r1.payload == 100 and r2.payload == 200 and r2.tag == "v2"
    print("[check] RC: first read 100, second read 200 (non-repeatable): OK")
    return r1, r2


# ----------------------------------------------------------------------------
# SECTION D: REPEATABLE READ - snapshot isolation (one snapshot, pinned)
# ----------------------------------------------------------------------------
def section_d(rc_r1, rc_r2):
    banner("SECTION D: REPEATABLE READ - snapshot isolation (snapshot pinned)")
    print("Isolation level REPEATABLE READ takes ONE snapshot at the transaction's")
    print("first statement and REUSES it for every later statement. The snapshot")
    print("is PINNED: transactions that commit later are invisible to it. So a")
    print("re-read always returns the same value -> reads are repeatable.\n")
    print("SAME timeline as Section C; the only difference is the snapshot rule.\n")

    # ---- T1 takes ONE snapshot at its first statement (t1) and keeps it ----
    committed_1 = {100}
    S = Snapshot(xmin=500, xmax=501, xip=[])    # the PINNED snapshot, taken at t1
    chain_1 = [Version("v1", 100, 0, payload=100)]
    r1 = visibility(chain_1, S, committed_1)

    # ---- T2 updates + commits; T1 re-reads but REUSES the pinned snapshot S ----
    committed_2 = {100, 501}
    chain_2 = [Version("v2", 501, 0, payload=200),
               Version("v1", 100, 501, payload=100)]
    r2 = visibility(chain_2, S, committed_2)    # NOTE: same S, not a fresh S2

    print("Timeline (identical to Section C):")
    print("  t0  T500 BEGIN")
    print("  t1  T500 SELECT balance WHERE id=1   (takes snapshot S, KEEPS it)")
    print("  t2  T501 BEGIN")
    print("  t3  T501 UPDATE balance=200 WHERE id=1;  COMMIT")
    print("  t4  T500 SELECT balance WHERE id=1   (REUSES snapshot S)\n")
    print(f"  pinned S = {S}   (captured at t1; xmax=501 -> 501 is 'not started')")
    print("  under S, committed_visible(501) = (501 < 501)? -> False\n")
    print(f"  read @ t1 : visibility(chain, S) -> {r1.tag}, balance = {r1.payload}")
    print(f"  read @ t4 : visibility(chain, S) -> {r2.tag}, balance = {r2.payload}\n")
    print("At t4 the chain also contains v2(xmin=501), but under the PINNED")
    print("snapshot S, xid 501 is >= xmax (501 >= 501) -> 'not started' -> v2's")
    print("insert is INVISIBLE. v1(xmin=100) is visible and its superseder 501 is")
    print("also invisible -> v1 stays the visible version. T500 sees balance=100")
    print("BOTH times.\n")
    print("                  READ COMMITTED (Sec C)   REPEATABLE READ (Sec D)")
    print(f"  read @ t1      balance = {rc_r1.payload}                 balance = {r1.payload}")
    print(f"  read @ t4      balance = {rc_r2.payload}                 balance = {r2.payload}")
    print("  repeatable?    NO  (non-repeatable read)   YES\n")
    assert r1.payload == 100 and r2.payload == 100 and r2.tag == "v1"
    print("[check] RR: both reads 100 (repeatable); only difference from C is the")
    print("       snapshot rule (reuse S vs take fresh S2): OK")


# ----------------------------------------------------------------------------
# SECTION E: dead tuple lifecycle + VACUUM
# ----------------------------------------------------------------------------
def section_e():
    banner("SECTION E: dead tuple lifecycle - UPDATE bloats, VACUUM reclaims")
    print("UPDATE never overwrites in place. It writes a NEW version and stamps the")
    print("OLD version's xmax, leaving the old version on the page as a DEAD TUPLE")
    print("once no live snapshot can need it. Dead tuples accumulate = BLOAT.\n")
    print("VACUUM removes dead tuples, reclaims their space, frees line pointers,")
    print("and sets the visibility-map bit so future index-only scans can skip the")
    print("heap. (🔗 FREE_SPACE_MAP.md is a sibling per-page bitmap.)\n")

    # After T100 INSERT, T200 UPDATE, T300 UPDATE (same chain as Section A).
    committed = {100, 200, 300}
    chain = [
        Version("v3", 300, 0),     # newest, LIVE
        Version("v2", 200, 300),   # dead (superseded by 300)
        Version("v1", 100, 200),   # dead (superseded by 200)
    ]
    # A tuple is removable iff NO live snapshot can see it.
    def is_removable(ver, snapshots, committed):
        return not any(visible_to_snapshot(ver, s, committed) for s in snapshots)

    print("Removable rule:  dead(v) = not visible under ANY live snapshot.\n")

    # ---- Case 1: only a current snapshot is open (sees just v3) ----
    snap_now = Snapshot(xmin=301, xmax=301, xip=[])   # everything <=300 finalized
    snaps_now = [snap_now]
    print(f"Case 1 - the only open snapshot is S_now = {snap_now} (sees only v3):")
    print("  | version | xmin | xmax | visible to S_now? | removable? |")
    print("  |---------|------|------|--------------------|------------|")
    for v in chain:
        vis = visible_to_snapshot(v, snap_now, committed)
        rem = is_removable(v, snaps_now, committed)
        print(f"  | {v.tag:<7} | {v.xmin:<4} | {v.xmax:<4} | "
              f"{'yes' if vis else 'no':<18} | {'YES' if rem else 'no':<10} |")
    print()
    removable = [v for v in chain if is_removable(v, snaps_now, committed)]
    live = [v for v in chain if not is_removable(v, snaps_now, committed)]
    print(f"  VACUUM frees {len(removable)} dead tuples {[v.tag for v in removable]},")
    print(f"  keeps {len(live)} live tuple {[v.tag for v in live]}.\n")

    PAGE_LINE_POINTERS_BEFORE = len(chain)
    PAGE_LINE_POINTERS_AFTER = len(live)
    print("  BEFORE VACUUM                 AFTER VACUUM")
    print("  -------------------------     -------------------------")
    print(f"  line pointers : {PAGE_LINE_POINTERS_BEFORE}            "
          f"line pointers : {PAGE_LINE_POINTERS_AFTER}")
    print(f"  dead tuples   : {len(removable)}            dead tuples   : 0")
    print(f"  live tuples   : {len(live)}            live tuples   : {len(live)}")
    print("  free space    : low           free space    : reclaimed")
    print("  vis-map bit   : clear         vis-map bit   : SET (all-visible)")
    print()

    # ---- Case 2: an old snapshot is still open and needs v1 ----
    print("Case 2 - a long-running reader opened S_old BEFORE T200 committed:")
    snap_old = Snapshot(xmin=200, xmax=301, xip=[200])  # 200 still 'in progress' to it
    snaps_old = [snap_old]
    print(f"  S_old = {snap_old}")
    print("  | version | visible to S_old? | removable now? |")
    print("  |---------|--------------------|----------------|")
    for v in chain:
        vis = visible_to_snapshot(v, snap_old, committed)
        rem = is_removable(v, snaps_old, committed)
        print(f"  | {v.tag:<7} | {'yes' if vis else 'no':<18} | {'YES' if rem else 'no':<14} |")
    print()
    print("  v1 is STILL VISIBLE to S_old (its superseder 200 is in xip -> the")
    print("  delete does not count). So VACUUM MUST RETAIN v1. This is why")
    print("  long-running transactions stall VACUUM and cause bloat: VACUUM can")
    print("  only remove what NO open transaction can still read.\n")
    v1_removable_old = is_removable(chain[2], snaps_old, committed)
    assert v1_removable_old is False
    print("[check] with S_old open, v1 is retained (not removable): OK")


# ----------------------------------------------------------------------------
# SECTION F: XID wraparound + freezing
# ----------------------------------------------------------------------------
def section_f():
    banner("SECTION F: XID wraparound - freeze old tuples before the counter wraps")
    print("Transaction IDs are a 32-bit counter: only 2^32 = 4,294,967,296 of them.")
    print("Eventually the counter WRAPS back to 0 and reuses old xids. An old tuple")
    print("stamped with xmin=1000 would then be confused with a brand-new xid 1000")
    print("-> visibility would silently break (data loss).\n")
    print("Defense: VACUUM FROZENS old tuples first - it overwrites their xmin with")
    print(f"FrozenTransactionId (== {FROZEN_XID}), a marker meaning 'committed")
    print("forever'. Once frozen, the original xid is no longer referenced, so it")
    print("can be reused safely after wraparound.\n")

    print("XIDs are compared as SIGNED 32-bit offsets (mod 2^32): a stored xid is")
    print("'older' if the forward distance (curr - old) mod 2^32 is < 2^31. Once the")
    print(f"distance reaches 2^31 ({XID_HALF:,}), the sign flips and the old tuple")
    print("looks 'in the future' -> broken. So everything must be frozen before that.\n")

    def xid_distance(curr, old):
        return (curr - old) % XID_MOD

    oldest_unfrozen = 1000                 # a tuple inserted way back at xid 1000
    print(f"Worked example: oldest UNFROZEN tuple has xmin = {oldest_unfrozen:,}.\n")
    H1, H2, H3, H4 = "current_xid", "distance = curr-old", "vs thresholds", "action"
    W1, W2, W3, W4 = 16, 19, 33, 47
    print(f"  | {H1:>{W1}} | {H2:>{W2}} | {H3:<{W3}} | {H4:<{W4}} |")
    print(f"  |{'-'*(W1+2)}|{'-'*(W2+2)}|{'-'*(W3+2)}|{'-'*(W4+2)}|")
    rows = [
        (60_000_000,                     "min_age(50M) <= d < max_age(200M)",
         "normal VACUUM freezes opportunistically"),
        (oldest_unfrozen + AUTOVACUUM_FREEZE_MAX_AGE, "d == max_age(200M)",
         "FORCED anti-wraparound autovacuum"),
        (1_000_000_000,                  "d < 2^31 (still comparable)",
         "freeze overdue but still safe"),
        (oldest_unfrozen + XID_HALF - 1, "d == 2^31 - 1 (edge)",
         "last safe moment - sign about to flip"),
        (oldest_unfrozen + XID_HALF,     "d == 2^31 (CLIFF)",
         "sign flips: old xid looks 'future' -> DATA LOSS"),
    ]
    for curr, vs, action in rows:
        d = xid_distance(curr, oldest_unfrozen)
        print(f"  | {curr:>{W1},} | {d:>{W2},} | {vs:<{W3}} | {action:<{W4}} |")
    print("\n  (the FORCED autovacuum at d == max_age(200M) CANNOT be disabled - it")
    print("   runs even if autovacuum is turned off, to prevent wraparound.)\n")

    # The hard wrap itself: counter passes 2^32-1 and continues at small xids.
    print("If not frozen, after a full wrap the old xid is reused and visibility")
    print("breaks. With freezing, xmin becomes FrozenXid(2) -> always visible:\n")
    wrapped_curr = 5                        # counter just wrapped past 2^32-1
    d_wrap = xid_distance(wrapped_curr, oldest_unfrozen)
    print(f"  current_xid = {wrapped_curr} (just wrapped)")
    print(f"  distance to xmin={oldest_unfrozen} = {d_wrap:,}  (>= 2^31 -> sign flip)")
    print("  unfrozen tuple: looks 'in the future' -> INVISIBLE -> data loss")
    print(f"  frozen tuple:   xmin == {FROZEN_XID} -> committed_visible -> True for")
    print("                  ANY snapshot -> SAFE across the wrap.\n")

    # commit log check on a frozen tuple
    committed = set()
    any_snap = Snapshot(xmin=wrapped_curr, xmax=wrapped_curr + 1, xip=[])
    frozen_ver = Version("frozen", xmin=FROZEN_XID, xmax=0)
    assert committed_visible(FROZEN_XID, any_snap, committed) is True
    assert visible_to_snapshot(frozen_ver, any_snap, committed) is True
    print(f"[check] committed_visible(FrozenXid={FROZEN_XID}) == True even with an")
    print("       EMPTY commit log and a wrapped snapshot: OK")

    # thresholds sanity
    assert VACUUM_FREEZE_MIN_AGE == 50_000_000
    assert AUTOVACUUM_FREEZE_MAX_AGE == 200_000_000
    assert xid_distance(oldest_unfrozen + XID_HALF, oldest_unfrozen) == XID_HALF
    print("[check] freeze thresholds 50M / 200M, cliff distance == 2^31: OK")


# ============================================================================
# 3. GOLD VALUES (pinned for mvcc.html - JS must reproduce these exactly)
# ============================================================================
def section_gold(rc_r2):
    banner("GOLD (pinned for mvcc.html) - JS must reproduce these")
    # Re-state the Section A scenario and pin the answer.
    chain_a = [
        Version("alice-v3", 300, 0),
        Version("alice-v2", 200, 300),
        Version("alice-v1", 100, 200),
    ]
    snap_a = Snapshot(xmin=250, xmax=251, xip=[])
    committed_a = {100, 200, 300}
    ans = visibility(chain_a, snap_a, committed_a)
    print(f"  visibility(chainA, snap@250) -> tag   = {ans.tag!r}")
    print(f"                                   xmin  = {ans.xmin}")
    print(f"                                   xmax  = {ans.xmax}")
    # RR second read (Section D) pinned balance
    print("  REPEATABLE READ second read balance  = 100  (v1)")
    print(f"  READ COMMITTED  second read balance  = {rc_r2.payload}  (v2)")
    print("  VACUUM dead tuples reclaimed         = 2   (v1, v2)")
    print(f"  XID wraparound cliff distance        = 2^31 = {XID_HALF:,}")
    assert ans.tag == "alice-v2" and ans.xmin == 200 and ans.xmax == 300
    assert rc_r2.payload == 200
    print("\n[check] GOLD: visibility -> alice-v2 (xmin=200, xmax=300): OK")


# ============================================================================
# main
# ============================================================================
def main():
    print("mvcc.py - reference impl. All numbers feed MVCC.md.")
    print("pure Python stdlib. XID space = 32-bit. Run: python3 mvcc.py")

    section_a()
    section_b()
    rc_r1, rc_r2 = section_c()
    section_d(rc_r1, rc_r2)
    section_e()
    section_f()
    section_gold(rc_r2)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
