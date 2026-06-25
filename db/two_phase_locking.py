"""
two_phase_locking.py - Reference implementation of Two-Phase Locking (2PL),
the classic lock-based concurrency control protocol.

This is the single source of truth that TWO_PHASE_LOCKING.md is built from.
Every number, table, lock-table snapshot, and worked example in the guide is
printed by this file. If you change something here, re-run and re-paste the
output into the guide.

Run:
    python3 two_phase_locking.py

============================================================================
THE INTUITION (read this first) - the office where you check out keys
============================================================================
Imagine every database row has a small set of KEYS hanging on a hook. Before a
transaction (T) can touch a row it must CHECK OUT the right key from the
lock manager:

  * a READ  needs an S-key (Shared)   - many readers may hold S-keys to the same row
  * a WRITE needs an X-key (eXclusive) - only ONE writer; nobody else may hold any key

The catch: 2PL says a transaction's life has exactly TWO phases, in order:

   PHASE 1 - GROWING  : T may only CHECK OUT keys. It cannot return any yet.
   PHASE 2 - SHRINKING: T may only RETURN keys. Once it has returned its FIRST
                        key, the growing phase is OVER - it can never check out
                        another key for the rest of its life.

The boundary between the phases is the FIRST release. Crossing it is one-way.
A transaction that returns a key and then tries to check one out VIOLATES 2PL,
and the lock manager rejects the request. That single rule - "never acquire
after you have started releasing" - is what GUARANTEES serializability.

WHY TWO PHASES? If a transaction could freely interleave acquire/release, it
could release a lock on A, then acquire a lock on B, in an order that no serial
schedule can match - producing a non-serializable result. Pinning all acquires
BEFORE all releases makes the transaction's lock footprint "grow then shrink",
which forces a serial order to exist (the 2PL theorem, see GOLD).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   S-lock          : a Shared (READ) lock. Many transactions may hold S on the
                     same item simultaneously (co-readers).
   X-lock          : an eXclusive (WRITE) lock. Only ONE holder; incompatible
                     with S and with other X.
   lock table      : the manager's map  item -> list of (txn, mode) holders.
                     An item with no holders is unlocked (absent from the map).
   growing phase   : the txn only ACQUIRES locks.
   shrinking phase : the txn only RELEASES locks. Begins at the first release.
   lock point      : the instant the txn acquires its LAST lock (peak of the
                     footprint). For two 2PL txns Ti, Tj, the one whose lock
                     point is earlier must serialize BEFORE the other.
   strict 2PL      : X-locks are held until COMMIT (not released mid-txn) ->
                     prevents cascading aborts.
   rigorous 2PL    : ALL locks (S and X) held until COMMIT. Simplest to build.
   upgrade         : S(R) -> X(R) on an item the txn already reads. Granted at
                     once if it is the SOLE S-holder; otherwise must WAIT.
   escalation      : trade many fine-grained locks (row) for one coarse lock
                     (page -> table) when a txn holds too many.
   conflict        : a pair of ops on the SAME item by DIFFERENT txns where at
                     least one is a WRITE: (R-W), (W-R), (W-W). (R-R is NOT.)
   precedence graph: node per txn; edge Ti -> Tj if Ti has an earlier op that
                     conflicts with a later op of Tj. ACYCLIC == serializable.

============================================================================
THE LINEAGE (sources)
============================================================================
   2PL (protocol)    Eswaran, Gray, Lorie, Traiger, "The Notions of Consistency
                     and Predicate Locks in a Database System", CACM 19(11),
                     Nov 1976 - the paper that DEFINED two-phase locking.
   2PL theorem       Kung & Papadimitriou, "An Optimality Theory of Concurrent
                     Control", ACM TODS 4(3), 1979 - proves 2PL => conflict-
                     serializable; it is the optimal class of "non-action"
                     schedulers (no a-priori info).
   Strict / rigorous Bernstein, Hadzilacos & Goodman, "Concurrency Control and
                     Recovery in Database Systems", 1987 (free online) - the
                     canonical taxonomy: basic vs strict vs rigorous 2PL,
                     cascading aborts, recoverability.
   Textbook          Silberschatz, Korth & Sudarshan, "Database System Concepts",
                     7th ed., Ch.16 "Transaction Processing" - the definitions
                     used here for S/X locks, the compatibility matrix, and the
                     strict/rigorous variants.
   vs MVCC           Bernstein & Goodman, "Concurrency Control in Distributed
                     Database Systems", ACM Comput. Surv. 1981 - the pessimistic
                     (locking) vs optimistic (multi-version) split. PostgreSQL's
                     MVCC default is contrasted in Section F. 🔗 See MVCC.md.

KEY RULES (all asserted/printed in the sections below):
   compatibility(m_req, m_held):
       (S,S) -> True ; (S,X), (X,S), (X,X) -> False     (only co-readers mix)
   grant(req, item)  = compatible(req, all OTHER holders)
   2PL phase rule    = a txn in the SHRINKING phase may NOT acquire.
                       The first release flips GROWING -> SHRINKING.
   strict 2PL rule   = X-locks released only at COMMIT (no mid-txn release).
   rigorous 2PL rule = ALL locks released only at COMMIT.
   upgrade S->X      = granted iff this txn is the SOLE holder of the item;
                       otherwise the upgrade WAITS (avoids breaking the matrix).
   2PL theorem       = every txn follows 2PL  =>  schedule is conflict-serializable
                       <=> precedence graph is ACYCLIC.

Conventions:
   Transaction ids are small deterministic integers (1, 2, 3).
   Items are single uppercase letters (A, B, C, R).
   The lock table is printed after every operation as a per-step snapshot.
"""

from __future__ import annotations

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# Lock modes + the compatibility matrix (the lock manager's only granting rule)
# ----------------------------------------------------------------------------
S = "S"   # Shared   (read lock)
X = "X"   # eXclusive (write lock)

# (requested, held) -> may they coexist?
COMPAT = {
    (S, S): True,    # two readers OK
    (S, X): False,   # reader vs writer NO
    (X, S): False,   # writer vs reader NO
    (X, X): False,   # two writers NO
}

# 2PL variants
BASIC_2PL    = "basic"
STRICT_2PL   = "strict"
RIGOROUS_2PL = "rigorous"

# Transaction phase
GROWING   = "growing"
SHRINKING = "shrinking"
COMMITTED = "committed"
ABORTED   = "aborted"

# Conflict pairs on the same item by different txns (R-R is NOT a conflict)
CONFLICT_PAIRS = {("R", "W"), ("W", "R"), ("W", "W")}


def is_conflict(op_a: str, op_b: str) -> bool:
    return (op_a, op_b) in CONFLICT_PAIRS


# ============================================================================
# 1. THE LOCK MANAGER (this is the code TWO_PHASE_LOCKING.md walks through)
# ============================================================================
class Transaction:
    """One transaction. Tracks its 2PL variant, current phase, and held locks."""
    __slots__ = ("tid", "variant", "phase", "status", "held")

    def __init__(self, tid, variant=BASIC_2PL):
        self.tid = tid
        self.variant = variant
        self.phase = GROWING
        self.status = "active"
        self.held = {}          # item -> mode (S or X)

    def __repr__(self):
        return f"T{self.tid}"


class LockTable:
    """item -> list of (tid, mode) holders. Empty/absent means unlocked."""

    def __init__(self):
        self.table: dict[str, list[tuple[int, str]]] = {}

    def holders(self, item):
        return self.table.get(item, [])

    def add(self, item, tid, mode):
        self.table.setdefault(item, []).append((tid, mode))

    def remove(self, item, tid):
        if item in self.table:
            self.table[item] = [(t, m) for (t, m) in self.table[item] if t != tid]
            if not self.table[item]:
                del self.table[item]

    def snapshot(self):
        """Deterministic snapshot for printing: items sorted, holders sorted."""
        return {i: sorted(self.table.get(i, [])) for i in sorted(self.table)}


def fmt_locks(snap: dict) -> str:
    """Compact one-line render of a lock-table snapshot, e.g. 'A:T1S,T2S  B:T1X'."""
    if not snap:
        return "(empty)"
    return "  ".join(
        f"{i}:" + ",".join(f"T{t}{m}" for (t, m) in snap[i]) for i in sorted(snap)
    )


class LockManager:
    """A tiny but faithful 2PL lock manager.

    Tracks the lock table, the per-transaction phase, a FIFO wait queue per
    item, and a step-by-step log (each entry records the lock-table state right
    AFTER the operation, so a section can print the full evolution)."""

    def __init__(self, variant=BASIC_2PL):
        self.variant = variant
        self.lt = LockTable()
        self.waiters: dict[str, list[tuple[int, str]]] = {}
        self.txns: dict[int, Transaction] = {}
        self.log: list[tuple[int, str, str, str, dict]] = []

    # ---- setup ----
    def add_txn(self, tid, variant=None):
        self.txns[tid] = Transaction(tid, variant or self.variant)
        return self.txns[tid]

    def reset(self):
        self.lt = LockTable()
        self.waiters = {}
        self.txns = {}
        self.log = []

    # ---- core granting rule ----
    def compatible(self, item, tid, mode):
        """May `tid` take `mode` on `item` given the OTHER current holders?"""
        for (h_tid, h_mode) in self.lt.holders(item):
            if h_tid == tid:
                continue
            if not COMPAT[(mode, h_mode)]:
                return False
        return True

    # ---- acquire ----
    def acquire(self, tid, item, mode):
        """Try to acquire `mode` on `item` for `tid`.

        Returns one of:
          'granted'           - new lock, granted in growing phase
          'granted-upgrade'   - S->X upgrade succeeded (sole holder)
          'granted-downgrade' - X->S downgrade succeeded
          'waiting'           - incompatible, queued in the wait list
          'rejected'          - 2PL violation (acquire during shrinking phase)
        """
        t = self.txns[tid]
        cur = t.held.get(item)
        if cur == mode:
            self._log(tid, item, mode, "already held")
            return "granted"
        if cur is not None:
            return self._upgrade_or_downgrade(tid, item, cur, mode)

        # 2PL phase rule: no acquires once the txn has started releasing
        if t.phase == SHRINKING:
            self._log(tid, item, mode,
                      "REJECT - shrinking phase, cannot acquire (2PL rule)")
            return "rejected"

        if self.compatible(item, tid, mode):
            self.lt.add(item, tid, mode)
            t.held[item] = mode
            self._log(tid, item, mode, f"GRANTED ({t.phase} phase)")
            return "granted"

        self.waiters.setdefault(item, []).append((tid, mode))
        self._log(tid, item, mode, "WAIT - incompatible with current holder")
        return "waiting"

    def _upgrade_or_downgrade(self, tid, item, cur, want):
        t = self.txns[tid]
        if cur == S and want == X:
            others = [(h, m) for (h, m) in self.lt.holders(item) if h != tid]
            if not others:
                self.lt.remove(item, tid)
                self.lt.add(item, tid, X)
                t.held[item] = X
                self._log(tid, item, X, "UPGRADED S->X (sole holder)")
                return "granted-upgrade"
            self.waiters.setdefault(item, []).append((tid, want))
            self._log(tid, item, want, "WAIT - upgrade blocked (other S-holder)")
            return "waiting"
        if cur == X and want == S:
            self.lt.remove(item, tid)
            self.lt.add(item, tid, S)
            t.held[item] = S
            self._log(tid, item, S, "DOWNGRADED X->S")
            return "granted-downgrade"
        return "granted"

    # ---- release ----
    def release(self, tid, item):
        """Release `tid`'s lock on `item`. In basic 2PL this is the moment the
        txn crosses into the shrinking phase."""
        t = self.txns[tid]
        if item not in t.held:
            self._log(tid, item, "-", "release: not held")
            return False
        mode = t.held.pop(item)
        self.lt.remove(item, tid)
        if t.variant == BASIC_2PL and t.phase == GROWING:
            t.phase = SHRINKING
            self._log(tid, item, mode, "RELEASED -> enters SHRINKING phase")
        else:
            self._log(tid, item, mode, "RELEASED")
        self._grant_waiters(item)
        return True

    def _grant_waiters(self, item):
        """After a release, try to admit waiting txns (FIFO, compatibility)."""
        if item not in self.waiters:
            return
        remaining = []
        for (w_tid, w_mode) in self.waiters[item]:
            t = self.txns[w_tid]
            if t.phase in (COMMITTED, ABORTED):
                continue
            if self.compatible(item, w_tid, w_mode):
                self.lt.add(item, w_tid, w_mode)
                t.held[item] = w_mode
                self._log(w_tid, item, w_mode, "GRANTED from wait queue")
            else:
                remaining.append((w_tid, w_mode))
        self.waiters[item] = remaining

    # ---- commit / abort (release everything) ----
    def commit(self, tid):
        t = self.txns[tid]
        n = len(t.held)
        granted_now = []
        for item in list(t.held):
            self.lt.remove(item, tid)
            # admit any waiters this release just unblocked (one combined log line)
            if item in self.waiters:
                keep = []
                for (w_tid, w_mode) in self.waiters[item]:
                    wt = self.txns[w_tid]
                    if wt.phase in (COMMITTED, ABORTED):
                        continue
                    if self.compatible(item, w_tid, w_mode):
                        self.lt.add(item, w_tid, w_mode)
                        wt.held[item] = w_mode
                        granted_now.append((w_tid, item, w_mode))
                    else:
                        keep.append((w_tid, w_mode))
                self.waiters[item] = keep
        t.held.clear()
        t.status = COMMITTED
        t.phase = COMMITTED
        extra = ""
        if granted_now:
            extra = "; admitted waiters: " + ", ".join(
                f"T{w}{i}{m}" for (w, i, m) in granted_now)
        self._log(tid, "-", "-", f"COMMIT - released {n} lock(s){extra}")

    def abort(self, tid):
        t = self.txns[tid]
        n = len(t.held)
        for item in list(t.held):
            self.lt.remove(item, tid)
            self._grant_waiters(item)
        t.held.clear()
        t.status = ABORTED
        t.phase = ABORTED
        self._log(tid, "-", "-", f"ABORT - released {n} lock(s), rolled back")

    # ---- logging ----
    def _log(self, tid, item, mode, action):
        self.log.append((tid, item, mode, action, self.lt.snapshot()))

    def print_log(self):
        rows = []
        for i, (tid, item, mode, action, snap) in enumerate(self.log, 1):
            it = item if item != "-" else " "
            md = mode if mode != "-" else " "
            rows.append((str(i), f"T{tid}", it, md, action, fmt_locks(snap)))
        heads = ("step", "txn", "item", "mode", "action", "lock table")
        widths = [max(len(h), max((len(r[c]) for r in rows), default=0))
                  for c, h in enumerate(heads)]
        sep = "  | " + " | ".join("-" * w for w in widths) + " |"
        print("  | " + " | ".join(h.ljust(widths[c]) for c, h in enumerate(heads)) + " |")
        print(sep)
        for r in rows:
            print("  | " + " | ".join(r[c].ljust(widths[c]) for c in range(len(heads))) + " |")


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 2. THE SECTIONS (each prints a banner + tables the guide pastes verbatim)
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: basic 2PL - growing then shrinking, with the no-reacquire rule
# ----------------------------------------------------------------------------
def section_a():
    banner("SECTION A: basic 2PL - growing (acquire) then shrinking (release)")
    print("Two-Phase Locking splits every transaction into two phases, in order:\n")
    print("  PHASE 1 - GROWING  : the txn only ACQUIRES locks.")
    print("  PHASE 2 - SHRINKING: the txn only RELEASES locks.\n")
    print("The phase boundary is the txn's FIRST release. Crossing it is one-way:")
    print("once a txn has released a lock it may NEVER acquire another. A txn that")
    print("releases then tries to acquire VIOLATES 2PL and the manager rejects it.\n")
    print("Worked run: T1 reads A, writes B, then commits. It tries to grab C AFTER")
    print("releasing A - watch the rejection.\n")

    lm = LockManager(BASIC_2PL)
    lm.add_txn(1, BASIC_2PL)
    lm.acquire(1, "A", S)        # growing
    lm.acquire(1, "B", X)        # growing
    lm.release(1, "A")           # first release -> SHRINKING
    res = lm.acquire(1, "C", S)  # shrinking -> REJECTED
    lm.commit(1)                 # releases B

    lm.print_log()
    print()
    print("Read the trace:")
    print("  steps 1-2 (GROWING) : T1 collects S(A) then X(B). Both granted.")
    print("  step 3  (release A) : first release -> T1 flips to SHRINKING.")
    print(f"  step 4  (acquire C) : {res} - T1 is in the shrinking phase, so the")
    print("                         manager REJECTS the acquire. This IS the 2PL rule.")
    print("                         (T1 should have taken C during the growing phase,")
    print("                         before releasing anything.)")
    print("  step 5  (commit)    : T1 releases its remaining X(B) and finishes.")
    assert res == "rejected"
    print("\n[check] acquire-after-release in basic 2PL -> rejected: OK")


# ----------------------------------------------------------------------------
# SECTION B: strict 2PL - X-locks held until COMMIT (no cascading aborts)
# ----------------------------------------------------------------------------
def section_b():
    banner("SECTION B: strict 2PL - X-locks held until COMMIT (no cascading aborts)")
    print("Basic 2PL has a fatal flaw: a txn RELEASES its write locks DURING the")
    print("transaction, BEFORE commit. Another txn may then READ that uncommitted")
    print("data. If the writer later ABORTS, every reader must ALSO abort - the")
    print("dreaded CASCADING ABORT.\n")
    print("STRICT 2PL fixes it: a txn's X-locks (writes) are held until COMMIT. No")
    print("other txn can read or overwrite its uncommitted writes, so cascading")
    print("aborts are impossible. (RIGOROUS 2PL goes further: ALL locks, S and X,")
    print("are held until commit - the easiest variant to build.)\n")
    print("Same schedule under both variants: T1 writes B, T2 reads B.\n")

    # ---- basic 2PL: T1 releases X(B) early; T2 reads dirty data ----
    print("--- BASIC 2PL: T1 releases X(B) mid-txn; T2 reads uncommitted B ---")
    basic = LockManager(BASIC_2PL)
    basic.add_txn(1, BASIC_2PL)
    basic.add_txn(2, BASIC_2PL)
    basic.acquire(1, "B", X)
    basic.release(1, "B")         # early release - dirty data now exposed
    basic.acquire(2, "B", S)      # T2 reads T1's UNCOMMITTED write
    basic.abort(1)                # T1 aborts -> T2 read garbage
    basic.abort(2)                # -> T2 must also abort (cascading)
    basic.print_log()
    print("  -> T1 released X(B) before commit (step 2). T2 acquired S(B) at step 3")
    print("     and READ T1's uncommitted write. When T1 aborts (step 4), T2 has")
    print("     read dirty data -> T2 must ALSO abort. CASCADING ABORT. X\n")

    # ---- strict 2PL: T1 holds X(B) until commit; T2 waits ----
    print("--- STRICT 2PL: T1 holds X(B) until COMMIT; T2 must WAIT ---")
    strict = LockManager(STRICT_2PL)
    strict.add_txn(1, STRICT_2PL)
    strict.add_txn(2, STRICT_2PL)
    strict.acquire(1, "B", X)     # T1 holds X(B) for its whole body
    r_wait = strict.acquire(2, "B", S)   # T2 blocked (X vs S incompatible)
    strict.commit(1)              # T1 commits -> releases X(B) -> T2 admitted
    strict.commit(2)
    strict.print_log()
    print("  -> T1 keeps X(B) across its whole body. T2's read at step 2 WAITS")
    print(f"     ({r_wait}). T2 only proceeds once T1 COMMITS and releases X(B), at")
    print("     which point the manager admits the waiter (step 3). T2 NEVER sees")
    print("     uncommitted data. NO cascading aborts. This is why production DBs")
    print("     (DB2, SQL Server under READ COMMITTED LOCKS / SERIALIZABLE, the 2PL")
    print("     side of MySQL/InnoDB) use strict or rigorous 2PL.\n")
    print("  | variant     | X-locks released when?      | read uncommitted? | cascading aborts? |")
    print("  |-------------|-----------------------------|-------------------|-------------------|")
    print("  | basic 2PL   | as soon as no longer needed | YES (dirty read)  | POSSIBLE          |")
    print("  | strict 2PL  | at COMMIT                   | no                | IMPOSSIBLE        |")
    print("  | rigorous 2PL| at COMMIT (S AND X)         | no                | IMPOSSIBLE        |")
    assert r_wait == "waiting"
    print("\n[check] strict 2PL: T2 waits for T1's X(B) until commit -> no dirty read: OK")


# ----------------------------------------------------------------------------
# SECTION C: lock compatibility matrix - S vs X
# ----------------------------------------------------------------------------
def section_c():
    banner("SECTION C: lock compatibility matrix - S (shared) vs X (exclusive)")
    print("Two lock modes:\n")
    print("  S (Shared)    : a READ lock. Many readers may hold S on the same item.")
    print("  X (eXclusive) : a WRITE lock. Only ONE txn may hold X; nobody else may")
    print("                   hold S or X concurrently.\n")
    print("Compatibility matrix  (rows = requested mode, cols = currently-held mode):\n")
    print("  | requested \\ held | S        | X        |")
    print("  |------------------|----------|----------|")
    print(f"  | S (read)         | {'OK' if COMPAT[(S, S)] else 'NO'}        | "
          f"{'OK' if COMPAT[(S, X)] else 'NO'}        |")
    print(f"  | X (write)        | {'OK' if COMPAT[(X, S)] else 'NO'}        | "
          f"{'OK' if COMPAT[(X, X)] else 'NO'}        |")
    print()
    print("Only S-S is compatible (co-readers coexist). Every pair that involves an")
    print("X is incompatible: a writer is mutually exclusive with everyone, including")
    print("other writers (only one writer at a time). This is the readers-writers")
    print("problem, and the matrix is the lock manager's ONLY granting rule.\n")
    assert COMPAT[(S, S)] is True
    assert COMPAT[(S, X)] is False
    assert COMPAT[(X, S)] is False
    assert COMPAT[(X, X)] is False

    print("Demonstrate each cell (fresh item per case, T1 holds first, T2 asks second):\n")
    cases = [
        ("S after S", S, S),
        ("S after X", S, X),
        ("X after S", X, S),
        ("X after X", X, X),
    ]
    print("  | case        | T1 holds | T2 wants | matrix says | T2 result |")
    print("  |-------------|----------|----------|-------------|-----------|")
    for name, m1, m2 in cases:
        lm = LockManager()
        lm.add_txn(1)
        lm.add_txn(2)
        lm.acquire(1, "R", m1)
        r = lm.acquire(2, "R", m2)
        decision = "compatible" if COMPAT[(m2, m1)] else "conflict"
        result = "granted" if r == "granted" else "WAITS"
        print(f"  | {name:<11} | {m1:<8} | {m2:<8} | {decision:<11} | {result:<9} |")
        assert (r == "granted") == COMPAT[(m2, m1)]
    print("\n[check] grant decision matches COMPAT matrix for all 4 cells: OK")


# ----------------------------------------------------------------------------
# SECTION D: lock upgrade (S->X) and why it can wait / deadlock
# ----------------------------------------------------------------------------
def section_d():
    banner("SECTION D: lock upgrade S->X - granted alone, must WAIT if shared")
    print("A txn that holds S(R) (it read R) and then decides to WRITE R must")
    print("UPGRADE its lock to X. An upgrade is special-cased:\n")
    print("  * if this txn is the SOLE S-holder of R -> upgrade granted AT ONCE")
    print("    (a txn never conflicts with itself);")
    print("  * if ANOTHER txn also holds S(R) -> the upgrade WAITS, otherwise two")
    print("    readers could both become writers and break the matrix.\n")
    print("(Downgrade X->S is the mirror move and is always safe - it only relaxes.)\n")

    # ---- scenario 1: sole S-holder, upgrade succeeds ----
    print("--- Scenario 1: T1 is the SOLE S-holder of A -> upgrade SUCCEEDS ---")
    lm1 = LockManager()
    lm1.add_txn(1)
    lm1.add_txn(2)
    lm1.acquire(1, "A", S)
    r1 = lm1.acquire(1, "A", X)   # upgrade
    lm1.print_log()
    print(f"  -> upgrade result: {r1}. T1 was the only S-holder, so the upgrade is")
    print("     applied in place (no waiting). T2 has no locks on A yet.\n")
    assert r1 == "granted-upgrade"

    # ---- scenario 2: another txn holds S, upgrade waits ----
    print("--- Scenario 2: T1 AND T2 both hold S(A) -> T1's upgrade WAITS ---")
    lm2 = LockManager()
    lm2.add_txn(1)
    lm2.add_txn(2)
    lm2.acquire(1, "A", S)        # T1 S(A)
    lm2.acquire(2, "A", S)        # T2 S(A) - two co-readers
    r2 = lm2.acquire(1, "A", X)   # T1 wants X(A) -> must wait (T2 still holds S)
    lm2.print_log()
    print(f"  -> upgrade result: {r2}. T2 also holds S(A); granting T1's X would let")
    print("     T1 write while T2 still reads -> conflict. So T1 WAITS. If T2 now")
    print("     ALSO tries to upgrade S(A)->X(A), BOTH wait on each other = an A-B")
    print("     DEADLOCK. This upgrade-deadlock is a classic 2PL hazard; DBs detect")
    print("     it (wait-for cycle) and abort one txn to break it.\n")
    assert r2 == "waiting"

    # contrast with downgrade
    print("--- Contrast: downgrade X->S always succeeds (only relaxes) ---")
    lm3 = LockManager()
    lm3.add_txn(1)
    lm3.add_txn(1)  # noop-ish
    lm3.acquire(1, "A", X)
    r3 = lm3.acquire(1, "A", S)   # downgrade
    print(f"  T1 holds X(A), asks for S(A) -> {r3} (X->S only drops strength, never")
    print("  conflicts with anyone). Some systems use this during the growing phase")
    print("  to release a write early while keeping a read.\n")
    assert r3 == "granted-downgrade"
    print("[check] sole-holder upgrade -> granted; shared-holder upgrade -> wait; "
          "downgrade -> granted: OK")


# ----------------------------------------------------------------------------
# SECTION E: lock escalation - row -> page -> table
# ----------------------------------------------------------------------------
def section_e():
    banner("SECTION E: lock escalation - many fine locks -> one coarse lock")
    print("A lock manager cannot keep one lock per row forever: 100M rows would mean")
    print("100M lock-table entries (each hundreds of bytes of RAM). Instead it")
    print("ESCALATES: when a single txn holds too many FINE-grained locks on adjacent")
    print("rows, the manager trades them in for ONE COARSER lock covering the whole")
    print("page, then the whole table. Coarser locks are cheap to track but cause")
    print("more contention (they block txns that only wanted unrelated rows).\n")
    print("Escalation ladder:\n")
    print("  row lock   -> covers 1 row")
    print("  page lock  -> covers ~8 KB (tens to hundreds of rows)")
    print("  table lock -> covers the whole table\n")
    ROWS_PER_PAGE = 5
    PAGES_PER_TABLE = 3
    TOTAL_ROWS = 15

    def page_of(row):
        return "P" + str(row // ROWS_PER_PAGE)

    print(f"Demo thresholds: ROW->PAGE at {ROWS_PER_PAGE} row-locks on one page; "
          f"PAGE->TABLE at {PAGES_PER_TABLE} page-locks. T1 locks rows 0..{TOTAL_ROWS-1}:\n")

    row_locks: list[int] = []
    page_locks: list[str] = []
    has_table = False
    events: list[tuple[str, str, str]] = []

    for row in range(TOTAL_ROWS):
        if has_table:
            events.append((f"lock row {row}", "TABLE",
                           "covered by table lock (no new entry)"))
            continue
        row_locks.append(row)
        pg = page_of(row)
        on_page = [r for r in row_locks if page_of(r) == pg]
        note = ""
        if len(on_page) >= ROWS_PER_PAGE:
            for r in on_page:
                row_locks.remove(r)
            page_locks.append(pg)
            note = f"ESCALATE {len(on_page)} row-locks on {pg} -> 1 page-lock"
            if len(page_locks) >= PAGES_PER_TABLE:
                npg = len(page_locks)
                page_locks.clear()
                row_locks.clear()
                has_table = True
                note += f"; ESCALATE {npg} page-locks -> 1 table-lock"
        tier = "TABLE" if has_table else ("PAGE" if page_locks else "ROW")
        state = []
        if row_locks:
            state.append("rows=[" + ",".join(str(r) for r in row_locks) + "]")
        if page_locks:
            state.append("pages=[" + ",".join(page_locks) + "]")
        if has_table:
            state.append("TABLE")
        events.append((f"lock row {row}", tier,
                       (note + " | " if note else "") + (" ".join(state) if state else "")))

    eheads = ("step", "op", "tier", "result")
    erows = [(str(i), op, tier, result) for i, (op, tier, result) in enumerate(events, 1)]
    ewidths = [max(len(h), max((len(r[c]) for r in erows), default=0))
               for c, h in enumerate(eheads)]
    print("  | " + " | ".join(h.ljust(ewidths[c]) for c, h in enumerate(eheads)) + " |")
    print("  | " + " | ".join("-" * ewidths[c] for c in range(len(eheads))) + " |")
    for r in erows:
        print("  | " + " | ".join(r[c].ljust(ewidths[c]) for c in range(len(eheads))) + " |")
    print()

    n_rows = len(row_locks)
    n_pages = len(page_locks)
    n_table = 1 if has_table else 0
    total = n_rows + n_pages + n_table
    print("Lock-table memory at the end:")
    print(f"  row-lock entries   : {n_rows}")
    print(f"  page-lock entries  : {n_pages}")
    print(f"  table-lock entries : {n_table}")
    print(f"  TOTAL entries      : {total}   (began as {TOTAL_ROWS} row locks)\n")
    print(f"At row {ROWS_PER_PAGE - 1} the {ROWS_PER_PAGE} row locks on P0 collapse to "
          f"ONE P0 page lock. At row {TOTAL_ROWS - 1} the {PAGES_PER_TABLE} page locks")
    print(f"collapse to ONE table lock. Memory: {TOTAL_ROWS} row entries -> {total} entry.")
    print("That is the whole point of escalation: cap the lock-table size, at the cost")
    print("of coarser (more blocking) locks. SQL Server escalates at ~5,000 locks per")
    print("transaction by default; PostgreSQL does NOT escalate (it relies on the")
    print("fast-path lock table + MVCC to avoid the contention spike).")
    assert has_table and total == 1
    print("\n[check] 15 row locks escalate to a single table lock: OK")


# ----------------------------------------------------------------------------
# SECTION F: 2PL vs MVCC - pessimistic (block) vs optimistic (multi-version)
# ----------------------------------------------------------------------------
def section_f():
    banner("SECTION F: 2PL vs MVCC - pessimistic (block) vs optimistic (version)")
    print("2PL and MVCC are the two big concurrency-control philosophies:\n")
    print("  2PL  - PESSIMISTIC: assume conflicts WILL happen, so BLOCK early. A reader")
    print("        takes an S-lock, a writer an X-lock; conflicting requests WAIT.")
    print("        Simple, strong guarantees, but throughput COLLAPSES under contention")
    print("        as txns spend most of their time blocked.\n")
    print("  MVCC - OPTIMISTIC (multi-version): keep OLD versions so readers NEVER block")
    print("        writers and writers NEVER block readers. The only blocking is on")
    print("        WRITE-WRITE (same row) - far rarer. Throughput stays HIGH under")
    print("        read-heavy or moderate load; only severe ww contention hurts it.")
    print("        PostgreSQL's DEFAULT since v6.5 (1999). 🔗 See MVCC.md.\n")
    print("Throughput model (deterministic; 100 = single-threaded maximum):\n")
    print("  contention c in [0,1] = fraction of txns touching the same hot rows.")
    print("  2PL_throughput(c)  = 100 * (1 - c)        pessimistic: linear drop")
    print("                                       (a txn waits with probability ~= c)")
    print("  MVCC_throughput(c) = 100 * (1 - c*c)      optimistic: quadratic drop")
    print("                              (only ww conflicts at probability ~= c*c)\n")
    print("  | contention c | 2PL throughput | MVCC throughput | winner | "
          "2PL blocks on   | MVCC blocks on |")
    print("  |--------------|----------------|-----------------|--------|"
          "----------------|----------------|")
    rows = []
    for pct in (0, 25, 50, 75, 100):
        c = pct / 100
        t2pl = 100 * (1 - c)
        tmvcc = 100 * (1 - c * c)
        winner = "tie" if abs(tmvcc - t2pl) < 1e-9 else ("MVCC" if tmvcc > t2pl else "2PL")
        rows.append((c, t2pl, tmvcc, winner))
        print(f"  | {c:<12.2f} | {t2pl:<14.1f} | {tmvcc:<15.1f} | {winner:<6} | "
              f"{'any conflict':<14} | {'write-write':<14} |")
    print()
    print("At c=0 both score 100 (no conflicts, no difference). As contention rises,")
    print("MVCC's curve sits strictly ABOVE 2PL's: 2PL blocks on EVERY conflict")
    print("(reader-writer AND writer-writer), MVCC only on writer-writer (~c^2). That")
    print("is why every major OLTP database moved to MVCC for the default: PostgreSQL")
    print("and Oracle (since v4, 1984), SQL Server (READ_COMMITTED_SNAPSHOT),")
    print("MySQL/InnoDB (consistent reads). 2PL survives where strong, simple")
    print("serializability is worth the blocking: DB2, and SQL Server under")
    print("SERIALIZABLE or READ COMMITTED with locking.\n")
    for c, t2pl, tmvcc, winner in rows:
        assert tmvcc >= t2pl - 1e-9
        if 0 < c < 1:
            assert tmvcc > t2pl
    print("[check] MVCC throughput >= 2PL at every contention level "
          "(strictly > for 0<c<1): OK")
    return rows


# ============================================================================
# 3. GOLD (pinned for two_phase_locking.html) - JS must reproduce these
# ============================================================================
def has_cycle(nodes, edges):
    """Kahn's topological sort: a cycle exists iff not all nodes get emitted."""
    adj = {n: [] for n in nodes}
    indeg = {n: 0 for n in nodes}
    for (a, b) in edges:
        adj[a].append(b)
        indeg[b] += 1
    queue = sorted([n for n in nodes if indeg[n] == 0])
    order = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in sorted(adj[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
                queue.sort()
    return len(order) != len(nodes)


def precedence_edges(schedule):
    """Build the precedence (serialization) graph edges for a schedule.

    schedule: list of (txn, op, item) with op in {'R','W'}. An edge Ti->Tj is
    added for each pair of CONFLICTING ops (i<j, same item, different txn)."""
    edges = set()
    for i in range(len(schedule)):
        ti, ki, ri = schedule[i]
        for j in range(i + 1, len(schedule)):
            tj, kj, rj = schedule[j]
            if ti == tj:
                continue
            if ri == rj and is_conflict(ki, kj):
                edges.add((ti, tj))
    return edges


def section_gold():
    banner("GOLD (pinned for two_phase_locking.html) - 2PL => conflict-serializable")
    print("THE 2PL THEOREM (Kung & Papadimitriou, TODS 1979): if EVERY transaction in")
    print("a schedule obeys two-phase locking, the schedule is CONFLICT-SERIALIZABLE.\n")
    print("Conflict-serializable = equivalent (by conflict order) to SOME serial")
    print("schedule. The test is the PRECEDENCE (serialization) GRAPH:\n")
    print("  * one node per transaction;")
    print("  * edge Ti -> Tj iff Ti has an EARLIER op that CONFLICTS with a LATER op")
    print("    of Tj on the same item (conflicts are R-W, W-R, W-W; R-R is NOT);")
    print("  * the schedule is conflict-serializable IFF this graph is ACYCLIC.\n")

    # A concrete 2PL schedule: 3 txns on items A,B,C. Under 2PL, T1 took X(A),X(B)
    # in its growing phase and released them in its shrinking phase before T2/T3
    # touched those items; T2 took S(A),X(C); T3 took S(B),S(C). All committed.
    good = [
        (1, "W", "A"),
        (1, "W", "B"),
        (2, "R", "A"),
        (2, "W", "C"),
        (3, "R", "B"),
        (3, "R", "C"),
    ]
    gnodes = sorted({t for (t, _, _) in good})
    gedges = precedence_edges(good)
    gcyclic = has_cycle(gnodes, gedges)

    print("Schedule A (legal under 2PL, all committed) - ops in order:")
    for k, (t, op, r) in enumerate(good, 1):
        print(f"  {k}. T{t} {op}({r})")
    print()
    print("Precedence edges (Ti->Tj for each conflicting earlier-later pair):")
    for (a, b) in sorted(gedges):
        print(f"  T{a} -> T{b}")
    print(f"\n  nodes = {gnodes} ; edges = {sorted(gedges)}")
    print(f"  cycle? {gcyclic}  ->  conflict-serializable? {not gcyclic}\n")
    assert not gcyclic, "expected the 2PL schedule to be acyclic"
    print("Topological order exists (e.g. T1 before T2 before T3), so the schedule is")
    print("equivalent to the serial run T1;T2;T3. Exactly what 2PL promises.\n")
    print("[check] precedence graph of the 2PL schedule is ACYCLIC: OK\n")

    # Contrast: a NON-2PL schedule that produces a CYCLE -> NOT serializable.
    print("Contrast - schedule B (NOT legal under 2PL): T1 and T2 each write both")
    print("A and B, interleaved so each releases-then-reacquires:\n")
    bad = [
        (1, "W", "A"),
        (2, "W", "B"),
        (1, "W", "B"),   # T1 writes B AFTER T2 did
        (2, "W", "A"),   # T2 writes A AFTER T1 did  -> cycle
    ]
    bnodes = sorted({t for (t, _, _) in bad})
    bedges = precedence_edges(bad)
    bcyclic = has_cycle(bnodes, bedges)
    for k, (t, op, r) in enumerate(bad, 1):
        print(f"  {k}. T{t} {op}({r})")
    print(f"\n  edges = {sorted(bedges)}  ;  cycle? {bcyclic}  ->  "
          f"conflict-serializable? {not bcyclic}")
    print("  The graph has the cycle T1->T2->T1. T1 must precede T2 (wrote A first)")
    print("  AND T2 must precede T1 (wrote B first) - impossible. T1 reacquiring a")
    print("  lock after releasing one is the 2PL violation that creates the cycle.")
    assert bcyclic, "expected the non-2PL schedule to be cyclic"

    print("\n--- GOLD values (pinned for two_phase_locking.html) ---")
    print(f"  compatibility matrix     : S-S={COMPAT[(S, S)]}, S-X={COMPAT[(S, X)]}, "
          f"X-S={COMPAT[(X, S)]}, X-X={COMPAT[(X, X)]}")
    print(f"  schedule A edges         : {sorted(gedges)}")
    print(f"  schedule A cyclic?       : {gcyclic}   (False = serializable)")
    print(f"  schedule B edges         : {sorted(bedges)}")
    print(f"  schedule B cyclic?       : {bcyclic}   (True = NOT serializable)")
    print(f"  2PL throughput @ c=0.5   : {100 * (1 - 0.5):.1f}")
    print(f"  MVCC throughput @ c=0.5  : {100 * (1 - 0.25):.1f}")
    print("  escalation final tier    : TABLE (1 entry from 15 row locks)")
    print("\n[check] GOLD: 2PL schedule acyclic, non-2PL schedule cyclic: OK")


# ============================================================================
# main
# ============================================================================
def main():
    print("two_phase_locking.py - reference impl. All numbers feed "
          "TWO_PHASE_LOCKING.md.")
    print("pure Python stdlib. Lock modes: S (shared/read), X (exclusive/write).")
    print("Run: python3 two_phase_locking.py")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
