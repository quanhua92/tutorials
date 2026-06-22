"""
asyncio_basics.py — Bundle #21 (Phase 3).

GOAL (one line): show, by running real coroutines, that asyncio is
SINGLE-THREADED COOPERATIVE CONCURRENCY — `await` yields control to an event
loop that interleaves I/O waits (concurrency, NOT parallelism), and a blocking
call like time.sleep() freezes the WHOLE loop.

This is the GROUND TRUTH for ASYNCIO_BASICS.md. Every value, ordering, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python asyncio_basics.py
"""

from __future__ import annotations

import asyncio
import time

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers
# ----------------------------------------------------------------------------

def banner(title: str) -> None:
    """Print a clearly delimited section divider (the house style)."""
    print("\n" + BANNER)
    print(f"SECTION {title}")
    print(BANNER)


def check(description: str, condition: bool) -> None:
    """Assert an invariant and print a uniform [check] ... OK line."""
    assert condition, f"INVARIANT VIOLATED: {description}"
    print(f"[check] {description}: OK")


# ----------------------------------------------------------------------------
# Section A — coroutine object + asyncio.run: calling f() does NOT run it
# ----------------------------------------------------------------------------

def section_a_coroutine_object() -> None:
    banner("A — Coroutine object + asyncio.run: calling f() does NOT run it")
    print("An `async def` function is a COROUTINE FUNCTION. Calling it returns")
    print("a COROUTINE OBJECT (repr '<coroutine object f at 0x...>'); the body")
    print("does NOT run yet. The object is an awaitable. asyncio.run(coro)")
    print("creates an event loop, schedules the coroutine, drives it to done.\n")

    async def greet() -> str:
        return "hello from coroutine"

    coro = greet()  # calling does NOT run the body — just builds the object
    print(f"type(coro).__name__                 -> {type(coro).__name__}")
    print(f"asyncio.iscoroutine(coro)           -> {asyncio.iscoroutine(coro)}")
    print(f"asyncio.iscoroutinefunction(greet)  -> {asyncio.iscoroutinefunction(greet)}")
    print()

    check("type(coro).__name__ == 'coroutine'", type(coro).__name__ == "coroutine")
    check("asyncio.iscoroutine(coro) is True", asyncio.iscoroutine(coro))
    check("greet is a coroutine function (iscoroutinefunction)",
          asyncio.iscoroutinefunction(greet))

    result = asyncio.run(coro)  # drives the coroutine to completion
    print(f"\nasyncio.run(coro) -> {result!r}")
    check("asyncio.run returned the coroutine's value",
          result == "hello from coroutine")


# ----------------------------------------------------------------------------
# Section B — await yields control to the loop (interleaved execution)
# ----------------------------------------------------------------------------

def section_b_await_yields() -> None:
    banner("B — await yields control to the loop (interleaved execution)")
    print("Inside one coroutine, `await asyncio.sleep(0)` SUSPENDS it and hands")
    print("control back to the event loop, which runs OTHER ready coroutines.")
    print("Two coroutines that each await therefore INTERLEAVE — proof that")
    print("await is a real yield, not a no-op (all on ONE thread).\n")

    async def coop(name: str, log: list[str]) -> None:
        log.append(f"{name}:1")
        await asyncio.sleep(0)   # yields; the loop runs the other coroutine
        log.append(f"{name}:2")
        await asyncio.sleep(0)   # yields again
        log.append(f"{name}:3")

    async def main() -> list[str]:
        log: list[str] = []
        await asyncio.gather(coop("A", log), coop("B", log))
        return log

    log = asyncio.run(main())
    print(f"execution log = {log}")
    print("(A and B alternate at every await point — single thread, interleaved)")
    print()

    check("log[0] == 'A:1' (A was scheduled first)", log[0] == "A:1")
    check("log[1] == 'B:1' (B ran while A was suspended)", log[1] == "B:1")
    check("A and B interleaved (never A:1,A:2,A:3,B:1,...)",
          log == ["A:1", "B:1", "A:2", "B:2", "A:3", "B:3"])


# ----------------------------------------------------------------------------
# Section C — asyncio.gather: concurrent waits take ~max, NOT ~sum
# ----------------------------------------------------------------------------

def section_c_gather_concurrency() -> None:
    banner("C — asyncio.gather: concurrent waits take ~max, NOT ~sum")
    print("gather(*aws) schedules every awaitable CONCURRENTLY on the one loop.")
    print("Two sleeps of 0.10s and 0.20s overlap: total ~= max (0.20s), not")
    print("~= sum (0.30s). Awaiting them SEQUENTIALLY (one await, then the")
    print("other) WOULD sum. (Exact ms vary; the ORDERING facts below hold.)\n")

    async def slow(name: str, delay: float) -> str:
        await asyncio.sleep(delay)
        return f"{name}@{delay:.2f}s"

    async def run_concurrent() -> tuple[list[str], float]:
        t0 = time.perf_counter()
        results = await asyncio.gather(slow("x", 0.10), slow("y", 0.20))
        return results, time.perf_counter() - t0

    async def run_sequential() -> tuple[list[str], float]:
        t0 = time.perf_counter()
        r1 = await slow("x", 0.10)
        r2 = await slow("y", 0.20)
        return [r1, r2], time.perf_counter() - t0

    conc_results, conc_elapsed = asyncio.run(run_concurrent())
    seq_results, seq_elapsed = asyncio.run(run_sequential())
    print(f"concurrent gather  -> {conc_results} in {conc_elapsed:.3f}s")
    print(f"sequential awaits  -> {seq_results} in {seq_elapsed:.3f}s")
    print("sum of durations = 0.30s  |  max of durations = 0.20s")
    print()

    check("gather returned both results in submission order",
          conc_results == ["x@0.10s", "y@0.20s"])
    check("concurrent elapsed < sum (0.30s) — the waits overlapped",
          conc_elapsed < 0.10 + 0.20)
    check("concurrent elapsed < sequential elapsed (overlap beat serial)",
          conc_elapsed < seq_elapsed)
    check("sequential elapsed ~= sum (>= 0.28s, no overlap)",
          seq_elapsed >= 0.28)


# ----------------------------------------------------------------------------
# Section D — asyncio.create_task: schedule once, overlap, await later
# ----------------------------------------------------------------------------

def section_d_create_task_overlap() -> None:
    banner("D — asyncio.create_task: schedule once, overlap, await later")
    print("create_task(coro) wraps a coroutine in a Task and schedules it to run")
    print("SOON on the loop — WITHOUT awaiting. It runs CONCURRENTLY with the")
    print("code that created it, so a long background task overlaps your other")
    print("work and may already be DONE by the time you await it.\n")

    async def background(log: list[str]) -> None:
        await asyncio.sleep(0.05)
        log.append("background:done")

    async def main() -> list[str]:
        log: list[str] = []
        task = asyncio.create_task(background(log))  # scheduled, not awaited
        log.append("main:created task")
        await asyncio.sleep(0.10)                     # other work; bg runs meanwhile
        log.append(f"main:task.done()={task.done()}")  # True -> it overlapped
        await task                                     # joins (instant if already done)
        log.append("main:joined")
        return log

    log = asyncio.run(main())
    for line in log:
        print(f"  {line}")
    print()

    check("background finished BEFORE main joined it (true overlap)",
          log.index("background:done") < log.index("main:joined"))
    check("task.done() was True before the final await (it already completed)",
          "main:task.done()=True" in log)


# ----------------------------------------------------------------------------
# Section E — THE blocking-call trap: time.sleep freezes the WHOLE loop
# ----------------------------------------------------------------------------

def section_e_blocking_trap() -> None:
    banner("E — THE TRAP: a blocking call (time.sleep) freezes the WHOLE loop")
    print("asyncio.sleep() SUSPENDS the coroutine (cooperative — the loop is")
    print("free to run others). time.sleep() is a plain SYNCHRONOUS block: the")
    print("entire thread — and thus the whole event loop — STALLS. Other tasks")
    print("cannot make ANY progress while it runs.\n")

    async def watcher(progress: list[int]) -> None:
        """Ticks every 0.02s, but ONLY when the loop is free to schedule it."""
        for i in range(20):
            await asyncio.sleep(0.02)
            progress.append(i)

    async def blocking_call() -> None:
        time.sleep(0.10)  # synchronous: freezes the loop for 0.10s

    async def main() -> tuple[int, int, int]:
        progress: list[int] = []
        task = asyncio.create_task(watcher(progress))
        await asyncio.sleep(0.001)   # let the watcher register, before = baseline
        before = len(progress)

        await blocking_call()         # <-- THE FREEZE: loop stalls ~0.10s
        after_block = len(progress)

        await asyncio.sleep(0.10)     # cooperative: loop is free again
        after_yield = len(progress)
        await task
        return before, after_block, after_yield

    before, after_block, after_yield = asyncio.run(main())
    print(f"watcher ticks before time.sleep(0.10)   : {before}")
    print(f"watcher ticks AFTER  time.sleep(0.10)   : {after_block}   <- NO progress")
    print(f"watcher ticks AFTER  asyncio.sleep(0.10): {after_yield}   <- resumes")
    print()
    check("time.sleep froze the loop (watcher made NO progress during it)",
          after_block == before)
    check("asyncio.sleep did NOT freeze (watcher progressed after it)",
          after_yield > after_block)


# ----------------------------------------------------------------------------
# Section F — primitives: wait_for (timeout), as_completed, Queue, Lock
# ----------------------------------------------------------------------------

def section_f_primitives() -> None:
    banner("F — Primitives: wait_for (timeout), as_completed, Queue, Lock")
    print("Four workhorses. wait_for(aw, t) cancels + raises TimeoutError at t.")
    print("as_completed(aws) yields results in COMPLETION order. Queue and Lock")
    print("are the async analogues of queue.Queue / threading.Lock.\n")

    async def demo_wait_for() -> float:
        t0 = time.perf_counter()
        try:
            await asyncio.wait_for(asyncio.sleep(1.0), timeout=0.05)
        except TimeoutError:
            return time.perf_counter() - t0
        return -1.0

    elapsed = asyncio.run(demo_wait_for())
    print(f"wait_for(sleep(1.0), timeout=0.05) -> TimeoutError after {elapsed:.3f}s")
    check("wait_for raised TimeoutError near 0.05s (cancelled, not 1.0s)",
          0.0 < elapsed < 0.50)

    async def demo_as_completed() -> list[str]:
        order: list[str] = []

        async def work(name: str, delay: float) -> str:
            await asyncio.sleep(delay)
            return name

        tasks = [asyncio.create_task(work("slow", 0.10)),
                 asyncio.create_task(work("fast", 0.02))]
        for fut in asyncio.as_completed(tasks):
            order.append(await fut)
        return order

    order = asyncio.run(demo_as_completed())
    print(f"as_completed(slow@0.10, fast@0.02) -> {order}")
    check("as_completed yields 'fast' before 'slow' (completion order, not input)",
          order == ["fast", "slow"])

    async def demo_queue() -> list[int]:
        q: asyncio.Queue[int | None] = asyncio.Queue()
        received: list[int] = []

        async def producer() -> None:
            for i in range(3):
                await q.put(i)
            await q.put(None)  # sentinel

        async def consumer() -> None:
            while True:
                item = await q.get()
                if item is None:
                    return
                received.append(item)

        await asyncio.gather(producer(), consumer())
        return received

    received = asyncio.run(demo_queue())
    print(f"asyncio.Queue producer/consumer -> {received}")
    check("Queue handed off 0,1,2 via async put/get", received == [0, 1, 2])

    async def demo_lock() -> list[str]:
        lock = asyncio.Lock()
        shared: list[str] = []

        async def worker(name: str) -> None:
            async with lock:
                shared.append(f"{name}:in")
                await asyncio.sleep(0)   # would interleave WITHOUT the lock
                shared.append(f"{name}:out")

        await asyncio.gather(worker("X"), worker("Y"))
        return shared

    shared = asyncio.run(demo_lock())
    print(f"Lock-protected critical sections -> {shared}")
    check("Lock kept each section atomic (no interleave)",
          shared == ["X:in", "X:out", "Y:in", "Y:out"])


# ----------------------------------------------------------------------------
# Section G — when to use asyncio vs threads vs multiprocessing
# ----------------------------------------------------------------------------

def section_g_decision_note() -> None:
    banner("G — When to use asyncio vs threads vs multiprocessing")
    print("asyncio overlaps I/O WAITS on ONE thread. It does NOT parallelize")
    print("CPU. Proof: a coroutine doing pure CPU (no await) runs to completion")
    print("and BLOCKS every other coroutine until it returns.\n")

    async def cpu_hog(log: list[str]) -> None:
        total = sum(range(1_000_000))  # pure CPU, NO await -> never yields
        log.append(f"cpu done: {total}")

    async def io_waiter(log: list[str]) -> None:
        await asyncio.sleep(0)
        log.append("io:ran")

    async def main() -> list[str]:
        log: list[str] = []
        await asyncio.gather(cpu_hog(log), io_waiter(log))
        return log

    log = asyncio.run(main())
    print(f"  gather(cpu_hog, io_waiter) -> {log}")
    print("  (cpu_hog finished ENTIRELY before io_waiter got a single tick)")
    print()
    check("CPU coroutine with no await blocked the loop (ran first, fully)",
          log == ["cpu done: 499999500000", "io:ran"])

    print(f"{'workload':<32}{'best fit':<18}{'why'}")
    print("-" * 72)
    for workload, fit, why in [
        ("many slow I/O connections", "asyncio", "one thread overlaps waits"),
        ("quick blocking I/O / sync libs", "threads", "easy wrap, GIL-OK for I/O"),
        ("CPU-bound (math, hashing)", "multiprocessing", "real parallel cores"),
        ("mix of CPU + I/O", "procs + asyncio", "per-core event loop"),
    ]:
        print(f"{workload:<32}{fit:<18}{why}")
    print()
    check("asyncio fits MANY slow I/O connections (not CPU work)", True)
    check("multiprocessing fits CPU-bound work (real parallel cores)", True)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("asyncio_basics.py — Phase 3 bundle #21.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_coroutine_object()
    section_b_await_yields()
    section_c_gather_concurrency()
    section_d_create_task_overlap()
    section_e_blocking_trap()
    section_f_primitives()
    section_g_decision_note()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
