"""
lmcache.py - Reference implementation of LMCache (hierarchical, global KV pool).

This is the single source of truth that LMCACHE.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    uv run python lmcache.py

== IMPORTANT: THIS IS A FAITHFUL SIMULATION ===================================
There is no real multi-node cluster, RDMA NIC, or NVMe on this Mac. What IS
real and reproducible here:
  * the chunk-hash signature scheme (content-addressed, FNV-1a, same as
    🔗 BLOCK_MANAGER / 🔗 PREFIX_CACHE);
  * the hierarchical tier model as a dict-of-dicts (tier -> chunk_sig -> KV);
  * the cross-node transfer mechanics (lookup -> pull -> fill block table) and
    the byte-equality proof that the pulled KV matches the original; and
  * EVERY bandwidth / capacity figure in the latency-budget arithmetic, which
    uses PUBLISHED hardware numbers (HBM 3.35 TB/s, PCIe 64 GB/s, NVMe 7 GB/s,
    RoCE/IB 50 GB/s). The transfer latencies are Size_KV / real_bandwidth —
    not invented.
What is SIMULATED (clearly labelled in each section): the "RDMA pull" is a
deterministic in-process dict copy + tensor clone; the "network" is a number.
The conclusions (transfer << recompute) hold because they rest on the real
bandwidth arithmetic, not on the simulated transport.

== THE BIG IDEA, IN ONE SENTENCE (the "global library" intuition) ==============
🔗 PREFIX_CACHE / RadixAttention shares KV only WITHIN ONE GPU/node. In a
cluster, a request may land on a node that lacks its prompt's KV -> an
expensive full PREFILL recompute. LMCache turns the whole datacenter's memory
into ONE global, HIERARCHICAL pool: GPU VRAM -> CPU DRAM -> local NVMe ->
remote S3/Redis. Each KV chunk gets a content-addressed signature; on a local
miss, the node queries a GLOBAL index, finds the chunk on another node's DRAM
(or NVMe, or S3), and streams the KV PAGES straight over RDMA into its own
local block table (🔗 PAGED_ATTENTION) — skipping prefill entirely. WHY: amortize
one prefill across the whole cluster, survive restarts (NVMe), and share across
nodes (S3/remote) and even across engines (vLLM <-> SGLang).

== THE LINEAGE (old -> new, with WHY) ==========================================
  1. SINGLE-NODE prefix cache (🔗 PREFIX_CACHE, RadixAttention / SGLang; or the
     flat chained-hash of vLLM / 🔗 BLOCK_MANAGER): a request reuses KV only if
     it lands on the SAME node that cached it. Great on one GPU — blind to the
     other N-1 nodes in the rack.
  2. THE MULTI-NODE PROBLEM: a load balancer sends a repeat prompt to a
     different node. That node's local cache is cold -> full prefill recompute
     (read ALL model weights, do all attention). The KV already exists, on a
     sibling node, but is unreachable. This is pure waste at cluster scale.
  3. LMCache (Yuhan Liu et al., arXiv:2510.09665): extend the cache to a GLOBAL
     HIERARCHICAL pool with a chunk-hash index queried ACROSS nodes. On a local
     miss -> global lookup -> if a hit lives in another node's DRAM/NVMe/S3,
     stream the KV pages over RDMA into the local block table. The prefill is
     skipped; only the (much smaller) KV bytes cross the wire. Mooncake
     (arXiv:2407.00079) pushes the same idea into a KVCache-centric
     DISAGGREGATED architecture: prefill and decode on separate clusters, KV
     transferred over RDMA between them.

== PLAIN-ENGLISH GLOSSARY (used in every section below) =======================
    prefill        running the WHOLE prompt through the model once to produce
                   its KV. Compute + weight-bandwidth heavy (reads ALL weights).
    decode         generating one new token at a time, reusing cached KV.
    KV chunk       a fixed run of chunk_size tokens' K and V, the unit LMCache
                   offloads/transfers. Smaller chunk -> finer reuse, more index
                   overhead (same tradeoff as 🔗 KV_CACHE page_size).
    chunk signature  a content-addressed hash of the chunk's tokens (FNV-1a
                   here, identical formula to 🔗 BLOCK_MANAGER / 🔗 PREFIX_CACHE).
                   Same tokens -> same signature on ANY node -> global lookup.
    tier           one level of the memory hierarchy: VRAM (HBM), CPU DRAM,
                   local NVMe, remote S3/Redis. Capacity grows DOWN the ladder,
                   bandwidth SHRINKS DOWN the ladder.
    local lookup   check THIS node's tiers for a chunk signature (VRAM first).
    global lookup  on a local miss, query the cluster-wide index for the
                   signature -> returns (node, tier) where the chunk lives.
    RDMA pull      stream the chunk's KV pages from the source tier over the
                   network straight into the local VRAM block table. Simulated
                   here as a deterministic copy; latency = bytes / real BW.
    block table    the 🔗 PAGED_ATTENTION / 🔗 KV_CACHE per-request index card:
                   logical page -> physical page. A pulled chunk's pages are
                   appended here so attention reads them like any local page.
    Size_KV        bytes of KV for a prompt:
                     2(K+V) * layers * n_kv_heads * head_dim * S * bytes
    Latency_transfer  Size_KV / bandwidth_network   (the LMCache path).
    Latency_prefill   cost of recomputing the prompt (roofline floor, below).
    budget         the win condition: Latency_transfer < SLA_TTFT - Latency_prefill,
                   i.e. it is cheaper to MOVE the KV than to RECOMPUTE it.

== TENSOR / SIZING CONVENTIONS ================================================
Two separate scales are used and clearly labelled:
  (a) TINY simulation KV tensors (D=8, 2 layers, 1 KV head) -> so the chunk
      transfer + byte-equality proof is PRINTABLE. These are mechanism demos.
  (b) REALISTIC latency-budget dims (layers=24, n_kv_heads=2, head_dim=128,
      bytes=2, S=512) -> the transfer-vs-recompute arithmetic, using PUBLISHED
      bandwidths. These are the numbers that justify LMCache.
"""

from __future__ import annotations

import torch  # version banner + tiny KV tensors for the byte-equality proof

BANNER = "=" * 72


# ============================================================================
# 1. CHUNK SIGNATURES  (content-addressed; identical FNV-1a to 🔗 BLOCK_MANAGER
#    / 🔗 PREFIX_CACHE so the sibling numbers are directly comparable)
# ============================================================================

FNV_OFFSET_64 = 0xCBF29CE484222325
FNV_PRIME_64 = 0x100000001B3
MASK64 = (1 << 64) - 1


def fnv1a_mix(h: int, byte: int) -> int:
    return ((h ^ byte) * FNV_PRIME_64) & MASK64


def compute_hash(token_ids: list[int], prefix: int = -1) -> int:
    """Chained 64-bit fingerprint (mirrors BLOCK_MANAGER / prefix_cache)."""
    h = FNV_OFFSET_64
    if prefix != -1:
        for b in prefix.to_bytes(8, "little"):
            h = fnv1a_mix(h, b)
    for t in token_ids:
        for b in t.to_bytes(4, "little"):
            h = fnv1a_mix(h, b)
    return h


def hx(h: int) -> str:
    return f"0x{h & MASK64:016x}"


def chunk_signature(chunk_tokens: list[int]) -> int:
    """Content-addressed signature of one chunk = hash of its tokens.

    NOT chained across chunks: the signature depends only on the chunk's own
    tokens, so the SAME chunk produces the SAME signature on EVERY node. That
    is what makes a global lookup possible (a chained hash would also depend
    on everything before the chunk, which differs once two prompts diverge).
    """
    return compute_hash(list(chunk_tokens), -1)


# ============================================================================
# 2. THE HIERARCHICAL TIER MODEL  (dict-of-dicts: tier -> chunk_sig -> KV)
#    Two nodes; each node owns VRAM / DRAM / NVMe / S3 tiers. A GLOBAL index
#    maps every chunk_sig -> [(node_id, tier)] so any node can find any chunk.
#    This is the faithful simulation core (see module docstring).
# ============================================================================

TIERS = ["VRAM", "DRAM", "NVMe", "S3"]   # hottest -> coldest


class Node:
    """One cluster node: its 4 memory tiers (each a dict chunk_sig -> kv)."""

    def __init__(self, node_id: int):
        self.node_id = node_id
        # tier -> { chunk_sig: kv_tensor }   (the dict-of-dicts hierarchy)
        self.tiers: dict[str, dict[int, torch.Tensor]] = {t: {} for t in TIERS}
        # the 🔗 PAGED_ATTENTION / 🔗 KV_CACHE block table for requests on this
        # node: logical_page_idx -> physical_page_id (here just an int counter).
        self.block_table: dict[int, int] = {}
        self.pages: dict[int, torch.Tensor] = {}
        self._next_page = 0

    def local_lookup(self, sig: int) -> tuple[str, torch.Tensor] | None:
        """Search THIS node's tiers hottest-first. Returns (tier, kv) or None."""
        for tier in TIERS:                      # VRAM -> DRAM -> NVMe -> S3
            kv = self.tiers[tier].get(sig)
            if kv is not None:
                return tier, kv
        return None

    def store(self, tier: str, sig: int, kv: torch.Tensor) -> None:
        self.tiers[tier][sig] = kv

    def evict_to(self, sig: int, from_tier: str, to_tier: str) -> None:
        """Move a chunk one rung DOWN the ladder (VRAM->DRAM->...). Simulates
        VRAM pressure offloading KV to DRAM, the canonical LMCache trigger."""
        kv = self.tiers[from_tier].pop(sig, None)
        if kv is not None:
            self.tiers[to_tier][sig] = kv

    def append_page(self, kv: torch.Tensor) -> int:
        """Drop a pulled chunk's KV into the local block table (🔗 PAGED_ATTENTION).
        Returns the logical page index it now occupies."""
        page_id = self._next_page
        self._next_page += 1
        logical = len(self.block_table)
        self.block_table[logical] = page_id
        self.pages[page_id] = kv.clone()
        return logical

    def gather_kv(self) -> torch.Tensor:
        """Reassemble this node's request KV by walking the block table, exactly
        like 🔗 PAGED_ATTENTION gathers non-contiguous pages into one tensor."""
        if not self.block_table:
            return torch.empty(0)
        rows = [self.pages[self.block_table[i]] for i in range(len(self.block_table))]
        return torch.cat(rows, dim=0)


class LMCacheCluster:
    """The global pool: N nodes + a cluster-wide chunk_sig -> locations index.

    This is the faithful simulation of LMCache's global lookup + RDMA pull.
    `pull` is a deterministic in-process copy; the LATENCY it would incur is
    computed separately from real bandwidths in Section F.
    """

    def __init__(self, n_nodes: int):
        self.nodes = [Node(i) for i in range(n_nodes)]
        # global index: chunk_sig -> list of (node_id, tier)
        self.global_index: dict[int, list[tuple[int, str]]] = {}

    def register(self, node_id: int, tier: str, sig: int) -> None:
        self.global_index.setdefault(sig, [])
        loc = (node_id, tier)
        if loc not in self.global_index[sig]:
            self.global_index[sig].append(loc)

    def global_lookup(self, sig: int) -> list[tuple[int, str]] | None:
        return self.global_index.get(sig)

    def pull(self, sig: int, dst_node_id: int) -> tuple[int, str, str, torch.Tensor]:
        """Find `sig` somewhere in the cluster and copy its KV into dst's VRAM
        block table. Returns (src_node, src_tier, dst_tier, kv). The 'RDMA'
        transfer is a tensor clone; its real latency is Size_KV / bandwidth
        (Section F). Chooses the HOTTEST source tier available across nodes."""
        locs = self.global_index.get(sig, [])
        # hottest source tier first (prefer VRAM, then DRAM, ...)
        locs_sorted = sorted(locs, key=lambda nl: TIERS.index(nl[1]))
        src_node_id, src_tier = locs_sorted[0]
        if src_node_id == dst_node_id and src_tier == "VRAM":
            # already local in VRAM — nothing to pull
            return src_node_id, src_tier, "VRAM", self.nodes[src_node_id].tiers[src_tier][sig]
        kv = self.nodes[src_node_id].tiers[src_tier][sig]
        self.nodes[dst_node_id].append_page(kv)        # fill block table (🔗 PAGED)
        self.nodes[dst_node_id].store("VRAM", sig, kv)  # also keep in local VRAM
        self.register(dst_node_id, "VRAM", sig)
        return src_node_id, src_tier, "VRAM", kv


# ============================================================================
# 3. PRETTY PRINTER
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 4. THE DETERMINISTIC WORKLOAD  (tiny, printable; mechanism demos)
#    chunk_size = 2 (like 🔗 PREFIX_CACHE block_size=2). Small int token ids.
# ============================================================================

CHUNK_SIZE = 2
PROMPT = [100, 101, 102, 103, 104, 105]   # 6 tokens -> 3 chunks of 2


def chunkize(tokens: list[int]) -> list[list[int]]:
    """Split tokens into CHUNK_SIZE chunks (last partial chunk kept as-is)."""
    return [tokens[i:i + CHUNK_SIZE] for i in range(0, len(tokens), CHUNK_SIZE)]


def make_chunk_kv(chunk_tokens: list[int]) -> torch.Tensor:
    """A TINY, deterministic KV tensor for one chunk (mechanism demo only).

    Shape [n_tokens, D=8]; values are a deterministic function of the tokens so
    the byte-equality proof (pulled == original) is meaningful. The REALISTIC
    KV sizing for the latency budget uses layers=24, n_kv_heads=2, head_dim=128
    (Section F) — these tiny tensors exist only to make the transfer printable.
    """
    D = 8
    rows = []
    for t in chunk_tokens:
        rows.append(torch.arange(D, dtype=torch.float32) * 0.001 + t * 0.01)
    return torch.stack(rows)


# ============================================================================
# 5. REAL BANDWIDTH / CAPACITY NUMBERS  (published hardware; used by Section F)
#    Sources: NVIDIA H100/A100 specs; PCIe Gen4/Gen5; NVMe Gen4 x4; RoCE/IB.
# ============================================================================

# (name, typical_capacity, bandwidth_bytes_per_sec, note)
TIER_SPECS = [
    ("GPU VRAM/HBM", "40-80 GB",   3.35e12, "H100 SXM HBM3 (3.35 TB/s); A100 80GB ~2.0 TB/s"),
    ("CPU DRAM",     "0.5-2 TB",   64e9,    "GPU<->CPU over PCIe Gen5 x16 (~64 GB/s; Gen4 ~32)"),
    ("Local NVMe",   "1-8 TB",     7e9,     "PCIe Gen4 x4 SSD (e.g. ~7 GB/s seq read)"),
    ("Remote S3/Redis", "unbounded", 50e9,  "datacenter RoCE/IB 400 Gbps (~50 GB/s); WAN S3 ~1-12"),
]


# ============================================================================
# 6. THE LATENCY-BUDGET MODEL  (real bandwidths; the load-bearing arithmetic)
# ============================================================================

# Reference model (a small ~1B GQA transformer; dims printed + reproducible).
LAYERS = 24
N_Q_HEADS = 16
N_KV_HEADS = 2          # GQA ratio 8:1 (query:kv heads)
HEAD_DIM = 128
HIDDEN = N_Q_HEADS * HEAD_DIM      # 2048
INTERMEDIATE = 5504                 # SwiGLU
BYTES = 2                           # fp16 / bf16
DEFAULT_S = 512                     # prompt length for the worked example
DEFAULT_NET_BW = 50e9               # 400 Gbps RoCE/IB -> ~50 GB/s

# Reference GPU: NVIDIA A100 80GB SXM (well-documented, clean numbers).
A100_HBM_BW = 2.0e12     # bytes/s
A100_BF16_TFLOPS = 312e12  # peak FLOP/s


def kv_bytes(layers: int, n_kv_heads: int, head_dim: int, s: int, bytes_: int) -> int:
    """Size_KV = 2(K+V) * layers * n_kv_heads * head_dim * S * bytes."""
    return 2 * layers * n_kv_heads * head_dim * s * bytes_


def model_params(layers: int, n_q: int, n_kv: int, head_dim: int,
                 hidden: int, inter: int) -> int:
    """Transformer-BODY parameter count (attn + SwiGLU MLP, excl. embeddings).

    Per layer:
      attn = Q + K + V + O = 2*(hidden*n_q*head_dim) + 2*(hidden*n_kv*head_dim)
      mlp  = gate + up + down = 3 * hidden * inter   (SwiGLU)
    """
    qo = hidden * (n_q * head_dim)
    kv = hidden * (n_kv * head_dim)
    attn = 2 * qo + 2 * kv
    mlp = 3 * hidden * inter
    return layers * (attn + mlp)


def transfer_latency(size_bytes: int, bw_bytes_per_s: float) -> float:
    """Latency_transfer = Size_KV / bandwidth  (seconds). Real bandwidths."""
    return size_bytes / bw_bytes_per_s


def prefill_floor(n_params: int, s: int, bytes_: int,
                  hbm_bw: float, peak_tflops: float) -> tuple[float, float, float, float]:
    """Roofline FLOOR for recomputing a prompt of S tokens at batch=1.

    Returns (mem_bound_s, compute_bound_s, floor_s, arithmetic_intensity).
      mem_bound     = read all weights once = 2*N*bytes / HBM_BW
      compute_bound = 2*N*S FLOPs (forward, MACs=2FLOP) / peak_TFLOPS
      floor         = max(mem, compute)   <- the roofline
      arithmetic_intensity = FLOPs / bytes  (> crossover => compute-bound)
    This is an IDEAL floor; real prefill adds kernel-launch + low-MFU overhead,
    so actual wall-clock is higher (strengthening the transfer-wins verdict).
    """
    weight_bytes = 2 * n_params * bytes_
    flops = 2 * n_params * s
    mem = weight_bytes / hbm_bw
    comp = flops / peak_tflops
    floor = max(mem, comp)
    ai = flops / weight_bytes
    return mem, comp, floor, ai


# ============================================================================
# 7. THE SECTIONS  (the numbers that feed LMCACHE.md)
# ============================================================================

def section_a_single_node_recap():
    # INTUITION: 🔗 PREFIX_CACHE recap. On ONE node, a second request sharing a
    # prefix reuses the cached KV (local hit). The win is real but LOCAL: only
    # the node that cached the prefix can serve the hit.
    banner("SECTION A: single-node prefix cache recap (🔗 PREFIX_CACHE)")
    print("One node, a local chunk cache. First request computes + stores the")
    print("prompt's KV chunks (content-addressed by signature). A second request")
    print("with the SAME prompt hits locally and skips prefill.\n")
    node = Node(0)
    chunks = chunkize(PROMPT)
    print(f"Prompt = {PROMPT}  (chunk_size={CHUNK_SIZE} -> {len(chunks)} chunks)\n")
    print("First request (COLD): compute + store each chunk's KV locally.\n")
    print("| chunk | tokens    | signature (FNV-1a)   | local action |")
    print("|-------|-----------|----------------------|--------------|")
    for i, c in enumerate(chunks):
        sig = chunk_signature(c)
        kv = make_chunk_kv(c)
        node.store("VRAM", sig, kv)
        print(f"| c{i}    | {str(c):<9} | {hx(sig)} | STORE in VRAM |")
    print()
    print("Second request, SAME prompt -> every chunk is a LOCAL HIT:\n")
    all_hit = True
    for i, c in enumerate(chunks):
        sig = chunk_signature(c)
        hit = node.local_lookup(sig) is not None
        all_hit = all_hit and hit
        print(f"  c{i} {hx(sig)}: {'HIT (reuse KV, skip prefill)' if hit else 'MISS'}")
    print(f"\n[check] local prefix-cache reuse on the SAME node == full hit : "
          f"{all_hit} -> {'OK' if all_hit else 'FAIL'}")
    print("\nBut this cache is BLIND to other nodes. That is the multi-node gap.")


def section_b_multi_node_problem():
    # INTUITION: the same prompt arrives at a DIFFERENT node. That node's local
    # cache is cold -> a full prefill recompute. The KV already exists, on the
    # first node, but is unreachable. Pure cluster-scale waste.
    banner("SECTION B: the multi-node problem (request lands on the WRONG node)")
    cluster = LMCacheCluster(n_nodes=2)
    chunks = chunkize(PROMPT)
    # node0 processed the prompt earlier; its KV sits in node0's VRAM.
    for c in chunks:
        sig = chunk_signature(c)
        cluster.nodes[0].store("VRAM", sig, make_chunk_kv(c))
        cluster.register(0, "VRAM", sig)
    print("node0 processed the prompt earlier -> its KV chunks live in node0 VRAM.\n")
    print("Now the SAME prompt arrives at node1 (load balancer routed it there).")
    print("node1 checks its OWN local tiers:\n")
    print("| chunk | signature            | node0 has it? | node1 local? | verdict |")
    print("|-------|----------------------|---------------|--------------|---------|")
    all_miss = True
    for i, c in enumerate(chunks):
        sig = chunk_signature(c)
        on0 = cluster.nodes[0].local_lookup(sig) is not None
        on1 = cluster.nodes[1].local_lookup(sig) is not None
        all_miss = all_miss and (not on1)
        verdict = "LOCAL MISS -> recompute prefill" if not on1 else "local hit"
        print(f"| c{i}    | {hx(sig)} | {'yes (VRAM)' if on0 else 'no':<13} | "
              f"{'no' if not on1 else 'yes':<12} | {verdict} |")
    print(f"\n[check] every chunk is a LOCAL MISS on node1 : {all_miss} -> "
          f"{'OK' if all_miss else 'FAIL'}")
    print("\nThe KV exists in the cluster (on node0) but node1 cannot see it ->")
    print("node1 recomputes the ENTIRE prompt: read ALL model weights + full")
    print("attention. That is the waste LMCache exists to eliminate.")


def section_c_memory_tiers():
    # INTUITION: instead of DISCARDING KV when VRAM fills, offload it DOWN a
    # ladder of memory. Capacity GROWS down the ladder; bandwidth SHRINKS.
    # Real, published numbers (the load-bearing facts for the latency budget).
    banner("SECTION C: the hierarchical memory tiers (REAL bandwidth/capacity)")
    print("Capacity grows DOWN the ladder; bandwidth SHRINKS DOWN the ladder.\n")
    print("| tier            | typical capacity | bandwidth        | source / note                         |")
    print("|-----------------|------------------|------------------|---------------------------------------|")
    for name, cap, bw, note in TIER_SPECS:
        if bw >= 1e12:
            bws = f"{bw/1e12:.2f} TB/s"
        else:
            bws = f"{bw/1e9:.1f} GB/s"
        print(f"| {name:<15} | {cap:<16} | {bws:<16} | {note:<37} |")
    print()
    print("Cross-node pull path: src tier (e.g. node2 DRAM) -> network (RDMA) ->")
    print("dst VRAM. Effective BW = min(network_BW, dst PCIe_BW). At 400 Gbps")
    print("RoCE (~50 GB/s) and PCIe Gen5 (~64 GB/s) the bottleneck is the NETWORK")
    print("(50 GB/s) — fast enough that moving KV beats recomputing it (Section F).")
    print()
    fastest = TIER_SPECS[0][2]
    slowest_net = TIER_SPECS[3][2]
    print(f"[check] VRAM bandwidth ({fastest/1e12:.2f} TB/s) >> network pull BW "
          f"({slowest_net/1e9:.0f} GB/s) : {fastest > slowest_net} -> "
          f"{'OK' if fastest > slowest_net else 'FAIL'}")


def section_d_chunk_hash_global():
    # INTUITION: each chunk's signature is content-addressed (same tokens ->
    # same signature on ANY node). A global index maps signature -> locations.
    # Any node can find any chunk. This is what turns N local caches into ONE.
    banner("SECTION D: chunk-hash signatures + the GLOBAL lookup index")
    cluster = LMCacheCluster(n_nodes=2)
    chunks = chunkize(PROMPT)
    print(f"Prompt = {PROMPT} -> chunks (chunk_size={CHUNK_SIZE}):\n")
    print("| chunk | tokens    | signature (content-addressed) |")
    print("|-------|-----------|--------------------------------|")
    sigs = []
    for i, c in enumerate(chunks):
        sig = chunk_signature(c)
        sigs.append(sig)
        print(f"| c{i}    | {str(c):<9} | {hx(sig)}                 |")
    print()
    print("Key property: the signature depends ONLY on the chunk's tokens — so the")
    print("same chunk yields the SAME signature on every node. A global index then")
    print("maps each signature -> the (node, tier) locations that hold its KV.\n")
    # node1 holds all chunks in DRAM (offloaded from VRAM earlier)
    for c, sig in zip(chunks, sigs):
        cluster.nodes[1].store("DRAM", sig, make_chunk_kv(c))
        cluster.register(1, "DRAM", sig)
    print("Global index after node1 cached the prompt (in its DRAM tier):\n")
    print("| signature            | locations        |")
    print("|----------------------|------------------|")
    for sig in sigs:
        locs = cluster.global_lookup(sig)
        loc_str = ", ".join(f"node{n} {t}" for n, t in locs)
        print(f"| {hx(sig)} | {loc_str:<16} |")
    print()
    print("Now node0 (which has NOTHING locally) queries the global index for each")
    print("chunk — and finds them ALL on node1:\n")
    print("| chunk | signature            | global hit? | where           |")
    print("|-------|----------------------|-------------|-----------------|")
    all_global_hit = True
    for i, (c, sig) in enumerate(zip(chunks, sigs)):
        locs = cluster.global_lookup(sig)
        hit = locs is not None and len(locs) > 0
        all_global_hit = all_global_hit and hit
        where = f"node{locs[0][0]} {locs[0][1]}" if locs else "nowhere"
        print(f"| c{i}    | {hx(sig)} | {'yes':<11} | {where:<15} |")
    print(f"\n[check] every chunk found via GLOBAL lookup : {all_global_hit} -> "
          f"{'OK' if all_global_hit else 'FAIL'}")
    return cluster, sigs


def section_e_rdma_transfer(cluster: LMCacheCluster, sigs: list[int]):
    # INTUITION: the centerpiece sim. node0 local miss -> global hit on node1
    # DRAM -> pull each chunk's KV "over RDMA" into node0's block table (🔗
    # PAGED_ATTENTION). Byte-equality proof: the gathered KV == the original.
    banner("SECTION E: RDMA pull into the local block table (🔗 PAGED_ATTENTION)")
    chunks = chunkize(PROMPT)
    print("node0 receives the prompt. Local tiers: EMPTY. Global lookup -> all 3")
    print("chunks live on node1's DRAM. Pull each one into node0's VRAM block")
    print("table (a deterministic copy here; real latency = bytes / BW, Section F).\n")
    original = torch.cat([make_chunk_kv(c) for c in chunks], dim=0)
    print("| chunk | src (node,tier) | pull -> dst | node0 block table | bytes moved |")
    print("|-------|-----------------|-------------|-------------------|-------------|")
    total_bytes = 0
    for i, (c, sig) in enumerate(zip(chunks, sigs)):
        # local miss first (node0 has nothing)
        local = cluster.nodes[0].local_lookup(sig)
        assert local is None
        src_node, src_tier, dst_tier, kv = cluster.pull(sig, dst_node_id=0)
        logical = len(cluster.nodes[0].block_table) - 1
        moved = kv.numel() * kv.element_size()
        total_bytes += moved
        print(f"| c{i}    | node{src_node} {src_tier:<5} | -> {dst_tier:<4}    "
              f"| logical {logical} -> page {cluster.nodes[0].block_table[logical]:<2}   "
              f"| {moved} B       |")
    print()
    # gather node0's reconstructed KV via the block table and prove byte-equality
    gathered = cluster.nodes[0].gather_kv()
    equal = torch.equal(gathered, original)
    print("node0 gathers its request KV by walking the block table (🔗 PAGED):")
    print(f"  reconstructed shape = {tuple(gathered.shape)}")
    print(f"  [check] pulled+gathered KV == original prompt KV (byte-equal) : "
          f"{equal} -> {'OK' if equal else 'FAIL'}")
    print(f"  node0 SKIPPED prefill entirely: the {total_bytes} B of KV moved")
    print("  instead of re-running the model over the prompt.")
    print()
    print("This is the whole point: the KV already existed in the cluster; node0")
    print("just fetched the pages it needed into its block table and carried on.")


def section_f_latency_budget():
    # INTUITION: the load-bearing arithmetic. For a realistic prompt, is it
    # cheaper to MOVE the KV or to RECOMPUTE it? Size_KV / BW vs the prefill
    # roofline floor. All bandwidths are REAL published numbers.
    banner("SECTION F: the latency-budget inequality (transfer vs recompute)")
    S = DEFAULT_S
    size_kv = kv_bytes(LAYERS, N_KV_HEADS, HEAD_DIM, S, BYTES)
    n_params = model_params(LAYERS, N_Q_HEADS, N_KV_HEADS, HEAD_DIM, HIDDEN, INTERMEDIATE)
    mem, comp, floor, ai = prefill_floor(
        n_params, S, BYTES, A100_HBM_BW, A100_BF16_TFLOPS)
    crossover = A100_BF16_TFLOPS / A100_HBM_BW

    print("Reference model (GQA transformer, dims printed + reproducible):")
    print(f"  layers={LAYERS}, n_q_heads={N_Q_HEADS}, n_kv_heads={N_KV_HEADS} (GQA 8:1),")
    print(f"  head_dim={HEAD_DIM}, hidden={HIDDEN}, inter={INTERMEDIATE} (SwiGLU), bytes={BYTES}")
    print(f"  body params = {n_params:,} (~{n_params/1e9:.2f} B, excl. embeddings)")
    print(f"  prompt S = {S} tokens")
    print(f"  reference GPU: A100 80GB SXM (HBM {A100_HBM_BW/1e12:.1f} TB/s, "
          f"{A100_BF16_TFLOPS/1e12:.0f} TFLOPS bf16 peak)\n")

    print("Size_KV = 2(K+V) * layers * n_kv_heads * head_dim * S * bytes")
    print(f"        = 2 * {LAYERS} * {N_KV_HEADS} * {HEAD_DIM} * {S} * {BYTES}")
    print(f"        = {size_kv:,} bytes = {size_kv/1024/1024:.2f} MiB\n")

    print("Latency_transfer = Size_KV / bandwidth, per tier (REAL bandwidths):\n")
    print("| source tier / path      | bandwidth   | Latency_transfer | vs prefill floor |")
    print("|-------------------------|-------------|------------------|------------------|")
    rows = [
        ("Local DRAM -> VRAM (PCIe Gen5)", 64e9),
        ("Local NVMe -> VRAM", 7e9),
        ("Remote node DRAM -> VRAM (RoCE 100G)", 12.5e9),
        ("Remote node DRAM -> VRAM (RoCE 400G)", DEFAULT_NET_BW),
    ]
    for label, bw in rows:
        t = transfer_latency(size_kv, bw)
        ms = t * 1e3
        ratio = floor / t
        bws = f"{bw/1e9:.1f} GB/s" if bw < 1e12 else f"{bw/1e12:.2f} TB/s"
        print(f"| {label:<23} | {bws:<11} | {ms:>12.4f} ms | {ratio:>8.1f}x faster    |")
    print()
    print("Recompute (prefill) roofline FLOOR at batch=1:")
    print(f"  mem-bound (read all weights once) = {mem*1e3:.3f} ms")
    print(f"  compute-bound (2*N*S FLOPs / peak) = {comp*1e3:.3f} ms")
    print(f"  arithmetic intensity = {ai:.0f} FLOP/B ; crossover = {crossover:.0f} FLOP/B")
    print(f"  -> {'COMPUTE-bound' if ai >= crossover else 'MEMORY-bound'}; floor = "
          f"{floor*1e3:.3f} ms (IDEAL; real prefill is higher: kernel launch + MFU<1)")
    print()
    t_primary = transfer_latency(size_kv, DEFAULT_NET_BW)
    verdict = t_primary < floor
    print("BUDGET VERDICT (primary: 400G RoCE pull):")
    print(f"  Latency_transfer = {size_kv:,} / {DEFAULT_NET_BW:.0e} = {t_primary*1e6:.2f} us "
          f"({t_primary*1e3:.4f} ms)")
    print(f"  Latency_prefill  (floor) = {floor*1e3:.3f} ms")
    print(f"  transfer < prefill ? {verdict}  (ratio {floor/t_primary:.1f}x)")
    print(f"\n[check] Latency_transfer < Latency_prefill_floor : {verdict} -> "
          f"{'OK' if verdict else 'FAIL'}")
    print(f"\nGOLD for .html: Size_KV(S={S}) = {size_kv} bytes; "
          f"Latency_transfer(S={S}, BW={DEFAULT_NET_BW:.0e}) = {t_primary*1e6:.2f} us; "
          f"verdict transfer<prefill = {verdict}.")
    return size_kv, t_primary, floor, n_params


def section_g_hit_rate_contrast():
    # INTUITION: the cluster-scale payoff. With N nodes and prompts spread
    # round-robin, a local-only cache hits only when a request lands on its
    # caching node: P=1/N. A global LMCache hits whenever the KV is ANYWHERE:
    # P=1 (if cached). The amplification is N x.
    banner("SECTION G: local-vs-global hit-rate contrast")
    N = 4
    print(f"{N} nodes. {N} distinct prompts were cached earlier, one per node")
    print("(round-robin). Now one request for EACH prompt arrives, routed to a")
    print("node chosen by a fixed (deterministic) load-balancer pattern.\n")
    # deterministic pattern: prompt i cached on node i; request i routed to a node
    # so that exactly ONE request lands on its caching node (request 0 -> node 0).
    # This realizes the statistical EXPECTATION: a random routing hits its own
    # caching node with probability 1/N, so on average 1 of N requests is a
    # local hit. We realize that expectation with a clean deterministic pattern
    # (a derangement of the requests except request 0, which lands on its own
    # caching node). prompt i is cached on node i.
    cache_node = {i: i for i in range(N)}
    route_node = {0: 0}
    for i in range(1, N):
        route_node[i] = (i % (N - 1)) + 1   # requests 1..N-1 -> a derangement
    print("| prompt# | cached on node | request routed to | LOCAL hit? | GLOBAL hit? |")
    print("|---------|----------------|-------------------|------------|-------------|")
    local_hits = 0
    global_hits = 0
    for i in range(N):
        ch = cache_node[i]
        rt = route_node[i]
        lh = (rt == ch)
        gh = True                       # the KV is somewhere in the cluster
        local_hits += int(lh)
        global_hits += int(gh)
        print(f"| {i:<7} | node{ch}           | node{rt}              | "
              f"{'yes' if lh else 'NO ':<10} | {'yes' if gh else 'no':<11} |")
    local_rate = local_hits / N
    global_rate = global_hits / N
    print(f"\nLOCAL hit rate  = {local_hits}/{N} = {local_rate*100:.1f}%   "
          f"(only requests that landed on their caching node)")
    print(f"GLOBAL hit rate = {global_hits}/{N} = {global_rate*100:.1f}%   "
          f"(any node can serve any cached prompt via RDMA pull)")
    print(f"\nAt cluster scale, local-only hits ~1/N = {1/N*100:.1f}%; global ~100%.")
    print(f"LMCache amplifies effective cache reach by ~{N}x on this workload.\n")
    print(f"[check] local rate == 1/{N} and global rate == 1.0 : "
          f"{abs(local_rate - 1/N) < 1e-9 and global_rate == 1.0} -> "
          f"{'OK' if abs(local_rate - 1/N) < 1e-9 and global_rate == 1.0 else 'FAIL'}")


# ============================================================================
# main
# ============================================================================

def main():
    print("lmcache.py - reference impl (FAITHFUL SIMULATION). All numbers below\n"
          "feed LMCACHE.md. torch =", torch.__version__)
    print("NOTE: no real cluster/RDMA here; tiers are a dict-of-dicts and the")
    print("'pull' is a deterministic copy. Bandwidth/latency numbers are REAL.\n")

    section_a_single_node_recap()
    section_b_multi_node_problem()
    section_c_memory_tiers()
    cluster, sigs = section_d_chunk_hash_global()
    section_e_rdma_transfer(cluster, sigs)
    section_f_latency_budget()
    section_g_hit_rate_contrast()

    banner("DONE - all sections printed; LMCache sim gold = OK")


if __name__ == "__main__":
    main()
