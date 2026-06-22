"""
lc_memory.py — Phase 6 bundle #39.

GOAL (one line): show, by printing every value, that chat history is just a list
of messages, threaded through a MessagesPlaceholder, and that the MODERN pattern
manages that list as explicit per-session state (a dict / DB), while the legacy
"memory classes" (ConversationBufferMemory et al.) are deprecated in favor of
explicit history or LangGraph checkpointed state.

This is the GROUND TRUTH for LC_MEMORY.md. Every value, message list, and
[check] in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

OFFLINE / NO API KEY: the only "model" used is FakeMessagesListChatModel (and a
recording subclass of it), which never touches the network. No API key and NO
langchain_community dependency — the BaseChatMessageHistory subclass below is a
tiny stdlib-only implementation. Byte-reproducible.

Run:
    uv run python lc_memory.py
"""

from __future__ import annotations

import warnings

from langchain_core._api.deprecation import LangChainDeprecationWarning
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory

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


def dump_messages(messages: list) -> None:
    """Pretty-print a list of BaseMessage as `Role: content` lines."""
    role_of = {"SystemMessage": "system", "HumanMessage": "human",
               "AIMessage": "ai"}
    for m in messages:
        role = role_of.get(type(m).__name__, type(m).__name__)
        print(f"  {role:<7}: {m.content}")


# ----------------------------------------------------------------------------
# a recording fake model + a minimal history store
# ----------------------------------------------------------------------------

def make_recording_fake(responses: list[str]):
    """Return (FakeMessagesListChatModel instance, received-list).

    `received` captures the message-list the model saw on each invoke, as
    [(TypeName, content), ...] tuples — so we can assert that the prompt for
    turn 2 contained turn 1's history. The list is closure-captured so every
    instance is isolated from the others.
    """
    received: list = []

    class _Recording(FakeMessagesListChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            received.append([(type(m).__name__, m.content) for m in messages])
            return super()._generate(messages, stop, run_manager=run_manager,
                                     **kwargs)

    model = _Recording(responses=[AIMessage(content=c) for c in responses])
    return model, received


class InMemoryHistory(BaseChatMessageHistory):
    """Minimal stdlib-only BaseChatMessageHistory: one list per session."""

    def __init__(self) -> None:
        self._msgs: list[BaseMessage] = []

    @property
    def messages(self) -> list[BaseMessage]:
        return list(self._msgs)

    def add_message(self, message: BaseMessage) -> None:
        self._msgs.append(message)

    def clear(self) -> None:
        self._msgs = []


PROMPT = ChatPromptTemplate.from_messages([
    ("system", "You are a concise assistant."),
    MessagesPlaceholder("history"),
    ("human", "{question}"),
])


# ----------------------------------------------------------------------------
# Section A — chat history is a list of messages, keyed by session
# ----------------------------------------------------------------------------

def section_a_history_is_a_list() -> None:
    banner("A — Chat history is a list of messages, keyed by session")
    print("A chat model is stateless: each .invoke is independent. Memory = YOU")
    print("keep a list of HumanMessage / AIMessage per conversation. A plain dict")
    print("keyed by session_id is the simplest store.\n")

    sessions: dict[str, list] = {}

    def store_for(session_id: str) -> list:
        return sessions.setdefault(session_id, [])

    store_for("a").append(HumanMessage(content="hi"))
    store_for("a").append(AIMessage(content="hello"))
    store_for("a").append(HumanMessage(content="my name is Sam"))
    print('sessions["a"] after 3 appends:')
    dump_messages(sessions["a"])
    print(f"\nsessions.get('b') = {sessions.get('b', '<missing>')}  ('b' was never touched)\n")

    check("history grows: sessions['a'] has 3 messages", len(sessions["a"]) == 3)
    check("sessions are isolated: 'b' was never created", "b" not in sessions)
    check("first turn is a HumanMessage", type(sessions["a"][0]).__name__ == "HumanMessage")
    check("second turn is an AIMessage", type(sessions["a"][1]).__name__ == "AIMessage")


# ----------------------------------------------------------------------------
# Section B — MessagesPlaceholder renders the history list into the prompt
# ----------------------------------------------------------------------------

def section_b_messages_placeholder() -> None:
    banner("B — MessagesPlaceholder renders the history list into the prompt")
    print("MessagesPlaceholder('history') reserves a slot in a ChatPromptTemplate")
    print("for an arbitrary list of BaseMessage. At invoke time the history list is")
    print("spliced inline — system + history + new question render together.\n")

    print(f"PROMPT.input_variables = {PROMPT.input_variables}")
    history = [
        HumanMessage(content="hi"),
        AIMessage(content="hello"),
        HumanMessage(content="my name is Sam"),
    ]
    rendered = PROMPT.invoke(
        {"history": history, "question": "What is my name?"}
    ).to_messages()
    print(f"rendered message count: {len(rendered)}  (system + 3 history + 1 question)")
    dump_messages(rendered)
    print()

    check("input_variables are history + question",
          set(PROMPT.input_variables) == {"history", "question"})
    check("rendered 5 messages (system + 3 history + 1 question)", len(rendered) == 5)
    check("history[0] ('hi') spliced into the rendered prompt", rendered[1].content == "hi")
    check("history AIMessage ('hello') preserved verbatim", rendered[2].content == "hello")
    check("{question} substituted into the final human turn",
          rendered[4].content == "What is my name?")


# ----------------------------------------------------------------------------
# Section C — manual history loop: append human -> run -> append ai
# ----------------------------------------------------------------------------

def section_c_manual_loop() -> None:
    banner("C — Manual history loop: append human -> run -> append ai")
    print("The explicit, modern pattern in six lines: take (session_id, question),")
    print("append the HumanMessage, run prompt | model with history=prior turns,")
    print("append the AIMessage back. No hidden state, fully testable.\n")

    sessions: dict[str, list] = {}
    model, received = make_recording_fake(
        ["Hi Sam, nice to meet you.", "Your name is Sam."]
    )
    chain = PROMPT | model

    def chat(session_id: str, question: str) -> str:
        store = sessions.setdefault(session_id, [])
        history = list(store)                          # prior turns
        store.append(HumanMessage(content=question))   # record human turn
        out = chain.invoke({"history": history, "question": question})
        store.append(AIMessage(content=out.content))   # record ai turn
        return out.content

    a1 = chat("alice", "I'm Sam.")
    a2 = chat("alice", "Who am I?")
    print(f"chat('alice', \"I'm Sam.\")   -> {a1!r}")
    print(f"chat('alice', \"Who am I?\")  -> {a2!r}")
    print(f"\nsessions['alice'] ({len(sessions['alice'])} messages):")
    dump_messages(sessions["alice"])
    print(f"\nmodel saw on turn 2: {received[1]}")
    print("(system + turn-1 human + turn-1 ai + new human question)\n")

    check("store holds 4 messages after 2 turns (2 human + 2 ai)",
          len(sessions["alice"]) == 4)
    check("turn 2 sent 4 msgs to the model (sys + H1 + AI1 + H2)",
          len(received[1]) == 4)
    check("turn 1's HumanMessage reached the model on turn 2",
          ("HumanMessage", "I'm Sam.") in received[1])
    check("turn 1's AIMessage reached the model on turn 2",
          ("AIMessage", "Hi Sam, nice to meet you.") in received[1])


# ----------------------------------------------------------------------------
# Section D — RunnableWithMessageHistory: auto load -> run -> save
# ----------------------------------------------------------------------------

def section_d_runnable_with_message_history() -> None:
    banner("D — RunnableWithMessageHistory: auto load -> run -> save by session_id")
    print("RunnableWithMessageHistory wraps a runnable + a get_session_history")
    print("factory. On each invoke it: loads history from the store keyed by")
    print("'session_id' in config['configurable'], injects it at history_messages_key,")
    print("runs, then saves the new human+ai turn. Same session_id sees prior turns;")
    print("a different id starts fresh.\n")

    session_store: dict[str, InMemoryHistory] = {}

    def get_session(session_id: str) -> InMemoryHistory:
        if session_id not in session_store:
            session_store[session_id] = InMemoryHistory()
        return session_store[session_id]

    model, received = make_recording_fake([
        "Hi Sam, nice to meet you.",
        "Your name is Sam.",
        "I don't know your name yet.",
    ])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", LangChainDeprecationWarning)
        wrapped = RunnableWithMessageHistory(
            PROMPT | model, get_session,
            input_messages_key="question",
            history_messages_key="history",
        )

    cfg_a = {"configurable": {"session_id": "alice"}}
    cfg_b = {"configurable": {"session_id": "bob"}}
    a1 = wrapped.invoke({"question": "I'm Sam."}, cfg_a)
    a2 = wrapped.invoke({"question": "Who am I?"}, cfg_a)
    b1 = wrapped.invoke({"question": "Who am I?"}, cfg_b)
    print(f"alice turn 1 -> {a1.content!r}")
    print(f"alice turn 2 -> {a2.content!r}   (model saw turn 1)")
    print(f"bob   turn 1 -> {b1.content!r}   (fresh session, never saw 'Sam')\n")

    print(f"session_store['alice'].messages ({len(session_store['alice'].messages)}):")
    dump_messages(session_store["alice"].messages)
    print(f"session_store['bob'].messages ({len(session_store['bob'].messages)}):")
    dump_messages(session_store["bob"].messages)
    print(f"\nmodel saw on alice turn 2: {received[1]}")
    print(f"model saw on bob turn 1:    {received[2]}\n")

    check("same session_id persists: alice store has 4 messages after 2 turns",
          len(session_store["alice"].messages) == 4)
    check("different session_id is isolated: bob store has 2 messages",
          len(session_store["bob"].messages) == 2)
    check("alice turn 2 saw turn 1's human turn",
          ("HumanMessage", "I'm Sam.") in received[1])
    check("alice turn 2 saw turn 1's ai turn",
          ("AIMessage", "Hi Sam, nice to meet you.") in received[1])
    check("bob turn 1 did NOT see alice's history",
          ("HumanMessage", "I'm Sam.") not in received[2])


# ----------------------------------------------------------------------------
# Section E — legacy "memory classes" vs modern explicit history / LangGraph
# ----------------------------------------------------------------------------

def section_e_legacy_vs_modern() -> None:
    banner("E — Legacy 'memory classes' vs modern explicit history / LangGraph")
    print("LangChain 0.0.x shipped ConversationBufferMemory, ConversationSummary-")
    print("Memory, ConversationBufferWindowMemory, ... These are LEGACY: deprecated")
    print("in 0.3.x. They were hidden global state bolted onto a Chain, lacked")
    print("multi-user/multi-session support, and broke with tool-calling chat")
    print("models. Constructing a RunnableWithMessageHistory TODAY literally emits a")
    print("LangChainDeprecationWarning that points you to LangGraph persistence.\n")

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        RunnableWithMessageHistory(
            ChatPromptTemplate.from_messages([("human", "{question}")]),
            lambda sid: InMemoryHistory(),
            input_messages_key="question",
        )

    dep = [w for w in captured if issubclass(w.category, LangChainDeprecationWarning)]
    print(f"deprecation warnings caught on construction: {len(dep)}")
    if dep:
        print(f"  category: {dep[0].category.__name__}")
        print(f"  message : {str(dep[0].message)!r}\n")

    print("Modern path (pick one):")
    print("  1. Explicit history — a dict/DB keyed by session_id + MessagesPlaceholder")
    print("     (Sections A-C). The store is just a list you inspect: testable.")
    print("  2. LangGraph checkpointed state for multi-turn agents — persists ANY")
    print("     state, native multi-user/threads, tool-call compatible. (LC_LANGGRAPH.)\n")

    check("RunnableWithMessageHistory emits LangChainDeprecationWarning", len(dep) >= 1)
    check("warning category is LangChainDeprecationWarning",
          dep[0].category is LangChainDeprecationWarning)
    check("warning text points to LangGraph persistence", "LangGraph" in str(dep[0].message))


# ----------------------------------------------------------------------------
# Section F — bounded / windowed history to cap token cost
# ----------------------------------------------------------------------------

def section_f_bounded_history() -> None:
    banner("F — Bounded history: keep the last N messages to cap token cost")
    print("Every saved turn is re-sent on the next invoke, so history grows without")
    print("bound and eventually blows the context window. The fix is a WINDOW: keep")
    print("only the last N messages (a transparent slice), or use langchain's")
    print("trim_messages helper for a token-budget cut.\n")

    history = [
        HumanMessage(content="q1"), AIMessage(content="a1"),
        HumanMessage(content="q2"), AIMessage(content="a2"),
        HumanMessage(content="q3"), AIMessage(content="a3"),
    ]
    print(f"full history ({len(history)} messages, 3 turns):")
    dump_messages(history)

    window = 2
    windowed = history[-window:]
    print(f"\nhistory[-{window}:] (keep last {window} messages):")
    dump_messages(windowed)
    print()

    check("window trims 6 messages down to 2", len(windowed) == 2)
    check("window keeps the most recent turn (q3 + a3)",
          [m.content for m in windowed] == ["q3", "a3"])
    check("window discards the oldest turn (q1, a1)",
          "q1" not in [m.content for m in windowed])

    rendered = PROMPT.invoke(
        {"history": windowed, "question": "q4"}
    ).to_messages()
    print(f"prompt.invoke(history=windowed, question='q4') -> {len(rendered)} messages")
    print("(system + 2 windowed + 1 new question = 4)\n")

    check("windowed history renders 4 messages (system + 2 + 1)", len(rendered) == 4)
    check("oldest turns never reach the prompt",
          "q1" not in [m.content for m in rendered])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    import langchain_core

    print("lc_memory.py — Phase 6 bundle #39.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed. OFFLINE: the model is a\n"
          "FakeMessagesListChatModel subclass (no network, no API key).\n"
          f"langchain-core {langchain_core.__version__} on this machine.")
    section_a_history_is_a_list()
    section_b_messages_placeholder()
    section_c_manual_loop()
    section_d_runnable_with_message_history()
    section_e_legacy_vs_modern()
    section_f_bounded_history()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
