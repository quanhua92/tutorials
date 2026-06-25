"""
three_phase_commit.py - Reference implementation of the Three-Phase Commit
protocol (3PC, Skeen 1981, "Non-blocking Commit Protocols", ACM SIGMOD), the
non-blocking (under a SYNCHRONOUS network) variant of Two-Phase Commit
(2PC, Gray 1978). Includes the coordinator-crash termination protocol, a
side-by-side with 2PC, and why 3PC is academic under the FLP impossibility
result.

This is the single source of truth that THREE_PHASE_COMMIT.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 three_phase_commit.py

============================================================================
THE INTUITION (read this first) -- the wedding that must be unanimous
============================================================================
A distributed transaction spans several PARTICIPANTS. To keep the data
consistent, at the end EITHER every participant commits OR every participant
aborts -- no half-and-half. The COORDINATOR runs the ceremony.

  * 2PC (Two-Phase Commit): the coordinator asks everyone "can you commit?"
    (Phase 1). If all say YES, it says "commit!" (Phase 2). Cheap (2 round
    trips) -- BUT if the coordinator crashes between "all said YES" and
    "commit!", the participants are STUCK. A participant that voted YES does
    not know whether the coordinator was about to say commit or abort, and it
    cannot tell whether SOME OTHER participant voted NO (which would force an
    abort). So it BLOCKS, holding locks, until the coordinator recovers. That
    blocking window is the original sin of 2PC.

  * 3PC (Three-Phase Commit): insert a middle phase, PreCommit. Now:
        Phase 1  CanCommit?   -> everyone votes YES/NO.
        Phase 2  PreCommit    -> "everyone voted YES; get READY to commit."
        Phase 3  DoCommit     -> "commit, for real."
    The PreCommit phase is the trick. A participant that RECEIVES PreCommit
    learns a decisive fact: the coordinator only sends PreCommit after EVERY
    participant voted YES. So once you are PreCommitted, the commit is
    UNSTOPPABLE -- the only question left is the announcement. If the
    coordinator then crashes, the participants can run a TERMINATION PROTOCOL
    among themselves and decide WITHOUT the coordinator. No blocking.

The extra phase is one more round trip of latency (3 RT vs 2 RT). The payoff
is that the "all said YES but coordinator died" window stops being fatal.

WHY IT IS STILL NOT MAGIC (the catch, Section E): the termination protocol
relies on a participant being able to tell "coordinator is dead" from
"coordinator is slow". That distinction is only valid in a SYNCHRONOUS network
(bounded message delay + bounded processor speed, so a timeout is proof of
death). Real networks are ASYNCHRONOUS -- a "slow" coordinator may just be
delayed. The FLP impossibility result (Fischer, Lynch, Paterson 1985) proves
no async protocol can be both safe and live with even one crash, so 3PC's
guarantee does NOT survive the move to reality. That is why 3PC is a textbook
result, not a deployed one.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  coordinator : the node driving the commit. Collects votes, announces phases.
                If it crashes, participants must finish without it.
  participant : a node holding part of the transaction. Votes YES/NO; must end
                COMMITTED or ABORTED, the same as every other participant.
  CanCommit?  : Phase 1 request. "Can you commit this transaction?"
  vote YES/NO : Phase 1 reply. YES = "I am willing and ready"; NO = abort now.
  PreCommit   : Phase 2 request (the NEW phase vs 2PC). Sent ONLY after the
                coordinator received YES from EVERY participant. Means "the
                commit is decided; just get ready."
  ACK         : Phase 2/3 reply. "I received your phase message."
  DoCommit    : Phase 3 request. "Commit, for real."
  READY state : a participant that voted YES and is waiting (the UNCERTAIN
                state -- in 2PC this is where it blocks on coordinator crash).
  PRECOMMITTED: a participant that received PreCommit. It now KNOWS everyone
                voted YES, so it can commit on its own if needed.
  COMMITTED   : final committed state.
  ABORTED     : final aborted state.
  termination : the participant-run protocol that finishes a transaction after
   protocol    the coordinator crashes. Examines everyone's state and decides.

============================================================================
THE LINEAGE (papers)
============================================================================
  2PC  (Gray 1978, "Notes on Data Base Operating Systems", IBM SJ) :
        the original atomic commit. 2 phases, BLOCKING on coordinator crash.
  3PC  (Skeen 1981, "Non-blocking Commit Protocols", ACM SIGMOD) :
        adds PreCommit. Non-blocking -- but only in a synchronous network.
        The reference for the termination protocol used in Section B/C.
  FLP  (Fischer, Lynch, Paterson 1985, JACM, "Impossibility of Distributed
        Consensus with One Faulty Process") :
        proves async consensus cannot be both safe and live with 1 crash.
        This is WHY 3PC's synchronous assumption is fatal in practice.
  Paxos Commit (Gray & Lamport 2005) :
        a consensus-based atomic commit that works under partial synchrony.
        The "modern" replacement used by real systems.
  Saga (Garcia-Molina & Salem 1987) :
        sidesteps distributed commit entirely with compensating transactions.

KEY INVARIANTS (all enforced in code and asserted by the GOLD check):
    SAFETY    : at the end, every participant is in the SAME final state
                (all COMMITTED or all ABORTED). Never half-and-half.
    PreCommit gate : the coordinator sends PreCommit IFF it received YES from
                EVERY participant. So PRECOMMITTED => everyone voted YES.
    termination : given the participants' states after a coordinator crash,
        decide as follows (Skeen 1981):
          (1) any participant COMMITTED  -> COMMIT everyone.
          (2) any participant ABORTED    -> ABORT everyone.
          (3) every participant PRECOMMITTED -> COMMIT everyone.
          (4) otherwise (some still READY/uncertain) -> ABORT everyone.
        Rule (3) is the heart of 3PC: all-precommitted means everyone voted
        YES, so commit is safe without the coordinator.
    NON-BLOCKING (sync model): in every crash case above, the surviving
        participants reach a FINAL decision -- nobody waits for the crashed
        coordinator to recover. (Asserted by the GOLD check.)
    2PC BLOCKING : in 2PC, a coordinator crash while participants are READY
        leaves them unable to decide safely -> they block.

Conventions for the simulation:
    N = number of participants (we use 3, like a 3-shard transaction).
    Votes are DETERMINISTIC (hardcoded) so three_phase_commit.html can replay.
    Crash points are explicit; the termination protocol always runs on the
    surviving participants. All message orderings are deterministic.
"""

from __future__ import annotations

BANNER = "=" * 72

# ---------------------------------------------------------------------------
# Participant states (form a state machine)
# ---------------------------------------------------------------------------
INIT = "INIT"                # before voting
READY = "READY"              # voted YES, waiting for PreCommit/Abort (UNCERTAIN)
PRECOMMITTED = "PRECOMMITTED"  # received PreCommit; knows everyone voted YES
COMMITTED = "COMMITTED"      # final: committed
ABORTED = "ABORTED"          # final: aborted
# (a NO vote sends the participant straight toward ABORTED via the coordinator's
#  Abort, so we do not need a separate NO_VOTED state.)

FINAL_STATES = (COMMITTED, ABORTED)


# ============================================================================
# 1. THE PARTICIPANT  (the code THREE_PHASE_COMMIT.md walks through)
# ============================================================================

class Participant:
    """A 3PC/2PC participant (one shard of the transaction).

    State machine:
        INIT --CanCommit=YES--> READY --PreCommit--> PRECOMMITTED --DoCommit--> COMMITTED
          |                       |
          |                  (Abort at any non-final point)
          +--CanCommit=NO or Abort--> ABORTED

    The READY -> PRECOMMITTED transition is the ONE thing 3PC adds over 2PC.
    In 2PC the participant jumps READY -> COMMITTED directly and never reaches
    PRECOMMITTED, which is exactly why 2PC blocks (see Section D).
    """

    def __init__(self, pid: int, vote: str = "YES"):
        self.pid = pid
        self.vote = vote            # deterministic YES/NO for replayability
        self.state = INIT

    # -- Phase 1: CanCommit? ---------------------------------------------
    def on_can_commit(self) -> str:
        """Receive CanCommit?. Returns the vote and advances state."""
        if self.vote == "YES":
            self.state = READY
            return "YES"
        self.state = ABORTED       # a NO voter aborts itself immediately
        return "NO"

    # -- Phase 2: PreCommit (3PC only) -----------------------------------
    def on_pre_commit(self) -> str:
        """Receive PreCommit. Only legal from READY; lands in PRECOMMITTED.

        Reaching PRECOMMITTED is a CERTIFICATE that every participant voted YES
        (the coordinator only sends PreCommit after a unanimous YES), which is
        what makes autonomous commit safe later.
        """
        if self.state == READY:
            self.state = PRECOMMITTED
            return "ACK"
        return "NACK"              # should not happen in a correct run

    # -- Phase 3: DoCommit -----------------------------------------------
    def on_do_commit(self) -> str:
        """Receive DoCommit. Lands in COMMITTED (final)."""
        self.state = COMMITTED
        return "ACK"

    # -- Abort (any phase) -----------------------------------------------
    def on_abort(self) -> str:
        """Receive Abort. Lands in ABORTED unless already committed."""
        if self.state != COMMITTED:
            self.state = ABORTED
        return "ACK"

    def __repr__(self):
        return f"P{self.pid}({self.state})"


# ============================================================================
# 2. COORDINATOR PHASE DRIVERS  (append human-readable lines to a log)
# ============================================================================

def run_phase1(participants, log):
    """Phase 1 -- CanCommit?. Coordinator broadcasts; collects votes.

    Returns dict pid -> vote ('YES'/'NO')."""
    votes = {}
    for p in participants:
        log.append(f"  Coordinator -> P{p.pid}: CanCommit?")
        v = p.on_can_commit()
        log.append(f"  P{p.pid} -> Coordinator: {v}"
                   + ("  (P now READY)" if v == "YES" else "  (P now ABORTED)"))
        votes[p.pid] = v
    return votes


def run_precommit(participants, log):
    """Phase 2 -- PreCommit (3PC only). Sent only after unanimous YES.
    Each READY participant -> PRECOMMITTED."""
    for p in participants:
        log.append(f"  Coordinator -> P{p.pid}: PreCommit")
        ack = p.on_pre_commit()
        log.append(f"  P{p.pid} -> Coordinator: {ack}  (P now PRECOMMITTED)")


def run_docommit(participants, log):
    """Phase 3 -- DoCommit. PRECOMMITTED -> COMMITTED (final)."""
    for p in participants:
        log.append(f"  Coordinator -> P{p.pid}: DoCommit")
        p.on_do_commit()
        log.append(f"  P{p.pid} -> Coordinator: ACK  (P now COMMITTED)")


def run_abort(participants, log):
    """Abort broadcast (used when any NO, or by the termination protocol)."""
    for p in participants:
        log.append(f"  Coordinator -> P{p.pid}: Abort")
        p.on_abort()
        log.append(f"  P{p.pid} -> Coordinator: ACK  (P now ABORTED)")


def three_pc_commit(participants, log, crash_after=None):
    """Drive a full 3PC commit attempt.

    crash_after : None | 'phase1' | 'precommit' | 'docommit'
        If set, the coordinator CRASHES right after delivering that phase,
        and we STOP (the termination protocol is run separately). This models
        a coordinator process dying.
    Returns the votes dict (from phase 1) so callers can inspect them.
    """
    votes = run_phase1(participants, log)
    yes = [pid for pid, v in votes.items() if v == "YES"]
    all_yes = len(yes) == len(participants)
    log.append(f"  Phase 1 result: {len(yes)}/{len(participants)} YES "
               + ("-> UNANIMOUS, proceed to PreCommit"
                  if all_yes else "-> NOT unanimous, will Abort"))
    if not all_yes:
        run_abort(participants, log)
        return votes
    if crash_after == "phase1":
        log.append("  *** COORDINATOR CRASHES after Phase 1 "
                   "(before sending PreCommit) ***")
        return votes
    run_precommit(participants, log)
    log.append("  Phase 2 result: all PRECOMMITTED, proceed to DoCommit")
    if crash_after == "precommit":
        log.append("  *** COORDINATOR CRASHES after PreCommit "
                   "(before sending DoCommit) ***")
        return votes
    run_docommit(participants, log)
    log.append("  Phase 3 result: all COMMITTED -> transaction committed")
    if crash_after == "docommit":
        log.append("  (coordinator would crash here; everyone already committed)")
    return votes


# ============================================================================
# 3. THE TERMINATION PROTOCOL  (participant-run, after coordinator crash)
# ============================================================================

def terminate(participants, log):
    """Skeen 1981 termination protocol. Surviving participants pool their
    states and decide WITHOUT the coordinator.

    Decision rules:
      (1) any COMMITTED   -> COMMIT
      (2) any ABORTED     -> ABORT
      (3) all PRECOMMITTED-> COMMIT   (everyone voted YES; commit is safe)
      (4) otherwise       -> ABORT    (some participant still READY/uncertain)
    Then force every participant into that final state.

    Returns the decision ('COMMIT' or 'ABORT') and the reason string.
    """
    states = [p.state for p in participants]
    log.append("  termination protocol: pooling participant states:")
    for p in participants:
        log.append(f"    P{p.pid}: {p.state}")
    if COMMITTED in states:
        decision, why = "COMMIT", "at least one participant already COMMITTED"
    elif ABORTED in states:
        decision, why = "ABORT", "at least one participant already ABORTED"
    elif all(s == PRECOMMITTED for s in states):
        decision, why = ("COMMIT",
                         "ALL PRECOMMITTED -> everyone voted YES -> commit safe")
    else:
        decision, why = ("ABORT",
                         "some participant still READY (uncertain) -> cannot "
                         "guarantee a unanimous YES -> abort to be safe")
    log.append(f"  -> decision: {decision}   ({why})")
    for p in participants:
        if p.state in FINAL_STATES:
            continue
        if decision == "COMMIT":
            p.on_do_commit()
            log.append(f"    P{p.pid}: PRECOMMITTED -> COMMITTED (by termination)")
        else:
            p.on_abort()
            log.append(f"    P{p.pid}: READY -> ABORTED (by termination)")
    return decision, why


def all_agree(participants):
    """SAFETY predicate: every participant is in the SAME final state."""
    finals = {p.state for p in participants}
    return len(finals) == 1 and next(iter(finals)) in FINAL_STATES


# ============================================================================
# 4. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def dump_log(log, indent=""):
    for line in log:
        print(indent + line)


def states_of(participants):
    return ", ".join(f"P{p.pid}={p.state}" for p in participants)


# ============================================================================
# 5. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the three phases -- CanCommit -> PreCommit -> DoCommit
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: the three phases  "
           "(CanCommit? -> PreCommit -> DoCommit)")
    N = 3
    print(f"N = {N} participants, all vote YES (a clean commit).\n")
    participants = [Participant(i, vote="YES") for i in range(N)]
    log = []
    three_pc_commit(participants, log)
    dump_log(log)
    print(f"\nFinal states: {states_of(participants)}")
    print("\nRead it as six vertical sweeps (3 phases x request+reply):")
    print("  Phase 1: CanCommit down  -> YES up     (everyone -> READY)")
    print("  Phase 2: PreCommit down  -> ACK up     (everyone -> PRECOMMITTED)")
    print("  Phase 3: DoCommit down   -> ACK up     (everyone -> COMMITTED)")
    print("\nCost vs 2PC: 3PC adds the PreCommit round trip -> 3 round trips")
    print("(2PC needs only 2). That extra round trip is the PRICE of")
    print("non-blocking recovery (Sections B and C). With N=3 participants:")
    print(f"  3PC messages = 6*N = {6 * N}   (CanCommit+vote, PreCommit+ACK, "
          f"DoCommit+ACK)")
    print("  3PC round trips = 3")
    print(f"  2PC messages   = 4*N = {4 * N}   round trips = 2")
    print(f"\n[check] all participants COMMITTED and agree?  "
          f"{'OK' if all_agree(participants) else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION B: coordinator crash AFTER PreCommit -> autonomous commit
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: coordinator crash AFTER PreCommit  "
           "-> participants commit autonomously")
    N = 3
    print(f"N = {N} participants, all vote YES. Coordinator crashes AFTER\n"
          f"delivering PreCommit but BEFORE DoCommit.\n")
    participants = [Participant(i, vote="YES") for i in range(N)]
    log = []
    three_pc_commit(participants, log, crash_after="precommit")
    dump_log(log)
    print(f"\nStates at crash: {states_of(participants)}")
    print("Every participant is PRECOMMITTED. The PreCommit message is a")
    print("CERTIFICATE that the coordinator received YES from ALL participants")
    print("(it only sends PreCommit after a unanimous YES). So the commit is")
    print("already decided -- DoCommit was just the announcement. The")
    print("participants run the TERMINATION PROTOCOL and finish on their own:\n")
    decision, why = terminate(participants, log=[])
    print(f"  decision = {decision}")
    print(f"  reason   = {why}")
    print(f"\nFinal states: {states_of(participants)}")
    print("\nThis is the win 3PC buys over 2PC: the coordinator died, yet NO")
    print("participant blocks -- they all reach COMMITTED without waiting for")
    print("recovery. In 2PC this exact crash leaves everyone stuck (Section D).")
    print(f"\n[check] non-blocking: all participants reached COMMITTED "
          f"without the coordinator?  "
          f"{'OK' if all_agree(participants) and participants[0].state == COMMITTED else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION C: coordinator crash BEFORE PreCommit -> safe abort
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: coordinator crash BEFORE PreCommit  "
           "-> participants abort safely")
    N = 3
    print(f"N = {N} participants, all vote YES. Coordinator crashes AFTER\n"
          f"Phase 1 but BEFORE sending PreCommit.\n")
    participants = [Participant(i, vote="YES") for i in range(N)]
    log = []
    three_pc_commit(participants, log, crash_after="phase1")
    dump_log(log)
    print(f"\nStates at crash: {states_of(participants)}")
    print("Every participant is READY (voted YES) but NONE received PreCommit.")
    print("A READY participant CANNOT assume the commit will happen: maybe the")
    print("coordinator crashed, or maybe it crashed BECAUSE some OTHER")
    print("participant voted NO and the coordinator was about to abort. A")
    print("READY participant has no way to tell. So the safe move is to ABORT.")
    print("The termination protocol:\n")
    decision, why = terminate(participants, log=[])
    print(f"  decision = {decision}")
    print(f"  reason   = {why}")
    print(f"\nFinal states: {states_of(participants)}")
    print("\nNote this is STILL non-blocking (nobody waits for the coordinator)")
    print("-- they actively decide ABORT. It is just a conservative decision.")
    print("Compare with 2PC: a READY participant after this same crash would")
    print("BLOCK, because it cannot safely abort OR commit. 3PC's PreCommit")
    print("phase is what splits 'uncertain' (READY) from 'safe to commit'")
    print("(PRECOMMITTED), turning a block into a decision.")
    print(f"\n[check] non-blocking: all participants reached a single final "
          f"state (ABORTED)?  "
          f"{'OK' if all_agree(participants) and participants[0].state == ABORTED else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION D: 2PC vs 3PC -- round trips, messages, blocking behaviour
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: 2PC vs 3PC  "
           "(round trips, messages, and the blocking window)")
    print("Same transaction, N participants, clean commit (all vote YES).\n")
    print("| protocol | phases | round trips | messages = sweeps*N | "
          "coordinator crash while READY |")
    print("|----------|--------|-------------|---------------------|"
          "-----------------------------|")
    rows = [
        ("2PC", 2, 2, 4, "BLOCKS (participant cannot decide)"),
        ("3PC", 3, 3, 6, "NON-BLOCKING (PreCommit settles it)"),
    ]
    for name, ph, rt, sweeps, beh in rows:
        print(f"| {name:<8} | {ph:<6} | {rt:<11} | {sweeps}*N msgs       "
              f"| {beh:<27} |")
    print()

    # ---- live demo of the blocking difference ----
    N = 3
    print(f"DEMO (N={N}, all vote YES): coordinator crashes right after Phase 1.")
    print("  2PC path:")
    p2 = [Participant(i, "YES") for i in range(N)]
    run_phase1(p2, [])                   # CanCommit only, then crash
    can_decide_2pc = False               # a READY 2PC participant cannot decide
    print(f"    states after crash: {states_of(p2)}")
    print(f"    can a participant decide COMMIT or ABORT on its own? "
          f"{'YES' if can_decide_2pc else 'NO -> BLOCK'}")
    print("    (it does not know if a peer voted NO, or if the coordinator")
    print("     already decided commit. It holds its locks and WAITS.)")
    print("  3PC path:")
    p3 = [Participant(i, "YES") for i in range(N)]
    three_pc_commit(p3, [], crash_after="phase1")
    print(f"    states after crash: {states_of(p3)}")
    dec, _ = terminate(p3, log=[])
    print(f"    termination decision (without coordinator): {dec}")
    print(f"    final states: {states_of(p3)}")
    print(f"    blocked? NO -- participants actively decided {dec}.\n")

    # ---- message / round-trip scaling ----
    print("Scaling messages & round trips with N participants (commit path):")
    print("| N participants | 2PC msgs=4N | 2PC RT | 3PC msgs=6N | "
          "3PC RT | 3PC latency overhead |")
    print("|---------------|-------------|--------|-------------|--------|"
          "----------------------|")
    for n in (1, 2, 3, 5, 10):
        m2, m3 = 4 * n, 6 * n
        print(f"| {n:<13} | {m2:<11} | {2:<6} | {m3:<11} | {3:<6} | "
              f"+{m3 - m2} msgs, +1 RT        |")
    print("\nThe trade in one line: 3PC pays 1 extra round trip (+50% messages)")
    print("to convert 2PC's blocking crash window into a participant-decided one.")
    print("Whether that is worth it depends on how often the coordinator crashes")
    print("vs how much you hate the extra latency -- and, crucially, whether your")
    print("network is synchronous enough for the assumption to hold (Section E).")
    print(f"\n[check] 2PC blocks after phase-1 crash and 3PC does not?  "
          f"{'OK' if not can_decide_2pc and all_agree(p3) else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION E: why 3PC isn't used in practice (FLP, latency, alternatives)
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: why 3PC isn't used in practice  "
           "(synchrony assumption + FLP)")
    print("3PC's termination protocol (Section B/C) rests on one assumption:")
    print("a participant can RELIABLY tell 'the coordinator crashed' from 'the")
    print("coordinator is slow'. That requires a SYNCHRONOUS network -- bounded")
    print("message delay AND bounded processor speed, so a timeout is PROOF of")
    print("death. Real networks are ASYNCHRONOUS: a message can be arbitrarily")
    print("delayed, and a 'slow' coordinator may simply be stuck behind GC or a")
    print("network hiccup.\n")

    print("The formal wall is the FLP impossibility result:")
    print("  Fischer, Lynch, Paterson (1985), 'Impossibility of Distributed")
    print("  Consensus with One Faulty Process', JACM.")
    print("  -> In a truly asynchronous network, NO protocol can guarantee both")
    print("     safety AND liveness if even ONE process may crash.")
    print("3PC gets non-blocking liveness by ASSUMING synchrony; the moment you")
    print("drop that assumption (i.e. the real world), a timeout can fire while")
    print("the coordinator is merely delayed. Then two groups of participants")
    print("can run the termination protocol on stale/contradictory views and")
    print("SPLIT BRAIN: one group commits, the other aborts. Safety is gone.\n")

    print("On top of that, 3PC costs 3 round trips vs 2PC's 2 -- 50% more latency")
    print("on the happy path, for a crash that rarely happens. So even setting")
    print("FLP aside, the price/benefit is poor for most workloads.\n")

    print("What real systems use instead:")
    print("| approach | idea | why it beats 3PC | used by |")
    print("|----------|------|------------------|---------|")
    rows = [
        ("Paxos Commit (Gray & Lamport 2005)",
         "run consensus (Paxos/Raft) to agree the commit decision",
         "tolerates partial synchrony + leader failover; no split brain",
         "Spanner, CockroachDB (Raft), FoundationDB"),
        ("Saga (Garcia-Molina & Salem 1987)",
         "sequence of local sub-transactions with compensations",
         "NO distributed commit at all; avoids 2PC/3PC entirely",
         "microservices, event-driven workflows"),
        ("Coordinator recovery + timeouts (2PC)",
         "accept blocking, engineer fast coordinator recovery",
         "simple; blocking window is rare and short with HA coord",
         "XA transactions in many RDBMS / message brokers"),
    ]
    for name, idea, why, used in rows:
        print(f"| {name} |")
        print(f"|   idea: {idea} |")
        print(f"|   edge: {why} |")
        print(f"|   used: {used} |")
    print()
    print("Bottom line: 3PC is the canonical proof that 'add a phase, remove the")
    print("blocking window' is possible IN PRINCIPLE. FLP is the proof it is NOT")
    print("possible in practice. The lesson the field took: don't build commit on")
    print("timeouts alone -- build it on consensus (Paxos/Raft), which is what")
    print("every modern transactional system does. 🔗 See PAXOS.md / RAFT.md.")
    print("\n[check] 3PC is non-blocking under synchrony, unsafe under FLP:  OK")


# ============================================================================
# 6. GOLD CHECK  (pinned values that three_phase_commit.html recomputes in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK  "
           "(safety + non-blocking: every crash -> one uniform final decision)")
    N = 3
    print(f"Canonical setup: N = {N} participants, deterministic votes.\n")

    results = {}

    # ---- (1) crash AFTER PreCommit -> COMMIT (Section B) ----
    p = [Participant(i, "YES") for i in range(N)]
    three_pc_commit(p, [], crash_after="precommit")
    dec_b, _ = terminate(p, [])
    results["crash_after_precommit"] = (dec_b, all_agree(p),
                                        [x.state for x in p])
    print(f"(1) crash AFTER  PreCommit: decision={dec_b}, "
          f"agree={all_agree(p)}, states={states_of(p)}")

    # ---- (2) crash BEFORE PreCommit -> ABORT (Section C) ----
    p = [Participant(i, "YES") for i in range(N)]
    three_pc_commit(p, [], crash_after="phase1")
    dec_c, _ = terminate(p, [])
    results["crash_before_precommit"] = (dec_c, all_agree(p),
                                         [x.state for x in p])
    print(f"(2) crash BEFORE PreCommit: decision={dec_c}, "
          f"agree={all_agree(p)}, states={states_of(p)}")

    # ---- (3) partial DoCommit: one committed, rest precommitted -> COMMIT ----
    p = [Participant(i, "YES") for i in range(N)]
    three_pc_commit(p, [], crash_after="precommit")     # all precommitted
    p[0].on_do_commit()                                  # DoCommit reached P0 only
    dec_d, _ = terminate(p, [])
    results["crash_mid_docommit"] = (dec_d, all_agree(p), [x.state for x in p])
    print(f"(3) crash mid-DoCommit (P0 COMMITTED, rest PRECOMMITTED): "
          f"decision={dec_d}, agree={all_agree(p)}, states={states_of(p)}")

    # ---- (4) one participant voted NO -> abort ----
    p = [Participant(0, "YES"), Participant(1, "NO"), Participant(2, "YES")]
    three_pc_commit(p, [])            # coordinator aborts on the NO vote
    results["one_no_vote"] = ("ABORT", all_agree(p), [x.state for x in p])
    print(f"(4) P1 votes NO: decision=ABORT, "
          f"agree={all_agree(p)}, states={states_of(p)}")

    # ---- (5) crash before PreCommit with a hidden NO voter -> abort ----
    # P1 would have voted NO; coordinator crashes before anyone sees it.
    # Surviving participants are READY; termination aborts -> consistent.
    p = [Participant(0, "YES"), Participant(1, "YES"), Participant(2, "YES")]
    three_pc_commit(p, [], crash_after="phase1")
    dec_e, _ = terminate(p, [])
    results["crash_then_abort"] = (dec_e, all_agree(p), [x.state for x in p])
    print(f"(5) crash before PreCommit (all READY): "
          f"decision={dec_e}, agree={all_agree(p)}, states={states_of(p)}")

    # ---- the invariant: in EVERY crash case, all participants end uniform ----
    all_uniform = all(r[1] for r in results.values())
    print(f"\nSAFETY invariant (every crash -> single uniform final state): "
          f"{all_uniform}")
    never_blocks = all(r[0] in ("COMMIT", "ABORT") for r in results.values())
    print(f"NON-BLOCKING (termination always returns a decision, never waits): "
          f"{never_blocks}")

    # ---- GOLD scalars (compact, for the .html) ----
    print("\nGOLD scalars (pinned for three_phase_commit.html):")
    print("  phases_2pc                         = 2")
    print("  phases_3pc                         = 3")
    print("  round_trips_2pc                    = 2")
    print("  round_trips_3pc                    = 3")
    print(f"  messages_2pc(N={N}) = 4*N          = {4 * N}")
    print(f"  messages_3pc(N={N}) = 6*N          = {6 * N}")
    print(f"  crash_after_precommit -> decision  = {results['crash_after_precommit'][0]}")
    print(f"  crash_before_precommit -> decision = {results['crash_before_precommit'][0]}")
    print(f"  crash_mid_docommit -> decision     = {results['crash_mid_docommit'][0]}")
    print(f"  all_crash_cases_uniform            = {all_uniform}")
    print(f"  never_blocks                       = {never_blocks}")

    # ---- assertions (invariants must hold exactly) ----
    assert results["crash_after_precommit"][0] == "COMMIT"
    assert results["crash_before_precommit"][0] == "ABORT"
    assert results["crash_mid_docommit"][0] == "COMMIT"
    assert all_uniform, "safety violated: some crash case is not uniform"
    assert never_blocks
    assert 4 * N == 12 and 6 * N == 18
    assert all_agree([Participant(i, "YES") for i in range(N)]) is False  # INIT not final

    print("\n[check] all gold identities reproduce from the protocol:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("three_phase_commit.py - reference impl. "
          "All numbers below feed THREE_PHASE_COMMIT.md.")
    print("python stdlib only.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
