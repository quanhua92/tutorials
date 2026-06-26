"""
huffman.py - Reference implementation of Huffman coding (Huffman 1952).

This is the single source of truth that HUFFMAN.md is built from. Every
number, table, and worked example in HUFFMAN.md is printed by this file.

Run:
    uv run python huffman.py

==========================================================================
THE INTUITION (read this first) — Morse code's good idea, made optimal
==========================================================================
Morse code gives SHORT dots-and-dashes to common letters (E = ".") and LONG
ones to rare letters (Q = "--.-"). That is a great idea, but Morse picked
the lengths by hand. Huffman (1952) found a construction that picks them
OPTIMALLY from the data, and guarantees the result is a PREFIX-FREE code
(no codeword is the start of another, so decoding is unambiguous).

The construction, in one sentence: repeatedly MERGE the two RAREST subtrees
into a new node whose weight is their sum, until one tree remains. Rare
symbols end up DEEP (long codes); common symbols end up SHALLOW (short
codes). The two children of every internal node get a 0 / 1 bit.

  * FREQUENCIES : count how often each symbol appears.
  * MIN-HEAP    : always grab the two lightest nodes.
  * MERGE       : pop two, push one combined node (weight = sum). Repeat
                  until one node remains — that is the root.
  * CODE TABLE  : walk the tree; left = '0', right = '1'. Each leaf's path
                  is its codeword.
  * ENCODE      : concatenate the codewords.
  * DECODE      : walk the tree bit by bit; emit a symbol at each leaf.

==========================================================================
WHY IT IS OPTIMAL (the key fact)
==========================================================================
Huffman coding is provably optimal for SYMBOL-BY-SYMBOL coding with a
binary alphabet: no prefix-free code for the same symbol probabilities can
have a shorter EXPECTED code length L. Specifically:

    H  <=  L  <  H + 1        (H = Shannon entropy, in bits/symbol)

i.e. it is within ONE BIT per symbol of the information-theoretic floor.
To beat Huffman you must code BLOCKS of symbols (arithmetic / range
coding) or model the stream adaptively (LZ77 + Huffman = DEFLATE).

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  symbol       : one element of the input alphabet (here, a character).
  frequency    : how many times the symbol appears in the input.
  weight       : the number stored at a tree node = total frequency of all
                 leaves beneath it. For a leaf, weight == frequency.
  leaf         : a node carrying a real symbol (no children).
  internal node: a node created by merging two others (no symbol, two kids).
  codeword     : the string of 0/1 bits on the path from root to a leaf.
  prefix-free  : no codeword is a prefix of another. This is what makes
                 bit-by-bit decoding unambiguous. Huffman codes are always
                 prefix-free BY CONSTRUCTION.
  min-heap     : a queue that always returns the smallest element. We push
                 (weight, tiebreak, node) so ties break deterministically.

==========================================================================
HISTORY
==========================================================================
  - Huffman (1952), "A Method for the Construction of Minimum-Redundancy
    Codes". Originally a term-paper response to Robert Fano's information
    theory class at MIT. Beat Fano-Shannon coding, which was not always
    optimal.
  - DEFLATE (Deutsch 1996, RFC 1951): LZ77 + Huffman. Used by gzip (.gz),
    zlib, and PNG (after the PNG filter stage). 🔗 Pair with RLE.md: the
    LZ77 part turns nearby repeats into runs; Huffman handles symbol skew.
  - JPEG: the final stage Huffman-codes the run/length symbols produced by
    the RLE-of-zeros stage.
  - MP3 / Huffman in dozens of codecs.

DETERMINISM NOTE: when two nodes tie in weight, the merge order can differ.
This implementation breaks ties by INSERTION ORDER (a monotonic counter),
so the tree, the codewords, and the bit count are byte-identical every run.
Initial leaves are inserted in (frequency, symbol) order for stability.

KEY FORMULAS (all asserted in code):
    weight(node)        = freq(node)  if leaf
                          weight(left) + weight(right)  if internal
    L (avg code len)    = sum( p_i * len(code_i) )     in bits/symbol
    H (entropy)         = -sum( p_i * log2 p_i )       in bits/symbol
    optimality          = H <= L < H + 1   (Huffman's guarantee)
    prefix-free decode  = unique & exact, no backtracking needed
"""

from __future__ import annotations

import heapq
import math
from collections import Counter

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code HUFFMAN.md walks through)
# ============================================================================

class Node:
    """A Huffman tree node. Leaves carry `sym`; internal nodes carry None.

    Comparison is done by (weight, order) at the heap level, NOT here, so we
    keep __repr__ readable and avoid relying on Python's node `<` (which
    would not break ties deterministically across runs).
    """

    __slots__ = ("sym", "weight", "left", "right")

    def __init__(self, sym, weight, left=None, right=None):
        self.sym = sym
        self.weight = weight
        self.left = left
        self.right = right

    def is_leaf(self):
        return self.left is None and self.right is None

    def __repr__(self):
        if self.is_leaf():
            return f"Leaf({self.sym!r}:{self.weight})"
        return f"Node({self.weight})"


def build_frequency(data: str) -> dict[str, int]:
    """Count symbol frequencies. Returns {symbol: count}."""
    return dict(Counter(data))


def build_tree(freq: dict[str, int]) -> Node:
    """Build the Huffman tree from a frequency table.

    Deterministic tie-breaking: heap entries are (weight, order, node) where
    `order` is a monotonically increasing counter. Ties therefore resolve
    FIFO (first inserted = first merged). Initial leaves are pushed in
    sorted (freq, symbol) order so the very first ties are alphabetical.

    Returns the root Node. Caller can derive the code table via build_codes.
    """
    if not freq:
        raise ValueError("cannot build a tree from an empty frequency table")
    heap = []
    order = 0
    for sym in sorted(freq, key=lambda s: (freq[s], s)):
        heapq.heappush(heap, (freq[sym], order, Node(sym, freq[sym])))
        order += 1
    while len(heap) > 1:
        w1, _, n1 = heapq.heappop(heap)
        w2, _, n2 = heapq.heappop(heap)
        parent = Node(None, w1 + w2, n1, n2)        # left=n1 (smaller), right=n2
        heapq.heappush(heap, (parent.weight, order, parent))
        order += 1
    return heap[0][2]


def build_codes(root: Node) -> dict[str, str]:
    """Walk the tree (left='0', right='1') to build {symbol: codeword}.

    A single-symbol input (tree is one leaf) gets the codeword '0', because
    a zero-length code cannot be emitted on the wire.
    """
    codes: dict[str, str] = {}
    if root.is_leaf():
        codes[root.sym] = "0"
        return codes

    def walk(node: Node, prefix: str):
        if node.is_leaf():
            codes[node.sym] = prefix
            return
        walk(node.left, prefix + "0")
        walk(node.right, prefix + "1")
    walk(root, "")
    return codes


def huffman_encode(data: str, codes: dict[str, str]) -> str:
    """Concatenate codewords. Returns the bit string (e.g. '0110111...')."""
    return "".join(codes[ch] for ch in data)


def huffman_decode(bits: str, root: Node) -> str:
    """Bit-by-bit decode. Walk from root; emit a symbol at each leaf.

    Because the code is prefix-free, there is exactly one way to parse the
    bit stream — no backtracking, no lookahead, no separator needed.
    """
    if root.is_leaf():
        # single-symbol alphabet: each '0' is one symbol
        return root.sym * bits.count("0")
    out = []
    node = root
    for b in bits:
        node = node.left if b == "0" else node.right
        if node.is_leaf():
            out.append(node.sym)
            node = root
    return "".join(out)


def entropy(freq: dict[str, int]) -> float:
    """Shannon entropy H = -sum(p_i * log2 p_i), in bits/symbol."""
    total = sum(freq.values())
    h = 0.0
    for c in freq.values():
        p = c / total
        h -= p * math.log2(p)
    return h


def avg_code_length(freq: dict[str, int], codes: dict[str, str]) -> float:
    """Expected code length L = sum(p_i * len(code_i)), bits/symbol."""
    total = sum(freq.values())
    return sum(c / total * len(codes[s]) for s, c in freq.items())


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_tree(root: Node) -> str:
    """ASCII rendering of the tree: root at top, edges labeled 0:/1:.

    *(w) = internal node of weight w ;  Sym(w) = leaf.
    """
    lines: list[str] = []

    def walk(node: Node, prefix: str, is_tail: bool, edge: str, is_root: bool):
        connector = "" if is_root else (("└─" if is_tail else "├─") + edge)
        label = (f"{node.sym}({node.weight})" if node.is_leaf()
                 else f"*({node.weight})")
        lines.append(prefix + connector + label)
        if not node.is_leaf():
            new_prefix = "" if is_root else prefix + ("   " if is_tail else "│  ")
            walk(node.left, new_prefix, False, "0:", False)
            walk(node.right, new_prefix, True, "1:", False)

    if root.is_leaf():
        lines.append(f"{root.sym}({root.weight})")
    else:
        walk(root, "", True, "", True)
    return "\n".join(lines)


# ============================================================================
# 3. SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: frequency table -> tree -> code table (the full pipeline)
# ----------------------------------------------------------------------------

def section_pipeline():
    banner("SECTION A: the full pipeline on 'ABRACADABRA'")
    s = "ABRACADABRA"
    print(f'input = "{s}"   (len = {len(s)})\n')

    freq = build_frequency(s)
    print("Step 1 - frequency table:")
    for sym in sorted(freq, key=lambda c: (-freq[c], c)):
        bar = "#" * freq[sym]
        print(f"    {sym}: {freq[sym]:>2}  {bar}")
    print()

    root = build_tree(freq)
    print("Step 2 - Huffman tree (left child = '0', right child = '1');")
    print("        *(w) = internal node of weight w;  Sym(w) = leaf:\n")
    print(fmt_tree(root))
    print()

    codes = build_codes(root)
    print("Step 3 - code table (walk root->leaf; left='0', right='1'):")
    for sym in sorted(codes, key=lambda c: (len(codes[c]), c)):
        print(f"    {sym}: {codes[sym]:<6}  (len {len(codes[sym])})")
    print()
    # prefix-free property check
    print("Step 4 - prefix-free check (no codeword is a prefix of another):")
    clist = sorted(codes.values(), key=len)
    pf_ok = True
    for i, c in enumerate(clist):
        for d in clist[i + 1:]:
            if d.startswith(c):
                pf_ok = False
                print(f"    VIOLATION: '{c}' is a prefix of '{d}'")
    print(f"    [check] prefix-free?  {pf_ok}")
    assert pf_ok


# ----------------------------------------------------------------------------
# SECTION B: the merge trace (min-heap step-by-step)
# ----------------------------------------------------------------------------

def section_merge_trace():
    banner("SECTION B: the merge trace  (always marry the two lightest)")
    s = "ABRACADABRA"
    freq = build_frequency(s)
    print(f'input = "{s}"\n')
    print("Heap entries are (weight, order, node). Ties break by `order`")
    print("(FIFO), so the tree is byte-identical every run.\n")

    heap = []
    order = 0
    for sym in sorted(freq, key=lambda x: (freq[x], x)):
        heapq.heappush(heap, (freq[sym], order, sym))
        order += 1
    print("Initial heap (sorted by freq, then symbol):")
    print(f"  {sorted(heap)}\n")

    step = 0
    while len(heap) > 1:
        w1, o1, a = heapq.heappop(heap)
        w2, o2, b = heapq.heappop(heap)
        step += 1
        merged = f"{{{a}+{b}}}"
        print(f"  step {step}: pop ({w1},{a}) & ({w2},{b})  ->  "
              f"merge into {merged} weight {w1 + w2}")
        heapq.heappush(heap, (w1 + w2, order, merged))
        order += 1
        print(f"           heap now: {sorted(heap, key=lambda x: (x[0], x[1]))}")
    print(f"\n  final: {heap[0][2]} (root, weight {heap[0][0]})\n")
    print("Notice the rare symbols (C, D) get merged FIRST and sink DEEP;")
    print("the common symbol (A) waits until the very last merge, so it")
    print("stays one step from the root -> the SHORTEST code.")


# ----------------------------------------------------------------------------
# SECTION C: encode + decode + round-trip (bit exactness)
# ----------------------------------------------------------------------------

def section_encode_decode():
    banner("SECTION C: encode + decode + round-trip  (bit-exact)")
    s = "ABRACADABRA"
    freq = build_frequency(s)
    root = build_tree(freq)
    codes = build_codes(root)

    bits = huffman_encode(s, codes)
    print(f'input = "{s}"\n')
    print("encode (concatenate codewords, symbol by symbol):")
    for ch in s:
        print(f"    {ch} -> {codes[ch]}")
    print(f"\nbit stream = {bits}   ({len(bits)} bits)\n")

    dec = huffman_decode(bits, root)
    print(f'decode(bits) = "{dec}"')
    ok = dec == s
    print(f"[check] round-trip decode(encode(x)) == x ?  {ok}")
    assert ok
    # show that you can start decoding anywhere — prefix-free = no ambiguity
    print("\nBecause the code is prefix-free, the decoder walks the tree bit")
    print("by bit and emits a symbol at every leaf — no separators needed.")


# ----------------------------------------------------------------------------
# SECTION D: compression ratio + optimality (entropy vs avg code length)
# ----------------------------------------------------------------------------

def section_ratio():
    banner("SECTION D: compression ratio + optimality  (H <= L < H + 1)")
    s = "ABRACADABRA"
    freq = build_frequency(s)
    root = build_tree(freq)
    codes = build_codes(root)
    bits = huffman_encode(s, codes)

    bin_ascii = len(s) * 8
    bin_fixed3 = len(s) * 3            # ceil(log2(5)) = 3 bits for 5 symbols
    bin_huff = len(bits)
    H = entropy(freq)
    L = avg_code_length(freq, codes)
    total_huff = L * len(s)

    print(f'input = "{s}"   (5 distinct symbols)\n')
    print(f"fixed 8-bit ASCII : {len(s)} x 8         = {bin_ascii:>4} bits")
    print(f"fixed 3-bit (5sym): {len(s)} x 3         = {bin_fixed3:>4} bits  "
          "(ceil(log2 5) = 3)")
    print(f"Huffman (variable): {bits}  = {bin_huff:>4} bits\n")

    print("ratios:")
    print(f"  Huffman / ASCII     = {bin_huff}/{bin_ascii} = "
          f"{bin_huff / bin_ascii:.3f}   "
          f"({(1 - bin_huff / bin_ascii) * 100:.1f}% smaller than ASCII)")
    print(f"  Huffman / fixed-3   = {bin_huff}/{bin_fixed3} = "
          f"{bin_huff / bin_fixed3:.3f}\n")

    print("OPTIMALITY CHECK (the headline result of Huffman 1952):")
    print(f"  entropy   H = -sum(p log2 p)              = {H:.4f} bits/symbol")
    print(f"  avg len   L = sum(p * len(code))          = {L:.4f} bits/symbol")
    print(f"  gap       L - H                           = {L - H:+.4f} "
          "bits/symbol")
    print(f"  guarantee H <= L < H + 1                  -> "
          f"{H:.4f} <= {L:.4f} < {H + 1:.4f}")
    ok = H <= L < H + 1
    print(f"  [check] H <= L < H+1 ?  {ok}")
    assert ok
    print(f"\n  Expected bits (L * n) = {L:.4f} * {len(s)} = "
          f"{total_huff:.2f}  ==  actual {bin_huff}?  "
          f"{abs(total_huff - bin_huff) < 1e-9}")
    assert abs(total_huff - bin_huff) < 1e-9
    print(f"\n  Huffman is within {L - H:.2f} bit/symbol of the entropy floor.")
    print("  To beat it you must code BLOCKS of symbols (arithmetic coding)")


# ----------------------------------------------------------------------------
# SECTION E: data skew matters — flat vs skewed alphabets
# ----------------------------------------------------------------------------

def section_skew():
    banner("SECTION E: data skew matters  (flat vs skewed alphabets)")
    print("Huffman only beats fixed-length coding when frequencies are SKEWED.")
    print("On a UNIFORM alphabet, Huffman cannot help — every codeword is the")
    print("same length, and L == log2(|alphabet|) == H.\n")

    cases = [
        ("uniform 4 symbols", "ABCDABCDABCDABCD", "all freq equal"),
        ("skewed (A-heavy)", "AAAAAAAABCD", "1 symbol dominates"),
        ("very skewed", "AAAAAAAAAAB", "almost a single symbol"),
        ("ABRACADABRA", "ABRACADABRA", "the running example"),
    ]
    print("| case               | input                  | |A| | H     | "
          "L     | L-H   | vs 8-bit ASCII |")
    print("|--------------------|------------------------|-----|-------|"
          "-------|-------|----------------|")
    for name, s, note in cases:
        freq = build_frequency(s)
        codes = build_codes(build_tree(freq))
        H = entropy(freq)
        L = avg_code_length(freq, codes)
        bits = sum(len(codes[c]) for c in s)
        ratio = bits / (len(s) * 8)
        print(f"| {name:<18} | {s:<22} | {len(freq):<3} | {H:.3f} | "
              f"{L:.3f} | {L - H:+.3f} | {ratio:.3f} ({(1-ratio)*100:4.1f}% saved) |")
    print()
    print("Read it as: the more SKEWED the frequencies, the bigger the win.")
    print("Uniform data -> Huffman == fixed-length (no gain). That is why")
    print("DEFLATE runs LZ77 first: LZ77 turns repetition into symbol skew,")
    print("which Huffman can then exploit.")


# ----------------------------------------------------------------------------
# SECTION F: when to use Huffman (real-world deployments)
# ----------------------------------------------------------------------------

def section_when_to_use():
    banner("SECTION F: when to use Huffman  (and the alternatives)")
    print("Huffman is the workhorse of the 'second stage' in almost every")
    print("lossless codec. It is fast, optimal for single-symbol coding, and")
    print("cheap to ship alongside the data.\n")
    rows = [
        ("DEFLATE", "gzip (.gz), zlib, PNG",
         "LZ77 (repetition) + Huffman (skew). The default stack."),
        ("JPEG", "lossy image",
         "RLE-of-zeros stage, then Huffman on the (run,len) symbols."),
        ("MP3 / AAC", "lossy audio",
         "Huffman the quantized spectral coefficients."),
        ("BZIP2", "block-sorting compressor",
         "uses Huffman as one of the final stages after BWT + MTF."),
        ("Barcodes/PKZIP", "general lossless",
         "DEFLATE again — Huffman is the entropy coder."),
    ]
    print("| codec      | used in               | role of Huffman                       |")
    print("|------------|-----------------------|---------------------------------------|")
    for name, used, role in rows:
        print(f"| {name:<10} | {used:<21} | {role:<37} |")
    print()
    print("ALTERNATIVES (when Huffman is not enough):")
    print("  - Arithmetic / range coding: codes BLOCKS of symbols, beats the")
    print("    'H+1' floor. Used in JPEG2000, modern video codecs. Slower.")
    print("  - Asymmetric Numeral Systems (rANS): arithmetic-coding speed")
    print("    at Huffman-like cost. Used in zstd, Facebook's lizard.")
    print("  - Adaptive Huffman: updates the tree as it reads the stream.")
    print("    One pass, no separate code table; used in some modem specs.")
    print("\nRULE OF THUMB: reach for Huffman when you want OPTIMAL")
    print("single-symbol coding at high speed. Reach for arithmetic/rANS when")
    print("you can afford more CPU to squeeze the last few percent.")


# ----------------------------------------------------------------------------
# SECTION G: GOLD values pinned for huffman.html (JS rebuilds & compares)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION G: GOLD values for huffman.html  (rebuild in JS, compare)")
    s = "ABRACADABRA"
    freq = build_frequency(s)
    root = build_tree(freq)
    codes = build_codes(root)
    bits = huffman_encode(s, codes)
    dec = huffman_decode(bits, root)

    print(f'gold input = "{s}"\n')
    print("gold frequency table:")
    for sym in sorted(freq, key=lambda c: (-freq[c], c)):
        print(f"    {sym}: {freq[sym]}")
    print("\ngold code table:")
    for sym in sorted(codes, key=lambda c: (len(codes[c]), c)):
        print(f"    {sym}: {codes[sym]}")
    print(f'\ngold bit stream = {bits}   ({len(bits)} bits)')
    print(f'gold decode(bits) = "{dec}"')
    ok = dec == s
    print(f"\n[check] gold round-trip ?  {ok}")
    assert ok
    H = entropy(freq)
    L = avg_code_length(freq, codes)
    print(f"[check] gold entropy H = {H:.4f}, avg len L = {L:.4f}, "
          f"gap = {L - H:.4f}")
    print("\nThe .html rebuilds this tree in JS (same tiebreak: freq then sym,")
    print("FIFO merges) and verifies the code table + bit stream + L match the")
    print(".py exactly.")


# ============================================================================
# main
# ============================================================================

def main():
    print("huffman.py - reference impl. All numbers below feed HUFFMAN.md.")
    print("pure Python stdlib, deterministic (FIFO tiebreak in the heap).\n")

    section_pipeline()
    section_merge_trace()
    section_encode_decode()
    section_ratio()
    section_skew()
    section_when_to_use()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
