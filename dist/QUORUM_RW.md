# QUORUM_RW — Quorum Replication (Dynamo / Cassandra)

> A **concept bundle**: this guide + [`quorum_rw.py`](./quorum_rw.py) + [`quorum_rw.html`](./quorum_rw.html).
> Every number below is printed by the `.py` (the single source of truth) and recomputed live by the `.html`. Nothing is hand-computed.
> Interactive companion: **[`quorum_rw.html`](./quorum_rw.html)**. 🔗 Back to [all tutorials](../index.html).

---

## 0. Why this exists: do the read circle and the write circle overlap?

Picture `N` replicas as `N` sticky notes pinned in a circle on the wall. Every copy of a piece of data lives on several of them. Two clients walk up to the wall:

- a **writer** circles `W` notes and writes the new value on each;
- a **reader** circles `R` notes and reads whichever value is newest.

If those two circles **overlap**, the reader is guaranteed to see at least one note the writer just touched — the fresh value. If they **don't** overlap, the reader may walk away with stale notes. The whole of quorum theory collapses to one question: **do the circles overlap?**

- `R + W > N` ⟹ they **must** overlap (pigeonhole: two circles of sizes `R` and `W` inside `N` notes share at least `R + W − N` notes) → **strong consistency**.
- `R + W ≤ N` ⟹ they **might not** — a misaligned reader/writer pair can miss each other entirely → **eventual consistency**.

So consistency is a **dial** the operator turns by choosing `R` and `W`: `W = N, R = 1` (fast reads), `W = 1, R = N` (fast writes), `W = R = N/2+1` (balanced), `W + R ≤ N` (fast both ways, no guarantee). Cassandra exposes this as the consistency levels `ONE` / `QUORUM` / `ALL`.

But quorums alone only guarantee that an overlapping replica **exists**. Three real-world problems still bite, and Dynamo has one mechanism for each:

| Problem | Dynamo's mechanism | Section |
|---|---|---|
| the overlapping replica **crashed** and missed the write | **sloppy quorum + hinted handoff** | §3 |
| a stale replica gets **selected by a later read** | **read repair** | §4 |
| the key is **never read**, so §4 never fires | **anti-entropy (Merkle tree)** | §5 |

| Concept | Definition |
|---|---|
| **replica** | one of the `N` machines holding a copy of the data. |
| **ring** | replicas ordered `0..N−1` around a consistent-hashing ring. |
| **coordinator** | the first alive replica in the preference list for a key; it forwards reads/writes to its quorum. |
| **preference list** | the `N` replicas in ring order starting at the coordinator. |
| **W** | write quorum size; a write returns after `W` replicas ACK. |
| **R** | read quorum size; a read returns after `R` replicas answer (picks max version). |
| **strong consistency** | `R + W > N` (every read overlaps every write). |
| **eventual** | `R + W ≤ N` (reads may miss writes; converges via repair). |
| **sloppy quorum** | when a preferred replica is DOWN, take the next alive one so the write still hits `W` living replicas. |
| **hinted handoff** | the substitute keeps a *hint* recording who the write was really for; forwards it on recovery. |
| **read repair** | during a read, stale replicas (older version) get the fresh value written back by the reader. |
| **anti-entropy** | background sync via a **Merkle tree**; reconcile only the leaves whose hashes differ. |
| **version** | per-key counter tagging each write; reads pick the highest version, repairs target lower ones. |

> **Papers**: DeCandia et al. (2007), *"Dynamo: Amazon's Highly Available Key-value Store,"* SOSP — `N/R/W` knobs (Sec 4.6/4.7); Lakshman & Malik (2010), *"Cassandra,"* VLDB Bulletin — same model, `CL=ONE/QUORUM/ALL`; Kleppmann, *Designing Data-Intensive Applications*, Ch. 5 — quorum proof, read repair, anti-entropy.

### The scenario (deterministic; reused by every section and the `.html`)

Five replicas `R0..R4` on a consistent-hashing ring. The coordinator for our key is `R0`, so its preference list walks clockwise: `[R0, R1, R2, R3, R4]`. Writes take the first `W` of that list; reads take the first `R`.

---

## 1. Quorum basics — `N=5, R=3, W=3`, the overlap guarantee

A write of `W=3` to coordinator `R0` contacts the first 3 of the preference list; a read of `R=3` contacts the first 3 too. Both circles are `{R0, R1, R2}`:

> From `quorum_rw.py` Section A:

```
  ring (clockwise from R0): R0 R1 R2 R3 R4
  preference list of R0   : {R0, R1, R2, R3, R4}
  write set W = 3        : {R0, R1, R2}
  read  set R = 3        : {R0, R1, R2}
  W INTERSECT R           : {R0, R1, R2}  (|intersection| = 3)

R + W = 3 + 3 = 6  >  N = 5   =>   STRONG CONSISTENCY.
Pigeonhole lower bound on |W INTERSECT R| = R + W - N = 3+3-5 = 1.
This configuration actually achieves |intersection| = 3 >= 1: OK (the bound holds).

[check] |W INTERSECT R| = 3 >= min_intersection = 1:  OK
```

The guarantee is the **floor**, not the typical case. Coordinator-aligned reads/writes (both start at `R0`) overlap in `{R0,R1,R2}`; an adversarial placement could shrink the overlap to exactly 1 — but **never 0**. That is what "strong" means here. The §6 gold-check brute-forces all 100 `(W-set, R-set)` pairs to prove the floor is real.

🔗 Drag `R` and `W` in **[panel ①](./quorum_rw.html)** to watch the two circles and their intersection recompute live.

---

## 2. Tunable consistency — the R/W dial

Same `N=5` ring, same coordinator `R0`. The operator chooses `(W, R)`. `R + W > N` ⟹ strong; `R + W ≤ N` ⟹ eventual.

> From `quorum_rw.py` Section B:

```
| config      | W | R | R+W | strong?       | write set             | read set                | coord-aligned intersection | min |
|-------------|---|---|-----|---------------|-----------------------|-------------------------|----------------------------|-----|
| fast writes | 1 | 5 |  6  | yes           | {R0}                  | {R0, R1, R2, R3, R4}    | {R0}                       |  1  |
| fast reads  | 5 | 1 |  6  | yes           | {R0, R1, R2, R3, R4}  | {R0}                    | {R0}                       |  1  |
| balanced    | 3 | 3 |  6  | yes           | {R0, R1, R2}          | {R0, R1, R2}            | {R0, R1, R2}               |  1  |
| eventual    | 2 | 2 |  4  | NO (R+W<=N)   | {R0, R1}              | {R0, R1}                | {R0, R1}                   |  0  |
```

The `strong?` column tracks `R+W` vs `N` exactly; `min` is the pigeonhole floor on `|W ∩ R|`. For the first **three** configs `min ≥ 1`, so any read quorum and any write quorum share a replica — a reader always sees the latest write.

### The eventual trap

The eventual row is subtle. Coordinator-aligned, `{R0,R1}` and `{R0,R1}` **do** overlap — but the **guarantee is gone**, because there **exist** disjoint quorums. Demonstration: write to `{R0,R1}`, then a reader whose preference list starts at `R2` picks `{R2,R3}`:

```
  write set (coord R0): {R0, R1}
  read  set (coord R2): {R2, R3}   <- a different coordinator
  W INTERSECT R        : {}   |intersection| = 0
```

The reader missed **both** replicas that got the write — it returns the stale value. `R+W=4 ≤ 5` means strong consistency is **not** guaranteed, even though a coordinator-aligned placement would have overlapped. This is exactly why Cassandra's `CL=ONE` is faster than `CL=QUORUM` but can return stale data: `QUORUM` forces `R+W>N`.

🔗 Click the **presets** in **[panel ②](./quorum_rw.html)** to flip between fast-read / fast-write / balanced / eventual and watch the intersection — and the consistency verdict — change.

---

## 3. Sloppy quorum + hinted handoff — replica DOWN

A preferred replica is DOWN. Dynamo still wants `W` acks, so it walks **past** the dead node and writes to the next **alive** one — the "sloppy" part. The substitute keeps a **hint** recording which dead node it stood in for; on recovery, it forwards the write.

Scenario: `N=5, W=3`, coordinator `R0`. Preference list `[R0..R4]`. **R1 is DOWN**. The top-`W` preference is `{R0,R1,R2}`; `R1` must be skipped.

> From `quorum_rw.py` Section C:

```
  preference list   : {R0, R1, R2, R3, R4}
  down              : {R1}
  chosen (sloppy W) : {R0, R2, R3}   <- first 3 ALIVE replicas
  hints             : R3 holds hint for R1
```

Walk: `R0` (alive, take) → `R1` (DOWN, skip) → `R2` (alive, take) → `R3` (alive, take; that is `W=3`). `R3` is **outside** the top-`W` preference list `{R0,R1,R2}`, so it is a **substitute**: it records a hint pointing at the dead replica it replaced (`R1`). The write returns after 3 acks even though `R1` is unreachable — **availability preserved**.

`R1` recovers. `R3` (via gossip) sees `R1` alive again and **forwards** the hinted write, then discards the hint:

```
  before handoff: R0=v1, R1=---, R2=v1, R3=v1, R4=---
  after  handoff: R0=v1, R1=v1,  R2=v1, R3=v1, R4=---
```

Now `R1` has `v1`. Hinted handoff is what makes sloppy quorum **invisible** to the application — the data ends up on the *right* replicas, just lazily. Without handoff, the substitute would keep the data forever and the owner's replica count would silently grow.

🔗 Toggle **R1 down** in **[panel ③](./quorum_rw.html)** and watch the write hop over it to `R3`, with the hint drawn as a dashed arrow.

---

## 4. Read repair — stale replica fixed on the fly

A read contacts `R` replicas. If one of them missed a recent write, its **version** is lower. The reader detects this and writes the fresh value back — that is **read repair**. It is the primary anti-entropy mechanism for keys that are **read often**.

Scenario: a write at version 2 reached `{R0, R1, R3}` but `R2` missed it (still version 1, stale value). A read of `R=3` picks `{R0, R1, R2}`:

> From `quorum_rw.py` Section D:

```
  read responses (replica -> (version, value)):
    R0: (version=2, value=v2)
    R1: (version=2, value=v2)
    R2: (version=1, value=v1-stale)

  highest version = 2, fresh value = 'v2'
  stale replicas (version < 2): R2 (will be repaired with 'v2')
```

Read repair **writes** `v2` back to `R2` before returning to the client. The reader got the right answer **and** fixed a divergence, in one round trip. Trade-off (Dynamo paper §4.7): read repair adds a write to the read path. For keys that are rarely read, the background Merkle anti-entropy of §5 is cheaper than waiting for a read.

🔗 Hit **play** on **[panel ④](./quorum_rw.html)** to watch the stale `R2` get repaired mid-read.

---

## 5. Anti-entropy — Merkle tree comparison

Background sync: two replicas exchange a **Merkle tree** (hash tree) of their key range and reconcile only the leaves whose hashes differ. Comparing two **root** hashes is `O(1)`; descending into mismatched subtrees pins the divergence to a small set of keys. Dynamo uses Merkle trees over the keyspace partition each replica owns.

Scenario: 4 keys. Replica `A` has the truth; replica `B` has a **stale** value for `k2` (missed a write). Everything else is identical.

> From `quorum_rw.py` Section E:

```
Leaf hashes  = sha1('key|value')[:8];  internal = sha1(left|right)[:8].
Padded to a power of 2 (4 keys -> 4 leaves -> tree of depth 2).

  level 2 (root)   level 1 (internal)        level 0 (leaves)
  --------------------------------   -----------------------
  A:  root=743046af   [92726ad9, dacd881f]   ['4de30b25', 'f05b87f9', '59bd9a7a', '1d8ca44a']
  B:  root=df25c573   [abe6311b, dacd881f]   ['4de30b25', '3ed23ae4', '59bd9a7a', '1d8ca44a']

Step 1  compare roots: 743046af != df25c573 -> DIVERGE, descend.

Step 2  compare level-1 nodes:
          subtree over {k1,k2}: A=92726ad9  B=abe6311b  [DIFFER -> descend]
          subtree over {k3,k4}: A=dacd881f  B=dacd881f  [SAME]

Step 3  descend into the differing subtree {k1,k2}, compare leaves:
  full leaf diff: k2
  -> sync 1 key(s): ['k2']

[check] roots differ before sync, EQUAL after, only k2 needed:  OK

GOLD (pinned for quorum_rw.html):
  root_A = 743046af
  root_B = df25c573   (stale)
  root_B_after_sync = 743046af   (== root_A)
  diff keys = ['k2']
```

`B` copies `A`'s value for the differing key(s), recomputes its tree, roots now match. Cost: `O(log K)` comparisons + the differing keys, **not** the whole keyspace. That is the whole point of the Merkle tree: compact representation, cheap divergence detection.

---

## 6. Gold check — `R + W > N` ⟹ every quorum pair intersects

The defining property. Brute-forced over **every** way to choose a `W`-set and an `R`-set (not just coordinator-aligned ones):

> From `quorum_rw.py` GOLD CHECK:

```
  N=5, W=3, R=3: 10 W-sets x 10 R-sets = 100 pairs enumerated.
  pigeonhole floor R+W-N = 1.
  minimum |W INTERSECT R| observed over all 100 placements = 1.
  disjoint (|intersection|=0) placements = 0 / 100.

  R+W=6 > N=5 -> strong consistency. Expect 0 disjoint.
  [check] GOLD: min_intersection >= 1 for all 100 pairs:  OK
```

Boundary sanity at the threshold `R+W=N` (here `W=2, R=3`): the pigeonhole floor drops to 0 and disjoint placements **do** exist:

```
  W-set {R0, R1} and R-set {R2, R3, R4} are DISJOINT (R+W=N=5).
  One replica more on either side and we are back at R+W>N (strong).

GOLD scalar: min_intersection(3,3,5) = 1  (must be 1)
[check] gold scalar reproduces from min_intersection():  OK
```

🔗 The green **`check: OK`** badge at the bottom of `quorum_rw.html` re-runs the same `R+W>N` ⇒ `|W ∩ R| ≥ 1` test in JavaScript against the live slider values.

---

## 7. How the pieces fit together

```
                       write v_{n+1}
                            |
                            v
        +-------------------+-------------------+
        |                   |                   |
   coordinator         W replicas          (some DOWN?)
   picks first W       ack the write            |
   of preference       -> write OK         sloppy quorum +
   list                                     hinted handoff (§3)
                                                  |
                                                  v
                                       eventual: data on
                                       the RIGHT replicas

                       read
                            |
                            v
        +-------------------+-------------------+
        |                   |                   |
   coordinator         R replicas          (stale one?)
   picks first R       answer; reader           |
   of preference       picks MAX version   read repair (§4)
   list                                     (on the read path)
                                                  |
                                                  v
                                       keys never read?
                                       background Merkle
                                       anti-entropy (§5)

   STRONG CONSISTENCY holds throughout IFF  R + W > N   (§6 gold check)
```

The four mechanisms are layered: **quorums** give the overlap *guarantee*; **sloppy quorum + hinted handoff** keep availability when replicas crash; **read repair** fixes divergences on the hot path; **Merkle anti-entropy** catches the cold keys. Strip any layer and a specific failure mode leaks through.

---

## Cross-references

- 🔗 [`quorum_rw.py`](./quorum_rw.py) — the single source of truth; run with `python3 quorum_rw.py`.
- 🔗 [`quorum_rw.html`](./quorum_rw.html) — interactive ring, sliders, presets, read-repair animation, gold badge.
- 🔗 [`RAFT.md`](./RAFT.md) / [`PAXOS.md`](./PAXOS.md) — `W = R = N/2+1` quorums are exactly what Raft/Paxos majorities are; this bundle is the *un-coordinated* (Dynamo) variant.
- 🔗 [`NETWORK_PARTITIONS.md`](./NETWORK_PARTITIONS.md) — sloppy quorum is the AP answer to a partition; cf. CAP.
