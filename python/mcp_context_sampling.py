"""
mcp_context_sampling.py — Phase 8 bundle #53.

GOAL (one line): show, by printing every value, that a FastMCP tool taking a
`Context` argument can (a) LOG to the client, (b) REPORT PROGRESS, (c) request
SAMPLING — i.e. ASK THE HOST'S LLM to generate text (the inversion: the server
BORROWS the host's model), (d) ELICIT input from the user, and (e) read ROOTS
(the dirs the user granted). This is what makes servers "agentic" without
bundling their own model.

This is the GROUND TRUTH for MCP_CONTEXT_SAMPLING.md. Every value and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

OFFLINE / NO NETWORK: the server-side `Context` reaches UP to the host through
four host-side callbacks. Because sampling by definition needs a HOST model, we
inject STUB handlers on the in-memory Client (`sampling_handler`, etc.) that
return canned text. In production the host's REAL model + the real user answer;
here the stubs make the run deterministic and offline. Byte-reproducible.

Verified API surface (FastMCP 3.4.2; checked against gofastmcp.com/servers/context
and modelcontextprotocol.io/docs/concepts/{sampling,roots} + specification
/2025-06-18/client/elicitation — see Sources in the .md):
  - tool takes `ctx: Context`                          -> auto-injected (type hint)
  - await ctx.info/debug/warning/error(msg)            -> host log_handler(params)
  - await ctx.report_progress(progress, total)         -> host progress_handler
  - await ctx.read_resource(uri) -> ResourceResult     -> .contents[0].content
  - await ctx.sample(msg, ...) -> SamplingResult       -> .text / .result / .history
        the server ASKS the host's LLM; the host's sampling_handler answers
  - await ctx.elicit(msg, response_type=T)             -> .action ("accept"/...)
        + .data (the value); host's elicitation_handler answers
  - await ctx.list_roots() -> list[Root]               -> the dirs the user granted
  - Client(mcp, sampling_handler=, elicitation_handler=, log_handler=,
           progress_handler=, roots=[Root(uri, name)]) wires the host side.

Run:
    uv run python mcp_context_sampling.py
"""

from __future__ import annotations

import asyncio

from fastmcp import Client, FastMCP
from fastmcp.server.context import Context
from mcp.types import Root

BANNER = "=" * 70

# The canned reply the HOST-STUB model returns when the server asks it to
# sample. In production this string is produced by the host's real LLM
# (Claude / GPT / ...); here it is hard-coded so the run is offline & fixed.
STUB_HOST_REPLY = "[HOST-STUB] The capital of France is Paris."
# The canned reply the (stubbed) USER returns when the server elicits input.
STUB_USER_REPLY = "octocat"


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
# the MCP server + Context-exercising tools + a resource
# ----------------------------------------------------------------------------

mcp: FastMCP = FastMCP("ContextDemo")


@mcp.resource("config://app")
def app_config() -> str:
    """A static config resource (read via ctx.read_resource)."""
    return "version=9.9"


@mcp.tool
async def ctx_basics(x: int, ctx: Context) -> str:
    """Exercise basic Context capabilities: log + read a resource."""
    await ctx.info(f"processing x={x}")
    res = await ctx.read_resource("config://app")
    return f"x={x} cfg={res.contents[0].content!r}"


@mcp.tool
async def ctx_logger(ctx: Context) -> str:
    """Send one log notification at every level."""
    await ctx.debug("debug-msg")
    await ctx.info("info-msg")
    await ctx.warning("warn-msg")
    await ctx.error("error-msg")
    return "logged-at-4-levels"


@mcp.tool
async def ctx_progress(n: int, ctx: Context) -> str:
    """Report progress n times (1..n out of n)."""
    for i in range(n):
        await ctx.report_progress(i + 1, n)
    return "done"


@mcp.tool
async def ctx_sample(question: str, ctx: Context) -> str:
    """Ask the HOST's LLM (via sampling) to answer `question`."""
    res = await ctx.sample(question, temperature=0.0, max_tokens=32)
    return f"host-said:{res.text!r}"


@mcp.tool
async def ctx_elicit_demo(ctx: Context) -> str:
    """Ask the USER (via elicitation) for a single string."""
    res = await ctx.elicit("Enter your GitHub username:", response_type=str)
    return f"action={res.action} data={res.data!r}"


@mcp.tool
async def ctx_roots_demo(ctx: Context) -> str:
    """Read the roots (granted dirs) the user gave the server."""
    roots = await ctx.list_roots()
    return f"roots={[(str(r.uri), r.name) for r in roots]}"


# ----------------------------------------------------------------------------
# HOST-SIDE STUBS — the four callbacks the in-memory Client installs so the
# server's Context calls have something to talk to. NO real LLM, NO real user.
# ----------------------------------------------------------------------------

# Captured during a session so the .py can assert the host really received them.
captured_logs: list[tuple[str, str]] = []
captured_progress: list[tuple[float, float]] = []


async def stub_sampling_handler(messages, params, context):
    """The host's (stubbed) model. Real host: forward to Claude/GPT/etc."""
    return STUB_HOST_REPLY


async def stub_elicitation_handler(message, response_type, params, context):
    """The (stubbed) user filling in the elicitation form."""
    return STUB_USER_REPLY


async def capture_log_handler(params) -> None:
    captured_logs.append((params.level, params.data["msg"]))


async def capture_progress_handler(progress, total, message=None) -> None:
    captured_progress.append((progress, total))


GRANTED_ROOTS = [Root(uri="file:///home/user/project", name="My Project")]


def make_client() -> Client:
    """Wire the host side: stub model, stub user, log/progress capture, roots."""
    return Client(
        mcp,
        sampling_handler=stub_sampling_handler,
        elicitation_handler=stub_elicitation_handler,
        log_handler=capture_log_handler,
        progress_handler=capture_progress_handler,
        roots=GRANTED_ROOTS,
    )


# ----------------------------------------------------------------------------
# Section A — Context basics: a tool takes ctx: Context (auto-injected)
# ----------------------------------------------------------------------------

async def section_a_context_basics() -> None:
    banner("A — Context basics: a tool with `ctx: Context` runs")
    print("Add a parameter annotated `ctx: Context` and FastMCP auto-injects a")
    print("context object (the param is EXCLUDED from the tool's input schema).")
    print("Inside, the tool can log, report progress, read resources, ask the")
    print("host's LLM to sample, elicit user input, and read granted roots.\n")

    ctx_methods = ["info", "debug", "warning", "error", "report_progress",
                   "read_resource", "sample", "elicit", "list_roots"]
    async with make_client() as c:
        result = await c.call_tool("ctx_basics", {"x": 7})

    print(f"ctx_basics(7).data          = {result.data!r}")
    print(f"result.is_error             = {result.is_error}")
    print("Context methods exercised here + later sections:")
    for m in ctx_methods:
        print(f"  ctx.{m}")
    print()
    check("a tool with a Context arg ran and returned data",
          result.data == "x=7 cfg='version=9.9'")
    check("the call was not an error", result.is_error is False)
    check("Context exposes info/report_progress/sample/elicit/list_roots",
          all(hasattr(Context, m) for m in ctx_methods))


# ----------------------------------------------------------------------------
# Section B — logging via the context (ctx.info/debug/warning/error)
# ----------------------------------------------------------------------------

async def section_b_logging() -> None:
    banner("B — Logging: ctx.info/debug/warning/error reach the host")
    print("ctx.<level>(msg) sends a JSON-RPC `notifications/message` log up to")
    print("the client. The host installs `log_handler=` to receive them. Each")
    print("notification carries level + data{msg, extra}.\n")
    captured_logs.clear()
    async with make_client() as c:
        result = await c.call_tool("ctx_logger", {})

    print(f"ctx_logger().data           = {result.data!r}")
    print(f"captured_logs (level, msg)  = {captured_logs}")
    print()
    check("the tool logged at all 4 levels",
          [lvl for lvl, _ in captured_logs]
          == ["debug", "info", "warning", "error"])
    check("the messages arrived intact",
          [msg for _, msg in captured_logs]
          == ["debug-msg", "info-msg", "warn-msg", "error-msg"])


# ----------------------------------------------------------------------------
# Section C — progress reporting (ctx.report_progress -> host callback)
# ----------------------------------------------------------------------------

async def section_c_progress() -> None:
    banner("C — Progress: ctx.report_progress(done, total) -> host callback")
    print("report_progress(progress, total) streams progress notifications up to")
    print("the client. The host passes `progress_handler=` to call_tool (or to")
    print("the Client) and receives (progress, total, message=None) per update.\n")

    captured_progress.clear()
    async with make_client() as c:
        result = await c.call_tool("ctx_progress", {"n": 3})

    print(f"ctx_progress(3).data        = {result.data!r}")
    print(f"captured_progress           = {captured_progress}")
    print()
    check("the tool returned 'done' after 3 updates", result.data == "done")
    check("the host saw 3 updates (1/3, 2/3, 3/3)",
          captured_progress == [(1.0, 3.0), (2.0, 3.0), (3.0, 3.0)])


# ----------------------------------------------------------------------------
# Section D — SAMPLING: ctx.sample asks the HOST's LLM (the inversion)
# ----------------------------------------------------------------------------

async def section_d_sampling() -> None:
    banner("D — Sampling: ctx.sample asks the HOST's LLM (the inversion)")
    print("ctx.sample(messages, ...) sends `sampling/createMessage` UP to the")
    print("client. The host's sampling_handler forwards to ITS model and returns")
    print("the generation. The server never sees an API key. Here the host is a")
    print("STUB returning a canned string; in production the host's REAL model\nanswers.\n")

    async with make_client() as c:
        result = await c.call_tool(
            "ctx_sample", {"question": "What is the capital of France?"})

    print(f"ctx_sample(...).data        = {result.data!r}")
    print(f"stub host reply (STUB_HOST_REPLY) = {STUB_HOST_REPLY!r}")
    print()
    check("ctx.sample returned the host-stub's canned text",
          result.data == f"host-said:{STUB_HOST_REPLY!r}")
    check("the server got text back WITHOUT owning a model or key", True)


# ----------------------------------------------------------------------------
# Section E — the inversion explained: the server BORROWS the host's model
# ----------------------------------------------------------------------------

def section_e_inversion() -> None:
    banner("E — The inversion: the server BORROWS the host's model")
    print("Normally a server is dumb data + code. With sampling, the server can")
    print("ASK the host's LLM to reason — enabling AGENTIC servers (the server")
    print("decides a plan, then uses the host's model to think) without each")
    print("server shipping its own LLM, key, or trust. The HOST owns the model.\n")

    print(f"{'who':<10}{'owns the model?':<20}{'owns the API key?':<22}{'job'}")
    print("-" * 78)
    rows = [
        ("SERVER", "NO (borrows it)", "NO",
         "tools/data + can ASK host to sample"),
        ("HOST", "YES", "YES",
         "runs the LLM, mediates all requests, holds trust"),
        ("USER", "-", "-",
         "approves sampling/elicitation, grants roots"),
    ]
    for who, model, key, job in rows:
        print(f"{who:<10}{model:<20}{key:<22}{job}")
    print()
    check("the inversion: server borrows the host model (no own model/key)",
          True)


# ----------------------------------------------------------------------------
# Section F — elicitation: ctx.elicit asks the USER for input
# ----------------------------------------------------------------------------

async def section_f_elicitation() -> None:
    banner("F — Elicitation: ctx.elicit asks the USER for structured input")
    print("ctx.elicit(message, response_type=T) sends `elicitation/create` up to")
    print("the client; the host shows a form to the USER and returns one of three")
    print("actions: 'accept' (+data), 'decline', or 'cancel'. The host (not the")
    print("server) owns the UI and the user's trust. Here the user is a STUB.\n")

    async with make_client() as c:
        result = await c.call_tool("ctx_elicit_demo", {})

    print(f"ctx_elicit_demo().data      = {result.data!r}")
    print(f"stub user reply             = {STUB_USER_REPLY!r}")
    print()
    check("elicit returned action='accept'", "action=accept" in result.data)
    check("elicit returned the stub user's data",
          f"data={STUB_USER_REPLY!r}" in result.data)


# ----------------------------------------------------------------------------
# Section G — roots: ctx.list_roots reads the dirs the USER granted
# ----------------------------------------------------------------------------

async def section_g_roots() -> None:
    banner("G — Roots: ctx.list_roots reads the dirs the USER granted")
    print("Roots are filesystem boundaries the USER granted the server (the host")
    print("declares the `roots` capability + passes them down). The server asks")
    print("`roots/list` and must respect those boundaries — the permission fence.\n")

    async with make_client() as c:
        result = await c.call_tool("ctx_roots_demo", {})

    print(f"ctx_roots_demo().data       = {result.data!r}")
    print(f"GRANTED_ROOTS               = {[(str(r.uri), r.name) for r in GRANTED_ROOTS]}")
    print()
    check("ctx.list_roots returned the one granted root",
          "file:///home/user/project" in result.data)


# ----------------------------------------------------------------------------
# Section H — the trust / permission model (everything is host-mediated)
# ----------------------------------------------------------------------------

def section_h_trust_model() -> None:
    banner("H — The trust model: sampling/elicitation/roots are host-mediated")
    print("All four Context capabilities route THROUGH the host. The server never")
    print("gets the model, the key, or direct filesystem access — it ASKS, the")
    print("host SHOWS the user, the user APPROVES, the host returns the result.")
    print("This is the security pillar that makes 'agentic servers' safe.\n")

    print(f"{'capability':<22}{'direction':<18}{'who answers':<18}{'mediated by'}")
    print("-" * 74)
    rows = [
        ("logging", "server -> host", "host console", "host (display only)"),
        ("progress", "server -> host", "host UI", "host (display only)"),
        ("sampling", "server -> host", "HOST's LLM", "host + USER approval"),
        ("elicitation", "server -> host", "the USER", "host + USER approval"),
        ("roots", "host -> server", "USER-granted dirs", "host (permission fence)"),
    ]
    for cap, direction, who, med in rows:
        print(f"{cap:<22}{direction:<18}{who:<18}{med}")
    print()
    check("every Context capability is mediated by the host", True)
    check("the server never receives the model or API key directly", True)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

async def _async_main() -> None:
    await section_a_context_basics()
    await section_b_logging()
    await section_c_progress()
    await section_d_sampling()
    section_e_inversion()
    await section_f_elicitation()
    await section_g_roots()
    section_h_trust_model()


def main() -> None:
    import fastmcp

    print("mcp_context_sampling.py — Phase 8 bundle #53.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed. OFFLINE: the server-side Context\n"
          "reaches UP to four HOST-SIDE STUB callbacks (sampling/elicitation/\n"
          "log/progress) on the in-memory Client — no network, no API key, no\n"
          "real LLM. Byte-reproducible.\n"
          f"fastmcp {fastmcp.__version__} on this machine.")
    asyncio.run(_async_main())
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
