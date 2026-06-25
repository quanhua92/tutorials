"""
quorum_rw.py - Reference implementation of QUORUM-BASED REPLICATION
(Dynamo / Cassandra style): N replicas, R = read quorum, W = write quorum,
with the R + W > N strong-consistency rule and the four repair mechanisms
Dynamo layers on top (sloppy quorum + hinted handoff, read repair,
Merkle-tree anti-entropy).

This is the single source of truth that QUORUM_RW.md is built from. Every
number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 quorum_rw.py

============================================================================
THE INTUITION (read this first) - the whiteboard with N sticky notes
============================================================================
Picture N replicas as N sticky notes pinned in a circle on the wall. Every
copy of a piece of data lives on several of them. Two clients - a WRITER and
a READER - walk up to the wall:

  * the writer circles W notes and writes the new value on each.
  * the reader  circles R notes and reads whichever value is newest.

If those two circles OVERLAP, the reader is guaranteed to see at least one
note the writer just touched, so it sees the fresh value. If they DON'T
overlap, the reader might walk away with stale notes. The whole of quorum
theory collapses to one question: do the circles overlap?

  R + W > N   =>   they MUST overlap (pigeonhole: two circles of sizes R
                   and W inside N notes share at least R + W - N notes).
  R + W <= N  =>   they MIGHT not - and a misaligned reader/writer pair can
                   miss each other entirely. That is "eventual consistency".

So consistency is a DIAL the operator turns by choosing R and W:
  * W = N, R = 1  : writer waits for all N acks (slow writes) but any single
                    replica answers a read (instant reads).
  * W = 1, R = N  : writer returns after 1 ack (instant writes) but reads
                    must ask all N (slow reads).
  * W = R = N/2+1 : the "majority both ways" sweet spot (Paxos/Raft-style).
  * W + R <= N    : fast both ways, but no overlap guarantee -> eventual.

But quorums alone only guarantee that an OVERLAPPING replica EXISTS. Three
real-world problems still bite, and Dynamo has one mechanism for each:

  (1) the overlapping replica might have CRASHED and missed the write.
      -> SLOPPY QUORUM + HINTED HANDOFF: write to the next alive node
         instead, with a sticky-note hint "this really belongs to R3";
         when R3 comes back, forward it. (Section C)
  (2) a replica that missed a write is SELECTED by a later read.
      -> READ REPAIR: the reader notices the stale value (older version)
         and writes the fresh one back on the spot. (Section D)
  (3) nobody ever read or wrote the key, so (2) never fires.
      -> ANTI-ENTROPY (MERKLE TREE): replicas periodically compare a
         compact hash tree of their key range; only the differing leaves
         get synced. (Section E)

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  replica       : one of the N machines holding a copy of the data.
  ring          : replicas ordered 0..N-1 around a consistent-hashing ring.
  coordinator   : the first alive replica in the preference list for a key;
                  it forwards reads/writes to the rest of its quorum.
  preference list: the N replicas in ring order starting at the coordinator.
  W             : write quorum size. A write returns after W replicas ACK.
  R             : read quorum size.  A read returns after R replicas answer.
  strong consist.: R + W > N  (every read overlaps every write).
  eventual      : R + W <= N  (reads may miss writes; converges via repair).
  sloppy quorum : when a preferred replica is DOWN, take the next alive one,
                  so the write still hits W living replicas - but maybe not
                  the TOP W in the preference list.
  hinted handoff: the substitute replica keeps a "hint" recording who the
                  write was really for; on recovery it forwards the write.
  read repair   : during a read, stale replicas (older version) get the
                  fresh value written back by the reader.
  anti-entropy  : background sync. Replicas exchange a MERKLE TREE of their
                  key range and reconcile only the leaves whose hashes differ.
  Merkle tree   : a binary tree of hashes; leaves = hash(key|value), internal
                  nodes = hash(left|right). Two replicas compare ROOTS, then
                  descend only into the subtrees whose hashes differ.
  version       : a per-key counter (or vector clock) tagging each write;
                  reads pick the highest version, repairs target lower ones.

============================================================================
THE PAPER (every formula below verified against this)
============================================================================
  DeCandia, G. et al. (2007). "Dynamo: Amazon's Highly Available Key-value
        Store." SOSP 2007.
        - N, R, W quorum knobs; sloppy quorum + hinted handoff (Sec 4.6);
          read repair + Merkle-tree anti-entropy (Sec 4.7).
  Lakshman, A. & Malik, P. (2010). "Cassandra - a Decentralized Structured
        Storage System." VLDB/DE Bulletin. Same quorum model; CL=ONE/QUORUM/ALL.
  Kleppmann, M. (2017). "Designing Data-Intensive Applications," Ch. 5.
        - Quorums and the R + W > N proof; read repair; anti-entropy.
  Tanenbaum & Van Steen, "Distributed Systems," Sec 7.5.

KEY FORMULAS (all asserted in code below):
    overlap guarantee : R + W > N  =>  |W_set INTERSECT R_set| >= R + W - N >= 1
    min intersection : |W INTERSECT R| >= max(0, W + R - N)        (pigeonhole)
    strong consist.  : W + R > N                            (Dynamo / Cassandra)
    write latency    : waits for the W-th fastest ack      (tail not summed)
    read  latency    : waits for the R-th fastest response; picks max version
    sloppy quorum    : write to first W ALIVE replicas (may exceed top-W)
    hinted handoff   : substitute stores (target_id, value); forwards on recovery
    read repair      : for each replica r in read set with ver(r) < max_ver:
                         write fresh value back to r
    merkle compare   : if root(A) != root(B): descend; sync leaves that differ.
"""

from __future__ import annotations

import hashlib
from itertools import combinations

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# The deterministic scenario. Single source of truth for every section.
# Five replicas R0..R4 arranged in a ring (consistent-hashing order).
# ----------------------------------------------------------------------------
N = 5
REPLICAS = ["R0", "R1", "R2", "R3", "R4"]


# ============================================================================
# 1. REFERENCE IMPLEMENTATIONS  (the code QUORUM_RW.md walks through)
# ============================================================================

def preference_list(coordinator: int, n: int = N) -> list[int]:
    """The N replicas in ring order, starting from `coordinator`.

    Dynamo model: the consistent-hash ring places every replica at a
    position; the coordinator for a key is the first replica CLOCKWISE
    after the key's hash. The preference list is that coordinator followed
    by the next N-1 replicas clockwise, wrapping around.
    """
    return [(coordinator + i) % n for i in range(n)]


def write_set(coordinator: int, w: int, n: int = N) -> list[int]:
    """Replicas contacted by a write: the first W in the preference list."""
    return preference_list(coordinator, n)[:w]


def read_set(coordinator: int, r: int, n: int = N) -> list[int]:
    """Replicas contacted by a read: the first R in the preference list."""
    return preference_list(coordinator, n)[:r]


def intersect(a: list[int], b: list[int]) -> list[int]:
    """Sorted intersection of two replica-id lists."""
    return sorted(set(a) & set(b))


def min_intersection(w: int, r: int, n: int = N) -> int:
    """Minimum guaranteed |W_set INTERSECT R_set| over ALL placements of the
    W-set and R-set into the N replicas (the pigeonhole lower bound).

    >= 1  iff  R + W > N  (the strong-consistency condition).
    This is the WORST case - coordinator-aligned reads/writes usually do
    better, but the GUARANTEE is this floor.
    """
    return max(0, w + r - n)


def strong_consistency(w: int, r: int, n: int = N) -> bool:
    """The Dynamo quorum strong-consistency condition."""
    return w + r > n


def sloppy_write(coordinator: int, w: int, down: set[int],
                 n: int = N) -> tuple[list[int], dict[int, int]]:
    """SLOPPY QUORUM write.

    Walk the preference list; take the first W ALIVE replicas (skip `down`).
    Any alive replica that is OUTSIDE the top-W preference list becomes a
    HINT: it stores the write tagged with the id of the down replica it is
    standing in for. Returns (chosen_replicas, hints) where
    hints[substitute_id] -> original_target_id.
    """
    pref = preference_list(coordinator, n)
    preferred_top_w = set(pref[:w])
    chosen: list[int] = []
    hints: dict[int, int] = {}
    # who in the top-W are we missing because they are down?
    missing = [r for r in pref[:w] if r in down]
    miss_iter = iter(missing)
    for r in pref:
        if len(chosen) >= w:
            break
        if r in down:
            continue
        chosen.append(r)
        # if this replica is a substitute (alive, but outside the top-W),
        # attribute the hint to the next missing preferred replica.
        if r not in preferred_top_w:
            try:
                hints[r] = next(miss_iter)
            except StopIteration:
                pass
    return chosen, hints


def read_repair(read_responses: dict[int, tuple[int, str]]) -> dict[int, str]:
    """READ REPAIR.

    read_responses: {replica_id: (version, value)} from the R replicas
    that answered. The reader picks the highest version; any replica whose
    version is strictly less gets a repair WRITE of the fresh value.
    Returns {stale_replica_id: fresh_value}.
    """
    max_ver = max(v for v, _ in read_responses.values())
    fresh_val = next(val for ver, val in read_responses.values() if ver == max_ver)
    return {r: fresh_val for r, (ver, _) in read_responses.items() if ver < max_ver}


# ----------------------------------------------------------------------------
# Merkle-tree anti-entropy (Section E)
# ----------------------------------------------------------------------------

def leaf_hash(key: str, value: str) -> str:
    """Hash a (key, value) leaf. Dynamo uses MD5 of the value; we hash
    key|value for stability across renames. Truncated to 8 hex chars for
    readable printing (the .py and .html use the SAME truncation)."""
    return hashlib.sha1(f"{key}|{value}".encode()).hexdigest()[:8]


def merkle_tree(keys: list[str], store: dict[str, str]) -> tuple[list[str], str]:
    """Build a binary Merkle tree over `keys` (in given order, padded to a
    power of 2 with empty leaves). Returns (leaf_hashes, root_hash).

    Internal node = hash(left || right) using the SAME truncation.
    The tree is a flat list of nodes, level by level; root is the last elem.
    """
    # pad to power of 2
    k = 1
    while k < len(keys):
        k *= 2
    padded = keys + ["__empty__"] * (k - len(keys))
    leaves = [leaf_hash(key, "" if key == "__empty__" else store.get(key, ""))
              for key in padded]
    level = leaves[:]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            nxt.append(hashlib.sha1(f"{level[i]}|{level[i+1]}".encode())
                       .hexdigest()[:8])
        level = nxt
    return leaves, level[0]


def merkle_diff(a_leaves: list[str], b_leaves: list[str], keys: list[str]
                ) -> list[str]:
    """Compare two Merkle trees leaf-by-leaf and return the keys whose leaves
    differ. (In a real system you'd compare roots, then descend only into
    differing subtrees - here we materialize the leaf diff for printing.)
    """
    return [keys[i] for i in range(len(keys))
            if a_leaves[i] != b_leaves[i]]


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def ids(xs: list[int]) -> str:
    return "{" + ", ".join(REPLICAS[x] for x in xs) + "}"


# ============================================================================
# SECTION A: quorum basics - the R + W > N overlap guarantee
# ============================================================================

def section_a():
    banner("SECTION A: quorum basics - N=5, R=3, W=3  (R + W > N => overlap)")
    print("Five replicas on a ring. A write contacts W of them; a read contacts")
    print("R. If those two sets OVERLAP, the reader sees the fresh value.\n")
    print("Fix N=5. A write of W=3 to coordinator R0 contacts the first 3 of the")
    print("preference list; a read of R=3 contacts the first 3 too:\n")

    coord = 0
    W, R = 3, 3
    pref = preference_list(coord)
    ws = write_set(coord, W)
    rs = read_set(coord, R)
    both = intersect(ws, rs)
    print(f"  ring (clockwise from R0): {' '.join(REPLICAS[r] for r in pref)}")
    print(f"  preference list of R0   : {ids(pref)}")
    print(f"  write set W = {W}        : {ids(ws)}")
    print(f"  read  set R = {R}        : {ids(rs)}")
    print(f"  W INTERSECT R           : {ids(both)}  (|intersection| = {len(both)})\n")

    mn = min_intersection(W, R)
    print(f"R + W = {R} + {W} = {R+W}  >  N = {N}   =>   STRONG CONSISTENCY.")
    print(f"Pigeonhole lower bound on |W INTERSECT R| = R + W - N = "
          f"{R}+{W}-{N} = {mn}.")
    print(f"This configuration actually achieves |intersection| = {len(both)} "
          f">= {mn}: OK (the bound holds).\n")
    print("The guarantee is the FLOOR, not the typical case. Coordinator-")
    print("aligned reads/writes (both start at R0) overlap in {R0,R1,R2}; an")
    print("adversarial placement could shrink the overlap to exactly 1 - but")
    print("never 0. That is what 'strong' means here.\n")
    print(f"[check] |W INTERSECT R| = {len(both)} >= min_intersection = {mn}:  "
          f"{'OK' if len(both) >= mn else 'FAIL'}")
    assert len(both) >= mn


# ============================================================================
# SECTION B: tunable consistency - the four classic configs
# ============================================================================

def section_b():
    banner("SECTION B: tunable consistency - the R/W dial (4 configs)")
    print("Same N=5 ring, same coordinator R0. The operator chooses (W, R).")
    print("R + W > N => strong (read overlaps every prior write).")
    print("R + W <= N => eventual (an overlap-MISSING placement exists).\n")
    print("| config      | W | R | R+W | strong? | write set | read set | "
          "|coord-aligned intersection| min |")
    print("|-------------|---|---|-----|---------|-----------|----------|"
          "---------------------------|-----|")

    coord = 0
    configs = [
        ("fast writes", 1, 5),
        ("fast reads",  5, 1),
        ("balanced",    3, 3),
        ("eventual",    2, 2),
    ]
    for name, W, R in configs:
        ws = write_set(coord, W)
        rs = read_set(coord, R)
        both = intersect(ws, rs)
        strong = strong_consistency(W, R)
        mn = min_intersection(W, R)
        tag = "yes" if strong else "NO (R+W<=N)"
        print(f"| {name:<11} | {W} | {R} |  {W+R} | {tag:<7} | "
              f"{ids(ws):<9} | {ids(rs):<8} | {ids(both):<25} |  {mn}  |")
    print()
    print("Read the columns: 'strong?' tracks R+W vs N exactly. 'min' is the")
    print("pigeonhole floor on |W INTERSECT R|. For the first THREE configs")
    print("min >= 1 -> ANY read quorum and write quorum must share a replica,")
    print("so a reader ALWAYS sees the latest write.\n")

    print("The EVENTUAL row is the trap. Coordinator-aligned, {R0,R1} and")
    print("{R0,R1} DO overlap - but the guarantee is GONE, because there EXIST")
    print("disjoint quorums. Demonstration: write to {R0,R1}, then a reader")
    print("whose preference list starts at R2 picks {R2,R3}:\n")
    ws = write_set(0, 2)
    rs_alt = read_set(2, 2)
    both = intersect(ws, rs_alt)
    print(f"  write set (coord R0): {ids(ws)}")
    print(f"  read  set (coord R2): {ids(rs_alt)}   <- a different coordinator")
    print(f"  W INTERSECT R        : {ids(both)}   |intersection| = {len(both)}")
    print("\nThe reader missed BOTH replicas that got the write. It returns the")
    print("STALE value. R+W=4<=5 means strong consistency is NOT guaranteed -")
    print("even though a coordinator-aligned placement would have overlapped.")
    print("Cassandra exposes this as CL=ONE/QUORUM/ALL: QUORUM forces R+W>N.\n")
    ok = (len(both) == 0) and (not strong_consistency(2, 2))
    print(f"[check] disjoint quorums exist iff NOT strong: "
          f"|intersection|=0 and strong=False -> "
          f"{'OK' if ok else 'FAIL'}")
    assert ok


# ============================================================================
# SECTION C: sloppy quorum + hinted handoff
# ============================================================================

def section_c():
    banner("SECTION C: sloppy quorum + hinted handoff (replica DOWN)")
    print("A preferred replica is DOWN. Dynamo still wants W acks, so it")
    print("walks PAST the dead node and writes to the next ALIVE one - the")
    print("\"sloppy\" part. The substitute keeps a HINT recording which dead")
    print("node it stood in for; on recovery, it forwards the write.\n")
    print("Scenario: N=5, W=3, coordinator R0. Preference list [R0..R4].")
    print("R1 is DOWN. The top-W preference is {R0,R1,R2}; R1 must be skipped.\n")

    W = 3
    down = {1}
    coord = 0
    chosen, hints = sloppy_write(coord, W, down)
    pref = preference_list(coord)
    print(f"  preference list   : {ids(pref)}")
    print(f"  down              : {ids(sorted(down))}")
    print(f"  chosen (sloppy W) : {ids(chosen)}   <- first {W} ALIVE replicas")
    print("  hints             : "
          + (", ".join(f"{REPLICAS[sub]} holds hint for {REPLICAS[orig]}"
                       for sub, orig in hints.items()) if hints else "(none)"))
    print()
    print("Walk: R0 (alive, take) -> R1 (DOWN, skip) -> R2 (alive, take) ->")
    print("R3 (alive, take; that is W=3). R3 is OUTSIDE the top-W preference")
    print("list {{R0,R1,R2}}, so it is a SUBSTITUTE: it records a hint pointing")
    print("at the dead replica it replaced (R1). The write returns after 3")
    print("acks even though R1 is unreachable - availability preserved.\n")

    # recovery
    print("R1 recovers. R3 (via gossip) sees R1 alive again and FORWARDS the")
    print("hinted write, then discards the hint:\n")
    state = {r: None for r in range(N)}
    for r in chosen:
        state[r] = "v1"
    print("  before handoff: " + ", ".join(f"{REPLICAS[r]}={state[r] or '---'}"
                                           for r in range(N)))
    for sub, orig in hints.items():
        state[orig] = state[sub]
    print("  after  handoff: " + ", ".join(f"{REPLICAS[r]}={state[r] or '---'}"
                                           for r in range(N)))
    print("\nNow R1 has v1. Hinted handoff is what makes sloppy quorum INVISIBLE")
    print("to the application - the data ends up on the RIGHT replicas, just")
    print("lazily. Without handoff, the substitute would keep the data forever")
    print("and the owner's replica count would silently grow.\n")
    ok = state[1] == "v1" and len(chosen) == W
    print(f"[check] R1 has v1 after handoff AND sloppy write hit {W} replicas:  "
          f"{'OK' if ok else 'FAIL'}")
    assert ok


# ============================================================================
# SECTION D: read repair
# ============================================================================

def section_d():
    banner("SECTION D: read repair - stale replica fixed on the fly")
    print("A read contacts R replicas. If one of them missed a recent write,")
    print("its VERSION is lower. The reader detects this and writes the fresh")
    print("value back - that is read repair. It is the primary anti-entropy")
    print("mechanism for keys that are READ OFTEN.\n")
    print("Scenario: a write at version 2 reached {R0, R1, R3} but R2 missed")
    print("it (still version 1, stale value). A read of R=3 picks {R0, R1, R2}.\n")

    # replica -> (version, value)
    responses = {
        0: (2, "v2"),
        1: (2, "v2"),
        2: (1, "v1-stale"),
    }
    print("  read responses (replica -> (version, value)):")
    for r in sorted(responses):
        ver, val = responses[r]
        print(f"    {REPLICAS[r]}: (version={ver}, value={val})")
    print()

    stale = read_repair(responses)
    max_ver = max(v for v, _ in responses.values())
    fresh = next(val for ver, val in responses.values() if ver == max_ver)
    print(f"  highest version = {max_ver}, fresh value = '{fresh}'")
    print(f"  stale replicas (version < {max_ver}): "
          + (", ".join(f"{REPLICAS[r]} (will be repaired with '{fresh}')"
                       for r in stale) if stale else "(none)"))
    print()
    print("Read repair WRITES 'v2' back to R2 before returning to the client.")
    print("The reader got the right answer AND fixed a divergence, in one round")
    print("trip. Trade-off (Dynamo paper Sec 4.7): read repair adds a write to")
    print("the read path. For keys that are rarely read, the background Merkle")
    print("anti-entropy of Section E is cheaper than waiting for a read.\n")

    # apply the repair, then a FOLLOW-UP read sees no staleness
    fixed = dict(responses)
    for r, val in stale.items():
        fixed[r] = (max_ver, val)
    stale_after = read_repair(fixed)
    ok = stale == {2: "v2"} and stale_after == {}
    print(f"[check] one replica repaired on first read, ZERO stale on second:  "
          f"{'OK' if ok else 'FAIL'}")
    assert ok


# ============================================================================
# SECTION E: anti-entropy (Merkle tree)
# ============================================================================

def section_e():
    banner("SECTION E: anti-entropy - Merkle tree comparison")
    print("Background sync: two replicas exchange a MERKLE TREE (hash tree) of")
    print("their key range and reconcile only the leaves whose hashes differ.")
    print("Comparing two ROOT hashes is O(1); descending into mismatched")
    print("subtrees pins the divergence to a small set of keys. Dynamo uses")
    print("Merkle trees over the keyspace partition each replica owns.\n")
    print("Scenario: 4 keys. Replica A has the truth; replica B has a STALE")
    print("value for k2 (missed a write). Everything else is identical.\n")

    keys = ["k1", "k2", "k3", "k4"]
    store_a = {"k1": "v1", "k2": "v2",  "k3": "v3", "k4": "v4"}
    store_b = {"k1": "v1", "k2": "v0",  "k3": "v3", "k4": "v4"}   # k2 stale

    leaves_a, root_a = merkle_tree(keys, store_a)
    leaves_b, root_b = merkle_tree(keys, store_b)

    print("Leaf hashes  = sha1('key|value')[:8];  internal = sha1(left|right)[:8].")
    print("Padded to a power of 2 (4 keys -> 4 leaves -> tree of depth 2).\n")
    print("  level 2 (root)   level 1 (internal)        level 0 (leaves)")
    print("  --------------------------------   -----------------------")
    # internal nodes
    int_a = [hashlib.sha1(f"{leaves_a[0]}|{leaves_a[1]}".encode()).hexdigest()[:8],
             hashlib.sha1(f"{leaves_a[2]}|{leaves_a[3]}".encode()).hexdigest()[:8]]
    int_b = [hashlib.sha1(f"{leaves_b[0]}|{leaves_b[1]}".encode()).hexdigest()[:8],
             hashlib.sha1(f"{leaves_b[2]}|{leaves_b[3]}".encode()).hexdigest()[:8]]
    print(f"  A:  root={root_a}   [{int_a[0]}, {int_a[1]}]   {leaves_a}")
    print(f"  B:  root={root_b}   [{int_b[0]}, {int_b[1]}]   {leaves_b}")
    print()
    print("Step 1  compare roots: " +
          (f"{root_a} != {root_b} -> DIVERGE, descend.\n"
           if root_a != root_b else "EQUAL -> nothing to do.\n"))
    print("Step 2  compare level-1 nodes:")
    for i in range(2):
        tag = "SAME" if int_a[i] == int_b[i] else "DIFFER -> descend"
        sub = f"{{{keys[2*i]},{keys[2*i+1]}}}"
        print(f"          subtree over {sub}: A={int_a[i]}  B={int_b[i]}  [{tag}]")
    print()
    print("Step 3  descend into the differing subtree {k1,k2}, compare leaves:")
    diffs = merkle_diff(leaves_a, leaves_b, keys)
    print("  full leaf diff: " + (", ".join(diffs) if diffs else "(none)"))
    print(f"  -> sync {len(diffs)} key(s): {diffs}\n")
    print("B copies A's value for the differing key(s), recomputes its tree,")
    print("roots now match. Cost: O(log K) comparisons + the differing keys,")
    print("NOT the whole keyspace. That is the whole point of the Merkle tree:")
    print("compact representation, cheap divergence detection.\n")

    # repair B
    store_b_fixed = dict(store_b)
    for k in diffs:
        store_b_fixed[k] = store_a[k]
    _, root_b_fixed = merkle_tree(keys, store_b_fixed)
    ok = (root_a != root_b) and (root_a == root_b_fixed) and diffs == ["k2"]
    print(f"[check] roots differ before sync, EQUAL after, only k2 needed:  "
          f"{'OK' if ok else 'FAIL'}")
    assert ok

    print("\nGOLD (pinned for quorum_rw.html):")
    print(f"  root_A = {root_a}")
    print(f"  root_B = {root_b}   (stale)")
    print(f"  root_B_after_sync = {root_b_fixed}   (== root_A)")
    print(f"  diff keys = {diffs}")
    return {"root_a": root_a, "root_b": root_b, "root_b_fixed": root_b_fixed,
            "diffs": diffs}


# ============================================================================
# GOLD CHECK: R + W > N  =>  EVERY read quorum overlaps EVERY write quorum
# ============================================================================

def gold_check():
    banner("GOLD CHECK: R + W > N  =>  every W-set intersects every R-set")
    print("Brute-force the strong-consistency claim. For N=5, R=3, W=3,")
    print("enumerate EVERY way to choose a W-set of size 3 and an R-set of")
    print("size 3, and check they share at least one replica. (In the real")
    print("system these would be coordinator-aligned, but the GUARANTEE must")
    print("hold even for the adversarial placements enumerated here.)\n")
    W, R = 3, 3
    all_w = list(combinations(range(N), W))
    all_r = list(combinations(range(N), R))
    total = len(all_w) * len(all_r)
    min_seen = N
    bad = []
    disjoint_examples = []
    for ws in all_w:
        for rs in all_r:
            ov = len(set(ws) & set(rs))
            min_seen = min(min_seen, ov)
            if ov == 0:
                bad.append((ws, rs))
                if len(disjoint_examples) < 2:
                    disjoint_examples.append((ws, rs))
    floor = min_intersection(W, R)
    print(f"  N={N}, W={W}, R={R}: {len(all_w)} W-sets x {len(all_r)} R-sets "
          f"= {total} pairs enumerated.")
    print(f"  pigeonhole floor R+W-N = {floor}.")
    print(f"  minimum |W INTERSECT R| observed over all {total} placements = "
          f"{min_seen}.")
    print(f"  disjoint (|intersection|=0) placements = {len(bad)} / {total}.")
    print()
    if W + R > N:
        print(f"  R+W={W+R} > N={N} -> strong consistency. Expect 0 disjoint.")
        print(f"  [check] GOLD: min_intersection >= 1 for all {total} pairs:  "
              f"{'OK' if not bad else 'FAIL'}")
        assert not bad
    else:
        print(f"  R+W={W+R} <= N={N} -> eventual. Disjoint placements exist.")
        print("  [check] GOLD holds vacuously (we picked the strong case):  OK")
    # also demonstrate the boundary: R+W=N has disjoint quorums
    print()
    print("Boundary sanity: with W=2,R=3 (R+W=N=5, the threshold), the")
    print("pigeonhole floor is 0 and disjoint placements DO exist:")
    W2, R2 = 2, 3
    found = next(((set(ws), set(rs)) for ws in combinations(range(N), W2)
                  for rs in combinations(range(N), R2)
                  if not (set(ws) & set(rs))), None)
    if found:
        ws, rs = found
        print(f"  W-set {ids(sorted(ws))} and R-set {ids(sorted(rs))} are "
              f"DISJOINT (R+W=N={N}).")
    print("  One replica more on either side and we are back at R+W>N (strong).")
    print(f"\nGOLD scalar: min_intersection(3,3,5) = {floor}  (must be 1)")
    assert floor == 1
    print("[check] gold scalar reproduces from min_intersection():  OK")
    return "OK" if not bad else "FAIL"


# ============================================================================
# main
# ============================================================================

def main():
    print("quorum_rw.py - reference impl. All numbers below feed QUORUM_RW.md.")
    print("Pure Python stdlib (hashlib). Scenario: N=5 replicas R0..R4.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
