"""
grammar_output.py - Reference implementation of GBNF grammar-constrained
generation (the token-mask sampler) in llama.cpp.

WHAT IS GRAMMAR-CONSTRAINED GENERATION? (start here if you are new)
   An LLM samples each token from a probability distribution over its
   vocabulary. Nothing in that distribution *guarantees* a structure you need:
   a stray quote can break JSON, a letter can land where a digit belongs, a
   trailing comma can appear. GBNF (GGML BNF) lets you hand the sampler a
   *context-free grammar*; BEFORE each token is drawn, the sampler builds a MASK
   over the whole vocabulary - tokens whose leading character(s) the grammar
   would reject are zeroed - then samples from the masked distribution. The
   output is *guaranteed* to parse against the grammar. This is how llama.cpp's
   `--grammar` / `--grammar-file` flags and `json_schema` mode force valid JSON.

THE LINEAGE (old -> new, each step motivated by the prior's failure):

   1. FREE sampling: top-k / top-p / temperature over the FULL vocab. Format is
      uncontrolled; "please output JSON" in the prompt is unreliable - models
      still drift, hallucinate keys, or leave the JSON unclosed.

   2. + NAIVE MASKING (first-char only): zero any token whose first byte the
      grammar forbids. Cheap, but wrong for multi-byte tokens: the token's
      *whole* leading string must fit the grammar state, not just byte zero.

   3. + FULL TOKEN MASKING (llama.cpp / GBNF): for every token in the vocab
      (32K-128K), test the ENTIRE leading string against the grammar's current
      parser state. Keep the model probability if it fits, zero it if not. Then
      run top-k/top-p on the masked logits. This is what `llama-cli --grammar`
      and `llama-server`'s `grammar` body field do.

   4. + JSON-SCHEMA -> GBNF compiler: auto-derive a grammar from a JSON schema
      (`examples/json_schema_to_gbnf.py`, or the `--json` / `-j` flag, or the
      server's `json_schema` field), so tool/function calling emits
      structurally-valid JSON every time without hand-writing GBNF.

HOW THE MASK IS BUILT (this bundle's load-bearing mechanism):
     before sampling token t:
       (1) the grammar sits in a current PARSER STATE (residual grammar);
       (2) for every token in the vocab, test whether the grammar can ACCEPT
           that token's text from the current state;
       (3) accepted tokens keep their model probability; rejected -> 0;
       (4) sample from the masked distribution (top-k/top-p applied AFTER mask);
       (5) advance the grammar state by the sampled token's characters.
     COST: ~10-30% slower - every token is checked against the grammar state
     at every step (issue #4218). Repetition like `x? x? x? ...` is especially
     slow; `x{0,N}` is the efficient rewrite.

THE MECHANISM USED HERE (concept-faithful, not byte-exact):
   This is a *simplified* model - a tiny GBNF parser + a derivative-based token
   mask simulator. It is NOT llama.cpp's exact C++ implementation (which uses a
   byte-level LL(1) parser with a stack of grammar positions, in
   `common/grammar-parser.cpp` + `common/json-schema-to-grammar.cpp`). The
   concept is identical: given a grammar state, compute the exact set of valid
   next tokens. We realize it with Brzozowski derivatives - the grammar state IS
   the residual grammar after consuming the output so far; a token is accepted
   iff derive(state, token_text) is not the empty language.

Companion code that GRAMMAR_OUTPUT.md is built from. Every number below prints:
    python3 grammar_output.py

PURE PYTHON STDLIB (no torch, no numpy). Tiny grammars + a 10-token vocabulary
so every number prints.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

BANNER = "=" * 72


# ============================================================================
# 1. Grammar AST  (the parsed shape of a GBNF rule)
# ============================================================================
#
# We support the GBNF subset that is enough to be honest about the mechanism:
#   * literal strings      "abc"
#   * character classes    [a-z]  [^0-9]  [abehlo]
#   * concatenation        a b c            (Seq)
#   * alternation          a | b | c        (Alt)
#   * repetition           a+  a*  a?       (Plus / Star / Opt)
#   * grouping             ( a b )+
#   * rule references      root ::= ... | ws | string | ...
#   * comments             # to end of line
# That subset covers the GOLD grammar, the JSON grammar, and a list grammar.

@dataclass
class Null:
    """The empty language: matches nothing. The 'failure' / masked residual."""
    _dcache: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass
class Eps:
    """The empty string (epsilon): matches here, consumes nothing. 'accepted'."""
    _dcache: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass
class Lit:
    """A literal string terminal, e.g. Lit("{")."""
    s: str
    _dcache: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass
class Cls:
    """A character class. `chars` is the explicit set; `neg` inverts it ([^..])."""
    chars: frozenset
    neg: bool
    label: str                      # human-readable, e.g. "a-z" or "^0-9"
    _dcache: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass
class Seq:
    a: object
    b: object
    _dcache: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass
class Alt:
    a: object
    b: object
    _dcache: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass
class Star:
    a: object
    _dcache: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass
class Plus:
    a: object
    _dcache: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass
class Opt:
    a: object
    _dcache: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass
class Ref:
    name: str
    _dcache: dict = field(default_factory=dict, repr=False, compare=False)


# ---- smart constructors collapse the empty language so masking is exact -------
def is_null(n) -> bool:
    return isinstance(n, Null)


def is_eps(n) -> bool:
    return isinstance(n, Eps) or (isinstance(n, Lit) and n.s == "")


def mk_seq(a, b):
    if is_null(a) or is_null(b):
        return Null()              # a sequence fails if any part fails
    if is_eps(a):
        return b
    if is_eps(b):
        return a
    return Seq(a, b)


def mk_alt(a, b):
    if is_null(a):
        return b
    if is_null(b):
        return a
    return Alt(a, b)


# ============================================================================
# 2. nullable + Brzozowski derivative  (the grammar-state engine)
# ============================================================================
#
# nullable(n): can `n` match the empty string? (i.e. is this an accepting state?)
# D(n, c):     the RESIDUAL grammar after consuming one character `c` from the
#              front of `n`. Null means `c` is forbidden here; anything else
#              means `c` was accepted and the residual is the new state.
#
# The whole grammar-constrained-generation concept reduces to: a token is valid
# iff D^*(state, token_text) != Null. That is the mask.

def nullable(n, rules, _guard=None) -> bool:
    if _guard is None:
        _guard = set()
    if isinstance(n, (Null, Lit, Cls)):
        return isinstance(n, Lit) and n.s == ""
    if isinstance(n, Eps):
        return True
    if isinstance(n, Seq):
        return nullable(n.a, rules, _guard) and nullable(n.b, rules, _guard)
    if isinstance(n, Alt):
        return nullable(n.a, rules, _guard) or nullable(n.b, rules, _guard)
    if isinstance(n, Star):
        return True
    if isinstance(n, Plus):
        return nullable(n.a, rules, _guard)
    if isinstance(n, Opt):
        return True
    if isinstance(n, Ref):
        if n.name in _guard:
            return False                 # cycle guard (left recursion)
        _guard.add(n.name)
        return nullable(rules[n.name], rules, _guard)
    return False


def derive(n, c, rules):
    """Brzozowski derivative: residual of `n` after consuming character `c`."""
    key = (c, id(rules))                 # cache per node per char (rules stable)
    if key in n._dcache:
        return n._dcache[key]

    if isinstance(n, Null):
        r = n
    elif isinstance(n, Eps):
        r = Null()
    elif isinstance(n, Lit):
        if n.s and n.s[0] == c:
            r = Lit(n.s[1:]) if len(n.s) > 1 else Eps()
        else:
            r = Null()
    elif isinstance(n, Cls):
        if n.neg:
            ok = c not in n.chars
        else:
            ok = c in n.chars
        r = Eps() if ok else Null()
    elif isinstance(n, Seq):
        da = derive(n.a, c, rules)
        left = mk_seq(da, n.b)
        if nullable(n.a, rules):
            r = mk_alt(left, derive(n.b, c, rules))
        else:
            r = left
    elif isinstance(n, Alt):
        r = mk_alt(derive(n.a, c, rules), derive(n.b, c, rules))
    elif isinstance(n, Star):
        r = mk_seq(derive(n.a, c, rules), Star(n.a))
    elif isinstance(n, Plus):
        # a+  ==  a a*   ->  D(a+, c) = D(a,c) a*
        r = mk_seq(derive(n.a, c, rules), Star(n.a))
    elif isinstance(n, Opt):
        r = derive(n.a, c, rules)
    elif isinstance(n, Ref):
        r = derive(rules[n.name], c, rules)
    else:
        r = Null()

    n._dcache[key] = r
    return r


def derive_str(n, s, rules):
    """Fold `derive` over a whole token string -> residual after the full token."""
    cur = n
    for ch in s:
        cur = derive(cur, ch, rules)
        if is_null(cur):
            return cur                 # short-circuit: token already illegal
    return cur


def valid_chars(n, rules, _guard=None) -> set:
    """The frontier: the set of SINGLE characters that `n` can accept next.

    Used only for DISPLAY / the mask shortcut on single-char vocabs. For
    negated classes we cannot enumerate, so we return a sentinel handled by the
    caller (the token mask falls back to derive_str, which always works).
    """
    if _guard is None:
        _guard = set()
    if isinstance(n, Null) or isinstance(n, Eps):
        return set()
    if isinstance(n, Lit):
        return {n.s[0]} if n.s else set()
    if isinstance(n, Cls):
        return set() if n.neg else set(n.chars)
    if isinstance(n, Seq):
        out = valid_chars(n.a, rules, _guard)
        if nullable(n.a, rules):
            out |= valid_chars(n.b, rules, _guard)
        return out
    if isinstance(n, Alt):
        return valid_chars(n.a, rules, _guard) | valid_chars(n.b, rules, _guard)
    if isinstance(n, (Star, Plus, Opt)):
        return valid_chars(n.a, rules, _guard)
    if isinstance(n, Ref):
        if n.name in _guard:
            return set()
        _guard.add(n.name)
        return valid_chars(rules[n.name], rules, _guard)
    return set()


def describe(n) -> str:
    """Render a residual compactly for tracing."""
    if isinstance(n, Null):
        return "(blocked)"
    if isinstance(n, Eps):
        return "(done)"
    if isinstance(n, Lit):
        return repr(n.s) if n.s else "(done)"
    if isinstance(n, Cls):
        return "[" + ("^" if n.neg else "") + n.label + "]"
    if isinstance(n, Seq):
        return f"({describe(n.a)} {describe(n.b)})"
    if isinstance(n, Alt):
        return f"({describe(n.a)} | {describe(n.b)})"
    if isinstance(n, Star):
        return describe(n.a) + "*"
    if isinstance(n, Plus):
        return describe(n.a) + "+"
    if isinstance(n, Opt):
        return describe(n.a) + "?"
    if isinstance(n, Ref):
        return n.name
    return "?"


# ============================================================================
# 3. Tiny GBNF parser  (text -> rules dict)
# ============================================================================
#
# Tokenize once into a flat list of typed tokens, then recursive-descent parse.
# Token kinds:
#   ('RULE', name)  ('ASSIGN', '::=')  ('LIT', text)  ('CLASS', inner)
#   ('LP',) ('RP',) ('PIPE',) ('PLUS',) ('STAR',) ('OPT',)

_ATOM_START = {"RULE", "LIT", "CLASS", "LP"}

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "-": "-"}


def _tokenize(src: str) -> list[tuple]:
    # strip comments (a '#' to end of line) before tokenizing
    cleaned = []
    for line in src.split("\n"):
        h = line.find("#")
        if h >= 0:
            line = line[:h]
        cleaned.append(line)
    s = "\n".join(cleaned)
    toks = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == '"':                         # literal string
            j = i + 1
            buf = []
            while j < n and s[j] != '"':
                if s[j] == "\\" and j + 1 < n:
                    buf.append(_ESCAPES.get(s[j + 1], s[j + 1]))
                    j += 2
                else:
                    buf.append(s[j])
                    j += 1
            toks.append(("LIT", "".join(buf)))
            i = j + 1
            continue
        if c == "[":                         # char class
            j = i + 1
            while j < n and s[j] != "]":
                j += 1
            toks.append(("CLASS", s[i + 1:j]))
            i = j + 1
            continue
        if s[i:i + 3] == "::=":
            toks.append(("ASSIGN", "::="))
            i += 3
            continue
        if c == "(":
            toks.append(("LP",));  i += 1; continue
        if c == ")":
            toks.append(("RP",));  i += 1; continue
        if c == "|":
            toks.append(("PIPE",)); i += 1; continue
        if c == "+":
            toks.append(("PLUS",)); i += 1; continue
        if c == "*":
            toks.append(("STAR",)); i += 1; continue
        if c == "?":
            toks.append(("OPT",));  i += 1; continue
        if c.isalpha() or c == "_":          # rule name (dashed lowercase)
            j = i
            while j < n and (s[j].isalnum() or s[j] in "-_"):
                j += 1
            toks.append(("RULE", s[i:j]))
            i = j
            continue
        i += 1                                # skip anything unrecognized
    return toks


def _parse_class(inner: str) -> Cls:
    """Parse the inside of [..] into a Cls. Handles a-z ranges and ^ negation."""
    neg = False
    if inner.startswith("^"):
        neg = True
        inner = inner[1:]
    chars = set()
    label_parts = []
    i = 0
    while i < len(inner):
        if inner[i] == "\\" and i + 1 < len(inner):       # escape
            nxt = inner[i + 1]
            chars.add(_ESCAPES.get(nxt, nxt))
            label_parts.append(inner[i:i + 2])
            i += 2
            continue
        if i + 2 < len(inner) and inner[i + 1] == "-":     # range a-z
            lo, hi = inner[i], inner[i + 2]
            for code in range(ord(lo), ord(hi) + 1):
                chars.add(chr(code))
            label_parts.append(f"{lo}-{hi}")
            i += 3
            continue
        chars.add(inner[i])
        label_parts.append(inner[i])
        i += 1
    return Cls(frozenset(chars), neg, "".join(label_parts))


class _Parser:
    """Recursive-descent GBNF parser: grammar -> {rule_name: node}."""

    def __init__(self, src: str):
        self.toks = _tokenize(src)
        self.pos = 0
        self.rules: dict[str, object] = {}

    def _peek(self, ahead=0):
        k = self.pos + ahead
        return self.toks[k][0] if k < len(self.toks) else None

    def _next(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def parse(self) -> dict[str, object]:
        while self.pos < len(self.toks):
            name_tok = self._next()
            assert name_tok[0] == "RULE", f"expected rule name, got {name_tok!r}"
            assign = self._next()
            assert assign[0] == "ASSIGN", \
                f"expected '::=' after {name_tok[1]!r}, got {assign!r}"
            self.rules[name_tok[1]] = self._alt()
        return self.rules

    def _alt(self):
        node = self._seq()
        while self._peek() == "PIPE":
            self._next()
            node = mk_alt(node, self._seq())
        return node

    def _seq(self):
        parts = []
        while self._peek() in _ATOM_START:
            # a RULE token immediately followed by '::=' starts a NEW rule -> stop
            if self._peek() == "RULE" and self._peek(1) == "ASSIGN":
                break
            parts.append(self._factor())
        if not parts:
            return Eps()
        node = parts[0]
        for p in parts[1:]:
            node = mk_seq(node, p)
        return node

    def _factor(self):
        atom = self._atom()
        while self._peek() in ("PLUS", "STAR", "OPT"):
            op = self._next()[0]
            atom = {"PLUS": Plus(atom), "STAR": Star(atom),
                    "OPT": Opt(atom)}[op]
        return atom

    def _atom(self):
        kind, text = self._next()
        if kind == "LP":
            inner = self._alt()
            close = self._next()
            assert close[0] == "RP", "expected ')'"
            return inner
        if kind == "LIT":
            return Lit(text)
        if kind == "CLASS":
            return _parse_class(text)
        return Ref(text)                      # RULE


def parse_gbnf(src: str) -> dict[str, object]:
    return _Parser(src).parse()


# ============================================================================
# 4. Token mask + generation simulator
# ============================================================================

def mask_tokens(state, vocab, rules):
    """Return (valid, invalid) lists of tokens, in VOCAB ORDER.

    A token is VALID iff derive(state, token_text) is not Null - i.e. the
    grammar can accept the token's whole leading string from the current state.
    This mirrors how llama.cpp tests each vocab id against the grammar position
    (it does NOT just look at the first byte).
    """
    valid, invalid = [], []
    for tok in vocab:
        if is_null(derive_str(state, tok, rules)):
            invalid.append(tok)
        else:
            valid.append(tok)
    return valid, invalid


def generate(root, vocab, rules, seed=42, max_steps=24):
    """Step-by-step constrained sampling trace.

    At each step: build the mask, pick a valid token (seeded RNG over the valid
    set, in vocab order for determinism), advance the grammar state. Stop when
    no valid token remains or the residual is the accepting (Eps) state.
    """
    rng = random.Random(seed)
    state = root
    out = ""
    trace = []
    for step in range(max_steps):
        valid, invalid = mask_tokens(state, vocab, rules)
        if not valid:
            trace.append((step, describe(state), valid, invalid, None, out))
            break
        # pick a valid token (deterministic given seed + sorted-by-vocab-order)
        picked = rng.choice(valid)
        trace.append((step, describe(state), valid, invalid, picked, out))
        out += picked
        state = derive_str(state, picked, rules)
        if is_eps(state) or is_null(state):
            trace.append((step + 1, describe(state), [], [], None, out))
            break
    return out, trace


# ============================================================================
# 5. pretty printer + check helper
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(label: str, cond: bool) -> bool:
    status = "OK" if cond else "FAIL"
    print(f"[check] {label}: {cond} -> {status}")
    return cond


# ============================================================================
# 6. Grammar presets  (the tiny grammars we trace)
# ============================================================================

# GOLD grammar. The char class is [abehlo] on purpose: it is the "hello
# alphabet", and it makes `x` / `9` clean out-of-class distractors so the mask
# visibly zeroes them. (A real [a-z] would accept `x`; see Section E.)
GOLD_GBNF = r'''# GOLD grammar:  {  <one or more letters>  }
root   ::= "{" letter+ "}"
letter ::= [abehlo]
'''

JSON_GBNF = r'''# a tiny JSON-ish object:  {"name": "..."}  with optional whitespace
root   ::= "{" ws "\"name\"" ws ":" ws string ws "}"
ws     ::= [ \t\n]*
string ::= "\"" [^"]* "\""
'''

LIST_GBNF = r'''# a markdown-ish list:  "- item\n" repeated
root ::= ("- " [^\n]+ "\n")+
'''


# ============================================================================
# 7. SECTIONS  (the numbers that feed GRAMMAR_OUTPUT.md)
# ============================================================================

def section_a_parse():
    banner("SECTION A: parse GBNF text into a grammar (the tiny parser)")
    print("GBNF source (the GOLD grammar):")
    for line in GOLD_GBNF.strip().split("\n"):
        print("    " + line)
    rules = parse_gbnf(GOLD_GBNF)
    print("\nParsed rules (recursive-descent parser -> AST nodes):")
    for name in sorted(rules):
        print(f"    {name:<7} ::= {describe(rules[name])}")
    check("root rule parsed", "root" in rules and not is_null(rules["root"]))
    check("letter rule is a class",
          isinstance(rules["letter"], Cls) and
          set(rules["letter"].chars) == set("abehlo"))
    return rules


def section_b_derivative(rules):
    banner("SECTION B: the grammar state = Brzozowski derivative")
    print("The state IS the residual grammar after consuming the output so far.")
    print("derive(state, c) returns the residual after eating one char `c`;\n"
          "  Null  = forbidden here (masked);  anything else = accepted.\n")

    state = rules["root"]
    print(f"start state        = {describe(state)}")
    print(f"  valid_chars      = {sorted(valid_chars(state, rules))}")
    print(f"  nullable (accept)= {nullable(state, rules)}\n")

    # walk the input '{' then 'h' then 'e' ..., printing the residual each step
    for ch in ["{", "h", "e", "l", "l", "o", "}"]:
        before = state
        state = derive(state, ch, rules)
        accepted = "ACCEPTED" if not is_null(state) else "REJECTED (masked)"
        print(f"  derive(state, {ch!r:<4}) = {describe(state):<34} {accepted}")
        if is_null(state):
            break
    print(f"\nfinal state        = {describe(state)}  "
          f"(nullable -> output complete & valid)")
    check("input '{hello}' drives state to accepting (Eps)", is_eps(state))
    check("derive(root, '9') is Null (9 is out of class)",
          is_null(derive(rules["root"], "9", rules)))


def section_c_mask(rules):
    banner("SECTION C: token mask = THE GOLD VALUE")
    print("Vocabulary (10 single-char tokens; x and 9 are distractors):")
    vocab = ["{", "a", "b", "h", "e", "l", "o", "}", "x", "9"]
    print("    " + ", ".join(repr(t) for t in vocab) + "\n")

    print("STATE 0  (start, before any token):")
    s0 = rules["root"]
    v0, i0 = mask_tokens(s0, vocab, rules)
    print(f"    valid   = {v0}")
    print(f"    invalid = {i0}")
    print("    -> only '{' can be sampled; the sampler sees all other logits as 0.\n")

    print("STATE 1  (after sampling '{'):")
    s1 = derive(s0, "{", rules)
    v1, i1 = mask_tokens(s1, vocab, rules)
    print(f"    valid   = {v1}")
    print(f"    invalid = {i1}")
    print("    -> the in-class letters are live; '}', 'x', '9', '{' are masked.\n")

    # GOLD assertions (the values badge-checked in grammar_output.html)
    g1 = v0 == ["{"]
    g2 = v1 == ["a", "b", "h", "e", "l", "o"]
    g3 = set(i1) >= {"{", "}", "x", "9"}
    check("STATE 0 valid == ['{']", g1)
    check("STATE 1 valid == ['a','b','h','e','l','o']", g2)
    check("STATE 1 invalid contains '{','}','x','9'", g3)
    return {"vocab": vocab, "s0_valid": v0, "s1_valid": v1, "s1_invalid": i1}


def section_d_generate(rules, gold):
    banner("SECTION D: constrained generation trace (seeded sampler)")
    print("At every step the mask is rebuilt, a valid token is picked (seeded\n"
          "RNG over the valid set), and the grammar state advances. The output\n"
          "is GUARANTEED to parse against the grammar - free sampling is not.\n")
    out, trace = generate(rules["root"], gold["vocab"], rules, seed=13, max_steps=16)
    print("| step | grammar state (residual)            | picked | output so far |")
    print("|------|-------------------------------------|--------|---------------|")
    for step, st, valid, invalid, picked, sofar in trace:
        st_short = (st[:35] + "..") if len(st) > 37 else st
        picked_s = picked if picked is not None else "(stop)"
        sofar_s = repr(sofar) if sofar else ""
        print(f"| {step:<4} | {st_short:<35} | {picked_s:<6} | {sofar_s:<13} |")
    print(f"\nFinal output: {out!r}   (always matches  '{{' letter+ '}}')\n")

    # verify the generated string really parses against the grammar
    state = rules["root"]
    for ch in out:
        state = derive(state, ch, rules)
    check("generated output parses against the grammar (ends accepting)",
          is_eps(state))
    check("generated output starts with '{' and ends with '}'",
          out.startswith("{") and out.endswith("}"))
    return out


def section_e_json():
    banner("SECTION E: a richer grammar (JSON object) + multi-char tokens")
    print("GBNF source (a tiny {\"name\": \"...\"} object grammar):")
    for line in JSON_GBNF.strip().split("\n"):
        print("    " + line)
    rules = parse_gbnf(JSON_GBNF)
    print("\nParsed rules:")
    for name in sorted(rules):
        print(f"    {name:<7} ::= {describe(rules[name])}")

    print("\nSTART state valid_chars (note whitespace is allowed first):")
    vc = sorted(valid_chars(rules["root"], rules))
    print(f"    {vc}\n")

    # multi-char vocabulary: shows the mask checks the WHOLE token, not byte 0
    vocab = ['{', '{"name"', '{"', 'name', '"name"', ':', '"hi"', '"', '}', ' ', '9']
    s0 = rules["root"]
    v0, i0 = mask_tokens(s0, vocab, rules)
    print(f"multi-char vocab: {vocab}")
    print(f"  valid   = {v0}")
    print(f"  invalid = {i0}")
    print('  -> \'{"name"\' and \'{"\' are valid (the whole token fits the state);')
    print('     \'{\\"name\\"\' even pre-types the key. \'{\\"\' alone is the minimal')

    # advance to just after {"  and show the mask there
    s_after = derive_str(rules["root"], '{"', rules)
    va, ia = mask_tokens(s_after, vocab, rules)
    print(f"\nSTATE after consuming '{{\"' :")
    print(f"  valid   = {va}")
    print(f"  invalid = {ia}")
    print('  -> only \'name\' (continuing the key) or the rest of the key is live.')

    check("'{\"name\"' accepted at start (whole token fits)",
          '{"name"' in v0)
    check("'9' masked at start (not allowed by grammar)", "9" in i0)
    check("after '{\"', '\"name\"' is NOT yet valid (key incomplete)",
          '"name"' not in va)


# ----------------------- THE GOLD CENTERPIECE --------------------------------

def section_gold(rules, gold):
    banner("SECTION G: GOLD mask trace (the centerpiece)")
    print("GOLD grammar : root ::= \"{\" letter+ \"}\"   letter ::= [abehlo]")
    print("Vocabulary   : " + ", ".join(repr(t) for t in gold["vocab"]) + "\n")

    s0 = rules["root"]
    s1 = derive(s0, "{", rules)
    v0, _ = mask_tokens(s0, gold["vocab"], rules)
    v1, i1 = mask_tokens(s1, gold["vocab"], rules)

    print("STATE 0 (start)        valid = " + str(v0))
    print("STATE 1 (after '{')    valid = " + str(v1))
    print("STATE 1 (after '{')    invalid= " + str(i1))

    g1 = v0 == ["{"]
    g2 = v1 == ["a", "b", "h", "e", "l", "o"]
    g3 = set(i1) >= {"{", "}", "x", "9"}
    check("GOLD state-0 valid == ['{']", g1)
    check("GOLD state-1 valid == ['a','b','h','e','l','o']", g2)
    check("GOLD state-1 invalid contains '{','}','x','9'", g3)

    print("\nGOLD (recomputed & badge-checked in grammar_output.html):")
    print(f"  state-0 valid   = {v0}")
    print(f"  state-1 valid   = {v1}")
    return {"v0": v0, "v1": v1, "i1": i1, "gold_ok": g1 and g2 and g3}


# ============================================================================
# main
# ============================================================================

def main():
    print("grammar_output.py - reference impl. All numbers feed GRAMMAR_OUTPUT.md.")
    print("pure Python stdlib (no torch, no numpy). Tiny GBNF parser + derivative")
    print("token-mask simulator. Models llama.cpp's --grammar constrained sampling.")

    rules = section_a_parse()
    section_b_derivative(rules)
    gold = section_c_mask(rules)
    section_d_generate(rules, gold)
    section_e_json()
    g = section_gold(rules, gold)

    banner("DONE - all sections printed; gold = " +
           ("OK" if g["gold_ok"] else "FAIL"))


if __name__ == "__main__":
    main()
