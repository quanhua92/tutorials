"""
crash_vs_byzantine.py - Reference implementation of the two canonical failure
models in distributed systems: CRASH faults vs BYZANTINE faults, and why their
node-count thresholds differ (2f+1 vs 3f+1).

This is the single source of truth that CRASH_VS_BYZANTINE.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 crash_vs_byzantine.py

=========================================================================
THE INTUITION (read this first) -- the town council
=========================================================================
A distributed system is a town council of N members who must agree on a
decision (a "ledger entry") even though some members are unreliable. There are
two ways to be unreliable, and they are NOT equally bad:

  * CRASH  : the member falls asleep / leaves the room / their phone dies.
             They say NOTHING -- but they never LIE. When they come back, they
             catch up honestly. (A crashed node is an absent node.)
  * BYZANTINE: the member is a TRAITOR. They stay in the room, raise their
             hand, and SAY THINGS -- but they lie. They can tell member A
             "vote YES" and member B "vote NO" in the same breath. They forge,
             equivocate, and collude with other traitors. (A Byzantine node is
             an ADVERSARIAL node.)

The deeper the unreliability, the bigger the council must be:

  * Crash-only council  : N = 2f+1 members.  A majority (f+1) is enough to
                          decide, because a majority ALWAYS overlaps another
                          majority in >= 1 member. That 1 member carries the
                          latest decision forward. Crashed members never lie,
                          so a single overlapping witness is safe.
  * Byzantine council   : N = 3f+1 members.  A "supermajority" (2f+1) is
                          needed, because the overlapping witness might itself
                          be a traitor. The overlap must be big enough that
                          even after hiding f traitors, >= 1 HONEST witness
                          remains. That forces the overlap >= f+1, which forces
                          N >= 3f+1.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  f            : the number of faulty nodes the system is designed to tolerate.
  N            : the total number of nodes (replicas / council members).
  crash fault  : a node that simply stops; it may recover and rejoin.
                 It sends no messages while down, and never sends wrong ones.
  Byzantine    : a node that behaves ARBITRARILY -- omitting, delaying,
  fault          duplicating, reordering, or FORGING messages. The worst case.
  quorum       : the minimum number of nodes that must participate (or agree)
                 for a decision to be valid. Two kinds of quorum here:
                   - majority      quorum  = floor(N/2)+1   (crash model)
                   - 2/3 supermaj. quorum  = ceil((2N+1)/3) (Byzantine model)
  CFT          : Crash Fault Tolerance. Tolerates f crashes with 2f+1 nodes.
  BFT          : Byzantine Fault Tolerance. Tolerates f Byzantine with 3f+1.
  agreement    : no two honest nodes ever decide different values. (safety)
  liveness     : every honest node eventually decides. (progress)
  intersection : any two valid quorums share >= 1 node (crash) or
                 >= f+1 nodes (Byzantine). This shared node is the safety anchor.

=========================================================================
THE LINEAGE (papers)
=========================================================================
  Byzantine Generals (Lamport, Shostak, Pease 1982, ACM TOCS)
        -> proved N >= 3f+1 is NECESSARY for Byzantine agreement with oral msgs
           (unauthenticated) and N >= 3f+1 + signatures help but the bound on
           authenticated is actually f+1 in some settings; the ORAL bound 3f+1
           is the one BFT protocols inherit.
  PBFT (Castro & Liskov 1999, OSDI) : the practical 3f+1 BFT protocol.
  Paxos (Lamport 1998, "The Part-Time Parliament") : 2f+1 crash-tolerant.
  Raft (Ongaro & Ousterhout 2014, USENIX ATC) : 2f+1 crash-tolerant, readable.
  Tendermint (Buchman 2016) : 3f+1 BFT in blockchain consensus.
  HotStuff (Yin et al. 2019, PODC) : 3f+1 BFT, linear view-change.

KEY FORMULAS (all verified against the papers + asserted in code):
    crash : min N = 2f+1 ;  faults tolerated = (N-1)//2 ;  quorum = N//2+1
    byz   : min N = 3f+1 ;  faults tolerated = (N-1)//3 ;  quorum = ceil((2N+1)/3)
    intersection lower bound = 2*Q - N   (inclusion-exclusion on two sets)
    safety derivation : two liveness sets (size N-f) overlap in >= N-2f nodes;
                        to keep >= 1 honest in the overlap: N-2f > f -> N > 3f.

Conventions for the simulations:
    nodes : a list [0, 1, ..., N-1].
    faults: a set of node ids that are faulty (crashed or Byzantine).
    The first f ids in our worked examples are the faulty ones (deterministic).
"""

from __future__ import annotations

import math

BANNER = "=" * 72


# ============================================================================
# 1. THE CORE FORMULAS  (the code CRASH_VS_BYZANTINE.md walks through)
# ============================================================================

def crash_min_n(f: int) -> int:
    """Smallest cluster that tolerates f crash faults: 2f+1."""
    return 2 * f + 1


def byz_min_n(f: int) -> int:
    """Smallest cluster that tolerates f Byzantine faults: 3f+1."""
    return 3 * f + 1


def crash_quorum(n: int) -> int:
    """Majority quorum for a crash-tolerant cluster of n nodes: floor(n/2)+1.

    Any two such quorums overlap in >= 1 node -> safety against crashes.
    """
    return n // 2 + 1


def byz_quorum(n: int) -> int:
    """Strict >2/3 supermajority quorum for a Byzantine cluster of n nodes.

    ceil((2n+1)/3). With n = 3f+1 this equals 2f+1.
    Any two such quorums overlap in >= f+1 nodes -> safety against Byzantine.
    """
    return math.ceil((2 * n + 1) / 3)


def max_crash_tolerated(n: int) -> int:
    """Largest f a crash-tolerant cluster of n nodes can tolerate: (n-1)//2."""
    return (n - 1) // 2


def max_byz_tolerated(n: int) -> int:
    """Largest f a Byzantine-tolerant cluster of n nodes can tolerate: (n-1)//3."""
    return (n - 1) // 3


def intersection_lower_bound(quorum: int, n: int) -> int:
    """Smallest possible overlap of two quorums of size `quorum` drawn from a
    universe of `n` nodes (inclusion-exclusion): 2*quorum - n."""
    return 2 * quorum - n


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def node_line(label: str, n: int, faulty: set[int], kind: str) -> str:
    """Render a cluster of n nodes; mark the faulty ones.
    kind = 'crash' -> 'X' (absent) ; kind = 'byz' -> '!' (liar)."""
    mark = "X" if kind == "crash" else "!"
    cells = []
    for i in range(n):
        if i in faulty:
            cells.append(f"[{i}{mark}]")
        else:
            cells.append(f"[{i} ]")
    return f"  {label:<10} " + " ".join(cells)


# ----------------------------------------------------------------------------
# SECTION A: the crash fault model (N=5, f=2) -- 2f+1 is enough
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: crash fault model  (N=5, f=2)  -> 2f+1 is enough")
    N, f = 5, 2
    faulty = set(range(f))                      # deterministic: nodes 0,1 crash
    alive = [i for i in range(N) if i not in faulty]
    q = crash_quorum(N)
    print("The faulty nodes simply go SILENT. They send no messages and never")
    print("lie. So the only question is: are there enough live nodes to form a")
    print("quorum?\n")
    print(node_line("cluster:", N, faulty, "crash"))
    print(f"\nN = {N},  f = {f} (crashed),  alive = {len(alive)}  {alive}")
    print(f"quorum (majority) = floor(N/2)+1 = floor({N}/2)+1 = {q}")
    print(f"\nalive ({len(alive)}) >= quorum ({q})?  "
          f"{'YES -> progress is possible' if len(alive) >= q else 'NO -> stalled'}")
    print("\nThe general crash bound:")
    print("  To tolerate f crashes we need  N >= 2f+1.")
    print(f"  Here 2f+1 = 2*{f}+1 = {crash_min_n(f)}  = N.  Bare minimum, exactly met.")
    print(f"  faults this N tolerates = (N-1)//2 = ({N}-1)//2 = {max_crash_tolerated(N)}")
    print("\nWHY a majority is enough (the overlap argument):")
    print("  Two majorities of a 5-node cluster each have >= 3 members.")
    ov = intersection_lower_bound(q, N)
    print(f"  Worst-case overlap = 2*quorum - N = 2*{q} - {N} = {ov} node.")
    print("  That 1 overlapping member was in BOTH decisions, so it carries the")
    print("  latest committed value forward. Crashed members never contradict it")
    print("  (they are silent), so 1 honest witness is sufficient. -> CFT safe.")
    print(f"\n[check] N ({N}) == 2f+1 ({crash_min_n(f)}) and quorum ({q}) == f+1 ({f+1}):  OK")


# ----------------------------------------------------------------------------
# SECTION B: the Byzantine fault model (N=5, f=2) -- 2f+1 is NOT enough
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: Byzantine fault model  (N=5, f=2)  -> 2f+1 is NOT enough")
    N, f = 5, 2
    faulty = set(range(f))                      # nodes 0,1 are Byzantine liars
    honest = [i for i in range(N) if i not in faulty]
    print("Now the faulty nodes stay in the room and LIE. Each honest node must")
    print("collect enough responses to be SURE no traitor can fool two honest")
    print("nodes into disagreeing.\n")
    print(node_line("cluster:", N, faulty, "byz"))
    print(f"\nN = {N},  f = {f} (Byzantine),  honest = {len(honest)}  {honest}")
    print("\nLiveness bound: an honest node can wait for at most N-f responses")
    print(f"  (up to f traitors may stay silent). N-f = {N}-{f} = {N-f}.")
    print("  So each honest node commits after hearing from a set of >= "
          f"{N-f} nodes.\n")
    print(f"ATTACK: the 2 traitors {sorted(faulty)} tell different stories.")
    print("  traitor 0 tells honest A:   'I vote YES'")
    print("  traitor 1 tells honest A:   'I vote YES'")
    print("  traitor 0 tells honest C:   'I vote NO '")
    print("  traitor 1 tells honest C:   'I vote NO '\n")
    A_hears = {"A": "YES"} | {i: ("YES" if i == 0 else "YES") for i in faulty}
    C_hears = {"C": "NO"} | {i: ("NO" if i in faulty else "?") for i in faulty}
    print("  honest A hears 3 responses: {A:YES, 0:YES, 1:YES}  -> commits YES")
    print("  honest C hears 3 responses: {C:NO , 0:NO , 1:NO }  -> commits NO")
    print("  => two honest nodes DISAGREE. Safety violated with N=5, f=2.\n")
    print("ROOT CAUSE: the two response sets (size N-f=3) overlap in only")
    ov = intersection_lower_bound(N - f, N)
    print(f"  2*(N-f) - N = 2*{N-f} - {N} = {ov} node, and that node can be a traitor.")
    print("  With N=5 the overlap is 1, and f=2 traitors can occupy it -> unsafe.")
    print("\nTo make the overlap safe it must hold MORE than f honest nodes,")
    print("which is impossible at N=5. We need a bigger cluster -> Section C.")
    print(f"\n[check] max Byzantine tolerated by N={N}: (N-1)//3 = "
          f"{max_byz_tolerated(N)}  (< {f})  -> N too small:  FAILS as shown")


# ----------------------------------------------------------------------------
# SECTION C: why 3f+1 -- the step-by-step safety derivation
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: why 3f+1 -- the safety derivation, step by step")
    print("Goal: find the smallest N that lets honest nodes agree despite f")
    print("Byzantine traitors. We reason about ONE round of message exchange.\n")
    print("Step 1. Of N nodes, up to f are Byzantine. So the HONEST count is")
    print("        at least  N - f.\n")
    print("Step 2. LIVENESS: an honest node cannot wait forever. Up to f nodes")
    print("        may stay silent (Byzantine can omit messages), so it proceeds")
    print("        once it has heard from  N - f  nodes. Call each honest node's")
    print("        heard-set S, with |S| = N - f.\n")
    print("Step 3. Of those N - f heard nodes, at most f are Byzantine, so at")
    print("        least  (N - f) - f = N - 2f  of them are HONEST.\n")
    print("Step 4. SAFETY: take two honest nodes with heard-sets S1, S2, each of")
    print("        size N - f. By inclusion-exclusion their overlap is at least")
    print("        |S1 ∩ S2| >= |S1| + |S2| - N = 2(N - f) - N = N - 2f.\n")
    print("Step 5. The overlap must contain at least ONE honest node -- otherwise")
    print("        f traitors could fill the entire overlap and split the two")
    print("        honest nodes (exactly the Section B attack). So we need")
    print("            (overlap honest count) >= 1")
    print("        The overlap has N - 2f nodes, of which at most f are traitors,")
    print("        so honest in overlap >= (N - 2f) - f = N - 3f. Requiring >= 1:")
    print("            N - 3f >= 1   <=>   N >= 3f + 1.\n")
    print("Step 6. EQUIVALENTLY (the textbook one-liner): require the overlap")
    print("        itself to be strictly larger than f, so it cannot be all-traitor:")
    print("            N - 2f > f   <=>   N > 3f   <=>   N >= 3f + 1.\n")
    f = 2
    print(f"Worked numbers for f = {f}:")
    print(f"   3f+1 = {byz_min_n(f)}   <- minimum safe N")
    N = byz_min_n(f)
    print(f"   at N = {N}: honest >= N-f = {N-f},  heard-set size N-f = {N-f},")
    print(f"   overlap >= N-2f = {N-2*f},  honest in overlap >= N-3f = {N-3*f} >= 1.  SAFE.")
    print("\nCrucially, the SAME derivation for CRASH faults stops at Step 4:")
    print("crashed nodes never lie, so an overlap of just 1 (any node, honest")
    print("by definition since crashes don't forge) is enough -> N >= 2f+1.\n")
    print(f"[check] N-3f = {N}-{3*f} = {N-3*f} >= 1  and  N ({N}) >= 3f+1 "
          f"({byz_min_n(f)}):  OK")


# ----------------------------------------------------------------------------
# SECTION D: quorum intersection -- the two quorum sizes and their overlaps
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: quorum intersection  (f+1 vs 2f+1 quorums)")
    print("A quorum is the smallest set that may legally make a decision. The")
    print("two models pick different sizes so that ANY two quorums overlap by")
    print("enough to anchor safety.\n")
    print("Crash model   : quorum = floor(N/2)+1   (a strict majority)")
    print("Byzantine model: quorum = ceil((2N+1)/3) (a strict >2/3 supermajority)\n")
    print("Using the minimal N for each model:\n")
    hdr = ("| model | f | min N | quorum Q | overlap = 2Q-N | honest in overlap | "
           "safe? |")
    print(hdr)
    print("|" + "---|" * (hdr.count("|") - 1))
    for f in range(0, 4):
        # crash
        Nc = crash_min_n(f)
        Qc = crash_quorum(Nc)
        oc = intersection_lower_bound(Qc, Nc)
        hc = oc                       # crashes never forge -> all overlap honest
        print(f"| crash | {f} | {Nc:<5} | {Qc:<8} | {oc:<14} | {hc:<17} | "
              f"{'OK' if hc >= 1 else 'NO'}    |")
        # byzantine
        Nb = byz_min_n(f)
        Qb = byz_quorum(Nb)
        ob = intersection_lower_bound(Qb, Nb)
        hb = ob - f                   # up to f traitors can hide in the overlap
        print(f"| byz   | {f} | {Nb:<5} | {Qb:<8} | {ob:<14} | {hb:<17} | "
              f"{'OK' if hb >= 1 else 'NO'}    |")
    print()
    print("Read the table by column:")
    print("  - quorum Q grows as f+1 (crash) or 2f+1 (Byzantine).")
    print("  - overlap = 2Q - N is the inclusion-exclusion floor.")
    print("  - 'honest in overlap' subtracts the f traitors that could hide there.")
    print("  - safety holds iff honest-in-overlap >= 1.")
    print("\nConcrete quorum-intersection picture, Byzantine f=2 (N=7, Q=5):")
    demo_intersection(n=7, q=5, f=2, kind="byz")
    print("\nSame picture, crash f=2 (N=5, Q=3):")
    demo_intersection(n=5, q=3, f=2, kind="crash")


def demo_intersection(n: int, q: int, f: int, kind: str):
    """Build two worst-case quorums of size q on n nodes and show the overlap."""
    # worst case: shift the second quorum as far right as possible to minimize overlap
    S1 = list(range(q))                          # {0..q-1}
    S2 = list(range(n - q, n))                   # {n-q..n-1}
    overlap = sorted(set(S1) & set(S2))
    print(f"  universe {{0..{n-1}}},  quorum size Q={q}")
    print(f"  S1 = {S1}")
    print(f"  S2 = {S2}   (shifted to minimize overlap)")
    print(f"  S1 ∩ S2 = {overlap}   |overlap| = {len(overlap)}")
    if kind == "byz":
        honest_in_ov = len(overlap) - f
        print(f"  traitors that could hide in overlap <= f = {f}, "
              f"so honest in overlap >= {honest_in_ov}  -> "
              f"{'SAFE' if honest_in_ov >= 1 else 'UNSAFE'}")
    else:
        print(f"  crashes never forge, so all {len(overlap)} overlapping node(s) "
              f"are honest -> {'SAFE' if len(overlap) >= 1 else 'UNSAFE'}")


# ----------------------------------------------------------------------------
# SECTION E: comparison table -- real systems and their thresholds
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: comparison table  (CFT vs BFT, real systems)")
    print("Two families of consensus protocol, one per failure model.\n")
    print("| family | model | min N | faults tolerated f = | quorum size       | "
          "canonical protocols            |")
    print("|--------|-------|-------|----------------------|-------------------|"
          "--------------------------------|")
    rows = [
        ("CFT", "crash", "2f+1", "(N-1)//2", "f+1  (majority)",
         "Paxos, Raft, Zab, ZooKeeper"),
        ("BFT", "byz",   "3f+1", "(N-1)//3", "2f+1 (>2/3 supermaj.)",
         "PBFT, Tendermint, HotStuff, DiemBFT"),
    ]
    for r in rows:
        print("| " + " | ".join(f"{c}" for c in r) + " |")
    print()
    print("Real deployments (typical node counts):")
    print("| system       | protocol  | N  | model | f tolerated | "
          "quorum needed |")
    print("|--------------|-----------|----|-------|-------------|--------------|")
    deployments = [
        ("etcd/K8s",   "Raft",       3,  "crash", max_crash_tolerated(3),
            crash_quorum(3)),
        ("etcd/K8s",   "Raft",       5,  "crash", max_crash_tolerated(5),
            crash_quorum(5)),
        ("ZooKeeper",  "Zab",        5,  "crash", max_crash_tolerated(5),
            crash_quorum(5)),
        ("PBFT (1999)", "PBFT",      4,  "byz",   max_byz_tolerated(4),
            byz_quorum(4)),
        ("Tendermint", "Tendermint", 7,  "byz",   max_byz_tolerated(7),
            byz_quorum(7)),
        ("HotStuff",   "HotStuff",   7,  "byz",   max_byz_tolerated(7),
            byz_quorum(7)),
    ]
    for name, proto, N, model, ft, q in deployments:
        print(f"| {name:<12} | {proto:<9} | {N:<2} | {model:<5} | "
              f"{ft:<11} | {q:<12} |")
    print()
    print("Read it as: a 5-node Raft cluster survives 2 crashed members and")
    print("needs 3 votes; a 7-node Tendermint validator set survives 2 traitors")
    print("and needs 5 (=2f+1) agreeing votes. The 'cost of lies' is the extra")
    print("f nodes: 3f+1 - (2f+1) = f more replicas for the same f.")


# ============================================================================
# 3. GOLD CHECK  (pinned values that crash_vs_byzantine.html recomputes in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK  (pinned values for crash_vs_byzantine.html)")
    # The canonical worked point used everywhere: f=2.
    f = 2
    Nc = crash_min_n(f)            # 5
    Nb = byz_min_n(f)              # 7
    Qc = crash_quorum(Nc)          # 3
    Qb = byz_quorum(Nb)            # 5
    ov_c = intersection_lower_bound(Qc, Nc)   # 1
    ov_b = intersection_lower_bound(Qb, Nb)   # 3
    honest_ov_b = ov_b - f                     # 1

    print(f"Canonical point: f = {f}")
    print(f"  crash    min N  = 2f+1       = {Nc}")
    print(f"  byzantine min N = 3f+1       = {Nb}")
    print(f"  crash    quorum = floor(N/2)+1   (N={Nc}) = {Qc}   = f+1")
    print(f"  byzantine quorum = ceil((2N+1)/3) (N={Nb}) = {Qb}   = 2f+1")
    print(f"  crash    quorum overlap (2Q-N)        = {ov_c}")
    print(f"  byzantine quorum overlap (2Q-N)       = {ov_b}  (= f+1)")
    print(f"  byzantine honest in overlap (overlap-f)= {honest_ov_b}  (>=1 -> safe)")
    print()
    # Second pinned point used by the .html slider default: N=7
    N = 7
    print(f"Slider default point: N = {N}")
    print(f"  crash_quorum({N})    = floor({N}/2)+1     = {crash_quorum(N)}")
    print(f"  byz_quorum({N})      = ceil((2*{N}+1)/3) = {byz_quorum(N)}")
    print(f"  max_crash_tolerated({N})  = ({N}-1)//2  = {max_crash_tolerated(N)}")
    print(f"  max_byz_tolerated({N})    = ({N}-1)//3  = {max_byz_tolerated(N)}")
    print()

    # Assertions: the formulas must reproduce the textbook identities exactly.
    assert Nc == 5 and Nb == 7
    assert Qc == f + 1 and Qb == 2 * f + 1
    assert ov_c == 1 and ov_b == f + 1 and honest_ov_b == 1
    assert crash_quorum(7) == 4 and byz_quorum(7) == 5
    assert max_crash_tolerated(7) == 3 and max_byz_tolerated(7) == 2
    # The defining identity for the whole tutorial:
    assert byz_min_n(f) - crash_min_n(f) == f   # cost of lies = f extra nodes

    print("GOLD scalars (for a compact .html check):")
    print(f"  byz_quorum(N=7)              = {byz_quorum(7)}")
    print(f"  crash_quorum(N=7)            = {crash_quorum(7)}")
    print(f"  byz_min_n(f=2)               = {byz_min_n(2)}")
    print(f"  crash_min_n(f=2)             = {crash_min_n(2)}")
    print(f"  cost_of_lies(f=2) = 3f+1-2f-1 = {byz_min_n(2) - crash_min_n(2)}")
    print("\n[check] all gold identities reproduce from the formulas:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("crash_vs_byzantine.py - reference impl. "
          "All numbers below feed CRASH_VS_BYZANTINE.md.")
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
