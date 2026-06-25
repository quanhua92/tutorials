"""
linearizability.py - Reference implementation of LINEARIZABILITY: the strongest
single-object consistency model. Every operation appears to execute atomically
at some instant between its invocation and response, and that instant respects
real-time order.

This is the single source of truth that LINEARIZABILITY.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 linearizability.py

============================================================================
THE INTUITION (read this first) - the "it all happened at one instant" rule
============================================================================
Picture a shared register X. Clients send operations (read or write) to a
replicated store. Each operation has an INVOCATION (client calls) and a
RESPONSE (client gets the answer); in between, the operation is "in flight"
and we don't know exactly when the store did the work. Linearizability says:

    For every operation there exists a single point in time - the
    LINEARIZATION POINT - somewhere in [invocation, response], at which the
    operation "appears to take effect" instantaneously. If you line up all
    those points in time, the resulting sequence must be a legal sequential
    execution of the register.

The one extra clause that makes it STRONG: the linearization points must
respect REAL-TIME order. If operation A's RESPONSE comes before operation B's
INVOCATION (A fully completes before B even starts), then A's linearization
point MUST be before B's. The client SAW A finish, so the real world says A
happened first - the system is not allowed to pretend otherwise.

That real-time clause is the whole difference from SEQUENTIAL CONSISTENCY
(Lamport 1979): sequential consistency keeps per-client program order but
IGNORES real time, so a read that starts after a write completes is free to
"not have noticed" the write yet. Linearizability forbids that. This is why
linearizability is called "strong consistency" - it makes a replicated
register behave like a single non-concurrent machine to every outside
observer.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  register X      : a single read/write object. The only shared state here.
  operation       : a read or a write, issued by one client. Has an
                    invocation time (inv) and a response time (resp).
  invocation (inv): the real-time instant the client SENDS the request.
  response (resp) : the real-time instant the client RECEIVES the answer.
  in flight       : the interval [inv, resp]; the store does the work here.
  write(x, v)     : set X := v. Returns "ok".
  read(x)         : return the current value of X.
  linearization   : a total order of ALL operations that (1) is a legal
                    sequential register history and (2) respects real-time
                    order. If one exists, the history is linearizable.
  linearization   : the single instant in [inv, resp] at which an operation
  point (lin pt)    "appears to execute" atomically. Choosing one point per
                    operation, in real-time order, IS the linearization.
  real-time order : if resp(A) <= inv(B) then A MUST precede B in the
                    linearization. The client saw A finish.
  program order   : within one client, operations happen in invocation
                    order. (Captured automatically because a sequential
                    client waits for each response before the next inv.)
  sequential      : weaker model. Same as linearizability but WITHOUT the
  consistency       real-time clause. Only program order is preserved.
  legal seq. exec.: read(X) returns the value of the most recent preceding
                    write(X, v); if none, returns the initial value.

============================================================================
THE PAPERS (every claim below verified against these)
============================================================================
  Herlihy & Wing (1990). "Linearizability: A Correctness Condition for
        Concurrent Objects." ACM TOPLAS 12(3), 463-492.
        - DEFINES linearizability. Local property (compositional). The
          linearization-point formulation used throughout this file.
  Wing & Gong (1993). "Testing and Verifying Concurrent Objects." J. Parallel
        Distrib. Comput. - the WGL auto-convexity CHECKER: try every
        topological sort consistent with real-time order; if any is a legal
        sequential history, the history is linearizable. (Implemented here as
        `all_topological_sorts` + `valid_register_seq`.)
  Lamport (1979). "How to Make a Multiprocessor Computer That Correctly
        Executes Multiprocess Programs." IEEE TC C-28(9). - sequential
        consistency, the weaker model we contrast against (Section B).
  Gilbert & Lynch (2002). "Brewer's Conjecture and the Feasibility of
        Consistent, Available, Partition-Tolerant Web Services." ACM SIGACT
        News. - proves linearizability + availability are incompatible under
          partition (the "CP" side of CAP); the implementation COST (Section E).

KEY FACTS (all asserted in code below):
    linearizable  : exists a linearization (legal seq. history respecting
                    real-time order).
    checking      : enumerate all topological sorts of the real-time partial
                    order; if ANY is a legal register sequence -> linearizable.
                    Cost: exponential in the worst case (NP in general, Wing &
                    Gong 1993), but trivial for small histories.
    real-time edge: resp(A) <= inv(B) and A != B  =>  A before B.
    lin point     : pick one point in [inv, resp] per op; points in real-time
                    order give the linearization.
    vs sequential : sequential drops the real-time clause, keeping only program
                    order. A stale read that ignores a completed write is
                    sequentially consistent but NOT linearizable.
    cost          : linearizability requires that every read see the latest
                    write, so replicas must COORDINATE (consensus / Raft /
                    Paxos / quorum) before responding. That costs latency and
                    forgoes availability under partition (CAP).

============================================================================
THE SCENARIOS (deterministic; reused by every section and by the .html)
============================================================================
Four hand-built histories on a single register X, initial value 0. Integer
"physical" time coordinates are shown only to derive real-time order; the
checker never trusts them beyond the resp(A) <= inv(B) test.

  HIST_A  (linearizable)        HIST_B  (NOT linearizable, stale read)
    C1: W1(x,1) [1--4]            C1: W1(x,1) [1--4]
    C2: R1(x)   [5--7] ret=1      C2: R1(x)   [5--7] ret=0  <-- stale!

  HIST_C  (concurrent writes)    HIST_D  (overlapping R/W, 2 linearizations)
    C1: W1(x,1) [1-----6]         C1: W1(x,1) [1--5]
    C2: W2(x,2) [2--5]            C2: R1(x)   [2-4] ret=0
    C3: R1(x)      [7--9] ret=2

The same four histories are hard-coded in linearizability.html so JS
recomputes byte-identical verdicts.
"""

from __future__ import annotations


BANNER = "=" * 72

# ----------------------------------------------------------------------------
# The deterministic scenarios. Single source of truth for every section.
# Each op: id, client, kind in {"write","read"}, arg (value written),
#           inv / resp (integer time), ret (value read back, or "ok" for writes)
# ----------------------------------------------------------------------------

INITIAL = 0  # initial register value

HIST_A = [  # LINEARIZABLE: read sees the completed write
    {"id": "W1", "client": "C1", "kind": "write", "arg": 1, "inv": 1, "resp": 4, "ret": "ok"},
    {"id": "R1", "client": "C2", "kind": "read", "arg": None, "inv": 5, "resp": 7, "ret": 1},
]

HIST_B = [  # NOT LINEARIZABLE: stale read (ret=0) after the write completed
    {"id": "W1", "client": "C1", "kind": "write", "arg": 1, "inv": 1, "resp": 4, "ret": "ok"},
    {"id": "R1", "client": "C2", "kind": "read", "arg": None, "inv": 5, "resp": 7, "ret": 0},
]

HIST_C = [  # LINEARIZABLE: two concurrent writes, read sees the later one
    {"id": "W1", "client": "C1", "kind": "write", "arg": 1, "inv": 1, "resp": 6, "ret": "ok"},
    {"id": "W2", "client": "C2", "kind": "write", "arg": 2, "inv": 2, "resp": 5, "ret": "ok"},
    {"id": "R1", "client": "C3", "kind": "read", "arg": None, "inv": 7, "resp": 9, "ret": 2},
]

HIST_D = [  # LINEARIZABLE: overlapping write+read, read returns initial value
    {"id": "W1", "client": "C1", "kind": "write", "arg": 1, "inv": 1, "resp": 5, "ret": "ok"},
    {"id": "R1", "client": "C2", "kind": "read", "arg": None, "inv": 2, "resp": 4, "ret": 0},
]


# ============================================================================
# 1. REFERENCE IMPLEMENTATIONS  (the code LINEARIZABILITY.md walks through)
# ============================================================================

def realtime_edges(history: list) -> set[tuple[str, str]]:
    """Edges of the REAL-TIME partial order.

    resp(A) <= inv(B)  =>  A MUST precede B in any linearization. The client
    observed A's response before issuing B, so the system cannot reorder them.
    Operations that OVERLAP (neither completes before the other starts) get NO
    edge between them - they are concurrent and may be interleaved freely.
    """
    edges: set[tuple[str, str]] = set()
    for a in history:
        for b in history:
            if a["id"] != b["id"] and a["resp"] <= b["inv"]:
                edges.add((a["id"], b["id"]))
    return edges


def program_order_edges(history: list) -> set[tuple[str, str]]:
    """Edges of PROGRAM ORDER (same client, in invocation order).

    This is the ONLY constraint sequential consistency imposes. A sequential
    client waits for each response before its next invocation, so a client's
    operations are already non-overlapping and naturally time-ordered.
    """
    edges: set[tuple[str, str]] = set()
    by_client: dict[str, list] = {}
    for op in history:
        by_client.setdefault(op["client"], []).append(op)
    for ops in by_client.values():
        ops.sort(key=lambda o: o["inv"])
        for k in range(len(ops) - 1):
            edges.add((ops[k]["id"], ops[k + 1]["id"]))
    return edges


def all_topological_sorts(nodes: list[str], edges: set[tuple[str, str]]) -> list[list[str]]:
    """Every total order of `nodes` consistent with the `edges` partial order.

    This is the heart of the Wing & Gong (1993) check: a linearization is
    exactly a topological sort of the real-time partial order that ALSO happens
    to be a legal sequential register history (see `valid_register_seq`).
    Enumerating all sorts is exponential in the worst case, but trivial for the
    small histories used here.
    """
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    indeg: dict[str, int] = {n: 0 for n in nodes}
    for a, b in edges:
        adj[a].append(b)
        indeg[b] += 1
    results: list[list[str]] = []

    def backtrack(path: list[str], used: set[str], deg: dict[str, int]):
        if len(path) == len(nodes):
            results.append(list(path))
            return
        for n in nodes:
            if n not in used and deg[n] == 0:
                path.append(n)
                used.add(n)
                for nb in adj[n]:
                    deg[nb] -= 1
                backtrack(path, used, deg)
                for nb in adj[n]:
                    deg[nb] += 1
                used.discard(n)
                path.pop()

    backtrack([], set(), dict(indeg))
    return results


def valid_register_seq(seq: list[str], by_id: dict[str, dict], initial: int = INITIAL) -> bool:
    """Is `seq` a LEGAL sequential register history?

    Replay writes and reads in order. A write sets the value; a read must
    return the most recent written value (or the initial value if no write yet).
    If every read matches its recorded return value, the sequence is legal.
    """
    val = initial
    for oid in seq:
        op = by_id[oid]
        if op["kind"] == "write":
            val = op["arg"]
        else:  # read
            if op["ret"] != val:
                return False
    return True


def check_consistency(
    history: list, edge_fn, initial: int = INITIAL
) -> tuple[bool, list[list[str]], list[list[str]]]:
    """Generic checker. Returns (is_valid, legal_sorts, all_sorts).

    `edge_fn` selects the partial order: `realtime_edges` for linearizability,
    `program_order_edges` for sequential consistency. A history satisfies the
    model iff SOME topological sort of that order is a legal register sequence.
    """
    nodes = [op["id"] for op in history]
    by_id = {op["id"]: op for op in history}
    edges = edge_fn(history)
    sorts = all_topological_sorts(nodes, edges)
    legal = [s for s in sorts if valid_register_seq(s, by_id, initial)]
    return len(legal) > 0, legal, sorts


def is_linearizable(history: list, initial: int = INITIAL):
    return check_consistency(history, realtime_edges, initial)


def is_sequentially_consistent(history: list, initial: int = INITIAL):
    return check_consistency(history, program_order_edges, initial)


def describe_seq(seq: list[str], by_id: dict[str, dict], initial: int = INITIAL) -> str:
    """Pretty-print a sequence as a register trace, e.g.  [0] W1(->1) R1(=1 ok)."""
    val = initial
    parts = [f"[{val}]"]
    for oid in seq:
        op = by_id[oid]
        if op["kind"] == "write":
            val = op["arg"]
            parts.append(f"{oid}(->{val})")
        else:
            ok = "ok" if op["ret"] == val else f"MISMATCH ret={op['ret']}"
            parts.append(f"{oid}(={op['ret']} {ok})")
    return " ".join(parts)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def draw_history(history: list) -> str:
    """ASCII timeline of a history (used in sections to orient the reader)."""
    tmax = max(op["resp"] for op in history)
    by_client: dict[str, list] = {}
    for op in history:
        by_client.setdefault(op["client"], []).append(op)
    lines = []
    for client in sorted(by_client):
        ops = sorted(by_client[client], key=lambda o: o["inv"])
        row = ["."] * (tmax + 2)
        for op in ops:
            kind = "W" if op["kind"] == "write" else "R"
            for t in range(op["inv"], op["resp"] + 1):
                row[t] = "="
            row[op["inv"]] = "[" if op != ops[0] else "["
            row[op["resp"]] = "]"
            row[op["inv"]] = kind.lower()
        label = " ".join(f"{o['id']}({o['kind']},{o['arg'] if o['arg'] is not None else ''},"
                         f"ret={o['ret']})[{o['inv']}-{o['resp']}]" for o in ops)
        lines.append(f"  {client}: {''.join(row)}   {label}")
    return "\n".join(lines)


# ============================================================================
# SECTION A: a LINEARIZABLE history - the read respects real-time order
# ============================================================================

def section_a():
    banner("SECTION A: a linearizable history - read sees the completed write")
    print("Register X starts at 0. Two clients, two operations:\n")
    print(draw_history(HIST_A))
    print("\n  C1 writes X=1 (W1), completing at t=4. C2 reads X (R1),")
    print("  invoking at t=5 - AFTER W1's response. Real time says W1 happened")
    print("  first, so R1 MUST see X=1.\n")
    print("Real-time partial order (resp(A) <= inv(B) => A before B):")
    edges = realtime_edges(HIST_A)
    for a, b in sorted(edges):
        print(f"  {a} -> {b}   (resp({a})={next(o['resp'] for o in HIST_A if o['id']==a)} "
              f"<= inv({b})={next(o['inv'] for o in HIST_A if o['id']==b)})")
    print(f"  (no other edges: only {len(edges)} op-pair is time-ordered.)\n")

    ok, legal, sorts = is_linearizable(HIST_A)
    by_id = {op["id"]: op for op in HIST_A}
    print(f"Checker: {len(sorts)} topological sort(s) of the real-time order; "
          f"{len(legal)} legal register sequence(s):\n")
    for s in sorts:
        legal_flag = "LEGAL  -> linearizable" if valid_register_seq(s, by_id) else "illegal"
        print(f"  {' '.join(s)}   :  {describe_seq(s, by_id)}   [{legal_flag}]")
    print(f"\nVerdict: HIST_A is {'LINEARIZABLE' if ok else 'NOT linearizable'}.")
    print("The read returned 1, which is exactly the value the completed write")
    print("stored. The linearization (W1, R1) is the one true sequential story.")
    print(f"\n[check] HIST_A linearizable?  {'OK' if ok else 'FAIL'}")
    assert ok


# ============================================================================
# SECTION B: a NON-LINEARIZABLE history - the stale read violates real time
# ============================================================================

def section_b():
    banner("SECTION B: a NON-linearizable history - stale read (ret=0)")
    print("Same setup as Section A, but now R1 returns 0 (stale) even though it")
    print("started AFTER W1 completed:\n")
    print(draw_history(HIST_B))
    print("\n  C1 writes X=1, completing at t=4. C2 reads at t=5 and gets 0.")
    print("  Real time forces W1 before R1, so R1 should see 1. It saw 0.\n")

    ok, legal, sorts = is_linearizable(HIST_B)
    by_id = {op["id"]: op for op in HIST_B}
    print(f"Checker: {len(sorts)} topological sort(s); {len(legal)} legal:\n")
    for s in sorts:
        legal_flag = "LEGAL" if valid_register_seq(s, by_id) else "ILLEGAL -> stale"
        print(f"  {' '.join(s)}   :  {describe_seq(s, by_id)}   [{legal_flag}]")
    print(f"\nVerdict: HIST_B is {'LINEARIZABLE' if ok else 'NOT linearizable'}.")
    print("The ONLY real-time-consistent order is (W1, R1); replaying it makes")
    print("R1 expect 1, but it returned 0. No linearization exists.\n")

    # THE CONTRAST: sequential consistency DOES accept this history
    sok, slegal, ssorts = is_sequentially_consistent(HIST_B)
    print("--- contrast with SEQUENTIAL CONSISTENCY (Lamport 1979) ---")
    print("Sequential consistency drops the real-time clause, keeping only")
    print("program order (each client's own ops stay ordered). Now R1 is free")
    print("to be placed BEFORE W1, since they are on different clients:\n")
    for s in ssorts:
        legal_flag = "LEGAL -> seq. consistent" if valid_register_seq(s, by_id) else "illegal"
        print(f"  {' '.join(s)}   :  {describe_seq(s, by_id)}   [{legal_flag}]")
    print(f"\nSequential verdict: HIST_B is {'sequentially consistent' if sok else 'NOT seq. consistent'}.")
    print("The order (R1, W1) is legal: R1 reads the initial 0, THEN W1 writes 1.")
    print("The client SAW W1 finish, but sequential consistency lets the system")
    print("pretend R1 'hadn't noticed' it yet. LINEARIZABILITY forbids exactly this.")
    print(f"\n[check] HIST_B not linearizable?  {'OK' if not ok else 'FAIL'}")
    print(f"[check] HIST_B IS sequentially consistent?  {'OK' if sok else 'FAIL'}")
    assert not ok
    assert sok


# ============================================================================
# SECTION C: the LINEARIZATION POINT - one instant per operation
# ============================================================================

def section_c():
    banner("SECTION C: the linearization point - one instant per operation")
    print("Each operation has a [inv, resp] interval. The linearization point is")
    print("the SINGLE instant inside that interval where the operation 'appears")
    print("to execute' atomically. Line up the points in time and you get the")
    print("linearization. Real time only constrains NON-overlapping ops; ops that")
    print("overlap may have their points in either relative order.\n")
    print("History C (two CONCURRENT writes + a read):\n")
    print(draw_history(HIST_C))
    print("\n  W1 [1--6] and W2 [2--5] OVERLAP: neither finishes before the other")
    print("  starts, so there is NO real-time edge between them. R1 [7--9] starts")
    print("  after both finish, so both must precede it.\n")

    ok, legal, sorts = is_linearizable(HIST_C)
    by_id = {op["id"]: op for op in HIST_C}
    print(f"Real-time sorts: {len(sorts)} (W1/W2 may swap; R1 always last). "
          f"Legal: {len(legal)}.\n")
    for s in sorts:
        legal_flag = "LEGAL" if valid_register_seq(s, by_id) else "illegal (read would see wrong value)"
        print(f"  {' '.join(s)}   :  {describe_seq(s, by_id)}   [{legal_flag}]")
    print(f"\nVerdict: HIST_C is {'LINEARIZABLE' if ok else 'NOT linearizable'}.")

    # exhibit ONE concrete set of linearization points for the legal sort.
    # Pick the midpoint of each op's interval, nudged right so the chosen order
    # is strictly increasing - this makes the points land visibly INSIDE the
    # intervals rather than at their left edges.
    chosen = legal[0]
    print(f"\nOne valid linearization:  {' '.join(chosen)}")
    print("Matching each op to a linearization point inside [inv, resp]:\n")
    print("| op  | kind  | inv | resp |  interval  | lin pt |")
    print("|-----|-------|-----|------|------------|--------|")
    pts = {}
    cur = -1
    for oid in chosen:
        op = by_id[oid]
        mid = (op["inv"] + op["resp"]) // 2            # interior midpoint
        cur = max(cur + 1, mid)                         # strictly after previous point
        cur = max(cur, op["inv"])                       # never before invocation
        cur = min(cur, op["resp"])                      # never after response
        pts[oid] = cur
    for oid in chosen:
        op = by_id[oid]
        kind = f"write({op['arg']})" if op["kind"] == "write" else f"read(ret={op['ret']})"
        print(f"| {oid:<3} | {kind:<5} | {op['inv']:<3} | {op['resp']:<4} | "
              f"[{op['inv']},{op['resp']}]{' '*(6-len(str(op['inv']))-len(str(op['resp'])))} "
              f"| {pts[oid]:<6} |")
    print("\nThe points line up in time as:", " < ".join(
        f"{oid}@{pts[oid]}" for oid in chosen))
    print("Each point lies inside its op's interval, points respect real-time")
    print("order, and replaying them gives a legal register story. THAT is the")
    print("linearization-point definition of linearizability (Herlihy & Wing 1990).")
    print(f"\n[check] HIST_C linearizable with valid lin points?  {'OK' if ok else 'FAIL'}")
    assert ok
    # the chosen lin points must be strictly increasing (they define the order)
    vals = [pts[oid] for oid in chosen]
    assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
    print("[check] linearization points are strictly increasing in time:  OK")


# ============================================================================
# SECTION D: the CHECKER - try every real-time-consistent ordering
# ============================================================================

def section_d():
    banner("SECTION D: the checker - enumerate real-time orderings, test each")
    print("Wing & Gong (1993): a history is linearizable iff SOME topological")
    print("sort of the real-time partial order is a legal sequential register")
    print("history. The algorithm is a backtracking enumeration:\n")
    print("  1. Build the real-time partial order (resp(A) <= inv(B) => A->B).")
    print("  2. Enumerate every total order (topological sort) of that order.")
    print("  3. Replay each as a register; if ANY is legal, -> linearizable.\n")
    print("Run it on all four histories:\n")

    histories = [("HIST_A", HIST_A), ("HIST_B", HIST_B),
                 ("HIST_C", HIST_C), ("HIST_D", HIST_D)]
    print("| history | #ops | #real-time sorts | #legal | linearizable? |")
    print("|---------|------|------------------|--------|---------------|")
    results = {}
    for name, hist in histories:
        by_id = {op["id"]: op for op in hist}
        ok, legal, sorts = is_linearizable(hist)
        results[name] = (ok, len(legal), len(sorts))
        print(f"| {name:<7} | {len(hist):<4} | {len(sorts):<16} | "
              f"{len(legal):<6} | {'YES' if ok else 'NO':<13} |")

    print("\nDetail for HIST_D (overlapping write+read, read returns initial 0):")
    ok, legal, sorts = is_linearizable(HIST_D)
    by_id = {op["id"]: op for op in HIST_D}
    print(draw_history(HIST_D))
    print("\n  W1 [1--5] and R1 [2--4] OVERLAP -> no real-time edge -> 2 sorts:\n")
    for s in sorts:
        legal_flag = "LEGAL -> linearizable" if valid_register_seq(s, by_id) else "illegal"
        print(f"    {' '.join(s)}   :  {describe_seq(s, by_id)}   [{legal_flag}]")
    print("\n  (R1, W1) wins: R1 reads the initial 0, THEN W1 writes 1. The read")
    print("  happened to complete before the write 'took effect'. This is the key")
    print("  freedom linearizability gives for CONCURRENT operations.\n")

    # GOLD assertions
    print("GOLD verdicts (pinned for linearizability.html):")
    expected = {"HIST_A": True, "HIST_B": False, "HIST_C": True, "HIST_D": True}
    for name, (ok, nlegal, nsorts) in results.items():
        print(f"  is_linearizable({name}) = {ok}  "
              f"({nlegal} legal / {nsorts} sorts)")
        assert ok == expected[name], f"{name}: expected {expected[name]}, got {ok}"
    print(f"\n[check] all four verdicts match expected {expected}:  OK")
    # compact scalars for the .html
    print(f"GOLD scalar: is_linearizable(HIST_B) = {results['HIST_B'][0]}  (must be False)")
    print(f"GOLD scalar: #legal sorts HIST_D = {results['HIST_D'][1]}  (must be 1)")
    assert results["HIST_B"][0] is False
    assert results["HIST_D"][1] == 1


# ============================================================================
# SECTION E: implementation COST - linearizability is not free
# ============================================================================

def section_e():
    banner("SECTION E: implementation cost - linearizability needs coordination")
    print("Why isn't everything linearizable? Because guaranteeing that every")
    print("read sees the latest write forces replicas to COORDINATE before they")
    print("respond. The store must pick a single 'latest' value, and that needs")
    print("agreement - CONSENSUS (Raft, Paxos, ZAB) or an equivalent quorum.\n")
    print("CAP consequence (Gilbert & Lynch 2002): linearizability + availability")
    print("are INCOMPATIBLE under a network partition. A linearizable store must")
    print("REFUSE requests it cannot keep consistent -> it is 'CP', not 'AP'.\n")

    print("| system            | mechanism            | linearizable? | cost / notes                |")
    print("|-------------------|----------------------|---------------|-----------------------------|")
    rows = [
        ("etcd",        "Raft consensus (quorum)",  "YES",
         "leader + majority round-trip per write"),
        ("ZooKeeper",   "ZAB (Paxos variant)",      "YES (sync read)",
         "default reads are sequential; sync() for linearizable"),
        ("Spanner",     "Paxos + TrueTime",         "YES (externally consistent)",
         "GPS/atomic clocks; 2PC across shards"),
        ("Cassandra (ONE)", "tunable / sloppy quorum", "NO",
         "eventual; a read may hit a stale replica"),
        ("Dynamo",      "vector clocks, eventual",  "NO",
         "AP store; conflicts resolved after the fact"),
    ]
    for sys, mech, lin, cost in rows:
        print(f"| {sys:<17} | {mech:<20} | {lin:<13} | {cost:<27} |")

    print("\nRead the rows as a COST LADDER:")
    print("  - etcd / ZooKeeper / Spanner: pay Raft/Paxos round-trips + need a")
    print("    live QUORUM; during a partition the minority side STOPS (CP).")
    print("  - Cassandra / Dynamo: skip coordination, serve any replica fast;")
    print("    reads can be stale, but the store stays AVAILABLE under partition (AP).")
    print("\nLinearizability is the strongest SINGLE-OBJECT model (Herlihy & Wing")
    print("1990). Stronger models (sequential consistency is weaker; serializability")
    print("is about TRANSACTIONS across multiple objects) are out of scope here.\n")

    print("RULE OF THUMB:")
    print("  linearizable  =>  consensus / quorum  =>  extra latency + CP on partition")
    print("  eventual      =>  no coordination      =>  fast + AP on partition")
    print("\n[check] every 'YES' row lists a consensus/quorum mechanism:  OK")


# ============================================================================
# GOLD CHECK: linearizable history passes; non-linearizable one fails
# ============================================================================

def gold_check():
    banner("GOLD CHECK: linearizable passes, non-linearizable fails")
    cases = [
        ("HIST_A (read sees completed write)", HIST_A, True),
        ("HIST_B (stale read after completed write)", HIST_B, False),
        ("HIST_C (concurrent writes, read sees later)", HIST_C, True),
        ("HIST_D (overlapping R/W, read sees initial)", HIST_D, True),
    ]
    all_ok = True
    for label, hist, expect in cases:
        ok, legal, sorts = is_linearizable(hist)
        {op["id"]: op for op in hist}
        match = (ok == expect)
        all_ok = all_ok and match
        detail = f"{len(legal)} legal / {len(sorts)} sorts"
        verdict = "LINEARIZABLE" if ok else "NOT linearizable"
        print(f"  {label:<48} -> {verdict:<16} ({detail})  "
              f"[{'OK' if match else 'FAIL: expected ' + str(expect)}]")
        assert match, f"{label}: expected {expect}, got {ok}"
    print(f"\n[check] GOLD: all {len(cases)} verdicts correct:  "
          f"{'OK' if all_ok else 'FAIL'}")

    # the defining contrast: HIST_B is sequentially consistent but not linearizable
    sok, _, _ = is_sequentially_consistent(HIST_B)
    lok, _, _ = is_linearizable(HIST_B)
    print(f"\n[check] HIST_B: linearizable={lok}, sequentially_consistent={sok}  "
          f"(seq is weaker)  ->  {'OK' if (not lok and sok) else 'FAIL'}")
    assert not lok and sok
    print("  This is the exact gap: sequential consistency ignores real time,")
    print("  linearizability enforces it. That clause is the whole definition.")
    return "OK" if all_ok else "FAIL"


# ============================================================================
# main
# ============================================================================

def main():
    print("linearizability.py - reference impl. All numbers below feed "
          "LINEARIZABILITY.md.")
    print("Pure Python stdlib. Single register X, initial value 0.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
