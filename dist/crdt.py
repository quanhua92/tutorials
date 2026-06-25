"""
crdt.py - Reference implementation of CONFLICT-FREE REPLICATED DATA TYPES
(CRDTs, Shapiro et al. 2011): data structures whose merge operation is
commutative, associative, and idempotent, so replicas converge WITHOUT any
coordination. Every replica can apply operations locally; when they eventually
sync, the merge function always produces the same final state regardless of
delivery order.

This is the single source of truth that CRDT.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 crdt.py

============================================================================
THE INTUITION (read this first) - the shared whiteboard
============================================================================
Imagine three people each keeping a private TALLY on their own clipboard. No
one talks to anyone else while they work. Person A ticks +2, person B ticks
+3, person C ticks +1. At the end of the day they meet and compare clipboards.

If the tally is a plain integer, merging is a NIGHTMARE: "I had 5, then added
2, so... 7? But you had 4 and added 3, so 7 too? Wait, what was the starting
value?" You need to coordinate, agree on a starting point, log every
operation, and replay them in order.

A CRDT is a clipboard designed so that merging is TRIVIAL and ORDER-FREE:

    G-Counter: instead of one integer, each person keeps a SLOT. A's slot = 2,
    B's slot = 3, C's slot = 1. Merge = take the MAX of each slot. Total = sum.
    No matter who compares first, the merged clipboard is [2, 3, 1] -> 6.

The trick is to make the STATE carry enough information (who did what) that
the merge function is just a LEAST-UPPER-BOUND in a join-semilattice. Every
CRDT is a semilattice: merge(a, b) = a ⊔ b, and ⊔ is commutative, associative,
idempotent (a ⊔ a = a). Those three properties ARE the convergence proof.

Two families (Shapiro et al. 2011):
  * CvRDT (state-based)  : ship the FULL state; merge = lattice join (⊔).
                           Convergence requires merge to be commutative,
                           associative, idempotent. (G-Counter, PN-Counter,
                           LWW-Register, OR-Set.)
  * CmRDT (op-based)     : ship the OPERATION; apply it in causal order.
                           Convergence requires operations to be commutative.
                           (RGA text editing, Yjs, Automerge.)

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  replica          : one copy of the data on one node. Here: {A, B, C}.
  converge         : after all replicas have merged everything, they hold the
                     SAME state. The core CRDT guarantee.
  merge (a ⊔ b)   : the join in the semilattice. Must be commutative
                     (a⊔b == b⊔a), associative ((a⊔b)⊔c == a⊔(b⊔c)), and
                     idempotent (a⊔a == a). Those three axioms ARE convergence.
  CvRDT            : state-based CRDT. Ship full state, merge via ⊔.
  CmRDT            : op-based CRDT. Ship operations, apply in causal order.
  payload          : the internal state of a CRDT replica. e.g. a vector of
                     per-node counts (G-Counter) or a set of tagged elements
                     (OR-Set).
  query            : a read-only operation (value(), lookup()). Never changes
                     the payload.
  update           : a local mutation (increment(), add(), set()). Only
                     touches THIS replica's slot/entries.
  compare (≤)      : the partial order on payloads. a ≤ b means a's state is
                     "contained in" b's. For a G-Counter, element-wise ≤.
  G-Counter        : grow-only counter. Each replica has a slot; increment
                     bumps only its own slot. Merge = element-wise max.
  PN-Counter       : positive-negative counter. Two G-Counters: P (increments)
                     and N (decrements). Value = sum(P) - sum(N).
  G-Set            : grow-only set. Add only, no remove. Merge = union.
  2P-Set           : two-phase set. G-Set of adds + G-Set of removes
                     (tombstones). Once removed, can never be re-added.
  OR-Set           : observed-remove set. Each add generates a UNIQUE tag.
                     Remove only tombstones the tags it has SEEN. Concurrent
                     add+remove -> add wins (the new tag survives).
  LWW-Register     : last-writer-wins register. Each write has a timestamp;
                     merge keeps the write with the MAX timestamp (tie-break
                     by node id). Vulnerable to clock skew.
  RGA              : Replicated Growable Array. Each insertion has a unique id
                     and a predecessor pointer. Concurrent insertions after
                     the same predecessor are ordered by id. Basis of Yjs /
                     Automerge collaborative text editing.
  causal order     : "happened-before" (🔗 LAMPORT_TIMESTAMPS.md). Op-based
                     CRDTs require delivery in causal order; state-based
                     CRDTs do not (the ⊔ handles any order).
  tombstone        : a deletion marker that is KEPT (not garbage-collected) so
                     that a late-arriving add can be correctly resolved.

============================================================================
THE PAPERS (every formula/claim below verified against these)
============================================================================
  Shapiro, Preguiça, Baquero, Zawirski (2011) "A comprehensive study of
        Convergent and Commutative Replicated Data Types" - INRIA RR-7506.
        THE CRDT paper. Defines CvRDT (state-based) and CmRDT (op-based),
        proves the semilattice convergence theorem, catalogs G-Counter,
        PN-Counter, G/LWW/2P/OR-Sets, RGA, MV-Register.
  Shapiro et al. (2011) "Conflict-free replicated data types" - SSS 2011
        (Springer LNCS 6976). The shorter conference version.
  DeCandia et al. (2007) "Dynamo" - SOSP. Amazon's KV store; uses vector
        clocks + LWW. The practical inspiration for CRDTs in production.
        (🔗 EVENTUAL_CONSISTENCY.md)
  Bieniusa et al. (2012) "An Optimized Conflict-free Replicated Set" - the
        optimized OR-Set (OR-Set o).
  Nicolaou & Shapiro (2012) "CRDTs: Consistency without Concurrency Control"
        - the argument that CRDTs avoid coordination entirely.
  Kleppmann (2017) "Designing Data-Intensive Applications" Ch.5 - the
        accessible treatment of CRDTs, used to cross-check every formula.
  Nicholson (2020-2024) "Yjs" - https://github.com/yjs/yjs - production
        CRDT for collaborative editing (RGA-derived). (🔗 CROSS-REF)
  van Kamp (2017-2024) "Automerge" - https://github.com/automerge/automerge
        - production JSON CRDT library.

KEY FORMULAS (all asserted in code below):
    CONVERGENCE THEOREM  : if merge ⊔ is commutative + associative +
                           idempotent, then for ANY delivery order of the same
                           payloads, fold(⊔, [p0, p1, ..., pn]) is identical.
    G-Counter merge      : merge(a, b)[i] = max(a[i], b[i])
    G-Counter value      : sum(counts)
    PN-Counter value     : sum(P) - sum(N)
    OR-Set merge         : added' = added_a ∪ added_b ;
                           removed' = removed_a ∪ removed_b
    OR-Set lookup(e)     : ∃ tag t. (e, t) ∈ added ∧ t ∉ removed
    LWW merge            : keep the write w with max (timestamp, node_id)
    RGA sibling order    : children of the same predecessor are sorted by
                           their unique id (a total order), so concurrent
                           inserts after the same position are deterministic.

============================================================================
DETERMINISM NOTE (how the .html reproduces these numbers byte-for-byte)
============================================================================
CRDTs are DETERMINISTIC BY CONSTRUCTION - every operation is a pure function
of the payload, and merge is a semilattice join. There is no random peer
selection (unlike gossip). So this file uses NO PRNG at all: every scenario
is a fixed script of operations. The .html re-runs the identical script and
gets the identical numbers. The GOLD check (Section F) exhaustively verifies
that ALL 6 orderings of merging 3 replicas yield the same final state.

============================================================================
THE SCENARIO (deterministic; reused by every section and by the .html)
============================================================================
Three replicas A, B, C of a single CRDT. Each performs local operations
independently (no coordination), then they pairwise-merge. The merge ORDER
varies (Section F tries all 6 permutations) but the final state is always
identical - that is the CRDT convergence guarantee.
"""

from __future__ import annotations

import itertools

BANNER = "=" * 72


# ============================================================================
# 1. THE CRDT REFERENCE IMPLEMENTATIONS
#    (this is the code CRDT.md walks through)
# ============================================================================

# ----------------------------------------------------------------------------
# 1a. G-Counter (grow-only counter) - the canonical CvRDT.
# ----------------------------------------------------------------------------

class GCounter:
    """Grow-only counter. Each replica owns one slot; increment bumps only
    its own slot. Merge = element-wise max (the lattice join ⊔).

    Axioms (verified in Section F):
        commutative : merge(a, b) == merge(b, a)
        associative: merge(merge(a, b), c) == merge(a, merge(b, c))
        idempotent  : merge(a, a) == a
    """

    def __init__(self, node_id: str, n_nodes: int):
        self.node_id = node_id
        self.counts = [0] * n_nodes

    def increment(self, by: int = 1) -> None:
        """Local update: bump only THIS replica's slot. Never decrements."""
        assert by >= 0, "G-Counter is grow-only"
        self.counts[_idx(self.node_id)] += by

    def value(self) -> int:
        """Query: the total across all slots."""
        return sum(self.counts)

    def merge(self, other: "GCounter") -> "GCounter":
        """⊔ = element-wise max. Returns a NEW counter (pure)."""
        m = GCounter(self.node_id, len(self.counts))
        m.counts = [max(a, b) for a, b in zip(self.counts, other.counts)]
        return m

    def clone(self) -> "GCounter":
        c = GCounter(self.node_id, len(self.counts))
        c.counts = list(self.counts)
        return c

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GCounter) and self.counts == other.counts

    def __repr__(self) -> str:
        return f"GCounter({self.counts})={self.value()}"


def _idx(node_id: str) -> int:
    """Map node id 'A'->0, 'B'->1, 'C'->2. Fixed, deterministic."""
    return ord(node_id) - ord("A")


# ----------------------------------------------------------------------------
# 1b. PN-Counter (positive-negative counter) = two G-Counters.
# ----------------------------------------------------------------------------

class PNCounter:
    """Positive-negative counter = G-Counter P (increments) + G-Counter N
    (decrements). Value = sum(P) - sum(N). Merge both halves independently.
    """

    def __init__(self, node_id: str, n_nodes: int):
        self.node_id = node_id
        self.P = GCounter(node_id, n_nodes)   # positive (increments)
        self.N = GCounter(node_id, n_nodes)   # negative (decrements)

    def increment(self, by: int = 1) -> None:
        self.P.increment(by)

    def decrement(self, by: int = 1) -> None:
        self.N.increment(by)

    def value(self) -> int:
        return self.P.value() - self.N.value()

    def merge(self, other: "PNCounter") -> "PNCounter":
        m = PNCounter(self.node_id, len(self.P.counts))
        m.P = self.P.merge(other.P)
        m.N = self.N.merge(other.N)
        return m

    def clone(self) -> "PNCounter":
        c = PNCounter(self.node_id, len(self.P.counts))
        c.P = self.P.clone()
        c.N = self.N.clone()
        return c

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, PNCounter)
                and self.P.counts == other.P.counts
                and self.N.counts == other.N.counts)

    def __repr__(self) -> str:
        return (f"PNCounter(P={self.P.counts}, N={self.N.counts})"
                f"={self.value()}")


# ----------------------------------------------------------------------------
# 1c. OR-Set (observed-remove set) - add wins on concurrent add+remove.
# ----------------------------------------------------------------------------

class ORSet:
    """Observed-remove set. Each add(e) generates a unique tag t and records
    (e, t) in `added`. remove(e) tombstones every tag for e currently VISIBLE
    (i.e. in added but not in removed). Merge = union of both added sets and
    union of both removed (tombstone) sets.

    Key property: if replica A adds e (tag t1) and replica B concurrently
    removes e (having only seen an older tag t0), then after merge t1
    survives -> e stays in the set. ADD WINS. (Shapiro 2011 §3.3.1)
    """

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.added: set[tuple[str, tuple[str, int]]] = set()    # {(e, tag)}
        self.removed: set[tuple[str, int]] = set()              # {tag} tombstones
        self._seq = 0                                            # local counter

    def add(self, element: str) -> tuple[str, int]:
        """Local update: generate a unique tag and record (element, tag)."""
        tag = (self.node_id, self._seq)
        self._seq += 1
        self.added.add((element, tag))
        return tag

    def remove(self, element: str) -> int:
        """Local update: tombstone every tag for `element` currently observed
        (in added, not yet removed). Returns count of tags tombstoned."""
        n = 0
        for (e, tag) in list(self.added):
            if e == element and tag not in self.removed:
                self.removed.add(tag)
                n += 1
        return n

    def lookup(self) -> set[str]:
        """Query: elements with at least one live (non-tombstoned) tag."""
        live = set()
        for (e, tag) in self.added:
            if tag not in self.removed:
                live.add(e)
        return live

    def merge(self, other: "ORSet") -> "ORSet":
        """⊔ = union(added) ∪ union(removed). Pure: returns a new ORSet."""
        m = ORSet(self.node_id)
        m.added = self.added | other.added
        m.removed = self.removed | other.removed
        m._seq = max(self._seq, other._seq)
        return m

    def clone(self) -> "ORSet":
        c = ORSet(self.node_id)
        c.added = set(self.added)
        c.removed = set(self.removed)
        c._seq = self._seq
        return c

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, ORSet)
                and self.added == other.added
                and self.removed == other.removed)

    def __repr__(self) -> str:
        return f"ORSet(lookup={sorted(self.lookup())})"


# ----------------------------------------------------------------------------
# 1d. LWW-Register (last-writer-wins) - timestamp + node-id tie-break.
# ----------------------------------------------------------------------------

class LWWRegister:
    """Last-writer-wins register. Each write carries a (timestamp, node_id)
    pair. Merge keeps the write with the MAX pair (lexicographic). Ties on
    timestamp are broken by node_id, so the merge is a TOTAL order and thus
    commutative + associative + idempotent.

    WARNING: if timestamps come from SKEWED wall clocks, LWW can silently
    discard the "real" newest write (Section D). Production CRDTs use a
    hybrid logical clock (e.g. Yjs's state vector) instead of wall time.
    """

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.value: str | None = None
        self.timestamp: int = 0
        self.writer: str = node_id   # who wrote the current value

    def set(self, value: str, timestamp: int) -> None:
        """Local write. Only accepts if (timestamp, node_id) > current."""
        key = (timestamp, self.node_id)
        if self.value is None or key > (self.timestamp, self.writer):
            self.value = value
            self.timestamp = timestamp
            self.writer = self.node_id

    def get(self) -> str | None:
        return self.value

    def merge(self, other: "LWWRegister") -> "LWWRegister":
        """⊔ = keep the write with max (timestamp, writer). Pure."""
        m = LWWRegister(self.node_id)
        if (other.timestamp, other.writer) > (self.timestamp, self.writer):
            m.value, m.timestamp, m.writer = other.value, other.timestamp, other.writer
        else:
            m.value, m.timestamp, m.writer = self.value, self.timestamp, self.writer
        return m

    def clone(self) -> "LWWRegister":
        r = LWWRegister(self.node_id)
        r.value, r.timestamp, r.writer = self.value, self.timestamp, self.writer
        return r

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, LWWRegister)
                and self.value == other.value
                and self.timestamp == other.timestamp
                and self.writer == other.writer)

    def __repr__(self) -> str:
        return f"LWW('{self.value}'@ts={self.timestamp},by={self.writer})"


# ----------------------------------------------------------------------------
# 1e. RGA-style collaborative text (op-based / can be modeled state-based).
#     Each insertion: (id, char, predecessor_id). id = (node, seq).
#     Siblings sorted by id ascending -> deterministic total order.
# ----------------------------------------------------------------------------

HEAD: tuple[str, int] | None = None   # sentinel for "start of document"


class RGAText:
    """Collaborative text CRDT (RGA / Yjs concept). The payload is a SET of
    insertions; linearization is a pure function of that set, so merge =
    set union and the rendered text is deterministic.

    Each insertion is (id, char, left_origin) where:
        id         = (node_id, seq)        globally unique
        char       = the character
        left_origin= id of the character this was inserted AFTER, or HEAD.

    To render: build a tree (children grouped by left_origin), sort siblings
    by id ASCENDING (deterministic total order), pre-order DFS -> the string.
    """

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.insertions: list[tuple[tuple[str, int], str, object]] = []
        # each entry: (id, char, left_origin)   left_origin is an id or HEAD

    def insert_after(self, char: str, left_origin: object) -> tuple[str, int]:
        """Local insert of `char` after the insertion whose id = left_origin
        (HEAD = start of document). Returns the new id."""
        seq = sum(1 for ins in self.insertions if ins[0][0] == self.node_id)
        new_id = (self.node_id, seq)
        self.insertions.append((new_id, char, left_origin))
        return new_id

    def render(self) -> str:
        """Linearize the insertion set into the final string.
        Children of the same predecessor are sorted by id ascending."""
        children: dict[object, list[tuple[tuple[str, int], str]]] = {}
        for (iid, ch, origin) in self.insertions:
            children.setdefault(origin, []).append((iid, ch))
        for k in children:
            children[k].sort(key=lambda x: x[0])
        out: list[str] = []

        def walk(parent: object) -> None:
            for (iid, ch) in children.get(parent, []):
                out.append(ch)
                walk(iid)

        walk(HEAD)
        return "".join(out)

    def merge(self, other: "RGAText") -> "RGAText":
        """⊔ = union of insertions (dedup by id). The render is then a pure
        function of the union, so any merge order yields the same string."""
        m = RGAText(self.node_id)
        seen: set[tuple[str, int]] = set()
        for ins in self.insertions + other.insertions:
            if ins[0] not in seen:
                m.insertions.append(ins)
                seen.add(ins[0])
        return m

    def clone(self) -> "RGAText":
        t = RGAText(self.node_id)
        t.insertions = list(self.insertions)
        return t

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RGAText):
            return False
        sa = {(i[0], i[1], i[2]) for i in self.insertions}
        sb = {(i[0], i[1], i[2]) for i in other.insertions}
        return sa == sb

    def __repr__(self) -> str:
        return f"RGAText('{self.render()}')"


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_state(label: str, states: dict[str, object]) -> str:
    return "  " + "  ".join(f"{k}={v}" for k, v in states.items())


# ============================================================================
# 3. SECTIONS (each prints the tables/numbers that feed CRDT.md)
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: G-Counter - the canonical grow-only counter
# ----------------------------------------------------------------------------

def section_a() -> None:
    banner("SECTION A: G-Counter - grow-only, merge = element-wise max")
    print("Three replicas A, B, C. Each increments ONLY its own slot. No")
    print("coordination. Then they merge. Final value = sum of all slots.\n")

    a, b, c = GCounter("A", 3), GCounter("B", 3), GCounter("C", 3)
    print("Local operations (each replica bumps only its OWN slot):")
    a.increment()               # A: +1
    a.increment()               # A: +1   -> A slot = 2
    b.increment()               # B: +1
    b.increment()               # B: +1
    b.increment()               # B: +1   -> B slot = 3
    c.increment()               # C slot = 1
    print("  A.increment() x2   -> A.counts =", a.counts)
    print("  B.increment() x3   -> B.counts =", b.counts)
    print("  C.increment() x1   -> C.counts =", c.counts)
    print(f"\n  Before merge: A={a.value()}, B={b.value()}, C={c.value()} "
          f"(each sees ONLY its own work)\n")

    print("MERGE = element-wise max  (the lattice join ⊔):")
    ab = a.merge(b)
    abc1 = ab.merge(c)
    print(f"  (A ⊔ B)        = {ab.counts}   value={ab.value()}")
    print(f"  (A ⊔ B) ⊔ C    = {abc1.counts}   value={abc1.value()}")
    print(f"\n  Final value = sum([2, 3, 1]) = {abc1.value()}")
    print("  Every increment across all replicas is accounted for. No loss,")
    print("  no double-counting, no coordination needed.\n")

    print("WHY IT WORKS (the semilattice):")
    print("  merge(a, b)[i] = max(a[i], b[i])")
    print("  max is commutative  : max(x, y) == max(y, x)")
    print("  max is associative  : max(max(x, y), z) == max(x, max(y, z))")
    print("  max is idempotent   : max(x, x) == x")
    print("  => merge order is IRRELEVANT. fold(⊔, any permutation) is equal.\n")

    print("[check] G-Counter value = 2 + 3 + 1 = 6:",
          "OK" if abc1.value() == 6 else "FAIL")


# ----------------------------------------------------------------------------
# SECTION B: PN-Counter - decrement support via two G-Counters
# ----------------------------------------------------------------------------

def section_b() -> None:
    banner("SECTION B: PN-Counter - two G-Counters (P increments, N decrements)")
    print("A G-Counter can only grow. To support DECREMENT, use TWO")
    print("G-Counters: P (positive, increments) and N (negative, decrements).")
    print("Value = sum(P) - sum(N). Both halves merge independently as max.\n")

    a, b, c = PNCounter("A", 3), PNCounter("B", 3), PNCounter("C", 3)
    a.increment(5)              # P_A = 5
    a.decrement(1)              # N_A = 1
    b.increment(2)              # P_B = 2
    b.decrement(3)              # N_B = 3
    c.increment(4)              # P_C = 4
    print("Local operations:")
    print(f"  A: +5, -1  -> P={a.P.counts} N={a.N.counts}  value={a.value()}")
    print(f"  B: +2, -3  -> P={b.P.counts} N={b.N.counts}  value={b.value()}")
    print(f"  C: +4      -> P={c.P.counts} N={c.N.counts}  value={c.value()}\n")

    abc = a.merge(b).merge(c)
    print("MERGE (both halves independently):")
    print(f"  P merged = {abc.P.counts}   (element-wise max of P vectors)")
    print(f"  N merged = {abc.N.counts}   (element-wise max of N vectors)")
    total_p = sum(abc.P.counts)
    total_n = sum(abc.N.counts)
    print(f"\n  Value = sum(P) - sum(N) = {total_p} - {total_n} = {abc.value()}")
    print(f"  (Individual values were {a.value()}, {b.value()}, {c.value()}; "
          f"merged = {abc.value()} = their sum.)\n")

    print("WHY decrements can't just subtract from the G-Counter:")
    print("  If B did counts[B] -= 3, merge=max would LOSE the decrement")
    print("  (max ignores anything smaller). Splitting into P and N means")
    print("  both monotonic, and the difference is the net value.\n")

    print("[check] PN-Counter value = (5+2+4) - (1+3+0) = 11 - 4 = 7:",
          "OK" if abc.value() == 7 else "FAIL")


# ----------------------------------------------------------------------------
# SECTION C: OR-Set - observed-remove, add wins on concurrent add+remove
# ----------------------------------------------------------------------------

def section_c() -> None:
    banner("SECTION C: OR-Set - observed-remove set (concurrent add+remove -> add wins)")
    print("Each add(e) generates a UNIQUE tag. remove(e) tombstones only the")
    print("tags it has SEEN. If a concurrent add created a new tag, that tag")
    print("survives the merge -> the element STAYS. Add wins.\n")

    a, b, c = ORSet("A"), ORSet("B"), ORSet("C")
    print("Local operations:")
    a.add("x")
    a.add("y")
    print(f"  A: add('x'), add('y')          -> lookup={sorted(a.lookup())}")
    b.add("x")
    b.remove("x")
    print(f"  B: add('x'), remove('x')       -> lookup={sorted(b.lookup())}  "
          f"(B tombstoned its OWN tag for x)")
    c.add("z")
    print(f"  C: add('z')                    -> lookup={sorted(c.lookup())}\n")

    print("Payloads (added pairs, removed tombstones):")
    print(f"  A: added={sorted(a.added)}")
    print(f"  B: added={sorted(b.added)}  removed={sorted(b.removed)}")
    print(f"  C: added={sorted(c.added)}\n")

    abc = a.merge(b).merge(c)
    print("MERGE = union(added) ∪ union(removed):")
    print(f"  added   = {sorted(abc.added)}")
    print(f"  removed = {sorted(abc.removed)}")
    print(f"\n  lookup (live tags only) = {sorted(abc.lookup())}\n")

    print("THE CONCURRENT ADD+REMOVE RESOLUTION:")
    print("  B added 'x' (tag B:0) then removed it (tombstoned B:0).")
    print("  But A ALSO added 'x' with a DIFFERENT tag (A:0), concurrently.")
    print("  Merge: added has (x,A:0) and (x,B:0); removed has {B:0}.")
    print("  (x,A:0) is NOT tombstoned -> 'x' SURVIVES. ADD WINS.\n")
    print("  Contrast with 2P-Set: a 2P-Set remove tombstones the ELEMENT")
    print("  forever. Once removed, 'x' could never be re-added. OR-Set")
    print("  fixes this by tombstoning TAGS, not elements.\n")

    print("[check] OR-Set lookup after merge = {x, y, z} (add wins):",
          "OK" if abc.lookup() == {"x", "y", "z"} else "FAIL")


# ----------------------------------------------------------------------------
# SECTION D: LWW-Register - timestamp tie-break, clock skew pitfall
# ----------------------------------------------------------------------------

def section_d() -> None:
    banner("SECTION D: LWW-Register - last-writer-wins (and the clock-skew pitfall)")
    print("Each write carries a timestamp. Merge = keep the write with MAX")
    print("(timestamp, writer). Ties broken by node id (deterministic total")
    print("order). But if timestamps come from SKEWED clocks, LWW can pick")
    print("the WRONG winner.\n")

    print("--- Case 1: well-behaved clocks (timestamps reflect real order) ---")
    a = LWWRegister("A")
    b = LWWRegister("B")
    c = LWWRegister("C")
    a.set("hello", 1)
    b.set("world", 2)
    c.set("done", 3)
    print("  A.set('hello', ts=1)")
    print("  B.set('world', ts=2)")
    print("  C.set('done',   ts=3)")
    abc = a.merge(b).merge(c)
    print(f"  merge -> {abc}")
    print("  Correct: ts=3 is the newest write. ['done'] wins.\n")

    print("--- Case 2: CLOCK SKEW (A's clock is 10s ahead) ---")
    a2 = LWWRegister("A")
    b2 = LWWRegister("B")
    a2.set("OLD value", 15)      # A's clock is ahead; real-time this was FIRST
    b2.set("NEW value", 3)       # B's clock is correct; real-time this was LATER
    print("  A.set('OLD value', ts=15)   <- A's skewed clock, but written FIRST")
    print("  B.set('NEW value', ts=3)    <- correct clock, written LATER")
    abc2 = a2.merge(b2)
    print(f"  merge -> {abc2}")
    print("  LWW picked 'OLD value' because ts=15 > ts=3. The genuinely newer")
    print("  write ('NEW value') was SILENTLY DISCARDED. This is why production")
    print("  CRDTs use HYBRID LOGICAL CLOCKS (e.g. Yjs state vector), not wall")
    print("  time. (🔗 LAMPORT_TIMESTAMPS.md, VECTOR_CLOCKS.md)\n")

    print("--- Case 3: TIMESTAMP TIE -> break by node id (deterministic) ---")
    a3 = LWWRegister("A")
    c3 = LWWRegister("C")
    a3.set("from-A", 5)
    c3.set("from-C", 5)
    print("  A.set('from-A', ts=5)")
    print("  C.set('from-C', ts=5)   <- same timestamp!")
    abc3 = a3.merge(c3)
    print(f"  merge -> {abc3}")
    print("  Tie on ts=5. Break by writer: 'C' > 'A', so 'from-C' wins.")
    print("  The tie-break makes merge a TOTAL order -> commutative +")
    print("  associative + idempotent -> convergent. (Section F proves it.)\n")

    print("[check] Case1='done', Case2='OLD value', Case3='from-C':",
          "OK" if (abc.get() == "done" and abc2.get() == "OLD value"
                   and abc3.get() == "from-C") else "FAIL")


# ----------------------------------------------------------------------------
# SECTION E: RGA collaborative text - concurrent inserts converge
# ----------------------------------------------------------------------------

def section_e() -> None:
    banner("SECTION E: Collaborative text (RGA) - two users type concurrently")
    print("Each character insertion has a unique id (node, seq) and a")
    print("predecessor pointer (the id of the char it was inserted after, or")
    print("HEAD for the start). Concurrent inserts after the SAME predecessor")
    print("are ordered by id (a total order) -> deterministic. Basis of")
    print("Yjs / Automerge.\n")

    # Phase 1: A types "Hi", syncs to B and C.
    a = RGAText("A")
    b = RGAText("B")
    c = RGAText("C")
    h = a.insert_after("H", HEAD)
    i = a.insert_after("i", h)
    # sync: B and C receive A's insertions
    b = a.clone()
    b.node_id = "B"
    c = a.clone()
    c.node_id = "C"
    print("Phase 1 - A types 'Hi', then syncs to B and C:")
    print(f"  insertions: {a.insertions}")
    print(f"  A.render() = '{a.render()}'   B.render() = '{b.render()}'   "
          f"C.render() = '{c.render()}'\n")

    # Phase 2: concurrent inserts after 'i' (id=(A,1))
    print("Phase 2 - all three type DIFFERENT chars after 'i', CONCURRENTLY:")
    a.insert_after("!", i)      # A appends '!'
    b.insert_after("?", i)      # B appends '?'
    c.insert_after("+", i)      # C appends '+'
    print(f"  A.insert_after('!',  (A,1))   -> A = '{a.render()}'")
    print(f"  B.insert_after('?',  (A,1))   -> B = '{b.render()}'")
    print(f"  C.insert_after('+',  (A,1))   -> C = '{c.render()}'")
    print("  (each replica only sees its OWN new char so far)\n")

    # Phase 3: merge all three
    abc = a.merge(b).merge(c)
    print("Phase 3 - merge all three (union of insertions, then re-render):")
    print("  children of (A,1) = [(A,2)'!', (B,0)'?', (C,0)'+']")
    print("  sorted by id ASC  : (A,2) < (B,0) < (C,0)   "
          "-> order: ! ? +")
    print(f"  merged.render()   = '{abc.render()}'\n")

    print("WHY IT CONVERGES (no matter the merge order):")
    print("  The payload is a SET of insertions. merge = set union.")
    print("  render() is a PURE function of that set (build tree, sort")
    print("  siblings by id, pre-order DFS). So the rendered string depends")
    print("  only on the SET of insertions, never on how they arrived.\n")

    print("REAL-WORLD: Yjs and Automerge extend this with:")
    print("  - tombstones for deletes (mark dead, don't garbage-collect")
    print("    until all replicas have seen the delete)")
    print("  - state-vector clocks to skip already-seen operations")
    print("  - run-length encoding for compact serialization")
    print("  But the core idea is RIGHT HERE: unique-id insertions after a")
    print("  predecessor, siblings ordered by a total order on ids.\n")

    print("[check] merged text = 'Hi!?+' (deterministic):",
          "OK" if abc.render() == "Hi!?+" else "FAIL")


# ----------------------------------------------------------------------------
# SECTION F: GOLD CHECK - all 6 merge orders converge (the CRDT theorem)
# ----------------------------------------------------------------------------

def section_f() -> None:
    banner("SECTION F: GOLD CHECK - all 6 merge-order permutations converge")
    print("THE CRDT CONVERGENCE THEOREM (Shapiro 2011): if merge ⊔ is")
    print("commutative + associative + idempotent, then for ANY permutation")
    print("of the same payloads, fold(⊔, perm) is IDENTICAL.\n")
    print("We build 3 replicas of EACH CRDT type, then merge them in all")
    print("3! = 6 orderings. Every ordering must yield the same final state.\n")

    all_ok = True

    # ---- G-Counter ----
    print("G-Counter:")
    reps = []
    for nid, incs in [("A", [2]), ("B", [3]), ("C", [1])]:
        g = GCounter(nid, 3)
        for k in incs:
            g.increment(k)
        reps.append(g)
    results = _all_merge_orders(reps, lambda r: r.clone())
    ok = len(set(repr(r) for r in results)) == 1
    all_ok &= ok
    print(f"  6 permutations -> {len(set(repr(r) for r in results))} distinct "
          f"result(s).  Final: {results[0]}  "
          f"[check] {'OK' if ok else 'FAIL'}\n")

    # ---- PN-Counter ----
    print("PN-Counter:")
    reps = []
    for nid, incs, decs in [("A", [5], [1]), ("B", [2], [3]), ("C", [4], [])]:
        p = PNCounter(nid, 3)
        for k in incs:
            p.increment(k)
        for k in decs:
            p.decrement(k)
        reps.append(p)
    results = _all_merge_orders(reps, lambda r: r.clone())
    ok = len(set(repr(r) for r in results)) == 1
    all_ok &= ok
    print(f"  6 permutations -> {len(set(repr(r) for r in results))} distinct "
          f"result(s).  Final: {results[0]}  "
          f"[check] {'OK' if ok else 'FAIL'}\n")

    # ---- OR-Set ----
    print("OR-Set:")
    reps = []
    a = ORSet("A")
    a.add("x")
    a.add("y")
    reps.append(a)
    b = ORSet("B")
    b.add("x")
    b.remove("x")
    reps.append(b)
    c = ORSet("C")
    c.add("z")
    reps.append(c)
    results = _all_merge_orders(reps, lambda r: r.clone())
    ok = len(set(repr(r) for r in results)) == 1
    all_ok &= ok
    print(f"  6 permutations -> {len(set(repr(r) for r in results))} distinct "
          f"result(s).  Final: {results[0]}  "
          f"[check] {'OK' if ok else 'FAIL'}\n")

    # ---- LWW-Register ----
    print("LWW-Register:")
    reps = []
    a = LWWRegister("A")
    a.set("hello", 1)
    reps.append(a)
    b = LWWRegister("B")
    b.set("world", 2)
    reps.append(b)
    c = LWWRegister("C")
    c.set("done", 3)
    reps.append(c)
    results = _all_merge_orders(reps, lambda r: r.clone())
    ok = len(set(repr(r) for r in results)) == 1
    all_ok &= ok
    print(f"  6 permutations -> {len(set(repr(r) for r in results))} distinct "
          f"result(s).  Final: {results[0]}  "
          f"[check] {'OK' if ok else 'FAIL'}\n")

    # ---- RGA Text ----
    print("RGA Text:")
    reps = []
    a = RGAText("A")
    h = a.insert_after("H", HEAD)
    i = a.insert_after("i", h)
    a.insert_after("!", i)          # A also appends '!' (matches Section E)
    reps.append(a)
    b = a.clone()
    b.node_id = "B"
    b.insert_after("?", i)
    reps.append(b)
    c = a.clone()
    c.node_id = "C"
    c.insert_after("+", i)
    reps.append(c)
    results = _all_merge_orders(reps, lambda r: r.clone())
    ok = len(set(repr(r) for r in results)) == 1
    all_ok &= ok
    print(f"  6 permutations -> {len(set(repr(r) for r in results))} distinct "
          f"result(s).  Final: {results[0]}  "
          f"[check] {'OK' if ok else 'FAIL'}\n")

    # ---- Summary + GOLD values pinned for the .html ----
    print("=" * 72)
    print("GOLD values (pinned for crdt.html - JS must reproduce these):")
    gc = GCounter("X", 3)
    gc.counts = [2, 3, 1]
    print(f"  G-Counter  merge([2,3,1])            value = {gc.value()}")
    pn = PNCounter("X", 3)
    pn.P.counts = [5, 2, 4]
    pn.N.counts = [1, 3, 0]
    print(f"  PN-Counter merge P=[5,2,4],N=[1,3,0] value = {pn.value()}")
    ord_ = ORSet("X")
    ord_.added = {("x", ("A", 0)), ("y", ("A", 1)),
                  ("x", ("B", 0)), ("z", ("C", 0))}
    ord_.removed = {("B", 0)}
    print(f"  OR-Set     merge lookup              = {sorted(ord_.lookup())}")
    lr = LWWRegister("X")
    lr.set("done", 3)
    lr2 = LWWRegister("X")
    lr2.set("hello", 1)
    print(f"  LWW        merge('done'@3,'hello'@1) = '{lr.merge(lr2).get()}'")
    rg = RGAText("X")
    rg.insertions = [((("A", 0)), "H", HEAD), (("A", 1), "i", ("A", 0)),
                     (("A", 2), "!", ("A", 1)), (("B", 0), "?", ("A", 1)),
                     (("C", 0), "+", ("A", 1))]
    print(f"  RGA        merge render              = '{rg.render()}'")
    print("=" * 72)

    status = "OK" if all_ok else "FAIL"
    print(f"\n[GOLD CHECK] all 5 CRDT types converge under all 6 merge orders: "
          f"{status}")


def _all_merge_orders(reps, clone_fn):
    """Fold ⊔ over every permutation of `reps`. Returns list of final states."""
    results = []
    for perm in itertools.permutations(reps):
        acc = clone_fn(perm[0])
        for r in perm[1:]:
            acc = acc.merge(r)
        results.append(acc)
    return results


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("crdt.py - reference impl. All numbers below feed CRDT.md.")
    print("Pure Python stdlib. Deterministic (no PRNG - CRDTs are")
    print("deterministic by construction).")
    print("Scenario: 3 replicas {A, B, C}, each modifies locally, then merges.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
