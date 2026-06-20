# research/ — ZeroServe Concept Bundles

> **One idea = four files that cite each other**, all deriving from a runnable
> `.py` that prints every number. Nothing is hand-computed; everything is
> fact-checked against the original papers. Each guide is written so a person
> with **minimal math and coding** background can follow every step.
>
> Source material: [`../learning_guide/`](../learning_guide/) (the ZeroServe
> journey). Start at [`HOW_TO_RESEARCH.md`](./HOW_TO_RESEARCH.md) for the
> philosophy, or just pick a bundle below.

---

## 🗺️ The map: every bundle, by phase

```mermaid
graph LR
    subgraph p1["Phase 1 — Foundations & Math Pipe (get the numbers right)"]
        direction LR
        N[NORMALIZATION]
        P[ROPE + ABSOLUTE_PE]
        M[MLP_ACTIVATION]
        G[GQA]
        C[CAUSAL_MASK]
        T[TOKENIZATION]
        S[SAMPLING]
    end
    subgraph p2["Phase 2 — Acceleration (memory bandwidth, not FLOPs)"]
        direction LR
        F[FLASH_ATTENTION]
        Q[QUANTIZATION]
        K[KV_CACHE]
    end
    p1 --> p2

    style p1 fill:#eaf2f8,stroke:#2980b9
    style p2 fill:#fdecea,stroke:#c0392b
    style F fill:#f5b7b1,stroke:#c0392b
```

**Cross-reference web** (🔗 in every guide):
- RoPE's `offset` ⟷ KV_CACHE's decode offset ⟷ CAUSAL_MASK's `k=(S−L)`
- RoPE & GQA both operate on Q/K; the frequency ladder is shared with ABSOLUTE_PE
- FLASH_ATTENTION + KV_CACHE + QUANTIZATION all share the "LLMs are bandwidth-bound" thesis

---

## 📚 All 11 bundles at a glance

Every row is the 4-file bundle: `.py` (ground truth) · `.md` (guide) · `.html` (interactive).
Also commit `*_output.txt` (captured stdout — see each `.md`'s `> From X.py Section Y:` callouts).

| # | Concept (lineage) | Phase | `name.py` | Guide `.md` | Interactive `.html` |
|---|---|---|---|---|---|
| 1 | **Normalization** — LayerNorm → RMSNorm | 1 | [`normalization.py`](./normalization.py) | [`NORMALIZATION.md`](./NORMALIZATION.md) | [`normalization.html`](./normalization.html) |
| 2 | **Position encoding (a)** — RoPE (rotary) | 1 | [`rope.py`](./rope.py) | [`ROPE.md`](./ROPE.md) | [`rope.html`](./rope.html) |
| 2 | **Position encoding (b)** — absolute (sinusoidal/learned) | 1 | [`absolute_pe.py`](./absolute_pe.py) | [`ABSOLUTE_PE.md`](./ABSOLUTE_PE.md) | [`absolute_pe.html`](./absolute_pe.html) |
| 3 | **MLP & activation** — ReLU → GELU → SwiGLU/SiLU | 1 | [`mlp_activation.py`](./mlp_activation.py) | [`MLP_ACTIVATION.md`](./MLP_ACTIVATION.md) | [`mlp_activation.html`](./mlp_activation.html) |
| 4 | **Attention heads** — MHA → MQA → GQA | 1 | [`gqa.py`](./gqa.py) | [`GQA.md`](./GQA.md) | [`gqa.html`](./gqa.html) |
| 5 | **Attention mechanics** — causal mask + `k=(S−L)` offset + QK-Norm + shapes | 1 | [`causal_mask.py`](./causal_mask.py) | [`CAUSAL_MASK.md`](./CAUSAL_MASK.md) | [`causal_mask.html`](./causal_mask.html) |
| 6 | **Tokenization** — WordPiece → BPE → SentencePiece | 1 | [`tokenization.py`](./tokenization.py) | [`TOKENIZATION.md`](./TOKENIZATION.md) | [`tokenization.html`](./tokenization.html) |
| 7 | **Sampling** — greedy → top-k → top-p nucleus | 1 | [`sampling.py`](./sampling.py) | [`SAMPLING.md`](./SAMPLING.md) | [`sampling.html`](./sampling.html) |
| 8 | **Attention compute** — materialized softmax → FlashAttention (online softmax) ★hardest | 2 | [`flash_attention.py`](./flash_attention.py) | [`FLASH_ATTENTION.md`](./FLASH_ATTENTION.md) | [`flash_attention.html`](./flash_attention.html) |
| 9 | **Precision & weights** — FP16 → W4A16 group quantization | 2 | [`quantization.py`](./quantization.py) | [`QUANTIZATION.md`](./QUANTIZATION.md) | [`quantization.html`](./quantization.html) |
| 10 | **KV memory** — recompute → dense cache → paged cache (+ rewind) | 2 | [`kv_cache.py`](./kv_cache.py) | [`KV_CACHE.md`](./KV_CACHE.md) | [`kv_cache.html`](./kv_cache.html) |

> The 11 files map to the **10 key problems** in the curriculum — position
> encoding is one problem split across two sibling bundles (`ROPE` ↔ `ABSOLUTE_PE`).

---

## 🧭 Suggested beginner reading order

Read the `.md` first, play with the `.html`, then skim the `.py` to see the
ground-truth numbers. Build the mental model bottom-up:

```mermaid
graph TD
    A["1. TOKENIZATION<br/>text → IDs"] --> B["2. NORMALIZATION<br/>keep features stable"]
    B --> C["3. MLP_ACTIVATION<br/>the 'thinking' block"]
    C --> D["4. POSITION ENCODING<br/>ROPE + ABSOLUTE_PE"]
    D --> E["5. GQA<br/>sharing the KV cabinets"]
    E --> F["6. CAUSAL_MASK<br/>no peeking at the future"]
    F --> G["7. SAMPLING<br/>picking the next word"]
    G --> H["8. KV_CACHE<br/>stop recomputing the past"]
    H --> I["9. FLASH_ATTENTION<br/>beat the memory wall"]
    I --> J["10. QUANTIZATION<br/>4× smaller weights"]
    style D fill:#eafaf1,stroke:#27ae60
    style I fill:#f5b7b1,stroke:#c0392b
```

If you only have time for three: **ROPE** (the relative-position idea),
**FLASH_ATTENTION** (the bandwidth-bound thesis), **KV_CACHE** (why serving is hard).

---

## 🛠️ The meta-guides (how this folder works)

| Guide | What it's for | When to read |
|---|---|---|
| [`HOW_TO_RESEARCH.md`](./HOW_TO_RESEARCH.md) | The 4-file bundle law: `.py` = ground truth, `.md` = verbatim numbers under callouts, `.html` = recompute + gold-check. | Before building any bundle by hand |
| [`HOW_TO_ANIMATE.md`](./HOW_TO_ANIMATE.md) | The self-contained `.html` recipe (zero deps, dark palette, slider + `[check: OK]` badge). | Before writing any animation |
| [`SUBAGENTS_RESEARCH_GUIDE.md`](./SUBAGENTS_RESEARCH_GUIDE.md) | How to delegate many bundles to parallel subagents at scale (prompt template + verification sweep). | Before spawning a build/review swarm |

---

## ✅ Verify everything (re-runnable)

Every `.py` runs clean with `[check]` asserts; every `.html` passes `node --check`
and shows a green `[check: OK]` gold badge. Re-confirm the whole folder:

```bash
cd research
for n in normalization mlp_activation gqa causal_mask tokenization sampling \
         flash_attention quantization kv_cache rope absolute_pe; do
  uv run python $n.py >/dev/null 2>&1 && echo "  $n.py: OK" || echo "  $n.py: FAILED"
  python3 -c "import re;open('/tmp/_j.js','w').write(re.search(r'<script>(.*)</script>',open('$n.html').read(),re.S).group(1))" 2>/dev/null
  node --check /tmp/_j.js 2>/dev/null && echo "  $n.html JS: OK" || echo "  $n.html JS: FAIL"
done
```

Each `.md` numbers its tables under `> From {name}.py Section X:` callouts —
diff them against `{name}_output.txt` to audit any value.

---

## ➕ Add a new bundle

1. Pick a concept from [`../learning_guide/`](../learning_guide/).
2. Follow [`HOW_TO_RESEARCH.md`](./HOW_TO_RESEARCH.md) (the 6-step workflow).
3. If building several at once, delegate via [`SUBAGENTS_RESEARCH_GUIDE.md`](./SUBAGENTS_RESEARCH_GUIDE.md).
4. Add a row to the table above and the reading-order mermaid.
5. 🔗 cross-reference the new bundle from the related existing ones.

---

## 🔑 The one rule (why this folder is trustworthy)

> **If a number appears in a `.md` or `.html`, it was printed by the `.py` — or
> recomputed in JS with the identical formula and gold-checked against it. Every
> formula is fact-checked against the original paper. Nothing is hand-waved.**

That single discipline is what lets these guides scale to 11+ topics without
drifting into "trust me" math.
