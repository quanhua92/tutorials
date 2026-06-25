# LINEARIZABILITY — The Strongest Single-Object Consistency Model

> A **concept bundle**: this guide + [`linearizability.py`](./linearizability.py) + [`linearizability.html`](./linearizability.html).
> Every number below is printed by the `.py` (the single source of truth) and recomputed live by the `.html`. Nothing is hand-computed.
> Interactive companion: **[`linearizability.html`](./linearizability.html)**. 🔗 Back to [all tutorials](../index.html).

---

## 0. Why this exists: "it all happened at one instant"

Picture a shared register `X` replicated across several machines. Clients send operations (`read` or `write`); each one has an **invocation** (client calls) and a **response** (client gets the answer). In between, the operation is *in flight* and we don't know exactly when the store did the work. **Linearizability** (Herlihy & Wing 1990) says:

> For every operation there exists a single point in time — the **linearization point** — somewhere in `[invocation, response]`, at which the operation *appears to take effect* instantaneously. Line up all those points and the result must be a **legal sequential execution** of the register.

The one extra clause that makes it **strong**: those points must respect **real-time order**. If operation `A`'s *response* comes before operation `B`'s *invocation* (`A` fully completes before `B` even starts), then `A`'s point **must** be before `B`'s. The client *saw* `A` finish, so the real world says `A` happened first — the system is not allowed to pretend otherwise.

That real-time clause is the whole difference from **sequential consistency** (Lamport 1979), which keeps per-client program order but *ignores* real time. A read that starts after a write completes is free, under sequential consistency, to "not have noticed" the write yet. Linearizability forbids exactly that. This is why linearizability is called **"strong consistency"** — it makes a replicated register behave like a single non-concurrent machine to every outside observer.

| Concept | Definition |
|---|---|
| **register** `X` | a single read/write object; the only shared state here. |
| **operation** | a `read` or `write`, issued by one client; has an `inv` and a `resp`. |
| **invocation** (`inv`) | the real-time instant the client *sends* the request. |
| **response** (`resp`) | the real-time instant the client *receives* the answer. |
| **in flight** | the interval `[inv, resp]`; the store does the work here. |
| **linearization** | a total order of *all* operations that (1) is a legal sequential register history and (2) respects real-time order. |
| **linearization point** | the single instant in `[inv, resp]` where an op "appears to execute" atomically. |
| **real-time order** | if `resp(A) ≤ inv(B)` then `A` *must* precede `B` in the linearization. |
| **sequential consistency** | the weaker model: same as linearizability but *without* the real-time clause. |

> **Paper**: Herlihy, M. & Wing, J. (1990). *"Linearizability: A Correctness Condition for Concurrent Objects."* ACM TOPLAS **12**(3), 463–492. Defines linearizability and the linearization-point formulation. The checker used here is from Wing & Gong (1993); the contrast model is Lamport (1979).

---

## 1. A linearizable history — the read respects real time

Register `X` starts at `0`. Client `C1` writes `X=1`; client `C2` reads *after* the write completes.

```
  C1: W1(x,1)[1-4]
  C2:        R1(x)[5-7] ret=1
```

> From `linearizability.py` Section A:

```
Real-time partial order (resp(A) <= inv(B) => A before B):
  W1 -> R1   (resp(W1)=4 <= inv(R1)=5)

Checker: 1 topological sort(s); 1 legal register sequence(s):
  W1 R1   :  [0] W1(->1) R1(=1 ok)   [LEGAL  -> linearizable]

Verdict: HIST_A is LINEARIZABLE.
```

`R1` returned `1` — exactly the value the completed write stored. The linearization `(W1, R1)` is the one true sequential story. Because `resp(W1)=4 ≤ inv(R1)=5`, real time *forces* `W1` before `R1`, and the read correctly observes the write.

🔗 See this as a draggable timeline in **[panel ①](./linearizability.html)**.

---

## 2. A non-linearizable history — the stale read violates real time

Same setup, but now `R1` returns `0` (stale) even though it started *after* `W1` completed.

```
  C1: W1(x,1)[1-4]
  C2:        R1(x)[5-7] ret=0   <-- stale!
```

> From `linearizability.py` Section B:

```
Checker: 1 topological sort(s); 0 legal:
  W1 R1   :  [0] W1(->1) R1(=0 MISMATCH ret=0)   [ILLEGAL -> stale]

Verdict: HIST_B is NOT linearizable.
```

The *only* real-time-consistent order is `(W1, R1)`; replaying it makes `R1` expect `1`, but it returned `0`. No linearization exists.

### The contrast — sequential consistency *accepts* this history

> From `linearizability.py` Section B (contrast):

```
--- sequential consistency (drops the real-time clause) ---
  W1 R1   :  [0] W1(->1) R1(=0 MISMATCH)   [illegal]
  R1 W1   :  [0] R1(=0 ok) W1(->1)          [LEGAL -> seq. consistent]

Sequential verdict: HIST_B IS sequentially consistent.
```

Sequential consistency drops the real-time clause, keeping only **program order** (each client's own ops stay ordered). Now `R1` is free to be placed *before* `W1`, since they are on different clients: `R1` reads the initial `0`, *then* `W1` writes `1`. The client *saw* `W1` finish, but sequential consistency lets the system pretend `R1` "hadn't noticed" it yet.

```
[check] HIST_B: linearizable=False, sequentially_consistent=True  ->  OK
```

**That clause — enforcing real time — is the entire definition of linearizability.** It is what costs you consensus (§5).

🔗 Toggle between **linearizable / sequential** in **[panel ②](./linearizability.html)** and watch the verdict flip.

---

## 3. The linearization point — one instant per operation

Each operation has a `[inv, resp]` interval. The **linearization point** is the single instant inside that interval where the operation "appears to execute" atomically. Real time only constrains *non-overlapping* ops; ops that **overlap** may have their points in either relative order.

```
  C1: W1(x,1)[1---6]       \
  C2: W2(x,2)[2-5]          > W1 and W2 OVERLAP (no real-time edge)
  C3:          R1(x)[7-9] ret=2
```

> From `linearizability.py` Section C:

```
Real-time sorts: 2 (W1/W2 may swap; R1 always last). Legal: 1.
  W1 W2 R1   :  [0] W1(->1) W2(->2) R1(=2 ok)           [LEGAL]
  W2 W1 R1   :  [0] W2(->2) W1(->1) R1(=2 MISMATCH)     [illegal]

Verdict: HIST_C is LINEARIZABLE.

One valid linearization:  W1 W2 R1
Matching each op to a linearization point inside [inv, resp]:

| op  | kind        | inv | resp | interval | lin pt |
|-----|-------------|-----|------|----------|--------|
| W1  | write(1)    | 1   | 6    | [1,6]    | 3      |
| W2  | write(2)    | 2   | 5    | [2,5]    | 4      |
| R1  | read(ret=2) | 7   | 9    | [7,9]    | 8      |

The points line up in time as: W1@3 < W2@4 < R1@8
```

Each point lies inside its op's interval, the points respect real-time order, and replaying them gives a legal register story. **That** is the linearization-point definition of linearizability.

🔗 Drag the **linearization points** in **[panel ③](./linearizability.html)** — invalid placements (outside `[inv,resp]` or violating real time) turn red.

---

## 4. The checker — try every real-time-consistent ordering

Wing & Gong (1993): a history is linearizable **iff** some topological sort of the real-time partial order is a legal sequential register history. The algorithm is a backtracking enumeration:

1. Build the real-time partial order (`resp(A) ≤ inv(B)` ⟹ `A → B`).
2. Enumerate every total order (topological sort) of that order.
3. Replay each as a register; if **any** is legal ⟹ linearizable.

> From `linearizability.py` Section D:

| history | #ops | #real-time sorts | #legal | linearizable? |
|---|---|---|---|---|
| HIST_A | 2 | 1 | 1 | **YES** |
| HIST_B | 2 | 1 | 0 | **NO** |
| HIST_C | 3 | 2 | 1 | **YES** |
| HIST_D | 2 | 2 | 1 | **YES** |

The interesting one is **HIST_D** — an overlapping write+read where the read returns the initial value:

```
  C1: W1(x,1)[1-5]
  C2:  R1(x)[2-4] ret=0     (overlaps W1)

  W1 [1-5] and R1 [2-4] OVERLAP -> no real-time edge -> 2 sorts:
    W1 R1   :  [0] W1(->1) R1(=0 MISMATCH)   [illegal]
    R1 W1   :  [0] R1(=0 ok) W1(->1)          [LEGAL -> linearizable]

  (R1, W1) wins: R1 reads the initial 0, THEN W1 writes 1.
```

This is the key freedom linearizability gives for **concurrent** operations: the read happened to complete before the write "took effect". Enumerating all orderings is exponential in the worst case (the general problem is NP-hard, Wing & Gong 1993), but trivial for small histories — which is why model-checkers and testing tools (Jepsen, Knossos) work on bounded histories.

🔗 Run the checker on any history in **[panel ④](./linearizability.html)** and watch it enumerate the sorts.

---

## 5. Implementation cost — linearizability is not free

Why isn't everything linearizable? Because guaranteeing that every read sees the latest write forces replicas to **coordinate** before they respond. The store must pick a single "latest" value, and that needs **consensus** (Raft, Paxos, ZAB) or an equivalent quorum.

> From `linearizability.py` Section E:

| system | mechanism | linearizable? | cost / notes |
|---|---|---|---|
| **etcd** | Raft consensus (quorum) | **YES** | leader + majority round-trip per write |
| **ZooKeeper** | ZAB (Paxos variant) | **YES** (sync read) | default reads are sequential; `sync()` for linearizable |
| **Spanner** | Paxos + TrueTime | **YES** (externally consistent) | GPS/atomic clocks; 2PC across shards |
| **Cassandra (ONE)** | tunable / sloppy quorum | **NO** | eventual; a read may hit a stale replica |
| **Dynamo** | vector clocks, eventual | **NO** | AP store; conflicts resolved after the fact |

**CAP consequence** (Gilbert & Lynch 2002): linearizability + availability are **incompatible** under a network partition. A linearizable store must *refuse* requests it cannot keep consistent ⟹ it is **"CP"**, not "AP".

```
RULE OF THUMB:
  linearizable  =>  consensus / quorum  =>  extra latency + CP on partition
  eventual      =>  no coordination      =>  fast + AP on partition
```

- etcd / ZooKeeper / Spanner: pay Raft/Paxos round-trips + need a live **quorum**; during a partition the minority side **stops** (CP).
- Cassandra / Dynamo: skip coordination, serve any replica fast; reads can be stale, but the store stays **available** under partition (AP).

Linearizability is the strongest **single-object** model. 🔗 It composes (Herlihy & Wing proved it is *local*: if each object is linearizable, the whole system is) — but cross-object transaction guarantees need **serializability**, a separate (stronger, multi-object) property.

---

## 6. Gold check — linearizable passes, non-linearizable fails

> From `linearizability.py` GOLD CHECK:

```
  HIST_A (read sees completed write)          -> LINEARIZABLE     (1 legal / 1 sorts)  [OK]
  HIST_B (stale read after completed write)   -> NOT linearizable (0 legal / 1 sorts)  [OK]
  HIST_C (concurrent writes, read sees later) -> LINEARIZABLE     (1 legal / 2 sorts)  [OK]
  HIST_D (overlapping R/W, read sees initial) -> LINEARIZABLE     (1 legal / 2 sorts)  [OK]

[check] GOLD: all 4 verdicts correct:  OK
[check] HIST_B: linearizable=False, sequentially_consistent=True  (seq is weaker)  ->  OK
```

```
GOLD scalar: is_linearizable(HIST_B) = False  (must be False)
GOLD scalar: #legal sorts HIST_D = 1  (must be 1)
```

The `.html` recomputes all of this in JS on the *identical* four histories and re-asserts the gold badge.

---

## Further reading

- **Herlihy & Wing (1990)**, ACM TOPLAS 12(3):463–492 — *the* source paper; defines linearizability, locality, the linearization-point formulation.
- **Wing & Gong (1993)**, J. Parallel Distrib. Comput. — the WGL checking algorithm (enumerate topological sorts).
- **Lamport (1979)**, IEEE TC C-28(9) — sequential consistency, the weaker model contrasted in §2.
- **Gilbert & Lynch (2002)**, ACM SIGACT News — proves the CAP impossibility result referenced in §5.
- 🔗 [`RAFT.md`](./RAFT.md) — Raft consensus, the mechanism etcd uses to *deliver* linearizability.
- 🔗 [`PAXOS.md`](./PAXOS.md) — Paxos, the consensus foundation behind Spanner/ZooKeeper.
- 🔗 *Kleppmann, DDIA* ch. 5 ("Replication") & ch. 9 ("Consistency and Consensus"); *Herlihy & Shavit, The Art of Multiprocessor Programming* ch. 3.
