# How to Add New Models — Known Issues & Checklist

This document tracks every architecture feature the visualizer **does not fully render**. Before adding a new model, check this list to understand what the generated graph will misrepresent.

---

## The Problem: One Template, Many Architectures

The visualizer template (`viz_template.html`) draws a **generic decoder-only transformer skeleton**:

```
Embed → RMSNorm → [QK-Norm] → [RoPE] → Attention → o_proj → Residual
      → RMSNorm → gate_proj/up_proj → SiLU → Multiply → down_proj → Residual
      → ... (repeat N layers) ... → Final RMSNorm → LM Head → Softmax → Output
```

Every model gets this same skeleton with its CFG values substituted. **When a model deviates from this skeleton, the graph is structurally wrong** — not just a numbers issue, but nodes and edges that don't match reality.

---

## Known Issues by Severity

### CRITICAL — Graph Shows Wrong Layer Type

These models use non-standard layer types that we render as standard attention+MLP. The **graph structure is misleading**.

| Feature | Models Affected | What We Show | What's Real | Fix Difficulty |
|---|---|---|---|---|
| **Gated DeltaNet** | Qwen3.5-4B, Ornith-9B, AgentWorld-35B, Ornith-35B, Agents-A1 | Standard attention (Q·K^T softmax) | DeltaNet: gated linear attention with delta update rule. 24/32 or 30/40 layers are DeltaNet, not attention. | Hard — needs new node type + subgraph |
| **Mamba/SSM blocks** | Nemotron-H (Audex-30B), Nemotron Puzzle-75B | Standard attention | Mamba: state-space model with selective scan. Alternating Mamba/MoE/Attention blocks via `block_configs` or `hybrid_override_pattern` | Hard — needs new node type + subgraph |
| **Standard (non-gated) MLP** | Phi-2, Nemotron Dense (Audex-2B) | 3 projections (gate/up/down with SiLU/GELU gating) | 2 projections (fc1 → activation → fc2). No gating multiply. | Medium — needs conditional MLP rendering |

**Visual impact:** For Qwen3.5, 75% of layers are DeltaNet but we draw them as attention. The graph suggests a standard transformer when it's actually a hybrid. For Nemotron, Mamba blocks are invisible.

---

### HIGH — Attention Subgraph Misleading

The attention computation is drawn differently from how it actually works.

| Feature | Models Affected | What We Show | What's Real |
|---|---|---|---|
| **MLA (Multi-head Latent Attention)** | DeepSeek V4 Flash/Pro, GLM-5.2, Hy3, LongCat-2.0 | Standard Q/K/V/O projections (full rank) | Low-rank compression: Q via `q_lora_rank`, KV via `kv_lora_rank`, partial RoPE on `qk_rope_head_dim` only. Attention subgraph shows wrong weight shapes and missing compression steps. |
| **Partial RoPE** | Gemma 4, Nemotron, GLM-5.2 | RoPE applied to entire head_dim | Only `partial_rotary_factor` × head_dim dimensions get RoPE. Rest passes through unchanged. |
| **Sliding window attention** | Gemma 4, Qwen2.5, SmolLM3, others | Standard global attention | Alternating sliding (local) and global attention layers. Sliding layers only attend to nearby tokens. |

**Visual impact:** Attention subgraph weight shapes are wrong for MLA models (show [2048, 1024] instead of compressed [q_lora_rank, hidden_size]). For sliding window, we don't differentiate local vs global layers.

---

### MEDIUM — Components Silently Dropped

These exist in the model but are invisible in the visualization.

| Feature | Models Affected | Impact |
|---|---|---|
| **Vision encoder** | Gemma 4, Ornith, Kimi-VL, MiniMax-M3, Unlimited-OCR | Full vision tower (ViT) dropped. Model is multimodal but graph shows text-only. |
| **Audio encoder** | Gemma 4 E2B/E4B, Nemotron Audex | USM conformer encoder dropped. |
| **Per-Layer Embeddings (PLE)** | Gemma 4 E2B/E4B | Extra embedding table (dim=256) feeding each layer. Adds a residual signal not shown in graph. |
| **Shared KV Cache** | Gemma 4 E2B/E4B | Last N layers reuse KV from earlier layers. No KV projection in those layers — graph shows projections that don't exist. |
| **MTP (Multi-Token Prediction)** | Hy3, Qwen3.5, LongCat, GLM-5.2 | Extra prediction head layers after main decoder. Not shown in graph. |
| **Double-wide MLP** | Gemma 4 E2B | down_proj input is 2× intermediate_size. MLP subgraph shows standard width. |

---

### LOW — Config Field Mapping Bugs

These cause wrong values in specs panel or edge labels but don't affect graph structure.

| Config Field | Standard Name | Alternative Names Seen | Models | Impact |
|---|---|---|---|---|
| num_hidden_layers | `num_hidden_layers` | `num_layers` | LongCat | num_layers=1 (should be 38) |
| intermediate_size | `intermediate_size` | `ffn_hidden_size` | LongCat, GLM-4 | Wrong inter size |
| num_key_value_heads | `num_key_value_heads` | `multi_query_group_num` | GLM-4 | Claims MHA, actually MQA |
| vocab_size | `vocab_size` | `padded_vocab_size` | GLM-4 | vocab=0 in edge labels |
| num_experts | `num_experts` | `n_routed_experts`, `num_local_experts` | DeepSeek, MiniMax, Nemotron | MoE not detected |
| experts_per_tok | `num_experts_per_tok` | `moe_topk`, `top_k_experts` | DiffusionGemma, Hunyuan | Shows 0 experts/tok |
| shared experts | `n_shared_experts` | `num_shared_experts` (plural), `num_shared_expert` (singular), `shared_expert_intermediate_size` (implies 1) | Hy3, Ornith, Laguna, MiniMax | n_shared=0 (should be 1) |
| QK-Norm | model_type in set | `use_qk_norm: true`, `qk_norm: true` | Hy3, Hunyuan | QK-Norm nodes missing |
| norm_eps | `rms_norm_eps` | `layer_norm_eps`, `layernorm_epsilon`, `norm_eps` | Phi-2, GLM-4 | Wrong eps value |
| dtype | `torch_dtype` | `dtype` (nested) | Hy3 | Defaults to float32, should be bfloat16 |

---

## Model-by-Model Status

| Model | Graph Correct? | Params Correct? | Key Issues |
|---|---|---|---|
| Qwen3-0.6B/1.7B/4B | YES | YES | — |
| Qwen2.5-0.5B/1.5B | YES | YES | — |
| Phi-4 / Phi-4-mini | YES | YES | — |
| SmolLM-135M / SmolLM3 | YES | YES | — |
| OLMo-2-1B | YES | YES | — |
| MiniCPM5-1B | YES | YES | — |
| Nemotron-Nano-8B | YES | YES | — |
| Supra-Router-51M | YES | YES | — |
| DeepSeek-R1-Qwen3-8B | YES | YES | — |
| Gemma-4-E4B | YES | YES | PLE/shared KV in specs but graph OK |
| Hunyuan-A13B | YES | YES | — |
| GLM-5.2 | Partial | YES | MLA attention subgraph wrong |
| Kimi-K2 / K2.7 | Partial | YES | MLA attention subgraph wrong |
| Hy3 | Partial | Close (293B vs 295B) | QK-Norm nodes MISSING, MLA |
| DeepSeek V4 Flash/Pro | Partial | Overcounted (MLA) | MLA attention subgraph wrong |
| GigaChat-432B | YES | YES | — |
| Unlimited-OCR | YES | Close (2.9B vs 3B) | — |
| DiffusionGemma-26B | YES | Close (24.6B vs 26B) | — |
| Gemma-4-E2B | Partial | Wrong (1.6B vs 2.3B) | double_wide_mlp not counted |
| **Qwen3.5-4B** | **WRONG** | Wrong (3.7B vs 4B) | **75% layers are DeltaNet, not attention** |
| **AgentWorld-35B** | **WRONG** | Wrong (34B vs 35B) | **75% layers are DeltaNet** |
| **Ornith-9B/35B** | **WRONG** | Partial | **DeltaNet + multimodal vision dropped** |
| **Agents-A1** | **WRONG** | Partial | **DeltaNet + multimodal vision dropped** |
| **Nemotron Audex-30B** | **WRONG** | Wrong (2.7B vs 30B) | **Mamba hybrid + MoE not detected** |
| **Nemotron Puzzle-75B** | **WRONG** | Wrong (1.4B vs 75B) | **Mamba+MoE+Attention hybrid** |
| **MiniMax-M3** | Partial | Wrong (12.3B vs 428B) | **MoE not detected (`num_local_experts`)** |
| **LongCat-2.0** | **WRONG** | Wrong (3.8B vs 1.8T) | **Non-standard field names, MLA, MoE** |
| **Phi-2** | **WRONG** | Wrong (3.6B vs 2.8B) | **Standard MLP drawn as gated GeGLU** |
| **GLM-4-9B** | Partial | Wrong (10.7B vs 9.4B) | **Non-standard fields: vocab=0, MQA as MHA** |
| **Laguna-XS-2.1** | YES | Close (33.8B vs 33B) | Shared expert not counted |
| **Audex-2B** | Partial | Close (2.5B) | Standard MLP drawn as SwiGLU (uses ReLU²) |

---

## Checklist: Adding a New Model

Before generating a visualizer for a new model, check:

### Step 1: Fetch and Inspect config.json

```bash
curl -sL "https://huggingface.co/{model_id}/resolve/main/config.json" | python3 -m json.tool | head -50
```

### Step 2: Check for Non-Standard Fields

Look for these alternative field names and verify `generate_viz.py` handles them:

- [ ] `num_hidden_layers` — or is it `num_layers`? `layers`?
- [ ] `intermediate_size` — or `ffn_hidden_size`? `d_intermediate`?
- [ ] `vocab_size` — or `padded_vocab_size`?
- [ ] `num_key_value_heads` — or `multi_query_group_num`? `num_kv_groups`?
- [ ] Expert count — `num_experts`? `n_routed_experts`? `num_local_experts`?
- [ ] Shared experts — `n_shared_experts`? `num_shared_experts`? `shared_expert_intermediate_size` (implies 1)?
- [ ] QK-Norm — in `QK_NORM_TYPES` set? Or has `use_qk_norm`? Or `qk_norm`?
- [ ] `moe_intermediate_size` — is it an int or a list (per-layer)?
- [ ] RoPE theta — top-level `rope_theta`? Nested in `rope_parameters`? Dual RoPE?
- [ ] Layer types — has `layer_types`? `block_configs`? `hybrid_override_pattern`?

### Step 3: Check for Hybrid Architecture

If the config has ANY of these, the standard graph is **structurally wrong**:

- [ ] `layer_types` with values other than `"attention"` (e.g., `"sliding_attention"`, `"mamba"`, `"full_attention"`)
- [ ] `block_configs` with `block_type` values like `"mamba"`, `"moe"`, `"attention"`
- [ ] `hybrid_override_pattern` (Nemotron-H)
- [ ] `mlp_layer_types` or `use_mixed_mlp_moe` (Hunyuan)
- [ ] Model name contains "DeltaNet", "Mamba", "SSM", "Hybrid"
- [ ] `first_k_dense_replace` > 0 (some layers are dense, rest MoE)

If any checked: **Document in this file under "Known Issues" and add a warning note in the specs panel.**

### Step 4: Check for MLA (Latent Attention)

If config has `q_lora_rank`, `kv_lora_rank`, `qk_nope_head_dim`, `qk_rope_head_dim`:
- The attention subgraph is misleading (shows full Q/K/V/O instead of compressed)
- Param count is overestimated (attention params computed at full rank)
- **Document this in the model's specs**

### Step 5: Check for Multimodal

If config has `vision_config`, `audio_config`, `image_token_id`:
- Vision/audio encoders are dropped from the visualization
- Param count only includes text decoder
- **This is acceptable** — the visualizer focuses on the text decoder architecture

### Step 6: Verify Output

After generating:
```bash
python generate_viz.py {model_id}
```

1. Open the HTML and check the specs panel against the model card on HuggingFace
2. Compare `Total Params` with the model card's stated total (allow 5% tolerance)
3. Check if QK-Norm nodes appear in the graph when they should
4. If the model card mentions "DeltaNet", "Mamba", "hybrid", or "MLA" — add a note that the graph is simplified

### Step 7: Update This File

If you found a new issue, add it to the appropriate section above. If you fixed a bug in `generate_viz.py`, remove the entry from the issues list.

---

## How to Extend the Generator

### Add a new config field mapping

In `generate_viz.py`, `parse_config()`:

```python
# Example: add support for num_local_experts (MiniMax)
"is_moe": ... or (tc.get("num_local_experts", raw.get("num_local_experts", 0)) or 0) > 0,
"num_experts": ... or tc.get("num_local_experts", raw.get("num_local_experts", 0)) or 0,
```

### Add a new QK-Norm detection

```python
# In parse_config()
has_qk = mt_text in QK_NORM_TYPES or mt in QK_NORM_TYPES
if not has_qk:
    has_qk = tc.get("use_qk_norm", raw.get("use_qk_norm", False)) is True or \
             tc.get("qk_norm", raw.get("qk_norm", False)) is True
```

### Add DeltaNet/Mamba rendering (future)

This would require changes to `viz_template.html`:
1. Add `layer_types` to CFG
2. In `buildNodes()`, conditionally render "DeltaNet" or "Mamba" nodes instead of attention nodes based on layer type
3. In `getSubgraph()`, return different subgraphs for DeltaNet/Mamba nodes
4. In `buildEdges()`, route through the correct node types

This is a significant feature — estimated 200+ lines of template changes.

### Add MLA rendering (future)

Changes to attention subgraph in `viz_template.html`:
1. Detect `q_lora_rank` / `kv_lora_rank` in CFG
2. Show compression → latent → expansion steps instead of direct Q/K/V projections
3. Show partial RoPE on `qk_rope_head_dim` only
