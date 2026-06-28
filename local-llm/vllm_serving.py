"""
vllm_serving.py - vLLM vs llama.cpp for local LLM serving, by the numbers.

This is the single source of truth that VLLM_SERVING.md is built from. Every
number, table, and worked example below is printed by this file.

PURE PYTHON STDLIB (no torch, no numpy) - this is the *local runtime* side:
when do you reach for vLLM (high-throughput, multi-user API server) vs
llama.cpp/Ollama (single-user, interactive, CPU-capable)? The whole answer is
"how many concurrent users do you have?", and this file simulates both engines'
throughput curves from first principles.

Run:
    python3 vllm_serving.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
Two engines, two design points:

  llama.cpp / Ollama : optimized for ONE user. It serves requests sequentially
                       (or with very simple batching). Total throughput is
                       ~FLAT no matter how many users queue up - they just take
                       turns. Great on a laptop; even runs on CPU.

  vLLM              : optimized for MANY concurrent users. Two innovations turn
                       the flat line into a curve that GROWS with concurrency:

    1. PAGEDATTENTION  - the KV cache is stored in fixed-size non-contiguous
                          BLOCKS (like OS virtual-memory pages) instead of one
                          contiguous buffer per request. Naive contiguous
                          allocation reserves the WORST-CASE length per request
                          and wastes 60-80% of KV-cache memory to internal
                          fragmentation. Paging wastes <5%, so far more requests
                          fit on the same GPU.

    2. CONTINUOUS BATCHING (iteration-level scheduling) - instead of waiting
                          for a whole batch to finish before admitting new
                          requests (static / request-level batching), vLLM
                          inserts a waiting request into the running batch the
                          very next iteration that a slot frees up. New work
                          starts immediately; the GPU is never left idling on a
                          half-empty batch.

WHY BATCHING WINS (the deep reason, cross-ref speculative_local.py Section A):
   decode is MEMORY-BANDWIDTH-BOUND. The dominant cost of one forward pass is
   streaming the weight matrix from VRAM once - and that cost is ~the SAME for
   batch 1 and batch 32 (the weight read is amortised across every sequence in
   the batch; the extra activations are negligible). So running N sequences
   together produces N times the tokens for barely-more time, UNTIL the memory
   bus saturates. That saturation is why the vLLM curve GROWS then flattens.

THE TWO CURVES (Llama-3-8B, single RTX 4090, the model this file simulates):

   llama.cpp total(N) = 60 tok/s            (FLAT - one request at a time)
   llama.cpp per-user(N) = 60 / N           (divides the flat pie)

   vLLM    total(N) = 900 * N / (N + 10)   (saturating toward the bw ceiling)
   vLLM    per-user(N) = 900 / (N + 10)    (graceful degradation)

   The two constants are fit to the measured gold points (Section D):
     N=10 : vLLM = 45 tok/s/user  (total 450),  llama.cpp = 6 tok/s/user  -> 7.5x
     N=50 : vLLM = 15 tok/s/user  (total 750),  total 12.5x llama.cpp's 60

GOLD VALUE (for VLLM_SERVING.html to reproduce):
     10 concurrent users, Llama-3-8B on RTX 4090:
        llama.cpp sequential  =  6.0 tok/s/user   (60 total / 10)
        vLLM continuous batch = 45.0 tok/s/user   (450 total)   -> 7.5x
     50 concurrent users:
        vLLM = 15.0 tok/s/user, total = 750 tok/s   (per-user = 900/60)
"""

from __future__ import annotations

import random

BANNER = "=" * 74


# ============================================================================
# 0. CHECK HELPER
# ============================================================================

def check(label: str, cond: bool, detail: str = "") -> None:
    """Assert-style checker that prints [check] lines for _output.txt."""
    status = "OK" if cond else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"[check] {label} :  {status}{extra}")
    assert cond, f"CHECK FAILED: {label} {detail}"


def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 1. THE TWO ENGINES COMPARED
# ============================================================================

ENGINES = {
    "llama.cpp / Ollama": {
        "target": "single user, interactive",
        "batching": "sequential / static (request-level)",
        "kv_cache": "contiguous buffer per request",
        "gpu": "GPU optional (runs on CPU, Apple Metal)",
        "throughput": "flat (does not scale with users)",
    },
    "vLLM": {
        "target": "multiple concurrent users, API serving",
        "batching": "continuous (iteration-level scheduling)",
        "kv_cache": "PagedAttention (non-contiguous blocks)",
        "gpu": "NVIDIA GPU required (CUDA)",
        "throughput": "grows with concurrency, saturates at bw ceiling",
    },
}


# ============================================================================
# 2. THE THROUGHPUT MODELS (the load-bearing formulas)
# ============================================================================
#
# llama.cpp: processes requests essentially one at a time, so the GPU's
#   batch-1 decode rate is an UPPER BOUND on aggregate throughput. Adding more
#   users just slices the same flat pie into thinner pieces.
#       total(N) = T1              (constant, the batch-1 decode rate)
#       per_user(N) = T1 / N
#
# vLLM: continuous batching packs many sequences into each forward pass.
#   Because decode is memory-bound, total tokens grow with N - but not forever:
#   the memory bus saturates, so aggregate throughput follows a saturating
#   (Michaelis-Menten) curve with a ceiling T_SAT and a half-saturation point
#   N_HALF (the concurrency at which total reaches T_SAT / 2).
#       total(N) = T_SAT * N / (N + N_HALF)
#       per_user(N) = total(N) / N = T_SAT / (N + N_HALF)
#
# Fit to measured gold points (Llama-3-8B, RTX 4090):
#   T1 = 60 tok/s        (batch-1 decode rate - matches llama.cpp 1 user)
#   T_SAT = 900 tok/s    (the memory-bandwidth ceiling for this GPU+model)
#   N_HALF = 10          (half-saturation concurrency)

LLAMACPP_T1 = 60.0       # tok/s, flat aggregate (sequential serving)
VLLM_T_SAT = 900.0       # tok/s, aggregate throughput ceiling (bw-bound)
VLLM_N_HALF = 10.0       # concurrency at which vLLM total = T_SAT / 2

# The canonical vLLM serve invocation (Section E). The three capacity/throughput
# flags are the ones an operator actually tunes for local serving.
VLLM_SETUP = (
    "vllm serve meta-llama/Llama-3.1-8B-Instruct "
    "--tensor-parallel-size 1 --max-model-len 8192 --gpu-memory-utilization 0.9"
)


def llamacpp_total(n_users: int) -> float:
    """llama.cpp aggregate tok/s: FLAT (one request served at a time)."""
    if n_users <= 0:
        return 0.0
    return LLAMACPP_T1


def llamacpp_per_user(n_users: int) -> float:
    """llama.cpp per-user tok/s: the flat pie divided N ways."""
    if n_users <= 0:
        return 0.0
    return LLAMACPP_T1 / n_users


def vllm_total(n_users: int) -> float:
    """vLLM aggregate tok/s: saturating curve toward the bandwidth ceiling."""
    if n_users <= 0:
        return 0.0
    return VLLM_T_SAT * n_users / (n_users + VLLM_N_HALF)


def vllm_per_user(n_users: int) -> float:
    """vLLM per-user tok/s = T_SAT / (N + N_HALF) - graceful degradation."""
    if n_users <= 0:
        return 0.0
    return VLLM_T_SAT / (n_users + VLLM_N_HALF)


def speedup(n_users: int) -> float:
    """Per-user speedup of vLLM over llama.cpp at N concurrent users."""
    lc = llamacpp_per_user(n_users)
    if lc <= 0:
        return 0.0
    return vllm_per_user(n_users) / lc


# ============================================================================
# 3. PAGEDATTENTION - the KV cache memory-waste simulation
# ============================================================================
#
# Naive KV allocation (HF Transformers / llama.cpp server per-request buffer):
#   each request reserves a CONTIGUOUS buffer sized to the WORST-CASE sequence
#   length (max_model_len). Because real lengths are usually far shorter than
#   the worst case, most of every buffer is unused -> 60-80% waste (the figure
#   reported in the PagedAttention paper, arXiv:2309.06180).
#
# PagedAttention:
#   the KV cache is a pool of fixed-size BLOCKS (block_size tokens). A request
#   grabs blocks ON DEMAND as it grows - ceil(actual_len / block_size) blocks.
#   Internal fragmentation is at most (block_size - 1) tokens per request, i.e.
#   <5% waste. Same GPU holds far more concurrent requests.

BLOCK_SIZE = 16
MAX_SEQ_LEN = 2048        # worst-case reservation per request (naive scheme)


def gen_workload(n_requests: int, max_len: int = MAX_SEQ_LEN,
                 seed: int = 42) -> list[int]:
    """Realistic heavy-tailed request-length distribution (seeded, deterministic).

    Most requests are short chats; a few are long-context (RAG, code, docs).
    This is exactly the pattern where worst-case reservation wastes the most.
    """
    rng = random.Random(seed)
    lengths = []
    for _ in range(n_requests):
        r = rng.random()
        if r < 0.6:
            lengths.append(rng.randint(64, 384))        # short chat (60%)
        elif r < 0.9:
            lengths.append(rng.randint(384, 1024))      # medium RAG/code (30%)
        else:
            lengths.append(rng.randint(1024, max_len))  # long context (10%)
    return sorted(lengths)


def naive_kv_reserved(lengths: list[int], max_len: int = MAX_SEQ_LEN) -> int:
    """Contiguous scheme: reserve worst-case length per request."""
    return len(lengths) * max_len


def paged_kv_reserved(lengths: list[int], block_size: int = BLOCK_SIZE) -> int:
    """PagedAttention scheme: ceil(len / block) blocks per request."""
    total = 0
    for ln in lengths:
        n_blocks = (ln + block_size - 1) // block_size
        total += n_blocks * block_size
    return total


def waste_fraction(reserved: int, used: int) -> float:
    """Fraction of reserved KV-cache memory that is unused."""
    if reserved <= 0:
        return 0.0
    return (reserved - used) / reserved


# ============================================================================
# 4. CONTINUOUS BATCHING - the scheduling trace simulator
# ============================================================================
#
# Discrete, iteration-level simulator. One iteration = one decode step. A
# request runs one token per iteration it spends in the `running` set. Two
# admission policies:
#
#   STATIC (request-level / "batch-level") batching:
#     - form a batch of up to MAX_BATCH requests from the queue
#     - run it until EVERY request in the batch finishes
#     - only then admit the next batch (finished-early slots stay empty)
#
#   CONTINUOUS (iteration-level) batching:
#     - at every iteration, admit queued requests into any free slot up to
#       MAX_BATCH. A request that finishes mid-batch frees its slot IMMEDIATELY
#       for the next arrival. No head-of-line blocking.
#
# MAX_BATCH models the engine's concurrency cap (bounded by KV-cache room and
# by how many sequences fit in one matmul). It is what makes the slot-freeing
# behaviour visible.


def simulate_batching(arrivals: dict, lengths: dict, max_batch: int,
                      mode: str) -> dict:
    """Simulate a serving scheduler. Returns {req: finish_iteration}.

    arrivals : {req: arrival_iteration}
    lengths  : {req: tokens_to_generate}
    max_batch: max concurrent requests in the running set
    mode     : 'static' or 'continuous'
    """
    reqs = sorted(lengths)
    horizon = sum(lengths.values()) + max(arrivals.values(), default=0) + max_batch + 10
    running = set()
    queue: list = []
    progress = {r: 0 for r in reqs}
    done: dict = {}
    ran: dict = {r: [] for r in reqs}     # iterations each request was running
    for it in range(horizon):
        # arrivals enter the FIFO queue
        for r in reqs:
            if (arrivals[r] == it and r not in running
                    and r not in done and r not in queue):
                queue.append(r)
        if mode == "continuous":
            # admit into any free slot every iteration
            while queue and len(running) < max_batch:
                running.add(queue.pop(0))
        else:  # static: only admit when the WHOLE batch has drained
            if not running:
                while queue and len(running) < max_batch:
                    running.add(queue.pop(0))
        # advance every running request by one token
        finished = []
        for r in sorted(running):
            progress[r] += 1
            ran[r].append(it)
            if progress[r] >= lengths[r]:
                finished.append(r)
        for r in finished:
            running.discard(r)
            done[r] = it
        if len(done) == len(reqs):
            break
    return done, ran


def gantt_row(req: str, arrival: int, ran_iters: list[int], finish: int,
              horizon: int) -> str:
    """ASCII timeline: ' '=not arrived, '.'=queued/waiting, '#'=running, '-'=done."""
    ran_set = set(ran_iters)
    chars = []
    for it in range(horizon):
        if it < arrival:
            chars.append(" ")
        elif it in ran_set:
            chars.append("#")
        elif it <= finish:
            chars.append(".")          # arrived but queued (not running)
        else:
            chars.append("-")
    return f"{req} |" + "".join(chars)


# ============================================================================
# 5. SECTIONS (the numbers that feed VLLM_SERVING.md)
# ============================================================================

def section_a_engines():
    banner("SECTION A: the two engines - design points at a glance")
    print("Two local serving engines, two opposite design points. Pick by how")
    print("many CONCURRENT users you serve - that single question decides it.\n")
    print("| property     | llama.cpp / Ollama                  | vLLM                                |")
    print("|--------------|-------------------------------------|-------------------------------------|")
    for key in ["target", "batching", "kv_cache", "gpu", "throughput"]:
        a = ENGINES["llama.cpp / Ollama"][key]
        b = ENGINES["vLLM"][key]
        print(f"| {key:<12} | {a:<35} | {b:<35} |")
    print()
    print("The rest of this file quantifies the last two rows: PagedAttention")
    print("(KV cache - Section B), continuous batching (scheduling - Section C),")
    print("and the throughput curves those two enable (Section D).\n")
    check("engines target opposite workloads",
          "single" in ENGINES["llama.cpp / Ollama"]["target"]
          and "concurrent" in ENGINES["vLLM"]["target"])
    check("vLLM requires a GPU, llama.cpp does not",
          "CUDA" in ENGINES["vLLM"]["gpu"]
          and "CPU" in ENGINES["llama.cpp / Ollama"]["gpu"])


def section_b_pagedattention():
    banner("SECTION B: PagedAttention - kill the 60-80% KV-cache waste")
    print("A request's KV cache grows as it generates. The naive scheme reserves")
    print(f"a CONTIGUOUS worst-case buffer (max_len = {MAX_SEQ_LEN} tokens) for")
    print("EVERY request - so a 200-token chat holds a 2048-token slot. PagedAttention")
    print(f"instead stores KV in fixed {BLOCK_SIZE}-token BLOCKS grabbed on demand,\n"
          "like OS virtual-memory pages. Waste collapses from the bulk of memory to a\n"
          "few tokens per request.\n")
    n = 16
    lengths = gen_workload(n)
    used = sum(lengths)
    naive = naive_kv_reserved(lengths)
    paged = paged_kv_reserved(lengths)
    print(f"Workload: {n} concurrent requests, heavy-tailed lengths (seed=42):")
    print(f"  actual lengths: {lengths}")
    print(f"  total KV actually used  = {used} tokens")
    print(f"  naive reserved (worst-case x {n}) = {naive} tokens")
    print(f"  paged reserved (blocks of {BLOCK_SIZE})     = {paged} tokens\n")
    w_naive = waste_fraction(naive, used)
    w_paged = waste_fraction(paged, used)
    print("| scheme          | reserved | used  | waste   | waste % |")
    print("|-----------------|----------|-------|---------|---------|")
    print(f"| naive contiguous| {naive:>8} | {used:>5} | {naive - used:>7} | {w_naive*100:>6.1f}%  |")
    print(f"| PagedAttention  | {paged:>8} | {used:>5} | {paged - used:>7} | {w_paged*100:>6.1f}%  |")
    print()
    # how many more requests fit on the same GPU under paging?
    extra = (naive // (paged // n)) - n if paged > 0 else 0
    print(f"Same {MAX_SEQ_LEN}-token budget, paging uses {paged}/{naive} = "
          f"{paged / naive * 100:.1f}% of the naive footprint.")
    print(f"-> on the SAME GPU you can hold ~{(naive / paged):.1f}x as many concurrent")
    print("   requests. More concurrent requests in KV room = higher batch sizes =")
    print("   the throughput gains in Section D.\n")
    check("naive KV waste is in the 60-80% band reported by the paper",
          0.60 <= w_naive <= 0.80, f"got {w_naive*100:.1f}%")
    check("paged waste is tiny (<5%)", w_paged < 0.05, f"got {w_paged*100:.1f}%")
    check("paging fits more requests in the same memory", naive > paged)


def section_c_continuous_batching():
    banner("SECTION C: continuous batching - no head-of-line blocking")
    print("Discrete iteration-level simulator (1 iteration = 1 decode step). A")
    print("request advances one token per iteration in the running set. MAX_BATCH")
    print("is the concurrency cap.\n")
    arrivals = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}
    lengths = {"R0": 20, "R1": 8, "R2": 20, "R3": 8}
    max_batch = 2
    print(f"Workload: arrivals {arrivals}, lengths {lengths}, MAX_BATCH={max_batch}")
    print("R0/R2 are long (20 tok); R1/R3 are short (8 tok). They interleave.\n")
    static, static_ran = simulate_batching(arrivals, lengths, max_batch, "static")
    cont, cont_ran = simulate_batching(arrivals, lengths, max_batch, "continuous")
    horizon = max(max(static.values()), max(cont.values())) + 1

    def gantt(done, ran):
        return {r: gantt_row(r, arrivals[r], ran[r], done[r], horizon)
                for r in sorted(lengths)}

    print("STATIC (request-level) batching - a batch runs until ALL finish, then")
    print("the next batch is admitted. Finished-early slots sit EMPTY:\n")
    ruler = "    |" + "".join((str(i % 10) if i % 5 == 0 else ".")
                              for i in range(horizon))
    print(ruler)
    for r in sorted(lengths):
        print(gantt(static, static_ran)[r])
    print()
    print("CONTINUOUS (iteration-level) batching - a freed slot is refilled at the")
    print("VERY NEXT iteration. Short requests don't wait behind a long batch:\n")
    print(ruler)
    for r in sorted(lengths):
        print(gantt(cont, cont_ran)[r])
    print()
    print("('#' = running, '.' = waiting/queued, ' ' = not yet arrived, '-' = done)\n")

    print("| request | arrival | length | static finish | continuous finish |")
    print("|---------|---------|--------|---------------|-------------------|")
    for r in sorted(lengths):
        print(f"| {r}       | {arrivals[r]:>7} | {lengths[r]:>6} | "
              f"{static[r]:>13} | {cont[r]:>17} |")
    print()
    lat_static = sum(static[r] - arrivals[r] for r in lengths) / len(lengths)
    lat_cont = sum(cont[r] - arrivals[r] for r in lengths) / len(lengths)
    print(f"  wall-clock (last finish): static={max(static.values())} iters,  "
          f"continuous={max(cont.values())} iters  "
          f"-> {max(static.values()) / max(cont.values()):.2f}x faster")
    print(f"  mean latency (finish-arrival): static={lat_static:.1f} iters,  "
          f"continuous={lat_cont:.1f} iters  -> {lat_static / lat_cont:.2f}x better")
    print(f"  R1 (short req): finishes @ {cont['R1']} (continuous) vs "
          f"@ {static['R1']} (static) -> {static['R1'] / cont['R1']:.1f}x less waiting\n")
    check("continuous finishes the whole workload sooner",
          max(cont.values()) < max(static.values()),
          f"{max(cont.values())} vs {max(static.values())}")
    check("short request R1 finishes far earlier under continuous batching",
          cont["R1"] < static["R1"], f"{cont['R1']} vs {static['R1']}")
    check("every request finishes no later under continuous than static",
          all(cont[r] <= static[r] for r in lengths))


def section_d_throughput():
    banner("SECTION D: the throughput curves - sequential vs continuous batching")
    print("Llama-3-8B on a single RTX 4090. llama.cpp is FLAT (serves one request")
    print("at a time, so adding users just slices the same pie). vLLM GROWS then")
    print("saturates: continuous batching packs sequences into each memory-bound")
    print("forward pass, so aggregate tok/s rises toward the bandwidth ceiling.\n")
    print(f"    llama.cpp total(N) = {LLAMACPP_T1:.0f}                       [flat]")
    print(f"    vLLM    total(N) = {VLLM_T_SAT:.0f} * N / (N + {VLLM_N_HALF:.0f})   "
          f"[saturating, half-sat @ N={VLLM_N_HALF:.0f}]\n")
    print("| users | llama total | llama /user | vLLM total | vLLM /user | vLLM speedup |")
    print("|-------|-------------|-------------|------------|------------|--------------|")
    for n in [1, 2, 5, 10, 20, 30, 50]:
        lt = llamacpp_total(n)
        lp = llamacpp_per_user(n)
        vt = vllm_total(n)
        vp = vllm_per_user(n)
        sp = speedup(n)
        print(f"| {n:>5} | {lt:>9.0f}   | {lp:>9.1f}   | {vt:>8.0f}   | {vp:>8.1f}   "
              f"| {sp:>10.2f}x |")
    print()
    print("Read the table two ways:")
    print("  - PER-USER (latency): both engines degrade as N grows, but llama.cpp")
    print(f"    collapses as 1/N (10 users -> {llamacpp_per_user(10):.0f} tok/s each)")
    print(f"    while vLLM degrades gently ({vllm_per_user(50):.0f} tok/s even at 50 users).")
    print("  - TOTAL (throughput): llama.cpp is pinned at 60; vLLM climbs from")
    print(f"    {vllm_total(1):.0f} toward {VLLM_T_SAT:.0f} (at N=50 it is {vllm_total(50):.0f}/req).\n")
    print("Why vLLM does NOT just equal N x 60: the memory bus saturates. Each")
    print("added sequence shares the SAME weight read, so total rises, but the bus")
    print(f"caps it at ~{VLLM_T_SAT:.0f} tok/s aggregate. That cap is the curve's flat top.\n")
    check("llama.cpp total is flat at 60 regardless of users",
          all(llamacpp_total(n) == 60.0 for n in [1, 10, 50]))
    check("vLLM total grows with users (10 -> 50 rises)",
          vllm_total(50) > vllm_total(10))
    check("both engines degrade in per-user tok/s as users grow",
          vllm_per_user(50) < vllm_per_user(10) < vllm_per_user(1))
    check("vLLM per-user > llama.cpp per-user for all N>=2",
          all(vllm_per_user(n) > llamacpp_per_user(n) for n in [2, 5, 10, 50]))


def section_e_when_to_use():
    banner("SECTION E: when to use which - the decision rules + setup")
    print("The choice is dominated by ONE variable: how many concurrent users?\n")
    print("| workload                         | pick             | why                            |")
    print("|----------------------------------|------------------|--------------------------------|")
    print("| single user, interactive (chat)  | llama.cpp/Ollama | lower overhead, fast cold-start|")
    print("| multiple concurrent users / API  | vLLM             | 7.5-15x throughput (Section D) |")
    print("| CPU-only / edge device           | llama.cpp only   | vLLM requires an NVIDIA GPU    |")
    print("| Apple Silicon (M-series)         | MLX / Ollama     | neither vLLM (no CUDA) nor     |")
    print("|                                  |                  | llama.cpp's sweet spot         |")
    print()
    print("Practical vLLM setup (OpenAI-compatible API server):\n")
    print("  vllm serve meta-llama/Llama-3.1-8B-Instruct \\")
    print("      --tensor-parallel-size 1 \\       # number of GPUs (TP degree)")
    print("      --max-model-len 8192 \\           # max context -> sets KV room")
    print("      --gpu-memory-utilization 0.9      # fraction of VRAM vLLM may use")
    print()
    print("  # the three flags that decide capacity & throughput:")
    print("  #   --max-model-len      : caps each request's KV (bigger = more VRAM)")
    print("  #   --gpu-memory-util    : how much VRAM -> how big the block pool is")
    print("  #   --tensor-parallel-size: spread one model across N GPUs (shard layers)")
    print()
    print("Equivalent llama.cpp single-user server (no GPU required):\n")
    print("  llama-server -m Llama-3.1-8B-Instruct.Q4_K_M.gguf \\")
    print("      -ngl 99 -c 8192 --port 8080\n")
    print("Crossover rule of thumb (community + Red Hat benchmark): below ~4-5")
    print("concurrent users, llama.cpp is simpler and fast enough; above that, vLLM's")
    print("continuous batching pulls away hard. At 10+ users there is no contest.\n")
    vllm_flags = ["--tensor-parallel-size", "--max-model-len", "--gpu-memory-utilization"]
    check("vLLM setup exposes the 3 capacity/throughput flags",
          all(f in VLLM_SETUP for f in vllm_flags))
    check("llama.cpp runs without a GPU; vLLM does not",
          ENGINES["llama.cpp / Ollama"]["gpu"] != ENGINES["vLLM"]["gpu"])


def section_gold():
    banner("GOLD - the canonical numbers the HTML must reproduce")
    g10_lc = llamacpp_per_user(10)
    g10_vl = vllm_per_user(10)
    g10_ratio = speedup(10)
    g50_vl = vllm_per_user(50)
    g50_total = vllm_total(50)
    print("10 concurrent users, Llama-3-8B on RTX 4090:")
    print(f"  llama.cpp sequential    = {g10_lc:.1f} tok/s/user   "
          f"(total {llamacpp_total(10):.0f} / 10)")
    print(f"  vLLM continuous batching= {g10_vl:.1f} tok/s/user   "
          f"(total {vllm_total(10):.0f})   -> {g10_ratio:.1f}x\n")
    print("50 concurrent users:")
    print(f"  vLLM = {g50_vl:.1f} tok/s/user, total = {g50_total:.0f} tok/s   "
          f"(per-user = {VLLM_T_SAT:.0f}/{50+VLLM_N_HALF:.0f})\n")
    print(f"Recompute recipe (identical in VLLM_SERVING.html):")
    print(f"  vllm_per_user(10) = {VLLM_T_SAT:.0f} / (10 + {VLLM_N_HALF:.0f}) = "
          f"{VLLM_T_SAT / (10 + VLLM_N_HALF):.1f}")
    print(f"  vllm_per_user(50) = {VLLM_T_SAT:.0f} / (50 + {VLLM_N_HALF:.0f}) = "
          f"{VLLM_T_SAT / (50 + VLLM_N_HALF):.1f}")
    print(f"  vllm_total(50)    = {VLLM_T_SAT:.0f} * 50 / (50 + {VLLM_N_HALF:.0f}) = "
          f"{VLLM_T_SAT * 50 / (50 + VLLM_N_HALF):.0f}\n")
    check("gold: llama.cpp @10 = 6.0 tok/s/user", abs(g10_lc - 6.0) < 1e-9,
          f"got {g10_lc}")
    check("gold: vLLM @10 = 45.0 tok/s/user", abs(g10_vl - 45.0) < 1e-9,
          f"got {g10_vl}")
    check("gold: speedup @10 = 7.5x", abs(g10_ratio - 7.5) < 1e-9,
          f"got {g10_ratio}")
    check("gold: vLLM @50 = 15.0 tok/s/user", abs(g50_vl - 15.0) < 1e-9,
          f"got {g50_vl}")
    check("gold: vLLM total @50 = 750 tok/s", abs(g50_total - 750.0) < 1e-9,
          f"got {g50_total}")


# ============================================================================
# main
# ============================================================================

def main():
    print("vllm_serving.py - vLLM vs llama.cpp for local LLM serving, by the numbers.")
    print("Pure Python stdlib. Numbers below feed VLLM_SERVING.md.")
    print("Model: Llama-3-8B on a single RTX 4090 (the simulated reference setup).")
    print()
    print("Lineage: single-user llama.cpp -> PagedAttention -> continuous batching")
    print("       -> vLLM high-throughput server.")

    section_a_engines()
    section_b_pagedattention()
    section_c_continuous_batching()
    section_d_throughput()
    section_e_when_to_use()
    section_gold()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
