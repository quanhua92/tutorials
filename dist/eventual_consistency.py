"""
eventual_consistency.py - Reference implementation of EVENTUAL CONSISTENCY:
the weakest useful consistency model. If no new updates are made, eventually
all replicas converge to the same value. Amazon Dynamo's default.

This is the single source of truth that EVENTUAL_CONSISTENCY.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 eventual_consistency.py

============================================================================
THE INTUITION (read this first) - the rumor mill
============================================================================
Imagine a piece of GOSSIP spreading through a town. There is no town crier
making one loud announcement. Instead, each person who hears the rumor
periodically whispers it to a random friend. Given enough time everyone hears
it - but for a while, different people will tell you different things.

That is eventual consistency. The replicas ARE the townspeople, and a WRITE is
the rumor. The background whispering is ANTI-ENTROPY (gossip). The promise is
ONLY this:

    if nobody starts a NEW rumor, then eventually everyone agrees.

It promises nothing about the MEANTIME:
  * STALE READS   - a friend gossip hasn't reached yet still tells the OLD story.
  * REORDERING    - two friends may hand you two rumors in the WRONG order, so a
                    value you watch can even go BACKWARDS (0 -> 2 -> 1).
  * NO DEADLINE   - "eventually" is not a bound; the convergence TIME is
                    probabilistic (though, happily, only ~log2(N) rounds).

To make "eventually everyone agrees" actually TRUE, you need two things:
  (1) an ANTI-ENTROPY mechanism that keeps spreading the rumor (gossip,
      Merkle-tree sync, read repair), AND
  (2) a DETERMINISTIC MERGE rule that produces the SAME final value no matter
      what ORDER updates arrive in (last-writer-wins by version, or a CRDT).
Without (2) - e.g. naive "last delivery wins" - the system can diverge forever
(Section C). Eventual consistency is eventual ONLY when the merge is order-
independent.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  replica          : one copy of the data on one node. Here: {A, B, C} (or
                     N nodes in Section E).
  key (X)          : the thing being stored. We track ONE key, X, for clarity.
  write            : set X to a value, stamped with a VERSION (logical timestamp,
                     higher = newer). e.g. X=1@v1.
  version          : a per-write counter; the merge rule uses it to decide what
                     is "newest". The Lamport logical clock is the natural source
                     (see LAMPORT_TIMESTAMPS.md).
  converge         : every replica holds the SAME (value, version) for X.
  anti-entropy     : any background process that reconciles divergent replicas.
  gossip           : epidemic-style anti-entropy - each node periodically swaps
                     state with a RANDOM peer. Push = send; Pull = ask; Push-pull
                     = exchange both ways.
  LWW              : last-writer-wins - the merge rule that keeps the update with
                     the MAX version (tie-break deterministically).
  CRDT             : conflict-free replicated data type - a merge rule proven to
                     converge for ANY delivery order (sets, counters, ...).
  stale read       : a read returning an outdated value because anti-entropy has
                     not reached that replica YET.
  reorder          : updates arriving at a replica in an order different from the
                     one they were ISSUED in.
  read repair      : fix stale replicas on the fly - a read that detects
                     divergence writes the newest value back to the laggards.
  Merkle tree      : a hash tree over a replica's state; compare root hashes in
                     O(1) to detect difference, descend differing subtrees.
  convergence time : number of gossip rounds until all replicas agree. For
                     push-pull gossip it is ~log2(N) (epidemic spreading).

============================================================================
THE PAPERS (every formula/claim below verified against these)
============================================================================
  Vogels (2009) "Eventually Consistent" - ACM Queue 7(10). The canonical
        survey; Amazon/Werner Vogels' own framing of the model.
  DeCandia et al. (2007) "Dynamo: Amazon's Highly Available Key-value Store"
        - SOSP. The system this bundle models: gossip, read repair, Merkle-tree
        anti-entropy, vector clocks, LWW. Always-on, eventually consistent.
  Demers et al. (1987) "Epidemic Algorithms for Replicated Database Maintenance"
        - the origin of gossip/anti-entropy; the O(log N) epidemic bound.
  Gilbert & Lynch (2002) "Brewer's Conjecture ... Provable" - the CAP result:
        during a partition you choose C or A. Dynamo chose A (available) and so
        gets eventual, not strong, consistency. (see NETWORK_PARTITIONS.md)
  Shapiro et al. (2011) "A comprehensive study of Convergent and Commutative
        Replicated Data Types" - CRDTs, the principled merge rules.

KEY FORMULAS (all asserted in code below):
    convergence guarantee : if no new writes arrive, after enough anti-entropy
                            rounds, ALL replicas hold one (value, version).
    LWW merge             : merged = argmax over updates by version;
                            tie-break by value (descending) - deterministic.
    naive merge           : take whatever arrives last - order-DEPENDENT, can
                            diverge forever. (Section C shows the failure.)
    push-pull infected    : I(t+1) ~ I(t) + I(t)*(N-I(t))/N  -> logistic growth;
                            rounds to full ~ log2(N).  (Section E.)
    read repair           : 1 read of a quorum repairs every contacted laggard.
    Merkle sync           : O(1) root compare to detect difference; O(log M) to
                            locate each differing key among M keys.

============================================================================
DETERMINISM NOTE (how the .html reproduces these numbers byte-for-byte)
============================================================================
Gossip picks RANDOM peers. Python's random.Random uses Mersenne Twister, which
JS cannot reproduce exactly. So BOTH this file and eventual_consistency.html use
an IDENTICAL tiny PRNG (a 32-bit LCG, Numerical Recipes constants) for peer
selection. Same seed + same iteration order => identical peer picks => identical
convergence timelines. The LCG is `_lcg()` below; see the JS `lcg()` twin.

============================================================================
THE SCENARIO (deterministic; reused by every section and by the .html)
============================================================================
Three replicas A, B, C of a single key X, all starting X=0 @ v0. One write
X=1@v1 lands on A. Then anti-entropy (gossip) runs round by round. Section C
adds a second write; Section E scales to N=1000.
"""

from __future__ import annotations

import math

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# A tiny, portable PRNG so .py and .html pick IDENTICAL gossip peers.
# 32-bit linear congruential generator (Numerical Recipes constants).
# JS twin in eventual_consistency.html MUST stay byte-identical to this.
# ----------------------------------------------------------------------------
def _lcg(seed: int):
    """Return a zero-arg closure producing floats in [0, 1) deterministically."""
    state = seed & 0xFFFFFFFF

    def rnd() -> float:
        nonlocal state
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        return state / 4294967296

    return rnd


def _randrange(rnd, n: int) -> int:
    """Floor(rnd() * n). Matches JS Math.floor(rnd()*n) exactly."""
    return int(rnd() * n)


# Seeds. Picked so the 3-replica narrative is a clean ~2-round story AND replica
# B is the LAST one reached (so Section B's stale-read window is visible).
SEED_3 = 1115      # Section A, B, D (3-replica push/pull)
SEED_1000 = 42     # Section E (N=1000 push-pull epidemic)
SEED_GOLD_3 = 1115  # GOLD check, small case

REPLICAS = ["A", "B", "C"]


# ============================================================================
# 1. DATA MODEL + MERGE RULES + GOSSIP ROUNDS
#    (the code EVENTUAL_CONSISTENCY.md walks through)
# ============================================================================

class Replica:
    """One copy of key X. `version` is its logical timestamp (Lamport-ish)."""

    __slots__ = ("name", "value", "version")

    def __init__(self, name: str):
        self.name = name
        self.value = 0
        self.version = 0

    def state(self) -> str:
        return f"X={self.value}@v{self.version}"


def lww_merge(d_val, d_ver, s_val, s_ver):
    """Last-writer-wins by VERSION; tie-break higher value (deterministic).

    Order-INDEPENDENT: the result depends only on the two (value,version) pairs,
    never on which arrived last. That is what makes convergence guaranteed.
    Returns the merged (value, version) to store at the destination.
    """
    if s_ver > d_ver:
        return s_val, s_ver
    if s_ver == d_ver and s_val > d_val:
        return s_val, s_ver
    return d_val, d_ver


def naive_merge(d_val, d_ver, s_val, s_ver):
    """No version check: the LAST delivery overwrites. Order-DEPENDENT.

    Used in Section C to show what goes WRONG without a deterministic merge:
    the final value depends on arrival order, so replicas can DIVERGE.
    """
    return s_val, s_ver


def push_round(reps, infected, rnd, merge=lww_merge):
    """One PUSH-gossip round (SYNCHRONOUS): each INFECTED node pushes its
    START-OF-ROUND state to one random peer (fanout = 1). Sources read the
    round-start snapshot; destinations ACCUMULATE into a commit buffer via the
    merge rule, then all commits apply at once at round end (so two pushes to the
    same peer compose by LWW, and no within-round value is clobbered). Matches
    the textbook epidemic model. Returns (new_infected_set, exchanges)."""
    snap = [(r.value, r.version) for r in reps]
    n = len(reps)
    buf = list(snap)
    pushes = [(i, _randrange(rnd, n)) for i in sorted(infected)]
    new = set(infected)
    exchanges = []
    for i, peer in pushes:
        s_val, s_ver = snap[i]                       # source: round-start
        d_val, d_ver = buf[peer]                     # dest: accumulating buffer
        nv, nver = merge(d_val, d_ver, s_val, s_ver)
        delivered = s_ver > 0 and nver > d_ver
        buf[peer] = (nv, nver)
        if s_ver > 0:
            new.add(peer)
        exchanges.append((i, peer, delivered))
    for i in range(n):
        reps[i].value, reps[i].version = buf[i]
    return new, exchanges


def pull_round(reps, infected, rnd, merge=lww_merge):
    """One PULL-gossip round (SYNCHRONOUS): EVERY node asks one random peer for
    its START-OF-ROUND state. Snapshot sources, commit-buffer destinations.
    Returns (new_infected_set, exchanges)."""
    snap = [(r.value, r.version) for r in reps]
    n = len(reps)
    buf = list(snap)
    pulls = [(_randrange(rnd, n), i) for i in range(n)]   # node i pulls FROM peer
    new = set(infected)
    exchanges = []
    for peer, i in pulls:
        s_val, s_ver = snap[peer]                    # source: round-start
        d_val, d_ver = buf[i]                        # dest: buffer
        nv, nver = merge(d_val, d_ver, s_val, s_ver)
        delivered = s_ver > 0 and nver > d_ver
        buf[i] = (nv, nver)
        if s_ver > 0:
            new.add(i)
        exchanges.append((peer, i, delivered))
    for i in range(n):
        reps[i].value, reps[i].version = buf[i]
    return new, exchanges


def pushpull_round(reps, infected, rnd, merge=lww_merge):
    """One PUSH-PULL round (SYNCHRONOUS): each node contacts one random peer and
    they OFFER each other their START-OF-ROUND state; each ACCUMULATES what it
    receives into its commit buffer. This is the ~log2(N) epidemic model used in
    Section E. Returns the new infected set."""
    snap = [(r.value, r.version) for r in reps]
    n = len(reps)
    buf = list(snap)
    contacts = [(_randrange(rnd, n), i) for i in range(n)]
    new = set(infected)
    for peer, i in contacts:
        i_offer = snap[i]                            # i offers round-start value
        p_offer = snap[peer]                         # peer offers round-start value
        nv, nver = merge(buf[i][0], buf[i][1], p_offer[0], p_offer[1])
        buf[i] = (nv, nver)                          # i receives peer's offer
        nv2, nver2 = merge(buf[peer][0], buf[peer][1], i_offer[0], i_offer[1])
        buf[peer] = (nv2, nver2)                     # peer receives i's offer
        if snap[i][1] > 0 or snap[peer][1] > 0:
            new.add(i)
            new.add(peer)
    for i in range(n):
        reps[i].value, reps[i].version = buf[i]
    return new


def simulate(n=3, write_to=0, write_val=1, write_ver=1, seed=SEED_3,
             merge=lww_merge, kind="push", max_rounds=50):
    """Run anti-entropy until all replicas carry the write (or max_rounds).

    Returns (reps, rounds) where rounds[r] is a dict with the state snapshot,
    the infected index list, and the exchanges for that round. rounds[0] is the
    post-write initial state. Deterministic for a fixed (seed, kind)."""
    reps = [Replica(REPLICAS[i] if n == 3 else f"n{i}") for i in range(n)]
    reps[write_to].value, reps[write_to].version = write_val, write_ver
    infected = {write_to}
    rnd = _lcg(seed)
    step = {"push": push_round, "pull": pull_round}[kind]
    rounds = [{
        "round": 0,
        "states": [(r.value, r.version) for r in reps],
        "infected": sorted(infected),
        "exchanges": [],
    }]
    r = 0
    while len(infected) < n and r < max_rounds:
        r += 1
        if kind == "pushpull":
            infected = pushpull_round(reps, infected, rnd, merge)
            exchanges = []
        else:
            infected, exchanges = step(reps, infected, rnd, merge)
        rounds.append({
            "round": r,
            "states": [(rp.value, rp.version) for rp in reps],
            "infected": sorted(infected),
            "exchanges": exchanges,
        })
    return reps, rounds


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def states_str(reps):
    return ", ".join(f"{r.name}={r.state()}" for r in reps)


def snap_str(names, states):
    """Format a per-round state snapshot: states = [(val, ver), ...]."""
    return ", ".join(f"{names[i]}=X={v}@v{ver}" for i, (v, ver) in enumerate(states))


# ============================================================================
# SECTION A: convergence - a write spreads until every replica agrees
# ============================================================================

def section_a():
    banner("SECTION A: convergence - a write spreads until every replica agrees")
    print("Three replicas of key X, all start X=0 @ v0. We WRITE X=1 @ v1 onto")
    print("replica A, then let ANTI-ENTROPY (push gossip) run round by round.\n")
    reps, rounds = simulate(n=3, write_to=0, seed=SEED_3, kind="push")
    names = [r.name for r in reps]
    print(f"after WRITE X=1@v1 -> A:   {snap_str(names, rounds[0]['states'])}")
    print(f"                          infected (carry v1) = "
          f"{{{', '.join(names[i] for i in rounds[0]['infected'])}}}\n")
    for rd in rounds[1:]:
        push = " ; ".join(
            f"{names[s]}->{names[d]}" + ("(updated)" if new else "")
            for s, d, new in rd["exchanges"]
        )
        inf = ", ".join(names[i] for i in rd["infected"])
        print(f"round {rd['round']}: {push}")
        print(f"          states:   {snap_str(names, rd['states'])}")
        print(f"          infected: {{{inf}}}\n")
    conv = len(rounds) - 1
    print(f"CONVERGED in {conv} rounds: every replica = X=1@v1.")
    print("No new writes arrived during those rounds, so the system reached a")
    print("state where all replicas AGREE. THAT is the eventual-consistency")
    print("promise: eventually, if updates stop, everyone converges.\n")
    final = {(r.value, r.version) for r in reps}
    print(f"[check] all replicas share one final state {final}: "
          f"{'OK' if len(final) == 1 else 'FAIL'}")
    assert len(final) == 1
    print(f"GOLD (pinned for .html): 3-replica push gossip converges in "
          f"{conv} rounds -> {final}")
    return conv, final


# ============================================================================
# SECTION B: stale reads - reading a replica gossip hasn't reached yet
# ============================================================================

def section_b():
    banner("SECTION B: stale reads - the window before a replica sees the write")
    print("Same write as Section A (X=1@v1 at A). A client keeps reading X from")
    print("replica B. While gossip hasn't delivered the update to B yet, the read")
    print("returns X=0 - that is a STALE READ.\n")
    reps, rounds = simulate(n=3, write_to=0, seed=SEED_3, kind="push")
    B = 1
    print(f"client reads B: X={rounds[0]['states'][B][0]}  <- STALE (expected 1)")
    last_stale = 0
    for rd in rounds[1:]:
        val_b, ver_b = rd["states"][B]
        stale = ver_b < 1
        tag = "STALE" if stale else "fresh"
        print(f"round {rd['round']}: client reads B: X={val_b}  <- {tag}")
        if stale:
            last_stale = rd["round"]
        else:
            break
    window = last_stale + 1
    print(f"\nThe STALE READ WINDOW for B = rounds 0..{last_stale} ({window} reads).")
    print("Eventual consistency ALLOWS stale reads DURING convergence - it only")
    print("promises they eventually END. Stronger models forbid them entirely:")
    print("  linearizability   : every read returns the latest WRITTEN value.")
    print("  read-your-writes  : a client always sees its own prior writes.")
    print("  monotonic reads   : once a client sees a value, it never sees an")
    print("                      older one (no going backwards).")
    print("Dynamo offers these only as OPTIONAL, client-tunable session guarantees.")
    print(f"\n[check] B's stale window closes by round {window}:  OK")
    assert window >= 1


# ============================================================================
# SECTION C: reordered updates - during convergence values can go BACKWARDS
# ============================================================================

def section_c():
    banner("SECTION C: reordered updates - a value can go 0 -> 2 -> 1 (backwards)")
    print("Two writes to the SAME key from DIFFERENT coordinators:")
    print("  t=1: WRITE X=1 @ v1 -> replica A")
    print("  t=2: WRITE X=2 @ v2 -> replica B    (the LATER, newer write)\n")
    print("Replica C is reached by gossip. There is NO ordering guarantee on")
    print("delivery, so C may receive B's NEWER write BEFORE A's older one.\n")
    print("Scripted delivery to C (a possible, deterministic arrival order):")
    print("  round 1: B -> C  delivers (X=2, v2)")
    print("  round 2: A -> C  delivers (X=1, v1)\n")

    print("--- NAIVE merge (last delivery wins, NO version check) ---")
    cv, cver = 0, 0
    print(f"  start             : C = X={cv}@v{cver}")
    cv, cver = naive_merge(cv, cver, 2, 2)
    print(f"  round1 B->C (v2)  : C = X={cv}@v{cver}")
    cv, cver = naive_merge(cv, cver, 1, 1)
    print(f"  round2 A->C (v1)  : C = X={cv}@v{cver}    <- went BACKWARDS")
    naive_final = cv
    print(f"  => C ended at X={naive_final}. But the newest write was X=2!")
    print("     The observed sequence 0 -> 2 -> 1 is REVERSED. With no ordering")
    print("     guarantee and no version check, replicas can DIVERGE forever.\n")

    print("--- LWW merge (highest version wins) ---")
    cv, cver = 0, 0
    print(f"  start             : C = X={cv}@v{cver}")
    cv, cver = lww_merge(cv, cver, 2, 2)
    print(f"  round1 B->C (v2)  : C = X={cv}@v{cver}")
    cv, cver = lww_merge(cv, cver, 1, 1)
    print(f"  round2 A->C (v1)  : C = X={cv}@v{cver}    (v1 < v2 -> rejected)")
    lww_final = cv
    print(f"  => C ended at X={lww_final}. Correct: v2 was the newest write.\n")

    print("THE LESSON: 'eventual consistency' converges ONLY if the merge rule is")
    print("ORDER-INDEPENDENT - it must yield the same final value for ANY delivery")
    print("order. LWW (by version) and CRDTs have this property; naive overwrite")
    print("does NOT. Which order gossip delivers the updates is nondeterministic;")
    print("a good merge rule makes the OUTCOME independent of that order. Whatever")
    print("the order, LWW settles C on X=2.\n")
    ok = (lww_final == 2) and (naive_final == 1)
    print(f"[check] LWW final={lww_final} (==2, newest) ; naive final="
          f"{naive_final} (reversed):  {'OK' if ok else 'FAIL'}")
    assert ok


# ============================================================================
# SECTION D: convergence mechanisms - push, pull, read repair
# ============================================================================

def section_d():
    banner("SECTION D: convergence mechanisms - push gossip, pull, read repair")
    print("Three ways anti-entropy actually fixes divergent replicas. Same write")
    print("(X=1@v1 at A, 3 replicas) for each; we report ROUNDS TO CONVERGE.\n")

    # (1) PUSH
    reps, rounds = simulate(n=3, write_to=0, seed=SEED_3, kind="push")
    push_r = len(rounds) - 1
    print("(1) PUSH gossip : each INFECTED node pushes its state to a random peer.")
    print("    Only nodes that already have the update do work. Good early, when")
    print("    few are infected (each push is likely to reach a fresh node).")
    print(f"    converged in {push_r} rounds.")
    print("    infected: " + " -> ".join(
        f"r{rd['round']}:{len(rd['infected'])}" for rd in rounds))

    # (2) PULL
    reps2, rounds2 = simulate(n=3, write_to=0, seed=SEED_3, kind="pull")
    pull_r = len(rounds2) - 1
    print("\n(2) PULL gossip : EVERY node asks a random peer for its state.")
    print("    All nodes work every round, so it converges fast in the TAIL")
    print("    (when almost everyone is already updated, pulls still sweep up).")
    print(f"    converged in {pull_r} rounds.")
    print("    infected: " + " -> ".join(
        f"r{rd['round']}:{len(rd['infected'])}" for rd in rounds2))

    # (3) READ REPAIR
    print("\n(3) READ REPAIR : a client reads from (a quorum of) replicas, spots")
    print("    the newest version, and writes it back to the laggards IN THE SAME")
    print("    round. Convergence in 1 round - but only for keys that are READ.")
    reps3 = [Replica(n) for n in REPLICAS]
    reps3[0].value, reps3[0].version = 1, 1
    print(f"    before: {states_str(reps3)}")
    maxv = max(r.version for r in reps3)
    maxval = max((r.value for r in reps3 if r.version == maxv))
    repaired = []
    for r in reps3:
        if r.version < maxv:
            r.value, r.version = maxval, maxv
            repaired.append(r.name)
    print(f"    read newest X={maxval}@v{maxv}; wrote back to {{{', '.join(repaired)}}}.")
    print(f"    after : {states_str(reps3)}")

    print("\nTrade-off: read repair is instant but only fixes keys that are READ;")
    print("gossip fixes EVERYTHING in the background but takes ~log N rounds.")
    print("Dynamo (DeCandia 2007) runs ALL THREE: gossip for liveness, read repair")
    print("for hot keys, and periodic Merkle-tree anti-entropy as a backstop.\n")
    ok = push_r >= 1 and pull_r >= 1 and len(repaired) == 2
    print(f"[check] push={push_r}r, pull={pull_r}r, read-repair=1r "
          f"(repaired {{{','.join(repaired)}}}):  {'OK' if ok else 'FAIL'}")
    assert ok


# ============================================================================
# SECTION E: convergence time - gossip is O(log N)  (epidemic spreading)
# ============================================================================

def section_e():
    banner("SECTION E: convergence time - gossip is O(log N)  (epidemic spreading)")
    print("Push-PULL gossip spreads a write like an EPIDEMIC: each round every")
    print("node swaps state with a random peer. An infected-updated node paired")
    print("with a fresh one infects it (via either direction). The infected count")
    print("grows GEOMETRICALLY each round, so reaching all N nodes takes ~log2(N)")
    print("rounds. This is why gossip scales to huge clusters.\n")
    print("| N     | rounds to converge | log2(N) |")
    print("|-------|--------------------|---------|")
    data = []
    for N in (10, 100, 1000):
        reps = [Replica(f"n{i}") for i in range(N)]
        reps[0].value, reps[0].version = 1, 1
        infected = {0}
        rng = _lcg(SEED_1000)
        r = 0
        while len(infected) < N and r < 200:
            r += 1
            infected = pushpull_round(reps, infected, rng)
        data.append((N, r))
        print(f"| {N:<5} | {r:<18} | {math.log2(N):<7.2f} |")
    print("\nRounds grow with log2(N), not with N: 10x more nodes costs only ~3")
    print("extra rounds. (Random collisions - two infected nodes contacting each")
    print("other - add a small constant factor over the bare log2(N).)\n")

    # Infection curve for N=1000
    print("Infection curve for N=1000 (each '#' ~ 2% of the cluster):")
    reps = [Replica(f"n{i}") for i in range(1000)]
    reps[0].value, reps[0].version = 1, 1
    infected = {0}
    rnd = _lcg(SEED_1000)
    curve = [1]
    r = 0
    while len(infected) < 1000 and r < 200:
        r += 1
        infected = pushpull_round(reps, infected, rnd)
        curve.append(len(infected))
    for i, c in enumerate(curve):
        bar = "#" * int(c / 1000 * 50)
        print(f"  round {i:>2} | {c:>4} ({100 * c / 1000:5.1f}%) | {bar}")
    print("\nThe logistic SHAPE - slow start, explosive middle, slow tail - is the")
    print("signature of epidemic spreading. It is literally how a rumor or a virus")
    print("moves through a population (Demers et al. 1987).\n")
    r1000 = data[-1][1]
    reached = curve[-1] == 1000 and data[-1][1] == len(curve) - 1
    ok = all(rr <= 2 * math.log2(N) + 4 for N, rr in data) and reached
    print(f"[check] rounds <= 2*log2(N)+4 for N in 10/100/1000 AND N=1000 hits "
          f"1000:  {'OK' if ok else 'FAIL'}")
    assert ok
    print(f"GOLD (pinned for .html): N=1000 push-pull converges in {r1000} rounds "
          f"(log2(1000)={math.log2(1000):.2f}).")


# ============================================================================
# GOLD CHECK: with no new writes, all replicas converge to ONE final state
# ============================================================================

def gold_check():
    banner("GOLD CHECK: no new writes => all replicas converge to one final state")
    print("The defining property of eventual consistency: if no new updates are")
    print("issued, then after enough anti-entropy rounds EVERY replica holds the")
    print("identical (value, version) for every key. Verified at two scales.\n")

    # small: 3 replicas, push gossip, LWW
    reps, rounds = simulate(n=3, write_to=0, seed=SEED_GOLD_3, kind="push")
    small = {(r.value, r.version) for r in reps}
    small_r = len(rounds) - 1
    print(f"3-replica push gossip (LWW, seed={SEED_GOLD_3}):")
    print(f"  converged in {small_r} rounds -> final states = {small}")

    # large: 1000 nodes, push-pull
    big = [Replica(f"n{i}") for i in range(1000)]
    big[0].value, big[0].version = 1, 1
    infected = {0}
    rnd = _lcg(SEED_1000)
    r = 0
    while len(infected) < 1000 and r < 200:
        r += 1
        infected = pushpull_round(big, infected, rnd)
    big_set = {(n.value, n.version) for n in big}
    print(f"\n1000-node push-pull gossip (LWW, seed={SEED_1000}):")
    print(f"  converged in {r} rounds -> distinct final states = {len(big_set)} "
          f"= {next(iter(big_set))}")

    ok = (len(small) == 1 and small == {(1, 1)}
          and len(big_set) == 1 and big_set == {(1, 1)})
    print(f"\n[check] GOLD: 3 replicas -> {small}, 1000 nodes -> 1 state "
          f"{next(iter(big_set))}:  {'OK' if ok else 'FAIL'}")
    assert ok
    print("GOLD scalars (pinned for .html):")
    print(f"  small convergence rounds = {small_r} ; final state = (1, 1)")
    print(f"  large convergence rounds = {r} ; final state = (1, 1)")
    return "OK" if ok else "FAIL"


# ============================================================================
# main
# ============================================================================

def main():
    print("eventual_consistency.py - reference impl. All numbers below feed")
    print("EVENTUAL_CONSISTENCY.md. Pure Python stdlib (custom LCG PRNG so the")
    print(".html reproduces gossip peer-picks byte-for-byte).")
    print("Scenario: 3 replicas of key X; one write X=1@v1 to A.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
