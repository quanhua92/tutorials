# Consistency Models & CAP — The Hierarchy, Session Guarantees, and Quorums

> A concept bundle for distributed systems. Every number below is printed by
> **[`consistency_models.py`](./consistency_models.py)** (pure Python stdlib, run
> with `python3 consistency_models.py`) and recomputed live in
> **[`consistency_models.html`](./consistency_models.html)**. This guide never
> hand-computes anything — it cites the `.py` output verbatim.
>
> 🔗 Interactive companion: [`consistency_models.html`](./consistency_models.html) &nbsp;|&nbsp;
>    Source of truth: [`consistency_models.py`](./consistency_models.py) &nbsp;|&nbsp;
>    Live capture: [`consistency_models_output.txt`](./consistency_models_output.txt)

---

## 0. The one-paragraph version

A **consistency model** is the contract a data store makes about what value a
read returns, given a history of concurrent writes. Stronger models make bigger
promises (and cost more coordination); weaker ones are faster and more available
but let clients see anomalies (stale data, reordered writes). The models form a
**hierarchy** — linearizable (strongest) implies sequential implies causal implies
read-your-writes implies eventual (weakest). The rule of thumb: pick the
**weakest** model your data's product promise allows. A bank balance needs
**linearizable** (over-selling is fatal); a like count is fine with **eventual**
(temporary undercount is invisible). **CAP** says that during a partition you
must drop Consistency (CP) or Availability (AP); **PACELC** adds that even with
no partition you still trade Latency vs Consistency every request. And in an AP
store with `N` replicas, the **quorum** identity `R + W > N` is what makes a read
guaranteed fresh — the read set and write set must overlap.

> From `consistency_models.py` GOLD CHECK (the headline numbers):
> ```text
>   models_count        = 5
>   strongest           = linearizable
>   weakest             = eventual
>   strongest_available = causal   (strongest model that survives a partition)
>   stale_read_divider  = linearizable/sequential PREVENT; causal+ ALLOW
>   quorum(3)           = 2
>   quorum(5)           = 3
>   strong_read_rule    = R + W > N
>   strong_N3_W2_R2     = YES (2+2=4>3)
>   strong_N3_W1_R1     = no (1+1=2<3)
>   intersection(N3,W2) = R+2-3
> ```

This is the **consistency capstone** of the `dist/` suite — it ties together the
building blocks the deeper bundles expand on:
[`linearizability.py`](https://github.com/quanhua92/tutorials/blob/main/dist/linearizability.py),
[`sequential_consistency.py`](https://github.com/quanhua92/tutorials/blob/main/dist/sequential_consistency.py),
[`causal_consistency.py`](https://github.com/quanhua92/tutorials/blob/main/dist/causal_consistency.py),
[`eventual_consistency.py`](https://github.com/quanhua92/tutorials/blob/main/dist/eventual_consistency.py),
[`session_guarantees.py`](https://github.com/quanhua92/tutorials/blob/main/dist/session_guarantees.py),
[`cap_tradeoffs.py`](https://github.com/quanhua92/tutorials/blob/main/dist/cap_tradeoffs.py), and
[`quorum_rw.py`](https://github.com/quanhua92/tutorials/blob/main/dist/quorum_rw.py).

---

## 1. Section A — the hierarchy: what each model guarantees and prevents

The models nest: each stronger model prevents **every** anomaly the weaker one
prevents, plus more. Stronger = safer but slower (coordination round-trips) and
less available under partition.

> From `consistency_models.py` Section A:
> ```text
>   linearizable  >  sequential  >  causal  >  read-your-writes  >  eventual
>   (strongest, most coordination)             (weakest, most available)
>
>   | model            | rank | stale read? | avail. under partition? | prevents          |
>   |------------------|------|-------------|-------------------------|-------------------|
>   | linearizable     |    5 | PREVENTED   | no (CP)                 | stale read + lost update |
>   | sequential       |    4 | PREVENTED   | no (CP)                 | stale read + lost update |
>   | causal           |    3 | allowed     | YES                     | convergence only |
>   | read-your-writes |    2 | allowed     | YES                     | convergence only |
>   | eventual         |    1 | allowed     | YES                     | convergence only |
>
>   [check] hierarchy strictly ordered, linearizable prevents stale, eventual doesn't: OK
> ```

**Stale read is the dividing line:** linearizable/sequential **prevent** it; causal
and weaker **allow** it (a read may return an old value). Linearizable adds a
**real-time** guarantee on top of sequential (once a write completes, every later
read sees it); sequential only guarantees program order. On the availability axis,
only the strong (CP) models block the minority; **causal is the strongest model
that stays available during a partition**. 🔗 Open
[`consistency_models.html`](https://github.com/quanhua92/tutorials/blob/main/dist/consistency_models.html)
Panel ① and click each rung to see what it prevents.

---

## 2. Section B — strong vs eventual: a concrete read-after-write trace

> From `consistency_models.py` Section B (3 replicas {A,B,C}, key x):
> ```text
>   t=0   x=0 on all replicas
>   t=10  client W1 writes x=1   (write begins)
>   t=20  write x=1 committed at the leader
>   t=25  client R1 reads x
>   t=30  replica C still has x=0 (async replication lag)
>
>   | model           | read served by A/B (has x=1) | served by C (x=0) | verdict        |
>   |-----------------|------------------------------|-------------------|----------------|
>   | linearizable    | x=1                          | x=1 (must consult) | CORRECT        |
>   | eventual        | x=1                          | x=0               | STALE (allowed)|
> ```

Under **linearizability** the read at `t=25` **must** return `x=1`: the write
completed at `t=20`, real-time says `t=25 > t=20`, so every later read sees it. A
linearizable read cannot be served from a stale replica alone — it consults a
quorum/leader. Under **eventual** consistency, a read served by the lagging
replica C returns `x=0` — a **stale read**. This is allowed (the model only
promises eventual convergence) but is a real anomaly a user can observe.

The **cost**: a linearizable read on `N=3` needs ≥ `quorum=2` acks (a round-trip
to a majority), so it is slower than a 1-replica eventual read. That latency is
the price of "no stale reads" — PACELC names it. 🔗 Deeper treatment in
[`LINEARIZABILITY.md`](https://github.com/quanhua92/tutorials/blob/main/dist/LINEARIZABILITY.md)
and
[`EVENTUAL_CONSISTENCY.md`](https://github.com/quanhua92/tutorials/blob/main/dist/EVENTUAL_CONSISTENCY.md).

---

## 3. Section C — causal consistency: the strongest always-available model

**Causal** consistency guarantees: if operation `a` **happens-before** `b`
(`a → b`), every client observes `a` before `b`. **Concurrent** operations
(`a ‖ b`) may be seen in different orders by different clients — and that is fine,
because there is no causal dependency to violate. This makes causal the
**strongest model that stays available under a partition** (linearizable/sequential
need coordination and are not available during a split).

> From `consistency_models.py` Section C (a comment thread):
> ```text
>   m1: Alice posts 'Hello'                        (P1 writes m1)
>   m2: Bob   replies 'Hi Alice'  (m2 causally->m1) (P2 writes m2, depends on m1)
>   m3: Carol posts 'Nice weather' (m3 || m2)       (P3 writes m3, independent)
>
>   Under CAUSAL consistency, every reader sees m1 before m2 (causal dep), but m2
>   and m3 may appear in EITHER order (they are concurrent - no dependency):
>
>     reader X sees: m1, m2, m3
>     reader Y sees: m1, m3, m2     <- both LEGAL (m2||m3)
>
>   Under EVENTUAL (without causal) a reader could even see m2 (Bob's 'Hi Alice')
>   BEFORE m1 (Alice's 'Hello') - a reply before the message it answers.
>
>   [check] m2 causally depends on m1; m2 and m3 are concurrent: OK
> ```

**Mechanism:** track causality with **vector clocks / version vectors**. A write
carries the versions it read-from; a replica delays applying a write until its
causal dependencies are present. This is how COPS / Bolt-on Causal and (effectively)
chat systems work. 🔗 See
[`CAUSAL_CONSISTENCY.md`](https://github.com/quanhua92/tutorials/blob/main/dist/CAUSAL_CONSISTENCY.md)
and
[`VECTOR_CLOCKS.md`](https://github.com/quanhua92/tutorials/blob/main/dist/VECTOR_CLOCKS.md).

---

## 4. Section D — session guarantees: read-your-writes & monotonic reads

**Session guarantees** (Terry et al 1994, Bayou) sit between causal and eventual.
They bound what a **single client's session** can see, without paying for global
coordination:

- **Read-your-writes (RYW):** if a client writes `x=v`, every later read of `x`
  by the **same** client returns `v` (or newer). You always see your own actions.
- **Monotonic reads:** once a client reads `x=v`, it never later reads an
  **older** value of `x`. Time never runs backwards for that client.

> From `consistency_models.py` Section D (profile edit then reload):
> ```text
>   write:  name = 'Quan'   (at t=10, accepted by replica A)
>   read at t=12 served by replica B (async lag, still has old 'Bob')
>
>   | guarantee        | what the reload shows | ok?                |
>   |------------------|-----------------------|---------------------|
>   | none (plain ev.) | 'Bob' (stale)         | VIOLATION (confusing)|
>   | read-your-writes | 'Quan'                | OK - sees own write  |
>   | monotonic reads  | (n/a here)            | prevents regressions |
>
>   Monotonic-reads violation (what it prevents):
>     t=1  read x from replica A -> sees version 5
>     t=2  read x from replica C -> sees version 3   <- went BACKWARDS in time
>     Monotonic reads forces t=2 to wait for version >= 5. Prevented.
>
>   [check] RYW => reload shows own write; monotonic reads => no backwards reads: OK
> ```

**How RYW is implemented without global linearizability:** sticky sessions
(route reads to the write's replica), write-through cache (client caches its own
writes), or version sticking (read carries the write's version; the store delays
until a replica has ≥ that version). Both are **per-session**, so they cost
nothing globally — this is why social feeds use them (you see your own post, your
feed never jumps backwards) without paying for linearizability on every like. 🔗
See
[`SESSION_GUARANTEES.md`](https://github.com/quanhua92/tutorials/blob/main/dist/SESSION_GUARANTEES.md).

---

## 5. Section E — quorum systems: the R+W>N tunable dial

In an AP store (Dynamo/Cassandra) with `N` replicas, each request picks how many
replicas must acknowledge: `W` for a write, `R` for a read. The **key identity**:

> a read is guaranteed to see the latest committed write  ⇔  **R + W > N**

**Why:** the read contacts `R` replicas and the write contacted `W`. If
`R + W > N` then those two sets must **overlap** in at least one replica
(pigeonhole), and that overlap replica holds the fresh value. The intersection
size is `|R_set ∩ W_set| >= R + W - N` (≥1 exactly when `R + W > N`).

> From `consistency_models.py` Section E (N=3, write to W=2):
> ```text
>   | read R | R+W | >N? | can read miss the write? | verdict        |
>   |--------|-----|-----|--------------------------|----------------|
>   | 1      | 3   | no  | YES - could read only C  | may be stale   |
>   | 2      | 4   | YES | NO - every R-set hits {A,B} | STRONG read    |
>   | 3      | 5   | YES | NO - every R-set hits {A,B} | STRONG read    |
>
>   The full tunable dial (N=3):
>   | config      | W | R | R+W | strong? | latency       | use when                  |
>   |-------------|---|---|-----|---------|---------------|---------------------------|
>   | one/one     | 1 | 1 |  2  | no      | lowest (1 RTT) | counters, fast stale reads |
>   | write-all   | 3 | 1 |  4  | YES     | higher (2+ RTT) | bank-balance reads |
>   | quorum      | 2 | 2 |  4  | YES     | higher (2+ RTT) | bank-balance reads |
>   | read-all    | 1 | 3 |  4  | YES     | higher (2+ RTT) | profile/registry reads |
>   | all/all     | 3 | 3 |  6  | YES     | higher (2+ RTT) | profile/registry reads |
>
>   Quorum majority grows with N. For N=5: quorum = floor(5/2)+1 = 3.
>     W=R=3 (both quorum) -> 3+3=6 > 5 -> STRONG. This is the Dynamo/Cassandra
>     'QUORUM reads/writes' default that gives strong-ish consistency on N=3 or N=5.
>
>   [check] strong read iff R+W>N; N=5 quorum=3, 3+3=6>5 strong: OK
> ```

🔗 Panel ③ of
[`consistency_models.html`](https://github.com/quanhua92/tutorials/blob/main/dist/consistency_models.html)
is a live quorum calculator — drag `N/R/W` and watch the overlap replicas turn
green as the read flips between fresh and stale. Deeper treatment in
[`QUORUM_RW.md`](https://github.com/quanhua92/tutorials/blob/main/dist/QUORUM_RW.md).

---

## 6. Gold check — CAP recap & data-type → model mapping

**CAP** (Brewer 2000 / Gilbert-Lynch 2002): during a partition you must drop
Consistency (CP) or Availability (AP). **PACELC** (Abadi 2010) adds: even with no
partition you still trade Latency vs Consistency every request.

> From `consistency_models.py` GOLD CHECK:
> ```text
>   | family | partitioned (CAP) | else (PACELC)  | example systems            |
>   |--------|-------------------|----------------|----------------------------|
>   | CP/EC  | drop A (block)    | drop L (quorum)| etcd, ZooKeeper, Spanner   |
>   | AP/EL  | drop C (diverge)  | drop C (async) | Cassandra, DynamoDB, Riak  |
>
>   Which model to pick? Map each DATA TYPE to the weakest model its product
>   promise allows (the CAP/PACELC 'right tool' philosophy):
>
>   | data type                   | model chosen    | why                                  |
>   |------------------------------|-----------------|--------------------------------------|
>   | bank balance / inventory    | LINEARIZABLE    | over-sell / split-brain is fatal     |
>   | leader election / lock      | LINEARIZABLE    | two leaders = data corruption        |
>   | DM thread / comment replies | CAUSAL          | reply must follow its parent message |
>   | user's own profile edit     | READ-YOUR-WRITES| user must see own write immediately  |
>   | like / view / follower count| EVENTUAL        | temp undercount ok; availability wins|
>   | distributed shopping cart   | EVENTUAL + CRDT | concurrent adds must merge, not drop |
>
>   [check] hierarchy, CAP families, R+W>N strong rule all hold: OK
> ```

**Rule of thumb:** start with the **weakest** model you can defend to product, and
escalate **only** where an anomaly would cause real harm. Stronger models cost
latency (quorum round-trips) and availability (CP blocks the minority). The `.html`
recomputes the hierarchy, CAP families, and `R+W>N` math in JavaScript — a green
`check: OK` badge means the two implementations agree.

---

## 7. References

- **Herlihy & Wing (1990)** — linearizability, formal definition.
- **Lamport (1979)** — "How to Make a Multiprocessor Computer…" (sequential/strong seeds).
- **Lamport (1978)** — happens-before → causal consistency foundation.
- **Terry et al (1994)** — "Session Guarantees for Weakly Consistent Replicated
  Data" (RYW, monotonic reads/writes, WFR; Bayou).
- **Brewer (2000) / Gilbert & Lynch (2002)** — CAP conjecture + formal proof.
- **Abadi (2010)** — PACELC.
- **DeCandia et al (2007)** — Dynamo; tunable `N/R/W` eventual consistency.
- **Lloyd et al (2011)** — COPS, scalable causal consistency.
- **Viotti & Vukolić (2016)** — "Consistency Models Not Just a Story" (survey).

🔗 Back to [`consistency_models.html`](https://github.com/quanhua92/tutorials/blob/main/dist/consistency_models.html)
for the interactive hierarchy ladder, CAP tradeoff visualizer, and quorum calculator.
