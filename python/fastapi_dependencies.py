"""
fastapi_dependencies.py — Phase 7 bundle (#45).

GOAL (one line): show, by printing every value, that FastAPI's Depends()
INVERTS dependencies — you declare what you need and the framework resolves
(then caches per-request) the graph; yield-deps give setup/teardown,
sub-deps compose, classes/callables work too, app-level deps gate every
route, and dependency_overrides swap any node for tests.

This is the GROUND TRUTH for FASTAPI_DEPENDENCIES.md. Every value below is
computed by this file via fastapi.testclient.TestClient; the .md guide pastes
it verbatim. Nothing here is hand-computed. Change it -> re-run -> re-paste.

Run:
    uv run python fastapi_dependencies.py
"""

from __future__ import annotations

import fastapi
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers (house style, copied from types_and_truthiness.py)
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
# Section A — Depends(fn): the framework calls fn and injects its return value
# ----------------------------------------------------------------------------

def section_a_depends_fn() -> None:
    banner("A — Depends(fn): framework calls fn, injects its return")
    print("A 'dependable' is just a function with path-op-style params.\n"
          "FastAPI calls it for you and passes what it RETURNS to the handler.\n")

    def common(q: str | None = None, skip: int = 0, limit: int = 100) -> dict:
        return {"q": q, "skip": skip, "limit": limit}

    app = FastAPI()

    @app.get("/items/")
    def read_items(commons: dict = Depends(common)) -> dict:
        return commons

    client = TestClient(app)
    r = client.get("/items/?q=foo&skip=5")
    print(f"GET /items/?q=foo&skip=5  -> {r.status_code}")
    print(f"handler received (injected): {r.json()}")
    print()

    check("Depends(common) injects common()'s return dict",
          r.json() == {"q": "foo", "skip": 5, "limit": 100})
    check("defaults fill in (limit=100)", r.json()["limit"] == 100)


# ----------------------------------------------------------------------------
# Section B — sub-dependencies: a dep can itself depend on a dep (a chain)
# ----------------------------------------------------------------------------

def section_b_sub_dependencies() -> None:
    banner("B — Sub-dependencies: a→b→handler resolves in order")
    print("A dependency may declare its OWN Depends(). FastAPI builds the\n"
          "graph and resolves leaves-first, so each dep gets its inputs.\n")

    order: list[str] = []

    def dep_a() -> str:
        order.append("a")
        return "A"

    def dep_b(value_a: str = Depends(dep_a)) -> str:
        order.append("b")
        return f"{value_a}->B"

    app = FastAPI()

    @app.get("/chain/")
    def chain(value_b: str = Depends(dep_b)) -> dict:
        order.append("handler")
        return {"value_b": value_b, "order": list(order)}

    client = TestClient(app)
    r = client.get("/chain/")
    print(f"GET /chain/  -> {r.status_code}")
    print(f"body: {r.json()}")
    print()

    check("chain resolved leaves-first: a, then b, then handler",
          r.json()["order"] == ["a", "b", "handler"])
    check("dep_a's value flowed THROUGH dep_b to the handler",
          r.json()["value_b"] == "A->B")


# ----------------------------------------------------------------------------
# Section C — yield-dependency: setup before, teardown after (context manager)
# ----------------------------------------------------------------------------

def section_c_yield_dependency() -> None:
    banner("C — yield-dependency: setup before, teardown after the handler")
    print("Use `yield` (not `return`): code BEFORE+INCLUDING yield is setup\n"
          "(the yielded value is injected); code AFTER yield is teardown that\n"
          "runs after the response. This is the DB-session / resource pattern.\n")

    events: list[str] = []

    def get_db() -> dict:
        events.append("open")
        conn = {"open": True}
        yield conn                      # injected into the handler
        events.append("close")          # teardown, runs AFTER the handler
        conn["open"] = False

    app = FastAPI()

    @app.get("/db/")
    def db_view(session: dict = Depends(get_db)) -> dict:
        events.append("handler")
        return {"open_at_handler": session["open"]}

    client = TestClient(app)
    r = client.get("/db/")
    print(f"GET /db/  -> {r.status_code}")
    print(f"body: {r.json()}")
    print(f"event log: {events}")
    print()

    check("setup ran BEFORE the handler", events[0] == "open")
    check("handler ran after setup", events[1] == "handler")
    check("teardown ran AFTER the handler", events[2] == "close")
    check("the yielded value (open=True) was what the handler saw",
          r.json()["open_at_handler"] is True)


# ----------------------------------------------------------------------------
# Section D — a class is a callable: FastAPI inspects __init__ as the dep
# ----------------------------------------------------------------------------

def section_d_class_dependency() -> None:
    banner("D — Class as a dependency: FastAPI inspects __init__")
    print("A dependency only needs to be CALLABLE. A class is callable (it\n"
          "builds an instance), so FastAPI inspects its __init__ params exactly\n"
          "like a path-op's, then injects the constructed INSTANCE.\n")

    class Paginator:
        def __init__(self, skip: int = 0, limit: int = 10) -> None:
            self.skip = skip
            self.limit = limit

    app = FastAPI()

    @app.get("/page/")
    def page(p: Paginator = Depends(Paginator)) -> dict:
        return {"type": type(p).__name__, "skip": p.skip, "limit": p.limit}

    client = TestClient(app)
    r = client.get("/page/?skip=2&limit=3")
    print(f"GET /page/?skip=2&limit=3  -> {r.status_code}")
    print(f"body: {r.json()}")
    print()

    check("an INSTANCE of the class was injected (not the class itself)",
          r.json()["type"] == "Paginator")
    check("__init__ params were parsed from the query string",
          r.json()["skip"] == 2 and r.json()["limit"] == 3)


# ----------------------------------------------------------------------------
# Section E — Header() guard dependency: raise HTTPException -> 4xx
# ----------------------------------------------------------------------------

def section_e_header_guard() -> None:
    banner("E — Header() guard dependency: bad/missing token -> 401")
    print("A dependency that reads Header() and raises HTTPException is the\n"
          "guard / auth pattern: it short-circuits the request before the\n"
          "handler ever runs.\n")

    def verify_token(x_token: str | None = Header(default=None)) -> str:
        if x_token != "secret":
            raise HTTPException(status_code=401, detail="invalid token")
        return x_token

    app = FastAPI()

    @app.get("/secure/")
    def secure(token: str = Depends(verify_token)) -> dict:
        return {"token": token}

    client = TestClient(app)
    no_hdr = client.get("/secure/")
    bad_hdr = client.get("/secure/", headers={"x-token": "wrong"})
    ok_hdr = client.get("/secure/", headers={"x-token": "secret"})
    print(f"GET /secure/                       -> {no_hdr.status_code}")
    print(f"GET /secure/  x-token=wrong        -> {bad_hdr.status_code}")
    print(f"GET /secure/  x-token=secret       -> {ok_hdr.status_code} "
          f"{ok_hdr.json()}")
    print()

    check("missing header -> 401 (dep raised)", no_hdr.status_code == 401)
    check("bad header    -> 401 (dep raised)", bad_hdr.status_code == 401)
    check("good header   -> 200 and the dep's return was injected",
          ok_hdr.status_code == 200 and ok_hdr.json() == {"token": "secret"})


# ----------------------------------------------------------------------------
# Section F — per-request cache: the same dep is called ONCE per request
# ----------------------------------------------------------------------------

def section_f_per_request_cache() -> None:
    banner("F — per-request cache: a dep used twice in one request runs once")
    print("If two params (or a sub-dep chain) ask for the SAME dependable in a\n"
          "single request, FastAPI calls it ONCE and reuses the cached value.\n")

    calls = {"n": 0}

    def counter() -> int:
        calls["n"] += 1
        return calls["n"]

    app = FastAPI()

    @app.get("/twin/")
    def twin(first: int = Depends(counter),
             second: int = Depends(counter)) -> dict:
        return {"first": first, "second": second, "dep_calls": calls["n"]}

    client = TestClient(app)
    calls["n"] = 0
    r = client.get("/twin/")
    body = r.json()
    print(f"GET /twin/  -> {r.status_code}")
    print(f"body: {body}")
    print()

    check("both params received the SAME cached value",
          body["first"] == body["second"])
    check("dep called exactly ONCE even though injected twice",
          body["dep_calls"] == 1)


# ----------------------------------------------------------------------------
# Section G — app-level deps: dependencies=[...] applies to EVERY route
# ----------------------------------------------------------------------------

def section_g_app_level() -> None:
    banner("G — App-level deps: dependencies=[...] runs for every route")
    print("FastAPI(app, dependencies=[...]) (or the same kwarg on an APIRouter)\n"
          "runs those deps for every path op, even handlers that ignore them.\n")

    hits = {"n": 0}

    def audit() -> None:
        hits["n"] += 1

    app = FastAPI(dependencies=[Depends(audit)])

    @app.get("/r1/")
    def r1() -> dict:
        return {"route": "r1"}

    @app.get("/r2/")
    def r2() -> dict:
        return {"route": "r2"}

    client = TestClient(app)
    hits["n"] = 0
    a = client.get("/r1/")
    b = client.get("/r2/")
    print(f"GET /r1/ -> {a.status_code} {a.json()}")
    print(f"GET /r2/ -> {b.status_code} {b.json()}")
    print(f"audit dep ran {hits['n']} time(s) across 2 requests")
    print()

    check("/r1/ still returns its own body", a.json() == {"route": "r1"})
    check("/r2/ still returns its own body", b.json() == {"route": "r2"})
    check("app-level dep ran for EVERY route (2 requests -> 2 runs)",
          hits["n"] == 2)


# ----------------------------------------------------------------------------
# Section H — dependency_overrides: swap any node for tests
# ----------------------------------------------------------------------------

def section_h_dependency_overrides() -> None:
    banner("H — dependency_overrides: swap a dep for tests (preview)")
    print("app.dependency_overrides[real] = fake makes FastAPI call `fake`\n"
          "instead of `real` everywhere. Reset with = {} . This is the testing\n"
          "lever (full treatment in FASTAPI_TESTING).\n")

    def real_settings() -> dict:
        return {"env": "production", "debug": False}

    def fake_settings() -> dict:
        return {"env": "test", "debug": True}

    app = FastAPI()

    @app.get("/cfg/")
    def cfg(settings: dict = Depends(real_settings)) -> dict:
        return settings

    client = TestClient(app)
    before = client.get("/cfg/")
    app.dependency_overrides[real_settings] = fake_settings
    overridden = client.get("/cfg/")
    app.dependency_overrides = {}                     # reset
    after_reset = client.get("/cfg/")
    print(f"no override   : {before.json()}")
    print(f"override set  : {overridden.json()}")
    print(f"override reset: {after_reset.json()}")
    print()

    check("without override the REAL dep ran",
          before.json() == {"env": "production", "debug": False})
    check("app.dependency_overrides swapped real -> fake",
          overridden.json() == {"env": "test", "debug": True})
    check("resetting overrides restored the real dep",
          after_reset.json() == {"env": "production", "debug": False})


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("fastapi_dependencies.py — Phase 7 bundle #45.\n"
          "Every value below is computed by this file via TestClient; the .md\n"
          "guide pastes it verbatim. Nothing is hand-computed.\n"
          f"FastAPI {fastapi.__version__} on this machine.")
    section_a_depends_fn()
    section_b_sub_dependencies()
    section_c_yield_dependency()
    section_d_class_dependency()
    section_e_header_guard()
    section_f_per_request_cache()
    section_g_app_level()
    section_h_dependency_overrides()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
