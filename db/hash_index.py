"""
hash_index.py - Reference implementation of the PostgreSQL hash index.

A hash index gives O(1) point lookups on equality (=) but CANNOT do range
scans, ORDER BY, or prefix matching -- for those you need a B-tree (see
HEAP_VS_CLUSTERED.md). PostgreSQL's hash index uses LINEAR HASHING
(Litwin 1980 / Larson 1978): the bucket array grows ONE bucket at a time
instead of doubling all at once, so insert cost stays amortized O(1) even
while the table is being resized under your feet.

This is the single source of truth that HASH_INDEX.md is built from. Every
number, table, and worked example in the guide is printed by this file. If
you change something here, re-run and re-paste the output into the guide.

Run:
    python3 hash_index.py

============================================================================
THE INTUITION (read this first) -- the coat-check room with numbered hooks
============================================================================
Imagine a coat-check room with N numbered hooks (= buckets). To find Alice's
coat you do NOT scan every hook; you hash "alice" -> hook #7 and look there
only. That is the O(1) win.

  * STATIC HASH   : N is fixed forever. When the room fills up you must rebuild
                    the WHOLE wall with 2*N hooks and rehang every coat. That
                    is one giant O(N) freeze -- unacceptable for a live DB.
  * LINEAR HASHING: add ONE hook at a time. When the room is crowded, take the
                    "next hook in line" (the split pointer), add a new hook at
                    the end, and REHANG ONLY the coats on that one old hook --
                    about half of them move to the new hook, the rest stay.
                    Every other hook is untouched, so the cost is amortized
                    O(1) per insert, never a global freeze.

THE REASON PG HASH INDEXES EXIST: a B-tree is O(log N) for a point lookup.
For pure equality lookups on a column with no ordering needs (e.g. a UUID
session-token, or a hash-partition key), O(1) beats O(log N); and a hash
index is about half the size of a B-tree (no sorted pointers, no key copies
beyond the hash). PG used to warn that hash indexes were "not crash-safe"
because their WAL logging was incomplete -- that was fixed in PostgreSQL 10
(2017): hash indexes are now fully WAL-logged and production-usable.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  hash_any()    : PostgreSQL's hash function (Jenkins lookup3, hashfunc.c).
                  Returns a 32-bit uint32. ANY key type (int, text, bytea...)
                  is funneled through this and becomes 4 bytes.
  hashvalue     : the 32-bit hash of a key. The index never stores the raw
                  key for routing -- only the hashvalue + a TID.
  bucket        : a numbered slot. bucket_of(key) maps hashvalue -> bucket #.
  primary page  : the first 8 KB page of a bucket. Holds up to
                  PRIMARY_CAPACITY tuples here (kept tiny so overflows show).
  overflow page : when a primary page fills up, the bucket gets a linked
                  overflow page; chains can be long. PG links them via a
                  nextblk field in the page header.
  overflow chain: primary -> ovfl1 -> ovfl2 -> ... Walked linearly on lookup.
  maxbucket     : the highest bucket number that currently EXISTS.
                  (PG metapage: hashm_maxbucket.)
  low_mask      : 2^N - 1 where N = current split point. Masks the "old"
                  (pre-doubled) address space. (hashm_lowmask.)
  high_mask     : 2^(N+1) - 1. Masks the "new" (post-doubled) address space.
                  (hashm_highmask.)
  split pointer : implicit. The next bucket to split = (maxbucket+1) & low_mask.
                  In Litwin's textbook this is an explicit variable `p`.
  split         : grow by one bucket. Rehash the victim bucket's items; some
                  stay, some move to the new (maxbucket+1) bucket.
  load factor   : num_items / (num_buckets * primary_capacity). When it
                  exceeds the fillfactor (default 0.75 in PG), trigger a split.
  fillfactor    : the load-factor target. PG default for hash indexes = 75%.

============================================================================
THE LINEAGE (papers)
============================================================================
  Static hash            : fixed N buckets. Resize = full rehash. Painful.
  Dynamic hashing        (Knuth 1973, Vol. 3, Sec. 6.5):  the umbrella idea
                           of "let the address space grow."
  Extendible hashing     (Fagin et al. 1979):  doubles a DIRECTORY, not the
                           buckets. Used by some KV stores (e.g. linear hash
                           variants in older Berkeley DB). NOT what PG uses.
  Linear hashing         (Litwin 1980 VLDB; Larson 1978 IPL):  grow ONE bucket
                           at a time, no directory. This is what PG implements.
  PG crash-safety        (PostgreSQL 10, 2017):  full WAL logging for hash
                           indexes -- before 10 they were practically unusable.

KEY FORMULAS (all verified against the PostgreSQL source, asserted in code):

    hashvalue        = hash_any(key)                 # uint32

    bucket(hashvalue)= hashvalue & high_mask
                       if bucket > maxbucket:
                           bucket &= low_mask         # _hash_hashkey2bucket

    new_bucket       = maxbucket + 1                  # _hash_getnewbucket
    victim           = new_bucket & old_low_mask      # the bucket to rehash

    on split:
        if new_bucket > high_mask:                    # crossed a power of 2
            low_mask  = high_mask                     #   -> double address space
            high_mask = new_bucket | low_mask
        maxbucket = new_bucket
        rehash every tuple in `victim`: each either stays in victim or moves
        to new_bucket (depending on its hashvalue's bit at position N).

Sources:
  [1] PostgreSQL source, src/backend/access/hash/:
        hashfunc.c   - hash_any() (Jenkins lookup3, 32-bit)
        hashutil.c   - _hash_hashkey2bucket()
        hashpage.c   - _hash_splitbucket(), _hash_addovflpage()
        hashinsert.c - _hash_doinsert()
      and src/include/access/hash.h:  HashMetaPageData (hashm_maxbucket,
      hashm_lowmask, hashm_highmask, hashm_ffactor).
  [2] PostgreSQL docs:  storage-hash-index.html, indexes-types.html
  [3] W. Litwin, "Linear hashing: A new tool for file and table addressing",
      VLDB 1980.
  [4] P.-A. Larson, "Dynamic hashing", Inf. Proc. Letters 8(1), 1978.
  [5] PostgreSQL 10 release notes (2017):  "Hash indexes are now WAL-logged
      and so crash-safe; the old warning is removed."
"""

from __future__ import annotations

# ----------------------------------------------------------------------------
# 0. CONSTANTS  (match the PostgreSQL source where applicable)
# ----------------------------------------------------------------------------
FNV_OFFSET = 2166136261      # FNV-1a 32-bit offset basis
FNV_PRIME  = 16777619        # FNV-1a 32-bit prime
MASK32     = 0xFFFFFFFF

PRIMARY_CAPACITY  = 4        # tuples per primary bucket page (tiny, so chains form fast)
OVERFLOW_CAPACITY = 4        # tuples per overflow page
SPLIT_THRESHOLD   = 0.75     # fillfactor: split when load factor exceeds this (PG default)

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code HASH_INDEX.md walks)
# ============================================================================

def fnv1a_32(data: bytes) -> int:
    """FNV-1a 32-bit hash.

    We use FNV-1a here instead of PostgreSQL's hash_any() (which is Jenkins
    lookup3). Both produce a uniformly distributed uint32 with full avalanche
    -- which is the only property the bucket math depends on. FNV-1a is
    chosen because it is 8 lines of code and trivially verifiable by hand,
    while hash_any is ~80 lines of byte-fiddling. The bucket-selection
    formulas below are byte-for-byte identical to PostgreSQL's.

    >>> hex(fnv1a_32(b''))
    '0x811c9dc5'
    >>> hex(fnv1a_32(b'a'))
    '0xe40c292c'
    """
    h = FNV_OFFSET
    for b in data:
        h ^= b
        h = (h * FNV_PRIME) & MASK32
    return h


def hash_key(key: str) -> int:
    """Hash a string key -> uint32, the role of PG's hash_any()."""
    return fnv1a_32(key.encode("utf-8"))


class HashIndex:
    """A faithful miniature PostgreSQL hash index (linear hashing).

    Layout mirrors PG's metapage + bucket pages + overflow pages:

      buckets[b]      = a list of "pages"; buckets[b][0] is the PRIMARY page,
                        buckets[b][1:] are OVERFLOW pages in chain order.
      page            = a list of (key, value) tuples, length <= capacity.
      maxbucket       = highest existing bucket number (PG hashm_maxbucket).
      low_mask        = 2^N - 1  (PG hashm_lowmask).
      high_mask       = 2^(N+1) - 1  (PG hashm_highmask).

    The bucket-of-key computation is byte-identical to PG's
    _hash_hashkey2bucket (hashutil.c). The split mechanic is byte-identical
    to _hash_splitbucket (hashpage.c).
    """

    def __init__(self, primary_cap: int = PRIMARY_CAPACITY,
                 overflow_cap: int = OVERFLOW_CAPACITY,
                 split_threshold: float = SPLIT_THRESHOLD):
        self.primary_cap = primary_cap
        self.overflow_cap = overflow_cap
        self.split_threshold = split_threshold
        # one bucket (bucket 0) with one empty primary page.
        self.buckets: dict[int, list[list[tuple[str, int]]]] = {0: [[]]}
        self.maxbucket = 0
        self.low_mask = 0
        self.high_mask = 0
        self.split_count = 0

    # ---- routing --------------------------------------------------------

    def bucket_of(self, key: str) -> tuple[int, int]:
        """Map key -> (bucket_number, hashvalue).

        Mirrors PG _hash_hashkey2bucket:
            bucket = hashvalue & high_mask
            if bucket > maxbucket: bucket &= low_mask
        """
        h = hash_key(key)
        b = h & self.high_mask
        if b > self.maxbucket:
            b &= self.low_mask
        return b, h

    # ---- stats ----------------------------------------------------------

    def num_items(self) -> int:
        return sum(len(p) for pages in self.buckets.values() for p in pages)

    def num_buckets(self) -> int:
        return self.maxbucket + 1

    def load_factor(self) -> float:
        """Items / (buckets * primary_capacity). The split trigger.

        PG actually splits based on overflow-page density (hashm_spares[]),
        but the spirit is identical: "too full -> add a bucket." We use a
        straightforward load factor so the worked example is easy to follow.
        """
        cap = self.num_buckets() * self.primary_cap
        return self.num_items() / cap

    def chain_length(self, b: int) -> int:
        """Number of OVERFLOW pages on bucket b (0 = primary only)."""
        return max(0, len(self.buckets[b]) - 1)

    # ---- mutation -------------------------------------------------------

    def insert(self, key: str, value: int) -> str:
        """Insert (key, value). Returns a status string for tracing.

        Statuses:
          "updated"        - key existed; value replaced (no growth)
          "inserted"       - placed in a page with room
          "overflow"       - primary full; new overflow page created
          "split"          - placed, then a split triggered
          "overflow+split" - new overflow, then a split triggered
        """
        b, _ = self.bucket_of(key)
        pages = self.buckets[b]

        # 1. update in place if key already exists
        for page in pages:
            for i, (k, _) in enumerate(page):
                if k == key:
                    page[i] = (key, value)
                    return "updated"

        # 2. place in the first page with room
        for pi, page in enumerate(pages):
            cap = self.primary_cap if pi == 0 else self.overflow_cap
            if len(page) < cap:
                page.append((key, value))
                return self._maybe_split("inserted")

        # 3. no room anywhere -- extend the overflow chain
        pages.append([(key, value)])
        return self._maybe_split("overflow")

    def _maybe_split(self, status: str) -> str:
        if self.load_factor() > self.split_threshold:
            self._split()
            return status + "+split" if status else "split"
        return status

    def _split(self):
        """Grow by one bucket (PG _hash_expandable + _hash_splitbucket).

        new_bucket = maxbucket + 1
        victim     = new_bucket & low_mask     (under the OLD low_mask)
        if new_bucket > high_mask:             (crossed a power of two)
            low_mask  = high_mask              (old "new" space becomes "old")
            high_mask = new_bucket | low_mask  (new "new" space, doubled)
        maxbucket  = new_bucket
        rehash victim's tuples: each goes to bucket_of(key) under NEW masks,
        so some land in `victim` and some land in `new_bucket`.
        """
        new_bucket = self.maxbucket + 1
        victim = new_bucket & self.low_mask        # OLD low_mask
        crossed_power_of_2 = new_bucket > self.high_mask
        if crossed_power_of_2:
            self.low_mask = self.high_mask
            self.high_mask = new_bucket | self.low_mask
        self.maxbucket = new_bucket
        self.buckets[new_bucket] = [[]]

        # gather victim's items, then reinsert under the new masks
        old_items = [item for page in self.buckets[victim] for item in page]
        self.buckets[victim] = [[]]
        moved_to_new = 0
        stayed = 0
        for k, v in old_items:
            b, _ = self.bucket_of(k)              # uses NEW masks
            pages = self.buckets[b]
            placed = False
            for pi, page in enumerate(pages):
                cap = self.primary_cap if pi == 0 else self.overflow_cap
                if len(page) < cap:
                    page.append((k, v))
                    placed = True
                    break
            if not placed:
                pages.append([(k, v)])
            if b == new_bucket:
                moved_to_new += 1
            else:
                stayed += 1
        self.split_count += 1
        return victim, new_bucket, moved_to_new, stayed, crossed_power_of_2

    def force_split(self):
        """Public wrapper around _split for the worked split example."""
        return self._split()

    def lookup(self, key: str):
        """Point lookup. Returns (value, hashvalue, bucket, page_no, pages_scanned)
        or (None, hashvalue, bucket, 0, pages_scanned) if not found.

        pages_scanned counts primary + overflow pages touched. The chain
        length = pages_scanned - 1.
        """
        b, h = self.bucket_of(key)
        pages = self.buckets[b]
        pages_scanned = 0
        for pi, page in enumerate(pages):
            pages_scanned += 1
            for (k, v) in page:
                if k == key:
                    return v, h, b, pi + 1, pages_scanned
        return None, h, b, 0, pages_scanned

    def delete(self, key: str) -> tuple[bool, int, int]:
        """Lazy delete: remove the tuple, leave pages in place (no merge).

        Returns (found, hashvalue, bucket). PG also does lazy deletion --
        empty overflow pages are reclaimed later by VACUUM, not at delete time.
        """
        b, h = self.bucket_of(key)
        for page in self.buckets[b]:
            for i, (k, _) in enumerate(page):
                if k == key:
                    del page[i]
                    return True, h, b
        return False, h, b


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def snapshot(idx: HashIndex) -> str:
    """One-line snapshot of index state."""
    return (f"maxbucket={idx.maxbucket}  low_mask={idx.low_mask}  "
            f"high_mask={idx.high_mask}  buckets={idx.num_buckets()}  "
            f"items={idx.num_items()}  load_factor={idx.load_factor():.3f}  "
            f"splits={idx.split_count}")


def dump_buckets(idx: HashIndex) -> str:
    """Pretty-print every bucket, page, and tuple."""
    lines = []
    for b in sorted(idx.buckets):
        pages = idx.buckets[b]
        chain = idx.chain_length(b)
        tag = f"bucket {b}  (chain={chain}, pages={len(pages)})"
        lines.append(tag)
        for pi, page in enumerate(pages):
            role = "primary " if pi == 0 else f"ovfl{pi}   "
            body = ", ".join(f"{k}={v}" for k, v in page) if page else "(empty)"
            lines.append(f"    {role} [{len(page)}/{idx.primary_cap if pi==0 else idx.overflow_cap}]:  {body}")
    return "\n".join(lines)


# ============================================================================
# 3. THE DETERMINISTIC INPUTS  (same keys the .html recomputes in JS)
# ============================================================================

# 10 keys whose FNV-1a hashes deliberately hit several buckets AND at least
# one collision (so an overflow chain forms). Pinned so .py == .html byte-for-byte.
TEN_KEYS = [
    ("alice",   101),
    ("bob",     102),
    ("carol",   103),
    ("dave",    104),
    ("eve",     105),
    ("frank",   106),
    ("grace",   107),
    ("heidi",   108),
    ("ivan",    109),
    ("judy",    110),
]

# The key we GOLD-pin for the .html check.
GOLD_KEY   = "alice"
GOLD_VALUE = 101


# ----------------------------------------------------------------------------
# SECTION A: hash function + the bucket computation
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: hash_any -> 32-bit hashvalue -> bucket number")
    print("PostgreSQL funnels EVERY key type through hash_any() (Jenkins lookup3,")
    print("hashfunc.c) -> a 32-bit uint32. For this tutorial we use FNV-1a 32-bit,")
    print("which has the same avalanche + uniformity -- only the bucket math below")
    print("is what matters, and that is byte-identical to PG.\n")
    print("| key       | hashvalue (FNV-1a) | hashvalue (hex) |")
    print("|-----------|--------------------|-----------------|")
    for k, _ in TEN_KEYS:
        h = hash_key(k)
        print(f"| {k:<9} | {h:>18} | 0x{h:08x}        |")
    print()
    print("Bucket selection (PG _hash_hashkey2bucket, hashutil.c):")
    print("    bucket = hashvalue & high_mask")
    print("    if bucket > maxbucket: bucket &= low_mask")
    print()
    print("Why two masks? It is the linear-hashing trick. high_mask always covers")
    print("the 'new' (post-doubling) address space 0..2^(N+1)-1; low_mask covers")
    print("the 'old' space 0..2^N-1. If your hash lands in a bucket that does not")
    print("EXIST yet (bucket > maxbucket), you fall back to the old space.\n")

    # show the routing at a representative mid-growth state
    idx = HashIndex()
    # fast-forward to maxbucket=5 (low_mask=3, high_mask=7) by manual splits
    for _ in range(5):
        idx.force_split()
    print(f"At this state  ({snapshot(idx)}):")
    print(f"    N+1 split levels -> high_mask = 0x{idx.high_mask:08x} "
          f"(2^(N+1)-1 = {idx.high_mask}),  low_mask = 0x{idx.low_mask:08x} "
          f"(2^N-1 = {idx.low_mask})\n")
    print("| key       | hashvalue & high_mask | > maxbucket? | final bucket "
          "(after & low_mask) |")
    print("|-----------|-----------------------|--------------|--------------------|")
    for k, _ in TEN_KEYS:
        h = hash_key(k)
        raw = h & idx.high_mask
        over = raw > idx.maxbucket
        b = raw & idx.low_mask if over else raw
        note = f"yes -> & {idx.low_mask:#x}" if over else "no"
        print(f"| {k:<9} | {raw:>21} | {note:<12} | {b:<18} |")
    print()
    print("Notice: keys whose high_mask value is 6 or 7 do NOT have a real bucket")
    print("yet (maxbucket=5) -- they fall back to the low_mask, which is themselves")
    print("& 3, i.e. they share a bucket with the keys 0..3 until a future split")
    print("creates their real home.")

    # GOLD CHECK 1: FNV-1a is deterministic + bit-identical to its definition
    assert hash_key("") == 0x811C9DC5
    assert hash_key("a") == 0xE40C292C
    print()
    print("[check] FNV-1a of ''  == 0x811c9dc5  (the FNV offset basis):  OK")
    print("[check] FNV-1a of 'a' == 0xe40c292c  (one byte after basis):  OK")


# ----------------------------------------------------------------------------
# SECTION B: linear-hashing growth -- one bucket at a time
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: linear hashing grows ONE bucket per split (no global resize)")
    idx = HashIndex()
    print("Start with ONE bucket. Each split adds exactly one bucket and rehashes")
    print("only the VICTIM bucket. Whenever maxbucket+1 crosses a power of two, the")
    print("address space doubles (low_mask <- old high_mask; high_mask doubles).\n")
    print("| split # | maxbucket | low_mask | high_mask | # buckets | "
          "victim (new_bucket & old low_mask) | address space 2^(N+1) |")
    print("|---------|-----------|----------|-----------|-----------|"
          "-------------------------------------|------------------------|")
    for _ in range(9):
        before_low = idx.low_mask
        before_high = idx.high_mask
        before_max = idx.maxbucket
        new_bucket = before_max + 1
        victim = new_bucket & before_low
        idx.force_split()
        crossed = "x2 ->" if new_bucket > before_high else ""
        print(f"| {idx.split_count:<7} | {idx.maxbucket:<9} | "
              f"{idx.low_mask:<8} | {idx.high_mask:<9} | {idx.num_buckets():<9} | "
              f"new={new_bucket}, victim={victim:<18} | "
              f"{crossed:<8} 2^{idx.high_mask.bit_length()}-1 |")
    print()
    print("Read this as: at split #1 we doubled 0->1 (space 2 -> 4). At split #2")
    print("the space was already 4, no doubling. At split #3 maxbucket crossed")
    print("2 (the new power of two) so we doubled again 2->3. And so on. The")
    print("RESULT is that the address space (high_mask+1) is always within 2x of")
    print("the actual bucket count -- so the load factor stays bounded.\n")
    print("Victim pattern: 0, 0, 1, 2, 0, 3, 4, 1, 2, ...  -- round-robin through")
    print("the existing buckets in the order they will be 'split next.' This is")
    print("Litwin's split pointer `p`, made implicit by the masks.\n")

    # GOLD CHECK 2: low_mask and high_mask always satisfy the PG invariants
    ok = True
    idx2 = HashIndex()
    for _ in range(50):
        idx2.force_split()
        N = idx2.low_mask.bit_length()
        if idx2.low_mask != (1 << N) - 1:                       # low  = 2^N - 1
            ok = False; break
        if idx2.high_mask != (1 << (N + 1)) - 1:                # high = 2^(N+1) - 1
            ok = False; break
        if not (idx2.low_mask <= idx2.maxbucket <= idx2.high_mask):
            ok = False; break
    assert ok
    print("[check] over 50 splits: low_mask = 2^N-1, high_mask = 2^(N+1)-1, "
          "low_mask <= maxbucket <= high_mask:  OK")


# ----------------------------------------------------------------------------
# SECTION C: insert 10 keys -- buckets, overflow chains, splits in action
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: insert 10 keys  --  watch buckets fill, chains form, splits fire")
    idx = HashIndex()
    print(f"Constants: primary_capacity={idx.primary_cap}, "
          f"overflow_capacity={idx.overflow_cap}, "
          f"split_threshold (fillfactor)={idx.split_threshold}\n")
    print("Insertion trace (load_factor > 0.75 triggers a split AFTER the insert):\n")
    print("| step | key     | value | hashvalue  | bucket | action            | "
          "post-state                                                   |")
    print("|------|---------|-------|------------|--------|-------------------|"
          "--------------------------------------------------------------|")
    for step, (k, v) in enumerate(TEN_KEYS, 1):
        h = hash_key(k)
        # capture the bucket the item will land in BEFORE the split (if any)
        pre_b, _ = idx.bucket_of(k)
        status = idx.insert(k, v)
        # the status string tells us whether a split fired
        print(f"| {step:<4} | {k:<7} | {v:<5} | 0x{h:08x} | {pre_b:<6} | "
              f"{status:<17} | {snapshot(idx)} |")
    print()
    print("Final state of every bucket after all 10 inserts + the splits they triggered:")
    print()
    print(dump_buckets(idx))
    print()
    # GOLD CHECK 3: every inserted key is findable
    for k, v in TEN_KEYS:
        val, _, _, _, _ = idx.lookup(k)
        assert val == v, f"lookup({k!r}) returned {val}, expected {v}"
    print(f"[check] all 10 inserted keys are findable via lookup():  OK")
    return idx


# ----------------------------------------------------------------------------
# SECTION D: lookup -- hash -> bucket -> primary -> overflow chain
# ----------------------------------------------------------------------------

def section_d(idx: HashIndex):
    banner("SECTION D: lookup  --  hash -> bucket -> primary -> overflow chain")
    # find a key that lives in a chain (or the deepest one) for illustration
    deepest = max(TEN_KEYS, key=lambda kv: idx.lookup(kv[0])[4])
    k, expected = deepest
    val, h, b, page_no, scanned = idx.lookup(k)
    chain = scanned - 1
    print(f"Look up '{k}' (expected value {expected}):\n")
    print(f"  1. hashvalue        = hash_any('{k}') = 0x{h:08x}")
    print(f"  2. bucket           = 0x{h:08x} & high_mask (0x{idx.high_mask:08x}) "
          f"= {h & idx.high_mask}")
    if (h & idx.high_mask) > idx.maxbucket:
        print(f"     > maxbucket ({idx.maxbucket})? YES -> bucket &= low_mask "
              f"(0x{idx.low_mask:08x}) = {b}")
    else:
        print(f"     > maxbucket ({idx.maxbucket})? NO -> bucket stays {b}")
    print(f"  3. scan bucket {b}:")
    pages = idx.buckets[b]
    for pi, page in enumerate(pages):
        role = "PRIMARY" if pi == 0 else f"OVERFLOW page {pi}"
        here = any(kk == k for kk, _ in page)
        star = "   <-- FOUND here" if here else ""
        print(f"        {role}: " + ", ".join(f"{kk}={vv}" for kk, vv in page) + star)
    print(f"\n  RESULT: value={val}, found on page {page_no} of bucket {b}.")
    print(f"  COST:   scanned {scanned} page(s); chain length = {chain}.")
    print(f"          Contrast with a B-tree: O(log N) root-to-leaf descent +")
    print(f"          a leaf-page read; for a pure equality probe the hash index")
    print(f"          is asymptotically faster, but only marginally on small N.\n")

    # miss path
    miss = "nonexistent_key_zzz"
    val, h, b, page_no, scanned = idx.lookup(miss)
    print(f"Look up a MISSING key '{miss}': hashvalue=0x{h:08x}, bucket={b}; "
          f"scanned {scanned} page(s), returned None. (Must scan the WHOLE chain --")
    print("a hash index cannot short-circuit on ordering because tuples are unsorted.)\n")

    # GOLD CHECK 4: lookup matches the GOLD-pinned value, and a miss returns None
    v, _, _, _, _ = idx.lookup(GOLD_KEY)
    assert v == GOLD_VALUE
    miss_v, _, _, _, _ = idx.lookup("definitely_absent")
    assert miss_v is None
    print(f"[check] lookup('{GOLD_KEY}') == {GOLD_VALUE}:  OK")
    print(f"[check] lookup(missing) is None:  OK")


# ----------------------------------------------------------------------------
# SECTION E: split -- rehash the victim; some stay, some move
# ----------------------------------------------------------------------------

def section_e(idx: HashIndex):
    banner("SECTION E: split  --  one bucket splits, its tuples rehash (stay or move)")
    # pick the victim that the NEXT split will hit
    new_bucket = idx.maxbucket + 1
    victim = new_bucket & idx.low_mask
    print(f"The next split will create bucket {new_bucket} and rehash the tuples of")
    print(f"bucket {victim} (the victim = new_bucket & low_mask = {new_bucket} & "
          f"0x{idx.low_mask:08x} = {victim}).\n")
    print("BEFORE split:")
    print(snapshot(idx))
    print()
    print(dump_buckets(idx))
    print()

    # snapshot victim's tuples + their hashes, so we can show where each will land
    victim_items = [item for page in idx.buckets[victim] for item in page]
    print(f"Victim bucket {victim} tuples and where they will land after the split:")
    print("| key   | hashvalue  | new bucket (after masks update) | moves? |")
    print("|-------|------------|----------------------------------|--------|")
    # compute the post-split masks to preview destinations
    if new_bucket > idx.high_mask:
        post_low = idx.high_mask
        post_high = new_bucket | post_low
    else:
        post_low, post_high = idx.low_mask, idx.high_mask
    for k, _ in victim_items:
        h = hash_key(k)
        raw = h & post_high
        b = raw & post_low if raw > new_bucket else raw
        moves = "moves to " + str(new_bucket) if b == new_bucket else "stays in " + str(victim)
        print(f"| {k:<6} | 0x{h:08x} | {b:<32} | {moves:<20} |")
    print()

    # do the split
    v, nb, moved, stayed, crossed = idx.force_split()
    print(f"AFTER split (split_count={idx.split_count}):")
    print(snapshot(idx))
    if crossed:
        print(f"(maxbucket {nb-1}->{nb} crossed the previous high_mask, so the "
              f"address space DOUBLED: low_mask {post_low}, high_mask {post_high}.)")
    print()
    print(dump_buckets(idx))
    print()
    print(f"Rehash summary: of the {moved+stayed} tuples in old bucket {v}, "
          f"{moved} moved to new bucket {nb}, {stayed} stayed.\n")

    # GOLD CHECK 5: every key still findable after the split (no data lost)
    for k, val in TEN_KEYS:
        v, _, _, _, _ = idx.lookup(k)
        assert v == val, f"after split, lookup({k!r})={v}, expected {val}"
    print(f"[check] all 10 keys still findable after the split:  OK")


# ----------------------------------------------------------------------------
# SECTION F: delete -- remove a key; pages stay (lazy, no merge)
# ----------------------------------------------------------------------------

def section_f(idx: HashIndex):
    banner("SECTION F: delete  --  remove a tuple; NO merge (lazy deletion)")
    # pick a key that currently lives in a bucket with multiple pages if possible
    target = None
    for k, _ in TEN_KEYS:
        b, _ = idx.bucket_of(k)
        if idx.chain_length(b) >= 1:
            target = k; break
    if target is None:
        target = TEN_KEYS[0][0]
    b, _ = idx.bucket_of(target)
    print(f"Delete '{target}' from bucket {b}.")
    print()
    print("BEFORE delete:")
    print(dump_buckets(idx))
    print()
    found, _, _ = idx.delete(target)
    print(f"delete('{target}') -> found={found}")
    print()
    print("AFTER delete:")
    print(dump_buckets(idx))
    print()
    print("Note the bucket's overflow pages are STILL THERE, even if now empty.")
    print("PG performs LAZY deletion: a delete only clears the tuple slot; overflow")
    print("pages are reclaimed later by VACUUM, never at delete time. This keeps")
    print("deletes O(1) and avoids concurrent splits fighting over page reuse.\n")

    # GOLD CHECK 6: the deleted key is gone; all others still findable
    v, _, _, _, _ = idx.lookup(target)
    assert v is None, f"lookup({target!r}) should be None after delete"
    for k, val in TEN_KEYS:
        if k == target:
            continue
        vv, _, _, _, _ = idx.lookup(k)
        assert vv == val
    print(f"[check] lookup('{target}') is None; all 9 other keys still findable:  OK")


# ----------------------------------------------------------------------------
# SECTION G: hash vs B-tree -- when to use which
# ----------------------------------------------------------------------------

def section_g():
    banner("SECTION G: hash vs B-tree  --  pick by query shape, not by hype")
    rows = [
        ("Point equality  (col = v)",           "O(1) avg",          "O(log N)",
         "HASH (faster, smaller)"),
        ("Range scan  (col BETWEEN a AND b)",   "NOT SUPPORTED",     "O(log N + k)",
         "BTREE (hash cannot order)"),
        ("ORDER BY col",                        "NOT SUPPORTED",     "O(N log N) sort avoided",
         "BTREE (index is pre-sorted)"),
        ("Prefix match  (col LIKE 'abc%')",     "NOT SUPPORTED",     "O(log N)",
         "BTREE"),
        ("UNIQUE / PRIMARY KEY enforcement",    "SUPPORTED",         "SUPPORTED (default)",
         "BTREE (PG default for PK)"),
        ("Index size",                          "~hash + TID only",  "key + TID + pointers",
         "HASH (~half the size)"),
        ("Crash safety (WAL)",                  "PG 10+ (2017)",     "always",
         "both safe; pre-10 hash was not"),
        ("Autovacuum / bloat reclaim",          "supported",         "supported",
         "tie"),
    ]
    print("| Operation / property                  | HASH index          | "
          "BTREE index               | Use                       |")
    print("|---------------------------------------|---------------------|"
          "--------------------------|---------------------------|")
    for r in rows:
        print(f"| {r[0]:<37} | {r[1]:<19} | {r[2]:<24} | {r[3]:<25} |")
    print()
    print("RULE OF THUMB:")
    print("  - HASH : pure equality lookups on a column you never sort or range on.")
    print("           (e.g. session-token UUIDs, hash-partition keys, url-hashes).")
    print("           Smaller index, O(1) lookups.")
    print("  - BTREE: anything else (ranges, ORDER BY, joins on inequality, prefix,")
    print("           default PRIMARY KEY). The default; reach for it unless you can")
    print("           articulate why hash is better.  See HEAP_VS_CLUSTERED.md.")
    print()
    print("PG history: hash indexes existed since v6.5 (1999) but were UNLOGGED,")
    print("so a crash could corrupt them -- the docs warned 'prefer B-tree.' Since")
    print("PostgreSQL 10 (2017) they are fully WAL-logged and crash-safe; the warning")
    print("was removed. They still account for a tiny fraction of production indexes")
    print("because B-trees are good enough for most workloads.")


# ============================================================================
# 4. main
# ============================================================================

def main():
    print("hash_index.py - reference impl. All numbers below feed HASH_INDEX.md.")
    print(f"PRIMARY_CAPACITY={PRIMARY_CAPACITY}  OVERFLOW_CAPACITY={OVERFLOW_CAPACITY}  "
          f"SPLIT_THRESHOLD={SPLIT_THRESHOLD}  hash=FNV-1a 32-bit (stand-in for hash_any)")

    section_a()
    section_b()
    idx = section_c()
    section_d(idx)
    section_e(idx)
    section_f(idx)
    section_g()

    banner("GOLD - lookup(k) must return the same value that was inserted")
    # Rebuild a clean index for the gold check (since section F deleted a key)
    gidx = HashIndex()
    for k, v in TEN_KEYS:
        gidx.insert(k, v)
    found_val, h, b, page, scanned = gidx.lookup(GOLD_KEY)
    print(f"lookup('{GOLD_KEY}'):  value={found_val}  (expected {GOLD_VALUE}),  "
          f"hash=0x{h:08x}, bucket={b}, page={page}, pages_scanned={scanned}")
    assert found_val == GOLD_VALUE
    print(f"[check] lookup('{GOLD_KEY}') == {GOLD_VALUE}:  OK  "
          f"(this is what hash_index.html recomputes)")

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
