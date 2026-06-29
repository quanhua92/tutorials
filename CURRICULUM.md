# CURRICULUM — Learn LLM Engineering in Public

> A Feynman-method curriculum for **AI application + AI inference**. Each topic is
> one learning cycle that produces three artifacts: a **runnable demo**, a **voiced
> article**, and an **animated video** (rendered via HyperFrames).
>
> **Goal:** build a personal brand as *an engineer who ships AI systems — and
> explains how they actually work, with every number runnable.* No hype, no
> hand-waving.
>
> **Focus:** AI applications + AI inference. Foundations are minimal-viable and
> cherry-picked — learned only when they change a decision. Training and
> distributed-scaling internals (DDP, tensor/pipeline parallel, ZeRO, MoE, LoRA)
> are **out of scope** for now.

---

## The shape

| Phase | Goal | Units | Why this order |
|---|---|---|---|
| **1. Foundations** | the load-bearing mental models | 9 | minimal vocabulary so Phases 2–3 are never a black box |
| **2. AI Applications via OpenRouter** | the brand-builder: call → RAG → agents → reliability | 16 | highest ROI, lowest infra (API); ships `aipa` |
| **3. Local LLM & Inference** | run → fit → serve | 16 | the hard infra part, deferred until Phase 1 makes it click |

**The payback rule:** every Phase 3 unit rests on a Phase 1 idea — 3.6 VRAM rests
on 1.5 (KV cache); 3.13 paged attention rests on 1.4 + 1.2. That is why foundations
come first, and why they are worth exactly those units, no more.

---

## HOW TO WORK — the 6-step method (per topic)

Every topic follows this exact cycle. Nothing is hand-computed: every number in
the article/video is printed by the demo or recomputed with the identical formula.
(This generalizes the existing `ovk-web/HOW_TO_RESEARCH.md` and `llm/HOW_TO_RESEARCH.md`
house style to the whole curriculum.)

### 1. Read (absorb)
Read the existing bundle (`.md` + `.py` + `.html`) **and** the canonical source it
cites (paper / official docs / authoritative blog). Goal: be able to explain the
topic from memory before you touch the demo.

### 2. Research (web-verify — non-skippable)
Verify every fact in **≥2 independent sources**. Log each URL with a `Verifies:`
line stating exactly what it confirms. If a fact cannot be verified, **flag it** —
never hide uncertainty.

### 3. Questions (the Feynman probe)
Answer the probe questions **out loud, in your own words, without notes**. If you
can't, you don't understand it yet — go back to step 1. These questions are the
pass/fail bar for the unit.

### 4. Demo `.py` (verify + gold-check)
Re-run the bundle, reproduce its gold value, then **extend it** (a new model, a new
context length, your own hardware). The extension is what makes the unit *yours*,
not a copy. Determinism is mandatory:
- fixed-seed RNG only (LCG/mulberry32) — no `Math.random()`, no `Date.now()` as a printed value
- print **≥2 `[check]` lines** using the `banner()`/`check()` helpers
- output must be **byte-stable** on re-run

### 5. What to teach (article + video)
- **Article:** voiced, first-person. Title, angle, the verified payload, ≥1 gotcha.
- **Video:** render via **HyperFrames** using the reusable 6-beat Explainer
  composition — `Hook → Analogy → Mechanism → Gold value → Gotcha → Recap` —
  slot-filled from this topic's bundle. Voiceover from the article prose; karaoke
  captions; a gold-check badge.

**Video tiers:** `T1` full narrated (keystones ⭐) · `T2` TL;DR 30s (most) · `T3`
interactive `.html` embed, no MP4 (tiny units).

### 6. Checklist (self-verify)
Run, in order, and ensure each is green:
- [ ] demo runs, exits 0, ≥2 `[check]` lines
- [ ] output byte-stable on re-run (determinism)
- [ ] gold value reproduced, matches reference
- [ ] ≥2 web sources logged with `Verifies:` lines
- [ ] article is voiced + embeds the diagram/demo + ≥1 gotcha
- [ ] HyperFrames video renders, 6 beats, gold-check badge green
- [ ] **all probe questions answered out loud, no notes** ← the real bar

---

## Progress

**Phase 1 — Foundations**
- [x] 1.1 The transformer in one diagram · `T1`
- [ ] 1.2 Attention, intuitively · `T2`
- [ ] 1.3 Tokens & the context window (+budget math) · `T2`
- [ ] 1.4 Prefill vs decode · `T1` ⭐
- [ ] 1.5 The KV cache (concept) · `T1` ⭐
- [ ] 1.6 Sampling (temp/top-p/top-k) · `T2`
- [ ] 1.7 Quantization (concept) · `T2`
- [ ] 1.8 Embeddings · `T2`
- [ ] 1.9 Why an LLM can call a function · `T2`

**Phase 2 — AI Applications via OpenRouter**
- [ ] 2.1 First call via OpenRouter · `T2`
- [ ] 2.2 Structured output (JSON schema) · `T2`
- [ ] 2.3 Prompting patterns · `T2`
- [ ] 2.4 Streaming + chat UX · `T3`
- [ ] 2.5 Embeddings for retrieval · `T2`
- [ ] 2.6 Vector DB basics (Qdrant/Milvus) · `T2`
- [ ] 2.7 Chunking · `T2`
- [ ] 2.8 Retrieval + reranking · `T2`
- [ ] 2.9 RAG end-to-end · `T1` ⭐
- [ ] 2.10 Function calling / tool use · `T2`
- [ ] 2.11 The agent loop · `T1` ⭐
- [ ] 2.12 Planning + memory · `T2`
- [ ] 2.13 Case study: aipa · `T1` ⭐
- [ ] 2.14 Evals · `T2`
- [ ] 2.15 Cost / latency · `T2`
- [ ] 2.16 Guardrails + observability · `T3`

**Phase 3 — Local LLM & Inference**
- [ ] 3.1 Ollama & LM Studio · `T2`
- [ ] 3.2 MLX (Apple Silicon) · `T2`
- [ ] 3.3 Open WebUI · `T3`
- [ ] 3.4 Hardware landscape · `T2`
- [ ] 3.5 Quant types (Q4_K_M) · `T2`
- [ ] 3.6 VRAM math · `T1` ⭐
- [ ] 3.7 GGUF format · `T3`
- [ ] 3.8 GPU offload · `T2`
- [ ] 3.9 Context extension · `T2`
- [ ] 3.10 KV-cache quant · `T2`
- [ ] 3.11 vLLM basics · `T2`
- [ ] 3.12 Continuous batching · `T2`
- [ ] 3.13 Paged attention · `T1` ⭐
- [ ] 3.14 Prefix cache / LMCache · `T2`
- [ ] 3.15 Speculative decoding · `T2`
- [ ] 3.16 (opt) CUDA graphs / disaggregated / ktransformers · `T3`

---

# Phase 1 — Foundations

> Minimal-viable mental models. Each unit motivates the next:
> architecture (1.1) → the block's core (1.2) → what flows through it (1.3) →
> how it runs (1.4) → why we cache (1.5) → how it picks tokens (1.6) → how it
> shrinks (1.7) → how meaning is searchable (1.8) → how it emits structure (1.9).

## 1.1 The transformer in one diagram

> The map. After this, "the model" is never a black box again.
> **Prerequisites:** none. **Pays off in:** everything. **Video:** `T1`.

### 1. Read
- **Your bundles:** `llm/TOKENIZATION.md` · `llm/CAUSAL_MASK.md` · `llm/MLP_ACTIVATION.md` · `llm/NORMALIZATION.md` · `llm/SAMPLING.md` — synthesize the overview from pieces you already own.
- **Canonical:** Alammar, *The Illustrated Transformer* · 3Blue1Brown, *But what is a GPT?* · Karpathy, *Let's build GPT* · "Attention Is All You Need" §3 (light skim).
- **Goal:** draw the full forward pass from memory.

### 2. Research (web-verify, ≥2 sources each)
- Architecture = `embed → N× blocks → final norm → LM head (unembedding) → softmax`. `Verifies:` Alammar + Karpathy.
- One block = `{attention, MLP, 2 residual connections, 2 pre-norms}`. `Verifies:` paper §3 + a real model's `config.json` (e.g. Llama-3).
- "Knowledge" lives in **MLP weights**; "context/reasoning" lives in **attention**. `Verifies:` ROME/MEMIT paper (*Locating and Editing Factual Associations in GPT*).

### 3. Questions (answer aloud, no notes)
1. Trace one token's journey in one sentence per stage.
2. What's inside one block, and why the residual connections?
3. Where does the model's *knowledge* live vs. its *context/reasoning*?
4. What does the LM head (unembedding) actually do?
5. Why is it autoregressive — one token out per step?
6. Why is *generation* slow but *reading the prompt* fast? (→ teases 1.4)

### 4. Demo `.py`
- Build a tiny end-to-end forward pass on a 4-token toy:
  `embed → 1 attention head → MLP → unembed → logits → argmax`.
- **Gold value:** the argmax token id (pinned; fixed-seed LCG, no RNG/date).
- Print ≥2 `[check]` lines: attention rows sum to 1 · logits shape correct · argmax == gold.
- **Extension (make it yours):** load a real config (Llama-3-8B `n_layers`/`n_heads`/`d_model`) and print total parameter count → seeds 1.7.

### 5. What to teach
- **Title:** *The whole transformer on one napkin.*
- **Angle:** the article *is* the annotated diagram. No math beyond intuition.
- **Payload:** the architecture map · the knowledge-vs-reasoning split · autoregressive = one token/step.
- **Gotcha:** generation is slow (sets up 1.4).
- **Video (`T1`):** Hook("embed → blocks → pick next token") → Analogy(assembly line) → Mechanism(diagram built stage-by-stage) → Gold(4-token pass) → Gotcha(one token/step) → Recap.

### 6. Checklist
- [ ] demo runs, exits 0, ≥2 `[check]` lines
- [ ] output byte-stable on re-run
- [ ] gold value reproduced, matches reference
- [ ] ≥2 web sources logged with `Verifies:` lines
- [ ] article centers on one annotated diagram + ≥1 gotcha
- [ ] HyperFrames video renders, 6 beats, gold-check badge green
- [ ] all 6 probe questions answered out loud, no notes

---

# Phase 2 — AI Applications via OpenRouter

> The brand-builder. API-based (OpenRouter = one key, many models), low infra.
> *(topics appended one at a time)*

---

# Phase 3 — Local LLM & Inference

> Run → fit → serve. Deferred until Phase 1 foundations make it comprehensible.
> *(topics appended one at a time)*
