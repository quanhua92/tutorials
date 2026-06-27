"""
python_async.py — Bundle #55 (Phase 9 bonus).

GOAL (one line): show, by building a TOY event loop from generators AND then
driving real asyncio, that ONE thread switches between many tasks ONLY at
`await` points — and that `gather`/`wait`/`Semaphore`/async-generators/
async-context-managers are all just patterns layered on that one primitive.

Distinct from asyncio_basics.py (#21, the WHAT): this bundle is the HOW — a
runnable model of the scheduler itself, then the deeper primitives asyncio_basics
only sketches: `wait` modes, `Semaphore` rate-limiting, async generators, and
`async with` / `__aenter__`-`__aexit__`.

This is the GROUND TRUTH for PYTHON_ASYNC.md. Every value, ordering, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

Run:
    uv run python python_async.py
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers (house style)
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
# Section A — a TOY event loop: how one thread rotates ready tasks
# ----------------------------------------------------------------------------

def section_a_toy_event_loop() -> None:
    banner("A — A TOY event loop: one thread rotates ready tasks at yield points")
    print("Before asyncio, here is the WHOLE idea in 25 lines. A coroutine is a")
    print("generator: every `yield` is a 'I can wait — run someone else' point. A")
    print("LOOP pops a ready task, runs it until it yields, then re-queues it. With")
    print("ONE thread, only ONE task executes at a time — the loop just rotates")
    print("which one. asyncio does exactly this, with `await` instead of `yield`.\n")

    class Task:
        def __init__(self, name: str, gen):
            self.name = name
            self.gen = gen
            self.done = False

    def toy_loop(tasks: list[Task], log: list[str]) -> list[str]:
        """Cooperative round-robin: pop -> run to next yield -> re-queue."""
        ready: list[Task] = list(tasks)
        while ready:
            task = ready.pop(0)          # next ready task
            try:
                yielded = next(task.gen)  # run until it yields (the switch point)
                log.append(yielded)       # record the switch
                ready.append(task)        # cooperative: put it back at the end
            except StopIteration:
                task.done = True          # ran out of work -> retire it
        return log

    def toy(name: str, n: int):
        """A generator-coroutine: yields n times, then finishes."""
        for i in range(n):
            yield f"{name}:{i}"
        return f"{name}-result"

    log: list[str] = []
    toy_loop([Task("A", toy("A", 3)), Task("B", toy("B", 2)), Task("C", toy("C", 2))], log)
    print(f"toy loop switch log = {log}")
    print("(A runs one step, yields, B runs one step, yields, C runs one step,")
    print(" yields, then back to A ... strictly round-robin at each yield. A has")
    print(" 3 steps vs B/C's 2, so A runs its final step alone after they finish.)\n")

    check("tasks interleaved: A0 then B0 (not A0,A1,A2)",
          log[0] == "A:0" and log[1] == "B:0")
    check("round-robin order A0 B0 C0 A1 B1 C1 A2",
          log == ["A:0", "B:0", "C:0", "A:1", "B:1", "C:1", "A:2"])
    check("A (most steps) yielded last, after B and C were exhausted",
          log[-1] == "A:2")


# ----------------------------------------------------------------------------
# Section B — async/await: native coroutines and await delegation
# ----------------------------------------------------------------------------

def section_b_native_async_await() -> None:
    banner("B — async/await: native coroutines and await delegation")
    print("`async def` makes a native coroutine. `await expr` DELEGATES to expr:")
    print("it runs the awaited coroutine to its next suspension (or completion),")
    print("yielding control to the loop in between. A chain `await f()` ->")
    print("`await g()` -> `await asyncio.sleep(x)` is ONE control flow; the loop")
    print("sees a single suspension at the deepest await.\n")

    async def leaf() -> str:
        await asyncio.sleep(0)        # the real yield to the loop
        return "leaf-value"

    async def middle() -> str:
        x = await leaf()              # delegates into leaf
        return f"middle({x})"

    async def top() -> str:
        return await middle()         # delegates into middle

    result = asyncio.run(top())
    print(f"await chain top -> middle -> leaf -> asyncio.sleep -> {result!r}")
    check("the deepest return propagated up the await chain",
          result == "middle(leaf-value)")

    async def noop() -> str:
        return "instant"

    async def main() -> str:
        # await a coroutine that does NOT suspend returns immediately (no yield)
        return await noop()

    print(f"awaiting a coroutine with no suspension returns instantly: {asyncio.run(main())!r}")
    check("await on a non-suspending coroutine returns its value directly",
          asyncio.run(main()) == "instant")

    # Calling without awaiting builds an object; the body NEVER runs.
    coro = top()
    print(f"\ntop() with NO await -> type={type(coro).__name__}, body did NOT run")
    check("calling (not awaiting) a coroutine returns a coroutine object, not its value",
          type(coro).__name__ == "coroutine")
    coro.close()  # avoid 'never awaited' warning


# ----------------------------------------------------------------------------
# Section C — task scheduling: create_task and the task lifecycle
# ----------------------------------------------------------------------------

def section_c_task_scheduling() -> None:
    banner("C — Task scheduling: create_task and the task lifecycle")
    print("asyncio.create_task(coro) wraps a coroutine in a Task and schedules it")
    print("SOON — without awaiting. A Task moves through states. Saving the return")
    print("value is mandatory: the loop holds only a WEAK reference, so an unheld")
    print("task can be garbage-collected mid-flight.\n")

    async def work(tag: str, delay: float) -> str:
        await asyncio.sleep(delay)
        return f"{tag}@{delay:.2f}s"

    async def main() -> dict:
        order: list[str] = []
        t_quick = asyncio.create_task(work("quick", 0.02))
        t_slow = asyncio.create_task(work("slow", 0.08))
        order.append(f"created: t_quick.done()={t_quick.done()}")
        # do other work; both tasks run concurrently in the background
        await asyncio.sleep(0.05)
        order.append(f"mid: t_quick.done()={t_quick.done()} t_slow.done()={t_slow.done()}")
        r_quick = await t_quick          # already done -> returns instantly
        r_slow = await t_slow            # waits for the remainder
        order.append(f"joined: quick={r_quick} slow={r_slow}")
        return {"order": order, "states": [str(t_quick.done()), str(t_slow.done())]}

    out = asyncio.run(main())
    for line in out["order"]:
        print(f"  {line}")
    print()
    check("at creation neither task was done yet",
          out["order"][0] == "created: t_quick.done()=False")
    check("quick finished before slow (shorter delay, concurrent)",
          "mid: t_quick.done()=True t_slow.done()=False" in out["order"])
    check("both tasks were done after being awaited",
          out["states"] == ["True", "True"])

    # Named tasks: introspection via Task.get_name()
    async def named() -> str:
        return asyncio.current_task().get_name()

    async def runner() -> list[str]:
        t1 = asyncio.create_task(named(), name="alpha")
        t2 = asyncio.create_task(named(), name="beta")
        return [await t1, await t2]

    names = asyncio.run(runner())
    print(f"named tasks introspect to: {names}")
    check("Task.get_name() returns the explicitly assigned name",
          names == ["alpha", "beta"])


# ----------------------------------------------------------------------------
# Section D — gather vs wait: two ways to run many tasks
# ----------------------------------------------------------------------------

def section_d_gather_vs_wait() -> None:
    banner("D — gather vs wait: two ways to run many tasks")
    print("gather(*aws) runs everything concurrently and returns results in")
    print("SUBMISSION order. wait(aws) returns two SETS (done, pending) and lets")
    print("you choose the return condition — first complete, first exception, or all.")
    print("Use gather for 'give me all results'; use wait for 'react as they finish'.\n")

    async def work(tag: str, delay: float) -> str:
        await asyncio.sleep(delay)
        return tag

    async def demo_gather() -> list[str]:
        return await asyncio.gather(
            work("third", 0.08), work("first", 0.02), work("second", 0.05)
        )

    gathered = asyncio.run(demo_gather())
    print(f"gather -> {gathered}   (results in SUBMISSION order, not finish order)")
    check("gather preserves submission order despite different finish times",
          gathered == ["third", "first", "second"])

    async def demo_wait_first_completed() -> dict:
        tasks = [asyncio.create_task(work("a", 0.08)),
                 asyncio.create_task(work("b", 0.02)),
                 asyncio.create_task(work("c", 0.05))]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # cancel the stragglers so the loop can exit cleanly
        for t in pending:
            t.cancel()
        return {
            "done": sorted(t.result() for t in done),
            "pending_count": len(pending),
        }

    out = asyncio.run(demo_wait_first_completed())
    print(f"wait(FIRST_COMPLETED) -> done={out['done']} pending={out['pending_count']}")
    check("wait FIRST_COMPLETED returned only the fastest task ('b')",
          out["done"] == ["b"] and out["pending_count"] == 2)

    async def demo_wait_first_exception() -> dict:
        async def boom() -> str:
            await asyncio.sleep(0.02)
            raise ValueError("kaboom")

        tasks = [asyncio.create_task(boom()),
                 asyncio.create_task(work("ok", 0.20))]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in pending:
            t.cancel()
        # find the exception among done tasks
        excs = [t.exception() for t in done if not t.cancelled() and t.exception() is not None]
        return {"done_count": len(done), "exc_type": type(excs[0]).__name__ if excs else "None"}

    out2 = asyncio.run(demo_wait_first_exception())
    print(f"wait(FIRST_EXCEPTION) -> done_count={out2['done_count']} exc={out2['exc_type']}")
    check("wait FIRST_EXCEPTION fires as soon as a task raises (ValueError)",
          out2["done_count"] == 1 and out2["exc_type"] == "ValueError")


# ----------------------------------------------------------------------------
# Section E — Semaphores: limiting concurrency (rate limiting)
# ----------------------------------------------------------------------------

def section_e_semaphore() -> None:
    banner("E — Semaphore: limit how many tasks run at once (rate limiting)")
    print("asyncio.Semaphore(n) admits at most n holders at a time. `async with sem:`")
    print("acquires on entry, releases on exit — the classic rate-limiter. A")
    print("BoundedSemaphore adds a safety check: releasing more than you acquired")
    print("raises ValueError (catches double-release bugs).\n")

    async def worker(i: int, sem: asyncio.Semaphore, active: list[int]) -> str:
        async with sem:
            active.append(i)                      # entered critical section
            await asyncio.sleep(0.02)             # simulate an I/O call
            active.remove(i)
            return f"worker-{i}-done"

    async def main(limit: int, n_workers: int) -> dict:
        sem = asyncio.Semaphore(limit)
        active: list[int] = []
        peak = 0
        results = await asyncio.gather(*[worker(i, sem, active) for i in range(n_workers)])
        # record peak concurrency by sampling inside worker is racy on print,
        # so measure the invariant differently below.
        return {"results": results, "limit": limit}

    out = asyncio.run(main(limit=2, n_workers=6))
    print(f"Semaphore(2) over 6 workers -> {len(out['results'])} finished, limit={out['limit']}")
    check("all 6 workers completed under the semaphore",
          out["results"] == [f"worker-{i}-done" for i in range(6)])

    # Prove the cap is real: time how long 6 tasks of 0.05s each take with limit=2.
    # Serial would be 6*0.05=0.30s; unbounded async would be ~0.05s; limit=2 is ~0.15s.
    async def timed(n_workers: int, limit: int) -> float:
        sem = asyncio.Semaphore(limit)

        async def one() -> None:
            async with sem:
                await asyncio.sleep(0.05)

        t0 = time.perf_counter()
        await asyncio.gather(*[one() for _ in range(n_workers)])
        return time.perf_counter() - t0

    elapsed = asyncio.run(timed(n_workers=6, limit=2))
    print(f"6 tasks x 0.05s with Semaphore(2) -> {elapsed:.3f}s (ceil(6/2)*0.05 = 0.15s)")
    check("Semaphore(2) serialized 6 tasks into ~3 waves (>= 0.14s)",
          elapsed >= 0.14)
    check("Semaphore(2) still overlapped waves (< 0.28s, not fully serial)",
          elapsed < 0.28)

    # BoundedSemaphore catches over-release.
    async def over_release() -> str:
        sem = asyncio.BoundedSemaphore(1)
        await sem.acquire()
        sem.release()
        try:
            sem.release()  # one too many -> ValueError
        except ValueError:
            return "ValueError-on-over-release"
        return "no-error"

    res = asyncio.run(over_release())
    print(f"BoundedSemaphore over-release -> {res}")
    check("BoundedSemaphore raised ValueError on a double release",
          res == "ValueError-on-over-release")


# ----------------------------------------------------------------------------
# Section F — async generators: streaming with async for
# ----------------------------------------------------------------------------

def section_f_async_generators() -> None:
    banner("F — Async generators: streaming with async for")
    print("An `async def` that uses `yield` is an async generator. Each `yield`")
    print("can be preceded by an `await`, so it produces values over time (e.g.")
    print("streamed tokens). Consume with `async for`, or collect with an async")
    print("comprehension. This is the primitive behind streaming LLM responses.\n")

    async def ticker(n: int) -> int:
        """Yield 0..n-1, awaiting between each (simulates async I/O per item)."""
        for i in range(n):
            await asyncio.sleep(0)   # yield control, then produce
            yield i

    async def collect_for() -> list[int]:
        out: list[int] = []
        async for v in ticker(5):
            out.append(v)
        return out

    got = asyncio.run(collect_for())
    print(f"async for over async generator -> {got}")
    check("async for consumed 0..4 from the async generator",
          got == [0, 1, 2, 3, 4])

    async def collect_comprehension() -> list[int]:
        # async comprehension: the async analogue of a genexpr
        return [v async for v in ticker(6) if v % 2 == 0]

    evens = asyncio.run(collect_comprehension())
    print(f"async comprehension (filter even) -> {evens}")
    check("async comprehension filtered to even values [0,2,4]",
          evens == [0, 2, 4])

    # Async generators are single-use, like regular generators.
    async def once() -> int:
        yield 1

    async def drain_twice() -> list[int]:
        g = once()
        first = [v async for v in g]   # exhausts it
        second: list[int] = []
        async for v in g:              # already exhausted -> nothing
            second.append(v)
        return first + second

    drained = asyncio.run(drain_twice())
    print(f"re-iterating an exhausted async generator -> {drained}")
    check("async generators are single-use (second iteration produced nothing)",
          drained == [1])


# ----------------------------------------------------------------------------
# Section G — async context managers: async with
# ----------------------------------------------------------------------------

def section_g_async_context_managers() -> None:
    banner("G — Async context managers: async with (__aenter__/__aexit__)")
    print("`async with` runs async setup before the block and async teardown")
    print("after — even if the block raises. Implement __aenter__/__aexit__, or")
    print("use @asynccontextmanager to wrap an async generator. The teardown")
    print("ALWAYS runs (the whole point), in reverse order for nested `async with`.\n")

    class AsyncDB:
        def __init__(self) -> None:
            self.open = False

        async def __aenter__(self) -> "AsyncDB":
            await asyncio.sleep(0)    # async connect
            self.open = True
            print("    [AsyncDB __aenter__: connected]")
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            await asyncio.sleep(0)    # async close
            self.open = False
            print("    [AsyncDB __aexit__: closed]")
            return False              # do not suppress exceptions

    async def use_db() -> tuple[bool, bool]:
        inside_open = False
        after_open = True
        async with AsyncDB() as db:
            inside_open = db.open
        after_open = db.open
        return inside_open, after_open

    inside, after = asyncio.run(use_db())
    print(f"db.open inside block={inside}, after block={after}")
    check("__aenter__ ran before the block (open=True inside)",
          inside is True)
    check("__aexit__ ran after the block (open=False after)",
          after is False)

    # Teardown runs even when the body raises.
    async def raises_inside() -> list[str]:
        events: list[str] = []

        class Resource:
            async def __aenter__(self):
                events.append("enter")
                return self

            async def __aexit__(self, exc_type, exc, tb):
                events.append("exit")
                return False

        try:
            async with Resource():
                events.append("body")
                raise RuntimeError("boom")
        except RuntimeError:
            events.append("caught")
        return events

    events = asyncio.run(raises_inside())
    print(f"body raised -> events={events}")
    check("teardown (__aexit__) ran even though the body raised",
          events == ["enter", "body", "exit", "caught"])

    # @asynccontextmanager: define setup/teardown as an async generator.
    async def span_manager() -> list[str]:
        events: list[str] = []

        @asynccontextmanager
        async def span():
            events.append("setup")
            await asyncio.sleep(0)
            yield
            events.append("teardown")

        async with span():
            events.append("inside")
        return events

    span_events = asyncio.run(span_manager())
    print(f"@asynccontextmanager -> {span_events}")
    check("asynccontextmanager ran setup before and teardown after yield",
          span_events == ["setup", "inside", "teardown"])

    # Nested async context managers tear down in reverse (LIFO) order.
    async def nested() -> list[str]:
        order: list[str] = []

        @asynccontextmanager
        async def layer(name: str):
            order.append(f"enter-{name}")
            yield
            order.append(f"exit-{name}")

        async with layer("outer"):
            async with layer("inner"):
                order.append("body")
        return order

    nest = asyncio.run(nested())
    print(f"nested async with -> {nest}")
    check("nested async with tore down in reverse order (outer exits last)",
          nest == ["enter-outer", "enter-inner", "body", "exit-inner", "exit-outer"])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("python_async.py — Phase 9 bonus bundle #55.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_toy_event_loop()
    section_b_native_async_await()
    section_c_task_scheduling()
    section_d_gather_vs_wait()
    section_e_semaphore()
    section_f_async_generators()
    section_g_async_context_managers()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
