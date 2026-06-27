# Architectural Patterns — The Deployment Spectrum, Service Mesh, Events & CQRS

> A concept bundle for distributed-systems architecture. Every number below is
> printed by **[`architectural_patterns.py`](./architectural_patterns.py)**
> (pure Python stdlib, run with `python3 architectural_patterns.py`) and
> recomputed live in **[`architectural_patterns.html`](./architectural_patterns.html)**.
> This guide never hand-computes anything — it cites the `.py` output verbatim.
>
> 🔗 Interactive companion: [`architectural_patterns.html`](./architectural_patterns.html) &nbsp;|&nbsp;
>    Source of truth: [`architectural_patterns.py`](./architectural_patterns.py) &nbsp;|&nbsp;
>    Live capture: [`architectural_patterns_output.txt`](./architectural_patterns_output.txt)

---

## 0. The one-paragraph version

Architecture is a **response to a forcing function** — a number or constraint
that makes a particular structure necessary. The deployment spectrum
(**monolith → SOA → microservices → serverless**) trades
independent-scalability and fault-isolation for operational-complexity and
network-latency; you move right only when the cost of the monolith exceeds the
cost of the distributed operations. A **service mesh** (sidecar data plane +
control plane) moves cross-cutting concerns — mTLS, retries, circuit breaking,
load balancing, tracing — out of every service into one uniform infrastructure
layer, worth it past ~20 services. **Event-driven** architecture temporally
decouples producers from consumers: the broker buffers bursts and enables
fan-out (one event → N consumers), at the cost of harder debugging and eventual
consistency. **CQRS** splits the normalized write model (Postgres, strong
consistency) from a denormalized read model (Elasticsearch/Redis, query-optimized),
synced by a CDC stream with a 50–500ms read lag — you pay that staleness to get
10x–100x read throughput without sharding the primary.

> From `architectural_patterns.py` GOLD CHECK (the headline numbers):
> ```text
>   score(monolith, MVP)      = 44
>   score(microservices, MVP) = 30
>   score(monolith, hyperscale)= 31
>   score(microservices, hyperscale)= 49
>   winner(MVP)       = monolith
>   winner(hyperscale)= microservices
>   cold_start_ms     = 500
>   grpc_hop_ms       = 1
>   cqrs_lag_min_ms   = 50
>   cqrs_lag_max_ms   = 500
> ```

This is the **architectural-patterns overlay** of the `dist/` suite. It connects
the structure decisions to the building blocks the deeper bundles expand on:
[`circuit_breaker.py`](https://github.com/quanhua92/tutorials/blob/main/dist/circuit_breaker.py)
(the retry/fail-fast logic a sidecar offloads),
[`consistent_hashing_lb.py`](https://github.com/quanhua92/tutorials/blob/main/dist/consistent_hashing_lb.py)
(the load balancing a mesh does),
[`gossip_protocol.py`](https://github.com/quanhua92/tutorials/blob/main/dist/gossip_protocol.py)
(the service-registry spreading),
[`backpressure.py`](https://github.com/quanhua92/tutorials/blob/main/dist/backpressure.py)
(the burst-absorbing a broker provides), and
[`saga_pattern.py`](https://github.com/quanhua92/tutorials/blob/main/dist/saga_pattern.py)
(the distributed-consistency story across services).

---

## 1. Section A — the deployment spectrum: monolith → serverless

Architecture is a slider, not a binary. Moving right trades
independent-scalability and fault-isolation for operational-complexity and
network-latency.

> From `architectural_patterns.py` Section A:
> ```text
>   | topology     | deploy unit  | owns DB        | scales by            |
>   |--------------|--------------|----------------|----------------------|
>   | monolith     | 1            | shared         | cloning the whole app|
>   | soa          | ~10          | shared (often) | cloning coarse services|
>   | microservices| ~100s        | per-service    | cloning the one hot svc|
>   | serverless   | 1 function   | managed        | the cloud (auto, per call)|
> ```

- **Monolith:** one process, one database, one deploy. The fastest way to
  deliver a working system — every call is an in-process function call
  (nanoseconds). The single failure mode is the deploy, but that deploy can
  break everything (blast radius = whole system). Scales only by cloning the
  entire unit, so the slowest feature caps every other.
- **SOA:** services communicating through an enterprise service bus (ESB),
  often with heavyweight protocols (SOAP/XML). The precursor to microservices —
  coarse-grained, frequently still sharing a database. The ESB became a
  bottleneck and single point of ownership, which is why microservices replaced
  it with dumb pipes (REST/gRPC) and smart endpoints.
- **Microservices:** small, independently-deployable services, **each owning its
  own database**, over lightweight protocols. The win is independent deploy +
  scale + fault isolation. The cost is the hardest distributed-systems problems
  now multiplied across every boundary: the network is unreliable, debugging a
  request hopping 8 services needs distributed tracing, and a **distributed
  monolith** (services that deploy together / share a DB) has all the costs and
  none of the benefits.
- **Serverless / FaaS:** the cloud runs your function per invocation. No
  servers, auto-scales to zero, bills per call. The cost is cold-start latency
  (50–2000ms), hard execution-time limits (~15min), and deep vendor lock-in.
  Ideal for sporadic/bursty workloads (webhooks, scheduled jobs), bad for steady
  hot paths.

**The database boundary IS the service boundary.** Sharing a database couples
services at the storage layer — a schema change by one team breaks another.
Database-per-service is what makes microservices actually independent.

> From `architectural_patterns.py` Section A (the latency tax of distribution):
> ```text
>   | call path                       | latency    | vs in-process |
>   |----------------------------------|------------|---------------|
>   | monolith (in-process call)      |   0.001 ms |         1x    |
>   | microservices (gRPC, same DC)   |   1.000 ms |      1000x    |
>   | microservices + mesh sidecar    |   2.000 ms |      2000x    |
>   | serverless cold start           | 500.000 ms |    500000x    |
> >
>   [check] cold start > 250000x in-process call => distribution has a latency tax: OK
> ```

A monolith function call is ~1µs; the same logical call as a gRPC round-trip is
~1ms (1000x). This is why you do NOT split a service for a call that happens
10000x per request. Split at **bounds that change at different rates**
(write model vs read model; billing vs catalog), not at every function. 🔗 Open
[`architectural_patterns.html`](https://github.com/quanhua92/tutorials/blob/main/dist/architectural_patterns.html)
Panel ① to compare the four topologies and Panel ④ to see the tradeoff matrix.

---

## 2. Section B — service mesh & the sidecar pattern

Every microservice re-implements the same cross-cutting concerns: mutual TLS,
retries with backoff, circuit breaking, load balancing, distributed tracing,
metrics. A **service mesh** moves this into a sidecar proxy (Envoy/Linkerd).

> From `architectural_patterns.py` Section B:
> ```text
>   | plane         | what it is                 | in the data path? |
>   |---------------|----------------------------|------------------|
>   | data plane    | sidecar proxy per pod      | YES (every call) |
>   | control plane | config/cert/policy brain    | NO (config push) |
> ```

- **The sidecar:** a second container in the same pod, sharing the network
  namespace. Your service talks to localhost; the sidecar intercepts, adds
  mTLS + retry + circuit-break, and forwards. App code sees no mesh — it just
  calls localhost. The mesh is transparent infrastructure.
- **The control plane** (Istiod/Consul): does NOT touch requests. It watches the
  service registry, computes routes/certs/policies, and **pushes** them to the
  data plane via xDS APIs. Because it is out of the data path, control-plane
  latency never affects a request.

The cost: each sidecar costs ~64MB RAM (Envoy baseline).

> From `architectural_patterns.py` Section B:
> ```text
>   | services N | replicas each | pods = N*R | sidecar RAM (GB) |
>   |------------|---------------|------------|------------------|
>   | 5          | 3             | 15         | 0.9              |
>   | 20         | 3             | 60         | 3.8              |
>   | 50         | 3             | 150        | 9.4              |
>   | 100        | 3             | 300        | 18.8             |
> ```

Below ~10–20 services the mesh is mostly overhead. Above ~20 services the mesh
pays for itself: uniform mTLS, zero-trust by default, and observability across
every hop without touching app code. The forcing function for adopting a mesh is
**service count + security posture**, not cool tech. The logical call graph can
be O(N²) (any service may call any other), but the **data plane stays O(N)** —
one sidecar per pod; the control plane computes the routes. 🔗 Deeper treatment
of the offloaded logic in
[`CIRCUIT_BREAKER.md`](https://github.com/quanhua92/tutorials/blob/main/dist/CIRCUIT_BREAKER.md)
and
[`CONSISTENT_HASHING_LB.md`](https://github.com/quanhua92/tutorials/blob/main/dist/CONSISTENT_HASHING_LB.md).

---

## 3. Section C — event-driven architecture: temporal decoupling + fan-out

A request/response call couples caller and callee in **time**: the caller blocks
until the callee replies. An **event** decouples them: the producer writes to a
broker (Kafka) and returns immediately; consumers react later. The broker is the
**buffer** that absorbs bursts and the **bus** that enables fan-out.

> From `architectural_patterns.py` Section C:
> ```text
>   | style          | coupling        | caller blocks? | failure mode               |
>   |----------------|-----------------|----------------|----------------------------|
>   | request/resp   | spatial+temporal| YES            | caller fails if callee down|
>   | event-driven   | temporal decoupled| NO          | broker buffers; consumer lag|
> ```

**Fan-out:** one `post.created` event triggers feed insertion, push notification,
search indexing, analytics — all independent consumers. Each runs at its own pace
in its own consumer group; the slowest does NOT block the others (the broker
retains the event).

**The cost:** harder debugging (no stack trace across a broker boundary — you
need correlation IDs + distributed tracing), and eventual consistency (a consumer
may lag seconds behind the producer). A notification fired 6 hours late is worse
than none — consumers must respect message expiry / time-to-live.

**Choice:** use events for async, fan-out, burst-absorbing work (feeds,
notifications, analytics, audit). Use request/response for synchronous
dependencies the caller cannot proceed without (a payment authorization before
confirming an order). The **outbox pattern** mixes both reliably: write the
record + the outbox event in one local transaction; a CDC relay (Debezium)
publishes the event. 🔗 Deeper treatment in
[`BACKPRESSURE.md`](https://github.com/quanhua92/tutorials/blob/main/dist/BACKPRESSURE.md)
(burst absorption) and
[`SAGA_PATTERN.md`](https://github.com/quanhua92/tutorials/blob/main/dist/SAGA_PATTERN.md)
(event-driven distributed transactions).

---

## 4. Section D — CQRS: split write (normalized) from read (denormalized)

Most systems are read-heavy (10:1 to 100:1 read:write). A single normalized
database serves writes well but struggles under read load: a complex join is
slow, and you cannot add read replicas forever. **CQRS** splits the two:

> From `architectural_patterns.py` Section D:
> ```text
>   | model | store              | optimized for          | consistency |
>   |-------|--------------------|------------------------|-------------|
>   | WRITE | PostgreSQL (normal)| low write contention   | strong      |
>   | READ  | Elasticsearch/Redis(denormal)| query speed  | eventual    |
> ```

A CDC stream (Debezium → Kafka) keeps the read model in sync. The write commits
to Postgres; the read model catches up 50–500ms later. You trade that staleness
for 10x–100x read throughput **without sharding the primary**.

> From `architectural_patterns.py` Section D (the economics):
> ```text
>   | option           | QPS added | cost $/mo | $ per 1K QPS |
>   |------------------|-----------|-----------|--------------|
>   | Redis cache node | 100,000   |     500   |         5.00 |
>   | 4th read replica |   5,000   |   5,000   |      1000.00 |
> ```

Redis at $500/mo absorbs 100K read QPS; a 4th read replica at $5000/mo adds only
5K QPS. **Cache first, replicate second.** CQRS pushes this further: the read
model is a purpose-built store for each query shape, not a generic replica.

**The read-lag reality:** 50–500ms between write commit and read-model update.
Fine for a feed; unacceptable for "read your own writes" (a user who updates
their profile and reloads expects to see the change). The fix is session pinning
(serve that user's reads from the write model for a short window) or
read-after-write consistency at the cost of latency.

---

## 5. Gold check — the weighted tradeoff analyzer: the right pattern per profile

The capstone: each topology is scored 1–5 on six axes (5 = best). A **weight
profile** encodes the forcing function — how much each axis matters for a given
business stage. The winner is the highest weighted sum. **Derive the profile
first; the pattern then follows.**

> From `architectural_patterns.py` GOLD CHECK:
> ```text
>   | pattern       | dev velocity | ops simple | latency | scalability | fault isolation | tech flex |
>   |---------------|--------------|------------|---------|-------------|-----------------|-----------|
>   | monolith      | 5            | 5          | 5       | 2           | 1               | 1         |
>   | soa           | 3            | 3          | 3       | 3           | 3               | 3         |
>   | microservices | 2            | 1          | 3       | 5           | 5               | 5         |
>   | serverless    | 4            | 4          | 2       | 5           | 4               | 2         |
> ```

The four weight profiles and their winners:

> From `architectural_patterns.py` GOLD CHECK:
> ```text
>   | profile                                    | winner         | score |
>   |--------------------------------------------|----------------|-------|
>   | MVP / startup (ship fast, small team)      | monolith       |    44 |
>   | Hyperscale (independent scale + blast radius)| microservices |   49 |
>   | Cost-sensitive (minimize infra & ops)      | monolith       |    40 |
>   | Polyglot org (many teams, many stacks)     | microservices  |    46 |
> >
>   [check] weighted scores + per-profile winners all match the tradeoff matrix: OK
> ```

- **MVP profile:** a 3-person startup should ship a **monolith**. The forcing
  function is dev_velocity + ops_simple — no SRE team, no traffic, and your job
  is product-market fit, not Kubernetes. Premature microservices is a classic
  over-engineering failure: "I'd start with a single Postgres and revisit at 10x
  scale."
- **Hyperscale profile:** at 1B users, the forcing function is scalability +
  fault_isolation. Billing crashes must NOT take down the feed; the hot read path
  must scale independently of the write path. **Microservices** (+ CQRS on the
  read path) is now justified — the operational cost is paid for by independent
  scale.

The `.html` recomputes the full weighted scoring in JavaScript and lets you
adjust the weight profile live to see the winner flip. A green `check: OK` badge
means the two implementations agree.

---

## 6. References

- **Fowler & Lewis (2011)** — "Microservices" (the term popularized by Fowler):
  the first clear articulation of the fine-grained service style and its tradeoffs.
- **Sam Newman** — *Building Microservices*: service boundaries, the
  database-per-service rule, integration patterns.
- **Brendan Burns et al.** — Borg/Omega/Kubernetes lineage: containers + pods,
  the substrate that made the sidecar/mesh pattern viable.
- **Matt Klein** — Envoy design; the data-plane/control-plane split and xDS APIs.
- **Chris Richardson** — microservices pattern language, including CQRS + event
  sourcing.
- **Conway (1968)** — Conway's law: the architecture mirrors the org chart.
- **Pat Helland** — "Life beyond Distributed Transactions" (event-driven sagas).

🔗 Back to [`architectural_patterns.html`](https://github.com/quanhua92/tutorials/blob/main/dist/architectural_patterns.html)
for the interactive pattern comparison, sidecar cost model, and the live
tradeoff-matrix analyzer.
