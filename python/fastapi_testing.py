"""
fastapi_testing.py — Phase 7 bundle (#49).

GOAL (one line): show, by printing every value, that TestClient drives a FastAPI
app in-process (no network) and dependency_overrides swap DB/auth for fakes —
fast, hermetic, deterministic API tests; async endpoints get a true async client
via httpx.AsyncClient + ASGITransport.

This is the GROUND TRUTH for FASTAPI_TESTING.md. Every value below is computed
by this file via fastapi.testclient.TestClient + httpx.AsyncClient + pytest.main
(on a tiny test file written to /tmp); the .md guide pastes it verbatim. Nothing
here is hand-computed. Change it -> re-run -> re-paste.

Run:
    uv run python fastapi_testing.py
"""

from __future__ import annotations

import asyncio
import io
import re
import sys
import tempfile
from pathlib import Path

import fastapi
import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

BANNER = "=" * 70
SCRATCH = Path(tempfile.mkdtemp(prefix="bundle49_"))


class Item(BaseModel):
    """Shared body model — MUST be module-level so FastAPI resolves the `Item`
    annotation (with `from __future__ import annotations`, local classes would
    turn into unresolvable strings and FastAPI would fall back to query params)."""
    name: str
    qty: int


# ----------------------------------------------------------------------------
# pretty printers + helpers (house style, copied from types_and_truthiness.py)
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


def _write(name: str, source: str) -> Path:
    """Write a tiny source file under the scratch dir; return its path."""
    p = SCRATCH / name
    p.write_text(source)
    return p


def _normalize(out: str) -> str:
    """Make captured pytest output byte-reproducible: hide the temp dir + any
    sub-second durations (pytest timing varies run-to-run)."""
    out = out.replace(str(SCRATCH), "<tmpdir>")
    out = re.sub(r"in \d+\.\d+s", "in <duration>s", out)
    return out.rstrip()


def _run_pytest(path: Path) -> tuple[int, str]:
    """Invoke pytest.main on a test file, capturing stdout. Return (exit, out)."""
    buf = io.StringIO()
    old = sys.stdout
    sys.path.insert(0, str(SCRATCH))
    sys.stdout = buf
    try:
        code = pytest.main(
            ["-q", "-p", "no:cacheprovider", "-p", "no:warnings",
             "--capture=no", str(path)]
        )
    finally:
        sys.stdout = old
        if str(SCRATCH) in sys.path:
            sys.path.remove(str(SCRATCH))
    return int(code), _normalize(buf.getvalue())


# ----------------------------------------------------------------------------
# Section A — TestClient basics: GET in-process, no network, no port
# ----------------------------------------------------------------------------

def section_a_testclient_get() -> None:
    banner("A — TestClient basics: GET in-process, no socket, no uvicorn")
    print("fastapi.testclient.TestClient (re-exported from Starlette, backed by")
    print("httpx) calls the ASGI app DIRECTLY in-process. No socket, no port, no")
    print("uvicorn. client.get('/...') returns an httpx.Response; .status_code")
    print("and .json() are the two assertions you write.\n")

    app = FastAPI()

    @app.get("/")
    def root() -> dict:
        return {"msg": "Hello World"}

    @app.get("/items/{item_id}")
    def read_item(item_id: int) -> dict:
        return {"item_id": item_id}

    client = TestClient(app)
    r1 = client.get("/")
    r2 = client.get("/items/42")
    print(f"GET /            -> {r1.status_code} {r1.json()}")
    print(f"GET /items/42    -> {r2.status_code} {r2.json()}")
    print(f"type(r1)         -> {type(r1).__name__} (httpx.Response)")
    print()

    check("GET / returns 200", r1.status_code == 200)
    check("GET / body is the handler's dict",
          r1.json() == {"msg": "Hello World"})
    check("path param parsed (item_id=42)", r2.json() == {"item_id": 42})
    check("TestClient returns an httpx.Response", type(r1).__name__ == "Response")


# ----------------------------------------------------------------------------
# Section B — POST/PUT/DELETE + JSON body + status codes
# ----------------------------------------------------------------------------

def section_b_post_put_delete() -> None:
    banner("B — POST/PUT/DELETE + JSON body + status codes")
    print("TestClient mirrors the httpx verbs: .post/.put/.delete accept a")
    print("`json=` kwarg that serializes the body. Set status_code=201 on the")
    print("route for create endpoints (the HTTP convention for 'created').\n")

    app = FastAPI()
    db: dict[int, Item] = {}

    @app.post("/items/", status_code=201)
    def create(item: Item) -> dict:
        db[item.qty] = item
        return {"created": item.model_dump()}

    @app.put("/items/{qty}")
    def replace(qty: int, item: Item) -> dict:
        db[qty] = item
        return {"replaced": item.model_dump()}

    @app.delete("/items/{qty}")
    def drop(qty: int) -> dict:
        db.pop(qty, None)
        return {"deleted": qty}

    client = TestClient(app)
    post = client.post("/items/", json={"name": "wrench", "qty": 7})
    put = client.put("/items/7", json={"name": "wrench", "qty": 7})
    dele = client.delete("/items/7")
    print(f"POST   /items/    -> {post.status_code} {post.json()}")
    print(f"PUT    /items/7   -> {put.status_code} {put.json()}")
    print(f"DELETE /items/7   -> {dele.status_code} {dele.json()}")
    print()

    check("POST returns 201 (status_code=201 on the route)",
          post.status_code == 201)
    check("POST body echoes the created item",
          post.json() == {"created": {"name": "wrench", "qty": 7}})
    check("PUT returns 200 and replaces", put.status_code == 200)
    check("DELETE returns 200 with the deleted key",
          dele.status_code == 200 and dele.json() == {"deleted": 7})


# ----------------------------------------------------------------------------
# Section C — validation 422: bad body returns error loc, not 500
# ----------------------------------------------------------------------------

def section_c_validation_422() -> None:
    banner("C — Validation 422: bad body returns error loc, not 500")
    print("A pydantic-model body that fails validation makes FastAPI return 422")
    print("(Unprocessable Entity) with detail=[{loc, msg, type, ...}]. The `loc`")
    print("pinpoints the failing field — assert on it in tests rather than")
    print("string-matching the message.\n")

    app = FastAPI()

    @app.post("/items/")
    def create(item: Item) -> Item:
        return item

    client = TestClient(app)
    bad = client.post("/items/", json={"name": "wrench"})  # missing 'qty'
    print(f"POST /items/ missing 'qty' -> {bad.status_code}")
    print(f"detail: {bad.json()['detail']}")
    print()

    check("missing required field -> 422 (not 500)", bad.status_code == 422)
    loc = tuple(bad.json()["detail"][0]["loc"])
    check("error loc points at ('body', 'qty')", loc == ("body", "qty"))


# ----------------------------------------------------------------------------
# Section D — dependency_overrides: swap get_db for a fake (no real DB)
# ----------------------------------------------------------------------------

def section_d_dependency_overrides_db() -> None:
    banner("D — dependency_overrides: swap get_db for a fake (no real DB)")
    print("app.dependency_overrides[real] = fake makes FastAPI call `fake`")
    print("instead of `real` everywhere. Below: a route Depends(get_db); we")
    print("override get_db with a fake returning canned data, then RESET with")
    print("= {}. This is the hermetic-test lever (full DI theory in #45).\n")

    def get_db() -> dict:
        return {"env": "production", "rows": []}  # imagine a real connection

    app = FastAPI()

    @app.get("/rows/")
    def list_rows(db: dict = Depends(get_db)) -> dict:
        return {"env": db["env"], "rows": db["rows"]}

    client = TestClient(app)
    before = client.get("/rows/")

    def fake_db() -> dict:
        return {"env": "test", "rows": [{"id": 1}, {"id": 2}]}

    app.dependency_overrides[get_db] = fake_db
    overridden = client.get("/rows/")
    app.dependency_overrides = {}                      # reset
    after_reset = client.get("/rows/")

    print(f"real dep      : {before.json()}")
    print(f"override set  : {overridden.json()}")
    print(f"override drop : {after_reset.json()}")
    print()

    check("real dep ran (env=production)", before.json()["env"] == "production")
    check("handler saw the FAKE rows (no real DB hit)",
          overridden.json() == {"env": "test", "rows": [{"id": 1}, {"id": 2}]})
    check("reset restores the real dep",
          after_reset.json()["env"] == "production")


# ----------------------------------------------------------------------------
# Section E — auth override: fake get_current_user skips real JWT
# ----------------------------------------------------------------------------

def section_e_auth_override() -> None:
    banner("E — Auth override: fake get_current_user skips real JWT/OAuth")
    print("The standard 'don't hit real auth in unit tests' pattern: a route")
    print("Depends(get_current_user); tests override it to return a fake user,")
    print("skipping JWT/OAuth entirely. The protected route returns 200.\n")

    def get_current_user() -> dict:
        raise HTTPException(status_code=401, detail="not authenticated")

    app = FastAPI()

    @app.get("/me")
    def me(user: dict = Depends(get_current_user)) -> dict:
        return {"user": user}

    client = TestClient(app)
    no_override = client.get("/me")

    def fake_user() -> dict:
        return {"id": 99, "name": "alice"}

    app.dependency_overrides[get_current_user] = fake_user
    with_override = client.get("/me")
    app.dependency_overrides = {}

    print(f"real dep          -> {no_override.status_code} {no_override.json()}")
    print(f"override to alice -> {with_override.status_code} {with_override.json()}")
    print()

    check("real auth dep raises 401", no_override.status_code == 401)
    check("overriding auth makes the protected route return 200",
          with_override.status_code == 200)
    check("the fake user was injected into the handler",
          with_override.json() == {"user": {"id": 99, "name": "alice"}})


# ----------------------------------------------------------------------------
# Section F — pytest fixtures: an app fixture + a client fixture
# ----------------------------------------------------------------------------

def section_f_fixtures() -> None:
    banner("F — pytest fixtures: an app fixture + a client fixture")
    print("The boilerplate: one @pytest.fixture builds the app, another wraps it")
    print("in a TestClient. Tests list `client` as a param — pytest injects it.")
    print("Below: a tiny test file written to /tmp, run via pytest.main.\n")

    src = (
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n"
        "import pytest\n"
        "\n"
        "@pytest.fixture\n"
        "def app():\n"
        "    a = FastAPI()\n"
        "    @a.get('/')\n"
        "    def root():\n"
        "        return {'msg': 'fx'}\n"
        "    return a\n"
        "\n"
        "@pytest.fixture\n"
        "def client(app):\n"
        "    return TestClient(app)\n"
        "\n"
        "def test_root(client):\n"
        "    r = client.get('/')\n"
        "    assert r.status_code == 200\n"
        "    assert r.json() == {'msg': 'fx'}\n"
    )
    test_file = _write("test_fixtures.py", src)
    code, out = _run_pytest(test_file)
    print(f"--- pytest on {test_file.name} (client/app fixtures) ---")
    print(out)
    print()

    check("fixture-based test -> exit code 0 (ExitCode.OK)", code == 0)
    check("output reports '1 passed'", "1 passed" in out)


# ----------------------------------------------------------------------------
# Section G — async testing: httpx.AsyncClient + ASGITransport
# ----------------------------------------------------------------------------

def section_g_async_client() -> None:
    banner("G — Async testing: httpx.AsyncClient + ASGITransport")
    print("TestClient runs async handlers via an internal portal — convenient")
    print("but SYNCHRONOUS. To exercise the REAL async path (and to `await`")
    print("other async code in the same test), use httpx.AsyncClient with")
    print("transport=httpx.ASGITransport(app=app); drive it with asyncio.run.\n")

    app = FastAPI()

    @app.get("/")
    async def root() -> dict:
        return {"msg": "async"}

    async def hit() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://test") as ac:
            return await ac.get("/")

    r = asyncio.run(hit())
    print(f"async GET /  -> {r.status_code} {r.json()}")
    print(f"type(r)      -> {type(r).__name__} (httpx.Response)")
    print()

    check("async client GET returns 200", r.status_code == 200)
    check("async client GET returns the body", r.json() == {"msg": "async"})
    check("AsyncClient also returns an httpx.Response",
          type(r).__name__ == "Response")


# ----------------------------------------------------------------------------
# Section H — the API test pyramid: many unit, fewer integration, smoke e2e
# ----------------------------------------------------------------------------

def section_h_test_pyramid() -> None:
    banner("H — The API test pyramid: many unit, fewer integration, smoke e2e")
    print("Tests form a PYRAMID. Bottom (most): UNIT tests — handlers with")
    print("dependency_overrides swapping DB/auth for fakes (hermetic, fast).")
    print("Middle: INTEGRATION — real deps / a real (often in-memory) DB. Top")
    print("(fewest): end-to-end SMOKE against a deployed/staged URL.\n")

    layers = [
        ("unit        ", "handlers + dep overrides", "fast, hermetic, ~ms each"),
        ("integration ", "real deps / in-memory DB", "slower, ~10-100ms each"),
        ("e2e         ", "deployed URL over HTTP  ", "slow, flaky, ~seconds"),
    ]
    print(f"{'layer':<14}{'strategy':<26}{'cost'}")
    print("-" * 70)
    for layer, strat, cost in layers:
        print(f"{layer:<14}{strat:<26}{cost}")
    print()

    unit, integration, e2e = 120, 25, 3
    total = unit + integration + e2e
    print(f"example counts: unit={unit}, integration={integration}, "
          f"e2e={e2e} (total {total})")
    print()

    check("unit tests are the MAJORITY", unit > integration > e2e)
    check("unit tests > integration tests", unit > integration)
    check("e2e is the thinnest layer (slowest, flakiest)", e2e < integration)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("fastapi_testing.py — Phase 7 bundle #49.\n"
          "Every value below is computed by this file via TestClient +\n"
          "httpx.AsyncClient + pytest.main (on a /tmp scratch test file); the\n"
          ".md guide pastes it verbatim. Nothing is hand-computed.\n"
          f"FastAPI {fastapi.__version__}, httpx {httpx.__version__}, "
          f"pytest {pytest.__version__} on this machine.\n"
          f"Scratch: {SCRATCH}")
    section_a_testclient_get()
    section_b_post_put_delete()
    section_c_validation_422()
    section_d_dependency_overrides_db()
    section_e_auth_override()
    section_f_fixtures()
    section_g_async_client()
    section_h_test_pyramid()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
