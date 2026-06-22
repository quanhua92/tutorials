"""
lc_prompts.py — Bundle #37 (Phase 6).

GOAL (one line): show, by printing every value, how LangChain's
ChatPromptTemplate / PromptTemplate turn free-form f-string prompt text into a
typed, reusable, composable runnable: variables, partial pre-fills, few-shot
examples, MessagesPlaceholder, and a Pydantic schema for structured output.

This is the GROUND TRUTH for LC_PROMPTS.md. Every value, message list, and
[check] in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

OFFLINE: template formatting needs NO model. The only model used is
FakeMessagesListChatModel, which never touches the network and needs no API
key. Real with_structured_output behavior (tool/function calling) is explained
in §F alongside the offline check.

Run:
    uv run python lc_prompts.py
"""

from __future__ import annotations

import json

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    PromptTemplate,
)
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field

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


def dump_messages(messages: list) -> None:
    """Pretty-print a list of BaseMessage as `Role: content` lines."""
    role_of = {
        "SystemMessage": "system",
        "HumanMessage": "human",
        "AIMessage": "ai",
    }
    for m in messages:
        role = role_of.get(type(m).__name__, type(m).__name__)
        print(f"  {role:<7}: {m.content}")


# ----------------------------------------------------------------------------
# Section A — ChatPromptTemplate.from_messages + variable substitution
# ----------------------------------------------------------------------------

def section_a_chat_prompt_template() -> None:
    banner("A — ChatPromptTemplate.from_messages + variable substitution")
    print("from_messages takes (role, template) tuples. {topic} is a VARIABLE:")
    print("at .invoke time it is substituted into the human message. The return")
    print("is a ChatPromptValue (NOT a string) — a typed message list ready to")
    print("feed a chat model.\n")

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful assistant."),
        ("user", "Tell me a joke about {topic}."),
    ])

    print(f"prompt.input_variables = {prompt.input_variables}\n")

    value = prompt.invoke({"topic": "cats"})
    print(f"type(value)               = {type(value).__name__}")
    print(f"value.to_string()         = {value.to_string()!r}")
    print("value.to_messages():")
    dump_messages(value.to_messages())
    print()

    check("invoke returns a ChatPromptValue", type(value).__name__ == "ChatPromptValue")
    check("two messages rendered (system + human)", len(value.to_messages()) == 2)
    human_msg = value.to_messages()[1]
    check("{topic} substituted to 'cats'",
          human_msg.content == "Tell me a joke about cats.")
    check("first message is the system message",
          type(value.to_messages()[0]).__name__ == "SystemMessage")
    check("second message is a HumanMessage",
          type(human_msg).__name__ == "HumanMessage")


# ----------------------------------------------------------------------------
# Section B — missing variable: a clear, early error
# ----------------------------------------------------------------------------

def section_b_missing_variable() -> None:
    banner("B — Missing variable: template raises instead of silently passing {x}")
    print("A plain f-string would leave '{topic}' in the output if you forgot it.")
    print("A ChatPromptTemplate raises a clear KeyError naming the missing var,")
    print("so the bug is caught at the template boundary, not downstream.\n")

    prompt = ChatPromptTemplate.from_messages([
        ("user", "Tell me a joke about {topic}."),
    ])

    raised = None
    try:
        prompt.invoke({})
    except KeyError as exc:
        raised = exc

    print(f"prompt.invoke({{}}) raised: {type(raised).__name__}")
    err_text = str(raised)
    print(f"  message: {err_text.splitlines()[0]}\n")

    check("missing var raises KeyError", isinstance(raised, KeyError))
    check("error names the missing variable 'topic'", "topic" in err_text)
    check("error lists Expected: ['topic']", "Expected: ['topic']" in err_text)


# ----------------------------------------------------------------------------
# Section C — partial: pre-fill some vars, defer the rest
# ----------------------------------------------------------------------------

def section_c_partial() -> None:
    banner("C — partial(): pre-fill some vars -> a template with fewer remaining")
    print(".partial(**prefilled) returns a NEW ChatPromptTemplate with those vars")
    print("baked in. The returned template has a SHORTER input_variables list, so")
    print("you can hand it to a sub-pipeline that only knows the rest of the vars.\n")

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a {role}."),
        ("user", "Explain {topic} to me."),
    ])
    print(f"original.input_variables = {prompt.input_variables}")

    teacher = prompt.partial(role="teacher")
    print(f"partial.input_variables  = {teacher.input_variables}")
    print("(role is gone — only topic remains)\n")

    value = teacher.invoke({"topic": "fractions"})
    print("teacher.invoke({'topic':'fractions'}) ->")
    dump_messages(value.to_messages())
    print()

    check("original has both vars", set(prompt.input_variables) == {"role", "topic"})
    check("partial removed 'role' from input_variables",
          "role" not in teacher.input_variables)
    check("partial kept 'topic' in input_variables",
          "topic" in teacher.input_variables)
    sys_msg = value.to_messages()[0]
    check("{role} substituted to 'teacher'",
          sys_msg.content == "You are a teacher.")
    check("{topic} substituted at invoke time",
          value.to_messages()[1].content == "Explain fractions to me.")


# ----------------------------------------------------------------------------
# Section D — PromptTemplate (single string) vs ChatPromptTemplate (messages)
# ----------------------------------------------------------------------------

def section_d_string_vs_chat() -> None:
    banner("D — PromptTemplate (string) vs ChatPromptTemplate (message list)")
    print("PromptTemplate is a SINGLE-STRING template. .invoke returns a")
    print("StringPromptValue (one string). Use it for plain-text LLMs (the legacy")
    print("string-in/string-out LLM API) or when you only need one rendered string.\n")
    print("ChatPromptTemplate is a MESSAGE-LIST template. .invoke returns a")
    print("ChatPromptValue (a list of typed messages). Use it for every chat model")
    print("(system/human/ai roles) and for any prompt | model | parser pipeline.\n")

    string_prompt = PromptTemplate.from_template("Translate: {sentence}")
    chat_prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a translator."),
        ("user", "Translate: {sentence}"),
    ])

    s = string_prompt.invoke({"sentence": "hola"})
    c = chat_prompt.invoke({"sentence": "hola"})

    print(f"PromptTemplate.invoke   -> {type(s).__name__}: {s.to_string()!r}")
    print(f"ChatPromptTemplate.invoke -> {type(c).__name__}")
    dump_messages(c.to_messages())
    print()

    check("PromptTemplate.invoke returns StringPromptValue",
          type(s).__name__ == "StringPromptValue")
    check("StringPromptValue.to_string() is a plain string",
          isinstance(s.to_string(), str))
    check("ChatPromptTemplate.invoke returns ChatPromptValue",
          type(c).__name__ == "ChatPromptValue")
    check("ChatPromptValue yields 2 messages (system + human)",
          len(c.to_messages()) == 2)
    check("both share the same {sentence} variable substitution",
          "Translate: hola" in s.to_string()
          and c.to_messages()[1].content == "Translate: hola")


# ----------------------------------------------------------------------------
# Section E — few-shot: bake Human/AI example pairs into the template
# ----------------------------------------------------------------------------

def section_e_few_shot() -> None:
    banner("E — Few-shot: example (human, ai) pairs inside the template")
    print("Few-shot prompting = include worked input/output examples IN the")
    print("template so the model sees the pattern before answering. In LangChain")
    print("this is just interleaving literal ('human', ...) / ('ai', ...) tuples")
    print("ahead of the real ('human', '{input}') slot. Variables in the example")
    print("tuples are NOT counted as input_variables — they are fixed text.\n")

    prompt = ChatPromptTemplate.from_messages([
        ("system", "Classify the sentiment as 'positive' or 'negative'."),
        ("human", "I love this product!"),
        ("ai", "positive"),
        ("human", "This broke on day one."),
        ("ai", "negative"),
        ("human", "{input}"),
    ])

    print(f"prompt.input_variables = {prompt.input_variables}")
    print("(only {input} is a real variable; the example texts are fixed)\n")

    value = prompt.invoke({"input": "It works as advertised."})
    print(f"rendered message count: {len(value.to_messages())}  "
          "(system + 2 example pairs + 1 real query)")
    dump_messages(value.to_messages())
    print()

    check("only 'input' is an input variable (examples are not)",
          prompt.input_variables == ["input"])
    check("rendered 6 messages: 1 system + 4 example + 1 query",
          len(value.to_messages()) == 6)
    check("example AIMessage 'positive' is preserved verbatim",
          value.to_messages()[2].content == "positive")
    check("example AIMessage 'negative' is preserved verbatim",
          value.to_messages()[4].content == "negative")
    check("{input} substituted into the final human message",
          value.to_messages()[5].content == "It works as advertised.")


# ----------------------------------------------------------------------------
# Section F — with_structured_output: a Pydantic schema binds a tool/function
# ----------------------------------------------------------------------------

class FactOut(BaseModel):
    """Schema for a fact + a confidence score. With a real chat model,
    with_structured_output(FactOut) binds this as a tool the model must call,
    and the runnable returns a *parsed* FactOut instance (not free text)."""

    fact: str = Field(description="A factual statement.")
    confidence: float = Field(description="Confidence score in [0.0, 1.0].")


def section_f_structured_output() -> None:
    banner("F — with_structured_output(Schema): bind a Pydantic schema to a model")
    print("model.with_structured_output(Schema) returns a NEW runnable that")
    print("returns a *parsed* object (Pydantic instance / TypedDict / dict) instead")
    print("of an AIMessage string. Internally (for OpenAI/Anthropic/etc.) it binds")
    print("the schema as a tool the model is FORCED to call, then parses the tool")
    print("call args into the schema. Below: the schema, the bound tool, and the")
    print("fake-model caveat.\n")

    print(f"FactOut.model_fields = {list(FactOut.model_fields)}")
    schema = FactOut.model_json_schema()
    print(f"JSON Schema 'required' = {schema.get('required')}")
    print(f"JSON Schema 'properties.fact.type' = "
          f"{schema['properties']['fact']['type']}\n")

    tool = convert_to_openai_tool(FactOut)
    print("convert_to_openai_tool(FactOut) — what a real model would be bound to:")
    print(json.dumps(tool, indent=2))
    print()

    fake = FakeMessagesListChatModel(
        responses=[AIMessage(content='{"fact":"sky is blue","confidence":0.9}')]
    )
    check("model exposes with_structured_output",
          hasattr(fake, "with_structured_output") and callable(fake.with_structured_output))

    bound = None
    raised = None
    try:
        bound = fake.with_structured_output(FactOut)
    except NotImplementedError as exc:
        raised = exc

    if bound is not None:
        print(f"fake.with_structured_output(FactOut) returned: {type(bound).__name__}")
    else:
        print("fake.with_structured_output(FactOut) raised: NotImplementedError")
        print(f"  msg: {raised}")
        print("  -> the FakeMessagesListChatModel inherits the base stub; a real")
        print("     chat model (e.g. ChatOpenAI) binds the tool, parses the call,")
        print("     and returns FactOut(fact=..., confidence=...). Demonstrated by")
        print("     the schema + the tool above; the parsing path needs a real model.")
    print()

    check("FactOut has fields fact, confidence",
          set(FactOut.model_fields) == {"fact", "confidence"})
    check("JSON schema marks both fields required",
          set(schema.get("required", [])) == {"fact", "confidence"})
    check("confidence has type 'number' in JSON schema",
          schema["properties"]["confidence"]["type"] == "number")
    check("convert_to_openai_tool emits a 'function' tool wrapper",
          tool.get("type") == "function"
          and "function" in tool
          and tool["function"]["name"] == "FactOut")


# ----------------------------------------------------------------------------
# Section G — MessagesPlaceholder: inject a dynamic list of messages
# ----------------------------------------------------------------------------

def section_g_messages_placeholder() -> None:
    banner("G — MessagesPlaceholder: inject a dynamic list of messages (history)")
    print("MessagesPlaceholder('name') reserves a slot into which you pass an")
    print("ARBITRARY list of BaseMessage at invoke time. The classic use is chat")
    print("history: the system message + injected history + the new user question")
    print("all render into one message list. (History usually lives in memory ->")
    print("see LC_MEMORY.)\n")

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful assistant."),
        MessagesPlaceholder("history"),
        ("human", "{question}"),
    ])

    print(f"prompt.input_variables = {prompt.input_variables}")
    history = [
        HumanMessage(content="What is 2+2?"),
        AIMessage(content="4."),
    ]
    print(f"history passed = {[type(m).__name__ for m in history]}")
    print()

    value = prompt.invoke({"history": history, "question": "And 3+3?"})
    print(f"rendered message count: {len(value.to_messages())}  "
          "(system + 2 history + 1 question)")
    dump_messages(value.to_messages())
    print()

    check("input_variables includes 'history' and 'question'",
          set(prompt.input_variables) == {"history", "question"})
    check("rendered 4 messages (system + 2 history + 1 question)",
          len(value.to_messages()) == 4)
    rendered = value.to_messages()
    check("history HumanMessage preserved verbatim",
          rendered[1].content == "What is 2+2?")
    check("history AIMessage preserved verbatim",
          rendered[2].content == "4.")
    check("{question} substituted into the final human message",
          rendered[3].content == "And 3+3?")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("lc_prompts.py — Phase 6 bundle #37.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed. Runs offline (FakeMessagesListChatModel;\n"
          "no network, no API key).\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_chat_prompt_template()
    section_b_missing_variable()
    section_c_partial()
    section_d_string_vs_chat()
    section_e_few_shot()
    section_f_structured_output()
    section_g_messages_placeholder()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
