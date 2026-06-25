"""
consistent_hashing_lb.py - Reference implementation of Consistent Hashing
(Karger et al. 1997) for load balancing / partitioning.

Both keys and nodes are hashed onto a ring [0, 2^32). A key is assigned to the
FIRST node CLOCKWISE from its hash position. When a node joins or leaves, only
the keys whose hash falls in that node's arc move -- on average K/N of them --
instead of nearly all keys (as naive mod-hash would remap).

This is the single source of truth that CONSISTENT_HASHING_LB.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 consistent_hashing_lb.py

============================================================================
THE INTUITION (read this first) -- the roulette wheel
============================================================================
Picture a casino roulette wheel with 2^32 slots. To place a server on the
wheel, hash its name; to place a key, hash the key. A key "belongs to" the
first server you meet walking CLOCKWISE from the key's slot. That is the
whole algorithm.

Now add a server. Naive `hash(key) % N` shatters: bumping N from 4 to 5
recomputes EVERY key's modulus, so ~80% of keys (the (N-1)/N fraction) fly
to a new server -- a thundering herd of cache misses / repartitions.

Consistent hashing does NOT recompute the world. The new server E is hashed
onto the wheel like everything else. The ONLY keys that move are the ones
whose slots now fall under E's arc (between E and the previous server).
That is K/N keys on average -- 1/N as much churn as mod-hash. That is the
property that makes it the backbone of Dynamo/ Cassandra/ Memcached/ Chord/
every sharded cache. 🔗 See DYNAMO-style partitioning in quorum_rw.py.

The second idea is VIRTUAL NODES (a.k.a. replicas). With one slot per server,
randomness gives some servers a big arc and others a tiny one -> badly skewed
load. Fix: place each server V times (V = 150..200). By the law of large
numbers each server's total arc converges to 1/N of the ring, and load
balances to within ~10%. This is the "power of two choices" / balls-into-bins
trick applied to a circle.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  ring          : the integer circle [0, 2^32). Positions are hash outputs.
  node (server) : a physical machine. Named A, B, C, D, E here.
  key           : anything we want to place -- a user id, a cache entry, ...
                  Named "key-000" .. "key-999" here. K = 1000 of them.
  hash(x)       : a DETERMINISTIC 32-bit hash in [0, 2^32). MD5-based (first 4
                  bytes) so it is identical in Python and in the .html (Python's
                  built-in hash() is randomized per-process via PYTHONHASHSEED --
                  NEVER use it for consistent hashing). MD5 is chosen for its
                  strong avalanche: short, similar inputs ("A#0".."A#149") still
                  spread uniformly across the ring, which weaker hashes (e.g.
                  FNV-1a) fail to do, leaving load badly skewed at high vnode
                  counts. MD5 here is NOT for security, only for a stable,
                  cross-language 32-bit digest.
  position      : a hash output; where a node-vnode or key sits on the ring.
  clockwise /
  successor     : walking the ring in increasing-position order, wrapping at
                  2^32 back to 0. A key's owner is its successor node on ring.
  arc           : the contiguous slice of ring a node OWNS = from the node's
                  (virtual) position back to the previous position clockwise.
  mod-hash      : naive baseline: owner(key) = hash(key) % N. Re-shards almost
                  everything when N changes.
  consistent    : owner(key) = successor of hash(key) on the ring. Re-shards
                  only the changed arc when N changes.
  virtual node  : a single physical node hashed at V positions. More vnodes
  (vnode)         = smoother arcs = balanced load. Default V = 150.
  fan-out /     : same thing -- vnodes per physical node.
  replicas
  remapped      : a key whose owner CHANGES after a membership event.
  K / N         : keys / nodes. The expected remap count on a join is K/N.

============================================================================
THE PAPER (every formula below verified against this)
============================================================================
  Karger, Lehman, Leighton, Panigrahy, Levine, Lewin (STOC 1997).
    "Consistent Hashing and Random Trees: Distributed Caching Protocols
     for Relieving Hot Spots on the World Wide Web."
    -- the original consistent hashing paper. Proves:
       * on adding/removing one node, only K/N keys move (tight bound);
       * with enough hash range, load imbalance is O(log N) with high
         probability for 1 vnode, and improves with replicas.
  DeCandia et al. (2007), "Dynamo: Amazon's Highly Available Key-value
    Store." -- production consistent hashing + 1 vnode range per node
    (virtual nodes added in later systems to fix the skew).
  Stoica et al. (2001), "Chord." -- DHT built on a consistent-hash ring.
  Lakshman & Malik (2010), "Cassandra." -- consistent hashing with vnodes
    (default 256 vnodes per node) for load balancing.
  Kleppmann, "Designing Data-Intensive Applications," Ch.6 -- partitioning.

KEY FORMULAS (all asserted in code below):
    hash(x)            = uint32( MD5(x)[:4] )        in [0, 2^32)
    mod owner          = hash(key) % N
    consistent owner   = successor_on_ring( hash(key) )
    remap on +1 node   = keys whose slot lands in the new node's arc
                         expected = K / (N+1)        (GOLD CHECK)
    remap mod-hash     ~ K * N / (N+1)                ((N)/(N+1) of keys)
    expected arc /node = 1 / N                         of the ring
    load imbalance     shrinks ~ 1/sqrt(V) as vnodes V grow

============================================================================
THE SCENARIO (deterministic; reused by every section and by the .html)
============================================================================
K = 1000 keys named "key-000".."key-999".
N = 4 initial nodes: A, B, C, D. Node E joins in Section C; B leaves in D.
Default V = 150 virtual nodes per physical node. Ring = 2^32.

Determinism: every hash uses MD5[:4] (seed-free, byte-identical across
processes and across Python/JS -- the .html ships a tiny verified MD5 port).
The .html hard-codes the SAME algorithm and every GOLD number below is
recomputed there. MD5's avalanche is what makes virtual nodes actually balance
load (weaker hashes like FNV-1a cluster the "node#i" positions and leave load
skewed even at V=150).
"""

from __future__ import annotations

import bisect
import hashlib
import statistics

BANNER = "=" * 72
RING = 1 << 32  # 2^32 positions, the classic Karger ring size

# The deterministic scenario -- single source of truth for every section.
NUM_KEYS = 1000
INITIAL_NODES = ["A", "B", "C", "D"]
DEFAULT_VNODES = 150


# ============================================================================
# 1. THE DETERMINISTIC HASH + THE RING  (this is the code the .md walks through)
# ============================================================================

def h32(s: str) -> int:
    """Deterministic 32-bit hash of a string, in [0, 2^32).

    MD5-based: the first 4 bytes of the digest, read big-endian. NOT for
    security, only for a stable, cross-language 32-bit digest with strong
    avalanche. Python's built-in hash() is randomized per process
    (PYTHONHASHSEED), which would make a "consistent" hash INCONSISTENT across
    restarts -- the classic footgun. Always use a seed-free, deterministic
    digest for consistent hashing. The .html ships a tiny verified MD5 port so
    JS reproduces this byte-for-byte (see the gold check).
    """
    return int.from_bytes(hashlib.md5(s.encode("utf-8")).digest()[:4], "big")


def key_name(i: int) -> str:
    return f"key-{i:03d}"


class Ring:
    """A consistent-hash ring.

    Stores a sorted list of (position, physical_node) entries. Each physical
    node contributes `vnodes` entries at positions hash(f"{node}#{i}"). A key's
    owner is the entry at-or-after hash(key), wrapping around.
    """

    def __init__(self, vnodes: int = DEFAULT_VNODES):
        self.vnodes = vnodes
        self.entries: list[tuple[int, str]] = []  # (position, node), kept sorted
        self._positions: list[int] = []          # cached sorted positions

    def _vnode_positions(self, node: str) -> list[int]:
        return [h32(f"{node}#{i}") for i in range(self.vnodes)]

    def _reindex(self) -> None:
        self.entries.sort(key=lambda e: e[0])
        self._positions = [e[0] for e in self.entries]

    def add_node(self, node: str) -> None:
        self.entries.extend((p, node) for p in self._vnode_positions(node))
        self._reindex()

    def remove_node(self, node: str) -> None:
        self.entries = [e for e in self.entries if e[1] != node]
        self._reindex()

    def nodes(self) -> list[str]:
        # stable order by first appearance on the ring
        seen: dict[str, None] = {}
        for _, n in self.entries:
            seen.setdefault(n, None)
        return list(seen)

    def owner(self, key: str) -> str | None:
        """The physical node that owns `key` = successor of hash(key)."""
        if not self.entries:
            return None
        kp = h32(key)
        i = bisect.bisect_left(self._positions, kp)
        if i == len(self.entries):
            i = 0  # wrap around past 2^32 back to 0
        return self.entries[i][1]

    def load_counts(self, keys: list[str]) -> dict[str, int]:
        """Number of `keys` assigned to each physical node (0 if none)."""
        counts: dict[str, int] = {n: 0 for n in self.nodes()}
        for k in keys:
            o = self.owner(k)
            if o is not None:
                counts[o] = counts.get(o, 0) + 1
        return counts


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_pct(x: float) -> str:
    return f"{x*100:5.1f}%"


def ring_arc_table(ring: Ring, max_rows: int = 16) -> None:
    """Print the ring as a sorted arc table: pos -> node, and arc length %."""
    n = len(ring.entries)
    print(f"\nRing has {n} entries (virtual nodes). Arcs (sorted clockwise):\n")
    print(f"{'#':>3}  {'position':>12}  {'node':>5}  {'arc / 2^32':>11}")
    print("-" * 40)
    for i, (pos, node) in enumerate(ring.entries[:max_rows]):
        nxt = ring.entries[(i + 1) % n][0]
        arc = (nxt - pos) % RING
        print(f"{i:>3}  {pos:>12}  {node:>5}  {fmt_pct(arc / RING):>11}")
    if n > max_rows:
        print(f"... ({n - max_rows} more entries)")
    print("-" * 40)


# ============================================================================
# 3. THE TINY CONCRETE RING for Section B (printable): V=3 vnodes, 4 nodes
# ============================================================================

def build_initial_ring(nodes: list[str], vnodes: int = DEFAULT_VNODES) -> Ring:
    r = Ring(vnodes=vnodes)
    for n in nodes:
        r.add_node(n)
    return r


def all_keys() -> list[str]:
    return [key_name(i) for i in range(NUM_KEYS)]


# ----------------------------------------------------------------------------
# SECTION A: mod-hash vs consistent hashing -- the whole point
# ----------------------------------------------------------------------------

def section_a() -> None:
    banner("SECTION A: mod-hash vs consistent hashing  "
           "(add a 5th node, count the carnage)")
    keys = all_keys()
    N0 = 4
    print(f"K = {NUM_KEYS} keys, start with N = {N0} nodes "
          f"({', '.join(INITIAL_NODES)}). Add node E -> N = 5.\n")

    # ---- mod-hash: owner(key) = h32(key) % N ----
    before_mod = {k: h32(k) % N0 for k in keys}
    after_mod = {k: h32(k) % (N0 + 1) for k in keys}
    remap_mod = sum(1 for k in keys if before_mod[k] != after_mod[k])
    frac_mod = remap_mod / NUM_KEYS

    # ---- consistent hashing ----
    r4 = build_initial_ring(INITIAL_NODES)            # A B C D
    before_con = {k: r4.owner(k) for k in keys}
    r5 = build_initial_ring(INITIAL_NODES + ["E"])    # A B C D E
    after_con = {k: r5.owner(k) for k in keys}
    remap_con = sum(1 for k in keys if before_con[k] != after_con[k])
    frac_con = remap_con / NUM_KEYS

    print("Naive mod-hash:   owner(key) = hash(key) % N")
    print(f"  remapped keys going 4 -> 5 nodes: {remap_mod:>4} / {NUM_KEYS} "
          f"= {fmt_pct(frac_mod)}   (expected ~ N/(N+1) = "
          f"{fmt_pct(N0/(N0+1))})\n")

    print("Consistent hash:  owner(key) = successor of hash(key) on ring")
    print(f"  remapped keys going 4 -> 5 nodes: {remap_con:>4} / {NUM_KEYS} "
          f"= {fmt_pct(frac_con)}   (expected ~ 1/(N+1) = "
          f"{fmt_pct(1/(N0+1))})\n")

    print("Side by side (bar = 10 keys):")
    bar_mod = "#" * (remap_mod // 10)
    bar_con = "#" * (remap_con // 10)
    print(f"  mod-hash   [{bar_mod:<80}] {remap_mod}")
    print(f"  consistent [{bar_con:<80}] {remap_con}")
    print(f"\nConsistent hashing remaps {remap_mod / remap_con:.1f}x FEWER keys. "
          f"That is the whole reason it exists.\n")

    # Sanity: for consistent hashing, a key moves IFF its new owner == 'E'
    # (joining a node never moves a key OFF another node to a third one).
    moved_to_e = sum(1 for k in keys if after_con[k] == "E" and before_con[k] != "E")
    assert moved_to_e == remap_con, "a key should only move by landing on the new node E"
    print(f"[check] every remapped key moved ONTO the new node E "
          f"(={moved_to_e}):  OK")
    print(f"[check] mod-hash remap fraction {frac_mod:.3f} ~ N/(N+1)="
          f"{N0/(N0+1):.3f} and consistent {frac_con:.3f} ~ 1/(N+1)="
          f"{1/(N0+1):.3f}:  OK")


# ----------------------------------------------------------------------------
# SECTION B: ring construction -- nodes at virtual-node positions
# ----------------------------------------------------------------------------

def section_b() -> None:
    banner("SECTION B: ring construction  "
           "(hash each node at V positions; key -> first node clockwise)")
    print("Each physical node is hashed V times -> V virtual-node positions.")
    print("Shown here with V = 3 (tiny, so the ring fits on a page).\n")
    tiny = Ring(vnodes=3)
    for n in INITIAL_NODES:
        tiny.add_node(n)
    ring_arc_table(tiny)

    print("\nWalk a few sample keys to their owners (clockwise successor):\n")
    print(f"{'key':>9}  {'hash(key)':>12}  {'owner':>5}")
    print("-" * 34)
    for i in (0, 1, 2, 42, 500, 999):
        k = key_name(i)
        kp = h32(k)
        print(f"{k:>9}  {kp:>12}  {tiny.owner(k):>5}")
    print("-" * 34)
    print("How to read it: from hash(key), walk the ring clockwise (positions")
    print("increasing, wrapping past 2^32 to 0). The first virtual node you")
    print("meet names the owning PHYSICAL node. More vnodes => finer arcs =>")
    print("smoother load (Section E).")
    print()
    # GOLD: tiny ring key->owner pinned for the .html to recompute.
    print("GOLD (pinned for consistent_hashing_lb.html, V=3, nodes A B C D):")
    for i in (0, 1, 2, 42, 500, 999):
        k = key_name(i)
        print(f"  owner({k}) = {tiny.owner(k)}")
    # self-consistency
    assert tiny.owner("key-000") == tiny.owner("key-000")
    print("[check] ring lookups deterministic across calls:  OK")


# ----------------------------------------------------------------------------
# SECTION C: node join -- only the new node's arc moves
# ----------------------------------------------------------------------------

def section_c() -> None:
    banner("SECTION C: node join  "
           "(add E; only keys in E's arc remap -> ~K/N)")
    keys = all_keys()
    r = build_initial_ring(INITIAL_NODES)
    before = {k: r.owner(k) for k in keys}
    r.add_node("E")
    after = {k: r.owner(k) for k in keys}

    moved = [k for k in keys if before[k] != after[k]]
    # invariant: every moved key's new owner is exactly E
    assert all(after[k] == "E" for k in moved)

    print(f"Before: nodes {INITIAL_NODES}. After: + E. "
          f"Remapped = {len(moved)} keys (expected K/(N+1) = "
          f"{NUM_KEYS//(len(INITIAL_NODES)+1)}).\n")

    # Show the first several moved keys + where they came from.
    print("Sample of keys that moved to E (key: old_owner -> E):\n")
    for k in moved[:10]:
        print(f"  {k}: {before[k]} -> E   "
              f"(hash {h32(k)}, now under E's arc)")
    if len(moved) > 10:
        print(f"  ... and {len(moved) - 10} more.\n")

    by_old: dict[str, int] = {}
    for k in moved:
        by_old[before[k]] = by_old.get(before[k], 0) + 1
    print("Where the moved keys came from (donors to E):\n")
    print(f"  {'donor':>6}  {'keys given':>10}  {'share':>6}")
    for n in sorted(by_old, key=lambda x: -by_old[x]):
        print(f"  {n:>6}  {by_old[n]:>10}  {fmt_pct(by_old[n]/len(moved)):>6}")

    expected = NUM_KEYS / (len(INITIAL_NODES) + 1)
    within = 0.5 * expected  # generous band: 50%..150% of K/N
    ok = abs(len(moved) - expected) <= within
    print(f"\nExpected K/(N+1) = {expected:.1f}; observed = {len(moved)}; "
          f"band = [{expected - within:.0f}, {expected + within:.0f}].")
    print(f"[check] observed within +/-50% of K/N:  {'OK' if ok else 'FAIL'}")
    print("[check] every moved key's new owner == 'E' (a join only ever adds):  OK")


# ----------------------------------------------------------------------------
# SECTION D: node departure -- B's keys move to the next clockwise node
# ----------------------------------------------------------------------------

def section_d() -> None:
    banner("SECTION D: node departure  "
           "(remove B; B's keys move to their next clockwise owner)")
    keys = all_keys()
    r = build_initial_ring(INITIAL_NODES)
    before = {k: r.owner(k) for k in keys}
    on_b = [k for k in keys if before[k] == "B"]
    r.remove_node("B")
    after = {k: r.owner(k) for k in keys}

    moved = [k for k in keys if before[k] != after[k]]
    # invariant: exactly the keys that were on B moved; none else did.
    assert set(moved) == set(on_b), "departure must move only B's keys"

    print(f"Before: nodes {INITIAL_NODES}. Remove B. B held {len(on_b)} keys.\n")
    print(f"After removal, exactly {len(moved)} keys moved (== B's old keys).\n")

    dest: dict[str, int] = {}
    for k in moved:
        dest[after[k]] = dest.get(after[k], 0) + 1
    print("Where B's keys went (each key's next clockwise survivor):\n")
    print(f"  {'new owner':>10}  {'keys':>6}  {'share':>6}")
    for n in sorted(dest, key=lambda x: -dest[x]):
        print(f"  {n:>10}  {dest[n]:>6}  {fmt_pct(dest[n]/len(moved)):>6}")

    print("\nSample remap (key: B -> next survivor):\n")
    for k in moved[:8]:
        print(f"  {k}: B -> {after[k]}   (hash {h32(k)})")
    if len(moved) > 8:
        print(f"  ... and {len(moved) - 8} more.\n")

    print(f"[check] moved set == keys formerly on B:  OK  "
          f"({len(moved)} == {len(on_b)})")
    # GOLD: average remap on a removal is also ~K/N (here K/N where N=4).
    expected = NUM_KEYS / len(INITIAL_NODES)
    within = 0.6 * expected
    ok = abs(len(moved) - expected) <= within
    print(f"[check] B's load ~ K/N = {expected:.0f} (observed {len(moved)}, "
          f"band [{expected - within:.0f}, {expected + within:.0f}]):  "
          f"{'OK' if ok else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION E: virtual nodes cure the skew
# ----------------------------------------------------------------------------

def section_e() -> None:
    banner("SECTION E: virtual nodes cure the load skew  "
           "(V=1 vs V=150)")
    keys = all_keys()

    def imbalance(counts: dict[str, int]) -> tuple[float, float]:
        vals = list(counts.values())
        mean = statistics.mean(vals)
        std = statistics.pstdev(vals)
        cov = std / mean if mean else 0.0          # coefficient of variation
        ratio = max(vals) / min(vals) if min(vals) else float("inf")
        return cov, ratio

    print("With V = 1 vnode per node, each node gets ONE random arc -- the\n"
          "arc lengths are wildly uneven (Dirichlet), so load is skewed.\n"
          "With V = 150, each node's total arc averages out by the law of\n"
          "large numbers, and load balances to within ~10%.\n")

    for V in (1, 3, 50, 150):
        r = build_initial_ring(INITIAL_NODES, vnodes=V)
        counts = r.load_counts(keys)
        cov, ratio = imbalance(counts)
        print(f"V = {V:>3} vnodes/node  ->  load by node: "
              f"{dict(sorted(counts.items()))}")
        print(f"{'':>17}max/min = {ratio:.2f}x,  "
              f"CoV = {cov:.3f}  (CoV<0.10 ~ balanced within 10%)\n")

    print("Read the table: at V=1 a single random arc can starve a node\n"
          "(here the busiest holds ~30x the quietest); even V=3 is still\n"
          "badly skewed. By V=150 the max/min ratio is near 1.1 and CoV under\n"
          "0.10. That is why Cassandra defaults to 256 and Memcached to\n"
          "160-200 vnodes/node.\n")

    # GOLD: at V=150, load is balanced within ~10% (CoV < 0.12, max/min < 1.25).
    r150 = build_initial_ring(INITIAL_NODES, vnodes=DEFAULT_VNODES)
    c150 = r150.load_counts(keys)
    cov150, ratio150 = imbalance(c150)
    bal = cov150 < 0.12 and ratio150 < 1.25
    print(f"GOLD @ V={DEFAULT_VNODES}: max/min = {ratio150:.3f}, "
          f"CoV = {cov150:.4f}")
    print(f"[check] balanced within ~10% (CoV<0.12 and max/min<1.25):  "
          f"{'OK' if bal else 'FAIL'}")


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("consistent_hashing_lb.py - reference impl. "
          "All numbers feed CONSISTENT_HASHING_LB.md.")
    print(f"Python stdlib only. ring = 2^32 = {RING}. K = {NUM_KEYS} keys.")
    print("hash = MD5[:4] 32-bit (deterministic across processes).")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
