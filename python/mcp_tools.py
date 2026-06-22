"""
mcp_tools.py — Phase 8 bundle #51.

GOAL (one line): show, by printing every value, how `@mcp.tool` turns a Python
function into a model-invokable MCP tool — name from the fn, description from
the docstring, inputSchema auto-derived from the type hints (JSON-Schema),
results returned as content/structured content, and errors returned as tool
results (NOT HTTP 500) — all verified with FastMCP's in-memory Client.

This is the GROUND TRUTH for MCP_TOOLS.md. Every value, schema, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

OFFLINE / NO NETWORK: every check below uses `async with Client(mcp) as c:`,
FastMCP's IN-MEMORY transport — the client and server live in the same process
and exchange MCP messages over an in-memory pipe. No HTTP server, no socket,
no API key. Byte-reproducible.

Verified API surface (FastMCP 3.4.2; checked against gofastmcp.com/servers/tools
and modelcontextprotocol.io/docs/concepts/tools — see Sources in the .md):
  - @mcp.tool            (no parens)  — canonical decorator form
  - tool.inputSchema     — JSON-Schema auto-derived from type hints
  - await c.list_tools() — returns [Tool(name, description, inputSchema, ...)]
  - await c.call_tool(name, {args}) -> CallToolResult with
        .content             (list[TextContent|...])
        .structured_content  (dict|None)  -- {"result": N} for primitives,
                                              model-dict for Pydantic returns
        .data                (typed python value)
        .is_error            (bool)       -- True for tool execution errors
  - raise_on_error=False  keeps the result on error instead of raising ToolError
  - Context arg           -> ctx.info(), ctx.report_progress(progress, total)
  - progress_handler=fn   on call_tool receives (progress, total, message=None)

Run:
    uv run python mcp_tools.py
"""

from __future__ import annotations

import asyncio

from fastmcp import Client, Context, FastMCP
from pydantic import BaseModel, Field

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
# the MCP server + tool registry (module-level so @mcp.tool registers them)
# ----------------------------------------------------------------------------

mcp: FastMCP = FastMCP("ToolsDemo")


@mcp.tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


class Address(BaseModel):
    street: str = Field(description="street name")
    zip: str = Field(description="postal code")


class Customer(BaseModel):
    name: str
    age: int = Field(ge=0, le=150)
    address: Address


@mcp.tool
def create_customer(customer: Customer) -> Customer:
    """Create and return a customer (nested Pydantic schema)."""
    return customer


@mcp.tool
def plain_text(x: int) -> str:
    """Return a plain text string."""
    return f"value is {x}"


@mcp.tool
def fail(x: int) -> int:
    """Always raises ValueError."""
    raise ValueError("boom: invalid x")


@mcp.tool
async def with_progress(n: int, ctx: Context) -> str:
    """Report progress n times via the Context."""
    await ctx.report_progress(0, n)
    for i in range(n):
        await ctx.report_progress(i + 1, n)
    return "done"


# ----------------------------------------------------------------------------
# Section A — @mcp.tool: function -> MCP tool with auto name + description
# ----------------------------------------------------------------------------

async def section_a_decorator() -> None:
    banner("A — @mcp.tool: function -> tool with auto name + description")
    print("@mcp.tool (no parens) registers a Python function as an MCP tool.")
    print("FastMCP auto-derives: name <- function name, description <- the")
    print("docstring, args <- the type hints. The host's model sees the tool")
    print("via tools/list and may invoke it via tools/call.\n")

    async with Client(mcp) as c:
        tools = await c.list_tools()
    names = sorted(t.name for t in tools)
    add_tool = next(t for t in tools if t.name == "add")

    print(f"{'expression':<36}{'value'}")
    print("-" * 60)
    print(f"{'sorted tool names':<36}{names}")
    print(f"{'add.name':<36}{add_tool.name!r}")
    print(f"{'add.description':<36}{add_tool.description!r}")
    print(f"{'type(add).__name__':<36}{type(add).__name__}")
    print()

    check("'add' is registered as a tool", "add" in names)
    check("add.name == 'add' (from the function name)",
          add_tool.name == "add")
    check("add.description == 'Add two numbers.' (from the docstring)",
          add_tool.description == "Add two numbers.")


# ----------------------------------------------------------------------------
# Section B — the auto inputSchema: JSON-Schema derived from type hints
# ----------------------------------------------------------------------------

async def section_b_input_schema() -> None:
    banner("B — The auto inputSchema: JSON-Schema from type hints")
    print("list_tools() returns each tool's inputSchema — a JSON-Schema dict")
    print("derived from the function's parameter annotations. The host model")
    print("reads this schema to decide HOW to call the tool.\n")

    async with Client(mcp) as c:
        tools = await c.list_tools()
    schema = next(t for t in tools if t.name == "add").inputSchema

    print(f"add.inputSchema = {schema}")
    print()
    print("Schema shape (the MCP/JSON-Schema contract):")
    print(f"  type                 = {schema['type']!r}")
    print(f"  properties.keys()    = {sorted(schema['properties'].keys())}")
    print(f"  properties['a']      = {schema['properties']['a']}")
    print(f"  properties['b']      = {schema['properties']['b']}")
    print(f"  required             = {schema['required']}")
    print(f"  additionalProperties = {schema['additionalProperties']}")
    print()

    check("schema type is 'object'", schema["type"] == "object")
    check("properties are a, b (from the param names)",
          sorted(schema["properties"]) == ["a", "b"])
    check("a is JSON-Schema integer", schema["properties"]["a"]["type"]
          == "integer")
    check("b is JSON-Schema integer", schema["properties"]["b"]["type"]
          == "integer")
    check("both a and b are required", schema["required"] == ["a", "b"])


# ----------------------------------------------------------------------------
# Section C — a Pydantic-arg tool: nested JSON-Schema
# ----------------------------------------------------------------------------

async def section_c_pydantic_arg() -> None:
    banner("C — A Pydantic-arg tool: nested JSON-Schema from the model")
    print("A Pydantic model as a parameter yields a NESTED JSON-Schema: each")
    print("field becomes a property, with descriptions (Field(description=...))")
    print("and constraints (Field(ge=..., le=...)) carried through. The model")
    print("reads the nested schema and produces a matching JSON object.\n")

    async with Client(mcp) as c:
        tools = await c.list_tools()
    schema = next(t for t in tools if t.name == "create_customer").inputSchema
    cust_prop = schema["properties"]["customer"]
    addr_prop = cust_prop["properties"]["address"]

    print(f"create_customer.inputSchema = {schema}")
    print()
    print("Schema highlights:")
    print(f"  customer.required              = {cust_prop['required']}")
    print(f"  customer.age (with constraints) = "
          f"{cust_prop['properties']['age']}")
    print(f"  customer.address.street          = "
          f"{addr_prop['properties']['street']}")
    print()

    check("top-level arg is 'customer'", "customer" in schema["properties"])
    check("customer has nested fields name, age, address",
          sorted(cust_prop["properties"]) == ["address", "age", "name"])
    check("age carries ge=0 and le=150 constraints from Field(...)",
          cust_prop["properties"]["age"]["minimum"] == 0
          and cust_prop["properties"]["age"]["maximum"] == 150)
    check("nested street description came through",
          addr_prop["properties"]["street"]["description"] == "street name")


# ----------------------------------------------------------------------------
# Section D — call_tool: the result shape (content / structured / data)
# ----------------------------------------------------------------------------

async def section_d_call_tool_result() -> None:
    banner("D — call_tool: the CallToolResult shape")
    print("await c.call_tool(name, {args}) runs the function server-side and")
    print("returns a CallToolResult. It carries FOUR views of the same answer:")
    print("  .content             list of MCP content blocks (TextContent, ...)")
    print("  .structured_content  the JSON dict (wraps primitives under 'result')")
    print("  .data                the typed python value (5, str, model, ...)")
    print("  .is_error            False here; True for tool failures (Section F)\n")

    async with Client(mcp) as c:
        result = await c.call_tool("add", {"a": 2, "b": 3})

    print(f"result                 = {result}")
    print(f"result.content[0]      = {result.content[0]}")
    print(f"result.content[0].text = {result.content[0].text!r}")
    print(f"result.structured_content = {result.structured_content}")
    print(f"result.data            = {result.data!r}  "
          f"(type={type(result.data).__name__})")
    print(f"result.is_error        = {result.is_error}")
    print()

    check("result.data == 5 (typed python int)", result.data == 5)
    check("structured_content wraps the int under 'result'",
          result.structured_content == {"result": 5})
    check("content[0].text is '5' (the human-readable view)",
          result.content[0].text == "5")
    check("is_error is False for a successful call", result.is_error is False)


# ----------------------------------------------------------------------------
# Section E — return content vs structured: primitives, str, Pydantic
# ----------------------------------------------------------------------------

async def section_e_content_vs_structured() -> None:
    banner("E — Return content vs structured: primitive, str, Pydantic")
    print("Three return shapes, one rule: the function's return type hint")
    print("controls what the host sees. Primitives WITH a hint -> wrapped")
    print("{'result': N} structured content + '5' text; str -> {'result': ...};")
    print("a Pydantic model -> its fields as structured content + JSON text.\n")

    async with Client(mcp) as c:
        r_add = await c.call_tool("add", {"a": 2, "b": 3})
        r_str = await c.call_tool("plain_text", {"x": 7})
        r_obj = await c.call_tool(
            "create_customer",
            {"customer": {"name": "Ada", "age": 30,
                          "address": {"street": "X St", "zip": "00000"}}},
        )

    print(f"{'tool':<18}{'return hint':<12}{'data':<26}"
          f"{'structured_content'}")
    print("-" * 80)
    print(f"{'add(2,3)':<18}{'int':<12}{str(r_add.data):<26}"
          f"{r_add.structured_content}")
    print(f"{'plain_text(7)':<18}{'str':<12}{str(r_str.data):<26}"
          f"{r_str.structured_content}")
    print(f"{'create_customer':<18}{'Customer':<12}{str(r_obj.data):<26}"
          f"{r_obj.structured_content}")
    print()
    print(f"create_customer content[0].text = {r_obj.content[0].text!r}")
    print()

    check("int return: data==5, structured wrapped under 'result'",
          r_add.data == 5 and r_add.structured_content == {"result": 5})
    check("str return: data=='value is 7', structured wraps the string",
          r_str.data == "value is 7"
          and r_str.structured_content == {"result": "value is 7"})
    check("Pydantic return: structured_content has the model's fields",
          r_obj.structured_content
          == {"name": "Ada", "age": 30,
              "address": {"street": "X St", "zip": "00000"}})
    check("Pydantic return: content[0].text is the JSON serialization",
          r_obj.content[0].text
          == '{"name":"Ada","age":30,"address":{"street":"X St",'
              '"zip":"00000"}}')


# ----------------------------------------------------------------------------
# Section F — tool errors returned as results (NOT HTTP 500)
# ----------------------------------------------------------------------------

async def section_f_errors_as_results() -> None:
    banner("F — Tool errors are returned as results (NOT an HTTP 500)")
    print("MCP separates two error paths: PROTOCOL errors (unknown tool, bad")
    print("JSON-RPC) come back as JSON-RPC error objects; TOOL EXECUTION")
    print("errors (the function raised) come back as a NORMAL result whose")
    print("is_error is True. The host model sees the failure message and can")
    print("retry. FastMCP's Client raises ToolError by default; pass")
    print("raise_on_error=False to inspect the raw result shape.\n")

    async with Client(mcp) as c:
        result = await c.call_tool("fail", {"x": 1}, raise_on_error=False)

    print(f"result               = {result}")
    print(f"result.is_error      = {result.is_error}")
    print(f"result.content[0]    = {result.content[0]}")
    print(f"result.content[0].text = {result.content[0].text!r}")
    print(f"result.data          = {result.data!r}")
    print(f"result.structured_content = {result.structured_content}")
    print()

    check("is_error is True for a raised exception", result.is_error is True)
    check("the error message is carried in content[0].text",
          "boom: invalid x" in result.content[0].text)
    check("data is None on error (no value to return)", result.data is None)
    check("structured_content is None on error",
          result.structured_content is None)


# ----------------------------------------------------------------------------
# Section G — Context: progress reporting + logging
# ----------------------------------------------------------------------------

async def section_g_context_progress() -> None:
    banner("G — Context: progress reporting + logging inside a tool")
    print("A tool that takes a Context-typed parameter gets server-side access")
    print("to MCP capabilities: ctx.info/warning/error (logging),")
    print("ctx.report_progress(progress, total), ctx.read_resource(uri), and")
    print("ctx.sample(...) (LLM round-trip — covered in MCP_CONTEXT_SAMPLING).")
    print("The host subscribes via call_tool(..., progress_handler=cb).\n")

    progress_log: list[tuple[float, float]] = []

    async def handler(progress: float, total: float,
                      message: str | None = None) -> None:
        progress_log.append((progress, total))

    async with Client(mcp) as c:
        result = await c.call_tool("with_progress", {"n": 3},
                                   progress_handler=handler)

    print(f"result.data            = {result.data!r}")
    print(f"progress_handler saw   = {progress_log}")
    print()
    print("Context has these capabilities (dir):")
    ctx_caps = ["info", "debug", "warning", "error", "report_progress",
                "read_resource", "sample", "request_id", "session_id"]
    for cap in ctx_caps:
        print(f"  ctx.{cap}")
    print()

    check("the tool returned 'done' after reporting progress",
          result.data == "done")
    check("the host saw 4 progress updates (0/3, 1/3, 2/3, 3/3)",
          progress_log == [(0.0, 3.0), (1.0, 3.0), (2.0, 3.0), (3.0, 3.0)])
    check("Context exposes report_progress, info, sample",
          all(hasattr(Context, m) for m in
              ("report_progress", "info", "sample")))


# ----------------------------------------------------------------------------
# Section H — contrast with LangChain @tool: wire protocol vs in-process
# ----------------------------------------------------------------------------

def section_h_contrast_langchain() -> None:
    banner("H — Contrast with LangChain @tool: wire protocol vs in-process")
    print("Same idea (fn -> JSON-Schema -> model-invokable), DIFFERENT layer:")
    print("LangChain @tool wraps a fn into a BaseTool (a Runnable) used IN the")
    print("agent's process — bind_tools -> .invoke() is a Python call. MCP")
    print("@mcp.tool wraps a fn into a tool EXPOSED OVER THE WIRE — tools/list")
    print("and tools/call are JSON-RPC messages, so the host and server may")
    print("live in different processes or machines.\n")

    from langchain_core.tools import BaseTool, tool as lc_tool

    @lc_tool
    def add_lc(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    print(f"{'aspect':<26}{'LangChain @tool':<32}{'MCP @mcp.tool'}")
    print("-" * 90)
    print(f"{'wraps fn into':<26}{'BaseTool (Runnable)':<32}{'FunctionTool'}")
    print(f"{'schema source':<26}{'type hints + docstring':<32}"
          f"{'type hints + docstring'}")
    print(f"{'invocation':<26}{'tool.invoke({args})':<32}"
          f"{'await c.call_tool(name, {args})'}")
    print(f"{'transport':<26}{'in-process Python call':<32}"
          f"{'JSON-RPC over stdio/http/SSE/in-memory'}")
    print(f"{'where the fn runs':<26}{'same process as agent':<32}"
          f"{'server process (often remote)'}")
    print(f"{'result shape':<26}{'the python return value':<32}"
          f"{'CallToolResult (.content/.data/.is_error)'}")
    print(f"{'errors':<26}{'raise ToolException -> caught':<32}"
          f"{'raised -> result with is_error=True'}")
    print()

    check("LC @tool yields a BaseTool", isinstance(add_lc, BaseTool))
    check("LC tool name == 'add_lc' (the full function name)",
          add_lc.name == "add_lc")
    check("LC description == 'Add two numbers.' (from the docstring)",
          add_lc.description == "Add two numbers.")
    check("LC tool.invoke({'a':2,'b':3}) == 5  (in-process)",
          add_lc.invoke({"a": 2, "b": 3}) == 5)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

async def _async_main() -> None:
    await section_a_decorator()
    await section_b_input_schema()
    await section_c_pydantic_arg()
    await section_d_call_tool_result()
    await section_e_content_vs_structured()
    await section_f_errors_as_results()
    await section_g_context_progress()


def main() -> None:
    import fastmcp

    print("mcp_tools.py — Phase 8 bundle #51.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed. OFFLINE: the client uses\n"
          "FastMCP's in-memory transport (Client(mcp)) — no HTTP, no socket,\n"
          "no API key, byte-reproducible.\n"
          f"fastmcp {fastmcp.__version__} on this machine.")
    asyncio.run(_async_main())
    section_h_contrast_langchain()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
