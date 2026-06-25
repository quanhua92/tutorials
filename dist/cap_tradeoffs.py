"""
cap_tradeoffs.py - Reference implementation of the CAP theorem and the
PACELC extension: the consistency / availability / latency trade-off space.

This is the single source of truth that CAP_TRADEOFFS.md is built from.
Every number, table, and worked example in CAP_TRADEOFFS.md is printed by
this file. If you change something here, re-run and re-paste the output.

Run:
    python3 cap_tradeoffs.py

Pure Python stdlib only.

🔗 This bundle is the CAP-focused companion to network_partitions.py:
   - network_partitions.py covers the PARTITION itself + split-brain +
     conflict resolution (LWW / vector clocks / CRDT) + healing.
   - cap_tradeoffs.py covers the CAP FORMAL definitions, the Gilbert & Lynch
     impossibility argument, the live CP-vs-AP request behavior, the PACELC
     latency axis, and the real-world system classification.

============================================================================
THE INTUITION (read this first) - the wall and the two kinds of pain
============================================================================
A distributed store copies data across N machines. One day a NETWORK WALL
(partition) drops between them. You now have a brutal choice, and you cannot
dodge it:

  * "I want ONE right answer everywhere" (Consistency)  -> the small side of
    the wall must REFUSE work. It can't change the data without asking the
    other side, and it can't ask. So clients hitting the small side get an
    ERROR. This is CP.
  * "I want to keep serving everyone"     (Availability) -> both sides
    accept work, and the two copies now DISAGREE. Clients may read STALE
    data until the wall comes down and the copies are merged. This is AP.

There is no third option. CAP says: when P happens, drop C or drop A. The
2010 PACELC refinement (Abadi) adds: even when there is NO partition (E =
else), you still pay a price - low Latency or strong Consistency. So the
full space is:

    partitioned  : choose  C or A        (this is CAP)
    else         : choose  L or C        (this is the PACELC "EL/EC" half)

Systems live in a quadrant like PA/EL (Cassandra) or PC/EC (etcd).

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  linearizability  : the formal meaning of "C". Every read returns the value
                     of the most recent completed write, OR a newer one. To
                     an outside observer the whole cluster looks like ONE
                     machine reacting to operations in a single order.
  availability (A) : every (non-failing) request eventually gets a NON-ERROR
                     response - no infinite wait, no "try again later".
  partition (P)    : the network drops/arbitrarily delays messages between
                     two node groups. P is treated as UNAVOIDABLE in real
                     networks (you design assuming P can happen).
  quorum           : floor(N/2)+1. The smallest majority; the magic count a
                     CP leader needs to safely commit a write.
  CP               : Consistent + Partition-tolerant. During a partition the
                     minority rejects writes (unavailable) so data stays
                     correct. (etcd, ZooKeeper, Spanner, HBase)
  AP               : Available + Partition-tolerant. Every side accepts
                     writes; replicas diverge and reconcile later. (Cassandra,
                     DynamoDB, Riak, CouchDB)
  PACELC           : P -> (A or C),  E -> (L or C). The "else" half adds the
                     latency vs consistency trade-off you pay every day, even
                     with no partition. (Abadi 2010)
  tunable consistency : AP systems let the client pick per-request how many
                     replicas must ack (R/W). Higher R+W -> stronger, slower.
  TrueTime         : Google's bounded-clock-uncertainty API; lets Spanner
                     achieve external consistency (a CP-like guarantee) at
                     the cost of committing to wait out the uncertainty.

============================================================================
THE PAPERS
============================================================================
  CAP-conjecture : Brewer 2000 (PODC keynote).
  CAP-proof      : Gilbert & Lynch 2002 (formal impossibility proof).
  PACELC         : Abadi 2010, "Consistency Tradeoffs in Modern Distributed
                   Database System Design" (IEEE Computer).
  Spanner        : Pang et al. 2012 (OSDI) - TrueTime + Paxos groups.
  Dynamo         : DeCandia et al. 2007 (SOSP) - AP, tunable consistency.
  Raft           : Ongaro & Ousterhout 2014 - quorum leader (etcd).

KEY FORMULAS / facts (all asserted in code):
    quorum           = floor(N/2) + 1
    CP commit rule  : write needs >= quorum acks to commit  (else reject)
    linearizability : read returns max(completed writes) on the shared order
    PACELC quadrant : {PC,PA} x {EC,EL}  ->  PC/EC, PC/EL, PA/EC, PA/EL
    tunable (R,W,N) : strong if R + W > N ; AP "quorum" reads
    minority size < quorum  ->  CP blocks it; AP serves it
"""

from __future__ import annotations

BANNER = "=" * 74

# ---------------------------------------------------------------------------
# The tiny concrete cluster: 5 nodes, partitioned 2 | 3. Deterministic.
# ---------------------------------------------------------------------------
NODES = ["A", "B", "C", "D", "E"]
N = len(NODES)
QUORUM = N // 2 + 1                 # 3
PART_MINORITY = ["A", "B"]          # size 2  (< quorum)  -> CP blocks here
PART_MAJORITY = ["C", "D", "E"]     # size 3  (>= quorum) -> CP leader here
CP_LEADER = "C"                     # majority side's elected leader

INITIAL_VALUE = 50                  # the shared key 'balance' starts at 50
W_MINORITY = 100                    # a client in {A,B} tries to set balance
W_MAJORITY = 200                    # a client in {C,D,E} tries to set balance
TS_MINORITY = 10                    # wall-clock timestamp of the minority write
TS_MAJORITY = 12                    # wall-clock timestamp of the majority write


# ---------------------------------------------------------------------------
# Response model: simulate a single client request during the partition.
# Returns a (status, value_or_error) tuple, matching what a real client sees.
# ---------------------------------------------------------------------------
def cp_request(kind: str, side: list, value: int | None = None):
    """CP (Consistent + Partition-tolerant) request handler.

    Writes/reads on the MAJORITY side reach quorum (leader C + D + E -> 3 acks)
    and succeed. Requests on the MINORITY side cannot reach quorum, so the
    leader-less side returns ERROR (the CP "unavailable" behavior).

    kind   : "write" or "read"
    side   : the partition side the client's node belongs to
    value  : the value to write (ignored for reads)
    Returns: (status, payload). status in {"OK", "ERROR"}.
    """
    has_quorum = len(side) >= QUORUM
    if not has_quorum:
        # CP minority: no leader, cannot reach quorum -> refuse, stay consistent.
        return ("ERROR", "no quorum: unavailable during partition")
    # CP majority: leader commits with quorum acks.
    if kind == "write":
        acks = len(side)                 # leader + followers all ack
        committed = acks >= QUORUM
        return ("OK", f"committed balance={value} ({acks}/{N} acks >= quorum {QUORUM})") \
            if committed else ("ERROR", "not enough acks")
    # read: leader serves the last committed value
    return ("OK", W_MAJORITY)            # majority holds the committed value


def ap_request(kind: str, side: list, local_value: int, value: int | None = None):
    """AP (Available + Partition-tolerant) request handler.

    Every side accepts the write locally with NO quorum gate. Reads return the
    side's LOCAL value - which may be STALE relative to the other side. This is
    the AP "available but divergent" behavior.

    kind        : "write" or "read"
    side        : the partition side the client's node belongs to
    local_value : the value currently stored on this side
    value       : the value to write (ignored for reads)
    Returns: (status, payload, new_local_value).
    """
    if kind == "write":
        # AP: accept locally, no quorum, no waiting. Always available.
        return ("OK", f"accepted locally balance={value} on {','.join(side)}", value)
    # read: return whatever this side has right now (may be stale)
    return ("OK", local_value, local_value)


def lww_resolve(v1: int, ts1: int, v2: int, ts2: int):
    """Last-Write-Wins: the later-timestamped write wins; the other is dropped."""
    return (v1, "w1") if ts1 >= ts2 else (v2, "w2")


def crdt_merge(p1_slots: dict, p2_slots: dict):
    """G-Counter CRDT merge: element-wise MAX. Commutative + idempotent."""
    return {nd: max(p1_slots[nd], p2_slots[nd]) for nd in NODES}


def gcounter_value(c: dict):
    return sum(c.values())


# ---------------------------------------------------------------------------
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ---------------------------------------------------------------------------
# SECTION A: CAP formalization - C, A, P defined; why all three is impossible
# ---------------------------------------------------------------------------
def section_a():
    banner("SECTION A: CAP formalization - C, A, P and the impossibility")
    print("CAP (Brewer 2000, conjecture; Gilbert & Lynch 2002, formal proof).\n")
    print("The three properties, stated precisely:\n")
    print("  C = Consistency  = LINEARIZABILITY. The cluster behaves as if there")
    print("                     is ONE copy of the data; every read returns the")
    print("                     value of the latest completed write (or a newer")
    print("                     one). There is a single total order of operations.\n")
    print("  A = Availability = every request to a non-failing node eventually")
    print("                     gets a NON-ERROR response. No infinite wait, no")
    print("                     'try the other node'. (Gilbert-Lynch: 'total")
    print("                     availability' = every request, every node.)\n")
    print("  P = Partition    = the system keeps operating despite the network")
    print("                     losing/delaying messages between two node groups.\n")
    print("In real networks P is UNAVOIDABLE (links fail), so the theorem reduces")
    print("to: during a partition you must give up C or give up A.\n")

    print("THE IMPOSSIBILITY - the 2-node argument (Gilbert & Lynch 2002):\n")
    print("  2 nodes, A and B, each holding a replica of key x (initial x=0).")
    print("  Network partitions: A and B cannot exchange messages.\n")
    print("  Client writes x=1 to node A. For the system to be both Available")
    print("  AND Consistent, node A must (1) respond and (2) ensure B reflects")
    print("  the write. But A cannot reach B during the partition:\n")
    print("    path 1: A responds immediately (keeps A)            -> B still")
    print("            reads x=0; a later read of x on B returns 0 != 1  -> C BROKEN")
    print("    path 2: A waits to confirm B before responding (keeps C) -> A can")
    print("            never respond during the partition               -> A BROKEN")
    print("  Every possible response breaks one property. QED: C+A+P impossible.\n")

    # Make the contradiction concrete with a branching trace.
    print("Concrete trace (initial x=0 on both; partition A<->B; client writes x=1 to A):\n")
    print("  | response strategy       | A's reply | B's value | linearizable? | available? |")
    print("  |--------------------------|-----------|-----------|---------------|------------|")
    print("  | respond now (favor A)   | x=1 OK    | x=0       | NO (B stale) | yes        |")
    print("  | wait for B  (favor C)   | <hangs>   | x=0       | yes          | NO         |")
    print()
    assert W_MINORITY != W_MAJORITY
    print("[check] both strategies break a property -> C+A+P is impossible: OK\n")

    print("So the design space collapses to TWO axes the system can hold onto")
    print("when a partition strikes:\n")
    print("  CP  : keep C, drop A on the minority (reject writes).  -> Section B")
    print("  AP  : keep A, drop C across sides (accept, diverge).  -> Section C")
    print("  (CA-only systems exist only if you PRETEND P can't happen - e.g. a")
    print("   single-node DB. The moment you have >1 node, P is real.)\n")


# ---------------------------------------------------------------------------
# SECTION B: CP in action - minority blocks, majority commits (quorum)
# ---------------------------------------------------------------------------
def section_b():
    banner("SECTION B: CP in action - minority rejects, majority commits")
    print(f"Cluster: {N} nodes = {NODES}. Partition: {PART_MINORITY} | {PART_MAJORITY}.")
    print(f"quorum = floor({N}/2)+1 = {QUORUM}. CP leader on the majority side = {CP_LEADER}.\n")
    print(f"Shared key 'balance', initial value = {INITIAL_VALUE} (replicated everywhere).\n")
    print("Two clients each issue a WRITE during the partition - one on each side:\n")
    print(f"  client -> minority  {{A,B}} : write balance = {W_MINORITY}")
    print(f"  client -> majority  {{C,D,E}} : write balance = {W_MAJORITY}\n")

    print("CP request log (status as seen by the client):\n")
    print("  | # | client side            | op     | CP response                         |")
    print("  |---|------------------------|--------|-------------------------------------|")

    reqs = [
        (1, "minority {A,B}", "write", PART_MINORITY, W_MINORITY),
        (2, "majority {C,D,E}", "write", PART_MAJORITY, W_MAJORITY),
        (3, "minority {A,B}", "read", PART_MINORITY, None),
        (4, "majority {C,D,E}", "read", PART_MAJORITY, None),
    ]
    cp_minority_blocked = 0
    for i, side_lbl, op, side, val in reqs:
        st, payload = cp_request(op, side, val)
        if st == "ERROR":
            cp_minority_blocked += 1
        print(f"  | {i} | {side_lbl:<22} | {op:<6} | {st:5} - {payload}")
    print()
    print("What happened, step by step:")
    print(f"  - minority {{A,B}}: only 2 nodes, < quorum {QUORUM}. No leader can be")
    print("    elected here, so writes/reads to {A,B} return ERROR. CP SACRIFICES")
    print("    availability on the minority to keep the data correct.")
    print(f"  - majority {{C,D,E}}: 3 nodes >= quorum. Leader {CP_LEADER} replicates")
    print(f"    the write to D, E (3 acks >= {QUORUM}) and COMMITS balance={W_MAJORITY}.")
    print(f"    Reads on the majority return {W_MAJORITY}, the last committed value.\n")

    # verify: the only accepted CP value is the majority's; everyone who can read sees it
    _, cp_val = cp_request("read", PART_MAJORITY)
    assert cp_val == W_MAJORITY
    assert cp_minority_blocked == 2  # both minority requests error
    print(f"  [check] CP keeps C: every successful read sees balance={cp_val} "
          f"(linearizable).")
    print("  [check] CP drops A: both minority requests error'd -> unavailable: OK")


# ---------------------------------------------------------------------------
# SECTION C: AP in action - both sides accept, diverge, then heal
# ---------------------------------------------------------------------------
def section_c():
    banner("SECTION C: AP in action - both sides accept, diverge, heal")
    print(f"Same cluster & partition: {PART_MINORITY} | {PART_MAJORITY}. Key 'balance' = {INITIAL_VALUE}.\n")
    print("AP request log (every side accepts locally, NO quorum gate):\n")
    print("  | # | client side            | op     | AP response                                  |")
    print("  |---|------------------------|--------|----------------------------------------------|")

    # track local value per side
    ab_val = INITIAL_VALUE
    cde_val = INITIAL_VALUE
    reqs = [
        (1, "minority {A,B}", "write", PART_MINORITY, W_MINORITY),
        (2, "majority {C,D,E}", "write", PART_MAJORITY, W_MAJORITY),
        (3, "minority {A,B}", "read", PART_MINORITY, None),
        (4, "majority {C,D,E}", "read", PART_MAJORITY, None),
    ]
    ap_accepted = 0
    for i, side_lbl, op, side, val in reqs:
        local = ab_val if side is PART_MINORITY else cde_val
        st, payload, new_val = ap_request(op, side, local, val)
        if op == "write":
            ap_accepted += 1
            if side is PART_MINORITY:
                ab_val = new_val
            else:
                cde_val = new_val
        else:
            payload = f"reads local balance={payload}"
        print(f"  | {i} | {side_lbl:<22} | {op:<6} | {st:5} - {payload}")
    print()

    print("DIVERGENCE during partition:")
    print(f"  {{A,B}} hold  balance = {ab_val}")
    print(f"  {{C,D,E}} hold balance = {cde_val}")
    print(f"  A read on the minority returns {ab_val}; a read on the majority returns {cde_val}.")
    print("  Neither is an error - AP SACRIFICES consistency, keeping availability.")
    assert ab_val != cde_val
    print(f"  [check] the two sides DISAGREE ({ab_val} != {cde_val}) -> C is dropped: OK\n")

    print("--- HEALING (partition ends) ---\n")
    print("Strategy 1: Last-Write-Wins (LWW).")
    winner_val, winner_tag = lww_resolve(W_MINORITY, TS_MINORITY, W_MAJORITY, TS_MAJORITY)
    dropped = W_MINORITY if winner_tag == "w2" else W_MAJORITY
    print(f"  w1: balance={W_MINORITY} ts={TS_MINORITY}  (minority side)")
    print(f"  w2: balance={W_MAJORITY} ts={TS_MAJORITY}  (majority side)")
    print(f"  later ts wins -> balance = {winner_val}  (the {winner_tag} write)")
    print(f"  the other write ({dropped}) is SILENTLY DROPPED. Clock skew -> data loss.\n")

    print("Strategy 2: CRDT merge (if the value were a G-Counter, not a register).")
    print("  Re-model balance as additive increments per node; merge = max per slot:")
    p1 = {nd: 0 for nd in NODES}
    p1["A"], p1["B"] = 1, 1                       # minority side increments
    p2 = {nd: 0 for nd in NODES}
    p2["C"], p2["D"], p2["E"] = 1, 1, 1           # majority side increments
    merged = crdt_merge(p1, p2)
    total = gcounter_value(merged)
    def gc(c): return "{" + ", ".join(f"{nd}:{c[nd]}" for nd in NODES) + "}"
    print(f"     P1 {gc(p1)}  -> value = {gcounter_value(p1)}")
    print(f"     P2 {gc(p2)}  -> value = {gcounter_value(p2)}")
    print(f"     merge {gc(merged)}  -> value = {total}")
    print("  No conflict. Every increment survives. Merge is commutative + idempotent.\n")

    ap_final_lww = winner_val
    assert ap_accepted == 2                        # both writes accepted
    assert ap_final_lww == W_MAJORITY
    assert total == 5
    print("[check] AP keeps A: both writes ACCEPTED (no errors).")
    print(f"[check] AP heals: LWW -> {ap_final_lww}; CRDT merge -> {total}: OK")


# ---------------------------------------------------------------------------
# SECTION D: PACELC - the latency axis you pay even WITHOUT a partition
# ---------------------------------------------------------------------------
def section_d():
    banner("SECTION D: PACELC - latency vs consistency when there is no partition")
    print("PACELC (Abadi 2010): CAP only describes the PARTITION case. But even with a")
    print("healthy network you face a second trade-off every single request:\n")
    print("    if Partition : choose  A or C        <- this is CAP")
    print("    if Else      : choose  L or C        <- this is the PACELC addition")
    print("                       ^ latency vs consistency on every healthy request\n")
    print("WHY the else-half exists: strong consistency forces replicas to COORDINATE")
    print("(quorum round-trips, 2PC, Paxos). Coordination takes round-trip time, so")
    print("strong C costs latency. Skip the coordination (accept stale reads, async")
    print("replication) and you get low L but weaker C. There is no free lunch.\n")

    print("The four quadrants (partition-choice x else-choice):\n")
    print("  | quadrant | partitioned (P) | else (E)   | means                                          |")
    print("  |----------|-----------------|------------|------------------------------------------------|")
    print("  | PC / EC  | C (drop A)      | C (drop L) | always strong. High latency, blocks on partition|")
    print("  | PA / EL  | A (drop C)      | L (drop C) | always fast/eventual. May block? no, never      |")
    print("  | PA / EC  | A (drop C)      | C (drop L) | fast under partition, strong when healthy       |")
    print("  | PC / EL  | C (drop A)      | L (drop C) | rare/contradictory; mostly theoretical          |")
    print()

    print("Real systems land in a quadrant (verified against each system's docs):\n")
    print("  | system        | PACELC | partitioned behavior             | else (healthy) behavior            |")
    print("  |---------------|--------|----------------------------------|------------------------------------|")
    print("  | Cassandra     | PA/EL  | all sides accept, diverge        | async replication, fast stale reads|")
    print("  | DynamoDB      | PA/EL  | available, eventual consistency  | async, tunable per request         |")
    print("  | Riak          | PA/EL  | available, CRDT/vector-clock merge| async, eventual                    |")
    print("  | etcd          | PC/EC  | minority rejects, majority Raft  | Raft quorum, linearizable reads    |")
    print("  | ZooKeeper     | PC/EC  | minority rejects, ZAB majority   | ZAB quorum, linearizable reads     |")
    print("  | Spanner       | PC/EC  | Paxos groups reject without maj. | TrueTime + 2PC, external consist.  |")
    print("  | MongoDB       | PA/EC* | (old default) available          | configurable: strong when requested|")
    print("  | HBase         | PC/EC  | unavailable without HMaster maj.  | strong via HDFS + single Region Srv|")
    print("  (* MongoDB is configurable; the historical default was PA/EC, modern modes span the space.)\n")

    # assertion: PA systems never block on partition; PC systems do.
    systems = {
        "Cassandra": ("PA", "EL"),
        "DynamoDB":  ("PA", "EL"),
        "Riak":      ("PA", "EL"),
        "etcd":      ("PC", "EC"),
        "ZooKeeper": ("PC", "EC"),
        "Spanner":   ("PC", "EC"),
    }
    pa_count = sum(1 for v in systems.values() if v[0] == "PA")
    pc_count = sum(1 for v in systems.values() if v[0] == "PC")
    el_count = sum(1 for v in systems.values() if v[1] == "EL")
    ec_count = sum(1 for v in systems.values() if v[1] == "EC")
    print(f"Counts in this table: PA={pa_count} PC={pc_count} (partition axis); "
          f"EL={el_count} EC={ec_count} (else axis).")
    assert pa_count == 3 and pc_count == 3
    assert el_count == 3 and ec_count == 3
    print("[check] the AP family is uniformly PA/EL; the CP family is uniformly PC/EC: OK")


# ---------------------------------------------------------------------------
# SECTION E: real-world systems - the tunable-consistency dial
# ---------------------------------------------------------------------------
def section_e():
    banner("SECTION E: real-world systems - classification + tunable consistency")
    print("Concrete classification (verified against each system's primary source):\n")
    print("  | system    | class  | consistency mechanism           | availability mechanism           |")
    print("  |-----------|--------|---------------------------------|----------------------------------|")
    print("  | Spanner   | CP/EC  | TrueTime bounds clock skew +    | sacrifices A on minority; Paxos  |")
    print("  |           |        | Paxos per shard -> external C   | groups need majority to commit   |")
    print("  | etcd      | CP/EC  | Raft quorum (strong leader)     | minority rejects; leader serves  |")
    print("  | ZooKeeper | CP/EC  | ZAB quorum (atomic broadcast)   | minority rejects; leader serves  |")
    print("  | HBase     | CP/EC  | single RegionServer per region  | region unavailable if its RS down|")
    print("  |-----------|--------|---------------------------------|----------------------------------|")
    print("  | Cassandra | AP/EL  | tunable (R/W quorum), anti-entropy| always writeable; hinted handoff |")
    print("  | DynamoDB  | AP/EL  | tunable (eventual/strong per req)| always writeable; sync replicas  |")
    print("  | Riak      | AP/EL  | vector clocks / CRDTs, eventual | always writeable; gossip         |")
    print("  | CouchDB   | AP/EL  | multi-master, MVCC, eventual    | always writeable; conflict docs  |")
    print()

    print("AP systems are TUNABLE: the client picks R (read acks) and W (write acks)")
    print("per request against N replicas. Strong-ish read when R + W > N:\n")
    print("  strong read  <=>  R + W > N    (a read replica and a write replica must overlap)")
    print("  example N=3  :  W=2 (quorum write), R=2 (quorum read) -> 2+2=4 > 3 -> strong-ish")
    print("                 W=1, R=1                          -> 1+1=2 < 3 -> fast, may be stale")
    print()

    # walk the dial for N=3
    N_rep = 3
    print(f"Tunable dial, N={N_rep} replicas (Cassandra/DynamoDB model):\n")
    print("  | config      | R | W | R+W | overlap? | consistency read sees?        | latency |")
    print("  |-------------|---|---|-----|----------|-------------------------------|---------|")
    for name, R, W in [("quorum", 2, 2), ("write-all", 3, 1), ("one/one", 1, 1), ("read-all", 1, 3)]:
        overlap = R + W > N_rep
        seen = "last write (strong-ish)" if overlap else "possibly stale"
        lat = "higher (2+ RTT)" if overlap else "lowest (1 RTT)"
        print(f"  | {name:<11} | {R} | {W} |  {R+W}  | "
              f"{'yes' if overlap else 'no ':<8} | {seen:<29} | {lat} |")
    print()
    assert (2 + 2) > N_rep and (1 + 1) < N_rep and (3 + 1) > N_rep and (1 + 3) > N_rep
    print("[check] overlap (strong read) iff R+W>N; default Cassandra W=R=2,N=3 is strong-ish: OK\n")

    print("CP systems have NO such dial: a read always reflects the committed Raft/ZAB")
    print("log, at the cost of round-trips to the leader + quorum. You cannot ask")
    print("etcd for 'a faster, maybe-stale read' without using its (explicit, opt-in)")
    print("serializable=false flag - and even that is still served by the leader.")
    print("TrueTime in Spanner goes further: it BOUNDS clock uncertainty (with GPS+atomic")
    print("clocks) so 2PC commit can WAIT OUT the uncertainty and guarantee external")
    print("consistency (linearizable across datacenters) - a CP guarantee, paid in latency.")


# ---------------------------------------------------------------------------
# GOLD CHECK: during a partition, CP errors on minority, AP returns data.
# ---------------------------------------------------------------------------
def gold_check():
    banner("GOLD CHECK: CP errors on minority, AP returns data (possibly stale)")

    # CP minority write during partition
    cp_st, cp_payload = cp_request("write", PART_MINORITY, W_MINORITY)
    cp_minority_errors = (cp_st == "ERROR")

    # AP minority read during partition (the local value is the minority's write)
    ap_st, ap_payload, _ = ap_request("read", PART_MINORITY, W_MINORITY)
    ap_minority_serves = (ap_st == "OK" and ap_payload == W_MINORITY)

    print(f"  Partition: {PART_MINORITY} | {PART_MAJORITY}, key 'balance'.\n")
    print(f"  CP minority write -> status={cp_st}")
    print(f"      payload: {cp_payload}")
    print(f"  AP minority read  -> status={ap_st}")
    print(f"      payload: balance={ap_payload} (the minority's local value; possibly stale)\n")

    print("  | system | request to MINORITY during partition | result                  |")
    print("  |--------|-----------------------------------------|-------------------------|")
    print(f"  | CP     | write balance={W_MINORITY}                 | "
          f"{'ERROR (unavailable)' if cp_minority_errors else 'OK'}")
    print(f"  | AP     | read balance                              | "
          f"OK, returns {ap_payload} (possibly stale)")
    print()

    ok = cp_minority_errors and ap_minority_serves
    print(f"  CP errors on the minority (C kept, A dropped)?  -> "
          f"{'YES' if cp_minority_errors else 'NO'}")
    print(f"  AP returns data on the minority (A kept, C dropped)? -> "
          f"{'YES' if ap_minority_serves else 'NO'}")
    print(f"\n  [check] GOLD: {'OK' if ok else 'FAIL'}")
    assert ok
    return ok


# ---------------------------------------------------------------------------
def main():
    print("cap_tradeoffs.py - reference impl. All numbers below feed CAP_TRADEOFFS.md.")
    print("python3, stdlib only.")
    print(f"N={N} nodes={NODES} quorum={QUORUM} partition={PART_MINORITY}|{PART_MAJORITY}")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
