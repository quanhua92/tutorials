"""
distributed_systems.py - Distributed systems FUNDAMENTALS: the system model,
time & clocks, and fault tolerance that every consensus / replication /
consistency algorithm rests on.

This is the synthesized FUNDAMENTALS capstone of the dist/ suite. It ties
together the building blocks (failure models, timing assumptions, logical
clocks, causality, reliability math, Byzantine agreement) that the deeper
bundles (crash_vs_byzantine, sync_vs_async, lamport_timestamps, vector_clocks,
...) expand on. Every number, table, and worked example below is printed by
this file and recomputed live in distributed_systems.html.

Run:
    python3 distributed_systems.py

Pure Python stdlib only (math for reliability / clock drift).

============================================================================
THE INTUITION (read this first) - four facts, one hard truth
============================================================================
A distributed system is a collection of AUTONOMOUS computers that cooperate by
PASSING MESSAGES over a network you do not control. Four facts follow, and they
shape every algorithm built on top:

  1. FAILURES ARE THE NORM, not the exception. Nodes CRASH, messages are LOST,
     clocks DRIFT, and a few nodes may even LIE. The system model names WHICH
     failures you tolerate; the quorum math (2f+1 vs 3f+1) tells you how many
     replicas you need.

  2. YOU CANNOT TRUST WALL-CLOCKS. Two machines' physical clocks are never
     perfectly aligned and DRIFT at a bounded rate rho. So we invented LOGICAL
     clocks (Lamport, vector) that order events by CAUSALITY, not by the time
     of day, and we invented clock-SYNCHRONIZATION algorithms (Cristian, NTP)
     that bound the skew to a known epsilon.

  3. THERE IS NO GLOBAL "NOW". The only honest ordering of events across
     machines is the partial order defined by HAPPENS-BEFORE (->): a message
     send happens-before its receive; everything else within a process is in
     program order. Concurrent events have NO agreed order unless you force one.

  4. TIMING ASSUMPTIONS CHANGE WHAT IS POSSIBLE. A SYNCHRONOUS system (bounded
     delay) can DETECT crashes with timeouts; an ASYNCHRONOUS one (unbounded
     delay) cannot, and the FLP impossibility says deterministic consensus is
     then impossible even with ONE crash. Real systems assume PARTIAL SYNCHRONY:
     "eventually the delay bound holds".

THE HARD TRUTH (Byzantine generals): if nodes may ACT ARBITRARILY (lie, forge,
collude) rather than merely crash, agreement needs 3f+1 replicas - not 2f+1 -
because the honest majority must outvote the traitors AND the crashers.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  node / process   : an autonomous computer running the protocol.
  link             : a communication channel between two nodes. A FAIR link
                     eventually delivers messages but may REORDER / DELAY /
                     DROP them unless you pay for stronger guarantees (TCP).
  system model     : the assumptions about failures + timing the algorithm is
                     allowed to rely on. Getting it wrong = incorrect algorithm.
  crash failure    : a node HALTS and never recovers (or recovers from stable
                     storage). The most common, most benign failure.
  omission failure : a node OMITS to send/receive a message (message loss).
                     Harder than crash: the node is still "alive" but silent.
  byzantine failure: a node behaves ARBITRARILY - wrong data, conflicting
                     data to different nodes, collusion. The hardest class.
  f                : the number of faulty nodes the system must tolerate.
  quorum (CFT)     : floor(N/2)+1 = the smallest majority; tolerates f crashes
                     with N = 2f+1. Any two majorities OVERLAP (>= 1 node).
  quorum (BFT)     : 2f+1 honest needed to outvote f traitors, so N = 3f+1.
  happens-before   : a -> b iff (same process, a before b) OR (a is a send and
   (->)               b is the matching receive) OR (transitive). Otherwise
                     CONCURRENT (a || b): no causal relationship.
  lamport clock    : a single integer L per process. Local/send: L++. Receive:
                     L = max(L, msg_L) + 1. Gives a TOTAL order consistent with
                     -> but CANNOT detect concurrency.
  vector clock     : an N-vector V per process. Local/send: V[i]++. Receive:
                     V = max(V, msg_V) elementwise then V[i]++. V[a] <= V[b]
                     everywhere (and !=) iff a -> b; else a || b (concurrent).
  clock drift (rho): physical clocks gain/lose at rate up to rho (e.g. 25 ppm
                     = 0.0025%). Over T seconds two clocks can diverge up to
                     2*rho*T. Sync algorithms (Cristian/NTP) bound skew to eps.
  synchronous sys  : message delay and processing time are BOUNDED and known.
                     Timeouts can DETECT crashes; FLP does not apply.
  asynchronous sys : message delay is UNBOUNDED. A "slow" node is
                     indistinguishable from a "dead" node.
  FLP impossibility: Fischer-Lynch-Paterson 1985: in a fully asynchronous
                     system, NO deterministic protocol solves consensus even
                     with only ONE crash failure. (Real systems escape via
                     partial synchrony / randomness / failure detectors.)
  partial synchrony: Dwork-Lynch-Stockmeyer 1988: delays are unbounded for a
                     while but EVENTUALLY a bound holds. This is what real
                     systems (Raft, Paxos) actually assume.

============================================================================
THE PAPERS
============================================================================
  Lamport 1978   "Time, Clocks, and the Ordering of Events" - happens-before,
                  Lamport clocks. The foundational paper of the field.
  Lamport 1978   "The Implementation of Reliable Distributed Multiprocess
                  Systems" - vector clocks (effectively).
  Fischer-Lynch- Paterson 1985 - FLP impossibility (asynchronous consensus).
   Paterson 1985
  Dwork-Lynch-   1988 - partial synchrony (how to escape FLP).
   Stockmeyer
  Lamport-       1982 - Byzantine Generals; 3f+1 threshold + OM algorithm.
   Shostak-Pease
  Cristian 1989  "Probabilistic Clock Synchronization" - bounded skew.
  Schneider 1990 "Implementing Fault-Tolerant Services Using the State Machine
                  Approach" - the recipe (replicated state machine).

KEY FORMULAS / facts (all asserted in code):
    CFT quorum  : N = 2f+1 tolerates f crashes   ; majority = floor(N/2)+1
    BFT quorum  : N = 3f+1 tolerates f traitors  ; honest quorum = 2f+1
    lamport     : on receive L = max(L, msg_L)+1
    vector clock: a -> b  <=>  V[a] <= V[b] everywhere AND V[a] != V[b]
    drift bound : skew over T <= 2 * rho * T
    reliability : R(t) = e^(-lambda*t), lambda = 1/MTBF
    replication : R_r(t) = 1 - (1 - R(t))^r  (survives if >=1 of r replicas up)
"""

from __future__ import annotations

import math

BANNER = "=" * 74

# A small deterministic event trace used for BOTH the Lamport and vector-clock
# sections, so the two clock types can be compared on the identical causality.
# Each event: (proc, label, kind, partner, msg_tag)
#   kind in {"local","send","recv"}; partner ignored for "local".
# Events are listed in EXECUTION order (top-to-bottom). The send of a tag must
# precede its recv. This trace has a CAUSAL CHAIN (a->b->c->d->y) AND an
# INDEPENDENT event (x) to make concurrency detectable.
TRACE = [
    ("P0", "a", "local", None, None),     # P0 local
    ("P0", "b", "send",  "P1", "m1"),     # P0 sends m1 -> P1
    ("P1", "c", "recv",  "P0", "m1"),     # P1 receives m1
    ("P2", "x", "local", None, None),     # P2 local (concurrent with a,b,c)
    ("P1", "d", "send",  "P2", "m2"),     # P1 sends m2 -> P2
    ("P2", "y", "recv",  "P1", "m2"),     # P2 receives m2
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def majority_cft(n: int) -> int:
    """CFT quorum size: floor(n/2)+1. With n=2f+1 this tolerates f crashes."""
    return n // 2 + 1


def n_cft(f: int) -> int:
    """Replicas needed to tolerate f crash failures."""
    return 2 * f + 1


def n_bft(f: int) -> int:
    """Replicas needed to tolerate f Byzantine (arbitrary) failures."""
    return 3 * f + 1


# ---------------------------------------------------------------------------
# SECTION A: the system model - nodes, links, failure modes, quorum thresholds
# ---------------------------------------------------------------------------
def section_a():
    banner("SECTION A: the system model - failures & the quorum thresholds")
    print("Every distributed algorithm assumes a SYSTEM MODEL: which failures")
    print("can occur and what the network/timing guarantees are. Name the model")
    print("wrong and the algorithm is silently incorrect.\n")
    print("The failure hierarchy (each level ADDS a harder failure mode):\n")
    print("  | level | failure     | what the faulty node does              |")
    print("  |-------|-------------|----------------------------------------|")
    print("  |   1   | crash       | HALTS. Stops talking. May recover later|")
    print("  |   2   | omission    | DROPS messages (send or receive). Still|")
    print("  |       |             | 'alive' but silent on some messages    |")
    print("  |   3   | byzantine   | ARBITRARY. Wrong data, conflicting data|")
    print("  |       |             | to different peers, collusion, forgery |")
    print()
    print("Crash is a SPECIAL CASE of omission (a crashed node omits EVERYTHING),")
    print("and omission is a special case of byzantine. Tolerating a harder class")
    print("needs MORE replicas and MORE message rounds.\n")

    print("THE QUORUM THRESHOLDS (why the numbers are what they are):\n")
    print("  Crash-fault tolerance (CFT): N = 2f + 1. With f crashed, 2f+1 - f =")
    print("  f+1 nodes remain - still a MAJORITY of the original 2f+1, so a quorum")
    print("  can always be formed. Equivalently: any two majorities OVERLAP in")
    print("  >= 1 non-crashed node -> decisions cannot diverge.\n")
    print("  Byzantine-fault tolerance (BFT): N = 3f + 1. With f traitors, f")
    print("  crashers, and the rest honest, the honest nodes (>= 2f+1) must form a")
    print("  quorum LARGER than the f traitors can sway, AND two honest quorums")
    print("  must overlap in >= f+1 honest nodes. 3f+1 is the tight bound.\n")

    print("  | f  | CFT N=2f+1 | BFT N=3f+1 | CFT majority | BFT honest quorum |")
    print("  |----|------------|------------|--------------|-------------------|")
    for f in range(0, 4):
        print(f"  | {f}  | {n_cft(f):<10} | {n_bft(f):<10} | "
              f"{majority_cft(n_cft(f)):<12} | {2*f+1:<17} |")
    print()

    # sanity: the two families need different replica counts
    assert n_cft(1) == 3 and n_bft(1) == 4
    assert n_cft(2) == 5 and n_bft(2) == 7
    assert majority_cft(5) == 3
    # quorum overlap property: two majorities of n always share >= 1 node
    n = n_cft(2)              # 5
    q = majority_cft(n)       # 3
    overlap_min = 2 * q - n   # >= 1 for any quorum system
    print(f"Overlap proof (CFT, N={n}): two majorities of {q} in {n} nodes share")
    print(f"  >= 2*{q} - {n} = {overlap_min} node. That shared node voted for only")
    print("  one value/leader -> at most one decision per term. This is the single")
    print("  fact that makes majority quorums safe.\n")
    assert overlap_min >= 1
    print("[check] CFT=2f+1, BFT=3f+1, two majorities overlap in >=1 node: OK")


# ---------------------------------------------------------------------------
# SECTION B: synchronous vs asynchronous - timing assumptions & FLP
# ---------------------------------------------------------------------------
def section_b():
    banner("SECTION B: synchronous vs asynchronous - timing assumptions & FLP")
    print("A system model is INCOMPLETE without a TIMING assumption. The delay of")
    print("messages (and processing) is either bounded and known, or not:\n")
    print("  | model        | message delay         | can detect crashes? | consensus? |")
    print("  |--------------|------------------------|---------------------|------------|")
    print("  | synchronous  | BOUNDED, known Delta   | YES (timeout)       | possible   |")
    print("  | asynchronous | UNBOUNDED              | NO (slow == dead)   | IMPOSSIBLE |")
    print("  | partial sync | bounded EVENTUALLY     | eventually          | possible   |")
    print()
    print("SYNCHRONOUS: if a message doesn't arrive within Delta, the sender KNOWS")
    print("the receiver crashed (or the network partitioned). Timeouts = perfect")
    print("failure detectors. Nice, but UNREALISTIC: real networks have no hard")
    print("delay bound (GC pauses, route flaps, congestion).\n")
    print("ASYNCHRONOUS: delay is unbounded. A message that hasn't arrived might")
    print("still arrive in 10 ms or 10 minutes. You CANNOT distinguish 'slow' from")
    print("'dead'. This is the INTERNET.\n")
    print("THE FLP IMPOSSIBILITY (Fischer-Lynch-Paterson 1985): in a fully")
    print("asynchronous system, NO deterministic protocol can solve consensus even")
    print("if ONLY ONE node may crash. Proof sketch: there is an execution where the")
    print("system stays forever in a 'bivalent' state (could still decide 0 or 1) by")
    print("delaying one critical message. So you cannot GUARANTEE termination.\n")
    print("HOW REAL SYSTEMS ESCAPE FLP (they all do - etcd, Cassandra, Spanner):\n")
    print("  - PARTIAL SYNCHRONY (Dwork-Lynch-Stockmeyer 1988): assume delays are")
    print("    unbounded for a while but EVENTUALLY a bound holds. Consensus then")
    print("    terminates after GST (Global Stabilization Time). This is what Raft/")
    print("    Paxos actually assume.\n")
    print("  - RANDOMIZATION: protocols that flip coins can terminate with")
    print("    probability 1 (Ben-Or 1983) even under asynchrony.\n")
    print("  - FAILURE DETECTORS (Chandra-Toueg 1996): an oracle that eventually")
    print("    suspects crashed nodes. With a 'perfect' detector, consensus is")
    print("    solvable; real detectors (timeouts, phi-accrual) approximate it.\n")

    # the practical consequence: timeouts are a GUESS, not a proof
    delta_best = 10      # ms, best-case LAN RTT
    delta_worst = 2000   # ms, GC pause / congestion
    print(f"Practical note: a timeout is a GUESS, not a proof. If you set the")
    print(f"failure timeout to T_best={delta_best} ms (the fast case), a node that")
    print(f"is merely SLOW (e.g. {delta_worst} ms GC pause) is wrongly declared")
    print(f"dead -> false positive -> spurious leader election. Set it to")
    print(f"{delta_worst} ms and real crashes take {delta_worst} ms to notice ->")
    print("slow failover. There is no perfect timeout; this is why adaptive /")
    print("phi-accrual detectors exist. (See failure_detection.py.)\n")
    assert delta_worst > 20 * delta_best
    print("[check] async => slow indistinguishable from dead => FLP applies: OK")


# ---------------------------------------------------------------------------
# SECTION C: time & clocks - physical drift & Lamport logical clocks
# ---------------------------------------------------------------------------
def lamport_run(trace):
    """Compute Lamport scalar clocks for `trace`.

    Returns dict label->clock. Rule: local/send -> L[i]++; recv of msg with
    timestamp tm -> L[i] = max(L[i], tm) + 1. Gives a TOTAL order consistent
    with happens-before (but cannot detect concurrency).
    """
    clk = {"P0": 0, "P1": 0, "P2": 0}
    res = {}
    in_flight = {}   # msg_tag -> sender's clock at send time
    for proc, label, kind, partner, tag in trace:
        if kind == "local":
            clk[proc] += 1
        elif kind == "send":
            clk[proc] += 1
            in_flight[tag] = clk[proc]
        else:  # recv
            tm = in_flight[tag]
            clk[proc] = max(clk[proc], tm) + 1
        res[label] = (proc, clk[proc], kind)
    return res


def section_c():
    banner("SECTION C: time & clocks - drift & Lamport logical clocks")
    print("PHYSICAL CLOCKS DRIFT. Two quartz clocks gain/lose at a rate up to rho")
    print("(a few parts per million, ppm). Over an interval T they can diverge by\n")
    rho_ppm = 25                      # 25 ppm = 0.0025% typical
    rho = rho_ppm / 1_000_000
    for hours in (1, 24, 24 * 30):
        t = hours * 3600
        skew = 2 * rho * t
        unit = "s"
        print(f"  rho = {rho_ppm} ppm,  T = {hours:>4} h  ->  max skew 2*rho*T "
              f"= {skew:.2f} {unit}")
    print("\nSo even 'good' clocks drift ~13 seconds/month apart. You CANNOT use")
    print("raw wall-clock readings to order events across machines. Two responses:\n")
    print("  (1) SYNC THE CLOCKS to a bounded skew eps (Cristian/NTP). Then you get")
    print("      a usable real-time order but with eps uncertainty. (See")
    print("      clock_sync_ntp.py.) Cristian: client asks time server, corrects for")
    print("      half the RTT; NTP layers this with statistics and strata.\n")
    print("  (2) IGNORE WALL-CLOCKS ENTIRELY and order events by CAUSALITY using a")
    print("      LOGICAL clock. This is Lamport's 1978 insight.\n")

    print("HAPPENS-BEFORE (->), Lamport's relation:\n")
    print("  a -> b  if  (a,b in same process and a precedes b),  OR")
    print("           if  a is a SEND and b is the matching RECEIVE,  OR")
    print("           by transitivity (a->c and c->b => a->b).")
    print("  If neither a->b nor b->a, the events are CONCURRENT: a || b.\n")

    print("LAMPORT CLOCK RULE (one integer L per process):\n")
    print("  local/send : L[i] = L[i] + 1")
    print("  receive(m) : L[i] = max(L[i], L_m) + 1     (L_m = timestamp carried by m)")
    print("  PROPERTY   : a -> b  =>  L[a] < L[b]   (but NOT the converse!)\n")
    print("Lamport clocks preserve happens-before but CANNOT tell you two events")
    print("are concurrent - they just give a consistent TOTAL order (ties broken by")
    print("process id). The trace used here (a,b,c,d,y are a causal chain; x is an")
    print("independent concurrent event):\n")
    print("  P0: a(local)  b(send m1->P1)")
    print("  P1:            c(recv m1)  d(send m2->P2)")
    print("  P2:   x(local)                         y(recv m2)\n")
    lam = lamport_run(TRACE)
    print("  | event | proc | kind | L |")
    print("  |-------|------|------|---|")
    for proc, label, kind, partner, tag in TRACE:
        _, lk, _ = lam[label]
        print(f"  | {label:<5} | {proc:<4} | {kind:<4} | {lk} |")
    print()
    print("The causal chain a->b->c->d->y gets L = 1,2,3,4,5 (strictly increasing,")
    print("as happens-before demands: a->b => L[a]<L[b]). But the independent event x")
    print("also gets L=1 - IDENTICAL to a - even though a and x are CONCURRENT. Worse,")
    print("x (L=1) sorts BEFORE d (L=4) in the total order, yet x || d (no causal")
    print("link). Lamport guarantees a->b => L[a]<L[b] but NOT the converse; a single")
    print("scalar cannot reveal concurrency. That is exactly what vector clocks fix.\n")

    # verify the happens-before => L[a] < L[b] direction holds on the chain
    assert lam["a"][1] < lam["b"][1] < lam["c"][1] < lam["d"][1] < lam["y"][1]
    print("[check] causal chain a<b<c<d<y has strictly increasing Lamport clocks: OK")


# ---------------------------------------------------------------------------
# SECTION D: vector clocks - detecting causality AND concurrency
# ---------------------------------------------------------------------------
def vector_run(trace):
    """Compute vector clocks for `trace`.

    Returns dict label->vector (list of 3 ints). Rule: local/send -> V[i]++;
    recv -> V = elementwise max(V, V_m) then V[i]++. a -> b iff V[a] <= V[b]
    componentwise AND V[a] != V[b]; otherwise a || b (concurrent).
    """
    vec = {"P0": [0, 0, 0], "P1": [0, 0, 0], "P2": [0, 0, 0]}
    idx = {"P0": 0, "P1": 1, "P2": 2}
    res = {}
    in_flight = {}
    for proc, label, kind, partner, tag in trace:
        i = idx[proc]
        if kind == "local":
            vec[proc][i] += 1
        elif kind == "send":
            vec[proc][i] += 1
            in_flight[tag] = list(vec[proc])
        else:  # recv
            vm = in_flight[tag]
            vec[proc] = [max(vec[proc][k], vm[k]) for k in range(3)]
            vec[proc][i] += 1
        res[label] = list(vec[proc])
    return res


def vcmp(va, vb):
    """Return 'a->b', 'b->a', or 'concurrent'."""
    le = all(va[k] <= vb[k] for k in range(3))
    ge = all(va[k] >= vb[k] for k in range(3))
    if le and any(va[k] < vb[k] for k in range(3)):
        return "a->b"
    if ge and any(va[k] > vb[k] for k in range(3)):
        return "b->a"
    return "concurrent"


def section_d():
    banner("SECTION D: vector clocks - detecting causality AND concurrency")
    print("A VECTOR clock fixes Lamport's blind spot. Each process keeps a vector")
    print("V of N integers (one entry per process). The rule:\n")
    print("  local/send : V[i] = V[i] + 1")
    print("  receive(m) : V[k] = max(V[k], V_m[k]) for ALL k,  then  V[i]++")
    print("  PROPERTY   : a -> b  <=>  V[a] <= V[b] componentwise AND V[a] != V[b]")
    print("              otherwise a || b  (CONCURRENT - no causal order)\n")
    print("On the SAME trace (a,b,c,d,y chain; x concurrent):\n")
    vec = vector_run(TRACE)
    print("  | event | proc | kind |   vector V    |")
    print("  |-------|------|------|---------------|")
    for proc, label, kind, partner, tag in TRACE:
        v = vec[label]
        vs = "[" + ",".join(str(x) for x in v) + "]"
        print(f"  | {label:<5} | {proc:<4} | {kind:<4} | {vs:<13} |")
    print()
    print("Now compare the causality the two clocks can see. The key pairs:\n")
    print("  | pair    | V[a]         | V[b]         | relation      |")
    print("  |---------|--------------|--------------|---------------|")
    pairs = [("a", "b"), ("a", "c"), ("c", "y"), ("x", "a"), ("x", "y"), ("a", "y")]
    for la, lb in pairs:
        rel = vcmp(vec[la], vec[lb])
        va = "[" + ",".join(str(x) for x in vec[la]) + "]"
        vb = "[" + ",".join(str(x) for x in vec[lb]) + "]"
        desc = "happens-before" if rel == "a->b" else ("concurrent (||)" if rel == "concurrent" else "reverse b->a")
        print(f"  | {la} , {lb:<2}  | {va:<12} | {vb:<12} | {desc:<13} |")
    print()
    print("So x is CONCURRENT with a,b,c,d (vector clock reveals it!), while")
    print("a->b->c->d->y is a genuine causal chain. Lamport could only say")
    print("'L increases' - it gave x the same L=1 as a, hiding that x is causally")
    print("independent of the whole chain. Dynamo/Riak use version vectors (a")
    print("close cousin) precisely to detect concurrent writes and surface them as")
    print("conflicts instead of silently dropping one.\n")

    # verify concurrency detection that Lamport could NOT see
    assert vcmp(vec["x"], vec["a"]) == "concurrent"
    assert vcmp(vec["x"], vec["y"]) == "a->b"      # x -> y (x precedes y, no other dep)
    assert vcmp(vec["a"], vec["y"]) == "a->b"
    print("[check] vector clock finds x || a (concurrent) and x -> y: OK")


# ---------------------------------------------------------------------------
# SECTION E: fault tolerance basics - reliability math & replication
# ---------------------------------------------------------------------------
def section_e():
    banner("SECTION E: fault tolerance - reliability math & replication")
    print("How much more reliable does REPLICATION make a system? Use the standard")
    print("exponential-failure model: a node fails at rate lambda = 1/MTBF, so its")
    print("reliability (prob of being up at time t) is R(t) = e^(-lambda*t).\n")
    mtbf_hours = 1_000_000        # ~114 years for a single good disk
    lam = 1.0 / mtbf_hours
    print(f"Single node: MTBF = {mtbf_hours:,} h  ->  lambda = {lam:.2e} /h\n")
    print("  | t (1 year = 8760 h) | R_single = e^(-lambda*t) |")
    print("  |----------------------|--------------------------|")
    for years in (1, 3, 5, 10):
        t = years * 8760
        r = math.exp(-lam * t)
        print(f"  | {years:>2} yr  ({t:>5} h)      | {r:.6f}               |")
    print()
    r1 = math.exp(-lam * 8760)
    print(f"After 1 year a single node is up with prob {r1:.5f} (~{(1-r1)*100:.2f}% chance")
    print("it has failed once). Replication makes the SYSTEM reliability = prob that")
    print("at least 1 of r replicas is up = 1 - (1 - R)^r (assuming independent")
    print("failures):\n")
    print("  | replicas r | R_system after 1 yr = 1-(1-R)^r | downtime reduction |")
    print("  |------------|--------------------------------|--------------------|")
    base = r1
    prev = base
    for r in (1, 2, 3, 5):
        rs = 1 - (1 - base) ** r
        impr = "baseline" if r == 1 else f"~{rs/prev:.0f}x better"
        print(f"  | {r:<10} | {rs:.10f}                 | {impr:<18} |")
        prev = rs
    r3 = 1 - (1 - base) ** 3
    print()
    print(f"Three replicas lift 1-year reliability from {base:.5f} to {r3:.10f} -")
    print("the chance ALL three fail simultaneously is (1-R)^3, vanishingly small.")
    print("This is the math behind 'replication factor 3' in Kafka / Cassandra /")
    print("Raft: tolerate 1 fault (2f+1 with f=1 needs N=3) while making total data")
    print("loss astronomically unlikely.\n")
    print("CAVEATS: this assumes INDEPENDENT failures. Correlated failures (a rack")
    print("PDU dies, a whole AZ loses power, a bad deploy) break the model - which is")
    print("why we spread replicas across failure domains (racks/AZs) and demand f+1")
    print("survivors, not f+1 machines in the same rack.\n")

    assert r3 > 0.999999
    assert (1 - (1 - base) ** 3) > base          # replication strictly helps
    print(f"[check] r=3 system reliability {r3:.7f} > single {base:.5f}: OK")


# ---------------------------------------------------------------------------
# GOLD CHECK: byzantine generals - 3f+1, OM algorithm, loyal decision
# ---------------------------------------------------------------------------
def om_messages(n, m):
    """Message count of the Oral Messages (OM) algorithm for n nodes, m rounds.

    f(n,0) = n-1  (commander -> all lieutenants)
    f(n,m) = (n-1) + (n-1) * f(n-1, m-1)
    """
    if m == 0:
        return n - 1
    return (n - 1) + (n - 1) * om_messages(n - 1, m - 1)


def gold_check():
    banner("GOLD CHECK: byzantine generals - 3f+1, OM algorithm, loyal decision")
    print("CAPSTONE: the Byzantine Generals Problem (Lamport-Shostak-Pease 1982).")
    print("Several generals must AGREE on a common plan (attack/retreat) by exchanging")
    print("messages, but the commander (or some lieutenants) may be TRAITORS sending")
    print("conflicting orders. Goal: all LOYAL lieutenants decide the SAME order.\n")
    print("THE THRESHOLD: agreement is possible iff the number of traitors f satisfies")
    print("  N >= 3f + 1\n")
    print("  | f traitors | min N = 3f+1 | honest >= | tolerate? |")
    print("  |------------|--------------|-----------|-----------|")
    for f in range(0, 4):
        n = 3 * f + 1
        print(f"  | {f:<10} | {n:<12} | {n-f:<9} | {'YES' if n>=3*f+1 else 'NO'} |")
    print()
    print("WHY 3f+1 (not 2f+1): with f traitors, the loyal majority quorum must be")
    print("> f to outvote them, AND any two such quorums must overlap in > f loyal")
    print("nodes (else traitors could make two groups disagree). That forces N = 3f+1.")
    print("Crash tolerance needs only 2f+1 because a crashed node merely STOPS - it")
    print("cannot actively forge conflicting votes.\n")

    print("THE OM ALGORITHM (Oral Messages), the canonical BFT protocol:\n")
    print("  OM(0): commander sends its order to every lieutenant; lieutenants use")
    print("         the value received (or a default if none).")
    print("  OM(m): commander sends its order; each lieutenant then recursively runs")
    print("         OM(m-1) as the NEW commander forwarding what it heard, over the")
    print("         remaining lieutenants. Finally each loyal lieutenant takes the")
    print("         MAJORITY of all values it collected.\n")
    print("OM(m) tolerates f traitors iff m >= f (so it runs f+1 rounds). Message")
    print("complexity is steep - it grows like O(N^(f+1)):\n")
    print("  | f | rounds m=f | min N | OM messages |")
    print("  |---|------------|-------|-------------|")
    gold_msgs = {}
    for f in range(0, 4):
        n = 3 * f + 1
        msgs = om_messages(n, f)
        gold_msgs[f] = msgs
        print(f"  | {f} | {f:<10} | {n:<5} | {msgs:<11} |")
    print()

    # WORKED EXAMPLE: f=1, N=4, the commander is the traitor.
    print("WORKED EXAMPLE (f=1, N=4, commander C is the traitor):\n")
    print("  commander C sends DIFFERENT orders to the 3 loyal lieutenants:")
    print("    C -> L1: 'attack'")
    print("    C -> L2: 'attack'")
    print("    C -> L3: 'retreat'      <- the lie")
    print("  OM(1): each lieutenant forwards what it heard from C to the other two.")
    print("  What L1 collects after the exchange:")
    print("    from C directly    : attack")
    print("    from L2 (C->L2)    : attack")
    print("    from L3 (C->L3)    : retreat")
    print("    majority('attack') : ATTACK   <- loyal decision\n")
    print("  Similarly L2 and L3 each compute majority(attack, attack, retreat) =")
    print("  ATTACK. ALL THREE LOYAL LIEUTENANTS DECIDE IDENTICALLY -> agreement.")
    print("  The traitor commander could not break it: with N=4=3*1+1 the loyal")
    print("  majority (3) always outvotes the 1 traitor.\n")

    # if only N=3 (3f with f=1), the traitor CAN split the loyal pair
    print("  Contrast N=3, f=1 (one short of 3f+1): C->L1 'attack', C->L2 'retreat'.")
    print("  L1 hears {attack, retreat} -> tie; L2 hears {retreat, attack} -> tie.")
    print("  They CANNOT agree. 3f+1 is TIGHT: lose one node and BFT fails.\n")

    # GOLD scalars pinned for the .html
    print("GOLD scalars (for a compact .html check):")
    print(f"  n_cft(1)        = {n_cft(1)}")
    print(f"  n_bft(1)        = {n_bft(1)}")
    print(f"  majority_cft(5) = {majority_cft(5)}")
    print(f"  om_messages(4,1)= {om_messages(4, 1)}")
    print(f"  om_messages(7,2)= {om_messages(7, 2)}")
    print(f"  lamport_trace   = {[lamport_run(TRACE)[lbl][1] for _,lbl,_,_,_ in TRACE]}")
    lv = vector_run(TRACE)
    print(f"  vector_x_vs_a   = {vcmp(lv['x'], lv['a'])}")
    print(f"  vector_x_vs_y   = {vcmp(lv['x'], lv['y'])}")
    print(f"  bft_threshold   = N >= 3f+1")

    # assertions (these pin the values the .html recomputes)
    assert n_cft(1) == 3 and n_bft(1) == 4
    assert majority_cft(5) == 3
    assert om_messages(4, 1) == 9
    assert om_messages(7, 2) == 156
    lam = lamport_run(TRACE)
    assert [lam[lbl][1] for _, lbl, _, _, _ in TRACE] == [1, 2, 3, 1, 4, 5]
    assert vcmp(lv["x"], lv["a"]) == "concurrent"
    assert vcmp(lv["x"], lv["y"]) == "a->b"
    print("\n[check] 3f+1 threshold, OM message counts, Lamport+vector traces all hold: OK")


# ---------------------------------------------------------------------------
def main():
    print("distributed_systems.py - fundamentals. All numbers below feed")
    print("DISTRIBUTED_SYSTEMS.md. Python stdlib only (math for reliability/drift).")
    print()
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
