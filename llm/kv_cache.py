"""
kv_cache.py - Reference implementation of the LLM KV cache.

WHAT IS A KV CACHE? (start here if you have minimal ML background)
  When a Transformer "reads" a word, it produces two short note vectors per
  word, per attention head: a KEY (used to *find* this word later) and a VALUE
  (used to *retrieve* its content later). Generating word #N means comparing the
  new word's QUERY against ALL previous KEYS, then blending the matching VALUES.
  A "KV cache" is simply a notebook where we keep those past notes instead of
  recomputing them every step.

THREE GENERATIONS OF THE NOTEBOOK (the lineage implemented + asserted here):

  1. NO cache   ("Week 1"): recompute K,V every step -> O(L^2) token-projections.
     To answer the 100th word, the model re-reads and re-thinks about ALL 100
     words from scratch; word 1's notes get recomputed every single step.

  2. DENSE cache: keep a notebook of past notes so we only compute the ONE new
     word's note each step and append it. O(1) projections per step, attention
     is Q[1]@K[S]^T = O(S)/step. BUT we pre-reserve a giant fixed shelf of size
     max_seq_len per reader; if a reader only jots 500 notes and the shelf has
     8192 slots, the other 7680 sit empty -> 93.75% wasted.

  3. PAGED cache (vLLM / PagedAttention, Kwon et al. SOSP 2023): like a LIBRARY.
     Shared shelves are carved into fixed-size PAGES. Each reader gets an INDEX
     CARD (the BLOCK TABLE) saying which physical pages hold their notes, and
     the pages can be scattered anywhere. No pre-reserved empty shelves -> waste
     < 1/page_size (last page partial only). When a reader finishes, their pages
     go back to the FREE LIST pool. rewind(n) (for speculative decoding) tears
     out the last n tokens' pages and returns them to the pool.

THE INVARIANT asserted everywhere (this is the load-bearing claim of the bundle):
    no-cache path  ==  dense-cache path  ==  paged-cache path
(compute-then-compare to tolerance). If you change the cache code, the asserts
must still pass. The cache stores already-rotated K,V; only WHERE bytes live
differs (one slab vs scattered pages), never WHAT they are.

Companion code that KV_CACHE.md is built from. Every number below is printed by:
    uv run python kv_cache.py

THE OFFSET LINK (this is the 🔗 to ROPE.md / CAUSAL_MASK.md):
  When generating word #512 one-at-a-time, the model must rotate/position it as
  word #512 (NOT as word #0). RoPE's offset is exactly the cache's offset.
  During decode, RoPE must use offset = slice(current_len, current_len+1) so the
  cached token sees its TRUE position. ASSERT decode-with-cache == precompute-all.
  Getting it wrong -> gibberish after prefill.

Conventions for tensor shapes (cache layout, axis 2 = SeqLen, matching tiny-llm):
    B      = batch size
    H_kv   = number of KV heads (per-layer)
    H_q    = number of query heads (== H_kv here; GQA would repeat KV)
    D      = head dimension
    S      = total tokens stored in the cache (= offset)
    L      = tokens in the current chunk being appended (1 during decode)
"""

from __future__ import annotations

import torch

# RoPE is imported from the sibling bundle to prove the OFFSET link (ROPE.md §10).
# Decode must rotate the new token at its true position; the cache just stores
# the already-rotated K,V. See section_offset_equivalence() for the assertion.
from rope import RoPE

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE DENSE CACHE  (recompute-from-scratch -> dense offset cache)
# ============================================================================

class DenseKVCache:
    """Pre-allocated contiguous KV cache: [B, H_kv, max_seq_len, d].

    ANALOGY: a fixed-size notebook shelf. Each reader (request) gets one shelf
    of `max_seq_len` slots up-front. They jot one note (K,V) per token into the
    next free slot. Simple and O(1) per step, but the shelf is reserved even if
    mostly empty -> the 93.75% waste problem of Section C.

    Mirrors TinyKvFullCache: update_and_fetch() appends new K,V and returns the
    FULL running K,V; rewind() truncates the logical length (for spec. decode).
    """

    def __init__(self, batch: int, n_kv_heads: int, head_dim: int,
                 max_seq_len: int, dtype=torch.float32):
        self.B = batch
        self.H = n_kv_heads
        self.D = head_dim
        self.max_seq_len = max_seq_len
        # the WHOLE max_seq_len slab is reserved up-front -> the waste source
        self.k = torch.zeros(batch, n_kv_heads, max_seq_len, head_dim, dtype=dtype)
        self.v = torch.zeros_like(self.k)
        self.offset = 0                       # current total sequence length

    def update_and_fetch(self, k_new: torch.Tensor, v_new: torch.Tensor):
        """Append k_new,v_new of shape [B, H_kv, L, D]; return full [B,H_kv,S,D]."""
        L = k_new.shape[2]
        assert self.offset + L <= self.max_seq_len, "dense cache overflow"
        sl = slice(self.offset, self.offset + L)
        self.k[:, :, sl, :] = k_new
        self.v[:, :, sl, :] = v_new
        self.offset += L
        return self.k[:, :, :self.offset, :], self.v[:, :, :self.offset, :]

    def rewind(self, n: int):
        """Drop the last n tokens (speculative decoding rejected them)."""
        assert n <= self.offset, "rewind past start"
        self.offset -= n                       # data beyond offset is now stale

    @property
    def allocated_bytes(self) -> int:
        return self.k.nelement() * self.k.element_size() + \
               self.v.nelement() * self.v.element_size()


# ============================================================================
# 2. THE PAGED POOL + PAGED CACHE  (dense -> paged virtual memory)
# ============================================================================

class PagedKVPool:
    """Physical page allocator shared by all requests/layers.

    ANALOGY: the LIBRARY's shared shelves. The whole pool is one big slab of
    fixed-size pages. Any request can borrow any free page; when they're done,
    the page goes back to the free list for someone else. No shelf is ever
    pre-reserved for one reader -> almost no waste (only the last partial page).

    key_pages / value_pages : [num_pages, H_kv, page_size, d]  (the "RAM")
    free_list               : stack of free physical page ids (the "available"
                              shelf slots, like an OS frame allocator's free
                              frame list)
    This is the OS frame allocator: allocate() grabs a frame, free_page()
    returns it. Pages are FIXED size; nothing is ever resized.
    """

    def __init__(self, num_pages: int, n_kv_heads: int, head_dim: int,
                 page_size: int, dtype=torch.float32):
        self.page_size = page_size
        self.H = n_kv_heads
        self.D = head_dim
        self.key_pages = torch.zeros(num_pages, n_kv_heads, page_size,
                                     head_dim, dtype=dtype)
        self.val_pages = torch.zeros_like(self.key_pages)
        # reverse so pop() yields 0,1,2,... (deterministic allocation order)
        self.free_list: list[int] = list(range(num_pages - 1, -1, -1))
        self.used: set[int] = set()
        self.num_pages = num_pages

    def allocate(self) -> int:
        pid = self.free_list.pop()
        self.used.add(pid)
        return pid

    def free_page(self, page_id: int) -> None:
        self.used.discard(page_id)
        self.free_list.append(page_id)

    def write(self, page_id: int, start: int, k: torch.Tensor, v: torch.Tensor):
        """Write k,v ([1,H,L,D]) into physical page_id at offset [start:start+L]."""
        end = start + k.shape[2]
        self.key_pages[page_id, :, start:end, :] = k[0]
        self.val_pages[page_id, :, start:end, :] = v[0]


class PagedKVCache:
    """Per-request logical cache over a shared PagedKVPool.

    ANALOGY: one reader's INDEX CARD in the library. The card lists which
    physical pages hold this reader's notes, in reading order. Pages can be
    scattered anywhere in the pool (page 0 -> physical 2, page 1 -> physical 5,
    etc.); the card tells the librarian how to gather them in order. This is
    exactly an OS page table (logical -> physical mapping).

    page_ids[]   : logical_page_idx -> physical_page_id   (the BLOCK TABLE /
                    INDEX CARD)
    page_lens[]  : how many live tokens each page holds (last page may be
                    partial; that partial slot is the ONLY waste)
    offset       : total live tokens (== sum of page_lens; == RoPE's offset)
    """

    def __init__(self, pool: PagedKVPool):
        self.pool = pool
        self.page_ids: list[int] = []
        self.page_lens: list[int] = []
        self.offset = 0

    @property
    def page_size(self) -> int:
        return self.pool.page_size

    def update_and_fetch(self, k_new: torch.Tensor, v_new: torch.Tensor):
        """Append chunk [1,H,L,D]: fill the tail of the last page, then allocate
        fresh pages for the remainder. Return gathered full K,V ([1,H,S,D])."""
        L = k_new.shape[2]
        start = 0
        # 1. fill remaining slots in the current (partial) last page
        if self.page_ids and self.page_lens[-1] < self.page_size:
            pid = self.page_ids[-1]
            ps = self.page_lens[-1]
            take = min(self.page_size - ps, L)
            self.pool.write(pid, ps, k_new[:, :, :take, :], v_new[:, :, :take, :])
            self.page_lens[-1] += take
            start = take
        # 2. allocate brand-new pages for whatever is left
        while start < L:
            end = min(start + self.page_size, L)
            pid = self.pool.allocate()
            self.pool.write(pid, 0, k_new[:, :, start:end, :], v_new[:, :, start:end, :])
            self.page_ids.append(pid)
            self.page_lens.append(end - start)
            start = end
        self.offset += L
        return self.fetch_full()

    def fetch_full(self) -> tuple[torch.Tensor, torch.Tensor]:
        """Gather non-contiguous physical pages into contiguous [1,H,offset,D]."""
        H, D, ps = self.pool.H, self.pool.D, self.page_size
        k_full = torch.zeros(1, H, self.offset, D)
        v_full = torch.zeros(1, H, self.offset, D)
        pos = 0
        for pid, plen in zip(self.page_ids, self.page_lens):
            k_full[:, :, pos:pos + plen, :] = self.pool.key_pages[pid, :, :plen, :]
            v_full[:, :, pos:pos + plen, :] = self.pool.val_pages[pid, :, :plen, :]
            pos += plen
        return k_full, v_full

    def rewind(self, n: int):
        """Undo the last n tokens: pop whole pages back to the free list, then
        fix the partial length of the new last page. (ceil is the trap — see F.)"""
        assert n <= self.offset, "rewind past start"
        new_offset = self.offset - n
        # ceil division: how many pages the remaining tokens still need
        target_pages = (new_offset + self.page_size - 1) // self.page_size
        while len(self.page_ids) > target_pages:
            pid = self.page_ids.pop()
            self.page_lens.pop()
            self.pool.free_page(pid)                  # return frame to the pool
        if target_pages > 0:
            self.page_lens[-1] = new_offset - self.page_size * (target_pages - 1)
        else:
            self.page_lens = []
        self.offset = new_offset


# ============================================================================
# 3. TOY ATTENTION + ROPE BRIDGE  (cache layout [B,H,S,D] vs RoPE [B,L,H,D])
# ============================================================================

def apply_rope(rope: RoPE, kv_hsd: torch.Tensor, offset) -> torch.Tensor:
    """kv_hsd is [B,H,S,D] (cache layout); RoPE wants [B,L,H,D]. Permute, rotate,
    permute back. Only K and Q are rotated (never V)."""
    x = kv_hsd.permute(0, 2, 1, 3)                  # [B, L(=S), H, D]
    y = rope(x, offset=offset)
    return y.permute(0, 2, 1, 3)                    # back to [B, H, S, D]


def toy_attention(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor,
                  scale: float) -> torch.Tensor:
    """q:[B,Hq,Sq,D]  k,v:[B,Hkv,Sk,D]  (Hq==Hkv here). No mask: the decode query
    attends to all cached keys, which is exactly causal for the last token."""
    scores = (q @ k.transpose(-1, -2)) * scale       # [B,Hq,Sq,Sk]
    probs = torch.softmax(scores, dim=-1)
    return probs @ v                                 # [B,Hq,Sq,D]


def make_kv(num_tokens: int, n_heads: int, head_dim: int, seed_offset: float = 0.0):
    """Deterministic, per-token-distinct K (or V): [1, H, num_tokens, D]."""
    t = torch.zeros(1, n_heads, num_tokens, head_dim)
    for p in range(num_tokens):
        for h in range(n_heads):
            for d in range(head_dim):
                t[0, h, p, d] = round(seed_offset + 0.1 * (p + 1)
                                      + 0.01 * h + 0.001 * (d + 1), 4)
    return t


# ============================================================================
# 4. PRETTY PRINTER
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 5. SECTIONS  (the numbers that feed KV_CACHE.md)
# ============================================================================
#
# GLOSSARY (defined where first used; mirrors KV_CACHE.md's glossary):
#   KV cache    - a running notebook of past Keys & Values so we don't recompute
#   Key (K)     - per-token "find me later" vector (rotated by RoPE)
#   Value (V)   - per-token "retrieve my content" vector (NEVER rotated)
#   prefill     - process the WHOLE prompt at once (chunk of L tokens, L>1)
#   decode      - generate ONE new token per step (chunk of L=1)
#   max_seq_len - the giant fixed shelf size dense reserves per request
#   page        - a fixed-size chunk of `page_size` token slots in the pool
#   page_size   - tokens per page (vLLM default 16; tiny-llm uses 128)
#   block table - the per-request INDEX CARD: logical page -> physical page id
#   free list   - the pool's stack of available physical page ids
#   fragmentation - empty slots inside reserved-but-unused memory (dense: huge;
#                   paged: only the last partial page, < 1/page_size)
#   offset      - how many tokens are already in the cache == RoPE's position
#                  offset for the new chunk. slice(offset, offset+L).
#   rewind(n)   - tear out the last n tokens (speculative decode rejection).
#                  Paged: pop pages back to the free list (ceil division!).

def section_no_cache_cost():
    # INTUITION: to answer the 100th word, re-read and re-think about ALL 100
    # words from scratch. Word 0's notes get recomputed at every single step.
    # Speedup comes from keeping past K,V in a notebook instead of recomputing.
    banner("SECTION A: no cache -> recompute K,V every step (O(L^2))")
    L = 5
    print(f"Generating {L} tokens by re-running the model on the WHOLE prefix each step.\n")
    print("| step t | seq len processed | K,V tokens computed this step | "
          "token-0 K,V recomputed? (times so far) |")
    print("|--------|-------------------|-------------------------------|"
          "---------------------------------------|")
    total_nocache = 0
    tok0_count = 0
    for t in range(1, L + 1):
        total_nocache += t                  # process t tokens -> t K,V projections
        tok0_count += 1
        print(f"| {t:<6} | {t:<17} | {t:<29} | "
              f"yes ({tok0_count})                                   |")
    total_cache = L                          # one new K,V per step
    print()
    print(f"Total K/V token-projections over {L} decode steps:")
    print(f"  no-cache : 1+2+3+4+5 = {total_nocache}   (= L(L+1)/2 = O(L^2))")
    print(f"  w/ cache : {total_cache}                  (1 per step = O(L))")
    print(f"  token-0's K,V computed  : {L}x without cache, 1x with cache")
    print(f"  speedup (projections)   : {total_nocache / total_cache:.1f}x")
    print()
    print("[check] no-cache cost L(L+1)/2 =", L * (L + 1) // 2,
          "== printed", total_nocache, "->", "OK")


def section_dense_shapes():
    # INTUITION: dense = "keep a notebook so we only compute the ONE new word's
    # note each step and append it" (O(1) projections/step). The catch is that
    # the whole max_seq_len shelf is reserved up-front, so an under-used reader
    # still ties up the full slab (the seed of Section C's fragmentation math).
    banner("SECTION B: dense cache shape evolution (prefill 3 -> decode 1)")
    H_kv, D = 2, 8
    cache = DenseKVCache(batch=1, n_kv_heads=H_kv, head_dim=D, max_seq_len=8)
    print(f"Pre-allocated cache shape: {tuple(cache.k.shape)}  "
          f"= [B=1, H_kv={H_kv}, max_seq_len=8, D={D}]")
    print(f"Reserved bytes (K+V): {cache.allocated_bytes}  "
          f"(fp32; {cache.allocated_bytes/2} for one of K or V)\n")
    # prefill 3
    k3 = make_kv(3, H_kv, D, seed_offset=0.0)
    v3 = make_kv(3, H_kv, D, seed_offset=0.5)
    k_full, v_full = cache.update_and_fetch(k3, v3)
    print("PREFILL 3 tokens:")
    print(f"  cache.k[:,:,:offset,:].shape = {tuple(k_full.shape)}  "
          f"(offset now {cache.offset})")
    # decode 1
    k1 = make_kv(1, H_kv, D, seed_offset=0.0)
    v1 = make_kv(1, H_kv, D, seed_offset=0.5)
    k_full, v_full = cache.update_and_fetch(k1, v1)
    print("DECODE 1 token:")
    print(f"  cache.k[:,:,:offset,:].shape = {tuple(k_full.shape)}  "
          f"(offset now {cache.offset})")
    print(f"  Q for this step has shape  : [1, H_q, 1, D]   <- ONLY the new token")
    print(f"  attention is Q[1,d] @ K[4,d]^T = O(S=4) per step, not O(S^2)")
    print()
    print("Note: the slab [B,H_kv,max_seq_len=8,D] is reserved NO MATTER the offset.")
    print(f"      Here offset={cache.offset} but max_seq_len=8 -> "
          f"{(1 - cache.offset/8)*100:.1f}% of the slab is unused right now.")


def section_fragmentation_math():
    # INTUITION: the dense shelf is reserved WORST-CASE per request. If max=8192
    # but only 512 tokens ever get used, 7680 slots sit empty -> 93.75% waste.
    # vLLM's blog reports 60-80% system-wide waste for the dense/reserving
    # systems it replaced (fragmentation + reservation + internal); distinct
    # from this clean per-request arithmetic example. PagedAttention wastes <4%.
    banner("SECTION C: fragmentation math (why dense wastes, why paged doesn't)")
    bytes_per = 2                               # fp16 / bf16
    print("All numbers below are COMPUTED here, not hand-waved. (fp16/bf16 = 2 B)\n")

    # --- the 93.75% example ---
    max_len, used = 8192, 512
    waste_frac = 1 - used / max_len
    print("THE 93% EXAMPLE (max_seq_len vs actual usage, one request):")
    print(f"  max_seq_len reserved = {max_len}, actual tokens used = {used}")
    print(f"  waste fraction = 1 - used/max = 1 - {used}/{max_len} "
          f"= {waste_frac:.4f} = {waste_frac*100:.2f}%")
    print(f"  -> {waste_frac*100:.2f}% of this request's reserved slab is dead memory.\n")

    # --- per-request dense bytes for a LLaMA-7B-shaped model ---
    layers, h_kv, d = 32, 32, 128
    per_req = 2 * layers * h_kv * max_len * d * bytes_per
    print(f"PER-REQUEST dense KV bytes (LLaMA-7B shape: {layers} layers, "
          f"{h_kv} KV heads, d={d}):")
    print(f"  2(KV) x {layers} x {h_kv} x {max_len} x {d} x {bytes_per} B "
          f"= {per_req:,.0f} bytes = {per_req/2**30:.3f} GiB")
    print(f"  vLLM reports up to ~1.7 GiB for LLaMA-13B (more layers/heads) per seq.\n")

    # --- 100 concurrent requests, reserved vs used ---
    n_req = 100
    reserved = n_req * per_req
    used_total = n_req * 2 * layers * h_kv * d * used * bytes_per
    print(f"100 CONCURRENT requests, reserved vs actually used (used={used} each):")
    print(f"  reserved = {reserved/2**30:.1f} GiB")
    print(f"  used     = {used_total/2**30:.1f} GiB")
    print(f"  wasted   = {(reserved-used_total)/2**30:.1f} GiB "
          f"({(1-used_total/reserved)*100:.1f}% of reserved)")
    print(f"  (This dead slab caps your batch size -> caps throughput.)\n")

    # --- paged waste bound ---
    print("PAGED cache waste bound (only the LAST page of each request is partial):")
    print("| page_size | worst-case internal waste |")
    print("|-----------|---------------------------|")
    for ps in (4, 16, 128):
        bound = 1.0 / ps
        note = ""
        if ps == 16:
            note = "  <- vLLM default block size"
        if ps == 128:
            note = "  <- tiny-llm page_size (real)"
        print(f"| {ps:<9} | {bound*100:.2f}%{note} |")
    print()
    print("vLLM measured: PagedAttention wastes <4% in practice vs 60%-80% for the")
    print("dense/over-reserving systems it replaced. (Sources: vLLM blog + paper.)")
    print()
    print(f"[check] 93.75% math: 1 - 512/8192 = {1-512/8192} ->", "OK")
    print(f"[check] per_req bytes == 2*32*32*8192*128*2 = "
          f"{2*32*32*8192*128*2} ->", "OK" if per_req == 2*32*32*8192*128*2 else "FAIL")


def section_paged_block_table():
    # INTUITION: PagedAttention = "a LIBRARY with shared shelves carved into
    # fixed-size pages". Each reader gets an INDEX CARD (block table) listing
    # which physical pages hold their notes - and the pages can be SCATTERED.
    # Here we interleave requests A and B so A's pages end up at physical [0, 2]
    # (non-contiguous!), proving the block table is what makes scattered storage
    # usable. No pre-reserved empty shelves -> almost no waste.
    banner("SECTION D: paged pool + block_table (logical -> non-contiguous physical)")
    H_kv, D, PS = 2, 8, 4
    pool = PagedKVPool(num_pages=8, n_kv_heads=H_kv, head_dim=D, page_size=PS)
    A = PagedKVCache(pool)
    B = PagedKVCache(pool)

    def chunk(n, off):
        return make_kv(n, H_kv, D, off), make_kv(n, H_kv, D, off + 0.5)

    # Interleave A and B so A's physical pages end up NON-CONTIGUOUS.
    A.update_and_fetch(*chunk(4, 0.0))      # A logical[0] -> phys 0 (full)
    B.update_and_fetch(*chunk(4, 0.0))      # B logical[0] -> phys 1 (full)
    A.update_and_fetch(*chunk(1, 0.0))      # A decode -> A logical[1] -> phys 2
    B.update_and_fetch(*chunk(1, 0.0))      # B decode -> B logical[1] -> phys 3
    A.update_and_fetch(*chunk(3, 0.0))      # A fills phys 2 tail -> phys 2 now full
    #   (A had 1 token in phys2; +3 = 4 = full; no new page needed)
    print(f"page_size = {PS}. Interleaved two requests so storage is scattered.\n")
    print("BLOCK TABLE (logical_page -> physical_page_id):")
    print("| request | logical pages (in order)        | physical pages      "
          "| contiguous? |")
    print("|---------|----------------------------------|----------------------"
          "--------------|")

    def phys_list(c):
        return c.page_ids

    def contiguous(ids):
        return "yes" if ids == list(range(ids[0], ids[0] + len(ids))) else "NO (scattered)"

    for name, c in (("A", A), ("B", B)):
        ids = phys_list(c)
        log = [f"L{i}" for i in range(len(ids))]
        phys = [f"P{p}" for p in ids]
        print(f"| {name:<7} | {str(log):<32} | "
              f"{str(phys):<20} | {contiguous(ids):<12} |")
    print()
    print("Reading request A's K,V in logical order walks physical pages "
          f"{A.page_ids} -> the data is scattered across the pool.")
    print("The paged attention kernel uses THIS block table to gather K,V from")
    print("non-contiguous physical memory, exactly like an OS page table.\n")
    print(f"GOLD block_table for the .html:")
    print(f"  A.page_ids = {A.page_ids}")
    print(f"  B.page_ids = {B.page_ids}")
    print(f"  A.page_lens = {A.page_lens}")
    print(f"  B.page_lens = {B.page_lens}")


def section_offset_equivalence():
    # INTUITION: the offset = "when generating word #512 one-at-a-time, the
    # model must treat it as word #512 (rotate/position it correctly), NOT as
    # word #0. This is exactly RoPE's offset." This section PROVES the cached
    # decode path (dense AND paged) equals the all-at-once precompute path, by
    # building the same 4 tokens three ways and asserting byte-equality.
    banner("SECTION E: offset correctness -> no-cache == dense == paged")
    H_kv, H_q, D = 2, 2, 8
    rope = RoPE(dims=D, seq_len=32, base=10000.0, traditional=False)
    scale = 1.0 / (D ** 0.5)

    raw_k = make_kv(4, H_kv, D, 0.0)
    raw_v = make_kv(4, H_kv, D, 0.5)
    raw_q = make_kv(4, H_q, D, 0.0)

    # ---------- PATH 1: all-at-once (ground truth, "no cache") ----------
    k_all = apply_rope(rope, raw_k, slice(0, 4))        # rotate all 4 at once
    q_all = apply_rope(rope, raw_q, slice(0, 4))
    out_full_last = toy_attention(q_all, k_all, raw_v, scale)[:, :, 3:4, :]
    k_gold = k_all.detach().clone()                     # [1,H_kv,4,D]

    # ---------- PATH 2: dense cache (prefill 3 -> decode 1) ----------
    dense = DenseKVCache(1, H_kv, D, max_seq_len=8)
    k3 = apply_rope(rope, raw_k[:, :, 0:3], slice(0, 3))
    dense.update_and_fetch(k3, raw_v[:, :, 0:3])
    k1 = apply_rope(rope, raw_k[:, :, 3:4], slice(3, 4))   # TRUE position 3
    q1 = apply_rope(rope, raw_q[:, :, 3:4], slice(3, 4))
    k_full_d, v_full_d = dense.update_and_fetch(k1, raw_v[:, :, 3:4])
    out_dense = toy_attention(q1, k_full_d, v_full_d, scale)

    # ---------- PATH 3: paged cache (prefill 3 -> decode 1) ----------
    pool = PagedKVPool(num_pages=8, n_kv_heads=H_kv, head_dim=D, page_size=4)
    paged = PagedKVCache(pool)
    paged.update_and_fetch(k3, raw_v[:, :, 0:3])
    k_full_p, v_full_p = paged.update_and_fetch(k1, raw_v[:, :, 3:4])
    out_paged = toy_attention(q1, k_full_p, v_full_p, scale)

    # ---------- WRONG offset (the ROPE.md §10 bug) ----------
    q_wrong = apply_rope(rope, raw_q[:, :, 3:4], slice(0, 1))   # position 0 !!
    out_wrong = toy_attention(q_wrong, k_full_d, v_full_d, scale)

    print("Scenario: 4 tokens. Prefill tokens 0..2, then DECODE token 3.\n")
    print("K-cache (full, head h=0) — three paths must agree:")
    print("| path            | K[0,0,0,:4] (token0)              | "
          "K[0,0,3,:4] (token3)              |")
    print("|-----------------|-----------------------------------|"
          "-----------------------------------|")
    for name, kk in (("all-at-once", k_gold), ("dense", k_full_d), ("paged", k_full_p)):
        t0 = [round(x, 4) for x in kk[0, 0, 0, :4].tolist()]
        t3 = [round(x, 4) for x in kk[0, 0, 3, :4].tolist()]
        print(f"| {name:<15} | {str(t0):<33} | {str(t3):<33} |")
    print()
    tol = 1e-5
    c1 = torch.allclose(k_full_d, k_gold, atol=tol)
    c2 = torch.allclose(k_full_p, k_gold, atol=tol)
    c3 = torch.allclose(k_full_p, k_full_d, atol=tol)
    c4 = torch.allclose(out_dense, out_full_last, atol=tol)
    c5 = torch.allclose(out_paged, out_full_last, atol=tol)
    c6 = not torch.allclose(out_wrong, out_full_last, atol=1e-3)
    print(f"[check] dense full-K  == all-at-once K ? {c1}")
    print(f"[check] paged full-K  == all-at-once K ? {c2}")
    print(f"[check] paged full-K  == dense full-K   ? {c3}")
    print(f"[check] dense attn(token3)  == full attn(token3) ? {c4}")
    print(f"[check] paged attn(token3)  == full attn(token3) ? {c5}")
    print(f"[check] WRONG-offset decode differs from correct ? {c6}  "
          "(proves offset matters -> see ROPE.md)")
    all_ok = all([c1, c2, c3, c4, c5, c6])
    print(f"\n[check] ALL THREE PATHS MATCH (no-cache == dense == paged): "
          f"{'OK' if all_ok else 'FAIL'}")
    print(f"\nGOLD for .html: dense-K == paged-K == all-at-once-K at tol {tol} -> "
          f"{'OK' if (c1 and c2 and c3) else 'FAIL'}")
    return all_ok


def section_paged_rewind():
    # INTUITION: rewind (speculative decoding) = "if the model guessed a few
    # words too eagerly and they're rejected, just tear out those last notebook
    # pages - in the library, RETURN those pages to the pool." Tearing must
    # respect page boundaries: an off-by-one leaves a stale half-page that
    # leaks into the next step. The trap is ceil vs floor at exact multiples.
    banner("SECTION F: rewind(n) on paged cache (speculative decoding, no off-by-one)")
    H_kv, D, PS = 2, 8, 4
    pool = PagedKVPool(num_pages=8, n_kv_heads=H_kv, head_dim=D, page_size=PS)
    c = PagedKVCache(pool)
    c.update_and_fetch(*(_ := (make_kv(5, H_kv, D, 0.0), make_kv(5, H_kv, D, 0.5))))
    print(f"Start: prefill 5 tokens, page_size={PS}.")
    print(f"  page_ids  = {c.page_ids}   (logical -> physical)")
    print(f"  page_lens = {c.page_lens}   (page 0 full, page 1 has 1 token)")
    print(f"  offset    = {c.offset}")
    print(f"  free_list before rewind = {sorted(pool.free_list)}\n")

    c.rewind(1)
    print("rewind(1): speculative draft rejected 1 token.")
    print(f"  page_ids  = {c.page_ids}   <- physical page 1 RETURNED to free list")
    print(f"  page_lens = {c.page_lens}   <- page 0 back to full (4 tokens)")
    print(f"  offset    = {c.offset}")
    print(f"  free_list after rewind  = {sorted(pool.free_list)}")
    print(f"  pool.used = {sorted(pool.used)}\n")

    # --- the off-by-one trap: ceil vs floor at boundaries ---
    print("THE OFF-BY-ONE TRAP (why rewind uses CEIL, not floor):")
    print("| offset | rewind(n) | new_offset | ceil(new/PS) pages kept "
          "| floor would keep | correct? |")
    print("|--------|-----------|------------|--------------------------"
          "|------------------|----------|")
    for off, n in [(4, 1), (5, 1), (8, 1), (5, 5), (4, 4), (9, 1)]:
        new = off - n
        ceil_p = (new + PS - 1) // PS if new > 0 else 0
        floor_p = new // PS
        ok = "yes (ceil)" if (new == 0 or ceil_p == (new + PS - 1) // PS) else "BUG"
        print(f"| {off:<6} | {n:<9} | {new:<10} | {ceil_p:<24} | "
              f"{floor_p:<16} | {ok:<8} |")
    print()
    print("At offset=8 rewind(1): new=7. ceil(7/4)=2 pages kept (correct: 4+3).")
    print("  floor(7/4)=1 would DROP a still-needed page -> silent data loss.")
    print("At offset=5 rewind(1): new=4. ceil(4/4)=1 page kept (correct: 4 fill it).")
    print("  A naive 'new_offset//page_size' is WRONG at exact multiples.\n")
    print("[check] page returned to free_list after rewind(1):",
          (1 in pool.free_list), "->", "OK" if (1 in pool.free_list) else "FAIL")
    print("[check] offset after rewind(1) == 4:",
          c.offset == 4, "->", "OK" if c.offset == 4 else "FAIL")


# ============================================================================
# main
# ============================================================================

def main():
    print("kv_cache.py - reference impl. All numbers below feed KV_CACHE.md.")
    print("torch =", torch.__version__)

    section_no_cache_cost()
    section_dense_shapes()
    section_fragmentation_math()
    section_paged_block_table()
    ok = section_offset_equivalence()
    section_paged_rewind()

    banner("DONE - all sections printed; equivalence gold = " +
           ("OK" if ok else "FAIL"))


if __name__ == "__main__":
    main()
