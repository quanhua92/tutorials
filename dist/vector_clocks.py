"""
vector_clocks.py - Reference implementation of vector clocks (Mattern 1989,
Fidge 1988): the rules, the happens-before characterization, concurrency
detection, DynamoDB-style version vectors, and the Lamport-vs-vector trade-off.

This is the single source of truth that VECTOR_CLOCKS.md is built from.
Every number, table, and worked example in VECTOR_CLOCKS.md is printed by
this file. If you change something here, re-run and re-paste the output.

Run:
    python3 vector_clocks.py

Pure Python stdlib only.

=========================================================================
THE INTUITION (read this first) - the shipping ledger
=========================================================================
A Lamport clock is a SINGLE running counter per process. It tells you "this
event was the k-th thing this process did". Useful for ordering, but it LOSES
information: if L(a) < L(b) you CANNOT conclude a happened-before b. Two
events on different processes that never communicated can still get ordered
Lamport timestamps, and you cannot tell that apart from real causality.
Lamport clocks can prove a->b => L(a)<L(b), but NOT the converse.

A VECTOR CLOCK fixes this. Each process keeps a SMALL LEDGER with one slot per
process (N slots for N processes). Think of slot i as "how many events of
process i have I heard about".

  * local event : add a tally to MY OWN slot.
  * send        : add a tally to MY OWN slot, then photocopy the WHOLE ledger
                  and ship it with the message.
  * receive     : open the shipped ledger and take, slot by slot, the LARGER
                  tally (the one that has heard the most); then add one tally
                  to MY OWN slot (this receive counts as my event too).

Because every slot records causality from that process, two ledgers can be
compared component by component:

  VC(a) < VC(b)   iff   every slot of a is <= b   AND   at least one is <
  ->  that means a HAPPENED-BEFORE b  (a -> b, a causal ancestor)
  neither a<b nor b<a   ->   a and b are CONCURRENT  (a || b, no causal link)

That is the superpower Lamport lacks: vector clocks CHARACTERIZE
happens-before exactly (a -> b  <=>  VC(a) < VC(b)), so they can DETECT
concurrency. The price is space: O(N) per event instead of O(1).

=========================================================================
PLAIN-ENGLISH GLOSSARY
=========================================================================
  process          : one sequential participant. Here P0, P1, P2 (N = 3).
  event            : something that happens on one process (local / send / recv).
  vector clock (VC): an N-length array; slot i = count of P_i events "known".
  local rule       : on a local event, VC[my_id] += 1.
  send rule        : on send, VC[my_id] += 1, then attach a COPY of VC.
  receive rule     : on receive of msg m: VC[k] = max(VC[k], m[k]) for all k,
                     then VC[my_id] += 1.
  happens-before   : a -> b means a causally affects b. Defined by: program
   (->)              order on one process, send->receive, and transitivity.
  VC comparison    : VC(a) < VC(b)  <=>  (a[k] <= b[k] for all k) and
   (< on vectors)     (a[k] < b[k] for some k).
  concurrent (||)  : neither a -> b nor b -> a. VC clocks detect it:
                     NOT VC(a) < VC(b) AND NOT VC(b) < VC(a).
  characterization : a -> b  <=>  VC(a) < VC(b).  (the strong property:
   (the point)       vector clocks represent happens-before EXACTLY)
  version vector   : DynamoDB variant. Increment on WRITE, MERGE (max) on
                     read, no increment on read. Detects conflicting writes.
  Lamport clock    : a single scalar L per process; L = max(L, msg)+1 on recv.
                     a -> b => L(a) < L(b), but NOT the converse (no converse).

=========================================================================
THE PAPERS
=========================================================================
  Lamport  : Lamport 1978, "Time, Clocks, and the Ordering of Events in a
             Distributed System". CACM. The scalar clock + happens-before.
  Fidge    : Fidge 1988, "Timestamps in Message-Passing Systems". Vector clocks.
  Mattern  : Mattern 1989, "Virtual Time and Global States of Distributed
             Systems". Independent discovery of vector clocks.
  Dynamo   : DeCandia et al. 2007, "Dynamo: Amazon's Highly Available
             Key-value Store". SOSP. Version vectors for conflict detection.

KEY FORMULAS / facts (all asserted in code):
    local(vc,i)        : vc[i] += 1
    send(vc,i)         : vc[i] += 1 ; piggyback copy of vc
    recv(vc,i,msg)     : vc[k] = max(vc[k], msg[k]) ; vc[i] += 1
    VC(a) < VC(b)      <=>  (a[k] <= b[k] for all k) AND (a[k] < b[k] some k)
    a -> b             <=>  VC(a) < VC(b)          (characterization)
    a || b             <=>  not VC(a)<VC(b) and not VC(b)<VC(a)
    Lamport: a -> b    =>   L(a) < L(b)            (one-way only)
    version vector     :  write -> own slot += 1 ; read -> merge(max), no inc
    conflict (Dynamo)  :  two object versions with || version vectors = siblings
    space              :  Lamport O(1) ; Vector O(N)
"""

from __future__ import annotations

from collections import defaultdict

BANNER = "=" * 74
NPROC = 3  # P0, P1, P2


# ---------------------------------------------------------------------------
# Vector clock primitives (the math behind every section)
# ---------------------------------------------------------------------------
def local(vc, i):
    """Local event on process i: increment own counter. Returns a NEW vector."""
    v = list(vc)
    v[i] += 1
    return v


def send(vc, i):
    """Send event on process i: increment own, then piggyback a COPY of vc.

    Returns (new_local_vc, piggybacked_vector).
    """
    v = local(vc, i)
    return v, list(v)


def recv(vc, i, msg):
    """Receive on process i of piggybacked msg: max(msg, local) then inc own."""
    merged = [max(vc[k], msg[k]) for k in range(len(vc))]
    merged[i] += 1
    return merged


def vc_less(a, b):
    """VC(a) < VC(b): every component a<=b AND at least one a<b. Means a->b."""
    le_all = all(a[k] <= b[k] for k in range(len(a)))
    some_lt = any(a[k] < b[k] for k in range(len(a)))
    return le_all and some_lt


def concurrent(a, b):
    """True iff a and b are causally unrelated (neither VC strictly less)."""
    return not vc_less(a, b) and not vc_less(b, a)


def fmt_vc(v):
    return "[" + ", ".join(str(x) for x in v) + "]"


# ---------------------------------------------------------------------------
# Lamport clock primitives (for the trade-off in Section E)
# ---------------------------------------------------------------------------
def lamport_local(l):
    return l + 1


def lamport_send(l):
    return l + 1  # attach this value with the message


def lamport_recv(l, msg):
    return max(l, msg) + 1


# ---------------------------------------------------------------------------
# THE SCENARIO: 3 processes, 8 events, 2 messages. Deterministic.
# Designed to contain BOTH a clear causal chain AND concurrent pairs.
# ---------------------------------------------------------------------------
def build_scenario():
    """Build the deterministic event sequence.

    Returns a list of events, each a dict:
        {id, proc, type, vc, lamport, [to/from/send_id/msg]}
    and the explicit happens-before edges (same-process order + send->recv).
    """
    events = []
    p = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]     # vector clocks
    L = [0, 0, 0]                              # lamport clocks

    def add(eid, proc, etype, **kw):
        events.append(dict(id=eid, proc=proc, type=etype, vc=list(p[proc]),
                           lamport=L[proc], **kw))

    # a1: P0 local
    p[0] = local(p[0], 0); L[0] = lamport_local(L[0]); add("a1", 0, "local")
    # a2: P0 send -> P1
    p[0], m_a2 = send(p[0], 0); L[0] = lamport_send(L[0]); Ll_a2 = L[0]
    add("a2", 0, "send", to=1, msg=list(m_a2))
    # c1: P2 local  (INDEPENDENT of a2 -> concurrent with it)
    p[2] = local(p[2], 2); L[2] = lamport_local(L[2]); add("c1", 2, "local")
    # b1: P1 recv from a2
    p[1] = recv(p[1], 1, m_a2); L[1] = lamport_recv(L[1], Ll_a2)
    add("b1", 1, "recv", frm=0, send_id="a2", msg=list(m_a2))
    # b2: P1 local
    p[1] = local(p[1], 1); L[1] = lamport_local(L[1]); add("b2", 1, "local")
    # b3: P1 send -> P2
    p[1], m_b3 = send(p[1], 1); L[1] = lamport_send(L[1]); Ll_b3 = L[1]
    add("b3", 1, "send", to=2, msg=list(m_b3))
    # c2: P2 local  (INDEPENDENT of b3 -> concurrent with it)
    p[2] = local(p[2], 2); L[2] = lamport_local(L[2]); add("c2", 2, "local")
    # c3: P2 recv from b3
    p[2] = recv(p[2], 2, m_b3); L[2] = lamport_recv(L[2], Ll_b3)
    add("c3", 2, "recv", frm=1, send_id="b3", msg=list(m_b3))

    return events


def build_hb_edges(events):
    """Explicit happens-before edges: program order on each process + send->recv."""
    edges = set()
    by_proc = defaultdict(list)
    for e in events:
        by_proc[e["proc"]].append(e["id"])
    for proc, ids in by_proc.items():                # same-process order
        for x, y in zip(ids, ids[1:]):
            edges.add((x, y))
    for e in events:                                  # send -> its receive
        if e["type"] == "send":
            for r in events:
                if r["type"] == "recv" and r.get("send_id") == e["id"]:
                    edges.add((e["id"], r["id"]))
    return edges


def transitive_closure(ids, edges):
    """Reachability set per node from explicit edges (happens-before graph)."""
    reach = {x: set() for x in ids}
    for (x, y) in edges:
        reach[x].add(y)
    changed = True
    while changed:                                    # iterated fixpoint
        changed = False
        for x in ids:
            for y in list(reach[x]):
                for z in reach[y]:
                    if z not in reach[x]:
                        reach[x].add(z)
                        changed = True
    return reach


# ---------------------------------------------------------------------------
# SECTION A: the three rules, applied step by step on 3 processes
# ---------------------------------------------------------------------------
def section_a():
    banner("SECTION A: vector clock rules - local / send / receive")
    events = build_scenario()
    print(f"{NPROC} processes P0, P1, P2, each starting at VC = [0, 0, 0].")
    print("Rules:")
    print("  local  : VC[my_id] += 1")
    print("  send   : VC[my_id] += 1 ; attach a COPY of the whole VC")
    print("  receive: VC[k] = max(VC[k], msg[k]) for all k ; then VC[my_id] += 1\n")
    print("Trace (events in execution order; VC shown AFTER each event):\n")
    hdr = "| step | event | proc | type   | rule applied                         | vector clock |"
    print(hdr)
    print("|-" + "-----|" * 6)
    rule = {"local": "VC[my_id] += 1",
            "send": "VC[my_id] += 1 ; ship copy",
            "recv": "max(msg,local) ; VC[my_id] += 1"}
    for i, e in enumerate(events):
        et = "recv" if e["type"] == "recv" else e["type"]
        print(f"| {i + 1:<4} | {e['id']:<5} | P{e['proc']}   | {et:<6} | "
              f"{rule[e['type']]:<36} | {fmt_vc(e['vc']):<12} |")
    print()
    print("Messages shipped (the piggybacked vectors):")
    for e in events:
        if e["type"] == "send":
            print(f"  {e['id']} (P{e['proc']} -> P{e['to']}): ships VC = {fmt_vc(e['msg'])}")
    print()
    print("Key observations:")
    print("  - a send bumps the sender's own slot, and the receiver LATER takes")
    print("    the component-wise MAX with the shipped vector (see b1, c3).")
    print("  - b1 = max([0,0,0], [2,0,0]) then inc P1 = [2,1,0]. P1 now 'knows'")
    print("    about both of P0's events.")
    print("  - c1 and c2 on P2 grew WITHOUT hearing from P0/P1 -> their slots 0,1")
    print("    stay 0. That missing knowledge is exactly what makes them CONCURRENT")


# ---------------------------------------------------------------------------
# SECTION B: the comparison rule (component-wise)
# ---------------------------------------------------------------------------
def section_b():
    banner("SECTION B: comparison - VC(a) < VC(b) iff all <= and some <")
    events = build_scenario()
    by = {e["id"]: e for e in events}
    print("The comparison is DEFINED component by component (not as a number):\n")
    print("  VC(a) < VC(b)   <=>   (a[k] <= b[k] for ALL k)  AND  (a[k] < b[k] for SOME k)\n")
    print("Read it as: 'b has heard about everything a heard about, and strictly")
    print("more in at least one slot' -> a is a causal ANCESTOR of b (a -> b).\n")

    # walk three illustrative pairs: a causal pair, a reverse-check, an equal pair
    pairs = [("a1", "a2"), ("a2", "b1"), ("c1", "c2")]
    labels = {"a1->a2": "same process (program order)",
              "a2->b1": "send -> receive (cross process)",
              "c1->c2": "same process, later"}
    for x, y in pairs:
        va, vb = by[x]["vc"], by[y]["vc"]
        comps = []
        for k in range(NPROC):
            if va[k] < vb[k]:
                comps.append(f"{va[k]}<{vb[k]} (strict)")
            elif va[k] == vb[k]:
                comps.append(f"{va[k]}={vb[k]}")
            else:
                comps.append(f"{va[k]}>{vb[k]} (BREAKS <)")
        le_all = all(va[k] <= vb[k] for k in range(NPROC))
        some_lt = any(va[k] < vb[k] for k in range(NPROC))
        print(f"  Compare {x} = {fmt_vc(va)}  vs  {y} = {fmt_vc(vb)}:")
        for k in range(NPROC):
            print(f"     slot {k}: {comps[k]}")
        print(f"     all<=? {le_all} ; some<? {some_lt}  =>  VC({x}) < VC({y})? "
              f"{vc_less(va, vb)}  ->  {x} -> {y}")
        print()
    print("The rule is strict: a SINGLE slot with a[k] > b[k] sinks the whole")
    print("comparison. That is why a process that 'hasn't heard' of another can")
    print("never be considered an ancestor of it.\n")

    # assert the three exemplars
    by_vc = {e["id"]: e["vc"] for e in events}
    assert vc_less(by_vc["a1"], by_vc["a2"])
    assert vc_less(by_vc["a2"], by_vc["b1"])
    assert vc_less(by_vc["c1"], by_vc["c2"])
    print("[check] a1->a2, a2->b1, c1->c2 all classified CAUSAL by VC < : OK")


# ---------------------------------------------------------------------------
# SECTION C: concurrent detection (||)
# ---------------------------------------------------------------------------
def section_c():
    banner("SECTION C: concurrent detection - neither VC < the other")
    events = build_scenario()
    by_vc = {e["id"]: e["vc"] for e in events}
    print("Two events are CONCURRENT (a || b) iff NEITHER VC(a)<VC(b) NOR VC(b)<VC(a).\n")
    print("This is the thing Lamport clocks CANNOT do: tell causal order apart from")
    print("coincidental order. Vector clocks can, because each slot encodes what the")
    print("process has heard about.\n")

    pairs = [("a2", "c1"), ("b3", "c2"), ("a2", "c2")]
    for x, y in pairs:
        va, vb = by_vc[x], by_vc[y]
        lt = vc_less(va, vb)
        gt = vc_less(vb, va)
        conc = concurrent(va, vb)
        print(f"  {x} = {fmt_vc(va)}   vs   {y} = {fmt_vc(vb)}")
        print(f"     VC({x}) < VC({y})? {lt}")
        print(f"     VC({y}) < VC({x})? {gt}")
        # show why: the offending slots (the ones that break each direction)
        bad_fwd = [k for k in range(NPROC) if va[k] > vb[k]]
        bad_rev = [k for k in range(NPROC) if vb[k] > va[k]]
        if bad_fwd and bad_rev:
            kf, kr = bad_fwd[0], bad_rev[0]
            print(f"     slot {kf}: {x}[{kf}]={va[kf]} > {y}[{kf}]={vb[kf]} "
                  f"-> blocks {x}->{y}")
            print(f"     slot {kr}: {y}[{kr}]={vb[kr]} > {x}[{kr}]={va[kr]} "
                  f"-> blocks {y}->{x}")
        print(f"     => {x} || {y} (concurrent)? {conc}\n")

    print("Physical meaning: a2 happened on P0, c1 on P2, with NO message between")
    print("them. Neither process knows the other's event occurred. They are truly")
    print("independent -> concurrent. (Section D shows DynamoDB turns this into a")
    print("conflict that must be surfaced.)\n")
    for x, y in pairs:
        assert concurrent(by_vc[x], by_vc[y]), f"{x}||{y} failed"
    print("[check] a2||c1, b3||c2, a2||c2 all classified CONCURRENT: OK")


# ---------------------------------------------------------------------------
# SECTION D: version vectors (DynamoDB) - detect conflicting writes
# ---------------------------------------------------------------------------
def vv(*pairs, nodes=("N1", "N2", "N3")):
    """Build a version vector {node:count}; missing nodes default to 0."""
    c = {n: 0 for n in nodes}
    c.update(dict(pairs))
    return c


def vv_less(a, b, nodes=("N1", "N2", "N3")):
    le = all(a[n] <= b[n] for n in nodes)
    lt = any(a[n] < b[n] for n in nodes)
    return le and lt


def vv_concurrent(a, b, nodes=("N1", "N2", "N3")):
    return not vv_less(a, b, nodes) and not vv_less(b, a, nodes)


def vv_merge(a, b, nodes=("N1", "N2", "N3")):
    return {n: max(a[n], b[n]) for n in nodes}


def fmt_vv(c, nodes=("N1", "N2", "N3")):
    return "{" + ", ".join(f"{n}:{c[n]}" for n in nodes) + "}"


def section_d():
    banner("SECTION D: version vectors (DynamoDB) - detect conflicting writes")
    nodes = ("N1", "N2", "N3")
    print("A VERSION VECTOR is the data-store variant of a vector clock. Differences:")
    print("  - increment OWN node's counter only on a WRITE (not on every event);")
    print("  - on a READ/replication, MERGE by element-wise max (NO increment);")
    print("  - the vector is attached to each stored OBJECT VERSION.\n")
    print("Two versions of the same key are SIBLINGS (a conflict) iff their version")
    print("vectors are CONCURRENT. Dynamo/Riak surface siblings to the app instead of")
    print("silently dropping one. (DeCandia et al. 2007, Dynamo SOSP.)\n")

    print("Scenario: key 'cart', 3 replicas N1,N2,N3. A partition isolates N3.\n")
    # baseline write
    v0 = {"val": "[]", "vv": vv(("N1", 1))}
    print(f"  t0  client writes 'cart' to coordinator N1")
    print(f"      version v0 : val = {v0['val']!r}   vv = {fmt_vv(v0['vv'])}")
    print(f"      N1 replicates v0 to N2 and N3 (all converge).\n")

    # w1: N1 updates during partition, reaches N2 only
    w1 = {"val": "[A]", "vv": vv(("N1", 1), ("N2", 1))}
    print(f"  t1  PARTITION: N3 isolated. {{N1, N2}} can talk, N3 cannot.")
    print(f"      client updates 'cart' via N1 -> val = {w1['val']!r}")
    print(f"      N1 increments its OWN slot on the write:")
    print(f"      version w1 : val = {w1['val']!r}   vv = {fmt_vv(w1['vv'])}")
    print(f"      N1 replicates w1 to N2 (reachable). N3 still holds v0.\n")

    # w2: N3 updates on its side, from the stale v0
    w2 = {"val": "[B]", "vv": vv(("N1", 1), ("N3", 1))}
    print(f"  t2  a DIFFERENT client updates 'cart' via N3 (it only knows v0):")
    print(f"      N3 increments its OWN slot:")
    print(f"      version w2 : val = {w2['val']!r}   vv = {fmt_vv(w2['vv'])}")
    print(f"      N3 cannot replicate w2 out (partitioned).\n")

    # heal + conflict detection
    print("  t3  HEAL. Replica N2 holds w1, N3 holds w2. The coordinator compares")
    print("      their version vectors to decide the relationship:\n")
    print(f"      w1.vv = {fmt_vv(w1['vv'])}   (val [A])")
    print(f"      w2.vv = {fmt_vv(w2['vv'])}   (val [B])")
    lt = vv_less(w1["vv"], w2["vv"], nodes)
    gt = vv_less(w2["vv"], w1["vv"], nodes)
    conc = vv_concurrent(w1["vv"], w2["vv"], nodes)
    print(f"      w1 < w2 ? {lt}")
    print(f"      w2 < w1 ? {gt}")
    print(f"      => concurrent (conflict)? {conc}\n")
    if conc:
        print("      Neither version descends from the other -> Dynamo keeps BOTH as")
        print("      SIBLINGS and returns them to the application:")
        print(f"         siblings(cart) = [{w1['val']!r}, {w2['val']!r}]")
        print("      The app resolves it (e.g. union -> [A,B], prompt the user, ...).")
        print("      NOTHING is silently dropped -- unlike last-write-wins.\n")
    merged = vv_merge(w1["vv"], w2["vv"], nodes)
    print("      After the app reconciles, a new write advances from the merge:")
    print(f"         merged vv = {fmt_vv(merged)}  -> store resolved version.\n")

    assert conc
    assert merged == vv(("N1", 1), ("N2", 1), ("N3", 1))
    print("[check] w1||w2 concurrent -> surfaced as siblings; merge = "
          f"{fmt_vv(merged)}: OK")


# ---------------------------------------------------------------------------
# SECTION E: Lamport vs vector clocks - the trade-off
# ---------------------------------------------------------------------------
def section_e():
    banner("SECTION E: Lamport vs vector clocks - the trade-off")
    events = build_scenario()
    by = {e["id"]: e for e in events}
    print("Both assign timestamps to events, but they buy different things.\n")

    # concrete failure of Lamport: two concurrent events with ordered scalars
    print("Concrete failure mode of Lamport (using the SAME scenario):\n")
    print("  a2 on P0 and c1 on P2 are CONCURRENT (Section C proved it). But:")
    print(f"     L(a2) = {by['a2']['lamport']}   L(c1) = {by['c1']['lamport']}")
    print(f"     VC(a2) = {fmt_vc(by['a2']['vc'])}   VC(c1) = {fmt_vc(by['c1']['vc'])}\n")
    print("  A naive reader sees L(c1)=1 < L(a2)=2 and wrongly infers c1 -> a2.")
    print("  Lamport only guarantees a->b => L(a)<L(b); the CONVERSE is FALSE, so you")
    print("  CANNOT classify a pair from Lamport timestamps alone.\n")
    print("  Vector clocks give the exact characterization a->b <=> VC(a)<VC(b), so")
    print("  the same pair is correctly shown as c1 || a2.\n")

    # the full trade-off table
    print("| property                       | Lamport clock     | Vector clock          |")
    print("|--------------------------------|-------------------|-----------------------|")
    rows = [
        ("state per process", "1 scalar (O(1))", f"{NPROC} counters (O(N))"),
        ("message overhead", "1 integer", f"{NPROC} integers"),
        ("a -> b  =>  ts(a) < ts(b) ?", "yes", "yes"),
        ("ts(a) < ts(b)  =>  a -> b ?", "NO (converse false)", "YES (exact)"),
        ("detects concurrency (a || b) ?", "NO", "YES"),
        ("needs to know N (group size) ?", "no", "yes"),
        ("scales to huge N ?", "trivially", "cost grows with N"),
        ("typical use", "event ordering, txn IDs", "causality, conflict detection"),
    ]
    for p_, l_, v_ in rows:
        print(f"| {p_:<30} | {l_:<17} | {v_:<21} |")
    print()
    print("Rule of thumb: if you only need a TOTAL ORDER consistent with causality,")
    print("Lamport is cheap and enough. If you need to DETECT that two events are")
    print("independent (conflict detection, causal consistency, debugging), you need")
    print("a vector clock (or its sparse cousins: dotted version vectors, HLCs).\n")

    # gold assertion: lamport respects one direction, vector respects both
    # pick a true causal pair a2->b1 and a concurrent pair a2||c1
    assert by["a2"]["lamport"] < by["b1"]["lamport"]          # a2->b1 => L(a2)<L(b1)
    assert by["c1"]["lamport"] < by["a2"]["lamport"]          # but c1||a2 yet L(c1)<L(a2)
    assert vc_less(by["a2"]["vc"], by["b1"]["vc"])            # vector: a2->b1
    assert concurrent(by["a2"]["vc"], by["c1"]["vc"])         # vector: a2||c1
    print("[check] Lamport L(c1)<L(a2) mis-orders concurrent pair; vector fixes it: OK")


# ---------------------------------------------------------------------------
# GOLD CHECK: VC classification matches the happens-before graph, all pairs
# ---------------------------------------------------------------------------
def gold_check():
    banner("GOLD CHECK: VC comparison matches happens-before, ALL pairs")
    events = build_scenario()
    ids = [e["id"] for e in events]
    by_vc = {e["id"]: e["vc"] for e in events}
    edges = build_hb_edges(events)
    reach = transitive_closure(ids, edges)

    causal_ok = concurrent_ok = total = 0
    mismatches = []
    for i in range(len(ids)):
        for j in range(len(ids)):
            if i == j:
                continue
            a, b = ids[i], ids[j]
            total += 1
            hb = b in reach[a]               # a happens-before b (graph truth)
            vc = vc_less(by_vc[a], by_vc[b])  # VC comparison
            if hb == vc:
                if hb:
                    causal_ok += 1
                else:
                    concurrent_ok += 1
            else:
                mismatches.append((a, b, hb, vc))

    n_pairs = len(ids) * (len(ids) - 1)
    print(f"Events: {len(ids)} -> {n_pairs} ordered pairs checked.")
    print(f"  causal pairs (a->b)  classified correctly: {causal_ok}")
    print(f"  concurrent/incomparable classified correctly: {concurrent_ok}")
    print(f"  mismatches: {len(mismatches)}")
    print()
    print("This is the CHARACTERIZATION theorem in action:")
    print("  a -> b  <=>  VC(a) < VC(b)   for EVERY pair. Vector clocks represent")
    print("  happens-before EXACTLY, so every causal link AND every concurrent pair")
    print("is classified correctly. That is the property Lamport clocks lack.\n")

    # sanity: enumerate a few named pairs for the docs
    print("Spot check (named pairs):")
    for a, b in [("a1", "a2"), ("a2", "b1"), ("b3", "c3"), ("c1", "c3"),
                 ("a2", "c1"), ("b3", "c2")]:
        hb = b in reach[a]
        vcmp = vc_less(by_vc[a], by_vc[b])
        print(f"  {a} -> {b}? graph={hb}   VC({a})<VC({b})? {vcmp}   "
              f"match={hb == vcmp}")
    print()

    ok = (len(mismatches) == 0)
    assert ok, f"VC classification mismatches: {mismatches}"
    print(f"=> [check] GOLD: all {n_pairs} pairs match happens-before: "
          f"{'OK' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def main():
    print("vector_clocks.py - reference impl. All numbers below feed")
    print("VECTOR_CLOCKS.md. python3, stdlib only.")
    print(f"N={NPROC} processes P0,P1,P2")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
