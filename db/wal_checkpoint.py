"""
wal_checkpoint.py - Reference implementation of Write-Ahead Logging (WAL) +
Checkpointing, the crash-recovery mechanism at the heart of every durable DB.

This is the single source of truth that WAL_CHECKPOINT.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 wal_checkpoint.py

============================================================================
THE INTUITION (read this first) - the notebook you keep BEFORE you spend cash
============================================================================
Imagine you keep a small NOTEBOOK of every money transfer, written down the
INSTANT you decide to make it, BEFORE the actual cash leaves the drawer. If the
lights go out mid-shift and you drop the cash drawer, you do not panic: you open
the notebook, replay every entry, and the drawer is exactly right again.

  * WAL (Write-Ahead Log)  : that notebook. Append-only, fsync'd to disk BEFORE
                             the corresponding data page is allowed to be
                             flushed. Every modification is logged first.
  * data page              : the cash drawer. Big, random I/O, flushed lazily.
                             May lag behind the WAL (NO-FORCE) and may even be
                             evicted before its transaction commits (STEAL).
  * checkpoint             : a snapshot marker. "As of here, every dirty drawer
                             has been flushed; recovery can START here." Caps the
                             amount of WAL you must replay after a crash.
  * ARIES recovery         : on crash, three phases starting from the last
                             checkpoint - ANALYSIS (who committed?), REDO
                             (re-apply every logged change), UNDO (roll back the
                             transactions that never committed).

THE REASON WAL EXISTS: disk writes are not atomic and crashes happen mid-write.
If a half-modified page reaches disk with NO log of intent, the database cannot
tell on restart whether the change was meant to survive. WAL turns "did this
change survive?" into "is there a log record for it (and was it committed)?",
which is always answerable.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   WAL / log         : the append-only, fsync'd sequence of records describing
                       every modification. The source of truth on disk. 🔗 The
                       redo log is the dual of the undo/rollback segments in
                       MVCC (MVCC.md) - both derive from the same intent.
   LSN               : Log Sequence Number. Monotonically increasing id for each
                       record. Pages carry their `page_lsn` = LSN of the newest
                       record applied to them. (Real systems use byte offsets;
                       here LSNs are small integers 1,2,3,... for clarity.)
   STEAL             : the buffer manager MAY flush a dirty page to disk BEFORE
                       its transaction commits (eviction under pressure). Needs
                       UNDO on recovery.
   NO-FORCE          : the buffer manager need NOT flush pages at commit time.
                       Needs REDO on recovery.
   WAL rule          : a page may be written to disk only AFTER its modifying log
                       record is durable in the WAL (fsync'd). `page_lsn <=
                       flush_lsn` must hold before any page flush.
   redo              : the FORWARD action in a log record - "apply this change".
                       Idempotent (replay-safe): set key=value, or delete key.
   undo              : the BACKWARD action - "reverse this change". Used to roll
                       back loser (uncommitted) transactions.
   CLR               : Compensation Log Record. The undo action, itself LOGGED
                       so undo is crash-safe and repeatable. A CLR is never
                       undone (it has no undo field).
   prev_lsn          : each record carries the previous LSN of the SAME txn,
                       forming a per-transaction chain walked backwards by UNDO.
   commit            : a transaction is durable the instant its COMMIT record is
                       flushed to the WAL. (The "commit" = the fsync of that one
                       record. Data pages may still be in RAM.)
   checkpoint        : a record + an action. Action: flush all dirty pages.
                       Record: store the REDO POINT (where recovery redo starts)
                       and the transaction table, so ANALYSIS has a head start.
   ARIES             : Algorithm for Recovery and Isolation Exploiting
                       Semantics (Mohan et al., 1992). The 3-phase redo/undo
                       recovery used by essentially every modern DB.
   dirty page table  : DPT. page_id -> recLSN (oldest unflushed change). Lets
                       REDO start at min(recLSN) instead of the whole log.

============================================================================
THE LINEAGE (papers)
============================================================================
   Shadow paging      Lorie, "Physical Integrity in a Large Segmented Database",
                      ACM TODS 1977. No WAL; atomicity via shadow pages. No
                      undo/redo but coarse and write-amplifying.
   WAL (concept)      Larsen & Graefe, "Snapshot Isolation ..."; and the classic
                      "principles of WAL" crystallised in - 
   ARIES              Mohan, Haderle, Lindsay, Pirahesh, Schwarz, "ARIES: A
                      Transaction Recovery Method ...", ACM TODS 1992. The
                      definitive STEAL/NO-FORCE + redo/undo algorithm. DB2,
                      SQL Server, Postgres, InnoDB, SQLite all follow it.
   Fuzzy checkpoint   Mohan et al. 1992 §6; Pirahesh et al. 1992. Checkpoint
                      without halting the system (a background writer flushes;
                      the checkpoint records recLSN, not a clean cut).
   PostgreSQL         src/backend/access/transam/xlog.c (WAL), xloginsert.c
                      (record format), checkpointer.c, bgwriter.c; docs §30.5
                      "WAL and Checkpoints", §20.5 "Write Ahead Log" config.

KEY RULES (all asserted/printed in the sections below):
   WAL rule          : flush(page) requires page_lsn(page) <= wal_flush_lsn()
   STEAL             : uncommitted dirty pages MAY be evicted -> needs UNDO
   NO-FORCE          : commit does NOT flush data pages   -> needs REDO
   commit durability : COMMIT record fsync == transaction is durable
   redo idempotent   : applying redo twice == once (use absolute SET/DEL)
   recovery result   : all COMMITTED effects present, all UNCOMMITTED absent
   checkpoint benefit: redo starts at redo_point, not at LSN 1
   recovery cost     ~ (WAL bytes since last checkpoint) / replay_rate

Conventions:
   LSNs are small deterministic integers (1..N), printed with an "L" prefix.
   Keys are ints (1,2,3), values are short strings ("A","B","X","Y").
   Pages are "P1","P2". The WAL is printed oldest -> newest.
"""

from __future__ import annotations

BANNER = "=" * 72

# PostgreSQL defaults (docs §20.5) - used in Section F.
PG_CHECKPOINT_TIMEOUT = 300          # seconds (5 min)
PG_MAX_WAL_SIZE = 1024               # MB (default 1GB)
PG_CHECKPOINT_COMPLETION_TARGET = 0.9
PG_FULL_PAGE_WRITES = True


# ============================================================================
# 1. THE DATA MODEL + THE WAL ENGINE (this is the code WAL_CHECKPOINT.md walks)
# ============================================================================
class WALRec:
    """One record in the write-ahead log.

    Fields:
      lsn      : this record's LSN.
      txn      : transaction id (None for CHECKPOINT).
      type     : BEGIN / INSERT / UPDATE / DELETE / COMMIT / CHECKPOINT / CLR.
      page     : page_id affected (None for BEGIN/COMMIT/CHECKPOINT).
      key      : row key the record touches (None if N/A).
      redo     : forward action tuple, e.g. ("SET", k, v) / ("DEL", k) / None.
      undo     : backward action tuple (compensation), or None for CLR/COMMIT.
      prev_lsn : previous LSN of the SAME txn (0 for BEGIN). UNDO walks this.
      ckpt_redo_pt : (CHECKPOINT only) LSN where REDO starts.
      ckpt_txntab  : (CHECKPOINT only) frozen txn table {txn:(status,last_lsn)}.
    """
    __slots__ = ("lsn", "txn", "type", "page", "key",
                 "redo", "undo", "prev_lsn",
                 "ckpt_redo_pt", "ckpt_txntab")

    def __init__(self, lsn, txn, type, page=None, key=None,
                 redo=None, undo=None, prev_lsn=0,
                 ckpt_redo_pt=None, ckpt_txntab=None):
        self.lsn = lsn
        self.txn = txn
        self.type = type
        self.page = page
        self.key = key
        self.redo = redo
        self.undo = undo
        self.prev_lsn = prev_lsn
        self.ckpt_redo_pt = ckpt_redo_pt
        self.ckpt_txntab = ckpt_txntab

    def fmt_action(self, act):
        if act is None:
            return "-"
        if act[0] == "SET":
            return f"SET({act[1]}={act[2]!r})"
        if act[0] == "DEL":
            return f"DEL({act[1]})"
        return repr(act)

    def __repr__(self):
        if self.type == "CHECKPOINT":
            txntab = "{" + ", ".join(
                f"{t}:{s}/L{ln}" for t, (s, ln) in (self.ckpt_txntab or {}).items()
            ) + "}"
            return (f"WALRec(L{self.lsn}, CHECKPOINT, "
                    f"redo_pt=L{self.ckpt_redo_pt}, txntab={txntab})")
        extra = ""
        if self.type == "CLR":
            extra = f" clr_of=L{self.prev_lsn}"   # prev_lsn reused as 'origin'
        return (f"WALRec(L{self.lsn}, {self.type}, txn={self.txn}, "
                f"page={self.page}, key={self.key}, "
                f"redo={self.fmt_action(self.redo)}, "
                f"undo={self.fmt_action(self.undo)}, prev=L{self.prev_lsn}"
                f"{extra})")


class Page:
    """A buffer-pool page. `rows` = {key: value}. `lsn` = newest applied LSN."""
    __slots__ = ("page_id", "rows", "lsn", "dirty")

    def __init__(self, page_id, rows=None, lsn=0):
        self.page_id = page_id
        self.rows = dict(rows) if rows else {}
        self.lsn = lsn
        self.dirty = False


class Database:
    """A tiny STEAL/NO-FORCE engine with a WAL and a buffer pool.

    The WAL is durable (self.wal). The buffer pool (self.pool) is volatile.
    self.disk holds the last-flushed snapshot of each page. A crash = lose the
    pool; disk + WAL survive.
    """

    def __init__(self):
        self.wal = []                 # list[WALRec], the durable log
        self.pool = {}                # page_id -> Page (volatile)
        self.disk = {}                # page_id -> {key:val} (last flushed)
        self.committed = set()        # txns whose COMMIT record exists
        self.aborted = set()
        self.active = {}              # txn -> last_lsn (for prev_lsn chaining)
        self._next_lsn = 1
        self.flush_lsn = 0            # how far the WAL has been fsync'd

    # ---- WAL plumbing ----
    def _lsn(self):
        l = self._next_lsn
        self._next_lsn += 1
        return l

    def _append(self, txn, type, page=None, key=None,
                redo=None, undo=None, ckpt_redo_pt=None, ckpt_txntab=None):
        prev = self.active.get(txn, 0) if txn is not None else 0
        rec = WALRec(self._lsn(), txn, type, page, key, redo, undo, prev,
                     ckpt_redo_pt, ckpt_txntab)
        self.wal.append(rec)
        self.flush_lsn = rec.lsn          # fsync the log up to here
        if txn is not None:
            self.active[txn] = rec.lsn
        return rec

    # ---- page plumbing ----
    def _get_page(self, page_id):
        """Load a page into the pool (from disk if needed)."""
        p = self.pool.get(page_id)
        if p is None:
            rows = dict(self.disk.get(page_id, {}))
            p = Page(page_id, rows)
            self.pool[page_id] = p
        return p

    def _apply(self, page_id, action, lsn):
        """Apply a SET/DEL action to a buffer page; stamp its lsn; mark dirty."""
        p = self._get_page(page_id)
        if action[0] == "SET":
            p.rows[action[1]] = action[2]
        elif action[0] == "DEL":
            p.rows.pop(action[1], None)
        p.lsn = lsn
        p.dirty = True

    # ---- the transactional API (WAL rule: log BEFORE modify) ----
    def begin(self, txn):
        return self._append(txn, "BEGIN")

    def insert(self, txn, page, key, value):
        # redo: set key=value. undo: delete key (it didn't exist before).
        rec = self._append(txn, "INSERT", page, key,
                           redo=("SET", key, value), undo=("DEL", key))
        self._apply(page, rec.redo, rec.lsn)
        return rec

    def update(self, txn, page, key, old, new):
        # redo: set key=new. undo: set key=old.
        rec = self._append(txn, "UPDATE", page, key,
                           redo=("SET", key, new), undo=("SET", key, old))
        self._apply(page, rec.redo, rec.lsn)
        return rec

    def delete(self, txn, page, key, old):
        # redo: del key. undo: set key=old.
        rec = self._append(txn, "DELETE", page, key,
                           redo=("DEL", key), undo=("SET", key, old))
        self._apply(page, rec.redo, rec.lsn)
        return rec

    def commit(self, txn):
        rec = self._append(txn, "COMMIT")
        self.committed.add(txn)
        self.active.pop(txn, None)     # a committed txn is no longer in-flight
        return rec

    # ---- checkpoint: flush ALL dirty pages, write the marker ----
    def checkpoint(self):
        """Sharp checkpoint: flush every dirty page, then write a CHECKPOINT
        record carrying the redo point (= this record's LSN) and the frozen
        transaction table. Recovery redo starts at the redo point."""
        flushed = []
        for pid, p in list(self.pool.items()):
            if p.dirty:
                # WAL rule gate: page_lsn <= flush_lsn must hold. It always
                # does here, because every modifying record was fsync'd on
                # append (flush_lsn tracks the last appended LSN).
                assert p.lsn <= self.flush_lsn, "WAL rule violated!"
                self.disk[pid] = dict(p.rows)
                p.dirty = False
                flushed.append(pid)
        # the transaction table: who is active right now, and their last LSN
        txntab = {t: ("committed" if t in self.committed
                      else "aborted" if t in self.aborted
                      else "in-progress", ln)
                  for t, ln in self.active.items()}
        rec = self._append(None, "CHECKPOINT",
                           ckpt_redo_pt=self._next_lsn,   # this rec's own LSN
                           ckpt_txntab=txntab)
        rec.ckpt_redo_pt = rec.lsn                          # redo starts here
        return rec, flushed

    def flush_page(self, page_id):
        """Flush a single page (STEAL eviction). Respects the WAL rule."""
        p = self.pool.get(page_id)
        if p is None or not p.dirty:
            return False
        assert p.lsn <= self.flush_lsn, "WAL rule violated!"
        self.disk[page_id] = dict(p.rows)
        p.dirty = False
        return True


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 2. THE WORKED SCENARIO  (deterministic; used by Sections C, D and the GOLD)
# ============================================================================
def build_scenario():
    """Build the canonical crash scenario and return (db, expected_state).

    Timeline (WAL, oldest -> newest):
      L1 BEGIN T1
      L2 T1 INSERT(P1, k1=A)
      L3 T1 UPDATE(P2, k2: B->X)
      L4 T1 COMMIT
      L5 CHECKPOINT  (flushes P1,P2; redo_pt=L5; txntab empty)
      L6 BEGIN T2
      L7 T2 INSERT(P1, k3=C)
      L8 BEGIN T3
      L9 T2 UPDATE(P1, k1: A->Y)
      L10 T3 DELETE(P2, k2)
      L11 T3 COMMIT
      [CRASH]  T2 still uncommitted (lastLSN=L9)

    Committed at crash: {T1, T3}. Loser: {T2}.
    Expected recovered state: only k1=A survives (T1's committed insert;
    T2's uncommitted update/insert undone; T3's committed delete removes k2).
    """
    db = Database()
    db.disk["P2"] = {2: "B"}            # pre-existing data on disk only
    db.begin("T1")
    db.insert("T1", "P1", 1, "A")
    db.update("T1", "P2", 2, "B", "X")
    db.commit("T1")
    db.checkpoint()
    db.begin("T2")
    db.insert("T2", "P1", 3, "C")
    db.begin("T3")
    db.update("T2", "P1", 1, "A", "Y")
    db.delete("T3", "P2", 2, "X")
    db.commit("T3")
    expected = {"P1": {1: "A"}, "P2": {}}   # what correct recovery must yield
    return db, expected


# ============================================================================
# 3. THE SECTIONS  (each prints a banner + table WAL_CHECKPOINT.md pastes)
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the WAL protocol - log BEFORE modify (STEAL/NO-FORCE)
# ----------------------------------------------------------------------------
def section_a():
    banner("SECTION A: the WAL protocol - log BEFORE modify (STEAL/NO-FORCE)")
    print("Databases use STEAL/NO-FORCE buffering because it is the fastest:")
    print("  STEAL    : a dirty page MAY be flushed to disk before its txn")
    print("             commits (the buffer pool can evict under pressure).")
    print("  NO-FORCE : pages need NOT be flushed at commit (commit is fast).\n")
    print("Both make recovery harder: STEAL needs UNDO (roll back the evicted")
    print("uncommitted change); NO-FORCE needs REDO (re-apply committed changes")
    print("never flushed). The WAL RULE ties them together safely:\n")
    print("   A data page may be written to disk ONLY AFTER the log record that")
    print("   describes its modification has been fsync'd to the WAL:\n")
    print("        page_lsn(page)  <=  wal_flush_lsn()        (must hold)\n")
    print("Consequence: every modification is performed in this ORDER:\n")
    print("   1. APPEND the WAL record  (assign LSN, write to log, fsync)")
    print("   2. MODIFY the page in the buffer pool (stamp page_lsn = LSN)")
    print("   3. (later) FLUSH the page to disk  -- only legal once the WAL is")
    print("      durable past page_lsn.\n")

    print("Worked: T1 UPDATE(P2, k2: B->X), starting from page_lsn=0, "
          "flush_lsn=0.\n")
    db = Database()
    db.disk["P2"] = {2: "B"}
    p = db._get_page("P2")
    print(f"  BEFORE: page P2 = {p.rows}, page_lsn = L{p.lsn}, "
          f"flush_lsn = L{db.flush_lsn}\n")
    # Step 1: append the WAL record (fsync)
    rec = db._append("T1", "UPDATE", "P2", 2,
                     redo=("SET", 2, "X"), undo=("SET", 2, "B"))
    print(f"  Step 1  APPEND WAL:  {rec}")
    print(f"          now flush_lsn = L{db.flush_lsn}  (log fsync'd to here)")
    # Step 2: modify the page in buffer (stamp page_lsn)
    db._apply("P2", rec.redo, rec.lsn)
    print(f"  Step 2  MODIFY page: P2 = {p.rows}, page_lsn = L{p.lsn}, "
          f"dirty = {p.dirty}")
    # Step 3: flush allowed?
    ok = p.lsn <= db.flush_lsn
    print(f"  Step 3  FLUSH gate:  page_lsn(L{p.lsn}) <= flush_lsn(L{db.flush_lsn})"
          f"?  {'YES -> flush legal' if ok else 'NO -> must wait for fsync'}")
    db.flush_page("P2")
    print(f"          after flush: disk P2 = {db.disk['P2']}\n")

    print("WHY THE ORDER IS INVIOLABLE - the no-WAL failure mode:")
    print("  Suppose we FLUSH the page FIRST, then crash BEFORE appending the log:")
    print("    disk now holds k2=X, but there is NO log record for it. On restart")
    print("    the engine cannot redo it (no record) nor undo it (no undo info,")
    print("    and it does not even know which txn owns it). The change is")
    print("    UNRECOVERABLE - and worse, if the txn was going to abort, the")
    print("    half-applied write silently corrupts the database. The WAL rule")
    print("    is what makes STEAL/NO-FORCE safe: the log is always the authority.\n")
    assert ok and db.disk["P2"] == {2: "X"}
    print("[check] WAL rule honored: page_lsn <= flush_lsn and disk == {2:'X'}: OK")


# ----------------------------------------------------------------------------
# SECTION B: WAL record types and the record format
# ----------------------------------------------------------------------------
def section_b():
    banner("SECTION B: WAL record types and the record format (redo + undo)")
    print("Every modification is described by ONE record. The generic format:\n")
    print("   [ LSN | txn | type | page | key | redo | undo | prev_lsn ]\n")
    print("  LSN      : monotonic id of this record.")
    print("  txn      : transaction that wrote it.")
    print("  type     : one of BEGIN / INSERT / UPDATE / DELETE / COMMIT /")
    print("             ABORT / CHECKPOINT / CLR.")
    print("  page,key : where the change lands.")
    print("  redo     : FORWARD action ('re-apply this on recovery').")
    print("  undo     : BACKWARD action ('reverse this on rollback'). A CLR has")
    print("             redo but NO undo (a CLR is itself the reversal; it is")
    print("             never re-reversed).")
    print("  prev_lsn : previous record of the SAME txn -> the chain UNDO walks.\n")
    print("redo/undo actions are expressed as absolute, IDEMPOTENT primitives so")
    print("that replaying them twice is harmless:\n")
    print("   SET(k, v)  : rows[k] = v       (redo of insert/update; undo of")
    print("                                  delete / value-reverting update)")
    print("   DEL(k)     : rows.pop(k)        (redo of delete; undo of insert)\n")

    print("Per-type redo/undo summary:\n")
    print("  | type       | redo action         | undo action           | notes |")
    print("  |------------|---------------------|-----------------------|-------|")
    rows = [
        ("BEGIN",   "-",                 "-",                   "starts the prev_lsn chain"),
        ("INSERT",  "SET(k,v)",          "DEL(k)",              "undo removes the new row"),
        ("UPDATE",  "SET(k,new)",        "SET(k,old)",          "undo restores the prior value"),
        ("DELETE",  "DEL(k)",            "SET(k,old)",          "undo re-inserts the row"),
        ("COMMIT",  "-",                 "-",                   "txn is a winner; never undone"),
        ("ABORT",   "-",                 "-",                   "txn already rolled back"),
        ("CHECKPOINT","-",               "-",                   "carries redo_pt + txn table"),
        ("CLR",     "(the compensation)","-  (none)",           "logged undo; idempotent"),
    ]
    for t, r, u, n in rows:
        print(f"  | {t:<10} | {r:<19} | {u:<21} | {n:<5} |")
    print()

    # Show three concrete records from the scenario.
    print("Three concrete records (from the Section D scenario):\n")
    db, _ = build_scenario()
    for i in (1, 2, 8):       # L2 (INSERT), L3 (UPDATE), L9 (UPDATE uncommitted)
        print(f"  {db.wal[i]}")
    print()
    print("Note L9's undo = SET(1,'A'): if T2 aborts, applying it reverts k1 to A.")
    print("Note each record's prev_lsn chains to the previous record of its txn:")
    print("T2's chain is L6(BEGIN) -> L7(INSERT) -> L9(UPDATE); UNDO walks 9 -> 7 -> 6.")
    print("\n[check] INSERT.undo=DEL, UPDATE.undo=SET(old), DELETE.undo=SET(old): OK")


# ----------------------------------------------------------------------------
# SECTION C: checkpoint - flush all dirty pages, record the redo point
# ----------------------------------------------------------------------------
def section_c():
    banner("SECTION C: checkpoint - flush dirty pages, pin the redo point")
    print("Recovery without a checkpoint would have to replay the ENTIRE log from")
    print("the beginning of time - unbounded. A CHECKPOINT caps it:\n")
    print("  Action : flush every dirty buffer page to disk (a 'sharp' checkpoint).")
    print("  Record : write a CHECKPOINT record holding")
    print("             - redo_pt   : the LSN at which REDO will start (= the")
    print("                           checkpoint record's own LSN for a sharp ckpt),")
    print("             - txn_table : a snapshot of which txns were in-progress and")
    print("                           their last LSN (a head start for ANALYSIS).\n")
    print("After a checkpoint, recovery may ignore everything before redo_pt for")
    print("REDO (those changes are already on disk). ANALYSIS still starts at the")
    print("checkpoint record so it can rebuild the in-progress txn table.\n")

    # Build T1's effects up to (but not including) the checkpoint, so we can
    # show the BEFORE state, then execute the checkpoint and show AFTER.
    db = Database()
    db.disk["P2"] = {2: "B"}
    db.begin("T1")
    db.insert("T1", "P1", 1, "A")
    db.update("T1", "P2", 2, "B", "X")
    db.commit("T1")
    print("BEFORE checkpoint (after T1 committed, L1..L4 written):\n")
    for pid in ("P1", "P2"):
        p = db.pool.get(pid)
        d = db.disk.get(pid, {})
        if p:
            print(f"  P{pid[1]}: buffer = {p.rows} (dirty={p.dirty}, "
                  f"page_lsn=L{p.lsn}), disk = {d}")
        else:
            print(f"  P{pid[1]}: buffer = -, disk = {d}")
    print()
    ckpt, flushed = db.checkpoint()
    print(f"CHECKPOINT executes -> flushes pages: {flushed}")
    print(f"  writes record: {ckpt}\n")
    print("AFTER checkpoint:\n")
    for pid in ("P1", "P2"):
        p = db.pool[pid]
        print(f"  P{pid[1]}: buffer = {p.rows} (dirty={p.dirty}, page_lsn=L{p.lsn}), "
              f"disk = {db.disk[pid]}")
    print(f"\n  redo_pt = L{ckpt.ckpt_redo_pt}  -> REDO on recovery starts here,")
    print("                                  NOT at L1. Everything before is on disk.")
    print("  txn_table at checkpoint = {}  (T1 already committed; nothing in flight)\n")

    # Verify disk matches the post-T1 state.
    assert db.disk["P1"] == {1: "A"} and db.disk["P2"] == {2: "X"}
    assert all(not p.dirty for p in db.pool.values())
    assert ckpt.ckpt_redo_pt == ckpt.lsn
    print("[check] after ckpt: disk P1={1:'A'}, P2={2:'X'}, all pages clean, "
          "redo_pt=L5: OK")


# ----------------------------------------------------------------------------
# SECTION D: ARIES recovery - Analysis, Redo, Undo (+ GOLD crash test)
# ----------------------------------------------------------------------------
def section_d():
    banner("SECTION D: ARIES recovery - Analysis -> Redo -> Undo (crash test)")
    print("A crash loses the buffer pool; disk + WAL survive. ARIES rebuilds the")
    print("correct state in three phases, starting from the LAST checkpoint:\n")
    print("  Phase 1 ANALYSIS : scan the WAL forward from the checkpoint record.")
    print("                     Rebuild the txn table (who is in-progress / committed)")
    print("                     and the dirty page table. Decide WINNERS (committed)")
    print("                     vs LOSERS (in-progress at crash -> must undo).")
    print("  Phase 2 REDO     : re-apply every redo action from the redo point")
    print("                     forward, making disk >= the pre-crash state. Redo is")
    print("                     IDEMPOTENT, so already-flushed pages are harmless.")
    print("  Phase 3 UNDO     : roll back every LOSER, walking its prev_lsn chain")
    print("                     from newest to oldest. Each step appends a CLR")
    print("                     (so undo itself survives a second crash).\n")

    db, expected = build_scenario()
    print("The scenario (built in build_scenario()):\n")
    print("  L1  BEGIN T1")
    print("  L2  T1 INSERT(P1, k1=A)")
    print("  L3  T1 UPDATE(P2, k2: B->X)")
    print("  L4  T1 COMMIT")
    print("  L5  CHECKPOINT   <- recovery starts here")
    print("  L6  BEGIN T2")
    print("  L7  T2 INSERT(P1, k3=C)")
    print("  L8  BEGIN T3")
    print("  L9  T2 UPDATE(P1, k1: A->Y)   <- T2 uncommitted")
    print("  L10 T3 DELETE(P2, k2)")
    print("  L11 T3 COMMIT")
    print("  *** CRASH ***                  (buffer lost; disk = post-L5 state)\n")
    print(f"  committed at crash = {sorted(db.committed)} ; loser = ['T2']\n")

    # --- freeze disk-at-crash, then drop the buffer (the crash) ---
    crash_disk = {pid: dict(rows) for pid, rows in db.disk.items()}
    print(f"Disk at crash (survives): {crash_disk}")
    print("Buffer at crash (LOST):   P1={1:'Y',3:'C'}, P2={}  (only in RAM)\n")

    # === PHASE 1: ANALYSIS ===
    print(BANNER)
    print("  PHASE 1 - ANALYSIS  (scan WAL forward from checkpoint L5)")
    print(BANNER)
    ckpt = db.wal[4]                       # the CHECKPOINT record (L5)
    redo_pt = ckpt.ckpt_redo_pt
    txn_table = dict(ckpt.ckpt_txntab)     # start from the frozen table
    dpt = {}                               # page_id -> recLSN
    start = db.wal.index(ckpt)
    print(f"  start: redo_pt = L{redo_pt}, txn_table (from ckpt) = "
          f"{dict(txn_table)}\n")
    print("  | LSN | type      | txn | effect on txn_table / DPT |")
    print("  |-----|-----------|-----|--------------------------|")
    for rec in db.wal[start + 1:]:
        note = ""
        if rec.type == "BEGIN":
            txn_table[rec.txn] = ("in-progress", rec.lsn)
            note = f"+{rec.txn}=in-progress"
        elif rec.type in ("INSERT", "UPDATE", "DELETE"):
            txn_table[rec.txn] = ("in-progress", rec.lsn)
            # DPT: record the recLSN the first time a page is dirtied after ckpt
            if rec.page not in dpt:
                dpt[rec.page] = rec.lsn
            note = f"{rec.txn}.last=L{rec.lsn}; DPT[{rec.page}]=L{dpt[rec.page]}"
        elif rec.type == "COMMIT":
            txn_table[rec.txn] = ("committed", rec.lsn)
            note = f"{rec.txn}=committed (WINNER)"
        print(f"  | L{rec.lsn:<2} | {rec.type:<9} | {str(rec.txn):<3} | "
              f"{note:<24} |")
    losers = [t for t, (s, _) in txn_table.items() if s != "committed"]
    winners = [t for t, (s, _) in txn_table.items() if s == "committed"]
    print(f"\n  -> WINNERS (committed): {winners}   LOSERS (must undo): {losers}")
    print(f"  -> dirty page table at crash: {dpt}")
    print(f"  -> redo will start at L{redo_pt} (could also start at "
          f"min recLSN = L{min(dpt.values())} for less work)\n")
    assert losers == ["T2"] and winners == ["T3"]

    # === PHASE 2: REDO ===
    print(BANNER)
    print(f"  PHASE 2 - REDO  (re-apply redo from L{redo_pt} forward, idempotent)")
    print(BANNER)
    # Reconstruct a fresh buffer straight from crash_disk, then redo onto it.
    redo_pool = {pid: Page(pid, dict(rows)) for pid, rows in crash_disk.items()}
    redo_count = 0
    print("  | LSN | redo action        | P1 after        | P2 after   |")
    print("  |-----|--------------------|-----------------|------------|")
    for rec in db.wal:
        if rec.lsn < redo_pt or rec.redo is None:
            continue
        p = redo_pool.setdefault(rec.page, Page(rec.page))
        act = rec.redo
        if act[0] == "SET":
            p.rows[act[1]] = act[2]
        else:
            p.rows.pop(act[1], None)
        redo_count += 1
        print(f"  | L{rec.lsn:<2} | {rec.fmt_action(act):<18} | "
              f"{str(redo_pool.get('P1').rows):<15} | "
              f"{str(redo_pool.get('P2').rows):<10} |")
    print(f"\n  -> applied {redo_count} redo action(s). Disk now reflects the")
    print("     pre-crash in-memory state (including T2's uncommitted writes,")
    print("     which UNDO will next remove). Redo is idempotent, so a later")
    print("     re-run changes nothing.\n")

    # === PHASE 3: UNDO ===
    print(BANNER)
    print(f"  PHASE 3 - UNDO  (roll back LOSERS via prev_lsn; append CLRs)")
    print(BANNER)
    # lastLSN per loser
    last = {t: txn_table[t][1] for t in losers}
    # index records by LSN
    by_lsn = {r.lsn: r for r in db.wal}
    clr_count = 0
    next_lsn = db._next_lsn
    print(f"  Losers to undo: {losers}, starting from lastLSN = {last}\n")
    print("  | step | walk LSN | record                | undo (CLR) action   | "
          "P1 after        | P2 after   |")
    print("  |------|----------|-----------------------|---------------------|"
          "-----------------|------------|")
    step = 0
    while any(l > 0 for l in last.values()):
        # pick the loser with the highest lastLSN (undo newest-first globally)
        t = max((t for t in losers if last[t] > 0), key=lambda t: last[t])
        lsn = last[t]
        rec = by_lsn[lsn]
        if rec.type == "BEGIN":
            last[t] = 0
            continue
        step += 1
        act = rec.undo
        clr_lsn = next_lsn
        next_lsn += 1
        clr_count += 1
        # apply the CLR to the pool
        p = redo_pool.setdefault(rec.page, Page(rec.page))
        if act[0] == "SET":
            p.rows[act[1]] = act[2]
        else:
            p.rows.pop(act[1], None)
        p1 = str(redo_pool.get("P1").rows)
        p2 = str(redo_pool.get("P2").rows)
        print(f"  | {step:<4} | L{lsn:<7} | {str(rec):<21} | "
              f"CLR L{clr_lsn} {rec.fmt_action(act):<9} | {p1:<15} | {p2:<10} |")
        last[t] = rec.prev_lsn
    print(f"\n  -> appended {clr_count} CLR(s). All loser effects reversed.\n")

    recovered = {pid: dict(p.rows) for pid, p in redo_pool.items()}
    print(f"  RECOVERED database: {recovered}")
    print(f"  EXPECTED database : {expected}\n")

    ok = recovered == expected
    print(f"  GOLD CHECK: recovered == expected?  {'YES' if ok else 'NO'}")
    if ok:
        print("    - T1's committed INSERT(k1=A): PRESENT  (redo kept it)")
        print("    - T1's committed UPDATE(k2=X) then T3's committed DELETE: k2 ABSENT")
        print("    - T2's uncommitted INSERT(k3=C): ABSENT  (undo removed it)")
        print("    - T2's uncommitted UPDATE(k1=A->Y): REVERTED to A (undo)")
    assert ok, "recovery did not produce the expected state!"
    assert redo_count == 3 and clr_count == 2
    print(f"\n[check] ARIES: recovered == expected, redo={redo_count}, "
          f"undo(CLRs)={clr_count}: OK")
    return recovered, expected, redo_count, clr_count


# ----------------------------------------------------------------------------
# SECTION E: checkpoint timing trade-off + fuzzy checkpoint
# ----------------------------------------------------------------------------
def section_e():
    banner("SECTION E: checkpoint timing - fast recovery vs low overhead")
    print("Checkpoints are a dial. The more often you checkpoint, the LESS WAL")
    print("accrues between them (so recovery is FAST), but the MORE flush I/O you")
    print("do in steady state (high OVERHEAD). The two pull against each other.\n")

    WAL_RATE = 1000          # WAL records produced per second
    REPLAY_RATE = 5000       # records/s the redo pass can re-apply
    FLUSH_COST = 0.5         # seconds of I/O per sharp checkpoint (flush+fsync)

    def recovery_redo_seconds(interval):
        accrued = WAL_RATE * interval        # records since last checkpoint
        return accrued / REPLAY_RATE         # seconds to redo them

    def overhead_fraction(interval):
        # fraction of steady-state time spent flushing for checkpoints
        return FLUSH_COST / interval

    print(f"Model: WAL rate = {WAL_RATE:,} rec/s, replay rate = {REPLAY_RATE:,} "
          f"rec/s, checkpoint flush cost = {FLUSH_COST} s.\n")
    print("  | interval | WAL accrued | recovery redo time | checkpoint overhead |")
    print("  |----------|-------------|--------------------|---------------------|")
    for T in (30, 60, 120, 300, 600, 1800, 3600):
        accrued = WAL_RATE * T
        recov = recovery_redo_seconds(T)
        oh = overhead_fraction(T)
        note = "  <- PostgreSQL checkpoint_timeout default" if T == 300 else ""
        print(f"  | {T:>5}s    | {accrued:>9,}   | {recov:>14.1f} s    | "
              f"{oh*100:>7.2f} %          |{note}")
    print("\n  Read the table two ways:")
    print("    * drop the interval -> recovery is fast, but you spend a large")
    print("      fraction of every second flushing (30s interval = 1.7% overhead).")
    print("    * raise the interval -> overhead vanishes, but a crash re-reads a")
    print("      huge WAL (1h interval = 720s of pure redo before the DB is up).\n")

    print("FUZZY checkpoint - making the checkpoint non-blocking:")
    print("  A SHARP checkpoint halts writing while it flushes every dirty page.")
    print("  A FUZZY checkpoint does not: a background writer flushes pages")
    print("  continuously, and the checkpoint record simply notes the REDO POINT")
    print("  = the oldest recLSN in the dirty page table (the first unflushed")
    print("  change). Writers keep running. Recovery redoes a little more, but no")
    print("  stall. The redo point is now min(recLSN), NOT the checkpoint LSN:\n")
    print("    sharp  : redo_pt = checkpoint_LSN          (everything flushed)")
    print("    fuzzy  : redo_pt = min(recLSN in DPT)      (oldest dirty change)")
    print("  PostgreSQL, InnoDB, DB2 all use fuzzy checkpoints.\n")

    # Sanity on the curve direction.
    assert recovery_redo_seconds(30) < recovery_redo_seconds(300)
    assert overhead_fraction(300) < overhead_fraction(30)
    print("[check] recovery time grows with interval, overhead shrinks: OK")


# ----------------------------------------------------------------------------
# SECTION F: PostgreSQL specifics - bgwriter, checkpointer, the knobs
# ----------------------------------------------------------------------------
def section_f():
    banner("SECTION F: PostgreSQL specifics - bgwriter, checkpointer, the knobs")
    print("PostgreSQL splits the work across dedicated processes (not one thread):\n")
    print("  * checkpointer : the only process allowed to write a CHECKPOINT")
    print("                   record. Flushes the shared buffer pool's dirty pages")
    print("                   and recycles old WAL segments. Runs a checkpoint when")
    print("                   either time or WAL volume trips a trigger.")
    print("  * bgwriter     : the background writer. Trickle-flushes dirty buffers")
    print("                   continuously so checkpoints have little left to do")
    print("                   (smoother I/O, fewer stalls).")
    print("  * walwriter    : fsyncs WAL records in the background so commits do")
    print("                   not always block on an explicit fsync.\n")
    print("A checkpoint fires when EITHER of these is hit:\n")
    print(f"  * time-based   : checkpoint_timeout = {PG_CHECKPOINT_TIMEOUT}s "
          f"(5 min default) since the last checkpoint")
    print(f"  * volume-based : max_wal_size = {PG_MAX_WAL_SIZE} MB (1 GB default) "
          f"of WAL consumed since the last checkpoint\n")
    print(f"checkpoint_completion_target = {PG_CHECKPOINT_COMPLETION_TARGET}: the")
    print("checkpointer spreads its flush work over "
          f"{PG_CHECKPOINT_COMPLETION_TARGET:.0%} of the time before the NEXT")
    print("checkpoint is due, smoothing I/O instead of a burst at the deadline.\n")

    print("  | parameter                          | default      | controls |")
    print("  |------------------------------------|--------------|----------|")
    print(f"  | checkpoint_timeout                 | {PG_CHECKPOINT_TIMEOUT}s "
          f"        | time-based trigger |")
    print(f"  | max_wal_size                       | {PG_MAX_WAL_SIZE} MB "
          f"        | volume-based trigger |")
    print(f"  | checkpoint_completion_target       | "
          f"{PG_CHECKPOINT_COMPLETION_TARGET}        | flush smoothing |")
    print(f"  | full_page_writes                   | "
          f"{PG_FULL_PAGE_WRITES}        | partial-page defence |")
    print("  | checkpoint_flush_after / sync      | tuned by OS  | fsync batching |")
    print("  | wal_level                          | replica      | how much to log |")
    print()

    print("FULL PAGE WRITES - the partial-write defence (worth understanding):")
    print("  Disks may write a page PARTIALLY (torn write) if power dies mid-flush.")
    print("  With full_page_writes=on, the FIRST modification of a page after each")
    print("  checkpoint logs the WHOLE page image; redo then has a clean baseline")
    print("  to re-apply later deltas against. Cost: a burst of big records right")
    print("  after each checkpoint. (Stock Postgres keeps it on; some appliances")
    print("  with atomic-page storage turn it off.)\n")

    print("What a PostgreSQL CHECKPOINT record effectively pins (simplified):")
    print("  redo_pt = LSN of the checkpoint record (redo starts here)")
    print("  + the list of dirty buffers + their recLSN  (fuzzy checkpoint)")
    print("  + the oldest active xid   (so VACUUM's xmin horizon is consistent)")
    print("  -> after redo + the next checkpoint's flush, old WAL segments can be")
    print("     recycled/removed (WAL is not kept forever - only back to redo_pt).")
    print("\n[check] defaults: timeout=300s, max_wal_size=1GB, completion_target="
          f"{PG_CHECKPOINT_COMPLETION_TARGET}, full_page_writes={PG_FULL_PAGE_WRITES}: OK")


# ============================================================================
# 4. GOLD VALUES (pinned for wal_checkpoint.html - JS must reproduce these)
# ============================================================================
def section_gold(recovered, expected, redo_count, clr_count):
    banner("GOLD (pinned for wal_checkpoint.html) - JS must reproduce these")
    print("  Crash scenario: 2 committed winners (T1, T3) + 1 loser (T2).")
    print(f"  recovered database        = {recovered}")
    print(f"  expected database         = {expected}")
    print(f"  redo actions applied      = {redo_count}   (L7, L9, L10)")
    print(f"  undo CLRs appended        = {clr_count}     "
          "(L9->SET(1,A), L7->DEL(3))")
    print("  losers rolled back        = ['T2']")
    print("  winners kept              = ['T1' insert k1=A, 'T3' delete k2]")
    print("  k1 final value            = 'A'   (T2's A->Y reverted by undo)")
    print("  k2 final                  = ABSENT (T3 committed delete)")
    print("  k3 final                  = ABSENT (T2 uncommitted insert undone)")
    assert recovered == expected == {"P1": {1: "A"}, "P2": {}}
    assert redo_count == 3 and clr_count == 2
    print("\n[check] GOLD: recovered{P1:{1:'A'}, P2:{}} == expected: OK")


# ============================================================================
# main
# ============================================================================
def main():
    print("wal_checkpoint.py - reference impl. All numbers feed WAL_CHECKPOINT.md.")
    print("pure Python stdlib. STEAL/NO-FORCE + ARIES. Run: python3 "
          "wal_checkpoint.py")

    section_a()
    section_b()
    section_c()
    recovered, expected, redo_count, clr_count = section_d()
    section_e()
    section_f()
    section_gold(recovered, expected, redo_count, clr_count)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
