"""
mcp_resources_prompts.py — Bundle #52 (Phase 8).

GOAL (one line): show, by printing every value, that MCP has THREE primitives —
tools (actions), resources (URI-addressed read-only DATA), and prompts
(parametrized prompt TEMPLATES) — and how to pick the right one.

This is the GROUND TRUTH for MCP_RESOURCES_PROMPTS.md. Every URI, message, and
[check] in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

No network, no transport. Everything is driven through FastMCP's in-memory
Client over the server object — fully deterministic and byte-reproducible.

Run:
    uv run python mcp_resources_prompts.py
"""

from __future__ import annotations

import asyncio
import json

from fastmcp import Client, FastMCP
from fastmcp.prompts import Message

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers (house style, copied from the style anchor)
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
# ONE FastMCP server — resources, a resource template, prompts, and a tool,
# all declared up front so every section reads from the same object.
# ----------------------------------------------------------------------------

mcp = FastMCP("ThreePrimitives")

# --- resources (URI-addressed read-only DATA) -------------------------------


@mcp.resource("config://app")
def get_config() -> str:
    """The application configuration (read-only context)."""
    return json.dumps({"theme": "dark", "version": "1.0"})


@mcp.resource("logs://tail")
def tail_log() -> str:
    """The last few log lines."""
    return "[INFO] boot\n[INFO] ready"


@mcp.resource("users://{uid}/profile")
def user_profile(uid: str) -> str:
    """A user profile, addressed by the {uid} baked into the URI."""
    return json.dumps({"uid": uid, "name": f"user-{uid}", "active": True})


@mcp.resource("metrics://q1", mime_type="application/json")
def q1_metrics() -> dict:
    """Quarterly metrics returned as structured data (auto JSON-encoded)."""
    return {"quarter": "Q1", "revenue": 1000, "users": 42}


# --- prompts (parametrized instruction TEMPLATES) ---------------------------


@mcp.prompt
def code_review(language: str, code: str) -> str:
    """Review source code for bugs and style."""
    return f"Review this {language} for bugs and style:\n{code}"


@mcp.prompt
def summarize(text: str, tone: str = "neutral") -> list:
    """Summarize text in a given tone (multi-message template)."""
    return [
        Message(f"Summarize the following in a {tone} tone."),
        Message(text),
    ]


# --- a tool (an ACTION the model invokes; may have side effects) ------------

sent: list[str] = []


@mcp.tool
def send_email(to: str, body: str) -> str:
    """Send an email — an action with a side effect."""
    sent.append(f"{to}: {body}")
    return f"sent to {to}"


# ----------------------------------------------------------------------------
# Section A — @mcp.resource: list_resources + read_resource
# ----------------------------------------------------------------------------

async def section_a_resource_basics(client: Client) -> None:
    banner("A — @mcp.resource: list_resources + read_resource")
    print("A resource is DATA the server exposes, addressed by a URI. The host")
    print("discovers it via list_resources and reads it via read_resource. It is")
    print("read-only CONTEXT the host attaches to the conversation.\n")

    resources = sorted(await client.list_resources(), key=lambda r: str(r.uri))
    print(f"{'uri':<20}{'name':<14}{'mimeType'}")
    print("-" * 44)
    for r in resources:
        print(f"{str(r.uri):<20}{r.name:<14}{r.mimeType}")
    print()

    contents = await client.read_resource("config://app")
    text = contents[0].text
    print(f"read_resource('config://app') -> {text!r}\n")

    uris = {str(r.uri) for r in resources}
    check("config://app appears in list_resources", "config://app" in uris)
    check("read_resource returns the JSON config blob",
          json.loads(text) == {"theme": "dark", "version": "1.0"})


# ----------------------------------------------------------------------------
# Section B — URI addressing: resource (DATA, by URI) vs tool (ACTION, by name)
# ----------------------------------------------------------------------------

async def section_b_resource_vs_tool(client: Client) -> None:
    banner("B — URI addressing: resource=DATA by URI vs tool=ACTION by name")
    print("Resources are DATA keyed by URI (read-only, host-attached). Tools are")
    print("ACTIONS keyed by NAME (model-invoked, may have side effects). The two")
    print("live in SEPARATE namespaces: list_resources != list_tools.\n")

    tools = await client.list_tools()
    tool_names = {t.name for t in tools}
    res_uris = {str(r.uri) for r in await client.list_resources()}
    print(f"list_tools()      -> {sorted(tool_names)}")
    print(f"list_resources()  -> {sorted(res_uris)}\n")

    result = await client.call_tool("send_email",
                                    {"to": "bob", "body": "hi"})
    print(f"call_tool('send_email', ...) -> {result.content[0].text!r}")
    print(f"side-effect log `sent`       -> {sent}\n")

    check("send_email is a TOOL (in list_tools)", "send_email" in tool_names)
    check("send_email is NOT a resource (not in list_resources)",
          "send_email" not in res_uris)
    check("config://app is a RESOURCE (in list_resources)",
          "config://app" in res_uris)
    check("calling the tool produced a side effect (sent grew)",
          sent == ["bob: hi"])


# ----------------------------------------------------------------------------
# Section C — resource templates: a URI with variables
# ----------------------------------------------------------------------------

async def section_c_resource_templates(client: Client) -> None:
    banner("C — Resource templates: a URI with {variables}")
    print("A resource TEMPLATE has {var} placeholders in the URI. It does NOT")
    print("appear in list_resources — it appears in list_resource_templates, and")
    print("the client reads a CONCRETE instance by filling in the variable.\n")

    templates = await client.list_resource_templates()
    for t in templates:
        print(f"uriTemplate={t.uriTemplate!r}  name={t.name!r}")
    res_uris = {str(r.uri) for r in await client.list_resources()}
    print(f"\ntemplate uri 'users://{{uid}}/profile' in list_resources? "
          f"{'users://{uid}/profile' in res_uris}\n")

    for uid in ("42", "7"):
        contents = await client.read_resource(f"users://{uid}/profile")
        print(f"read_resource('users://{uid}/profile') -> {contents[0].text}")

    print()
    tmpl = templates[0]
    check("the template appears in list_resource_templates",
          str(tmpl.uriTemplate) == "users://{uid}/profile")
    check("the template does NOT appear in list_resources (it is a factory)",
          "users://{uid}/profile" not in res_uris)
    p42 = json.loads((await client.read_resource("users://42/profile"))[0].text)
    p7 = json.loads((await client.read_resource("users://7/profile"))[0].text)
    check("uid=42 instance carries uid 42", p42["uid"] == "42")
    check("uid=7 instance carries uid 7 (the URI variable parameterized it)",
          p7["uid"] == "7")


# ----------------------------------------------------------------------------
# Section D — @mcp.prompt: list_prompts + get_prompt
# ----------------------------------------------------------------------------

async def section_d_prompt_basics(client: Client) -> None:
    banner("D — @mcp.prompt: list_prompts + get_prompt")
    print("A prompt is a reusable, server-authored instruction TEMPLATE the host")
    print("surfaces. list_prompts publishes them; get_prompt renders one with")
    print("arguments. Parameters with defaults are optional.\n")

    prompts = sorted(await client.list_prompts(), key=lambda p: p.name)
    print(f"published prompts (sorted): {[p.name for p in prompts]}\n")
    for p in prompts:
        print(f"{p.name}")
        print(f"  description: {p.description or '-'}")
        print("  arguments:   "
              + ", ".join(f"{a.name} "
                          f"({'required' if a.required else 'optional'})"
                          for a in p.arguments))
    print()

    pr = await client.get_prompt(
        "code_review", {"language": "python", "code": "x = 1"})
    print(f"get_prompt('code_review', ...) -> {len(pr.messages)} message(s)\n")

    check("code_review appears in list_prompts",
          "code_review" in {p.name for p in prompts})
    check("summarize appears in list_prompts",
          "summarize" in {p.name for p in prompts})
    cr_args = {a.name: a.required
               for a in next(p for p in prompts
                             if p.name == "code_review").arguments}
    check("code_review args: language & code both required",
          cr_args == {"language": True, "code": True})


# ----------------------------------------------------------------------------
# Section E — rendered prompt: string -> 1 user msg; list[Message] -> N msgs
# ----------------------------------------------------------------------------

async def section_e_rendered_messages(client: Client) -> None:
    banner("E — Rendered prompt: a prompt returns a list of messages")
    print("A prompt function may return a str (auto-wrapped as ONE user message)")
    print("or a list[Message] (a multi-message conversation). get_prompt returns")
    print("a GetPromptResult whose .messages carry role + content.\n")

    cr = await client.get_prompt(
        "code_review", {"language": "python", "code": "x = 1"})
    print("code_review (returned a str):")
    for m in cr.messages:
        print(f"  role={m.role!r}  text={m.content.text!r}")

    sz = await client.get_prompt(
        "summarize", {"text": "MCP has three primitives.", "tone": "wry"})
    print("\nsummarize (returned a list[Message]):")
    for m in sz.messages:
        print(f"  role={m.role!r}  text={m.content.text!r}")
    print()

    check("str-returning prompt -> exactly one message", len(cr.messages) == 1)
    check("that message has role 'user'", cr.messages[0].role == "user")
    check("that message text embeds both args",
          cr.messages[0].content.text
          == "Review this python for bugs and style:\nx = 1")
    check("list-returning prompt -> two messages", len(sz.messages) == 2)
    check("summarize second message carries the source text",
          sz.messages[1].content.text == "MCP has three primitives.")


# ----------------------------------------------------------------------------
# Section F — when a prompt beats a tool
# ----------------------------------------------------------------------------

async def section_f_prompt_vs_tool(client: Client) -> None:
    banner("F — When a prompt beats a tool (the expert move)")
    print("TOOL   = a CAPABILITY the model drives for side-effects/data-fetch")
    print("         (send_email, query_db). The model decides when to call it.")
    print("PROMPT = a RECIPE the server authors and the host surfaces to the")
    print('         user/model ("code review", "summarize"). It injects')
    print("         STRUCTURE/instructions, not a capability.\n")

    before = len(sent)
    cr = await client.get_prompt(
        "code_review", {"language": "python", "code": "x = 1"})
    print(f"get_prompt('code_review') -> {cr.messages[0].content.text!r}")
    print(f"  side-effect log `sent` unchanged? {len(sent) == before}\n")

    r = await client.call_tool("send_email", {"to": "carol", "body": "yo"})
    print(f"call_tool('send_email')   -> {r.content[0].text!r}")
    print(f"  side-effect log `sent` grew?     {len(sent) > before}\n")

    check("getting a prompt has NO side effect", len(sent) == before + 1)
    check("calling a tool HAS a side effect (sent now has carol)",
          sent[-1] == "carol: yo")
    check("the prompt injected an instruction (not a capability)",
          cr.messages[0].content.text.startswith("Review this"))


# ----------------------------------------------------------------------------
# Section G — the three-primitives contrast table (printed, not hand-typed)
# ----------------------------------------------------------------------------

def section_g_contrast_table() -> None:
    banner("G — The three primitives: tools vs resources vs prompts")
    rows = [
        ("tools", "ACTION / capability", "name",
         "model (LLM)", "yes (may)", "tools/list, tools/call",
         "@mcp.tool"),
        ("resources", "read-only DATA", "URI",
         "host/app attaches", "no", "resources/list, resources/read",
         '@mcp.resource("uri")'),
        ("prompts", "instruction TEMPLATE", "name",
         "user/host surfaces", "no", "prompts/list, prompts/get",
         "@mcp.prompt"),
    ]
    headers = ("primitive", "what it is", "keyed by",
               "triggered by", "side fx", "MCP methods", "decorator")
    widths = [9, 20, 10, 18, 9, 26, 20]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers).rstrip())
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt.format(*row).rstrip())
    print()


# ----------------------------------------------------------------------------
# Section H — MIME types / structured resources
# ----------------------------------------------------------------------------

async def section_h_mime_and_structure(client: Client) -> None:
    banner("H — MIME types & structured resource contents")
    print("A resource may declare a mime_type and return structured data. A str")
    print("defaults to text/plain; a dict/list is JSON-encoded and can be tagged")
    print("application/json so the host knows how to render it.\n")

    cfg = (await client.read_resource("config://app"))[0]
    met = (await client.read_resource("metrics://q1"))[0]
    print(f"{'uri':<18}{'mimeType':<22}{'text'}")
    print("-" * 66)
    print(f"{str(cfg.uri):<18}{cfg.mimeType:<22}{cfg.text}")
    print(f"{str(met.uri):<18}{met.mimeType:<22}{met.text}")
    print()

    check("str resource defaults to text/plain", cfg.mimeType == "text/plain")
    check("metrics resource is tagged application/json",
          met.mimeType == "application/json")
    check("metrics text parses back to the structured dict",
          json.loads(met.text) == {"quarter": "Q1", "revenue": 1000,
                                   "users": 42})


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

async def main() -> None:
    import fastmcp

    print("mcp_resources_prompts.py — Phase 8 bundle #52.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]}, "
          f"FastMCP {fastmcp.__version__}.")
    async with Client(mcp) as client:
        await section_a_resource_basics(client)
        await section_b_resource_vs_tool(client)
        await section_c_resource_templates(client)
        await section_d_prompt_basics(client)
        await section_e_rendered_messages(client)
        await section_f_prompt_vs_tool(client)
    section_g_contrast_table()
    async with Client(mcp) as client:
        await section_h_mime_and_structure(client)
    banner("DONE — all sections printed")


if __name__ == "__main__":
    asyncio.run(main())
