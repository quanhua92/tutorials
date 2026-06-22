"""
lc_chains_lcel.py — Phase 6 bundle #38.

GOAL (one line): show, by printing every value, how the LangChain Expression
Language (LCEL) composes Runnables with the pipe `|` so that
`prompt | model | parser` is a chain you can invoke/stream/batch uniformly —
and how RunnablePassthrough / RunnableLambda / RunnableParallel are the glue.

This is the GROUND TRUTH for LC_CHAINS_LCEL.md. Every number, type name, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

OFFLINE / NO API KEY: every "model" below is a FakeMessagesListChatModel that
returns canned AIMessage objects, cycling through its `responses` list. No
network, no key, byte-reproducible.

Run:
    uv run python lc_chains_lcel.py
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import (
    Runnable,
    RunnableLambda,
    RunnableParallel,
    RunnablePassthrough,
)

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


def fake(responses: list[str]) -> FakeMessagesListChatModel:
    """Build a deterministic offline chat model from canned response strings."""
    return FakeMessagesListChatModel(
        responses=[AIMessage(content=c) for c in responses]
    )


# ----------------------------------------------------------------------------
# Section A — the pipe: prompt | model
# ----------------------------------------------------------------------------

def section_a_the_pipe() -> None:
    banner("A — The pipe: prompt | model is a RunnableSequence")
    print("In LCEL the `|` operator (Python's __or__ dunder) feeds the output of")
    print("the left Runnable into the right Runnable. `prompt | model` returns a")
    print("brand-new object — a RunnableSequence — that you invoke once. The")
    print("output here is an AIMessage (because the model emits AIMessages).\n")

    prompt = ChatPromptTemplate.from_messages(
        [("system", "You are a concise assistant."),
         ("human", "Tell me about {topic}.")]
    )
    model = fake(["Cats are small carnivorous mammals."])
    chain = prompt | model

    print(f"{'expression':<46}{'value'}")
    print("-" * 72)
    print(f"{'type(prompt).__name__':<46}{type(prompt).__name__}")
    print(f"{'type(model).__name__':<46}{type(model).__name__}")
    print(f"{'type(prompt | model).__name__':<46}{type(chain).__name__}")
    print(f"{'isinstance(prompt, Runnable)':<46}{isinstance(prompt, Runnable)}")
    print(f"{'isinstance(model, Runnable)':<46}{isinstance(model, Runnable)}")
    print(f"{'isinstance(chain, Runnable)':<46}{isinstance(chain, Runnable)}")

    out = chain.invoke({"topic": "cats"})
    print("\nchain.invoke({'topic': 'cats'}) ->")
    print(f"  type  : {type(out).__name__}")
    print(f"  content: {out.content!r}")
    print()

    check("`prompt | model` is a RunnableSequence",
          type(chain).__name__ == "RunnableSequence")
    check("prompt, model, chain are ALL Runnables (uniform unit)",
          isinstance(prompt, Runnable)
          and isinstance(model, Runnable)
          and isinstance(chain, Runnable))
    check("chain.invoke returns an AIMessage", isinstance(out, AIMessage))
    check("the AIMessage content is the canned string",
          out.content == "Cats are small carnivorous mammals.")


# ----------------------------------------------------------------------------
# Section B — prompt | model | StrOutputParser  ->  plain str
# ----------------------------------------------------------------------------

def section_b_add_parser() -> None:
    banner("B — prompt | model | StrOutputParser -> a plain str")
    print("Append a StrOutputParser at the tail. The parser takes the AIMessage")
    print("and returns its .content as a string, so the WHOLE chain now yields a")
    print("str instead of an AIMessage. Every link is still a Runnable; the pipe")
    print("keeps composing.\n")

    prompt = ChatPromptTemplate.from_messages(
        [("human", "Summarize {topic} in one sentence.")]
    )
    model = fake(["Dogs are loyal domesticated canines."])
    parser = StrOutputParser()
    chain = prompt | model | parser

    print(f"{'expression':<46}{'value'}")
    print("-" * 72)
    print(f"{'type(parser).__name__':<46}{type(parser).__name__}")
    print(f"{'isinstance(parser, Runnable)':<46}{isinstance(parser, Runnable)}")
    print(f"{'type(prompt | model | parser).__name__':<46}"
          f"{type(chain).__name__}")

    out = chain.invoke({"topic": "dogs"})
    print("\nchain.invoke({'topic': 'dogs'}) ->")
    print(f"  type  : {type(out).__name__}")
    print(f"  value : {out!r}")
    print()

    check("parser is a Runnable too", isinstance(parser, Runnable))
    check("the three-stage chain is still a RunnableSequence",
          type(chain).__name__ == "RunnableSequence")
    check("adding the parser makes the output a str",
          isinstance(out, str))
    check("the str equals the canned AIMessage content",
          out == "Dogs are loyal domesticated canines.")


# ----------------------------------------------------------------------------
# Section C — RunnablePassthrough: the identity Runnable
# ----------------------------------------------------------------------------

def section_c_passthrough() -> None:
    banner("C — RunnablePassthrough echoes its input unchanged")
    print("RunnablePassthrough is the identity Runnable: invoke(x) returns x.")
    print("Its real power shows inside a parallel branch, where it echoes the")
    print("original input alongside a freshly-computed value (see Section E).\n")

    pt = RunnablePassthrough()
    for x in [{"question": "what is lc?"}, ["a", "b"], "bare string", 42]:
        out = pt.invoke(x)
        print(f"{'RunnablePassthrough().invoke(' + repr(x) + ')':<52}-> {out!r}")
    print()

    check("RunnablePassthrough is a Runnable", isinstance(pt, Runnable))
    check("dict passes through unchanged",
          pt.invoke({"question": "what is lc?"}) == {"question": "what is lc?"})
    check("list passes through unchanged",
          pt.invoke(["a", "b"]) == ["a", "b"])
    check("a bare string passes through unchanged",
          pt.invoke("bare string") == "bare string")


# ----------------------------------------------------------------------------
# Section D — RunnableLambda: wrap any callable as a Runnable
# ----------------------------------------------------------------------------

def section_d_lambda() -> None:
    banner("D — RunnableLambda wraps a plain function as a Runnable")
    print("RunnableLambda(fn) turns any 1-arg callable into a Runnable you can")
    print("pipe. This is how custom Python logic joins an LCEL chain without")
    print("subclassing Runnable.\n")

    upper = RunnableLambda(lambda s: s.upper())
    chain = upper

    for s in ["hello", "lc", "langchain"]:
        print(f"{'upper.invoke(' + repr(s) + ')':<30}-> {chain.invoke(s)!r}")
    print()

    check("RunnableLambda is a Runnable", isinstance(upper, Runnable))
    check("it uppercases the input", upper.invoke("hello") == "HELLO")
    check("a RunnableLambda can be piped into another Runnable",
          (upper | RunnableLambda(len)).invoke("hi") == 2)


# ----------------------------------------------------------------------------
# Section E — RunnableParallel: concurrent branches -> a dict
# ----------------------------------------------------------------------------

def section_e_parallel() -> None:
    banner("E — RunnableParallel runs branches concurrently -> a dict")
    print("RunnableParallel(**branches) runs each branch on the SAME input and")
    print("returns a dict keyed by the branch name. This is how LCEL fans out")
    print("(e.g. echo the question while retrieving context).\n")

    branches = RunnableParallel(
        original=RunnablePassthrough(),
        upper=RunnableLambda(lambda s: s.upper()),
        length=RunnableLambda(lambda s: len(s)),
    )
    out = branches.invoke("hello")

    print("branches = RunnableParallel(")
    print("    original=RunnablePassthrough(),")
    print("    upper=RunnableLambda(lambda s: s.upper()),")
    print("    length=RunnableLambda(lambda s: len(s)),")
    print(")")
    print(f"\nbranches.invoke('hello') -> {out}\n")

    print(f"{'key':<10}{'value':<12}{'type'}")
    print("-" * 38)
    for k, v in out.items():
        print(f"{k:<10}{str(v):<12}{type(v).__name__}")
    print()

    check("RunnableParallel is a Runnable", isinstance(branches, Runnable))
    check("output has exactly the 3 branch keys",
          set(out.keys()) == {"original", "upper", "length"})
    check("'original' echoes the input unchanged", out["original"] == "hello")
    check("'upper' applies its branch transform", out["upper"] == "HELLO")
    check("'length' applies its branch transform", out["length"] == 5)


# ----------------------------------------------------------------------------
# Section F — uniform interface: stream + batch (free on every chain)
# ----------------------------------------------------------------------------

def section_f_stream_batch() -> None:
    banner("F — stream + batch: every chain gets them for free")
    print("Because every step is a Runnable, every RunnableSequence inherits")
    print("invoke / stream / batch / ainvoke / abatch uniformly. .stream(...) is")
    print("a generator of output chunks; .batch([...]) runs a list of inputs and")
    print("returns a list. (The fake model yields one chunk per response; real")
    print("LLMs stream token-by-token — the API is identical.)\n")

    prompt = ChatPromptTemplate.from_messages(
        [("human", "Reply about {topic}.")]
    )
    model = fake(["Chunk-0"])
    chain = prompt | model | StrOutputParser()

    chunks = list(chain.stream({"topic": "cats"}))
    print(f"chunks = list(chain.stream({{'topic': 'cats'}})) -> {chunks}")
    print(f"number of chunks yielded: {len(chunks)}\n")

    model2 = fake(["answer-1", "answer-2"])
    chain2 = prompt | model2 | StrOutputParser()
    batched = chain2.batch([{"topic": "cats"}, {"topic": "dogs"}])
    print("batched = chain.batch([{'topic':'cats'}, {'topic':'dogs'}])")
    print(f"        -> {batched}")
    print(f"length  : {len(batched)}\n")

    check("chain.stream yields at least one chunk", len(chunks) >= 1)
    check("the stream chunk equals the canned content", chunks[0] == "Chunk-0")
    check("chain.batch returns a list of length 2", len(batched) == 2)
    check("batch preserves input order",
          batched == ["answer-1", "answer-2"])


# ----------------------------------------------------------------------------
# Section G — a realistic chain: assign -> prompt -> model -> parser
# ----------------------------------------------------------------------------

def section_g_realistic_chain() -> None:
    banner("G — realistic: RunnablePassthrough.assign + prompt | model | parser")
    print("A RAG-shaped chain: take {'question': ...}, attach a 'context' key")
    print("with RunnablePassthrough.assign(), then feed {question, context} into")
    print("the prompt, model, and parser. assign() merges a new key into the dict")
    print("while keeping the originals — the declarative glue RAG relies on.\n")

    add_context = RunnablePassthrough.assign(
        context=lambda d: f"stub-context-for: {d['question']}"
    )
    prompt = ChatPromptTemplate.from_messages(
        [("human", "Context: {context}\nQuestion: {question}\nAnswer:")]
    )
    model = fake(["Answer: cats were domesticated ~9000 years ago."])
    chain = add_context | prompt | model | StrOutputParser()

    after_assign = add_context.invoke({"question": "origin of cats?"})
    print("After assign step:")
    print(f"  {after_assign}")
    final = chain.invoke({"question": "origin of cats?"})
    print("\nFull chain.invoke({'question': 'origin of cats?'}) ->")
    print(f"  type  : {type(final).__name__}")
    print(f"  value : {final!r}\n")

    check("assign() adds the 'context' key while keeping 'question'",
          set(after_assign.keys()) == {"question", "context"})
    check("the full chain ends in a str (parser at the tail)",
          isinstance(final, str))
    check("the final str equals the canned AIMessage content",
          final == "Answer: cats were domesticated ~9000 years ago.")
    check("assign | prompt | model | parser is still ONE RunnableSequence",
          type(chain).__name__ == "RunnableSequence")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    import langchain_core

    print("lc_chains_lcel.py — Phase 6 bundle #38.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed. OFFLINE: the model is a\n"
          "FakeMessagesListChatModel (no network, no API key).\n"
          f"langchain-core {langchain_core.__version__} on this machine.")
    section_a_the_pipe()
    section_b_add_parser()
    section_c_passthrough()
    section_d_lambda()
    section_e_parallel()
    section_f_stream_batch()
    section_g_realistic_chain()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
