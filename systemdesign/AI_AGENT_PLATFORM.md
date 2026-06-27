# Design an AI Agent Platform

> **Companion code:** [`ai_agent_platform.py`](https://github.com/quanhua92/tutorials/blob/main/systemdesign/ai_agent_platform.py).
> **Live demo:** [`ai_agent_platform.html`](https://github.com/quanhua92/tutorials/blob/main/systemdesign/ai_agent_platform.html) — open in a browser.

---

## 0. TL;DR — the one idea

> **The analogy:** an agent platform is an **operating system for LLM workflows**.
> The LLM is the CPU; **tools** are syscalls, **memory** is RAM + disk, the
> **orchestrator** is the process scheduler, **guardrails** are the MMU / permission
> checks, and the **token budget** is the quota / fair-share scheduler. Everything
> an agent platform adds on top of a raw model call exists to make that one call
> **routed correctly, context-aware, coordinated, safe, and affordable** at scale.

The hard part is not "call the LLM" — it is orchestrating **non-deterministic,
multi-step, tool-augmented** workflows for **hundreds of tenants concurrently**,
under a per-tenant token budget, with **fault-tolerant state** (so a crashed node
resumes mid-workflow), **sandboxed untrusted code**, and **observability** into
why an agent did what it did.

```mermaid
graph LR
    U(["user request"]) -->|POST /workflow| GW["API Gateway<br/>auth + rate-limit"]
    GW --> ORC["Orchestrator<br/>planner -> executor -> reviewer"]
    ORC -->|intent| TR["Tool Router<br/>keyword + cosine"]
    TR -->|route| RG[("Tool Registry<br/>MCP, schemas, RBAC")]
    RG --> SB["Sandbox Manager<br/>container / microVM"]
    ORC -->|read/write| MEM["Memory<br/>short-term window<br/>+ long-term vector store"]
    ORC -->|validate in/out| GR["Guardrails<br/>PII + injection + safety"]
    ORC -->|checkpoint| ST[("State Store<br/>Postgres + Redis")]
    ORC -.OTel traces/metrics.> OB["Observability<br/>Prometheus + Jaeger"]
    style ORC fill:#eafaf1,stroke:#27ae60,stroke-width:3px
    style TR fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    style MEM fill:#eaf2f8,stroke:#2980b9
    style RG fill:#fef9e7,stroke:#f1c40f
    style SB fill:#fef9e7,stroke:#f1c40f
```

---

## 1. Requirements

### Functional
- **Register, configure, and deploy multiple agents** per tenant, each with its own tools, prompts, and guardrails.
- **Route user intent to the right tool** (web search, calculator, code, calendar, email, DB) — dynamically, not hardcoded.
- **Manage memory**: a bounded short-term context window + a persistent long-term vector store, retrieved by semantic similarity.
- **Orchestrate multi-agent workflows** (planner → executor → reviewer) with a maker-checker revision loop.
- **Enforce guardrails** at every boundary: input (PII redaction, prompt-injection) and output (safety denylist, length, format).
- **Track and enforce token budgets** per agent / workflow / tenant via model routing.

### Non-Functional
- **Interactive latency** p95 < 5s for one super-step (orchestrate → LLM → tool → review → guardrail).
- **Scale** to ~100 tenants × 10 agents, 1000 concurrent sessions, 500 workflow invocations/s peak.
- **Fault tolerance** via checkpointing at each super-step; resume only the failed node on crash.
- **Multi-tenant isolation** with per-tenant data, tool, and budget boundaries.
- **Observability** via OpenTelemetry traces (every LLM call + tool invocation + agent handoff).

---

## 2. Scale Estimation

> From `ai_agent_platform.py` **Section 6** (100 tenants, 500 invocations/s peak):

| Metric | Value |
|---|---|
| Registered agents | 1,000 |
| Workflow invocations /s (peak) | 500 /s |
| **LLM calls /s** | **5,000 /s** (10 calls/workflow) |
| **Token throughput** | **10,000,000 tok/s** |
| Concurrent sessions | 1,000 |

> From `ai_agent_platform.py` **Section 6** — storage (50 KB checkpoint per super-step, 5 steps/workflow):

| Storage metric | Value |
|---|---|
| Checkpoint write rate | 125.00 MB /s |
| **Checkpoints /day** | **10.80 TB /day** (75.60 TB kept @ 7d) |
| Long-term memory store | 100,000 entries ~ 100.00 MB |

> From `ai_agent_platform.py` **Section 6** — latency budget (p95 < 5s):

| Stage | Budget |
|---|---|
| Orchestrator routing | < 50 ms |
| LLM call (streaming first token) | < 800 ms |
| Tool execution (sandboxed) | < 2,000 ms |
| Reviewer check | < 500 ms |
| Guardrails (in + out) | < 100 ms |
| **Total (1 super-step)** | **< 3,500 ms** |

---

## 3. Architecture

```mermaid
graph TD
    LB["Load Balancer"] --> AGW["API Gateway<br/>auth + rate-limit"]
    AGW -->|POST /workflow| ORC["Orchestrator<br/>planner / executor / reviewer"]
    AGW -->|GET /stream SSE| STR["Stream Gateway<br/>token-by-token"]
    ORC -->|"intent -> score"| TR["Tool Router<br/>keyword + cosine"]
    TR --> RG[("Tool Registry<br/>MCP, JSON-Schema, RBAC")]
    RG -->|"validated call"| SB["Sandbox Manager<br/>Docker / Firecracker"]
    ORC -->|"short-term"| CW[("Context Window<br/>Redis, FIFO + compaction")]
    ORC -->|"long-term"| VS[("Vector Store<br/>pgvector / Pinecone")]
    ORC -->|"in/out"| GR["Guardrails<br/>PII + injection + safety"]
    ORC -->|checkpoint each step| PG[("Postgres<br/>state + AES")]
    ORC -.OTel.> OTC["OTel Collector"]
    OTC -.metrics.> PROM["Prometheus / Thanos"]
    OTC -.traces.> JAE["Jaeger / Datadog"]
    ORC -.token metering.> COST["Cost Metering<br/>per-tenant budget"]
    style ORC fill:#eafaf1,stroke:#27ae60,stroke-width:3px
    style TR fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    style PG fill:#eaf2f8,stroke:#2980b9
    style SB fill:#fef9e7,stroke:#f1c40f
    style RG fill:#fef9e7,stroke:#f1c40f
```

### Key Components

| Component | Technology | Why |
|---|---|---|
| **Orchestrator** | **LangGraph (StateGraph) / OpenAI Agents SDK** | **The scheduler.** Graph nodes = steps; supports parallelization, streaming, checkpointing, HITL. Supervisor pattern: planner → executor → reviewer. |
| **Tool Router** | keyword overlap + embedding cosine (v1) → learned classifier | Picks one tool per turn. v1 fuses `0.6·keyword + 0.4·cosine`; routes all 6 demo intents correctly. |
| Tool Registry | MCP (Model Context Protocol), JSON-Schema, RBAC | Discovery + schema validation + per-agent/tenant/user permission policies. MCP standardizes tool, resource, and prompt capabilities over JSON-RPC 2.0. |
| **Sandbox Manager** | **Docker (low threat) / Firecracker+E2B (multi-tenant)** | Isolates untrusted code. Containers share a kernel (~500 ms); microVMs give each sandbox its own kernel (~150 ms, pre-warmed). |
| **Memory** | **Redis (short-term) + pgvector/Pinecone (long-term)** | Short-term = bounded context window with FIFO eviction or compaction. Long-term = vector store, cosine top-k retrieval. |
| State Store | PostgreSQL + Redis | Checkpoints at each super-step (resume only the failed node); AES encryption for sensitive state; DeltaChannel stores only deltas. |
| Guardrails | regex PII + injection patterns + safety denylist | Defense in depth at every boundary (input, tool-call, tool-response, LLM-output, final-output). |
| Observability | OpenTelemetry + Prometheus + Jaeger | GenAI semantic conventions (`gen_ai.request.model`, `gen_ai.usage.cost`); traces for every LLM call + tool invocation. |

---

## 4. Key Design Decisions

### 4.1 Tool routing: keyword + semantic fusion

> From `ai_agent_platform.py` **Section 1** (6 tools, 8-dim concept embeddings, `0.6·kw + 0.4·sem`):

| Decision | Option A | Option B | Winner | Why |
|---|---|---|---|---|
| **Router signal** | **Keyword + cosine fusion** | Keyword-only / cosine-only | **Fusion** | Keyword alone is brittle (no overlap → 0.0 for all tools); cosine alone is gamed by synonyms. Demo: `search the web for latest AI news` → web_search score **0.8512** (kw 0.80 + sem 0.9279); `run this python script` → code_interpreter **0.9870**. All 6 intents routed correctly. Production graduates to a learned classifier on embeddings. |

### 4.2 Memory: FIFO eviction vs context compaction

> From `ai_agent_platform.py` **Section 2** (40-token toy window, 11-message conversation):

| Decision | Option A | Option B | Winner | Why |
|---|---|---|---|---|
| **Window policy** | **Compaction (summarize)** | FIFO eviction | **Compaction (with cap)** | FIFO drops the oldest non-system message: demo **evicts 6**, keeps `[system, 7, 8, 9, 10]` = 40 tokens — the early math turns are **lost**. Compaction summarizes the oldest 3 into one (ratio 0.4): **4 compactions**, final 27 tokens, retains a compressed trace of **every** turn. Cost: an extra summarization LLM call + summary fidelity loss. Use compaction capped at 1–2 rounds, then fall back to FIFO. |

- **Long-term store** (top-3 cosine): query *"what programming language should I use"* → `user_likes_python_language` (cosine **0.9987**) > `user_uses_macos_system` (0.5067). Retrieved memory is injected into the next prompt as system context.

### 4.3 Orchestration: planner → executor → reviewer with maker-checker

> From `ai_agent_platform.py` **Section 3** (supervisor pattern, reviewer threshold 0.8):

| Decision | Option A | Option B | Winner | Why |
|---|---|---|---|---|
| **Pattern** | **Supervisor (planner→executor→reviewer)** | Single ReAct agent | **Supervisor** | Separating plan / execute / review gives explainable checkpoints and a built-in maker-checker loop. Demo A (BTC): planner emits 2 steps, executor runs `web_search` then `calculator`, reviewer proves `7 coins × $67000 = $469000 ≤ $500000` → overall **1.00**, ACCEPT. Demo B (sum 1..100): attempt 1 off-by-one = **4950** → correctness 0.0 → overall **0.40**, REJECT; attempt 2 = **5050** → **1.00**, ACCEPT. Cap revisions at 2–3 to bound latency/cost. |

### 4.4 Guardrails: defense in depth

> From `ai_agent_platform.py` **Section 4** (PII + injection regex, safety denylist, 200-char cap):

| Decision | Option A | Option B | Winner | Why |
|---|---|---|---|---|
| **Where to validate** | **Every boundary** | Final output only | **Every boundary** | A prompt-injected tool response is just as dangerous as a malicious user input. Demo INPUT: 2 PII (SSN, email+phone) + 2 injection (`ignore previous instructions`, `you are now DAN`) + 1 clean. Demo OUTPUT: 1 safety-block (`bomb`) + 1 length-violation (500 chars) + 2 pass. Validate input, tool-call, tool-response, LLM-output, and final-output. |

### 4.5 Token budget: model routing + per-tenant enforcement

> From `ai_agent_platform.py` **Section 5** (mini/standard/large, $2500/month budget):

| Decision | Option A | Option B | Winner | Why |
|---|---|---|---|---|
| **Cost control** | **Model routing + budget enforcement** | One model for everything | **Routing + enforcement** | Route each task to the cheapest model meeting its quality bar. Demo: routed **$69.65/day** vs all-large **$205.50/day** → **66.1% savings**. Projected monthly **$2089.50** = 83.6% of $2500 budget (OK); a +25% spike → $2611.87 → **ENFORCE** (degrade / route-down). |

| Model | In $/1M | Out $/1M | Routed to |
|---|---|---|---|
| mini | 0.15 | 0.60 | classification, extraction |
| standard | 1.00 | 4.00 | summarization |
| large | 3.00 | 15.00 | complex_reasoning, code_generation |

---

## 5. Data Model

| Table | Columns | Notes |
|---|---|---|
| `agents` | `agent_id`, `tenant_id`, `name`, `system_prompt`, `tool_ids[]`, `model_tier` | Per-tenant; RBAC scopes tool access. |
| `workflows` | `workflow_id`, `tenant_id`, `agent_id`, `status`, `started_at` | `status` ∈ {running, paused, complete, failed}. |
| `checkpoints` | `checkpoint_id`, `workflow_id`, `super_step`, `state` (BLOB), `parent_id` | One per super-step; `parent_id` enables time-travel / forking. AES-encrypted. |
| `tool_invocations` | `invocation_id`, `workflow_id`, `tool`, `args`, `result`, `latency_ms`, `tokens` | Audit log; drives cost metering + traces. |
| `memory_vectors` | `memory_id`, `tenant_id`, `user_id`, `embedding`, `content`, `namespace` | Long-term store; `(user_id, "memories")` namespace; cosine index. |
| `usage_ledger` | `tenant_id`, `model`, `input_tokens`, `output_tokens`, `cost`, `ts` | Per-call; rolled up monthly for budget enforcement. |

---

## 6. API Endpoints

| Method | Path | Response | Notes |
|---|---|---|---|
| `POST` | `/api/agents` | `{agent_id}` | Register/configure an agent (write, low frequency). |
| `POST` | `/api/workflows` | `{workflow_id}` | Submit a workflow invocation (read-write, latency-sensitive). |
| `GET` | `/api/workflows/{id}/stream` | SSE token stream | Stream agent output (high QPS, first-token < 800ms). |
| `POST` | `/api/workflows/{id}/resume` | `{status}` | Resume from last checkpoint after HITL pause or crash. |
| `POST` | `/api/tools` | `{tool_id}` | Register a tool in the registry (MCP schema). |
| `GET` | `/api/tenants/{id}/usage` | `{tokens, cost, budget, utilization}` | Cost metering + budget health. |

---

## 7. Deep dives

- **Checkpointing & super-steps.** A super-step is one "tick" where all scheduled
  nodes execute (possibly in parallel). Checkpoints at each boundary enable fault
  tolerance: on crash, **pending writes** from successful nodes are kept and only
  the failed node re-runs. This also powers human-in-the-loop (pause for days,
  resume from the exact state) and time-travel (replay/fork any checkpoint).
- **Sandbox threat spectrum.** Docker (shared kernel, ~500 ms) is fine for
  trusted internal tools. Multi-tenant / untrusted input needs **Firecracker/E2B
  microVMs** (independent kernel per sandbox, ~150 ms with pre-warmed snapshots,
  used by Manus/Perplexity). The decision rule: *if a sandbox escape affects
  other tenants, you need a microVM.*
- **MCP (Model Context Protocol).** Standardizes tool discovery / invocation over
  JSON-RPC 2.0 with three server capabilities — **Tools** (functions), **Resources**
  (data), **Prompts** (templates). Without it, every platform rebuilds bespoke
  tool integrations; with it, tools compose across agents and organizations.
- **Context compaction vs eviction.** FIFO is cheap but loses early turns.
  Compaction (summarize oldest N into one message) preserves recall at the cost of
  a summarization LLM call + fidelity loss. DeltaChannel stores only incremental
  deltas for append-heavy channels, slashing checkpoint size for long threads.
- **Deterministic concurrency (Pregel/BSP).** LangGraph executes nodes in parallel
  with isolated state copies, then applies updates deterministically — so node
  ordering/latency never changes the final output. All operations are **constant
  on history length** (only the latest checkpoint is fetched, no replay).

---

### Killer Gotchas

- **Multi-agent is not free.** Each extra agent adds coordination overhead,
  latency, and a growing token bill. Default to a **single agent + tools**; reach
  for multi-agent only when one agent genuinely cannot span the security or
  skill boundaries the task needs.
- **FIFO eviction silently amnesias the agent.** The demo drops 6 of 11 messages;
  the agent forgets its own earlier math. Cap compaction rounds, then fall back
  to FIFO — and surface a "context truncated" signal to the user.
- **Validate every boundary, not just the final answer.** A prompt-injected tool
  response (e.g., a web page that says *"ignore prior instructions"*) is just as
  exploitable as a malicious user. Guardrails belong on input, tool-call,
  tool-response, LLM-output, and final-output.
- **Model routing is the single biggest cost lever.** Routing cheap tasks to mini
  cuts the demo bill **66.1%** vs all-large. Without it, a tenant's token budget
  burns in hours; with per-tenant enforcement, a +25% spike degrades gracefully.
- **Checkpoint storage explodes.** 125 MB/s → **10.8 TB/day**. Set retention
  (7-day hot, then cold archive), use DeltaChannel for deltas, and shard Postgres.
- **Handoff/magentic loops can run forever.** Always set a hard iteration cap and
  timeout — a stuck planner will quietly burn an entire monthly budget.

---

### Reproduce

```bash
python3 ai_agent_platform.py          # prints all sections + [check] OK
```

> From `ai_agent_platform.py` **Section 7 — GOLD CHECK** (values pinned for `ai_agent_platform.html`):

```
route_winners                = web_search,calculator,code_interpreter,calendar,email,database_query
route_cos_web_search         = 0.9279
route_cos_calculator         = 0.9879
route_score_intent0_top      = 0.8512
route_score_intent1_top      = 0.6952
mem_fifo_evicted             = 6
mem_fifo_total_tokens        = 40
mem_compact_total_tokens     = 27
mem_compact_count            = 4
mem_top1_name                = user_likes_python_language
mem_top1_cosine              = 0.9987
orch_btc_coins               = 7
orch_btc_overall             = 1.0
orch_sum_bug                 = 4950
orch_sum_correct             = 5050
orch_review_attempt1         = 0.4
orch_review_attempt2         = 1.0
guard_pii_count              = 2
guard_injection_count        = 2
guard_safety_block           = 1
guard_length_violation       = 1
budget_routed_daily          = 69.65
budget_alllarge_daily        = 205.5
budget_savings_pct           = 66.1
budget_monthly               = 2089.5
budget_utilization_pct       = 83.6
scale_llm_calls_per_s        = 5000
scale_token_throughput       = 10000000
scale_checkpoint_mbps        = 125.0
scale_checkpoint_tb_day      = 10.8
```

`[check] GOLD reproduces from routing + memory + orchestration + guardrails +
budget + scale? OK` — the gold badge `check: OK` at the bottom of
[`ai_agent_platform.html`](https://github.com/quanhua92/tutorials/blob/main/systemdesign/ai_agent_platform.html)
re-implements **tool routing** (keyword + cosine), **memory management** (FIFO +
compaction + vector retrieval), **planner→executor→reviewer orchestration**
(maker-checker), **guardrails** (PII + injection + safety + length), and **token
budget routing** in **pure JavaScript**, and confirms they match the `.py` exactly
(all 6 intents routed, FIFO evicts 6 / compaction 27 tok, BTC 7 coins, sum
4950→5050 reject→accept, routing saves 66.1%, 5000 LLM calls/s).
