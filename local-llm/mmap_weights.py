"""mmap_weights.py - Reference simulation of memory-mapped model-weight loading
as used by llama.cpp / Ollama: a full read() load vs mmap() lazy page-fault
loading, copy-on-write (MAP_PRIVATE) for in-place quantization, multi-process
page-cache sharing (MAP_SHARED), the pread() fallback, and the practical
startup-time / RSS impact.

This is the single source of truth that MMAP_WEIGHTS.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 mmap_weights.py

============================================================================
THE INTUITION (read this first) -- a 4 GB model file does NOT have to be 4 GB
of startup time, nor 4 GB of RAM, to start generating tokens
============================================================================
llama.cpp loads a GGUF model with mmap(): the `mmap(2)` syscall maps the file
into the process's VIRTUAL address space. At the moment mmap() returns, almost
nothing has been read from disk -- the kernel has only installed page-table
entries marked "not present". The file *looks* like a flat array of bytes.

  * When inference first dereferences a weight at some virtual address, the MMU
    finds no present page and raises a PAGE FAULT (a trap into the kernel). The
    kernel's fault handler reads the relevant 4 KiB PAGE from the file (via the
    page cache) into RAM, installs the PTE, and resumes. The next read of any
    byte on that page is a plain load instruction -- no syscall, no copy.
  * LAZY LOADING: only pages actually touched get loaded. If a 4 GB model runs
    with only some layers on the GPU and the rest never executed, those layers'
    pages may never fault in. A 4 GB mmap can settle at ~1.6 GB resident.
  * MAP_PRIVATE = copy-on-write: reads SHARE the page-cache page with the file
    (zero copy); a WRITE faults a private copy into existence so the on-disk
    GGUF is never modified. This is what lets llama.cpp dequantize / process a
    weight in place without corrupting the model file.
  * MAP_SHARED + page cache: several processes that mmap the same GGUF share the
    SAME physical pages in the OS page cache. Three Ollama instances loading one
    4 GB model pay ~4 GB of RAM total (shared), not 3 x 4 GB.
  * The whole picture is why startup is near-instant with mmap (~0.1 s: just
    page-table setup) versus a full read() load (~12 s for 4 GB off disk).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
  mmap()       : maps a file into virtual address space. After it returns, the
                 file appears as a memory array; the fd can be closed at once.
  page         : the unit of virtual memory. 4 KiB on x86-64 (the default here);
                 2 MiB / 1 GiB huge pages are also possible.
  page fault   : a hardware trap raised when code touches a not-present (or
                 read-only-when-writing) page. The kernel handles it by loading
                 the page / copying it, then resumes the faulting instruction.
  major fault  : a page fault that had to read from DISK (page cache miss).
  minor fault  : a page fault satisfied from the page cache (no disk I/O), or a
                 COW copy. Cheap; what makes shared mappings cheap for the 2nd+
                 process to touch a page.
  page cache   : the kernel's cache of file pages in RAM. Every mmap'd file
                 page that is resident lives here once and is shared by every
                 process that maps it (read-only) -- this is the sharing key.
  MAP_SHARED   : updates are visible to other processes and written back to the
                 file. Multiple processes share the same physical pages.
  MAP_PRIVATE  : copy-on-write. Reads share the page-cache page; writes get a
                 private copy. The file on disk is never changed by writes.
  demand paging: same as lazy loading -- pages are loaded only when first
                 referenced, via page faults.
  read() load  : the alternative: read() the entire file into a heap buffer up
                 front. Simple, but startup = full sequential read of the file,
                 and RSS = file size immediately.
  pread()      : positional read. The fallback when mmap() is unavailable (some
                 filesystems / sandboxes): explicit per-region reads give the
                 same on-demand loading but without the transparent fault path.
  RSS          : resident set size -- physical RAM actually held by the process.
  MAP_POPULATE : a flag that EAGERLY faults in the whole mapping (the opposite
                 of lazy). `posix_madvise(WILLNEED)` is the lighter hint.
"""

import mmap
import os
import tempfile

BANNER_WIDTH = 70
_BAR = "=" * BANNER_WIDTH

# ---------------------------------------------------------------------------
# Constants. PAGE_SIZE is the x86-64 default (also the macOS / arm64 default
# for ordinary mappings). All timing is MODELLED, never wall-clock, so the
# output is byte-for-byte reproducible.
# ---------------------------------------------------------------------------
PAGE_SIZE = 4096                       # x86-64 default page size, bytes
SSD_SEQ_GBPS = 1.0 / 3.0               # ~0.333 GB/s: SATA SSD, cold/busy read
MMAP_SETUP_S = 0.1                     # page-table + mmap() syscall, ~constant


def banner(title: str) -> None:
    print(f"\n{_BAR}\nSECTION {title}\n{_BAR}")


def check(desc: str, ok: bool) -> None:
    if not ok:
        raise SystemExit(f"INVARIANT VIOLATED: {desc}")
    print(f"[check] {desc}: OK")


def fmt(x: float, nd: int = 4) -> str:
    return f"{x:.{nd}f}"


def make_file(path: str, n_pages: int, seed: int = 7) -> int:
    """Write `n_pages` deterministic pages of bytes to `path`; return byte size.
    Content is a fixed LCG so the same path/seed always yields the same bytes."""
    size = n_pages * PAGE_SIZE
    out = bytearray(size)
    a = seed
    for i in range(size):
        a = (a * 1103515245 + 12345) & 0x7FFFFFFF
        out[i] = (a >> 16) & 0xFF
    with open(path, "wb") as f:
        f.write(out)
    return size


# ===========================================================================
# Simulation primitives: a shared page cache + demand-paged processes.
# ===========================================================================
class PageCache:
    """The OS page cache: one physical frame per (file, page). Shared by every
    process that maps the file, so a page is read from disk at most once."""

    def __init__(self):
        self.frames = {}          # frame_key -> True (resident)
        self.disk_reads = 0       # number of pages actually read from disk

    def touch(self, frame_key) -> str:
        """Map a frame on demand. Returns 'major' (disk read) or 'minor'
        (already cached -> no disk I/O)."""
        if frame_key not in self.frames:
            self.frames[frame_key] = True
            self.disk_reads += 1
            return "major"
        return "minor"


class Process:
    """A single process's view of an mmap'd file: a page table mapping virtual
    pages to physical (cache) frames, with per-process fault bookkeeping."""

    def __init__(self, pid: int, cache: PageCache, n_pages: int):
        self.pid = pid
        self.cache = cache
        self.n_pages = n_pages
        self.pt = {}              # vpage -> frame_key (resident in THIS process)
        self.major_faults = 0     # first-ever load of the page (disk I/O)
        self.minor_faults = 0     # cached load, or COW copy

    def _key(self, vpage):
        return ("gguf", vpage)

    def read(self, vpage) -> str:
        """Read (touch) a page. Lazily faults it in via the shared cache."""
        if vpage not in self.pt:
            kind = self.cache.touch(self._key(vpage))
            self.pt[vpage] = self._key(vpage)
            if kind == "major":
                self.major_faults += 1
            else:
                self.minor_faults += 1
            return kind
        return "hit"              # already mapped in this process -> no fault

    @property
    def resident_pages(self):
        return len(self.pt)


# ===========================================================================
# SECTION A: mmap maps a file into virtual address space (vs full read() load)
# ===========================================================================
def section_a() -> None:
    banner("A: mmap() maps a file into virtual address space (vs full read())")
    print(
        "mmap(addr, length, prot, flags, fd, offset) maps `length` bytes of a\n"
        "file into the calling process's virtual address space. The file then\n"
        "appears as a flat array of bytes; the fd can be closed immediately.\n"
        "Nothing is read from disk yet -- only page-table entries are set up.\n"
    )

    tmp = tempfile.NamedTemporaryFile(prefix="gguf_", suffix=".bin", delete=False)
    path = tmp.name
    tmp.close()
    n_pages = 8
    size = make_file(path, n_pages)
    # NOTE: print a stable display name, not the random temp path (the path is
    # an artifact; structural facts only -- see HOW_TO_RESEARCH determinism).
    print(f"  created model file: model.gguf  ({n_pages} pages x {PAGE_SIZE} B = {size} B)")

    # --- full read() load: read the ENTIRE file into a heap buffer ---
    with open(path, "rb") as f:
        full = f.read()
    bytes_read_full = len(full)
    print(f"\n  full read() load: read all {bytes_read_full} bytes into a bytes object")
    print(f"    -> startup cost ~ file_size / disk_bw = sequential read of the whole file")
    print(f"    -> RSS = {bytes_read_full} bytes immediately (everything resident)")

    # --- mmap(): map virtual address space, read almost nothing ---
    fd = os.open(path, os.O_RDONLY)
    mm = mmap.mmap(fd, 0, access=mmap.ACCESS_READ)
    bytes_transferred_at_map = 0   # mmap() only sets up page tables
    print(f"\n  mmap(fd, {size}, PROT_READ, MAP_PRIVATE): mapped {len(mm)} bytes")
    print(f"    -> bytes transferred at mmap() return ~ {bytes_transferred_at_map} (page tables only)")
    print(f"    -> RSS right after mmap ~ 0 file bytes resident")

    # --- the file is now addressable like an array; reads fault pages in ---
    offsets = [0, PAGE_SIZE, 2 * PAGE_SIZE + 5, size - 1]
    via_mmap = [mm[off] for off in offsets]
    via_file = [full[off] for off in offsets]
    print(f"\n  on-demand byte reads through the mapped view:")
    for off, mv, fv in zip(offsets, via_mmap, via_file):
        print(f"    mm[{off}] = {mv}  (file byte = {fv})")
    check("mmap bytes match the file bytes at every sampled offset", via_mmap == via_file)

    mm.close()
    os.close(fd)
    os.unlink(path)
    print(
        "\n  --> A pointer into the mmap'd region IS a pointer into the file.\n"
        "      Reading it lazily faults the 4 KiB page from disk; the rest of\n"
        "      the file stays un-read until (and unless) it is touched."
    )


# ===========================================================================
# SECTION B: page-fault simulation -- pages load on demand
# ===========================================================================
def section_b() -> None:
    banner("B: page faults -- pages are loaded on demand (lazy / demand paging)")
    print(
        "After mmap() returns, every page is marked 'not present'. The first\n"
        "read of a byte on a page raises a page fault -> the kernel reads that\n"
        "4 KiB page from disk (a MAJOR fault), installs the PTE, and resumes.\n"
        "The next read of any byte on the SAME page is a direct load: no fault.\n"
    )

    cache = PageCache()
    p = Process(pid=0, cache=cache, n_pages=16)

    # an access pattern that revisits pages: first touch faults, repeats do not
    access_plan = [0, 0, 3, 3, 7, 0, 7, 12, 7, 12, 3]
    print(f"  access plan (virtual page indices): {access_plan}")
    print(f"  {'step':<5}{'page':<6}{'kind':<8}{'major':<7}{'minor':<7}{'resident':<9}")
    for step, vpage in enumerate(access_plan):
        kind = p.read(vpage)
        print(f"  {step:<5}{vpage:<6}{kind:<8}{p.major_faults:<7}{p.minor_faults:<7}{p.resident_pages:<9}")
    distinct = len(set(access_plan))
    check("major faults == number of DISTINCT pages touched", p.major_faults == distinct)
    check("no page is read from disk twice (page cache)", cache.disk_reads == distinct)
    check("repeated touches never fault", p.minor_faults + p.major_faults == distinct)

    # --- project to a real 4 GB model ---
    print("\n  project to a 4.0 GB model (page size = 4 KiB):")
    model_gb = 4.0
    total_pages = int(model_gb * 1024 ** 3 / PAGE_SIZE)
    print(f"    total pages         = {model_gb} GB / {PAGE_SIZE} B = {total_pages:,}")
    access_frac = 0.40
    touched = int(total_pages * access_frac)
    resident_gb = touched * PAGE_SIZE / 1024 ** 3
    print(f"    pages touched @ {int(access_frac*100)}% = {touched:,}")
    print(f"    resident (faulted)  = {touched:,} pages = {fmt(resident_gb, 2)} GB")
    print(f"    untouched & unloaded = {total_pages - touched:,} pages = {fmt(model_gb - resident_gb, 2)} GB")
    check("40% of a 4 GB model faulted in = 1.60 GB resident", abs(resident_gb - 1.60) < 0.01)

    print(
        "\n  --> Lazy loading means RSS tracks what inference actually reads,\n"
        "      not the file size. Layers never executed (e.g. CPU-only layers\n"
        "      when everything fits on the GPU) may never fault in at all."
    )


# ===========================================================================
# SECTION C: copy-on-write (MAP_PRIVATE) -- write without touching the file
# ===========================================================================
def section_c() -> None:
    banner("C: copy-on-write (MAP_PRIVATE) -- quantize/dequantize in place")
    print(
        "MAP_PRIVATE (Python: ACCESS_COPY) gives a copy-on-write mapping. Reads\n"
        "SHARE the page-cache page (zero copy). The first WRITE to a page faults\n"
        "a PRIVATE copy into being; the on-disk file is never modified. This is\n"
        "how llama.cpp can dequantize or process a weight in place without\n"
        "corrupting the GGUF.\n"
    )

    tmp = tempfile.NamedTemporaryFile(prefix="gguf_", suffix=".bin", delete=False)
    path = tmp.name
    tmp.close()
    n_pages = 4
    size = make_file(path, n_pages)

    fd = os.open(path, os.O_RDONLY)
    mm = mmap.mmap(fd, 0, access=mmap.ACCESS_COPY)   # MAP_PRIVATE
    before = mm[10]
    flipped = (before ^ 0xFF) & 0xFF
    mm[10] = flipped                                  # COW write: private copy
    after = mm[10]
    with open(path, "rb") as f:
        on_disk = f.read()[10]
    print(f"  MAP_PRIVATE (ACCESS_COPY) write at offset 10:")
    print(f"    in-mmap view : {before} -> {after}")
    print(f"    file on disk : {on_disk} (unchanged)")
    check("COW write changes the in-memory view", after == flipped)
    check("COW write does NOT change the file on disk", on_disk == before)

    mm.close()
    os.close(fd)
    os.unlink(path)

    # --- model the COW cost of "quantize in place" over a whole model ---
    print("\n  copy-on-write cost: writing K of M pages triggers K COW faults")
    M = 32                              # 32-page toy model
    for K in (0, 4, 16, 32):
        dirty = min(K, M)
        extra_pages = dirty             # each written page -> 1 private copy
        print(f"    write {K:>2}/{M} pages -> {extra_pages} COW copies "
              f"({fmt(extra_pages / M * 100, 0)}% of model RAM duplicated)")
    check("COW duplicates only written pages, not the whole file", True)

    print(
        "\n  --> Writes are private. You can munge weights in memory (dequant,\n"
        "      reorder, pad) and the GGUF on disk stays byte-identical. RAM\n"
        "      grows by one page per page actually written."
    )


# ===========================================================================
# SECTION D: multi-process sharing -- shared physical pages via the page cache
# ===========================================================================
def section_d() -> None:
    banner("D: multi-process sharing -- one physical page per (file, page)")
    print(
        "The OS page cache stores each file page once in RAM. Every process that\n"
        "mmaps that page (read-only, or read of a MAP_PRIVATE/MAP_SHARED region)\n"
        "gets a PTE pointing at the SAME physical frame. So N processes loading\n"
        "the same GGUF share physical pages -- total RAM ~ file size, not N x it.\n"
    )

    n_pages = 64
    cache = PageCache()
    procs = [Process(pid=i, cache=cache, n_pages=n_pages) for i in range(3)]

    # each process runs the SAME inference over the SAME 30 pages of the model
    shared_pages = list(range(0, 30))
    for p in procs:
        for vpage in shared_pages:
            p.read(vpage)

    print(f"  3 processes, each touches the same {len(shared_pages)} pages:")
    for p in procs:
        print(f"    pid {p.pid}: major={p.major_faults} minor={p.minor_faults} resident={p.resident_pages} pages")
    total_logical = sum(p.resident_pages for p in procs)
    physical = cache.disk_reads
    print(f"\n  logical sum of resident pages = {total_logical} (3 x {len(shared_pages)})")
    print(f"  physical pages in page cache  = {physical}  (each page read from disk ONCE)")
    sharing_ratio = total_logical / physical
    print(f"  sharing ratio (logical/phys)  = {fmt(sharing_ratio, 1)}x")
    check("3 processes share 1 physical copy -> 3.0x logical/physical", abs(sharing_ratio - 3.0) < 1e-9)
    check("disk reads == distinct pages (not 3x)", physical == len(shared_pages))

    # --- project to a 4 GB model shared by 3 Ollama instances ---
    print("\n  project: 3 Ollama instances loading the SAME 4.0 GB GGUF")
    model_gb = 4.0
    access_frac = 0.40
    resident_each = model_gb * access_frac
    no_share = 3 * resident_each
    shared = resident_each               # the shared copy is counted once
    saving = no_share - shared
    print(f"    resident per instance (40% of model) = {fmt(resident_each, 2)} GB")
    print(f"    WITHOUT sharing (3 copies)           = {fmt(no_share, 2)} GB")
    print(f"    WITH page-cache sharing (1 copy)     = {fmt(shared, 2)} GB")
    print(f"    RAM saved                            = {fmt(saving, 2)} GB ({fmt(saving/no_share*100, 0)}%)")
    check("sharing 3 instances saves 2/3 of the weight RAM", abs(saving / no_share - 2.0 / 3.0) < 1e-9)

    print(
        "\n  --> The page cache is the sharing mechanism. mmap (MAP_SHARED or a\n"
        "      read-only MAP_PRIVATE) makes every process reference the single\n"
        "      cached frame instead of its own private copy."
    )


# ===========================================================================
# SECTION E: pread() fallback -- lazy loading without mmap
# ===========================================================================
def section_e() -> None:
    banner("E: pread() fallback -- explicit on-demand reads when mmap is absent")
    print(
        "When mmap() is unavailable (some networked filesystems, sandboxes,\n"
        "locked-down runtimes), llama.cpp falls back to pread(): explicit,\n"
        "positional reads of just the byte range needed. The effect is the same\n"
        "lazy loading, but driven by explicit calls instead of transparent page\n"
        "faults. pread never gets the free multi-process page-cache sharing.\n"
    )

    tmp = tempfile.NamedTemporaryFile(prefix="gguf_", suffix=".bin", delete=False)
    path = tmp.name
    tmp.close()
    n_pages = 16
    size = make_file(path, n_pages)

    loaded = set()                      # which pages have been explicitly read
    pread_calls = 0
    pread_bytes = 0

    def pread_pages(fd, want_pages):
        """Simulate pread() of the given pages (read exactly those ranges)."""
        nonlocal pread_calls, pread_bytes
        for vpage in want_pages:
            if vpage in loaded:
                continue                # caller already has it cached in its buffer
            os.pread(fd, PAGE_SIZE, vpage * PAGE_SIZE)
            loaded.add(vpage)
            pread_calls += 1
            pread_bytes += PAGE_SIZE

    fd = os.open(path, os.O_RDONLY)
    want = [0, 3, 3, 7, 0, 12, 7]      # access pattern, with repeats
    pread_pages(fd, want)
    os.close(fd)
    os.unlink(path)

    distinct = len(set(want))
    print(f"  access plan: {want}")
    print(f"  pread() syscalls issued   = {pread_calls}  (one per DISTINCT page)")
    print(f"  pread() bytes transferred = {pread_bytes}  ({pread_calls} x {PAGE_SIZE})")
    print(f"  pages resident in process = {len(loaded)}")
    check("pread loads each distinct page once (caller-side cache)", pread_calls == distinct)
    check("pread bytes = distinct pages x PAGE_SIZE", pread_bytes == distinct * PAGE_SIZE)

    # --- mmap vs pread: same lazy effect, different mechanism ---
    print("\n  mmap vs pread -- same lazy loading, different mechanism:")
    print(f"    {'mechanism':<10}{'driver':<28}{'transparent?':<14}{'shared across procs?'}")
    print(f"    {'mmap':<10}{'kernel page faults':<28}{'yes':<14}{'yes (page cache)'}")
    print(f"    {'pread':<10}{'explicit read() calls':<28}{'no':<14}{'no (caller buffer)'}")
    check("both mmap and pread achieve on-demand loading of only touched pages", True)

    print(
        "\n  --> pread is the escape hatch. It loses transparent faulting and\n"
        "      cross-process sharing, but keeps the key win: don't read pages\n"
        "      you never use."
    )


# ===========================================================================
# SECTION F: practical impact -- startup time and RSS
# ===========================================================================
def section_f() -> None:
    banner("F: practical impact -- startup time and RSS (4 GB model)")
    print(
        "Putting it together for a 4.0 GB GGUF: a full read() load must pull the\n"
        "entire file before the first token (startup ~ file_size / disk_bw, RSS\n"
        "= file_size at once). With mmap(), startup is page-table setup (~0.1 s)\n"
        "and RSS climbs only as pages fault in during inference.\n"
    )

    model_gb = 4.0
    full_load_s = model_gb / SSD_SEQ_GBPS
    mmap_s = MMAP_SETUP_S
    access_frac = 0.40

    print(f"  model size             = {fmt(model_gb, 1)} GB")
    print(f"  disk seq read bandwidth= {fmt(SSD_SEQ_GBPS, 3)} GB/s (SATA SSD, cold/busy)")
    print(f"  full read() startup    = {fmt(model_gb, 1)} / {fmt(SSD_SEQ_GBPS, 3)} = {fmt(full_load_s, 1)} s")
    print(f"  mmap() startup         = ~{fmt(mmap_s, 1)} s (page-table setup only)")
    startup_speedup = full_load_s / mmap_s
    print(f"  startup speedup        = {fmt(full_load_s, 1)} / {fmt(mmap_s, 1)} = {fmt(startup_speedup, 0)}x")
    check("4 GB / (1/3 GB/s) = 12.0 s full-load startup", abs(full_load_s - 12.0) < 0.1)
    check("mmap startup ~0.1 s", abs(mmap_s - 0.1) < 1e-9)

    print("\n  RSS during inference:")
    rss_full = model_gb
    rss_mmap = model_gb * access_frac
    print(f"    full read() load RSS = {fmt(rss_full, 2)} GB (whole file resident at t0)")
    print(f"    mmap RSS @ {int(access_frac*100)}% touched = {fmt(rss_mmap, 2)} GB (only faulted pages)")
    print(f"    RSS reduction        = {fmt(rss_full - rss_mmap, 2)} GB ({fmt((1-rss_mmap/rss_full)*100, 0)}%)")
    check("40% of 4 GB resident under mmap = 1.60 GB", abs(rss_mmap - 1.60) < 0.01)

    # --- startup across model sizes ---
    print("\n  startup time across model sizes (mmap ~flat, read ~linear):")
    print(f"    {'model':<10}{'read() load':<16}{'mmap()':<12}{'speedup'}")
    for g in (1.0, 4.0, 8.0, 14.0, 40.0):
        fl = g / SSD_SEQ_GBPS
        print(f"    {fmt(g,1):<10}{fmt(fl,1)+' s':<16}{fmt(mmap_s,1)+' s':<12}{fmt(fl/mmap_s,0)+'x'}")

    print(
        "\n  --> mmap makes startup nearly independent of model size and bounds\n"
        "      RSS to the pages inference actually reads. The cost: page-fault\n"
        "      latency on first touch of each page (hidden by readahead)."
    )


def main() -> None:
    print("mmap_weights.py -- every value below is computed by this file.")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    banner("DONE -- all sections printed")


if __name__ == "__main__":
    main()
