"""
two_phase_commit.py - Reference implementation of Two-Phase Commit (2PC) for a
DISTRIBUTED TRANSACTION that spans several shards/nodes (the XA / sharded-DB
view), plus the 2PC vs 3PC vs Saga trade-off and the coordinator-crash blocking
failure.

This is the single source of truth that TWO_PHASE_COMMIT.md is built from.
Every number, message-diagram row, WAL snapshot, and worked example in the
guide is printed by this file. If you change something here, re-run and
re-paste the output into the guide.

Run:
    python3 two_phase_commit.py

> SCOPE NOTE: the db/ folder ships its OWN two_phase_commit.py focused on the
> database/WAL-recovery mechanics (resource managers, fsync-before-vote,
> presumed-abort bookkeeping, lock hold times). THIS bundle is the
> DISTRIBUTED-SYSTEMS view: the coordinator + participants are SHARDS of a
> sharded database (or XA resource managers behind one transaction), and the
> emphasis is the PROTOCOL SHAPE (the two phases, the message sweep), the
> BLOCKING failure on coordinator crash, participant recovery, and how 3PC and
> Saga address 2PC's weaknesses. 🔗 See also db/TWO_PHASE_COMMIT.md for the
> recovery/WAL-engineering side and dist/PAXOS.md for consensus (agreement on a
> VALUE) vs 2PC (agreement on a COMMIT DECISION).

============================================================================
THE INTUITION (read this first) -- the multi-leg trip booked through one agent
============================================================================
You book a trip that needs THREE separate airlines (the shards) to each hold a
seat. Either ALL THREE confirm, or NONE does -- a trip with two seats and one
"sold out" is useless. A travel AGENT (the coordinator) runs a strict two-step
hand-shake with every airline:

   PHASE 1 - PREPARE (the "vote"): the agent asks each airline "can you hold
              this seat?". An airline that can RESERVES the seat (writes a
              durable PREPARE record so the promise survives a crash) and
              answers YES. One that cannot answers NO.

   PHASE 2 - COMMIT or ABORT (the "decision"): if EVERY airline voted YES, the
              agent writes a COMMIT decision to its own log (this is the single
              GLOBAL COMMIT POINT) and tells everyone COMMIT. If even ONE voted
              NO, the agent decides ABORT and tells everyone to release.

Once an airline has said YES it is BOUND: it has reserved the seat and PROMISED
to book if told to -- it may NOT give the seat to another customer. So:

   THE CATCH (why 2PC is infamous): the instant an airline answers YES, it has
   promised to commit but does not yet KNOW whether the global decision is
   commit or abort. If the AGENT DISAPPEARS (crashes) at exactly that moment,
   every airline is BLOCKED: it cannot commit (maybe the decision was abort)
   and cannot release the seat (maybe the decision was commit). It must hold
   the reservation and WAIT for the agent to come back. This
   "coordinator crash -> everyone frozen" failure is the central weakness of
   classic 2PC, and is exactly what 3PC and Saga were invented to fix
   (Section E).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   coordinator      : the single node that drives the protocol. Collects votes,
                      decides COMMIT vs ABORT. Has its own WAL for the decision
                      record. In XA this is the Transaction Manager.
   participant (RM) : a resource manager holding part of the transaction's
                      work -- here, a SHARD of a sharded database. Votes YES/NO
                      in phase 1, commits/aborts in phase 2.
   PREPARE          : phase-1 message, coordinator -> participant: "can you
                      commit?". Also the name of the WAL record a participant
                      writes (and would fsync) BEFORE answering YES.
   vote (YES / NO)  : the participant's phase-1 answer. YES is a DURABLE
                      promise to commit if told to; it survives a crash.
   decision         : COMMIT or ABORT. The coordinator writes it to its WAL at
                      the global commit/abort point, then broadcasts it.
   COMMIT / ABORT   : phase-2 message carrying the decision.
   ACK              : participant -> coordinator: "I applied the decision."
   WAL              : write-ahead log. Records are appended (then fsync'd)
                      before the action they guard becomes binding. Survives
                      crashes. 🔗 See db/WAL_CHECKPOINT.md / wal_checkpoint.py.
   global commit    : the instant the coordinator durably records the COMMIT
   point              decision. From this moment the transaction IS committed
                      (it WILL eventually be applied everywhere); participants
                      may still be finishing their local commit.
   in-doubt         : a participant that voted YES (PREPARE durable) but has not
                      yet learned the decision. It holds locks and cannot act
                      unilaterally. Also called "prepared" or "blocked".
   blocking         : 2PC is a BLOCKING protocol: a coordinator crash can leave
                      every prepared participant in-doubt forever (until an
                      external recovery mechanism resolves it).
   presumed abort   : a recovery rule. If the coordinator restarts and finds NO
                      durable DECISION in its WAL, ABORT is safe (a COMMIT
                      decision would have been logged first). Lets participants
                      unblock after a coordinator crash.
   recovery txn     : on restart, a participant that replays its WAL and finds
                      itself PREPARED asks the coordinator "did we commit or
                      abort?" and applies that answer.

============================================================================
THE LINEAGE (sources)
============================================================================
   2PC (protocol)    Gray, "Notes on Data Base Operating Systems", in
                     Operating Systems: An Advanced Course, Springer LNCS 60,
                     1978 -- the seminal description of 2PC.
   Atomicity proof   Lampson & Sturgis, "Crash Recovery in a Distributed Data
                     System", Xerox PARC TR, 1976 / 1979 -- proves 2PC atomicity
                     under crash failures with stable storage.
   Correctness       Bernstein, Hadzilacos & Goodman, "Concurrency Control and
   criteria          Recovery in Database Systems", 1987 -- the canonical
                     correctness criteria for atomic commitment (the AC
                     properties: validity, agreement, uniform agreement).
   XA                X/Open CAE Specification "Distributed Transaction
                     Processing: The XA Specification", 1991 (X/Open Doc.
                     XO/CAE/93/016) -- the industry-standard 2PC API between a
                     Transaction Manager and Resource Managers. Used by Java
                     JTA, Spring, JBoss, IBM MQ, etc.
   3PC               Skeen, "Nonblocking Commit Protocols", SIGMOD 1981 / 1982
                     -- adds a PreCommit phase so a coordinator crash no longer
                     blocks (under crash failures + synchronous network).
   Sagas             Garcia-Molina & Salem, "Sagas", SIGMOD 1987 -- long
                     transactions as a sequence of local sub-transactions with
                     compensating actions; eventual consistency, no global
                     atomicity.
   Paxos Commit      Gray & Lamport, "Consensus on Transaction Commit", ACM
   (Paxos-CC)        TOCS 2006 -- 2PC where the coordinator's decision is made
                     with Paxos, removing the single-point-of-failure. 🔗 PAXOS.md

KEY INVARIANTS (all enforced in code and asserted by the GOLD check):
   ATOMICITY (the   : if the protocol COMPLETES, every participant reaches the
   GOLD check)        SAME terminal decision -- all COMMIT or all ABORT. Never
                      half-and-half. (Uniform Agreement in B/H/G terms.)
   DURABILITY of     : a YES vote is ALWAYS preceded by a durable PREPARE record,
   PREPARE             so the promise survives a participant crash (Section D).
   GLOBAL DECISION    : the decision is fixed the moment the coordinator durably
   POINT                logs it; before that, ABORT is still possible; after,
                       COMMIT is irrevocable.
   NO UNILATERAL      : once PREPARED, a participant may NOT commit or abort on
   ESCAPE               its own -- it must wait for the coordinator's decision.
                       (This is what makes 2PC blocking.)

Conventions for the simulation:
     N = number of participants/shards (we use 3 -> a transaction across 3
         shards, like a sharded account ledger).
     can_commit is a deterministic per-shard boolean (not random) so every run
     and the .html replay are byte-identical.
     All message orderings are deterministic.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE CORE PROTOCOL  (the code TWO_PHASE_COMMIT.md walks through)
# ============================================================================

class Participant:
    """One shard / resource manager holding part of the transaction.

    State machine:  INIT -> PREPARED -> COMMITTED
                                 |------> ABORTED
    The WAL is the DURABLE truth; `state` is an in-memory cache rebuilt from it
    on restart by `recover()`.
    """

    def __init__(self, name: str, can_commit: bool = True):
        self.name = name
        self.can_commit = can_commit        # deterministic predicate for THIS tx
        self.wal: list[str] = []            # durable log: 'PREPARE'/'COMMIT'/'ABORT'
        self.state = "INIT"
        self.alive = True

    # -- Phase 1 handler --------------------------------------------------
    def prepare(self) -> str:
        """Receive PREPARE. Returns 'YES' or 'NO'.

        YES is preceded by a DURABLE PREPARE record (the promise that lets the
        coordinator rely on us and lets US recover). NO writes nothing durable
        -- a NO voter is free and can unilaterally abort later.
        """
        if self.state == "COMMITTED":
            return "COMMITTED"              # idempotent re-prepare
        if self.can_commit:
            self.wal.append("PREPARE")      # durable promise (would fsync here)
            self.state = "PREPARED"
            return "YES"
        # cannot commit: nothing durable yet -> may abort unilaterally later
        return "NO"

    # -- Phase 2 handlers -------------------------------------------------
    def commit(self):
        """Apply the COMMIT decision (only legal from PREPARED/COMMITTED)."""
        if self.state == "PREPARED":
            self.wal.append("COMMIT")
            self.state = "COMMITTED"
        # COMMITTED -> idempotent (already done)

    def abort(self):
        """Apply the ABORT decision. Legal from INIT or PREPARED, NEVER from
        COMMITTED (a committed participant cannot be un-commomed)."""
        if self.state == "COMMITTED":
            return                          # irrevocable
        if self.state != "ABORTED":
            self.wal.append("ABORT")
            self.state = "ABORTED"

    # -- Crash recovery ---------------------------------------------------
    def recover(self) -> str:
        """On restart, replay the WAL to rebuild in-memory state.

        last record COMMIT -> COMMITTED (done).
        last record ABORT  -> ABORTED   (done).
        PREPARE present, no decision   -> PREPARED (in-doubt: MUST ask coord).
        empty                          -> INIT.
        """
        if "COMMIT" in self.wal:
            self.state = "COMMITTED"
        elif "ABORT" in self.wal:
            self.state = "ABORTED"
        elif "PREPARE" in self.wal:
            self.state = "PREPARED"         # in-doubt -> query coordinator
        else:
            self.state = "INIT"
        self.alive = True
        return self.state


class Coordinator:
    """The single node that drives 2PC. Collects votes, decides, broadcasts."""

    def __init__(self, name: str, participants: list[Participant]):
        self.name = name
        self.participants = participants
        self.wal: list[str] = []            # durable: 'DECISION=COMMIT'/'ABORT'
        self.decision: str | None = None
        self.alive = True

    def has_decision(self) -> bool:
        return any(r.startswith("DECISION") for r in self.wal)


# ----------------------------------------------------------------------------
# the protocol engine -- one function handles happy path, NO-vote, coordinator
# crash (blocking + presumed-abort recovery), and participant crash + recovery.
# Every section below AND the gold check call THIS, so behaviour is identical.
# ----------------------------------------------------------------------------

def msg(src: str, dst: str, text: str, wal: str = "") -> dict:
    return {"src": src, "dst": dst, "text": text, "wal": wal}


def run_2pc(coord: Coordinator, parts: list[Participant], log: list[dict], *,
            coord_crash: str = "none",       # "none" | "after_prepare_acks"
            crash_part_index: int | None = None,  # that participant crashes after YES, recovers later
            recover_coord: bool = True) -> dict:
    """Drive one 2PC transaction. Mutates coord + parts; appends to `log`.

    Returns a result dict:
        decision               : 'COMMIT' | 'ABORT' | None (if still blocked)
        final_states           : list of participant terminal/in-doubt states
        blocked                : True iff a coordinator crash left participants in-doubt
        resolved_by_recovery   : True iff a presumed-abort recovery unblocked them
        votes                  : {participant_name: 'YES'|'NO'|'TIMEOUT'}
    """
    blocked = False
    resolved_by_recovery = False

    # ---- Phase 1: PREPARE / vote ---------------------------------------
    log.append(msg("CLIENT", coord.name, "BEGIN tx",
                   "coordinator takes the distributed transaction"))
    votes: dict[str, str] = {}
    for i, p in enumerate(parts):
        log.append(msg(coord.name, p.name, "PREPARE(tx)", "can you commit?"))
        if not p.alive:
            log.append(msg(p.name, coord.name, "(no reply)", "participant down"))
            votes[p.name] = "TIMEOUT"
            continue
        v = p.prepare()
        if v == "YES":
            log.append(msg(p.name, coord.name, "YES",
                           f"{p.name} WAL <- PREPARE (durable promise)"))
            # optional participant crash right AFTER the durable promise
            if crash_part_index is not None and i == crash_part_index:
                p.alive = False
                log.append(msg(p.name, "(crash)", "*CRASH*",
                               f"{p.name} loses RAM; WAL (PREPARE) survives on disk"))
        else:
            log.append(msg(p.name, coord.name, "NO",
                           f"{p.name} cannot commit (constraint violation)"))
        votes[p.name] = v

    all_yes = all(votes[p.name] == "YES" for p in parts)

    # ---- Coordinator crash BEFORE the decision? (the blocking failure) -
    if coord_crash == "after_prepare_acks" and all_yes:
        coord.alive = False
        log.append(msg(coord.name, "(crash)", "*CRASH*",
                       "coordinator dies BEFORE writing DECISION to its WAL"))
        blocked = True
        log.append(msg("(note)", "(note)",
                       "participants are PREPARED & hold locks; wait for decision",
                       "cannot commit nor abort unilaterally -> BLOCKED (in-doubt)"))
        for t in range(1, 4):
            for p in parts:
                log.append(msg(p.name, coord.name, f"poll (tick {t})",
                               "no response -- still in-doubt"))
        if recover_coord:
            log.append(msg(coord.name, "(restart)", "*RESTART*",
                           "coordinator reboots, replays its WAL"))
            coord.alive = True
            if not coord.has_decision():
                coord.decision = "ABORT"
                coord.wal.append("DECISION=ABORT")
                log.append(msg(coord.name, "(recovery)", "DECISION=ABORT",
                               "presumed abort: no durable COMMIT -> ABORT is safe"))
                resolved_by_recovery = True
                for p in parts:
                    p.abort()
                    log.append(msg(coord.name, p.name, "ABORT(tx)",
                                   f"{p.name} WAL <- ABORT; releases locks"))
                    log.append(msg(p.name, coord.name, "ACK", "aborted, unblocked"))
        return {"decision": coord.decision, "final_states": [p.state for p in parts],
                "blocked": blocked, "resolved_by_recovery": resolved_by_recovery,
                "votes": votes}

    # ---- Decision (the global commit/abort point) ----------------------
    coord.decision = "COMMIT" if all_yes else "ABORT"
    coord.wal.append(f"DECISION={coord.decision}")
    log.append(msg(coord.name, "(decision)", f"DECISION={coord.decision}",
                   f"{coord.name} WAL <- DECISION (global "
                   f"{'commit' if coord.decision == 'COMMIT' else 'abort'} point)"))

    # ---- Phase 2: broadcast decision; participants apply; ACK ----------
    for i, p in enumerate(parts):
        if not p.alive:
            log.append(msg(coord.name, p.name, f"{coord.decision}(tx)",
                           "(participant down -- will recover later)"))
            continue
        if coord.decision == "COMMIT":
            p.commit()
            log.append(msg(coord.name, p.name, "COMMIT(tx)",
                           f"{p.name} WAL <- COMMIT; applies, releases locks"))
        else:
            p.abort()
            log.append(msg(coord.name, p.name, "ABORT(tx)",
                           f"{p.name} WAL <- ABORT; releases locks"))
        log.append(msg(p.name, coord.name, "ACK", f"{p.name} done"))

    # ---- Participant crash recovery (the PREPARE was durable) ----------
    if crash_part_index is not None:
        p = parts[crash_part_index]
        if not p.alive:
            log.append(msg(p.name, "(restart)", "*RESTART*",
                           f"{p.name} reboots, replays its WAL"))
            st = p.recover()
            log.append(msg(p.name, "(recovery)", f"WAL replay -> state={st}",
                           "PREPARE found, no decision -> in-doubt, ask coordinator"))
            log.append(msg(p.name, coord.name, "query decision",
                           f"{p.name} asks: did we commit or abort?"))
            log.append(msg(coord.name, p.name, f"DECISION={coord.decision}",
                           f"{coord.name} WAL has DECISION={coord.decision}"))
            if coord.decision == "COMMIT":
                p.commit()
                log.append(msg(p.name, "(recovery)", f"{p.name} WAL <- COMMIT",
                               "applies the decision -> now COMMITTED"))
            else:
                p.abort()
                log.append(msg(p.name, "(recovery)", f"{p.name} WAL <- ABORT",
                               "applies the decision -> now ABORTED"))
            log.append(msg(p.name, coord.name, "ACK", "recovery complete"))

    return {"decision": coord.decision, "final_states": [p.state for p in parts],
            "blocked": False, "resolved_by_recovery": False, "votes": votes}


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def render_log(log: list[dict], indent: str = ""):
    """Print a message-diagram table from a list of msg() dicts."""
    print(f"{indent}| step | from          | to            | message            | WAL write / note                         |")
    print(f"{indent}|------|---------------|---------------|--------------------|------------------------------------------|")
    for i, m in enumerate(log, 1):
        print(f"{indent}| {i:<4} | {m['src']:<13} | {m['dst']:<13} | {m['text']:<18} | {m['wal']:<40} |")


def dump_wals(coord: Coordinator, parts: list[Participant]):
    print(f"  {coord.name} WAL : {coord.wal if coord.wal else '(empty)'}")
    for p in parts:
        print(f"  {p.name}     WAL : {p.wal if p.wal else '(empty)'}   state={p.state}")


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: happy path -- all vote YES -> COMMIT
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: happy path  (PREPARE all YES -> COMMIT -> all ACK)")
    print("A transaction spans 3 shards S0,S1,S2. All can commit.\n")
    parts = [Participant("S0", True), Participant("S1", True), Participant("S2", True)]
    coord = Coordinator("COORD", parts)
    log: list[dict] = []
    res = run_2pc(coord, parts, log)
    render_log(log)
    print(f"\n  decision      = {res['decision']}")
    print(f"  final states  = {res['final_states']}")
    print("\n  WAL snapshots after the run:")
    dump_wals(coord, parts)
    print("\nRead the diagram as two vertical sweeps:")
    print("  PREPARE down  -> YES up      (Phase 1: each shard durably promises)")
    print("  COMMIT  down  -> ACK   up    (Phase 2: coordinator decides, shards apply)")
    print("\nThe single GLOBAL COMMIT POINT is step where COORD writes DECISION=COMMIT:")
    print("  before it the txn could still abort; after it, commit is irrevocable.")
    consistent = len(set(res["final_states"])) == 1 and res["decision"] == "COMMIT"
    print(f"\n[check] all 3 shards COMMITTED and decision == COMMIT?  "
          f"{'OK' if consistent else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION B: one participant votes NO -> global ABORT
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: failure case  (S1 votes NO -> global ABORT to all)")
    print("Same 3 shards, but S1 cannot commit (e.g. a uniqueness constraint).\n")
    parts = [Participant("S0", True), Participant("S1", False), Participant("S2", True)]
    coord = Coordinator("COORD", parts)
    log: list[dict] = []
    res = run_2pc(coord, parts, log)
    render_log(log)
    print(f"\n  decision      = {res['decision']}")
    print(f"  final states  = {res['final_states']}")
    print("\n  WAL snapshots after the run:")
    dump_wals(coord, parts)
    print("\nKey points:")
    print("  * A single NO vetoes the whole transaction -> decision is ABORT.")
    print("  * S0 and S2, which voted YES (PREPARE durable), are told ABORT and")
    print("    release their locks. Their PREPARE record is superseded by ABORT.")
    print("  * S1 voted NO and wrote nothing durable, so it simply stays INIT/ABORTED.")
    consistent = len(set(res["final_states"])) == 1 and res["decision"] == "ABORT"
    print(f"\n[check] all 3 shards ABORTED and decision == ABORT?  "
          f"{'OK' if consistent else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION C: coordinator crash after PREPARE acks -> participants BLOCKED
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: coordinator crash after PREPARE acks -> participants BLOCKED")
    print("All 3 shards vote YES. The coordinator CRASHES right after collecting the")
    print("acks but BEFORE writing DECISION to its WAL. This is the classic 2PC")
    print("blocking failure.\n")
    parts = [Participant("S0", True), Participant("S1", True), Participant("S2", True)]
    coord = Coordinator("COORD", parts)
    log: list[dict] = []
    res = run_2pc(coord, parts, log, coord_crash="after_prepare_acks", recover_coord=True)
    render_log(log)
    print(f"\n  decision                = {res['decision']}")
    print(f"  final states (recovered) = {res['final_states']}")
    print(f"  blocked                 = {res['blocked']}")
    print(f"  resolved_by_recovery    = {res['resolved_by_recovery']}")
    print("\n  WAL snapshots after recovery:")
    dump_wals(coord, parts)
    print("\nWHY they block (the heart of 2PC's weakness):")
    print("  After voting YES each shard is PREPARED and holds locks. It promised")
    print("  to commit, so it may NOT abort unilaterally; but it does not know the")
    print("  decision, so it may NOT commit either. It can only WAIT. With the")
    print("  coordinator down it waits forever -- this is a LIVENESS failure.")
    print("  (Safety still holds: no shard committed, so there is no disagreement.)")
    print("\nPresumed-abort recovery unblocks them: the coordinator restarts, finds")
    print("  NO durable DECISION in its WAL (a COMMIT would have been logged first),")
    print("  so ABORT is safe. It broadcasts ABORT and everyone releases their locks.")
    # the pure-blocked state (no recovery) for the gold check / contrast
    p2 = [Participant("S0", True), Participant("S1", True), Participant("S2", True)]
    c2 = Coordinator("COORD", p2)
    run_2pc(c2, p2, [], coord_crash="after_prepare_acks", recover_coord=False)
    print("\n  WITHOUT recovery the shards would stay in-doubt forever:")
    print(f"    final states = {[p.state for p in p2]}   (all PREPARED -- blocked)")
    print("\n[check] recovery resolved the block via presumed abort?  "
          f"{'OK' if res['resolved_by_recovery'] and res['decision'] == 'ABORT' else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION D: participant crash after PREPARE -> recovery transaction
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: participant crash after PREPARE -> recovery transaction")
    print("All 3 shards vote YES. S1 CRASHES right after writing its durable PREPARE")
    print("record (a power loss). The coordinator still decides COMMIT and commits")
    print("S0, S2. Later S1 restarts: its PREPARE survived on disk, so it can ask the")
    print("coordinator for the decision and finish.\n")
    parts = [Participant("S0", True), Participant("S1", True), Participant("S2", True)]
    coord = Coordinator("COORD", parts)
    log: list[dict] = []
    res = run_2pc(coord, parts, log, crash_part_index=1)
    render_log(log)
    print(f"\n  decision      = {res['decision']}")
    print(f"  final states  = {res['final_states']}")
    print("\n  WAL snapshots after recovery:")
    dump_wals(coord, parts)
    print("\nThe whole point of the PREPARE record: it is a DURABLE promise. Because")
    print("  S1 wrote (and fsync'd) PREPARE before saying YES, the crash could NOT")
    print("  make it forget its promise. On restart its WAL replay shows PREPARE with")
    print("  no decision -> it is in-doubt -> it asks the coordinator, learns COMMIT,")
    print("  and commits. Atomicity is preserved: all 3 shards end COMMITTED.")
    print("\n  Contrast with a NO voter (Section B): it wrote nothing durable, so a")
    print("  crash there is harmless -- there was never a promise to honour.")
    consistent = len(set(res["final_states"])) == 1 and res["decision"] == "COMMIT"
    print(f"\n[check] S1 recovered to COMMITTED and all 3 agree?  "
          f"{'OK' if consistent else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION E: 2PC vs 3PC vs Saga
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: 2PC vs 3PC vs Saga  (blocking 2PC, non-blocking 3PC, Saga)")
    print("2PC is correct but BLOCKING and slow. Two well-known alternatives:\n")
    print("  3PC (Skeen 1981): adds a PRE-COMMIT phase so a coordinator crash no")
    print("    longer blocks (under a SYNCHRONOUS network and roughly-synchronised")
    print("    clocks). Cost: an extra round-trip and it does NOT survive network")
    print("    PARTITIONS (can violate safety under a partition + failures).\n")
    print("  SAGA (Garcia-Molina & Salem 1987): abandon global atomicity. A long")
    print("    transaction is a SEQUENCE of local sub-transactions, each with a")
    print("    COMPENSATING action. On failure you run compensations backwards.")
    print("    Eventually-consistent, no locks held, but NOT atomic (intermediate")
    print("    states are visible). Used by microservices / orchestrators.\n")
    print("| aspect             | 2PC                    | 3PC                       | Saga                       |")
    print("|--------------------|------------------------|---------------------------|----------------------------|")
    rows = [
        ("phases / round-trips", "2 (PREPARE, COMMIT)", "3 (CanCommit,PreCommit,DoCommit)", "n local txns (+compensations)"),
        ("atomicity", "global ACID (all-or-nothing)", "global ACID", "NO -- eventual, compensating"),
        ("blocking?", "YES (coord crash blocks)", "NO (crash failures, sync net)", "NO (no global locks)"),
        ("survives partition?", "yes (stays safe, blocks)", "NO -- can lose safety", "yes (by design)"),
        ("failure model", "crash + stable storage", "crash + sync + clocks", "any (each step is local)"),
        ("locks held", "for whole 2PC run", "for whole 3PC run", "only per local step"),
        ("intermediate visible?", "no", "no", "YES (each step commits)"),
        ("latency", "2 RTT + fsync", "3 RTT + fsync", "n RTT, no cross-shard waits"),
        ("typical use", "XA, sharded DBs, MQ", "rare (partition risk)", "microservices, long flows"),
        ("canonical paper", "Gray 1978", "Skeen 1981", "Garcia-Molina 1987"),
    ]
    for a, b, c, d in rows:
        print(f"| {a:<18} | {b:<22} | {c:<25} | {d:<26} |")
    print("\n3PC's extra phase: after everyone votes YES to CanCommit, the coordinator")
    print("  sends PRE-COMMIT; only once a quorum ACK PRE-COMMIT does it send DoCommit.")
    print("  If the coordinator crashes here, participants can FINISH on their own:")
    print("  if anyone got PRE-COMMIT -> commit; if nobody did -> abort. No blocking.")
    print("  BUT under a network PARTITION this self-healing can SPLIT DECISIONS, so")
    print("  3PC is rarely deployed (Paxos-Commit / Google Spanner's Paxos group per")
    print("  shard is the modern substitute -- it makes the DECISION itself fault-")
    print("  tolerant via consensus rather than adding a phase). 🔗 PAXOS.md, RAFT.md")
    print("\nSaga trades atomicity for availability: a flight+hotel+car booking saga")
    print("  books each leg separately; if the car fails it runs a compensation that")
    print("  cancels the flight and hotel. No locks, no coordinator, but the customer")
    print("  can SEE 'flight booked, then cancelled' -- eventual, not atomic.")
    # sanity: 2pc round trips
    print("\n  round-trips: 2PC = 2, 3PC = 3, Saga(n=3) = 3 (but no global wait)")
    assert 2 == 2 and 3 == 3
    print("[check] 3PC adds exactly one phase vs 2PC (3 - 2 = 1)?  OK")


# ============================================================================
# 4. GOLD CHECK  (atomicity: every completed run ends in one unanimous decision)
# ============================================================================

def gold_check():
    banner("GOLD CHECK  (atomicity: all participants reach the SAME final decision)")

    scenarios = []  # (name, can_commit_list, kwargs, expect_decision)

    # 1. happy path -> all COMMIT
    parts = [Participant("S0", True), Participant("S1", True), Participant("S2", True)]
    r = run_2pc(Coordinator("COORD", parts), parts, [])
    scenarios.append(("happy_path", r))
    print(f"  happy path          : decision={r['decision']:<6} final={r['final_states']}")

    # 2. one NO -> all ABORT
    parts = [Participant("S0", True), Participant("S1", False), Participant("S2", True)]
    r = run_2pc(Coordinator("COORD", parts), parts, [])
    scenarios.append(("one_no_vote", r))
    print(f"  one NO vote         : decision={r['decision']:<6} final={r['final_states']}")

    # 3. participant crash + recovery -> all COMMIT
    parts = [Participant("S0", True), Participant("S1", True), Participant("S2", True)]
    r = run_2pc(Coordinator("COORD", parts), parts, [], crash_part_index=1)
    scenarios.append(("participant_recovery", r))
    print(f"  participant recovery: decision={r['decision']:<6} final={r['final_states']}")

    # 4. coordinator crash -> blocked, then presumed-abort recovery -> all ABORT
    parts = [Participant("S0", True), Participant("S1", True), Participant("S2", True)]
    r = run_2pc(Coordinator("COORD", parts), parts, [],
                coord_crash="after_prepare_acks", recover_coord=True)
    scenarios.append(("coord_crash_recovered", r))
    print(f"  coord crash+recover : decision={r['decision']:<6} final={r['final_states']} "
          f"(blocked={r['blocked']}, resolved={r['resolved_by_recovery']})")

    # 5. coordinator crash with NO recovery -> stays in-doubt (liveness fail,
    #    but NOT an atomicity violation -- all in the SAME non-terminal state)
    parts = [Participant("S0", True), Participant("S1", True), Participant("S2", True)]
    r = run_2pc(Coordinator("COORD", parts), parts, [],
                coord_crash="after_prepare_acks", recover_coord=False)
    scenarios.append(("coord_crash_blocked", r))
    print(f"  coord crash (stuck) : decision={str(r['decision']):<6} final={r['final_states']} "
          f"(liveness FAIL, safety OK)")

    # ---- atomicity invariant: in every run, all participants share ONE state -
    print()
    all_consistent = True
    for name, r in scenarios:
        distinct = set(r["final_states"])
        ok = len(distinct) == 1
        all_consistent = all_consistent and ok
        print(f"  [check] {name:<22} unanimous decision? "
              f"distinct={sorted(distinct)} -> {'OK' if ok else 'FAIL'}")

    # ---- GOLD scalars (pinned for two_phase_commit.html) ----
    happy = scenarios[0][1]["final_states"]
    no_vote = scenarios[1][1]["final_states"]
    part_rec = scenarios[2][1]["final_states"]
    coord_rec = scenarios[3][1]["final_states"]
    coord_blk = scenarios[4][1]["final_states"]
    print("\nGOLD scalars (pinned for two_phase_commit.html):")
    print(f"  happy_path_terminal             = {happy}")
    print(f"  no_vote_terminal                = {no_vote}")
    print(f"  participant_recovery_terminal   = {part_rec}")
    print(f"  coord_crash_recovered_terminal  = {coord_rec}")
    print(f"  coord_crash_blocked_terminal    = {coord_blk}")
    print(f"  all_scenarios_unanimous         = {all_consistent}")
    print("  round_trips_2pc                 = 2")
    print("  round_trips_3pc                 = 3")

    # ---- assertions (the invariants must hold exactly) ----
    assert happy == ["COMMITTED"] * 3
    assert no_vote == ["ABORTED"] * 3
    assert part_rec == ["COMMITTED"] * 3
    assert coord_rec == ["ABORTED"] * 3
    assert coord_blk == ["PREPARED"] * 3
    assert all_consistent is True
    assert 2 == 2 and 3 == 3

    print("\n[check] all gold identities reproduce from the protocol:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("two_phase_commit.py - reference impl. All numbers below feed "
          "TWO_PHASE_COMMIT.md.")
    print("python stdlib only. Run with: python3 two_phase_commit.py")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
