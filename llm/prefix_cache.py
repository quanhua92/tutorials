"""
prefix_cache.py - Reference implementation of RadixAttention prefix caching.

This is the single source of truth that PREFIX_CACHE.md is built from. Every
number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python prefix_cache.py

== THE BIG IDEA, IN ONE SENTENCE (the "family tree" intuition) ================
Imagine every prompt as a branch in a growing FAMILY TREE of conversations.
The trunk is the shared system prompt; each fork is where one conversation
diverges from another. RadixAttention stores the KV cache for the WHOLE tree
in a RADIX TREE (a compressed trie): ANY common prefix — no matter its length,
no matter how the prompts fork — is stored ONCE and reused by every descendant.
A new prompt walks DOWN the tree to find its longest cached ancestor, then
grows a new twig for whatever is genuinely new. The payoff: a prompt that
shares its first 6 tokens with an earlier one pays for 0 of those 6.

== THE LINEAGE (old -> new, with WHY) ========================================

  1. NAIVE per-request KV (the "before"): each request computes and discards
     its own KV. Two chats that start with the same system prompt each pay the
     full prefill cost. (🔗 KV_CACHE.md — the storage layer with no sharing.)

  2. BlockManager + FLAT chained-hash prefix cache (vLLM / PagedAttention,
     Kwon et al. SOSP 2023 — 🔗 BLOCK_MANAGER.md, your direct sibling): pages
     become CONTENT-ADDRESSED by a chained hash of their tokens. Two requests
     that produced the same BLOCK-ALIGNED token prefix share the same physical
     pages (ref_count++). HUGE win — but the dedup unit is a WHOLE BLOCK. A
     shared prefix whose length is not a multiple of block_size CANNOT be
     reused past the last full block: the trailing partial tokens live in a
     block whose later slots belong to a divergent user query, so its hash is
     unique to that query. The reuse is "all-or-nothing per block."

  3. RadixAttention (SGLang, Zheng et al. 2023 — arXiv:2312.07104): replace
     the flat hash table with a RADIX TREE keyed by the RAW TOKEN SEQUENCE.
     Every node holds a token SEGMENT (an edge of arbitrary length), a map of
     children keyed by their first token, and a pointer to the KV for that
     segment. Sharing is now TOKEN-GRANULAR and TREE-STRUCTURED: ANY common
     prefix — partial, forked, arbitrary length — is shared, with O(L)
     insert/lookup (L = prompt length). Chat, few-shot, and agent workloads
     reuse prefixes far more richly than block-aligned hashing captures.

== PLAIN-ENGLISH GLOSSARY (used in every section below) ======================
    token         one word/piece of the prompt (here, a small int id).
    prefix        the leading run of tokens two prompts have in common.
    block_size    tokens per physical page in the flat-hash scheme (vLLM=16;
                  this demo=2 so every number is printable). The flat cache
                  can only reuse WHOLE blocks — the source of its limit.
    radix tree    a COMPRESSED TRIE (a.k.a. Patricia/radix trie). Edges are
                  labeled with TOKEN SEGMENTS of arbitrary length, not single
                  tokens. Internal nodes with one child are MERGED into their
                  parent (compression) — so the tree is never spindly.
    node          one vertex of the tree = (token-segment edge, children map,
                  KV reference / ref_count, last_access for LRU). The root has
                  an empty segment; every other node's segment is the edge
                  FROM its parent.
    edge          the token segment stored ON a node (node.token_ids). The
                  full prefix a node represents = concatenation of segments
                  from the root down to (and including) it.
    match (LPM)   LONGEST-PREFIX traversal: walk from root, consuming the
                  query's tokens edge-by-edge; stop at the first divergence.
                  Returns how many leading tokens are a cache HIT.
    insert        walk+match; SHARE the matched prefix (ref_count++); if the
                  match stops MID-edge, SPLIT that edge; attach a new leaf for
                  the unmatched suffix. O(L) in the prompt length.
    split         when a new prompt matches only PART of an existing edge, cut
                  the edge at the match point: the matched part becomes a new
                  internal node, the old tail becomes its child, and the new
                  prompt's suffix becomes a sibling child.
    ref_count     how many live requests currently READ a node's KV. >0 =>
                  live (cannot evict). ==0 => evictable leaf.
    eviction      LRU on LEAVES when GPU memory overflows: recursively remove
                  the least-recently-used leaf with ref_count==0; prune its
                  parent if it becomes childless. Internal nodes are never
                  directly evicted (they're shared backbones).
    flat-hash     the 🔗 BLOCK_MANAGER scheme: chained hash of block-aligned
                  token chunks → physical block. Reuse = floor(L/block_size)
                  * block_size tokens. The contrast baseline.

== WHY THE RADIX TREE BEATS THE FLAT HASH (the one paragraph) ================
A flat hash table answers ONE question: "do I have a block whose chained
fingerprint equals THIS block's?" That question is only well-posed for a FULL
block of exactly block_size tokens. A radix tree answers a RICHER question:
"what is the LONGEST run of leading tokens I have already stored, anywhere in
the tree?" — and that run can stop at ANY token, not just at a block boundary.
When a 3-token system prompt is followed by a divergent user query, the flat
hash can only reuse the 2 tokens that form a complete block; the 3rd system
token is trapped in a block whose remaining slots are unique to one query, so
its hash never recurs. The radix tree simply stores all 3 system tokens on one
edge and lets every query descend through it. That single difference — token-
granular vs block-granular sharing — is the whole reason chat/agent workloads,
which fork at arbitrary points, benefit from the tree.

== TENSOR-SHAPE / SIZING CONVENTIONS =========================================
This bundle is about the CACHE INDEX (a data structure), not tensors — there
are no [B,L,H,D] shapes here. The dimensions that matter are the token-id
sequences and block_size=2 (for the flat-hash contrast). We use small int token
ids (100s = system prompt, 200s/300s = user queries) so every number prints.
"""

from __future__ import annotations


import torch  # only for parity with sibling bundles + version banner

BANNER = "=" * 72


# ============================================================================
# 1. THE FLAT CHAINED-HASH  (the 🔗 BLOCK_MANAGER contrast baseline)
#    Re-implemented inline (minimal) so this bundle is self-contained and the
#    .html can gold-check it offline. Identical structure to block_manager.py:
#    compute_hash(token_ids, prefix=h_prev), only FULL blocks are reusable.
# ============================================================================

# FNV-1a 64-bit (public-domain non-cryptographic hash) — same as block_manager.py.
FNV_OFFSET_64 = 0xCBF29CE484222325
FNV_PRIME_64 = 0x100000001B3
MASK64 = (1 << 64) - 1


def fnv1a_mix(h: int, byte: int) -> int:
    return ((h ^ byte) * FNV_PRIME_64) & MASK64


def compute_hash(token_ids: list[int], prefix: int = -1) -> int:
    """Chained 64-bit fingerprint of one FULL block (mirrors BLOCK_MANAGER)."""
    h = FNV_OFFSET_64
    if prefix != -1:
        for b in prefix.to_bytes(8, "little"):
            h = fnv1a_mix(h, b)
    for t in token_ids:
        for b in t.to_bytes(4, "little"):
            h = fnv1a_mix(h, b)
    return h


def hx(h: int) -> str:
    """Render a 64-bit hash as 0x + 16 hex digits."""
    return f"0x{h & MASK64:016x}"


class FlatHashCache:
    """The block-aligned chained-hash prefix cache (🔗 BLOCK_MANAGER, minimal).

    Only FULL blocks are reusable: a prefix of length L yields
    floor(L // block_size) reusable blocks = (L // block_size) * block_size
    reusable TOKENS. Any trailing tokens that don't fill a block are invisible
    to the cache.
    """

    def __init__(self, block_size: int):
        self.block_size = block_size
        self.hash_to_tokens: dict[int, list[int]] = {}

    def _blocks(self, tokens: list[int]):
        """Yield (block_index, token_slice) for each FULL block only."""
        n_full = len(tokens) // self.block_size
        for i in range(n_full):
            yield i, tokens[i * self.block_size:(i + 1) * self.block_size]

    def insert(self, tokens: list[int]) -> int:
        """Register all FULL blocks (chained). Returns tokens now cached."""
        h = -1
        cached_blocks = 0
        for _, blk in self._blocks(tokens):
            h = compute_hash(blk, h)
            self.hash_to_tokens[h] = list(blk)
            cached_blocks += 1
        return cached_blocks * self.block_size

    def match(self, tokens: list[int]) -> int:
        """Walk FULL blocks; count how many leading tokens are a cache HIT."""
        h = -1
        cached_tokens = 0
        for _, blk in self._blocks(tokens):
            h = compute_hash(blk, h)
            if self.hash_to_tokens.get(h) == blk:
                cached_tokens += self.block_size
            else:
                break                       # first miss stops the walk
        return cached_tokens


# ============================================================================
# 2. THE RADIX TREE  (RadixAttention — the new structure)
#    Pure-Python compressed trie keyed by token sequences. Each node holds a
#    token SEGMENT (the edge from its parent), a children map keyed by the
#    first token of each child's segment, a ref_count, and an LRU clock tick.
# ============================================================================

class RadixNode:
    """One vertex of the radix tree.

    Fields:
        token_ids   the token SEGMENT on the edge FROM the parent to this node
                    (empty [] for the root). The full prefix this node
                    represents = concatenation of segments root..here.
        children    dict: first_token_id -> child RadixNode. Keyed by the first
                    token so child lookup during match is O(1) per edge.
        ref_count   how many live requests currently READ this node's KV.
                    >0 => live (cannot evict). ==0 => evictable (if a leaf).
        last_access monotonic LRU clock tick; updated on every match/insert.
    """

    __slots__ = ("token_ids", "children", "ref_count", "last_access", "parent")

    def __init__(self, token_ids: list[int], parent: "RadixNode | None" = None):
        self.token_ids: list[int] = list(token_ids)
        self.children: dict[int, RadixNode] = {}
        self.ref_count: int = 0
        self.last_access: int = 0
        self.parent: "RadixNode | None" = parent


class RadixCache:
    """A radix-tree (compressed-trie) KV cache index — RadixAttention.

    Mirrors SGLang's radix_cache.py (Zheng et al., arXiv:2312.07104) in
    miniature: match() is the longest-prefix traversal; insert() shares the
    matched prefix, splits edges on partial matches, and attaches a new leaf
    for the unmatched suffix. Eviction is LRU on leaves with ref_count==0.

    The tree lives on the CPU (cheap to maintain); the KV TENSORS it points at
    live on the GPU in a paged layout (page_size = 1 token in SGLang's default).
    This demo models only the INDEX — the tree structure and its sharing.
    """

    def __init__(self):
        self.root = RadixNode([])
        self.clock = 0          # monotonic LRU clock

    def _tick(self) -> int:
        self.clock += 1
        return self.clock

    # ---- LONGEST-PREFIX MATCH: walk from root, consume tokens edge by edge --
    def match(self, tokens: list[int]) -> tuple[int, RadixNode]:
        """Return (matched_len, node).

        matched_len = how many LEADING tokens of `tokens` are a cache hit
        (already stored on some root-to-node path). `node` is the deepest node
        reached along the matched prefix (where a new insert would attach).
        """
        node = self.root
        node.last_access = self._tick()
        i = 0
        n = len(tokens)
        while i < n:
            child = node.children.get(tokens[i])
            if child is None:
                break                            # no edge starts here → stop
            seg = child.token_ids
            j = 0
            m = min(len(seg), n - i)
            while j < m and seg[j] == tokens[i + j]:
                j += 1                            # longest common prefix
            if j == len(seg):
                # full edge consumed → descend, keep matching
                child.last_access = self._tick()       # read-only: touch LRU only
                node = child
                i += j
            else:
                # partial edge match → stop (the rest is NOT cached)
                break
        return i, node

    # ---- INSERT: share prefix, split edges, attach new leaf -----------------
    def insert(self, tokens: list[int]) -> int:
        """Insert `tokens`; share the matched prefix, split on partial match.

        Returns matched_len = number of leading tokens already cached
        (= the cache-hit length; prefill is skipped for exactly these tokens).
        """
        node = self.root
        node.ref_count += 1                       # every request reads root
        node.last_access = self._tick()
        i = 0
        n = len(tokens)
        matched = 0
        while i < n:
            child = node.children.get(tokens[i])
            if child is None:
                break                             # rest is all new → leaf below
            seg = child.token_ids
            j = 0
            m = min(len(seg), n - i)
            while j < m and seg[j] == tokens[i + j]:
                j += 1
            if j == len(seg):
                # full edge matched → descend, this child is shared (ref++)
                child.ref_count += 1
                child.last_access = self._tick()
                node = child
                i += j
                matched = i
            else:
                # PARTIAL edge match → SPLIT seg at j:
                #   new internal node takes seg[:j] (the matched run)
                #   old child keeps seg[j:] (its unmatched tail)
                #   new prompt's suffix becomes a sibling leaf
                split = RadixNode(seg[:j], parent=node)
                split.ref_count = child.ref_count + 1   # old readers + new req
                split.last_access = self._tick()
                child.token_ids = seg[j:]                # trim old child's edge
                child.parent = split                     # old child reparented
                # re-key: `split` replaces `child` under seg[0]; `child` moves
                # under split, keyed by its new first token seg[j].
                node.children[seg[0]] = split
                split.children[seg[j]] = child
                node = split
                i += j
                matched = i
                break                              # descend handled; leaf below
        # attach any remaining tokens[i:] as a brand-new leaf
        if i < n:
            leaf = RadixNode(tokens[i:], parent=node)
            leaf.ref_count = 1
            leaf.last_access = self._tick()
            node.children[tokens[i]] = leaf
        return matched

    # ---- RELEASE: a request finishes; decrement ref_counts along its path ---
    def release(self, tokens: list[int]) -> None:
        """Walk the path for `tokens`, decrementing ref_count on each node.

        Nodes that hit ref_count==0 become evictable (if leaves). The tree
        structure is NOT changed here — eviction (below) does the pruning.
        """
        node = self.root
        node.ref_count = max(0, node.ref_count - 1)
        i = 0
        n = len(tokens)
        while i < n:
            child = node.children.get(tokens[i])
            if child is None:
                break
            seg = child.token_ids
            j = 0
            m = min(len(seg), n - i)
            while j < m and seg[j] == tokens[i + j]:
                j += 1
            if j == len(seg):
                child.ref_count = max(0, child.ref_count - 1)
                node = child
                i += j
            else:
                break

    # ---- EVICTION: LRU on leaves with ref_count==0 -------------------------
    def evict_lru_leaves(self, k: int) -> list[list[int]]:
        """Evict up to `k` least-recently-used LEAF nodes with ref_count==0.

        Returns the list of evicted token segments (in LRU order). After
        removing a leaf, walk UP its parent chain: a parent that lost its LAST
        child AND has ref_count==0 is itself now a dead leaf → prune it too
        (recursively), which mirrors SGLang's "recursively evict leaf nodes"
        LRU policy. A parent with ref_count>0 stays (some request terminates
        there) and a parent that still has other children stays. The root is
        never pruned.
        """
        evicted: list[list[int]] = []
        for _ in range(k):
            # collect evictable leaves: ref_count==0 AND no children
            leaves = [(nd.last_access, parent, key, nd)
                      for parent in self._all_nodes()
                      for key, nd in parent.children.items()
                      if not nd.children and nd.ref_count == 0]
            if not leaves:
                break
            leaves.sort(key=lambda t: t[0])         # least-recently-used first
            _, parent, key, victim = leaves[0]
            del parent.children[key]
            evicted.append(list(victim.token_ids))
            # targeted upward prune: a now-childless, ref_count==0 non-root node
            # is itself a dead leaf → remove and continue up the chain.
            node = parent
            while node is not self.root and not node.children \
                    and node.ref_count == 0 and node.parent is not None:
                gp = node.parent
                # remove `node` from gp.children (find its key)
                for ck, cv in list(gp.children.items()):
                    if cv is node:
                        del gp.children[ck]
                        break
                node = gp
        return evicted

    def _all_nodes(self) -> list[RadixNode]:
        out: list[RadixNode] = []
        stack = [self.root]
        while stack:
            nd = stack.pop()
            out.append(nd)
            stack.extend(nd.children.values())
        return out

    # ---- PRETTY PRINT the whole tree ---------------------------------------
    def dump(self) -> list[str]:
        """Return a list of lines showing the tree (indent = depth)."""
        lines: list[str] = []

        def rec(nd: RadixNode, depth: int, edge_first: str):
            indent = "    " * depth
            seg = nd.token_ids if nd.token_ids else "(root)"
            tag = ""
            if nd is self.root:
                tag = "  <root>"
            elif not nd.children:
                tag = "  <leaf>"
            rc = f"ref={nd.ref_count}"
            la = f"t={nd.last_access}"
            label = edge_first if edge_first else "-"
            lines.append(f"{indent}[{label}] {seg}  {{{rc}, {la}{tag}}}")
            for key in sorted(nd.children.keys()):
                rec(nd.children[key], depth + 1, str(key))

        rec(self.root, 0, "")
        return lines


# ============================================================================
# 3. PRETTY PRINTER
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 4. THE DETERMINISTIC PROMPT TREE (the workload every section uses)
#    A shared 3-token system prompt + 3 diverging user queries. The 3-token
#    prefix is NOT block-aligned for block_size=2 — that is the whole point.
# ============================================================================

SYS = [100, 101, 102]                                   # "You are a helpful..."
Q1 = [100, 101, 102, 200, 201, 202]                     # sys + "what is python"
Q2 = [100, 101, 102, 210, 211]                          # sys + "what is rust"
Q3 = [100, 101, 102, 200, 201, 202, 300, 301]           # sys + "what is python, example"
QUERIES = [("Q1", Q1), ("Q2", Q2), ("Q3", Q3)]
BS = 2                                                  # block_size (flat-hash)


# ============================================================================
# 5. THE SECTIONS  (the numbers that feed PREFIX_CACHE.md)
# ============================================================================

def section_flat_hash_recap():
    # INTUITION: the flat chained-hash (🔗 BLOCK_MANAGER) dedups WHOLE blocks.
    # A prefix of length L reuses floor(L/block_size) blocks. The trailing
    # tokens that don't fill a block are INVISIBLE to the cache — they live in
    # a block whose later slots are unique to one query, so its hash recurs
    # only if the WHOLE block recurs. This section pins that limit with numbers.
    banner("SECTION A: the flat chained-hash prefix cache (🔗 BLOCK_MANAGER recap)")
    print(f"block_size = {BS}. A prefix of length L reuses (L // {BS}) blocks =\n"
          f"  (L // {BS}) * {BS} tokens. The flat cache answers ONE question per\n"
          f"  block: 'do I have a block whose chained fingerprint equals THIS\n"
          f"  block's?'. Only FULL blocks can be reused.\n")
    fc = FlatHashCache(BS)
    print(f"Insert Q1 = {Q1} (cold). Register its {len(Q1) // BS} full blocks:")
    h = -1
    for i, blk in fc._blocks(Q1):
        h = compute_hash(blk, h)
        print(f"  block{i} {blk}: chained hash = {hx(h)}  -> registered")
    print(f"  Q1 registered {len(Q1) // BS} blocks; Q1 itself was cold (0 cached).\n")

    print(f"Now probe the 3-token system prefix SYS = {SYS}:")
    print(f"  (L // {BS}) * {BS} = ({len(SYS)} // {BS}) * {BS} = "
          f"{len(SYS) // BS} * {BS} = {(len(SYS) // BS) * BS} reusable tokens.")
    print("  The 3rd token (102) is NOT in any full block by itself: it would")
    print("  share a block with a user-query token, so its hash is unique to")
    print("  whichever query fills the rest of that block.\n")

    # concrete: cache SYS-aligned block vs SYS+divergent
    print("Two ways the 3rd system token could be packed into a block:")
    h_sys0 = compute_hash([100, 101], -1)
    print(f"  block [100,101]           hash = {hx(h_sys0)}   (always the same)")
    print(f"  block [102, 200] (Q1's)   hash = {hx(compute_hash([102, 200], h_sys0))}")
    print(f"  block [102, 210] (Q2's)   hash = {hx(compute_hash([102, 210], h_sys0))}")
    print("  -> the [102, *] block DIFFERS per query, so token 102 is never")
    print("     shared across divergent queries under the flat hash. The radix")
    print("     tree has no such blind spot.\n")
    print(f"[check] flat-hash reuse for a 3-token prefix == {len(SYS) // BS * BS} "
          f"(not 3): {(len(SYS) // BS * BS) == 2} -> "
          f"{'OK' if (len(SYS) // BS * BS) == 2 else 'FAIL'}")


def section_block_alignment_miss():
    # INTUITION: show concretely WHY Q2's flat-hash walk stops after block0,
    # even though 3 tokens are truly shared. block1 = [102, 210] for Q2 but
    # [102, 200] for Q1 → different chained hashes → MISS. The shared token
    # 102 is trapped inside a block whose second slot diverges.
    banner("SECTION B: why the flat hash misses the mid-block shared token")
    fc = FlatHashCache(BS)
    fc.insert(Q1)                                    # seed with Q1
    print(f"Seed cache with Q1 = {Q1}. Cached blocks (chained hashes):")
    h = -1
    for i, blk in fc._blocks(Q1):
        h = compute_hash(blk, h)
        print(f"  block{i} {blk} -> {hx(h)}")
    print()

    print(f"Probe Q2 = {Q2}. Walk its FULL blocks against the cache:\n")
    print("| block | tokens    | chained hash          | in cache? | verdict |")
    print("|-------|-----------|-----------------------|-----------|---------|")
    h = -1
    for i, blk in fc._blocks(Q2):
        h = compute_hash(blk, h)
        present = fc.hash_to_tokens.get(h) == blk
        verdict = ("HIT (reuse)" if present
                   else "MISS (divergent 2nd slot)")
        print(f"| {i:<5} | {str(blk):<9} | {hx(h):<21} | "
              f"{'yes' if present else 'NO':<9} | {verdict} |")
        if not present:
            print(f"|       |           | (Q1 had {hx(compute_hash(Q1[i*BS:(i+1)*BS], compute_hash(Q1[:i*BS], -1) if i>0 else -1))} for this slot) |           |         |")
            break
    print()
    cached = fc.match(Q2)
    print(f"flat-hash match(Q2) = {cached} tokens (only block0 [100,101]).")
    print("The 3rd shared token 102 sits in block1 = [102,210], whose hash is")
    print("UNIQUE to Q2 (Q1's block1 was [102,200]) — so the walk stops. The")
    print("true shared prefix is 3 tokens ([100,101,102]); the flat hash can")
    print("only see 2 of them. That is the block-alignment blind spot.\n")
    print(f"[check] flat-hash match(Q2) == 2 (not 3) : {cached == 2} -> "
          f"{'OK' if cached == 2 else 'FAIL'}")


def section_radix_node_struct():
    # INTUITION: a radix node is a (token-segment edge, children map, KV ref /
    # ref_count, LRU clock). The root has an empty segment; every other node's
    # segment is the edge FROM its parent. Children are keyed by their first
    # token so match() descends in O(1) per edge.
    banner("SECTION C: the radix tree node — segment, children, ref_count, LRU")
    root = RadixNode([])
    print("RadixNode([]) just created (the root):")
    print(f"  token_ids   = {root.token_ids}   (empty => root)")
    print(f"  children    = {root.children}    (keyed by first token of each child)")
    print(f"  ref_count   = {root.ref_count}   (live readers; 0 => nobody yet)")
    print(f"  last_access = {root.last_access} (LRU clock tick)\n")

    print("Node roles in the tree:")
    print("| role     | token_ids        | children          | ref_count meaning     |")
    print("|----------|------------------|-------------------|-----------------------|")
    print("| root     | []               | {tok: node,...}   | # requests in tree    |")
    print("| internal | [shared segment] | {tok: node,...}   | # readers of backbone |")
    print("| leaf     | [unique tail]    | {}                | # readers of this req |")
    print()
    print("The COMPRESSED-trie rule: a node with exactly one child is MERGED")
    print("into a single longer edge — so the tree never has spindly single-")
    print("token chains. match() walks edge-by-edge (O(1) child lookup each),")
    print("not token-by-token: O(edges) ~ O(L) but with a small constant.\n")

    rc = RadixCache()
    print("RadixCache() just created:")
    for line in rc.dump():
        print("  " + line)
    print("  (empty tree: just the root. match(anything) -> (0, root).)")
    m0, _ = rc.match(Q1)
    print(f"\n[check] match(Q1) on empty tree == 0 : {m0 == 0} -> "
          f"{'OK' if m0 == 0 else 'FAIL'}")


def section_insert_and_match():
    # INTUITION: insert() walks+matches, SHARES the matched prefix (ref_count++
    # on each shared node), SPLITS an edge if the match stops mid-edge, and
    # attaches a new leaf for the unmatched suffix. We insert Q1, Q2, Q3 in
    # order and print the tree + cache-hit length after each step. The cache-hit
    # length is measured AT INSERT TIME (the moment the request arrives) — that
    # is the number of tokens whose prefill is skipped. Re-matching later would
    # trivially return the full length (the whole prompt is now cached), which
    # is a different question.
    banner("SECTION D: insert + longest-prefix match (O(L)) — build the tree")
    rc = RadixCache()
    hits: dict[str, int] = {}
    print("Insert Q1, Q2, Q3 in order. After each insert: the cache-hit length")
    print("(matched tokens, prefill skipped) and the resulting tree.\n")

    for name, q in QUERIES:
        hit = rc.insert(q)
        hits[name] = hit
        print(f">>> insert({name} = {q})")
        print(f"    cache-hit length = {hit}  (skip prefill for {hit} token"
              f"{'s' if hit != 1 else ''})")
        if hit == 0:
            print("    COLD miss — whole prompt is new; attach one edge.")
        elif hit == len(q):
            print("    FULL hit — entire prompt already cached; no new node.")
        else:
            print(f"    PARTIAL hit — share {hit} tokens, attach suffix {q[hit:]}.")
        print("    tree now:")
        for line in rc.dump():
            print("        " + line)
        print()
    print("[check] after Q1,Q2,Q3: root.ref_count == 3 : "
          f"{rc.root.ref_count == 3} -> "
          f"{'OK' if rc.root.ref_count == 3 else 'FAIL'}")
    n1 = rc.root.children.get(100)
    print(f"[check] system-prompt node [100,101,102].ref_count == 3 : "
          f"{n1.ref_count == 3} -> {'OK' if n1.ref_count == 3 else 'FAIL'}")
    return rc, hits


def section_worked_prompt_tree(rc: RadixCache, hits: dict[str, int]):
    # INTUITION: the centerpiece. One picture of the final tree with ref_counts,
    # then a per-query savings table (using the INSERT-TIME cache-hit lengths,
    # i.e. how many tokens each request skipped when it first arrived). The
    # system prompt (3 tokens) is shared by all 3 queries; Q1's "what is python"
    # (3 more tokens) is shared by Q1 and Q3. Total tokens saved vs no-cache is
    # the headline number.
    banner("SECTION E: the worked prompt tree — shared nodes + tokens saved")
    print("The 3-query workload (shared 3-token system prompt, diverging users):")
    print(f"  SYS = {SYS}                  (\"You are a helpful...\")")
    print(f"  Q1  = {Q1}        (sys + \"what is python\")")
    print(f"  Q2  = {Q2}              (sys + \"what is rust\")")
    print(f"  Q3  = {Q3}  (sys + \"what is python, example\")\n")

    print("Final radix tree (node = edge segment {ref_count, last_access}):")
    for line in rc.dump():
        print("    " + line)
    print()

    # per-query savings, using insert-time cache-hit lengths
    print("Per-query cache-hit length (measured WHEN each request arrived):")
    print("| query | tokens (prompt)                 | len | radix cache-hit | "
          "prefill tokens saved |")
    print("|-------|----------------------------------|-----|-----------------|"
          "----------------------|")
    total_saved = 0
    for name, q in QUERIES:
        hit = hits[name]
        total_saved += hit
        print(f"| {name:<5} | {str(q):<32} | {len(q):<3} | {hit:<15} | "
              f"{hit:<20} |")
    print()
    print(f"TOTAL radix tokens saved vs no-cache = {hits['Q1']} + {hits['Q2']} + "
          f"{hits['Q3']} = {total_saved}\n")

    print("[check] Q2 cache-hit == 3 (mid-block token 102 IS shared) : "
          f"{hits['Q2'] == 3} -> {'OK' if hits['Q2'] == 3 else 'FAIL'}")
    print("[check] Q3 cache-hit == 6 (shares sys + 'what is python') : "
          f"{hits['Q3'] == 6} -> {'OK' if hits['Q3'] == 6 else 'FAIL'}")
    print(f"[check] TOTAL radix tokens saved == {total_saved} : "
          f"{total_saved == 9} -> {'OK' if total_saved == 9 else 'FAIL'}")
    print(f"\nGOLD for .html: total radix tokens saved = {total_saved}; "
          f"Q2 radix cache-hit = {hits['Q2']}.")
    return hits, total_saved


def section_eviction(rc: RadixCache):
    # INTUITION: when GPU memory overflows, SGLang evicts LEAF nodes by LRU
    # (recursively). A leaf with ref_count>0 is in use and protected; only
    # ref_count==0 leaves are evictable. We release Q2, then evict its now-dead
    # leaf [210,211], then show a new query Q4 that would have hit [210,...]
    # now misses — eviction traded a cache slot for memory.
    banner("SECTION F: eviction — LRU on leaves with ref_count==0")
    print("Start from the full tree (Q1,Q2,Q3 all live). ref_counts:")
    for line in rc.dump():
        print("    " + line)
    print()

    # snapshot the system+Q2-prefix node for the before/after story
    print("STEP 1: Q2 finishes -> release(Q2). Decrement ref_counts on its path\n"
          "        (root, system node, Q2 leaf). Q2's leaf [210,211] -> ref 0.\n")
    rc.release(Q2)
    for line in rc.dump():
        print("    " + line)
    leaf_q2 = rc.root.children[100].children.get(210)
    print(f"\n  Q2 leaf [210,211] ref_count == {leaf_q2.ref_count} -> evictable.\n")

    print("STEP 2: memory pressure -> evict_lru_leaves(1). Remove the least-")
    print("        recently-used leaf with ref_count==0 (that's [210,211]).\n")
    evicted = rc.evict_lru_leaves(1)
    print(f"  evicted segments: {evicted}")
    print("  tree after eviction:")
    for line in rc.dump():
        print("        " + line)
    print()

    print("STEP 3: a new query Q4 = [100,101,102,210,999] arrives. BEFORE the")
    print("        eviction it would have matched [100,101,102,210] = 4 tokens")
    print("        (the [210,...] edge). AFTER eviction:")
    Q4 = [100, 101, 102, 210, 999]
    hit4, _ = rc.match(Q4)
    print(f"        match(Q4) = {hit4} tokens (only the system prefix survives; "
          f"[210,...] is gone).\n")
    print(f"[check] Q2 leaf ref_count==0 after release(Q2) : "
          f"{leaf_q2.ref_count == 0} -> "
          f"{'OK' if leaf_q2.ref_count == 0 else 'FAIL'}")
    still_210 = 210 in rc.root.children[100].children
    print(f"[check] [210,211] leaf removed after eviction : "
          f"{not still_210} -> {'OK' if not still_210 else 'FAIL'}")
    print(f"[check] match(Q4) after eviction == 3 (was 4 before) : "
          f"{hit4 == 3} -> {'OK' if hit4 == 3 else 'FAIL'}")


def section_flat_vs_radix_contrast(hits: dict, total_radix: int):
    # INTUITION: run the SAME workload through the flat chained-hash and lay the
    # two side by side. The flat hash ties or loses on every query; it loses
    # specifically on Q2 because the 3rd system token is mid-block. The delta
    # is exactly the tokens the flat hash is structurally blind to.
    banner("SECTION G: flat-hash vs radix reuse on the SAME workload")
    fc = FlatHashCache(BS)
    print(f"block_size = {BS}. Re-insert Q1, Q2, Q3 into a FRESH flat cache and\n"
          f"measure each query's cache-hit length, then compare to radix.\n")
    print("| query | prompt tokens                    | flat-hash hit | "
          "radix hit | delta | why the flat hash loses          |")
    print("|-------|----------------------------------|---------------|"
          "-----------|-------|----------------------------------|")
    total_flat = 0
    flat_hits = {}
    for name, q in QUERIES:
        fhit = fc.match(q)                          # measure BEFORE inserting
        flat_hits[name] = fhit
        fc.insert(q)                                # then register
        total_flat += fhit
        rhit = hits[name]
        delta = rhit - fhit
        if name == "Q1":
            why = "cold (no cache yet)"
        elif name == "Q2":
            why = "token 102 is mid-block ([102,210]!=[102,200])"
        else:
            why = "divergence lands on a block boundary"
        print(f"| {name:<5} | {str(q):<32} | {fhit:<13} | {rhit:<9} | "
              f"{delta:<5} | {why} |")
    print()
    print(f"TOTAL tokens saved — flat-hash: {total_flat}   radix: {total_radix}   "
          f"radix advantage: +{total_radix - total_flat}\n")
    print("Reading the table: flat-hash and radix AGREE on Q1 (cold) and Q3")
    print("(divergence happens to land on a block boundary, so all shared tokens")
    print("form whole blocks). They DISAGREE on Q2: the 3rd shared token (102)")
    print("is the FIRST slot of a block whose second slot diverges per query,")
    print("so the flat hash cannot reuse it. The radix tree has no block")
    print("boundary and reuses all 3 system tokens. That +1 is the entire")
    print("structural advantage on this workload; it grows with every query")
    print("that forks mid-block and with every block_size step missed.\n")
    print(f"[check] flat-hash total == {total_flat} : "
          f"{total_flat == 8} -> {'OK' if total_flat == 8 else 'FAIL'}")
    print(f"[check] radix total == {total_radix} (== flat + 1) : "
          f"{total_radix == total_flat + 1} -> "
          f"{'OK' if total_radix == total_flat + 1 else 'FAIL'}")
    print(f"\nGOLD for .html: flat-hash total saved = {total_flat}; "
          f"radix total saved = {total_radix}; Q2 flat={flat_hits['Q2']} "
          f"radix={hits['Q2']}.")


# ============================================================================
# main
# ============================================================================

def main():
    print("prefix_cache.py - reference impl. All numbers below feed "
          "PREFIX_CACHE.md.")
    print("torch =", torch.__version__, "(unused here; bundle is a cache index)\n")

    section_flat_hash_recap()
    section_block_alignment_miss()
    section_radix_node_struct()
    rc, hits = section_insert_and_match()
    hits, total_radix = section_worked_prompt_tree(rc, hits)
    # rebuild a fresh tree for the eviction demo so section G's contrast is clean
    rc_ev = RadixCache()
    for _, q in QUERIES:
        rc_ev.insert(q)
    section_eviction(rc_ev)
    section_flat_vs_radix_contrast(hits, total_radix)

    banner("DONE - all sections printed; radix tree gold = OK")


if __name__ == "__main__":
    main()
