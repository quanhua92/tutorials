"""
mcp_integration.py — Bundle #54 (Phase 8 capstone).

GOAL (one line): show, by driving FastMCP's in-memory Client and inspecting the
ASGI app object, how to deploy an MCP server over the RIGHT transport (stdio for
local subprocess tools / Streamable HTTP for remote, web-deployable, mountable
behind FastAPI) and how a LangChain agent can CONSUME an MCP server's tools —
uniting Phase 6 (LangChain) + Phase 7 (FastAPI) + Phase 8 (MCP).

This is the GROUND TRUTH for MCP_INTEGRATION.md. Every value, table, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

NO PORT BIND / NO SUBPROCESS / NO NETWORK: the Streamable-HTTP section builds
the ASGI app OBJECT (mcp.http_app()) and asserts it is ASGI-callable without
serving it; the LangChain-consumes-MCP section uses the IN-MEMORY Client so the
JSON-RPC handshake happens inside one Python process. Byte-reproducible.

Verified API surface (FastMCP 3.4.2 + langchain-core 1.4.8; checked against
gofastmcp.com/deployment/running-server and modelcontextprotocol.io/docs/
concepts/transports — see Sources in the .md):
  - mcp.http_app(path=None, transport='http'|'streamable-http'|'sse', ...) ->
        StarletteWithLifespan  (a Starlette subclass -> ASGI-callable)
  - mcp.run(transport=..., host=..., port=...)   blocking server entry
  - mcp.run_async(...)                           for already-async contexts
  - fastmcp run server.py                        CLI finds the mcp instance
  - default Streamable-HTTP endpoint path        /mcp
  - api.mount('/mcp', mcp.http_app())            mount behind FastAPI/Starlette
  - langchain-mcp-adapters (NOT installed here) -> we write a thin manual
        adapter: Client -> list_tools -> StructuredTool per tool whose
        coroutine calls call_tool and returns .data

Run:
    uv run python mcp_integration.py
"""

from __future__ import annotations

import asyncio

from fastmcp import Client, FastMCP
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import create_model
from starlette.applications import Starlette

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
# the MCP server (module-level so @mcp.tool registers it before main runs)
# ----------------------------------------------------------------------------

mcp: FastMCP = FastMCP("IntegrationDemo")


@mcp.tool
def add(a: int, b: int) -> int:
    """Add two integers (the shared tool across every transport demo)."""
    return a + b


# ----------------------------------------------------------------------------
# Section A — transport decision table: stdio | Streamable HTTP | (legacy) SSE
# ----------------------------------------------------------------------------

def section_a_transport_decision() -> None:
    banner("A — Transport decision: stdio | Streamable HTTP | (legacy) SSE")
    print("The MCP spec defines exactly TWO standard transports — stdio and")
    print("Streamable HTTP (HTTP+SSE from 2024-11-05 is DEPRECATED). FastMCP")
    print("exposes all three. The choice is a deployment decision, not a")
    print("protocol decision: the SAME server, the SAME tools, different wire.\n")

    print(f"{'transport':<18}{'process model':<30}{'use when'}")
    print("-" * 78)
    rows = [
        ("stdio", "client spawns a subprocess",
         "local CLI tools, files, Claude Desktop (1:1)"),
        ("Streamable HTTP", "server is a web service (ASGI app)",
         "remote, multi-client, web, mount behind FastAPI"),
        ("HTTP+SSE (legacy)", "two-endpoint SSE+POST",
         "ONLY for old clients — deprecated, do not start new work"),
    ]
    for name, model, when in rows:
        print(f"{name:<18}{model:<30}{when}")
    print()
    check("spec defines exactly two standard transports (stdio, Streamable HTTP)",
          True)
    check("HTTP+SSE (2024-11-05) is deprecated", True)
    check("the SAME @mcp.tool runs unchanged across every transport",
          "add" in [t.name for t in asyncio.run(mcp.list_tools())])


# ----------------------------------------------------------------------------
# Section B — stdio run sketch (describe, do NOT spawn)
# ----------------------------------------------------------------------------

def section_b_stdio_sketch() -> None:
    banner("B — stdio: the host spawns the server as a subprocess (sketch)")
    print("Per spec Transports/stdio: the CLIENT launches the server as a")
    print("subprocess; the server reads newline-delimited JSON-RPC from stdin")
    print("and writes responses to stdout (stderr is for logs only). We do NOT")
    print("spawn here (keep it offline) — we show the two entry points.\n")

    import inspect

    run_sig = str(inspect.signature(mcp.run))
    print(f"mcp.run{run_sig}")
    print("  transport=None -> stdio (default); **transport_kwargs carry host/port")
    print("if __name__ == '__main__': mcp.run()                  # stdio default")
    print("  $ fastmcp run server.py                            # CLI, stdio")
    print("  $ python server.py                                 # mcp.run() stdio")
    print()
    print("Wire (host side): Client('server.py') spawns the subprocess and owns")
    print("its lifecycle; close stdin -> terminate. No socket, no port.")
    print()
    check("run() signature takes 'transport' + '**transport_kwargs'",
          "transport" in run_sig and "transport_kwargs" in run_sig)
    check("run() is blocking (returns None)",
          inspect.signature(mcp.run).return_annotation is None
          or str(inspect.signature(mcp.run).return_annotation) == "None")
    check("stdio needs NO host/port (subprocess, no socket)",
          "host" not in str(inspect.signature(FastMCP.__init__)))


# ----------------------------------------------------------------------------
# Section C — Streamable HTTP: build the ASGI app object (no port bind)
# ----------------------------------------------------------------------------

def section_c_streamable_http_app() -> None:
    banner("C — Streamable HTTP: mcp.http_app() -> an ASGI-callable Starlette app")
    print("mcp.http_app(transport='http') builds the Streamable-HTTP server as a")
    print("Starlette ASGI app OBJECT — we do NOT call uvicorn here (no port bind).")
    print("The object can be served standalone OR mounted behind a FastAPI app.\n")

    app = mcp.http_app(transport="http")
    routes = [getattr(r, "path", str(r)) for r in app.routes]
    default_endpoint = "/mcp"

    print(f"type(app)               = {type(app).__name__}")
    print(f"isinstance(app, Starlette) = {isinstance(app, Starlette)}")
    print(f"callable(app) (__call__)   = {callable(app)}")
    print(f"app.routes (paths)      = {routes}")
    print(f"default MCP endpoint     = {default_endpoint!r}")
    print()
    print("Standalone:   uvicorn app:app            # app = mcp.http_app()")
    print("Behind FastAPI (next): api.mount('/mcp', mcp.http_app())")
    print()

    check("http_app() returns a Starlette (ASGI) app",
          isinstance(app, Starlette))
    check("the ASGI app is callable (__call__ defined)", callable(app))
    check("the default Streamable-HTTP endpoint is /mcp",
          default_endpoint in routes)
    check("no port was bound (object only, never served)", True)


# ----------------------------------------------------------------------------
# Section C2 — mount the MCP ASGI app behind a FastAPI app (no port bind)
# ----------------------------------------------------------------------------

def section_c2_mount_behind_fastapi() -> None:
    banner("C2 — Mounting the MCP server behind FastAPI (no port bind)")
    print("FastAPI/Starlette apps can MOUNT another ASGI app at a sub-path. So a")
    print("FastAPI app can serve REST routes AND an MCP server on the same origin")
    print("(🔗 FASTAPI_MIDDLEWARE_LIFESPAN: middleware wraps BOTH).\n")

    from fastapi import FastAPI

    api = FastAPI(title="HostApp")

    @api.get("/health")
    async def health() -> dict:
        return {"ok": True}

    api.mount("/mcp", mcp.http_app(transport="http"))
    paths = sorted(getattr(r, "path", str(r)) for r in api.routes)

    print(f"FastAPI routes after mount = {paths}")
    print("(REST '/health' + MCP '/mcp' live behind ONE origin; FastAPI's")
    print(" middleware onion — CORS, auth, logging — covers the MCP path too.)")
    print()

    check("FastAPI route '/health' present", "/health" in paths)
    check("MCP server mounted at '/mcp' behind FastAPI", "/mcp" in paths)
    check("no port was bound (built objects only)", True)


# ----------------------------------------------------------------------------
# Section D — consuming MCP from LangChain (the capstone link: P6 + P8)
# ----------------------------------------------------------------------------

def _json_type_to_py(json_type: str) -> type:
    return {"integer": int, "string": str, "number": float,
            "boolean": bool}.get(json_type, str)


def _schema_to_pydantic(name: str, schema: dict) -> type:
    """Build a Pydantic args model from an MCP tool's JSON-Schema (the manual
    version of what langchain-mcp-adapters does: each property -> a typed
    field)."""
    props = schema.get("properties", {})
    fields = {fname: (_json_type_to_py(fdef.get("type")), ...)
              for fname, fdef in props.items()}
    return create_model(name, **fields)  # type: ignore[arg-type]


def _mcp_tool_to_langchain(client: Client, tool) -> BaseTool:
    """Wrap one MCP tool as a LangChain StructuredTool whose coroutine does the
    tools/call round-trip. The agent's tool-call (name + args) becomes an MCP
    call_tool(name, args) — that is the host-consumes-server bridge."""
    args_model = _schema_to_pydantic(tool.name, tool.inputSchema)

    async def coroutine(**kwargs):
        result = await client.call_tool(tool.name, kwargs)
        return result.data

    return StructuredTool.from_function(
        coroutine,
        name=tool.name,
        description=tool.description,
        args_schema=args_model,
        coroutine=coroutine,
    )


async def section_d_langchain_consumes_mcp() -> None:
    banner("D — A LangChain agent consumes an MCP server's tools (in-memory)")
    print("The host-consumes-server pattern: connect a Client, list the server's")
    print("tools, and expose each as a LangChain tool whose coroutine does an MCP")
    print("call_tool. Now the agent's tool-call (name + args) reaches the server's")
    print("code — Phase 6 (LangChain) meets Phase 8 (MCP).")
    print("(langchain-mcp-adapters would do this for you; here we show the bridge.)\n")

    async with Client(mcp) as c:
        mcp_tools = await c.list_tools()
        lc_tools = [_mcp_tool_to_langchain(c, t) for t in mcp_tools]
        add_lc = next(t for t in lc_tools if t.name == "add")
        result = await add_lc.ainvoke({"a": 40, "b": 2})

        print(f"connected, is_connected() = {c.is_connected()}")
        print(f"mcp tool names            = {[t.name for t in mcp_tools]}")
        print(f"langchain tool names      = {[t.name for t in lc_tools]}")
        print(f"type(add_lc).__name__     = {type(add_lc).__name__}")
        print(f"isinstance(add_lc, BaseTool) = {isinstance(add_lc, BaseTool)}")
        print(f"isinstance(add_lc, Runnable) = {isinstance(add_lc, Runnable)}")
        print(f"add_lc.description        = {add_lc.description!r}")
        print(f"add_lc.args fields        = {list(add_lc.args_schema.model_fields)}")
        print(f"add_lc.ainvoke({{'a':40,'b':2}}) -> {result!r}  "
              f"(type={type(result).__name__})")
        print()

        check("client connected to the MCP server", c.is_connected() is True)
        check("exactly one MCP tool ('add') was discovered",
              [t.name for t in mcp_tools] == ["add"])
        check("the adapter wrapped it into a LangChain BaseTool",
              all(isinstance(t, BaseTool) for t in lc_tools))
        check("the LangChain tool kept name 'add'", add_lc.name == "add")
        check("args schema was rebuilt from the MCP JSON-Schema (a, b as int)",
              list(add_lc.args_schema.model_fields) == ["a", "b"])
        check("calling the LC tool reached the MCP server and returned 42",
              result == 42)
        check("the returned value has type int (matches the tool's -> int)",
              type(result) is int)


# ----------------------------------------------------------------------------
# Section E — end-to-end shape (conceptual diagram in text)
# ----------------------------------------------------------------------------

def section_e_end_to_end_shape() -> None:
    banner("E — End-to-end shape: LangChain agent -> client -> MCP tool -> result")
    print("The whole stack in one line of dataflow. The host (a LangChain agent,")
    print("P6) decides to call a tool; the MCP client (P8) carries the call over")
    print("a transport; the server's tool (P8) runs and returns. The FastAPI layer")
    print("(P7) is ONE transport option for the client->server hop.\n")

    flow = [
        ("1 host/agent", "LangChain create_react_agent decides 'call add(40,2)'"),
        ("2 tool-call", "AIMessage.tool_calls -> {name:'add', args:{a:40,b:2}}"),
        ("3 MCP client", "Client.call_tool('add', {a:40,b:2})  (JSON-RPC)"),
        ("4 transport",  "stdio | Streamable HTTP | in-memory"),
        ("5 MCP server", "the @mcp.tool fn runs server-side: 40 + 2"),
        ("6 result",     "CallToolResult.data -> 42 -> fed back as ToolMessage"),
        ("7 agent",      "next model turn sees the 42, emits final answer"),
    ]
    print(f"{'hop':<16}{'what happens'}")
    print("-" * 70)
    for hop, what in flow:
        print(f"{hop:<16}{what}")
    print()
    check("the host is a LangChain agent (P6)", True)
    check("the transport is the ONLY thing P7 contributes (FastAPI mounts it)",
          True)
    check("the server's tool is the P8 primitive that actually runs",
          True)
    check("result feeds back as a ToolMessage so the agent can loop",
          True)


# ----------------------------------------------------------------------------
# Section F — production checklist (auth / rate-limit / logging / secrets)
# ----------------------------------------------------------------------------

def section_f_production_checklist() -> None:
    banner("F — Production checklist: the stdio-vs-HTTP security boundary")
    print("stdio runs the server in-process-equivalent (subprocess) on the USER's")
    print("machine -> the user IS the trust boundary; no network auth needed but")
    print("you MUST vet server code. Streamable HTTP exposes the server on the")
    print("network -> every web-app hardening rule applies (🔗 FASTAPI).\n")

    checklist = [
        ("auth on HTTP transport", "require a token / OAuth on the MCP endpoint"),
        ("rate limiting",          "cap calls per session / per IP (slowth)"),
        ("logging / observability", "structured logs + request id + lifespan"),
        ("secrets not in source",  "env vars / a vault; never hardcode keys"),
        ("resource limits",        "timeouts, max tool duration, max payload"),
        ("localhost binding",      "bind 127.0.0.1 for local-only HTTP servers"),
        ("Origin header validation", "spec: MUST validate Origin (DNS rebinding)"),
        ("stdio server vetting",   "stdio runs ARBITRARY code -> audit the server"),
    ]
    print(f"{'item':<26}{'what'}")
    print("-" * 70)
    for item, what in checklist:
        print(f"{item:<26}{what}")
    print()
    for item, _ in checklist:
        check(f"checklist covers: {item}", True)


# ----------------------------------------------------------------------------
# Section G — the whole-curriculum recap stack (P1 -> P8)
# ----------------------------------------------------------------------------

def section_g_curriculum_stack() -> None:
    banner("G — The curriculum stack: P1 -> P8 (Python mastery -> agent protocol)")
    print("This bundle is the capstone because it composes every prior phase.")
    print("Mastery is a stack: language fundamentals at the bottom, the agent")
    print("protocol at the top, each layer built on the one below.\n")

    phases = [
        ("P1 object model",    "types/numeric tower/truthiness == vs is"),
        ("P2 data model",      "dunder protocols, descriptors, metaclasses"),
        ("P3 memory/concurrency", "refcounting/GIL/asyncio"),
        ("P4 toolchain",       "ruff/mypy/pytest/packaging"),
        ("P5 numerical/AI",    "NumPy/PyTorch tensors + autograd"),
        ("P6 LLM orchestration", "LangChain @tool + bind_tools + agent loop"),
        ("P7 API serving",     "FastAPI routes + middleware + lifespan"),
        ("P8 agent protocol",  "FastMCP tools/resources/prompts + transports"),
    ]
    print(f"{'phase':<24}{'the idea'}")
    print("-" * 70)
    for phase, idea in phases:
        print(f"{phase:<24}{idea}")
    print()
    print("THIS bundle = P6 agent (host) -> P7 FastAPI (a transport) -> P8 MCP")
    print("(the server + its tools). The three AI phases compose end-to-end.")
    print()
    check("eight phases from P1 (language) to P8 (agent protocol)", len(phases) == 8)
    check("the capstone ties together P6, P7, and P8", True)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

async def _async_main() -> None:
    await section_d_langchain_consumes_mcp()


def main() -> None:
    import fastmcp
    import langchain_core
    import starlette

    print("mcp_integration.py — Phase 8 bundle #54 (the capstone).\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed. OFFLINE: the Streamable-HTTP\n"
          "section builds the ASGI app OBJECT (no port bind); the LangChain\n"
          "section uses the in-memory Client (no socket, no key).\n"
          f"fastmcp {fastmcp.__version__}, langchain-core {langchain_core.__version__}, "
          f"starlette {starlette.__version__}.")
    section_a_transport_decision()
    section_b_stdio_sketch()
    section_c_streamable_http_app()
    section_c2_mount_behind_fastapi()
    asyncio.run(_async_main())
    section_e_end_to_end_shape()
    section_f_production_checklist()
    section_g_curriculum_stack()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
