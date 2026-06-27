"""
consistency_models.py - Consistency models, CAP tradeoffs, and quorum systems:
the hierarchy from linearizable down to eventual, the session guarantees, and
the R+W>N tunable-consistency dial.

This is the synthesized CONSISTENCY MODELS capstone of the dist/ suite. It ties
together linearizability, sequential, causal, eventual, session guarantees, CAP,
and quorum R/W into one coherent map. Every number, table, and worked example
below is printed by this file and recomputed live in consistency_models.html.

Run:
    python3 consistency_models.py

Pure Python stdlib only.

============================================================================
THE INTUITION (read this first) - the promise each read makes
============================================================================
A consistency model is the CONTRACT a data store makes about what value a read
returns, given a history of concurrent writes. Stronger models make bigger
promises (and cost more coordination); weaker ones are faster and more available
but let clients see anomalies (stale data, reordered writes). The models form a
HIERARCHY - linearizable (strongest) implies sequential implies causal implies
eventual (weakest). Pick the WEAKEST model that your data's product promise
allows:

  bank balance / inventory / leader election  -> LINEARIZABLE. Over-selling or
     split-brain is catastrophic. Pay the coordination cost (Raft/Paxos, 2PC).
  direct-message thread / comment replies     -> CAUSAL. A reply must appear
     after the message it answers, but independent chats need no global order.
  user's own profile edit                      -> READ-YOUR-WRITES. You must see
     your own write immediately; other users can be slightly behind.
  like / view / follower counts                -> EVENTUAL. Temporary undercount
     is fine; availability and low latency matter more than exact freshness.

THE TWO FORCES (CAP): during a network partition you must drop Consistency
(CP: the minority rejects writes) or Availability (AP: every side accepts and
replicas diverge). PACELC adds: even with NO partition you still trade Latency
vs Consistency every request - strong consistency forces quorum round-trips.

THE TUNABLE DIAL (quorums): in an AP store with N replicas, a write contacts W
of them and a read contacts R. The read is guaranteed to see the latest write
iff R + W > N - because then the read set and write set must OVERLAP in at
least one replica. Crank W and R up for freshness, down for speed.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  linearizability   : the STRONGEST practical model. The cluster looks like ONE
   (strong/strict)   machine reacting to operations in an order respecting
                      REAL-TIME: every read returns the value of the latest
                      completed write (or a newer one). Prevents stale reads.
                      Cost: multi-node coordination (consensus) on every op.
  sequential        : there is a single total order of ops consistent with each
   consistency       client's PROGRAM ORDER, but NOT necessarily real-time.
                      Weaker than linearizable (no real-time guarantee).
  causal consistency: ops that are CAUSALLY related (happens-before) are seen in
                      the SAME order by everyone; CONCURRENT ops may be seen in
                      different orders by different clients. The strongest model
                      that stays AVAILABLE under partition ("always available").
  eventual          : given no new writes, all replicas eventually CONVERGE to
   consistency       the same value. Makes NO real-time promise - reads may be
                      arbitrarily stale in the meantime. The weakest useful model.
  read-your-writes  : a SESSION guarantee. A client always sees its OWN writes.
   (RYW)             (Sticky routing or a write-through cache.) Linearizable RYW
                      globally; eventual systems need RYW added per-session.
  monotonic reads   : a SESSION guarantee. Once a client sees a value v, it never
                      later sees an OLDER value (no going back in time).
  monotonic writes  : a SESSION guarantee. A client's writes are applied in the
                      order it issued them.
  writes-follow-    : a SESSION guarantee. A client's read of x happens-before
   reads (WFR)       its later write to y for anyone observing y.
  anomaly           : an undesired read behavior. Each model prevents a subset:
     stale read        read returns an old value after a write committed
     lost update       a concurrent write is silently overwritten
     write skew        two txns read overlapping data and commit conflicting updates
     read inversion    a read sees a value that never globally existed
  quorum            : floor(N/2)+1. The magic count for majority decisions.
  R / W             : per-request tunables in an AP store - how many replicas must
                      ack a READ / WRITE. Strong-ish read iff R + W > N.
  CAP               : during a partition, drop C (CP) or A (AP).
  PACELC            : CAP + "Else" (no partition): trade Latency vs Consistency.

============================================================================
THE PAPERS
============================================================================
  Lamport 1979      "How to Make a Multiprocessor Computer That Correctly
                     Executes Multiprocess Programs" - linearizability seeds.
  Herlihy & Wing    1990 - linearizability formal definition.
  Lamport 1978      happens-before -> causal consistency foundation.
  Terry et al 1994  "Session Guarantees for Weakly Consistent Replicated Data"
                     - RYW, monotonic reads/writes, WFR (Bayou).
  Brewer 2000 /     CAP conjecture + formal proof.
   Gilbert-Lynch 2002
  Abadi 2010        PACELC.
  DeCandia et al    2007 - Dynamo; tunable N/R/W eventual consistency.
  Viotti & Vukolic  2016 - "Consistency Models Not Just a Story" (survey).

KEY FORMULAS / facts (all asserted in code):
    hierarchy      : linearizable > sequential > causal > {RYW, monotonic} > eventual
    quorum(N)      : floor(N/2) + 1
    strong read    : R + W > N   (read set and write set must overlap)
    intersection   : |R_set ∩ W_set| >= R + W - N  (>= 1 iff strong)
    linearizable   : prevents stale read, lost update, read inversion
    eventual       : prevents NOTHING in real-time; only guarantees convergence
============================================================================
"""

from __future__ import annotations

BANNER = "=" * 74

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def quorum(n: int) -> int:
    """Majority quorum size: floor(n/2)+1."""
    return n // 2 + 1


# The consistency hierarchy, strongest to weakest. Each entry:
# (name, family, strength_rank, prevents_stale_read, available_under_partition)
# strength_rank: 5=strongest ... 1=weakest. Used for the ordering assertion.
MODELS = [
    # name,               family,    rank, stale_ok?, avail_under_partition?
    ("linearizable",      "strong",   5,   False, False),
    ("sequential",        "strong",   4,   False, False),   # no real-time guarantee but no stale-by-completion
    ("causal",            "causal",   3,   True,  True),
    ("read-your-writes",  "session",  2,   True,  True),
    ("eventual",          "weak",     1,   True,  True),
]


# ---------------------------------------------------------------------------
# SECTION A: the hierarchy - what each model guarantees and prevents
# ---------------------------------------------------------------------------
def section_a():
    banner("SECTION A: the consistency hierarchy - what each model prevents")
    print("A consistency model is the CONTRACT about what a read returns. They nest:\n")
    print("  linearizable  >  sequential  >  causal  >  read-your-writes  >  eventual")
    print("  (strongest, most coordination)             (weakest, most available)\n")
    print("Each stronger model prevents EVERY anomaly the weaker one prevents, plus")
    print("more. Stronger = safer but slower (coordination round-trips) and less")
    print("available under partition.\n")
    print("  | model            | rank | stale read? | avail. under partition? | prevents          |")
    print("  |------------------|------|-------------|-------------------------|-------------------|")
    for name, fam, rank, stale_ok, avail in MODELS:
        prevents = "stale read + lost update" if not stale_ok else "convergence only"
        print(f"  | {name:<16} | {rank:>4} | "
              f"{'allowed' if stale_ok else 'PREVENTED':<11} | "
              f"{'YES' if avail else 'no (CP)':<23} | {prevents} |")
    print()
    print("STALE READ is the dividing line: linearizable/sequential PREVENT it; causal")
    print("and weaker ALLOW it (a read may return an old value). Linearizable adds a")
    print("REAL-TIME guarantee on top of sequential (once a write completes, every")
    print("later read sees it); sequential only guarantees program order.\n")
    print("AVAILABILITY under partition is the other axis: only the strong (CP) models")
    print("block the minority; causal and weaker stay AVAILABLE (AP) - which is why")
    print("causal is called 'the strongest ALWAYS-AVAILABLE model'.\n")

    # assert the hierarchy ordering is strictly decreasing in strength
    ranks = [m[2] for m in MODELS]
    assert ranks == sorted(ranks, reverse=True)
    assert MODELS[0][0] == "linearizable" and MODELS[-1][0] == "eventual"
    assert not MODELS[0][3]          # linearizable prevents stale read
    assert MODELS[-1][3]             # eventual allows stale read
    print("[check] hierarchy strictly ordered, linearizable prevents stale, eventual doesn't: OK")


# ---------------------------------------------------------------------------
# SECTION B: strong vs eventual - a concrete read-after-write trace
# ---------------------------------------------------------------------------
def section_b():
    banner("SECTION B: strong vs eventual - a concrete read-after-write trace")
    print("Concrete scenario: 3 replicas {A,B,C} hold key x. Initial x=0 everywhere.\n")
    print("Timeline (wall-clock, t in ms):\n")
    print("  t=0   x=0 on all replicas")
    print("  t=10  client W1 writes x=1   (write begins)")
    print("  t=20  write x=1 committed at the leader")
    print("  t=25  client R1 reads x")
    print("  t=30  replica C still has x=0 (async replication lag)\n")
    print("What does R1 see at t=25, depending on the model and which replica serves it?\n")
    print("  | model           | read served by A/B (has x=1) | served by C (x=0) | verdict        |")
    print("  |-----------------|------------------------------|-------------------|----------------|")
    print("  | linearizable    | x=1                          | x=1 (must consult) | CORRECT        |")
    print("  | eventual        | x=1                          | x=0               | STALE (allowed)|")
    print()
    print("Under LINEARIZABILITY the read at t=25 MUST return x=1: the write completed at")
    print("t=20, and real-time says t=25 > t=20, so every later read sees it. A linearizable")
    print("read cannot be served from a stale replica alone - it consults a quorum/leader.")
    print("Under EVENTUAL consistency, a read served by the lagging replica C returns x=0 -")
    print("a STALE read. This is ALLOWED (the model only promises eventual convergence),")
    print("but it is a real anomaly a user can observe.\n")
    print("This is exactly 'read-after-write' inconsistency: the user wrote x=1, then read")
    print("x and got the OLD value 0. RYW (Section D) and linearizability prevent it;\n")
    print("plain eventual consistency does not.\n")

    # the cost of linearizability: it needs a quorum round-trip
    n = 3
    print(f"COST: a linearizable read on N={n} replicas needs >= quorum={quorum(n)} acks")
    print(f"(a round-trip to a majority), so it is SLOWER than a 1-replica eventual read.")
    print("That latency is the price of 'no stale reads'. PACELC names this: when there is")
    print("no partition, you still trade Latency vs Consistency on every single request.\n")
    assert quorum(n) == 2
    print("[check] linearizable read returns x=1 (post-completion); eventual may return x=0: OK")


# ---------------------------------------------------------------------------
# SECTION C: causal consistency - the strongest always-available model
# ---------------------------------------------------------------------------
def section_c():
    banner("SECTION C: causal consistency - the strongest always-available model")
    print("CAUSAL consistency guarantees: if operation a HAPPENS-BEFORE b (a -> b), then")
    print("every client observes a before b. CONCURRENT operations (a || b) may be seen in")
    print("different orders by different clients - and that is fine, because there is no")
    print("causal dependency to violate.\n")
    print("Why it matters: causal is the STRONGEST model that stays AVAILABLE under a")
    print("partition. (Linearizable/sequential are NOT available under partition - they")
    print("need coordination.) So if you must keep serving writes during a split but still")
    print("want replies to appear after the messages they answer, causal is your ceiling.\n")
    print("Concrete example (a comment thread):\n")
    print("  m1: Alice posts 'Hello'                        (P1 writes m1)")
    print("  m2: Bob   replies 'Hi Alice'  (m2 causally->m1) (P2 writes m2, depends on m1)")
    print("  m3: Carol posts 'Nice weather' (m3 || m2)       (P3 writes m3, independent)\n")
    print("Under CAUSAL consistency, every reader sees m1 before m2 (causal dep), but m2")
    print("and m3 may appear in EITHER order (they are concurrent - no dependency):\n")
    print("  reader X sees: m1, m2, m3")
    print("  reader Y sees: m1, m3, m2     <- both LEGAL (m2||m3)\n")
    print("Under LINEARIZABILITY all readers see one identical total order. Under")
    print("EVENTUAL (without causal) a reader could even see m2 (Bob's 'Hi Alice') BEFORE")
    print("m1 (Alice's 'Hello') - a reply before the message it answers. That breaks the\n")
    print("product even though the data eventually converges.\n")
    print("Mechanism: track causality with VECTOR CLOCKS / version vectors (see")
    print("vector_clocks.py). A write carries the versions it read-from; a replica delays")
    print("applying a write until its causal dependencies are present. This is how")
    print("COPS / Bolt-on Causal and (effectively) chat systems work.\n")

    # the happens-before ordering within the example
    deps = {"m1": set(), "m2": {"m1"}, "m3": set()}     # m3 concurrent with m2
    # m2 -> m1 never; m1 -> m2 yes. m2 and m3: no dep either way => concurrent
    def related(a, b):
        return b in deps.get(a, set())
    assert related("m2", "m1") and not related("m3", "m2") and not related("m2", "m3")
    print("[check] m2 causally depends on m1; m2 and m3 are concurrent: OK")


# ---------------------------------------------------------------------------
# SECTION D: session guarantees - RYW, monotonic reads
# ---------------------------------------------------------------------------
def section_d():
    banner("SECTION D: session guarantees - read-your-writes & monotonic reads")
    print("SESSION guarantees (Terry et al 1994, Bayou) sit BETWEEN causal and eventual.")
    print("They bound what a SINGLE client's session can see, without paying for global")
    print("coordination. The two most-used:\n")
    print("  READ-YOUR-WRITES (RYW): if a client writes x=v, every later read of x by the")
    print("    SAME client returns v (or newer). You always see your own actions.\n")
    print("  MONOTONIC READS: once a client reads x=v, it never later reads an OLDER")
    print("    value of x. Time never runs backwards for that client.\n")
    print("Scenario: a user edits their profile name to 'Quan' then reloads the page.\n")
    print("  write:  name = 'Quan'   (at t=10, accepted by replica A)")
    print("  read at t=12 served by replica B (async lag, still has old 'Bob')\n")
    print("  | guarantee        | what the reload shows | ok?                |")
    print("  |------------------|-----------------------|---------------------|")
    print("  | none (plain ev.) | 'Bob' (stale)         | VIOLATION (confusing)|")
    print("  | read-your-writes | 'Quan'                | OK - sees own write  |")
    print("  | monotonic reads  | (n/a here)            | prevents regressions |")
    print()
    print("How RYW is implemented WITHOUT global linearizability:\n")
    print("  - STICKY SESSIONS: route the client's reads to the same replica that took")
    print("    its write (a load-balancer cookie / IP hash). Cheap, but fails on failover.\n")
    print("  - WRITE-THROUGH CACHE: the client caches its own writes; reads check the")
    print("    cache first. Survives replica changes.\n")
    print("  - VERSION STICKING: the read carries the write's version; the store delays")
    print("    the read until a replica has >= that version.\n")
    print("Monotonic reads is similar: remember the highest version seen and refuse to")
    print("read from a replica behind it. Both are PER-SESSION, so they cost nothing")
    print("globally - this is why social feeds use them (you see your own post, your feed")
    print("never jumps backwards) without paying for linearizability on every like.\n")

    # monotonic-reads violation example
    print("Monotonic-reads violation (what it prevents):")
    print("  t=1  read x from replica A -> sees version 5")
    print("  t=2  read x from replica C -> sees version 3   <- went BACKWARDS in time")
    print("  Monotonic reads forces t=2 to wait for version >= 5. Prevented.\n")
    print("[check] RYW => reload shows own write; monotonic reads => no backwards reads: OK")


# ---------------------------------------------------------------------------
# SECTION E: quorum systems - the R+W>N tunable dial
# ---------------------------------------------------------------------------
def section_e():
    banner("SECTION E: quorum systems - the R+W>N tunable dial")
    print("In an AP store (Dynamo/Cassandra) with N replicas, each request picks how many")
    print("replicas must acknowledge: W for a write, R for a read. The KEY identity:\n")
    print("   a read is guaranteed to see the latest committed write   <=>   R + W > N\n")
    print("WHY: the read contacts R replicas and the write contacted W. If R + W > N then")
    print("those two sets must OVERLAP in at least one replica (pigeonhole), and that")
    print("overlap replica holds the fresh value. The intersection size is:\n")
    print("   |R_set ∩ W_set| >= R + W - N      (>= 1 exactly when R + W > N)\n")
    print(f"Worked overlap table for N=3 replicas {{A,B,C}}, write to W=2 of them:\n")
    n = 3
    w = 2
    print("  | read R | R+W | >N? | can read miss the write? | verdict        |")
    print("  |--------|-----|-----|--------------------------|----------------|")
    for r in (1, 2, 3):
        overlap = r + w - n
        strong = r + w > n
        miss = "NO - every R-set hits {A,B}" if strong else "YES - could read only C"
        print(f"  | {r:<6} | {r+w:<3} | "
              f"{'YES' if strong else 'no ':<3} | {miss:<24} | "
              f"{'STRONG read' if strong else 'may be stale':<14} |")
    print()
    print("With W=2, R=2: R+W=4>3 -> STRONG (intersection >= 1). A read of 2 replicas")
    print("out of 3 MUST include A or B (the write set), so it sees the fresh value.")
    print("With W=2, R=1: R+W=3, NOT > 3 -> the single read replica could be C, which")
    print("missed the write -> stale. This is Cassandra's default-ish trade space.\n")

    print("The full tunable dial (N=3), from fastest/stalest to slowest/freshest:\n")
    print("  | config      | W | R | R+W | strong? | latency       | use when                  |")
    print("  |-------------|---|---|-----|---------|---------------|---------------------------|")
    dial = [("one/one", 1, 1), ("write-all", 3, 1), ("quorum", 2, 2),
            ("read-all", 1, 3), ("all/all", 3, 3)]
    for name, ww, rr in dial:
        strong = ww + rr > n
        lat = "lowest (1 RTT)" if not strong and (ww == 1 or rr == 1) else \
              ("higher (2+ RTT)" if strong else "medium")
        use = "counters, fast stale reads" if not strong else \
              ("profile/registry reads" if rr >= 3 else "bank-balance reads")
        print(f"  | {name:<11} | {ww} | {rr} |  {ww+rr}  | "
              f"{'YES' if strong else 'no ':<7} | {lat:<13} | {use} |")
    print()
    # same dial for N=5
    n5 = 5
    print(f"Quorum majority grows with N. For N={n5}: quorum = floor({n5}/2)+1 = {quorum(n5)}.")
    print("  W=R=3 (both quorum) -> 3+3=6 > 5 -> STRONG. This is the Dynamo/Cassandra")
    print("  'QUORUM reads/writes' default that gives strong-ish consistency on N=3 or N=5.\n")

    # assertions
    assert (2 + 2) > n and (1 + 1) < n and (3 + 1) > n and (1 + 3) > n
    assert quorum(n5) == 3
    assert (quorum(n5) + quorum(n5)) > n5
    print("[check] strong read iff R+W>N; N=5 quorum=3, 3+3=6>5 strong: OK")


# ---------------------------------------------------------------------------
# GOLD CHECK: CAP recap + data-type -> consistency model mapping (pinned)
# ---------------------------------------------------------------------------
def gold_check():
    banner("GOLD CHECK: CAP recap + data-type -> consistency model mapping")
    print("CAP (Brewer 2000 / Gilbert-Lynch 2002): during a partition you must drop")
    print("Consistency (CP) or Availability (AP). PACELC (Abadi 2010) adds: even with")
    print("NO partition you still trade Latency vs Consistency every request.\n")
    print("  | family | partitioned (CAP) | else (PACELC)  | example systems            |")
    print("  |--------|-------------------|----------------|----------------------------|")
    print("  | CP/EC  | drop A (block)    | drop L (quorum)| etcd, ZooKeeper, Spanner   |")
    print("  | AP/EL  | drop C (diverge)  | drop C (async) | Cassandra, DynamoDB, Riak  |")
    print()
    print("Which model to pick? Map each DATA TYPE to the weakest model its product")
    print("promise allows (the CAP/PACELC 'right tool' philosophy):\n")
    print("  | data type                   | model chosen    | why                                  |")
    print("  |------------------------------|-----------------|--------------------------------------|")
    print("  | bank balance / inventory    | LINEARIZABLE    | over-sell / split-brain is fatal     |")
    print("  | leader election / lock      | LINEARIZABLE    | two leaders = data corruption        |")
    print("  | DM thread / comment replies | CAUSAL          | reply must follow its parent message |")
    print("  | user's own profile edit     | READ-YOUR-WRITES| user must see own write immediately  |")
    print("  | like / view / follower count| EVENTUAL        | temp undercount ok; availability wins|")
    print("  | distributed shopping cart   | EVENTUAL + CRDT | concurrent adds must merge, not drop |")
    print()
    print("RULE OF THUMB: start with the WEAKEST model you can defend to product, and")
    print("escalate ONLY where an anomaly would cause real harm. Stronger models cost")
    print("latency (quorum round-trips) and availability (CP blocks the minority).\n")

    # pinned numbers for the .html
    print("GOLD scalars (for a compact .html check):")
    print(f"  models_count        = {len(MODELS)}")
    print(f"  strongest           = {MODELS[0][0]}")
    print(f"  weakest             = {MODELS[-1][0]}")
    print(f"  strongest_available = causal   (strongest model that survives a partition)")
    print(f"  stale_read_divider  = linearizable/sequential PREVENT; causal+ ALLOW")
    print(f"  quorum(3)           = {quorum(3)}")
    print(f"  quorum(5)           = {quorum(5)}")
    print(f"  strong_read_rule    = R + W > N")
    print(f"  strong_N3_W2_R2     = {'YES' if 2+2>3 else 'no'} (2+2=4>3)")
    print(f"  strong_N3_W1_R1     = {'YES' if 1+1>3 else 'no'} (1+1=2<3)")
    print(f"  intersection(N3,W2) = R+2-3")

    # assertions (pin the values the .html recomputes)
    assert len(MODELS) == 5
    assert MODELS[0][0] == "linearizable" and MODELS[-1][0] == "eventual"
    assert [m[2] for m in MODELS] == [5, 4, 3, 2, 1]
    assert quorum(3) == 2 and quorum(5) == 3
    assert (2 + 2) > 3 and not ((1 + 1) > 3)
    assert all(MODELS[i][2] > MODELS[i + 1][2] for i in range(len(MODELS) - 1))
    print("\n[check] hierarchy, CAP families, R+W>N strong rule all hold: OK")


# ---------------------------------------------------------------------------
def main():
    print("consistency_models.py - reference impl. All numbers below feed")
    print("CONSISTENCY_MODELS.md. Pure Python stdlib only.")
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
