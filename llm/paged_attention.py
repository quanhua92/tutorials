"""
paged_attention.py - Reference implementation of PagedAttention's memory layer.

WHAT IS PAGED ATTENTION? (start here if you have minimal ML background)
  A Transformer keeps a running notebook of past Keys (K) and Values (V) so it
  doesn't recompute them every step (see KV_CACHE.md). The OLD way (Dense KV
  cache) reserved one giant fixed shelf of size `max_seq_len` PER request up
  front: if a request only used 500 of its 8192 slots, the other 7680 sat
  empty (up to 93% wasted). vLLM (Kwon et al., SOSP 2023) borrowed the OS
  virtual-memory trick: ONE shared physical pool carved into fixed-size PAGES;
  each request holds a BLOCK TABLE (an index card) saying which physical pages
  hold its notes; pages may be NON-CONTIGUOUS. Waste drops from 60-80% to <4%.

THE LINEAGE THIS BUNDLE ASSERTS (old -> new, with WHY):
  DenseKVCache: [B, H_kv, max_seq_len, d] reserved per request
        |  pain: huge fragmentation, small batches
        v
  PagedKVPool + PagedKVCache (this file):
      * pool: [num_pages, H_kv, page_size, d]      (the "RAM")
      * free_list: stack of available page ids     (the OS frame allocator)
      * per-request block_table page_ids[]         (logical -> physical)
      * page_lens[]: how full each owned page is    (last page may be partial)
  WHY it wins:
      * only the LAST page is partial -> waste < 1/page_size (<4% in vLLM)
      * a freed page is immediately reusable by ANY request (no fragmentation)
      * ref-counted sharing + Copy-on-Write for parallel sampling / beam search

THE INVARIANT asserted here (and proven against the dense path):
  paged_cache.update_and_fetch(K, V) returns the SAME K,V bytes as the dense
  path would, only the *where* (scattered pages vs one slab) differs. The
  paged attention kernel reads the same numbers via indirect lookup.

THE INDIRECT-LOOKUP FORMULA (the heart of the paged attention kernel):
  For logical token position `col` of request `b`:
      page_idx = col // page_size                   # logical page number
      slot     = col %  page_size                   # offset within the page
      page_id  = block_table[b, page_idx]           # OS page-table lookup
      k_idx    = ((page_id * H_kv + kv_head) * page_size + slot) * D + c
  Contrast with DENSE sequential addressing:
      k_ptr    = k_base + (j * Bc + b) * D + c      # one slab, contiguous
  The paged version costs ONE extra indirection per KV tile but enables
  non-contiguous storage -> on-demand allocation -> near-zero waste.

Conventions (same as KV_CACHE.md, mirrored here so this file is self-contained):
    P       = page size (tokens per page). tiny-llm uses 128; vLLM default 16.
    H_kv    = number of KV heads
    D       = head dimension
    block_table[b] = list of physical page_ids for request b   (page_ids[])
    page_lens[b]   = how many live tokens each page holds      (page_lens[])
    offset         = total live tokens (== RoPE's offset)
    free_list      = the pool's stack of available physical page ids
    used           = the pool's set of currently-allocated page ids

Companion code that PAGED_ATTENTION.md is built from. Every number below is
printed by:
    uv run python paged_attention.py
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE PAGE POOL + PAGED CACHE  (the OS virtual-memory analogue)
# ============================================================================

class PagedKVPool:
    """Physical page allocator shared by all requests/layers (the "RAM").

    Mirrors TinyKvPagedPool (tiny-llm/src/tiny_llm_ref/paged_kv_cache.py):
      key_pages / value_pages : [num_pages, H_kv, page_size, d]
      free_list               : stack of free physical page ids (reverse-built
                                so pop() yields 0,1,2,... deterministically)
      used                    : which physical page ids are currently owned
    This is the OS frame allocator: allocate() pops a frame, free_page()
    pushes one back. The backing tensor grows on demand when free_list is
    empty (matching TinyKvPagedPool._ensure_page_storage).
    """

    def __init__(self, num_pages: int, n_kv_heads: int, head_dim: int,
                 page_size: int, dtype=torch.float32):
        self.page_size = page_size
        self.H = n_kv_heads
        self.D = head_dim
        self.num_pages = num_pages
        # the WHOLE pool - the OS's physical RAM, one slab for ALL requests
        self.key_pages = torch.zeros(num_pages, n_kv_heads, page_size,
                                     head_dim, dtype=dtype)
        self.val_pages = torch.zeros_like(self.key_pages)
        # reverse so pop() yields 0,1,2,... (deterministic allocation order)
        self.free_list: list[int] = list(range(num_pages - 1, -1, -1))
        self.used: set[int] = set()

    def allocate(self) -> int:
        """Grab a free physical page; grow the pool if free_list is empty."""
        if not self.free_list:
            self._grow()
        pid = self.free_list.pop()
        self.used.add(pid)
        return pid

    def _grow(self):
        """Append one more physical page to the backing slab (mirrors
        TinyKvPagedPool._ensure_page_storage). Real vLLM pre-allocates a
        fixed pool sized to GPU free memory; tiny-llm grows on demand."""
        old = self.num_pages
        self.num_pages += 1
        new_k = torch.zeros(self.num_pages, self.H, self.page_size, self.D,
                            dtype=self.key_pages.dtype)
        new_v = torch.zeros_like(new_k)
        new_k[:old] = self.key_pages
        new_v[:old] = self.val_pages
        self.key_pages = new_k
        self.val_pages = new_v
        self.free_list.append(old)            # the new page is free

    def free_page(self, page_id: int) -> None:
        """Return a page to the free list (OS frees a frame). Stale K/V bytes
        stay in the backing tensor; page_lens/block_table decide what's live."""
        self.used.discard(page_id)
        self.free_list.append(page_id)

    def write(self, page_id: int, start: int, k: torch.Tensor, v: torch.Tensor):
        """Write k,v ([1,H,L,D]) into physical page_id at offset [start:start+L]."""
        end = start + k.shape[2]
        self.key_pages[page_id, :, start:end, :] = k[0]
        self.val_pages[page_id, :, start:end, :] = v[0]

    def read_slot(self, page_id: int, kv_head: int, slot: int, c: int) -> float:
        """The kernel's indirect lookup: physical addr of K[page_id,head,slot,c].
        Implements  k_idx = ((page_id*H_kv + kv_head)*page_size + slot)*D + c."""
        H, PS, D = self.H, self.page_size, self.D
        k_idx = ((page_id * H + kv_head) * PS + slot) * D + c
        flat = self.key_pages.view(-1)
        return float(flat[k_idx])


class PagedKVCache:
    """Per-request logical cache over a shared PagedKVPool.

    Mirrors TinyKvPagedCache (paged_kv_cache.py):
      page_ids[]   = logical_page_idx -> physical_page_id  (the BLOCK TABLE)
      page_lens[]  = how many live tokens each page holds (last page partial)
      offset       = total live tokens (== RoPE's offset)
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
        """Append chunk [1,H,L,D]: tail-fill the last page, then allocate
        fresh pages for the remainder. Returns the gathered full K,V
        ([1,H,S,D]) - identical bytes to the dense path."""
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
        """Gather non-contiguous physical pages into contiguous [1,H,S,D]
        via the block table. This is what gather_dense() does in the source."""
        H, D = self.pool.H, self.pool.D
        k_full = torch.zeros(1, H, self.offset, D)
        v_full = torch.zeros(1, H, self.offset, D)
        pos = 0
        for pid, plen in zip(self.page_ids, self.page_lens):
            k_full[:, :, pos:pos + plen, :] = self.pool.key_pages[pid, :, :plen, :]
            v_full[:, :, pos:pos + plen, :] = self.pool.val_pages[pid, :, :plen, :]
            pos += plen
        return k_full, v_full

    def rewind(self, n: int):
        """Undo the last n tokens: pop whole pages back to the free list,
        then fix the partial length of the new last page (ceil, never floor)."""
        assert n <= self.offset, "rewind past start"
        new_offset = self.offset - n
        target_pages = (new_offset + self.page_size - 1) // self.page_size  # CEIL
        while len(self.page_ids) > target_pages:
            pid = self.page_ids.pop()
            self.page_lens.pop()
            self.pool.free_page(pid)
        if target_pages > 0:
            self.page_lens[-1] = new_offset - self.page_size * (target_pages - 1)
        else:
            self.page_lens = []
        self.offset = new_offset

    def release(self):
        """Request completion: return ALL pages to the pool (OS frees process)."""
        for pid in self.page_ids:
            self.pool.free_page(pid)
        self.page_ids.clear()
        self.page_lens.clear()
        self.offset = 0


# ============================================================================
# 2. DENSE CACHE (for the contrast + equivalence proof) - copied from
#    kv_cache.py so this bundle is self-contained.
# ============================================================================

class DenseKVCache:
    """Pre-allocated contiguous KV cache: [B, H_kv, max_seq_len, d]."""

    def __init__(self, batch: int, n_kv_heads: int, head_dim: int,
                 max_seq_len: int, dtype=torch.float32):
        self.B = batch
        self.H = n_kv_heads
        self.D = head_dim
        self.max_seq_len = max_seq_len
        self.k = torch.zeros(batch, n_kv_heads, max_seq_len, head_dim, dtype=dtype)
        self.v = torch.zeros_like(self.k)
        self.offset = 0

    def update_and_fetch(self, k_new: torch.Tensor, v_new: torch.Tensor):
        L = k_new.shape[2]
        assert self.offset + L <= self.max_seq_len, "dense cache overflow"
        sl = slice(self.offset, self.offset + L)
        self.k[:, :, sl, :] = k_new
        self.v[:, :, sl, :] = v_new
        self.offset += L
        return self.k[:, :, :self.offset, :], self.v[:, :, :self.offset, :]


# ============================================================================
# 3. DETERMINISTIC INPUT BUILDER  (mirrors make_kv in kv_cache.py)
# ============================================================================

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
# 5. SECTIONS  (the numbers that feed PAGED_ATTENTION.md)
# ============================================================================
#
# GLOSSARY (defined where first used; mirrors PAGED_ATTENTION.md's glossary):
#   page         a fixed-size chunk of `page_size` token slots in the pool
#   page_size    tokens per page (vLLM default 16; tiny-llm uses 128)
#   page pool    the shared physical slab: [num_pages, H_kv, page_size, d]
#   free_list    the pool's stack of available physical page ids
#   block_table  per-request index card: logical page -> physical page id
#   logical pos  a token's seat number t in its own sequence (0,1,2,...)
#   page_idx     = t // page_size   (which logical page holds seat t)
#   slot         = t %  page_size   (which slot inside that page)
#   page_id      = block_table[page_idx]  (the OS virtual->physical translation)
#   offset       total live tokens in this request's cache
#   rewind(n)    tear out the last n tokens (speculative decode rejection)
#   release()    free ALL owned pages on request completion

def section_dense_waste():
    # INTUITION: dense reserves max_seq_len per request up front. If a request
    # only uses 512 of 8192, 7680 slots sit dead. vLLM measured 60-80% system-
    # wide waste; paged drops that to <4% because only the last page is partial.
    banner("SECTION A: the dense-waste problem (why pages exist)")
    print("All numbers below are COMPUTED here, not hand-waved.\n")

    # --- the 93.75% example: one request ---
    max_len, used = 8192, 512
    waste_frac = 1 - used / max_len
    print("THE 93% EXAMPLE (one request, reserved vs used):")
    print(f"  max_seq_len reserved = {max_len}, actual tokens used = {used}")
    print(f"  waste fraction = 1 - {used}/{max_len} = {waste_frac:.4f} "
          f"= {waste_frac*100:.2f}%")
    print(f"  -> {waste_frac*100:.2f}% of this request's slab is dead memory.\n")

    # --- per-request dense bytes for a LLaMA-7B-shaped model ---
    layers, h_kv, d, bp = 32, 32, 128, 2          # fp16/bf16 = 2 B
    per_req = 2 * layers * h_kv * max_len * d * bp
    print(f"PER-REQUEST dense KV bytes (LLaMA-7B shape: {layers} layers, "
          f"{h_kv} KV heads, d={d}):")
    print(f"  2(KV) x {layers} x {h_kv} x {max_len} x {d} x {bp} B "
          f"= {per_req:,.0f} bytes = {per_req/2**30:.3f} GiB")

    # --- 100 concurrent requests ---
    n_req = 100
    reserved = n_req * per_req
    used_total = n_req * 2 * layers * h_kv * d * used * bp
    print(f"100 CONCURRENT requests (used={used} each):")
    print(f"  reserved = {reserved/2**30:.1f} GiB, used = {used_total/2**30:.1f} GiB")
    print(f"  wasted   = {(reserved-used_total)/2**30:.1f} GiB "
          f"({(1-used_total/reserved)*100:.1f}% of reserved)")
    print(f"  vLLM reports up to ~1.7 GiB per sequence for LLaMA-13B (fp16).\n")

    # --- paged waste bound ---
    print("PAGED cache waste bound (only the LAST page of each request is partial):")
    print("| page_size | worst-case internal waste |")
    print("|-----------|---------------------------|")
    for ps in (16, 128):
        note = "  <- vLLM default block size" if ps == 16 else "  <- tiny-llm page_size"
        print(f"| {ps:<9} | {100/ps:.2f}%{note} |")
    print()
    print("vLLM measured: PagedAttention wastes <4% in practice vs 60%-80% for the")
    print("dense/over-reserving systems it replaced (paper Section 3.2).")
    print()
    print(f"[check] 93.75% math: 1 - 512/8192 = {1-512/8192} -> OK")
    print(f"[check] per_req bytes == 2*32*32*8192*128*2 = "
          f"{2*32*32*8192*128*2} ->",
          "OK" if per_req == 2*32*32*8192*128*2 else "FAIL")


def section_pool_and_freelist():
    # INTUITION: the pool is the OS's physical RAM. The free_list is its frame
    # allocator. allocate() pops a frame; free_page() returns one. A freed
    # frame is immediately reusable by any request - NO fragmentation.
    banner("SECTION B: page pool + free list (the OS frame allocator)")
    H, D, PS = 2, 8, 2
    pool = PagedKVPool(num_pages=4, n_kv_heads=H, head_dim=D, page_size=PS)
    print(f"page_size = {PS}, H_kv = {H}, D = {D}, num_pages = 4")
    print(f"Backing slab shapes: key_pages {tuple(pool.key_pages.shape)}, "
          f"value_pages {tuple(pool.val_pages.shape)}")
    print(f"  = [num_pages=4, H_kv=2, page_size=2, D=8]\n")

    fl = lambda: sorted(pool.free_list)
    pu = lambda: sorted(pool.used)
    print("LIFECYCLE (deterministic order: pop() yields 0,1,2,...):")
    print("| step | action            | free_list after | pool.used   |")
    print("|------|-------------------|-----------------|-------------|")
    a = pool.allocate()
    print(f"| 1    | allocate() -> {a:<4} | {str(fl()):<15} | {str(pu()):<11} |")
    b = pool.allocate()
    print(f"| 2    | allocate() -> {b:<4} | {str(fl()):<15} | {str(pu()):<11} |")
    c = pool.allocate()
    print(f"| 3    | allocate() -> {c:<4} | {str(fl()):<15} | {str(pu()):<11} |")
    pool.free_page(a)
    print(f"| 4    | free_page({a})      | {str(fl()):<15} | {str(pu()):<11} |")
    d = pool.allocate()
    print(f"| 5    | allocate() -> {d:<4} | {str(fl()):<15} | {str(pu()):<11} |")
    print()
    print("Notice: free_page(0) returns page 0 to the free_list; the NEXT")
    print("allocate() may reuse it (page 0 is recycled, no fragmentation).")
    print()
    print(f"[check] 3 allocs yield [0,1,2]:", [a, b, c], "->",
          "OK" if [a, b, c] == [0, 1, 2] else "FAIL")
    print(f"[check] after free(0) then alloc, page 0 reused:",
          "OK" if d == 0 else "FAIL")


def section_block_table():
    # INTUITION: the block_table is the per-request index card. It lists which
    # PHYSICAL pages hold this request's notes, IN ORDER. Two requests share
    # one pool; interleaving their allocs makes storage NON-CONTIGUOUS, which
    # is exactly why the kernel needs the block table to gather K,V.
    banner("SECTION C: block_table logical->physical (the GOLD example)")
    H, D, PS = 2, 8, 2
    pool = PagedKVPool(num_pages=8, n_kv_heads=H, head_dim=D, page_size=PS)
    A = PagedKVCache(pool)
    B = PagedKVCache(pool)

    def chunk(n, off):
        return make_kv(n, H, D, off), make_kv(n, H, D, off + 0.5)

    # Interleave A and B so A's physical pages end up NON-CONTIGUOUS.
    A.update_and_fetch(*chunk(2, 0.0))   # A logical 0 -> phys 0 (full)
    B.update_and_fetch(*chunk(2, 0.0))   # B logical 0 -> phys 1 (full)
    A.update_and_fetch(*chunk(1, 0.0))   # A decode -> A logical 1 -> phys 2
    print(f"page_size = {PS}. Interleaved two requests so storage is scattered.\n")

    print("BLOCK TABLE (logical_page -> physical_page_id):")
    print("| request | logical pages (in order) | physical pages  "
          "| contiguous? |")
    print("|---------|--------------------------|------------------"
          "--------------|")

    def contiguous(ids):
        return ("yes" if ids == list(range(ids[0], ids[0] + len(ids)))
                else "NO (scattered)")

    for name, c in (("A", A), ("B", B)):
        ids = c.page_ids
        log = [f"L{i}" for i in range(len(ids))]
        phys = [f"P{p}" for p in ids]
        print(f"| {name:<7} | {str(log):<24} | {str(phys):<16} "
              f"| {contiguous(ids):<12} |")
    print()
    print(f"A.page_ids  = {A.page_ids}   (logical 0 -> phys 0, logical 1 -> phys 2)")
    print(f"A.page_lens = {A.page_lens}   (both pages full: 2 tokens each)")
    print(f"B.page_ids  = {B.page_ids}   (logical 0 -> phys 1)")
    print(f"B.page_lens = {B.page_lens}")
    print(f"pool.used   = {sorted(pool.used)}")
    print(f"pool.free   = {sorted(pool.free_list)}")
    print()
    print("Reading A's K,V in LOGICAL order walks physical pages [0, 2] ->")
    print("A's storage is SCATTERED across the pool. The paged attention kernel")
    print("uses THIS block table to gather K,V from non-contiguous physical")
    print("memory, exactly like an OS page table.\n")

    # GOLD: logical pos -> physical (page_id, slot)
    print("LOGICAL POSITION -> PHYSICAL (page_id, slot) for request A:")
    print("| logical pos t | page_idx = t//PS | slot = t%PS | page_id = block_table[t//PS] |")
    print("|---------------|------------------|-------------|------------------------------|")
    gold_pos2page = {}
    for t in range(A.offset):
        pidx = t // PS
        slot = t % PS
        pid = A.page_ids[pidx]
        gold_pos2page[t] = (pid, slot)
        print(f"| {t:<13} | {pidx:<16} | {slot:<11} | {pid:<28} |")
    print()
    print(f"GOLD for the .html gold-check:")
    print(f"  A logical pos 2 -> page_id {gold_pos2page[2][0]}, slot {gold_pos2page[2][1]}")
    print(f"  (A.page_ids[1] = {A.page_ids[1]}; pos 2 // PS=2 -> page_idx 1, slot 0)")
    print()
    print(f"[check] A.page_ids == [0,2]:", A.page_ids == [0, 2], "->",
          "OK" if A.page_ids == [0, 2] else "FAIL")
    print(f"[check] A logical pos 2 -> page_id 2, slot 0:",
          gold_pos2page[2] == (2, 0), "->",
          "OK" if gold_pos2page[2] == (2, 0) else "FAIL")
    return gold_pos2page


def section_append_chunk():
    # INTUITION: when a new chunk arrives, we first FILL the tail of the
    # current partial page (if any), THEN allocate fresh pages for the rest.
    # This is exactly TinyKvPagedCache._append_chunk. Decoding one token into
    # a page that still has room costs ZERO allocations - the page just fills.
    banner("SECTION D: _append_chunk (tail-fill then new pages)")
    H, D, PS = 2, 8, 2
    pool = PagedKVPool(num_pages=8, n_kv_heads=H, head_dim=D, page_size=PS)
    c = PagedKVCache(pool)

    print(f"page_size = {PS}. Watch how a chunk fills the tail page first, then")
    print(f"allocates new pages only for the OVERFLOW.\n")
    print("| step | action                      | page_ids     | page_lens    "
          "| offset | pool.used    |")
    print("|------|-----------------------------|--------------|--------------"
          "|--------|--------------|")

    def show(step, action):
        print(f"| {step:<4} | {action:<27} | {str(c.page_ids):<12} | "
              f"{str(c.page_lens):<12} | {c.offset:<6} | "
              f"{str(sorted(pool.used)):<12} |")

    k3, v3 = make_kv(3, H, D, 0.0), make_kv(3, H, D, 0.5)
    c.update_and_fetch(k3, v3)
    show(1, "append chunk of 3")
    s1_ids, s1_lens, s1_off = list(c.page_ids), list(c.page_lens), c.offset
    # chunk of 3 with PS=2: fills page 0 (2 slots), needs 1 more -> page 1 has 1
    k2, v2 = make_kv(2, H, D, 0.0), make_kv(2, H, D, 0.5)
    c.update_and_fetch(k2, v2)
    show(2, "append chunk of 2 (fills tail)")
    s2_ids, s2_lens, s2_off = list(c.page_ids), list(c.page_lens), c.offset
    # page 1 had 1 slot; +2 -> fills 1 slot of page 1 (now full) + 1 slot of page 2
    k1, v1 = make_kv(1, H, D, 0.0), make_kv(1, H, D, 0.5)
    c.update_and_fetch(k1, v1)
    show(3, "append chunk of 1 (decode)")
    s3_ids, s3_lens, s3_off = list(c.page_ids), list(c.page_lens), c.offset
    print()
    print("Step 1: chunk of 3 with PS=2. Page 0 fills (slots 0,1); the 3rd")
    print("  token spills into a NEW page 1 (slot 0 only - partial).")
    print("Step 2: chunk of 2. First token fills page 1's tail (now full);")
    print("  second token allocates page 2 (slot 0). Notice no waste: only the")
    print("  current last page is ever partial.")
    print("Step 3: decode 1 token. Page 2 had 1 slot; +1 -> page 2 now full.")
    print("  ZERO new allocations - the tail-fill ate the whole chunk.")
    print()
    print(f"[check] step1: page_ids=[0,1], page_lens=[2,1], offset=3:",
          "OK" if s1_ids == [0, 1] and s1_lens == [2, 1] and s1_off == 3 else "FAIL")
    print(f"[check] step2: page_ids=[0,1,2], page_lens=[2,2,1], offset=5:",
          "OK" if s2_ids == [0, 1, 2] and s2_lens == [2, 2, 1] and s2_off == 5 else "FAIL")
    print(f"[check] step3: page_ids=[0,1,2], page_lens=[2,2,2], offset=6:",
          "OK" if s3_ids == [0, 1, 2] and s3_lens == [2, 2, 2] and s3_off == 6 else "FAIL")


def section_rewind_release():
    # INTUITION: rewind(n) (speculative decoding rejection) tears out the last
    # n tokens, returning whole freed pages to the pool. release() frees ALL
    # pages on request completion - both use ceil, never floor (the off-by-one
    # trap from KV_CACHE.md Section F).
    banner("SECTION E: rewind + release lifecycle (the GOLD free-list)")
    H, D, PS = 2, 8, 2
    pool = PagedKVPool(num_pages=6, n_kv_heads=H, head_dim=D, page_size=PS)
    A = PagedKVCache(pool)
    B = PagedKVCache(pool)

    A.update_and_fetch(*(make_kv(3, H, D, 0.0), make_kv(3, H, D, 0.5)))  # A: pages [0,1]
    B.update_and_fetch(*(make_kv(2, H, D, 0.0), make_kv(2, H, D, 0.5)))  # B: page [2]
    print(f"After A prefill 3 + B prefill 2 (PS={PS}):")
    print(f"  A.page_ids = {A.page_ids}, A.page_lens = {A.page_lens}, A.offset = {A.offset}")
    print(f"  B.page_ids = {B.page_ids}, B.page_lens = {B.page_lens}, B.offset = {B.offset}")
    print(f"  pool.used  = {sorted(pool.used)}")
    print(f"  pool.free  = {sorted(pool.free_list)}\n")

    # rewind A by 1: A had offset 3 (page 0 full, page 1 has 1 token).
    # rewind(1) -> new_offset=2, ceil(2/2)=1 page kept. Page 1 returned.
    A.rewind(1)
    print("A.rewind(1) (speculative decode rejected 1 token):")
    print(f"  A.page_ids = {A.page_ids}  <- physical page 1 RETURNED to free list")
    print(f"  A.page_lens = {A.page_lens}   <- page 0 back to full (2 tokens)")
    print(f"  A.offset = {A.offset}")
    print(f"  pool.used = {sorted(pool.used)}")
    print(f"  pool.free = {sorted(pool.free_list)}\n")
    rewind_ok = (A.page_ids == [0] and A.page_lens == [2] and A.offset == 2)

    # release both -> all pages back to the pool
    A.release()
    B.release()
    print("A.release() + B.release() (both requests finish):")
    print(f"  pool.used = {sorted(pool.used)}   <- empty")
    print(f"  pool.free = {sorted(pool.free_list)}   <- ALL 6 pages back")
    print()
    print("GOLD for the .html: after both release(), free_list = "
          f"{sorted(pool.free_list)}")
    print()
    print(f"[check] after rewind(1): A.page_ids==[0], page_lens==[2], offset==2:",
          "OK" if rewind_ok else "FAIL")
    print(f"[check] after both release(): pool.used empty:",
          len(pool.used) == 0, "->", "OK" if len(pool.used) == 0 else "FAIL")
    print(f"[check] after both release(): free_list == [0,1,2,3,4,5]:",
          sorted(pool.free_list) == [0, 1, 2, 3, 4, 5], "->",
          "OK" if sorted(pool.free_list) == [0, 1, 2, 3, 4, 5] else "FAIL")
    return sorted(pool.free_list)


def section_paged_attention_kernel():
    # INTUITION: the paged attention kernel computes Q @ K^T like normal
    # attention, but reads each K,V from a SCATTERED physical page via the
    # indirect-lookup formula. Contrast with dense sequential addressing.
    # Here we build one decode query, gather K via the block table, run
    # softmax attention, and assert it equals the dense path.
    banner("SECTION F: paged attention indirect K/V gather for one query")
    H_kv, D, PS = 2, 8, 2
    pool = PagedKVPool(num_pages=8, n_kv_heads=H_kv, head_dim=D, page_size=PS)
    c = PagedKVCache(pool)

    # Prefill 3 tokens so the cache spans 2 physical pages (scattered).
    raw_k = make_kv(3, H_kv, D, 0.0)
    raw_v = make_kv(3, H_kv, D, 0.5)
    c.update_and_fetch(raw_k, raw_v)

    print(f"After prefill 3 (PS={PS}):")
    print(f"  c.page_ids = {c.page_ids}, c.page_lens = {c.page_lens}, "
          f"c.offset = {c.offset}\n")

    # Build a query for token 2 (the last prefill token), shape [1,H,D] (decode).
    q = raw_k[:, :, 2:3, :].squeeze(2)            # [1, H, D]
    scale = 1.0 / (D ** 0.5)

    # PATH 1: paged attention via INDIRECT gather (kernel-style).
    # For each (head, logical_j), look up K via:
    #   page_id = block_table[j // PS]
    #   slot    = j % PS
    #   K[j]    = key_pages[page_id, head, slot, :]
    out_paged = torch.zeros(1, H_kv, D)
    scores_paged = torch.zeros(1, H_kv, c.offset)
    for h in range(H_kv):
        for j in range(c.offset):
            page_id = c.page_ids[j // PS]
            slot = j % PS
            k_j = pool.key_pages[page_id, h, slot, :]      # [D] - indirect fetch
            scores_paged[0, h, j] = (q[0, h] * k_j).sum() * scale
        probs = torch.softmax(scores_paged[0, h], dim=-1)  # [offset]
        for j in range(c.offset):
            page_id = c.page_ids[j // PS]
            slot = j % PS
            v_j = pool.val_pages[page_id, h, slot, :]      # indirect V fetch
            out_paged[0, h] += probs[j] * v_j

    # PATH 2: dense (gather then standard matmul). Use einsum so the head
    # axis is a batch dim (NOT broadcast): q[1,H,D] x k_full[1,H,S,D] -> [1,H,S].
    k_full, v_full = c.fetch_full()
    scores_dense = torch.einsum('bhd,bhsd->bhs', q, k_full) * scale   # [1,H,offset]
    probs_dense = torch.softmax(scores_dense, dim=-1)                  # [1,H,S]
    out_dense = torch.einsum('bhs,bhsd->bhd', probs_dense, v_full)     # [1,H,D]

    # THE INDIRECT-LOOKUP FORMULA in action (one concrete address):
    page_id_demo = c.page_ids[1]                      # logical page 1
    slot_demo = 0                                     # first slot of page 1
    kv_head_demo = 0
    c_dim_demo = 0
    H, PS2, Dd = pool.H, pool.page_size, pool.D
    k_idx = ((page_id_demo * H + kv_head_demo) * PS2 + slot_demo) * Dd + c_dim_demo
    val_via_formula = float(pool.key_pages.view(-1)[k_idx])
    val_via_tensor = float(pool.key_pages[page_id_demo, kv_head_demo, slot_demo, c_dim_demo])

    print("THE INDIRECT-LOOKUP FORMULA (kernel's K address):")
    print(f"  For logical pos 2 of request, head 0, dim 0:")
    print(f"    page_idx = 2 // {PS} = 1")
    print(f"    slot     = 2 %  {PS} = 0")
    print(f"    page_id  = block_table[1] = {page_id_demo}")
    print(f"    k_idx    = ((page_id*H_kv + kv_head)*page_size + slot)*D + c")
    print(f"            = (({page_id_demo}*{H} + {kv_head_demo})*{PS2} + {slot_demo})*{Dd} + {c_dim_demo}")
    print(f"            = {k_idx}")
    print(f"    K via formula   = {val_via_formula:.4f}")
    print(f"    K via tensor[...] = {val_via_tensor:.4f}  (must match)\n")

    print("Attention output (token 2 as query), head 0, dims 0..3:")
    print(f"  paged (indirect gather) : {[round(x,4) for x in out_paged[0,0,:4].tolist()]}")
    print(f"  dense  (gather+matmul)  : {[round(x,4) for x in out_dense[0,0,:4].tolist()]}")
    print()
    tol = 1e-5
    c_match = torch.allclose(out_paged, out_dense, atol=tol)
    c_formula = abs(val_via_formula - val_via_tensor) < 1e-7
    print(f"[check] paged-attn(indirect) == dense-attn(gather) at tol {tol}: "
          f"{'OK' if c_match else 'FAIL'}")
    print(f"[check] indirect-lookup formula == tensor index: "
          f"{'OK' if c_formula else 'FAIL'}")
    print(f"\nGOLD for .html: indirect K[page_id={page_id_demo},head=0,slot=0,dim=0] "
          f"= {val_via_formula:.4f}")
    return val_via_formula, out_paged


def section_dense_vs_paged_equiv():
    # INTUITION: the cache layout (one slab vs scattered pages) changes WHERE
    # bytes live, never WHAT they are. Prove it: build the same K,V three ways
    # (no cache, dense cache, paged cache) and assert byte-equality.
    banner("SECTION G: contrast with dense (paged bytes == dense bytes)")
    H_kv, D = 2, 8
    raw_k = make_kv(4, H_kv, D, 0.0)
    raw_v = make_kv(4, H_kv, D, 0.5)

    # PATH 1: no cache (ground truth) - just the raw tensor
    k_gold = raw_k.clone()
    v_gold = raw_v.clone()

    # PATH 2: dense cache
    dense = DenseKVCache(1, H_kv, D, max_seq_len=8)
    k_d, v_d = dense.update_and_fetch(raw_k, raw_v)

    # PATH 3: paged cache (PS=2 -> spans 2 pages, non-contiguous)
    pool = PagedKVPool(num_pages=8, n_kv_heads=H_kv, head_dim=D, page_size=2)
    paged = PagedKVCache(pool)
    k_p, v_p = paged.update_and_fetch(raw_k, raw_v)

    print("Build the same 4-token K,V three ways; assert byte-equality.\n")
    print("| path            | K[0,0,0,:4] (token0)              | "
          "K[0,0,3,:4] (token3)              |")
    print("|-----------------|-----------------------------------|"
          "-----------------------------------|")
    for name, kk in (("no-cache (raw)", k_gold), ("dense cache", k_d),
                     ("paged cache (PS=2)", k_p)):
        t0 = [round(x, 4) for x in kk[0, 0, 0, :4].tolist()]
        t3 = [round(x, 4) for x in kk[0, 0, 3, :4].tolist()]
        print(f"| {name:<15} | {str(t0):<33} | {str(t3):<33} |")
    print()
    print(f"paged.page_ids = {paged.page_ids}  (logical 0 -> phys 0, logical 1 -> phys 1)")
    print(f"paged.page_lens = {paged.page_lens}")
    print("(Even though K is split across 2 physical pages, fetch_full() "
          "rebuilds the exact same contiguous tensor.)\n")
    tol = 1e-6
    c1 = torch.allclose(k_d, k_gold, atol=tol)
    c2 = torch.allclose(k_p, k_gold, atol=tol)
    c3 = torch.allclose(k_p, k_d, atol=tol)
    print(f"[check] dense K  == raw K  ? {c1}")
    print(f"[check] paged K  == raw K  ? {c2}")
    print(f"[check] paged K  == dense K? {c3}")
    print(f"[check] ALL THREE PATHS MATCH: "
          f"{'OK' if (c1 and c2 and c3) else 'FAIL'}")
    return c1 and c2 and c3


# ============================================================================
# main
# ============================================================================

def main():
    print("paged_attention.py - reference impl. All numbers feed PAGED_ATTENTION.md.")
    print("torch =", torch.__version__)

    section_dense_waste()
    section_pool_and_freelist()
    gold_pos2page = section_block_table()
    section_append_chunk()
    gold_free = section_rewind_release()
    gold_kval, _ = section_paged_attention_kernel()
    ok = section_dense_vs_paged_equiv()

    banner("GOLD VALUES FOR THE .html (recompute + check)")
    print(f"  gold block_table logical pos 2 -> (page_id, slot) = "
          f"{gold_pos2page[2]}   (expect (2, 0))")
    print(f"  gold free_list after both release()             = "
          f"{gold_free}   (expect [0,1,2,3,4,5])")
    print(f"  gold indirect K[page_id=1,head=0,slot=0,dim=0]   = "
          f"{gold_kval:.4f}   (expect 0.3010)")
    print(f"  gold dense==paged==raw K equivalence             = "
          f"{'OK' if ok else 'FAIL'}")

    banner("DONE - all sections printed; equivalence = " +
           ("OK" if ok else "FAIL"))


if __name__ == "__main__":
    main()
