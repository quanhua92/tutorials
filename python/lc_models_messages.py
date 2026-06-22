"""
lc_models_messages.py — Phase 6 bundle #36.

GOAL (one line): show, by printing every value, how LangChain chat models are
Runnables with a UNIFORM invoke/stream/batch interface and message-typed input
and output — all demonstrated OFFLINE with FakeMessagesListChatModel.

This is the GROUND TRUTH for LC_MODELS_MESSAGES.md. Every value, type, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

OFFLINE / NO API KEY: every call uses FakeMessagesListChatModel from
langchain_core.language_models.fake_chat_models, which returns canned AIMessages
deterministically. No real provider is contacted; no API key is read; no network
is touched. The SAME code shape works for ChatOpenAI / ChatAnthropic — just swap
the model class. That swap-in-place uniformity is the whole point of the
Runnable interface.

Run:
    uv run python lc_models_messages.py
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

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
# Section A — message types: SystemMessage / HumanMessage / AIMessage / ToolMessage
# ----------------------------------------------------------------------------

def section_a_message_types() -> None:
    banner("A — Message types: System/Human/AI/Tool; .type, .content, .tool_calls")
    print("LangChain's unified message format (python.langchain.com/docs/concepts/")
    print("messages): every message has a ROLE and CONTENT. Each subclass maps to a")
    print("role; .type exposes the role string; AIMessage adds .tool_calls and")
    print(".usage_metadata (both empty by default).\n")

    rows = [
        ("SystemMessage", SystemMessage(content="You are a helpful assistant.")),
        ("HumanMessage", HumanMessage(content="What is 2+2?")),
        ("AIMessage", AIMessage(content="2 + 2 = 4")),
        ("ToolMessage", ToolMessage(content="4", tool_call_id="call_1")),
    ]
    print(f"{'class':<16}{'type':<10}{'content'}")
    print("-" * 56)
    for name, m in rows:
        print(f"{name:<16}{m.type:<10}{m.content!r}")
    print()
    ai = AIMessage(content="a")
    print(f"AIMessage.tool_calls        = {ai.tool_calls}")
    print(f"AIMessage.invalid_tool_calls= {ai.invalid_tool_calls}")
    print(f"AIMessage.usage_metadata    = {ai.usage_metadata}")
    print()

    check("SystemMessage.type == 'system'",
          SystemMessage(content="s").type == "system")
    check("HumanMessage.type == 'human'",
          HumanMessage(content="h").type == "human")
    check("AIMessage.type == 'ai'",
          AIMessage(content="a").type == "ai")
    check("ToolMessage.type == 'tool'",
          ToolMessage(content="t", tool_call_id="x").type == "tool")
    check("AIMessage.tool_calls defaults to []",
          AIMessage(content="a").tool_calls == [])
    check("AIMessage.usage_metadata defaults to None",
          AIMessage(content="a").usage_metadata is None)


# ----------------------------------------------------------------------------
# Section B — model.invoke(...) with FakeMessagesListChatModel
# ----------------------------------------------------------------------------

def section_b_invoke_with_fake_model() -> None:
    banner("B — model.invoke([...messages]) with FakeMessagesListChatModel")
    print("A chat model is a Runnable. .invoke takes a list of messages and returns")
    print("ONE AIMessage. Here the model is FakeMessagesListChatModel — it returns a")
    print("canned AIMessage regardless of input. Swap 'FakeMessagesListChatModel' for")
    print("'ChatOpenAI'/'ChatAnthropic' and the SAME line runs against a real model.\n")

    model = FakeMessagesListChatModel(
        responses=[AIMessage(content="hi there")]
    )
    out = model.invoke([HumanMessage(content="hello")])

    print(f"type(model).__name__ = {type(model).__name__}")
    print(f"type(out).__name__   = {type(out).__name__}")
    print(f"out.type             = {out.type!r}")
    print(f"out.content          = {out.content!r}")
    print()

    check("model.invoke returns an AIMessage", isinstance(out, AIMessage))
    check("out.content == 'hi there' (canned response)",
          out.content == "hi there")
    check("out.type == 'ai'", out.type == "ai")


# ----------------------------------------------------------------------------
# Section C — the Runnable interface: invoke / batch / stream
# ----------------------------------------------------------------------------

def section_c_runnable_interface() -> None:
    banner("C — The Runnable interface: invoke / batch / stream")
    print("The Runnable contract (python.langchain.com/docs/concepts/runnables/) is")
    print("UNIFORM across chat models, chains, output parsers, retrievers, and")
    print("compiled LangGraph graphs:\n")
    print("  invoke(input)           -> single output")
    print("  batch([in1, in2, ...])  -> list of outputs (parallel; threadpool)")
    print("  stream(input)           -> generator yielding output chunks")
    print()
    print("Below: ONE canned AIMessage is reused for every call, so batch's parallel")
    print("ordering cannot perturb the captured output.\n")

    single = AIMessage(content="ack")
    model = FakeMessagesListChatModel(responses=[single])

    one = model.invoke([HumanMessage(content="ping")])
    print(f"invoke(...)  -> {type(one).__name__}, content={one.content!r}")

    many = model.batch([
        [HumanMessage(content="q1")],
        [HumanMessage(content="q2")],
        [HumanMessage(content="q3")],
    ])
    print(f"batch([...3]) -> {type(many).__name__}, len={len(many)}, "
          f"contents={[m.content for m in many]}")

    chunks = list(model.stream([HumanMessage(content="stream me")]))
    print(f"stream(...)  -> {len(chunks)} chunk(s); first chunk class="
          f"{type(chunks[0]).__name__}, content={chunks[0].content!r}")
    print("(Real models yield AIMessageChunk tokens; the fake has no _stream")
    print(" override, so BaseChatModel.stream falls back to the full message.)\n")

    from langchain_core.messages import BaseMessage

    check("invoke returns an AIMessage", isinstance(one, AIMessage))
    check("batch returns a list", isinstance(many, list))
    check("batch returns 3 outputs (one per input)", len(many) == 3)
    check("every batch output is an AIMessage",
          all(isinstance(m, AIMessage) for m in many))
    check("stream yields >=1 chunk", len(chunks) >= 1)
    check("stream chunk is a BaseMessage",
          isinstance(chunks[0], BaseMessage))


# ----------------------------------------------------------------------------
# Section D — a conversation is a list of messages (chat history)
# ----------------------------------------------------------------------------

def section_d_conversation_as_message_list() -> None:
    banner("D — A conversation is a list of messages (chat history)")
    print("invoke() takes the WHOLE conversation as a list — system prompt, prior")
    print("turns, tool results — and the model sees every message in order. Below we")
    print("hand it a 4-message history; the fake model ignores the contents but the")
    print("interface accepts the full list and returns a fresh AIMessage.\n")

    convo = [
        SystemMessage(content="You are a concise tutor."),
        HumanMessage(content="What is a Runnable?"),
        AIMessage(content="A uniform interface: invoke/batch/stream."),
        HumanMessage(content="Give me a one-line example."),
    ]
    model = FakeMessagesListChatModel(
        responses=[AIMessage(content="model.invoke([HumanMessage('hi')])")]
    )
    out = model.invoke(convo)

    print(f"{'#':<3}{'type':<10}{'content'}")
    print("-" * 60)
    for i, m in enumerate(convo):
        print(f"{i:<3}{m.type:<10}{m.content!r}")
    print()
    print(f"len(history) = {len(convo)}")
    print(f"out.type     = {out.type!r}")
    print(f"out.content  = {out.content!r}")
    print()

    check("history has 4 messages", len(convo) == 4)
    check("history[0] is the SystemMessage", isinstance(convo[0], SystemMessage))
    check("history[-1] is a HumanMessage", isinstance(convo[-1], HumanMessage))
    check("invoke over a 4-message history still returns an AIMessage",
          isinstance(out, AIMessage))


# ----------------------------------------------------------------------------
# Section E — content: a string OR a list of content blocks
# ----------------------------------------------------------------------------

def section_e_content_string_vs_blocks() -> None:
    banner("E — content: a string OR a list of content blocks")
    print("message.content is usually a Python str. For multimodal or structured")
    print("content it can also be a LIST of blocks (text / image / tool_use / ...).")
    print("The exact block shape is provider-specific; LangChain passes it through.\n")

    text_msg = HumanMessage(content="What color is the sky?")
    blocks_msg = HumanMessage(content=[
        {"type": "text", "text": "Describe this image:"},
        {"type": "image", "source_type": "url",
         "url": "https://example.com/sky.png"},
    ])

    print(f"text_msg.content     = {text_msg.content!r}")
    print(f"                       (type={type(text_msg.content).__name__})")
    print(f"blocks_msg.content   = {blocks_msg.content!r}")
    print(f"                       (type={type(blocks_msg.content).__name__}, "
          f"{len(blocks_msg.content)} blocks)")
    print(f"block[0]['type']     = {blocks_msg.content[0]['type']!r}")
    print(f"block[1]['type']     = {blocks_msg.content[1]['type']!r}")
    print()

    check("string content has type str", isinstance(text_msg.content, str))
    check("block content has type list", isinstance(blocks_msg.content, list))
    check("blocks_msg has 2 content blocks", len(blocks_msg.content) == 2)
    check("first block is a text block",
          blocks_msg.content[0]["type"] == "text")


# ----------------------------------------------------------------------------
# Section F — why a fake model: offline, deterministic, key-free
# ----------------------------------------------------------------------------

def section_f_why_fake_model() -> None:
    banner("F — Why a fake model: offline, deterministic, key-free")
    print("FakeMessagesListChatModel is a BaseChatModel subclass that returns a")
    print("canned response list. Properties that make it the right tool here:\n")
    print("  * DETERMINISTIC: same responses list -> same output, byte-for-byte.")
    print("  * OFFLINE:       no network, no provider, no API key, no rate limit.")
    print("  * UNIFORM:       it implements the SAME Runnable methods as")
    print("                   ChatOpenAI / ChatAnthropic — invoke/batch/stream.")
    print("  * SWAP-IN SAFE:  tests written against the fake pass unchanged when")
    print("                   you swap in a real model behind the same interface.")
    print()
    print("Real providers add: real text generation, token-level streaming,")
    print("usage_metadata from the API, and live tool-calling. The Runnable contract")
    print("above stays identical — that is why the fake is a faithful test double.\n")

    model = FakeMessagesListChatModel(responses=[AIMessage(content="ok")])
    is_runnable = (hasattr(model, "invoke") and hasattr(model, "batch")
                   and hasattr(model, "stream"))
    print(f"has invoke/batch/stream: {is_runnable}")
    print(f"_llm_type               = {model._llm_type!r}")
    print()

    check("FakeMessagesListChatModel exposes invoke/batch/stream",
          is_runnable)
    check("FakeMessagesListChatModel is a BaseChatModel subclass",
          any(c.__name__ == "BaseChatModel"
              for c in type(model).__mro__))


# ----------------------------------------------------------------------------
# Section G — AIMessage.tool_calls: the model decides to call a tool
# ----------------------------------------------------------------------------

def section_g_aimessage_tool_calls() -> None:
    banner("G — AIMessage.tool_calls: the model decides to call a tool")
    print("An AIMessage can carry .tool_calls — a list of {name, args, id, type}")
    print("dicts the model produced instead of (or alongside) plain text. With a real")
    print("tool-calling model this is how agents hand off to tools; with the fake")
    print("model we CANNED one to assert the parsing shape. (🔗 LC_TOOLS_AGENTS.)\n")

    canned = AIMessage(
        content="",
        tool_calls=[{
            "name": "get_weather",
            "args": {"city": "San Francisco", "units": "metric"},
            "id": "call_abc123",
        }],
    )
    model = FakeMessagesListChatModel(responses=[canned])
    out = model.invoke([HumanMessage(content="Weather in SF?")])

    print(f"len(out.tool_calls)      = {len(out.tool_calls)}")
    tc = out.tool_calls[0]
    print(f"tool_call keys           = {sorted(tc.keys())}")
    print(f"tc['type']               = {tc['type']!r}")
    print(f"tc['name']               = {tc['name']!r}")
    print(f"tc['args']               = {tc['args']!r}")
    print(f"tc['id']                 = {tc['id']!r}")
    print(f"out.invalid_tool_calls   = {out.invalid_tool_calls}")
    print()

    check("invoke returns an AIMessage carrying tool_calls",
          isinstance(out, AIMessage) and len(out.tool_calls) == 1)
    check("tool_call has 'name' key", "name" in tc)
    check("tool_call has 'args' key", "args" in tc)
    check("tool_call name is 'get_weather'", tc["name"] == "get_weather")
    check("tool_call args.city == 'San Francisco'",
          tc["args"]["city"] == "San Francisco")
    check("parsed tool_call carries 'type' == 'tool_call'",
          tc.get("type") == "tool_call")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("lc_models_messages.py — Phase 6 bundle #36.\n"
          "Every value below is printed by this file; the .md guide pastes it\n"
          "verbatim. OFFLINE: FakeMessagesListChatModel only — no network/API key.\n"
          f"Python {__import__('sys').version.split()[0]}, "
          f"langchain_core {__import__('langchain_core').__version__}.")
    section_a_message_types()
    section_b_invoke_with_fake_model()
    section_c_runnable_interface()
    section_d_conversation_as_message_list()
    section_e_content_string_vs_blocks()
    section_f_why_fake_model()
    section_g_aimessage_tool_calls()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
