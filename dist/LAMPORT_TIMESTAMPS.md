# LAMPORT_TIMESTAMPS — Logical Clocks & the Happens-Before Relation

> A **concept bundle**: this guide + [`lamport_timestamps.py`](./lamport_timestamps.py) + [`lamport_timestamps.html`](./lamport_timestamps.html).
> Every number below is printed by the `.py` (the single source of truth) and recomputed live by the `.html`. Nothing is hand-computed.
> Interactive companion: **[`lamport_timestamps.html`](./lamport_timestamps.html)**. 🔗 Back to [all tutorials](../index.html).

---

## 0. Why this exists: causality, not clock time

In a distributed system there is **no global clock**, and every wall clock is wrong by some unknown amount — drift, leap seconds, NTP steps that jump *backward* (see [`CLOCK_SYNC_NTP.md`](./CLOCK_SYNC_NTP.md)). So we **cannot** decide "did event `a` happen before event `b`?" by comparing the timestamps two machines stamped locally; two machines will disagree about what time it is.

Lamport's insight (1978): we don't *need* the real time an event happened. We only need to know the **causal ordering** — which events could have *influenced* which. And causality is fully captured by just two clock-free facts:

- **program order** — within one process, events happen in a sequence;
- **messages** — if `P` sends a message and `Q` receives it, the send *must* have happened before the receive.

Glue those together with transitivity and you get the **happens-before** relation (`a → b`): the skeleton of causality for the whole system. If neither `a → b` nor `b → a`, the events are **concurrent** (`a ‖ b`) — they could not have influenced each other, and their real-time order is unknowable *and irrelevant*.

Then Lamport attaches **numbers** to events so the numbering *agrees* with the skeleton: `a → b ⟹ L(a) < L(b)`. This is the **logical clock**. It is not a measure of time — it is a measure of *causal progress*. The rule is one line:

> before every event, bump your local counter by 1; on receiving a message, set `counter = max(counter, msg_timestamp) + 1`.

That single rule guarantees *causal consistency*, enough to build a **total order** (add process id as tiebreaker) and Lamport's **distributed mutual exclusion** algorithm. The catch (§4): the implication runs **one way** — `L(a) < L(b)` does *not* mean `a → b`; the events might be concurrent. Detecting concurrency requires **vector clocks**.

| Concept | Definition |
|---|---|
| **event** | an atomic happening at one process — local step, message *send*, or message *receive*. |
| **process** | a single sequential thread; its events are totally ordered by program order. |
| **happens-before** (`→`) | "`a` could have influenced `b`": program order, send→receive, or transitive. No clocks. |
| **concurrent** (`‖`) | neither `a → b` nor `b → a`. |
| **logical clock** (`L`) | an integer label on each event with `a → b ⟹ L(a) < L(b)`. Not a wall-clock time. |
| **total order** | a linear extension of `→`, made by breaking ties with `(L, pid)`. |
| **causal consistency** | the clock condition `a → b ⟹ L(a) < L(b)` (one-way — see §4). |

> **Paper**: Lamport, L. (1978). *"Time, Clocks, and the Ordering of Events in a Distributed System."* Communications of the ACM **21**(7), 558–565. Defines `→`, logical clocks (IR1/IR2), the total-ordering rule, and the mutual-exclusion algorithm (§5).

---

## 1. Happens-before — causality with NO clocks

Goal: decide "could `a` have influenced `b`?" without any clock. Lamport defines `→` from two ingredients:

1. **program order** — `a` before `b` in the same process ⟹ `a → b`;
2. **messages** — `a` = send and `b` = receive of the same message ⟹ `a → b`;
3. **transitivity** — `a → b` and `b → c` ⟹ `a → c`.

### The scenario (deterministic; reused by every section and the `.html`)

Three processes, nine events, two messages. Physical time `t` is shown only to *contrast* with the logical clock — the algorithm never reads it.

```
P1:  a --b----c       (b sends m1 to e)
P2:  d --e--f         (e receives m1; f sends m2 to h)
P3:     g--h--i       (h receives m2)
```

> From `lamport_timestamps.py` Section A:

```
DIRECT -> edges (8 total - transitivity not yet applied):
  program order: a->b, b->c, d->e, e->f, g->h, h->i
  messages     : b->e, f->h

TRANSITIVE CLOSURE (the full -> relation). For each event, the set it
could have influenced:

  a -> {b, e, f, c, h, i}
  b -> {e, f, c, h, i}
  c -> {}   (no descendants)
  d -> {e, f, h, i}
  e -> {f, h, i}
  f -> {h, i}
  g -> {h, i}
  h -> {i}
  i -> {}   (no descendants)

Total happens-before pairs a -> b: 23
```

Crucially, some events are **concurrent** — `→` is a *partial* order:

```
[check] #-> pairs (23) + #|| pairs (13) = 36 == C(9,2) = 36:  OK
```

The 13 concurrent pairs (`a‖d`, `a‖g`, `d‖b`, `d‖g`, `d‖c`, `b‖g`, `c‖g`, `c‖e`, `c‖f`, `c‖h`, `c‖i`, `e‖g`, `f‖g`) are simply not ordered. Their real-time order cannot be observed and does not matter for correctness.

🔗 Click any event in **[panel ①](./lamport_timestamps.html)** to light up its causal past/future and its concurrent set.

---

## 2. The logical clock rule — `L = max(local, msg) + 1`

Attach an integer `L(e)` to each event so that `a → b ⟹ L(a) < L(b)`. `L` is not a time-of-day; it is a counter of causal progress.

$$L(\text{local/send}) = L_{\text{prev}} + 1 \qquad L(\text{receive}) = \max(L_{\text{prev}},\ L_{\text{msg}}) + 1$$

> From `lamport_timestamps.py` Section B — the rule walked event-by-event in physical-time order (sends precede their receives, so `L(send)` is always known):

```
  a [P1, local]: clock[P1]=0 + 1 = 1
  d [P2, local]: clock[P2]=0 + 1 = 1
  b [P1, send ]: clock[P1]=1 + 1 = 2  (piggyback L=2 on msg to e)
  e [P2, recv <-b]: max(clock[P2]=1, L(b)=2) + 1 = 3
  f [P2, send ]: clock[P2]=3 + 1 = 4  (piggyback L=4 on msg to h)
  c [P1, local]: clock[P1]=2 + 1 = 3
  g [P3, local]: clock[P3]=0 + 1 = 1
  h [P3, recv <-f]: max(clock[P3]=1, L(f)=4) + 1 = 5
  i [P3, local]: clock[P3]=5 + 1 = 6
```

Resulting clock values:

| event | process | kind | physical t | L (logical) |
|---|---|---|---|---|
| a | P1 | local | 1 | **1** |
| d | P2 | local | 2 | **1** |
| b | P1 | send→e | 3 | **2** |
| e | P2 | recv←b | 4 | **3** |
| f | P2 | send→h | 5 | **4** |
| c | P1 | local | 6 | **3** |
| g | P3 | local | 7 | **1** |
| h | P3 | recv←f | 8 | **5** |
| i | P3 | local | 9 | **6** |

`L` **ignores** physical time. `c` happens at `t=6` but gets `L=3`, while `h` happens at `t=8` and gets `L=5` — because `h` causally depends on the chain `b→e→f→h`, whereas `c` is just the next local step of `P1`. The `max()` rule is what propagates causal progress *across* message arrows.

> **GOLD** (pinned for `lamport_timestamps.html`, reproduced identically in JS):
> ```
> L = a=1, d=1, b=2, e=3, f=4, c=3, g=1, h=5, i=6
> compact check scalar: L(h) = 5  (receive of f; the max() rule)
> [check] L matches hand-derived values:  OK
> ```

🔗 Toggle **physical time ↔ Lamport time** in **[panel ①](./lamport_timestamps.html)** and watch the event dots reposition — `c` and `h` visibly swap their relative positions.

---

## 3. Total order — the `(L, pid)` tiebreaker

`L` alone is only a *partial* order: distinct events can share a value (`a`, `d`, `g` all have `L=1`). To get a single global order — needed for mutual exclusion, log replication, determinism — Lamport breaks ties with the process id:

$$e \prec f \iff (L(e),\ \text{pid}(e)) < (L(f),\ \text{pid}(f)) \quad\text{lexicographically}$$

Because `a → b ⟹ L(a) < L(b)`, causally-related events are *always* in the right order; `pid` only ever orders events that are **concurrent**, so no causal constraint is ever violated.

> From `lamport_timestamps.py` Section C — sorted by `(L, pid)`:

| rank | event | process | L | pid | (L, pid) |
|---|---|---|---|---|---|
| 0 | a | P1 | 1 | 0 | (1, 0) |
| 1 | d | P2 | 1 | 1 | (1, 1) |
| 2 | g | P3 | 1 | 2 | (1, 2) |
| 3 | b | P1 | 2 | 0 | (2, 0) |
| 4 | c | P1 | 3 | 0 | (3, 0) |
| 5 | e | P2 | 3 | 1 | (3, 1) |
| 6 | f | P2 | 4 | 1 | (4, 1) |
| 7 | h | P3 | 5 | 2 | (5, 2) |
| 8 | i | P3 | 6 | 2 | (6, 2) |

```
Linearized total order:  a < d < g < b < c < e < f < h < i
[check] total order consistent with -> ?  violations = 0  ->  OK
[check] total order is a linear extension of ->:  OK
```

🔗 See the queue build live in **[panel ③](./lamport_timestamps.html)**.

---

## 4. Limitation — `L(a) < L(b)` does NOT mean `a → b`

The clock condition runs **one way**:

$$a \to b \;\Longrightarrow\; L(a) < L(b) \quad\text{(guaranteed)} \qquad L(a) < L(b) \;\Longrightarrow\; a \to b \quad\text{(FALSE in general)}$$

Lamport clocks are **scalar**: they collapse the partial order `→` onto a linear chain of integers, throwing away the difference between "`a` caused `b`" and "`a` and `b` just happen to be numbered this way". You **cannot** read causality off the clock values.

> From `lamport_timestamps.py` Section D — of the 13 concurrent pairs, **9** have `L(x) ≠ L(y)` (a naive reader would wrongly infer an ordering):

| x | y | L(x) | L(y) | clocks say | truth |
|---|---|---|---|---|---|
| c | i | 3 | 6 | c→i | **c‖i** |
| f | g | 4 | 1 | g→f | **f‖g** |
| c | d | 3 | 1 | d→c | **c‖d** |
| c | g | 3 | 1 | g→c | **c‖g** |
| c | h | 3 | 5 | c→h | **c‖h** |
| e | g | 3 | 1 | g→e | **e‖g** |
| b | d | 2 | 1 | d→b | **b‖d** |
| b | g | 2 | 1 | g→b | **b‖g** |
| **c** | **f** | **3** | **4** | **c→f** | **c‖f** |

**The clearest example:** `c` (P1, `t=6`) and `f` (P2, `t=5`) are **concurrent** — there is no path `c → … → f` or `f → … → c`. But `L(c)=3 < L(f)=4`, so the clocks make it *look* as though `c → f`. They are unrelated; the inequality is an accident of how the counters happened to bump.

**Why:** `c` bumps P1's counter (`2 → 3`); `f` bumps P2's counter (`3 → 4`). The two counters are independent, so their *relative* values carry **no** information about causality between the two processes.

**The fix — vector clocks** (Mattern 1989 / Fidge 1988): each process keeps one counter *per* process; then `a ‖ b ⟺` neither vector dominates the other. Lamport's scalar clock is the price of a single integer.

```
[check] c || f but L(c)=3 < L(f)=4  (the misleading case):  OK
```

🔗 Click `c` in **[panel ②](./lamport_timestamps.html)** and watch `f` light up as *concurrent* despite its higher clock — the trap, made visible.

---

## 5. Lamport's mutual exclusion — `min (timestamp, pid)` wins

A textbook use of the total order: distributed mutual exclusion. `N` processes share one resource and must take turns, with **no server** and **no physical clock**. Lamport's algorithm (1978):

1. To **request**, process `P` stamps a REQUEST with its current logical clock `t` and broadcasts `(t, pid)` to everyone (including itself).
2. Every process keeps a shared **request queue**, ordered by `(t, pid)` — the *same* total order as §3.
3. `P` may **enter** the critical section when its own REQUEST is at the *head* of its queue **and** it has received a message (even just an ACK) from every other process timestamped `> t` (so everyone has seen its request).
4. On **exit**, `P` broadcasts RELEASE; everyone removes `P`'s request.

The key invariant: because everyone orders the queue by the *same* `(t, pid)` rule, every process **agrees** on who is first → mutual exclusion is automatic, with no votes and no leader.

> From `lamport_timestamps.py` Section E — three requests for one resource:

| request from | logical timestamp t | pid | queue key (t, pid) |
|---|---|---|---|
| P1 | 1 | 0 | (1, 0) |
| P3 | 1 | 2 | (1, 2) |
| P2 | 2 | 1 | (2, 1) |

Shared queue ordered by `(t, pid)` — everyone agrees:

| grant # | process | enters at (t, pid) |
|---|---|---|
| 1 | P1 | (1, 0) |
| 2 | P3 | (1, 2) |
| 3 | P2 | (2, 1) |

```
Grant order:  P1 -> P3 -> P2
[check] grant order is P1 -> P3 -> P2 (min (t,pid) wins):  OK
```

Note the **tiebreaker in action**: P1 and P3 both request at `t=1`. The timestamps alone cannot choose, so `(1, pid)` orders them: P1 (pid 0) beats P3 (pid 2). P3 then waits for P1 to RELEASE. This is *exactly* the §3 total order applied to request events.

🔗 Drag the request timestamps in **[panel ④](./lamport_timestamps.html)** and watch the grant order recompute.

---

## 6. Gold check — the clock condition holds for every `a → b`

The defining property of a Lamport clock: causally-ordered events **always** get strictly increasing logical timestamps. (The converse is false — see §4.)

> From `lamport_timestamps.py` GOLD CHECK:

```
Testing all 23 happens-before pairs a -> b ...

  a -> b:  L(a)=1 < L(b)=2  [ok]
  a -> i:  L(a)=1 < L(i)=6  [ok]
  b -> e:  L(b)=2 < L(e)=3  [ok]
  f -> h:  L(f)=4 < L(h)=5  [ok]

Violations of the clock condition: 0 / 23
[check] GOLD: a -> b => L(a) < L(b) for all 23 pairs:  OK
GOLD scalar: L(h) = 5  (must be 5)
```

The `.html` recomputes all of this in JS on the *identical* scenario and re-asserts the gold badge.

---

## Further reading

- **Lamport (1978)**, CACM 21(7):558–565 — the source paper.
- **Mattern (1989)** / **Fidge (1988)** — vector clocks, the fix for §4.
- 🔗 [`CLOCK_SYNC_NTP.md`](./CLOCK_SYNC_NTP.md) — why *physical* clocks can't do this job (drift, leap seconds, NTP steps).
- 🔗 *Kleppmann, DDIA* ch. 8 — "The Trouble with Clocks"; *Tanenbaum & Van Steen, Distributed Systems* ch. 6.
