"""
comfyui_workflow.py - Reference implementation of the ComfyUI node-graph executor.

WHAT IS COMFYUI? (start here if you have minimal ML background)
   A visual, node-based interface for image/video generation. Instead of writing a
   Python script that calls model -> encode -> sample -> decode -> save in order, you
   drag NODES onto a canvas and wire their output ports into other nodes' input
   ports. The result is a DAG (directed acyclic graph). ComfyUI saves it as a JSON
   file, topo-sorts it on load, and executes the nodes in dependency order. Each
   node is exactly ONE operation (load checkpoint, encode text, sample, decode,
   save). Edges are typed data (MODEL, CLIP, VAE, CONDITIONING, LATENT, IMAGE).

THE LINEAGE (old -> new, each step motivated by the prior's failure):

   1. MONOLITHIC SCRIPTS (the "default"): a single Python file that hard-codes the
      pipeline `pipe(prompt).images`. Problem: changing one step (swap sampler, add a
      ControlNet, chain an upscaler) means editing code, and you can't *see* the data
      flow. Sharing a setup means copy-pasting scripts.

   2. NODE-BASED / ComfyUI: every operation is a node with typed input/output ports.
      You connect them on a canvas; the layout is saved as workflow JSON. To change
      the pipeline you rewire nodes - no code edits. The graph is composable
      (mix any nodes), reusable (share the JSON), and visual.

   3. + API/EXECUTION FORMAT: the canvas saves a *graph* JSON (with x/y positions);
      the executor consumes a *prompt* JSON (node_id -> {class_type, inputs}) where
      each link is [source_node_id, output_slot_index]. This file models the prompt
      format - the exact thing the backend topo-sorts and runs.

   4. + INCREMENTAL EXECUTION: ComfyUI only re-runs nodes whose inputs changed. If
      you tweak the prompt text, only CLIPTextEncode + KSampler + VAEDecode +
      SaveImage re-run; the heavy CheckpointLoaderSimple result is cached. The topo
      order is recomputed, but cached outputs are reused.

   WHY IT MATTERS: a generation pipeline is a DAG. Expressing it as a graph (not a
   script) makes it reusable, composable, shareable, and incrementally executable.
   The JSON is portable - the same workflow runs on your laptop, a cloud GPU, or a
   headless API call.

THE NODE TYPES (a standard Stable Diffusion / Flux workflow):
   CheckpointLoaderSimple -> MODEL, CLIP, VAE   (loads one .safetensors, 3 outputs)
   CLIPTextEncode         -> CONDITIONING       (encodes prompt text via CLIP)
   EmptyLatentImage       -> LATENT             (start noise canvas, e.g. 512x512)
   KSampler               -> LATENT             (runs the diffusion loop, denoises)
   VAEDecode              -> IMAGE              (latent space -> pixel space)
   SaveImage              -> (writes PNG)       (final output to disk)

Companion code that COMFYUI_WORKFLOW.md is built from. Every number below is printed
by:
    python3 comfyui_workflow.py

This is PURE PYTHON STDLIB (only `json`). It faithfully models the prompt JSON
format, the DAG it implies, the topological sort, and a symbolic execution trace.
No torch, no models, no images - the *structure* is the concept.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque

BANNER = "=" * 72


# ============================================================================
# 1. The sample workflow (prompt / API-format JSON, exactly as ComfyUI runs it)
# ============================================================================

SAMPLE_WORKFLOW: dict = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
            "seed": 42,
            "steps": 20,
            "cfg": 8,
            "sampler": "euler",
            "scheduler": "normal",
        },
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "model.safetensors"},
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "beautiful landscape", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "blurry, bad", "clip": ["4", 1]},
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"images": ["8", 0]},
    },
}


# ============================================================================
# 2. Node output ports (what each class_type produces, by slot index)
# ============================================================================

# class_type -> list of output type names (slot 0, 1, 2, ...)
NODE_OUTPUTS: dict[str, list[str]] = {
    "CheckpointLoaderSimple": ["MODEL", "CLIP", "VAE"],
    "EmptyLatentImage":       ["LATENT"],
    "CLIPTextEncode":         ["CONDITIONING"],
    "KSampler":               ["LATENT"],
    "VAEDecode":              ["IMAGE"],
    "SaveImage":              ["(saved)"],
}

# the typed INPUT ports each class_type expects (for the inputs/outputs panel)
NODE_INPUT_TYPES: dict[str, list[str]] = {
    "CheckpointLoaderSimple": [],
    "EmptyLatentImage":       [],
    "CLIPTextEncode":         ["CLIP", "text"],
    "KSampler":               ["MODEL", "positive", "negative", "LATENT"],
    "VAEDecode":              ["LATENT", "VAE"],
    "SaveImage":              ["IMAGE"],
}


def is_link(value) -> bool:
    """A ComfyUI link is a 2-element list [node_id_str, slot_int]."""
    return (isinstance(value, list) and len(value) == 2
            and isinstance(value[0], str) and isinstance(value[1], int))


# ============================================================================
# 3. Workflow model: parse the prompt JSON into nodes + typed edges
# ============================================================================

class Workflow:
    """A parsed ComfyUI prompt-format workflow.

    Fields:
        nodes   - dict[str, dict]  node_id -> {class_type, inputs}
        edges   - list[(src_id, slot, dst_id, input_name)]  every dependency link
        indeg   - dict[str, int]  number of unresolved incoming links per node
        adj     - dict[str, list[str]]  src_id -> [consumer node ids]
    """

    def __init__(self, prompt: dict):
        self.nodes: dict[str, dict] = dict(prompt)
        self.edges: list[tuple[str, int, str, str]] = []
        self.indeg: dict[str, int] = {nid: 0 for nid in self.nodes}
        self.adj: dict[str, list[str]] = defaultdict(list)
        for nid, node in self.nodes.items():
            for iname, val in node["inputs"].items():
                if is_link(val):
                    src_id, slot = val[0], val[1]
                    self.edges.append((src_id, slot, nid, iname))
                    self.indeg[nid] += 1
                    self.adj[src_id].append(nid)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def distinct_source_ports(self) -> int:
        """Distinct (src_id, slot) output ports that are consumed. A port may fan
        out to several nodes (e.g. CLIP feeds both prompt encoders) but is one
        source point - so this is <= edge_count."""
        return len({(s, slot) for s, slot, _, _ in self.edges})

    def output_type(self, node_id: str, slot: int) -> str:
        ct = self.nodes[node_id]["class_type"]
        outs = NODE_OUTPUTS.get(ct, [])
        return outs[slot] if slot < len(outs) else f"slot{slot}"

    def topo_sort(self) -> list[str]:
        """Kahn's algorithm with a numeric tie-break on node id, so the order is
        deterministic and matches ComfyUI's stable execution order for this graph."""
        indeg = dict(self.indeg)
        ready = sorted([n for n in self.nodes if indeg[n] == 0], key=int)
        order: list[str] = []
        while ready:
            cur = ready.pop(0)
            order.append(cur)
            for nb in self.adj[cur]:
                indeg[nb] -= 1
                if indeg[nb] == 0:
                    ready.append(nb)
                    ready.sort(key=int)
        return order


# ============================================================================
# 4. Symbolic execution (no models - trace the data types flowing through)
# ============================================================================

def execute_node(wf: Workflow, node_id: str,
                 results: dict[str, list]) -> list[str]:
    """Produce symbolic output descriptions for one node, given its resolved inputs.
    This mirrors how ComfyUI dispatches class_type -> python callable, but instead of
    real tensors we emit short type+value strings so every value prints."""
    node = wf.nodes[node_id]
    ct = node["class_type"]
    ins = node["inputs"]

    if ct == "CheckpointLoaderSimple":
        name = ins["ckpt_name"]
        return [f"MODEL({name})", f"CLIP({name})", f"VAE({name})"]
    if ct == "EmptyLatentImage":
        w, h = ins["width"], ins["height"]
        return [f"LATENT({w}x{h} noise)"]
    if ct == "CLIPTextEncode":
        clip = results[ins["clip"][0]][ins["clip"][1]]
        return [f"COND({ins['text']!r} via {clip})"]
    if ct == "KSampler":
        model = results[ins["model"][0]][ins["model"][1]]
        pos = results[ins["positive"][0]][ins["positive"][1]]
        neg = results[ins["negative"][0]][ins["negative"][1]]
        lat = results[ins["latent_image"][0]][ins["latent_image"][1]]
        return [f"LATENT(denoised seed={ins['seed']} steps={ins['steps']})"]
    if ct == "VAEDecode":
        samples = results[ins["samples"][0]][ins["samples"][1]]
        vae = results[ins["vae"][0]][ins["vae"][1]]
        return [f"IMAGE(512x512x3 pixels)"]
    if ct == "SaveImage":
        return [f"SAVED(ComfyUI_00001_.png)"]
    return [f"UNKNOWN({ct})"]


# ============================================================================
# 5. pretty printer + check helper
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(label: str, cond: bool) -> bool:
    status = "OK" if cond else "FAIL"
    print(f"[check] {label}: {cond} -> {status}")
    return cond


# ============================================================================
# 6. SECTIONS  (the numbers that feed COMFYUI_WORKFLOW.md)
# ============================================================================

def section_a_parse_nodes():
    banner("SECTION A: parse the prompt JSON -> nodes")
    print("ComfyUI prompt format: a dict keyed by node id (string). Each value has")
    print("  class_type : the node's operation name (a registered Python class)")
    print("  inputs     : dict of input_name -> value OR link [src_id, slot]")
    print("A link [src_id, slot] means 'take output slot #slot of node src_id'.\n")

    wf = Workflow(SAMPLE_WORKFLOW)
    raw = json.dumps(SAMPLE_WORKFLOW, indent=2)
    print("prompt JSON (first node):")
    print("  " + json.dumps(SAMPLE_WORKFLOW["4"], separators=(",", ":")))
    print("  " + json.dumps(SAMPLE_WORKFLOW["6"], separators=(",", ":")))
    print()
    print("| node_id | class_type             | inputs (links marked *)              |")
    print("|---------|------------------------|--------------------------------------|")
    for nid in sorted(wf.nodes, key=int):
        node = wf.nodes[nid]
        parts = []
        for iname, val in sorted(node["inputs"].items()):
            if is_link(val):
                parts.append(f"{iname}*=[{val[0]},{val[1]}]")
            else:
                parts.append(f"{iname}={val!r}")
        print(f"| {nid:<7} | {node['class_type']:<22} | {', '.join(parts):<36} |")
    print()
    print("CheckpointLoaderSimple (node 4) has THREE output slots:")
    print("  slot 0 = MODEL   slot 1 = CLIP   slot 2 = VAE")
    check("parsed 7 nodes", wf.node_count == 7)


def section_b_build_dag():
    banner("SECTION B: build the DAG (every link is a directed edge)")
    wf = Workflow(SAMPLE_WORKFLOW)
    print("Walk every input; if it is a [src, slot] link, record a directed edge")
    print("src -> dst. The collection of edges IS the workflow's DAG.\n")
    print("| # | src_id | slot | -> | dst_id | input_name | source type |")
    print("|---|--------|------|----|--------|------------|-------------|")
    for i, (s, slot, d, iname) in enumerate(wf.edges, 1):
        print(f"| {i} | {s:<6} | {slot:<4} | -> | {d:<6} | {iname:<10} | "
              f"{wf.output_type(s, slot):<11} |")
    print()
    print(f"total dependency edges (wires):   {wf.edge_count}")
    print(f"distinct source output ports:     {wf.distinct_source_ports}")
    print("(CLIP slot 1 of node 4 fans out to nodes 6 AND 7 -> counted once as a")
    print(" source port, but twice as a dependency wire.)")
    check("edge_count == 9 (one wire per link)", wf.edge_count == 9)
    check("distinct source ports == 8", wf.distinct_source_ports == 8)


def section_c_topo_sort():
    banner("SECTION C: topological sort (Kahn's algorithm, numeric tie-break)")
    print("A node can only execute once ALL its input producers have executed.")
    print("Kahn's algorithm: emit zero-in-degree nodes, decrement consumers, repeat.")
    print("Tie-break by numeric node id so the order is deterministic.\n")

    wf = Workflow(SAMPLE_WORKFLOW)
    print("in-degree per node:")
    for nid in sorted(wf.nodes, key=int):
        print(f"  node {nid:<2} ({wf.nodes[nid]['class_type']:<22}) "
              f"in-degree = {wf.indeg[nid]}")
    print()
    order = wf.topo_sort()
    print("topo-sorted execution order:")
    for i, nid in enumerate(order, 1):
        ct = wf.nodes[nid]["class_type"]
        print(f"  {i}. node {nid} -> {ct}")
    print(f"\norder = {order}")
    check("topo order == ['4','5','6','7','3','8','9']", order == ["4","5","6","7","3","8","9"])
    # legal: every producer appears before every consumer
    pos = {n: i for i, n in enumerate(order)}
    legal = all(pos[s] < pos[d] for s, _, d, _ in wf.edges)
    check("order is a legal topological sort", legal)


def section_d_execute():
    banner("SECTION D: execute in topo order (symbolic trace)")
    print("Run graph_compute: for each node in topo order, read resolved inputs and")
    print("produce typed outputs. Real ComfyUI swaps each node for the actual model")
    print("op (load weights, run CLIP, denoise 20 steps, VAE decode, write PNG).\n")

    wf = Workflow(SAMPLE_WORKFLOW)
    order = wf.topo_sort()
    results: dict[str, list] = {}
    print("| step | node | class_type             | outputs                              |")
    print("|------|------|------------------------|--------------------------------------|")
    for i, nid in enumerate(order, 1):
        outs = execute_node(wf, nid, results)
        results[nid] = outs
        ct = wf.nodes[nid]["class_type"]
        print(f"| {i:<4} | {nid:<4} | {ct:<22} | {outs[0]:<36} |")
    print()
    print("Data flow summary (typed ports):")
    print("  node 4 CheckpointLoaderSimple -> MODEL[0], CLIP[1], VAE[2]")
    print("  node 5 EmptyLatentImage       -> LATENT[0]")
    print("  node 6 CLIPTextEncode(+)      -> CONDITIONING[0]   (reads CLIP[1] of 4)")
    print("  node 7 CLIPTextEncode(-)      -> CONDITIONING[0]   (reads CLIP[1] of 4)")
    print("  node 3 KSampler               -> LATENT[0]         (MODEL+pos+neg+noise)")
    print("  node 8 VAEDecode              -> IMAGE[0]          (LATENT+VAE)")
    print("  node 9 SaveImage              -> writes PNG        (IMAGE)")
    check("final node (9) is SaveImage", order[-1] == "9")
    check("KSampler (3) ran before VAEDecode (8)",
          order.index("3") < order.index("8"))


# ----------------------- THE GOLD CENTERPIECE --------------------------------

def section_gold():
    banner("SECTION G: GOLD trace (the centerpiece)")
    print("Full parse -> topo-sort -> execute on the canonical 7-node workflow.\n")

    wf = Workflow(SAMPLE_WORKFLOW)
    print(f"STEP 1  parse prompt JSON")
    print(f"        node_count = {wf.node_count}")
    print(f"        edge_count = {wf.edge_count}  (distinct source ports = "
          f"{wf.distinct_source_ports})")

    order = wf.topo_sort()
    print(f"STEP 2  topo_sort (Kahn, numeric tie-break)")
    print(f"        order = {order}")

    results: dict[str, list] = {}
    for nid in order:
        results[nid] = execute_node(wf, nid, results)
    print("STEP 3  execute (symbolic)")
    print("| order | node | class_type             | output[0]                            |")
    print("|-------|------|------------------------|--------------------------------------|")
    for i, nid in enumerate(order, 1):
        print(f"| {i:<5} | {nid:<4} | {wf.nodes[nid]['class_type']:<22} | "
              f"{results[nid][0]:<36} |")

    print(f"\nSTEP 4  result: {results['9'][0]}")

    # GOLD checks
    gold_nodes = wf.node_count == 7
    gold_order = order == ["4", "5", "6", "7", "3", "8", "9"]
    pos = {n: i for i, n in enumerate(order)}
    legal = all(pos[s] < pos[d] for s, _, d, _ in wf.edges)
    gold_edges = wf.edge_count == 9
    check("node_count == 7", gold_nodes)
    check("topo order == [4,5,6,7,3,8,9]", gold_order)
    check("topo order is legal", legal)
    check("edge_count == 9 (dependency wires)", gold_edges)

    print("\nGOLD (recomputed & badge-checked in comfyui_workflow.html):")
    print(f"  node_count   = {wf.node_count}")
    print(f"  edge_count   = {wf.edge_count}")
    print(f"  topo order   = {order}")
    print(f"  final output = {results['9'][0]}")
    return {"nodes": wf.node_count, "edges": wf.edge_count, "order": order,
            "legal": legal, "gold_ok": gold_nodes and gold_order and legal}


# ============================================================================
# main
# ============================================================================

def main():
    print("comfyui_workflow.py - reference impl. All numbers below feed COMFYUI_WORKFLOW.md.")
    print("pure Python stdlib (json only). Models the ComfyUI prompt-format DAG.")

    section_a_parse_nodes()
    section_b_build_dag()
    section_c_topo_sort()
    section_d_execute()
    gold = section_gold()

    banner("DONE - all sections printed; gold = " +
           ("OK" if gold["gold_ok"] else "FAIL"))


if __name__ == "__main__":
    main()
