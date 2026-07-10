#!/usr/bin/env python3
"""
Generate an interactive architecture visualizer HTML for any HuggingFace model.

Supports: Qwen2/Qwen3, Llama 2/3, Mistral, Gemma 2/3, Cohere, and similar
decoder-only transformers with RMSNorm + RoPE + GQA/SwiGLU or GeGLU.

Usage:
    python scripts/generate_viz.py Qwen/Qwen3-0.6B
    python scripts/generate_viz.py Qwen/Qwen3-1.7B -o qwen3_1_7b.html
    python scripts/generate_viz.py google/gemma-2-2b -o gemma2.html
    python scripts/generate_viz.py Qwen/Qwen2.5-0.5B
"""

import argparse
import json
import urllib.request
import sys
from pathlib import Path

QK_NORM_TYPES = {"qwen3", "qwen3_vl", "qwen3_5_text", "qwen3_moe", "gemma2", "gemma3", "gemma3n", "gemma4", "gemma4_text", "cohere", "command_a"}
NO_ROPE_TYPES = {"gpt2", "bert", "t5", "bart", "bloom"}
LAYER_NORM_TYPES = {"gpt2", "bert", "t5", "bart"}

ACTIVATION_MAP = {
    "silu": ("SwiGLU", "SiLU"),
    "swish": ("SwiGLU", "SiLU"),
    "gelu": ("GeGLU", "GELU"),
    "gelu_pytorch_tanh": ("GeGLU", "GELU"),
    "gelu_new": ("GeGLU", "GELU"),
    "relu": ("MLP", "ReLU"),
    "relu2": ("MLP", "ReLU\u00b2"),
}


def _scalar(v):
    """Convert list values (per-layer configs) to a single int. Takes max of non-zero values."""
    if isinstance(v, list):
        nums = [x for x in v if isinstance(x, (int, float)) and x > 0]
        return int(max(nums)) if nums else 0
    return int(v) if v else 0


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

    # Handle nested configs (Gemma 3/4, Llama 3.2 Vision, Qwen3-VL, etc.)
    tc = raw.get("text_config", raw)
    mt_text = tc.get("model_type", mt)

    H = tc.get("hidden_size", raw.get("hidden_size", 0))
    nh = tc.get("num_attention_heads", raw.get("num_attention_heads", 1))
    nkv = tc.get("num_key_value_heads", raw.get("num_key_value_heads", nh))
    hd = tc.get("head_dim", raw.get("head_dim", H // nh if nh else 64))
    inter = tc.get("intermediate_size", raw.get("intermediate_size", H * 4))
    hact = tc.get("hidden_activation", tc.get("hidden_act", raw.get("hidden_act", "silu")))
    mlp, act = ACTIVATION_MAP.get(hact, ("SwiGLU", hact.upper()))
    dt = tc.get("dtype", raw.get("dtype", raw.get("torch_dtype", "float32")))
    dt_bytes = {"bfloat16": 2, "float16": 2, "float32": 4}.get(dt, 2)

    # Detect features
    has_qk = mt_text in QK_NORM_TYPES or mt in QK_NORM_TYPES
    if not has_qk:
        has_qk = tc.get("use_qk_norm", raw.get("use_qk_norm", False)) is True
    has_rope = mt_text not in NO_ROPE_TYPES and mt not in NO_ROPE_TYPES
    norm_type = "layer" if mt_text in LAYER_NORM_TYPES else "rms"

    # MQA detection (num_kv_heads == 1)
    is_mqa = nkv == 1 and nh > 1
    is_gqa = nkv != nh and not is_mqa

    # Shared KV cache (Gemma 4)
    num_kv_shared = tc.get("num_kv_shared_layers", 0)

    # Per-Layer Embeddings (Gemma 3n/4)
    ple_dim = tc.get("hidden_size_per_layer_input", 0)

    # Dual head_dim (Gemma 4: separate for global attention)
    global_hd = tc.get("global_head_dim", 0)

    # Layer types (Gemma 4: alternating sliding/full)
    layer_types = tc.get("layer_types", [])

    # Logits softcapping
    logit_softcapping = tc.get("final_logit_softcapping", raw.get("final_logit_softcapping", 0))

    # Double-wide MLP (Gemma 4)
    double_wide_mlp = tc.get("use_double_wide_mlp", False)

    # Sliding window
    sw = tc.get("sliding_window", raw.get("sliding_window"))
    has_sliding = sw is not None

    # RoPE theta (may be dual in Gemma 4, or nested in rope_parameters)
    rope_params = tc.get("rope_parameters", raw.get("rope_parameters", {}))
    if isinstance(rope_params, dict):
        if "full_attention" in rope_params:
            # Dual RoPE (Gemma 4): take the full attention theta as primary
            rope_theta = rope_params.get("full_attention", {}).get("rope_theta",
                          rope_params.get("sliding_attention", {}).get("rope_theta", 10000))
        elif "rope_theta" in rope_params:
            # Single RoPE nested in rope_parameters (Nemotron, etc.)
            rope_theta = rope_params["rope_theta"]
        else:
            rope_theta = tc.get("rope_theta", raw.get("rope_theta", 10000))
    else:
        rope_theta = tc.get("rope_theta", raw.get("rope_theta", 10000))

    return {
        "model_id": model_id,
        "model_name": model_id.split("/")[-1],
        "model_type": mt,
        "text_model_type": mt_text,
        "hidden_size": H,
        "num_layers": tc.get("num_hidden_layers", raw.get("num_hidden_layers", 1)),
        "num_heads": nh,
        "num_kv_heads": nkv,
        "head_dim": hd,
        "global_head_dim": global_hd,
        "intermediate_size": inter,
        "vocab_size": tc.get("vocab_size", raw.get("vocab_size", 0)),
        "rope_theta": rope_theta,
        "norm_eps": tc.get("rms_norm_eps", raw.get("rms_norm_eps", 1e-6)),
        "tie_embeddings": tc.get("tie_word_embeddings", raw.get("tie_word_embeddings", False)),
        "attention_bias": tc.get("attention_bias", raw.get("attention_bias", mt_text in {"gpt2", "bert"})),
        "max_position_embeddings": tc.get("max_position_embeddings", raw.get("max_position_embeddings", 2048)),
        "dtype": dt,
        "hidden_act": hact,
        "has_qk_norm": has_qk,
        "has_rope": has_rope,
        "norm_type": norm_type,
        "norm_name": "LayerNorm" if norm_type == "layer" else "RMSNorm",
        "mlp_type": mlp,
        "act_name": act,
        "is_gqa": is_gqa,
        "is_mqa": is_mqa,
        "gqa_ratio": nh // nkv if nkv > 0 else 1,
        "has_sliding_window": has_sliding,
        "sliding_window": sw or 0,
        "has_logits_softcapping": logit_softcapping > 0,
        "logit_softcapping": logit_softcapping,
        "num_kv_shared_layers": num_kv_shared,
        "ple_dim": ple_dim,
        "double_wide_mlp": double_wide_mlp,
        "layer_types_summary": (f"{layer_types.count('sliding_attention')} sliding + "
                                f"{layer_types.count('full_attention')} global"
                                if layer_types else ""),
        "q_proj_out": nh * hd,
        "kv_proj_out": nkv * hd,
        "dtype_bytes": dt_bytes,
        "bytes_per_token": 2 * tc.get("num_hidden_layers", 1) * nkv * hd * dt_bytes,
        "is_moe": (tc.get("num_experts", raw.get("num_experts", 0)) or 0) > 0 or
                  (tc.get("n_routed_experts", raw.get("n_routed_experts", 0)) or 0) > 0,
        "num_experts": tc.get("num_experts", raw.get("num_experts", 0)) or
                       tc.get("n_routed_experts", raw.get("n_routed_experts", 0)) or 0,
        "num_experts_per_tok": _scalar(tc.get("num_experts_per_tok", raw.get("num_experts_per_tok", 0)) or
                                        tc.get("moe_topk", raw.get("moe_topk", 0)) or 0),
        "n_shared_experts": _scalar(tc.get("n_shared_experts", raw.get("n_shared_experts", 0)) or
                                    tc.get("num_shared_expert", raw.get("num_shared_expert", 0)) or 0),
        "moe_intermediate_size": _scalar(tc.get("moe_intermediate_size", raw.get("moe_intermediate_size", 0)) or 0),
        "first_k_dense_replace": tc.get("first_k_dense_replace", raw.get("first_k_dense_replace", 0)) or 0,
    }


def compute_params(cfg: dict) -> int:
    H = cfg["hidden_size"]
    embed = cfg["vocab_size"] * H
    attn = (cfg["q_proj_out"] + 2 * cfg["kv_proj_out"] + cfg["q_proj_out"]) * H
    if cfg["has_qk_norm"]:
        attn += 2 * cfg["head_dim"]
    norm = 2 * H

    if cfg.get("is_moe") and cfg.get("moe_intermediate_size", 0) > 0:
        dense_mlp = 3 * cfg["intermediate_size"] * H
        moe_inter = cfg["moe_intermediate_size"]
        n_experts = cfg["num_experts"]
        n_shared = cfg.get("n_shared_experts", 0)
        moe_mlp = (n_experts + n_shared) * 3 * moe_inter * H
        n_dense = cfg.get("first_k_dense_replace", 0)
        n_moe = cfg["num_layers"] - n_dense
        per_layer = attn + norm
        total = embed + n_dense * (per_layer + dense_mlp) + n_moe * (per_layer + moe_mlp) + H
    else:
        mlp = 3 * cfg["intermediate_size"] * H
        total = embed + cfg["num_layers"] * (attn + mlp + norm) + H

    if not cfg["tie_embeddings"]:
        total += embed
    return total


def fmt_params(n: int) -> str:
    if n >= 1e9: return f"{n/1e9:.1f}B"
    if n >= 1e6: return f"{n/1e6:.1f}M"
    return str(n)



def generate_specs(cfg, total_params):
    """Generate specs panel <li> items."""
    # Attention type label
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
    # Gemma 4 / Gemma 3n specific
    if cfg.get("layer_types_summary"):
        items.append(("Layer Types", cfg["layer_types_summary"], False))
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
    ap.add_argument("-o", "--output", default=None, help="Output file (default: viz/<name>_viz.html)")
    ap.add_argument("--subfolder", default="", help="Subfolder within repo for config.json (e.g. checkpoint_folder_textonly)")
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
    attn_type = "MQA" if cfg.get("is_mqa") else ("GQA" if cfg["is_gqa"] else "MHA")
    print(f"Generated: {out_path} ({len(html):,} bytes)")
    print(f"  Type: {cfg['model_type']} | Params: {fmt_params(total)} | "
          f"QK-Norm: {cfg['has_qk_norm']} | MLP: {cfg['mlp_type']} | "
          f"Attn: {attn_type}")


if __name__ == "__main__":
    main()
