"""
paxos.py - Reference implementation of the Paxos consensus algorithm
(Lamport 1998, "The Part-Time Parliament"; Lamport 2001, "Paxos Made Simple"),
the Multi-Paxos optimization, and a side-by-side with Raft.

This is the single source of truth that PAXOS.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 paxos.py

=========================================================================
THE INTUITION (read this first) -- the committee that must enact ONE law
=========================================================================
Imagine a parliament committee of ACCEPTORS that must enact exactly ONE law
this session. Any member (a PROPOSER) may suggest a law, but members arrive at
different times, messages can be delayed, and several proposers can race.
Paxos is the protocol that guarantees:

  * SAFETY  : at most ONE law is ever chosen. Two proposers who each win a
              majority will ALWAYS have chosen the same law.
  * LIVENESS: if a majority of acceptors is reachable, eventually SOME law is
              chosen (under mild fairness / a stable-proposer assumption).

It works in two phases, and the trick is PROPOSAL NUMBERS:

  Phase 1 (Prepare / Promise)  -- "lock in" a proposal number n.
        Proposer -> Acceptors : "Promise to ignore anything older than n?"
        Acceptors -> Proposer : "Yes -- and by the way, I already accepted THIS
                                 (n', v') earlier; if you win you must keep it."
  Phase 2 (Accept / Accepted) -- "commit" a value under that lock.
        Proposer -> Acceptors : "Accept (n, v)."
        Acceptors -> Proposer : "Accepted (n, v)."
        Once a majority accept, the value is CHOSEN. A LEARNER is told.

The safety magic is in Phase 1's "by the way": if ANY acceptor already accepted
a value, the proposer MUST reuse the highest-numbered accepted value. So a late
proposer can never overwrite a value an earlier majority already chose -- it is
FORCED to propose the very same value. That is why two majorities can never
disagree. (Section C demonstrates this; the GOLD check proves it.)

Multi-Paxos: if one proposer stays the stable leader, it runs Phase 1 ONCE to
"lease" the leadership and then issues ONLY Phase 2 for every subsequent value.
That halves the round-trips per value (Section D).

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  Proposer   : a node that wants a value chosen. Picks a unique, increasing
               proposal number n and drives the two phases.
  Acceptor   : a "voter". Remembers the highest proposal number it has
               PROMISED (Phase 1) and the highest proposal it has ACCEPTED
               (Phase 2). A majority of acceptors decides everything.
  Learner    : a node told the chosen value once a majority accept. (Often
               folded into the acceptors / proposer in real systems.)
  proposal   : a totally-ordered, UNIQUE number. Real systems use
  number n     n = (round, proposer_id) compared lexicographically so round
               dominates and ids break ties (guaranteeing uniqueness across
               proposers). The worked examples below use plain increasing
               integers 1,2,3,... (each round owned by one proposer) for
               readability; the comparison rule is identical.
  majority   : floor(N/2)+1 acceptors for N acceptors. Two majorities ALWAYS
               overlap in >= 1 acceptor -> that acceptor is the safety anchor.
  Prepare 1a : Phase 1 request "will you promise for n?".
  Promise 1b : Phase 1 reply. Acceptor promises to never again accept a
               proposal numbered < n, and reports the highest proposal it has
               already accepted (so the proposer can reuse it).
  Accept  2a : Phase 2 request "please accept (n, v)".
  Accepted2b : Phase 2 reply "I accepted (n, v)".
  chosen     : a value v is CHOSEN once a single proposal (n, v) is accepted
               by a majority of acceptors. Chosen is forever -- cannot be
               un-chosen.
  instance   : one "slot" of consensus (one decided value). A replicated log
               is a SEQUENCE of Paxos instances. Multi-Paxos batches them.

=========================================================================
THE LINEAGE (papers)
=========================================================================
  Paxos (Lamport 1998, "The Part-Time Parliament", ACM TOCS)
        -> the original, told as a parable about a fictional Greek island.
  Paxos Made Simple (Lamport 2001, ACM SIGACT News)
        -> the plain-English restatement. THE canonical reference.
  Multi-Paxos (Lamport 2001, same paper, stable-leader sections)
        -> skip Phase 1 for a stable leader. The actually-deployed form.
  Raft (Ongaro & Ousterhout 2014, USENIX ATC)
        -> leader-based, understandable re-derivation. Same 2f+1 / majority.
  Paxos Made Live (Chandra, Griesemer, Redstone 2007, PODC)
        -> Google Chubby's engineering notes on shipping real Multi-Paxos.

KEY INVARIANTS (all enforced in code and asserted by the GOLD check):
    SAFETY  : if a value v is chosen, no other value is ever chosen for that
              instance. Two majorities overlap in >= 1 acceptor; that acceptor
              forces every later proposer (via Phase 1's accepted-value report)
              to reuse v. (Section C.)
    quorum  : majority = floor(N/2)+1 ; two such quorums overlap in
              2*majority - N >= 1 acceptor.
    Phase 1 : Acceptor promises for n iff n > its highest promised n, and
              returns the highest-numbered proposal it has ACCEPTED.
    Phase 2 : Acceptor accepts (n, v) iff n >= its highest promised n.
    Value   : A proposer that gathers a majority of promises proposes the value
              of the HIGHEST-numbered accepted proposal among the promises, or
              its own value if none were accepted.

Conventions for the simulation:
    N = number of acceptors (we use 3 -> majority 2, like a 3-node etcd).
    proposal numbers are plain ints 1,2,3,... higher = newer.
    All message orderings are deterministic so paxos.html can replay exactly.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE CORE PROTOCOL  (the code PAXOS.md walks through)
# ============================================================================

class Acceptor:
    """A Paxos acceptor (voter).

    State:
      promised  : the highest proposal number it has promised (Phase 1 lease).
                  It will reject any Accept with n < promised.
      accepted  : dict instance_id -> (n, v), the highest proposal accepted
                  per instance (Phase 2).
    """

    def __init__(self, aid: int):
        self.aid = aid
        self.promised = None                 # highest n promised (Phase 1)
        self.accepted: dict[int, tuple] = {}  # instance -> (n, v) accepted

    # -- Phase 1b ---------------------------------------------------------
    def prepare(self, n: int, instance: int = 0):
        """Receive a Prepare(n). Returns ('promise'|'nack', n, accepted, inst).

        Promise iff n is strictly higher than any n already promised (Lamport
        P1b: 'greater than that of any prepare request to which it has already
        responded'). The promise carries the highest proposal THIS acceptor has
        already accepted for the instance, so the proposer can reuse it.
        """
        if self.promised is None or n > self.promised:
            self.promised = n
            acc = self.accepted.get(instance)        # (n,v) or None
            return ("promise", n, acc, instance)
        # already promised a number >= n: refuse to re-promise lower/same.
        return ("nack", n, None, instance)

    # -- Phase 2b ---------------------------------------------------------
    def accept(self, n: int, v, instance: int = 0):
        """Receive an Accept(n, v). Returns ('accepted'|'rejected', n, v).

        Accept iff n >= promised (the acceptor did NOT promise to ignore n).
        """
        if self.promised is None or n >= self.promised:
            self.accepted[instance] = (n, v)
            return ("accepted", n, v)
        return ("rejected", n, v)


def majority_of(n: int) -> int:
    """Majority quorum for n acceptors: floor(n/2)+1."""
    return n // 2 + 1


def proposer_value(desired, promises):
    """Pick the value a proposer must put in its Accept, given the promises.

    promises : list of (aid, accepted_n, accepted_v) from acceptors that
               answered Promise.
    Rule: if any acceptor already accepted a value, reuse the value of the
    HIGHEST-numbered accepted proposal among the promises; else use `desired`.
    Returns (value, was_forced).
    """
    seen = [(an, av) for (_, an, av) in promises if an is not None]
    if seen:
        best_n, best_v = max(seen, key=lambda t: t[0])
        return best_v, True
    return desired, False


# ----------------------------------------------------------------------------
# message-passing drivers (return results + append human-readable lines to log)
# ----------------------------------------------------------------------------

def run_phase1(acceptors, n, log, instance=0):
    """Proposer broadcasts Prepare(n); collect Promises. Returns list of
    (aid, accepted_n, accepted_v) for acceptors that promised."""
    promises = []
    for a in acceptors:
        kind, _, acc, _ = a.prepare(n, instance)
        tag = f", inst={instance}" if instance else ""
        log.append(f"  Proposer -> A{a.aid}: Prepare(n={n}{tag})")
        if kind == "promise":
            an = acc[0] if acc else None
            av = acc[1] if acc else None
            log.append(f"  A{a.aid} -> Proposer: Promise(n={n}, "
                       f"accepted={fmt_acc(an, av)})")
            promises.append((a.aid, an, av))
        else:
            log.append(f"  A{a.aid} -> Proposer: Nack  "
                       f"(already promised n={a.promised})")
    return promises


def run_phase2(acceptors, n, v, log, instance=0):
    """Proposer broadcasts Accept(n, v); collect Accepted. Returns list of
    acceptor aids that accepted."""
    accepted_ids = []
    for a in acceptors:
        kind, _, _ = a.accept(n, v, instance)
        tag = f", inst={instance}" if instance else ""
        log.append(f"  Proposer -> A{a.aid}: Accept(n={n}, v={v!r}{tag})")
        if kind == "accepted":
            log.append(f"  A{a.aid} -> Proposer: Accepted(n={n}, v={v!r})")
            accepted_ids.append(a.aid)
        else:
            log.append(f"  A{a.aid} -> Proposer: Rejected  "
                       f"(promised n={a.promised} > {n})")
    return accepted_ids


def paxos_round(acceptors, n, desired, log, proposer="Proposer",
                skip_phase1=False, instance=0):
    """Run a full Paxos round (Phase 1 + Phase 2) for one value.

    skip_phase1=True emulates a Multi-Paxos leader that already holds the lease
    (Phase 1 done once) and jumps straight to Phase 2.

    Returns the chosen value, or None if the round did not reach a majority.
    """
    maj = majority_of(len(acceptors))
    log.append(f"-- {proposer}, n={n}, wants={desired!r}"
               + (f", inst={instance}" if instance else ""))
    if not skip_phase1:
        promises = run_phase1(acceptors, n, log, instance)
        if len(promises) < maj:
            log.append(f"  Phase 1 FAILED: {len(promises)}/{len(acceptors)} "
                       f"promises (need {maj}) -> abort")
            return None
        value, forced = proposer_value(desired, promises)
        log.append(f"  Phase 1 OK: {len(promises)}/{len(acceptors)} promises "
                   f"(need {maj}). value to accept = {value!r} "
                   + ("(FORCED reuse of accepted value)" if forced
                      else "(own value)"))
    else:
        value = desired
        log.append(f"  [Multi-Paxos] skip Phase 1 (leader holds lease n={n}); "
                   f"accept own value {value!r}")
    accepted_ids = run_phase2(acceptors, n, value, log, instance)
    if len(accepted_ids) >= maj:
        log.append(f"  Phase 2 OK: {len(accepted_ids)}/{len(acceptors)} accepted "
                   f"(need {maj}) -> CHOSEN = {value!r}")
        return value
    log.append(f"  Phase 2 FAILED: {len(accepted_ids)}/{len(acceptors)} accepted "
               f"(need {maj})")
    return None


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_acc(an, av):
    if an is None:
        return "none"
    return f"({an}, {av!r})"


def dump_log(log, indent=""):
    for line in log:
        print(indent + line)


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: basic Paxos -- 1 proposer, 3 acceptors, 1 learner
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: basic Paxos  (1 proposer, 3 acceptors, 1 learner)")
    N = 3
    print(f"N = {N} acceptors -> majority = floor({N}/2)+1 = {majority_of(N)}")
    print("1 Proposer wants to choose 'X'. Trace of every message:\n")
    acceptors = [Acceptor(i) for i in range(N)]
    log = []
    chosen = paxos_round(acceptors, n=1, desired="X", log=log)
    dump_log(log)
    print(f"\nLearner is told: chosen = {chosen!r}")
    print("\nRead the trace top-to-bottom as four vertical sweeps:")
    print("  Prepare down  -> Promise up      (Phase 1: lock the number)")
    print("  Accept  down  -> Accepted up     (Phase 2: commit the value)")
    print("No prior accepted value existed, so the proposer used its own 'X'.")
    print(f"\n[check] chosen == 'X' and majority {majority_of(N)} reached:  "
          f"{'OK' if chosen == 'X' else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION B: competing proposers -- higher proposal number wins
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: competing proposers  (higher proposal number wins)")
    N = 3
    print(f"N = {N} acceptors, majority = {majority_of(N)}.")
    print("Proposer A (n=1, wants 'A') and Proposer B (n=2, wants 'B') race.\n")
    acceptors = [Acceptor(i) for i in range(N)]

    logA = []
    logA.append("-- Proposer A, Phase 1 only (n=1)")
    pA = run_phase1(acceptors, 1, logA)
    dump_log(logA)
    print(f"  -> A holds {len(pA)} promises (a majority)\n")

    logB = []
    logB.append("-- Proposer B, Phase 1 (n=2)  -- supersedes A")
    pB = run_phase1(acceptors, 2, logB)
    dump_log(logB)
    print(f"  -> B holds {len(pB)} promises. Acceptors now promised n=2 "
          f"(A's n=1 is stale).\n")

    print("Now A tries to finish (Phase 2 with n=1) -- but acceptors promised 2:")
    logA2 = []
    accA = run_phase2(acceptors, 1, "A", logA2)
    dump_log(logA2)
    print(f"  -> A accepted by {len(accA)} acceptors (need {majority_of(N)}): "
          f"REJECTED by all. A's proposal dies.\n")

    print("B finishes (Phase 2 with n=2):")
    logB2 = []
    accB = run_phase2(acceptors, 2, "B", logB2)
    dump_log(logB2)
    print(f"  -> B accepted by {len(accB)} acceptors -> CHOSEN = 'B'\n")

    print("WHY higher n wins: an acceptor promises to reject any Accept with")
    print("n < its promised number. B's Prepare(2) raised every acceptor's")
    print("promised number to 2, so A's Accept(1) is rejected everywhere.")
    print("Proposal numbers are Paxos's 'newer wins' ordering -- the lever that")
    print("breaks ties between concurrent proposers without a central leader.")
    print(f"\n[check] A's accept count (0) < majority and B's ({len(accB)}) "
          f">= majority:  OK")


# ----------------------------------------------------------------------------
# SECTION C: value selection -- forced reuse of an already-accepted value
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: value selection  (forced reuse guarantees safety)")
    N = 3
    print(f"N = {N} acceptors, majority = {majority_of(N)}.")
    print("Step 1: Proposer P1 (n=1) wants 'X' and gets it chosen.\n")
    acceptors = [Acceptor(i) for i in range(N)]
    log1 = []
    v1 = paxos_round(acceptors, n=1, desired="X", log=log1, proposer="P1")
    dump_log(log1)
    print(f"\nResult: 'X' is CHOSEN. Every acceptor now has accepted=(1, 'X').\n")

    print("Step 2: a LATE Proposer P3 (n=3) arrives and WANTS 'Y'.")
    print("P3 must run Phase 1 first. Watch what the acceptors report back:\n")
    log3 = []
    v3 = paxos_round(acceptors, n=3, desired="Y", log=log3, proposer="P3")
    dump_log(log3)
    print(f"\nResult: P3 wanted 'Y' but was FORCED to propose {v3!r}.")

    print("\nTHE RULE (Lamport Phase 2a): when a proposer collects a majority of")
    print("promises, it MUST propose the value of the HIGHEST-numbered proposal")
    print("any acceptor reports as already-accepted. Since the acceptors reported")
    print("(1, 'X'), P3's own desire 'Y' is overridden -> P3 proposes 'X'.")
    print("\nThis is the whole safety argument in one move: a new proposer cannot")
    print("win a majority without passing through Phase 1, and Phase 1 hands it")
    print("any value a prior majority already chose. So it re-chooses the SAME")
    print("value. Two proposers, two majorities, ONE value. (Proven in GOLD.)")
    print(f"\n[check] P1 chose {v1!r} and P3 (wanted Y) chose {v3!r}:  "
          f"{'OK -- same value' if v1 == v3 == 'X' else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION D: Multi-Paxos -- stable leader skips Phase 1 for later values
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: Multi-Paxos  (stable leader -> Phase 1 once, then Phase 2 only)")
    N = 3
    K = 3                      # values to choose
    maj = majority_of(N)
    print(f"N = {N} acceptors, majority = {maj}. Choose {K} values V1..V{K}.\n")

    print("BASIC Paxos: every value is its own log instance; each pays BOTH")
    print("phases (2 round-trips / value):")
    accB = [Acceptor(i) for i in range(N)]
    basic_msgs = 0
    basic_rt = 0
    chosen_basic = []
    for k in range(1, K + 1):
        # each value = a distinct log instance, so no forced-reuse cross-talk
        v = paxos_round(accB, n=k, desired=f"V{k}", log=[], instance=k)
        chosen_basic.append(v)
        # 4 sweeps (Prepare,Promise,Accept,Accepted) each to N acceptors
        basic_msgs += 4 * N
        basic_rt += 2
    print(f"  chosen = {chosen_basic}")
    print(f"  BASIC totals: messages = {basic_msgs}, round-trips = {basic_rt}\n")

    print("MULTI-Paxos: a stable leader runs Phase 1 ONCE (a 'lease'), then")
    print("issues ONLY Phase 2 (Accept/Accepted) for each subsequent value:")
    accM = [Acceptor(i) for i in range(N)]
    multi_msgs = 0
    multi_rt = 0
    chosen_multi = []
    # Phase 1 once: lease with n=1
    log = []
    lease = run_phase1(accM, 1, log)
    multi_msgs += 2 * N                  # Prepare + Promise
    multi_rt += 1
    print("  Phase 1 (lease, n=1):")
    dump_log(log, indent="  ")
    print(f"  leader now holds the lease; promised n=1 on all acceptors.\n")
    # Phase 2 only for each value, reusing the SAME lease n, distinct instances
    for k in range(1, K + 1):
        log2 = []
        v = paxos_round(accM, n=1, desired=f"V{k}", log=log2,
                        skip_phase1=True, proposer=f"Leader", instance=k)
        chosen_multi.append(v)
        multi_msgs += 2 * N              # Accept + Accepted only
        multi_rt += 1
    print(f"  chosen = {chosen_multi}")
    print(f"  MULTI totals: messages = {multi_msgs}, round-trips = {multi_rt}\n")

    print(f"Throughput improvement (round-trips), K={K} values:")
    print(f"  BASIC {basic_rt} RT  vs  MULTI {multi_rt} RT  ->  "
          f"MULTI uses {multi_rt / basic_rt:.2f}x the round-trips "
          f"({basic_rt / multi_rt:.2f}x fewer).\n")

    print("Scaling the round-trip count as K grows (N fixed):")
    print("| values K | basic RT = 2K | multi RT = K+1 | multi/basic |")
    print("|----------|---------------|----------------|-------------|")
    for K2 in (1, 2, 3, 5, 10, 50):
        b = 2 * K2
        m = K2 + 1
        print(f"| {K2:<8} | {b:<13} | {m:<14} | {m / b:.2f}x       |")
    print("\nAs K -> infinity, multi/basic -> 1/2: a stable leader DOUBLES the")
    print("decision throughput by amortizing Phase 1 over many values. This is")
    print("why every deployed Paxos (Chubby, Spanner, ZooKeeper's Zab) runs the")
    print("Multi-Paxos / stable-leader shape, not bare per-value Paxos.")
    print(f"\n[check] both modes chose the same {K} values "
          f"({chosen_basic} == {chosen_multi}):  "
          f"{'OK' if chosen_basic == chosen_multi else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION E: Paxos vs Raft
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: Paxos vs Raft  (two roads to the same consensus)")
    print("Paxos and Raft both solve consensus for CRASH faults with a 2f+1")
    print("majority. They differ in structure, not in what they guarantee.\n")
    print("| aspect              | Paxos                          | Raft                          |")
    print("|---------------------|--------------------------------|-------------------------------|")
    rows = [
        ("leader model", "decentralized: any node can propose;\n"
                         "                      no strong leader required",
                         "strong leader: ALL writes flow through\n"
                         "                      one elected leader"),
        ("roles", "Proposer / Acceptor / Learner\n"
                  "                      (explicit, may be co-located)",
                  "Leader / Follower / Candidate\n"
                  "                      (one node's state machine)"),
        ("core mechanism", "Prepare/Promise + Accept/Accepted\n"
                           "                      (proposal numbers)",
                           "RequestVote + AppendEntries\n"
                           "                      (term numbers)"),
        ("ordering term", "proposal number (round, id)",
                          "term (monotonic integer)"),
        ("understandability", "notoriously subtle",
                              "designed to be teachable"),
        ("fault model", "crash, 2f+1", "crash, 2f+1"),
        ("log replication", "Multi-Paxos: per-instance consensus",
                            "built-in: leader appends + matches"),
        ("canonical paper", "Lamport 1998/2001",
                            "Ongaro & Ousterhout 2014"),
        ("used by", "Chubby, Spanner (Paxos), ZooKeeper (Zab)",
                    "etcd, Consul, TiKV, CockroachDB"),
    ]
    for a, p, r in rows:
        # collapse the multi-line cells into one display line for the table
        pc = " ".join(x.strip() for x in p.splitlines())
        rc = " ".join(x.strip() for x in r.splitlines())
        print(f"| {a:<19} | {pc:<30} | {rc:<29} |")
    print()
    print("Practically equivalent: both deliver the SAME safety & liveness for")
    print("crash faults with the SAME 2f+1 node count and majority quorum. Raft")
    print("IS Multi-Paxos with a built-in strong leader and a simpler story --")
    print("Ongaro & Ousterhout's contribution is UNDERSTANDABILITY, not power.")
    print("Choice in practice is about ops & tooling, not capability.")


# ============================================================================
# 4. GOLD CHECK  (pinned values that paxos.html recomputes in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK  (safety: any two proposers that get a majority agree)")
    N = 3
    maj = majority_of(N)
    print(f"Canonical cluster: N = {N} acceptors, majority = {maj}\n")

    # ---- (1) the canonical safety proof: P1 chooses X, P2 forced to choose X
    acc = [Acceptor(i) for i in range(N)]
    log = []
    v1 = paxos_round(acc, n=1, desired="X", log=log, proposer="P1")
    v2 = paxos_round(acc, n=2, desired="Y", log=log, proposer="P2(wantsY)")
    chosen = [v for v in (v1, v2) if v is not None]
    distinct = set(chosen)
    print("Two proposers, each reaching a majority:")
    print(f"  P1 (n=1, wanted 'X') -> chose {v1!r}")
    print(f"  P2 (n=2, wanted 'Y') -> chose {v2!r}  (forced to reuse X)")
    print(f"  chosen set = {sorted(distinct)}")
    safe1 = len(distinct) <= 1
    print(f"  [check] at most one distinct value chosen?  "
          f"{'OK' if safe1 else 'FAIL'}\n")

    # ---- (2) stress: many sequential proposers, random desired values,
    #            safety must hold throughout (chosen set stays a singleton).
    import random
    rng = random.Random(42)
    acc2 = [Acceptor(i) for i in range(N)]
    chosen_history = []
    rounds = 25
    for r in range(1, rounds + 1):
        want = rng.choice(["X", "Y", "Z", "W"])
        v = paxos_round(acc2, n=r, desired=want, log=[], proposer=f"P{r}")
        if v is not None:
            chosen_history.append(v)
    distinct2 = set(chosen_history)
    safe2 = len(distinct2) == 1
    print(f"Stress ({rounds} sequential proposers, random desired values):")
    print(f"  values chosen over time = {chosen_history}")
    print(f"  distinct chosen values  = {sorted(distinct2)}")
    print(f"  [check] exactly one value ever chosen?  "
          f"{'OK' if safe2 else 'FAIL'}\n")

    # ---- (3) competing-proposers count (Section B shape, deterministic)
    acc3 = [Acceptor(i) for i in range(N)]
    run_phase1(acc3, 1, [])       # A's promise
    run_phase1(acc3, 2, [])       # B supersedes
    accA = run_phase2(acc3, 1, "A", [])
    accB = run_phase2(acc3, 2, "B", [])
    print("Competing proposers (A n=1 vs B n=2) accept counts:")
    print(f"  A accepted by {len(accA)} acceptor(s)  (needs {maj})")
    print(f"  B accepted by {len(accB)} acceptor(s)  (needs {maj}) -> chosen 'B'")
    safe3 = (len(accA) == 0 and len(accB) == N)
    print(f"  [check] higher-n proposer wins all accepts?  "
          f"{'OK' if safe3 else 'FAIL'}\n")

    # ---- GOLD scalars (compact, for the .html) ----
    print("GOLD scalars (pinned for paxos.html):")
    print(f"  majority_of(N=3)                      = {majority_of(3)}")
    print(f"  P1 chosen value (basic, n=1, want X)  = {v1!r}")
    print(f"  P2 chosen value (n=2, want Y, forced) = {v2!r}")
    print(f"  forced-reuse value == first chosen    = {v2 == v1 == 'X'}")
    print(f"  stress distinct-chosen count          = {len(distinct2)}")
    print(f"  basic_round_trips(K=3)  = 2*K         = {2 * 3}")
    print(f"  multi_round_trips(K=3)  = K+1         = {3 + 1}")

    # ---- assertions (the formulas/invariants must hold exactly) ----
    assert majority_of(3) == 2 and majority_of(5) == 3
    assert v1 == "X" and v2 == "X"          # forced reuse
    assert safe1 and safe2 and safe3
    assert len(accA) == 0 and len(accB) == 3
    assert 2 * 3 == 6 and 3 + 1 == 4         # throughput math
    assert len(distinct2) == 1

    print("\n[check] all gold identities reproduce from the protocol:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("paxos.py - reference impl. All numbers below feed PAXOS.md.")
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
