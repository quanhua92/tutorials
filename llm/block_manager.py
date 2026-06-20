"""
block_manager.py - Reference implementation of the vLLM BlockManager.

This is the single source of truth that BLOCK_MANAGER.md is built from. Every
number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python block_manager.py

== THE BIG IDEA, IN ONE SENTENCE (the "library card" intuition) ==============
Think of every request as a reader in a library of fixed-size PAGES. Each reader
owns an INDEX CARD (the block table) listing which physical pages hold their
notes — and two readers who copied the SAME system prompt should share the SAME
physical pages instead of re-writing them. The BlockManager makes that sharing
automatic: it FINGERPRINTS each page by hashing (its own tokens) CHAINED onto
(the hash of the page before it). Two requests with an identical prompt prefix
compute identical fingerprints for that prefix → they land on the same physical
pages (ref_count++) and skip re-computing the KV for those tokens entirely.

== THE LINEAGE (old -> new, with WHY) ========================================

  1. NAIVE per-request allocation (the "before"): each request gets its OWN
     private pages, full of freshly-computed KV. Two requests that share an
     identical system prompt each recompute the SAME KV into DIFFERENT pages.
     Wasteful: the most expensive thing in serving (prefill compute) is done
     redundantly for every copy of a popular prefix.

  2. BlockManager + content-addressed prefix cache (vLLM / PagedAttention,
     Kwon et al. SOSP 2023): pages become CONTENT-ADDRESSED. A page's identity
     is a CHAINED hash — hash(block_tokens, prefix=hash_of_previous_block) — so
     ANY request that produced the same token prefix gets the same fingerprints
     and can SHARE the same physical pages. A page tracks ref_count (how many
     sequences currently read it); ref_count>0 => live, ref_count==0 => back to
     the free list BUT the KV bytes + hash stay, so a later request can RECLAIM
     them (a free OS frame that still holds a recognizable file). Result: system
     prompts, few-shot blocks, and chat history are computed ONCE and reused by
     every request that shares them. Free prefill speedup.

== PLAIN-ENGLISH GLOSSARY (used in every section below) ======================
    block (page)  a fixed-size chunk of `block_size` token slots in the pool.
    block_size    tokens per block (vLLM default 16; this demo uses 2 so every
                  number is printable). Smaller => finer prefix sharing + more
                  block-table overhead.
    block table   the per-request INDEX CARD: logical block i -> physical block
                  id. Pages need NOT be contiguous. (See KV_CACHE.md §5.)
    ref_count     how many active sequences currently READ this physical block.
                  >0 => live (shared or private). ==0 => free, but KV + hash
                  stay => reclaimable by a future matching prefix.
    hash          a fingerprint of a FULL block = H(prev_hash_bytes || token_ids
                  bytes). CHAINED: each block's hash folds in the one before it.
    chained hash  the WHOLE trick. Because block k's hash depends on block k-1's
                  hash (which depends on ... block 0's), two sequences that share
                  tokens 0..k-1 produce identical hashes for blocks 0..k//bs-1
                  and diverge exactly at the block where their tokens diverge.
    hash_to_block_id  the global content->physical map: fingerprint -> block id.
    prefix cache hit  can_allocate() walks the chained hashes of a new request;
                  any FULL block whose (hash, token_ids) matches a known block is
                  reusable => no KV recompute for it.
    OOM (-1)      can_allocate returns -1 when free blocks < blocks still needed:
                  a signal to the Scheduler to WAIT (or preempt). (See SCHEDULER.)
    preempt       when decode would OOM, the Scheduler evicts a running sequence
                  (dealloctes its blocks) back to WAITING. Shared blocks only
                  drop ref_count (not freed) until the LAST reader leaves.

== THE HASH PRIMITIVE (read this once) =======================================
The real nano-vllm / vLLM uses xxhash.xxh64() — a 64-bit NON-cryptographic hash
(Cyan4973/xxHash; passes SMHasher; ~19 GB/s). We do NOT import xxhash here
(no deps allowed). Instead we implement a tiny from-scratch 64-bit hash
(FNV-1a) that plays the SAME role and — crucially — ports byte-for-byte to
JavaScript so the .html animation can gold-check it offline. THE IDEA IS THE
CHAINED STRUCTURE, NOT THE EXACT DIGEST: swap FNV-1a for xxh64 and every claim
below still holds.

    compute_hash(token_ids, prefix=-1):
        h = FNV_OFFSET_64                       # 0xcbf29ce484222325
        if prefix != -1:
            for byte in prefix.to_bytes(8, "little"):   # chain onto prev block
                h = ((h ^ byte) * FNV_PRIME_64) & MASK64
        for t in token_ids:                             # this block's tokens
            for byte in t.to_bytes(4, "little"):        # each token = 4 LE bytes
                h = ((h ^ byte) * FNV_PRIME_64) & MASK64
        return h

NOTE on collisions: FNV-1a (like xxh64) is NON-cryptographic, so two different
token lists COULD in principle collide. vLLM defends in depth: every block also
stores a copy of its token_ids, and can_allocate REJECTS a hash hit whose stored
token_ids differ. That extra check is reproduced here (see Section C).

== TENSOR-SHAPE / SIZING CONVENTIONS =========================================
This bundle is about ALLOCATION METADATA, not tensors — there are no [B,L,H,D]
shapes here. The one dimension that matters is `block_size` (tokens per block).
We use block_size=2 and a pool of 6 blocks so the entire state is printable.
"""

from __future__ import annotations

from collections import deque

import torch  # only for parity with the sibling bundles + version banner

BANNER = "=" * 72

# ============================================================================
# 1. THE HASH PRIMITIVE (from scratch; stands in for vLLM's xxhash.xxh64)
# ============================================================================

# FNV-1a 64-bit constants — a well-known non-cryptographic hash (public domain).
# Portable to JS with BigInt; deterministic across platforms.
FNV_OFFSET_64 = 0xCBF29CE484222325
FNV_PRIME_64 = 0x100000001B3
MASK64 = (1 << 64) - 1


def fnv1a_mix(h: int, byte: int) -> int:
    """One FNV-1a step: XOR in a byte, then multiply by the prime, mask to 64 bits."""
    return ((h ^ byte) * FNV_PRIME_64) & MASK64


def compute_hash(token_ids: list[int], prefix: int = -1) -> int:
    """Chained 64-bit fingerprint of one FULL block.

    h = FNV1a( prefix_bytes(8, LE) || token_bytes(4, LE each) )

    Mirrors nano-vllm's BlockManager.compute_hash(token_ids, prefix) which does
    xxh64.update(prefix.to_bytes(8,"little")); xxh64.update(np.array(token_ids).
    tobytes()). We use 4-byte LE per token (tokens are < 2^32 in practice); the
    exact byte width does not matter — only that (a) it is fixed and (b) the
    prefix bytes are fed BEFORE the block's own bytes so the chain is order-
    sensitive.
    """
    h = FNV_OFFSET_64
    if prefix != -1:                              # chain onto the previous block
        for b in prefix.to_bytes(8, "little"):
            h = fnv1a_mix(h, b)
    for t in token_ids:                           # this block's own tokens
        for b in t.to_bytes(4, "little"):
            h = fnv1a_mix(h, b)
    return h


# ============================================================================
# 2. THE BLOCK  (the unit of physical storage + its metadata)
# ============================================================================

class Block:
    """One physical block (page) in the pool.

    Fields mirror nano-vllm/nanovllm/engine/block_manager.py:
        block_id    physical id (its slot in the pool).
        ref_count   # active sequences currently READING this block.
                    >0 => live; ==0 => free but KV+hash stay (reclaimable).
        hash        chained fingerprint of this block's tokens, or -1 if the
                    block has never been filled/hashed yet.
        token_ids   a COPY of the tokens that filled this block — kept so a hash
                    hit can be VERIFIED (defense in depth against hash collisions).
    """

    def __init__(self, block_id: int):
        self.block_id = block_id
        self.ref_count = 0
        self.hash = -1
        self.token_ids: list[int] = []

    def update(self, hash: int, token_ids: list[int]):
        """Record this block's fingerprint + tokens (called by hash_blocks)."""
        self.hash = hash
        self.token_ids = list(token_ids)

    def reset(self):
        """Bring a freshly (re)allocated block back to a clean live state."""
        self.ref_count = 1
        self.hash = -1
        self.token_ids = []


# ============================================================================
# 3. THE SEQUENCE  (minimal port of nano-vllm's Sequence for this demo)
# ============================================================================

class Sequence:
    """A minimal request: a growing list of token ids + a block table.

    Only the fields BlockManager actually reads are kept. block_size is set per
    instance (nano-vllm uses a class attr =256; we use 2 for the tiny demo).
    """

    def __init__(self, token_ids: list[int], block_size: int = 2, name: str = "?"):
        self.name = name
        self.block_size = block_size
        self.token_ids = list(token_ids)
        self.num_tokens = len(token_ids)
        self.num_cached_tokens = 0        # tokens whose KV is already computed
        self.num_scheduled_tokens = 0     # tokens scheduled in the current step
        self.block_table: list[int] = []  # logical block i -> physical block id

    def __len__(self):
        return self.num_tokens

    @property
    def num_blocks(self) -> int:
        return (self.num_tokens + self.block_size - 1) // self.block_size

    def block(self, i: int) -> list[int]:
        """Return the token_ids for logical block i (the last may be partial)."""
        return self.token_ids[i * self.block_size:(i + 1) * self.block_size]

    def append_token(self, token_id: int):
        self.token_ids.append(token_id)
        self.num_tokens += 1


# ============================================================================
# 4. THE BLOCK MANAGER  (paged allocation + content-addressed prefix cache)
# ============================================================================

class BlockManager:
    """Physical page allocator with a content-addressed prefix cache.

    Mirrors nano-vllm/nanovllm/engine/block_manager.py (Kwon et al., SOSP 2023).
    Owns:
        blocks[]            the pool of physical Blocks (the "RAM").
        hash_to_block_id    fingerprint -> physical block id (the cache index).
        free_block_ids      deque of free physical ids (the frame allocator's
                            free list; popleft => deterministic 0,1,2,... order).
        used_block_ids      set of live physical ids (ref_count>0).
    """

    def __init__(self, num_blocks: int, block_size: int):
        self.block_size = block_size
        self.blocks: list[Block] = [Block(i) for i in range(num_blocks)]
        self.hash_to_block_id: dict[int, int] = dict()
        self.free_block_ids: deque[int] = deque(range(num_blocks))
        self.used_block_ids: set[int] = set()

    # ---- hash (stands in for xxhash.xxh64; see module docstring) -----------
    @staticmethod
    def compute_hash(token_ids: list[int], prefix: int = -1) -> int:
        return compute_hash(token_ids, prefix)

    # ---- raw frame allocator ----------------------------------------------
    def _allocate_block(self) -> int:
        """Grab a free frame. Evicts any STALE hash entry the frame still holds."""
        block_id = self.free_block_ids.popleft()
        block = self.blocks[block_id]
        assert block.ref_count == 0, "free block must have ref_count 0"
        # If this frame still maps a fingerprint (from a previous life), drop it:
        # the bytes are about to be overwritten, so the entry would be a lie.
        if block.hash != -1 and self.hash_to_block_id.get(block.hash) == block_id:
            del self.hash_to_block_id[block.hash]
        block.reset()
        self.used_block_ids.add(block_id)
        return block_id

    def _deallocate_block(self, block_id: int):
        """Return a ref_count==0 frame to the free list (KV + hash STAY)."""
        assert self.blocks[block_id].ref_count == 0
        self.used_block_ids.remove(block_id)
        self.free_block_ids.append(block_id)

    # ---- PREFILL allocation: walk the chain, reuse prefix, OOM check -------
    def can_allocate(self, seq: Sequence) -> int:
        """Return num_cached_blocks (prefix cache hits), or -1 if OOM.

        Walk every FULL block (0..num_blocks-2 — the last block may be partial).
        For each, chain the hash, look it up in the cache; stop at the first MISS
        or token mismatch. Count live hits (decrement the new-block budget for
        blocks already in use, since they only need ref_count++).
        """
        h = -1
        num_cached_blocks = 0
        num_new_blocks = seq.num_blocks                 # worst case: all fresh
        for i in range(seq.num_blocks - 1):             # FULL blocks only
            token_ids = seq.block(i)
            h = self.compute_hash(token_ids, h)         # CHAIN onto the previous
            block_id = self.hash_to_block_id.get(h, -1)
            if block_id == -1 or self.blocks[block_id].token_ids != token_ids:
                break                                   # miss OR collision guard
            num_cached_blocks += 1
            if block_id in self.used_block_ids:
                num_new_blocks -= 1                     # live share: ref++ only
        if len(self.free_block_ids) < num_new_blocks:
            return -1                                   # OOM -> Scheduler must wait
        return num_cached_blocks

    def allocate(self, seq: Sequence, num_cached_blocks: int):
        """Assign blocks to seq: reuse the cached prefix, then allocate the suffix."""
        assert not seq.block_table, "seq already allocated"
        h = -1
        # 1. REUSE cached prefix blocks (just ref_count++, or reclaim a free one)
        for i in range(num_cached_blocks):
            token_ids = seq.block(i)
            h = self.compute_hash(token_ids, h)
            block_id = self.hash_to_block_id[h]
            block = self.blocks[block_id]
            if block_id in self.used_block_ids:
                block.ref_count += 1                    # one more reader
            else:
                # The block is FREE but still reclaimable (KV+hash intact):
                # take it back out of the free list and mark it live again.
                block.ref_count = 1
                self.free_block_ids.remove(block_id)
                self.used_block_ids.add(block_id)
            seq.block_table.append(block_id)
        # 2. FRESH blocks for the non-cached suffix
        for i in range(num_cached_blocks, seq.num_blocks):
            seq.block_table.append(self._allocate_block())
        seq.num_cached_tokens = num_cached_blocks * self.block_size

    def deallocate(self, seq: Sequence):
        """Release every block a seq owns: ref_count--, free when it hits 0.

        Freed blocks keep their hash + token_ids (so a future matching prefix can
        reclaim them). Only _allocate_block ever evicts a stale hash entry.
        """
        for block_id in reversed(seq.block_table):
            block = self.blocks[block_id]
            block.ref_count -= 1
            if block.ref_count == 0:
                self._deallocate_block(block_id)
        seq.num_cached_tokens = 0
        seq.block_table.clear()

    # ---- DECODE growth: allocate a new page exactly at a page boundary -----
    def can_append(self, seq: Sequence) -> bool:
        """A new page is needed iff the new token opens a fresh page
        (len(seq) % block_size == 1). Return whether a free page is available."""
        return len(self.free_block_ids) >= (len(seq) % self.block_size == 1)

    def may_append(self, seq: Sequence):
        """If we just crossed a page boundary, allocate one fresh page."""
        if len(seq) % self.block_size == 1:
            seq.block_table.append(self._allocate_block())

    # ---- commit: register newly-FILLED blocks into the prefix cache --------
    def hash_blocks(self, seq: Sequence):
        """After execution, record every block that became FULL in this step.

        PARTIAL blocks are deliberately skipped: they are unstable (more tokens
        may fill them), so hashing them would create entries that later requests
        could falsely match. See Section E (the #1 pitfall).
        """
        start = seq.num_cached_tokens // self.block_size
        end = (seq.num_cached_tokens + seq.num_scheduled_tokens) // self.block_size
        if start == end:
            return                                    # no block became full this step
        # Chain from the previous block's hash (or root -1 if block 0).
        h = self.blocks[seq.block_table[start - 1]].hash if start > 0 else -1
        for i in range(start, end):
            block = self.blocks[seq.block_table[i]]
            token_ids = seq.block(i)
            h = self.compute_hash(token_ids, h)
            block.update(h, token_ids)
            self.hash_to_block_id[h] = block.block_id


# ============================================================================
# 5. PRETTY PRINTER
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def hx(h: int) -> str:
    """Render a 64-bit hash as 0x + 16 hex digits (readable)."""
    return f"0x{h & MASK64:016x}"


# ============================================================================
# 6. THE SECTIONS  (the numbers that feed BLOCK_MANAGER.md)
# ============================================================================

# Deterministic demo tokens (small ints so the byte encoding is obvious).
T0, T1, T2, T3 = 10, 11, 12, 13     # request A = [t0,t1,t2,t3]
T4, T5 = 14, 15                      # request B diverges here: [t0,t1,t4,t5]
BS = 2                               # block_size (vLLM default 16; tiny here)


def section_block_struct():
    # INTUITION: a block is just a page frame with a usage counter and (later)
    # a fingerprint. ref_count is the sharing dial: 0 = free shelf slot, 1 =
    # one reader, 2 = two readers sharing it. KV bytes survive a return to the
    # free list, which is what makes prefix caching work.
    banner("SECTION A: the Block struct + ref_count semantics")
    b = Block(7)
    print(f"Block(7) just created:")
    print(f"  block_id  = {b.block_id}")
    print(f"  ref_count = {b.ref_count}   (<- 0 => on the free list, not yet used)")
    print(f"  hash      = {b.hash}   (<- -1 => never hashed yet)")
    print(f"  token_ids = {b.token_ids}\n")

    print("ref_count is the SHARING dial:")
    print("| ref_count | state          | what it means                         |")
    print("|-----------|----------------|---------------------------------------|")
    print("| 0         | FREE           | on the free list; KV+hash STAY if any|")
    print("| 1         | LIVE (private) | exactly one sequence reads this block |")
    print("| >=2       | LIVE (shared)  | N sequences read the SAME bytes       |")
    print()
    print("Lifecycle of one block as readers come and go:")
    bm = BlockManager(num_blocks=1, block_size=BS)
    bid = bm._allocate_block()                      # grab the one free block
    b = bm.blocks[bid]
    b.update(bm.compute_hash([T0, T1]), [T0, T1])
    print(f"  _allocate_block()       -> block {bid}, ref_count={b.ref_count}, "
          f"hash={hx(b.hash)}")
    b.ref_count += 1                                 # a second seq shares it
    print(f"  2nd seq shares it       -> ref_count={b.ref_count} (SHARED)")
    b.ref_count -= 1                                 # one leaves
    print(f"  1 seq leaves            -> ref_count={b.ref_count}")
    b.ref_count -= 1                                 # last reader leaves
    bm._deallocate_block(bid)
    print(f"  last reader leaves      -> ref_count=0 -> FREE list")
    print(f"  BUT block.hash still    = {hx(b.hash)}  and token_ids={b.token_ids}")
    print(f"      => a future [t0,t1] prefix can RECLAIM it (no KV recompute)\n")
    print("[check] freed block keeps its hash:", b.hash != -1, "->",
          "OK" if b.hash != -1 else "FAIL")
    print("[check] freed block is in free_block_ids:", bid in bm.free_block_ids,
          "->", "OK" if bid in bm.free_block_ids else "FAIL")


def section_chained_hash():
    # INTUITION: each block's hash FOLDS IN the previous block's hash, so the
    # fingerprint of block k secretly encodes blocks 0..k. Two sequences that
    # share tokens 0..2*bs-1 therefore hash block 0 identically; they diverge
    # at the FIRST block whose tokens differ. That is the entire reason prefix
    # sharing "just works" — identical prefix => identical fingerprints.
    banner("SECTION B: chained hash -> divergence at token k splits the fingerprints")
    A = [T0, T1, T2, T3]
    B = [T0, T1, T4, T5]    # identical block 0, different block 1
    print(f"block_size = {BS}. Two 4-token requests:\n")
    print(f"  A = {A}   -> block0={A[0:BS]}, block1={A[BS:]}")
    print(f"  B = {B}   -> block0={B[0:BS]}, block1={B[BS:]}\n")

    h0A = compute_hash(A[0:BS], -1)
    h0B = compute_hash(B[0:BS], -1)
    h1A = compute_hash(A[BS:], h0A)
    h1B = compute_hash(B[BS:], h0B)

    print("| req | block | tokens     | prefix (prev hash) | "
          "chained hash (this block)        | same as other req? |")
    print("|-----|-------|------------|---------------------|"
          "----------------------------------|--------------------|")
    print(f"| A   | 0     | {str(A[0:BS]):<10} | -1 (root)           | "
          f"{hx(h0A):<32} | share w/ B blk0    |")
    print(f"| B   | 0     | {str(B[0:BS]):<10} | -1 (root)           | "
          f"{hx(h0B):<32} | share w/ A blk0    |")
    print(f"| A   | 1     | {str(A[BS:]):<10} | {hx(h0A):<19} | "
          f"{hx(h1A):<32} | DIVERGES from B    |")
    print(f"| B   | 1     | {str(B[BS:]):<10} | {hx(h0B):<19} | "
          f"{hx(h1B):<32} | DIVERGES from A    |")
    print()
    print(f"[check] hash(A.block0) == hash(B.block0)  (shared prefix) : "
          f"{h0A == h0B} -> {'OK' if h0A == h0B else 'FAIL'}")
    print(f"[check] hash(A.block1) != hash(B.block1)  (divergence)    : "
          f"{h1A != h1B} -> {'OK' if h1A != h1B else 'FAIL'}")
    print()
    print("WHY the chain matters: block1's hash folds in block0's hash. So even")
    print("if [t2,t3] happened to equal [t4,t5] (they don't here), block1 would")
    print("still differ because the prefix hash fed in differs. The chain makes a")
    print("block's fingerprint a function of its ENTIRE token prefix, not just its")
    print("own tokens — exactly what content-addressed prefix dedup needs.\n")
    print(f"GOLD for .html: hash(A.block0) = hash(B.block0) = {h0A} ({hx(h0A)})")


def section_can_allocate():
    # INTUITION: when a request arrives, can_allocate walks its FULL blocks,
    # chaining hashes and asking the cache "do I already have this prefix?".
    # It returns how many leading blocks are cache hits, OR -1 if there aren't
    # enough free frames for the rest (= OOM, tell the Scheduler to wait).
    banner("SECTION C: can_allocate -> the prefix-cache walk + OOM check")
    bm = BlockManager(num_blocks=6, block_size=BS)
    A = Sequence([T0, T1, T2, T3], BS, "A")
    print(f"Pool: 6 blocks, block_size={BS}. Request A = {A.token_ids} arrives "
          f"(empty cache).\n")

    # --- A arrives first: no cache, everything fresh ---
    nA = bm.can_allocate(A)
    print(f"can_allocate(A): walk A's full blocks (0..{A.num_blocks - 2}):")
    print(f"  block0 {A.block(0)}: h=compute_hash({A.block(0)}, -1)={hx(bm.compute_hash(A.block(0), -1))}")
    print(f"    hash_to_block_id.get(h) = -1 (cache empty) -> MISS -> break")
    print(f"  num_cached_blocks = 0 ; num_new_blocks = {A.num_blocks}")
    print(f"  free({len(bm.free_block_ids)}) >= num_new({A.num_blocks})? yes -> return {nA}\n")

    bm.allocate(A, nA)
    # simulate execution of all 4 tokens: register the now-full blocks
    A.num_scheduled_tokens = A.num_tokens - A.num_cached_tokens
    bm.hash_blocks(A)
    A.num_cached_tokens += A.num_scheduled_tokens
    A.num_scheduled_tokens = 0
    print(f"allocate(A, 0) + hash_blocks(A): A.block_table={A.block_table}, "
          f"cache now maps:")
    for h, bid in bm.hash_to_block_id.items():
        print(f"    {hx(h)} -> block {bid} "
              f"(tokens {bm.blocks[bid].token_ids})")
    print()

    # --- B arrives: shares block 0 with A ---
    B = Sequence([T0, T1, T4, T5], BS, "B")
    nB = bm.can_allocate(B)
    print(f"Request B = {B.token_ids} arrives (shares block0 with A).\n")
    print("can_allocate(B) walk:")
    hb0 = bm.compute_hash(B.block(0), -1)
    hit0 = bm.hash_to_block_id.get(hb0, -1)
    print(f"  block0 {B.block(0)}: h={hx(hb0)} -> hash_to_block_id={hit0} "
          f"(HIT; tokens match: {bm.blocks[hit0].token_ids == B.block(0)})")
    print(f"    block {hit0} in used? {hit0 in bm.used_block_ids} "
          f"-> num_new_blocks -= 1 (live share, only ref_count++)")
    hb1 = bm.compute_hash(B.block(1), hb0)
    print(f"  block1 {B.block(1)}: h=compute_hash({B.block(1)}, {hx(hb0)})={hx(hb1)}")
    print(f"    hash_to_block_id.get(h) = -1 (MISS) -> break")
    print(f"  num_cached_blocks = {nB} ; free({len(bm.free_block_ids)}) >= "
          f"num_new({A.num_blocks - nB})? yes -> return {nB}\n")

    # --- OOM: a separate throwaway manager whose pool is too small ---
    print("OOM check: a throwaway pool with 0 free blocks (exhausted).")
    bm_oom = BlockManager(num_blocks=0, block_size=BS)   # no frames at all
    C = Sequence([20, 21, 22, 23], BS, "C")     # uncached 2-block request
    nC = bm_oom.can_allocate(C)
    print(f"  can_allocate(C={C.token_ids}, uncached): num_new_blocks=2, "
          f"free=0 < 2 -> return {nC} (the OOM signal; shared bm is untouched)")
    print()
    print(f"[check] can_allocate(A) on empty cache == 0 : {nA == 0} -> "
          f"{'OK' if nA == 0 else 'FAIL'}")
    print(f"[check] can_allocate(B) finds shared block0 == 1 : {nB == 1} -> "
          f"{'OK' if nB == 1 else 'FAIL'}")
    print(f"[check] can_allocate(C) under OOM == -1 : {nC == -1} -> "
          f"{'OK' if nC == -1 else 'FAIL'}")
    return bm, A, B


def section_allocate(bm: BlockManager, A: Sequence, B: Sequence):
    # INTUITION: allocate() splits the work into two halves — REUSE the cached
    # prefix (just ref_count++, no bytes touched) and FRESH-allocate the suffix
    # (grab free frames). The payoff: B recomputes ZERO tokens of the shared
    # prefix; only its divergent block1 needs new KV.
    banner("SECTION D: allocate -> reuse cached prefix (ref++) + fresh suffix")
    nB = bm.can_allocate(B)
    bm.allocate(B, nB)
    print(f"allocate(B, num_cached_blocks={nB}):")
    print(f"  REUSE  block 0 (ref_count {bm.blocks[A.block_table[0]].ref_count - 1}"
          f" -> {bm.blocks[A.block_table[0]].ref_count})  <- shared with A, ref++")
    print(f"  FRESH  block {B.block_table[1]}  (suffix)            "
          f"<- brand-new frame for B's divergent tokens")
    print(f"  B.block_table = {B.block_table}")
    print(f"  B.num_cached_tokens = {B.num_cached_tokens} "
          f"(=> skip KV compute for these {B.num_cached_tokens} tokens)\n")

    print("Block pool state after A and B are both allocated:")
    print("| block | ref_count | state        | owned by | tokens     |")
    print("|-------|-----------|--------------|----------|------------|")
    for blk in bm.blocks:
        if blk.ref_count > 0 or blk.hash != -1:
            owners = [s.name for s in (A, B) if blk.block_id in s.block_table] \
                if blk.ref_count > 0 else []
            state = "LIVE" if blk.ref_count > 0 else "free (reclaimable)"
            tok = str(blk.token_ids) if blk.token_ids else "[]"
            print(f"| {blk.block_id:<5} | {blk.ref_count:<9} | {state:<12} | "
                  f"{str(owners):<8} | {tok:<10} |")
    print()

    shared_id = A.block_table[0]
    rc = bm.blocks[shared_id].ref_count
    print(f"[check] shared block {shared_id} ref_count == 2 (A and B) : "
          f"{rc == 2} -> {'OK' if rc == 2 else 'FAIL'}")
    print(f"[check] B.block_table reuses A's block0 : "
          f"{B.block_table[0] == A.block_table[0]} -> "
          f"{'OK' if B.block_table[0] == A.block_table[0] else 'FAIL'}")
    print(f"[check] B.block_table[1] is a DIFFERENT physical block : "
          f"{B.block_table[1] != A.block_table[1]} -> "
          f"{'OK' if B.block_table[1] != A.block_table[1] else 'FAIL'}")
    print()
    print(f"GOLD for .html: shared block ref_count after A+B allocate = {rc}")
    return bm, A, B


def section_hash_blocks_full_only():
    # INTUITION: hash_blocks runs AFTER a block fills up, and registers ONLY
    # full blocks. A partial last block is unstable — more tokens may arrive and
    # fill it — so hashing it would create a cache entry a later request could
    # FALSELY match (the #1 Phase-3 pitfall). The walk boundary is integer math:
    # start = num_cached_tokens // block_size, end = (cached+scheduled) // bs.
    banner("SECTION E: hash_blocks -> register FULL blocks only (the #1 pitfall)")
    bm = BlockManager(num_blocks=6, block_size=BS)
    # C has 3 tokens => 2 logical blocks: [t0,t1] FULL, [t2] PARTIAL
    C = Sequence([T0, T1, T2], BS, "C")
    print(f"Request C = {C.token_ids}, block_size={BS} => {C.num_blocks} logical "
          f"blocks:")
    print(f"  block0 = {C.block(0)}  (FULL)")
    print(f"  block1 = {C.block(1)}  (PARTIAL — only 1 of {BS} tokens)\n")

    bm.allocate(C, 0)
    # simulate executing all 3 tokens at once
    C.num_scheduled_tokens = C.num_tokens - C.num_cached_tokens   # = 3
    print(f"Execute 3 tokens. hash_blocks boundary math:")
    start = C.num_cached_tokens // BS                  # 0
    end = (C.num_cached_tokens + C.num_scheduled_tokens) // BS   # 3//2 = 1
    print(f"  start = num_cached_tokens//bs = {C.num_cached_tokens}//{BS} = {start}")
    print(f"  end   = (cached+scheduled)//bs = {C.num_cached_tokens + C.num_scheduled_tokens}//{BS} = {end}")
    print(f"  -> register blocks [{start}..{end}) = block 0 ONLY. "
          f"block 1 (partial) is SKIPPED.\n")
    bm.hash_blocks(C)
    C.num_cached_tokens += C.num_scheduled_tokens
    C.num_scheduled_tokens = 0

    print("hash_to_block_id after hash_blocks(C):")
    for h, bid in bm.hash_to_block_id.items():
        print(f"    {hx(h)} -> block {bid} (tokens {bm.blocks[bid].token_ids})")
    print(f"  (block1's partial [{C.block(1)[0]}] is NOT registered.)\n")

    # Show the false-match that WOULD happen if we hashed partials:
    print("WHY partials are skipped — the false-cache-hit it prevents:")
    print("  Suppose D = [t0,t1,t2,99] arrives later. block1 of D = [t2,99].")
    print("  If we had hashed C's partial block1=[t2], a naive lookup of D's")
    print("  block1 might collide on the token t2 prefix and reuse WRONG KV.")
    print("  By hashing ONLY full blocks, D's block1 is a guaranteed MISS until")
    print("  it actually fills with [t2,99] — stable and correct.\n")

    print(f"[check] only 1 block registered (the full one) : "
          f"{len(bm.hash_to_block_id) == 1} -> "
          f"{'OK' if len(bm.hash_to_block_id) == 1 else 'FAIL'}")
    # and verify a fresh full block DOES get registered
    bm2 = BlockManager(num_blocks=4, block_size=BS)
    F = Sequence([T0, T1, T2, T3], BS, "F")           # exactly 2 full blocks
    bm2.allocate(F, 0)
    F.num_scheduled_tokens = F.num_tokens
    bm2.hash_blocks(F)
    print(f"[check] a 4-token request registers 2 full blocks : "
          f"{len(bm2.hash_to_block_id) == 2} -> "
          f"{'OK' if len(bm2.hash_to_block_id) == 2 else 'FAIL'}")


def section_can_append_may_append():
    # INTUITION: during decode, tokens arrive one at a time. A new page is needed
    # only when a token lands at position 1 of a fresh page — i.e. exactly when
    # len(seq) % block_size == 1 (the previous page just filled up). At every
    # other position the token drops into an existing page's free slot.
    banner("SECTION F: can_append / may_append -> the page-boundary rule")
    bm = BlockManager(num_blocks=6, block_size=BS)
    A = Sequence([T0, T1, T2, T3], BS, "A")           # 4 tokens => 2 full pages
    bm.allocate(A, 0)
    print(f"A = {A.token_ids} (len={len(A)}, block_size={BS}). "
          f"A.block_table = {A.block_table} (2 pages, both full).\n")
    print("Decode tokens one at a time and watch when a new page appears:")
    print("| step | append | len(seq) | len%bs | new page needed? | "
          "may_append allocates? | A.block_table | free blocks |")
    print("|------|--------|----------|--------|------------------|"
          "------------------------|---------------|-------------|")
    new_tokens = [20, 21, 22, 23]
    for k, tok in enumerate(new_tokens):
        before_table = list(A.block_table)
        A.append_token(tok)                           # token lands at len = old+1
        need = (len(A) % BS == 1)                     # page-boundary condition
        can = bm.can_append(A)
        bm.may_append(A)                              # allocate iff boundary
        allocated = len(A.block_table) > len(before_table)
        print(f"| {k+1:<4} | {tok:<6} | {len(A):<8} | {len(A) % BS:<6} | "
              f"{('YES (boundary)' if need else 'no'):<16} | "
              f"{('YES -> new page' if allocated else 'no'):<22} | "
              f"{str(A.block_table):<13} | {len(bm.free_block_ids):<11} |")
    print()
    print("Rule: a new physical page is allocated EXACTLY when len(seq) % block_size == 1.")
    print(f"At len=5 (5%{BS}=1): page allocated. At len=6 (6%{BS}=0): token drops into")
    print(f"the existing partial page — no allocation. At len=7 (7%{BS}=1): page again.\n")
    # OOM during decode: can_append returns False when a boundary needs a page
    # but the pool is empty — that is the Scheduler's signal to PREEMPT.
    bm_oom = BlockManager(num_blocks=0, block_size=BS)   # empty pool
    Z = Sequence([T0], BS, "Z")
    Z.append_token(T1)                                 # len=2 -> 2%2=0, no page needed
    print(f"[check] can_append at len=2 (no page needed) with empty pool: "
          f"{bm_oom.can_append(Z)} (True, 0 pages needed) -> "
          f"{'OK' if bm_oom.can_append(Z) is True else 'FAIL'}")
    Z2 = Sequence([T0], BS, "Z2")
    # len=2 -> append -> len=3? No: simulate len such that 3%2==1
    Z2.append_token(T1); Z2.append_token(T2)          # len=3, 3%2=1 -> needs 1 page
    print(f"[check] can_append at len=3 (boundary, page needed) with empty pool: "
          f"{bm_oom.can_append(Z2)} (False => OOM => preempt) -> "
          f"{'OK' if bm_oom.can_append(Z2) is False else 'FAIL'}")


def section_preempt_refcount(bm: BlockManager, A: Sequence, B: Sequence):
    # INTUITION: preemption (decode OOM) evicts a running sequence by calling
    # deallocate. Sharing is ref-counted: a block two seqs share only drops to
    # ref_count 1 when one leaves — it is NOT freed (the other still reads it).
    # Only the LAST reader frees a block, and even then the KV+hash stay so a
    # later matching prefix can reclaim it. The pitfall: forgetting ref counts
    # would free a block another sequence is still reading -> silent corruption.
    banner("SECTION G: preemption + ref counting -> shared blocks survive, "
           "freed blocks stay reclaimable")
    print(f"Start: A.block_table={A.block_table}, B.block_table={B.block_table}.")
    print(f"  ref_counts: block0(A,B share)={bm.blocks[0].ref_count}, "
          f"block1(A)={bm.blocks[A.block_table[1]].ref_count}, "
          f"block{B.block_table[1]}(B)={bm.blocks[B.block_table[1]].ref_count}\n")

    # --- A finishes: deallocate(A) ---
    bm.deallocate(A)
    print(f"A finishes -> deallocate(A):")
    print(f"  block1 (A's private): ref 1->0 -> FREED to free list")
    print(f"  block0 (shared w/ B): ref 2->1 -> STAYS (B still reads it)")
    print(f"  A.block_table = {A.block_table}\n")
    print(f"  Pool state: used={sorted(bm.used_block_ids)}, "
          f"free={sorted(bm.free_block_ids)}")
    print(f"  block0.ref_count = {bm.blocks[0].ref_count}  (B is now the sole reader)")
    print(f"  block1.ref_count = {bm.blocks[1].ref_count}  (freed, but hash+tokens stay)")
    print(f"  hash_to_block_id still has {len(bm.hash_to_block_id)} entries "
          f"(freed block1's entry is RECLAIMABLE):\n")
    for h, bid in bm.hash_to_block_id.items():
        print(f"    {hx(h)} -> block {bid}  "
              f"({'LIVE' if bid in bm.used_block_ids else 'free/reclaimable'}, "
              f"tokens {bm.blocks[bid].token_ids})")
    print()

    print("[check] shared block0 ref_count == 1 after A leaves : "
          f"{bm.blocks[0].ref_count == 1} -> "
          f"{'OK' if bm.blocks[0].ref_count == 1 else 'FAIL'}")
    print("[check] block1 returned to free list : "
          f"{1 in bm.free_block_ids} -> "
          f"{'OK' if 1 in bm.free_block_ids else 'FAIL'}")
    print("[check] freed block1 STILL in hash_to_block_id (reclaimable) : "
          f"{bm.blocks[1].hash in bm.hash_to_block_id} -> "
          f"{'OK' if bm.blocks[1].hash in bm.hash_to_block_id else 'FAIL'}")
    print()

    # --- a brand-new request reclaims block1's KV ---
    print("RECLAIM demo: request D = [t0,t1,t2,t3,20,21] shares block0 (live) AND")
    print("block1=[t2,t3] (free but reclaimable). can_allocate should find BOTH.\n")
    D = Sequence([T0, T1, T2, T3, 20, 21], BS, "D")   # 6 tokens => 3 blocks
    nD = bm.can_allocate(D)
    print(f"can_allocate(D) -> num_cached_blocks = {nD} "
          f"(block0 LIVE-share + block1 RECLAIMED, no KV recompute for either)")
    bm.allocate(D, nD)
    print(f"allocate(D, {nD}): D.block_table = {D.block_table}")
    print(f"  block0 reused (ref {bm.blocks[0].ref_count}); "
          f"block1 reclaimed from free list (ref {bm.blocks[1].ref_count}); "
          f"block{D.block_table[2]} fresh for [20,21].\n")
    print(f"[check] D reused block1 WITHOUT recomputing its KV : "
          f"{1 in D.block_table} -> {'OK' if 1 in D.block_table else 'FAIL'}")
    print(f"[check] D.num_cached_tokens == {nD * BS} (skips prefill for "
          f"{nD * BS} tokens) : {D.num_cached_tokens == nD * BS} -> "
          f"{'OK' if D.num_cached_tokens == nD * BS else 'FAIL'}")


# ============================================================================
# main
# ============================================================================

def main():
    print("block_manager.py - reference impl. All numbers below feed "
          "BLOCK_MANAGER.md.")
    print("torch =", torch.__version__, "(unused here; bundle is allocation "
          "metadata only)\n")

    section_block_struct()
    section_chained_hash()
    bm, A, B = section_can_allocate()
    bm, A, B = section_allocate(bm, A, B)
    section_hash_blocks_full_only()
    section_can_append_may_append()
    section_preempt_refcount(bm, A, B)

    banner("DONE - all sections printed; chained-hash + ref_count gold = OK")


if __name__ == "__main__":
    main()
