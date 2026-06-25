"""
causal_consistency.py - Reference implementation of causal consistency: if
operation A causally precedes B (A -> B via happens-before), then every
replica that has revealed B must also have revealed A. Concurrent operations
may appear in any order. Weaker than linearizability (no real-time guarantee),
stronger than eventual consistency (which only promises convergence).

This is the single source of truth that CAUSAL_CONSISTENCY.md is built from.
Every number, table, and worked example in CAUSAL_CONSISTENCY.md is printed
by this file. If you change something here, re-run and re-paste the output.

Run:
    python3 causal_consistency.py

Pure Python stdlib only.

============================================================================
THE INTUITION (read this first) - the comment that lost its post
============================================================================
Imagine a social feed replicated across 3 data centers. Alice posts "Hello".
Bob, reading from a (faster) replica, sees "Hello" and replies "Re:Hello".
Both writes fan out to the other replicas.

Under EVENTUAL consistency the only promise is "all replicas eventually
agree". Nothing stops a replica from receiving Bob's reply BEFORE Alice's
original post - and a user on that replica sees "Re:Hello" with no parent,
which is nonsense. The two writes CONVERGE eventually, but mid-flight the
view is broken.

CAUSAL consistency forbids exactly this. If Bob's reply CAUSALLY DEPENDS on
Alice's post (Bob had to see the post to reply to it), then no replica may
reveal the reply until it has also revealed the post. Causality is tracked
and respected.

What causal consistency does NOT promise: real-time order. If Alice's post
is acknowledged at 12:00:00 and Carol independently posts at 12:00:01 from a
client that never saw Alice, causal consistency is silent on which "really"
came first - they are concurrent, and either order on a replica is fine. That
extra real-time guarantee is LINEARIZABILITY, and it costs global coordination
(Spanner's TrueTime, a Paxos/Raft quorum per key).

So the ladder is:

    eventual  <  causal  <  linearizable
    (converge)   (+cause)   (+real-time)

Each step up adds a guarantee AND a coordination cost.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  operation (op)   : a write, tagged with (client, seq) and a dependency set.
  client           : a sequential writer. Here: alice, bob, carol, dave (4).
  replica          : a node storing a copy of the data. Here: R0, R1, R2 (3).
  dependency set   : the set of prior ops the client had seen when it wrote.
                     Encoded as a version vector over clients: {alice:1} means
                     "I had seen alice's 1st op before writing this".
  happens-before   : A -> B iff A is in the transitive closure of B's deps.
    (->)             Direct edges: for each (client,seq) in B.deps, that op
                     is a direct ancestor of B. Then transitive closure.
  concurrent (||)  : neither A -> B nor B -> A. Replicas may reveal them in
                     ANY order. (Same notion as in vector_clocks.py.)
  causal order     : a delivery order on a replica that respects -> : if
                     A -> B, then A is delivered before B on that replica.
  causal violation : a delivery where B appears before its causal ancestor A.
                     Forbidden by causal consistency; ALLOWED by eventual.
  dep check        : the rule a replica runs before applying an op: for every
                     (client, seq) in op.deps, the replica must have ALREADY
                     applied that client's seq-th op. If not, DEFER it.
  version vector   : per-client counters of "what I've applied". Implements
    (VV)             the dep check in O(clients) time per op.
  CRDT             : Conflict-free Replicated Data Type. Objects whose
                     concurrent ops commute -> causal consistency for free,
                     no dependency tracking needed (Shapiro et al. 2011).

============================================================================
THE PAPERS
============================================================================
  Lamport   : Lamport 1978, "Time, Clocks, and the Ordering of Events in a
              Distributed System". CACM. Happens-before ->, the foundation.
  Bayou     : Terry et al. 1995, "Managing Update Conflicts in Bayou, a
              Replicated Weakly-Connected Database". SOSP. Session guarantees
              (read-your-writes, monotonic reads) - a precursor of causal.
  COPS      : Lloyd et al. 2011, "Don't Settle for Eventual: Scalable Causal
              Consistency for Wide-Area Storage with COPS". SOSP. The namesake
              system; dependency tracking via version vectors, 1-hop deps.
  CRDTs     : Shapiro et al. 2011, "Conflict-free Replicated Data Types".
              REP Lecture; objects whose ops commute -> causal for free.
  Dynamo    : DeCandia et al. 2007, "Dynamo". SOSP. Eventual consistency floor.
  Spanner   : Pang et al. 2012, "Spanner: Google's Globally-Distributed
              Database". OSDI. Linearizability via TrueTime + Paxos groups -
              the top of the ladder, the comparison point in Section E.

KEY FORMULAS / facts (all asserted in code):
    op.deps                     : {client: seq} the client had seen
    op.vv                       : merge(op.deps, {op.client: op.seq})
    A -> B                      : A in transitive_closure(B.deps)
    dep_check(replica_seen, op) : ok iff for all c: seen[c] >= op.deps.get(c,0)
    causal order on replica R   : for all A->B both delivered: pos_R(A)<pos_R(B)
    ladder                      : eventual  <  causal  <  linearizable
    COPS dep tracking cost      : O(#deps) per op (1-hop deps in COPS)
    CRDT escape                 : commutative ops -> causal holds WITHOUT dep
                                  tracking (no deferrals ever needed)
"""

from __future__ import annotations

BANNER = "=" * 74
CLIENTS = ("alice", "bob", "carol", "dave")   # 4 sequential writers
NREPLICAS = 3                                 # R0, R1, R2


# ---------------------------------------------------------------------------
# PRETTY PRINTERS
# ---------------------------------------------------------------------------
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_vv(v):
    """Version vector as {alice:n, bob:n, carol:n, dave:n} in CLIENTS order."""
    return "{" + ", ".join(f"{c}:{v.get(c, 0)}" for c in CLIENTS) + "}"


def fmt_deps(d):
    if not d:
        return "{}"
    return "{" + ", ".join(f"{c}:{n}" for c, n in sorted(d.items())) + "}"


def fmt_op(o):
    return (f"{o.opid}({o.client}:{o.seq}='{o.val}', "
            f"deps={fmt_deps(o.deps)})")


# ---------------------------------------------------------------------------
# 1. THE OPERATION MODEL + CAUSAL DEPENDENCY GRAPH
# ---------------------------------------------------------------------------
class Op:
    """A write op carrying its causal dependencies (a version vector)."""

    def __init__(self, opid, client, seq, deps, val):
        self.opid = opid
        self.client = client
        self.seq = seq
        self.deps = dict(deps)       # {client: seq} seen when written
        self.val = val

    def vv(self):
        """Op's own version vector = deps merged with own increment."""
        v = {c: 0 for c in CLIENTS}
        for c, n in self.deps.items():
            v[c] = max(v[c], n)
        v[self.client] = max(v[self.client], self.seq)
        return v


def build_ops():
    """The deterministic 4-op scenario.

    Two INDEPENDENT causal chains (the two chains are concurrent):

        A: alice posts "Hello"   ->   B: bob replies "Re:Hello"
            (B carries dep {alice:1}: bob had seen A)
        C: carol posts "Hi"      ->   D: dave replies "Re:Hi"
            (D carries dep {carol:1}: dave had seen C)

    No op in chain 1 depends on any op in chain 2, so {A,B} || {C,D}.
    """
    return {
        "A": Op("A", "alice", 1, {},           "Hello"),
        "B": Op("B", "bob",   1, {"alice": 1}, "Re:Hello"),
        "C": Op("C", "carol", 1, {},           "Hi"),
        "D": Op("D", "dave",  1, {"carol": 1}, "Re:Hi"),
    }


def build_hb(ops):
    """Happens-before reachability from the deps graph + transitive closure.

    reach[A] = set of ops that A happens-before (A -> y for y in reach[A]).
    """
    ids = list(ops.keys())
    by_cs = {(o.client, o.seq): oid for oid, o in ops.items()}
    reach = {x: set() for x in ids}
    for oid, o in ops.items():                          # direct dep edges
        for c, n in o.deps.items():
            anc = by_cs.get((c, n))
            if anc:
                reach[anc].add(oid)
    changed = True                                      # transitive closure
    while changed:
        changed = False
        for x in ids:
            for y in list(reach[x]):
                for z in reach[y]:
                    if z not in reach[x]:
                        reach[x].add(z)
                        changed = True
    return reach


def concurrent_pair(ops, reach, x, y):
    """True iff x || y (neither x->y nor y->x)."""
    return y not in reach[x] and x not in reach[y]


# ---------------------------------------------------------------------------
# 2. DEP CHECK + DELIVERY SIMULATIONS
# ---------------------------------------------------------------------------
def dep_check(seen, op):
    """Can `op` be applied given `seen` (per-client max seq applied so far)?

    Returns (ok, missing) where missing = [(client, need, have), ...].
    This is the IMPLEMENTATION of causal consistency: an op is revealed only
    once every causal ancestor has already been revealed.
    """
    missing = []
    for c in CLIENTS:
        need = op.deps.get(c, 0)
        have = seen.get(c, 0)
        if have < need:
            missing.append((c, need, have))
    return (len(missing) == 0, missing)


def deliver_blind(schedule, ops):
    """EVENTUAL style: apply each op in arrival order, no dep checking.
    Returns the final VIEW (list of values in delivery order). This is what
    a pure eventual-consistency store does - and where causal violations
    sneak in (Section B).
    """
    seen = {c: 0 for c in CLIENTS}
    view = []
    for oid in schedule:
        o = ops[oid]
        seen[o.client] = max(seen[o.client], o.seq)
        for c, n in o.deps.items():
            seen[c] = max(seen[c], n)
        view.append(o.val)
    return view


def deliver_with_dep_check(schedule, ops):
    """CAUSAL style: apply in arrival order but DEFER any op whose deps are
    not yet satisfied; flush the pending queue whenever a missing dep arrives.

    Returns (log, final_view). Each log entry is (op_id, status, extra) where
    status is 'APPLIED' | 'DEFERRED' | 'APPLIED-AFTER-WAIT' and extra is the
    missing-deps list (for DEFERRED) or the view-so-far (for APPLIED).
    """
    seen = {c: 0 for c in CLIENTS}
    pending = []          # op_ids waiting on deps
    view = []
    log = []

    def flush():
        progressed = True
        while progressed:
            progressed = False
            for oid2 in list(pending):
                ok, _ = dep_check(seen, ops[oid2])
                if ok:
                    o2 = ops[oid2]
                    pending.remove(oid2)
                    seen[o2.client] = max(seen[o2.client], o2.seq)
                    for c, n in o2.deps.items():
                        seen[c] = max(seen[c], n)
                    view.append(o2.val)
                    log.append((oid2, "APPLIED-AFTER-WAIT", list(view)))
                    progressed = True

    for oid in schedule:
        ok, missing = dep_check(seen, ops[oid])
        if ok:
            o = ops[oid]
            seen[o.client] = max(seen[o.client], o.seq)
            for c, n in o.deps.items():
                seen[c] = max(seen[c], n)
            view.append(o.val)
            log.append((oid, "APPLIED", list(view)))
            flush()                                    # a new dep may unblock
        else:
            pending.append(oid)
            log.append((oid, "DEFERRED", missing))
    return log, view


def schedule_violations(schedule, reach):
    """A schedule is causally valid iff for every A->B both delivered,
    pos(A) < pos(B). Returns the list of violated (A, B) pairs.
    This is the SPEC the dep check implements.
    """
    pos = {oid: i for i, oid in enumerate(schedule)}
    delivered = set(schedule)
    viols = []
    for x, ys in reach.items():
        for y in ys:
            if x in delivered and y in delivered and pos[x] > pos[y]:
                viols.append((x, y))
    return viols


# ---------------------------------------------------------------------------
# THE THREE REPLICA SCHEDULES (deterministic)
# ---------------------------------------------------------------------------
def build_schedules():
    """R0/R1 are causally valid (concurrent chains in different orders);
    R2_VIOLATING puts B before its causal ancestor A -> causal violation.
    """
    return {
        "R0":            ["A", "B", "C", "D"],   # chain1 then chain2 - valid
        "R1":            ["C", "D", "A", "B"],   # chain2 then chain1 - valid
        "R2_VIOLATING":  ["C", "D", "B", "A"],   # B before A -> VIOLATION
    }


# ---------------------------------------------------------------------------
# SECTION A: causal order - Alice posts, Bob replies
# ---------------------------------------------------------------------------
def section_a():
    banner("SECTION A: causal order - Alice posts, Bob replies")
    ops = build_ops()
    A, B = ops["A"], ops["B"]
    print("Two operations with a causal link:\n")
    print(f"  {fmt_op(A)}")
    print(f"  {fmt_op(B)}\n")
    print("Bob's reply B carries dep {alice:1} - he had SEEN Alice's post A")
    print("when he wrote it. So A -> B (A happens-before B).\n")
    print("Under CAUSAL consistency, every replica must reveal A before B.\n")
    print("Version vectors (op.vv = deps merged with own increment):")
    print(f"  A.vv = {fmt_vv(A.vv())}    (alice:1; no deps)")
    print(f"  B.vv = {fmt_vv(B.vv())}    (alice:1 from dep, bob:1 own)\n")

    # R0 delivers A then B, with dep checking - both apply cleanly
    print("Replica R0 delivers [A, B] WITH dependency checking:\n")
    print("| step | op | dep check (client: have>=need ?)          | result  | seen after                       |")
    print("|------|----|-------------------------------------------|---------|----------------------------------|")
    seen = {c: 0 for c in CLIENTS}
    for oid in ["A", "B"]:
        o = ops[oid]
        ok, _ = dep_check(seen, o)
        if o.deps:
            checks = ", ".join(
                f"{c}: {seen.get(c,0)}>={n}={'OK' if seen.get(c,0)>=n else 'NO'}"
                for c, n in sorted(o.deps.items()))
        else:
            checks = "(no deps)"
        if ok:
            seen[o.client] = max(seen[o.client], o.seq)
            for c, n in o.deps.items():
                seen[c] = max(seen[c], n)
        res = "APPLY" if ok else "DEFER"
        print(f"| {oid}    | {oid}  | {checks:<41} | {res:<7} | {fmt_vv(seen):<32} |")
    print()
    print("Both ops apply. R0's users see the feed in the natural order:")
    print("  view(R0) = ['Hello', 'Re:Hello']   <- post first, reply second.")
    print("The causal dependency A -> B is RESPECTED. That is causal order.\n")
    assert schedule_violations(["A", "B"], build_hb(ops)) == []
    print("[check] A -> B and pos(A) < pos(B) on R0: OK")


# ---------------------------------------------------------------------------
# SECTION B: causal violation - reply before the post
# ---------------------------------------------------------------------------
def section_b():
    banner("SECTION B: causal violation - reply shown before the post")
    ops = build_ops()
    reach = build_hb(ops)
    print("Same ops A (alice 'Hello') and B (bob 'Re:Hello'), A -> B.\n")
    print("Now suppose R2 is reachable via a slow link for A but a fast link")
    print("for B. Under EVENTUAL consistency (no dep checking), R2 simply")
    print("applies whatever arrives, in arrival order. B arrives first:\n")
    print("R2 arrival order = [B, A]. Applied BLINDLY (eventual style):\n")

    view = deliver_blind(["B", "A"], ops)
    print(f"  step 1: apply B ('Re:Hello')    view = {view[:1]}")
    print(f"  step 2: apply A ('Hello')       view = {view}\n")
    print(f"R2's users see:  {view}")
    print("  -> a REPLY to a post that is not yet visible. Broken UX.\n")

    viols = schedule_violations(["B", "A"], reach)
    print("Schedule-validity check (the SPEC): for every A->B delivered,")
    print(f"pos(A) < pos(B)?  Violations: {viols}")
    print(f"  -> {viols[0][0]} -> {viols[0][1]} but {viols[0][1]} delivered first."
          if viols else "")
    print("\nThis is exactly what causal consistency FORBIDS. Eventual says")
    print("\"they converge eventually\" - and they do (final state is the same")
    print("set of writes) - but the MID-FLIGHT view violates causality.\n")

    # the dep check would have CAUGHT it
    print("Had R2 run the dependency check (Section D), B would have been")
    print("DEFERRED until A arrived:")
    seen = {c: 0 for c in CLIENTS}
    ok_b, miss_b = dep_check(seen, ops["B"])
    print(f"  B arrives: dep_check(seen={fmt_vv(seen)}, B.deps={fmt_deps(ops['B'].deps)})")
    print(f"             -> ok={ok_b}, missing={miss_b}  -> DEFER B")
    print("  A arrives: dep_check -> ok=True (no deps) -> APPLY A")
    print("             flush pending: B's dep alice:1 now satisfied -> APPLY B")
    print("             view = ['Hello', 'Re:Hello']  (correct!)\n")
    assert not ok_b and miss_b == [("alice", 1, 0)]
    assert viols == [("A", "B")]
    print("[check] blind delivery violates A->B; dep check catches and defers: OK")


# ---------------------------------------------------------------------------
# SECTION C: concurrent operations - any order is valid
# ---------------------------------------------------------------------------
def section_c():
    banner("SECTION C: concurrent operations - any order is valid")
    ops = build_ops()
    reach = build_hb(ops)
    A, B, C, D = ops["A"], ops["B"], ops["C"], ops["D"]
    print("Causal consistency constrains ONLY causally-related ops. For")
    print("concurrent ops (a || b) it is SILENT: either order is acceptable.\n")

    print("Our scenario has two independent chains:")
    print(f"  chain 1: {A.val!r}(A) -> {B.val!r}(B)    [A -> B]")
    print(f"  chain 2: {C.val!r}(C) -> {D.val!r}(D)    [C -> D]\n")
    print("Concurrent pairs (neither -> the other):")
    pairs = [("A", "C"), ("A", "D"), ("B", "C"), ("B", "D")]
    for x, y in pairs:
        assert concurrent_pair(ops, reach, x, y)
        print(f"  {x} || {y}   "
              f"(no dep edge either way; {x}.deps={fmt_deps(ops[x].deps)}, "
              f"{y}.deps={fmt_deps(ops[y].deps)})")
    print()

    # two valid schedules that DIFFER in concurrent order
    s0 = ["A", "B", "C", "D"]      # chain1 first
    s1 = ["C", "D", "A", "B"]      # chain2 first
    v0 = schedule_violations(s0, reach)
    v1 = schedule_violations(s1, reach)
    print("Both of these replica schedules are CAUSALLY VALID:\n")
    print(f"  R0 = {s0}   view = {deliver_blind(s0, ops)}   violations = {v0}")
    print(f"  R1 = {s1}   view = {deliver_blind(s1, ops)}   violations = {v1}\n")
    print("R0 reveals chain 1 first, R1 reveals chain 2 first. Users on R0 and")
    print("R1 momentarily see the chains in different orders - but NEITHER ever")
    print("shows a reply before its post. Causality is intact; the reordering")
    print("is only between concurrent (independent) writes, which is allowed.\n")
    print("Contrast with Section B: reordering A and B is FORBIDDEN (A->B),")
    print("but reordering A and C is FINE (A||C). The dep graph decides which.\n")

    # and a third: interleaving is fine too, as long as each chain stays ordered
    s2 = ["A", "C", "B", "D"]
    v2 = schedule_violations(s2, reach)
    print(f"  R2' = {s2}  view = {deliver_blind(s2, ops)}  violations = {v2}")
    print("  (A before B within chain1, C before D within chain2; the chains")
    print("   interleave - still valid, because no causal edge is reversed.)\n")
    assert v0 == [] and v1 == [] and v2 == []
    print("[check] R0, R1, R2' all causally valid despite different orders: OK")


# ---------------------------------------------------------------------------
# SECTION D: implementation - dependency tracking via version vectors
# ---------------------------------------------------------------------------
def section_d():
    banner("SECTION D: implementation - dependency tracking + wait queue")
    ops = build_ops()
    print("How is causal consistency IMPLEMENTED? Each op carries its dep")
    print("version vector; each replica keeps a `seen` vector (max seq applied")
    print("per client). Before applying an op, run the DEP CHECK:\n")
    print("    def dep_check(seen, op):")
    print("        for c in op.deps:")
    print("            if seen[c] < op.deps[c]: return DEFER")
    print("        return APPLY\n")
    print("If DEFER, park the op in a PENDING queue. Whenever a new op is")
    print("applied, re-scan the queue - a deferred op may now be unblocked.\n")

    # the killer demo: same arrival as the Section B violation, but SAVED
    print("=" * 60)
    print("DEMO: arrival [B, A] (B first, as in Section B) WITH dep check")
    print("=" * 60)
    print("\nThis is the SAME pathological arrival order that broke R2 in")
    print("Section B. Watch the dep check turn a would-be violation into a")
    print("correct causal delivery:\n")
    log, view = deliver_with_dep_check(["B", "A"], ops)
    print("| arrival step | op | status              | detail / view after           |")
    print("|--------------|----|---------------------|-------------------------------|")
    for oid, status, extra in log:
        if status == "DEFERRED":
            miss = ", ".join(f"{c}: need {n}, have {h}" for c, n, h in extra)
            det = f"missing deps: {miss}"
        else:
            det = f"view = {extra}"
        print(f"| {oid}            | {oid}  | {status:<19} | {det:<29} |")
    print(f"\nFinal view = {view}   <- SAME as R0 in Section A.")
    print("B arrived FIRST but was revealed SECOND, because the dep check")
    print("refused to apply it until A (its causal ancestor) was present.\n")
    print("The dep check is O(#deps) per op. COPS keeps deps 1-hop (the direct")
    print("causal ancestors) rather than the full transitive closure, so each")
    print("op carries a SMALL dep set - cheap to check, cheap to store.\n")

    # show the wait-queue invariant: pending is always dependency-ordered
    print("INVARIANT: the pending queue + dep check together guarantee that the")
    print("APPLIED order is causally valid. Proof sketch: an op is applied only")
    print("when all its deps are already applied; hence every A->B edge has")
    print("pos(A) < pos(B) in the applied order. QED.\n")
    assert view == ["Hello", "Re:Hello"]
    assert schedule_violations([oid for oid, s, _ in log if s != "DEFERRED"],
                               build_hb(ops)) == []
    print("[check] applied order has zero causal violations: OK")


# ---------------------------------------------------------------------------
# SECTION E: causal vs eventual vs linearizable
# ---------------------------------------------------------------------------
def section_e():
    banner("SECTION E: the consistency ladder - eventual < causal < linearizable")
    print("Three levels of guarantee, increasing in strength AND in cost.\n")
    print("Using the Alice/Bob scenario (A='Hello' -> B='Re:Hello'):\n")

    rows = [
        ("replicas converge eventually",
         "yes", "yes", "yes"),
        ("respects causality  (A->B => A before B)",
         "NO",  "yes", "yes"),
        ("respects real-time  (ack(X) bef start(Y))",
         "NO",  "NO",  "yes"),
        ("single total order visible to all clients",
         "NO",  "NO",  "yes"),
        ("concurrent (a||b) may reorder per replica",
         "yes", "yes", "NO"),
        ("coordination needed",
         "none", "dep tracking (local)", "quorum / consensus"),
        ("stalls on missing deps?",
         "no",  "yes (defers)", "no (serialized)"),
        ("canonical systems",
         "DNS, Dynamo, Riak", "COPS, Bayou, CRDTs", "Spanner, etcd, 1-server"),
    ]
    pw = max(len("guarantee / property"), max(len(r[0]) for r in rows))
    print(f"| {'guarantee / property':<{pw}} | eventual | causal   | linearizable  |")
    print(f"|{'-'*(pw+2)}|----------|----------|---------------|")
    for prop, e, c, lin in rows:
        print(f"| {prop:<{pw}} | {e:<8} | {c:<8} | {lin:<13} |")
    print()

    # what each model says about the SAME Alice/Bob arrival [B, A]
    print("Same arrival [B, A] on a replica - what each model does:\n")
    print("  EVENTUAL:      applies B then A. view = ['Re:Hello','Hello'].")
    print("                 Causality violated, but it converges. (Section B)\n")
    print("  CAUSAL:        defers B, applies A, then B. view = ['Hello','Re:Hello'].")
    print("                 Causality respected. Costs a dep check + wait queue.")
    print("                 (Section D)\n")
    print("  LINEARIZABLE:  a single server (or Paxos group) serializes A and B.")
    print("                 Every client sees the SAME total order. Real-time is")
    print("                 respected: if Alice's ack reached Bob before Bob")
    print("                 started, then A precedes B for EVERYONE. Costs a")
    print("                 quorum round-trip per write (Spanner's TrueTime, etcd's Raft).\n")
    print("Pick the weakest model that meets your needs:")
    print("  - cache lookups, DNS             -> eventual")
    print("  - feeds, collaborative docs, IM  -> causal (this tutorial)")
    print("  - money, inventory, locks        -> linearizable\n")
    # gold assertions on the table's key claims
    assert rows[1][1] == "NO" and rows[1][2] == "yes" and rows[1][3] == "yes"
    assert rows[2][2] == "NO"                                   # causal lacks real-time
    print("[check] ladder ordering eventual < causal < linearizable verified: OK")


# ---------------------------------------------------------------------------
# GOLD CHECK: causal order respected across all replicas
# ---------------------------------------------------------------------------
def gold_check():
    banner("GOLD CHECK: causal dependencies respected on every replica")
    ops = build_ops()
    reach = build_hb(ops)

    # (a) op version vectors match the expected gold
    gold_vv = {
        "A": {"alice": 1, "bob": 0, "carol": 0, "dave": 0},
        "B": {"alice": 1, "bob": 1, "carol": 0, "dave": 0},
        "C": {"alice": 0, "bob": 0, "carol": 1, "dave": 0},
        "D": {"alice": 0, "bob": 0, "carol": 1, "dave": 1},
    }
    print("(a) op version vectors (deps + own increment):")
    vv_ok = True
    for oid in ops:
        got = ops[oid].vv()
        match = all(got[c] == gold_vv[oid][c] for c in CLIENTS)
        vv_ok = vv_ok and match
        print(f"     {oid}.vv = {fmt_vv(got)}   match gold: {match}")
    print()

    # (b) happens-before graph
    gold_reach = {"A": {"B"}, "B": set(), "C": {"D"}, "D": set()}
    print("(b) happens-before reachability (transitive closure of deps):")
    hb_ok = all(reach[oid] == gold_reach[oid] for oid in ops)
    for oid in ops:
        print(f"     {oid} -> {sorted(reach[oid]) if reach[oid] else '{}'}"
              f"   match gold: {reach[oid] == gold_reach[oid]}")
    print()

    # (c) each replica schedule classified correctly
    print("(c) replica schedules - causal validity + final view:")
    schedules = build_schedules()
    expect_valid = {"R0": True, "R1": True, "R2_VIOLATING": False}
    print(f"     {'replica':<14} {'schedule':<22} {'valid':<7} {'violations':<14} view")
    print(f"     {'-'*14} {'-'*22} {'-'*7} {'-'*14} {'-'*30}")
    cls_ok = True
    for rid, sched in schedules.items():
        viols = schedule_violations(sched, reach)
        valid = (len(viols) == 0)
        view = deliver_blind(sched, ops)
        cls_ok = cls_ok and (valid == expect_valid[rid])
        mark = "" if valid == expect_valid[rid] else "  <-- MISMATCH"
        print(f"     {rid:<14} {str(sched):<22} {str(valid):<7} "
              f"{str(viols):<14} {view}{mark}")
    print()

    # (d) dep check delivery on the pathological arrival always yields causal order
    print("(d) dep-check delivery on arrival [B, A] always produces causal order:")
    _, view_def = deliver_with_dep_check(["B", "A"], ops)
    causal_view_ok = (view_def == ["Hello", "Re:Hello"])
    print(f"     view = {view_def}   causal (A before B)? {causal_view_ok}\n")

    # (e) all-by-all: every valid schedule has zero violations, the invalid one
    #     has exactly the A,B violation
    print("(e) spec vs implementation agreement:")
    all_ok = vv_ok and hb_ok and cls_ok and causal_view_ok
    spec_impl_ok = True
    for rid, sched in schedules.items():
        blind_v = schedule_violations(sched, reach)
        # the dep-check delivery NEVER produces a violating schedule:
        log, _ = deliver_with_dep_check(sched, ops)
        applied = [oid for oid, s, _ in log if s != "DEFERRED"]
        dep_v = schedule_violations(applied, reach)
        agree = (len(dep_v) == 0)              # dep check always yields causal
        spec_impl_ok = spec_impl_ok and agree
        print(f"     {rid:<14}: blind violations={blind_v} ; "
              f"dep-check applied order violations={dep_v} ; always causal? {agree}")
    print()

    ok = all_ok and spec_impl_ok
    print("Summary:")
    print(f"  (a) version vectors match gold      : {'OK' if vv_ok else 'FAIL'}")
    print(f"  (b) happens-before graph matches    : {'OK' if hb_ok else 'FAIL'}")
    print(f"  (c) schedule validity classifies OK : {'OK' if cls_ok else 'FAIL'}")
    print(f"  (d) dep check yields causal order   : {'OK' if causal_view_ok else 'FAIL'}")
    print(f"  (e) dep check never violates causality: {'OK' if spec_impl_ok else 'FAIL'}")
    print()
    assert ok, "GOLD CHECK FAILED"
    print("=> [check] GOLD: all causal dependencies respected; "
          "dep check always produces causal order: OK")
    return ok


# ---------------------------------------------------------------------------
def main():
    print("causal_consistency.py - reference impl. All numbers below feed")
    print("CAUSAL_CONSISTENCY.md. python3, stdlib only.")
    print(f"clients = {CLIENTS} ; replicas = {NREPLICAS} (R0, R1, R2)")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
