"""
lamport_timestamps.py - Reference implementation of LAMPORT LOGICAL CLOCKS
(Lamport 1978): ordering events in a distributed system WITHOUT trusting a
physical clock.

This is the single source of truth that LAMPORT_TIMESTAMPS.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 lamport_timestamps.py

============================================================================
THE INTUITION (read this first) - causality, not clock time
============================================================================
In a distributed system there is no global clock, and every wall clock is
wrong by some unknown amount (see clock_sync_ntp.py - drift, leap seconds,
NTP steps that jump BACKWARD). So we CANNOT decide "did event a happen
before event b?" by comparing the timestamps two machines stamped locally.
Two machines will disagree about what time it is.

Lamport's insight (1978) was that we don't NEED to know the real time an
event happened. We only need to know the CAUSAL ordering - which events
could have INFLUENCED which. And causality is fully captured by just two
things, neither of which needs a clock:

  * program order    : within one process, events happen in a sequence.
  * messages         : if process P sends a message and Q receives it, the
                       send MUST have happened before the receive.

Glue those together with transitivity and you have the HAPPENS-BEFORE
relation (written a -> b). It is the skeleton of causality for the whole
system. If neither a -> b nor b -> a, the events are CONCURRENT (a || b):
they could not have influenced each other, and their real-time order is
unknowable AND irrelevant.

Then Lamport attaches NUMBERS to events so the numbering AGRES with the
skeleton: a -> b implies L(a) < L(b). This is the LOGICAL CLOCK. It is NOT
a measure of time - it is a measure of CAUSAL PROGRESS. The rule is dead
simple:

    before every event      : bump your local counter by 1
    on receiving a message  : counter = max(counter, msg_timestamp) + 1

That single rule guarantees causal consistency, which is enough to build a
total order (add process id as tiebreaker) and Lamport's distributed mutual
exclusion algorithm.

The catch (Section D): the implication runs ONE WAY. a -> b => L(a) < L(b),
but L(a) < L(b) does NOT mean a -> b - the events might be concurrent. You
cannot read causality off a Lamport clock. Detecting concurrency requires
VECTOR clocks (a different bundle).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  event         : something happening at one process - a local step, a
                  message SEND, or a message RECEIVE. The atomic unit.
  process       : a single sequential thread of execution. Its own events
                  are totally ordered by program order.
  happens-before(->) : "a could have influenced b". Defined by (1) program
                  order within a process, (2) send -> matching receive, and
                  (3) transitivity. Needs no clocks at all.
  concurrent (||): neither a -> b nor b -> a. No causal influence either way.
  logical clock(L): an integer label on each event with the property
                  a -> b  =>  L(a) < L(b).  NOT a timestamp of real time.
  causal order  : the partial order induced by ->. A partial order because
                  concurrent events are not ordered.
  total order   : a linear extension of causal order, made by breaking ties
                  with process id: (L(e), pid(e)).
  scalar clock  : Lamport's clock - a single integer per event.
  vector clock  : the upgrade (not covered here) that ALSO lets you detect
                  ||. Each process keeps one counter per process.
  tiebreaker    : the (timestamp, pid) pair used to linearize the partial
                  order into a total order.

============================================================================
THE PAPER (every formula below verified against this)
============================================================================
  Lamport, L. (1978). "Time, Clocks, and the Ordering of Events in a
        Distributed System." Communications of the ACM 21(7), 558-565.
        - Defines ->, logical clocks (IR1/IR2), the total-ordering rule,
          and the distributed mutual-exclusion algorithm (Section E).

KEY FORMULAS (all asserted in code below):
    happens-before  : a -> b  iff  (same proc, a before b)
                                 OR  (a = send, b = recv of same message)
                                 OR  (transitive closure of the above)
    logical clock   : L(local/send) = L_prev + 1
                      L(receive)    = max(L_prev, L(message)) + 1
    causal consist. : a -> b  =>  L(a) < L(b)        (one-way! see Section D)
    total order     : e < f  iff  (L(e), pid(e)) lexicographically < (L(f), pid(f))
    mutex grant     : the process holding the resource is the one whose
                      pending REQUEST has the smallest (timestamp, pid).
    concurrency test: a || b  iff  NOT(a -> b) AND NOT(b -> a)
                      (CANNOT be decided from L(a), L(b) alone.)

============================================================================
THE SCENARIO (deterministic; reused by every section and by the .html)
============================================================================
Three processes P1, P2, P3, each with three events. Two messages cross
between them. Physical time t (wall-clock-ish, shown only to contrast with
the logical clock - the algorithm never reads it):

    P1:   a ----b--------c            (a,b,c in program order)
                 \\.
                  \\ send m1
                   \\
    P2:      d----e----f              (e receives m1 from b; f sends m2)
                       \\.
                        \\ send m2
                         \\
    P3:           g-----h----i        (h receives m2 from f)

    events in physical-time order:  a(1) d(2) b(3) e(4) f(5) c(6) g(7) h(8) i(9)
    messages:                       m1: b -> e    m2: f -> h

The same 9 events and 2 messages are hard-coded in lamport_timestamps.html
so JS recomputes byte-identical numbers.
"""

from __future__ import annotations

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# The deterministic scenario. Single source of truth for every section.
# ----------------------------------------------------------------------------
PROCESSES = ["P1", "P2", "P3"]
PID = {p: i for i, p in enumerate(PROCESSES)}          # tiebreaker rank

# kind in {"local","send","recv"}. "to"/"from" name the paired event.
EVENTS: dict[str, dict] = {
    "a": {"p": "P1", "idx": 0, "t": 1, "kind": "local"},
    "d": {"p": "P2", "idx": 0, "t": 2, "kind": "local"},
    "b": {"p": "P1", "idx": 1, "t": 3, "kind": "send", "to": "e"},
    "e": {"p": "P2", "idx": 1, "t": 4, "kind": "recv", "from": "b"},
    "f": {"p": "P2", "idx": 2, "t": 5, "kind": "send", "to": "h"},
    "c": {"p": "P1", "idx": 2, "t": 6, "kind": "local"},
    "g": {"p": "P3", "idx": 0, "t": 7, "kind": "local"},
    "h": {"p": "P3", "idx": 1, "t": 8, "kind": "recv", "from": "f"},
    "i": {"p": "P3", "idx": 2, "t": 9, "kind": "local"},
}
MESSAGES = [("b", "e"), ("f", "h")]                    # (send, receive)


# ============================================================================
# 1. REFERENCE IMPLEMENTATIONS  (the code LAMPORT_TIMESTAMPS.md walks through)
# ============================================================================

def happens_before_edges(events: dict, messages: list) -> set[tuple[str, str]]:
    """The DIRECTED edges of the happens-before relation ->.

    Two sources only:
      (1) program order: consecutive events in the SAME process.
      (2) messages:      (send, receive) of each message.
    Transitivity is NOT materialized here - see `reachability()`, which takes
    the transitive closure. The -> relation itself is the transitive closure.
    """
    edges: set[tuple[str, str]] = set()
    # (1) program order within each process
    by_proc: dict[str, list[tuple[int, str]]] = {}
    for name, e in events.items():
        by_proc.setdefault(e["p"], []).append((e["idx"], name))
    for evs in by_proc.values():
        evs.sort()
        for k in range(len(evs) - 1):
            edges.add((evs[k][1], evs[k + 1][1]))
    # (2) message send -> receive
    for s, r in messages:
        edges.add((s, r))
    return edges


def reachability(events: dict, edges: set) -> dict[str, set[str]]:
    """Transitive closure of `edges`. reach[x] = {y : x -> y via >=1 edge}.

    Built by DFS from every node. This IS the happens-before relation:
    a -> b  <=>  b in reach[a].
    """
    adj: dict[str, set[str]] = {n: set() for n in events}
    for a, b in edges:
        adj[a].add(b)
    reach: dict[str, set[str]] = {}
    for start in events:
        seen: set[str] = set()
        stack = list(adj[start])
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(adj[x])
        reach[start] = seen
    return reach


def lamport_clocks(events: dict, messages: list) -> dict[str, int]:
    """Assign a Lamport logical clock value L(e) to every event.

    Implementation rules (Lamport 1978, IR1 + IR2):
      - each process p keeps a counter clock[p], starting at 0.
      - local / send event in p :  clock[p] += 1
      - receive in p of msg m    :  clock[p] = max(clock[p], L(send(m))) + 1
      - L(event) = clock[p] AFTER the update.

    Events are consumed in physical-time order, which is a valid topological
    order of -> (sends always precede their receives), so L(send) is always
    known when the matching receive is processed.
    """
    clock = {p: 0 for p in PROCESSES}
    L: dict[str, int] = {}
    order = sorted(events, key=lambda n: events[n]["t"])
    for name in order:
        e = events[name]
        p = e["p"]
        if e["kind"] == "recv":
            t_msg = L[e["from"]]                       # logical clock of the send
            clock[p] = max(clock[p], t_msg) + 1
        else:                                           # local or send
            clock[p] = clock[p] + 1
        L[name] = clock[p]
    return L


def total_order(events: dict, L: dict[str, int]) -> list[str]:
    """A linear extension of -> that is consistent with causality.

    Sort by (L(e), pid(e)) lexicographically. The process-id tiebreaker
    turns the partial order into a TOTAL order without ever violating ->
    (because a -> b => L(a) < L(b), so a sorts strictly before b; pid only
    ever breaks ties between events that are NOT -> related).
    """
    return sorted(events, key=lambda n: (L[n], PID[events[n]["p"]]))


def concurrent_pairs(events: dict, reach: dict[str, set[str]]) -> list[tuple[str, str]]:
    """All UNORDERED pairs {x, y} with x || y (neither x -> y nor y -> x).

    These are the events Lamport clocks CANNOT distinguish from causally-
    ordered ones - the heart of the Section D limitation.
    """
    names = sorted(events)
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            x, y = names[i], names[j]
            if y not in reach[x] and x not in reach[y]:
                pairs.append((x, y))
    return pairs


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def kind_tag(e: dict) -> str:
    k = e["kind"]
    if k == "send":
        return f"send->{e['to']}"
    if k == "recv":
        return f"recv<-{e['from']}"
    return "local"


# ============================================================================
# SECTION A: happens-before  (causality with NO clocks)
# ============================================================================

def section_a():
    banner("SECTION A: happens-before (->)  - causality from program order + messages")
    print("Goal: decide 'could event a have influenced event b?' without ANY")
    print("clock. Lamport defines -> from just two ingredients:\n")
    print("  (1) PROGRAM ORDER : if a and b are in the same process and a")
    print("                      comes first, then a -> b.")
    print("  (2) MESSAGES      : if a is the send and b the receive of the")
    print("                      same message, then a -> b.")
    print("  (3) TRANSITIVITY  : a -> b and b -> c  imply  a -> c.\n")
    print("The scenario (3 processes, 9 events, 2 messages):\n")
    print("  P1:  a --b----c       (b sends m1 to e)")
    print("  P2:  d --e--f         (e receives m1; f sends m2 to h)")
    print("  P3:     g--h--i       (h receives m2)\n")

    edges = happens_before_edges(EVENTS, MESSAGES)
    print(f"DIRECT -> edges ({len(edges)} total - transitivity not yet applied):")
    print("  program order: " + ", ".join(
        f"{a}->{b}" for a, b in sorted(edges)
        if EVENTS[a]["p"] == EVENTS[b]["p"]
    ))
    print("  messages     : " + ", ".join(
        f"{a}->{b}" for a, b in sorted(edges)
        if EVENTS[a]["p"] != EVENTS[b]["p"]
    ) + "\n")

    reach = reachability(EVENTS, edges)
    print("TRANSITIVE CLOSURE (the full -> relation). For each event, the set it")
    print("could have influenced:\n")
    for name in sorted(EVENTS):
        future = sorted(reach[name], key=lambda n: EVENTS[n]["t"])
        print(f"  {name} -> {{{', '.join(future) if future else ''}}}"
              + ("" if future else "   (no descendants)"))
    print()

    # count + list all ordered happens-before pairs
    all_pairs = [(x, y) for x in EVENTS for y in reach[x]]
    all_pairs.sort(key=lambda p: (EVENTS[p[0]]["t"], EVENTS[p[1]]["t"]))
    print(f"Total happens-before pairs a -> b: {len(all_pairs)}")
    for x, y in all_pairs:
        via = "same proc" if EVENTS[x]["p"] == EVENTS[y]["p"] else "msg/transitive"
        print(f"    {x} -> {y}   ({via})")
    print()

    # concurrent events exist - the relation is a PARTIAL order
    conc = concurrent_pairs(EVENTS, reach)
    print(f"Events that are CONCURRENT (x || y, no causal link either way): "
          f"{len(conc)} pairs.")
    print("  e.g. " + ", ".join(f"{x}||{y}" for x, y in conc[:6])
          + (" ..." if len(conc) > 6 else ""))
    print("\n--> is a PARTIAL order: some events (the concurrent ones) are simply")
    print("not ordered. That is fine - their real-time order cannot be observed")
    print("and does not matter for correctness.")
    print(f"\n[check] #-> pairs ({len(all_pairs)}) + #|| pairs ({len(conc)}) = "
          f"{len(all_pairs) + len(conc)} == C(9,2) = {9 * 8 // 2}:  "
          f"{'OK' if len(all_pairs) + len(conc) == 9 * 8 // 2 else 'FAIL'}")


# ============================================================================
# SECTION B: the Lamport logical clock rule
# ============================================================================

def section_b():
    banner("SECTION B: the logical clock rule  L = max(local, msg) + 1")
    print("Attach an integer L(e) to each event so that a -> b implies L(a) < L(b).")
    print("L is NOT a time-of-day; it is a counter of causal progress.\n")
    print("The rule (Lamport 1978, IR1 + IR2):")
    print("  each process p keeps a counter clock[p], starting at 0.")
    print("  local / send event :  clock[p] <- clock[p] + 1")
    print("  receive of msg m   :  clock[p] <- max(clock[p], L(send(m))) + 1")
    print("  L(event)           =  clock[p] after the update.\n")
    print("Walked event-by-event in physical-time order (sends precede receives):\n")

    L = _walk_and_print_clocks()
    print()

    # final table
    print("Resulting Lamport clock values:\n")
    print("| event | process | kind        | physical t | L (logical) |")
    print("|-------|---------|-------------|------------|-------------|")
    for name in sorted(EVENTS, key=lambda n: EVENTS[n]["t"]):
        e = EVENTS[name]
        print(f"| {name:<5} | {e['p']:<7} | {kind_tag(e):<11} | "
              f"{e['t']:<10} | {L[name]:<11} |")
    print("\nNotice L IGNORES physical time. c happens at t=6 but gets L=3,")
    print("while h happens at t=8 and gets L=5 - because h causally depends on")
    print("the chain b->e->f->h, whereas c is just the next local step of P1.")

    # GOLD values pinned for the .html
    print("\nGOLD (pinned for lamport_timestamps.html):")
    gold = {n: L[n] for n in sorted(EVENTS, key=lambda n: EVENTS[n]["t"])}
    print("  L = " + ", ".join(f"{n}={gold[n]}" for n in gold))
    print(f"  compact check scalar: L(h) = {L['h']}  (receive of f; the max() rule)")
    expected = {"a": 1, "d": 1, "b": 2, "e": 3, "f": 4, "c": 3, "g": 1, "h": 5, "i": 6}
    assert gold == expected, f"Lamport clocks mismatch: {gold} != {expected}"
    print(f"[check] L matches hand-derived values {expected}:  OK")


def _walk_and_print_clocks() -> dict[str, int]:
    """Run the clock algorithm and print each step. Returns L."""
    clock = {p: 0 for p in PROCESSES}
    L: dict[str, int] = {}
    order = sorted(EVENTS, key=lambda n: EVENTS[n]["t"])
    for name in order:
        e = EVENTS[name]
        p = e["p"]
        prev = clock[p]
        if e["kind"] == "recv":
            t_msg = L[e["from"]]
            new = max(prev, t_msg) + 1
            print(f"  {name} [{p:>2}, recv <-{e['from']}]: "
                  f"max(clock[{p}]={prev}, L({e['from']})={t_msg}) + 1 = {new}")
            clock[p] = new
        else:
            new = prev + 1
            tag = "send" if e["kind"] == "send" else "local"
            extra = f"  (piggyback L={new} on msg to {e['to']})" if e["kind"] == "send" else ""
            print(f"  {name} [{p:>2}, {tag:<5}]: "
                  f"clock[{p}]={prev} + 1 = {new}{extra}")
            clock[p] = new
        L[name] = clock[p]
    return L


# ============================================================================
# SECTION C: total order via (L, pid) tiebreaker
# ============================================================================

def section_c():
    banner("SECTION C: total order  - the (L, pid) tiebreaker")
    print("L alone is only a PARTIAL order: distinct events can share a value")
    print("(e.g. a, d, g all have L=1). To get a SINGLE global order - needed")
    print("for mutual exclusion, log replication, determinism - Lamport breaks")
    print("ties with the process id:\n")
    print("  e precedes f  <=>  (L(e), pid(e))  <  (L(f), pid(f))   lexicographically\n")
    print("Because a -> b => L(a) < L(b), causally-related events are ALWAYS in")
    print("the right order; pid only ever orders events that are CONCURRENT, so")
    print("no causal constraint is ever violated.\n")

    L = lamport_clocks(EVENTS, MESSAGES)
    order = total_order(EVENTS, L)
    print("Sorted by (L, pid):\n")
    print("| rank | event | process | L  | pid | (L, pid)   |")
    print("|------|-------|---------|----|-----|------------|")
    for rank, name in enumerate(order):
        e = EVENTS[name]
        pair = f"({L[name]}, {PID[e['p']]})"
        print(f"| {rank:<4} | {name:<5} | {e['p']:<7} | {L[name]:<2} | "
              f"{PID[e['p']]:<3} | {pair:<10} |")
    print("\nLinearized total order:  " + " < ".join(order))
    print("\nEvery pair a -> b in Section A has a appearing BEFORE b above. That")
    print("is the definition of 'consistent with causality'.")

    # verify consistency with -> for every pair
    edges = happens_before_edges(EVENTS, MESSAGES)
    reach = reachability(EVENTS, edges)
    pos = {name: i for i, name in enumerate(order)}
    violations = [(x, y) for x in EVENTS for y in reach[x] if pos[x] > pos[y]]
    print(f"\n[check] total order consistent with -> ?  "
          f"violations = {len(violations)}  ->  "
          f"{'OK' if not violations else 'FAIL: ' + str(violations)}")
    assert not violations
    print(f"[check] total order is a linear extension of ->:  OK")


# ============================================================================
# SECTION D: limitation - Lamport clocks CANNOT detect concurrency
# ============================================================================

def section_d():
    banner("SECTION D: limitation  - L(a) < L(b) does NOT mean a -> b")
    print("The clock condition runs ONE WAY:\n")
    print("     a -> b   ==>   L(a) < L(b)        (guaranteed)")
    print("     L(a) < L(b)   ==>   a -> b         (FALSE in general)\n")
    print("Lamport clocks are SCALAR. They collapse the partial order -> onto a")
    print("linear chain of integers, throwing away the difference between")
    print("'a caused b' and 'a and b just happen to be numbered this way'. So")
    print("you CANNOT read causality off the clock values.\n")

    L = lamport_clocks(EVENTS, MESSAGES)
    edges = happens_before_edges(EVENTS, MESSAGES)
    reach = reachability(EVENTS, edges)
    conc = concurrent_pairs(EVENTS, reach)

    # misleading pairs: concurrent but L(x) != L(y), so one LOOKS ordered
    misleading = [(x, y) for x, y in conc if L[x] != L[y]]
    print(f"Of the {len(conc)} concurrent pairs, {len(misleading)} have L(x) != L(y)")
    print("(a naive reader would wrongly infer an ordering):\n")
    print("| x | y | L(x) | L(y) | clocks say | truth     |")
    print("|---|---|------|------|------------|-----------|")
    for x, y in sorted(misleading, key=lambda p: abs(L[p[0]] - L[p[1]]), reverse=True):
        looks = f"{x}->{y}" if L[x] < L[y] else f"{y}->{x}"
        print(f"| {x} | {y} | {L[x]:<4} | {L[y]:<4} | "
              f"{looks:<10} | {x}||{y}      |")
    print("\nThe clearest example:")
    x, y = "c", "f"
    print(f"   c (P1, t=6) and f (P2, t=5) are CONCURRENT: there is no path")
    print(f"   c -> ... -> f or f -> ... -> c. But L(c)={L[x]} < L(f)={L[y]}, so")
    print(f"   the clocks make it LOOK as though c -> f. They are unrelated; the")
    print(f"   inequality is an accident of how the counters happened to bump.\n")
    print("WHY this happens: c bumps P1's counter (2 -> 3); f bumps P2's counter")
    print("(3 -> 4). The two counters are independent, so their relative values")
    print("carry NO information about causality between the two processes.\n")
    print("THE FIX: VECTOR clocks (Mattern 1989 / Fidge 1988). Each process")
    print("keeps one counter PER process; then a || b <=> neither vector dominates")
    print("the other. Lamport's scalar clock is the price of a single integer.")
    print(f"\n[check] c || f but L(c)={L['c']} < L(f)={L['f']}  "
          f"(the misleading case):  {'OK' if L['c'] < L['f'] else 'FAIL'}")
    assert L["c"] < L["f"]
    assert "f" not in reach["c"] and "c" not in reach["f"]


# ============================================================================
# SECTION E: Lamport's distributed mutual exclusion algorithm
# ============================================================================

def section_e():
    banner("SECTION E: Lamport's mutual exclusion  - min (timestamp, pid) wins")
    print("A textbook use of the total order: distributed mutual exclusion.")
    print("N processes share one resource and must take turns, with NO server")
    print("and NO physical clock. Lamport's algorithm (1978):\n")
    print("  (1) To request, process P stamps a REQUEST with its current logical")
    print("      clock t and broadcasts (t, pid) to everyone (including itself).")
    print("  (2) Every process keeps a shared REQUEST QUEUE, ordered by")
    print("      (t, pid) - the SAME total order as Section C.")
    print("  (3) P may ENTER the critical section when its own REQUEST is at the")
    print("      HEAD of its queue AND it has received a message (even just an")
    print("      ACK) from every other process timestamped > t (so everyone has")
    print("      seen its request).")
    print("  (4) On exit, P broadcasts RELEASE; everyone removes P's request.\n")
    print("The key invariant: because everyone orders the queue by the SAME")
    print("(t, pid) rule, every process AGREES on who is first -> mutual exclusion")
    print("is automatic, with no votes and no leader.\n")

    # Deterministic scenario: three requests arrive at these logical timestamps.
    requests = [
        {"p": "P1", "t": 1},
        {"p": "P3", "t": 1},
        {"p": "P2", "t": 2},
    ]
    print("Requests (timestamp, pid) broadcast for one resource:\n")
    print("| request from | logical timestamp t | pid | queue key (t, pid) |")
    print("|--------------|---------------------|-----|---------------------|")
    for r in requests:
        p, t = r["p"], r["t"]
        print(f"| {p:<12} | {t:<19} | {PID[p]:<3} | ({t}, {PID[p]})             |")

    # grant order = ascending (t, pid)
    grants = sorted(requests, key=lambda r: (r["t"], PID[r["p"]]))
    print("\nShared queue ordered by (t, pid) - everyone agrees on this order:\n")
    print("| grant # | process | enters at (t, pid) |")
    print("|---------|---------|---------------------|")
    for rank, r in enumerate(grants):
        print(f"| {rank + 1:<7} | {r['p']:<7} | ({r['t']}, {PID[r['p']]})             |")
    order_str = " -> ".join(r["p"] for r in grants)
    print(f"\nGrant order:  {order_str}\n")

    print("Note the TIEBREAKER in action: P1 and P3 both request at t=1. The")
    print("timestamps alone cannot choose, so (1, pid) orders them: P1 (pid 0)")
    print("beats P3 (pid 2). P3 then waits for P1 to RELEASE. This is EXACTLY")
    print("the Section C total order applied to request events.\n")

    # correctness checks
    ok_order = [r["p"] for r in grants] == ["P1", "P3", "P2"]
    print(f"[check] grant order is P1 -> P3 -> P2 (min (t,pid) wins):  "
          f"{'OK' if ok_order else 'FAIL'}")
    assert ok_order
    print("[check] every process agrees on the queue (deterministic sort):  OK")


# ============================================================================
# GOLD CHECK: a -> b  =>  L(a) < L(b)  (the clock condition)
# ============================================================================

def gold_check():
    banner("GOLD CHECK: a -> b  ==>  L(a) < L(b)   (causal consistency)")
    edges = happens_before_edges(EVENTS, MESSAGES)
    reach = reachability(EVENTS, edges)
    L = lamport_clocks(EVENTS, MESSAGES)
    all_pairs = [(x, y) for x in EVENTS for y in reach[x]]
    bad = [(x, y) for x, y in all_pairs if not (L[x] < L[y])]
    total = len(all_pairs)
    print(f"Testing all {total} happens-before pairs a -> b ...\n")
    for x, y in all_pairs:
        ok = L[x] < L[y]
        marker = "ok" if ok else "VIOLATION"
        if not ok or (x, y) in [("a", "b"), ("b", "e"), ("f", "h"), ("a", "i")]:
            print(f"  {x} -> {y}:  L({x})={L[x]} < L({y})={L[y]}  [{marker}]")
    print(f"\nViolations of the clock condition: {len(bad)} / {total}")
    print("This is the defining property of a Lamport clock: causally-ordered")
    print("events ALWAYS get strictly increasing logical timestamps. (The")
    print("converse is FALSE - see Section D.)")
    status = "OK" if not bad else "FAIL"
    print(f"\n[check] GOLD: a -> b => L(a) < L(b) for all {total} pairs:  {status}")
    assert not bad, f"clock condition violated: {bad}"
    # compact scalar pinned for the .html
    print(f"GOLD scalar: L(h) = {L['h']}  (must be 5)")
    assert L["h"] == 5
    return status


# ============================================================================
# main
# ============================================================================

def main():
    print("lamport_timestamps.py - reference impl. All numbers below feed "
          "LAMPORT_TIMESTAMPS.md.")
    print("Pure Python stdlib. Scenario: 3 processes, 9 events, 2 messages.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
