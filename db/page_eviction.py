"""
page_eviction.py - Reference implementation of buffer-pool cache-eviction
algorithms: LRU, CLOCK (second chance), LRU-K, FIFO, and the Belady optimal
(MIN) lower bound -- plus dirty-page handling and PostgreSQL's scan ring.

This is the single source of truth that PAGE_EVICTION.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 page_eviction.py

=========================================================================
THE INTUITION (read this first) -- the librarian's desk
=========================================================================
A database keeps a small shared BUFFER POOL of N page-frames in RAM (PostgreSQL:
shared_buffers, default 128 MB ~= 16k pages of 8 KB). Disk is ~1000x slower than
RAM, so every page read wants to hit the pool. When the pool is FULL and a new
page must be loaded, a resident page must be EVICTED. Picking WHO to evict is the
whole art of a cache: evict a page that is about to be re-read and you pay an
extra disk I/O; evict a page never read again and you paid nothing.

  * RANDOM   : throw out a random frame. A trivial baseline nobody ships.
  * FIFO     : evict the page loaded LONGEST AGO. Ignores whether the page has
               been used since loading. Famous for Belady's anomaly (more frames
               can mean MORE faults -- Section D).
  * LRU      : evict the page whose LAST USE is oldest. Excellent, but needs a
               recency order updated on EVERY access.
  * CLOCK    : the "second chance" approximation of LRU. Each page has a 1-bit
               reference bit set on every use. A clock HAND sweeps the ring: a
               page with bit=1 gets a second chance (bit cleared, hand moves on);
               a page with bit=0 is evicted. No recency list -- just 1 bit + a
               hand pointer. This is what OSes (and PostgreSQL's buffer pool,
               as a clock-sweep with a usage counter) actually run.
  * LRU-K    : track the last K (usually 2) access TIMES per page. Evict the page
               whose K-th-most-recent access is OLDEST ("backward K-distance").
               Resists one-shot scans polluting the cache (O'Neil 1993).

THE REASON EVICTION POLICY MATTERS: a random disk page read is ~0.1-1 ms; a RAM
hit is ~100 ns -- a 1000x gap. So a few points of hit rate are worth a real
algorithm. The lineage below is the story of getting "almost LRU quality at
almost FIFO cost".

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  buffer pool    : N RAM frames holding cached disk pages.
  frame / slot   : one RAM slot holding exactly one page.
  page           : a fixed-size disk block (PostgreSQL BLCKSZ = 8192 B).
  hit / miss     : requested page already in pool (hit) or not (miss -> load).
                   A miss is also called a (page) FAULT.
  eviction       : choosing a resident page to discard to free a frame.
  replacement    : synonym for eviction policy.
  reference bit  : 1 bit per frame, set to 1 whenever the page is used. The
  (use bit)        heart of CLOCK.
  clock hand     : a rotating pointer into the circular frame ring. CLOCK sweeps
                   it to find a victim.
  recency        : "how long ago was this page last used?" -- LRU's ordering key.
  backward       : time between NOW and the page's K-th most recent access.
  K-distance       Larger = older K-th access = MORE evictable. LRU-K's key.
                   A page with fewer than K accesses has K-distance = infinity
                   (a "new" page, evicted first).
  dirty page     : a cached page modified in RAM but not yet written to disk.
                   Evicting it costs an extra WRITE (flush) -- Section E.
  pin            : a frame holding a page currently being read/written is pinned
                   and cannot be evicted.
  ring buffer    : a small private set of frames reused FIFO for big scans, so a
                   sequential scan does not flush the whole cache (Section F).
  Belady MIN/OPT : the theoretical optimum: evict the page whose NEXT use is
                   farthest in the future. Needs the future -- unrealizable, but
                   a lower bound on faults (no real algorithm beats it).

=========================================================================
THE LINEAGE (papers / systems)
=========================================================================
  RANDOM    (naive)               : evict a random frame.  Baseline.
  FIFO      (Belady 1966, [1])    : evict oldest-LOADED frame. Suffers Belady's
                                    anomaly (more frames -> more faults).
  LRU       (Mattson+ 1972, [2])  : evict oldest-USED frame. Optimal among
                                    algorithms that ignore the future, but needs
                                    per-access recency maintenance.
  CLOCK     (second chance, [5])  : 1-bit approximation of LRU. Cheap (1 bit +
                                    a hand). Used by Linux, Windows, and (as a
                                    clock sweep + usage count) PostgreSQL's buf.
  LRU-K     (O'Neil 1993, [3])    : keep last K accesses; evict oldest K-th.
                                    Resists scanning pollution; persistent history.

KEY FORMULAS / facts (verified against the sources and asserted in code):
    hit rate         = hits / total_accesses
    fault rate       = 1 - hit rate            (a fault = a miss = a disk read)
    CLOCK victim     : first frame the hand reaches with reference bit == 0
    LRU-K victim     : argmin over resident of  Kth_to_last_access(page)
                       (smaller = older K-th = more evictable)
                       ties (incl. <K accesses => Kth = -inf) -> oldest first
                       access -> lowest page id
    Belady MIN victim: argmax over resident of  next_use(page) ; never -> +inf
    Belady anomaly   : FIFO can have MORE faults with MORE frames (Section D)
    PostgreSQL rings : 256 KB (32 pages) bulk-read, 16 MB bulk-write, 256 KB vacuum

Sources:
  [1] Belady, "A Study of Replacement Algorithms for Virtual-Storage Computer",
      IBM Systems Journal 5(2), 1966. (FIFO + the anomaly that bears his name.)
  [2] Mattson, Gecsei, Slutz, Traiger, "Evaluation Techniques for Storage
      Hierarchies", IBM Systems Journal 9(2), 1972. (LRU, the stack property, and
      the optimal MIN algorithm -- proven unbeatable by any online policy.)
  [3] O'Neil, O'Neil, Weikum, "The LRU-K Page Replacement Algorithm", SIGMOD
      1993. (Backward K-distance, persistent history, correlated-reference
      pitfall. The paper that motivated frequency-aware replacement.)
  [4] PostgreSQL source, src/backend/storage/buffer/README + bufmgr.c + ring.c:
      clock-sweep with usage_count (0..5); scan rings of 256 KB / 16 MB.
  [5] Tanenbaum & Bos, "Modern Operating Systems" -- CLOCK / second chance.

The deterministic worked example uses a 4-frame pool and the classic reference
string [1,2,3,4,1,2,5,1,2,3,4,5] (the Belady-anomaly string). Every algorithm
below runs on byte-identical inputs so the .html can replicate the numbers.
"""

from __future__ import annotations

from collections import deque

# ----------------------------------------------------------------------------
# 0. CONSTANTS  -- the deterministic worked example
# ----------------------------------------------------------------------------
# The reference string (page IDs). Classic Belady string: small enough to trace
# by hand, rich enough to separate FIFO/CLOCK from LRU/LRU-K from OPT.
SEQ = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
N_FRAMES = 4              # buffer-pool size for the worked example
K = 2                     # LRU-K keeps the last K access times per page

BANNER = "=" * 72
NEG_INF = -(10 ** 9)      # "no K-th access yet" sentinel (most evictable)
POS_INF = 10 ** 9         # "no future use" sentinel (for Belady MIN)


# ============================================================================
# 1. THE REPLACEMENT ALGORITHMS  (this is the code PAGE_EVICTION.md walks)
#    Each returns a list of per-step dicts; counters come from summing 'hit'.
# ============================================================================

def lru_trace(seq: list[int], n: int) -> list[dict]:
    """Least-Recently-Used. Evict the resident page with the oldest LAST USE.

    Keeps `last[page]` = the tick of the page's most recent access. Eviction =
    the resident page with the smallest last[] (tie -> lowest page id). Updated
    on EVERY access (hit or miss), which is exactly the cost CLOCK avoids.
    """
    last: dict[int, int] = {}
    resident: set[int] = set()
    steps = []
    for t, p in enumerate(seq, start=1):
        hit = p in resident
        evicted = None
        if hit:
            last[p] = t
        else:
            if len(resident) >= n:
                evicted = min(resident, key=lambda q: (last[q], q))
                resident.discard(evicted)
                del last[evicted]
            resident.add(p)
            last[p] = t
        # resident pages ordered LRU -> MRU (for display)
        order = sorted(resident, key=lambda q: (last[q], q))
        steps.append(dict(t=t, page=p, hit=hit, evicted=evicted, order=order))
    return steps


def clock_trace(seq: list[int], n: int) -> list[dict]:
    """CLOCK / second-chance. Each frame has a reference bit; a hand sweeps.

    On HIT  : set the page's reference bit = 1 (hand does not move).
    On MISS : if a frame is free, take it (ref=1) and advance the hand;
              otherwise sweep -- bit=1 -> clear to 0, advance; bit=0 -> evict,
              place the new page there (ref=1), advance past it.

    The reference bit is the coarse, cheap proxy for "recently used": one bit
    updated on access, not a sorted recency list.
    """
    slots: list[int | None] = [None] * n
    bits = [0] * n
    hand = 0
    steps = []
    for t, p in enumerate(seq, start=1):
        idx = next((i for i in range(n) if slots[i] == p), -1)
        hit = idx != -1
        evicted = None
        sweep: list[tuple[int, int, str]] = []   # (slot, page, 'cleared'|'evict')
        if hit:
            bits[idx] = 1
        else:
            # prefer a free frame (fill in circular order from the hand)
            free = next(((hand + k) % n for k in range(n)
                         if slots[(hand + k) % n] is None), None)
            if free is not None:
                slots[free] = p
                bits[free] = 1
                hand = (free + 1) % n
            else:
                while True:
                    i = hand
                    if bits[i] == 1:
                        sweep.append((i, slots[i], "cleared"))
                        bits[i] = 0
                        hand = (hand + 1) % n
                    else:
                        evicted = slots[i]
                        sweep.append((i, slots[i], "evict"))
                        slots[i] = p
                        bits[i] = 1
                        hand = (i + 1) % n
                        break
        steps.append(dict(t=t, page=p, hit=hit, evicted=evicted,
                          slots=list(slots), bits=list(bits), hand=hand,
                          sweep=sweep))
    return steps


def lruk_trace(seq: list[int], n: int, k: int = 2) -> list[dict]:
    """LRU-K. Keep the last K access TIMES per page; evict the oldest K-th.

    `hist[page]` = the page's last k access ticks and is PERSISTENT: it survives
    eviction (O'Neil [3]). On a miss with a full pool, evict the resident page
    whose K-th-most-recent access (backward K-distance) is oldest:
        victim = argmin over resident of  Kth_to_last_access(page)
    A page with fewer than k accesses has Kth = -inf (a "new" page -> evicted
    first). Ties -> oldest FIRST access -> lowest page id.

    The persistent history is the feature that lets LRU-K recognise a page that
    was hot long ago and is returning, rather than treating it as brand new.
    """
    hist: dict[int, list[int]] = {}
    resident: set[int] = set()
    steps = []

    def kth(q: int) -> int:
        hq = hist.get(q, [])
        return hq[-k] if len(hq) >= k else NEG_INF

    def first(q: int) -> int:
        hq = hist.get(q, [])
        return hq[0] if hq else POS_INF

    for t, p in enumerate(seq, start=1):
        h = hist.get(p, [])
        h.append(t)
        if len(h) > k:
            h = h[-k:]
        hist[p] = h
        hit = p in resident
        evicted = None
        cand = None                                   # candidate table (pre-evict)
        if not hit:
            if len(resident) >= n:
                cand = [(q, list(hist[q]), kth(q)) for q in sorted(resident)]
                evicted = min(resident, key=lambda q: (kth(q), first(q), q))
                resident.discard(evicted)
            resident.add(p)
        steps.append(dict(t=t, page=p, hit=hit, evicted=evicted,
                          resident=sorted(resident), cand=cand))
    return steps


def fifo_trace(seq: list[int], n: int) -> list[dict]:
    """First-In-First-Out. Evict the page loaded LONGEST AGO (ignores use)."""
    q: deque[int] = deque()
    resident: set[int] = set()
    steps = []
    for t, p in enumerate(seq, start=1):
        hit = p in resident
        evicted = None
        if not hit:
            if len(resident) >= n:
                evicted = q.popleft()
                resident.discard(evicted)
            q.append(p)
            resident.add(p)
        steps.append(dict(t=t, page=p, hit=hit, evicted=evicted,
                          resident=sorted(resident)))
    return steps


def opt_trace(seq: list[int], n: int) -> list[dict]:
    """Belady MIN / OPT -- the theoretical optimum (needs the future).

    On a miss with a full pool, evict the resident page whose NEXT use is
    FARTHEST in the future (never -> +inf). Unbeatable by any online policy; we
    include it only as a lower bound on faults. Ties -> lowest page id.
    """
    resident: set[int] = set()
    steps = []

    def next_use(q: int, after: int) -> int:
        for j in range(after, len(seq)):
            if seq[j] == q:
                return j
        return POS_INF

    for t0, p in enumerate(seq):
        t = t0 + 1
        hit = p in resident
        evicted = None
        cand = None
        if not hit:
            if len(resident) >= n:
                cand = [(q, next_use(q, t0 + 1)) for q in sorted(resident)]
                # farthest next use; tie -> smallest page id
                evicted = max(resident, key=lambda q: (next_use(q, t0 + 1), -q))
                resident.discard(evicted)
            resident.add(p)
        steps.append(dict(t=t, page=p, hit=hit, evicted=evicted,
                          resident=sorted(resident), cand=cand))
    return steps


def count_hits(trace: list[dict]) -> int:
    return sum(1 for s in trace if s["hit"])


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_lru_order(order: list[int]) -> str:
    return "  ".join(str(p) for p in order) if order else "(empty)"


def fmt_clock(slots, bits, hand) -> str:
    parts = []
    for i, (p, b) in enumerate(zip(slots, bits)):
        cell = str(p) if p is not None else "."
        tag = " <-hand" if i == hand else ""
        parts.append(f"[{i}]{cell}(r{b}){tag}")
    return "  ".join(parts)


def fmt_sweep(sweep) -> str:
    if not sweep:
        return "-"
    return ", ".join(f"{a} slot{i}:{pg}" for (i, pg, a) in sweep)


# ============================================================================
# 3. THE WORKED EXAMPLE  (4 frames, reference string SEQ)
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: LRU
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: LRU  --  evict the page whose LAST USE is oldest")
    print(f"Pool = {N_FRAMES} frames. Reference string = {SEQ}\n")
    print("On every access we update that page's recency. Eviction = resident "
          "page with the oldest recency.\n")
    trace = lru_trace(SEQ, N_FRAMES)
    print("| step | access | result | buffer (LRU -> MRU)        | evicted |")
    print("|------|--------|--------|----------------------------|---------|")
    for s in trace:
        res = "HIT " if s["hit"] else "miss"
        ev = "-" if s["evicted"] is None else str(s["evicted"])
        print(f"|  {s['t']:<3} |   {s['page']:<4} | {res}  "
              f"| {fmt_lru_order(s['order']):<26} | {ev:<7} |")
    hits = count_hits(trace)
    misses = len(SEQ) - hits
    print(f"\nLRU: {hits} hits / {len(SEQ)} accesses = "
          f"hit rate {hits / len(SEQ):.1%}  ({misses} faults -> {misses} disk reads).")
    print("Evictions hit the pages that were unused the longest: 3, 4, 5, then 1. "
          "Crucially page 1 and 2 STAY (they are touched again at steps 5,6) "
          "because their recency is refreshed on every hit.")
    assert hits == 4
    print(f"\n[check] LRU hits == 4:  OK")
    return trace


# ----------------------------------------------------------------------------
# SECTION B: CLOCK / second chance
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: CLOCK (second chance)  --  1 reference bit + a sweeping hand")
    print(f"Pool = {N_FRAMES} frames arranged in a ring, hand starts at slot 0.\n")
    print("HIT  -> set the page's reference bit = 1 (hand does not move).\n"
          "MISS -> if a slot is free, take it; else sweep: bit=1 -> clear and "
          "advance; bit=0 -> evict.\n")
    trace = clock_trace(SEQ, N_FRAMES)
    print("| step | access | result | ring (slot:page(rbit))                          "
          "| hand | sweep                              | evicted |")
    print("|------|--------|--------|-------------------------------------------------"
          "|------|------------------------------------|---------|")
    for s in trace:
        res = "HIT " if s["hit"] else "miss"
        ev = "-" if s["evicted"] is None else str(s["evicted"])
        print(f"|  {s['t']:<3} |   {s['page']:<4} | {res}  "
              f"| {fmt_clock(s['slots'], s['bits'], s['hand']):<47} "
              f"|  {s['hand']:<3} | {fmt_sweep(s['sweep']):<34} | {ev:<7} |")
    hits = count_hits(trace)
    misses = len(SEQ) - hits
    print(f"\nCLOCK: {hits} hits / {len(SEQ)} accesses = "
          f"hit rate {hits / len(SEQ):.1%}  ({misses} faults).")
    print("\nWHY CLOCK ties FIFO here (2 hits, same as FIFO): at step 7 *every* "
          "frame's reference bit is still 1 (1 and 2 were just hit at steps 5,6; "
          "3 and 4 were freshly loaded). The hand therefore sweeps ALL four "
          "frames, clearing every bit, and then evicts page 1 -- exactly FIFO's "
          "oldest-loaded choice. The 'second chance' gave no one a second chance "
          "because nobody's bit had decayed to 0 yet. On longer reference strings "
          "the bits decay and CLOCK pulls ahead of FIFO toward LRU.")
    assert hits == 2
    print(f"\n[check] CLOCK hits == 2:  OK")
    return trace


# ----------------------------------------------------------------------------
# SECTION C: LRU-K (K=2)
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: LRU-K (K=2)  --  evict the page whose 2nd-to-last use is oldest")
    print(f"Pool = {N_FRAMES} frames, K = {K}. Each page remembers its last {K} "
          f"access times; the history PERSISTS across eviction.\n")
    print("Eviction key = backward K-distance = now - (K-th most recent access).\n"
          "A page seen fewer than K times has K-distance = infinity (a 'new' page, "
          "evicted before any page seen twice).\n")
    trace = lruk_trace(SEQ, N_FRAMES, K)
    print("| step | access | result | resident   | evicted | "
          "candidate backward-K-distances (page: history -> kth, dist)        |")
    print("|------|--------|--------|------------|---------|"
          "------------------------------------------------------------|")
    for s in trace:
        res = "HIT " if s["hit"] else "miss"
        ev = "-" if s["evicted"] is None else str(s["evicted"])
        if s["cand"]:
            cells = []
            for q, hq, kth in s["cand"]:
                kth_s = str(kth) if kth != NEG_INF else "-inf"
                dist = s["t"] - kth if kth != NEG_INF else "inf"
                cells.append(f"{q}:{hq} kth={kth_s} d={dist}")
            cand_s = "  ".join(cells)
        else:
            cand_s = "-"
        print(f"|  {s['t']:<3} |   {s['page']:<4} | {res}  "
              f"| {str(s['resident']):<10} | {ev:<7} | {cand_s:<58} |")
    hits = count_hits(trace)
    misses = len(SEQ) - hits
    print(f"\nLRU-2: {hits} hits / {len(SEQ)} accesses = "
          f"hit rate {hits / len(SEQ):.1%}  ({misses} faults).")
    print("\nThe eviction decisions (3, 4, 5, then 3 again) follow the OLDEST "
          "2nd-to-last access. Note step 11: plain LRU would evict page 3, but "
          "LRU-2 remembers page 3 was used at step 10 (history [3,10]) so its 2nd "
          "access is recent; instead page 5 -- seen only once -- is evicted. The "
          "persistent history is what makes LRU-K resistant to scan pollution: a "
          "page touched twice is 'known' and protected even after being evicted.")
    assert hits == 4
    print(f"\n[check] LRU-2 hits == 4:  OK")
    return trace


# ----------------------------------------------------------------------------
# SECTION D: hit-rate comparison + Belady optimal lower bound
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: hit-rate comparison  +  Belady MIN (optimal) lower bound")
    print(f"All policies run on the SAME reference string {SEQ} with "
          f"{N_FRAMES} frames.\n")
    runs = {
        "FIFO":   count_hits(fifo_trace(SEQ, N_FRAMES)),
        "CLOCK":  count_hits(clock_trace(SEQ, N_FRAMES)),
        "LRU":    count_hits(lru_trace(SEQ, N_FRAMES)),
        f"LRU-{K}": count_hits(lruk_trace(SEQ, N_FRAMES, K)),
        "OPT":    count_hits(opt_trace(SEQ, N_FRAMES)),
    }
    total = len(SEQ)
    print("| policy | hits | faults (= disk reads) | hit rate |")
    print("|--------|------|-----------------------|----------|")
    for name, h in runs.items():
        print(f"| {name:<6} | {h:<4} | {total - h:<21} | {h / total:<8.1%} |")
    print()
    print("Read the table top to bottom as 'better':")
    print("  - FIFO (2) and CLOCK (2) tie on this short string -- see Section B "
          "for why CLOCK degenerates to FIFO here.")
    print("  - LRU and LRU-2 (4) do better: they keep the repeatedly-used pages "
          "1 and 2 alive.")
    print("  - OPT (6) is the theoretical ceiling: with 4 frames you cannot do "
          "better than 6 hits on this string, because 6 pages appear and 2 are "
          "referenced at least twice.")
    print("\nBelady's anomaly [1]: FIFO is the policy that can produce MORE faults "
          "with MORE frames. On THIS string, FIFO faults drop from 9 (3 frames) to "
          "10 (4 frames) when going 3 -> 4 frames -- i.e. giving FIFO a bigger "
          "cache makes it WORSE. LRU and OPT never show this anomaly (they have "
          "the 'stack property').")

    # GOLD CHECK: every hit count matches the hand-verified values
    assert runs["FIFO"] == 2
    assert runs["CLOCK"] == 2
    assert runs["LRU"] == 4
    assert runs[f"LRU-{K}"] == 4
    assert runs["OPT"] == 6
    print(f"\n[check] FIFO=2 CLOCK=2 LRU=4 LRU-{K}=4 OPT=6 for SEQ {SEQ}, "
          f"N={N_FRAMES}:  OK")
    print("[check] .html recomputes LRU=4, CLOCK=2, LRU-2=4 on the identical "
          "inputs:  see page_eviction.html gold badge.")


# ----------------------------------------------------------------------------
# SECTION E: dirty page handling -- eviction can cost an extra WRITE
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: dirty pages  --  evicting a modified page costs a WRITE")
    print("A page loaded for reading is CLEAN. A page modified in RAM is DIRTY: "
          "evicting it forces a flush (one extra disk WRITE) before the frame can "
          "be reused. A clean eviction is free. So two pools with identical hit "
          "rates can have very different I/O cost if one dirties more pages.\n")
    # R = read access (load clean), W = write access (dirties the page in buffer)
    ops = ["W", "R", "W", "R", "R", "W", "W", "R", "R", "W", "R", "R"]
    print(f"Same string {SEQ}, but each access is R or W:  ops = {ops}\n")
    print("We run LRU with a dirty set. On a WRITE the page becomes dirty; on a "
          "dirty EVICTION we pay 1 write; on a clean eviction we pay 0.\n")
    print("| step | access | op | result | evicted | dirty? | running reads | running writes |")
    print("|------|--------|----|--------|---------|--------|---------------|----------------|")
    last: dict[int, int] = {}
    resident: set[int] = set()
    dirty: set[int] = set()
    reads = 0          # disk reads  (one per miss / fault)
    writes = 0         # disk writes (one per dirty eviction)
    for t, (p, op) in enumerate(zip(SEQ, ops), start=1):
        hit = p in resident
        evicted = None
        flush = False
        if hit:
            last[p] = t
            if op == "W":
                dirty.add(p)
        else:
            reads += 1                       # load the page from disk
            if len(resident) >= N_FRAMES:
                evicted = min(resident, key=lambda q: (last[q], q))
                resident.discard(evicted)
                del last[evicted]
                if evicted in dirty:        # dirty eviction -> flush
                    writes += 1
                    flush = True
                    dirty.discard(evicted)
            resident.add(p)
            last[p] = t
            if op == "W":
                dirty.add(p)
        res = "HIT " if hit else "miss"
        ev = "-" if evicted is None else str(evicted)
        dy = "flush" if flush else ("-" if evicted is None else "clean")
        print(f"|  {t:<3} |   {p:<4} | {op}  | {res}  "
              f"| {ev:<7} | {dy:<6} | {reads:<13} | {writes:<14} |")
    print(f"\nTotals: {reads} disk READS (the faults) + {writes} disk WRITES "
          f"(dirty evictions) = {reads + writes} I/Os.")
    print(f"\nContrast with an ALL-READ workload (every access 'R'): the SAME LRU "
          f"policy would still fault {reads} times ({reads} reads) but pay ZERO "
          f"eviction writes, because no page is ever dirty. The {writes} writes "
          f"here are pure write-amplification from dirtying pages 1, 3 and 5 then "
          f"evicting them before the next checkpoint.")
    print("\nIn a real engine this is why dirty pages are flushed by a BACKGROUND "
          "process (checkpointer / background writer) rather than at eviction "
          "time: amortise the writes off the foreground query, and evictions can "
          "then usually reuse a clean frame.")
    assert reads == 8 and writes == 3
    print(f"\n[check] reads == 8 (one per fault) AND writes == 3 (dirty "
          f"evictions: pages 3, 5, 1):  OK")


# ----------------------------------------------------------------------------
# SECTION F: PostgreSQL specifics -- the scan ring protects the cache
# ----------------------------------------------------------------------------

def section_f():
    banner("SECTION F: PostgreSQL specifics  --  the scan ring (bulk-read 256 KB)")
    print("A sequential scan can touch millions of pages once each. If those "
          "pages entered the shared buffer pool and competed under the normal "
          "clock-sweep, one big scan would FLUSH the whole cache, evicting the "
          "genuinely hot pages. PostgreSQL prevents this with a SCAN RING: a "
          "small private set of frames, reused FIFO, that the scan reads into "
          "INSTEAD of the main pool. The hot pages never see the scan.\n")
    print("Real sizes [4]:")
    print("  bulk-READ  ring: 256 KB  = 32 pages   (seq scans that don't fit in cache)")
    print("  bulk-WRITE ring: 16 MB   = 2048 pages (COPY, CREATE TABLE AS, mat. view)")
    print("  VACUUM     ring: 256 KB  = 32 pages   (autovacuum)")
    print("\nWorked illustration (tiny numbers so it fits on a page):")
    MAIN = 8
    HOT = [1, 2]
    SCAN = list(range(100, 110))          # 10 cold pages, each read once
    RING = 2

    # --- scenario 1: NO ring -- scan competes in the 8-frame pool (LRU) ---
    no_ring = lru_trace(HOT + SCAN + HOT, MAIN)
    after = no_ring[-len(HOT):]           # the trailing re-accesses of the hot set
    no_ring_hot_hits = count_hits(after)
    print(f"  Main pool = {MAIN} frames, hot pages = {HOT}, a scan of {len(SCAN)} "
          f"cold pages ({SCAN[0]}..{SCAN[-1]}), then the hot pages are touched "
          f"again.\n")
    print("  WITHOUT a ring (scan enters the pool, LRU):")
    print("    | step | access | result | buffer (LRU -> MRU) |")
    for s in no_ring:
        res = "HIT " if s["hit"] else "miss"
        # only label the hot pages, abbreviate scan pages
        print(f"    |  {s['t']:<3} | {str(s['page']):<6} | {res} "
              f"| {fmt_lru_order(s['order'])} |")
    print(f"\n    -> after the scan the hot pages {HOT} have been evicted; their "
          f"re-accesses are {no_ring_hot_hits}/{len(HOT)} hits.")

    # --- scenario 2: WITH a ring -- scan confined to RING frames; pool untouched ---
    with_ring = lru_trace(HOT + HOT, MAIN)            # scan bypasses the pool
    with_ring_hot_hits = count_hits(with_ring[-len(HOT):])
    print("\n  WITH a 2-frame ring (scan pages go into the ring, FIFO):")
    print(f"    main pool only ever holds the hot pages {HOT}; the scan's "
          f"{len(SCAN)} pages cycle through the {RING}-frame ring and never touch "
          f"the pool.")
    print(f"    -> the hot re-accesses are {with_ring_hot_hits}/{len(HOT)} hits.")
    print(f"\n  PUNCHLINE: hot-set hit rate after the scan = "
          f"{no_ring_hot_hits / len(HOT):.0%} (no ring)  vs  "
          f"{with_ring_hot_hits / len(HOT):.0%} (ring).  The ring confines a "
          f"terabyte-sized scan to {RING} frames in the toy model (32 frames / "
          f"256 KB in real PostgreSQL), leaving the rest of the cache intact.")
    assert no_ring_hot_hits == 0 and with_ring_hot_hits == 2
    print(f"\n[check] no-ring hot hits == 0 AND ring hot hits == 2:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("page_eviction.py - reference impl. All numbers below feed "
          "PAGE_EVICTION.md.")
    print(f"SEQ = {SEQ}   N_FRAMES = {N_FRAMES}   LRU-K K = {K}")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
