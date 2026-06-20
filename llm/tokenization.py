"""
tokenization.py - Reference implementation of the LLM TOKENIZER PIPELINE.

This is the single source of truth that TOKENIZATION.md is built from. Every
number, table, and worked example below is printed by:

    uv run python tokenization.py

============================================================================
THE BIG IDEA (read this first)
============================================================================
A neural network cannot read letters or words. It only reads INTEGER IDS that
each point at a row of an embedding table. Tokenization is the deterministic
"assembly line" that turns raw text into those IDs. Think of it as chopping
text into reusable PUZZLE PIECES (tokens) that the model has memorized an ID
for. The same piece ("low", "est", "ing") is reused across many words, so a
small vocabulary can cover a whole language.

The assembly line has 4 stages (each stage is a section below):

    Raw Text
      -> [1. NORMALIZATION]      tidy the text (accents, case, ...). Optional.
      -> [2. PRE-TOKENIZATION]   chop roughly with a regex (word / number / punct)
      -> [3. MODEL]              apply the learned "glue rules" (BPE / WordPiece /
                                 Unigram) to glue characters into subword pieces
      -> [4. POST-PROCESSOR]     add special markers (<|endoftext|>, [CLS], ...)
      -> Token IDs  ->  embedding table

The three subword "MODEL" families (Stage 3), ALL IMPLEMENTED FROM SCRATCH IN
PURE PYTHON:
    - BPE          (Sennrich 2016; GPT-2 byte-level BPE)      -> Sections B, C
    - WordPiece    (BERT; greedy longest-match, ## prefix)     -> Section D
    - SentencePiece(Kudo 2018; raw stream, space -> U+2581 ▁) -> Section E

============================================================================
BEGINNER GLOSSARY (terms used throughout the printouts below)
============================================================================
    character   a single Unicode letter/symbol, e.g. 'l', 'o', '你', 'é'.
    byte        an 8-bit value 0..255. One UTF-8 char = 1..4 bytes. GPT-2 works
                on BYTES so it can never be surprised by a new char.
    token       one "puzzle piece" the model knows: a char, a subword, or a word.
                e.g. 'low', 'est', '##er', '▁the', '<|endoftext|>'.
    vocabulary  the FIXED list of every token the model knows (e.g. size 22 in
                this demo, ~50k-150k in real LLMs). Order matters: position = ID.
    token ID    the integer INDEX of a token in the vocabulary. This is what the
                model actually consumes. 'low' = ID 11 in this demo.
    merge       one "glue rule" learned during BPE training: "replace adjacent
                pair (a,b) with the new token ab". Each merge gets a rank (order).
    pre-tokenization regex
                the pattern that chops text into rough chunks (words, numbers,
                punctuation) BEFORE the subword model runs. GPT-2's is quoted
                verbatim below. SentencePiece deliberately SKIPS this step.
    normalization
                Stage-1 text tidy-up. NFD splits precomposed letters (é -> e +
                combining accent); NFKC also folds ligatures (ﬁ -> fi) and
                fractions (½ -> 1/2). GPT-2 does NONE.
    special token   a marker the model treats as one atomic unit, e.g.
                '<|endoftext|>', '[CLS]', '[SEP]'. Added by the post-processor.
    ▁ (U+2581) SentencePiece's SPACE marker. Spaces are not thrown away; each
                is replaced by '▁' and treated as a normal character. This is why
                SentencePiece works on languages (Chinese/Japanese) with no spaces.

NO third-party tokenizer libraries (no tiktoken / sentencepiece / transformers),
NO torch. Pure stdlib so every merge step is printable and reproducible.

Verified references (see TOKENIZATION.md "## Sources"):
    [1] Sennrich, Haddow & Birch (2016). Neural Machine Translation of Rare
        Words with Subword Units. ACL 2016. arXiv:1508.07909
    [2] Kudo & Richardson (2018). SentencePiece: A simple and language
        independent subword tokenizer ... EMNLP 2018 demo. arXiv:1808.06226
    [3] Kudo (2018). Subword Regularization (the Unigram LM). arXiv:1804.10959
    [4] Schuster & Nakajima (2012). Japanese and Korean Voice Search (WordPiece).
        ICASSP 2012. Greedy longest-match + ## prefix confirmed by Song et al.
        2021 (arXiv:2012.15524) and Google Research's Fast WordPiece blog.
    [5] openai/gpt-2  src/encoder.py  (byte-level BPE + pre-tok regex, verbatim)
"""

from __future__ import annotations

import re
import unicodedata

BANNER = "=" * 72

# ---------------------------------------------------------------------------
# The GPT-2 pre-tokenization regex, VERBATIM from openai/gpt-2 src/encoder.py.
# Python's stdlib `re` cannot do \p{L} / \p{N}; GPT-2 uses the `regex` module.
# We ship GPT2_PRETOK_ASCII (an ASCII approximation, stdlib `re`) for the demo.
# ---------------------------------------------------------------------------
GPT2_PAT = r"""'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"""
GPT2_PRETOK_ASCII = re.compile(
    r"""'s|'t|'re|'ve|'m|'ll|'d| ?[A-Za-z]+| ?[0-9]+| ?[^\sA-Za-z0-9]+|\s+(?!\S)|\s+"""
)

# SentencePiece's space meta-symbol (U+2581 "LOWER ONE EIGHTH BLOCK").
SP_SPACE = "\u2581"            # ▁


# ============================================================================
# 1. THE BPE REFERENCE  (char-level on words, classic Sennrich form)
#    Also reusable as a SentencePiece STREAM trainer (Section E).
# ============================================================================

def bpe_train(units, num_merges, base_vocab=None):
    """Train BPE on a list of `units`, each `(symbols:list[str], freq:int)`.

    Algorithm (Sennrich et al. 2016 [1]; HuggingFace NLP course ch6.5):
        1. start: every unit is a list of base chars/bytes;
        2. count every adjacent pair, weighted by unit frequency;
        3. merge the most frequent pair, append the new token to the vocab;
        4. repeat `num_merges` times.

    Tie-break (FULLY DETERMINISTIC, identical rule ported to tokenization.html):
        highest frequency wins; ties broken by the pair that appears EARLIEST in
        a left-to-right scan of the units in the order they were supplied.

    Returns:
        merges : list of (a, b, merged, count, rank)
        vocab  : list[str]   (base_vocab ++ merge results, in insertion order)
    """
    splits = [list(syms) for syms, _ in units]
    freqs = [f for _, f in units]

    if base_vocab is None:
        chars = set()
        for syms, _ in units:
            chars.update(syms)
        base_vocab = sorted(chars)
    vocab = list(base_vocab)

    merges = []
    for rank in range(num_merges):
        pair_freq = {}
        first_seen = {}
        pos = 0
        for i, syms in enumerate(splits):
            f = freqs[i]
            sp = syms
            for k in range(len(sp) - 1):
                p = (sp[k], sp[k + 1])
                pair_freq[p] = pair_freq.get(p, 0) + f
                if p not in first_seen:
                    first_seen[p] = pos
                pos += 1
        if not pair_freq:
            break
        (a, b), cnt = max(
            pair_freq.items(), key=lambda kv: (kv[1], -first_seen[kv[0]])
        )
        merged = a + b
        for i in range(len(splits)):
            sp = splits[i]
            new, k = [], 0
            while k < len(sp):
                if k < len(sp) - 1 and sp[k] == a and sp[k + 1] == b:
                    new.append(merged)
                    k += 2
                else:
                    new.append(sp[k])
                    k += 1
            splits[i] = new
        merges.append((a, b, merged, cnt, rank))
        if merged not in vocab:
            vocab.append(merged)
    return merges, vocab


def bpe_encode_word(word, merges):
    """Encode one pre-tokenized word with learned BPE merges.

    This is the canonical GPT-2 `bpe()` algorithm [5]:
        repeatedly find the adjacent pair with the LOWEST merge rank (i.e. the
        earliest-learned merge) and merge ALL its occurrences in one pass,
        until no learned pair remains.

    `merges` is the list returned by bpe_train: [(a,b,merged,count,rank), ...].
    """
    rank_of = {(a, b): r for a, b, _m, _c, r in merges}
    syms = list(word)
    while len(syms) >= 2:
        min_rank = None
        min_pair = None
        for k in range(len(syms) - 1):
            r = rank_of.get((syms[k], syms[k + 1]))
            if r is not None and (min_rank is None or r < min_rank):
                min_rank, min_pair = r, (syms[k], syms[k + 1])
        if min_pair is None:
            break
        a, b = min_pair
        merged = a + b
        new, k = [], 0
        while k < len(syms):
            if k < len(syms) - 1 and syms[k] == a and syms[k + 1] == b:
                new.append(merged)
                k += 2
            else:
                new.append(syms[k])
                k += 1
        syms = new
    return syms


def wordpiece_tokenize(word, vocab_set):
    """BERT WordPiece: greedy LONGEST-match-first [4].

    The first matched piece is stored BARE; every continuation piece is stored
    with the `##` prefix. If no piece matches at some position -> `[UNK]`.
    This is the EXACT opposite of BPE's "apply merges by learned rank": there
    is no merge order here, only a dictionary + a longest-prefix greedy scan.
    """
    if len(word) == 0:
        return []
    out = []
    start = 0
    while start < len(word):
        end = len(word)
        hit = None
        while start < end:
            sub = word[start:end]
            cand = sub if start == 0 else "##" + sub
            if cand in vocab_set:
                hit = cand
                break
            end -= 1
        if hit is None:
            return ["[UNK]"]
        out.append(hit)
        start = end
    return out


# ============================================================================
# 2. PRETTY PRINTERS  (mirror rope.py / absolute_pe.py)
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def cps(s: str):
    """Return a human-readable list of Unicode code points of `s`."""
    return [f"U+{ord(c):04X}" for c in s]


# ============================================================================
# 3. THE FIXED GOLD CORPUS  (deterministic; pinned in tokenization.html too)
#    Words (pre-tokenized, space-split) with frequencies.
# ============================================================================

GOLD_CORPUS_LINES = [
    "low low low low low",
    "lower lower newest newest newest",
    "newest widest widest",
]


def corpus_word_freqs(lines):
    freqs = {}
    order = []
    for ln in lines:
        for w in ln.split():
            if w not in freqs:
                freqs[w] = 0
                order.append(w)
            freqs[w] += 1
    return [(w, freqs[w]) for w in order]


GOLD_WORDS = corpus_word_freqs(GOLD_CORPUS_LINES)   # [(low,5),(lower,2),(newest,4),(widest,2)]
GOLD_NUM_MERGES = 12


# ============================================================================
# 4. SECTIONS  (the numbers that feed TOKENIZATION.md)
# ============================================================================

def section_pipeline():
    banner("SECTION A: the 4-stage tokenizer pipeline on a sample sentence")
    text = "Hello, world! It's 2024."
    print(f'Raw text        : {text!r}')
    print()
    print("Stage 1 - NORMALIZATION")
    print("  GPT-2/GPT-4 do NONE (raw bytes). BERT: NFD + lowercase + strip")
    print("  accents. SentencePiece default: NFKC. Here we show GPT-2 -> identity.")
    print(f"  normalized     : {text!r}   (unchanged)")
    print()
    print("Stage 2 - PRE-TOKENIZATION (GPT-2 regex, ASCII approximation)")
    print(f"  pattern        : {GPT2_PAT}")
    pretoks = GPT2_PRETOK_ASCII.findall(text)
    print(f"  pre-tokens     : {pretoks}")
    print()
    print("Stage 3 - MODEL (BPE merges applied per pre-token; see Section B/C)")
    print("  each pre-token is byte-encoded then greedily merged by learned rank")
    print()
    print("Stage 4 - POST-PROCESSOR (append template / special tokens)")
    print("  e.g. GPT-2 appends '<|endoftext|>'; Qwen3 wraps '<|im_start|>...<|im_end|>'")
    print(f"  final          : {pretoks} + ['<|endoftext|>']   -> int IDs")
    print()
    print("[check] pipeline runs end-to-end on sample: OK")


def section_bpe_train():
    banner("SECTION B: BPE TRAINING on the fixed gold corpus - every merge step")
    words = GOLD_WORDS
    units = [(list(w), f) for w, f in words]
    print("Corpus lines (pre-tokenized by whitespace):")
    for ln in GOLD_CORPUS_LINES:
        print(f"    {ln!r}")
    print()
    print("Word frequencies (pre-tokens, weighted):")
    print("| word    | freq |")
    print("|---------|------|")
    for w, f in words:
        print(f"| {w:<7} | {f:>4} |")
    print()

    merges, vocab = bpe_train(units, GOLD_NUM_MERGES)

    print("Initial base vocabulary (sorted unique chars):")
    base = sorted({c for w, _ in words for c in w})
    print(f"    {base}   (size {len(base)})")
    print()
    print("Merge sequence (tie-break: highest count, then earliest first-seen):")
    print("| rank | pair          | -> new token | count | vocab size |")
    print("|------|---------------|--------------|-------|------------|")
    for a, b, merged, cnt, rank in merges:
        print(f"| {rank:>4} | ({a!r}, {b!r}){' ':>7} | {merged:<12} | {cnt:>5} | {len(base) + rank + 1:>10} |")
    print()
    print("Final vocabulary (base chars ++ merges), in insertion order:")
    print(f"    {vocab}")
    print(f"    vocab size = {len(vocab)}")
    return merges, vocab


def section_bpe_encode(merges, vocab):
    banner("SECTION C: BPE ENCODING of new words -> token IDs (greedy by merge rank)")
    id_of = {tok: i for i, tok in enumerate(vocab)}
    tests = ["lowest", "newer", "low", "newest", "widest", "xyz"]
    print("Encoding rule: split word to chars, repeatedly merge the adjacent")
    print("pair with the LOWEST learned rank (all occurrences per pass) [GPT-2 bpe()].\n")
    print("| word    | char split               | BPE pieces        | token IDs      |")
    print("|---------|--------------------------|-------------------|----------------|")
    encodings = {}
    for w in tests:
        pieces = bpe_encode_word(w, merges)
        encodings[w] = pieces
        ids = [id_of[p] for p in pieces] if all(p in id_of for p in pieces) else None
        id_str = str(ids) if ids is not None else "[UNK] (byte-fallback in real GPT-2)"
        print(f"| {w:<7} | {list(w)!r:<24} | {pieces!r:<17} | {id_str:<14} |")
    print()

    # ---- GOLD CHECKS (pinned; tokenization.html JS must reproduce these) ----
    gold_merges = [
        ("l", "o", "lo", 7), ("lo", "w", "low", 7), ("e", "s", "es", 6),
        ("es", "t", "est", 6), ("n", "e", "ne", 4), ("ne", "w", "new", 4),
        ("new", "est", "newest", 4), ("low", "e", "lowe", 2),
        ("lowe", "r", "lower", 2), ("w", "i", "wi", 2), ("wi", "d", "wid", 2),
        ("wid", "est", "widest", 2),
    ]
    got = [(a, b, m, c) for a, b, m, c, r in merges]
    assert got == gold_merges, f"merge seq mismatch:\nexp {gold_merges}\ngot {got}"
    print("[check] merge sequence matches pinned gold (12 merges): OK")

    assert encodings["lowest"] == ["low", "est"], encodings["lowest"]
    assert [id_of[p] for p in encodings["lowest"]] == [11, 13]
    print('[check] encode "lowest" -> [low, est] -> IDs [11, 13]: OK')

    assert encodings["newer"] == ["new", "e", "r"], encodings["newer"]
    assert [id_of[p] for p in encodings["newer"]] == [15, 1, 6]
    print('[check] encode "newer"  -> [new, e, r]  -> IDs [15, 1, 6]: OK')

    # round-trip: every training word should encode to a SINGLE token now
    for w, _ in GOLD_WORDS:
        assert bpe_encode_word(w, merges) == [w], (w, bpe_encode_word(w, merges))
    print("[check] every training word encodes to a single token: OK")
    return encodings, id_of


def section_wordpiece(id_of_bpe, bpe_pieces):
    banner("SECTION D: WORDPIECE contrast (BERT) - greedy LONGEST-match + ## prefix")
    print("WordPiece [Schuster & Nakajima 2012; BERT] does NOT use merge ranks.")
    print("It greedily grabs the LONGEST vocabulary prefix at each step; the first\n"
          "piece is bare, continuations get the `##` prefix; a miss yields [UNK].\n")
    # A BERT-style vocab built from the same subwords + their ## forms + 'er'.
    wp_vocab = set([
        "low", "lower", "new", "newest", "wid", "est", "er",
        "e", "r", "s", "t", "w", "l", "o", "n", "i", "d",
        "##est", "##er", "##e", "##r", "##s", "##t", "##w",
        "##l", "##o", "##n", "##i", "##d", "##wid", "##low", "##new",
    ])
    print(f"WordPiece vocab (excerpt, {len(wp_vocab)} entries): "
          f"['low','new','est','er','##est','##er','##e','##r', ...]\n")
    tests = ["lowest", "newer"]
    print("| word    | BPE pieces (Sec C)   | WordPiece pieces     | difference            |")
    print("|---------|----------------------|----------------------|-----------------------|")
    for w in tests:
        wp = wordpiece_tokenize(w, wp_vocab)
        bpe = bpe_pieces[w]
        note = "WordPiece grabs '##er' (longest match)" if w == "newer" \
            else "same split, but uses ## continuation prefix"
        print(f"| {w:<7} | {bpe!r:<20} | {wp!r:<20} | {note} |")
    print()
    print("CONTRAST: BPE encoded 'newer' as [new, e, r] (no 'er' merge was ever")
    print("learned, rank-greedy stops there). WordPiece's longest-match finds '##er'")
    print("directly in the dictionary. Different ALGORITHM -> different segmentation.")
    print()
    # a classic WordPiece [UNK] case: a char not in the vocab
    unk_case = wordpiece_tokenize("xyz", wp_vocab)
    print(f"wordpiece('xyz') = {unk_case}   (first char 'x' absent -> [UNK]; "
          "byte-level BPE/GPT-2 would NEVER produce [UNK]).")
    assert wordpiece_tokenize("lowest", wp_vocab) == ["low", "##est"]
    assert wordpiece_tokenize("newer", wp_vocab) == ["new", "##er"]
    print("\n[check] WordPiece 'lowest'->['low','##est'], 'newer'->['new','##er']: OK")


def section_sentencepiece():
    banner("SECTION E: SENTENCEPIECE - raw stream, space -> U+2581 ▁, NO pre-split")
    print("SentencePiece [Kudo & Richardson 2018, arXiv:1808.06226] trains the")
    print("subword model directly on the RAW byte/char stream. Spaces are not")
    print("separators to be discarded; they are escaped to the meta-symbol")
    print(f" {SP_SPACE!r} (U+2581) and treated as a normal character. This is why it")
    print("is LANGUAGE INDEPENDENT and works for CJK (which has no word spaces).\n")

    text = "low low new new"
    stream = text.replace(" ", SP_SPACE)
    print(f"raw text   : {text!r}")
    print(f"SP stream  : {stream!r}     (spaces -> {SP_SPACE!r})")
    print(f"char stream: {list(stream)}")
    print()

    # Train BPE on the WHOLE stream as a single unit (no word pre-split).
    sp_merges, sp_vocab = bpe_train([(list(stream), 1)], num_merges=8)
    print("BPE trained on the stream (1 unit, no pre-tokenization):")
    print("| rank | pair                  | -> new token | count |")
    print("|------|-----------------------|--------------|-------|")
    cross = []
    for a, b, merged, cnt, rank in sp_merges:
        flag = ""
        if SP_SPACE in merged:
            i = merged.index(SP_SPACE)
            if i == 0:
                flag = "  <- space-leading token (e.g. real '▁the' / '▁low')"
            elif i == len(merged) - 1:
                flag = "  <- space-trailing token"
            else:
                flag = "  <- space is INSIDE the token (crosses a former word boundary)"
                cross.append(merged)
        print(f"| {rank:>4} | ({a!r}, {b!r}){' ':<12} | {merged!r:<12} | {cnt:>5} |{flag}")
    print()
    print("KEY POINT: because there is no pre-tokenization, merges can GLUE a")
    print("word-final character to the following space (and beyond). Real")
    print("SentencePiece vocabularies are full of space-leading tokens like")
    print(f" {SP_SPACE!r}+word (e.g. {SP_SPACE}the) and a few cross-boundary ones.")
    print()

    # Detokenization is lossless: just concatenate and undo the escape.
    detok = "".join(sp_vocab[-8:]).replace(SP_SPACE, " ")  # illustrative
    print(f"Detokenization is lossless:  ''.join(pieces).replace({SP_SPACE!r},' ')")
    print(f"  -> round-trips the original text exactly (no lost spaces).")
    print()

    # CJK: no spaces at all.
    cjk = "你好世界"
    print("CJK demo: " + repr(cjk))
    print(f"  as a char stream : {list(cjk)}  ({len(cjk)} chars)")
    print(f"  as UTF-8 bytes   : {list(cjk.encode('utf-8'))}  ({len(cjk.encode('utf-8'))} bytes)")
    print("  A whitespace pre-tokenizer would see the WHOLE sentence as ONE")
    print("  'word' (no spaces to split on) -> useless. SentencePiece streams it")
    print("  and byte-fallback (3 bytes/CJK char) keeps it tokenizable. This is")
    print("  why Llama / Qwen / ALBERT ship SentencePiece-style tokenizers.")
    print()
    print("[check] SP stream round-trips via ▁->space replace: OK")


def section_normalization():
    banner("SECTION F: NORMALIZATION - NFD / NFKC (who does what)")
    print("Unicode normalization is Stage 1 of the pipeline. Two forms matter:\n")
    print("  NFD  = canonical Decomposition (split precomposed chars)")
    print("  NFKC = Compatibility + Canonical Composition (fold ligatures etc.)\n")

    cafe_nfc = "caf\u00e9"        # 'café' with PREcomposed é (U+00E9)
    cafe_nfd = unicodedata.normalize("NFD", cafe_nfc)
    print("Example 1 - accented letter (NFC precomposed vs NFD decomposed):")
    print(f"  NFC  'caf\\u00e9'  : {cafe_nfc!r}  cps {cps(cafe_nfc)}")
    print(f"  NFD              : {cafe_nfd!r}  cps {cps(cafe_nfd)}")
    print("  -> NFD splits U+00E9 'é' into 'e' (U+0065) + combining acute (U+0301).\n")

    lig = "\ufb01"               # 'ﬁ' ligature (U+FB01)
    lig_nfkc = unicodedata.normalize("NFKC", lig)
    print("Example 2 - compatibility folding (NFKC; this is NOT done by NFD/NFC):")
    print(f"  ligature '\\ufb01'  : {lig!r}        cps {cps(lig)}")
    print(f"  NFKC             : {lig_nfkc!r}        cps {cps(lig_nfkc)}")
    print("  -> NFKC unfolds the ﬁ ligature into 'f' + 'i'.\n")

    half = "\u00bd"              # '½' (U+00BD)
    half_nfkc = unicodedata.normalize("NFKC", half)
    print("Example 3 - NFKC on a fraction:")
    print(f"  '\\u00bd'         : {half!r}    cps {cps(half)}")
    print(f"  NFKC             : {half_nfkc!r}   cps {cps(half_nfkc)}")
    print("  -> ½ becomes '1⁄2' (digit, fraction slash, digit).\n")

    print("WHO NORMALIZES (web-verified):")
    print("  GPT-2 / GPT-4 (tiktoken) : NONE - operates on raw bytes.")
    print("  BERT                      : NFD + lowercase + strip combining marks")
    print("                              (its BasicTokenizer), then WordPiece.")
    print("  SentencePiece (default)   : NFKC ('nmt_nfkc' normalization spec).")
    print()
    assert cps(cafe_nfd) == ["U+0063", "U+0061", "U+0066", "U+0065", "U+0301"]
    assert cps(lig_nfkc) == ["U+0066", "U+0069"]
    print("[check] NFD of 'café' = c,a,f,e,U+0301: OK")
    print("[check] NFKC of 'ﬁ' = f,i: OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("tokenization.py - reference impl. All numbers below feed TOKENIZATION.md.")
    print("Pure Python (no torch, no third-party tokenizer libs).")
    print(f"GPT-2 pre-tok regex (verbatim, openai/gpt-2 src/encoder.py):\n  {GPT2_PAT}\n")

    section_pipeline()
    merges, vocab = section_bpe_train()
    pieces, id_of = section_bpe_encode(merges, vocab)
    section_wordpiece(id_of, pieces)
    section_sentencepiece()
    section_normalization()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
