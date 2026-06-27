"""Operating Systems — ground-truth simulations of CPU scheduling, page
replacement, and virtual-memory translation.

Three pillars of an OS course, each simulated deterministically:

  1. CPU Scheduling   — FCFS, SJF (non-preemptive), SRTF (preemptive SJF),
                        and Round Robin (quantum 1, 2, 4). Waiting time,
                        turnaround time, and Gantt charts for each.
  2. Page Replacement — FIFO, LRU, and Clock (second-chance) on the classic
                        Silberschatz reference string, plus Belady's anomaly.
  3. Virtual Memory   — page-table translation (VPN/PFN/offset) and a
                        TLB hit/miss simulation across an access stream.

Every number printed below is produced by running this file; nothing is
hand-computed.  Capture with:

    python3 operating_systems.py > operating_systems_output.txt 2>/dev/null
"""

from __future__ import annotations

from collections import deque


# ---------------------------------------------------------------------------
# Process dataset — (pid, arrival_time, burst_time)
# P1 long, P2 medium, P3 tiny, P4 medium: chosen so every scheduler produces
# a visibly different Gantt chart and a different average waiting time.
# ---------------------------------------------------------------------------
PROCESSES = [
    ("P1", 0, 7),
    ("P2", 2, 4),
    ("P3", 4, 1),
    ("P4", 5, 4),
]

# Classic Silberschatz reference string (Operating System Concepts).
# With 3 frames: FIFO=15, LRU=12, Clock=14 faults.
REF_STRING = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]

# Reference string that exhibits Belady's anomaly under FIFO.
# 3 frames -> 9 faults, 4 frames -> 10 faults (more frames, MORE faults).
BELADY_STRING = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]


# ===========================================================================
# Scheduling primitives
# ===========================================================================

def fcfs(procs):
    """First-Come First-Served (non-preemptive). Run in arrival order."""
    order = sorted(range(len(procs)), key=lambda i: (procs[i][1], i))
    time = 0
    gantt = []
    completion = [0] * len(procs)
    for i in order:
        start = max(time, procs[i][1])
        time = start + procs[i][2]
        gantt.append((procs[i][0], start, time))
        completion[i] = time
    return gantt, completion


def sjf_nonpreemptive(procs):
    """Shortest Job First, non-preemptive. Pick min burst among arrived."""
    n = len(procs)
    done = [False] * n
    completion = [0] * n
    time = 0
    gantt = []
    finished = 0
    while finished < n:
        avail = [i for i in range(n) if not done[i] and procs[i][1] <= time]
        if not avail:
            time = min(procs[i][1] for i in range(n) if not done[i])
            continue
        # min burst, tie-break by arrival then index
        i = min(avail, key=lambda i: (procs[i][2], procs[i][1], i))
        start = time
        time += procs[i][2]
        gantt.append((procs[i][0], start, time))
        completion[i] = time
        done[i] = True
        finished += 1
    return gantt, completion


def srtf(procs):
    """Shortest Remaining Time First (preemptive SJF).

    At each step run the arrived process with the least remaining time,
    advancing the clock to the next arrival or completion.
    """
    n = len(procs)
    remaining = [procs[i][2] for i in range(n)]
    done = [False] * n
    completion = [0] * n
    time = 0
    gantt = []
    finished = 0
    while finished < n:
        avail = [i for i in range(n) if not done[i] and procs[i][1] <= time]
        if not avail:
            time = min(procs[i][1] for i in range(n) if not done[i])
            continue
        i = min(avail, key=lambda i: (remaining[i], procs[i][1], i))
        # run until the next future arrival or completion
        future = [procs[j][1] for j in range(n)
                  if not done[j] and procs[j][1] > time]
        run = remaining[i]
        if future:
            run = min(run, min(future) - time)
        start = time
        time += run
        remaining[i] -= run
        # merge consecutive slices of the same pid for a clean Gantt chart
        if gantt and gantt[-1][0] == procs[i][0]:
            gantt[-1] = (procs[i][0], gantt[-1][1], time)
        else:
            gantt.append((procs[i][0], start, time))
        if remaining[i] == 0:
            completion[i] = time
            done[i] = True
            finished += 1
    return gantt, completion


def round_robin(procs, quantum):
    """Round Robin. Arrivals during a slice are enqueued (in arrival order)
    BEFORE the preempted process re-enters the ready queue."""
    n = len(procs)
    remaining = [procs[i][2] for i in range(n)]
    order = sorted(range(n), key=lambda i: (procs[i][1], i))
    ready = deque()
    ptr = 0
    time = 0
    gantt = []
    completion = [0] * n

    def add_arrivals(t):
        nonlocal ptr
        while ptr < n and procs[order[ptr]][1] <= t:
            ready.append(order[ptr])
            ptr += 1

    add_arrivals(0)
    while True:
        if not ready:
            if ptr < n:
                time = procs[order[ptr]][1]
                add_arrivals(time)
                continue
            break
        i = ready.popleft()
        start = time
        run = min(quantum, remaining[i])
        time += run
        remaining[i] -= run
        gantt.append((procs[i][0], start, time))
        add_arrivals(time)
        if remaining[i] > 0:
            ready.append(i)
        else:
            completion[i] = time
    return gantt, completion


def times_from_completion(procs, completion):
    """Return (waiting, turnaround) lists from a completion vector."""
    n = len(procs)
    turnaround = [completion[i] - procs[i][1] for i in range(n)]
    waiting = [turnaround[i] - procs[i][2] for i in range(n)]
    return waiting, turnaround


# ===========================================================================
# Scheduling display helpers
# ===========================================================================

def print_gantt(gantt):
    """Render a Gantt chart as aligned text segments."""
    print("  Gantt: " + " | ".join(
        f"{pid}[{s}-{e}]" for pid, s, e in gantt))
    print("  " + " ".join(
        f"{pid:^{len(f'{s}-{e}')}}" for pid, s, e in gantt))


def print_schedule_table(procs, completion):
    waiting, turnaround = times_from_completion(procs, completion)
    print(f"  {'pid':>4}  {'arrive':>6}  {'burst':>5}  {'finish':>6}"
          f"  {'wait':>5}  {'turn':>5}")
    print(f"  {'----':>4}  {'------':>6}  {'-----':>5}  {'------':>6}"
          f"  {'-----':>5}  {'-----':>5}")
    for i in range(len(procs)):
        print(f"  {procs[i][0]:>4}  {procs[i][1]:>6}  {procs[i][2]:>5}"
              f"  {completion[i]:>6}  {waiting[i]:>5}  {turnaround[i]:>5}")
    avg_wait = sum(waiting) / len(procs)
    avg_turn = sum(turnaround) / len(procs)
    print(f"  average waiting = {avg_wait:.2f}    average turnaround = {avg_turn:.2f}")
    return sum(waiting), sum(turnaround)


# ===========================================================================
# Scheduling sections
# ===========================================================================

def section_fcfs():
    print("=" * 72)
    print("=== FCFS — First-Come First-Served (non-preemptive)")
    print("=" * 72)
    print(f"  processes = {[(p[0], p[1], p[2]) for p in PROCESSES]}")
    print()
    gantt, comp = fcfs(PROCESSES)
    print_gantt(gantt)
    print()
    total_w, total_t = print_schedule_table(PROCESSES, comp)
    print()
    ok = total_w == 19
    print(f"  total wait = {total_w}   [check] {'OK' if ok else 'FAIL'}"
          f"   (long P1 blocks everyone)")
    assert ok


def section_sjf():
    print()
    print("=" * 72)
    print("=== SJF — Shortest Job First (non-preemptive)")
    print("=" * 72)
    print(f"  processes = {[(p[0], p[1], p[2]) for p in PROCESSES]}")
    print()
    gantt, comp = sjf_nonpreemptive(PROCESSES)
    print_gantt(gantt)
    print()
    total_w, total_t = print_schedule_table(PROCESSES, comp)
    print()
    ok = total_w == 16
    print(f"  total wait = {total_w}   [check] {'OK' if ok else 'FAIL'}"
          f"   (short jobs cut the line)")
    assert ok


def section_srtf():
    print()
    print("=" * 72)
    print("=== SRTF — Shortest Remaining Time First (preemptive SJF)")
    print("=" * 72)
    print(f"  processes = {[(p[0], p[1], p[2]) for p in PROCESSES]}")
    print()
    gantt, comp = srtf(PROCESSES)
    print_gantt(gantt)
    print()
    total_w, total_t = print_schedule_table(PROCESSES, comp)
    print()
    ok = total_w == 12
    print(f"  total wait = {total_w}   [check] {'OK' if ok else 'FAIL'}"
          f"   (preemption yields the minimum average wait)")
    assert ok


def section_round_robin():
    print()
    print("=" * 72)
    print("=== Round Robin — quantum comparison (q = 1, 2, 4)")
    print("=" * 72)
    print(f"  processes = {[(p[0], p[1], p[2]) for p in PROCESSES]}")
    print()

    rr_results = {}
    for q in (1, 2, 4):
        gantt, comp = round_robin(PROCESSES, q)
        waiting, turnaround = times_from_completion(PROCESSES, comp)
        n_ctx = len(gantt)
        rr_results[q] = (sum(waiting), sum(turnaround), n_ctx)
        print(f"  --- quantum = {q} ---")
        print_gantt(gantt)
        print()
        print(f"  {'pid':>4}  {'finish':>6}  {'wait':>5}  {'turn':>5}")
        print(f"  {'----':>4}  {'------':>6}  {'-----':>5}  {'-----':>5}")
        for i in range(len(PROCESSES)):
            print(f"  {PROCESSES[i][0]:>4}  {comp[i]:>6}"
                  f"  {waiting[i]:>5}  {turnaround[i]:>5}")
        avg_w = sum(waiting) / len(PROCESSES)
        print(f"  average wait = {avg_w:.2f}   context switches = {n_ctx}")
        print()

    print("  quantum comparison (total wait / total turn / context switches):")
    print(f"  {'q':>4}  {'total_wait':>10}  {'total_turn':>10}  {'ctx_sw':>6}")
    print(f"  {'----':>4}  {'----------':>10}  {'----------':>10}  {'------':>6}")
    for q in (1, 2, 4):
        w, t, c = rr_results[q]
        print(f"  {q:>4}  {w:>10}  {t:>10}  {c:>6}")
    # q=2 is the canonical textbook quantum; small q -> many switches -> more wait
    ok = rr_results[2][0] == 20 and rr_results[1][2] > rr_results[4][2]
    print()
    print(f"  q=2 total wait = {rr_results[2][0]}   "
          f"switches q1({rr_results[1][2]}) > q4({rr_results[4][2]})"
          f"   [check] {'OK' if ok else 'FAIL'}")
    assert ok


def section_scheduling_comparison():
    print()
    print("=" * 72)
    print("=== Scheduling comparison — average waiting time & turnaround")
    print("=" * 72)
    print(f"  processes = {[(p[0], p[1], p[2]) for p in PROCESSES]}")
    print()

    runs = [
        ("FCFS", fcfs(PROCESSES)),
        ("SJF (non-preem)", sjf_nonpreemptive(PROCESSES)),
        ("SRTF (preem)", srtf(PROCESSES)),
        ("RR q=1", round_robin(PROCESSES, 1)),
        ("RR q=2", round_robin(PROCESSES, 2)),
        ("RR q=4", round_robin(PROCESSES, 4)),
    ]
    print(f"  {'algorithm':>16}  {'avg_wait':>8}  {'avg_turn':>8}")
    print(f"  {'----------------':>16}  {'--------':>8}  {'--------':>8}")
    summary = {}
    for name, (_, comp) in runs:
        w, t = times_from_completion(PROCESSES, comp)
        aw = sum(w) / len(PROCESSES)
        at = sum(t) / len(PROCESSES)
        summary[name] = (aw, at)
        print(f"  {name:>16}  {aw:>8.2f}  {at:>8.2f}")

    best = min(summary, key=lambda k: summary[k][0])
    worst = max(summary, key=lambda k: summary[k][0])
    print()
    print(f"  best  (min avg wait): {best:>16}  {summary[best][0]:.2f}")
    print(f"  worst (max avg wait): {worst:>16}  {summary[worst][0]:.2f}")
    ok = best == "SRTF (preem)" and summary["SRTF (preem)"][0] < summary["FCFS"][0]
    print(f"  [check] {'OK' if ok else 'FAIL'}"
          f"   (SRTF optimal; RR approaches FCFS as quantum grows)")
    assert ok


# ===========================================================================
# Page replacement
# ===========================================================================

def fifo(refs, frames):
    memory = []  # insertion order (front = oldest = next evicted)
    faults = 0
    trace = []
    for ref in refs:
        if ref in memory:
            trace.append((ref, list(memory), False))
        else:
            faults += 1
            if len(memory) >= frames:
                memory.pop(0)
            memory.append(ref)
            trace.append((ref, list(memory), True))
    return faults, trace


def lru(refs, frames):
    memory = []  # front = least recently used
    faults = 0
    trace = []
    for ref in refs:
        if ref in memory:
            memory.remove(ref)
            memory.append(ref)
            trace.append((ref, list(memory), False))
        else:
            faults += 1
            if len(memory) >= frames:
                memory.pop(0)
            memory.append(ref)
            trace.append((ref, list(memory), True))
    return faults, trace


def clock(refs, frames):
    """Clock / second-chance. Circular buffer with a use bit per frame."""
    slots = [None] * frames
    use = [False] * frames
    ptr = 0
    faults = 0
    trace = []
    for ref in refs:
        if ref in slots:
            use[slots.index(ref)] = True
            trace.append((ref, list(slots), False))
        else:
            faults += 1
            while use[ptr]:
                use[ptr] = False
                ptr = (ptr + 1) % frames
            slots[ptr] = ref
            use[ptr] = True
            ptr = (ptr + 1) % frames
            trace.append((ref, list(slots), True))
    return faults, trace


def print_page_trace(refs, trace, label):
    """Print a compact reference-string trace with frame columns."""
    print(f"  {label}:  ref  " + " ".join(f"{r:>3}" for r in refs))
    width = max(len(snap) for _, snap, _ in trace) if trace else 1
    rows = []
    for f in range(width):
        cells = []
        for _, snap, _ in trace:
            val = snap[f] if f < len(snap) and snap[f] is not None else "."
            cells.append(f"{val:>3}")
        rows.append("  " + " " * (len(label) + 3) + " ".join(cells))
    print("\n".join(rows))
    print("  " + " " * (len(label) + 3) + " ".join(
        ("  F" if fault else "   ") for _, _, fault in trace))
    print(f"  faults = {sum(1 for _, _, f in trace if f)}")


def section_page_replacement():
    frames = 3
    print()
    print("=" * 72)
    print(f"=== Page replacement — FIFO / LRU / Clock  ({frames} frames)")
    print("=" * 72)
    print(f"  reference string = {REF_STRING}")
    print(f"  frames = {frames}")
    print()

    ff, t_fifo = fifo(REF_STRING, frames)
    lf, t_lru = lru(REF_STRING, frames)
    cf, t_clock = clock(REF_STRING, frames)

    print_page_trace(REF_STRING, t_fifo, "FIFO ")
    print()
    print_page_trace(REF_STRING, t_lru, "LRU  ")
    print()
    print_page_trace(REF_STRING, t_clock, "Clock")
    print()

    print(f"  {'algorithm':>10}  {'faults':>6}")
    print(f"  {'----------':>10}  {'------':>6}")
    print(f"  {'FIFO':>10}  {ff:>6}")
    print(f"  {'LRU':>10}  {lf:>6}")
    print(f"  {'Clock':>10}  {cf:>6}")
    print()
    ok = ff == 15 and lf == 12 and cf == 14
    print(f"  FIFO={ff}, LRU={lf}, Clock={cf}   [check] {'OK' if ok else 'FAIL'}"
          f"   (LRU <= Clock <= FIFO)")
    assert ok


def section_belady():
    print()
    print("=" * 72)
    print("=== Belady's anomaly — FIFO: MORE frames can mean MORE faults")
    print("=" * 72)
    print(f"  reference string = {BELADY_STRING}")
    print()

    print(f"  {'algorithm':>8}  {'3 frames':>8}  {'4 frames':>8}  {'delta':>6}")
    print(f"  {'--------':>8}  {'--------':>8}  {'--------':>8}  {'-----':>6}")
    results = {}
    for name, fn in (("FIFO", fifo), ("LRU", lru), ("Clock", clock)):
        f3, _ = fn(BELADY_STRING, 3)
        f4, _ = fn(BELADY_STRING, 4)
        delta = f4 - f3
        results[name] = (f3, f4, delta)
        print(f"  {name:>8}  {f3:>8}  {f4:>8}  {delta:>+6}")

    fifo3, fifo4, fifo_delta = results["FIFO"]
    lru3, lru4, lru_delta = results["LRU"]
    ok = (fifo4 > fifo3) and (lru4 <= lru3)
    print()
    print(f"  FIFO: 3 frames -> {fifo3} faults, 4 frames -> {fifo4} faults"
          f"  (+{fifo_delta}, ANOMALY)")
    print(f"  LRU:  3 frames -> {lru3} faults, 4 frames -> {lru4} faults"
          f"  ({lru_delta:+d}, monotonic — LRU is a stack algorithm)")
    print(f"  [check] {'OK' if ok else 'FAIL'}"
          f"   (only FIFO-style replacement shows Belady's anomaly)")
    assert ok


# ===========================================================================
# Virtual memory — page-table translation + TLB
# ===========================================================================

PAGE_BITS = 12                       # 4 KB pages
PAGE_SIZE = 1 << PAGE_BITS           # 4096 bytes
VPN_BITS = 4                         # 16-bit virtual addresses -> VPN 0..15
PFN_BITS = 4                         # 16 frames of physical memory

# Page table: virtual page number -> physical frame number.
# Pages 4, 5, 8, 9, 12-15 are invalid (not mapped) to demonstrate page faults.
PAGE_TABLE = {
    0: 5, 1: 9, 2: 3, 3: 7,
    6: 1, 7: 12, 10: 0, 11: 8,
}

# Virtual addresses used for the translation demo.
DEMO_ADDRESSES = [0x2C8A, 0x1A2F, 0x0710, 0x7005, 0xB300, 0x9000]


def translate(vaddr):
    vpn = vaddr >> PAGE_BITS
    offset = vaddr & (PAGE_SIZE - 1)
    if vpn not in PAGE_TABLE:
        return None, vpn, offset
    pfn = PAGE_TABLE[vpn]
    paddr = (pfn << PAGE_BITS) | offset
    return paddr, vpn, offset


def tlb_simulate(accesses, tlb_size):
    """LRU TLB over an access stream. Returns (hits, misses, faults, trace)."""
    tlb = []  # VPNs in LRU order (front = least recently used)
    cache = {}  # vpn -> pfn for fast membership
    hits = misses = faults = 0
    trace = []
    for vaddr in accesses:
        vpn = vaddr >> PAGE_BITS
        if vpn in cache:
            hits += 1
            tlb.remove(vpn)
            tlb.append(vpn)
            trace.append((vaddr, vpn, "TLB HIT"))
            continue
        misses += 1
        if vpn not in PAGE_TABLE:
            faults += 1
            trace.append((vaddr, vpn, "PAGE FAULT"))
            continue
        if len(tlb) >= tlb_size:
            evicted = tlb.pop(0)
            cache.pop(evicted, None)
        tlb.append(vpn)
        cache[vpn] = PAGE_TABLE[vpn]
        trace.append((vaddr, vpn, "TLB MISS"))
    return hits, misses, faults, trace


def section_virtual_memory():
    print()
    print("=" * 72)
    print("=== Virtual memory — page-table translation (VPN / offset / PFN)")
    print("=" * 72)
    print(f"  page size = {PAGE_SIZE} bytes (2^{PAGE_BITS})")
    print(f"  virtual address = {VPN_BITS}-bit VPN | {PAGE_BITS}-bit offset")
    print(f"  page table = {{vpn: pfn}} = {dict(sorted(PAGE_TABLE.items()))}")
    print()

    print("  virtual addr   vpn   offset    pfn   physical addr")
    print("  ------------   ---   ------    ---   -------------")
    for vaddr in DEMO_ADDRESSES:
        paddr, vpn, offset = translate(vaddr)
        if paddr is None:
            print(f"  0x{vaddr:04X}        {vpn:>2}   0x{offset:03X}     "
                  f"--    PAGE FAULT (vpn {vpn} not mapped)")
        else:
            pfn = PAGE_TABLE[vpn]
            print(f"  0x{vaddr:04X}        {vpn:>2}   0x{offset:03X}    "
                  f"{pfn:>2}    0x{paddr:04X}")

    paddr, _, _ = translate(0x2C8A)
    ok = paddr == 0x3C8A
    print()
    print(f"  translate(0x2C8A) = 0x{paddr:04X}   [check] {'OK' if ok else 'FAIL'}"
          f"   (vpn2->pfn3, offset 0xC8A)")
    assert ok

    # --- TLB simulation --------------------------------------------------
    # Working set = {vpn0, vpn1, vpn2} fits the 3-entry TLB, so after three
    # cold misses every re-access is a HIT (spatial+temporal locality).
    print()
    print("--- TLB simulation (LRU, 3-entry) ---")
    accesses = [
        0x2C8A, 0x2C8B, 0x1A2F, 0x0710,  # VPNs 2,2,1,0  -> cold-load working set
        0x2C8C, 0x1A30, 0x0711, 0x2000,  # 2,1,0,2       -> all HITs
        0x1A31, 0x0712, 0x2C8D, 0x0713,  # 1,0,2,0       -> all HITs
        0x1A32, 0x2C8E, 0x0700, 0x1A33,  # 1,2,0,1       -> all HITs
    ]
    tlb_size = 3
    hits, misses, faults, trace = tlb_simulate(accesses, tlb_size)
    print(f"  TLB size = {tlb_size}   accesses = {len(accesses)}")
    print()
    print(f"  {'#':>3}  {'vaddr':>8}  {'vpn':>3}  result")
    print(f"  {'---':>3}  {'--------':>8}  {'---':>3}  ------")
    for idx, (vaddr, vpn, res) in enumerate(trace, 1):
        print(f"  {idx:>3}  0x{vaddr:04X}   {vpn:>3}  {res}")
    total = hits + misses
    hit_rate = hits / total * 100 if total else 0
    print()
    print(f"  TLB hits = {hits}   misses = {misses}   "
          f"page faults = {faults}   hit rate = {hit_rate:.1f}%")
    ok_tlb = hits > misses
    print(f"  [check] {'OK' if ok_tlb else 'FAIL'}"
          f"   (working set fits TLB -> hit rate exceeds miss rate)")
    assert ok_tlb


# ===========================================================================
# Main driver
# ===========================================================================

if __name__ == "__main__":
    section_fcfs()
    section_sjf()
    section_srtf()
    section_round_robin()
    section_scheduling_comparison()
    section_page_replacement()
    section_belady()
    section_virtual_memory()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
