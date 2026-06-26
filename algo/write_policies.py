"""
write_policies.py - cache write policies, from scratch.

This is the single source of truth that WRITE_POLICIES.md is built from.
Every number and trace in WRITE_POLICIES.md is printed by this file.

Run:
    uv run python write_policies.py    (or: python write_policies.py)

==========================================================================
THE INTUITION (read this first) - the desk, the filing cabinet, and the safe
==========================================================================
A cache sits in front of a slow backing store (DRAM in front of SSD, SSD in
front of cloud, CPU L1 in front of RAM). Reads are simple: try the cache, and
if it misses, fetch from the backing store. WRITES are the hard part, because
now there are TWO copies of the data and a decision: which one do I update?

  * WRITE-THROUGH : update BOTH (cache + backing) on every write.
                    -> the backing store is always fresh. Safe. But every
                       write pays the slow backing-store latency.
  * WRITE-BACK    : update ONLY the cache; mark the block DIRTY; flush to the
                    backing store later (on eviction, or on an explicit flush).
                    -> writes are FAST (cache speed) and COALESCED (ten writes
                       to the same block = one eventual writeback). But the
                       backing store is STALE until the flush, so a crash
                       between the write and the flush LOSES DATA.
  * WRITE-AROUND  : DON'T touch the cache on a write - go straight to the
                    backing store, and INVALIDATE the cache line if present.
                    -> write-only data (logs, bulk loads) never pollutes the
                    cache. But a read of the just-written block is a MISS
                    (and the cache may serve a STALE line if you forget to
                    invalidate - that is the classic write-around bug).

ORTHOGONAL AXIS - what to do on a WRITE MISS:
  * WRITE-ALLOCATE    : load the block into the cache, then write it there.
                        (assumes you'll write/read it again soon)
  * NO-WRITE-ALLOCATE : write straight to the backing store; don't load.
                        (assumes writes are one-shot; don't pollute the cache)

The two axes compose into the four combos real hardware uses:
    write-through + write-allocate    (simple, consistent, slow writes)
    write-through + no-write-allocate (the strict "write-around" write path)
    write-back   + write-allocate     (CPU L1/L2 - the common case; fast,
                                       coalesced, crash-risky)
    write-back   + no-write-allocate  (some database buffer pools)

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  dirty bit    : a per-cache-line flag = "the cache copy is newer than the
                 backing copy; a flush is owed." Set by write-back writes;
                 cleared by a writeback (flush to backing).
  writeback    : the act of copying a dirty line back to the backing store.
                 Triggered by eviction of a dirty line or an explicit flush.
                 Costs one backing-store write.
  invalidate   : dropping a cache line WITHOUT writing it back (because the
                 backing store already has the fresh data). Used by write-around.
  coalescing   : several writes to the same dirty block become ONE writeback.
                 The main performance win of write-back.
  consistency  : whether the backing store always reflects the latest writes.
                 write-through / write-around: YES. write-back: NO (stale
                 until flush).

==========================================================================
THE LATENCY MODEL (deterministic, for the trace)
==========================================================================
    T_CACHE = 1     # hit a cache line (read or write)
    T_BACK  = 10    # touch the backing store (read OR write)
  So:
    read  hit  = 1 ; read  miss = 10 (fetch) + 1 (insert/serve) = 11
    write-through hit      = 1 (cache) + 10 (backing)        = 11
    write-through miss+WA  = 10 (load) + 1 (cache) + 10 (backing) = 21
    write-through miss+NWA = 10 (backing only)               = 10
    write-back    hit      = 1 (cache; set dirty)            = 1
    write-back    miss+WA  = 10 (load) + 1 (cache; dirty)    = 11
    write-back    miss+NWA = 10 (backing only)               = 10
    write-around  (any)    = 10 (backing) [+ invalidate]     = 10
  Plus, evicting a DIRTY line in write-back costs an extra T_BACK writeback.

References:
  * Hennessy & Patterson, "Computer Architecture: A Quantitative Approach",
    Appendix B (memory hierarchy) - the canonical write-policy treatment.
  * SQLite, PostgreSQL buffer managers - write-back + no-write-allocate
    variants tuned for durability (WAL/flush).
"""

from __future__ import annotations

from collections import OrderedDict

BANNER = "=" * 74

T_CACHE = 1
T_BACK = 10


# ============================================================================
# 1. THE CACHE + POLICY SIMULATOR
# ============================================================================

class WriteCache:
    """Fully-associative, LRU cache with configurable write policy.

    write_mode : "through" | "back" | "around"
    allocate   : True (write-allocate) | False (no-write-allocate)
    Reads always allocate on a miss (standard).
    """

    def __init__(self, capacity: int, write_mode: str, allocate: bool):
        assert write_mode in ("through", "back", "around")
        self.cap = capacity
        self.mode = write_mode
        self.allocate = allocate
        self.lines: OrderedDict = OrderedDict()   # addr -> dirty(bool)
        # instrumentation
        self.backing_reads = 0
        self.backing_writes = 0
        self.latency = 0
        self.writebacks = 0
        self.invalidations = 0
        self.trace: list[tuple] = []

    # -- internal: evict LRU line; write it back if dirty -------------------
    def _evict_if_needed(self):
        if len(self.lines) < self.cap:
            return None
        victim, dirty = self.lines.popitem(last=False)   # LRU
        if dirty:
            self.backing_writes += 1
            self.writebacks += 1
            self.latency += T_BACK
            return ("writeback", victim)
        return ("evict-clean", victim)

    # -- internal: load a block from backing store into the cache -----------
    def _load(self, addr):
        self.backing_reads += 1
        self.latency += T_BACK
        self._evict_if_needed()
        self.lines[addr] = False     # clean on load
        self.latency += T_CACHE

    # -- READ ---------------------------------------------------------------
    def read(self, addr):
        if addr in self.lines:
            self.lines.move_to_end(addr)
            self.latency += T_CACHE
            self.trace.append(("R", addr, "hit", "-", self.snapshot()))
            return
        self._load(addr)
        self.trace.append(("R", addr, "miss(load)", "-", self.snapshot()))

    # -- WRITE --------------------------------------------------------------
    def write(self, addr):
        if self.mode == "around":
            # bypass cache entirely; invalidate if present
            self.backing_writes += 1
            self.latency += T_BACK
            note = "-"
            if addr in self.lines:
                del self.lines[addr]
                self.invalidations += 1
                note = "invalidate"
            self.trace.append(("W", addr, "around", note, self.snapshot()))
            return

        hit = addr in self.lines
        if self.mode == "through":
            self.backing_writes += 1
            if hit:
                self.lines.move_to_end(addr)
                self.latency += T_CACHE + T_BACK
                self.trace.append(("W", addr, "hit", "wt", self.snapshot()))
            else:
                if self.allocate:
                    self._load(addr)             # load (may evict dirty)
                    self.latency += T_BACK       # then write through
                    self.trace.append(
                        ("W", addr, "miss", "wt+alloc", self.snapshot()))
                else:
                    self.latency += T_BACK       # backing only
                    self.trace.append(
                        ("W", addr, "miss", "wt-noalloc", self.snapshot()))
        elif self.mode == "back":
            if hit:
                self.lines[addr] = True          # set dirty
                self.lines.move_to_end(addr)
                self.latency += T_CACHE
                self.trace.append(("W", addr, "hit", "wb(dirty)",
                                   self.snapshot()))
            else:
                if self.allocate:
                    self._load(addr)             # load (may evict dirty)
                    self.lines[addr] = True      # then mark dirty
                    self.trace.append(
                        ("W", addr, "miss", "wb+alloc(dirty)",
                         self.snapshot()))
                else:
                    self.backing_writes += 1
                    self.latency += T_BACK
                    self.trace.append(
                        ("W", addr, "miss", "wb-noalloc", self.snapshot()))

    def snapshot(self):
        return "{" + ",".join(
            f"{a}{'*' if d else ''}" for a, d in self.lines.items()) + "}"

    def dirty_lines(self):
        return [a for a, d in self.lines.items() if d]

    def flush_all(self):
        """Write back every dirty line (e.g. at shutdown)."""
        flushed = 0
        for a in list(self.lines):
            if self.lines[a]:
                self.backing_writes += 1
                self.writebacks += 1
                self.latency += T_BACK
                self.lines[a] = False
                flushed += 1
        return flushed


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_ops(ops):
    return " ".join(f"{op}{a}" for op, a in ops)


# ============================================================================
# 3. THE WORKLOAD + STEP-TRACE ENGINE
# ============================================================================

# A write-heavy mixed workload. Touches addrs 0..7 with a 4-line cache so the
# write burst W4..W7 forces evictions (and, under write-back, writebacks).
# Note ops 4-6: R1 brings 1 into the cache, W1 then writes that SAME line, and
# R1 re-reads it. This is where the policies visibly diverge:
#   - write-back    : W1 hits the cached line (dirty); R1 hits.
#   - write-through : W1 hits (cache+backing); R1 hits.
#   - write-around  : W1 INVALIDATES the cached line; R1 is a MISS (reloads the
#                     fresh value from backing - the only reason it isn't STALE).
OPS = [("W", 0), ("W", 0), ("W", 0),   # coalescing demo (write-back coalesces)
       ("R", 1),                        # bring 1 into the cache
       ("W", 1),                        # write the SAME cached line
       ("R", 1),                        # re-read it (write-around -> MISS)
       ("W", 2), ("R", 2),
       ("W", 3), ("W", 3), ("R", 0),
       ("W", 4), ("W", 5), ("W", 6), ("W", 7),
       ("R", 0)]
CACHE_CAP = 4

POLICIES = [
    ("write-through + write-allocate",     "through", True),
    ("write-through + no-write-allocate",  "through", False),
    ("write-back    + write-allocate",     "back",    True),
    ("write-back    + no-write-allocate",  "back",    False),
    ("write-around",                       "around",  False),
]


def run_policy(write_mode, allocate, *, name, verbose=True):
    c = WriteCache(CACHE_CAP, write_mode, allocate)
    for op, addr in OPS:
        if op == "R":
            c.read(addr)
        else:
            c.write(addr)
    if verbose:
        print(f"\n  {name}, capacity = {CACHE_CAP}")
        print(f"  workload: {fmt_ops(OPS)}\n")
        print(f"  {'#':>2}  {'op':<2}  {'result':<10}  {'note':<14}  "
              f"{'cache ( *=dirty )':<22}")
        print("  " + "-" * 62)
        for i, (op, addr) in enumerate(OPS, 1):
            t = c.trace[i - 1]
            print(f"  {i:>2}  {op}{addr:<2} {t[2]:<10}  {t[3]:<14}  {t[4]:<22}")
    return c


# ----------------------------------------------------------------------------
# SECTION A: the policy space (2 axes -> the combos hardware actually ships)
# ----------------------------------------------------------------------------

def section_space():
    banner("SECTION A: the two-axis write-policy space")
    print("Every cache write answers TWO independent questions:\n")
    print("  Q1 (write-hit path) : through | back | around")
    print("  Q2 (write-miss path): write-allocate | no-write-allocate\n")
    print("  +-----------+------------------+---------------------+")
    print("  | hit \\ miss| write-allocate   | no-write-allocate   |")
    print("  +-----------+------------------+---------------------+")
    print("  | THROUGH   | simple, safe,    | strict write-around |")
    print("  |           | slow writes      | write path          |")
    print("  +-----------+------------------+---------------------+")
    print("  | BACK      | CPU L1/L2: FAST, | some DB buffer      |")
    print("  |           | coalesced, risky | pools               |")
    print("  +-----------+------------------+---------------------+")
    print("  | AROUND    | (n/a - around bypasses on every write)       |")
    print("  +-----------+-----------------------------------------+")
    print("\n  Reads are NOT a choice: always allocate on a read miss.")


# ----------------------------------------------------------------------------
# SECTION B: the headline contrast - write-back COALESCES, write-through doesn't
# ----------------------------------------------------------------------------

def section_coalescing():
    banner("SECTION B: coalescing - write-back turns 3 writes into 1 dirty block")
    print("Look at the first three ops: W0, W0, W0 (write address 0 three times).\n")
    c_wb = WriteCache(CACHE_CAP, "back", True)
    for op, a in OPS:
        (c_wb.write if op == "W" else c_wb.read)(a)
    c_wt = WriteCache(CACHE_CAP, "through", True)
    for op, a in OPS:
        (c_wt.write if op == "W" else c_wt.read)(a)
    print("  write-BACK    : the 3x W0 hit the SAME cache line, set dirty once.")
    print(f"    backing writes caused by W0,W0,W0 = "
          f"{0}  (deferred until eviction/flush)")
    print(f"    -> the three writes cost 3 * T_CACHE = {3 * T_CACHE}, "
          f"NOT 3 * (T_CACHE + T_BACK) = {3 * (T_CACHE + T_BACK)}.\n")
    print("  write-THROUGH : each W0 writes the backing store immediately.")
    print("    backing writes caused by W0,W0,W0 = 3")
    print(f"    -> cost 3 * (T_CACHE + T_BACK) = {3 * (T_CACHE + T_BACK)}, "
          f"{3 * (T_CACHE + T_BACK) // (3 * T_CACHE)}x the write-back cost.\n")
    print('  THIS is why CPU caches and DB buffer pools use write-back: writes\n'
          '  to a hot line are coalesced into one eventual writeback. The price\n'
          '  is the dirty bit - a crash before the writeback loses those writes\n'
          '  (mitigated by WAL / journaling / fsync - see Section D).')


# ----------------------------------------------------------------------------
# SECTION C: all five policies on the SAME workload (the comparison table)
# ----------------------------------------------------------------------------

def section_comparison():
    banner("SECTION C: all five policies on the same workload")
    print(f"capacity = {CACHE_CAP}, workload = {fmt_ops(OPS)}\n")
    print(f"  {'policy':<38}{'latency':>9}{'bk_reads':>10}"
          f"{'bk_writes':>11}{'dirty':>7}{'writebacks':>12}")
    print("  " + "-" * 87)
    results = {}
    for name, mode, alloc in POLICIES:
        c = run_policy(mode, alloc, name=name, verbose=False)
        dirty = len(c.dirty_lines())
        results[name] = (c.latency, c.backing_reads, c.backing_writes,
                         dirty, c.writebacks, c.invalidations)
        print(f"  {name:<38}{c.latency:>9}{c.backing_reads:>10}"
              f"{c.backing_writes:>11}{dirty:>7}{c.writebacks:>12}")
    print()
    wb = results["write-back    + write-allocate"]
    wt = results["write-through + write-allocate"]
    wa = results["write-around"]
    print("  Read it as the three-way trade-off:")
    print(f"    write-BACK    : latency {wb[0]}, "
          f"{wb[2]} backing writes, {wb[3]} dirty line(s) at risk.")
    print(f"    write-THROUGH : latency {wt[0]} (highest), "
          f"{wt[2]} backing writes, 0 dirty (always consistent).")
    print(f"    write-AROUND  : latency {wa[0]}, {wa[2]} backing writes, "
          f"0 dirty, {wa[5]} invalidation(s).")
    print("                    The invalidation at W1 is the ONLY reason the")
    print("                    later R1 does not serve a STALE cached value.")
    return results


# ----------------------------------------------------------------------------
# SECTION D: the consistency / crash trade-off
# ----------------------------------------------------------------------------

def section_consistency():
    banner("SECTION D: consistency vs latency - the durability question")
    print("After the workload, is the backing store guaranteed to hold every\n"
          "write? Only if there are NO dirty lines, OR a flush has run.\n")
    for name, mode, alloc in POLICIES:
        c = run_policy(mode, alloc, name=name, verbose=False)
        dirty = c.dirty_lines()
        pre = len(dirty)
        flushed = c.flush_all()
        consistent_pre = (pre == 0)
        print(f"  {name:<38} dirty_before_flush={pre:<2} "
              f"flushed={flushed:<2} "
              f"consistent_before_flush={'YES' if consistent_pre else 'NO (crash loses data)'}")
    print()
    print("  write-through / write-around : the backing store is ALWAYS the\n"
          "    source of truth. A crash at any instant loses NOTHING. Cost:\n"
          "    every write pays T_BACK, and there is no coalescing.\n")
    print("  write-back : the backing store is STALE for every dirty line. A\n"
          "    crash before flush/writeback loses those writes. Mitigations:\n"
          "    - WAL (write-ahead log) / journaling: durably log the intent\n"
          "      first, so a crash can REPLAY unfinished writebacks.\n"
          "    - fsync / explicit flush at commit boundaries (forces writeback).\n"
          "    - battery-backed NVRAM: the 'dirty' window survives a power cut.\n"
          "    This is the entire reason databases and filesystems have journals.")


# ----------------------------------------------------------------------------
# SECTION E: GOLD values (pinned for write_policies.html to recompute in JS)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION E: GOLD values - pinned for write_policies.html")
    print(f"workload = {fmt_ops(OPS)}, capacity = {CACHE_CAP}, "
          f"T_CACHE={T_CACHE}, T_BACK={T_BACK}\n")
    gold = {}
    for name, mode, alloc in POLICIES:
        c = run_policy(mode, alloc, name=name, verbose=False)
        gold[name] = {
            "latency": c.latency,
            "backing_reads": c.backing_reads,
            "backing_writes": c.backing_writes,
            "writebacks": c.writebacks,
            "invalidations": c.invalidations,
            "dirty_before_flush": len(c.dirty_lines()),
        }
        print(f"  {name:<38} latency={c.latency:<4} "
              f"bk_reads={c.backing_reads:<3} bk_writes={c.backing_writes:<3} "
              f"writebacks={c.writebacks:<3} inval={c.invalidations:<3} "
              f"dirty={len(c.dirty_lines())}")
    # headline gold checks (the .html recomputes these in JS)
    wb = gold["write-back    + write-allocate"]
    wt = gold["write-through + write-allocate"]
    wa = gold["write-around"]
    print("\nGOLD (pinned, the .html re-derives these from the same model):")
    print(f"  write-back    + allocate : latency = {wb['latency']}, "
          f"backing_writes = {wb['backing_writes']}, "
          f"dirty_before_flush = {wb['dirty_before_flush']}")
    print(f"  write-through + allocate : latency = {wt['latency']}, "
          f"backing_writes = {wt['backing_writes']}")
    print(f"  write-around             : latency = {wa['latency']}, "
          f"invalidations = {wa['invalidations']}")
    # self-consistency asserts
    assert wb["latency"] < wt["latency"], "write-back must beat write-through"
    assert wb["backing_writes"] < wt["backing_writes"], \
        "write-back must coalesce (fewer backing writes)"
    assert wb["dirty_before_flush"] >= 1, "write-back should leave dirty lines"
    assert wt["dirty_before_flush"] == 0, "write-through never dirty"
    assert wa["dirty_before_flush"] == 0, "write-around never dirty"
    assert wa["invalidations"] >= 1, "write-around should invalidate"
    # the coalescing headline: W0 written 3x but write-back owes only 1 block
    assert wb["backing_writes"] == wb["writebacks"], \
        "all write-back backing writes come from writebacks"
    print("\n[check] all GOLD asserts passed:  OK")
    return gold


# ============================================================================
# main
# ============================================================================

def main():
    print("write_policies.py - reference impl. All numbers feed WRITE_POLICIES.md.")
    print("stdlib only; deterministic; no torch/numpy.")
    print("Latency model: T_CACHE=1, T_BACK=10.")
    section_space()
    section_coalescing()
    print("\n  --- full step traces (write-back vs write-through) ---")
    run_policy("back", True, name="write-back + write-allocate", verbose=True)
    run_policy("through", True, name="write-through + write-allocate",
               verbose=True)
    section_comparison()
    section_consistency()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
