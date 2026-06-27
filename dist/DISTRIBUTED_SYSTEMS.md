# Distributed Systems Fundamentals — The System Model, Time, and Fault Tolerance

> A concept bundle for distributed systems. Every number below is printed by
> **[`distributed_systems.py`](./distributed_systems.py)** (pure Python stdlib,
> run with `python3 distributed_systems.py`) and recomputed live in
> **[`distributed_systems.html`](./distributed_systems.html)**. This guide never
> hand-computes anything — it cites the `.py` output verbatim.
>
> 🔗 Interactive companion: [`distributed_systems.html`](./distributed_systems.html) &nbsp;|&nbsp;
>    Source of truth: [`distributed_systems.py`](./distributed_systems.py) &nbsp;|&nbsp;
>    Live capture: [`distributed_systems_output.txt`](./distributed_systems_output.txt)

---

## 0. The one-paragraph version

A distributed system is a collection of **autonomous** computers that cooperate
by **passing messages** over a network you do not control. Four facts shape
every algorithm built on top: (1) **failures are the norm** — nodes crash,
messages are lost, clocks drift, a few nodes may even lie, so the *system model*
names which failures you tolerate and the quorum math (`2f+1` vs `3f+1`) tells
you how many replicas you need; (2) **you cannot trust wall-clocks** — two
machines' clocks drift apart at a bounded rate `ρ`, so we invented **logical
clocks** (Lamport, vector) that order events by *causality* and
**clock-synchronization** algorithms (Cristian, NTP) that bound the skew; (3)
**there is no global "now"** — the only honest cross-machine ordering is the
partial order **happens-before** (`→`), where a send happens-before its receive
and everything else is program order; (4) **timing assumptions change what is
possible** — a *synchronous* system can detect crashes with timeouts, an
*asynchronous* one cannot, and **FLP** says deterministic consensus is then
impossible even with one crash. Real systems assume **partial synchrony**.

> From `distributed_systems.py` GOLD CHECK (the headline numbers):
> ```text
>   n_cft(1)        = 3
>   n_bft(1)        = 4
>   majority_cft(5) = 3
>   om_messages(4,1)= 9
>   om_messages(7,2)= 156
>   lamport_trace   = [1, 2, 3, 1, 4, 5]
>   vector_x_vs_a   = concurrent
>   vector_x_vs_y   = a->b
>   bft_threshold   = N >= 3f+1
> ```

This is the **fundamentals capstone** of the `dist/` suite — it ties together
the building blocks that the deeper bundles expand on:
[`crash_vs_byzantine.py`](https://github.com/quanhua92/tutorials/blob/main/dist/crash_vs_byzantine.py)
(2f+1/3f+1 derivation),
[`sync_vs_async.py`](https://github.com/quanhua92/tutorials/blob/main/dist/sync_vs_async.py)
(FLP & partial synchrony),
[`clock_sync_ntp.py`](https://github.com/quanhua92/tutorials/blob/main/dist/clock_sync_ntp.py)
(Cristian/NTP),
[`lamport_timestamps.py`](https://github.com/quanhua92/tutorials/blob/main/dist/lamport_timestamps.py)
(scalar logical clocks),
[`vector_clocks.py`](https://github.com/quanhua92/tutorials/blob/main/dist/vector_clocks.py)
(causality & concurrency), and
[`failure_detection.py`](https://github.com/quanhua92/tutorials/blob/main/dist/failure_detection.py)
(timeouts vs phi-accrual).

---

## 1. Section A — the system model: failure modes & quorum thresholds

Every distributed algorithm assumes a **system model**: which failures can occur
and what the network/timing guarantees are. Name the model wrong and the
algorithm is silently incorrect. The failure hierarchy, where each level *adds*
a harder failure mode:

> From `distributed_systems.py` Section A:
> ```text
>   | level | failure     | what the faulty node does              |
>   |-------|-------------|----------------------------------------|
>   |   1   | crash       | HALTS. Stops talking. May recover later|
>   |   2   | omission    | DROPS messages (send or receive). Still|
>   |       |             | 'alive' but silent on some messages    |
>   |   3   | byzantine   | ARBITRARY. Wrong data, conflicting data|
>   |       |             | to different peers, collusion, forgery |
> ```

Crash is a **special case** of omission (a crashed node omits everything), and
omission is a special case of byzantine. Tolerating a harder class costs more
replicas. The two quorum thresholds:

- **Crash-fault tolerance (CFT): `N = 2f + 1`.** With `f` crashed, `2f+1 − f =
  f+1` nodes remain — still a **majority** of the original `2f+1`, so a quorum
  can always be formed. Equivalently, any two majorities **overlap** in ≥1
  non-crashed node, so decisions cannot diverge.
- **Byzantine-fault tolerance (BFT): `N = 3f + 1`.** With `f` traitors, the
  honest nodes (≥ `2f+1`) must form a quorum larger than the `f` traitors can
  sway, **and** two honest quorums must overlap in ≥ `f+1` honest nodes.
  `3f+1` is the tight bound.

> From `distributed_systems.py` Section A:
> ```text
>   | f  | CFT N=2f+1 | BFT N=3f+1 | CFT majority | BFT honest quorum |
>   |----|------------|------------|--------------|-------------------|
>   | 0  | 1          | 1          | 1            | 1                 |
>   | 1  | 3          | 4          | 2            | 3                 |
>   | 2  | 5          | 7          | 3            | 5                 |
>   | 3  | 7          | 10         | 4            | 7                 |
>
>   Overlap proof (CFT, N=5): two majorities of 3 in 5 nodes share
>     >= 2*3 - 5 = 1 node. That shared node voted for only
>     one value/leader -> at most one decision per term. This is the single
>     fact that makes majority quorums safe.
>
>   [check] CFT=2f+1, BFT=3f+1, two majorities overlap in >=1 node: OK
> ```

That **overlap fact** (any two majorities share ≥1 node) is the single reason
majority quorums stay safe — it underpins Raft's election safety and Paxos's
quorum intersection. 🔗 Open
[`distributed_systems.html`](https://github.com/quanhua92/tutorials/blob/main/dist/distributed_systems.html)
Panel ① and flip between crash / omission / byzantine at `f=1,2,3` to watch the
minimal cluster grow from 3 → 4 nodes.

---

## 2. Section B — synchronous vs asynchronous: timing assumptions & FLP

A system model is incomplete without a **timing assumption**. Message (and
processing) delay is either bounded and known, or not:

> From `distributed_systems.py` Section B:
> ```text
>   | model        | message delay         | can detect crashes? | consensus? |
>   |--------------|------------------------|---------------------|------------|
>   | synchronous  | BOUNDED, known Delta   | YES (timeout)       | possible   |
>   | asynchronous | UNBOUNDED              | NO (slow == dead)   | IMPOSSIBLE |
>   | partial sync | bounded EVENTUALLY     | eventually          | possible   |
> ```

- **Synchronous:** if a message doesn't arrive within `Δ`, the sender *knows*
  the receiver crashed. Timeouts = perfect failure detectors. Nice, but
  unrealistic — real networks have no hard delay bound (GC pauses, route flaps,
  congestion).
- **Asynchronous:** delay is unbounded. A message that hasn't arrived might
  still arrive in 10 ms or 10 minutes. You **cannot distinguish "slow" from
  "dead"**. This is the Internet.

**The FLP impossibility** (Fischer-Lynch-Paterson 1985): in a fully
asynchronous system, *no deterministic protocol can solve consensus even if
only one node may crash*. Proof sketch: there is an execution where the system
stays forever in a "bivalent" state (could still decide 0 or 1) by delaying one
critical message, so you cannot guarantee termination.

**How real systems escape FLP** (they all do — etcd, Cassandra, Spanner):

- **Partial synchrony** (Dwork-Lynch-Stockmeyer 1988): assume delays are
  unbounded for a while but *eventually* a bound holds. Consensus terminates
  after GST (Global Stabilization Time). **This is what Raft/Paxos actually
  assume.**
- **Randomization:** protocols that flip coins terminate with probability 1
  (Ben-Or 1983) even under asynchrony.
- **Failure detectors** (Chandra-Toueg 1996): an oracle that eventually
  suspects crashed nodes; real detectors (timeouts, φ-accrual) approximate it.

> From `distributed_systems.py` Section B (the practical consequence):
> ```text
>   Practical note: a timeout is a GUESS, not a proof. If you set the
>   failure timeout to T_best=10 ms (the fast case), a node that
>   is merely SLOW (e.g. 2000 ms GC pause) is wrongly declared
>   dead -> false positive -> spurious leader election. Set it to
>   2000 ms and real crashes take 2000 ms to notice ->
>   slow failover. There is no perfect timeout; this is why adaptive /
>   phi-accrual detectors exist.
>
>   [check] async => slow indistinguishable from dead => FLP applies: OK
> ```

🔗 Panel ③ of
[`distributed_systems.html`](https://github.com/quanhua92/tutorials/blob/main/dist/distributed_systems.html)
contrasts the three timing models. Deeper treatment in
[`SYNC_VS_ASYNC.md`](https://github.com/quanhua92/tutorials/blob/main/dist/SYNC_VS_ASYNC.md).

---

## 3. Section C — time & clocks: drift and Lamport logical clocks

**Physical clocks drift.** Two quartz clocks gain/lose at a rate up to `ρ` (a
few parts per million). Over an interval `T` they can diverge by `2·ρ·T`:

> From `distributed_systems.py` Section C:
> ```text
>   rho = 25 ppm,  T =    1 h  ->  max skew 2*rho*T = 0.18 s
>   rho = 25 ppm,  T =   24 h  ->  max skew 2*rho*T = 4.32 s
>   rho = 25 ppm,  T =  720 h  ->  max skew 2*rho*T = 129.60 s
> ```

So even "good" clocks drift ~13 seconds/month apart — you cannot use raw
wall-clock readings to order events across machines. Two responses: (1)
**synchronize** the clocks to a bounded skew `ε` (Cristian/NTP), giving a usable
real-time order with `ε` uncertainty; or (2) **ignore wall-clocks entirely** and
order events by **causality** using a logical clock (Lamport's 1978 insight).

**Happens-before (`→`):** `a → b` if (a,b in the same process with a before b),
OR (a is a send and b is the matching receive), OR by transitivity. If neither
`a → b` nor `b → a`, the events are **concurrent** (`a ‖ b`).

**Lamport clock rule** (one integer `L` per process):

- local/send: `L[i] = L[i] + 1`
- receive(m): `L[i] = max(L[i], L_m) + 1`
- **Property:** `a → b  ⇒  L[a] < L[b]` (but **not** the converse!)

> From `distributed_systems.py` Section C (the pinned 3-process trace):
> ```text
>   P0: a(local)  b(send m1->P1)
>   P1:            c(recv m1)  d(send m2->P2)
>   P2:   x(local)                         y(recv m2)
>
>   | event | proc | kind | L |
>   |-------|------|------|---|
>   | a     | P0   | local | 1 |
>   | b     | P0   | send | 2 |
>   | c     | P1   | recv | 3 |
>   | x     | P2   | local | 1 |
>   | d     | P1   | send | 4 |
>   | y     | P2   | recv | 5 |
>
>   The causal chain a->b->c->d->y gets L = 1,2,3,4,5 (strictly increasing,
>   as happens-before demands: a->b => L[a]<L[b]). But the independent event x
>   also gets L=1 - IDENTICAL to a - even though a and x are CONCURRENT. Worse,
>   x (L=1) sorts BEFORE d (L=4) in the total order, yet x || d (no causal
>   link). Lamport guarantees a->b => L[a]<L[b] but NOT the converse; a single
>   scalar cannot reveal concurrency. That is exactly what vector clocks fix.
>
>   [check] causal chain a<b<c<d<y has strictly increasing Lamport clocks: OK
> ```

A single scalar cannot reveal concurrency — `L[a] == L[x] == 1` hides that they
are concurrent, and `L[x] < L[d]` falsely suggests `x` precedes `d`. 🔗 Panel ②
of [`distributed_systems.html`](https://github.com/quanhua92/tutorials/blob/main/dist/distributed_systems.html)
steps through this trace; toggle Lamport → vector to see the blind spot vanish.

---

## 4. Section D — vector clocks: detecting causality AND concurrency

A **vector clock** fixes Lamport's blind spot. Each process keeps a vector `V`
of `N` integers (one entry per process):

- local/send: `V[i] = V[i] + 1`
- receive(m): `V[k] = max(V[k], V_m[k])` for all `k`, then `V[i]++`
- **Property:** `a → b  ⇔  V[a] ≤ V[b]` componentwise **and** `V[a] ≠ V[b]`;
  otherwise `a ‖ b` (concurrent).

> From `distributed_systems.py` Section D (same trace):
> ```text
>   | event | proc | kind |   vector V    |
>   |-------|------|------|---------------|
>   | a     | P0   | local | [1,0,0]       |
>   | b     | P0   | send | [2,0,0]       |
>   | c     | P1   | recv | [2,1,0]       |
>   | x     | P2   | local | [0,0,1]       |
>   | d     | P1   | send | [2,2,0]       |
>   | y     | P2   | recv | [2,2,2]       |
>
>   | pair    | V[a]         | V[b]         | relation      |
>   |---------|--------------|--------------|---------------|
>   | a , b   | [1,0,0]      | [2,0,0]      | happens-before |
>   | a , c   | [1,0,0]      | [2,1,0]      | happens-before |
>   | c , y   | [2,1,0]      | [2,2,2]      | happens-before |
>   | x , a   | [0,0,1]      | [1,0,0]      | concurrent (||) |
>   | x , y   | [0,0,1]      | [2,2,2]      | happens-before |
>   | a , y   | [1,0,0]      | [2,2,2]      | happens-before |
>
>   [check] vector clock finds x || a (concurrent) and x -> y: OK
> ```

`x = [0,0,1]` vs `a = [1,0,0]`: neither dominates, so they are **concurrent** —
exactly what the Lamport scalar could not show. Dynamo/Riak use **version
vectors** (a close cousin) precisely to detect concurrent writes and surface
them as conflicts instead of silently dropping one. 🔗 Deeper treatment in
[`VECTOR_CLOCKS.md`](https://github.com/quanhua92/tutorials/blob/main/dist/VECTOR_CLOCKS.md)
and
[`LAMPORT_TIMESTAMPS.md`](https://github.com/quanhua92/tutorials/blob/main/dist/LAMPORT_TIMESTAMPS.md).

---

## 5. Section E — fault tolerance: reliability math & replication

How much more reliable does **replication** make a system? Using the standard
exponential-failure model — a node fails at rate `λ = 1/MTBF`, so its
reliability (prob of being up at time `t`) is `R(t) = e^(−λ·t)`:

> From `distributed_systems.py` Section E:
> ```text
>   Single node: MTBF = 1,000,000 h  ->  lambda = 1.00e-06 /h
>
>   | t (1 year = 8760 h) | R_single = e^(-lambda*t) |
>   |----------------------|--------------------------|
>   |  1 yr  ( 8760 h)      | 0.991278               |
>   |  3 yr  (26280 h)      | 0.974062               |
>   |  5 yr  (43800 h)      | 0.957145               |
>   | 10 yr  (87600 h)      | 0.916127               |
> ```

Replication makes the **system** reliability = probability that at least 1 of
`r` replicas is up = `1 − (1 − R)^r` (assuming independent failures):

> From `distributed_systems.py` Section E:
> ```text
>   | replicas r | R_system after 1 yr = 1-(1-R)^r | downtime reduction |
>   |------------|--------------------------------|--------------------|
>   | 1          | 0.9912782570                 | baseline           |
>   | 2          | 0.9999239312                 | ~1x better         |
>   | 3          | 0.9999993365                 | ~1x better         |
>   | 5          | 0.9999999999                 | ~1x better         |
>
>   Three replicas lift 1-year reliability from 0.99128 to 0.9999993365 -
>   the chance ALL three fail simultaneously is (1-R)^3, vanishingly small.
>   This is the math behind 'replication factor 3' in Kafka / Cassandra /
>   Raft: tolerate 1 fault (2f+1 with f=1 needs N=3) while making total data
>   loss astronomically unlikely.
>
>   CAVEATS: this assumes INDEPENDENT failures. Correlated failures (a rack
>   PDU dies, a whole AZ loses power, a bad deploy) break the model - which is
>   why we spread replicas across failure domains (racks/AZs) and demand f+1
>   survivors, not f+1 machines in the same rack.
>
>   [check] r=3 system reliability 0.9999993 > single 0.99128: OK
> ```

The caveat matters more than the formula: **correlated failures** (rack/AZ power
loss, a bad deploy) break the independence assumption, which is why production
systems spread replicas across **failure domains** and demand `f+1` survivors
across distinct racks/AZs, not `f+1` machines in one rack.

---

## 6. Gold check — the Byzantine generals: `3f+1`, OM algorithm, loyal decision

**The Byzantine Generals Problem** (Lamport-Shostak-Pease 1982): several
generals must agree on a common plan (attack/retreat) by exchanging messages,
but the commander (or some lieutenants) may be **traitors** sending conflicting
orders. Goal: all **loyal** lieutenants decide the **same** order.

**The threshold:** agreement is possible iff the number of traitors `f`
satisfies `N ≥ 3f + 1`. Why `3f+1` (not `2f+1`): with `f` traitors, the loyal
majority quorum must be `> f` to outvote them, **and** any two such quorums must
overlap in `> f` loyal nodes (else traitors could make two groups disagree).
Crash tolerance needs only `2f+1` because a crashed node merely *stops* — it
cannot actively forge conflicting votes.

**The OM algorithm** (Oral Messages), the canonical BFT protocol:

- `OM(0)`: commander sends its order to every lieutenant; lieutenants use the
  value received (or a default if none).
- `OM(m)`: commander sends its order; each lieutenant then recursively runs
  `OM(m−1)` as the *new* commander forwarding what it heard, over the remaining
  lieutenants. Finally each loyal lieutenant takes the **majority** of all
  values it collected.

`OM(m)` tolerates `f` traitors iff `m ≥ f` (so it runs `f+1` rounds). Message
complexity grows like `O(N^(f+1))`:

> From `distributed_systems.py` GOLD CHECK:
> ```text
>   | f | rounds m=f | min N | OM messages |
>   |---|------------|-------|-------------|
>   | 0 | 0          | 1     | 0           |
>   | 1 | 1          | 4     | 9           |
>   | 2 | 2          | 7     | 156         |
>   | 3 | 3          | 10    | 3609        |
>
>   WORKED EXAMPLE (f=1, N=4, commander C is the traitor):
>     commander C sends DIFFERENT orders to the 3 loyal lieutenants:
>       C -> L1: 'attack'
>       C -> L2: 'attack'
>       C -> L3: 'retreat'      <- the lie
>     OM(1): each lieutenant forwards what it heard from C to the other two.
>     What L1 collects: majority('attack','attack','retreat') = ATTACK
>     Similarly L2 and L3 each compute ATTACK.
>     ALL THREE LOYAL LIEUTENANTS DECIDE IDENTICALLY -> agreement.
>
>     Contrast N=3, f=1 (one short of 3f+1): C->L1 'attack', C->L2 'retreat'.
>     L1 hears {attack, retreat} -> tie; L2 hears {retreat, attack} -> tie.
>     They CANNOT agree. 3f+1 is TIGHT.
>
>   GOLD scalars (for a compact .html check):
>     n_cft(1)        = 3
>     n_bft(1)        = 4
>     majority_cft(5) = 3
>     om_messages(4,1)= 9
>     om_messages(7,2)= 156
>     lamport_trace   = [1, 2, 3, 1, 4, 5]
>     vector_x_vs_a   = concurrent
>     vector_x_vs_y   = a->b
>     bft_threshold   = N >= 3f+1
>
>   [check] 3f+1 threshold, OM message counts, Lamport+vector traces all hold: OK
> ```

The `.html` recomputes the **full pipeline** in JavaScript — the quorum
thresholds, the OM message-count recurrence, and the identical Lamport +
vector-clock traces. A green `check: OK` badge means the two implementations
agree. 🔗 Deeper BFT treatment in
[`PBFT.md`](https://github.com/quanhua92/tutorials/blob/main/dist/PBFT.md) and
[`CRASH_VS_BYZANTINE.md`](https://github.com/quanhua92/tutorials/blob/main/dist/CRASH_VS_BYZANTINE.md).

---

## 7. References

- **Lamport (1978)** — "Time, Clocks, and the Ordering of Events in a
  Distributed System". Happens-before, Lamport clocks. The foundational paper.
- **Mattern (1989) / Fidge (1988)** — vector clocks; exact causality detection.
- **Fischer, Lynch, Paterson (1985)** — FLP impossibility (asynchronous
  consensus with one crash).
- **Dwork, Lynch, Stockmeyer (1988)** — partial synchrony (how to escape FLP).
- **Lamport, Shostak, Pease (1982)** — The Byzantine Generals Problem; `3f+1`
  threshold + OM algorithm.
- **Chandra & Toueg (1996)** — unreliable failure detectors → consensus.
- **Schneider (1990)** — "Implementing Fault-Tolerant Services Using the State
  Machine Approach" (the replicated-state-machine recipe).
- **Cristian (1989)** / **Mills (NTP, 1991)** — probabilistic / statistical
  clock synchronization.
- **Tanenbaum & Van Steen** — *Distributed Systems*, Ch. 3 (Synchronization).

🔗 Back to [`distributed_systems.html`](https://github.com/quanhua92/tutorials/blob/main/dist/distributed_systems.html)
for the interactive failure-model explorer, clock-sync visualizer, and timing-model comparison.
