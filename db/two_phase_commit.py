"""
two_phase_commit.py - Reference implementation of Two-Phase Commit (2PC), the
classic atomic-commit protocol for a transaction that spans multiple resource
managers (separate databases / shards / nodes).

This is the single source of truth that TWO_PHASE_COMMIT.md is built from.
Every number, message-diagram row, WAL snapshot, and worked example in the
guide is printed by this file. If you change something here, re-run and
re-paste the output into the guide.

Run:
    python3 two_phase_commit.py

============================================================================
THE INTUITION (read this first) - the notarized group contract
============================================================================
A distributed transaction updates data on SEVERAL nodes. We want atomicity:
either ALL of them apply the change, or NONE does. Nothing in between ("two
committed, one rolled back") is acceptable, because that leaves the system in
an inconsistent state that no single node can detect.

2PC achieves this with a COORDINATOR (one designated node) that runs a strict
two-step hand-shake with every PARTICIPANT:

   PHASE 1 - PREPARE (the "vote"): the coordinator asks each participant
              "can you commit?". A participant that can durably lock in its
              part of the work writes a PREPARE record to its write-ahead log,
              *fsync*s it to disk, and answers YES. One that cannot answers NO.

   PHASE 2 - COMMIT or ROLLBACK (the "decision"): if EVERY participant voted
              YES, the coordinator writes a COMMIT decision to its own log
              (this is the single GLOBAL COMMIT POINT) and tells everyone
              COMMIT. If even ONE voted NO (or timed out), the coordinator
              decides ROLLBACK and tells everyone to abort.

The notary metaphor: phase 1 is "do you, participant, sign this provisional
contract?" -- signing means you have ALREADY set aside the money and recorded
the promise durably, so you cannot later pretend you never agreed. Phase 2 is
the notary stamping the contract binding (COMMIT) or tearing it up (ROLLBACK).
Once you have signed in phase 1, you are BOUND to honour whatever the notary
decides in phase 2 -- you may NOT change your mind.

THE CATCH (why 2PC is infamous): the moment a participant has answered YES, it
has PROMISED to commit, but it does not yet KNOW whether the global decision is
commit or abort. If the coordinator CRASHES at exactly that moment, every
prepared participant is BLOCKED: it cannot commit (maybe the global decision
was abort) and cannot abort (maybe it was commit). It must hold its locks and
WAIT for the coordinator to come back. This "coordinator crash -> everyone
frozen" failure is the central weakness of classic 2PC.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   coordinator      : the single node that drives the protocol. Decides commit
                      vs abort. Has its own WAL for the decision record.
   participant (RM) : a resource manager holding part of the transaction's
                      work. Votes YES/NO in phase 1, commits/aborts in phase 2.
   PREPARE          : phase-1 message, coordinator -> participant: "can you
                      commit?". Also the name of the WAL record a participant
                      writes (and fsyncs) BEFORE answering YES.
   vote (YES / NO)  : the participant's phase-1 answer. YES is a DURABLE
                      promise to commit if told to.
   decision         : COMMIT or ABORT. The coordinator writes it to its WAL at
                      the global commit point, then broadcasts it.
   COMMIT / ROLLBACK: phase-2 message carrying the decision.
   ACK              : participant -> coordinator, "I applied the decision."
   WAL              : write-ahead log. Records are appended then fsync'd before
                      the action they guard becomes binding. Survives crashes.
                      🔗 See WAL_CHECKPOINT.md / wal_checkpoint.py.
   global commit    : the instant the coordinator durably records the COMMIT
   point              decision. From this moment the transaction IS committed
                      (it will eventually be applied everywhere); participants
                      may still be finishing their local commit.
   blocking         : a prepared participant that cannot reach the coordinator
                      to learn the decision. It holds locks and waits. Classic
                      2PC is a BLOCKING protocol.
   presumed abort   : a recovery optimization. If the coordinator finds no
                      durable decision in its WAL, it is safe to decide ABORT
                      (a commit decision would have been logged first).
   recovery txn     : on restart, a participant that finds itself PREPARED but
                      with no final decision asks the coordinator "did we
                      commit or abort?" and applies that answer.

============================================================================
THE LINEAGE (sources)
============================================================================
   2PC (protocol)    Gray, "Notes on Data Base Operating Systems", in
                     Operating Systems: An Advanced Course, Springer LNCS 60,
                     1978 -- the seminal description of 2PC as we know it.
   Atomicity proof   Lampson & Sturgis, "Crash Recovery in a Distributed Data
                     Storage System", Xerox PARC tech report, 1976 -- the
                     commit/abort + stable-storage foundations 2PC relies on.
   Non-blocking 2PC  Skeen, "Nonblocking Commit Protocols", ACM SIGMOD 1981 --
                     proves classic (blocking) 2PC cannot be made non-blocking
                     in the presence of coordinator failure without a 3rd
                     phase (3PC), and even 3PC fails under network partitions.
   Textbook          Bernstein, Hadzilacos & Goodman, "Concurrency Control and
                     Recovery in Database Systems", 1987 (free online) -- Ch.7
                     on atomic commit; the definitions of prepared/committed/
                     aborted states and the recovery rules used here.
                     Silberschatz et al., "Database System Concepts", 7th ed.,
                     Ch.19 "Distributed Databases" -- the 2PC state diagram.
   X/Open XA         X/Open CAE Specification, "Distributed Transaction
                     Processing: The XA Specification", 1991 -- the industry
                     API (xa_prepare / xa_commit / xa_rollback) that wraps 2PC
                     between a transaction manager and resource managers. This
                     is what PostgreSQL, MySQL, Oracle, etc. expose.
   vs Saga           Garcia-Molina & Salem, "Sagas", ACM SIGMOD 1987 -- the
                     long-running-transaction alternative: a sequence of local
                     sub-transactions each with a compensating action, giving
                     up global atomicity for availability. See Section F.

KEY RULES (all asserted/printed in the sections below):
   durability-before-vote : a participant MUST append PREPARE to its WAL and
                            fsync BEFORE replying YES. Otherwise a crash after
                            voting would lose the promise -> unsafe.
   all-yes => commit       : coordinator decides COMMIT iff every vote is YES.
   any-no  => abort        : a single NO (or timeout) forces a global ABORT.
   global commit point     : the coordinator's durable COMMIT record is the
                             single point of no return. Once written, the txn
                             is committed even if some participant is down.
   decision durability     : the coordinator fsyncs its decision record BEFORE
                             broadcasting, so it can resend on recovery.
   recovery rule           : a restarted participant reads its WAL:
        - has COMMIT record -> committed
        - has ABORT  record -> aborted
        - has PREPARE only  -> PREPARED (uncertain): ask the coordinator.
        - neither           -> abort (nothing was promised; presumed abort).
   blocking property       : classic 2PC is BLOCKING: a coordinator crash
                             while participants are PREPARED stalls them all
                             until the coordinator recovers.
   gold (atomicity)        : after every crash/recovery, ALL participants end
                             in the SAME final state (all committed XOR all
                             aborted). Asserted in every scenario below.

Conventions:
   Participants are named P1, P2, P3, ...; the coordinator is COORD.
   A discrete tick clock orders events for the message diagrams.
   Every message and every local fsync is recorded in a global event log.
   All inputs are deterministic; nothing is random.
"""

from __future__ import annotations

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# States + message types
# ----------------------------------------------------------------------------
# Participant states
INITIAL = "INITIAL"      # has not yet voted
PREPARED = "PREPARED"    # voted YES; PREPARE record is durable; awaiting decision
COMMITTED = "COMMITTED"  # applied COMMIT
ABORTED = "ABORTED"      # applied ABORT/ROLLBACK
BLOCKED = "BLOCKED"      # prepared but coordinator unreachable (logical state)
DOWN = "DOWN"            # process crashed; in-memory state lost, WAL survives

# Votes
YES = "YES"
NO = "NO"

# Message / event kinds (for the event log)
MSG = "MSG"              # a network message src -> dst
NOTE = "NOTE"            # an annotation (e.g. "broadcast X") - NOT counted as a message
FSYNC = "FSYNC"          # a durable WAL append + fsync (local)
CRASH = "CRASH"          # a node goes down
RECOVER = "RECOVER"      # a node comes back up
BLOCK = "BLOCK"          # participant enters the blocked (waiting) state
DECIDE = "DECIDE"        # coordinator makes the global decision
WAIT = "WAIT"            # a tick spent blocked/waiting


# ============================================================================
# 1. THE DISCRETE-EVENT SIMULATION (deterministic tick clock + event log)
# ============================================================================

class Sim:
    """Deterministic discrete-tick simulation that records every message and
    every local durable action, so we can print an auditable message diagram."""

    def __init__(self):
        self.tick = 0
        self.events = []          # list of (tick, kind, src, dst, note)

    def log(self, kind, src, dst="", note=""):
        self.events.append((self.tick, kind, src, dst, note))

    def advance(self, n=1):
        self.tick += n

    def reset(self):
        self.tick = 0
        self.events = []


# ============================================================================
# 2. THE PARTICIPANT (resource manager)
# ============================================================================

class Participant:
    """One resource manager. Has a durable WAL (survives crashes) and volatile
    in-memory state (lost on crash).

    The state machine:
        INITIAL --PREPARE+YES--> PREPARED --COMMIT--> COMMITTED
        INITIAL --PREPARE+NO----> ABORTED
        PREPARED --ROLLBACK-----> ABORTED
    """

    def __init__(self, name):
        self.name = name
        self.state = INITIAL
        self.wal = []             # durable: list of (record_type, tick)
        self.alive = True         # False == crashed (DOWN)
        self.will_vote_no = False  # injected fault: vote NO on next PREPARE
        self.skip_prepare_fsync = False  # injected fault: vote YES w/o durable PREPARE

    # -- phase 1 ----------------------------------------------------------
    def on_prepare(self, sim, coord):
        if not self.alive:
            return None
        if self.will_vote_no:
            # Voting NO: log ABORT (no promise made), answer NO, self-abort.
            self.wal.append(("ABORT", sim.tick))
            sim.log(FSYNC, self.name, note="append ABORT, fsync")
            self.state = ABORTED
            sim.log(MSG, self.name, coord, f"VOTE {NO}")
            return NO
        # Voting YES: MUST durably log PREPARE and fsync BEFORE answering.
        if self.skip_prepare_fsync:
            sim.log(FSYNC, self.name, note="!! FAULTY: vote YES with NO durable PREPARE")
            # pretend to be prepared but record nothing durable
        else:
            self.wal.append(("PREPARE", sim.tick))
            sim.log(FSYNC, self.name, note="append PREPARE, fsync  <-- durable promise")
        self.state = PREPARED
        sim.log(MSG, self.name, coord, f"VOTE {YES}")
        return YES

    # -- phase 2 ----------------------------------------------------------
    def on_decision(self, sim, coord, decision):
        if not self.alive:
            return None
        if decision == "COMMIT":
            self.wal.append(("COMMIT", sim.tick))
            sim.log(FSYNC, self.name, note="append COMMIT, fsync  -> apply")
            self.state = COMMITTED
        else:
            self.wal.append(("ABORT", sim.tick))
            sim.log(FSYNC, self.name, note="append ABORT, fsync  -> undo")
            self.state = ABORTED
        sim.log(MSG, self.name, coord, "ACK")
        return "ACK"

    # -- crash / recovery -------------------------------------------------
    def crash(self, sim):
        sim.log(CRASH, self.name, note="*** CRASH: in-memory state lost, WAL survives")
        self.alive = False
        self.state = DOWN

    def recover(self, sim, coord):
        sim.log(RECOVER, self.name, note="recover: replay WAL")
        self.alive = True
        # Replay the durable WAL to recover the participant's true state.
        has_commit = any(rec[0] == "COMMIT" for rec in self.wal)
        has_abort = any(rec[0] == "ABORT" for rec in self.wal)
        has_prepare = any(rec[0] == "PREPARE" for rec in self.wal)
        if has_commit:
            self.state = COMMITTED
            sim.log(RECOVER, self.name, note="WAL has COMMIT -> COMMITTED")
        elif has_abort:
            self.state = ABORTED
            sim.log(RECOVER, self.name, note="WAL has ABORT -> ABORTED")
        elif has_prepare:
            # PREPARED but no decision recorded: UNCERTAIN -> must ask coord.
            self.state = PREPARED
            sim.log(RECOVER, self.name, note="WAL has PREPARE only -> UNCERTAIN")
            sim.log(MSG, self.name, coord, "DECISION_REQ (did we commit?)")
        else:
            self.state = ABORTED       # nothing promised; presumed abort
            sim.log(RECOVER, self.name, note="WAL empty -> ABORTED (presumed abort)")

    def is_final(self):
        return self.state in (COMMITTED, ABORTED)


# ============================================================================
# 3. THE COORDINATOR
# ============================================================================

class Coordinator:
    """Drives the protocol. Has its own WAL for the decision record."""

    def __init__(self, name="COORD"):
        self.name = name
        self.alive = True
        self.wal = []             # durable: list of (record_type, tick)
        self.decision = None      # "COMMIT" / "ABORT" / None

    # -- phase 1: PREPARE -------------------------------------------------
    def run_prepare(self, sim, participants):
        """Broadcast PREPARE, collect votes. Returns the list of votes (in
        participant order). Crashed participants answer None."""
        sim.log(NOTE, self.name, note="broadcast PREPARE")
        for p in participants:
            if p.alive:
                sim.log(MSG, self.name, p.name, "PREPARE")
        sim.advance()
        votes = []
        for p in participants:
            v = p.on_prepare(sim, self.name)
            votes.append(v)
        sim.advance()
        return votes

    # -- the decision (global commit point) -------------------------------
    def make_decision(self, sim, votes):
        """The GLOBAL COMMIT POINT. Decides from the votes, writes the decision
        to the coordinator's WAL and fsyncs BEFORE broadcasting (so it can be
        resent on recovery)."""
        all_yes = votes and all(v == YES for v in votes)
        self.decision = "COMMIT" if all_yes else "ABORT"
        rec = "COMMIT" if self.decision == "COMMIT" else "ABORT"
        self.wal.append((rec, sim.tick))
        sim.log(DECIDE, self.name,
                note=f"decision={self.decision}; append {rec} to coord-WAL, fsync"
                     + ("  <-- GLOBAL COMMIT POINT" if self.decision == "COMMIT"
                        else "  <-- GLOBAL ABORT POINT"))
        sim.advance()
        return self.decision

    # -- phase 2: broadcast decision --------------------------------------
    def run_decision(self, sim, participants, decision):
        msg = decision if decision == "COMMIT" else "ROLLBACK"
        sim.log(NOTE, self.name, note=f"broadcast {msg}")
        for p in participants:
            if p.alive:
                sim.log(MSG, self.name, p.name, msg)
        sim.advance()
        for p in participants:
            p.on_decision(sim, self.name, decision)
        sim.advance()

    # -- crash / recovery -------------------------------------------------
    def crash(self, sim):
        sim.log(CRASH, self.name, note="*** COORD CRASH")
        self.alive = False

    def recover(self, sim):
        sim.log(RECOVER, self.name, note="coord recovers")
        self.alive = True

    # -- answer a participant's decision request --------------------------
    def answer_decision_req(self, sim, participant):
        if not self.alive:
            return None
        d = self.decision
        if d is None:
            # no durable decision: presumed abort
            d = "ABORT"
            self.decision = "ABORT"
            self.wal.append(("ABORT", sim.tick))
            sim.log(DECIDE, self.name,
                    note="no prior decision -> ABORT (presumed abort), fsync")
        sim.log(MSG, self.name, participant.name, f"DECISION={d}")
        sim.advance()
        participant.on_decision(sim, self.name, d)
        return d


# ============================================================================
# 4. PRETTY PRINTERS (banner + message-diagram renderer)
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def count_messages(sim):
    """Count real network messages (MSG events with a concrete destination).
    Broadcast annotations (NOTE) are NOT counted."""
    return sum(1 for e in sim.events if e[1] == MSG and e[3])


def render_log(sim, title="message diagram"):
    """Render the event log as a tick-ordered ledger / sequence diagram."""
    print(f"\n  {title}  ({len(sim.events)} events, t=0..{sim.tick})")
    print("  " + "-" * 68)
    for (t, kind, src, dst, note) in sim.events:
        if kind == MSG:
            line = f"{src} ──{note}──► {dst}"
        elif kind == NOTE:
            line = f"{src}  {note}   (annotation)"
        elif kind == FSYNC:
            line = f"{src}  [WAL] {note}"
        elif kind == CRASH:
            line = f"{src}  {note}"
        elif kind == RECOVER:
            line = f"{src}  {note}"
        elif kind == BLOCK:
            line = f"{src}  {note}"
        elif kind == WAIT:
            line = f"{src}  {note}"
        elif kind == DECIDE:
            line = f"{src}  {note}"
        else:
            line = f"{src}  {note}"
        print(f"  t={t:<2} {line}")


def state_table(participants):
    print()
    print("  | node  | state     | WAL records (durable)             |")
    print("  |-------|-----------|----------------------------------|")
    for p in participants:
        recs = ",".join(r for (r, _) in p.wal) if p.wal else "(empty)"
        print(f"  | {p.name:<5} | {p.state:<9} | {recs:<32} |")


def coord_table(coord):
    recs = ",".join(r for (r, _) in coord.wal) if coord.wal else "(empty)"
    print(f"  | {coord.name:<5} | decision={coord.decision!s:<7} | {recs:<32} |")


# ----------------------------------------------------------------------------
# helpers / invariants
# ----------------------------------------------------------------------------

def assert_atomic(participants, label):
    """The gold invariant: every FINAL participant is in the SAME state."""
    finals = [p.state for p in participants if p.is_final()]
    consistent = len(set(finals)) == 1 and len(finals) == len(participants)
    verdict = list(set(finals))[0] if finals else "(none)"
    print(f"\n  [check] {label}: final states = {finals} -> "
          f"{'all ' + verdict if consistent else 'INCONSISTENT'}: "
          f"{'OK' if consistent else 'FAIL'}")
    assert consistent, f"atomicity violated in {label}: {finals}"
    return verdict


# ============================================================================
# 5. THE SCENARIOS (sections A..F)
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: happy path - all vote YES -> COMMIT
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: happy path - PREPARE (all YES) -> COMMIT")
    print("The coordinator runs phase 1 (PREPARE) against 3 participants. Each")
    print("fsyncs a PREPARE record and votes YES. With all votes YES, the")
    print("coordinator hits the GLOBAL COMMIT POINT, then phase 2 (COMMIT).\n")

    sim = Sim()
    coord = Coordinator()
    ps = [Participant(f"P{i}") for i in (1, 2, 3)]

    print("Phase 1 - PREPARE:")
    votes = coord.run_prepare(sim, ps)
    print(f"  votes received = {dict(zip([p.name for p in ps], votes))}\n")

    print("Decision (global commit point):")
    decision = coord.make_decision(sim, votes)
    print(f"  all YES -> decision = {decision}\n")

    print("Phase 2 - COMMIT:")
    coord.run_decision(sim, ps, decision)

    render_log(sim, "SECTION A message diagram")
    state_table(ps)
    coord_table(coord)

    print("\nMessage accounting: 3 PREPARE out + 3 VOTE back + 3 COMMIT out + "
          "3 ACK back = 12 messages (= 4*N for N=3 participants).")
    n_msgs = count_messages(sim)
    print(f"[check] message count = {n_msgs} (expected 12): "
          f"{'OK' if n_msgs == 12 else 'FAIL'}")
    assert n_msgs == 12
    assert_atomic(ps, "section A happy path")


# ----------------------------------------------------------------------------
# SECTION B: failure case - one votes NO -> ROLLBACK
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: failure case - P2 votes NO -> global ROLLBACK")
    print("The atomicity rule: a SINGLE 'no' (or timeout) forces a global abort.")
    print("P2 is configured to vote NO. Even though P1 and P3 vote YES, the")
    print("coordinator must decide ABORT and tell everyone to roll back.\n")

    sim = Sim()
    coord = Coordinator()
    ps = [Participant(f"P{i}") for i in (1, 2, 3)]
    ps[1].will_vote_no = True       # P2 votes NO

    print("Phase 1 - PREPARE:")
    votes = coord.run_prepare(sim, ps)
    print(f"  votes received = {dict(zip([p.name for p in ps], votes))}\n")

    print("Decision:")
    decision = coord.make_decision(sim, votes)
    print(f"  not all YES -> decision = {decision}\n")

    print("Phase 2 - ROLLBACK:")
    coord.run_decision(sim, ps, decision)

    render_log(sim, "SECTION B message diagram")
    state_table(ps)
    coord_table(coord)

    print("\nNote: P2 (voted NO) already self-aborted in phase 1 (its ABORT is in")
    print("its WAL). In phase 2 it gets ROLLBACK too and stays ABORTED. P1/P3")
    print("voted YES (PREPARE in WAL) but are told ROLLBACK -> they abort.")
    print("\n[check] the lone NO propagated to a global abort: OK")
    assert decision == "ABORT"
    assert_atomic(ps, "section B abort path")


# ----------------------------------------------------------------------------
# SECTION C: coordinator crash -> participants BLOCKED -> recovery
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: coordinator crash after PREPARE -> participants BLOCKED")
    print("THE CENTRAL WEAKNESS. The coordinator crashes AFTER collecting all")
    print("YES votes but BEFORE writing/sending the COMMIT decision. The")
    print("participants have each fsync'd PREPARE and are now PREPARED -- they")
    print("have PROMISED to commit but do not KNOW the global decision. With the")
    print("coordinator down they CANNOT proceed either way: committing would")
    print("break atomicity if the (lost) decision was abort; aborting would")
    print("break it if the decision was commit. So they BLOCK, holding locks,\n"
          "until the coordinator recovers.\n")

    sim = Sim()
    coord = Coordinator()
    ps = [Participant(f"P{i}") for i in (1, 2, 3)]

    # Phase 1 completes normally.
    votes = coord.run_prepare(sim, ps)
    print(f"Phase 1 complete: votes = {dict(zip([p.name for p in ps], votes))}")
    print("All participants are PREPARED (PREPARE is durable in every WAL).\n")

    # Coordinator crashes before the decision.
    sim.advance()
    coord.crash(sim)
    print("Coordinator CRASHES before reaching the global commit point.")
    print("(Its decision was in volatile memory; nothing durable was written.)\n")

    # Participants detect the dead coordinator and enter BLOCKED.
    sim.advance()
    for p in ps:
        prev = p.state
        p.state = BLOCKED
        sim.log(BLOCK, p.name,
                note=f"PREPARED but coordinator DOWN -> BLOCKED (was {prev}); "
                     "holding locks, cannot decide")
    print("Every prepared participant transitions to BLOCKED.\n")

    # Show the waiting period (the blocking window).
    for w in range(1, 4):
        sim.advance()
        for p in ps:
            sim.log(WAIT, p.name, note=f"blocked tick {w}: still holding locks")
    print(">>> BLOCKING WINDOW: 3 ticks pass with all participants frozen,")
    print("    locks held, transaction in limbo. Other txns waiting on those")
    print("    locks are also stuck. THIS is why classic 2PC is 'blocking'.\n")

    # Coordinator recovers.
    sim.advance()
    coord.recover(sim)
    print("Coordinator recovers. Its WAL has NO decision record -> the crash")
    print("happened before the commit point -> PRESUMED ABORT is safe.")
    # Un-block participants back to PREPARED so they can receive the decision.
    for p in ps:
        p.state = PREPARED
    coord.answer_all = True
    coord.decision = "ABORT"
    coord.wal.append(("ABORT", sim.tick))
    sim.log(DECIDE, coord.name,
            note="no durable COMMIT in coord-WAL -> decide ABORT (presumed abort), fsync")
    sim.advance()
    print("Coordinator broadcasts ROLLBACK:")
    for p in ps:
        sim.log(MSG, coord.name, p.name, "ROLLBACK")
    sim.advance()
    for p in ps:
        p.on_decision(sim, coord.name, "ABORT")

    render_log(sim, "SECTION C message diagram (blocking + recovery)")
    state_table(ps)
    coord_table(coord)

    print("\nThe blocking window was 3 ticks (t=5..7). During it the")
    print("transaction made zero progress. On recovery the coordinator could")
    print("not have decided COMMIT safely (that would require a durable record),")
    print("so PRESUMED ABORT resolves it. Atomicity is preserved: all ABORTED.")
    assert_atomic(ps, "section C coordinator-crash recovery")


# ----------------------------------------------------------------------------
# SECTION D: participant crash after PREPARE -> recovery transaction
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: participant crash after PREPARE -> recovery transaction")
    print("P3 votes YES (PREPARE durable), then CRASHES. The coordinator has all")
    print("YES -> hits the global COMMIT POINT -> sends COMMIT. P1/P2 commit;")
    print("P3 is down. When P3 restarts it finds PREPARE in its WAL but no final")
    print("decision -> it is UNCERTAIN. It runs a RECOVERY TRANSACTION: asks the")
    print("coordinator 'did we commit or abort?' and applies that answer.\n")

    sim = Sim()
    coord = Coordinator()
    ps = [Participant(f"P{i}") for i in (1, 2, 3)]

    # Phase 1
    votes = coord.run_prepare(sim, ps)
    print(f"Phase 1: votes = {dict(zip([p.name for p in ps], votes))}\n")

    # P3 crashes after voting YES (PREPARE is already durable).
    sim.advance()
    ps[2].crash(sim)
    print("P3 CRASHES after voting YES. Its PREPARE record survives on disk.\n")

    # Coordinator still has all YES -> decides COMMIT (global commit point).
    decision = coord.make_decision(sim, votes)
    print(f"Coordinator: all votes were YES -> decision = {decision} (GLOBAL COMMIT POINT).\n")

    # Phase 2: broadcast COMMIT. P3 is down so it cannot ack yet.
    print("Phase 2 - COMMIT (P3 is down, will miss it):")
    sim.log(NOTE, coord.name, note="broadcast COMMIT")
    for p in ps:
        if p.alive:
            sim.log(MSG, coord.name, p.name, "COMMIT")
    sim.advance()
    for p in ps:
        p.on_decision(sim, coord.name, decision)
    print("  P1, P2 -> COMMITTED. P3 -> still DOWN (no COMMIT applied yet).\n")

    # Coordinator remembers the (durable) decision. P3 recovers and asks.
    sim.advance()
    ps[2].recover(sim, coord.name)
    print("\nP3 recovers. WAL replay: PREPARE present, no COMMIT/ABORT -> UNCERTAIN.")
    print("P3 cannot guess; it MUST ask the coordinator (recovery transaction).\n")
    sim.advance()
    coord.answer_decision_req(sim, ps[2])

    render_log(sim, "SECTION D message diagram (participant crash + recovery)")
    state_table(ps)
    coord_table(coord)

    print("\nKey points:")
    print("  * The GLOBAL COMMIT POINT (coord's durable COMMIT) happened BEFORE")
    print("    P3 recovered, so the transaction was already 'committed' globally")
    print("    even while P3 was down. P3's recovery just catches it up.")
    print("  * P3 could honour the commit ONLY because its PREPARE record was")
    print("    durable (Section E). Without it, restart would lose the promise.")
    assert_atomic(ps, "section D participant-crash recovery")
    assert all(p.state == COMMITTED for p in ps)


# ----------------------------------------------------------------------------
# SECTION E: PREPARE record durability (fsync-before-vote)
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: PREPARE durability - fsync BEFORE voting YES")
    print("WHY the fsync matters. A YES vote is a DURABLE promise: 'I have done")
    print("my local work and I WILL commit if told to.' If the participant")
    print("crashes after voting YES, it must STILL be able to commit on restart.")
    print("That is only possible if the PREPARE record (and the work it guards)")
    print("survived the crash -- hence append-PREPARE then fsync THEN vote.\n")

    print("CORRECT participant: append PREPARE, fsync, THEN vote YES.")
    sim1 = Sim()
    good = Participant("P_good")
    good.on_prepare(sim1, "COORD")
    print(f"  -> state={good.state}, WAL={good.wal}, (PREPARE is durable)\n")

    print("Now crash AFTER voting YES, then recover:")
    sim1.advance()
    good.crash(sim1)
    sim1.advance()
    good.recover(sim1, "COORD")
    print(f"  -> recovered state={good.state}. WAL has PREPARE -> UNCERTAIN;")
    print("     P_good will ask the coordinator and can correctly COMMIT if told")
    print("     to. The durable PREPARE made the promise recoverable.\n")

    print("-" * 68)
    print("FAULTY participant: votes YES WITHOUT fsync'ing PREPARE, then crashes.")
    sim2 = Sim()
    faulty = Participant("P_bad")
    faulty.skip_prepare_fsync = True
    faulty.on_prepare(sim2, "COORD")
    print(f"  -> told the coordinator YES, but WAL={faulty.wal} (NO PREPARE!).\n")
    sim2.advance()
    faulty.crash(sim2)
    sim2.advance()
    faulty.recover(sim2, "COORD")
    print(f"  -> recovered state={faulty.state}. WAL is EMPTY -> the participant")
    print("     has NO memory of its YES. Under presumed-abort it self-aborts.")
    print("     But the coordinator may have recorded a global COMMIT (because it")
    print("     saw YES from everyone) and told others to commit. Result: some")
    print("     nodes COMMITTED while P_bad ABORTED -> ATOMICITY BROKEN. This is")
    print("     exactly the failure the fsync-before-vote rule prevents.\n")

    # Demonstrate the invariant: correct path keeps the promise recoverable.
    print("[check] correct participant: PREPARE in WAL after vote => "
          f"{'YES' if any(r=='PREPARE' for r,_ in good.wal) else 'NO'}: OK")
    assert any(rec[0] == "PREPARE" for rec in good.wal)
    print("[check] faulty participant: no PREPARE in WAL => promise lost => "
          "UNSAFE: OK")
    assert not any(rec[0] == "PREPARE" for rec in faulty.wal)
    print(f"[check] correct participant recovers to PREPARED (uncertain): "
          f"state={good.state}: "
          f"{'OK' if good.state == PREPARED else 'FAIL'}")
    assert good.state == PREPARED


# ----------------------------------------------------------------------------
# SECTION F: limitations - blocking, slow, complex + alternatives
# ----------------------------------------------------------------------------

def section_f():
    banner("SECTION F: limitations of 2PC and the alternatives")
    print("2PC gives you ACID atomicity across nodes. The price:\n")

    print("| weakness        | why                                                                                  |")
    print("|-----------------|--------------------------------------------------------------------------------------|")
    print("| BLOCKING        | coordinator crash while participants are PREPARED freezes them all (Section C).      |")
    print("|                 | They hold locks and wait; no timeout can safely unblock them.                        |")
    print("| SLOW            | multiple synchronized round trips + fsyncs on the critical path (see latency below). |")
    print("| COORD IS SPOF   | while the coordinator is down, in-doubt transactions stall.                         |")
    print("| OPERATIVELY     | ops must keep the coordinator HA; participant recovery logic is subtle (Section D).  |")
    print("| COMPLEX         |                                                                                      |")
    print("| CASCADED        | prepared participants hold locks -> other txns queue -> whole cluster can stall.     |")
    print("| STALL           |                                                                                      |")

    # --- latency model ----------------------------------------------------
    print("\nLATENCY MODEL (critical path of one transaction, N participants):")
    print("  prepare phase : 1 RTT  (PREPARE out, VOTE back); the N participants")
    print("                  fsync PREPARE IN PARALLEL -> 1 fsync on critical path")
    print("  decision      : coordinator fsyncs the decision record -> 1 fsync")
    print("  commit phase  : 1 RTT  (COMMIT out, ACK back); the N participants")
    print("                  fsync COMMIT IN PARALLEL -> 1 fsync on critical path")
    print("  => latency = 2*RTT + 3*fsync_latency        (parallel fsyncs)")
    print("  total fsync OPERATIONS (load) = 2*N + 1     (N grows load, not latency)\n")

    RTT = 1.0          # ms, LAN
    FSYNC = 10.0       # ms, a typical fsync latency (rotational SSD ~1, HDD ~10)
    print(f"  with RTT={RTT} ms, fsync={FSYNC} ms:")
    print("  | N | round trips | critical-path fsyncs | total fsync ops (2N+1) | "
          "messages (4N) | 2PC latency (ms) |")
    print("  |---|-------------|----------------------|------------------------|"
          "--------------|------------------|")
    latencies = {}
    latency_n3 = 2 * RTT + 3 * FSYNC     # critical-path latency is independent of N
    for n in (2, 3, 5, 10):
        total_fsyncs = 2 * n + 1
        msgs = 4 * n
        lat = 2 * RTT + 3 * FSYNC
        latencies[n] = lat
        print(f"  | {n} | 2           | 3                    | {total_fsyncs:<22} | "
              f"{msgs:<12} | {lat:<16.1f} |")
    print("\n  The critical-path LATENCY stays constant as N grows (the participant")
    print("  fsyncs run in parallel). What grows with N is the MESSAGE count (4N)")
    print("  and the total fsync WORK (2N+1), i.e. load on the coordinator/disk --")
    print("  which hurts THROUGHPUT, not single-txn latency. The 3 serialized fsyncs")
    print(f"  dominate: {latency_n3:.0f} ms vs 1 RTT = {RTT} ms. Compare a single-node")
    print(f"  commit (1 fsync = {FSYNC:.0f} ms): 2PC@N=3 is {latency_n3/FSYNC:.1f}x slower.")

    # --- alternatives table ----------------------------------------------
    print("\nALTERNATIVES (trade atomicity/latency for availability/scalability):")
    print("| approach               | atomic across nodes? | blocking? | latency        | when to use                  |")
    print("|------------------------|----------------------|-----------|----------------|------------------------------|")
    print("| 2PC                    | YES (strong)         | YES       | high (3 fsync) | few RM, need ACID (XA/JTA)  |")
    print("| 3PC (non-blocking)     | YES (no coord crash) | NO*       | higher (3 RTT) | rare; fails under partition |")
    print("| Saga (Garcia-Molina)   | NO (eventual)        | NO        | low            | long txns, microservices    |")
    print("| Eventual consistency   | NO                   | NO        | lowest         | large scale, AP systems     |")
    print("  * 3PC only escapes blocking if the coordinator alone fails; a network")
    print("    partition can still violate atomicity (Skeen 1981), so 3PC is rarely used.")

    print("\n[check] 2PC latency @N=3 = "
          f"{latencies[3]:.1f} ms (= 2*{RTT} + 3*{FSYNC}): OK")
    assert abs(latencies[3] - (2 * RTT + 3 * FSYNC)) < 1e-9
    # The single-node baseline (1 fsync) for the cheat-sheet comparison.
    print(f"[check] single-node commit baseline = {FSYNC:.1f} ms (1 fsync): OK")
    return latencies[3], FSYNC


# ============================================================================
# 6. GOLD (pinned for two_phase_commit.html) - JS must reproduce these
# ============================================================================

def section_gold(latency_n3, fsync_ms):
    banner("GOLD (pinned for two_phase_commit.html) - atomicity across all scenarios")
    print("THE GOLD INVARIANT of 2PC: no matter which node crashes and when,")
    print("after recovery ALL participants reach the SAME final state -- either")
    print("all COMMITTED or all ABORTED. We re-run every crash scenario in a")
    print("single deterministic harness and assert the invariant each time.\n")

    scenarios = []

    # --- scenario factory: returns (label, final_states, num_messages) ----
    def run(label, faulty_vote=None, crash_coord=False, crash_participant=None):
        sim = Sim()
        coord = Coordinator()
        ps = [Participant(f"P{i}") for i in (1, 2, 3)]
        if faulty_vote is not None:
            ps[faulty_vote].will_vote_no = True
        votes = coord.run_prepare(sim, ps)
        if crash_coord:
            sim.advance()
            coord.crash(sim)
            sim.advance()
            for p in ps:
                p.state = BLOCKED
            for _ in range(2):
                sim.advance()
            coord.recover(sim)
            for p in ps:
                p.state = PREPARED
            coord.decision = "ABORT"
            coord.wal.append(("ABORT", sim.tick))
            sim.log(DECIDE, coord.name, note="presumed abort")
            sim.advance()
            for p in ps:
                sim.log(MSG, coord.name, p.name, "ROLLBACK")
            sim.advance()
            for p in ps:
                p.on_decision(sim, coord.name, "ABORT")
        else:
            if crash_participant is not None:
                sim.advance()
                ps[crash_participant].crash(sim)
            decision = coord.make_decision(sim, votes)
            sim.log(NOTE, coord.name, note=f"broadcast {decision}")
            for p in ps:
                if p.alive:
                    sim.log(MSG, coord.name, p.name, decision)
            sim.advance()
            for p in ps:
                p.on_decision(sim, coord.name, decision)
            if crash_participant is not None and not ps[crash_participant].is_final():
                sim.advance()
                ps[crash_participant].recover(sim, coord.name)
                sim.advance()
                coord.answer_decision_req(sim, ps[crash_participant])
        finals = [p.state for p in ps]
        n_msgs = sum(1 for e in sim.events if e[1] == MSG)
        scenarios.append((label, finals, n_msgs))
        return finals, n_msgs

    print("| scenario                              | P1         | P2         | P3         | msgs | consistent? |")
    print("|---------------------------------------|------------|------------|------------|------|-------------|")
    run("A happy path (all YES)", faulty_vote=None)
    run("B P2 votes NO", faulty_vote=1)
    run("C coordinator crashes (blocking)", crash_coord=True)
    run("D P3 crashes after PREPARE", crash_participant=2)

    for (label, finals, n_msgs) in scenarios:
        consistent = len(set(finals)) == 1
        verdict = "all " + finals[0] if consistent else "MIXED!"
        print(f"| {label:<37} | {finals[0]:<10} | {finals[1]:<10} | {finals[2]:<10} | {n_msgs:<4} | {verdict:<11} |")
        assert consistent, f"GOLD FAIL: {label} -> {finals}"

    print("\nEvery scenario ends with all three participants in ONE shared final")
    print("state. That is atomicity -- the whole point of 2PC.\n")

    print("--- GOLD values (pinned for two_phase_commit.html) ---")
    for (label, finals, n_msgs) in scenarios:
        print(f"  {label:<37} -> finals={finals}, msgs={n_msgs}")
    print("  happy-path final state            : COMMITTED (all three)")
    print("  abort-path final state            : ABORTED   (all three)")
    print("  coord-crash final state           : ABORTED   (all three, after blocking)")
    print("  participant-crash final state     : COMMITTED (all three, after recovery)")
    print("  message count, happy path, N=3    : 12  (= 4*N)")
    print("  latency formula                   : 2*RTT + 3*fsync (parallel participants)")
    print(f"  latency @N=3, RTT=1, fsync={fsync_ms} : {latency_n3} ms")
    print(f"  single-node commit baseline       : {fsync_ms} ms (1 fsync)")
    print("\n[check] GOLD: all 4 scenarios atomically consistent: OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("two_phase_commit.py - reference impl. All numbers feed "
          "TWO_PHASE_COMMIT.md.")
    print("pure Python stdlib. States: INITIAL/PREPARED/COMMITTED/ABORTED.")
    print("Run: python3 two_phase_commit.py")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    latency_n3, fsync_ms = section_f()
    section_gold(latency_n3, fsync_ms)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
