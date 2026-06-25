# SEQUENTIAL CONSISTENCY — Program Order Is the Only Law

> A **concept bundle**: this guide + [`sequential_consistency.py`](./sequential_consistency.py) + [`sequential_consistency.html`](./sequential_consistency.html).
> Every number below is printed by the `.py` (the single source of truth) and recomputed live by the `.html`. Nothing is hand-computed.
> Interactive companion: **[`sequential_consistency.html`](./sequential_consistency.html)**. 🔗 Back to [all tutorials](../index.html).

---

## 0. Why this exists: "one agreed script, real time be damned"

Picture `N` processes sharing a single register `X`. Each process runs a **program** — a fixed sequence of reads and writes in **program order**. The processes run concurrently, so in real time their operations interleave unpredictably. **Sequential consistency** (Lamport 1979) says:

> There exists *some* total order of all operations (a single **script**) such that (1) replaying it is a **legal** sequential register history and (2) the script preserves each process's own **program order**. If such a script exists, the execution is sequentially consistent.

Notice what is **not** in the definition: **real time**. The script does *not* have to respect the order in which operations actually completed. If process `P1`'s write finishes at noon and process `P2`'s read starts at 1pm, sequential consistency is free to place `P2`'s read **before** `P1`'s write in the script — as if `P2` "hadn't noticed" the write yet. The only thing it must honor is each process's **own** operation order.

That missing real-time clause is the whole difference from **linearizability** (Herlihy & Wing 1990): linearizability *adds* "and the script must respect real-time order." **Sequential consistency = linearizability minus real time.** This single clause makes sequential consistency *strictly weaker*: every linearizable history is sequentially consistent, but not vice versa (§2).

The classic consequence is the **stale read**: `P1` writes `X=1`, then `P2` reads `X=0` even though `P2`'s read started *after* `P1`'s write completed. Sequential consistency accepts it (place `P2`'s read first in the script); linearizability rejects it. This is why "strongly consistent" systems (etcd, Spanner) cost you consensus, while sequential consistency is what a shared-memory multiprocessor with snooping caches gives you "for free" (Papamarcos & Patel 1984) — and is all Lamport's 1979 paper actually required.

| Concept | Definition |
|---|---|
| **register** `X` | a single read/write object; the only shared state here. |
| **process** (`P_i`) | one of the concurrent programs; has a fixed **program order**. |
| **program order** | the order of operations *inside* one process. MUST be preserved by any sequentially-consistent script. The ONLY constraint sequential consistency imposes. |
| **operation** | a `read` or `write`, issued by one process; has `inv`/`resp` — real-time instants used ONLY for the linearizability contrast. |
| **total order** (script) | a permutation of all operations — the candidate single agreed sequence. |
| **valid script** | a total order that (1) preserves program order AND (2) is a legal register history. A history is sequentially consistent iff **some** valid script exists. |
| **real-time order** | if `resp(A) ≤ inv(B)` then `A` precedes `B`. *Ignored* by sequential consistency; *enforced* by linearizability. |
| **stale read** | a read returning an older value than a write that completed before it started. Sequentially OK; NOT linearizable. |

> **Paper**: Lamport, L. (1979). *"How to Make a Multiprocessor Computer That Correctly Executes Multiprocess Programs."* IEEE Trans. Comput. **C-28**(9), 690–691. Defines sequential consistency. The stronger contrast model is Herlihy & Wing (1990); the cheap-implementation argument is Papamarcos & Patel (1984).

---

## 1. A sequentially consistent history — the stale-read script

Register `X` starts at `0`. `P1` writes `X=1` then reads it back (`1`); `P2` reads twice — first `0`, then `1`. The catch: `P2`'s first read returns `0` *although* `W1` completed at `t=3`, long before the read started at `t=7`.

```
  P1: W1(x,1)[1-3]  R2(x)=1[4-6]
  P2:                    R3(x)=0[7-9]  R4(x)=1[10-12]
```

> From `sequential_consistency.py` Section A:

```
PROGRAM ORDER (the ONLY thing sequential consistency enforces):
  R3 -> R4   (same process, invocation order)
  W1 -> R2   (same process, invocation order)
  (NO cross-process edges: P1's ops and P2's ops may be interleaved
   however we like when building the script.)

Checker: 6 program-order-preserving script(s); 2 legal register history(s):

  W1 R2 R3 R4    :  [0] W1(->1) R2(=1 ok) R3(=0 MISMATCH ret=0) R4(=1 ok)   [illegal (read mismatch)]
  W1 R3 R2 R4    :  [0] W1(->1) R3(=0 MISMATCH ret=0) R2(=1 ok) R4(=1 ok)   [illegal (read mismatch)]
  W1 R3 R4 R2    :  [0] W1(->1) R3(=0 MISMATCH ret=0) R4(=1 ok) R2(=1 ok)   [illegal (read mismatch)]
  R3 W1 R2 R4    :  [0] R3(=0 ok) W1(->1) R2(=1 ok) R4(=1 ok)   [LEGAL  -> valid script]
  R3 W1 R4 R2    :  [0] R3(=0 ok) W1(->1) R4(=1 ok) R2(=1 ok)   [LEGAL  -> valid script]
  R3 R4 W1 R2    :  [0] R3(=0 ok) R4(=1 MISMATCH ret=1) W1(->1) R2(=1 ok)   [illegal (read mismatch)]

Verdict: HIST_A is sequentially consistent.
Canonical valid script:  R3 W1 R2 R4
  replay: [0] R3(=0 ok) W1(->1) R2(=1 ok) R4(=1 ok)
```

Two valid scripts exist, both of the form `R3, W1, …`: `P2`'s stale read is placed **first** in the script, so it correctly observes the initial `0`; only *then* does `W1` write `1`. Each process's own order is intact (`P1`: `W1<R2`; `P2`: `R3<R4`). Real time is simply ignored. **That** is sequential consistency (Lamport 1979): there exists *some* sequential order.

🔗 Build your own script and watch the verdict in **[panel ②](./sequential_consistency.html)**.

---

## 2. vs linearizability — add the real-time clause, the verdict flips

Same history `HIST_A`. Now *also* require the script to respect real time (Herlihy & Wing 1990): if `resp(A) ≤ inv(B)` then `A` MUST precede `B`.

> From `sequential_consistency.py` Section B:

```
Real-time partial order (resp(A) <= inv(B) => A before B):
  R2 -> R3   (resp(R2)=6 <= inv(R3)=7)
  R2 -> R4   (resp(R2)=6 <= inv(R4)=10)
  R3 -> R4   (resp(R3)=9 <= inv(R4)=10)
  W1 -> R2   (resp(W1)=3 <= inv(R2)=4)
  W1 -> R3   (resp(W1)=3 <= inv(R3)=7)
  W1 -> R4   (resp(W1)=3 <= inv(R4)=10)

  Cross-process edge W1 -> R3 is forced: resp(W1)=3 <= inv(R3)=7.
  Under linearizability R3 CANNOT be placed before W1 in the script.

Linearizability checker: 1 real-time sort(s); 0 legal:

  W1 R2 R3 R4    :  [0] W1(->1) R2(=1 ok) R3(=0 MISMATCH ret=0) R4(=1 ok)   [illegal (read mismatch)]

Verdict: HIST_A is NOT linearizable.

--- side-by-side ---
  sequential consistency: 6 program-order sorts, 2 legal -> YES
  linearizability      : 1 real-time sorts, 0 legal -> NO

Real-time edges minus program-order edges (the ones seq IGNORES): [('R2', 'R3'), ('R2', 'R4'), ('W1', 'R3'), ('W1', 'R4')]
W1 -> R3 is exactly the edge that, once removed, lets R3 read 0.
```

The *only* real-time-consistent script starts with `W1`, so `R3` must read `1`; it read `0` → no linearization exists. **THE GAP:** real-time edges are a **superset** of program-order edges (every same-process pair is also time-ordered), so linearizability permits *fewer* scripts. Sequential consistency drops the cross-process real-time edges (like `W1 → R3`) and the stale read becomes legal.

```
[check] HIST_A seq=True, linearizable=False (seq strictly weaker) -> OK
[check] HIST_B (well-behaved) seq=True, linearizable=True -> OK
```

**That clause — enforcing real time — is exactly what linearizability adds.** It is what costs you consensus (§5). The well-behaved `HIST_B` (all reads see the completed write, return `1`) satisfies *both* models.

🔗 Toggle the model in **[panel ③](./sequential_consistency.html)** and watch `HIST_A` flip from YES (sequential) to NO (linearizable).

---

## 3. Program order is locked, cross-process order is free

Sequential consistency lets the script reorder operations **across** processes at will, but each process's **own** operations must stay in program order. `HIST_C` makes this vivid: both writes set `1`, both reads see `1`, so *several* cross-process interleavings are legal.

```
  P1: W1(x,1)[1-2]  W2(x,1)[3-4]
  P2: R3(x)=1[5-6]  R4(x)=1[7-8]
```

> From `sequential_consistency.py` Section C:

```
PROGRAM ORDER: [('R3', 'R4'), ('W1', 'W2')]
  (W1 before W2 on P1; R3 before R4 on P2. Nothing else is locked.)

There are 6 program-order-preserving scripts; 3 are LEGAL register histories:

  W1 W2 R3 R4    :  [0] W1(->1) W2(->1) R3(=1 ok) R4(=1 ok)   [LEGAL  -> valid script]
  W1 R3 W2 R4    :  [0] W1(->1) R3(=1 ok) W2(->1) R4(=1 ok)   [LEGAL  -> valid script]
  W1 R3 R4 W2    :  [0] W1(->1) R3(=1 ok) R4(=1 ok) W2(->1)   [LEGAL  -> valid script]
  R3 W1 W2 R4    :  [0] R3(=1 MISMATCH ret=1) ...             [illegal]
  R3 W1 R4 W2    :  [0] R3(=1 MISMATCH ret=1) ...             [illegal]
  R3 R4 W1 W2    :  [0] R3(=1 MISMATCH ret=1) R4(=1 MISMATCH ret=1) ...  [illegal]

Verdict: HIST_C is sequentially consistent (3 valid scripts).
```

The 3 valid scripts all honor `W1<W2` and `R3<R4`, yet interleave the cross-process operations differently (`W1 W2 R3 R4`, `W1 R3 W2 R4`, `W1 R3 R4 W2`). The 3 illegal ones all *start* with `R3` or `R4` — a read of `1` *before any write* — so the register would return the initial `0`, not `1`. They still preserve program order; they just aren't legal register traces.

> **MORAL:** "preserves program order" is *necessary but not sufficient* — the script must **also** read back values consistent with the writes.

🔗 Drag the operation chips into your own order in **[panel ②](./sequential_consistency.html)** and see which orderings are valid.

---

## 4. An invalid history — same-process write then stale read

Sequential consistency can be **violated within a single process**. `P1` writes `X=1`, then on the **same** process reads `X` back and gets `0`:

```
  P1: W1(x,1)[1-2]  R2(x)=0[3-4]
```

> From `sequential_consistency.py` Section D:

```
  W1 and R2 are on process P1, so program order forces W1 before R2
  in EVERY script. After W1 the register holds 1, so R2 must read >=1.
  R2 returned 0 -> no legal script can exist.

Checker: 1 program-order sort(s); 0 legal:

  W1 R2          :  [0] W1(->1) R2(=0 MISMATCH ret=0)   [illegal (read mismatch)]

Verdict: HIST_D is NOT sequentially consistent.
```

The *only* script is `(W1, R2)`; replaying it writes `1` then reads back `0`, which no register can produce. Program order has been violated by the **execution itself** — a process must always see its own writes.

This is the deepest guarantee sequential consistency gives you: **a process never observes its own past as "not having happened yet."** The stale read of §1 was allowed *precisely* because the reader (`P2`) was a **different** process from the writer (`P1`). Same process? Forbidden.

```
[check] HIST_D NOT sequentially consistent?  OK
```

🔗 Try to build a valid script for `HIST_D` in **[panel ②](./sequential_consistency.html)** — you can't.

---

## 5. The consistency hierarchy

Each model is a constraint on the allowed scripts. Moving **down** the hierarchy **drops** a constraint, so more histories become legal:

> From `sequential_consistency.py` Section E:

| model | what it requires of the script | stale read of a COMPLETED write? | real-world systems |
|---|---|---|---|
| **strict** | op appears to execute AT its invocation instant | FORBIDDEN (write visible immediately) | idealized; needs global clock |
| **linearizable** | op atomic somewhere in `[inv,resp]`, respects real time | FORBIDDEN (real-time forces write before read) | etcd, Spanner, ZooKeeper+sync |
| **sequential** | total order preserving program order (NO real time) | ALLOWED if reader is a different process | shared-memory multiprocessors |
| **causal** | preserves causally-related order; concurrent ops free | ALLOWED (read may be causally unrelated to write) | cooperative caches, some stores |
| **eventual** | no order guarantee; replicas converge eventually | ALLOWED, possibly for a long time | Dynamo, Cassandra (default) |

Applied to the stale-read scenario (`P1` writes `X=1` [completes], `P2` reads `X=0`):

```
  strict        -> P2 reads 1 (write visible the instant P1 invoked it)
  linearizable  -> P2 reads 1 (write completed before P2's read started)
  sequential    -> P2 MAY read 0 (real time ignored; reader != writer)
  causal        -> P2 MAY read 0 (read not caused by the write)
  eventual      -> P2 MAY read 0, and may keep reading 0 for a while

Containment (every higher model implies every lower one):
  strict  >  linearizable  >  sequential  >  causal  >  eventual
  i.e. linearizable => sequentially consistent (always), but NOT back.
  HIST_A proves the strictness: seq=YES but linearizable=NO.
```

Where sequential consistency sits:
- **Stronger than causal/eventual:** it enforces a *single global order*, so two processes always agree on the order of **all** operations (even concurrent ones). Causal/eventual let different processes *disagree* on the order of concurrent operations.
- **Weaker than linearizable/strict:** it drops the real-time clause, so a read can ignore a completed write. That is the gap in §2, and it is why sequential consistency is **cheap** to provide (a snooping cache suffices, Papamarcos & Patel 1984) while linearizability needs **consensus** (CAP, Gilbert & Lynch 2002).

🔗 See the hierarchy visualized in **[panel ④](./sequential_consistency.html)**.

---

## 6. Gold check — sequentially consistent iff a valid program-order script exists

> From `sequential_consistency.py` GOLD CHECK:

```
Defining test: a history is sequentially consistent IFF some total
order that preserves program order is a legal register history.

  HIST_A (stale read across processes)           -> seq. consistent      (2 legal / 6 sorts)  [OK]
  HIST_B (well-behaved reads)                    -> seq. consistent      (3 legal / 6 sorts)  [OK]
  HIST_C (program-order freedom)                 -> seq. consistent      (3 legal / 6 sorts)  [OK]
  HIST_D (same-process write then stale read)    -> NOT seq. consistent  (0 legal / 1 sorts)  [OK]

[check] GOLD: all 4 sequential verdicts correct:  OK

[check] HIST_A: sequentially_consistent=True, linearizable=False  (seq strictly weaker)  ->  OK
  This is the exact gap: sequential consistency ignores real time,
  linearizability enforces it. That clause is the whole definition.

GOLD scalars (pinned for sequential_consistency.html):
  is_seq_consistent(HIST_A) = True   (must be True)
  #legal program-order scripts HIST_A = 2 / 6  (must be 2 / 6)
  #legal program-order scripts HIST_C = 3 / 6  (must be 3 / 6)
  is_seq_consistent(HIST_D) = False   (must be False)
```

The `.html` recomputes all of this in JS on the *identical* four histories and re-asserts the gold badge.

---

## Further reading

- **Lamport (1979)**, IEEE TC C-28(9):690–691 — *the* source paper; defines sequential consistency ("as if ... some sequential order, preserving program order").
- **Herlihy & Wing (1990)**, ACM TOPLAS 12(3):463–492 — linearizability, the strictly-stronger contrast model in §2.
- **Papamarcos & Patel (1984)**, IEEE TC C-33(10) — a snooping-cache coherence protocol; the practical reason shared-memory machines give you sequential consistency cheaply.
- **Gilbert & Lynch (2002)**, ACM SIGACT News — CAP; why the *next* step up (linearizability) costs you consensus and availability under partition.
- 🔗 [`LINEARIZABILITY.md`](./LINEARIZABILITY.md) — the stronger sibling; this guide is its mirror image (same checker, real-time edges instead of program-order edges).
- 🔗 [`CAUSAL_CONSISTENCY.md`](./CAUSAL_CONSISTENCY.md) & [`EVENTUAL_CONSISTENCY.md`](./EVENTUAL_CONSISTENCY.md) — the weaker rungs of the §5 hierarchy.
- 🔗 *Kleppmann, DDIA* ch. 5 ("Replication") & ch. 9 ("Consistency and Consensus"); *Tanenbaum & Van Steen, Distributed Systems* ch. 6 ("Consistency and Replication").
