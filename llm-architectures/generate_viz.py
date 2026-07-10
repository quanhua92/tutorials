#!/usr/bin/env python3
"""
Generate an interactive architecture visualizer HTML for any HuggingFace model.

Supports: Qwen2/Qwen3/3.5, Llama 2/3, Mistral, Gemma 2/3/4, DeepSeek V4,
Cohere, Phi, Nemotron, Kimi, Hy3, GLM, and 25+ other architecture types.

Usage:
    python generate_viz.py Qwen/Qwen3-0.6B
    python generate_viz.py google/gemma-4-E2B-it
    python generate_viz.py tencent/Hy3
    python generate_viz.py nvidia/Nemotron-Labs-Audex-2B --subfolder checkpoint_folder_textonly
"""

import argparse
import json
import urllib.request
import sys
from pathlib import Path

QK_NORM_TYPES = {
    "qwen3", "qwen3_vl", "qwen3_5_text", "qwen3_moe", "qwen3_5_moe",
    "gemma2", "gemma3", "gemma3n", "gemma4", "gemma4_text",
    "cohere", "command_a",
}
NO_ROPE_TYPES = {"gpt2", "bert", "t5", "bart", "bloom"}
LAYER_NORM_TYPES = {"gpt2", "bert", "t5", "bart"}

# Model types known to use standard (non-gated) MLP: fc1 -> activation -> fc2
# instead of gated: gate_proj + up_proj + down_proj
STANDARD_MLP_TYPES = {"phi", "gpt2", "bloom"}

ACTIVATION_MAP = {
    "silu": ("SwiGLU", "SiLU"),
    "swish": ("SwiGLU", "SiLU"),
    "gelu": ("GeGLU", "GELU"),
    "gelu_pytorch_tanh": ("GeGLU", "GELU"),
    "gelu_new": ("GeGLU", "GELU"),
    "gelu_python": ("GeGLU", "GELU"),
    "relu": ("MLP", "ReLU"),
    "relu2": ("MLP", "ReLU\u00b2"),
    "swigluoai": ("SwiGLU", "SwiGLU"),
}


def _scalar(v):
    """Convert list values (per-layer configs) to a single int. Takes max of non-zero values."""
    if isinstance(v, list):
        nums = [x for x in v if isinstance(x, (int, float)) and x > 0]
        return int(max(nums)) if nums else 0
    return int(v) if v else 0


def _first_nonzero(*keys, tc, raw):
    """Try multiple field names in order, return first non-zero value."""
    for k in keys:
        v = tc.get(k, raw.get(k))
        if v is not None and v != 0:
            return v
    return 0


def fetch_config(model_id: str, subfolder: str = "") -> dict:
    sf = f"/{subfolder}" if subfolder else ""
    url = f"https://huggingface.co/{model_id}/resolve/main{sf}/config.json"
    print(f"Fetching {url} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "generate_viz/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def parse_config(raw: dict, model_id: str) -> dict:
    mt = raw.get("model_type", "unknown")

    # Handle nested configs (Gemma 3/4, VL models, etc.)
    tc = raw.get("text_config", raw)
    # Some models nest under language_config (baidu/Unlimited-OCR)
    if not tc or tc is raw:
        tc = raw.get("language_config", raw)
    mt_text = tc.get("model_type", mt)

    # --- Core dimensions (with fallback field names) ---
    H = _first_nonzero("hidden_size", tc=tc, raw=raw)
    nh = _first_nonzero("num_attention_heads", "n_head", "num_heads", tc=tc, raw=raw) or 1
    nkv = (_first_nonzero("num_key_value_heads", "num_kv_heads", "multi_query_group_num",
                          "num_kv_groups", tc=tc, raw=raw) or nh)
    hd = (_first_nonzero("head_dim", "attention_head_dim", "qk_head_dim", "kv_channels",
                         tc=tc, raw=raw) or (H // nh if nh else 64))
    inter = (_first_nonzero("intermediate_size", "ffn_hidden_size", "d_intermediate",
                            tc=tc, raw=raw) or H * 4)
    vocab = (_first_nonzero("vocab_size", "padded_vocab_size", "org_vocab_size",
                            tc=tc, raw=raw) or 0)

    # --- Activation ---
    hact = (tc.get("hidden_activation", tc.get("hidden_act",
            raw.get("hidden_act", raw.get("hidden_activation", "silu")))))
    mlp_type, act_name = ACTIVATION_MAP.get(hact, ("SwiGLU", hact.upper() if hact else "SiLU"))
    is_gated_mlp = mlp_type in ("SwiGLU", "GeGLU")
    # Override: some model types always use standard (non-gated) MLP
    if mt_text in STANDARD_MLP_TYPES or mt in STANDARD_MLP_TYPES:
        mlp_type = "MLP"
        is_gated_mlp = False

    # --- Dtype ---
    dt = tc.get("dtype", raw.get("dtype", raw.get("torch_dtype", "bfloat16")))
    if dt not in ("bfloat16", "float16", "float32"):
        dt = "bfloat16"  # most common default
    dt_bytes = {"bfloat16": 2, "float16": 2, "float32": 4}.get(dt, 2)

    # --- QK-Norm detection ---
    has_qk = mt_text in QK_NORM_TYPES or mt in QK_NORM_TYPES
    if not has_qk:
        has_qk = (tc.get("use_qk_norm", raw.get("use_qk_norm", False)) is True or
                  tc.get("qk_norm", raw.get("qk_norm", False)) is True)

    # --- RoPE ---
    has_rope = mt_text not in NO_ROPE_TYPES and mt not in NO_ROPE_TYPES
    rope_params = tc.get("rope_parameters", raw.get("rope_parameters", {}))
    if isinstance(rope_params, dict):
        if "full_attention" in rope_params:
            rope_theta = rope_params.get("full_attention", {}).get("rope_theta",
                          rope_params.get("sliding_attention", {}).get("rope_theta", 10000))
        elif "rope_theta" in rope_params:
            rope_theta = rope_params["rope_theta"]
        else:
            rope_theta = _first_nonzero("rope_theta", tc=tc, raw=raw) or 10000
    else:
        rope_theta = _first_nonzero("rope_theta", tc=tc, raw=raw) or 10000

    # --- Norm type & eps ---
    norm_eps_val = (tc.get("rms_norm_eps", raw.get("rms_norm_eps", 0)) or
                    tc.get("layer_norm_eps", raw.get("layer_norm_eps", 0)) or
                    tc.get("layernorm_epsilon", raw.get("layernorm_epsilon", 0)) or
                    tc.get("norm_eps", raw.get("norm_eps", 0)) or 1e-6)
    has_layer_norm_key = any(
        tc.get(k, raw.get(k)) is not None
        for k in ("layer_norm_eps", "layernorm_epsilon")
    )
    norm_type = "layer" if (mt_text in LAYER_NORM_TYPES or has_layer_norm_key) else "rms"

    # --- Attention type ---
    is_mqa = nkv == 1 and nh > 1
    is_gqa = nkv != nh and not is_mqa

    # --- MLA detection (DeepSeek V4, GLM-5.2, etc.) ---
    has_mla = (tc.get("q_lora_rank", raw.get("q_lora_rank")) is not None or
               tc.get("kv_lora_rank", raw.get("kv_lora_rank")) is not None)

    # --- MoE detection (multiple field name conventions) ---
    num_experts = (_first_nonzero("num_experts", "n_routed_experts", "num_local_experts",
                                  tc=tc, raw=raw))
    is_moe = num_experts > 0

    experts_per_tok = _scalar(_first_nonzero(
        "num_experts_per_tok", "moe_topk", "top_k_experts", "moe_topk",
        tc=tc, raw=raw))

    # --- Shared experts (multiple field name conventions) ---
    n_shared = _scalar(_first_nonzero(
        "n_shared_experts", "num_shared_experts", "num_shared_expert",
        tc=tc, raw=raw))
    # shared_expert_intermediate_size implies at least 1 shared expert
    if n_shared == 0:
        sei = _first_nonzero("shared_expert_intermediate_size", tc=tc, raw=raw)
        if sei:
            n_shared = 1

    moe_inter = _scalar(_first_nonzero("moe_intermediate_size", "expert_ffn_hidden_size",
                                       tc=tc, raw=raw))
    first_k_dense = (_first_nonzero("first_k_dense_replace", "moe_layer_num_skipped",
                                    tc=tc, raw=raw) or 0)

    # --- Layers ---
    num_layers = (_first_nonzero("num_hidden_layers", "num_layers", "n_layers",
                                 tc=tc, raw=raw) or 1)

    # --- Hybrid layer detection ---
    layer_types_list = tc.get("layer_types", raw.get("layer_types", []))
    block_configs = tc.get("block_configs", raw.get("block_configs", []))
    hybrid_patterns = tc.get("hybrid_override_pattern", raw.get("hybrid_override_pattern"))
    has_deltanet = bool(layer_types_list) and any("deltanet" in str(l).lower() for l in layer_types_list)
    has_mamba = (bool(block_configs) and any(
        isinstance(b, dict) and b.get("block_type") == "mamba" for b in block_configs
    )) or (hybrid_patterns is not None)

    # --- Sliding window ---
    sw = tc.get("sliding_window", raw.get("sliding_window"))
    has_sliding = sw is not None

    # --- Logit softcapping ---
    logit_softcapping = tc.get("final_logit_softcapping", raw.get("final_logit_softcapping", 0))

    # --- Double-wide MLP (Gemma 4) ---
    double_wide_mlp = tc.get("use_double_wide_mlp", raw.get("use_double_wide_mlp", False))

    # --- Per-Layer Embeddings (Gemma 3n/4) ---
    ple_dim = tc.get("hidden_size_per_layer_input", raw.get("hidden_size_per_layer_input", 0))

    # --- Shared KV cache (Gemma 4) ---
    num_kv_shared = tc.get("num_kv_shared_layers", raw.get("num_kv_shared_layers", 0))

    # --- Global head_dim (Gemma 4) ---
    global_hd = _first_nonzero("global_head_dim", tc=tc, raw=raw)

    # --- Max position ---
    max_pos = (_first_nonzero("max_position_embeddings", "seq_length", "max_seq_len",
                              tc=tc, raw=raw) or 2048)

    # --- Layer types summary ---
    layer_types_summary = ""
    if layer_types_list:
        counts = {}
        for lt in layer_types_list:
            key = str(lt).replace("_attention", "")
            counts[key] = counts.get(key, 0) + 1
        layer_types_summary = " + ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    elif block_configs and isinstance(block_configs, list):
        counts = {}
        for b in block_configs:
            if isinstance(b, dict):
                bt = b.get("block_type", "unknown")
                counts[bt] = counts.get(bt, 0) + 1
        if counts:
            layer_types_summary = " + ".join(f"{v} {k}" for k, v in sorted(counts.items()))

    return {
        "model_id": model_id,
        "model_name": model_id.split("/")[-1],
        "model_type": mt,
        "text_model_type": mt_text,
        "hidden_size": H,
        "num_layers": num_layers,
        "num_heads": nh,
        "num_kv_heads": nkv,
        "head_dim": hd,
        "global_head_dim": global_hd,
        "intermediate_size": inter,
        "vocab_size": vocab,
        "rope_theta": rope_theta,
        "norm_eps": norm_eps_val,
        "tie_embeddings": tc.get("tie_word_embeddings", raw.get("tie_word_embeddings", False)),
        "attention_bias": bool(tc.get("attention_bias", raw.get("attention_bias",
                         tc.get("add_qkv_bias", raw.get("add_qkv_bias",
                         tc.get("add_bias_linear", raw.get("add_bias_linear", mt_text in {"gpt2", "bert"}))))))),
        "max_position_embeddings": max_pos,
        "dtype": dt,
        "hidden_act": hact,
        "has_qk_norm": has_qk,
        "has_rope": has_rope,
        "norm_type": norm_type,
        "norm_name": "LayerNorm" if norm_type == "layer" else "RMSNorm",
        "mlp_type": mlp_type,
        "act_name": act_name,
        "is_gated_mlp": is_gated_mlp,
        "is_gqa": is_gqa,
        "is_mqa": is_mqa,
        "gqa_ratio": nh // nkv if nkv > 0 else 1,
        "has_mla": has_mla,
        "has_sliding_window": has_sliding,
        "sliding_window": sw or 0,
        "has_logits_softcapping": logit_softcapping > 0,
        "logit_softcapping": logit_softcapping,
        "num_kv_shared_layers": num_kv_shared,
        "ple_dim": ple_dim,
        "double_wide_mlp": double_wide_mlp,
        "layer_types_summary": layer_types_summary,
        "has_deltanet": has_deltanet,
        "has_mamba": has_mamba,
        "q_proj_out": nh * hd,
        "kv_proj_out": nkv * hd,
        "dtype_bytes": dt_bytes,
        "bytes_per_token": 2 * num_layers * nkv * hd * dt_bytes,
        "is_moe": is_moe,
        "num_experts": num_experts,
        "num_experts_per_tok": experts_per_tok,
        "n_shared_experts": n_shared,
        "moe_intermediate_size": moe_inter,
        "first_k_dense_replace": first_k_dense,
    }


def compute_params(cfg: dict) -> int:
    H = cfg["hidden_size"]
    V = cfg["vocab_size"]
    embed = V * H
    attn = 2 * cfg["q_proj_out"] * H + 2 * cfg["kv_proj_out"] * H
    if cfg["has_qk_norm"]:
        attn += 2 * cfg["head_dim"]
    norm = 2 * H

    inter = cfg["intermediate_size"]
    is_gated = cfg.get("is_gated_mlp", True)
    dw = cfg.get("double_wide_mlp", False)

    # Dense MLP params per layer
    if is_gated:
        # gate(H->inter) + up(H->inter) + down(inter->H) or down(2*inter->H)
        dense_mlp = (2 + (2 if dw else 1)) * inter * H
    else:
        # Standard: fc1(H->inter) + fc2(inter->H)
        dense_mlp = 2 * inter * H

    if cfg.get("is_moe") and cfg.get("moe_intermediate_size", 0) > 0:
        moe_inter = cfg["moe_intermediate_size"]
        n_experts = cfg["num_experts"]
        n_shared = cfg.get("n_shared_experts", 0)
        if is_gated:
            moe_mlp = (2 + (2 if dw else 1)) * moe_inter * H
        else:
            moe_mlp = 2 * moe_inter * H
        total_moe_mlp = (n_experts + n_shared) * moe_mlp
        n_dense = cfg.get("first_k_dense_replace", 0)
        n_moe = max(0, cfg["num_layers"] - n_dense)
        per_layer = attn + norm
        total = embed + n_dense * (per_layer + dense_mlp) + n_moe * (per_layer + total_moe_mlp) + H
    else:
        total = embed + cfg["num_layers"] * (attn + dense_mlp + norm) + H

    if not cfg["tie_embeddings"]:
        total += embed
    return total


def fmt_params(n: int) -> str:
    if n >= 1e9: return f"{n/1e9:.1f}B"
    if n >= 1e6: return f"{n/1e6:.1f}M"
    return str(n)


def generate_specs(cfg, total_params):
    """Generate specs panel <li> items."""
    if cfg.get("is_mqa"):
        attn_label = f"MQA ({cfg['num_heads']} Q, 1 KV)"
    elif cfg["is_gqa"]:
        attn_label = f"GQA ({cfg['num_heads']} Q, {cfg['num_kv_heads']} KV)"
    else:
        attn_label = f"MHA ({cfg['num_heads']} heads)"

    items = [
        ("Model ID", cfg["model_id"], False),
        ("Model Type", cfg["model_type"], False),
        ("Total Params", f"{total_params:,} ({fmt_params(total_params)})", False),
        ("Hidden Size", str(cfg["hidden_size"]), False),
        ("Layers", str(cfg["num_layers"]), False),
        ("Attention", attn_label, False),
        ("Head Dimension", str(cfg["head_dim"]), True),
        ("FFN Intermediate", str(cfg["intermediate_size"]), True),
        ("Vocab Size", f"{cfg['vocab_size']:,}", True),
        ("QK-Norm", "Yes (per-head)" if cfg["has_qk_norm"] else "No", True),
        ("Activation", f"{cfg['mlp_type']} ({cfg['act_name']})", False),
        ("Pos. Encoding",
         f"RoPE (theta={cfg['rope_theta']:,.0f})" if cfg["has_rope"] else "Learned", False),
        (f"{cfg['norm_name']} Eps", str(cfg["norm_eps"]), False),
        ("Weight Tying", str(cfg["tie_embeddings"]).lower(), False),
        ("Attention Bias", str(cfg["attention_bias"]).lower(), False),
        ("Max Context", f"{cfg['max_position_embeddings']:,}", False),
        ("Dtype", cfg["dtype"], False),
        ("KV Cache/Token", f"{cfg['bytes_per_token']:,} B ({cfg['bytes_per_token']//1024} KiB)", False),
    ]
    # Architecture-specific
    if cfg.get("has_mla"):
        items.append(("Attention", "MLA (latent)", False))
    if cfg.get("layer_types_summary"):
        items.append(("Layer Types", cfg["layer_types_summary"], False))
    if cfg.get("has_deltanet"):
        items.append(("DeltaNet Layers", "Yes (hybrid)", False))
    if cfg.get("has_mamba"):
        items.append(("Mamba Layers", "Yes (hybrid)", False))
    if cfg.get("num_kv_shared_layers", 0) > 0:
        items.append(("Shared KV Layers", str(cfg["num_kv_shared_layers"]), False))
    if cfg.get("ple_dim", 0) > 0:
        items.append(("Per-Layer Embed", str(cfg["ple_dim"]), False))
    if cfg.get("global_head_dim", 0) > 0:
        items.append(("Global Head Dim", str(cfg["global_head_dim"]), False))
    if cfg.get("double_wide_mlp"):
        items.append(("Double-Wide MLP", "true", False))
    if cfg.get("is_moe"):
        items.append(("MoE Experts", str(cfg["num_experts"]), True))
        items.append(("Experts/Tok", str(cfg["num_experts_per_tok"]), False))
        if cfg.get("n_shared_experts", 0) > 0:
            items.append(("Shared Experts", str(cfg["n_shared_experts"]), False))
    if cfg["has_sliding_window"]:
        items.append(("Sliding Window", str(cfg["sliding_window"]), False))
    if cfg["has_logits_softcapping"]:
        items.append(("Logits Softcap", str(cfg.get("logit_softcapping", 0)), False))

    lines = []
    for label, val, hl in items:
        cls = "text-emerald-400 font-bold" if hl else "text-slate-200"
        lines.append(
            f'                        <li class="flex justify-between items-center">'
            f'<span class="text-slate-400">{label}</span> '
            f'<span class="font-mono {cls}">{val}</span></li>'
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Generate architecture visualizer HTML")
    ap.add_argument("model_id", help="HuggingFace model ID (e.g. Qwen/Qwen3-0.6B)")
    ap.add_argument("-o", "--output", default=None, help="Output file path")
    ap.add_argument("--subfolder", default="", help="Subfolder for config.json")
    args = ap.parse_args()

    raw = fetch_config(args.model_id, args.subfolder)
    cfg = parse_config(raw, args.model_id)
    total = compute_params(cfg)

    out_dir = Path(__file__).resolve().parent
    out_dir.mkdir(exist_ok=True)
    default_name = args.model_id.replace("/", "_") + "_viz.html"
    out_path = Path(args.output) if args.output else out_dir / default_name

    specs = generate_specs(cfg, total)
    cfg_json = json.dumps(cfg)

    tpl_path = Path(__file__).resolve().parent / "viz_template.html"
    html = tpl_path.read_text()
    html = (html
            .replace("__SPECS__", specs)
            .replace("__CFG__", cfg_json)
            .replace("__TITLE__", f"{cfg['model_name']} Architecture Visualizer")
            .replace("__MODEL_NAME__", cfg["model_name"]))

    out_path.write_text(html)
    attn_type = "MLA" if cfg.get("has_mla") else ("MQA" if cfg.get("is_mqa") else ("GQA" if cfg["is_gqa"] else "MHA"))
    extra = ""
    if cfg.get("has_deltanet"): extra += " DeltaNet"
    if cfg.get("has_mamba"): extra += " Mamba"
    if cfg.get("double_wide_mlp"): extra += " DW-MLP"
    print(f"Generated: {out_path} ({len(html):,} bytes)")
    print(f"  Type: {cfg['model_type']} | Params: {fmt_params(total)} | "
          f"QK-Norm: {cfg['has_qk_norm']} | MLP: {cfg['mlp_type']} | "
          f"Attn: {attn_type}{extra}")

    # --- Config coverage report ---
    unrecognized = _find_unrecognized_fields(raw)
    if unrecognized:
        # Highlight fields that look architecturally important
        important_keywords = ("moe", "expert", "delta", "mamba", "lora", "norm",
                              "rope", "attention", "layer", "hybrid", "block",
                              "embed", "shared", "sparse", "kv", "head")
        important = [f for f in unrecognized if any(kw in f.lower() for kw in important_keywords)]
        other = [f for f in unrecognized if f not in important]
        if important:
            print(f"  \u26a0\ufe0f  Unrecognized fields (may affect accuracy):")
            for f in sorted(important):
                v = _get_nested(raw, f)
                vstr = str(v)[:60] if v is not None else "?"
                print(f"      {f} = {vstr}")
        if other:
            print(f"  Other unrecognized fields: {', '.join(sorted(other)[:15])}")
            if len(other) > 15:
                print(f"      ... and {len(other)-15} more")


KNOWN_FIELDS = {
    # Identity & metadata
    "model_type", "architectures", "auto_map", "torch_dtype", "dtype",
    "transformers_version", "model_name", "description", "_name_or_path",
    "default_checkpoint_folder", "checkpoint_folders",
    # Core dimensions
    "hidden_size", "num_hidden_layers", "num_attention_heads",
    "num_key_value_heads", "head_dim", "intermediate_size", "vocab_size",
    "max_position_embeddings", "initializer_range",
    # Alternative names we handle
    "num_layers", "n_layers", "n_head", "num_kv_heads",
    "multi_query_group_num", "num_kv_groups",
    "ffn_hidden_size", "d_intermediate", "padded_vocab_size", "org_vocab_size",
    "attention_head_dim", "qk_head_dim", "seq_length", "max_seq_len",
    # Activation
    "hidden_act", "hidden_activation",
    # Attention
    "attention_bias", "attention_dropout", "mlp_bias",
    "q_lora_rank", "kv_lora_rank", "qk_nope_head_dim", "qk_rope_head_dim",
    "v_head_dim", "o_lora_rank", "index_head_dim", "index_n_heads",
    "attention_k_eq_v", "attention_logit_cap", "attention_invalid_logits_value",
    "attention_chunk_size", "attention_context_left", "attention_context_right",
    # RoPE
    "rope_theta", "rope_scaling", "rope_parameters", "rope_interleave",
    "partial_rotary_factor", "use_rotary_pos_emb", "rope_ratio",
    # QK-Norm
    "use_qk_norm", "qk_norm",
    # Norm
    "rms_norm_eps", "layer_norm_eps", "layernorm_epsilon", "norm_eps", "norm_type",
    # Embeddings & tokens
    "tie_word_embeddings", "bos_token_id", "eos_token_id", "pad_token_id",
    "eod_token_id",
    # MoE
    "num_experts", "n_routed_experts", "num_local_experts",
    "num_experts_per_tok", "moe_topk", "top_k_experts",
    "n_shared_experts", "num_shared_experts", "num_shared_expert",
    "shared_expert_intermediate_size",
    "moe_intermediate_size", "expert_ffn_hidden_size",
    "first_k_dense_replace", "moe_layer_num_skipped",
    "moe_drop_tokens", "moe_random_routing_dropped_token",
    "moe_router_dtype", "moe_layer_freq", "norm_topk_prob",
    "routed_scaling_factor", "scoring_func", "topk_method", "topk_group",
    "n_group", "ep_size", "pretraining_tp", "group_limited_greedy",
    "use_mixed_mlp_moe", "enable_moe_block", "expert_intermediate_size",
    "num_global_key_value_heads",
    # Sliding window
    "sliding_window", "use_sliding_window", "max_window_layers",
    # Gemma
    "use_double_wide_mlp", "hidden_size_per_layer_input",
    "num_kv_shared_layers", "global_head_dim",
    "final_logit_softcapping", "use_clipped_linears",
    "layer_types", "vocab_size_per_layer_input",
    "standardize", "default_output_length", "pooling_kernel_size", "patch_size",
    "output_proj_dims", "residual_weight", "position_embedding_size",
    # Hybrid
    "block_configs", "hybrid_override_pattern", "mlp_layer_types",
    "dense_list", "cla_share_factor", "use_cla",
    "use_bidirectional_attention",
    # ChatGLM / Megatron-style fields
    "add_qkv_bias", "add_bias_linear", "kv_channels",
    "multi_query_attention", "rmsnorm", "post_layer_norm",
    "apply_query_key_layer_scaling", "original_rope",
    "apply_residual_connection_post_layernorm", "attention_softmax_in_fp32",
    "attn_implementation", "bias_dropout_fusion", "fp32_residual_connection",
    "embd_pdrop", "resid_pdrop", "num_heads",
    # Nested configs
    "text_config", "vision_config", "audio_config", "language_config",
    # MTP
    "num_nextn_predict_layers", "mtp_num_hidden_layers",
    "index_share_for_mtp_iteration", "index_skip_topk_offset",
    "index_topk", "index_topk_freq", "index_topk_pattern",
    "indexer_rope_interleave", "indexer_types",
    # Multimodal tokens
    "image_token_id", "video_token_id", "audio_token_id",
    "boi_token_id", "eoi_token_id", "boa_token_id", "eoa_token_id",
    "im_start_id", "im_end_id", "im_newline_id",
    "text_start_id", "text_end_id", "video_start_id", "video_end_id",
    "mask_init_id", "vit_token", "num_media_embeds",
    # Position
    "position_embedding_xdrope", "xdrope_section", "use_mrope", "use_cache",
    # Vision/audio extras
    "anyres_pooling_size", "anyres_vit_max_image_size", "anyres_vit_two_views",
    "vit_input_resolution", "vit_patch", "vit_type", "vit_path",
    "vit_norm_type", "vit_remove_prenorm", "vit_mapping_type",
    "vit_add_patchemb_bias", "vit_used_rms_norm",
    "audio_encoder_hidden_size", "audio_model_type", "audio_preprocessor_path",
    "audio_projector_activation", "audio_projector_intermediate_size",
    "audio_projector_norm_eps",
    "conv_kernel_size", "subsampling_conv_channels", "expand", "hidden_dropout",
    "add_classification_head", "class_num", "skip_cls_token",
    "vision_soft_tokens_per_image",
    # Misc framework
    "output_attentions", "output_hidden_states",
    "chunk_size_feed_forward", "is_encoder_decoder",
    "problem_type", "id2label", "label2id",
    "hidden_act", "hidden_activation",
}


def _find_unrecognized_fields(raw):
    """Find config fields not in KNOWN_FIELDS. Searches top-level + text_config."""
    seen = set()
    # Top-level keys
    for k in raw:
        if k not in KNOWN_FIELDS and not k.startswith("_"):
            seen.add(k)
    # text_config / language_config keys
    for nested_key in ("text_config", "language_config"):
        nested = raw.get(nested_key, {})
        if isinstance(nested, dict):
            for k in nested:
                if k not in KNOWN_FIELDS and not k.startswith("_"):
                    seen.add(k)
    return sorted(seen)


def _get_nested(raw, field):
    """Try to get a field value from top-level or nested configs."""
    if field in raw:
        return raw[field]
    for nested_key in ("text_config", "language_config"):
        nested = raw.get(nested_key, {})
        if isinstance(nested, dict) and field in nested:
            return nested[field]
    return None


if __name__ == "__main__":
    main()
