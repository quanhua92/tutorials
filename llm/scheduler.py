"""
scheduler.py - Reference implementation of the LLM serving Scheduler.

WHAT IS A SCHEDULER? (start here if you have minimal ML background)
   A Transformer generates text ONE TOKEN AT A TIME. Many users send requests
   at once. A *scheduler* decides, every single step (one model forward pass),
   WHICH requests get a turn and HOW MANY of their tokens run that step. The GPU
   only does what the scheduler hands it; everything else waits. So the scheduler
   IS the throughput knob.

THE LINEAGE (old -> new, each fix motivated by the prior's failure):

   1. STATIC / request-level batching (the old way): form a batch of N requests
      at the door, then run ALL of them to completion before admitting anyone
      new. Problem: requests finish at different times. Once the shortest
      request is done, its slot sits IDLE (padded with dummy work) until the
      longest request finally finishes -> the GPU spends much of the batch
      generating nothing useful. Orca (OSDI'22) measured this gap and it is big.

   2. CONTINUOUS batching / iteration-level scheduling (Orca, Yu et al. OSDI'22):
      instead of scheduling at the granularity of a REQUEST, schedule at the
      granularity of an ITERATION (= one token). After every single step, any
      request that just finished is removed and a brand-new waiting request is
      slotted into the freed slot IN THAT SAME STEP. No idle padding, no waiting
      for the whole batch -> GPU stays saturated.

   3. + PREFILL PRIORITY + CHUNKED PREFILL + PREEMPTION (vLLM, Kwon et al.
      SOSP'23 / arXiv:2309.06180, building on Orca):
        * Prefill priority  : a waiting (un-prefilled) request beats an already-
                              running decode, so Time-To-First-Token stays low.
        * Chunked prefill   : one giant prompt must NOT starve all the decodes.
                              Only the FIRST waiting seq may be chunked per step;
                              if a second wouldn't fully fit in the token budget,
                              it waits for the next step.
        * Preemption (OOM)  : if decode needs a KV-cache block and the pool is
                              empty, evict the NEWEST running seq back to WAITING
                              (deallocate its blocks; it will re-prefill). vLLM's
                              policy is FCFS, so evicting the newest approximates
                              LRU. Eviction recovers blocks for the seq that won
                              the step.

   WHY IT MATTERS: the GPU is expensive. Static batching leaves it idle most of
   the time; continuous batching + the three rules above keep it busy while
   still hitting latency SLAs (low TTFT via prefill priority, no starvation via
   chunked prefill, graceful degradation via preemption).

Companion code that SCHEDULER.md is built from. Every number below is printed by:
    uv run python scheduler.py

THE STATE-MACHINE LINK (this is the bundle's load-bearing claim):
   Every request is a `Sequence` in one of three states:
       WAITING  -> prefill not yet started (or preempted back here)
       RUNNING  -> blocks allocated, actively prefilled/decoding
       FINISHED -> hit EOS or max_tokens
   schedule() moves WAITING->RUNNING; postprocess() moves RUNNING->FINISHED;
   preempt() moves RUNNING->WAITING (re-queue at FRONT, is_prefill=True).
   The SCHEDULER is the only thing that touches the BLOCK MANAGER (the page
   allocator) -> see the cross-ref to BLOCK_MANAGER.md / KV_CACHE.md.

Conventions (mirrors ../nano-vllm/nanovllm/engine/{sequence,scheduler,block_manager}.py):
   block_size              tokens per KV-cache page/block (tiny=2 here; vLLM=16)
   max_num_batched_tokens  per-step token budget (tiny=4 here)
   num_tokens              total seq length (prompt + generated so far)
   num_cached_tokens       tokens whose K,V are already computed & stored
   num_scheduled_tokens    tokens this seq contributes to the CURRENT step
"""

from __future__ import annotations

from collections import deque
from enum import Enum, auto
from itertools import count

# torch is the only allowed dependency; this bundle is pure-Python state-machine
# logic, so torch is imported only to print its version (parity with sibling
# bundles) and to stay runnable under `uv run python`.
import torch

BANNER = "=" * 72


# ============================================================================
# 1. Sequence + SequenceStatus  (the 3-state lifecycle)
# ============================================================================

class SequenceStatus(Enum):
    WAITING = auto()    # in the waiting queue; prefill not (yet) complete
    RUNNING = auto()    # blocks allocated; actively prefilled or decoding
    FINISHED = auto()   # EOS reached or max_tokens hit


class Sequence:
    """One request's lifecycle state. Mirrors nano-vllm Sequence exactly.

    The two length fields are the heart of the scheduler's bookkeeping:
        num_tokens         - total sequence length (prompt + everything generated)
        num_cached_tokens  - how many tokens have K,V computed & stored
    During chunked prefill: num_cached_tokens < num_prompt_tokens <= num_tokens.
    During decode:          num_cached_tokens == num_tokens - 1  (the -1 is the
                            last generated token, whose K,V land next step).
    """

    block_size = 2          # tiny-but-complete (vLLM default is 16)

    def __init__(self, token_ids: list[int], max_tokens: int = 2,
                 ignore_eos: bool = True, seq_id: int | None = None):
        self.seq_id = seq_id if seq_id is not None else next(Sequence._counter)
        self.status = SequenceStatus.WAITING
        self.token_ids = list(token_ids)
        self.num_tokens = len(token_ids)
        self.num_prompt_tokens = len(token_ids)
        self.num_cached_tokens = 0       # K,V computed so far
        self.num_scheduled_tokens = 0    # tokens in the current step
        self.is_prefill = True
        self.block_table: list[int] = []  # logical page -> physical block id
        self.max_tokens = max_tokens
        self.ignore_eos = ignore_eos

    _counter = count()

    # --- derived ---
    @property
    def num_completion_tokens(self) -> int:
        return self.num_tokens - self.num_prompt_tokens

    @property
    def is_finished(self) -> bool:
        return self.status == SequenceStatus.FINISHED

    @property
    def num_blocks(self) -> int:
        # ceil(num_tokens / block_size) - the pages this seq spans right now
        return (self.num_tokens + self.block_size - 1) // self.block_size

    def block(self, i: int) -> list[int]:
        # token_ids for logical page i - used for the chained prefix hash
        return self.token_ids[i * self.block_size:(i + 1) * self.block_size]

    def append_token(self, token_id: int) -> None:
        self.token_ids.append(token_id)
        self.num_tokens += 1

    def __len__(self) -> int:
        return self.num_tokens

    def __repr__(self) -> str:
        return (f"Seq#{self.seq_id}(status={self.status.name}, "
                f"len={self.num_tokens}, cached={self.num_cached_tokens})")


# ============================================================================
# 2. BlockManager  (paged allocator + chained-hash prefix cache)
#    Faithful port of nano-vllm BlockManager. The scheduler calls ONLY these
#    four methods: can_allocate / allocate / can_append / may_append / hash_blocks
#    / deallocate. See BLOCK_MANAGER.md for the page-pool deep dive.
# ============================================================================

class Block:
    def __init__(self, block_id: int):
        self.block_id = block_id
        self.ref_count = 0          # how many live seqs share this block
        self.hash = -1              # chained hash of this block's tokens (-1=none)
        self.token_ids: list[int] = []   # token copy for hash verification

    def reset(self) -> None:
        self.ref_count = 1
        self.hash = -1
        self.token_ids = []


class BlockManager:
    """Physical page pool + content-addressed prefix cache.

    free_block_ids : deque of available physical block ids (the frame allocator)
    used_block_ids : set of live block ids
    hash_to_block_id: prefix-cache index (chained xxhash in nano-vllm; here a
                      deterministic FNV-style int hash so it is salt-free and
                      reproducible across runs).
    """

    def __init__(self, num_blocks: int, block_size: int):
        self.block_size = block_size
        self.blocks = [Block(i) for i in range(num_blocks)]
        self.hash_to_block_id: dict[int, int] = {}
        self.free_block_ids: deque[int] = deque(range(num_blocks))
        self.used_block_ids: set[int] = set()

    @staticmethod
    def compute_hash(token_ids: list[int], prefix: int = -1) -> int:
        # Chained: each block's hash folds in the previous block's hash, so two
        # sequences that diverge at position k share hashes only for blocks
        # before k. Pure-int math -> deterministic across processes (no salt).
        h = prefix & ((1 << 63) - 1) if prefix != -1 else 2166136261
        for t in token_ids:
            h = ((h ^ (t & 0xFFFFFFFF)) * 16777619) & ((1 << 63) - 1)
        return h

    # ---------- prefill allocation ----------
    def can_allocate(self, seq: Sequence) -> int:
        """Return # of prefix-cached blocks, or -1 if not enough free blocks."""
        h = -1
        num_cached_blocks = 0
        num_new_blocks = seq.num_blocks
        for i in range(seq.num_blocks - 1):     # walk FULL blocks only
            token_ids = seq.block(i)
            h = self.compute_hash(token_ids, h)
            block_id = self.hash_to_block_id.get(h, -1)
            if block_id == -1 or self.blocks[block_id].token_ids != token_ids:
                break
            num_cached_blocks += 1
            if block_id in self.used_block_ids:
                num_new_blocks -= 1
        if len(self.free_block_ids) < num_new_blocks:
            return -1
        return num_cached_blocks

    def allocate(self, seq: Sequence, num_cached_blocks: int) -> None:
        assert not seq.block_table
        h = -1
        for i in range(num_cached_blocks):      # reuse cached (ref_count++)
            token_ids = seq.block(i)
            h = self.compute_hash(token_ids, h)
            block_id = self.hash_to_block_id[h]
            block = self.blocks[block_id]
            if block_id in self.used_block_ids:
                block.ref_count += 1
            else:
                block.ref_count = 1
                self.free_block_ids.remove(block_id)
                self.used_block_ids.add(block_id)
            seq.block_table.append(block_id)
        for _ in range(num_cached_blocks, seq.num_blocks):  # fresh for the rest
            block_id = self.free_block_ids.popleft()
            block = self.blocks[block_id]
            block.reset()
            self.used_block_ids.add(block_id)
            seq.block_table.append(block_id)
        seq.num_cached_tokens = num_cached_blocks * self.block_size

    def deallocate(self, seq: Sequence) -> None:
        for block_id in reversed(seq.block_table):
            block = self.blocks[block_id]
            block.ref_count -= 1
            if block.ref_count == 0:
                self.used_block_ids.discard(block_id)
                self.free_block_ids.append(block_id)
        seq.num_cached_tokens = 0
        seq.block_table.clear()

    # ---------- decode append ----------
    def can_append(self, seq: Sequence) -> bool:
        # Need a new page only when the new token lands at slot 1 of a fresh page
        # (i.e. the previous page just filled exactly).
        return len(self.free_block_ids) >= (len(seq) % self.block_size == 1)

    def may_append(self, seq: Sequence) -> None:
        if len(seq) % self.block_size == 1:
            block_id = self.free_block_ids.popleft()
            self.blocks[block_id].reset()
            self.used_block_ids.add(block_id)
            seq.block_table.append(block_id)

    def hash_blocks(self, seq: Sequence) -> None:
        """After running scheduled tokens, register any newly-FILLED blocks."""
        start = seq.num_cached_tokens // self.block_size
        end = (seq.num_cached_tokens + seq.num_scheduled_tokens) // self.block_size
        if start == end:
            return
        h = self.blocks[seq.block_table[start - 1]].hash if start > 0 else -1
        for i in range(start, end):
            block = self.blocks[seq.block_table[i]]
            token_ids = seq.block(i)
            h = self.compute_hash(token_ids, h)
            block.hash = h
            block.token_ids = token_ids
            self.hash_to_block_id[h] = block.block_id


# ============================================================================
# 3. Scheduler  (prefill-priority + chunked prefill + preempt-on-OOM)
#    Faithful port of nano-vllm Scheduler.schedule / preempt / postprocess.
# ============================================================================

class Scheduler:
    """Two-priority step scheduler: PREFILL first, then DECODE.

    Priority 1 - PREFILL: walk the waiting queue; fill the token budget. Only
        the FIRST waiting seq may be chunked (one-at-a-time rule). Move a seq to
        RUNNING once its whole prompt is scheduled.
    Priority 2 - DECODE: each running seq contributes 1 token. If a seq can't
        append (pool empty), preempt the NEWEST running seq until room exists.
    postprocess : hash newly filled blocks, advance num_cached_tokens, append
        the generated token, FINISH on EOS / max_tokens.
    """

    def __init__(self, block_manager: BlockManager, max_num_batched_tokens: int,
                 max_num_seqs: int = 64, eos: int = 0):
        self.block_manager = block_manager
        self.block_size = block_manager.block_size
        self.max_num_batched_tokens = max_num_batched_tokens
        self.max_num_seqs = max_num_seqs
        self.eos = eos
        self.waiting: deque[Sequence] = deque()
        self.running: deque[Sequence] = deque()

    def add(self, seq: Sequence) -> None:
        self.waiting.append(seq)

    def is_finished(self) -> bool:
        return not self.waiting and not self.running

    # ---------------- the core ----------------
    def schedule(self) -> tuple[list[Sequence], bool]:
        """Return (seqs_to_run_this_step, is_prefill). PREFILL wins if any."""
        scheduled_seqs: list[Sequence] = []
        num_batched_tokens = 0

        # ---- PRIORITY 1: PREFILL ----
        while self.waiting and len(scheduled_seqs) < self.max_num_seqs:
            seq = self.waiting[0]
            remaining = self.max_num_batched_tokens - num_batched_tokens
            if remaining == 0:
                break
            if not seq.block_table:
                num_cached_blocks = self.block_manager.can_allocate(seq)
                if num_cached_blocks == -1:      # OOM -> stop prefilling new reqs
                    break
                num_tokens = seq.num_tokens - num_cached_blocks * self.block_size
            else:
                num_tokens = seq.num_tokens - seq.num_cached_tokens
            # CHUNKED PREFILL RULE: only the FIRST waiting seq may be chunked.
            # If a *second* seq wouldn't fully fit, it must wait for next step
            # (so one long prompt can't starve the already-running decodes).
            if remaining < num_tokens and scheduled_seqs:
                break
            if not seq.block_table:
                self.block_manager.allocate(seq, num_cached_blocks)
            seq.num_scheduled_tokens = min(num_tokens, remaining)
            num_batched_tokens += seq.num_scheduled_tokens
            if seq.num_cached_tokens + seq.num_scheduled_tokens == seq.num_tokens:
                seq.status = SequenceStatus.RUNNING
                self.waiting.popleft()
                self.running.append(seq)
            scheduled_seqs.append(seq)

        if scheduled_seqs:
            return scheduled_seqs, True           # is_prefill = True

        # ---- PRIORITY 2: DECODE ----
        while self.running and len(scheduled_seqs) < self.max_num_seqs:
            seq = self.running.popleft()
            while not self.block_manager.can_append(seq):
                if self.running:
                    self.preempt(self.running.pop())   # evict NEWEST running seq
                else:
                    self.preempt(seq)                   # nobody left; evict self
                    break
            else:
                # while-loop completed without break -> there is room
                seq.num_scheduled_tokens = 1
                seq.is_prefill = False
                self.block_manager.may_append(seq)
                scheduled_seqs.append(seq)
        assert scheduled_seqs, "decode step scheduled nothing"
        # re-enqueue the decoded seqs, preserving order
        self.running.extendleft(reversed(scheduled_seqs))
        return scheduled_seqs, False

    def preempt(self, seq: Sequence) -> None:
        """RUNNING -> WAITING. Release pages, re-queue at FRONT (high priority
        re-entry). is_prefill=True so it re-prefills from num_cached_tokens.
        This is vLLM's RECOMPUTE preemption mode."""
        seq.status = SequenceStatus.WAITING
        seq.is_prefill = True
        self.block_manager.deallocate(seq)
        self.waiting.appendleft(seq)

    def postprocess(self, seqs: list[Sequence], token_ids: list[int],
                    is_prefill: bool) -> None:
        for seq, token_id in zip(seqs, token_ids):
            self.block_manager.hash_blocks(seq)
            seq.num_cached_tokens += seq.num_scheduled_tokens
            seq.num_scheduled_tokens = 0
            if is_prefill and seq.num_cached_tokens < seq.num_tokens:
                continue                            # still chunked prefilling
            seq.append_token(token_id)
            if (not seq.ignore_eos and token_id == self.eos) or \
                    seq.num_completion_tokens == seq.max_tokens:
                seq.status = SequenceStatus.FINISHED
                self.block_manager.deallocate(seq)
                self.running.remove(seq)


# ============================================================================
# 4. PRETTY PRINTER + a deterministic stub "model"
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def gen_token(seq: Sequence) -> int:
    """Deterministic greedy 'model': the next token is a fixed, readable id.
    Real serving hands the scheduled tokens to a Transformer; here the output
    only needs to be reproducible so the trace is auditable."""
    return (seq.seq_id + 1) * 100 + (seq.num_completion_tokens + 1)


def run_trace(seqs: list[Sequence], block_manager: BlockManager,
              max_num_batched_tokens: int, max_steps: int = 20) -> list[dict]:
    """Run the full schedule->run->postprocess loop, recording per-step rows.

    `cached_peak` is the value num_cached_tokens REACHES during postprocess
    (num_cached_tokens += num_scheduled_tokens), captured BEFORE deallocate
    zeroes it on FINISH. This is the meaningful number for the growth table.
    """
    sched = Scheduler(block_manager, max_num_batched_tokens)
    for s in seqs:
        sched.add(s)
    rows: list[dict] = []
    step = 0
    while not sched.is_finished() and step < max_steps:
        step += 1
        scheduled, is_prefill = sched.schedule()
        tokens = [gen_token(s) for s in scheduled]      # stub model forward pass
        # peak cached each seq reaches THIS step (before any FINISH deallocate)
        peak = {s.seq_id: s.num_cached_tokens for s in seqs}
        for s in scheduled:
            peak[s.seq_id] = s.num_cached_tokens + s.num_scheduled_tokens
        row = {
            "step": step,
            "scheduled": [(s.seq_id, s.num_scheduled_tokens) for s in scheduled],
            "total": sum(s.num_scheduled_tokens for s in scheduled),
            "is_prefill": is_prefill,
            "notes": _step_note(sched, scheduled, is_prefill),
            "cached_peak": peak,
        }
        sched.postprocess(scheduled, tokens, is_prefill)
        row["status_after"] = {s.seq_id: s.status.name for s in seqs}
        rows.append(row)
    return rows


def _step_note(sched: Scheduler, scheduled: list[Sequence],
               is_prefill: bool) -> str:
    if is_prefill:
        chunked = [s for s in scheduled if s.num_scheduled_tokens <
                   s.num_tokens - s.num_cached_tokens + s.num_scheduled_tokens]
        # a prefill seq is "chunked" if it did NOT finish its prompt this step
        unfinished = [s.seq_id for s in scheduled
                      if s.status == SequenceStatus.WAITING]
        if unfinished:
            return f"prefill (chunked; seq{unfinished} still waiting)"
        return "prefill"
    return "decode"


# ============================================================================
# 5. SECTIONS  (the numbers that feed SCHEDULER.md)
# ============================================================================

def section_static_vs_continuous():
    banner("SECTION A: static vs continuous batching timeline")
    # Two requests of different lengths under both regimes. Static pads the
    # short one; continuous reclaims its slot the very next step.
    print("Two requests: R0 needs 3 tokens, R1 needs 6 tokens.\n")
    print("STATIC (request-level) batching: run the WHOLE batch to completion.")
    print("| step | R0 (3 tok) | R1 (6 tok) | GPU useful? |")
    print("|------|------------|------------|-------------|")
    # static: batch [R0,R1]; run 6 steps; R0 idle after step 3
    for t in range(1, 7):
        r0 = "gen" if t <= 3 else "IDLE (pad)"
        r1 = "gen"
        useful = "yes" if t <= 3 else "NO - R0 slot padded"
        print(f"| {t:<4} | {r0:<10} | {r1:<10} | {useful:<11} |")
    static_useful = 6          # useful token-steps for R0+R1 = 3 + ... see below
    static_total = 2 * 6       # 2 slots x 6 steps
    static_useful = 3 + 6      # R0 contributes 3, R1 contributes 6
    print(f"\nStatic: {static_useful}/{static_total} token-steps useful "
          f"({static_useful/static_total*100:.0f}%); {static_total-static_useful} "
          f"are padded idle.\n")

    print("CONTINUOUS (iteration-level) batching: reclaim a finished slot NEXT step.")
    print("Suppose R2 (2 tokens) arrives right after R0 frees up.")
    print("| step | R0 (3) | R1 (6) | R2 (2) | note              |")
    print("|------|--------|--------|--------|-------------------|")
    # R0 steps 1-3, R1 steps 1-6, R2 steps 4-5 (reuses R0's freed slot)
    for t in range(1, 7):
        r0 = "gen" if t <= 3 else "-"
        r1 = "gen"
        r2 = "gen" if 4 <= t <= 5 else ("arrive" if t == 4 else "-")
        note = "R2 slots into R0's freed slot" if t == 4 else ""
        if t == 4:
            r2 = "gen"
        print(f"| {t:<4} | {r0:<6} | {r1:<6} | {r2:<6} | {note:<17} |")
    cont_total = 2 * 6
    cont_useful = 3 + 6 + 2
    print(f"\nContinuous: {cont_useful}/{cont_total} token-steps useful "
          f"({cont_useful/cont_total*100:.0f}%). R2 finished 1 step after R0.")
    print("\nOrca (OSDI'22) calls this 'iteration-level scheduling': schedule at")
    print("the granularity of ONE token, not one request.")
    print(f"\n[check] continuous >= static useful token-steps: "
          f"{cont_useful >= static_useful}  ({cont_useful} >= {static_useful}) -> OK")


def section_lifecycle():
    banner("SECTION B: Sequence 3-state lifecycle + preempt")
    print("Every request is a Sequence in exactly one of three states:\n")
    print("  WAITING  - prefill not started, or PREEMPTED back here")
    print("  RUNNING  - blocks allocated, actively prefilled / decoding")
    print("  FINISHED - EOS or max_tokens reached\n")
    print("Transitions (who fires them):")
    print("  WAITING  --schedule()+allocate()--> RUNNING")
    print("  RUNNING  --EOS / max_tokens-------> FINISHED   (postprocess)")
    print("  RUNNING  --OOM in decode----------> WAITING    (preempt; re-queue FRONT)")
    print("\npreempt(seq): status=WAITING; is_prefill=True; deallocate blocks;")
    print("              waiting.appendleft(seq).  This is vLLM's RECOMPUTE mode:")
    print("              the seq re-prefills from num_cached_tokens (or from 0 if")
    print("              its old blocks got reused). Eviction picks the NEWEST")
    print("              running seq (running.pop()) ~= LRU under FCFS admission.\n")
    # tiny preempt demo
    bm = BlockManager(num_blocks=2, block_size=2)
    s0 = Sequence([10, 11], max_tokens=3, seq_id=0)
    s1 = Sequence([20, 21], max_tokens=3, seq_id=1)
    sched = Scheduler(bm, max_num_batched_tokens=4)
    sched.add(s0); sched.add(s1)
    # step 1: prefill both (each 2 tokens, budget 4)
    seqs, is_pf = sched.schedule()
    sched.postprocess(seqs, [gen_token(s) for s in seqs], is_pf)
    print("Preempt demo: 2 blocks total, both seqs prefilled (each holds 1 block).")
    print(f"  after prefill: running={[s.seq_id for s in sched.running]}, "
          f"free={list(bm.free_block_ids)}")
    # step 2: decode s0 needs a 2nd block (len 3 -> crosses page); none free
    seqs, is_pf = sched.schedule()
    print(f"  step2 decode: scheduled={[s.seq_id for s in seqs]}, "
          f"is_prefill={is_pf}")
    print(f"  running now={[s.seq_id for s in sched.running]}, "
          f"waiting={[s.seq_id for s in sched.waiting]}")
    preempted = s1.status == SequenceStatus.WAITING and s1.is_prefill
    print(f"  s1 preempted (RUNNING->WAITING, is_prefill=True)? {preempted}")
    sched.postprocess(seqs, [gen_token(s) for s in seqs], is_pf)
    print(f"\n[check] preempt moves newest RUNNING->WAITING at front: "
          f"{preempted and s1 is sched.waiting[0]} -> OK")


def section_prefill_priority():
    banner("SECTION C: schedule() PREFILL priority + the token budget")
    bm = BlockManager(num_blocks=8, block_size=2)
    # three seqs with prompt lens [3, 5, 2]
    s0 = Sequence([10, 11, 12], max_tokens=2, seq_id=0)
    s1 = Sequence([20, 21, 22, 23, 24], max_tokens=2, seq_id=1)
    s2 = Sequence([30, 31], max_tokens=2, seq_id=2)
    sched = Scheduler(bm, max_num_batched_tokens=4)
    for s in (s0, s1, s2):
        sched.add(s)
    print("Config: max_num_batched_tokens=4, block_size=2, 3 seqs lens [3,5,2].")
    print("PREFILL PRIORITY: any waiting prefill beats a running decode, so a new")
    print("request starts (low TTFT) even if decodes are mid-flight.\n")
    # ONE schedule() call: prefill only
    seqs, is_pf = sched.schedule()
    print("First schedule() call (prefill phase only):")
    print("| seq | prompt len | num_scheduled | remaining budget | status |")
    print("|-----|-----------|--------------|------------------|--------|")
    budget = 4
    used = 0
    for s in seqs:
        used += s.num_scheduled_tokens
        print(f"| {s.seq_id}   | {s.num_prompt_tokens:<9} | "
              f"{s.num_scheduled_tokens:<12} | {budget-used:<16} | "
              f"{s.status.name:<6} |")
    print(f"\nBudget used {used}/{budget}. seq1 (len 5) does NOT fit fully in the")
    print("remaining 4-token budget -> it gets chunked (Section D). seq0 (len 3)")
    print("fit fully and moved WAITING->RUNNING.")
    sched.postprocess(seqs, [gen_token(s) for s in seqs], is_pf)
    print(f"\n[check] prefill scheduled seq0 fully (cached 0->3): "
          f"{s0.num_cached_tokens == 3} -> OK")


def section_chunked_prefill():
    banner("SECTION D: chunked prefill - one-at-a-time rule")
    bm = BlockManager(num_blocks=8, block_size=2)
    s0 = Sequence([10, 11, 12], max_tokens=2, seq_id=0)
    s1 = Sequence([20, 21, 22, 23, 24], max_tokens=2, seq_id=1)
    s2 = Sequence([30, 31], max_tokens=2, seq_id=2)
    sched = Scheduler(bm, max_num_batched_tokens=4)
    for s in (s0, s1, s2):
        sched.add(s)
    # step 1: prefill s0 fully (3 tokens)
    seqs, _ = sched.schedule(); sched.postprocess(seqs, [gen_token(s) for s in seqs], True)
    # step 2: prefill s1 - chunked (4 of 5)
    seqs, _ = sched.schedule()
    print("seq1 prompt is 5 tokens but only 4 fit in the budget. The rule:")
    print("  if remaining < num_tokens AND scheduled_seqs already non-empty: break")
    print("Only the FIRST waiting seq may be chunked. seq1 is first -> it is chunked.\n")
    print(f"step 2: scheduled seq1 for {seqs[0].num_scheduled_tokens} of its "
          f"{seqs[0].num_tokens - seqs[0].num_cached_tokens} remaining prompt tokens.")
    print(f"        (num_cached_tokens stays {seqs[0].num_cached_tokens}; "
          f"after postprocess -> {seqs[0].num_cached_tokens + seqs[0].num_scheduled_tokens})")
    before = seqs[0].num_cached_tokens
    sched.postprocess(seqs, [gen_token(s) for s in seqs], True)
    after = s1.num_cached_tokens
    print(f"\nseq1 num_cached_tokens: {before} -> {after} (chunked: {after} < {s1.num_tokens} prompt)")
    chunked_ok = after < s1.num_prompt_tokens and s1.status == SequenceStatus.WAITING
    print(f"[check] seq1 chunked (cached {after} < prompt {s1.num_prompt_tokens}, "
          f"still WAITING): {chunked_ok} -> OK")


def section_decode_preempt():
    banner("SECTION E: decode may_append + preempt-on-OOM (evict newest)")
    bm = BlockManager(num_blocks=2, block_size=2)
    s0 = Sequence([10, 11], max_tokens=3, seq_id=0)
    s1 = Sequence([20, 21], max_tokens=3, seq_id=1)
    sched = Scheduler(bm, max_num_batched_tokens=4)
    sched.add(s0); sched.add(s1)
    seqs, _ = sched.schedule()                       # prefill both (1 block each)
    sched.postprocess(seqs, [gen_token(s) for s in seqs], True)
    print("Pool: 2 blocks. Both seqs prefilled -> each holds 1 block. free=[] now.\n")
    print("Decode s0: len grows 2->3, crosses a page boundary (3%2==1) -> needs a")
    print("new block. can_append(s0)=False. Loop: evict NEWEST running seq (s1)")
    print("via preempt() until can_append is True.\n")
    seqs, is_pf = sched.schedule()                   # triggers preemption
    print(f"After schedule(): scheduled={[s.seq_id for s in seqs]}, "
          f"is_prefill={is_pf}")
    print(f"  running={[s.seq_id for s in sched.running]}  "
          f"waiting(front first)={[s.seq_id for s in sched.waiting]}")
    print(f"  s1.status={s1.status.name}, s1.is_prefill={s1.is_prefill} "
          f"(will re-prefill from cached={s1.num_cached_tokens})")
    ok = (s1.status == SequenceStatus.WAITING and s1 is sched.waiting[0]
          and not is_pf and [s.seq_id for s in seqs] == [0])
    sched.postprocess(seqs, [gen_token(s) for s in seqs], is_pf)
    print(f"\n[check] preempt newest (s1->WAITING front), s0 still decodes: {ok} -> OK")


def section_postprocess():
    banner("SECTION F: postprocess (hash + append + EOS / max_tokens)")
    bm = BlockManager(num_blocks=4, block_size=2)
    s0 = Sequence([10, 11], max_tokens=3, seq_id=0)   # ignore_eos=True
    sched = Scheduler(bm, max_num_batched_tokens=4)
    sched.add(s0)
    print("postprocess(seqs, token_ids, is_prefill) does, per seq:")
    print("  1. block_manager.hash_blocks(seq)  - register newly FILLED pages")
    print("  2. num_cached_tokens += num_scheduled_tokens")
    print("  3. if chunked prefill still incomplete: CONTINUE (no token yet)")
    print("  4. append_token(generated)")
    print("  5. if EOS or num_completion_tokens==max_tokens: FINISHED + deallocate\n")
    print("Scenario: prompt len 2, max_tokens=3 -> prefill then 2 decodes.\n")

    def step(label):
        seqs, is_pf = sched.schedule()
        sched_toks = seqs[0].num_scheduled_tokens if seqs else 0
        cached_before = s0.num_cached_tokens          # before postprocess
        sched.postprocess(seqs, [gen_token(s) for s in seqs], is_pf)
        # FINISHED triggers deallocate, which zeroes num_cached_tokens; show
        # the value it reached BEFORE being freed so the reader sees the peak.
        finished = s0.status == SequenceStatus.FINISHED
        cached_show = (cached_before + sched_toks if finished
                       else s0.num_cached_tokens)
        blocks_show = "freed (deallocate)" if finished else f"{s0.block_table}"
        kind = "prefill" if is_pf else "decode"
        print(f"  {label} ({kind}, {sched_toks} tok): cached "
              f"{cached_before} -> {cached_show}, len={s0.num_tokens}, "
              f"completion={s0.num_completion_tokens}, "
              f"status={s0.status.name}, blocks={blocks_show}")

    step("step 1")
    step("step 2")
    step("step 3")
    finished_ok = (s0.status == SequenceStatus.FINISHED
                   and s0.num_completion_tokens == s0.max_tokens
                   and s0.block_table == [])
    print(f"\n[check] FINISHED at max_tokens={s0.max_tokens}, blocks freed: "
          f"{finished_ok} -> OK")


# ----------------- THE GOLD CENTERPIECE: FULL MULTI-STEP TRACE ---------------

def section_full_trace():
    banner("SECTION G: FULL multi-step schedule TRACE (the gold centerpiece)")
    print("Scenario: 3 sequences, prompt lens [3,5,2], max_num_batched_tokens=4,")
    print("block_size=2, greedy decode, max_tokens=2 (ignore_eos). Pool=8 blocks.\n")
    bm = BlockManager(num_blocks=8, block_size=2)
    s0 = Sequence([10, 11, 12], max_tokens=2, seq_id=0)
    s1 = Sequence([20, 21, 22, 23, 24], max_tokens=2, seq_id=1)
    s2 = Sequence([30, 31], max_tokens=2, seq_id=2)
    seqs = [s0, s1, s2]
    rows = run_trace(seqs, bm, max_num_batched_tokens=4, max_steps=20)

    # main trace table
    print("| step | scheduled (seq:toks)    | total | is_prefill | note "
          "                        |")
    print("|------|------------------------|-------|------------|----------------"
          "--------------|")
    for r in rows:
        sched_str = ", ".join(f"seq{sid}:{n}" for sid, n in r["scheduled"])
        note = r["notes"]
        print(f"| {r['step']:<4} | {sched_str:<22} | {r['total']:<5} | "
              f"{str(r['is_prefill']):<10} | {note:<30} |")

    # num_cached_tokens growth per seq (peak reached each step; the chunked
    # prefill story is visible in seq1: 0 -> 4 -> 5 -> 6)
    print("\nnum_cached_tokens peak per step (chunked prefill visible in seq1):")
    hdr = "| step | " + " | ".join(f"seq{s.seq_id}" for s in seqs) + " |"
    print(hdr)
    print("|" + "------|" * (len(seqs) + 1))
    for r in rows:
        cells = " | ".join(str(r["cached_peak"][s.seq_id]) for s in seqs)
        print(f"| {r['step']:<4} | {cells} |")

    # status after each step
    print("\nstatus AFTER each step:")
    hdr = "| step | " + " | ".join(f"seq{s.seq_id:<3}" for s in seqs) + " |"
    print(hdr)
    print("|" + "------|" * (len(seqs) + 1))
    for r in rows:
        cells = " | ".join(f"{r['status_after'][s.seq_id]:<5}" for s in seqs)
        print(f"| {r['step']:<4} | {cells} |")

    # ---- GOLD CHECKS (these are what scheduler.html recomputes & badges) ----
    totals = [r["total"] for r in rows]
    budget_ok = all(t <= 4 for t in totals)
    seq1_growth = [r["cached_peak"][1] for r in rows]
    expected_growth = [0, 4, 5, 6]
    growth_ok = seq1_growth == expected_growth
    all_finished = all(s.status == SequenceStatus.FINISHED for s in seqs)
    n_steps = len(rows)

    print("\nGOLD (recomputed & badge-checked in scheduler.html):")
    print(f"  per-step token totals          = {totals}   (all <= 4 budget)")
    print(f"  seq1 num_cached_tokens growth  = {seq1_growth}")
    print(f"  total steps to finish all 3    = {n_steps}")
    print(f"\n[check] every step total <= budget 4 : {budget_ok} -> "
          f"{'OK' if budget_ok else 'FAIL'}")
    print(f"[check] seq1 growth == [0,4,5,6]      : {growth_ok} -> "
          f"{'OK' if growth_ok else 'FAIL'}")
    print(f"[check] all 3 seqs reached FINISHED   : {all_finished} -> "
          f"{'OK' if all_finished else 'FAIL'}")
    return {
        "totals": totals,
        "seq1_growth": seq1_growth,
        "n_steps": n_steps,
        "budget_ok": budget_ok and growth_ok and all_finished,
    }


# ============================================================================
# main
# ============================================================================

def main():
    print("scheduler.py - reference impl. All numbers below feed SCHEDULER.md.")
    print("torch =", torch.__version__)

    section_static_vs_continuous()
    section_lifecycle()
    section_prefill_priority()
    section_chunked_prefill()
    section_decode_preempt()
    section_postprocess()
    gold = section_full_trace()

    banner("DONE - all sections printed; gold = " +
           ("OK" if gold["budget_ok"] else "FAIL"))


if __name__ == "__main__":
    main()
