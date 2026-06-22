"""
fastapi_middleware_lifespan.py — Bundle #47 (Phase 7).

GOAL (one line): show, by driving FastAPI apps with TestClient, that
middleware is the ONION around every request (the LAST added is the
OUTERMOST), CORSMiddleware answers preflight OPTIONS, exception handlers
map raised exceptions to JSON responses, and the lifespan async context
manager owns startup/shutdown (replacing on_event) — three layers that
shape every request and the whole app life.

This is the GROUND TRUTH for FASTAPI_MIDDLEWARE_LIFESPAN.md. Every value
and ordering below is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python fastapi_middleware_lifespan.py
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
# Section A — custom middleware adds a response header
# ----------------------------------------------------------------------------

def section_a_custom_header_middleware() -> None:
    banner("A — Custom middleware adds a response header")
    print("@app.middleware('http') wraps EVERY request. The function takes")
    print("(request, call_next), awaits call_next(request) to get the response,")
    print("then mutates the response before returning it. Below: stamp every")
    print("response with a constant X-Served-By header.\n")

    app = FastAPI()

    @app.middleware("http")
    async def tag(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Served-By"] = "fastapi-mw-demo"
        return response

    @app.get("/")
    async def root() -> dict:
        return {"hello": "world"}

    client = TestClient(app)
    r = client.get("/")
    print(f"GET / -> {r.status_code}")
    print(f"  X-Served-By  header -> {r.headers.get('X-Served-By')!r}")
    print(f"  content-type header -> {r.headers.get('content-type')!r}")
    print()
    check("GET / returned 200", r.status_code == 200)
    check("middleware stamped the X-Served-By header",
          r.headers.get("X-Served-By") == "fastapi-mw-demo")
    check("middleware ran AFTER the route built the JSON response",
          r.headers.get("content-type", "").startswith("application/json"))


# ----------------------------------------------------------------------------
# Section B — middleware order: the onion (LAST added = OUTERMOST)
# ----------------------------------------------------------------------------

def section_b_middleware_order() -> None:
    banner("B — Middleware order: the onion (LAST added = OUTERMOST)")
    print("FastAPI docs: 'each new middleware wraps the application, forming")
    print("a stack. The LAST middleware added is the OUTERMOST, and the first")
    print("is the INNERMOST.' So adding A then B gives request B->A->route and")
    print("response route->A->B. The recording below proves it.\n")

    events: list[str] = []
    app = FastAPI()

    @app.middleware("http")
    async def mw_a(request: Request, call_next):
        events.append("A-in")
        response = await call_next(request)
        events.append("A-out")
        return response

    @app.middleware("http")
    async def mw_b(request: Request, call_next):
        events.append("B-in")
        response = await call_next(request)
        events.append("B-out")
        return response

    @app.get("/")
    async def root() -> dict:
        events.append("handler")
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/")
    print(f"GET / -> {r.status_code}; recorded order:")
    for e in events:
        print(f"  {e}")
    print("(B was added AFTER A -> B is outermost -> request: B->A->handler,")
    print(" response: handler->A->B)")
    print()
    check("GET / returned 200", r.status_code == 200)
    check("request path is B-in -> A-in -> handler (B outermost)",
          events[:3] == ["B-in", "A-in", "handler"])
    check("response path is handler -> A-out -> B-out (unwound LIFO)",
          events[3:] == ["A-out", "B-out"])
    check("full onion: B-in, A-in, handler, A-out, B-out",
          events == ["B-in", "A-in", "handler", "A-out", "B-out"])


# ----------------------------------------------------------------------------
# Section C — CORSMiddleware: preflight OPTIONS gets CORS headers
# ----------------------------------------------------------------------------

def section_c_cors_preflight() -> None:
    banner("C — CORSMiddleware: preflight OPTIONS gets CORS headers")
    print("CORS is just another middleware. A browser preflight is an OPTIONS")
    print("request with Origin + Access-Control-Request-Method; CORSMiddleware")
    print("intercepts it, answers 200 with Access-Control-Allow-* headers, and")
    print("never calls the route.\n")

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://example.com"],
        allow_methods=["GET", "POST"],
        allow_headers=["X-Custom"],
        allow_credentials=True,
        max_age=600,
    )

    @app.get("/")
    async def root() -> dict:
        return {"hello": "world"}

    client = TestClient(app)
    pre = client.options(
        "/",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Custom",
        },
    )
    simple_ok = client.get("/", headers={"Origin": "https://example.com"})
    simple_bad = client.get("/", headers={"Origin": "https://evil.test"})
    print(f"preflight OPTIONS / -> {pre.status_code}")
    for k in (
        "access-control-allow-origin",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "access-control-allow-credentials",
        "access-control-max-age",
        "vary",
    ):
        print(f"  {k}: {pre.headers.get(k)}")
    print(f"\nsimple GET / (allowed origin)    -> ACAO: "
          f"{simple_ok.headers.get('access-control-allow-origin')!r}")
    print(f"simple GET / (disallowed origin) -> ACAO: "
          f"{simple_bad.headers.get('access-control-allow-origin')!r}")
    print()
    check("preflight returned 200", pre.status_code == 200)
    check("allow-origin echoes the allowed origin",
          pre.headers.get("access-control-allow-origin") == "https://example.com")
    check("allow-methods lists the configured methods",
          pre.headers.get("access-control-allow-methods") == "GET, POST")
    check("allow-credentials is true",
          pre.headers.get("access-control-allow-credentials") == "true")
    check("max-age is 600 (configured cache seconds)",
          pre.headers.get("access-control-max-age") == "600")
    check("simple request from allowed origin still gets ACAO",
          simple_ok.headers.get("access-control-allow-origin")
          == "https://example.com")
    check("simple request from disallowed origin gets NO ACAO",
          simple_bad.headers.get("access-control-allow-origin") is None)


# ----------------------------------------------------------------------------
# Section D — custom exception handler -> JSON
# ----------------------------------------------------------------------------

class BusinessError(Exception):
    """A domain exception mapped to an HTTP response by a global handler."""

    def __init__(self, msg: str, code: int) -> None:
        self.msg = msg
        self.code = code


def section_d_custom_exception_handler() -> None:
    banner("D — Custom exception handler -> JSON response")
    print("@app.exception_handler(SomeException) installs a global mapper: when")
    print("any handler raises SomeException, FastAPI calls your function with")
    print("(request, exc) and your returned JSONResponse goes to the client.\n")

    app = FastAPI()

    @app.exception_handler(BusinessError)
    async def handle_business(
        request: Request, exc: BusinessError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=418,
            content={"error": exc.msg, "code": exc.code},
        )

    @app.get("/charge")
    async def charge() -> dict:
        raise BusinessError("insufficient-funds", 7)

    client = TestClient(app)
    r = client.get("/charge")
    print(f"GET /charge (raises BusinessError) -> {r.status_code} {r.json()}")
    print("(the handler mapped the domain exception to a 418 JSON body)")
    print()
    check("GET /charge returned 418 (mapped by custom handler)",
          r.status_code == 418)
    check("response body carries the exception's msg and code",
          r.json() == {"error": "insufficient-funds", "code": 7})


# ----------------------------------------------------------------------------
# Section E — HTTPException default handling + generic status-code handler
# ----------------------------------------------------------------------------

def section_e_http_exception_and_generic() -> None:
    banner("E — HTTPException default handling + generic status-code handler")
    print("raise HTTPException(status_code=404, detail=...) -> FastAPI's default")
    print("handler returns 404 with body {'detail': ...}. You can also register")
    print("a handler keyed on a STATUS CODE (int): anything that surfaces as")
    print("that status is routed through your function. Below, an unhandled")
    print("RuntimeError becomes a 500 with our custom body.\n")

    app = FastAPI()

    @app.get("/missing")
    async def missing() -> dict:
        raise HTTPException(status_code=404, detail="no such thing")

    @app.exception_handler(500)
    async def handle_500(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"caught": "generic-500"})

    @app.get("/boom")
    async def boom() -> dict:
        raise RuntimeError("kaboom")

    client = TestClient(app, raise_server_exceptions=False)
    r404 = client.get("/missing")
    r500 = client.get("/boom")
    print(f"GET /missing (raises HTTPException(404)) -> {r404.status_code} "
          f"{r404.json()}")
    print(f"GET /boom   (raises RuntimeError)      -> {r500.status_code} "
          f"{r500.json()}")
    print("(HTTPException used the default handler; the 500 status handler")
    print(" intercepted the unhandled RuntimeError)")
    print()
    check("HTTPException(404) -> 404 via the default handler",
          r404.status_code == 404)
    check("HTTPException default body is {'detail': ...}",
          r404.json() == {"detail": "no such thing"})
    check("generic 500 handler caught the RuntimeError",
          r500.status_code == 500 and r500.json() == {"caught": "generic-500"})


# ----------------------------------------------------------------------------
# Section F — lifespan: startup runs on enter, shutdown on exit
# ----------------------------------------------------------------------------

def section_f_lifespan() -> None:
    banner("F — Lifespan: startup runs on `with` enter, shutdown on exit")
    print("FastAPI(lifespan=...) takes an ASYNC CONTEXT MANAGER. Code BEFORE")
    print("yield runs once at startup; code AFTER yield runs once at shutdown.")
    print("Using TestClient(app) as a context manager triggers BOTH — entering")
    print("the with runs startup, exiting it runs shutdown. This REPLACES the")
    print("deprecated on_event('startup'/'shutdown').\n")

    events: list[str] = []

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        events.append("startup")
        yield
        events.append("shutdown")

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def root() -> dict:
        return {"events_at_request": list(events)}

    before = list(events)
    print(f"events before `with TestClient(app)`     : {before}")
    with TestClient(app) as client:
        inside_before = list(events)
        print(f"events inside `with`, before any request : {inside_before}")
        r = client.get("/")
        inside_after = list(events)
        print(f"GET / inside the with-block              : "
              f"{r.status_code} {r.json()}")
        print(f"events inside `with`, after the request  : {inside_after}")
    print(f"events AFTER the with-block exited       : {events}")
    print("(startup ran once on enter; shutdown ran once on exit)")
    print()
    check("nothing ran before the with-block", before == [])
    check("startup ran exactly once on `with` enter (before any request)",
          inside_before == ["startup"])
    check("serving a request did not add startup/shutdown events",
          inside_after == ["startup"])
    check("shutdown ran once on `with` exit",
          events == ["startup", "shutdown"])


# ----------------------------------------------------------------------------
# Section G — app.state: shared namespace populated at startup
# ----------------------------------------------------------------------------

def section_g_app_state() -> None:
    banner("G — app.state: a shared namespace populated at startup")
    print("The lifespan receives the app; whatever you set on app.state there")
    print("is visible in every handler via request.app.state. Below: lifespan")
    print("'opens the DB' (a string) and seeds a counter; the handler reads")
    print("and mutates it across requests.\n")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = "postgres://demo"
        app.state.counter = 0
        yield
        app.state.db = None  # tear down

    app = FastAPI(lifespan=lifespan)

    @app.get("/info")
    async def info(request: Request) -> dict:
        request.app.state.counter += 1
        return {
            "db": request.app.state.db,
            "counter": request.app.state.counter,
        }

    with TestClient(app) as client:
        r1 = client.get("/info")
        r2 = client.get("/info")
    print(f"1st GET /info -> {r1.status_code} {r1.json()}")
    print(f"2nd GET /info -> {r2.status_code} {r2.json()}")
    print("(handler saw the db string the lifespan set; counter persisted")
    print(" ACROSS requests — state outlives any single request)")
    print()
    check("handler saw the startup-set db string",
          r1.json()["db"] == "postgres://demo")
    check("counter was seeded at 0 and incremented to 1 on first request",
          r1.json()["counter"] == 1)
    check("state persisted across requests (2nd request saw counter 2)",
          r2.json()["counter"] == 2)


# ----------------------------------------------------------------------------
# Section H — request-logging middleware (the production pattern)
# ----------------------------------------------------------------------------

def section_h_logging_middleware() -> None:
    banner("H — Request-logging middleware (the production pattern)")
    print("The cross-cutting pattern: a middleware that logs (method, path,")
    print("status, duration_ms) for every request. We capture into a list so")
    print("the output is deterministic (duration varies -> assert >= 0).\n")

    log: list[dict[str, object]] = []

    app = FastAPI()

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        log.append({
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": round(ms, 3),
        })
        return response

    @app.get("/")
    async def root() -> dict:
        return {"ok": True}

    @app.get("/missing")
    async def missing() -> dict:
        raise HTTPException(status_code=404, detail="absent")

    client = TestClient(app)
    client.get("/")
    client.get("/")
    client.get("/missing")

    print(f"{'method':<8}{'path':<12}{'status':<8}{'ms>=0'}")
    print("-" * 38)
    for row in log:
        print(f"{str(row['method']):<8}{str(row['path']):<12}"
              f"{str(row['status']):<8}{row['ms'] >= 0}")
    print()
    check("middleware recorded exactly 3 requests", len(log) == 3)
    check("recorded methods/paths/statuses match the calls",
          [(r["method"], r["path"], r["status"]) for r in log]
          == [("GET", "/", 200), ("GET", "/", 200), ("GET", "/missing", 404)])
    check("every duration is non-negative", all(r["ms"] >= 0 for r in log))


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    import fastapi
    print("fastapi_middleware_lifespan.py — Phase 7 bundle #47.\n"
          "Every value below is computed by driving apps with TestClient;\n"
          "the .md guide pastes it verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]}, "
          f"FastAPI {fastapi.__version__}.")
    section_a_custom_header_middleware()
    section_b_middleware_order()
    section_c_cors_preflight()
    section_d_custom_exception_handler()
    section_e_http_exception_and_generic()
    section_f_lifespan()
    section_g_app_state()
    section_h_logging_middleware()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
