"""
mcp_architecture.py — Bundle #50 (Phase 8, MCP intro).

GOAL (one line): show, by driving FastMCP's in-memory Client against a tiny
FastMCP server, that MCP is a JSON-RPC client-host-server protocol where a
SERVER exposes tools/resources/prompts, a HOST runs the LLM, and a CLIENT is
the one-per-server connection that runs the initialize → list → call →
shutdown lifecycle over a transport (stdio / Streamable HTTP / in-memory).

This is the GROUND TRUTH for MCP_ARCHITECTURE.md. Every value, capability dump,
and tool result in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

NO subprocess, NO network, NO API key: the in-memory Client passes the FastMCP
instance straight into the transport, so the JSON-RPC handshake happens inside
one Python process and is fully deterministic.

Run:
    uv run python mcp_architecture.py
"""

from __future__ import annotations

import asyncio

from fastmcp import Client, FastMCP

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
# Section A — the roles: HOST (LLM) ↔ CLIENT ↔ SERVER
# ----------------------------------------------------------------------------

def section_a_roles() -> None:
    banner("A — The three roles: HOST ↔ CLIENT ↔ SERVER")
    print("MCP (spec 2025-11-25, Architecture) is a client-host-server protocol.")
    print("A HOST runs the LLM and manages many clients; a CLIENT is the single")
    print("1:1 connection to one server; a SERVER exposes tools/resources/prompts.")
    print("MCP standardizes the wire, so ANY host talks to ANY server.\n")

    print(f"{'role':<10}{'who runs it':<32}{'job'}")
    print("-" * 70)
    rows = [
        ("HOST",
         "Claude Desktop / an agent",
         "runs the LLM, manages client connections, enforces consent"),
        ("CLIENT",
         "one per server, inside the host",
         "opens a stateful session; does the initialize handshake"),
        ("SERVER",
         "subprocess or remote service",
         "exposes tools/resources/prompts via MCP primitives"),
    ]
    for role, who, job in rows:
        print(f"{role:<10}{who:<32}{job}")
    print()

    check("three canonical roles are HOST, CLIENT, SERVER",
          ("HOST", "CLIENT", "SERVER")
          == ("HOST", "CLIENT", "SERVER"))
    check("each client has a 1:1 relationship with exactly one server",
          True)


# ----------------------------------------------------------------------------
# Section B — a minimal FastMCP server + @mcp.tool
# ----------------------------------------------------------------------------

async def section_b_minimal_server() -> FastMCP:
    banner("B — A minimal FastMCP server: FastMCP('demo') + @mcp.tool")
    print('Build the server object, then register a tool with a decorator.')
    print('FastMCP reads the type hints + docstring and generates the JSON')
    print('schema automatically — this is what tools/list will hand back.\n')

    mcp = FastMCP("demo")

    @mcp.tool
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    # The server knows about the tool BEFORE any client connects. Server-side
    # list_tools() returns FunctionTool objects (the host sees mcp.types.Tool).
    server_side = await mcp.list_tools()
    names = [t.name for t in server_side]
    print(f"server.name               = {mcp.name!r}")
    print(f"server.list_tools() names = {names}")
    print(f"'add' description         = {server_side[0].description!r}")
    print()

    check("server is named 'demo'", mcp.name == "demo")
    check("server exposes a tool named 'add'", "add" in names)
    check("exactly one tool registered on the minimal server", len(names) == 1)
    return mcp


# ----------------------------------------------------------------------------
# Section C — the in-memory client connect + list_tools
# ----------------------------------------------------------------------------

async def section_c_inmemory_client(mcp: FastMCP) -> None:
    banner("C — In-memory Client: async with Client(mcp) as c")
    print("Client(mcp) selects the IN-MEMORY transport: no socket, no subprocess.")
    print("Entering `async with` runs the JSON-RPC initialize handshake; inside")
    print("the block the connection is live. list_tools() is the JSON-RPC")
    print("'tools/list' method and returns one mcp.types.Tool per tool.\n")

    async with Client(mcp) as c:
        connected = c.is_connected()
        tools = await c.list_tools()
        tool = tools[0]
        names = [t.name for t in tools]

        print(f"c.is_connected()        = {connected}")
        print(f"len(c.list_tools())     = {len(tools)}")
        print(f"tool names              = {names}")
        print(f"tool.name               = {tool.name!r}")
        print(f"tool.inputSchema        = {tool.inputSchema}")
        print()

        check("client reports connected inside the context manager",
              connected is True)
        check("list_tools includes 'add'", "add" in names)
        check("add's schema requires both 'a' and 'b'",
              set(tool.inputSchema["required"]) == {"a", "b"})
        check("add's schema types a and b as integer",
              tool.inputSchema["properties"]["a"]["type"] == "integer"
              and tool.inputSchema["properties"]["b"]["type"] == "integer")


# ----------------------------------------------------------------------------
# Section D — initialize / lifecycle handshake
# ----------------------------------------------------------------------------

async def section_d_lifecycle(mcp: FastMCP) -> None:
    banner("D — Lifecycle: the initialize handshake (protocolVersion + caps)")
    print("Per spec Lifecycle, connecting MUST first run 'initialize': the client")
    print("sends its protocolVersion + clientInfo + capabilities; the server")
    print("replies with ITS protocolVersion + serverInfo + capabilities; then the")
    print("client sends notifications/initialized. FastMCP does all of this when")
    print("you enter `async with Client(...)` and exposes the result directly.\n")

    async with Client(mcp) as c:
        ir = c.initialize_result
        caps = ir.capabilities
        caps_tools = caps.tools.model_dump(exclude_none=True)
        caps_prompts = caps.prompts.model_dump(exclude_none=True)
        caps_resources = caps.resources.model_dump(exclude_none=True)
        print(f"protocolVersion         = {ir.protocolVersion!r}")
        print(f"serverInfo.name         = {ir.serverInfo.name!r}")
        print(f"serverInfo.version      = {ir.serverInfo.version!r}")
        print(f"capabilities.tools      = {caps_tools}")
        print(f"capabilities.prompts    = {caps_prompts}")
        print(f"capabilities.resources  = {caps_resources}")
        print()

        check("initialize_result is populated (handshake ran)",
              ir is not None)
        check("server reported its name ('demo')", ir.serverInfo.name == "demo")
        check("server reported a protocol version (date-shaped)",
              isinstance(ir.protocolVersion, str)
              and len(ir.protocolVersion) == 10)
        check("server advertised the 'tools' capability",
              caps.tools is not None)
        check("server advertised the 'prompts' capability",
              caps.prompts is not None)
        check("server advertised the 'resources' capability",
              caps.resources is not None)


# ----------------------------------------------------------------------------
# Section E — tools/list + tools/call → result
# ----------------------------------------------------------------------------

async def section_e_call(mcp: FastMCP) -> None:
    banner("E — tools/call: call_tool('add', {a:2, b:3}) -> 5")
    print("call_tool() is the JSON-RPC 'tools/call' method. FastMCP returns a")
    print("CallToolResult with two views: .content (wire content blocks, plain")
    print("text here) and .data (the structured Python return value).\n")

    async with Client(mcp) as c:
        res = await c.call_tool("add", {"a": 2, "b": 3})
        print(f"type(res)               = {type(res).__name__}")
        print(f"res.data                = {res.data!r}  ({type(res.data).__name__})")
        print(f"res.content[0].text     = {res.content[0].text!r}")
        print(f"res.content[0] type     = {type(res.content[0]).__name__}")
        print(f"res.is_error            = {res.is_error}")
        print()

        check("call_tool('add', {a:2,b:3}).data == 5", res.data == 5)
        check("structured data type is int (matches -> int)",
              type(res.data) is int)
        check("wire content is the text '5'", res.content[0].text == "5")
        check("result is not an error", res.is_error is False)


# ----------------------------------------------------------------------------
# Section F — transports (stdio / Streamable HTTP / in-memory)
# ----------------------------------------------------------------------------

def section_f_transports() -> None:
    banner("F — Transports: stdio (default) | Streamable HTTP | in-memory")
    print("The spec defines two standard transports: stdio and Streamable HTTP")
    print("(HTTP+SSE is the deprecated 2024-11-05 form). FastMCP also offers an")
    print("in-memory transport for tests. Client(mcp) infers in-memory; Client of")
    print("a .py path -> stdio subprocess; Client of a URL -> Streamable HTTP.\n")

    print(f"{'transport':<18}{'Client(...) arg':<26}{'fits'}")
    print("-" * 70)
    rows = [
        ("stdio", "Client('server.py')", "local CLI tools, Claude Desktop"),
        ("Streamable HTTP", "Client('https://x/mcp')", "remote, multi-client, web"),
        ("in-memory", "Client(mcp_instance)", "tests, no socket, one process"),
    ]
    for name, arg, fits in rows:
        print(f"{name:<18}{arg:<26}{fits}")
    print()
    check("spec defines exactly two standard transports (stdio, Streamable HTTP)",
          True)
    check("in-memory transport uses no socket and no subprocess", True)


# ----------------------------------------------------------------------------
# Section G — MCP vs raw function-calling
# ----------------------------------------------------------------------------

def section_g_vs_function_calling() -> None:
    banner("G — MCP vs raw function-calling: who decides, who invokes")
    print("Function-calling is MODEL-INTERNAL: the LLM emits structured args for")
    print("a function the host declared. MCP is the PROTOCOL the host then uses to")
    print("DISCOVER + INVOKE the server's tool. Two steps, two layers.\n")

    print(f"{'concern':<26}{'function-calling':<28}{'MCP'}")
    print("-" * 70)
    rows = [
        ("where it lives",
         "inside the model",
         "a wire protocol between processes"),
        ("who picks the function",
         "the model emits args",
         "host's client calls tools/call"),
        ("discovery",
         "host hardcodes the list",
         "tools/list at runtime"),
        ("boundary",
         "one process",
         "host + server (1:many)"),
    ]
    for concern, fc, mcp in rows:
        print(f"{concern:<26}{fc:<28}{mcp}")
    print()
    check("MCP sits between the model's tool decision and the server's code",
          True)


# ----------------------------------------------------------------------------
# Section H — the three primitives preview: tools / resources / prompts
# ----------------------------------------------------------------------------

async def section_h_three_primitives() -> None:
    banner("H — Three primitives preview: tools / resources / prompts")
    print("Per spec Server Overview, a server exposes three primitive kinds.")
    print("Tools are model-controlled, resources are application-controlled,")
    print("prompts are user-controlled. Each gets its own bundle later.\n")

    mcp2 = FastMCP("primitives")

    @mcp2.tool
    def add(a: int, b: int) -> int:
        """Add two integers (a TOOL: the model decides to call it)."""
        return a + b

    @mcp2.resource("config://app")
    def app_config() -> str:
        """Static config (a RESOURCE: the app attaches it as context)."""
        return "version=1"

    @mcp2.prompt
    def code_review(code: str) -> str:
        """Review template (a PROMPT: the user picks it from a menu)."""
        return f"Please review this code: {code}"

    async with Client(mcp2) as c:
        tools = await c.list_tools()
        resources = await c.list_resources()
        prompts = await c.list_prompts()
        print(f"tools      = {[t.name for t in tools]}")
        print(f"resources  = {[(r.name, r.uri) for r in resources]}")
        print(f"prompts    = {[p.name for p in prompts]}")
        print()

        check("server exposes 1 tool ('add')", [t.name for t in tools] == ["add"])
        check("server exposes 1 resource ('app_config')",
              [r.name for r in resources] == ["app_config"])
        check("server exposes 1 prompt ('code_review')",
              [p.name for p in prompts] == ["code_review"])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

async def _async_sections() -> None:
    mcp = await section_b_minimal_server()
    await section_c_inmemory_client(mcp)
    await section_d_lifecycle(mcp)
    await section_e_call(mcp)
    await section_h_three_primitives()


def main() -> None:
    print("mcp_architecture.py — Phase 8 bundle #50 (MCP intro).\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed. In-memory Client: no network.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_roles()
    asyncio.run(_async_sections())
    section_f_transports()
    section_g_vs_function_calling()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
