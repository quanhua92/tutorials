"""
lc_tools_agents.py — Phase 6 bundle #41.

GOAL (one line): show, by printing every value, how `@tool` turns a Python
function into a JSON-schema'd callable, how `bind_tools` exposes those schemas
to a chat model, and how an agent loops model → tool_calls → ToolMessage →
model until it emits a final answer — all demonstrated OFFLINE with a
FakeMessagesListChatModel seeded with canned AIMessages carrying .tool_calls.

This is the GROUND TRUTH for LC_TOOLS_AGENTS.md. Every value, type, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

OFFLINE / NO API KEY: every "model" below is a FakeMessagesListChatModel that
returns canned AIMessage objects (some carrying .tool_calls), cycling through
its `responses` list. No network, no key, byte-reproducible. A real
tool-calling model (ChatOpenAI / ChatAnthropic) would EMIT the .tool_calls
itself; the fake lets us inject the canned ones to assert the parsing +
dispatch + loop shape deterministically.

NOTE on bind_tools: BaseChatModel.bind_tools is abstract (raises
NotImplementedError); real providers override it to translate tool schemas into
their wire format and return a RunnableBinding. FakeMessagesListChatModel does
NOT override it, so we subclass it below and delegate to bind(tools=...),
which is exactly the generic Runnable.bind the real overrides build on. The
KEY property asserted (bind_tools returns a Runnable) is therefore faithful.

Run:
    uv run python lc_tools_agents.py
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool, ToolException, tool

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


class _ToolCallingFakeModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel that implements bind_tools.

    The base FakeMessagesListChatModel inherits the abstract bind_tools from
    BaseChatModel (which raises NotImplementedError). Real chat models
    translate the tool schemas into the provider wire format and return a
    RunnableBinding wrapping the model. For the OFFLINE bundle we only need
    bind_tools to (a) accept tools and (b) return a Runnable — the fake model
    ignores them when generating (we feed canned responses). So we delegate to
    the generic Runnable.bind(tools=...), which is the building block the real
    overrides use. This keeps the asserted shape (Runnable with .invoke)
    faithful to a real bind_tools call.
    """

    def bind_tools(  # type: ignore[override]
        self, tools: list[BaseTool], **kwargs: object
    ) -> Runnable:
        return self.bind(tools=tools, **kwargs)


# ----------------------------------------------------------------------------
# Section A — @tool decorator: a function -> a BaseTool with an auto schema
# ----------------------------------------------------------------------------

@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def section_a_tool_decorator() -> None:
    banner("A — @tool decorator: function -> BaseTool with an auto schema")
    print("@tool wraps a Python function into a StructuredTool (subclass of")
    print("BaseTool, which is a Runnable). It AUTO-DERIVES the tool's schema")
    print("from the function: name <- function name, description <- docstring,")
    print("args <- type-hinted parameters as a Pydantic model (args_schema).\n")

    print(f"{'expression':<48}{'value'}")
    print("-" * 72)
    print(f"{'add.name':<48}{add.name!r}")
    print(f"{'add.description':<48}{add.description!r}")
    print(f"{'type(add).__name__':<48}{type(add).__name__}")
    print(f"{'isinstance(add, BaseTool)':<48}{isinstance(add, BaseTool)}")
    print(f"{'isinstance(add, Runnable)':<48}{isinstance(add, Runnable)}")
    print(f"{'add.args_schema.__name__':<48}{add.args_schema.__name__!r}")
    print(f"{'list(add.args_schema.model_fields)':<48}"
          f"{list(add.args_schema.model_fields)}")
    print(f"{'a annotation':<48}{add.args_schema.model_fields['a'].annotation}")
    print(f"{'b annotation':<48}{add.args_schema.model_fields['b'].annotation}")
    print(f"{'add.args (JSON schema dict)':<48}{add.args}")
    print()

    check("add.name == 'add' (from the function name)", add.name == "add")
    check("add.description == 'Add two numbers.' (from the docstring)",
          add.description == "Add two numbers.")
    check("add is a BaseTool (and a Runnable)",
          isinstance(add, BaseTool) and isinstance(add, Runnable))
    check("args_schema is a Pydantic model with fields a, b",
          list(add.args_schema.model_fields) == ["a", "b"])
    check("a and b are typed int (from the type hints)",
          add.args_schema.model_fields["a"].annotation is int
          and add.args_schema.model_fields["b"].annotation is int)
    check("add.args JSON schema marks a, b as integer",
          add.args["a"]["type"] == "integer"
          and add.args["b"]["type"] == "integer")


# ----------------------------------------------------------------------------
# Section B — tool.invoke({...args...}): execute the wrapped function
# ----------------------------------------------------------------------------

def section_b_invoke_by_args_dict() -> None:
    banner("B — tool.invoke({'a': 2, 'b': 3}) executes the wrapped function")
    print("A tool is a Runnable: invoke() takes an args DICT (validated against")
    print("args_schema) and returns the function's return value. Below: 2 + 3.\n")

    result = add.invoke({"a": 2, "b": 3})
    print(f"add.invoke({{'a': 2, 'b': 3}}) -> {result!r}  "
          f"(type={type(result).__name__})")
    print(f"add.invoke({{'a': 10, 'b': -4}}) -> {add.invoke({'a': 10, 'b': -4})!r}")
    print()

    check("add.invoke({'a':2,'b':3}) == 5", result == 5)
    check("result has type int (the function's return type)",
          type(result) is int)
    check("add.invoke({'a':10,'b':-4}) == 6",
          add.invoke({"a": 10, "b": -4}) == 6)


# ----------------------------------------------------------------------------
# Section C — bind_tools: attach tool schemas to the model
# ----------------------------------------------------------------------------

def section_c_bind_tools() -> None:
    banner("C — model.bind_tools([add]) -> a Runnable that knows the tool")
    print("bind_tools([...]) attaches tool schemas to the model. Real chat")
    print("models translate the schemas into the provider's tool-call format")
    print("and return a RunnableBinding; on subsequent .invoke() calls the")
    print("model MAY emit AIMessages with .tool_calls. The fake model can't")
    print("translate schemas (it has no provider), but bind_tools STILL returns")
    print("a Runnable — we feed canned tool_calls by hand in Section F.\n")

    model = _ToolCallingFakeModel(responses=[AIMessage(content="ack")])
    bound = model.bind_tools([add])

    print(f"{'expression':<40}{'value'}")
    print("-" * 64)
    print(f"{'type(bound).__name__':<40}{type(bound).__name__}")
    print(f"{'isinstance(bound, Runnable)':<40}{isinstance(bound, Runnable)}")
    print(f"{'bound.kwargs keys':<40}{list(bound.kwargs.keys())}")
    print(f"{'bound tools':<40}{[t.name for t in bound.kwargs['tools']]}")
    out = bound.invoke([HumanMessage(content="ping")])
    print(f"{'bound.invoke(...).content':<40}{out.content!r}")
    print()

    check("bind_tools returns a Runnable", isinstance(bound, Runnable))
    check("the bound runnable carries the tool by name",
          [t.name for t in bound.kwargs["tools"]] == ["add"])
    check("bound.invoke still returns an AIMessage (canned)",
          isinstance(out, AIMessage) and out.content == "ack")


# ----------------------------------------------------------------------------
# Section D — AIMessage.tool_calls + ToolMessage keyed by tool_call_id
# ----------------------------------------------------------------------------

def section_d_tool_calls_and_tool_message() -> None:
    banner("D — AIMessage.tool_calls + ToolMessage keyed by tool_call_id")
    print("A tool-calling model returns an AIMessage whose .tool_calls is a list")
    print("of {name, args, id, type} dicts (type is always 'tool_call'). Each id")
    print("is a unique handle; the matching ToolMessage echoes it in")
    print("tool_call_id so the model can pair request with result.\n")

    canned = AIMessage(
        content="",
        tool_calls=[{
            "name": "add",
            "args": {"a": 2, "b": 3},
            "id": "call_1",
            "type": "tool_call",
        }],
    )
    tc = canned.tool_calls[0]
    print(f"AIMessage.tool_calls[0] keys = {sorted(tc.keys())}")
    for k in ("name", "args", "id", "type"):
        print(f"  tc[{k!r}] = {tc[k]!r}")
    tm = ToolMessage(content="5", tool_call_id="call_1")
    print(f"\nToolMessage.type          = {tm.type!r}")
    print(f"ToolMessage.content       = {tm.content!r}")
    print(f"ToolMessage.tool_call_id  = {tm.tool_call_id!r}")
    print()

    check("tool_call has keys name, args, id, type",
          set(tc.keys()) == {"name", "args", "id", "type"})
    check("tool_call type is always 'tool_call'", tc["type"] == "tool_call")
    check("tool_call name == 'add'", tc["name"] == "add")
    check("tool_call args == {'a':2,'b':3}", tc["args"] == {"a": 2, "b": 3})
    check("ToolMessage.type == 'tool'", tm.type == "tool")
    check("ToolMessage echoes the tool_call_id", tm.tool_call_id == "call_1")


# ----------------------------------------------------------------------------
# Section E — executing a tool call: dispatch by name, build the ToolMessage
# ----------------------------------------------------------------------------

def section_e_execute_tool_call() -> None:
    banner("E — Executing a tool call: dispatch by name -> ToolMessage")
    print("Given an AIMessage.tool_calls entry, the agent: (1) looks up the tool")
    print("by name in a registry, (2) invokes it with .args, (3) wraps the")
    print("result string into a ToolMessage keyed by .id. Below: the full round")
    print("trip for one tool_call.\n")

    registry: dict[str, BaseTool] = {add.name: add}
    tc = {"name": "add", "args": {"a": 2, "b": 3}, "id": "call_1",
          "type": "tool_call"}
    result = registry[tc["name"]].invoke(tc["args"])
    tm = ToolMessage(content=str(result), tool_call_id=tc["id"])

    print(f"registry           = {{name: tool}}  ->  {list(registry)}")
    print(f"tc['name']         = {tc['name']!r}")
    print(f"tc['args']         = {tc['args']}")
    print(f"invoke result      = {result!r}  (type={type(result).__name__})")
    print(f"ToolMessage.content      = {tm.content!r}")
    print(f"ToolMessage.tool_call_id = {tm.tool_call_id!r}")
    print()

    check("registry lookup by name returns the add tool",
          registry[tc["name"]].name == "add")
    check("dispatch + invoke returns 5", result == 5)
    check("the ToolMessage content is str(result)", tm.content == "5")
    check("the ToolMessage id matches the tool_call id",
          tm.tool_call_id == tc["id"])


# ----------------------------------------------------------------------------
# Section F — the agent loop: model -> tool_calls? -> execute -> repeat
# ----------------------------------------------------------------------------

def section_f_agent_loop() -> None:
    banner("F — The agent loop: model -> tool_calls? -> execute -> repeat")
    print("The agent loop, in one sentence: invoke the model; if its AIMessage")
    print("carries tool_calls, execute each, append ToolMessages, and re-invoke;")
    print("otherwise return the AIMessage's content as the final answer.\n")

    print("Seed: responses = [AIMessage(tool_calls=[add(2,3)]),")
    print("                       AIMessage(content='The sum is 5')]")
    print()

    model = _ToolCallingFakeModel(responses=[
        AIMessage(
            content="",
            tool_calls=[{"name": "add", "args": {"a": 2, "b": 3},
                         "id": "call_1", "type": "tool_call"}],
        ),
        AIMessage(content="The sum is 5"),
    ])
    registry: dict[str, BaseTool] = {add.name: add}
    messages: list = [HumanMessage(content="What is 2 + 3?")]

    n_rounds = 0
    n_tool_calls = 0
    final: str | None = None
    print(f"{'step':<6}{'role':<10}{'content':<22}{'tool_calls'}")
    print("-" * 64)
    print(f"{'init':<6}{'human':<10}{messages[0].content!r:<22}")
    while True:
        n_rounds += 1
        resp = model.invoke(messages)
        messages.append(resp)
        if resp.tool_calls:
            print(f"{'L' + str(n_rounds):<6}{'ai':<10}{resp.content!r:<22}"
                  f"{[(tc['name'], tc['args']) for tc in resp.tool_calls]}")
            for tc in resp.tool_calls:
                result = registry[tc["name"]].invoke(tc["args"])
                n_tool_calls += 1
                tm = ToolMessage(content=str(result), tool_call_id=tc["id"])
                messages.append(tm)
                print(f"{'T' + str(n_rounds):<6}{'tool':<10}{tm.content!r:<22}"
                      f"id={tm.tool_call_id!r}")
        else:
            print(f"{'L' + str(n_rounds):<6}{'ai':<10}{resp.content!r:<22}[]")
            final = resp.content
            break
    print()

    check("the loop produced a final answer", final is not None)
    check("final answer is 'The sum is 5'", final == "The sum is 5")
    check("exactly one tool round-trip happened (1 tool_call executed)",
          n_tool_calls == 1)
    check("the loop took 2 model invocations (call + final)", n_rounds == 2)
    final_msg = messages[-1]
    check("the last message is the final AIMessage with no tool_calls",
          isinstance(final_msg, AIMessage) and not final_msg.tool_calls)
    check("a ToolMessage sits between the two AIMessages",
          isinstance(messages[-2], ToolMessage))


# ----------------------------------------------------------------------------
# Section G — tool errors + the modern prebuilt agent
# ----------------------------------------------------------------------------

@tool
def divide(a: int, b: int) -> float:
    """Divide a by b."""
    if b == 0:
        raise ToolException("division by zero")
    return a / b


def section_g_tool_errors_and_prebuilt() -> None:
    banner("G — Tool errors -> feed back as a ToolMessage; the prebuilt agent")
    print("A tool may raise ToolException. The agent catches it and feeds the")
    print("ERROR STRING back as a ToolMessage (same tool_call_id) so the model")
    print("can recover — e.g. retry with different args. Below we simulate the")
    print("error path of one round.\n")

    registry: dict[str, BaseTool] = {divide.name: divide}
    tc = {"name": "divide", "args": {"a": 1, "b": 0}, "id": "call_err",
          "type": "tool_call"}
    try:
        registry[tc["name"]].invoke(tc["args"])
        error_text = "<no error>"
    except ToolException as exc:
        error_text = f"Error: {exc}"
    tm = ToolMessage(content=error_text, tool_call_id=tc["id"])
    print(f"tc['args']               = {tc['args']}")
    print(f"caught ToolException text = {error_text!r}")
    print(f"ToolMessage.content       = {tm.content!r}")
    print(f"ToolMessage.tool_call_id  = {tm.tool_call_id!r}")
    print()

    check("divide raises ToolException on b=0",
          error_text == "Error: division by zero")
    check("the error becomes a ToolMessage keyed by tool_call_id",
          tm.tool_call_id == "call_err" and "Error:" in tm.content)

    print("The modern API: LangGraph ships a prebuilt tool-calling agent that")
    print("RUNS this exact loop as a graph (model node <-> tools node, edge on")
    print("'has tool_calls?'). In the installed langgraph it is exposed as")
    print("create_react_agent (a.k.a. chat_agent_executor); the latest LangChain")
    print("concepts docs rename it create_agent. The legacy AgentExecutor is")
    print("phased out. Tools are the universal contract — the same @tool works")
    print("across all of them and across MCP (🔗 MCP_TOOLS, P8 #51).")
    print()

    try:
        from langgraph.prebuilt import create_react_agent  # noqa: F401
        prebuilt_available = True
    except ImportError:
        prebuilt_available = False
    check("langgraph.prebuilt.create_react_agent is importable",
          prebuilt_available)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    import langchain_core

    print("lc_tools_agents.py — Phase 6 bundle #41.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed. OFFLINE: the model is a\n"
          "FakeMessagesListChatModel seeded with canned AIMessages that carry\n"
          ".tool_calls (no network, no API key).\n"
          f"langchain-core {langchain_core.__version__} on this machine.")
    section_a_tool_decorator()
    section_b_invoke_by_args_dict()
    section_c_bind_tools()
    section_d_tool_calls_and_tool_message()
    section_e_execute_tool_call()
    section_f_agent_loop()
    section_g_tool_errors_and_prebuilt()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
