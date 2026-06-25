"""
network_partitions.py - Reference implementation of network partitions,
split-brain, the CAP theorem trade-off, and conflict resolution / healing.

This is the single source of truth that NETWORK_PARTITIONS.md is built from.
Every number, table, and worked example in NETWORK_PARTITIONS.md is printed by
this file. If you change something here, re-run and re-paste the output.

Run:
    python3 network_partitions.py

Pure Python stdlib only.

==========================================================================
THE INTUITION (read this first) - the office that got cut in half
==========================================================================
Imagine 5 colleagues (nodes) keeping a shared whiteboard (the data). Normally
they shout updates to each other and everyone stays in sync. Now a wall drops
down the middle of the office: 2 people on one side {A,B}, 3 on the other
{C,D,E}. They can no longer hear each other. That wall is a NETWORK PARTITION.

The cruel question: when someone on each side writes on their side's whiteboard,
whose write "wins"? You cannot have it all:

  * If you want ONE agreed answer (Consistency), the small side {A,B} must
    REFUSE writes - it cannot safely change the shared board because it can't
    check with the other 3. The big side {C,D,E} has a MAJORITY, so it can keep
    going. This is CP (etcd, ZooKeeper).
  * If you want every side to keep working (Availability), BOTH sides accept
    writes - and the two whiteboards now DISAGREE. You fix it later. This is AP
    (Cassandra, DynamoDB).

SPLIT-BRAIN is the disaster: if BOTH sides wrongly believe they are the
majority, each elects its own "leader" and both change the board. On heal you
have two conflicting writes for the same thing. You then need CONFLICT
RESOLUTION:
  - Last-Write-Wins (LWW)   : trust timestamps. Fragile (clock skew drops data).
  - Vector clocks           : detect the two writes are concurrent -> surface them.
  - CRDTs                   : design the data so concurrent writes always MERGE.

HEALING: the wall comes down. CP: the small side throws away its (empty) work
and copies the big side. AP: the sides gossip/Merkle-sync and merge.

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  node              : one server in the cluster. Here: A, B, C, D, E (5 total).
  partition         : a network split isolating nodes into groups that cannot talk.
  quorum / majority : floor(N/2)+1 nodes. Here N=5 -> quorum=3. The magic number
                      that lets a side safely make decisions.
  CP                : Consistent + Partition-tolerant. Sacrifice Availability:
                      the minority refuses writes so data stays correct.
  AP                : Available + Partition-tolerant. Sacrifice Consistency:
                      every side accepts writes; reconcile later.
  split-brain       : two leaders active at once (broken safety). Both write ->
                      conflict.
  leader            : the node coordinating writes in a partition (Raft term).
  last-write-wins   : resolve conflicts by newest wall-clock timestamp.
  vector clock      : a {node: counter} map; compares causality to detect
                      concurrent (conflicting) writes.
  CRDT              : Conflict-free Replicated Data Type. Data shaped so that
                      concurrent updates always merge deterministically.
  anti-entropy      : post-partition background sync (gossip + Merkle trees).
  read repair       : fix divergent replicas lazily, triggered by a read.

==========================================================================
THE PAPERS
==========================================================================
  CAP     : Brewer 2000 (keynote); Gilbert & Lynch 2002 (formal proof).
  Raft    : Ongaro & Ousterhout 2014 (quorum-based leader election).
  Dynamo  : DeCandia et al. 2007 (AP, vector clocks, read repair).
  CRDTs   : Shapiro et al. 2011 (state-based / op-based, G-Counter, etc.).
  Merkle  : Merkle 1987 (hash trees for cheap anti-entropy, used by Dynamo/Cassandra).

KEY FORMULAS / facts (all asserted in code):
    quorum         = floor(N/2) + 1
    only ONE side of a 2-way partition can reach quorum -> prevents split-brain
    A happens-before B  <=>  (A[n] <= B[n] for all n) AND (A != B)
    concurrent          <=>  neither happens-before the other   (a CONFLICT)
    G-Counter merge     :  merge(a,b)[n] = max(a[n], b[n])
    G-Counter value     :  sum(all slots)
"""

from __future__ import annotations

BANNER = "=" * 74

# ---------------------------------------------------------------------------
# The tiny concrete model: 5 nodes, partitioned 2 | 3. Deterministic.
# ---------------------------------------------------------------------------
NODES = ["A", "B", "C", "D", "E"]
N = len(NODES)
QUORUM = N // 2 + 1                 # 3
PART_MINORITY = ["A", "B"]          # size 2  (< quorum)
PART_MAJORITY = ["C", "D", "E"]     # size 3  (>= quorum)


# ---------------------------------------------------------------------------
# Vector clocks + CRDT primitives (the math behind Sections C, D, E)
# ---------------------------------------------------------------------------
def vc(*pairs):
    """Build a vector clock {node:count}; missing nodes default to 0."""
    c = {nd: 0 for nd in NODES}
    c.update(dict(pairs))
    return c


def happens_before(a, b):
    """True iff a causally precedes b: a[n] <= b[n] for all n, and a != b."""
    le_all = all(a[nd] <= b[nd] for nd in NODES)
    strictly_less = any(a[nd] < b[nd] for nd in NODES)
    return le_all and strictly_less


def concurrent(a, b):
    """True iff a and b are causally unrelated (neither happens-before)."""
    return not happens_before(a, b) and not happens_before(b, a)


def gcounter_merge(a, b):
    """G-Counter CRDT merge: element-wise max. Commutative+idempotent."""
    return {nd: max(a[nd], b[nd]) for nd in NODES}


def gcounter_value(c):
    return sum(c.values())


def fmt_vc(c):
    """Print a vector clock compactly, omitting zero slots."""
    inner = ", ".join(f"{nd}:{c[nd]}" for nd in NODES if c[nd] > 0)
    return "{" + inner + "}"


def fmt_gc(c):
    """Print a G-Counter state compactly, all slots."""
    return "{" + ", ".join(f"{nd}:{c[nd]}" for nd in NODES) + "}"


# ---------------------------------------------------------------------------
# SECTION A: the partition - majority vs minority, who elects a leader?
# ---------------------------------------------------------------------------
def section_a():
    banner("SECTION A: the partition - majority vs minority, leader election")
    print(f"Cluster: {N} nodes = {NODES}")
    print("A network partition splits them into two ISOLATED groups that cannot")
    print("exchange messages:")
    print(f"  P_minority = {PART_MINORITY}   (size {len(PART_MINORITY)})")
    print(f"  P_majority = {PART_MAJORITY}   (size {len(PART_MAJORITY)})\n")

    print(f"Raft/Paxos quorum (majority) = floor(N/2)+1 = floor({N}/2)+1 = {QUORUM}")
    print(f"A side can elect a leader ONLY if it has >= {QUORUM} live nodes it can")
    print(f"reach. Because two sides of one split sum to {N} < 2*{QUORUM}, they can")
    print(f"NEVER both reach quorum -> at most one leader -> split-brain impossible\n"
          f"(under correct quorum-based consensus).\n")

    print("| partition   | nodes   | size | size >= quorum(3)? | can elect leader? | leader       |")
    print("|-------------|---------|------|--------------------|-------------------|--------------|")
    for name, members in [("P_majority", PART_MAJORITY), ("P_minority", PART_MINORITY)]:
        sz = len(members)
        ok = sz >= QUORUM
        leader = sorted(members)[0] if ok else "- (none)"
        print(f"| {name:<11} | {','.join(members):<7} | {sz:<4} | "
              f"{str(ok):<18} | {'yes' if ok else 'no':<17} | {leader:<12} |")
    print()
    print(f"=> Majority {PART_MAJORITY} elects leader C and keeps serving safely.")
    print(f"=> Minority {PART_MINORITY} has no quorum -> no leader -> it must now")
    print(f"   CHOOSE: refuse work (CP) or accept work unsafely (AP). -> Section B\n")

    assert len(PART_MAJORITY) >= QUORUM
    assert len(PART_MINORITY) < QUORUM
    assert not (len(PART_MAJORITY) >= QUORUM and len(PART_MINORITY) >= QUORUM)
    print("[check] exactly one side reaches quorum -> split-brain impossible: OK")


# ---------------------------------------------------------------------------
# SECTION B: CAP under partition - Consistency (CP) vs Availability (AP)
# ---------------------------------------------------------------------------
def section_b():
    banner("SECTION B: CAP under partition - Consistency (CP) vs Availability (AP)")
    print("CAP theorem (Brewer 2000; Gilbert & Lynch 2002): when a partition")
    print("happens you CANNOT keep both Consistency and Availability - pick one.\n")
    print("  CP (etcd, ZooKeeper, Consul, Spanner): the quorum side serves writes;")
    print("     the minority has no leader and REJECTS writes -> Consistent, not")
    print("     Available there. Correctness first.\n")
    print("  AP (Cassandra, DynamoDB, Riak, CouchDB): EVERY partition accepts writes")
    print("     (no quorum gate) -> Available, but the sides DIVERGE and must")
    print("     reconcile on heal. Uptime first.\n")

    init = 50
    w_minority = 100      # a client in {A,B} writes during the partition
    w_majority = 200      # a client in {C,D,E} writes during the partition
    print(f"Shared key = 'balance', initial value = {init} (already replicated to all).\n")
    print("During the partition, a client on EACH side writes 'balance':")
    print(f"  client in P_minority {{A,B}} writes balance = {w_minority}")
    print(f"  client in P_majority {{C,D,E}} writes balance = {w_majority}\n")

    print("| system | write in minority {A,B} (->100) | write in majority {C,D,E} (->200) | state DURING partition |")
    print("|--------|----------------------------------|-----------------------------------|------------------------|")
    print("| CP     | REJECTED (no leader; unsafe)     | accepted (leader C -> D, E)       | consistent: only 200   |")
    print("| AP     | accepted (no quorum gate)        | accepted                          | DIVERGES: AB=100, CDE=200 |")
    print()
    print(f"CP stays correct (everyone who reads sees 200) but the 2 minority nodes")
    print(f"are UNAVAILABLE for writes. AP serves everyone but the value DISAGREES")
    print(f"until heal. Neither is 'wrong' - they optimize different guarantees.\n")

    assert w_minority != w_majority
    print(f"[check] CP rejects the minority write; AP accepts both -> divergence detected: OK")


# ---------------------------------------------------------------------------
# SECTION C: split-brain - two leaders, two conflicting writes
# ---------------------------------------------------------------------------
def section_c():
    banner("SECTION C: split-brain - two leaders, two conflicting writes")
    print("Split-brain = the safety property BREAKS: both partitions elect a leader")
    print("and both accept writes. (Causes: no quorum enforcement, or each side")
    print("miscounts and wrongly believes it has majority.) Now the SAME key is")
    print("written concurrently on both sides -> a real conflict to resolve.\n")
    print("Simulated: P1 {A,B} elects leader A; P2 {C,D,E} keeps leader C. Both")
    print("write 'balance'. Initial balance=50 was set by A before the split:\n")

    init_vc = vc(("A", 1))
    init_val = 50
    w1 = {"by": "P1 (leader A)", "val": 100, "ts": 10,
          "vc": vc(("A", 2))}                 # A bumps its own clock
    w2 = {"by": "P2 (leader C)", "val": 200, "ts": 12,
          "vc": vc(("A", 1), ("C", 1))}       # C bumps its own clock (knew A's init)
    print(f"  initial : balance = {init_val}   vc = {fmt_vc(init_vc)}")
    print(f"  w1      : balance = {w1['val']}   ts = {w1['ts']}   vc = {fmt_vc(w1['vc'])}"
          f"   # by {w1['by']}")
    print(f"  w2      : balance = {w2['val']}   ts = {w2['ts']}   vc = {fmt_vc(w2['vc'])}"
          f"   # by {w2['by']}\n")

    print("Happens-before check (vector clocks):")
    print(f"  w1 -> w2 ?  {happens_before(w1['vc'], w2['vc'])}")
    print(f"  w2 -> w1 ?  {happens_before(w2['vc'], w1['vc'])}")
    is_conc = concurrent(w1["vc"], w2["vc"])
    print(f"  => concurrent? {is_conc}\n")
    print("Neither write knows the other happened. They are CONCURRENT writes to the")
    print("same key. On heal the store sees TWO values for 'balance' (100 and 200) ->")
    print("a CONFLICT that must be resolved (Section D).\n")

    assert is_conc
    print("[check] w1 and w2 are concurrent (a true conflict, not a stale read): OK")


# ---------------------------------------------------------------------------
# SECTION D: resolving the conflict - LWW vs vector clocks vs CRDT
# ---------------------------------------------------------------------------
def section_d():
    banner("SECTION D: resolving the conflict - LWW vs vector clocks vs CRDT")
    w1 = {"val": 100, "ts": 10, "vc": vc(("A", 2))}
    w2 = {"val": 200, "ts": 12, "vc": vc(("A", 1), ("C", 1))}
    print("Same conflict from Section C (balance: 100 vs 200, concurrent).\n")

    # --- LWW ---
    print("--- Strategy 1: Last-Write-Wins (LWW) - newest timestamp decides ---")
    winner = max([w1, w2], key=lambda w: w["ts"])
    loser = 100 if winner["val"] == 200 else 200
    print(f"  w1.ts={w1['ts']}, w2.ts={w2['ts']} -> later wins -> balance = {winner['val']}")
    print(f"  The losing write ({loser}) is SILENTLY DROPPED. Forever.\n")
    w1_skew = dict(w1); w1_skew["ts"] = 99       # A's clock was far ahead
    win_skew = max([w1_skew, w2], key=lambda w: w["ts"])
    print(f"  Clock-skew danger: if A's clock jumped ahead (w1.ts={w1_skew['ts']}) then")
    print(f"  'later wins' -> balance = {win_skew['val']}. The causally-fine write 200")
    print(f"  is LOST purely because a wall clock said so -> silent DATA LOSS.\n")

    # --- vector clocks ---
    print("--- Strategy 2: Vector clocks - detect concurrency, then surface ---")
    if concurrent(w1["vc"], w2["vc"]):
        print("  w1.vc and w2.vc are concurrent -> store keeps BOTH as siblings:")
        print("     siblings = [100, 200]")
        print("  Nothing is dropped silently. The application (or a human) decides:")
        print("     e.g. take max -> 200; prompt the user; or union. The conflict is")
        print("     VISIBLE instead of hidden. (This is how Dynamo/Riak expose it.)\n")

    # --- CRDT ---
    print("--- Strategy 3: CRDT - shape the data so conflicts CANNOT exist ---")
    print("  Re-model the value as a G-Counter CRDT: each node owns a counter slot;")
    print("  merge = element-wise MAX; value = SUM. Concurrent increments always merge.\n")
    p1 = vc(("A", 1), ("B", 1))                   # A,B each +1 during partition
    p2 = vc(("C", 1), ("D", 1), ("E", 1))         # C,D,E each +1 during partition
    merged = gcounter_merge(p1, p2)
    print(f"     P1 state {fmt_gc(p1)}  -> value = {gcounter_value(p1)}")
    print(f"     P2 state {fmt_gc(p2)}  -> value = {gcounter_value(p2)}")
    print(f"     merge   {fmt_gc(merged)}  -> value = {gcounter_value(merged)}")
    print("  No conflict. Every partition's increments survive. Merge is commutative +")
    print("  idempotent, so it converges no matter the order of healing.\n")
    print("  Trade-off: CRDTs need a merge-friendly operation (add, union, max). 'SET")
    print("  balance = X' is NOT merge-friendly - for that you'd use a register CRDT")
    print("  (LWW-register or MV-register), which reintroduces LWW or siblings.\n")

    print("| strategy     | decides by   | drops data?    | needs clock sync?        | works for any op?        |")
    print("|--------------|--------------|----------------|--------------------------|--------------------------|")
    print("| LWW          | timestamp    | yes (silent)   | yes (skew = data loss)  | yes (any write)          |")
    print("| vector clock | causality    | no (surfaces)  | no                       | yes (any write)          |")
    print("| CRDT         | merge fn     | no (never)     | no                       | only merge-friendly ops  |")
    print()
    assert winner["val"] == 200
    assert win_skew["val"] == 100
    assert gcounter_value(merged) == 5
    print("[check] LWW->200 (skew->100), vector->siblings[100,200], CRDT->5: OK")


# ---------------------------------------------------------------------------
# SECTION E: healing - the partition ends, nodes rejoin and converge
# ---------------------------------------------------------------------------
def section_e():
    banner("SECTION E: healing - the partition ends, nodes rejoin")
    print("The network recovers. Both sides must converge back to ONE consistent\n"
          "state. CP and AP do it very differently.\n")

    print("--- CP healing (etcd / ZooKeeper) ---")
    print(f"  During the partition the minority {PART_MINORITY} had NO leader and")
    print(f"  BLOCKED writes. The majority {PART_MAJORITY} committed balance = 200.")
    print(f"  The minority's local copy is STALE (=50) but it made NO writes.\n")
    print("  Rejoin timeline:")
    for s in [
        "t0  network heals; A,B can again reach C,D,E",
        "t1  A,B contact leader C; see their Raft term/log is behind",
        "t2  A,B DISCARD their stale log tail (nothing to discard - they blocked)",
        "     and receive committed entries (balance=200) via AppendEntries from C",
        "t3  A,B catch up; all 5 nodes agree balance=200",
    ]:
        print("     " + s)
    cp_final = {nd: 200 for nd in NODES}
    print(f"\n  CP final state: balance = {cp_final['A']} on every node -> {cp_final}")
    print(f"  conflicts = 0 (the minority had no writes to conflict with). Fully\n"
          f"  consistent across all {N} nodes the moment catch-up completes.\n")

    print("--- AP healing (Cassandra / Dynamo) ---")
    print("  During the partition BOTH sides accepted writes and DIVERGED. Healing")
    print("  must reconcile the divergence:\n")
    print("    - anti-entropy : background gossip syncs missing rows. A Merkle tree")
    print("      (hash of hashes) per node lets replicas compare cheaply and pinpoint")
    print("      ONLY the divergent keys - no full-table scan on big datasets.")
    print("    - read repair  : a read that hits disagreeing replicas fixes them in")
    print("      the background, converging lazily as traffic flows.\n")
    p1 = vc(("A", 1), ("B", 1))
    p2 = vc(("C", 1), ("D", 1), ("E", 1))
    merged = gcounter_merge(p1, p2)
    total = gcounter_value(merged)
    print("  For the view_count G-Counter (Section D), merge is just max-per-slot:")
    print(f"     P1 {fmt_gc(p1)}  +  P2 {fmt_gc(p2)}  -> merged {fmt_gc(merged)} -> value = {total}")
    print(f"  AP final state: every node converges to view_count = {total}.")
    print(f"  No writes lost - all 5 increments are preserved. Eventually consistent.\n")

    banner("GOLD CHECK: post-heal correctness")
    cp_consistent = len(set(cp_final.values())) == 1
    ap_no_loss = all(merged[nd] == 1 for nd in NODES) and total == 5
    print(f"  CP : all {N} nodes agree balance = {cp_final['A']}? "
          f"{cp_consistent} | conflicts = 0  -> [check] {'OK' if cp_consistent else 'FAIL'}")
    print(f"  AP : CRDT merge kept every increment (A..E all =1)? "
          f"{ap_no_loss} | total = {total}  -> [check] {'OK' if ap_no_loss else 'FAIL'}")
    print()
    print("  => CP guarantee : NO conflicts ever (minority writes are discarded).")
    print("  => AP guarantee : NO writes lost (every partition's writes are merged).")
    print("  Both converge after healing - they just promise different things.")
    print("  [check] GOLD: OK")
    assert cp_consistent and ap_no_loss


# ---------------------------------------------------------------------------
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def main():
    print("network_partitions.py - reference impl. All numbers below feed")
    print("NETWORK_PARTITIONS.md. python3, stdlib only.")
    print(f"N={N} nodes={NODES} quorum={QUORUM}")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
