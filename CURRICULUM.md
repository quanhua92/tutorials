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
- [x] 1.2 Attention, intuitively · `T2`
- [x] 1.3 Tokens & the context window (+budget math) · `T2`
- [x] 1.4 Prefill vs decode · `T1` ⭐
- [x] 1.5 The KV cache (concept) · `T1` ⭐
- [x] 1.6 Sampling (temp/top-p/top-k) · `T2`
- [x] 1.7 Quantization (concept) · `T2`
- [x] 1.8 Embeddings · `T2`
- [x] 1.9 Why an LLM can call a function · `T2`

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

## 1.2 Attention, intuitively

> The block's core, made small. After this, "attention" is never scary again.
> **Prerequisites:** 1.1. **Pays off in:** 3.13 paged attention. **Video:** `T2`.

### 1. Read
- **Your bundles:** `llm/CAUSAL_MASK.md` · `llm/CAUSAL_MASK.py` (the Q/K/V glossary + the one-line SDPA) · `llm/FLASH_ATTENTION.md` (§0 intuition only — skip the tiling/HBM math, that's Phase 3) · `llm/KV_CACHE.md` (the Q/K/V glossary).
- **Canonical:** Alammar, *The Illustrated Transformer* (self-attention section) · 3Blue1Brown, *Attention in transformers, step-by-step* · "Attention Is All You Need" §3.2.1–3.2.2.
- **Goal:** explain what "attention" means from memory, using only dot products + softmax.

### 2. Research (web-verify, ≥2 sources each)
- Q, K, V are **not** three separate inputs — each is the **same token vector** times a different learned projection: `q = x·Wq`, `k = x·Wk`, `v = x·Wv`. `Verifies:` Alammar ("create three vectors... by multiplying the embedding by three matrices") + 3Blue1Brown ("the query matrix `W_Q`... multiplied by the embedding").
- `Q·K` is a **similarity score** — a larger dot product means stronger alignment. `Verifies:` Alammar ("the score is calculated by taking the dot product of the query vector with the key vector") + 3Blue1Brown ("measure how closely [a pair] align is to take their dot product. A larger dot product = stronger alignment").
- Scale by **`√d_k`** so the dot products (whose variance grows with `d_k`) don't blow up and push softmax into near-one-hot saturation with vanishing gradients. `Verifies:` "Attention Is All You Need" §3.2.1 ("for large values of `dk`, the dot products grow large in magnitude... pushing the softmax into regions where it has extremely small gradients") + Alammar ("divide the scores by 8 = √64... leads to having more stable gradients").
- **Softmax** turns each row of scores into non-negative weights that **sum to 1**. `Verifies:` Alammar ("softmax normalizes the scores so they're all positive and add up to 1") + 3Blue1Brown ("the numbers... between 0 and 1 and... each column [adds] up to 1").
- The output is a **weighted average** of `V`: `out = probs · V`. Each weight row is a convex combination, so `out` is a blend of the value vectors — that's how one token "borrows" meaning from others. `Verifies:` Alammar ("sum up the weighted value vectors... produces the output of the self-attention layer") + 3Blue1Brown ("multiply each value vector by the corresponding weight... adding together all of these rescaled values").
- It's **`O(n²)`** in sequence length: the score matrix is `n×n` — one cell per token pair. That's why long context is expensive. `Verifies:` 3Blue1Brown ("the size of this attention pattern is equal to the *square* of the context size") + `llm/FLASH_ATTENTION.md` §0.1 (the `n×n` table grows as the square of the sequence length; 256 MiB per head per layer at `n=8192`).
- "**Self**"-attention: Q, K, V all come from the **same** sequence. (Cross-attention, used in encoder–decoder translation, takes Q from one sequence and K, V from another — teased only.) `Verifies:` 3Blue1Brown ("a cross-attention head looks almost identical... the only difference being that the key and query maps act on different data sets") + "Attention Is All You Need" §3.2.2 ("self-attention... relating different positions of a single sequence").

### 3. Questions (answer aloud, no notes)
1. Where do Q, K, V come from — are they three separate inputs, or projections of one?
2. Why does a dot product between Q and K count as "similarity"?
3. Why divide by `√d_k` — what breaks if you skip it?
4. Why does softmax make each row a convex combination, and why does that make the output a weighted average of V?
5. Why is attention `O(n²)` in sequence length, and what does that cost at long context?
6. What makes it "**self**"-attention vs cross-attention? (one line, tease only)

### 4. Demo `.py`
- Build a **4-token single-head attention** toy: `q,k,v = x·Wq,Wk,Wv → scores = Q·Kᵀ/√d → softmax → out = probs·V`. File: `attention_intro.py`.
- **Determinism:** fixed-seed LCG for `Wq/Wk/Wv`, no `Math.random()`/`Date.now()`, output byte-stable on re-run.
- **Gold value:** prove the attention matrix is **row-stochastic** — every row sums to 1.0 (print `max|rowsum − 1|`). Prove each output position is a **convex combination** of input V vectors (so `out` lives in the span of V).
- Print ≥2 `[check]` lines: `row-sums all == 1.0` · `output is convex combo of V (weights == probs)` · `out` shape correct.
- **Extension (make it yours):** add a **causal mask** (set future scores to `−∞` before softmax) and show the masked matrix is still **lower-triangular row-stochastic** — bridges to 1.4 / decode.

### 5. What to teach
- **Title:** *Attention is just a weighted average (and that's the whole magic).*
- **Angle:** no math beyond dot products + softmax. Build the one diagram: `Q·K → scale √d → softmax → ×V`.
- **Payload:** the row-stochastic property (weights sum to 1) · the output = convex blend of V (one token borrows meaning from another) · why it's `O(n²)`.
- **Gotcha:** `O(n²)` is why long context is expensive — the `n×n` score matrix is the cost (teases Phase 3 / FlashAttention).
- **Video (`T2`):** Hook("it's a weighted average") → Mechanism(Q·K → scale → softmax → ×V) → Gold(row-stochastic check) → Gotcha(O(n²)).

### 6. Checklist
- [ ] demo runs, exits 0, ≥2 `[check]` lines
- [ ] output byte-stable on re-run
- [ ] gold value reproduced, matches reference
- [ ] ≥2 web sources logged with `Verifies:` lines
- [ ] article centers on one annotated diagram + ≥1 gotcha
- [ ] HyperFrames video renders, 6 beats, gold-check badge green
- [ ] all 6 probe questions answered out loud, no notes

---

## 1.3 Tokens & the context window (+budget math)

> The unit of cost, context, and chunking. After this, every bill, window, and RAG
> chunk size is a number you can compute — not guess.
> **Prerequisites:** 1.1. **Pays off in:** Phase 2 (cost/chunking), 3.9 context extension. **Video:** `T2`.

### 1. Read
- **Your bundles:** `llm/TOKENIZATION.md` (the 4-stage pipeline, BPE merges, `lowest → [11,13]`) · `llm/tokenization.py` (Sections A–C: pre-tok regex, gold merge table, rank-greedy encode) · `llm/tokenization.html` (live BPE).
- **Canonical:** OpenAI Help, *What are tokens and how to count them?* · OpenAI `tiktoken` README + the interactive Tokenizer tool (platform.openai.com/tokenizer) · Hugging Face NLP Course ch. 6.
- **Goal:** state, from memory, what a token is, why `" token"` ≠ `"token"`, what shares the context window, and how to turn tokens into dollars.

### 2. Research (web-verify, ≥2 sources each)
- A **token** is a BPE *subword* piece — not a word, not a char. It can be a single char (`e`), a common subword (`ing`), or a whole word; the model only ever sees its integer ID. `Verifies:` tiktoken README (https://github.com/openai/tiktoken) — "Byte pair encoding (BPE) is a way of converting text into tokens... Language models don't see text... they see a sequence of numbers (known as tokens)" + OpenAI Help Center (https://help.openai.com/en/articles/4936856) — "Tokens are the building blocks of text... as short as a single character or as long as a full word."
- **`" token"` ≠ `"token"`** — the pre-tokenizer glues a leading space onto the following word, so the space becomes part of the token. Same letters, different ID (verified: `" token"→[4037]`, `"token"→[5963]` in `cl100k_base`). `Verifies:` OpenAI Help Center — shows `' red'→2266` vs `'Red'→7738`, "when 'Red' is... at the beginning of a sentence, the generated token does not include a leading space" + `openai/gpt-2` `src/encoder.py` pre-tok regex `' ?\p{L}+|...'` (quoted verbatim in `llm/TOKENIZATION.md` §1; the optional leading space stays inside the pre-token).
- **~4 chars ≈ 1 token** for English — but it is only an *average*. `Verifies:` tiktoken README — "each token corresponds to about 4 bytes... On average, in practice" + OpenAI Help Center — "1 token ≈ 4 characters, 1 token ≈ ¾ of a word."
- The 4-chars/token rule **breaks hard for non-English**: a tokenizer trained mostly on English splits CJK / morphologically-rich text into far more tokens per word (a CJK char ≈ 3 UTF-8 bytes, often its own token). `Verifies:` OpenAI Community, *All languages are NOT created (tokenized) equal* (https://community.openai.com/t/all-languages-are-not-created-tokenized-equal/216407) — "tokenizing a message in one language may result in 10–20× more tokens than... another" + Petrov et al. 2023, *Language Model Tokenizers Introduce Unfairness Between Languages* (arXiv:2305.15425, https://arxiv.org/pdf/2305.15425).
- The **context window** is the max tokens the model attends over in *one pass* — and it is a **shared budget**: system prompt + chat history + retrieved docs + tool outputs + the model's own reserved output all compete for it. `Verifies:` OpenAI Help Center — "Each model has a maximum combined token limit (input + output)" + Redis, *Context windows in AI* (https://redis.io/blog/context-window-ai/) — "It covers both what you send and what the model generates back... every token you give to one component displaces a token from another."
- **Cost = `price_per_1M × token_count`**, and input/output are priced separately (cached and reasoning tokens differently again). `Verifies:` OpenAI Help Center — "API usage is priced per token, varying by model and whether tokens are input, output, or cached" + Redis, *Context windows in AI* — "You pay by the token, so a longer prompt costs more, every time you send it."
- **Count tokens, not chars/words**, when chunking for RAG or budgeting prompts — only the real tokenizer knows the count, and chunk boundaries must fall on token edges. `Verifies:` OpenAI Help Center — "Use the Tokenizer tool or `tiktoken.encoding_for_model(model)` to get the exact count" + `llm/TOKENIZATION.md` §8 (pitfall #8: "1 word ≈ 1–3 tokens; a CJK char ≈ 3 bytes ≈ up to 3 tokens").

### 3. Questions (answer aloud, no notes)
1. What is a token — vs a word, vs a char? Why is it none of those exactly?
2. Why does a leading space change the tokenization (`" token"` ≠ `"token"`)?
3. Why is ~4 chars/token only an average — and where does it break badly?
4. What shares the context window, and what happens when you exceed it?
5. Given a price-per-1M for input and output, how do you estimate one request's cost?
6. Why must you count *tokens* (not characters) when chunking a doc for RAG?

### 4. Demo `.py`
- File: `tokens_budget.py`. Pin one encoder (`tiktoken.get_encoding("cl100k_base")`; if `tiktoken` is absent, fall back to the deterministic toy BPE from `tokenization.py`) and a **pinned prompt**.
- **Determinism:** fixed input string, fixed encoder name, no `random`/`Date.now()`/network, output byte-stable on re-run.
- Print the prompt's token count + the leading-space effect: `enc.encode(" token") == [4037]` vs `enc.encode("token") == [5963]` (different IDs, both length 1).
- **Gold value (must match on re-run):** the pinned prompt `"The transformer attends over tokens, and tokens are the unit of cost."` → **14 tokens** (69 chars ⇒ 4.93 chars/token), ids `[791, 43678, 75112, 927, 11460, 11, 323, 11460, 527, 279, 5089, 315, 2853, 13]`.
- Compute **(a) cost**: `cost = (n_in·price_in + n_out·price_out)/1e6` — e.g. 14 input @ $2.50/1M + 80 output @ $10/1M = **$0.000835** per request.
- Compute **(b) the shared budget**: replay a realistic multi-turn chat (system 12 + 123 tokens per user/assistant pair) into an 8192-token window with 256 reserved for output → **budget blows at turn 65** (cumulative 8007 + 256 = 8263 > 8192); from there the earliest turns fall off.
- Print ≥2 `[check]` lines: `[check] pinned prompt -> 14 tokens` · `[check] " token" [4037] != "token" [5963]` · `[check] cost == 0.000835 USD` · `[check] budget overflow at turn 65`.
- **Extension (make it yours):** chunk a sample doc (`"A token is a puzzle piece. "×200` ⇒ 1401 tokens) into 64-token chunks (⇒ 22 chunks) and show how many full chunks + the prompt fit inside a model's window — e.g. Llama-3-8B's 8k: room = 8192 − 14 (prompt) − 256 (reserve out) = 7922 ⇒ **123 full chunks** fit. Swap in the 128k window and re-print → seeds Phase 2 chunking + 3.9 context extension.

### 5. What to teach
- **Title:** *A token is not a word (and that's why your bill looks weird).*
- **Angle:** tokens are the *universal unit* — of cost, of context, and of RAG chunking. Build one equation and read everything off it: `context_used = prompt + history + retrieved + reserved_output`.
- **Payload:** the leading-space surprise (`" token"`≠`"token"`) · the 4-chars/token average + where it breaks (non-English, CJK ≈ 3 bytes) · the shared-budget insight (input + output + history + docs all draw from one pool).
- **Gotcha:** input and output share the window — a long chat silently fills it and the model "forgets" the earliest turns (the turn-65 overflow). Same pool also means a 1M-token window does not mean 1M tokens *of output*.
- **Video (`T2`):** Hook(token ≠ word) → Mechanism(BPE subword + the leading-space rule) → Gold(14 tokens + $0.000835 cost) → Gotcha(shared context budget, turn-65 overflow).

### 6. Checklist
- [ ] demo runs, exits 0, ≥2 `[check]` lines
- [ ] output byte-stable on re-run
- [ ] gold value reproduced, matches reference
- [ ] ≥2 web sources logged with `Verifies:` lines
- [ ] article centers on one annotated diagram + ≥1 gotcha
- [ ] HyperFrames video renders, 6 beats, gold-check badge green
- [ ] all 6 probe questions answered out loud, no notes

---

## 1.4 Prefill vs decode

> The keystone of inference. After this, "generation is slow" stops being a
> mystery and becomes *one number* — the arithmetic-intensity gap between reading
> a prompt and writing a token. Everything in Phase 3 serving is a reaction to it.
> **Prerequisites:** 1.1, 1.2. **Pays off in:** 3.11–3.15 (continuous batching,
> speculative decoding, disaggregated serving). **Video:** `T1` ⭐.

### 1. Read
- **Your bundles:** `llm/KV_CACHE.md` (glossary: prefill = process the whole prompt at once, `L>1`, fills the cache; decode = one new token per step, `L=1`, appends) · `llm/SCHEDULER.md` §1/§4 (the prefill-vs-decode tension — a long prefill starves the running decodes; the TTFT glossary entry) · `llm/BLOCK_MANAGER.md` (the `can_append`/OOM tension is *downstream* of decode running one token at a time).
- **Canonical:** Zhong et al., *DistServe: Disaggregating Prefill and Decoding for Goodput-optimized LLM Serving*, OSDI 2024 (arXiv:2401.09670), §1–§2 · Anyscale, *How continuous batching enables 23× throughput in LLM inference* (2023) · NVIDIA A100 product page (bandwidth spec).
- **Goal:** state, from memory, why prefill is compute-bound, why decode is memory-bandwidth-bound, what TTFT/TPOT are, and why the two phases fight inside one batch.

### 2. Research (web-verify, ≥2 sources each)
- **Prefill processes the whole prompt in parallel** — one big matmul over all `L>1` prompt tokens at once; the weights are loaded *once* and reused across every prompt token. `Verifies:` DistServe §2.1 — "The prefill step deals with a new sequence, often comprising many tokens, and processes these tokens concurrently" (https://arxiv.org/html/2401.09670v3) + Anyscale blog — "The initial ingestion ('prefill') of the prompt … efficiently uses the GPU's parallel compute because these inputs can be computed independently of each other" (https://www.anyscale.com/blog/continuous-batching-llm-inference).
- **Prefill is compute-bound** at realistic prompt lengths — a 13B model prefilling 512 tokens already saturates an A100. `Verifies:` DistServe §2.1 — "When dealing with user prompts that are not brief, the prefill step tends to be compute-bound. For instance, for a 13B LLM, computing the prefill of a 512-token sequence makes an A100 near compute-bound" (https://arxiv.org/html/2401.09670v3) + Anyscale blog — prefill "has a different computational pattern than generation" (https://www.anyscale.com/blog/continuous-batching-llm-inference).
- **Decode emits ONE token per step** (`L=1`) but, to produce it, the GPU must load *essentially every weight* from HBM — a near-prefill-sized memory load for a single token's worth of compute. `Verifies:` DistServe §2.1 — "each decoding step only processes one new token … despite processing only one new token per step, the decoding phase incurs a similar level of I/O to the prefill phase, making it constrained by the GPU's memory bandwidth" (https://arxiv.org/html/2401.09670v3) + Anyscale blog — "LLM inference is memory-IO bound, not compute bound … it currently takes more time to load 1MB of data to the GPU's compute cores than it does for those compute cores to perform LLM computations on 1MB" (https://www.anyscale.com/blog/continuous-batching-llm-inference).
- **Arithmetic intensity** = `FLOPs ÷ bytes-moved` (FLOP/byte). A workload is compute-bound when its intensity exceeds the GPU's **ridge point** `peak_FLOPs ÷ peak_bandwidth`; below it, it is memory-bound. For a weight-matmul shared across `L` tokens, intensity ≈ `L` (weights loaded once: `2·L·in·out` FLOPs over `2·in·out` weight-bytes — the factors cancel). `Verifies:` Anyscale blog — the memory-IO-vs-compute framing, "so much of the chip's memory bandwidth is spent loading model parameters" (https://www.anyscale.com/blog/continuous-batching-llm-inference) + the **roofline model** (Williams et al., CACM 2009) is standard computer architecture. *The `intensity ≈ L` figure is derived arithmetic, computed in `prefill_vs_decode.py` (§4).*
- **Latency splits into TTFT (prefill) and TPOT (decode).** TTFT = duration of the prefill phase (time to *first* token); TPOT = average time per *output* token in decode (every token after the first); full request latency = `TTFT + TPOT × (number of generated tokens)`. `Verifies:` DistServe §1 — "time to first token (TTFT), which is the duration of the prefill phase, and the time per output token (TPOT) … The overall request latency equals TTFT plus TPOT times the number of generated tokens" (https://arxiv.org/html/2401.09670v3) + local `llm/SCHEDULER.md` glossary — "TTFT | Time To First Token. Prefill priority exists to keep this low." (grounded in vLLM's scheduler). *Flagged: the natural 2nd web source — vLLM's serving/metrics docs — returned HTTP 429 and could not be fetched; not invented.*
- **Prefill and decode fight inside one batch.** A prefill step runs far longer than a decode step; batched together, the decodes stall waiting on the prefill (TPOT inflates), and adding decodes slows the prefill (TTFT inflates). This single interference is what every Phase-3 scheduler fights. `Verifies:` DistServe §1 — "colocation leads to strong prefill-decoding interference. A prefill step often takes much longer than a decoding step. When batched together, decoding steps in the batch are delayed by the prefill steps, significantly elongating their TPOT" (https://arxiv.org/html/2401.09670v3) + Anyscale blog — "since the prefill phase takes compute and has a different computational pattern than generation, it cannot be easily batched with the generation of tokens" (https://www.anyscale.com/blog/continuous-batching-llm-inference).
- **This one tension motivates all of Phase 3.** Continuous batching (3.12) keeps decode seats full; speculative decoding (3.15) fakes several decode steps with one prefill-class matmul; disaggregated serving (3.16) *physically splits* prefill and decode onto separate GPUs to kill the interference outright. `Verifies:` DistServe §1 (disaggregation assigns prefill & decoding to different GPUs, "eliminating prefill-decoding interferences," up to 7.4× more requests; https://arxiv.org/abs/2401.09670) + local `llm/SCHEDULER.md` §0 (continuous batching + chunked prefill + preemption all exist to manage the prefill/decode tension).

### 3. Questions (answer aloud, no notes)
1. Why is the prompt processed *all at once* while generation emits *one token per step* — what makes them different passes?
2. Why is decode **memory-bound** — exactly what must the GPU load to emit a single token?
3. What are **TTFT** and **TPOT**, which phase dominates each, and what is the full request-latency formula?
4. What is **arithmetic intensity**, and why is prefill's ≈ `L` FLOP/byte while decode's is ≈ 1?
5. Why do prefill and decode **fight** when batched together on one GPU?
6. How does this single tension motivate continuous batching, speculative decoding, and disaggregated serving? (tease → Phase 3)

### 4. Demo `.py`
- File: `prefill_vs_decode.py`. **Determinism:** all shapes and `L` are pinned constants; no `random`/`Date.now()`/network; output byte-stable on re-run.
- **Model.** For a linear layer `x[L,in] @ W[in,out]` (fp16): `flops = 2·L·in·out`, `weight_bytes = 2·in·out`, so **arithmetic intensity = `flops/weight_bytes = L`** (weights loaded once, reused across `L` tokens — the factors cancel). Print this for a 4-token toy (`d=8`, 1 layer) and a 7B-class shape (`d_model=4096`, `n_layers=32`).
- **Gold value (must match on re-run):** with prefill `L=512` and decode `L=1`, `intensity_prefill / intensity_decode = 512 / 1 =` **`512`** — prefill's arithmetic intensity is **512×** decode's. (Independent of model size: numerator and denominator scale with the same parameter count; only `L` differs. At toy `L=4` the ratio is `4`.) Decode's attention KV-cache traffic is *additional* bytes on top, so `≈1` is an upper bound — decode is *at least* 512× more memory-starved.
- Print ≥2 `[check]` lines: `[check] prefill intensity(512tok) / decode intensity(1tok) == 512` · `[check] decode intensity == 1 FLOP/byte (weights loaded once for 1 token)` · `[check] toy L=4 ratio == 4`.
- **Extension (make it yours):** plug **Llama-3-8B** (`d_model=4096`, `n_layers=32`, `n_heads=32`, ~8B params) and argue decode is memory-bound on real hardware — the **A100 ridge point** `= peak_compute / peak_bandwidth ≈ 312 TFLOP/s ÷ 2.0 TB/s ≈ 156 FLOP/byte`. Decode intensity `≈1` is **156× below** the ridge ⇒ memory-bound; prefill at `L=512` is `≈3.3× above` ⇒ compute-bound. (Bandwidth `≥2 TB/s` verified from the NVIDIA A100 product page, https://www.nvidia.com/en-us/data-center/a100/; 312 TF FP16 is the datasheet peak.) Swap in an H100 (`≈990 TF FP16` / `≈3.35 TB/s` ⇒ ridge ≈ 296) and re-print — decode is *still* memory-bound by ~296×.

### 5. What to teach
- **Title:** *Why generating text is slow (and reading your prompt isn't).*
- **Angle:** to emit *one* token, the GPU touches essentially every weight. Two phases, one compute-vs-memory split, and one intensity ratio (`512`) that explains everything downstream.
- **Payload:** the prefill (big parallel matmul, compute-bound) vs decode (one token, memory-bound) split · TTFT vs TPOT + the latency formula · the `intensity ≈ L` ratio and the `512` gold · the A100 ridge (`156`) showing decode lives 156× below it.
- **Gotcha:** prefill and decode *competing* in one batch is the root cause that every Phase-3 serving trick (continuous batching, speculative decoding, disaggregation) is built to fix.
- **Video (`T1`, 6 beats):** Hook("to emit one token, the GPU touches every weight") → Analogy(reading a page in one glance vs writing one word at a time) → Mechanism(prefill's big parallel matmul vs decode's serial one-token matmul, animated) → Gold(the `512` intensity ratio + the `156` A100 ridge) → Gotcha(prefill + decode fight in one batch) → Recap.

### 6. Checklist
- [ ] demo runs, exits 0, ≥2 `[check]` lines
- [ ] output byte-stable on re-run (determinism)
- [ ] gold value reproduced, matches reference
- [ ] ≥2 web sources logged with `Verifies:` lines
- [ ] article is voiced + embeds the diagram/demo + ≥1 gotcha
- [ ] HyperFrames video renders, 6 beats, gold-check badge green
- [ ] **all probe questions answered out loud, no notes** ← the real bar

---

## 1.5 The KV cache (concept)

> The model's running notebook — and, at long context, a memory cost that can
> out-weigh the model itself. After this, "will it fit on my GPU?" becomes one
> linear formula you can compute in your head. Dense concept only; *how servers
> manage* this memory is 3.13.
> **Prerequisites:** 1.2 (attention), 1.4 (prefill vs decode). **Pays off in:**
> 3.6 (VRAM math), 3.13 (paged attention). **Video:** `T1` ⭐.

### 1. Read
- **Your bundles:** `llm/KV_CACHE.md` (§0 TL;DR's three-generations lineage; §1 the no-cache `O(L²)` recompute; §2 the dense cache `O(1)`/step; §3 the `[B,H_kv,S,D]` layout; the glossary) — **read the dense parts only; explicitly SKIP §4 fragmentation, §5 paged/block-table, §8 rewind (those are 3.13).** · `llm/kv_cache.py` Section A (the `1+2+3+4+5=15` vs `5` recompute table) + Section C (the per-request dense byte-count line `2 × layers × h_kv × max_len × d × 2 B`).
- **Canonical:** Sebastian Raschka, *What is a KV cache, and why does it make LLM inference faster?* · Michael Brenndoerfer, *KV Cache Memory: Calculating GPU Requirements for LLM Inference* · João Marques, *KV cache memory calculator* (dev.to).
- **Goal:** state, from memory, *what* the cache stores, *why* it exists (the recompute it kills), and the **linear byte formula** — then compute it for a real model.

### 2. Research (web-verify, ≥2 sources each)
- **Why cache at all — without it, decode recomputes K,V for ALL past tokens every step.** Generation is autoregressive: each new token must attend over the *whole* running prefix. With no cache, token 0's K,V get recomputed at *every* step (across `L` steps → `O(L²)` projections); the cache stores each token's K,V once so decode projects only the single new token (`O(1)` projections/step). `Verifies:` Raschka — "Without caching, it would repeatedly recompute attention keys and values for all earlier tokens at every generation step" (https://sebastianraschka.com/faq/docs/kv-cache.html) + Brenndoerfer — "instead of recomputing key and value projections for every token at every generation step, we store them once and read them back later" (https://mbrenndoerfer.com/writing/kv-cache-memory-calculation-llm-inference-gpu).
- **What's stored per token per layer — a K vector and a V vector (never Q).** The current token's query is used to produce logits then discarded; old queries are dead. Only K and V persist, because every *future* token must compare its query against *all* past keys and blend the matching values. `Verifies:` Raschka — "we cache keys and values, not old queries. The model only needs the query of the current token… Older queries are no longer needed, but older keys and values are still needed" (https://sebastianraschka.com/faq/docs/kv-cache.html) + Brenndoerfer — per-layer cache stores *both* a Key tensor and a Value tensor, each shaped `[batch, num_kv_heads, seq, head_dim]` (https://mbrenndoerfer.com/writing/kv-cache-memory-calculation-llm-inference-gpu).
- **The byte formula — and every term is linear.** `bytes = 2 (K+V) × n_layers × batch × n_ctx × n_kv_heads × head_dim × bytes_per_element`. No squares, no logs: doubling any factor doubles the bytes. `Verifies:` Brenndoerfer — "KV Cache Memory = 2 × L × B × T × H_kv × D_h × bytes… every term in this product is linear: there are no squares" (https://mbrenndoerfer.com/writing/kv-cache-memory-calculation-llm-inference-gpu) + Marques — "KV cache bytes = 2 × L × H × d × T × 2" with a worked Llama-3-8B table 4K→0.5 GB (https://dev.to/jagmarques/kv-cache-memory-calculator-how-much-does-your-llm-actually-use-85n).
- **The cache grows *linearly* with context — and that's the term that blows up.** Attention *compute* is `O(n²)` (the `n×n` score matrix from 1.2), but the cache is `O(n)` — it stores exactly one K,V per token. At 4× the context you pay 4× the cache bytes, forever, with no shortcut. `Verifies:` Brenndoerfer — "Sequence length has a linear effect on KV cache size… unlike attention score computation, which grows quadratically with sequence length, cache memory grows strictly linearly" (https://mbrenndoerfer.com/writing/kv-cache-memory-calculation-llm-inference-gpu) + Marques — Llama-3-8B table: 4K→0.5 GB, 32K→4 GB, 128K→16 GB (each 8× context = 8× bytes; https://dev.to/jagmarques/kv-cache-memory-calculator-how-much-does-your-llm-actually-use-85n).
- **The punchline: at long context the cache out-weighs the model.** Llama-3-8B weights ≈ 16 GB (fp16); its KV cache at the 128k window ≈ 16 GB — the "notebook" is as big as the "model." The cross-over (cache bytes == weight bytes) sits around **~122k tokens**. This is why "will it fit on my GPU?" is a *cache* question, not just a *weights* question. `Verifies:` Brenndoerfer — "crossover point… where KV cache exceeds model weights"; for LLaMA-7B "approximately 28,000 tokens… beyond this threshold the cache becomes the primary memory consumer" (https://mbrenndoerfer.com/writing/kv-cache-memory-calculation-llm-inference-gpu) + Marques — "For a 7B-class model, KV cache at 128K is already 16 GB… The model weights themselves (in FP16) are only ~14 GB" (https://dev.to/jagmarques/kv-cache-memory-calculator-how-much-does-your-llm-actually-use-85n). *(Teases 3.6 VRAM math.)*
- **GQA shrinks the cache (tease, out of scope here).** Grouped-Query Attention shares one K,V head across several query heads, so `n_kv_heads` (and thus the cache) drops by the group factor while quality barely moves — Llama-3-8B has 32 query heads but only **8 KV heads**, cutting the cache 4× vs full MHA. `Verifies:` Brenndoerfer — "Reduction Factor = H / H_kv… a model with 64 query heads and 8 KV heads achieves an 8-fold reduction in cache size" (https://mbrenndoerfer.com/writing/kv-cache-memory-calculation-llm-inference-gpu) + Raschka — grouped-query attention is among the techniques that "focus heavily on reducing KV-cache cost" (https://sebastianraschka.com/faq/docs/kv-cache.html).

### 3. Questions (answer aloud, no notes)
1. Without a cache, what gets recomputed at every decode step — and why is the total `O(L²)`?
2. What exactly is stored per token, per layer — and why is **Q never** cached?
3. Why does the cache grow *linearly* with context length while attention compute grows quadratically?
4. Write the byte formula from memory. Which term blows up at long context?
5. Why is this cache the bridge to VRAM / memory limits — what question does it answer?
6. At roughly what context does Llama-3-8B's cache out-weigh its weights, and why does that matter?
7. What does GQA do to the cache size — in one line? (tease only)

### 4. Demo `.py`
- File: `kv_cache_concept.py`. **Determinism:** every config is a pinned constant; no `random`/`Date.now()`/network; output byte-stable on re-run.
- **The formula:** `kv_bytes = 2 * n_layers * n_kv_heads * n_ctx * head_dim * bytes_per_element` (the leading `2` is K+V; `bytes_per_element` is 2 for fp16). The `batch` axis multiplies linearly too — pin `batch=1` for the concept demo.
- **Toy config** (`2 layers, 2 KV heads, head_dim 4, max_seq_len 8`): print the dense cache shape `[1, 2, 8, 4]` and its reserved bytes — mirrors `DenseKVCache` in `kv_cache.py` Section B.
- **Gold value (must match on re-run):** **Llama-3-8B** (`n_layers=32, n_kv_heads=8, head_dim=128`) at **ctx 4096, fp16** → `2 × 32 × 8 × 4096 × 128 × 2 = 536,870,912 bytes = 512 MiB`. Per token: `131,072 bytes` (128 KiB).
- **Linear-growth table** — print the cache at `1k / 4k / 16k / 32k` context and show `bytes ∝ n_ctx` (each 4× context ⇒ 4× bytes): **128 MiB → 512 MiB → 2 GiB → 4 GiB**.
- Print ≥2 `[check]` lines: `[check] Llama-3-8B @4096 ctx fp16 == 536870912 B (512 MiB)` · `[check] linear: ctx x4 -> bytes x4 (128MiB/512MiB/2GiB/4GiB)` · `[check] formula 2(KV)*layers*ctx*kv_heads*head_dim*bpe`.
- **Extension (make it yours):** compute the **cross-over context** where `kv_cache_bytes > weights_bytes` for Llama-3-8B (pin `n_params = 8,030,261,248`, `bpe = 2`): `cross_over = n_params / (2 × n_layers × n_kv_heads × head_dim) ≈ 122,532 tokens`. Print that at the 128k window the cache (**15.625 GiB**) **exceeds** the weights (**14.958 GiB**) — the punchline that motivates **3.6 VRAM math** (and, downstream, **3.13 paged attention**).

### 5. What to teach
- **Title:** *The KV cache: the model's running notebook.*
- **Angle:** dense concept only. The cache is a notebook of past K,V so decode is `O(1)` projections/step instead of `O(L²)` recompute — and its size is one linear formula you can compute in your head. Stop at "it grows forever → that's a memory problem (→ 3.6 / 3.13)."
- **Payload:** the recompute-it-caches insight (K,V per token per layer, never Q) · the all-linear byte formula · the linear-growth + cross-over punchline (the notebook can out-weigh the model).
- **Gotcha:** the cache grows without bound with context — left unmanaged it OOMs the GPU. That single fact is the bridge to **3.6** ("will it fit?") and **3.13** ("how do servers avoid reserving it up-front?"). *(We do NOT cover paging/block-tables/fragmentation here — that is 3.13's job.)*
- **Video (`T1`, 6 beats):** Hook("at long context, this notebook can weigh more than the model itself") → Analogy(a running notebook — jot each token's K,V once, never re-read from scratch) → Mechanism(cache filling as decode proceeds, animated — prefill fills 3 rows, each decode appends 1) → Gold(byte count growing linearly: 128 MiB / 512 MiB / 2 GiB / 4 GiB) → Gotcha(grows forever → OOM → a memory problem) → Recap.

### 6. Checklist
- [ ] demo runs, exits 0, ≥2 `[check]` lines
- [ ] output byte-stable on re-run (determinism)
- [ ] gold value reproduced, matches reference
- [ ] ≥2 web sources logged with `Verifies:` lines
- [ ] article is voiced + embeds the diagram/demo + ≥1 gotcha
- [ ] HyperFrames video renders, 6 beats, gold-check badge green
- [ ] **all probe questions answered out loud, no notes** ← the real bar

---

## 1.6 Sampling (temperature / top-k / top-p)

> How the model picks its next word — and a knob you will set on every API call
> you ever make. After this, "temperature" stops being a mystery slider and
> becomes the softmax divisor it is, and you know *exactly* why your agent must
> run cold.
> **Prerequisites:** 1.1. **Pays off in:** 2.11 (agent determinism), 3.15
> (speculative decoding). **Video:** `T2`.

### 1. Read
- **Your bundles:** `llm/SAMPLING.md` (the lineage greedy → temperature → top-k → top-p; the fixed 8-token logit vector `[2.3, 2.0, 0.4, 1.5, 0.1, 2.5, 0.7, 1.2]`; §4 the temperature sweep; §7 the nucleus algorithm) · `llm/sampling.py` (Sections A–G: softmax / greedy / top-k / top-p / combined + seeded draw) · `llm/sampling.html` (live slider).
- **Canonical:** Patrick von Platen, HuggingFace *How to generate text* · Karpathy, *The Unreasonable Effectiveness of Recurrent Neural Networks* (the temperature intuition) · Holtzman et al., *The Curious Case of Neural Text Degeneration*, ICLR 2020 (nucleus sampling + why greedy is degenerate) · HuggingFace `transformers` *Generation strategies* docs.
- **Goal:** state, from memory, how logits become one next token, what temperature divides and why, why top-p is adaptive and top-k is not, and why an agent that calls tools wants `temperature → 0`.

### 2. Research (web-verify, ≥2 sources each)
- **The model outputs a logit per vocab token; softmax turns logits into a probability distribution you sample from.** At each step the LM head emits a raw score (a *logit*) for *every* token; `softmax` converts those scores into non-negative probabilities that sum to 1, and one token is drawn from that distribution. `Verifies:` HuggingFace blog, *How to generate text* — "sampling means randomly picking the next word w_t according to its conditional probability distribution P(w|w_{1:t-1})" (https://huggingface.co/blog/how-to-generate) + Karpathy, *The Unreasonable Effectiveness of RNNs* — at test time "we feed a character into the RNN and get a distribution over what characters are likely to come next. We sample from this distribution" (https://karpathy.github.io/2015/05/21/rnn-effectiveness/).
- **Temperature divides the logits *before* softmax.** `probs = softmax(logits / T)`. A smaller `T` widens the gaps (the favorite pulls ahead → sharper, more confident); a larger `T` shrinks them (the tail catches up → flatter, more random). `Verifies:` HuggingFace blog — "make the distribution... sharper... by lowering the so-called `temperature` of the softmax" (https://huggingface.co/blog/how-to-generate) + Karpathy — "Decreasing the temperature from 1 to some lower number (e.g. 0.5) makes the RNN more confident... Conversely, higher temperatures will give more diversity" (https://karpathy.github.io/2015/05/21/rnn-effectiveness/).
- **Behavior at the limits: T→0 ⇒ argmax (greedy, deterministic); T=1 ⇒ the raw model distribution; T>1 ⇒ flatter/more random.** In the bundle's fixed logits the top-1 ("on") share goes `T=0.5 → 0.4351`, `T=1.0 → 0.2903`, `T=2.0 → 0.2053` — it shrinks as the distribution flattens; entropy rises `1.3981 → 1.8062 → 1.9984` nats. `Verifies:` Karpathy — "setting temperature very near zero will give the most likely thing" (which then loops; https://karpathy.github.io/2015/05/21/rnn-effectiveness/) + `llm/SAMPLING.md` §4 (the temperature-sweep table, output of `sampling.py` Section B).
- **Greedy decoding (argmax) is degenerate — it loops and repeats.** Always taking the single most-likely token traps the model in repetition, because the most-likely token after a repeated phrase is the phrase again. `Verifies:` HuggingFace generation docs — "Greedy search... selects the next most likely token... it breaks down when generating longer sequences because it begins to repeat itself" (https://huggingface.co/docs/transformers/main/en/generation_strategies) + Holtzman et al. — "using likelihood as a decoding objective leads to text that is bland and strangely repetitive" (https://arxiv.org/abs/1904.09751). *(Karpathy's near-zero-temperature sample loop — "is that they were all the same thing that was a startup..." — is the same effect.)*
- **Top-k keeps a FIXED set of the k highest-prob tokens and renormalizes.** Mask every token outside the top `k` to `-inf` (softmax prob → 0), then renormalize over the survivors. Its flaw is that `k` is fixed — it cannot tell a peaked distribution (1 good word) from a flat one (20 plausible words). `Verifies:` HuggingFace blog — "In Top-K sampling, the K most likely next words are filtered and the probability mass is redistributed among only those K next words"; "One concern... is that it does not dynamically adapt the number of words that are filtered" (https://huggingface.co/blog/how-to-generate) + `llm/SAMPLING.md` §6 (top-k=3 → kept `[0,1,5]`, fixed size regardless of shape).
- **Top-p (nucleus) keeps the SMALLEST set whose cumulative probability ≥ p — it is adaptive.** Sort tokens by probability, keep a running sum of the *probabilities* (never the logprobs — the bundle's #1 pitfall), and cut at `p`. The set size adapts: tiny when the model is confident, large when it is uncertain. `Verifies:` HuggingFace blog — "Top-p sampling chooses from the smallest possible set of words whose cumulative probability exceeds the probability p... the size of the set of words can dynamically increase and decrease" (https://huggingface.co/blog/how-to-generate) + Holtzman et al. — "sampling text from the dynamic nucleus of the probability distribution... effectively truncating the less reliable tail" (https://arxiv.org/abs/1904.09751). *(In the bundle, top-p=0.6 → nucleus `[0,5]` = 2 tokens, mass `0.5281` — stricter than top-k=3 on this peaked distribution.)*
- **For agents / tool-use, set temperature → 0 (greedy) for deterministic, reproducible behavior.** The only randomness in decoding is the final categorical draw; at `T→0` there is no draw at all (argmax), so the same prompt + model yields byte-identical output run after run — which is what you want when an agent must reliably emit valid tool-call JSON. `Verifies:` HuggingFace blog — "setting temperature → 0, temperature scaled sampling becomes equal to greedy decoding" (https://huggingface.co/blog/how-to-generate) + HuggingFace generation docs — greedy "selects the next most likely token at each step" and is the deterministic default (https://huggingface.co/docs/transformers/main/en/generation_strategies). *(Flagged: the "agents run cold" deployment guidance is a widely-used practitioner convention, not a single canonical citation — but the determinism of T→0 itself is fully verified above.)*

### 3. Questions (answer aloud, no notes)
1. What are logits, and how do they become the probabilities you sample from?
2. What does temperature mathematically do to the distribution *before* sampling — and what's the behavior at T→0, T=1, T>1?
3. Why is pure greedy decoding (argmax) degenerate and repetitive?
4. Top-k vs top-p — what's the core difference, and why is top-p called adaptive?
5. In top-p, why must the cumulative sum run over *probabilities*, not logits or logprobs? (the bundle's #1 pitfall)
6. Why do you set temperature→0 for an agent that calls tools, and what does it cost you?
7. The four strategies form a lineage — each fixes a flaw of the previous. Name the flaws.

### 4. Demo `.py`
- File: `sampling_intro.py`. Pin the bundle's fixed 8-token logit vector `LOGITS = [2.3, 2.0, 0.4, 1.5, 0.1, 2.5, 0.7, 1.2]`, `TOKENS = ["the","cat","xyz","sat","qqq","on","a","mat"]`. **Determinism:** implement the sampler with a **fixed-seed mulberry32/LCG** (no `random`/`Math.random()`/`Date.now()`); the filtering steps are RNG-free, only the final multinomial uses the seed; output byte-stable on re-run.
- Implement, in order: `log_softmax = z - logsumexp(z)` · `softmax` · **temperature** `softmax(logits/T)` · **top-k** mask (top `k`, rest `-inf`) · **top-p / nucleus** (sort desc by prob → `cumsum(probs)` → keep `cumsum < p`, always keep top-1) → seeded multinomial draw.
- **Gold value (must match on re-run):** pinned `seed=0`, `T=0.7`, `top_k=3`, `top_p=0.6`. Composing top-k(3) → top-p(0.6) over the fixed logits collapses the renormalized support to a **single token `{idx 5 ("on")}`**, so the seeded multinomial draw returns **`idx 5 ("on")`** every run — the draw is *seed-invariant* (a one-element support has zero variance), which is exactly why it is reproducible. *(Matches the bundle's `sampling.py` Section G.)*
- Print the probability mass the nucleus retains: top-p=0.6 → nucleus `[0,5]` ("the","on"), mass **`0.5281`** (< 0.6, because the token that would cross 0.6 is excluded).
- Demonstrate T→0 ⇒ argmax: as `T→0` the distribution one-hots on `idx 5 ("on")` (the greedy result); at `T=0.5 / 1.0 / 2.0` print the top-1 share `0.4351 / 0.2903 / 0.2053`.
- Print ≥2 `[check]` lines: `[check] greedy (T->0) == idx 5 ("on")` · `[check] top-k=3 kept == [0,1,5]` · `[check] top-p=0.6 nucleus == [0,5], mass 0.5281` · `[check] seed=0, T=0.7, top_k=3, top_p=0.6 -> sampled idx 5`.
- **Extension (make it yours):** greedy-vs-sampled divergence — feed the fixed logits as a toy repeated "logit stream" and generate a short sequence two ways: **greedy** (always argmax → loops on `idx 5` forever) vs **sampled at T=0.8, top_p=0.9** (the nucleus keeps ≥2 tokens, so the loop breaks). Print the first position where the two sequences diverge (greedy never leaves idx 5; the sampled run leaves it at position 1) — the *visible* payoff of not running cold, and the seed for 2.11 (agent determinism) + 3.15 (speculative decoding).

### 5. What to teach
- **Title:** *How the model picks its next word (and why your agent should run cold).*
- **Angle:** the model never picks *THE* best word — it **samples from a distribution you can bend**. One pipeline, four knobs: `logits → softmax → (temperature bend) → (top-k/top-p filter) → draw`. No math beyond softmax + a divisor.
- **Payload:** the temperature divisor (T→0 argmax / T=1 raw / T>1 flat, with the bundle's `0.4351 / 0.2903 / 0.2053` top-1 shares) · the top-k (fixed) vs top-p (adaptive) distinction, with the disagreement on the fixed logits (top-k=3 → `[0,1,5]` vs top-p=0.6 → `[0,5]`) · greedy degeneracy (loops).
- **Gotcha:** agents / tool-use want `temperature → 0` for reproducible, valid output; creative writing wants higher T. Run an agent hot and the same prompt gives a different (possibly malformed) tool call every time.
- **Video (`T2`):** Hook("the next word is a *sample*, not a pick") → Mechanism(logits → /T → top-p filter → seeded draw) → Gold(sampled token `idx 5`) → Gotcha(greedy loops / agents run cold).

### 6. Checklist
- [ ] demo runs, exits 0, ≥2 `[check]` lines
- [ ] output byte-stable on re-run (determinism)
- [ ] gold value reproduced, matches reference
- [ ] ≥2 web sources logged with `Verifies:` lines
- [ ] article is voiced + embeds the diagram/demo + ≥1 gotcha
- [ ] HyperFrames video renders, 6 beats, gold-check badge green
- [ ] **all probe questions answered out loud, no notes** ← the real bar

---

## 1.7 Quantization (concept)

> Shrinking the model, keeping the smarts. After this, "a 4-bit model is roughly a
> quarter of the size with most of the brain" stops being marketing and becomes one
> formula — `params × bits_per_weight / 8` — plus the one insight (outliers) that
> explains why naive rounding isn't enough. Concept only; *which* GGUF quant type
> (Q4_K_M) to actually pick is 3.5.
> **Prerequisites:** 1.1. **Pays off in:** 3.5 (quant types), 3.6 (VRAM math). **Video:** `T2`.

### 1. Read
- **Your bundles:** `llm/QUANTIZATION.md` (§0 the one-sentence idea; §1.1 the five intuitions — read the *coarser-ruler* and *why-weights-not-activations* ones only; **explicitly SKIP** §3 the MLX sign-convention math, §6 nibble packing, §8 the pitfall — those are 3.5 / server-side) · `llm/quantization.py` (Sections A–B only: the memory-math table + the one-row round-trip; the `scale = edge/q0` int4 mechanics are 3.5's job).
- **Canonical:** HuggingFace *Quantization overview* docs · Dettmers et al., *LLM.int8()* (arXiv:2208.07339) + the HF/bitsandbytes *Gentle Introduction to 8-bit Matrix Multiplication* blog · the HuggingFace *bitsandbytes* integration docs.
- **Goal:** state, from memory, what quantization does in one line, the size formula, why quality survives, and the trade-off.

### 2. Research (web-verify, ≥2 sources each)
- **Quantization stores the model's weights in fewer bits** — fp32 (4 B) → fp16/bf16 (2 B) → int8 (1 B) → int4 (½ B) — to cut memory while trying to preserve accuracy. (The same idea is later applied to activations and the KV cache in heavier variants, but the concept is "fewer bits per weight.") `Verifies:` HuggingFace *Quantization overview* — "Quantization lowers the memory requirements of loading and using a model by storing the weights in a lower precision while trying to preserve as much accuracy as possible... reduce the precision even further to integer representations, like int8 or int4" (https://huggingface.co/docs/transformers/main/en/quantization/overview) + Cloudflare, *What is quantization in machine learning?* — "Quantization converts big marbles to small marbles... reducing the number of bits used by data points... reducing this to 8 bits. The result is that quantized numbers take up half or a quarter as much space in memory" (https://www.cloudflare.com/learning/ai/what-is-quantization/).
- **The model-size formula is one line:** `size_bytes = params × bits_per_weight / 8`. A 4-bit model is ¼ the bytes of fp16, an 8-bit model ½. "bits per weight" (bpw) is the single knob that sets the **weights term** of the VRAM budget (→ 3.6). `Verifies:` HF/bitsandbytes *Gentle Introduction to 8-bit* — "To calculate the model size in bytes, one multiplies the number of parameters by the size of the chosen precision in bytes. For example... BLOOM-176B... `176*10**9 x 2 bytes = 352GB`" (https://huggingface.co/blog/hf-bitsandbytes-integration) + HF *bitsandbytes* docs — "Quantizing a model in 8-bit halves the memory-usage" and "Quantizing a model in 4-bit reduces your memory-usage by 4x" (https://huggingface.co/docs/transformers/main/en/quantization/bitsandbytes).
- **Why quality survives: neural weights are robust to low-bit rounding.** Quantization is lossy compression — it rounds each weight to the nearest of a few allowed levels and accepts up to `±scale/2` of error per weight — yet real LLM weights tolerate that approximation, and the tiny per-weight error rarely compounds enough to dent the output. `Verifies:` HF/bitsandbytes *Gentle Introduction* — "Quantization is done by essentially 'rounding' from one data type to another... a noisy process that can lead to information loss, a sort of lossy compression," yet int8 shows "0 performance degradation" on OPT-175B / BLOOM-176B benchmarks (https://huggingface.co/blog/hf-bitsandbytes-integration) + Cloudflare — "with fewer bits, quantized values are not as precise... in practice... the quantized AI model is 'good enough'" (https://www.cloudflare.com/learning/ai/what-is-quantization/).
- **The catch — a few large-magnitude outliers carry most of the signal and must be handled.** Once a model is big enough, a handful of hidden-state channels swing far outside the normal `[-3.5, 3.5]` band (e.g. `[-60, 6]`); a *single* global scale set by those outliers stretches the ruler so coarse that all the ordinary weights collapse onto a couple of levels — accuracy craters. LLM.int8() solves it by keeping those outlier channels in fp16 and quantizing the rest (mixed precision). `Verifies:` HF/bitsandbytes *Gentle Introduction* — "performance deterioration is caused by outlier features... 8-bit precision is extremely constrained, therefore quantizing a vector with several big values can produce wildly erroneous results... extracting all outliers with magnitude 6 or greater... recovers full inference performance" (https://huggingface.co/blog/hf-bitsandbytes-integration) + HF *bitsandbytes* docs — "An 'outlier' is a hidden state value greater than a certain threshold... usually normally distributed ([-3.5, 3.5]), [but] for large models ([-60, 6] or [6, 60])... beyond [~5] there is a significant performance penalty" (https://huggingface.co/docs/transformers/main/en/quantization/bitsandbytes).
- **The trade-off: smaller footprint + less memory bandwidth (faster decode) vs a small, monotonic quality loss.** Decode is bandwidth-bound (→ 1.4), so shrinking the weights ~4× both fits the model into smaller VRAM *and* streams it faster every single token; the price is a sliver of accuracy that grows as you cut more bits. `Verifies:` Cloudflare — quantization lets models "use less memory and computing power for faster responses and reduce costs. However, it can make AI inference less precise" (https://www.cloudflare.com/learning/ai/what-is-quantization/) + HF *bitsandbytes* docs — the "halves" (8-bit) / "4x" (4-bit) memory reduction is the gain side of that very trade-off (https://huggingface.co/docs/transformers/main/en/quantization/bitsandbytes). *(Bandwidth-bound decode is 1.4; the full VRAM budget is 3.6.)*
- **Quality falls off a cliff at the extremes — below ~3 bpw, naive uniform quantization breaks and you need calibration / importance-aware methods.** The error-vs-bits curve is gentle through 8→4 bits and steep below it; that cliff is exactly why real formats (GGUF's `Q4_K_M`, `IQ3_S`) mix precision per tensor and spend their scale-metadata budget cleverly instead of using one global ruler. *(Teases 3.5.)* `Verifies:` HF *Quantization overview* — "Some quantization methods require calibration for greater accuracy and extreme compression (1-2 bits)" (https://huggingface.co/docs/transformers/main/en/quantization/overview) + local `local-llm/QUANT_TYPES.md` §0 (the `Q4_0 → K-quants → I-quants` lineage exists to "spend the scale-metadata budget more cleverly"; I-quants reach 3.4 bpw only via importance-matrix calibration). *(Flagged: the exact "~3 bpw cliff" threshold is a widely-used llama.cpp practitioner heuristic, not a single canonical citation — the principle that extreme compression needs special methods is fully verified above.)*

### 3. Questions (answer aloud, no notes)
1. What does quantization do, in one line — and which part of the model does it usually compress, and why?
2. Write the model-size formula from memory. What is "bits per weight" (bpw), and how much smaller is a 4-bit model than an fp16 one?
3. Why does dropping from 16 bits to 4 *barely* hurt quality — what kind of process is quantization, and why is the per-weight error tolerable?
4. What are weight outliers, and why does a single global scale set by an outlier wreck the ordinary weights?
5. What's the trade-off — what do you *gain* (two things) and what do you *risk*, and in which phase of inference does the gain show up?
6. How does bpw connect to the VRAM budget — which term of "will it fit?" does it set? (tease → 3.6)
7. Where does the quality curve fall off a cliff, and what do real formats do about it? (tease → 3.5)

### 4. Demo `.py`
- File: `quantization_concept.py`. Pin a toy weight matrix (16 fp16 values): `W = [[0.55,-0.35,1.20,-0.85],[0.25,-1.15,1.05,-0.45],[0.75,-0.65,0.90,-0.05],[0.15,-0.95,0.40,-1.00]]` (`min=-1.15, max=1.20, range=2.35`). **Determinism:** the matrix, the bit-widths, and the round-to-nearest rule are all pinned constants; no `random`/`Date.now()`/network; output byte-stable on re-run.
- Implement **asymmetric round-to-nearest uniform quantization** with one global `scale = (max−min)/(2^bits − 1)` and offset `= min`: `q = clip(round((w−min)/scale), 0, 2^bits−1)`, `dequant = min + q·scale`. Run it for **INT8** (256 levels) and **INT4** (16 levels), then de-quantize and measure the gap to the original.
- **Gold values (must match on re-run):** FP16 weights = `16 × 2 = 32 B`; INT8 = `16 × 1 = 16 B` (½×); **INT4 = `16 × 4/8 = 8 B` (¼× FP16)** — the headline. INT4 max reconstruction error on the pinned tensor = **`0.073333`** (ceiling `scale/2 = 2.35/30 = 0.078333`); INT4 MSE = `0.000774`. INT8 max error = `0.004314` (ceiling `2.35/510 = 0.004608`) — ~17× tighter than INT4. *Error ≤ scale/2 is the theoretical ceiling for any round-to-nearest scheme; the demo prints the actual.*
- Print ≥2 `[check]` lines: `[check] FP16 32 B | INT8 16 B (0.50x) | INT4 8 B (0.25x)` · `[check] INT4 == params*4/8 == 8 B` · `[check] INT4 max abs err 0.073333 <= scale/2 0.078333`.
- Print a **model-size table** from the formula for **Llama-3-8B** (`8,030,261,248` params): 16 bpw → **`16.06 GB`**, 8 bpw → **`8.03 GB`**, 4 bpw → **`4.02 GB`** — one knob, a 4× span.
- **Extension (make it yours):** inject two large **outliers** into `W` (`W[0][0] = 9.0`, `W[2][3] = -7.0` ⇒ `range = 16.0`, INT4 `scale = 16/15 ≈ 1.067`). Re-run INT4: the small-magnitude weights collapse — only **6 distinct levels** are used (out of 16), and the max error jumps from `0.073` to **`~0.517`** (ceiling `scale/2 ≈ 0.533`). That visible collapse is *why* a single global scale fails and outlier-aware / mixed-precision methods (LLM.int8()) keep the big channels in fp16 — and why real per-tensor formats (→ 3.5) exist.

### 5. What to teach
- **Title:** *Shrinking the model, keeping the smarts.*
- **Angle:** a 4-bit model is roughly a quarter of the size with most of the brain. One knob (bpw), one formula, one trade-off curve — and the single insight (outliers) that explains why naive rounding isn't enough.
- **Payload:** the `params × bpw / 8` formula (4-bit = ¼ fp16, 8-bit = ½) · why quality survives (lossy rounding, per-weight error ≤ `scale/2`, weights tolerate it) · the outlier problem (one big weight stretches the ruler, the small weights collapse) · the size + bandwidth vs quality trade-off.
- **Gotcha:** outliers silently wreck naive uniform quantization, and at the extreme (sub-3 bpw) quality falls off a cliff — which is exactly why real formats (→ 3.5) mix precision per tensor instead of using one global scale.
- **Video (`T2`):** Hook("4-bit ≈ ¼ the size with most of the brain") → Mechanism(scale → round-to-nearest → de-quantize, animated on the pinned matrix) → Gold(INT4 = 8 B = ¼ FP16; max err `0.073333`) → Gotcha(outliers blow up the error / the sub-3 bpw cliff).

### 6. Checklist
- [ ] demo runs, exits 0, ≥2 `[check]` lines
- [ ] output byte-stable on re-run (determinism)
- [ ] gold value reproduced, matches reference
- [ ] ≥2 web sources logged with `Verifies:` lines
- [ ] article is voiced + embeds the diagram/demo + ≥1 gotcha
- [ ] HyperFrames video renders, 6 beats, gold-check badge green
- [ ] **all probe questions answered out loud, no notes** ← the real bar

---

## 1.8 Embeddings

> Turning meaning into numbers a computer can compare. After this, "semantic
> similarity" stops being a buzzword and becomes *one operation* — the angle
> between two vectors. Concept only; *embedding a corpus and querying it* is 2.5.
> **Prerequisites:** 1.1. **Pays off in:** 2.5 (embeddings for retrieval), 2.6–2.9
> (RAG). **Video:** `T2`.

### 1. Read
- **Your bundles:** `vector-db/VECTOR_DATABASES.md` §1 (embeddings intuition — a learned embedding is what TF-IDF approximates; the cosine metric applies to both) + §2 (similarity metrics: cosine / dot / euclidean) · `vector-db/vector_databases.py` Section A (the TF-IDF proxy) + Section B (the `A=[1,2,3], B=[4,5,6]` worked metrics). **Explicitly SKIP** §3 ANN, §4 indexing, §5 Qdrant — those are 2.6.
- **Canonical:** OpenAI, *Vector embeddings* guide · Sentence-Transformers (SBERT), *Semantic Textual Similarity* + the `all-MiniLM-L6-v2` model card · Mikolov et al. 2013, *Efficient Estimation of Word Representations in Vector Space* (arXiv:1301.3781) · gensim, *Word2Vec Model* tutorial (the `king − man + woman ≈ queen` walkthrough).
- **Goal:** state, from memory, what an embedding is, why similar meanings land near each other, what `king − man + woman ≈ queen` proves, and when cosine vs dot vs L2 applies.

### 2. Research (web-verify, ≥2 sources each)
- **An embedding is a vector (list) of floating-point numbers** — a fixed-length array (hundreds to thousands of dims) a model emits for a piece of text, an image, or audio. Common sizes: `384` (SBERT `all-MiniLM-L6-v2`), `1536` (OpenAI `text-embedding-3-small`), `3072` (`text-embedding-3-large`). `Verifies:` OpenAI embeddings guide — "An embedding is a vector (list) of floating point numbers... the length of the embedding vector is `1536` for `text-embedding-3-small` or `3072` for `text-embedding-3-large`" (https://platform.openai.com/docs/guides/embeddings) + HuggingFace `all-MiniLM-L6-v2` card — "It maps sentences & paragraphs to a **384** dimensional dense vector space" (https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2).
- **Near = similar: the embedding is built so that semantic closeness becomes geometric closeness.** Items humans judge similar land at nearby points; dissimilar items land far apart. That one property is what makes a vector "searchable." `Verifies:` Pinecone, *What are vector embeddings* — "This representation makes it possible to translate semantic similarity as perceived by humans to proximity in a vector space... the semantic similarity of these objects... can be quantified by how close they are to each other as points in vector spaces" (https://www.pinecone.io/learn/vector-embeddings/) + OpenAI embeddings guide — "The distance between two vectors measures their relatedness. Small distances suggest high relatedness and large distances suggest low relatedness" (https://platform.openai.com/docs/guides/embeddings).
- **The near=similar property is *learned*, not hand-coded.** The model's weights are optimized by a contrastive objective — pull paired/similar examples together, push the rest apart — so the geometry is a side-effect of training, not a rule you write. `Verifies:` HuggingFace `all-MiniLM-L6-v2` card — "train sentence embedding models on very large sentence level datasets using a self-supervised contrastive learning objective... given a sentence from the pair, the model should predict which out of a set of randomly sampled other sentences, was actually paired with it" (https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) + Pinecone, *What are vector embeddings* — "The weights are being optimized in a way that images with the same labels are embedded closer compared to images with different labels" (https://www.pinecone.io/learn/vector-embeddings/).
- **The space encodes *relationships*, not just neighborhoods — vector arithmetic has meaning.** The classic word2vec result `vec("king") − vec("man") + vec("woman") ≈ vec("queen")` shows the model learned directions for concepts (gender, royalty, capital-of) you can slide along algebraically. `Verifies:` gensim, *Word2Vec Model* tutorial — `vec("king") - vec("man") + vec("woman") =~ vec("queen")`... "The output are vectors, one vector per word, with remarkable linear relationships" (https://radimrehurek.com/gensim/auto_examples/tutorials/run_word2vec.html) + Mikolov et al. 2013, *Efficient Estimation of Word Representations in Vector Space* — "continuous vector representations of words... state-of-the-art performance on our test set for measuring syntactic and semantic word similarities" (arXiv:1301.3781, https://arxiv.org/abs/1301.3781).
- **Similarity between two embeddings is one number from three interchangeable metrics.** **Cosine similarity** (angle, `−1..1`) is the text default and ignores magnitude; **dot product** is the raw `Σ aᵢbᵢ`; **L2 / Euclidean** is the straight-line `√Σ(aᵢ−bᵢ)²`. For **L2-normalized** vectors (`‖v‖=1`) cosine == dot product **exactly**, so most systems pre-normalize once and use the cheaper dot-product index with no quality loss. `Verifies:` Sentence-Transformers, *Semantic Textual Similarity* — "Valid options are: `SimilarityFunction.COSINE` (default), `DOT_PRODUCT`, `EUCLIDEAN` (Negative Euclidean Distance)... Dot product on normalized embeddings is equivalent to cosine similarity... the 'dot' metric will be faster than 'cosine'" (https://sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html) + OpenAI embeddings guide — "we use the cosine similarity between the embedding vectors of the query and each document" (https://platform.openai.com/docs/guides/embeddings). *(Worked for all three on `A=[1,2,3], B=[4,5,6]`: cosine `0.9746`, dot `32.0`, L2 `5.1962` — `vector_databases.py` Section B.)*
- **Embeddings turn text into numbers a computer can compare — the foundation of semantic search and RAG.** Because "similar meaning" = "nearby vector," finding the documents most relevant to a query reduces to: embed the query, return the `k` corpus vectors with the highest cosine. That is *all* retrieval is — but we stop at the concept here; *embedding a corpus, storing it, and querying at scale* is 2.5/2.6. `Verifies:` OpenAI embeddings guide — embeddings "are commonly used for: Search (where results are ranked by relevance to a query string)..." (https://platform.openai.com/docs/guides/embeddings) + Pinecone, *What are vector embeddings* — "Similarity search is one of the most popular uses of vector embeddings... Nearest neighbor search in turn can be used for tasks like... recommendations, anomaly detection" (https://www.pinecone.io/learn/vector-embeddings/). *(Teases 2.5.)*

### 3. Questions (answer aloud, no notes)
1. What is an embedding — and does any single dimension "mean" something you can name?
2. Why do similar meanings end up *near each other* in the space — what puts them there?
3. What does `king − man + woman ≈ queen` tell you about the geometry the model learned?
4. Cosine similarity vs dot product vs L2 — when is each the right choice, and why are cosine and dot *identical* on normalized vectors?
5. Why must you compare embeddings produced by the *same* model? (→ never mix models)
6. How do embeddings turn a piece of text into something searchable? (tease → 2.5)
7. Why is "high cosine similarity" not the same as "true" or "correct"? (bias / similarity ≠ truth)

### 4. Demo `.py`
- File: `embeddings_intro.py`. **Determinism:** the toy embedder is a **TF-IDF bag-of-words** (the same model-free proxy as `vector_databases.py` Section A) — the vocabulary is a pure function of the pinned corpus, so there is **no RNG and no `Date.now()`/network**; output is byte-stable on re-run.
- **Corpus** (1 query + 7 candidates): `["the cat sat on the mat"(q), "the dog sat on the log", "the cat lay on the bed", "a kitten sleeps on the rug", "the car parked on the street", "machine learning models train on data", "vector databases store dense embeddings", "she cooked pasta for dinner"]`. Build TF-IDF over the 31-term vocabulary, print the **8×8 pairwise cosine matrix**, and the **top-k nearest neighbors** of the pinned query `s0 = "the cat sat on the mat"`.
- **Gold value (must match on re-run):** nearest-neighbor ranking of `s0` (query excluded) = **`[1, 2, 4, 3, 5, 6, 7]`** with cosine scores **`[0.2814, 0.2814, 0.0856, 0.0414, 0.0059, 0.0000, 0.0000]`**. The two sentences sharing *rare content words* with the query — `s1 "the dog sat on the log"` (shares `sat`) and `s2 "the cat lay on the bed"` (shares `cat`) — tie at the top (`0.2814`); the two sharing *no content words* — `s6 "vector databases store dense embeddings"` and `s7 "she cooked pasta for dinner"` — sit at exactly `0.0000`. **Near == similar holds.**
- Print ≥2 `[check]` lines: `[check] top-2 nearest == s1,s2 (shared rare words: sat, cat)` · `[check] bottom-2 == s6,s7 (cos 0.0000, no shared content words)` · `[check] deterministic TF-IDF: no RNG/Date.now, vocab fixed by pinned corpus`.
- **The honest limit (a teaching beat, not a check):** the toy is *lexical* — it ranks `s4 "the car parked on the street"` (`0.0856`, filler overlap on `the/on`) *above* `s3 "a kitten sleeps on the rug"` (`0.0414`), even though a kitten is far closer in *meaning* to the cat than a parked car is. That gap — lexical vs semantic — is exactly what a *learned dense* embedding closes.
- **Extension (make it yours):** if `sentence-transformers` is available locally, ADD a real-embedder row — embed the same 8 sentences with `all-MiniLM-L6-v2` (`384`-dim) and re-rank. The deterministic TF-IDF ranking above stays the gold; the neural row is the comparison. Expect `s3 "a kitten sleeps..."` to jump *above* `s4` (semantic kinship beats filler overlap) — the visible payoff of learned geometry, and the seed for **2.5** (embeddings for retrieval).

### 5. What to teach
- **Title:** *Turning meaning into numbers a computer can compare.*
- **Angle:** text → vector → distance = semantic similarity. One move, reused everywhere downstream. The hook is that the geometry is *learned* — `king − man + woman ≈ queen` is the proof the model built directions for concepts.
- **Payload:** what an embedding is (a learned float vector, `384`/`1536`/`3072` dims) · the near=similar property (and that it is *trained* in via a contrastive objective) · cosine vs dot vs L2 (and cosine == dot on normalized vectors) · the lexical-vs-semantic limit from the toy demo.
- **Gotcha:** embeddings inherit their training data's bias, and **similarity ≠ correctness or truth** — the same geometry that yields `king − man + woman ≈ queen` also bakes in stereotypes, so a high cosine is not an endorsement. And **never mix embedding models** in one index — vectors from different models live in different spaces, so cosine between them is meaningless (→ 2.6).
- **Video (`T2`):** Hook(`king − man + woman ≈ queen` — the model learned geometry of meaning) → Mechanism(text → vector → cosine, the 8×8 matrix filling in) → Gold(nearest-neighbor ranking `[1, 2, 4, 3, 5, 6, 7]`; top-2 share rare words, bottom-2 at `0.0000`) → Gotcha(bias / similarity ≠ truth / never mix models).

### 6. Checklist
- [ ] demo runs, exits 0, ≥2 `[check]` lines
- [ ] output byte-stable on re-run (determinism)
- [ ] gold value reproduced, matches reference
- [ ] ≥2 web sources logged with `Verifies:` lines
- [ ] article is voiced + embeds the diagram/demo + ≥1 gotcha
- [ ] HyperFrames video renders, 6 beats, gold-check badge green
- [ ] **all probe questions answered out loud, no notes** ← the real bar

---

## 1.9 Why an LLM can call a function

> Demystifying function-calling before Phase 2. After this, "the model called a
> function" stops being magic and becomes *one loop*: the model emits tokens that
> look like JSON, **your code** parses them and runs the function, then feeds the
> result back as new tokens. The model executes nothing — ever. This kills the
> "agents are magic" framing one unit before Phase 2.
> **Prerequisites:** 1.1 (the model only outputs tokens), 1.6 (sampling). **Pays off in:**
> 2.10 (function calling), 2.11 (the agent loop). **Video:** `T2`.

### 1. Read
- **Your bundles:** `local-llm/GRAMMAR_OUTPUT.md` (the mask — before each token the sampler zeros every vocab token the grammar would reject, survivors keep their model score; the GOLD `{` letter+ `}` trace in §4) · `llm/SAMPLING.md` (logit masking: top-k/top-p set disallowed logits to `-inf`; `-inf` is invariant under `/temp` and survives `log_softmax`, so a mask is a *hard* constraint layered *before* top-p/temperature).
- **Canonical:** OpenAI, *Function calling* + *Structured Outputs* guides · Anthropic, *Tool use with Claude* · llama.cpp *GBNF Guide* (grammar-constrained decoding) · Outlines — Willard & Louf 2023, *Efficient Guided Generation for Large Language Models* (arXiv:2307.09702).
- **Goal:** state, from memory, *who* executes a function call (your code, never the model), the two mechanisms that make the token stream schema-valid (prompt+parse vs grammar/constrained decoding), and how the tool's result re-enters the conversation as tokens.

### 2. Research (web-verify, ≥2 sources each)
- **An LLM only ever emits a sequence of tokens — it cannot execute code, hit a network, or call an API itself.** There is no "function" inside the model; the most it can do is write characters. Every "tool call" is the host application *interpreting* a token sequence the model produced. `Verifies:` OpenAI *Function calling* — the flow is "a multi-step conversation between your application and a model," whose step 3 is "Execute code **on the application side** with input from the tool call" (https://platform.openai.com/docs/guides/function-calling) + Anthropic *Tool use* — "Tool use lets Claude call functions that you define... It then returns a structured call that **your application executes** (client tools)" (https://docs.anthropic.com/en/docs/build-with-claude/tool-use/overview).
- **"Function calling" = the model emits a structured token sequence (a JSON object matching a declared schema) that your code parses and dispatches to a real function.** The function's parameters are declared as a JSON schema; the model's "call" is just the arguments serialized as JSON text; your code `json.loads` it and invokes the matching handler. `Verifies:` OpenAI *Function calling* — "the `parameters` are defined by a [JSON schema]," and the example does `args = json.loads(tool_call.function.arguments)` then `get_horoscope(args["sign"])` (https://platform.openai.com/docs/guides/function-calling) + Anthropic *Tool use* — Claude "returns a structured call" as `tool_use` blocks whose `input` your code runs (https://docs.anthropic.com/en/docs/build-with-claude/tool-use/overview).
- **Two mechanisms make that token stream reliably schema-valid. (a) Prompt + fine-tune, then parse (with retries).** You instruct the model to emit JSON, it (mostly) does, you parse — and retry on malformed output. The lineage is "ask nicely" → **JSON mode** (guarantees valid JSON, *not* schema) → **Structured Outputs / strict mode** (guarantees valid JSON *and* schema adherence). `Verifies:` OpenAI *Structured Outputs* — "Structured Outputs is the evolution of JSON mode. While both ensure valid JSON is produced, only Structured Outputs ensure schema adherence"; benefit "Reliable type-safety: No need to validate or retry incorrectly formatted responses" (https://platform.openai.com/docs/guides/structured-outputs) + Anthropic *Tool use* — "Add `strict: true` to your custom tool definitions to ensure Claude's tool calls always match your schema exactly" (https://docs.anthropic.com/en/docs/build-with-claude/tool-use/overview).
- **(b) Constrained / grammar decoding — mask the logits at every step so only grammar-valid tokens can be sampled.** Before each token the sampler builds a mask over the *whole* vocabulary: tokens the grammar rejects get logit `-inf` (softmax prob 0), survivors keep their model score; you then sample (greedy/top-p) *after* the mask. **The output is guaranteed to parse.** `Verifies:` llama.cpp *GBNF Guide* — "GBNF... is a format for defining formal grammars to constrain model outputs in llama.cpp. For example, you can use it to force the model to generate valid JSON" (https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md) + Outlines — "LLMs are powerful but their outputs are unpredictable. Most solutions attempt to fix bad outputs *after* generation using parsing, regex, or fragile code... Outlines guarantees structured outputs *during* generation — directly from any LLM" (https://github.com/dottxt-ai/outlines/blob/main/README.md). *(Mechanism + the ~10–30% slowdown are in the local `local-llm/GRAMMAR_OUTPUT.md` §0/§5; the method is Willard & Louf 2023, arXiv:2307.09702, cited by Outlines.)*
- **Crucial nuance — for plain completion the grammar only masks (the model never sees the schema); for tool-calling the schema is *also* injected into the prompt.** A mask makes tokens valid but gives the model no idea *what* to produce, so tool-calling APIs put the tool definitions in a system prompt the model attends over, *and* constrain the output. `Verifies:` llama.cpp *GBNF Guide* — "The JSON schema is only used to constrain the model output and is **not** injected into the prompt. The model has no visibility into the schema... This does not apply to tool calling, where schemas are injected into the prompt" (https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md) + Anthropic *Tool use* — "When you use tools, the API also automatically includes a special system prompt for the model which enables tool use" (https://docs.anthropic.com/en/docs/build-with-claude/tool-use/overview).
- **The tool's result is fed back as new input tokens on the next turn — that is "the loop."** The model never touches the outside world; it sees the result as more text in the conversation, then decides whether to call another tool or answer. Repeat until it stops emitting tool calls. `Verifies:` OpenAI *Function calling* — "We then send all of the tool definition, the original prompt, the model's tool call, **and the tool call output** back to the model to finally receive a text response" (https://platform.openai.com/docs/guides/function-calling) + Anthropic *Tool use* — "Your code executes the operation and **sends back a `tool_result`**" (https://docs.anthropic.com/en/docs/build-with-claude/tool-use/overview). *(Teases 2.11 — the agent loop is this turn repeated.)*
- **Run the call cold (temperature → 0) so the tool-call token stream is deterministic and reliably parses.** Sampling randomness can mutate the JSON into a malformed token on one run and not the next; `T→0` (greedy/argmax) removes the only RNG step, so the same prompt + model yields byte-identical output. `Verifies:` carried from 1.6 — HuggingFace *How to generate* ("setting temperature → 0... becomes equal to greedy decoding," https://huggingface.co/blog/how-to-generate) + HuggingFace *Generation strategies* (greedy "selects the next most likely token," the deterministic default, https://huggingface.co/docs/transformers/main/en/generation_strategies). *(The OpenAI/Anthropic "strict / no-retry" guarantee above is exactly why a cold, constrained call needs no retry path.)*

### 3. Questions (answer aloud, no notes)
1. An LLM only ever emits tokens — so what *actually* happens when it "calls a function"? Who runs the code: the model, or your application?
2. Name the two mechanisms that make the model's token stream reliably schema-valid — and which one *guarantees* a parse?
3. In constrained/grammar decoding, what happens to the logits at each step — which tokens survive, and where do top-p/temperature sit relative to the mask?
4. A grammar mask forces valid output for plain completion — but does the model "see" the schema? How does tool-calling differ (schema in the prompt)?
5. How does a tool's *result* get back into the conversation, and why is that "a loop"? (tease → 2.11)
6. Why run the tool call cold (temperature → 0), and what does an *unconstrained* hot model intermittently emit?
7. Why does all of this mean "agents are not magic"?

### 4. Demo `.py`
- File: `function_calling_mechanism.py`. **Determinism:** the vocab, the grammar, and the per-step logits are all pinned constants; decoding is greedy (`argmax`) so there is **no RNG at all** — no `random`/`Date.now()`/network; output byte-stable on re-run.
- **Micro-vocab** (15 single-char tokens): `['{','"','t','o','l',':','s','e','a','r','c','h','}','x','9']` — `x` is a valid-but-wrong letter, `9` is a digit the grammar never allows (the trap).
- **The grammar** (a one-tool JSON schema): `root ::= "{" "\"tool\"" ":" "\"" letter+ "\"" "}"`, `letter ::= [a-z]`. Implement `valid_next(prefix)` as a tiny state machine: while building the literal `{"tool":"` only the next literal char is live; in the value region any letter is live (and `"` becomes live once ≥1 letter is down); after the value's closing `"` only `}` is live. (Mirrors the GOLD mask in `GRAMMAR_OUTPUT.md` §4.)
- **Logits per step** (pinned, no RNG): the *target* char for that step gets logit `3.0`; every other token `0.0`; **plus a trap** — token `9` gets logit `9.0` at steps 0 and 9, so the raw model *wants* to emit an invalid digit where only `{` / letters are legal.
- **Masked greedy decode:** at each step set `logit = -inf` for every token NOT in `valid_next(prefix)`, then `argmax` over the survivors. Print the per-step trace (raw argmax vs masked argmax) and the final string.
- **Gold value (must match on re-run):** masked greedy forces exactly **`{"tool":"search"}`**, which `json.loads` parses to **`{"tool": "search"}`** — schema-valid every run. The mask **rescued 2 steps** (steps 0 and 9: raw argmax was `9`, masked argmax was `{` / `s`). Unconstrained greedy on the *same* logits emits **`9"tool":"9earch"}`** — not valid JSON (`json.loads` raises) — the exact failure mode that constrained decoding deletes.
- Print ≥2 `[check]` lines: ``[check] masked forced output == '{"tool":"search"}'`` · ``[check] masked output json.loads -> {"tool": "search"}`` · ``[check] unmasked greedy -> invalid JSON (starts with '9')`` · ``[check] mask rescued 2 steps (0 and 9)``.
- **Extension (make it yours):** move the trap to step 15 (closing quote) where the raw argmax is a *letter* (`e`) instead of `9` — now the breakage is *structural* (unterminated string) with no invalid *character*, proving the mask enforces shape, not just charset. Then keep the mask but offer two tools (`search` / `delete`): the output stays valid JSON, yet the model can confidently name the **wrong** tool — the deeper gotcha that a mask fixes *shape*, never *correctness* (→ 2.10 / 2.11).

### 5. What to teach
- **Title:** *Why an LLM can call a function (it's tokens all the way down).*
- **Angle:** the model never executes anything — it emits tokens your code interprets. Kill the magic; show the two mechanisms (prompt-and-parse vs constrained decoding) and the dispatch loop. The pinned demo is the proof: the *same* logits that vomit `9"tool":"9earch"}` unmasked are coerced into valid `{"tool":"search"}` by a logit mask.
- **Payload:** the token-only insight (the model writes characters; your code runs functions) · JSON-as-protocol (schema in, arguments-JSON out, parse, dispatch) · logit-masking (invalid → `-inf` before sampling) · the result-fed-back loop (→ 2.11).
- **Gotcha:** (1) unconstrained models emit malformed JSON *intermittently* — which is why the naive "ask nicely + parse" path needs retries, and why strict/grammar modes exist; (2) a mask guarantees *valid JSON*, never the *correct* function or arguments — the model can be confidently wrong about which tool to call.
- **Video (`T2`):** Hook("the model never executes — it emits tokens your code interprets") → Mechanism(prompt → JSON → parse → dispatch OR logit-mask, side by side) → Gold(forced valid `{"tool":"search"}` vs unmasked `9...`) → Gotcha(malformed JSON / wrong tool).

### 6. Checklist
- [ ] demo runs, exits 0, ≥2 `[check]` lines
- [ ] output byte-stable on re-run (determinism)
- [ ] gold value reproduced, matches reference
- [ ] ≥2 web sources logged with `Verifies:` lines
- [ ] article is voiced + embeds the diagram/demo + ≥1 gotcha
- [ ] HyperFrames video renders, 6 beats, gold-check badge green
- [ ] **all probe questions answered out loud, no notes** ← the real bar

---

# Phase 2 — AI Applications via OpenRouter

> The brand-builder. API-based (OpenRouter = one key, many models), low infra.
> *(topics appended one at a time)*

---

# Phase 3 — Local LLM & Inference

> Run → fit → serve. Deferred until Phase 1 foundations make it comprehensible.
> *(topics appended one at a time)*
