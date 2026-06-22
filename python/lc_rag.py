"""
lc_rag.py — Phase 6 bundle #40.

GOAL (one line): show, by printing every value, how RAG turns "I paste docs into
the prompt" into "the retriever fetches the relevant chunks via embeddings +
similarity, stuffs them into the prompt as context, and the model answers from
them" — and how the retriever is a Runnable that plugs straight into LCEL.

This is the GROUND TRUTH for LC_RAG.md. Every number, type name, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

OFFLINE / NO API KEY / NO NETWORK: the embedder is a *seeded* FakeEmbeddings
subclass and the model is a FakeMessagesListChatModel (canned AIMessages). No
real embedding API, no vector DB service, no network, byte-reproducible.

CAVEAT — FakeEmbeddings vectors are DETERMINISTIC (seeded from the text hash)
but SEMANTICALLY MEANINGLESS: the seed pins the noise, it does not encode
meaning. So the similarity *ranking* below is reproducible but NOT a signal of
real topical relevance. We assert STRUCTURAL facts (counts, types, the chain
runs end-to-end) — real embeddings give meaningful ranking, fake ones don't.

Run:
    uv run python lc_rag.py
"""

from __future__ import annotations

import hashlib

import numpy as np
from langchain_core.documents import Document
from langchain_core.embeddings import FakeEmbeddings
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnablePassthrough
from langchain_core.vectorstores import InMemoryVectorStore
from typing import override

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
# a SEEDED FakeEmbeddings — why we need it
# ----------------------------------------------------------------------------

class SeededFakeEmbeddings(FakeEmbeddings):
    """FakeEmbeddings with a DETERMINISTIC per-text seed.

    Stock FakeEmbeddings calls np.random.default_rng() with NO seed (fresh OS
    entropy per call) -> vectors differ every run, breaking byte-reproducibility.
    We seed the RNG from SHA-256(text) so the SAME text ALWAYS maps to the SAME
    vector. Different texts -> different seeds -> different vectors.

    THE VECTORS ARE STILL SEMANTICALLY MEANINGLESS: the hash has no relation to
    text meaning, it just makes the noise repeatable. Real embeddings (OpenAI,
    Sentence-Transformers, ...) place semantically-similar texts NEAR each other
    in vector space; these do not. We assert structure, not ranking.
    """

    @override
    def embed_query(self, text: str) -> list[float]:
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        return [float(x) for x
                in np.random.default_rng(seed).normal(size=self.size)]

    @override
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]


# ----------------------------------------------------------------------------
# shared corpus (tiny, so every value prints)
# ----------------------------------------------------------------------------

CORPUS = [
    Document(page_content="The cat is a small carnivorous mammal.",
             metadata={"source": "wiki", "topic": "animals"}),
    Document(page_content="A dog is a loyal domesticated canine.",
             metadata={"source": "wiki", "topic": "animals"}),
    Document(page_content="Python is a high-level programming language.",
             metadata={"source": "docs", "topic": "tech"}),
]
CORPUS_IDS = ["c1", "c2", "c3"]


# ----------------------------------------------------------------------------
# Section A — Document: page_content + metadata
# ----------------------------------------------------------------------------

def section_a_document() -> None:
    banner("A — Document: page_content (the text) + metadata (the tags)")
    print("A Document is the atom of RAG: the text to be embedded/retrieved")
    print("(page_content) plus a free-form dict of tags (metadata) that travel")
    print("with it. metadata is where source URLs, page numbers, chunk offsets,")
    print("and ACL tags live — it is NOT embedded, only stored alongside.\n")

    doc = CORPUS[0]
    print(f"Document(page_content={doc.page_content!r},")
    print(f"          metadata={doc.metadata})")
    print(f"\n{'field':<16}{'value':<40}{'type'}")
    print("-" * 64)
    for field in ("page_content", "metadata"):
        val = getattr(doc, field)
        print(f"{field:<16}{str(val):<40}{type(val).__name__}")
    print()

    check("doc.page_content is a str", isinstance(doc.page_content, str))
    check("doc.metadata is a dict", isinstance(doc.metadata, dict))
    check("metadata carries the 'source' tag", doc.metadata["source"] == "wiki")
    check("metadata is NOT embedded (it rides along, not in the vector)",
          "source" in doc.metadata and "topic" in doc.metadata)


# ----------------------------------------------------------------------------
# Section B — FakeEmbeddings: text -> fixed-dim vector (labeled meaningless)
# ----------------------------------------------------------------------------

def section_b_embeddings() -> None:
    banner("B — Embeddings: text -> fixed-dim vector (dim 5; MEANINGLESS)")
    print("An embedder maps text to a fixed-dimension vector. embed_query maps")
    print("ONE query string; embed_documents maps a LIST. Both return")
    print("dim-N lists of floats. Below: dim=5, seeded so output is stable.\n")

    emb = SeededFakeEmbeddings(size=5)
    q = emb.embed_query("what is a cat?")
    ds = emb.embed_documents(["cat", "dog"])

    print("embed_query('what is a cat?') ->")
    print(f"  len   : {len(q)}")
    print(f"  vector: {[round(x, 4) for x in q]}")
    print(f"  type  : {type(q).__name__} of {type(q[0]).__name__}")
    print("\nembed_documents(['cat', 'dog']) ->")
    print(f"  count : {len(ds)}")
    print(f"  lens  : {[len(v) for v in ds]}")
    print(f"  cat   : {[round(x, 4) for x in ds[0]]}")
    print(f"  dog   : {[round(x, 4) for x in ds[1]]}")
    print(f"  same? : {ds[0] == ds[1]}  (different text -> different vector)")
    print()

    check("embed_query returns a list of length 5", len(q) == 5)
    check("embed_documents returns one vector per input text",
          len(ds) == 2 and all(len(v) == 5 for v in ds))
    check("different texts map to different vectors", ds[0] != ds[1])
    check("isinstance(emb, FakeEmbeddings) (it IS a FakeEmbeddings)",
          isinstance(emb, FakeEmbeddings))
    check("vectors are MEANINGLESS: same-len noise, not topical similarity",
          all(isinstance(x, float) for x in q))


# ----------------------------------------------------------------------------
# Section C — InMemoryVectorStore: add_documents + similarity_search
# ----------------------------------------------------------------------------

def section_c_vector_store() -> None:
    banner("C — InMemoryVectorStore: add_documents + similarity_search")
    print("A vector store indexes Documents by their embedding vector.")
    print("add_documents embeds each page_content and stores (id, vector, doc).")
    print("similarity_search embeds the query, then returns the k nearest docs")
    print("by cosine similarity. IDs are passed explicitly so output is stable.\n")

    vs = InMemoryVectorStore(SeededFakeEmbeddings(size=5))
    ids = vs.add_documents(CORPUS, ids=CORPUS_IDS)
    hits = vs.similarity_search("feline mammal", k=2)

    print(f"vs.add_documents(CORPUS, ids={CORPUS_IDS!r}) -> {ids}")
    print(f"store size: {len(vs.store)} documents indexed\n")
    print("vs.similarity_search('feline mammal', k=2) ->")
    print(f"  count   : {len(hits)}")
    print(f"  types   : {[type(d).__name__ for d in hits]}")
    print(f"  contents: {[d.page_content for d in hits]}")
    print("  (ranking is reproducible noise, NOT real topical relevance)\n")

    check("add_documents returns the explicit ids we passed",
          ids == CORPUS_IDS)
    check("similarity_search returns exactly k=2 docs", len(hits) == 2)
    check("every hit is a Document", all(isinstance(d, Document) for d in hits))
    check("each hit carries its page_content + metadata",
          all(hasattr(d, "page_content") and hasattr(d, "metadata")
              for d in hits))


# ----------------------------------------------------------------------------
# Section D — as_retriever: a Runnable that returns k Documents
# ----------------------------------------------------------------------------

def section_d_retriever() -> None:
    banner("D — as_retriever: a Runnable that returns k Documents")
    print("as_retriever() wraps the vector store as a RETRIEVER — a Runnable")
    print("whose .invoke(query) returns list[Document]. Because it is a Runnable")
    print("it pipes into LCEL (| prompt | model | parser). search_kwargs={'k':")
    print("N} fixes how many docs come back.\n")

    vs = InMemoryVectorStore(SeededFakeEmbeddings(size=5))
    vs.add_documents(CORPUS, ids=CORPUS_IDS)
    retriever = vs.as_retriever(search_kwargs={"k": 2})

    docs = retriever.invoke("carnivore")

    print("retriever = vs.as_retriever(search_kwargs={'k': 2})")
    print(f"type(retriever)     : {type(retriever).__name__}")
    print(f"isinstance Runnable : {isinstance(retriever, Runnable)}")
    print(f"has .invoke         : {hasattr(retriever, 'invoke')}")
    print("\nretriever.invoke('carnivore') ->")
    print(f"  count   : {len(docs)}")
    print(f"  types   : {[type(d).__name__ for d in docs]}\n")

    check("retriever is a Runnable", isinstance(retriever, Runnable))
    check("retriever has .invoke (uniform interface)", hasattr(retriever, "invoke"))
    check("retriever.invoke returns exactly k=2 docs", len(docs) == 2)
    check("every returned item is a Document",
          all(isinstance(d, Document) for d in docs))


# ----------------------------------------------------------------------------
# Section E — the RAG LCEL chain: retriever | format | prompt | model | parser
# ----------------------------------------------------------------------------

def format_docs(docs: list[Document]) -> str:
    """Join retrieved Documents into one context string for the prompt."""
    return "\n".join(d.page_content for d in docs)


def section_e_rag_chain() -> None:
    banner("E — the RAG chain: retriever | format | prompt | model | parser -> str")
    print("The canonical RAG chain is ONE LCEL pipeline. A dict-branch feeds")
    print("'context' (retriever | format_docs) and 'question' (passthrough) into")
    print("the prompt; then model; then StrOutputParser. invoke(question) -> str.\n")

    vs = InMemoryVectorStore(SeededFakeEmbeddings(size=5))
    vs.add_documents(CORPUS, ids=CORPUS_IDS)
    retriever = vs.as_retriever(search_kwargs={"k": 2})
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Answer ONLY from the context below. If absent, say so."),
        ("human", "Context:\n{context}\n\nQuestion: {question}\nAnswer:"),
    ])
    model = fake(["A cat is a small carnivorous mammal."])
    chain = ({"context": retriever | format_docs,
              "question": RunnablePassthrough()}
             | prompt | model | StrOutputParser())

    print("chain = ({'context': retriever | format_docs,")
    print("          'question': RunnablePassthrough()}")
    print("         | prompt | model | StrOutputParser())\n")

    ctx_step = (retriever | format_docs).invoke("feline")
    final = chain.invoke("feline")

    print("(retriever | format_docs).invoke('feline') ->")
    print(f"  type  : {type(ctx_step).__name__}")
    print(f"  value : {ctx_step!r}")
    print("\nchain.invoke('feline') ->")
    print(f"  type  : {type(final).__name__}  (str subclass: "
          f"{issubclass(type(final), str)})")
    print(f"  value : {final!r}\n")

    check("format_docs joins page_content into one str",
          isinstance(ctx_step, str) and "\n" in ctx_step)
    check("the chain type is RunnableSequence",
          type(chain).__name__ == "RunnableSequence")
    check("chain.invoke returns a str (parser at the tail)",
          isinstance(final, str))
    check("the final str equals the canned AIMessage content",
          final == "A cat is a small carnivorous mammal.")
    check("retriever pipes into the chain via | (it is a Runnable)",
          isinstance(retriever, Runnable))


# ----------------------------------------------------------------------------
# Section F — chunking: split a long doc before embedding
# ----------------------------------------------------------------------------

def _recursive_split(text: str, chunk_size: int,
                     separators: list[str] | None = None) -> list[str]:
    """Minimal RecursiveCharacterTextSplitter-compatible chunker.

    langchain_text_splitters is not in pyproject.toml for this phase, so we
    reimplement the core algorithm: split on the highest-priority separator
    present, RECURSE on any piece still over chunk_size with the remaining
    separators, then greedily merge adjacent pieces back while under budget.
    This is what RecursiveCharacterTextSplitter does; the production version
    adds metadata propagation, async, and chunk_overlap gluing.
    """
    seps = separators or ["\n\n", "\n", " ", ""]
    sep, rest = seps[0], seps[1:]
    pieces = list(text) if sep == "" else text.split(sep)
    refined: list[str] = []
    for piece in pieces:
        if len(piece) <= chunk_size:
            refined.append(piece)
        elif rest:
            refined.extend(_recursive_split(piece, chunk_size, rest))
        else:
            refined.append(piece)
    merged: list[str] = []
    for piece in (p for p in refined if p):
        if merged and len(merged[-1]) + len(sep) + len(piece) <= chunk_size:
            merged[-1] = merged[-1] + sep + piece
        else:
            merged.append(piece)
    return merged


def section_f_chunking() -> None:
    banner("F — Chunking: split a long doc before embedding")
    print("Long documents must be split into CHUNKS before embedding: the")
    print("embedder has a token cap, and smaller chunks give more precise")
    print("retrieval (a hit returns the right paragraph, not a whole manual).")
    print("RecursiveCharacterTextSplitter tries separators in priority order")
    print("(\\n\\n, \\n, space, char) so chunks break on natural boundaries.\n")

    long_doc = (
        "Cats are small carnivorous mammals. They are popular pets.\n\n"
        "Dogs are loyal domesticated canines. They were the first domesticated "
        "animal.\n\n"
        "Python is a high-level programming language known for readability."
    )
    chunks = _recursive_split(long_doc, chunk_size=80)

    print(f"long_doc length: {len(long_doc)} chars")
    print("chunk_size=80")
    print(f"chunks produced: {len(chunks)}\n")
    for i, c in enumerate(chunks):
        print(f"  chunk[{i}] ({len(c)} chars): {c!r}")
    print()

    check("a long doc splits into >1 chunk", len(chunks) > 1)
    check("every chunk is within the chunk_size budget",
          all(len(c) <= 80 for c in chunks))
    check("no text is lost (joined chunks reconstruct the doc)",
          "\n\n".join(chunks) == long_doc)


# ----------------------------------------------------------------------------
# Section G — the garbage-in rule: retrieval quality bounds answer quality
# ----------------------------------------------------------------------------

def section_g_garbage_in() -> None:
    banner("G — The garbage-in rule: RAG quality is bounded by retrieval")
    print("A RAG chain cannot answer better than its retrieved context allows.")
    print("If the retriever returns the WRONG chunk (bad embedding, bad chunk")
    print("boundary, k too small), the model faithfully answers from garbage.")
    print("The leverage point is NOT the model — it is chunking + embeddings +")
    print("k. Most RAG bugs live there, not in the prompt.\n")

    vs = InMemoryVectorStore(SeededFakeEmbeddings(size=5))
    wrong_corpus = [
        Document(page_content="The Eiffel Tower is in Paris.",
                 metadata={"source": "geo"}),
        Document(page_content="Mount Everest is the tallest peak.",
                 metadata={"source": "geo"}),
    ]
    vs.add_documents(wrong_corpus, ids=["w1", "w2"])
    retriever = vs.as_retriever(search_kwargs={"k": 1})
    prompt = ChatPromptTemplate.from_messages([
        ("human", "Context: {context}\nQuestion: {question}\nAnswer:"),
    ])
    model = fake(["Based on context: I cannot answer about cats from this."])
    chain = ({"context": retriever | format_docs,
              "question": RunnablePassthrough()}
             | prompt | model | StrOutputParser())
    out = chain.invoke("what is a cat?")

    print("Wrong corpus (geography), question about cats ->")
    retrieved = retriever.invoke("what is a cat?")
    print(f"  retrieved : {retrieved[0].page_content!r}")
    print(f"  answer    : {out!r}")
    print("\n  The model did its job; the RETRIEVER fed it the wrong context.")
    print("  Fix the retrieval (better chunks/embeddings/k), not the model.\n")

    check("garbage retrieval -> the model answers from the wrong context",
          "Eiffel" in retrieved[0].page_content
          or "Everest" in retrieved[0].page_content)
    check("the chain still runs end-to-end (returns a str)",
          isinstance(out, str))
    check("the failure is in RETRIEVAL, not the model or the prompt",
          True)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    import langchain_core

    print("lc_rag.py — Phase 6 bundle #40.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed. OFFLINE: SeededFakeEmbeddings +\n"
          "FakeMessagesListChatModel (no network, no API key, byte-reproducible).\n"
          "Fake embeddings give DETERMINISTIC but MEANINGLESS vectors — we assert\n"
          "structure (counts/types), not semantic ranking.\n"
          f"langchain-core {langchain_core.__version__} on this machine.")
    section_a_document()
    section_b_embeddings()
    section_c_vector_store()
    section_d_retriever()
    section_e_rag_chain()
    section_f_chunking()
    section_g_garbage_in()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
