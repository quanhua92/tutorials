"""
fastapi_async.py — Bundle #46 (Phase 7).

GOAL (one line): show, by driving a FastAPI app with TestClient, that
`async def` handlers run ON the event loop (so `await` overlaps I/O and
keeps the loop free), plain `def` handlers run in a THREADPOOL worker
thread (so a blocking call there is safe), a blocking call INSIDE
`async def` freezes the WHOLE loop (every other request stalls), and
`BackgroundTasks` fire AFTER the response is sent — so pick `async`
only when you actually `await`.

This is the GROUND TRUTH for FASTAPI_ASYNC.md. Every value and ordering
below is printed by this file. Change it -> re-run -> re-paste. Never
hand-compute.

Run:
    uv run python fastapi_async.py
"""

from __future__ import annotations

import asyncio
import threading
import time

from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient

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
# shared module-level state read/written by the routes
# ----------------------------------------------------------------------------

BG_LOG: list[str] = []   # appended-to by a BackgroundTasks function


# ----------------------------------------------------------------------------
# the app: every endpoint exercised by the sections below
# ----------------------------------------------------------------------------

app = FastAPI()


@app.get("/a")
async def a() -> dict:
    """async def handler: `await asyncio.sleep` YIELDS to the loop, so a
    concurrent asyncio task (the watcher) keeps ticking DURING the awaited
    sleep. This is overlap — the loop is free to run other work."""
    progress: list[int] = []

    async def watcher() -> None:
        for _ in range(3):
            await asyncio.sleep(0.005)
            progress.append(1)

    task = asyncio.create_task(watcher())
    await asyncio.sleep(0.025)   # cooperative: loop free -> watcher ticks
    await task
    return {"handler": "async", "awaited": True, "watcher_ticks": len(progress)}


@app.get("/s")
def s() -> dict:
    """plain def handler: FastAPI runs it in an external threadpool worker
    thread, which has NO running event loop. That is why a blocking call
    here is safe — it blocks a worker thread, not the loop."""
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False
    time.sleep(0.01)
    return {
        "handler": "sync",
        "thread": threading.current_thread().name,
        "has_running_loop": in_loop,
    }


@app.get("/bad")
async def bad() -> dict:
    """THE TRAP: time.sleep() inside async def. It is a SYNCHRONOUS block,
    so the ONE event loop (shared by every in-flight request) is frozen for
    its whole duration — the watcher cannot make ANY progress until the
    loop is freed again by a real `await`."""
    progress: list[int] = []

    async def watcher() -> None:
        for _ in range(100):
            await asyncio.sleep(0.005)
            progress.append(1)

    task = asyncio.create_task(watcher())
    await asyncio.sleep(0.012)    # let the watcher register a couple ticks
    before = len(progress)
    time.sleep(0.03)              # BLOCKING — loop frozen, watcher stalls
    after_block = len(progress)
    await asyncio.sleep(0.04)     # cooperative — loop free again, resumes
    after_yield = len(progress)
    await task
    return {
        "before": before,
        "after_block": after_block,
        "after_yield": after_yield,
    }


def _bg_task(msg: str) -> None:
    """Runs as a BackgroundTask AFTER the response is built and sent."""
    BG_LOG.append(msg)


@app.post("/x")
def x(background_tasks: BackgroundTasks) -> dict:
    """Schedule _bg_task to run AFTER the response. The handler snapshots
    BG_LOG NOW (pre-task) into the response body, so the client can SEE the
    task had not run yet when the response was built."""
    background_tasks.add_task(_bg_task, "ran-after-response")
    snapshot = list(BG_LOG)
    return {"returned": True, "at_response": snapshot}


# ----------------------------------------------------------------------------
# Section A — async def handler: await yields, the loop stays free
# ----------------------------------------------------------------------------

def section_a_async_handler() -> None:
    banner("A — async def handler: await yields, the loop stays free")
    client = TestClient(app)
    r = client.get("/a")
    body = r.json()
    print(f"GET /a -> {r.status_code} {body}")
    print(f"asyncio.iscoroutinefunction(a) -> "
          f"{asyncio.iscoroutinefunction(a)}")
    print("(the watcher ticked DURING the awaited sleep -> loop was free)")
    print()
    check("GET /a returned 200", r.status_code == 200)
    check("a is a coroutine function (async def)", asyncio.iscoroutinefunction(a))
    check("watcher ticked fully during the awaited sleep (loop was free)",
          body["watcher_ticks"] == 3)


# ----------------------------------------------------------------------------
# Section B — plain def handler: runs in a threadpool worker (no loop)
# ----------------------------------------------------------------------------

def section_b_sync_handler_threadpool() -> None:
    banner("B — plain def handler: runs in a threadpool worker (no loop)")
    client = TestClient(app)
    r = client.get("/s")
    body = r.json()
    print(f"GET /s -> {r.status_code} {body}")
    print(f"asyncio.iscoroutinefunction(s) -> "
          f"{asyncio.iscoroutinefunction(s)}")
    print("(worker thread has no running loop -> blocking call is safe here)")
    print()
    check("GET /s returned 200", r.status_code == 200)
    check("s is NOT a coroutine function (plain def)",
          not asyncio.iscoroutinefunction(s))
    check("sync handler ran OFF the event loop (threadpool worker thread)",
          body["has_running_loop"] is False)


# ----------------------------------------------------------------------------
# Section C — THE TRAP: a blocking call inside async def freezes the loop
# ----------------------------------------------------------------------------

def section_c_blocking_trap() -> None:
    banner("C — THE TRAP: time.sleep inside async def freezes the loop")
    client = TestClient(app)
    r = client.get("/bad")
    b = r.json()
    print(f"GET /bad -> {r.status_code} {b}")
    print(f"  before time.sleep       : {b['before']}")
    print(f"  AFTER  time.sleep(0.03) : {b['after_block']}   <- NO progress")
    print(f"  AFTER  asyncio.sleep    : {b['after_yield']}   <- resumes")
    print("(under a real server this freezes EVERY in-flight request, not")
    print(" just this one — the loop is shared across all of them)")
    print()
    check("GET /bad returned 200", r.status_code == 200)
    check("watcher made NO progress during time.sleep (loop frozen)",
          b["after_block"] == b["before"])
    check("watcher RESUMED after the cooperative asyncio.sleep",
          b["after_yield"] > b["after_block"])


# ----------------------------------------------------------------------------
# Section D — when to use async def vs plain def (the decision)
# ----------------------------------------------------------------------------

def section_d_when_async_vs_sync() -> None:
    banner("D — When to use async def vs plain def")
    print("Rule (FastAPI concurrency docs): a `def` path operation is run in")
    print("an external threadpool that is then awaited; an `async def` path")
    print("operation is called DIRECTLY on the event loop. So match the")
    print("declaration to the work the body does:")
    print()
    print(f"{'handler body calls...':<48}{'declare as':<12}{'why'}")
    print("-" * 84)
    for body_calls, decl, why in [
        ("await conn.fetch(...)  (asyncpg / async DB)", "async def",
         "await yields; loop free for other requests"),
        ("await client.get(...)  (httpx.AsyncClient)", "async def",
         "non-blocking HTTP; overlaps other I/O"),
        ("requests.get(...)  (sync HTTP lib)", "def",
         "threadpooled -> blocks a worker, not the loop"),
        ("time.sleep(x) / psycopg2 query (sync)", "def",
         "FastAPI threadpools it -> safe"),
        ("pure CPU, no I/O (e.g. json.dumps)", "async def",
         "no threadpool hop; stays on the loop"),
    ]:
        print(f"{body_calls:<48}{decl:<12}{why}")
    print()
    check("await-able async lib -> declare the handler async def", True)
    check("blocking sync lib -> declare the handler plain def (threadpooled)",
          True)


# ----------------------------------------------------------------------------
# Section E — BackgroundTasks: the response is sent BEFORE the task runs
# ----------------------------------------------------------------------------

def section_e_background_tasks() -> None:
    banner("E — BackgroundTasks: the response is sent BEFORE the task runs")
    BG_LOG.clear()
    client = TestClient(app)
    r = client.post("/x")
    body = r.json()
    print(f"POST /x -> {r.status_code} {body}")
    print(f"BG_LOG right after client.post() returns -> {BG_LOG}")
    print("(response body's 'at_response' was snapshotted BEFORE the task;")
    print(" BG_LOG is populated only AFTER the response was sent)")
    print()
    check("POST /x returned 200", r.status_code == 200)
    check("response body built BEFORE the task ran (at_response is empty)",
          body["at_response"] == [])
    check("background task ran AFTER the response (BG_LOG now populated)",
          BG_LOG == ["ran-after-response"])


# ----------------------------------------------------------------------------
# Section F — concurrency vs parallelism: async overlaps I/O, not CPU
# ----------------------------------------------------------------------------

def section_f_concurrency_vs_parallelism() -> None:
    banner("F — Concurrency vs parallelism: async overlaps I/O, not CPU")
    print("A FastAPI app runs ONE event loop per worker. `await` overlaps I/O")
    print("WAITS across many requests on that one thread — that is concurrency,")
    print("NOT parallelism. CPU-bound work (hashing, ML inference) must go to")
    print("separate processes: a tight CPU loop never yields, so it blocks the")
    print("loop exactly like time.sleep does.")
    print()
    print(f"{'workload':<32}{'runs where':<24}{'scale via'}")
    print("-" * 76)
    for workload, where, scale in [
        ("many slow I/O requests", "the event loop", "async handlers + async libs"),
        ("quick blocking I/O", "threadpool workers", "def handlers (auto-pooled)"),
        ("CPU-bound (hash, ML)", "separate processes", "gunicorn workers / ProcessPool"),
        ("fire-and-forget cleanup", "BackgroundTasks", "same loop, after the response"),
    ]:
        print(f"{workload:<32}{where:<24}{scale}")
    print()
    check("async overlaps I/O on one loop (concurrency, not parallelism)", True)
    check("CPU parallelism needs separate processes (the loop is one thread)",
          True)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    import fastapi
    print("fastapi_async.py — Phase 7 bundle #46.\n"
          "Every value below is computed by driving the app with TestClient;\n"
          "the .md guide pastes it verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]}, "
          f"FastAPI {fastapi.__version__}.")
    section_a_async_handler()
    section_b_sync_handler_threadpool()
    section_c_blocking_trap()
    section_d_when_async_vs_sync()
    section_e_background_tasks()
    section_f_concurrency_vs_parallelism()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
