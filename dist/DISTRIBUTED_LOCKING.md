# DISTRIBUTED_LOCKING — Distributed Locks (ZooKeeper, Redis/Redlock, Fencing)

> A **concept bundle**: this guide + [`distributed_locking.py`](./distributed_locking.py) + [`distributed_locking.html`](./distributed_locking.html).
> Every number below is printed by the `.py` (the single source of truth) and recomputed live by the `.html`. Nothing is hand-computed.
> Interactive companion: **[`distributed_locking.html`](./distributed_locking.html)**. 🔗 Back to [all tutorials](../index.html).

---

## 0. Why this exists: the talking stick and the frozen speaker

A distributed lock is a **talking stick**. Only the node holding the stick may write to shared storage; everyone else waits. The hard part: nodes cannot see each other directly — they hand the stick around through an **intermediary** (ZooKeeper, or Redis). The whole subject of distributed locking is: *what guarantees does that intermediary give you, and what breaks them?*

- **ZooKeeper** is a **consensus** service (a Zab/Paxos-like protocol). It hands you a tiny filesystem of **ephemeral** nodes — nodes that vanish the instant the session that created them dies. That ties a lock to a **live session for free, no clocks involved** (§1). The naive version has every waiter watch the *same* node, so one release wakes *all* of them (the **herd effect**); the fix is **sequential** nodes where each waiter watches only its predecessor (§2).

- **Redis** is a cache that happens to expose a set-if-absent primitive (`SET key value NX PX ttl`). It is fast, but the lock's lifetime is a **clock countdown**: the lock expires at `now+ttl` whether or not the holder is still alive. If the holder **freezes** (a stop-the-world GC pause) longer than the TTL, the lock silently expires, a second client acquires it, and now **two** clients believe they hold the stick — the **stale lock holder** (§3).

- **Redlock** spreads the lock across `N` independent Redis masters and asks for a **majority**. The hope is that majority agreement defeats any single failure. **Martin Kleppmann's critique**: it does not. The expiry is still a per-master clock countdown, and a clock jump (NTP step / VM suspend) after acquisition is undetectable — two clients can hold the lock via two **disjoint majorities**. Majority quorum does not fix bad clocks (§4).

- **Fencing tokens** are the fix. Every grant carries a **monotonically increasing token**; the shared storage **refuses** any write whose token isn't strictly greater than the last one it accepted. So even a frozen, stale holder that wakes and writes is **rejected at the storage** — mutual exclusion is enforced at the resource, not just at the lock service (§5).

| Problem | Mechanism | Section |
|---|---|---|
| lock must die if the holder dies | **ZooKeeper ephemeral nodes** (session-tied) | §1 |
| one release wakes every waiter | **sequential nodes + predecessor watch** | §2 |
| lock expires underneath a frozen holder | **(the clock problem — unavoidable in Redis)** | §3 |
| majority doesn't prevent two holders | **(Kleppmann: clocks break Redlock)** | §4 |
| a stale holder still corrupts data | **fencing tokens checked at the storage** | §5 |

| Concept | Definition |
|---|---|
| **mutual exclusion** | at most ONE client believes it holds the lock at any instant — the goal. |
| **ephemeral node** | a ZooKeeper node tied to a session; auto-deleted when that session ends. No clocks. |
| **session** | a client's live connection to ZK; ephemeral nodes die with it (liveness is consensus-driven). |
| **watch** | a one-shot ZK notification fired when a watched node is created/deleted/changed. |
| **herd effect** | when `N` waiters all watch one node, a single release wakes all `N` ("thundering herd"). |
| **sequential node** | a ZK node auto-suffixed with a monotonic counter (`/lock-0000000001`); gives an ordered queue. |
| **predecessor watch** | each sequential waiter watches only the node with the next-lower sequence → one wakeup per release. |
| **SET NX PX** | Redis `SET key value NX PX ttl` = set only if absent, expire after `ttl` ms. The single-Redis lock. |
| **TTL** | time-to-live; a Redis lock auto-expires at `now+ttl`. |
| **stale lock holder** | a client that still believes it holds the lock after the TTL silently expired (it was frozen). The #1 danger of clock-based locks. |
| **Redlock** | acquire the same `SET NX PX` lock on `N` (usually 5) independent masters; succeed on a **majority**. |
| **quorum** | `floor(N/2) + 1`. For `N=5`, quorum = `3`. |
| **fencing token** | a strictly-increasing number issued with each grant (`33, 34, 35, …`). |
| **fencing** | the storage rejects any write whose token is not strictly greater than the last accepted one → a stale holder is harmless. |

> **Sources**: Junqueira & Reed, *ZooKeeper: Distributed Process Coordination* (O'Reilly, 2013) — ephemeral/sequential nodes, the lock recipe; antirez (Salvatore Sanfilippo), *Redlock* algorithm write-up (antirez.com, 2014) — `SET NX PX` and N-master quorum; **Martin Kleppmann**, *"How to do distributed locking"* (blog, 2016) and *Designing Data-Intensive Applications*, Ch. 8 — the GC-pause / clock-skew critique of Redlock and fencing tokens (DDIA Fig 8.5); Gray & Reuter, *Transaction Processing* (1993), §7.6 — the original lease/fencing-token idea.

---

## 1. ZooKeeper ephemeral lock (naive) — create `/lock`, watch

The naive ZK recipe: an **ephemeral** node `/lock`. The first client to create it holds the lock. Everyone else *fails* to create it (it exists) and instead sets a **watch** on `/lock`. When the holder's session ends, ZK deletes the ephemeral node and fires the watch — on **every** waiter at once.

> From `distributed_locking.py` Section A:

```
  tick  event
  ----  -----
    0   C1 create_ephemeral('/lock') -> True  [C1 HOLDS]
    1   C1 create_ephemeral('/lock') -> False (exists); C2 watches /lock
    2   C1 create_ephemeral('/lock') -> False (exists); C3 watches /lock

  watchers on /lock = {C2, C3}   (N-1 = 2 waiters)

Now C1's session EXPIRES (crash / timeout). ZK auto-deletes the
ephemeral /lock and fires the watch on EVERY registered waiter:

  tick   3   C1 session expired -> /lock deleted
  tick   3   watches fired on: {C2, C3}   (2 waiters woke up = the HERD EFFECT)

[check] number of waiters woken by a single release = 2 (== N-1 == 3-1):  OK
```

The key mechanism: ephemeral ties the lock to a **session**, so a crashed holder's lock vanishes automatically — no clocks, no expiry race. The cost: **one release wakes `N-1` waiters**, all of them hammering ZK to re-create `/lock`. With 1000 waiters that is a thundering herd. That is the problem §2 fixes.

🔗 Toggle **naive vs sequential** in **[panel ①](./distributed_locking.html)** and watch the herd (all watchers) vs the queue (one wakeup).

---

## 2. Sequential nodes — the ordered queue (herd-free)

Fix: each waiter creates a **sequential ephemeral** node. The node with the **lowest** sequence holds the lock; every other waiter watches only its **immediate predecessor**. A release wakes exactly **one** client.

> From `distributed_locking.py` Section B:

```
  C1 create_sequential -> /lock-0000000001  [seq 1]  watches predecessor: (none - is lowest)
  C2 create_sequential -> /lock-0000000002  [seq 2]  watches predecessor: /lock-0000000001
  C3 create_sequential -> /lock-0000000003  [seq 3]  watches predecessor: /lock-0000000002

  queue (sorted by seq): 0000000001(C1) -> 0000000002(C2) -> 0000000003(C3)
  holder = argmin_seq = /lock-0000000001 on C1  (unique, so <= 1 holder by construction)

C1 finishes and RELEASES (deletes its node). Only the watcher on
that node wakes - C2, the immediate successor. C3 sleeps through it:

  C1 releases 0000000001 -> wakes C2 only -> new holder = /lock-0000000002
  C2 releases 0000000002 -> wakes C3 only -> new holder = /lock-0000000003

HERD vs QUEUE, side by side (Section A vs Section B):
  naive (A): 1 release -> 2 waiters woken (ALL of them)
  queue (B): 2 releases -> 2 waiter woken (ONE per release, the immediate successor)

[check] every release woke exactly 1 waiter (not the herd):  OK
```

Because the holder is `argmin_seq` over the live ephemeral nodes, and sequence numbers are **distinct**, the holder is **unique by construction** — at most one client holds the lock at any time, with no clock involvement. This is why the §6 gold-check treats ZK-sequential as the *correct* baseline against which the clock-based locks are measured.

> **GOLD** (pinned for `distributed_locking.html`): `herd_woken_per_release` (naive, N=3) = **2**; `queue_woken_per_release` (sequential) = **1**; holder rule `argmin_seq(live nodes)` → unique → mutual exclusion.

---

## 3. Redis SETNX lock — `SET NX PX` and the stale holder

Redis lock primitive: `SET key value NX PX ttl`.

- `NX` → set **only if** the key does not exist (atomic test-and-set);
- `PX` → expire after `ttl` milliseconds (a **clock countdown**).

Returns `OK` if you got it, `nil` if someone else holds it. The danger: the lock expires at `now+ttl` **whether or not the holder is still alive**.

> From `distributed_locking.py` Section C:

```
Scenario: TTL = 30 ticks. C1 acquires at tick 0, does work to
tick 10, then FREEZES in a GC pause longer than the remaining TTL.

  tick   0   C1 SET lock c1 NX PX 30 -> 'OK'   [C1 holds, expires at tick 30]
  tick  10   C2 SET lock c2 NX PX 30 -> nil  (held; C1 still believes it holds)

  tick  10   *** C1 enters a stop-the-world GC pause (frozen 25 ticks, until tick 35) ***
  tick  30   TTL elapsed -> lock EXPIRED (is_expired=True). C1 is frozen and does NOT know.
  tick  32   C2 SET lock c2 NX PX 30 -> 'OK'   [C2 holds]. C1 is STILL frozen.
  tick  32   *** holders that BELIEVE they hold = {C1, C2}  -> |holders| = 2 ***

  tick  35   C1 WAKES from GC. It never released, never saw
          the expiry, so it STILL believes it holds the lock. It writes
          to shared storage. Meanwhile C2 ALSO writes -> DATA CORRUPTION.

[check] mutual-exclusion invariant |holders| <= 1 under Redis+GC:  FAIL (2 holders)
```

This is the **stale lock holder**: the lock's lifetime is a clock countdown decoupled from the holder's liveness. A pause longer than the remaining TTL silently hands the lock to a second client while the first keeps writing. **Mutual exclusion is violated.** You cannot make a Redis lock "safer" by fiddling with the TTL — the GC pause can always be longer than whatever you pick.

> **GOLD**: `TTL = 30`, `GC pause = 25` (freeze ends at tick 35 > TTL 30, so expiry happens *during* the freeze); `max |holders| = 2` → a Redis lock cannot guarantee mutual exclusion against a GC pause. This motivates §5.

🔗 Drag the **GC pause** slider past the TTL in **[panel ③](./distributed_locking.html)** and watch the second holder appear while the first is still frozen.

---

## 4. Redlock — N masters, majority quorum, and why clocks break it

Redlock spreads the `SET-NX-PX` lock across `N` (here **5**) **independent** Redis masters. A client `SET`s on all of them; it holds the lock iff a **majority** accepted. `quorum = floor(N/2)+1 = 3` for `N=5`.

> From `distributed_locking.py` Section D:

```
  N = 5 masters (M1..M5),  quorum = 3,  TTL = 10 ticks (per-master clock)

  C1 acquire: M4,M5 slow/unreachable; SET on M1,M2,M3 -> got 3  (>= quorum 3?) -> LOCK ACQUIRED on {M1,M2,M3}
             each acquired master's lock expires at its own clock 10.

  Clock skew: M3's clock jumps to 12 (an NTP step) -> C1's lock on M3 EXPIRED. M1 (clock 0) and M2 (clock 0) still hold C1's lock.

  C2 acquire: SET on all 5 -> got 3 on {M3,M4,M5}  (>= quorum 3?) -> LOCK ACQUIRED on {M3,M4,M5}

  TWO VALID MAJORITIES: C1 holds {M1,M2,M3}, C2 holds {M3,M4,M5}.
  They overlap only on {M3} - but M3's lock EXPIRED (clock jump), so it protects neither. Both got 3 >= quorum 3: both legitimately acquired. -> |holders| = 2.

  [check] Redlock mutual-exclusion under a clock jump:  FAIL (2 holders)
```

**The majority did not help.** C1 had majority `{M1,M2,M3}`; C2 got a *different* majority `{M3,M4,M5}`. They overlap only on `M3` — but `M3`'s lock had *expired* (a clock jump), so it protects neither side. Both are legitimate quorums (`3 ≥ 3`); both acquired. Redlock's validity check (`T2−T1 < TTL`) only runs at **acquire** time; a clock jump *afterward* is undetectable.

> **Kleppmann's point**: Redlock is correct **only if** you assume bounded clock skew and no long pauses — an assumption that NTP steps, VM suspends, and GC routinely violate. For real mutual exclusion you need **fencing tokens** (§5), not just a bigger quorum.

> **GOLD**: `N=5`, `quorum=3`, `TTL=10`; C1 majority = `{M1,M2,M3}`, C2 majority = `{M3,M4,M5}`, intersection = `{M3}` (expired → no protection); `max |holders| = 2` → Redlock violates mutual exclusion under clock skew.

🔗 Press **clock jump on M3** in **[panel ④](./distributed_locking.html)** and watch C2 assemble a disjoint majority while C1 still believes it holds the lock.

---

## 5. Fencing tokens — monotonic tokens defeat the stale holder

The fix: every lock grant carries a **fencing token** that **strictly increases** over time. The shared storage **refuses** any write whose token is not greater than the last one it accepted. So a stale holder that wakes after expiry is detected and rejected — by the storage itself.

> From `distributed_locking.py` Section E:

```
  C1 acquire -> fencing token 33
  *** C1 GC pause; lock EXPIRES ***
  C2 acquire -> fencing token 34   (monotonic: 34 > 33)

  C2 write(token=34, 'v34') -> last_token was 0 -> ACCEPTED  (store.last_token = 34)
  C1 write(token=33, 'v33-stale') -> 33 <= 34 -> REJECTED

  final storage data = ('C2', 'v34')   (C2's write, the correct one)

[check] C2 accepted, C1 rejected, storage holds C2's data:  OK
```

The stale holder (C1) was still able to *believe* it held the lock — fencing cannot stop a client from being mistaken. But it stops the mistake from **corrupting** anything: the storage gate-keeps on the token, so only the genuinely-newest holder's write survives. **Mutual exclusion is enforced at the resource, not just at the lock service.** This is why Kleppmann recommends fencing tokens (or a consensus-based lock like ZK/etcd that gives you a monotonic version) over Redlock for anything that needs real correctness.

> **GOLD**: token sequence `C1=33, C2=34` (strictly increasing); `storage.last_token = 34` after C2's write; C1's stale write (token `33`) → **REJECTED** (`33 ≤ 34`); `storage.data = ('C2','v34')` → data integrity preserved.

🔗 Hit **play** in **[panel ⑤](./distributed_locking.html)** to watch the stale C1 write bounce off the storage's token check while C2's goes through.

---

## 6. Gold check — consensus-based locking ⟹ at most one holder at every tick

The defining property of a lock: at most **one** client believes it holds it, at every instant. Brute-forced over a deterministic timeline.

**(1) ZooKeeper sequential lock (consensus-based):** `holder == argmin_seq(live ephemeral nodes)`. Distinct sequences ⟹ `argmin` is unique ⟹ at most one holder at all times, by proof.

> From `distributed_locking.py` GOLD CHECK:

```
    tick  op                live queue (holder *)          |holders|
    ----  --                ------------------------------  --------
       0   create  C1        0000000001(C1)                 1
       1   create  C2        0000000001(C1) -> 0000000002(C2) 1
       2   create  C3        0000000001(C1) -> 0000000002(C2) -> 0000000003(C3) 1
       3   create  C4        0000000001(C1) -> 0000000002(C2) -> 0000000003(C3) -> 0000000004(C4) 1
       4   release C1        0000000002(C2) -> 0000000003(C3) -> 0000000004(C4) 1
       5   create  C5        0000000002(C2) -> 0000000003(C3) -> 0000000004(C4) -> 0000000005(C5) 1
       6   release C2        0000000003(C3) -> 0000000004(C4) -> 0000000005(C5) 1
       7   release C3        0000000004(C4) -> 0000000005(C5) 1
       8   release C4        0000000005(C5)                 1
       9   release C5        (empty)                        0

    max |holders| over 10 ticks = 1.
    [check] GOLD (consensus): |holders| <= 1 at EVERY tick:  OK
```

**(2) Counter-model — Redis SETNX under a GC pause** (same "mutual exclusion" claim, but the lock's lifetime is a clock countdown). A pause longer than the TTL silently creates a second holder:

```
    tick 0  C1 SET NX PX 10 -> OK     (C1 holds, expires tick 10)
    tick 12 GC pause over, lock EXPIRED; C2 SET NX PX 10 -> OK
    C1 woke and STILL believes it holds -> |holders| = 2
    [check] Redis: mutual exclusion VIOLATED (|holders| = 2):  confirmed
```

> **GOLD scalar**: `consensus max_holders = 1` (must be 1); `redis max_holders = 2`.

🔗 The green **`check: OK`** badge at the bottom of `distributed_locking.html` re-runs the same 10-tick ZK-sequential timeline in JavaScript and asserts `max |holders| == 1` at every tick, then contrasts it with the Redis counter-model that reaches 2.

---

## 7. How the pieces fit together

```
                      acquire the lock
                            |
            +---------------+---------------+
            |                               |
     CONSENSUS service               CLOCK-based service
     (ZooKeeper / etcd)             (Redis / Redlock)
            |                               |
   ephemeral + sequential          SET NX PX (TTL countdown)
   node tied to a SESSION          lock expires at now+ttl
            |                               |
   holder = argmin_seq(live)       holder = whoever last SET OK
   => UNIQUE => <=1 holder         => can be 2 if a holder FREEZES
   (no clocks)                        (GC pause / clock skew)
            |                               |
            |                       STALE LOCK HOLDER possible
            |                               |
            |              +----------------+----------------+
            |              |                                 |
            |        accept the violation              FENCING TOKEN
            |        (efficiency, not safety)    every grant gets a monotonic
            |                                  token; storage REJECTS writes
            |                                  with token <= last accepted
            |                                  => stale holder harmless
            v                                  v
   SAFE by construction            SAFE only with fencing at the storage
   (ZK sequential recipe)          (or: just use ZK/etcd instead of Redis)
```

The takeaway is a single sentence: **a lock is only as safe as the thing that enforces it.** ZooKeeper enforces safety via consensus + ephemeral sessions (no clocks, holder is the unique minimum). Redis enforces nothing beyond a TTL countdown, so a frozen holder escapes — and neither a bigger TTL nor a bigger quorum (Redlock) closes that hole. Only fencing tokens, checked *at the resource*, make a clock-based lock safe.

---

## Cross-references

- 🔗 [`distributed_locking.py`](./distributed_locking.py) — the single source of truth; run with `python3 distributed_locking.py`.
- 🔗 [`distributed_locking.html`](./distributed_locking.html) — interactive herd-vs-queue, GC-pause timeline, Redlock majority diagram, fencing-token gate, gold badge.
- 🔗 [`RAFT.md`](./RAFT.md) / [`PAXOS.md`](./PAXOS.md) — ZooKeeper's safety comes from a consensus protocol underneath (Zab is Paxos-descended); this bundle is the *application* of consensus to locking.
- 🔗 [`QUORUM_RW.md`](./QUORUM_RW.md) — Redlock's "majority of N masters" is the same `floor(N/2)+1` quorum idea; cf. the `R+W>N` overlap rule.
- 🔗 [`CLOCK_SYNC_NTP.md`](./CLOCK_SYNC_NTP.md) — the NTP clock jumps that break Redlock are exactly the unbounded skew discussed here.
- 🔗 [`LINEARIZABILITY.md`](./LINEARIZABILITY.md) — what "the lock behaves like a single mutex" formally means.
