"""
lc_langgraph.py — Bundle #42 (Phase 6).

GOAL (one line): show, by printing every value, how LangGraph models an agent as
a STATE MACHINE — a TypedDict `State`, pure-function `nodes` that return a PATCH,
`edges` (incl. conditional routing) connecting them, and the `add_messages`
reducer that accumulates the conversation — the bridge from linear LCEL chains
to real stateful, cyclic agents.

This is the GROUND TRUTH for LC_LANGGRAPH.md. Every graph, call order, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

OFFLINE / NO API KEY: the chat model is a `FakeMessagesListChatModel` that
returns canned `AIMessage`s in order. No network, no key, byte-reproducible.

Run:
    uv run python lc_langgraph.py
"""

from __future__ import annotations

import operator
from typing import Annotated

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict, get_type_hints

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


def _fmt(msg: object) -> str:
    """Format a message without its random id() / UUID (non-deterministic)."""
    name = type(msg).__name__
    content = getattr(msg, "content", "")
    tcs = getattr(msg, "tool_calls", None)
    extra = f" tool_calls={tcs!r}" if tcs else ""
    return f"{name}({content!r}{extra})"


# ----------------------------------------------------------------------------
# Section A — the State schema: a TypedDict + the add_messages reducer
# ----------------------------------------------------------------------------

class State(TypedDict):
    """The shared state of a chat graph.

    `messages` is annotated with `add_messages`, so each node's update APPENDS
    to the list (and de-dupes by id). Without the annotation, every update
    would OVERWRITE the previous list.
    """

    messages: Annotated[list, add_messages]
    count: int


def section_a_state_schema() -> None:
    banner("A — State schema: TypedDict + the add_messages reducer")
    print("A graph is parameterized by ONE State schema. Each key may carry a")
    print("REDUCER (a binary (old, new) -> merged). With no reducer, updates")
    print("OVERWRITE; with `add_messages`, list updates APPEND (and replace by")
    print("id). A node never returns the whole state — only a PATCH.\n")

    hints = get_type_hints(State, include_extras=True)
    msg_meta = hints["messages"].__metadata__  # type: ignore[attr-defined]
    print("State (TypedDict) fields:")
    print(f"  messages: Annotated[list, add_messages]  (id={msg_meta[0].__name__!r})")
    print("  count   : int   (no reducer -> overwrites)\n")

    builder = StateGraph(State)
    check("StateGraph(State) constructs (schema compiles)",
          builder is not None)
    check("messages annotation carries the add_messages reducer",
          add_messages in msg_meta)
    check("count has no reducer (default = overwrite)",
          "count" in get_type_hints(State) and not hasattr(
              hints["count"], "__metadata__"))


# ----------------------------------------------------------------------------
# Section B — a node is a function: State -> PATCH (partial state)
# ----------------------------------------------------------------------------

def greet(state: State) -> dict:
    """A node returns a PATCH — only the keys it wants to update."""
    return {"messages": [AIMessage("hi")], "count": state.get("count", 0) + 1}


def section_b_node_returns_patch() -> None:
    banner("B — A node is a function: State -> PATCH (partial state)")
    print("A node is a plain function. Its signature is State -> Partial[State].")
    print("It does NOT return the whole state — only the keys it changes. The")
    print("graph's REDUCERS merge the patch into the shared state.\n")

    patch = greet({"messages": [HumanMessage("hello")], "count": 0})
    print("greet({messages:[HumanMessage('hello')], count:0})")
    print(f"  -> {patch}\n"
          f"     (a PARTIAL dict — only 'messages' and 'count', no schema)\n")

    check("greet() returns a dict (the patch)", isinstance(patch, dict))
    check("patch contains the 'messages' key", "messages" in patch)
    check("patch['count'] is 1 (incremented)", patch["count"] == 1)
    check("the patch is NOT the whole state (no 'foo', no extras)",
          set(patch) <= {"messages", "count"})


# ----------------------------------------------------------------------------
# Section C — edges START -> node -> END; compile + invoke
# ----------------------------------------------------------------------------

def section_c_edges_compile_invoke() -> None:
    banner("C — Edges START -> node -> END; compile() + invoke()")
    print("START and END are special virtual nodes. add_edge(START, x) marks x")
    print("as the entry; add_edge(x, END) marks x as a finish. compile() turns")
    print("the builder into a runnable; invoke(input) runs once and returns the")
    print("final state.\n")

    builder = StateGraph(State)
    builder.add_node("greet", greet)
    builder.add_edge(START, "greet")
    builder.add_edge("greet", END)
    app = builder.compile()

    out = app.invoke({"messages": [HumanMessage("hello")], "count": 0})
    print("app.invoke({messages:[HumanMessage('hello')], count:0})")
    print(f"  -> type={type(out).__name__}")
    print(f"     messages = [{_fmt(out['messages'][0])}, "
          f"{_fmt(out['messages'][1])}]")
    print(f"     count    = {out['count']}\n")

    check("invoke returns a dict", isinstance(out, dict))
    check("the node ran (count incremented to 1)", out["count"] == 1)
    check("the final state has the node's AIMessage",
          any(isinstance(m, AIMessage) and m.content == "hi"
              for m in out["messages"]))


# ----------------------------------------------------------------------------
# Section D — the add_messages reducer appends (final state grows)
# ----------------------------------------------------------------------------

def section_d_reducer_appends() -> None:
    banner("D — The add_messages reducer APPENDS (final messages grow)")
    print("Because `messages: Annotated[list, add_messages]`, each node's")
    print("returned messages are APPENDED to the running list (not overwriting")
    print("it). Input of 1 Human -> node returns 1 AIMessage -> final list has")
    print("BOTH, len == 2.\n")

    builder = StateGraph(State)
    builder.add_node("greet", greet)
    builder.add_edge(START, "greet")
    builder.add_edge("greet", END)
    app = builder.compile()

    out = app.invoke({"messages": [HumanMessage("hello")], "count": 0})
    n_in = 1
    n_out = len(out["messages"])
    types = [type(m).__name__ for m in out["messages"]]
    print(f"input  messages len = {n_in}  ([HumanMessage])")
    print(f"output messages len = {n_out}  ({types})")
    print("the input HumanMessage is PRESERVED and the node's AIMessage is")
    print("APPENDED — that is what the reducer buys you.\n")

    check("output messages len grew from 1 to 2", n_out == 2)
    check("first message is the input HumanMessage",
          isinstance(out["messages"][0], HumanMessage))
    check("second message is the node's AIMessage",
          isinstance(out["messages"][1], AIMessage))


# ----------------------------------------------------------------------------
# Section E — conditional routing: the router function picks the next node
# ----------------------------------------------------------------------------

class BranchState(TypedDict):
    go: str
    ran: Annotated[list[str], operator.add]


def _noop(state: BranchState) -> dict:  # noqa: ARG001
    return {}


def _node_a(state: BranchState) -> dict:  # noqa: ARG001
    return {"ran": ["A"]}


def _node_b(state: BranchState) -> dict:  # noqa: ARG001
    return {"ran": ["B"]}


def _router(state: BranchState) -> str:
    """A routing function returns the NAME of the next node."""
    return "nodeA" if state["go"] == "a" else "nodeB"


def _build_branch_graph() -> object:
    builder = StateGraph(BranchState)
    builder.add_node("decide", _noop)
    builder.add_node("nodeA", _node_a)
    builder.add_node("nodeB", _node_b)
    builder.add_edge(START, "decide")
    builder.add_conditional_edges(
        "decide", _router, {"nodeA": "nodeA", "nodeB": "nodeB"},
    )
    builder.add_edge("nodeA", END)
    builder.add_edge("nodeB", END)
    return builder.compile()


def section_e_conditional_routing() -> None:
    banner("E — Conditional routing: the router function picks a branch")
    print("add_conditional_edges(node, router, mapping) calls router(state)")
    print("after `node` runs; its return value (a node NAME) selects the next")
    print("node. The mapping {key: nodeName} translates the router's output.\n")

    app = _build_branch_graph()
    ra = app.invoke({"go": "a", "ran": []})
    rb = app.invoke({"go": "b", "ran": []})
    print(f'go="a" -> ran = {ra["ran"]}')
    print(f'go="b" -> ran = {rb["ran"]}\n')

    check('go="a" routed to nodeA (ran == ["A"])', ra["ran"] == ["A"])
    check('go="b" routed to nodeB (ran == ["B"])', rb["ran"] == ["B"])


# ----------------------------------------------------------------------------
# Section F — a loop agent (offline): call_model -> should_continue -> tools
# ----------------------------------------------------------------------------

@tool
def get_weather(city: str) -> str:
    """Return a deterministic fake weather string for `city`."""
    return f"{city}: 22C"


def _build_loop_agent() -> object:
    """A tool-calling agent graph, fully offline."""
    fake = FakeMessagesListChatModel(responses=[
        AIMessage(
            content="",
            tool_calls=[{
                "name": "get_weather", "args": {"city": "Paris"}, "id": "c1",
            }],
        ),
        AIMessage(content="Paris is 22C"),
    ])

    def call_model(state: State) -> dict:
        return {"messages": [fake.invoke(state["messages"])]}

    def should_continue(state: State) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    def call_tools(state: State) -> dict:
        last = state["messages"][-1]
        msgs = []
        for tc in last.tool_calls:
            content = get_weather.invoke(tc["args"])
            msgs.append(ToolMessage(
                content=str(content), tool_call_id=tc["id"], name=tc["name"],
            ))
        return {"messages": msgs}

    builder = StateGraph(State)
    builder.add_node("call_model", call_model)
    builder.add_node("call_tools", call_tools)
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges(
        "call_model", should_continue, {"tools": "call_tools", END: END},
    )
    builder.add_edge("call_tools", "call_model")  # the CYCLE back
    return builder.compile()


def section_f_loop_agent() -> None:
    banner("F — A loop agent (offline): call_model -> tools -> call_model")
    print("This is the bridge from chains to agents. A conditional edge lets")
    print("the graph LOOP: call_model -> should_continue -> tools -> back to")
    print("call_model. should_continue inspects the latest AIMessage; if it")
    print("has tool_calls, route to 'tools'; else route to END. The cycle is")
    print("what no linear LCEL chain can express.\n")

    app = _build_loop_agent()
    result = app.invoke({"messages": [HumanMessage("weather in Paris?")]})

    print("Trace (final state messages):")
    for m in result["messages"]:
        print(f"  - {_fmt(m)}")
    print()

    last = result["messages"][-1]
    check("the loop terminated (did not recurse forever)",
          isinstance(last, AIMessage))
    check("the final AIMessage has the tool's answer",
          getattr(last, "content", "") == "Paris is 22C")
    check("a full tool round-trip happened (4 messages: H, AI(tool), Tool, AI)",
          len(result["messages"]) == 4)
    check("message #3 is the ToolMessage produced by call_tools",
          isinstance(result["messages"][2], ToolMessage))


# ----------------------------------------------------------------------------
# Section G — compile / invoke / stream + checkpointing (conceptual)
# ----------------------------------------------------------------------------

class CountState(TypedDict):
    messages: Annotated[list, add_messages]
    turns: Annotated[int, operator.add]


def _say_hi(state: CountState) -> dict:
    return {"messages": [AIMessage("hi")], "turns": 1}


def section_g_stream_and_checkpointing() -> None:
    banner("G — compile() -> a runnable; invoke / stream; checkpointing")
    print("compile() returns a runnable. invoke() returns the FINAL state;")
    print("stream() yields one chunk per super-step (one per node). Compiling")
    print("with a checkpointer (InMemorySaver / Sqlite / Postgres) persists")
    print("state across invocations on the same thread_id -> enables memory,")
    print("human-in-the-loop, and resumable runs.\n")

    # (1) streaming yields one chunk per super-step
    app = _build_loop_agent()
    steps = [list(chunk.keys())[0] for chunk in app.stream(
        {"messages": [HumanMessage("weather in Paris?")]})]
    print(f"app.stream(...) yielded {len(steps)} super-steps: {steps}\n")

    check("stream yielded more than one super-step (>1 node ran)",
          len(steps) > 1)
    check("stream order is call_model, call_tools, call_model",
          steps == ["call_model", "call_tools", "call_model"])

    # (2) checkpointing: the same thread_id persists state across invokes
    builder = StateGraph(CountState)
    builder.add_node("say_hi", _say_hi)
    builder.add_edge(START, "say_hi")
    builder.add_edge("say_hi", END)
    saver = InMemorySaver()
    ck_app = builder.compile(checkpointer=saver)

    cfg = {"configurable": {"thread_id": "t1"}}
    r1 = ck_app.invoke({"messages": [HumanMessage("hi")], "turns": 0}, cfg)
    r2 = ck_app.invoke({"messages": [HumanMessage("again")], "turns": 0}, cfg)
    print("With checkpointer + thread_id='t1':")
    print(f"  invoke 1 -> turns={r1['turns']}, messages len={len(r1['messages'])}")
    print(f"  invoke 2 -> turns={r2['turns']}, messages len={len(r2['messages'])}")
    print("state ACCUMULATED across invocations on the same thread — the basis")
    print("of memory and human-in-the-loop.\n")

    check("turn 1: turns==1, 2 messages", r1["turns"] == 1
          and len(r1["messages"]) == 2)
    check("turn 2: turns==2 (accumulated via checkpointer)",
          r2["turns"] == 2)
    check("turn 2: 4 messages (Human,AI,Human,AI)", len(r2["messages"]) == 4)


# ----------------------------------------------------------------------------
# Section H — why LangGraph over LCEL: cycles + state + memory + HITL
# ----------------------------------------------------------------------------

def section_h_why_over_lcel() -> None:
    banner("H — Why LangGraph over plain LCEL")
    print("LCEL chains are LINEAR DAGs (a | b | c). Real agents need: cycles")
    print("(call_model <-> tools), shared STATE, MEMORY across turns, and")
    print("HUMAN-IN-THE-LOOP pauses. LangGraph is the explicit state machine\n"
          "that gives you all four. 🔗 LC_TOOLS_AGENTS (#41) shows the agent")
    print("loop; this bundle turns that loop into a graph.\n")

    rows = [
        ("linear a|b|c", "state machine (cycles, branches)"),
        ("Runnable.output passes data", "shared State + per-key reducers"),
        ("one-shot invoke", "invoke + stream + checkpoint"),
        ("no memory", "InMemorySaver / Sqlite / Postgres"),
        ("no pause", "interrupt() + Command(resume=...) for HITL"),
        ("recursion: N/A", "recursion_limit (default 1000)"),
    ]
    print(f"{'LCEL chain':<32}{'LangGraph'}")
    print("-" * 60)
    for lcel, lg in rows:
        print(f"{lcel:<32}{lg}")
    print()

    # Structural proof of a CYCLE: stream the loop agent and confirm a node
    # is visited twice (call_model -> call_tools -> call_model). LCEL chains
    # cannot revisit a step — that is the whole reason LangGraph exists.
    loop = _build_loop_agent()
    steps = [list(c.keys())[0]
             for c in loop.stream({"messages": [HumanMessage("x")]})]
    check("LangGraph supports CYCLES (call_model visited twice)",
          steps.count("call_model") == 2)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("lc_langgraph.py — Phase 6 bundle #42.\n"
          "Every value below is computed by this file; the .md guide pastes\n"
          "it verbatim. Nothing is hand-computed. OFFLINE: the chat model is\n"
          "a FakeMessagesListChatModel (no network, no API key).\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_state_schema()
    section_b_node_returns_patch()
    section_c_edges_compile_invoke()
    section_d_reducer_appends()
    section_e_conditional_routing()
    section_f_loop_agent()
    section_g_stream_and_checkpointing()
    section_h_why_over_lcel()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
