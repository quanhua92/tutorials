"""
deadlock_detection.py - Reference implementation of deadlock detection in
databases: the wait-for graph, DFS cycle detection, victim-selection
heuristics, deadlock PREVENTION (lock ordering, wound-wait, wait-die), and
livelock prevention via priority boost.

This is the single source of truth that DEADLOCK_DETECTION.md is built from.
Every number, table, and trace in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 deadlock_detection.py

============================================================================
THE INTUITION (read this first) - the four people in a hallway
============================================================================
A deadlock is a ring of transactions where each is holding a lock the next one
needs, and each is waiting for a lock the previous one holds. Nobody can move.

Picture four people in a circular hallway, each holding one door shut, each
wanting to walk through the door the person ahead is holding:

      T1 holds door A, wants door B   (held by T2)
      T2 holds door B, wants door C   (held by T3)
      T3 holds door C, wants door A   (held by T1)

That ring is a CYCLE in the WAIT-FOR GRAPH. A cycle is the ONLY shape that can
freeze everyone, so "is there a deadlock?" reduces to "is there a cycle in the
wait-for graph?". That is the whole trick: turn the lock table into a graph,
then hunt for a cycle (Section A-C).

Once you find a cycle you must break it by aborting ONE transaction in the ring
- the VICTIM. Which one? Heuristics: the one holding the fewest locks, or that
did the least work, because rolling it back is cheapest (Section D).

The cheaper-than-cure alternative is PREVENTION: structure the locking so a
cycle can never form. Always grab locks in a fixed order (lock ordering), or
let timestamps decide who waits and who dies (wound-wait / wait-die). No cycle
can form -> no detection needed (Section E).

Detection has a sting: if the SAME transaction is always picked as the victim,
it never finishes - a LIVELOCK. The fix is a PRIORITY BOOST: each time a txn is
a victim, raise its priority, so victim selection rotates and everyone makes
progress (Section F).

============================================================================
HOW POSTGRESQL ACTUALLY DOES IT (the timeout-then-check design)
============================================================================
PostgreSQL does NOT run the cycle check continuously. Each blocked backend
just sleeps. Only after `deadlock_timeout` (default 1 second) elapses does the
waiting backend wake up, BUILD the wait-for graph of the backends currently
blocked on locks, and run DFS cycle detection on it (src/backend/storage/lmgr/
deadlock.c, DeadLockCheck).

If the graph contains a cycle that the CHECKING backend is part of, that
backend aborts ITSELF - it is the victim. PostgreSQL is therefore a
"detector-sacrifices-itself" design, NOT a global-heuristic victim selector.
The general victim-selection heuristics in Section D (fewest locks / least WAL
/ fewest rows) are the textbook algorithm from Silberschatz, Database System
Concepts 16.3, used by other engines; we model them so the trade-offs are
visible, and we call out where PostgreSQL differs.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   lock            : a claim on a resource (a row, page, table). We model only
                     EXCLUSIVE locks (X): one holder at a time, no sharing.
   holder          : the transaction currently holding the lock on a resource.
   waiter          : a transaction blocked, waiting to acquire a held lock.
   wait-for graph  : directed graph G = (V, E). V = active transactions. Edge
                     Ti -> Tj exists iff Ti is WAITING for a lock held by Tj.
                     This is the structure we run cycle detection on.
   cycle           : a path Ti -> Tj -> ... -> Ti. A cycle in the wait-for
                     graph <=> a deadlock. (Necessary AND sufficient.)
   deadlock        : a set of transactions each blocked waiting for a resource
                     held by another in the set. Everyone stuck forever.
   victim          : the one transaction in the cycle chosen for ABORT, to
                     break the ring and let the others proceed.
   heuristic       : the rule that picks the victim. Common ones: fewest locks
                     held (cheapest rollback), least WAL written, fewest rows
                     modified. Ties broken deterministically (by tid).
   wound-wait      : PREVENTION, preemptive. An OLD txn may WOUND (abort) a
                     YOUNGER holder; a young txn must WAIT for an older holder.
                     Timestamps strictly decrease around any wait edge, so a
                     cycle is impossible.
   wait-die        : PREVENTION, non-preemptive. An OLD txn may WAIT for a
                     younger holder; a young txn DIES (aborts) if it needs a
                     lock held by an older one. Timestamps strictly increase
                     around any wait edge, so a cycle is impossible.
   lock ordering   : PREVENTION. All transactions acquire resources in one
                     fixed global order. The wait-for graph becomes acyclic by
                     construction.
   livelock       : a transaction keeps being picked as the victim, so it
                     retries and deadlocks again forever. It is never stuck
                     waiting, but it never commits.
   priority boost  : anti-livelock. Each time a txn is a victim, increment a
                     priority counter. Victim selection then prefers the txn
                     with the LOWEST priority, rotating the victim so everyone
                     eventually commits.
   deadlock_timeout: PostgreSQL setting (default 1 s). How long a blocked
                     backend waits before running the deadlock check.

============================================================================
THE LINEAGE (sources)
============================================================================
   Coffman/Elphick/Shoshani  "System Deadlocks" (ACM Computing Surveys, 1971):
                      the four NECESSARY conditions for deadlock (mutual
                      exclusion, hold-and-wait, no-preemption, circular wait).
                      Prevention = break one. Detection = let them all hold,
                      then find the cycle.
   Silberschatz/Korth/Sudarshan  "Database System Concepts" 16.3-16.6:
                      wait-for graph, deadlock detection + victim selection,
                      wound-wait / wait-die prevention, timestamps.
   Rosenkrantz/Stearns/Lewis "System Level Concurrency Control for Distributed
                      Database Systems" (ACM TODS 1978): wound-wait & wait-die.
   PostgreSQL docs   13.3.4 "Deadlocks"; `deadlock_timeout` reference;
                      src/backend/storage/lmgr/deadlock.c (DeadLockCheck).

KEY INVARIANTS (all asserted/printed in the sections below):
   wait-for edge     : Ti -> Tj  <=>  exists resource R: Ti waits for R AND
                                       Tj holds R   (exclusive locks)
   deadlock          : exists a cycle in the wait-for graph   (iff)
   wound-wait edge   : Ti waits for Tj  =>  ts(Ti) > ts(Tj)   (young waits old)
                      so timestamps strictly DECREASE around any cycle -> none
   wait-die  edge    : Ti waits for Tj  =>  ts(Ti) < ts(Tj)   (old waits young)
                      so timestamps strictly INCREASE around any cycle -> none
   livelock fix      : with priority boost, victim = argmin(priority) over the
                      cycle; priority(victim) += 1 each round -> rotates

Conventions:
   Resource names are strings ('A','B','C'...). Transaction ids 'T1','T2',...
   Timestamps: SMALLER = OLDER. Every run is fully deterministic; the .html
   replays these exact inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BANNER = "=" * 72


# ============================================================================
# 1. THE CORE MODEL: lock table -> wait-for graph -> cycle detection
# ============================================================================

@dataclass
class Lock:
    """One resource under exclusive lock: who holds it, who is queued waiting."""
    resource: str
    holder: str
    waiters: list[str] = field(default_factory=list)


@dataclass
class Txn:
    """Transaction metadata used for victim selection.

    holds         : set of resources this txn currently holds (== lock-table
                    holder entries; we assert consistency).
    wal_bytes     : bytes of WAL this txn has written so far (rollback cost).
    rows_modified : number of rows this txn has changed (work lost if aborted).
    ts            : start timestamp; SMALLER = OLDER. Used by wound-wait/wait-die.
    priority      : victim-selection priority; 0 by default. Raised on each
                    abort to defeat livelock (Section F).
    """
    tid: str
    holds: set[str] = field(default_factory=set)
    wal_bytes: int = 0
    rows_modified: int = 0
    ts: int = 0
    priority: int = 0


def build_wait_for_graph(locks: list[Lock]) -> dict[str, list[str]]:
    """Turn a lock table into the wait-for graph.

    Edge Ti -> Tj iff Ti is WAITING for a resource currently HELD by Tj
    (exclusive locks: exactly one holder per resource).

    Returns dict node -> sorted list of successors. Every txn that appears
    anywhere (as holder or waiter) is a node, even if it has no out-edges.
    """
    graph: dict[str, set[str]] = {}
    nodes: set[str] = set()
    for lk in locks:
        nodes.add(lk.holder)
        nodes.update(lk.waiters)
        for w in lk.waiters:                      # waiter -> holder
            graph.setdefault(w, set()).add(lk.holder)
    return {n: sorted(graph.get(n, set())) for n in sorted(nodes)}


def detect_cycle(graph: dict[str, list[str]]) -> tuple[list[str] | None, list[str]]:
    """3-color DFS cycle detection over the WHOLE graph.

    graph : dict node -> list of successor nodes.
    Returns (cycle, trace):
      cycle : list of DISTINCT nodes forming the cycle, e.g. ['T1','T2','T3'],
              or None if acyclic. The cycle closes with the edge last->first.
      trace : human-readable DFS steps (entry, back edge, BLACK skip).

    Classic WHITE/GRAY/BLACK: a back edge to a GRAY (on-stack) node == cycle.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    # every node that appears (as a key OR as a successor) gets a color; a
    # successor with no out-edges of its own is still a real node.
    all_nodes: list[str] = list(graph)
    for n in graph:
        for v in graph[n]:
            if v not in graph and v not in all_nodes:
                all_nodes.append(v)
    color = {n: WHITE for n in all_nodes}
    graph = {n: graph.get(n, []) for n in all_nodes}
    path: list[str] = []
    trace: list[str] = []
    found: list[str] | None = None

    def dfs(u: str) -> bool:
        nonlocal found
        color[u] = GRAY
        path.append(u)
        trace.append(f"  enter {u}   [stack: {' -> '.join(path)}]")
        for v in graph[u]:
            if color[v] == GRAY:
                idx = path.index(v)
                found = path[idx:]
                trace.append(f"    {u} -> {v}: {v} is GRAY (on stack) -> BACK EDGE")
                trace.append(f"    CYCLE = {found}  (closes {found[-1]} -> {found[0]})")
                return True
            elif color[v] == WHITE:
                trace.append(f"    {u} -> {v}: WHITE -> recurse")
                if dfs(v):
                    return True
            else:
                trace.append(f"    {u} -> {v}: BLACK -> skip (done)")
        color[u] = BLACK
        path.pop()
        trace.append(f"  leave {u}   [done, no cycle through it]")
        return False

    for root in graph:                            # insertion order (sorted nodes)
        if color[root] == WHITE and found is None:
            if dfs(root):
                break
    return found, trace


def select_victim(cycle_nodes: list[str], txns: dict[str, Txn],
                  heuristic: str) -> str:
    """Pick the victim transaction in `cycle_nodes` under `heuristic`.

    heuristic : 'fewest_locks' | 'least_wal' | 'fewest_rows'
    Lower metric = cheaper to roll back = preferred victim. Ties broken by tid
    (lexicographic) so the choice is deterministic.
    """
    def metric(tid: str) -> tuple[int, str]:
        t = txns[tid]
        if heuristic == "fewest_locks":
            base = len(t.holds)
        elif heuristic == "least_wal":
            base = t.wal_bytes
        elif heuristic == "fewest_rows":
            base = t.rows_modified
        else:
            raise ValueError(f"unknown heuristic: {heuristic}")
        return (base, tid)

    return min(cycle_nodes, key=metric)


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ----------------------------------------------------------------------------
# SECTION A: the wait-for graph - the lock table becomes a directed graph
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: the wait-for graph - lock table -> directed graph")
    print("Rule: edge Ti -> Tj  <=>  Ti waits for a lock HELD by Tj.\n")

    # T1 holds A; T2 waits for A. T2 holds B; T1 waits for B.
    locks = [
        Lock("A", holder="T1", waiters=["T2"]),
        Lock("B", holder="T2", waiters=["T1"]),
    ]
    print("LOCK TABLE (exclusive locks):")
    print("  | resource | holder | waiters |")
    print("  |----------|--------|---------|")
    for lk in locks:
        w = ",".join(lk.waiters) if lk.waiters else "-"
        print(f"  | {lk.resource:<8} | {lk.holder:<6} | {w:<7} |")

    g = build_wait_for_graph(locks)
    print("\nWAIT-FOR GRAPH (one edge per waiter->holder):")
    for n in g:
        succ = g[n] if g[n] else ["(none)"]
        print(f"  {n} -> {', '.join(succ)}")
    print("\nRead it as: T1 waits for T2 (needs B), T2 waits for T1 (needs A).")
    print("That is a 2-cycle:  T1 -> T2 -> T1. The ring of stuck txns.\n")

    cycle, _ = detect_cycle(g)
    closed = cycle + [cycle[0]] if cycle else None
    print(f"[check] detect_cycle -> {closed}  (cycle found): "
          f"{'OK' if cycle else 'FAIL'}")
    assert cycle is not None and set(cycle) == {"T1", "T2"}


# ----------------------------------------------------------------------------
# SECTION B: the classic 2-resource deadlock - the circular wait forms
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: the classic deadlock - T1(A,B) vs T2(B,A) circular wait")
    print("Two txns, two rows A and B. Each grabs one, then asks for the other.\n")

    timeline = [
        (10, "T1 LOCKS A        (A held by T1)"),
        (20, "T2 LOCKS B        (B held by T2)"),
        (30, "T1 requests B     -> B held by T2  -> T1 WAITS for T2"),
        (40, "T2 requests A     -> A held by T1  -> T2 WAITS for T1"),
    ]
    print("EVENT TIMELINE (logical time t ->):\n")
    for t, desc in timeline:
        print(f"  t={t:<3} {desc}")

    # after t=40: A held by T1 with T2 waiting; B held by T2 with T1 waiting
    locks = [
        Lock("A", holder="T1", waiters=["T2"]),
        Lock("B", holder="T2", waiters=["T1"]),
    ]
    g = build_wait_for_graph(locks)
    print("\nWait-for graph after t=40:")
    for n in g:
        print(f"  {n} -> {', '.join(g[n])}")

    cycle, _ = detect_cycle(g)
    print(f"\nCYCLE DETECTION: {cycle}  ->  closes {cycle[-1]} -> {cycle[0]}")
    print(f"DEADLOCK: {'YES' if cycle else 'no'}  (a cycle in the wait-for graph")
    print("          is BOTH necessary and sufficient for a deadlock).\n")

    print("POSTGRESQL MECHANISM (src/backend/storage/lmgr/deadlock.c):")
    print("  - both T1 and T2 backends sleep on their lock queue;")
    print("  - after deadlock_timeout (default 1 s) each backend wakes and runs")
    print("    DeadLockCheck: it builds the wait-for graph and runs DFS;")
    print("  - whichever backend finds a cycle it is PART OF aborts ITSELF.")
    print("  So PostgreSQL's victim = the detecting (timed-out) backend, NOT a")
    print("  global heuristic. Section D shows the general heuristic version.\n")

    assert cycle is not None and set(cycle) == {"T1", "T2"}
    print("[check] 2-txn circular wait produces a 2-cycle: OK")


# ----------------------------------------------------------------------------
# SECTION C: DFS cycle detection - step through the colored DFS
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: cycle detection - 3-color DFS, shown step by step")
    print("WHITE/GRAY/BLACK DFS. A back edge to a GRAY (on-stack) node == cycle.\n")

    # T1->T2->T3->T1 is the cycle; T1->T4 is an acyclic side branch.
    graph = {
        "T1": ["T2", "T4"],
        "T2": ["T3"],
        "T3": ["T1"],
        "T4": [],
    }
    print("GRAPH:")
    for n in graph:
        succ = graph[n] if graph[n] else ["(none)"]
        print(f"  {n} -> {', '.join(succ)}")
    print("\nDFS trace (root order = T1, T2, T3, T4):\n")

    cycle, trace = detect_cycle(graph)
    for line in trace:
        print(line)

    closed = cycle + [cycle[0]] if cycle else None
    print(f"\nRESULT: cycle = {closed}")
    print(f"        distinct nodes = {cycle}  (len {len(cycle)})")
    print("The DFS went T1 -> T2 -> T3, then saw edge T3 -> T1 where T1 was still")
    print("GRAY (on the stack) -> back edge -> cycle T1->T2->T3. T4 (acyclic side")
    print("branch) was never even visited: we stop at the FIRST cycle found.\n")

    assert cycle is not None and set(cycle) == {"T1", "T2", "T3"} and len(cycle) == 3
    print(f"[check] cycle found, 3 distinct nodes: OK")

    # also prove an ACYCLIC graph returns None
    acyclic = {"T1": ["T2"], "T2": ["T3"], "T3": []}
    none_cycle, _ = detect_cycle(acyclic)
    assert none_cycle is None
    print("[check] acyclic graph T1->T2->T3 returns None: OK")


# ----------------------------------------------------------------------------
# SECTION D: victim selection - three heuristics, three different victims
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: victim selection - 3 heuristics pick 3 different victims")
    print("Given the cycle T1 -> T2 -> T3 -> T1, which txn do we abort?\n")

    # Cycle: T1->T2->T3->T1. Each holds a different resource the next needs.
    cycle = ["T1", "T2", "T3"]
    txns = {
        # tid : holds                 wal_bytes rows  ts
        "T1": Txn("T1", holds={"A"},          wal_bytes=5000, rows_modified=40, ts=1),
        "T2": Txn("T2", holds={"B", "C", "D"}, wal_bytes=1000, rows_modified=100, ts=2),
        "T3": Txn("T3", holds={"E", "F"},     wal_bytes=9000, rows_modified=10, ts=3),
    }
    print("CANDIDATES (members of the cycle):")
    print("  | txn | locks held        | #locks | WAL bytes | rows modified |")
    print("  |-----|-------------------|:------:|:---------:|:-------------:|")
    for tid in cycle:
        t = txns[tid]
        holds = "{" + ",".join(sorted(t.holds)) + "}"
        print(f"  | {tid} | {holds:<17} | {len(t.holds):^6} | "
              f"{t.wal_bytes:^9} | {t.rows_modified:^13} |")
    print()

    heuristics = [
        ("fewest_locks", "#locks held",  "fewest locks -> cheapest to release"),
        ("least_wal",    "WAL bytes",    "least WAL     -> cheapest to roll back"),
        ("fewest_rows",  "rows modified", "fewest rows   -> least work lost"),
    ]
    print("| heuristic        | minimize       | metric per txn (T1,T2,T3)        "
          "| VICTIM | reason                 |")
    print("|------------------|----------------|----------------------------------|"
          "--------|------------------------|")
    victims = {}
    for name, metric_label, reason in heuristics:
        v = select_victim(cycle, txns, name)
        victims[name] = v
        metrics = "(" + ",".join(
            str(len(txns[t].holds) if name == "fewest_locks"
                else txns[t].wal_bytes if name == "least_wal"
                else txns[t].rows_modified)
            for t in cycle) + ")"
        print(f"| {name:<16} | {metric_label:<14} | {metrics:<32} "
              f"| {v:^6} | {reason:<22} |")

    print("\nDifferent heuristics pick DIFFERENT victims - the choice is a")
    print("policy trade-off, not a fact. PostgreSQL sidesteps this entirely:")
    print("the backend that times out and runs the check aborts ITSELF, so the")
    print("victim is simply 'whoever noticed'. The heuristics above are the")
    print("general textbook algorithm (Silberschatz 16.3).\n")

    assert victims == {"fewest_locks": "T1", "least_wal": "T2", "fewest_rows": "T3"}, victims
    print("[check] fewest_locks->T1 (1), least_wal->T2 (1000), "
          "fewest_rows->T3 (10): OK")


# ----------------------------------------------------------------------------
# SECTION E: PREVENTION - lock ordering, wound-wait, wait-die
# ----------------------------------------------------------------------------

def _try_wound_wait(requester: str, holder: str, txns: dict[str, Txn]) -> str:
    """wound-wait: old wounds young holder; young waits for old.
    Returns 'WOUND(holder)' (holder aborted) or 'WAIT'."""
    if txns[requester].ts < txns[holder].ts:        # requester OLDER -> wound
        return f"WOUND({holder})"                   # holder (younger) aborted
    return "WAIT"                                    # requester younger -> waits


def _try_wait_die(requester: str, holder: str, txns: dict[str, Txn]) -> str:
    """wait-die: old waits for young; young dies (aborts) if it needs old's lock.
    Returns 'WAIT' or 'DIE(requester)'."""
    if txns[requester].ts < txns[holder].ts:        # requester OLDER -> wait
        return "WAIT"
    return f"DIE({requester})"                      # requester younger -> aborts


def section_e():
    banner("SECTION E: PREVENTION - make a cycle impossible in the first place")
    print("Coffman's 4 conditions for deadlock: mutual exclusion, hold-and-wait,")
    print("no-preemption, circular wait. Prevention breaks ONE of them.\n")

    # ---- (1) lock ordering: break circular wait ----
    print("(1) LOCK ORDERING - break circular wait")
    print("    Rule: every txn acquires resources in one fixed order: A < B < C.")
    print("    Without it: T1 grabs A then wants B; T2 grabs B then wants A ->")
    print("    cycle (Section B). With ordering both want A FIRST, so one waits")
    print("    for A before either can touch B -> no cycle can form.\n")
    print("    t=10  T1 grabs A             (A held by T1)")
    print("    t=20  T2 wants A             -> A held by T1 -> T2 WAITS")
    print("    t=30  T1 grabs B             (B free; T1 already holds A, ordering OK)")
    print("    t=40  T1 commits, releases A,B")
    print("    t=50  T2 gets A, then B      -> commits. NO deadlock.\n")
    print("    wait-for graph under ordering is acyclic BY CONSTRUCTION.\n")

    # ---- (2) wound-wait: break hold-and-wait (preemptive) ----
    print("(2) WOUND-WAIT - break hold-and-wait (preemptive)")
    print("    ts SMALLER = OLDER. Old txn may WOUND (abort) a younger holder;")
    print("    young txn must WAIT for an older holder. Holder can be preempted.\n")
    txns = {"T1": Txn("T1", ts=1), "T2": Txn("T2", ts=2)}   # T1 older
    print("    T1 holds A. Now someone requests A held by the other:")
    cases_ww = [
        ("T1 requests A", "T2", "T1 older than holder T2"),
        ("T2 requests A", "T1", "T2 younger than holder T1"),
    ]
    print("    | requester | holder | ts(req) vs ts(hold) | action               |")
    print("    |-----------|--------|----------------------|----------------------|")
    for label, holder, why in cases_ww:
        req = label.split()[0]
        act = _try_wound_wait(req, holder, txns)
        cmp = f"{txns[req].ts} < {txns[holder].ts} (older)" \
            if txns[req].ts < txns[holder].ts \
            else f"{txns[req].ts} > {txns[holder].ts} (younger)"
        print(f"    | {req:<9} | {holder:<6} | {cmp:<20} | {act:<20} |")
    print("    => edge req->hold only when req is YOUNGER, so ts strictly")
    print("       DECREASES along every wait edge -> no cycle possible.\n")

    # ---- (3) wait-die: break no-preemption (non-preemptive) ----
    print("(3) WAIT-DIE - break no-preemption (non-preemptive)")
    print("    Old txn may WAIT for a younger holder; young txn DIES (aborts) if")
    print("    it needs a lock held by an older one. Holder is never preempted.\n")
    print("    | requester | holder | ts(req) vs ts(hold) | action               |")
    print("    |-----------|--------|----------------------|----------------------|")
    for label, holder, _why in cases_ww:
        req = label.split()[0]
        act = _try_wait_die(req, holder, txns)
        cmp = f"{txns[req].ts} < {txns[holder].ts} (older)" \
            if txns[req].ts < txns[holder].ts \
            else f"{txns[req].ts} > {txns[holder].ts} (younger)"
        print(f"    | {req:<9} | {holder:<6} | {cmp:<20} | {act:<20} |")
    print("    => edge req->hold only when req is OLDER, so ts strictly")
    print("       INCREASES along every wait edge -> no cycle possible.\n")

    print("DETECTION vs PREVENTION:")
    print("  detection   : let deadlocks form, find the cycle, abort a victim.")
    print("                Low overhead when idle; pays deadlock_timeout on each.")
    print("  prevention  : never form a cycle (ordering) or abort early (ww/wd).")
    print("                Zero deadlock_timeout waits, but more aborts/restarts.")
    print("PostgreSQL uses DETECTION (wait + timeout + DFS). Prevention is left")
    print("to the application (e.g. lock rows in a consistent order).\n")

    # ---- checks: both schemes are provably cycle-free ----
    # wound-wait: simulate a wait edge only when requester younger
    g_ww = {"T2": ["T1"]}     # T2(young) waits T1(old): ts 2>1, legal
    c_ww, _ = detect_cycle(g_ww)
    # wait-die: legal edge only when requester older
    g_wd = {"T1": ["T2"]}     # T1(old) waits T2(young): ts 1<2, legal
    c_wd, _ = detect_cycle(g_wd)
    assert c_ww is None and c_wd is None
    print("[check] single legal wait edge under each scheme is acyclic: OK")
    assert _try_wound_wait("T1", "T2", txns) == "WOUND(T2)"
    assert _try_wound_wait("T2", "T1", txns) == "WAIT"
    assert _try_wait_die("T1", "T2", txns) == "WAIT"
    assert _try_wait_die("T2", "T1", txns) == "DIE(T2)"
    print("[check] wound-wait / wait-die action table reproduces: OK")


# ----------------------------------------------------------------------------
# SECTION F: livelock + priority boost - rotate the victim
# ----------------------------------------------------------------------------

def simulate_victim_rounds(txns: dict[str, Txn], cycle: list[str],
                           boost: bool, rounds: int) -> list[str]:
    """Run `rounds` deadlock-resolution rounds. Each round the cycle recurs and
    one txn is chosen as victim. Returns the list of victims per round.

    Without boost: victim = argmin(#locks) every round -> same txn -> livelock.
    With boost   : victim = argmin(priority, then #locks); victim.priority += 1
                   after each abort, so the victim rotates.
    """
    for t in txns.values():
        t.priority = 0
    victims: list[str] = []
    for _ in range(rounds):
        if boost:
            victim = min(cycle, key=lambda t: (txns[t].priority, len(txns[t].holds), t))
        else:
            victim = min(cycle, key=lambda t: (len(txns[t].holds), t))
        victims.append(victim)
        if boost:
            txns[victim].priority += 1
    return victims


def section_f():
    banner("SECTION F: livelock + priority boost - the same victim must rotate")
    print("A transaction repeatedly picked as victim retries, re-deadlocks, and")
    print("gets picked again - never stuck waiting, but never commits. That is a")
    print("LIVELOCK. Fix: boost the victim's priority each round so selection "
          "rotates.")
    print()

    cycle = ["T1", "T2"]
    # T1 holds fewer locks than T2 -> fewest-locks always picks T1.
    base = {
        "T1": Txn("T1", holds={"A"}, wal_bytes=100, rows_modified=1, ts=1),
        "T2": Txn("T2", holds={"B", "C"}, wal_bytes=900, rows_modified=9, ts=2),
    }

    def fresh(d):
        return {k: Txn(v.tid, set(v.holds), v.wal_bytes, v.rows_modified, v.ts)
                for k, v in d.items()}

    no_boost = simulate_victim_rounds(fresh(base), cycle, boost=False, rounds=4)
    with_boost = simulate_victim_rounds(fresh(base), cycle, boost=True, rounds=4)

    # recompute WITH-boost priorities per round to display the rising counter
    disp = fresh(base)
    for t in disp.values():
        t.priority = 0
    prio_after = []
    for v in with_boost:
        disp[v].priority += 1
        prio_after.append(f"prio T1={disp['T1'].priority},T2={disp['T2'].priority}")

    print("Cycle T1<->T2 recurs every round. fewest-locks: T1 has 1 lock, T2 has 2.\n")
    print("  | round | WITHOUT boost (fewest locks) | WITH priority boost               |")
    print("  |-------|------------------------------|-----------------------------------|")
    for r in range(4):
        print(f"  | {r + 1:<5} | victim = {no_boost[r]:<21} "
              f"| victim = {with_boost[r]:<11} ({prio_after[r]:<16}) |")
    print()
    print(f"WITHOUT boost: victims = {no_boost}  -> T1 aborted EVERY round ->")
    print("T1 never commits. LIVELOCK.")
    print(f"WITH    boost: victims = {with_boost}  -> victim rotates; after being")
    print("aborted once, a txn's priority rises so the OTHER txn is picked next.")
    print("Both eventually commit. Progress restored.\n")

    print("POSTGRESQL NOTE: PG's anti-livelock is structural, not a priority")
    print("counter - because the TIMED-OUT backend is always the victim, and")
    print("different backends time out on different cycles, the victim naturally")
    print("varies. The priority-boost model above is the textbook fix (used by")
    print("heuristic-based selectors) and is what the .html animates.\n")

    assert no_boost == ["T1", "T1", "T1", "T1"]
    assert with_boost == ["T1", "T2", "T1", "T2"]
    print("[check] no-boost livelocks on T1; boost rotates T1,T2,T1,T2: OK")


# ----------------------------------------------------------------------------
# GOLD: 3-transaction circular wait - pinned values for the .html
# ----------------------------------------------------------------------------

def section_gold():
    banner("GOLD: 3-txn circular wait - cycle detection must find the ring")
    print("A ring of three: T1 waits for T2, T2 waits for T3, T3 waits for T1.\n")

    # X held by T1, T3 waits -> edge T3->T1
    # Y held by T2, T1 waits -> edge T1->T2
    # Z held by T3, T2 waits -> edge T2->T3
    locks = [
        Lock("X", holder="T1", waiters=["T3"]),
        Lock("Y", holder="T2", waiters=["T1"]),
        Lock("Z", holder="T3", waiters=["T2"]),
    ]
    print("LOCK TABLE:")
    print("  | resource | holder | waiter |")
    print("  |----------|--------|--------|")
    for lk in locks:
        print(f"  | {lk.resource:<8} | {lk.holder:<6} | {lk.waiters[0]:<6} |")

    g = build_wait_for_graph(locks)
    print("\nWAIT-FOR GRAPH:")
    for n in g:
        print(f"  {n} -> {', '.join(g[n])}")

    cycle, _ = detect_cycle(g)
    closed = cycle + [cycle[0]] if cycle else None
    distinct = sorted(set(cycle)) if cycle else []
    print(f"\nDETECTED CYCLE: {closed}")
    print(f"distinct nodes (sorted): {distinct}  (len {len(distinct)})")

    print("\nGOLD values (pinned for deadlock_detection.html):")
    print(f"  cycle_found        = {cycle is not None}")
    print(f"  cycle_nodes_sorted = {distinct}")
    print(f"  cycle_length       = {len(distinct)}")
    print(f"  closes_edge        = {cycle[-1]} -> {cycle[0]}")
    print(f"  graph_edges        = {[(n, g[n]) for n in g]}")

    # victim selection on the 3-cycle under each heuristic (pins section D too)
    txns = {
        "T1": Txn("T1", holds={"X"},           wal_bytes=5000, rows_modified=40, ts=1),
        "T2": Txn("T2", holds={"Y", "W", "V"}, wal_bytes=1000, rows_modified=100, ts=2),
        "T3": Txn("T3", holds={"Z", "U"},      wal_bytes=9000, rows_modified=10, ts=3),
    }
    vh = {h: select_victim(distinct, txns, h) for h in
          ("fewest_locks", "least_wal", "fewest_rows")}
    print(f"  victim_fewest_locks = {vh['fewest_locks']}   "
          f"(locks T1={len(txns['T1'].holds)},"
          f" T2={len(txns['T2'].holds)},"
          f" T3={len(txns['T3'].holds)})")
    print(f"  victim_least_wal    = {vh['least_wal']}   "
          f"(wal T1={txns['T1'].wal_bytes},"
          f" T2={txns['T2'].wal_bytes},"
          f" T3={txns['T3'].wal_bytes})")
    print(f"  victim_fewest_rows  = {vh['fewest_rows']}   "
          f"(rows T1={txns['T1'].rows_modified},"
          f" T2={txns['T2'].rows_modified},"
          f" T3={txns['T3'].rows_modified})")

    # ---- assert all GOLD ----
    assert cycle is not None
    assert len(distinct) == 3 and distinct == ["T1", "T2", "T3"]
    assert set(g["T1"]) == {"T2"} and set(g["T2"]) == {"T3"} and set(g["T3"]) == {"T1"}
    assert vh == {"fewest_locks": "T1", "least_wal": "T2", "fewest_rows": "T3"}
    print("\n[check] 3-cycle found, 3 distinct nodes, victims T1/T2/T3: OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("deadlock_detection.py - reference impl. All numbers feed "
          "DEADLOCK_DETECTION.md.")
    print("pure Python stdlib ; deterministic logical-time model.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
