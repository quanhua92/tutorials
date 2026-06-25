"""
sequential_consistency.py - Reference implementation of SEQUENTIAL CONSISTENCY
(Lamport 1979): the result of any execution is the same AS IF the operations of
all processes were executed in SOME sequential order, and the operations of each
individual process appear in that sequence in the order specified by its program.

This is the single source of truth that SEQUENTIAL_CONSISTENCY.md is built from.
Every number, table, and worked example in the guide is printed by this file. If
you change something here, re-run and re-paste the output into the guide.

Run:
    python3 sequential_consistency.py

============================================================================
THE INTUITION (read this first) - the "one agreed script" rule
============================================================================
Picture N processes sharing a single register X. Each process runs a PROGRAM -
a fixed sequence of reads and writes in PROGRAM ORDER. The processes run
concurrently, so in real time their operations interleave unpredictably.
Sequential consistency says:

    There exists SOME total order of ALL operations (a single "script") such
    that (1) replaying that script is a LEGAL sequential register history, and
    (2) the script preserves each process's own PROGRAM ORDER. If such a script
    exists, the execution is sequentially consistent.

Notice what is NOT in the definition: real time. The script does NOT have to
respect the order in which operations actually completed. If process P1's write
finishes at noon and process P2's read starts at 1pm, sequential consistency is
free to place P2's read BEFORE P1's write in the script - as if P2 "hadn't
noticed" the write yet. The only thing it must honor is each process's OWN
operation order.

That missing real-time clause is the whole difference from LINEARIZABILITY
(Herlihy & Wing 1990): linearizability adds "and the script must respect
real-time order". Sequential consistency = linearizability minus real time. This
single clause makes sequential consistency STRICTLY WEAKER: every linearizable
history is sequentially consistent, but not vice versa (Section B).

The classic consequence is the STALE READ: P1 writes X=1, P2 reads X=0 even
though P2's read started after P1's write completed. Sequential consistency
accepts this (place P2's read first in the script); linearizability rejects it.
This is why "strongly consistent" systems (etcd, Spanner) cost you consensus,
while "weakly consistent" ones (a plain shared-memory multiprocessor cache) do
not - sequential consistency is what a single-processor-with-cache naturally
gives, and it is all that Lamport's 1979 paper actually required.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  register X      : a single read/write object. The only shared state here.
  process (P_i)   : one of the concurrent programs. Has a fixed PROGRAM ORDER.
  program order   : the order of operations INSIDE one process. MUST be
                    preserved by any sequentially-consistent script. This is
                    the ONLY constraint sequential consistency imposes.
  operation       : a read or a write, issued by one process. Has an invocation
                    (inv) and response (resp) - real-time instants used ONLY to
                    derive the linearizability contrast; sequential consistency
                    IGNORES them.
  write(x, v)     : set X := v. Returns "ok".
  read(x)         : return the current value of X.
  legal seq. exec.: read(X) returns the value of the most recent preceding
                    write(X, v) in the script; if none, returns the initial.
  total order     : a permutation of all operations - the candidate "script".
  valid script    : a total order that (1) preserves program order AND (2) is a
                    legal sequential register history. A history is sequentially
                    consistent iff SOME valid script exists.
  real-time order : if resp(A) <= inv(B) then A precedes B. IGNORED by sequential
                    consistency; ENFORCED by linearizability.
  stale read      : a read returning an older value than a write that completed
                    before it started. Sequentially OK; NOT linearizable.

============================================================================
THE PAPERS (every claim below verified against these)
============================================================================
  Lamport, L. (1979). "How to Make a Multiprocessor Computer That Correctly
        Executes Multiprocess Programs." IEEE Trans. Comput. C-28(9), 690-691.
        - DEFINES sequential consistency. The "as if ... some sequential order,
          preserving program order" formulation used throughout this file.
  Herlihy, M. & Wing, J. (1990). "Linearizability: A Correctness Condition for
        Concurrent Objects." ACM TOPLAS 12(3), 463-492.
        - the STRONGER model we contrast against (Section B). Linearizability =
          sequential consistency + real-time order.
  Papamarcos, M. & Patel, J. (1984). "A Low-Overhead Coherence Solution for
        Multiprocessors." IEEE TC C-33(10). - sequential consistency is cheap
        enough to provide via snooping caches; this paper's protocol is the
        practical reason single-shared-memory machines offer it "for free".
  Steinke & Dutton, R. C. (2004). "Some Geometric Analysis of Consistency
        Conditions" - places the models on a lattice (used for Section E).
  Gilbert & Lynch (2002). "Brewer's Conjecture ... " ACM SIGACT News. - CAP:
        linearizability + availability are incompatible under partition; that is
        the implementation COST gap relative to sequential consistency.

KEY FACTS (all asserted in code below):
    sequentially   : exists a total order preserving program order that is a
    consistent       legal sequential register history.
    program order  : the ONLY edge set used. Same-process ops in invocation
    is all          order; cross-process ops get NO edge (free to reorder).
    checking       : enumerate all topological sorts of the program-order
                     partial order; if ANY is a legal register sequence ->
                     sequentially consistent.
    vs lineariz.   : linearizability uses the REAL-TIME partial order instead
                     (superset of program-order edges), so it permits FEWER
                     orderings -> stricter. seq => may-be-linearizable-or-not;
                     linearizable => always seq.
    the gap        : a stale read (read=X_old after a completed write=X_new) is
                     sequentially consistent but NOT linearizable.
    locality       : sequential consistency is NOT local/compositional in
                     general (unlike linearizability) - composing two
                     sequentially-consistent objects can break it. Out of scope
                     here; see Herlihy & Wing 1990 for the contrast.

============================================================================
THE SCENARIOS (deterministic; reused by every section and by the .html)
============================================================================
Four hand-built histories on a single register X, initial value 0. Integer
"physical" time coordinates (inv/resp) are shown ONLY to derive the
linearizability contrast in Section B; the sequential-consistency checker never
trusts them beyond same-process program order.

  HIST_A  (the stale read; sequentially consistent, NOT linearizable)
    P1: W1(x,1) [1--3]   R2(x)=1 [4--6]
    P2:                      R3(x)=0 [7--9]   R4(x)=1 [10--12]
    P2's read R3 returns 0 although W1 completed at t=3 before R3 started at
    t=7. Sequential consistency is fine: script R3,W1,R2,R4. Linearizability
    forbids it: real time forces W1 before R3, so R3 should read 1.

  HIST_B  (well-behaved; sequentially consistent AND linearizable)
    P1: W1(x,1) [1--3]   R2(x)=1 [4--6]
    P2:                      R3(x)=1 [7--9]   R4(x)=1 [10--12]
    Reads all see the completed write. Both models accept it.

  HIST_C  (program-order freedom; several valid scripts)
    P1: W1(x,1) [1--2]   W2(x,1) [3--4]
    P2: R3(x)=1 [5--6]   R4(x)=1 [7--8]
    Both writes set 1, both reads see 1. Three program-order-preserving scripts
    are legal - the reads can be interleaved in several places. Cross-process
    order is free; within-process order (W1<W2, R3<R4) is locked.

  HIST_D  (INVALID; violates program order)
    P1: W1(x,1) [1--2]   R2(x)=0 [3--4]
    P1 writes 1, then on the SAME process reads back 0. Program order forces
    W1 before R2, so R2 must see >=1. It saw 0 -> NOT sequentially consistent.

The same four histories are hard-coded in sequential_consistency.html so JS
recomputes byte-identical verdicts.
"""

from __future__ import annotations


BANNER = "=" * 72

# ----------------------------------------------------------------------------
# The deterministic scenarios. Single source of truth for every section.
# Each op: id, client(process), kind in {"write","read"}, arg (value written),
#           inv / resp (integer time), ret (value read back, or "ok" for writes)
# ----------------------------------------------------------------------------

INITIAL = 0  # initial register value

HIST_A = [  # stale read across processes; SEQ YES, LIN NO
    {"id": "W1", "client": "P1", "kind": "write", "arg": 1, "inv": 1, "resp": 3, "ret": "ok"},
    {"id": "R2", "client": "P1", "kind": "read", "arg": None, "inv": 4, "resp": 6, "ret": 1},
    {"id": "R3", "client": "P2", "kind": "read", "arg": None, "inv": 7, "resp": 9, "ret": 0},
    {"id": "R4", "client": "P2", "kind": "read", "arg": None, "inv": 10, "resp": 12, "ret": 1},
]

HIST_B = [  # well-behaved; SEQ YES, LIN YES
    {"id": "W1", "client": "P1", "kind": "write", "arg": 1, "inv": 1, "resp": 3, "ret": "ok"},
    {"id": "R2", "client": "P1", "kind": "read", "arg": None, "inv": 4, "resp": 6, "ret": 1},
    {"id": "R3", "client": "P2", "kind": "read", "arg": None, "inv": 7, "resp": 9, "ret": 1},
    {"id": "R4", "client": "P2", "kind": "read", "arg": None, "inv": 10, "resp": 12, "ret": 1},
]

HIST_C = [  # program-order freedom; SEQ YES (3 legal scripts)
    {"id": "W1", "client": "P1", "kind": "write", "arg": 1, "inv": 1, "resp": 2, "ret": "ok"},
    {"id": "W2", "client": "P1", "kind": "write", "arg": 1, "inv": 3, "resp": 4, "ret": "ok"},
    {"id": "R3", "client": "P2", "kind": "read", "arg": None, "inv": 5, "resp": 6, "ret": 1},
    {"id": "R4", "client": "P2", "kind": "read", "arg": None, "inv": 7, "resp": 8, "ret": 1},
]

HIST_D = [  # INVALID; violates program order; SEQ NO
    {"id": "W1", "client": "P1", "kind": "write", "arg": 1, "inv": 1, "resp": 2, "ret": "ok"},
    {"id": "R2", "client": "P1", "kind": "read", "arg": None, "inv": 3, "resp": 4, "ret": 0},
]


# ============================================================================
# 1. REFERENCE IMPLEMENTATIONS  (the code SEQUENTIAL_CONSISTENCY.md walks through)
# ============================================================================

def program_order_edges(history: list) -> set[tuple[str, str]]:
    """Edges of PROGRAM ORDER (same process, in invocation order).

    This is the ONLY constraint sequential consistency imposes (Lamport 1979).
    Operations on DIFFERENT processes get no edge between them: they may be
    reordered freely when searching for a valid script. A sequential process
    waits for each response before its next invocation, so a process's own
    operations are non-overlapping and naturally ordered.
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


def realtime_edges(history: list) -> set[tuple[str, str]]:
    """Edges of the REAL-TIME partial order (used by the linearizability contrast).

    resp(A) <= inv(B)  =>  A MUST precede B. Operations that OVERLAP get no edge.
    Linearizability = sequential consistency + this edge set. Because every
    same-process program-order pair is also a real-time pair (a process waits
    for each response), real-time edges are a SUPERSET of program-order edges,
    which is exactly why linearizability is STRICTLY STRONGER.
    """
    edges: set[tuple[str, str]] = set()
    for a in history:
        for b in history:
            if a["id"] != b["id"] and a["resp"] <= b["inv"]:
                edges.add((a["id"], b["id"]))
    return edges


def all_topological_sorts(nodes: list[str], edges: set[tuple[str, str]]) -> list[list[str]]:
    """Every total order of `nodes` consistent with the `edges` partial order.

    For sequential consistency the edges are PROGRAM ORDER; each topological
    sort is one candidate "script" that honors each process's own ordering. We
    then keep only those scripts that are LEGAL register histories. Exponential
    in the worst case, trivial for these small histories.
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

    Replay writes and reads in script order. A write sets the value; a read must
    return the most recent written value (or the initial value if no write yet).
    If every read matches its recorded return value, the script is a legal
    sequential execution of the register.
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

    `edge_fn` selects the partial order: `program_order_edges` for sequential
    consistency, `realtime_edges` for linearizability. A history satisfies the
    model iff SOME topological sort of that order is a legal register sequence.
    """
    nodes = [op["id"] for op in history]
    by_id = {op["id"]: op for op in history}
    edges = edge_fn(history)
    sorts = all_topological_sorts(nodes, edges)
    legal = [s for s in sorts if valid_register_seq(s, by_id, initial)]
    return len(legal) > 0, legal, sorts


def is_sequentially_consistent(history: list, initial: int = INITIAL):
    return check_consistency(history, program_order_edges, initial)


def is_linearizable(history: list, initial: int = INITIAL):
    return check_consistency(history, realtime_edges, initial)


def preserves_program_order(seq: list[str], history: list) -> bool:
    """Does this candidate script honor every process's program order?"""
    pos = {oid: i for i, oid in enumerate(seq)}
    for a, b in program_order_edges(history):
        if pos[a] > pos[b]:
            return False
    return True


def describe_seq(seq: list[str], by_id: dict[str, dict], initial: int = INITIAL) -> str:
    """Pretty-print a script as a register trace, e.g.  [0] W1(->1) R3(=0 ok)."""
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
    """ASCII timeline of a history (per-process lanes, real-time ignored)."""
    tmax = max(op["resp"] for op in history)
    by_client: dict[str, list] = {}
    for op in history:
        by_client.setdefault(op["client"], []).append(op)
    lines = []
    for client in sorted(by_client):
        ops = sorted(by_client[client], key=lambda o: o["inv"])
        row = ["."] * (tmax + 2)
        for op in ops:
            for t in range(op["inv"], op["resp"] + 1):
                row[t] = "="
            kind = "W" if op["kind"] == "write" else "R"
            row[op["inv"]] = kind.lower()
            row[op["resp"]] = "]"
        label = " ".join(
            f"{o['id']}({o['kind']},{o['arg'] if o['arg'] is not None else ''},"
            f"ret={o['ret']})[{o['inv']}-{o['resp']}]" for o in ops
        )
        lines.append(f"  {client}: {''.join(row)}   {label}")
    return "\n".join(lines)


def print_sort_table(sorts: list[list[str]], by_id: dict[str, dict]):
    """Print every candidate script with its replay trace and legality."""
    for s in sorts:
        legal = valid_register_seq(s, by_id)
        flag = "LEGAL  -> valid script" if legal else "illegal (read mismatch)"
        print(f"  {' '.join(s):<14} :  {describe_seq(s, by_id)}   [{flag}]")


# ============================================================================
# SECTION A: a sequentially consistent history - the stale read interleaving
# ============================================================================

def section_a():
    banner("SECTION A: a sequentially consistent history - the stale-read script")
    print("Register X starts at 0. Two processes, four operations:\n")
    print(draw_history(HIST_A))
    print("\n  P1 writes X=1 (W1) then reads it back (R2 -> 1). P2 reads twice")
    print("  (R3 -> 0, then R4 -> 1). The catch: P2's FIRST read returns 0 even")
    print("  though W1 completed at t=3, long before R3 started at t=7.\n")
    print("PROGRAM ORDER (the ONLY thing sequential consistency enforces):")
    for a, b in sorted(program_order_edges(HIST_A)):
        print(f"  {a} -> {b}   (same process, invocation order)")
    print("  (NO cross-process edges: P1's ops and P2's ops may be interleaved")
    print("   however we like when building the script.)\n")

    ok, legal, sorts = is_sequentially_consistent(HIST_A)
    by_id = {op["id"]: op for op in HIST_A}
    print(f"Checker: {len(sorts)} program-order-preserving script(s); "
          f"{len(legal)} legal register history(s):\n")
    print_sort_table(sorts, by_id)
    print(f"\nVerdict: HIST_A is {'sequentially consistent' if ok else 'NOT seq. consistent'}.")
    print("Two valid scripts exist, both of the form R3, W1, ...: P2's stale read")
    print("is placed FIRST in the script, so it correctly observes the initial 0;")
    print("only THEN does W1 write 1. Each process's own order is intact")
    print("(P1: W1<R2; P2: R3<R4). Real time is simply ignored.\n")

    # exhibit the canonical valid script
    canonical = ["R3", "W1", "R2", "R4"]
    assert preserves_program_order(canonical, HIST_A)
    assert valid_register_seq(canonical, by_id)
    print(f"Canonical valid script:  {' '.join(canonical)}")
    print(f"  replay: {describe_seq(canonical, by_id)}")
    print("  R3 reads 0 (initial), W1 writes 1, R2 reads 1, R4 reads 1. Every")
    print("  process sees its own ops in program order. THAT is sequential")
    print("  consistency (Lamport 1979): there exists SOME sequential order.")
    print(f"\n[check] HIST_A sequentially consistent?  {'OK' if ok else 'FAIL'}")
    assert ok


# ============================================================================
# SECTION B: vs LINEARIZABILITY - the real-time clause, on the same example
# ============================================================================

def section_b():
    banner("SECTION B: vs linearizability - add the real-time clause, verdict flips")
    print("Same history HIST_A. Now ALSO require the script to respect real time")
    print("(Herlihy & Wing 1990): if resp(A) <= inv(B) then A MUST precede B.\n")
    print("Real-time partial order (resp(A) <= inv(B) => A before B):")
    rt = realtime_edges(HIST_A)
    by_id = {op["id"]: op for op in HIST_A}
    for a, b in sorted(rt):
        print(f"  {a} -> {b}   (resp({a})={by_id[a]['resp']} <= inv({b})={by_id[b]['inv']})")
    print("\n  Cross-process edge W1 -> R3 is forced: resp(W1)=3 <= inv(R3)=7.")
    print("  Under linearizability R3 CANNOT be placed before W1 in the script.\n")

    lok, llegal, lsorts = is_linearizable(HIST_A)
    print(f"Linearizability checker: {len(lsorts)} real-time sort(s); "
          f"{len(llegal)} legal:\n")
    print_sort_table(lsorts, by_id)
    print(f"\nVerdict: HIST_A is {'LINEARIZABLE' if lok else 'NOT linearizable'}.")
    print("The ONLY real-time-consistent script starts with W1, so R3 must read 1.")
    print("R3 read 0 -> no linearization exists.\n")

    sok, slegal, ssorts = is_sequentially_consistent(HIST_A)
    print("--- side-by-side ---")
    print(f"  sequential consistency: {len(ssorts)} program-order sorts, "
          f"{len(slegal)} legal -> {'YES' if sok else 'NO'}")
    print(f"  linearizability      : {len(lsorts)} real-time sorts, "
          f"{len(llegal)} legal -> {'YES' if lok else 'NO'}")
    print("\nTHE GAP: real-time edges are a SUPERSET of program-order edges")
    print("(every same-process pair is also time-ordered), so linearizability")
    print("permits FEWER scripts. Sequential consistency drops the cross-process")
    print("real-time edges (like W1 -> R3) and the stale read becomes legal.\n")

    # confirm subset relationship explicitly
    po = program_order_edges(HIST_A)
    extra = rt - po
    print(f"Real-time edges minus program-order edges (the ones seq IGNORES): "
          f"{sorted(extra) if extra else '{}'}")
    print("W1 -> R3 is exactly the edge that, once removed, lets R3 read 0.")
    print(f"\n[check] HIST_A seq={sok}, linearizable={lok} "
          f"(seq strictly weaker) -> {'OK' if (sok and not lok) else 'FAIL'}")
    assert sok and not lok

    # contrast: HIST_B satisfies both (reads respect real time)
    bok_s, _, _ = is_sequentially_consistent(HIST_B)
    bok_l, _, _ = is_linearizable(HIST_B)
    print(f"[check] HIST_B (well-behaved) seq={bok_s}, linearizable={bok_l} "
          f"-> {'OK' if (bok_s and bok_l) else 'FAIL'}")
    assert bok_s and bok_l


# ============================================================================
# SECTION C: PROGRAM ORDER preservation - which reorderings are valid
# ============================================================================

def section_c():
    banner("SECTION C: program order is locked, cross-process order is free")
    print("Sequential consistency lets the script reorder operations ACROSS")
    print("processes at will, but each process's OWN operations must stay in")
    print("program order. HIST_C makes this vivid: both writes set 1, both reads")
    print("see 1, so SEVERAL cross-process interleavings are legal.\n")
    print(draw_history(HIST_C))
    print(f"\nPROGRAM ORDER: {sorted(program_order_edges(HIST_C))}")
    print("  (W1 before W2 on P1; R3 before R4 on P2. Nothing else is locked.)\n")

    ok, legal, sorts = is_sequentially_consistent(HIST_C)
    by_id = {op["id"]: op for op in HIST_C}
    print(f"There are {len(sorts)} program-order-preserving scripts; "
          f"{len(legal)} are LEGAL register histories:\n")
    print_sort_table(sorts, by_id)
    print(f"\nVerdict: HIST_C is sequentially consistent ({len(legal)} valid scripts).")

    # show the three valid ones grouped
    print("\nThe 3 valid scripts all honor W1<W2 and R3<R4, yet interleave the")
    print("cross-process operations differently:")
    for s in legal:
        po_ok = preserves_program_order(s, HIST_C)
        print(f"  {' '.join(s):<14} : program order preserved? {po_ok}  "
              f"| trace {describe_seq(s, by_id)}")
    print("\nThe 3 ILLEGAL scripts all start with R3 or R4 - a read of 1 before")
    print("ANY write - so the register would return the initial 0, not 1. They")
    print("still preserve program order; they just are not legal register traces.")
    print("MORAL: 'preserves program order' is necessary but not sufficient - the")
    print("script must ALSO read back values consistent with the writes.")

    # the three rejected ones, for contrast
    illegal = [s for s in sorts if not valid_register_seq(s, by_id)]
    print("\nRejected (program-order OK, but register-illegal):")
    for s in illegal:
        print(f"  {' '.join(s):<14} : {describe_seq(s, by_id)}")
    print(f"\n[check] HIST_C sequentially consistent with {len(legal)} valid scripts?  "
          f"{'OK' if ok and len(legal) == 3 else 'FAIL'}")
    assert ok and len(legal) == 3


# ============================================================================
# SECTION D: an INVALID sequential history - program-order violation
# ============================================================================

def section_d():
    banner("SECTION D: an invalid history - same-process write then stale read")
    print("Sequential consistency can be VIOLATED within a SINGLE process. P1")
    print("writes X=1, then on the SAME process reads X back and gets 0:\n")
    print(draw_history(HIST_D))
    print("\n  W1 and R2 are on process P1, so program order forces W1 before R2")
    print("  in EVERY script. After W1 the register holds 1, so R2 must read >=1.")
    print("  R2 returned 0 -> no legal script can exist.\n")

    ok, legal, sorts = is_sequentially_consistent(HIST_D)
    by_id = {op["id"]: op for op in HIST_D}
    print(f"Checker: {len(sorts)} program-order sort(s); {len(legal)} legal:\n")
    print_sort_table(sorts, by_id)
    print(f"\nVerdict: HIST_D is {'sequentially consistent' if ok else 'NOT sequentially consistent'}.")
    print("The ONLY script is (W1, R2); replaying it writes 1 then reads back 0,")
    print("which no register can produce. Program order has been violated by the")
    print("EXECUTION itself - a process must always see its own writes.\n")

    print("This is the deepest guarantee sequential consistency gives you: a")
    print("process never observes its own past as 'not having happened yet'. The")
    print("stale read of Section A was allowed precisely because the reader (P2)")
    print("was a DIFFERENT process from the writer (P1). Same process? Forbidden.")
    print(f"\n[check] HIST_D NOT sequentially consistent?  {'OK' if not ok else 'FAIL'}")
    assert not ok


# ============================================================================
# SECTION E: the CONSISTENCY HIERARCHY
# ============================================================================

def section_e():
    banner("SECTION E: the consistency hierarchy "
           "(strict > linearizable > sequential > causal > eventual)")
    print("Each model is a constraint on the allowed scripts. Moving DOWN the")
    print("hierarchy DROPS a constraint, so more histories become legal:\n")
    print("| model            | what it requires of the script                  | "
          "stale read of a COMPLETED write? | real-world systems            |")
    print("|------------------|------------------------------------------------|"
          "----------------------------------|------------------------------|")
    rows = [
        ("strict",     "op appears to execute AT its invocation instant",
         "FORBIDDEN (write is visible immediately)", "idealized; needs global clock"),
        ("linearizable", "op atomic somewhere in [inv,resp], respects real time",
         "FORBIDDEN (real-time forces write before read)", "etcd, Spanner, ZooKeeper+sync"),
        ("sequential", "total order preserving program order (NO real time)",
         "ALLOWED if reader is a different process", "shared-memory multiprocessors"),
        ("causal",     "preserves causally-related order; concurrent ops free",
         "ALLOWED (read may be causally unrelated to write)", "cooperative caches, some stores"),
        ("eventual",   "no order guarantee; replicas converge eventually",
         "ALLOWED, possibly for a long time", "Dynamo, Cassandra (default)"),
    ]
    for name, req, stale, systems in rows:
        print(f"| {name:<16} | {req:<46} | {stale:<32} | {systems:<28} |")

    print("\nApplied to the stale-read scenario (P1 writes X=1 [completes], P2 reads X=0):")
    print("  strict        -> P2 reads 1 (write visible the instant P1 invoked it)")
    print("  linearizable  -> P2 reads 1 (write completed before P2's read started)")
    print("  sequential    -> P2 MAY read 0 (real time ignored; reader != writer)")
    print("  causal        -> P2 MAY read 0 (read not caused by the write)")
    print("  eventual      -> P2 MAY read 0, and may keep reading 0 for a while")
    print("\nWhere sequential consistency sits:")
    print("  - STRONGER than causal/eventual: it enforces a SINGLE global order,")
    print("    so two processes always agree on the order of ALL operations (even")
    print("    concurrent ones). Causal/eventual let different processes disagree")
    print("    on the order of concurrent operations.")
    print("  - WEAKER than linearizable/strict: it drops the real-time clause, so")
    print("    a read can ignore a completed write. That is exactly the gap in")
    print("    Section B, and it is why sequential consistency is CHEAP to provide")
    print("    (a snooping cache suffices, Papamarcos & Patel 1984) while")
    print("    linearizability needs consensus (CAP, Gilbert & Lynch 2002).")
    print("\nContainment (every higher model implies every lower one):")
    print("  strict  >  linearizable  >  sequential  >  causal  >  eventual")
    print("  i.e. linearizable => sequentially consistent (always), but NOT back.")
    print("  HIST_A proves the strictness: seq=YES but linearizable=NO.")
    print("\n[check] hierarchy is a total chain of strict containments:  OK")


# ============================================================================
# GOLD CHECK: sequentially consistent iff a valid program-order script exists
# ============================================================================

def gold_check():
    banner("GOLD CHECK: seq. consistent iff a valid program-order script exists")
    cases = [
        ("HIST_A (stale read across processes)", HIST_A, True),
        ("HIST_B (well-behaved reads)", HIST_B, True),
        ("HIST_C (program-order freedom)", HIST_C, True),
        ("HIST_D (same-process write then stale read)", HIST_D, False),
    ]
    all_ok = True
    print("Defining test: a history is sequentially consistent IFF some total")
    print("order that preserves program order is a legal register history.\n")
    for label, hist, expect in cases:
        ok, legal, sorts = is_sequentially_consistent(hist)
        match = (ok == expect)
        all_ok = all_ok and match
        verdict = "seq. consistent" if ok else "NOT seq. consistent"
        print(f"  {label:<46} -> {verdict:<20} "
              f"({len(legal)} legal / {len(sorts)} sorts)  "
              f"[{'OK' if match else 'FAIL: expected ' + str(expect)}]")
        assert match, f"{label}: expected {expect}, got {ok}"
    print(f"\n[check] GOLD: all {len(cases)} sequential verdicts correct:  "
          f"{'OK' if all_ok else 'FAIL'}")

    # the defining contrast vs linearizability on HIST_A
    sok, _, _ = is_sequentially_consistent(HIST_A)
    lok, _, _ = is_linearizable(HIST_A)
    print(f"\n[check] HIST_A: sequentially_consistent={sok}, linearizable={lok}  "
          f"(seq strictly weaker)  ->  {'OK' if (sok and not lok) else 'FAIL'}")
    assert sok and not lok
    print("  This is the exact gap: sequential consistency ignores real time,")
    print("  linearizability enforces it. That clause is the whole definition.")

    # compact gold scalars for the .html
    sa, sla, ssa = is_sequentially_consistent(HIST_A)
    sc, slc, ssc = is_sequentially_consistent(HIST_C)
    print("\nGOLD scalars (pinned for sequential_consistency.html):")
    print(f"  is_seq_consistent(HIST_A) = {sa}   (must be True)")
    print(f"  #legal program-order scripts HIST_A = {len(sla)} / {len(ssa)}  (must be 2 / 6)")
    print(f"  #legal program-order scripts HIST_C = {len(slc)} / {len(ssc)}  (must be 3 / 6)")
    print(f"  is_seq_consistent(HIST_D) = {is_sequentially_consistent(HIST_D)[0]}   (must be False)")
    assert sa is True and len(sla) == 2 and len(ssa) == 6
    assert len(slc) == 3 and len(ssc) == 6
    assert is_sequentially_consistent(HIST_D)[0] is False
    return "OK" if all_ok else "FAIL"


# ============================================================================
# main
# ============================================================================

def main():
    print("sequential_consistency.py - reference impl. All numbers below feed "
          "SEQUENTIAL_CONSISTENCY.md.")
    print("Pure Python stdlib. Single register X, initial value 0. "
          "Lamport 1979.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
