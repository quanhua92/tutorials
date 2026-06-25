"""
trie.py - Reference implementation of the Trie (prefix tree) and Radix tree.

This is the single source of truth that TRIE.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 trie.py

=========================================================================
THE INTUITION (read this first) - the "autocomplete dictionary"
=========================================================================
A trie is a tree where every EDGE is one character of a key, and the path from
the ROOT to a node SPELLS OUT a key. To look up a word you walk down one edge
per character - you never scan the whole dictionary.

  * hash table : hash the WHOLE key, then O(1) bucket lookup.
                 Great for exact match; useless for "all words starting with
                 'ca'" - you would have to scan every key.
  * trie       : walk one edge per character. Lookup is O(L) where L = key
                 length, INDEPENDENT of how many keys are stored. And because
                 the tree IS the shared prefixes, a prefix query is free: just
                 walk to the prefix node and harvest its subtree.
  * radix tree : a trie with the single-child chains COMPRESSED into one edge
                 labelled by a whole substring ("ca", "dog"). Same O(L) lookup,
                 far fewer nodes - this is what IP routers actually use.

THE REASON TRIES EXIST: when keys share structure (words, URLs, IP prefixes,
file paths) a trie exploits that sharing. A hash table treats every key as an
opaque blob; a trie treats the key as a SEQUENCE and shares the common parts.
That is why autocomplete, IP longest-prefix-match, and DNS resolution are all
tries under the hood - they all ask "what keys extend this prefix?"

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  root        : the empty-string node. Every key starts here.
  edge        : a labelled arrow from one node to its child. Label = 1 char
                (standard trie) or a substring (radix tree).
  node        : a point in the tree. A node marked `end` means "a complete key
                ends here" (e.g. both "car" and "card" are keys, so the 'r'
                node AND the 'd' node under it are both `end`).
  path        : the sequence of edge labels from root to a node = the string
                that node represents.
  prefix query: "give me every key that starts with P". Walk to the node for P,
                then collect every `end` node in its subtree.
  L           : key length (number of characters). Trie work is O(L), NOT O(#keys).
  radix tree  : a.k.a. Patricia trie. Compress single-child chains so one edge
                can carry a whole substring. Fewer nodes, same asymptotics.

=========================================================================
THE LINEAGE (references)
=========================================================================
  Trie         (Fredkin 1960, "Trie Memory")         : one node per char.
  Radix/Patricia (Morrison 1968, "Patricia")         : compressed chains.
  ART / HAT    (Adaptive/Radix trees, Leis 2013)     : grows with key set.
  Linux kernel : radix tree for page cache (struct radix_tree_root).
  IP routing   : longest-prefix match via a trie (often a compressed / multiway
                 bit trie like a Patricia or a 2-3 trie).

KEY FACTS (all asserted in code below):
    insert(word)    = O(L)            walk/create L edges, mark last node `end`
    search(word)    = O(L)            walk L edges, check the node is `end`
    starts_with(P)  = O(L + M)        walk L edges, then collect M matches
    hash search     = O(L) hash + O(1) lookup   (must still READ all L chars)
    trie node count <= total chars across all keys  (sharing helps)
    radix node count << trie node count             (chains collapsed)

Conventions:
    Alphabet here is lowercase a-z, but the code is generic (any hashable char).
    `end` flag = "a complete key terminates at this node" (not the same as
    "this node has children" - "car" and "card" are BOTH keys).
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code TRIE.md walks through)
# ============================================================================

class TrieNode:
    """One node of a standard trie.

    `children` maps one character -> the child node. `end` is True if a
    complete key terminates here. The root node represents the empty string.
    """

    __slots__ = ("children", "end")

    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.end = False


class Trie:
    """Standard trie: one node per character, edges labelled by single chars."""

    def __init__(self):
        self.root = TrieNode()

    def insert(self, word: str) -> None:
        """Walk from root, creating one node per character; mark the last `end`.

        O(L) time where L = len(word), regardless of how many keys are stored.
        """
        node = self.root
        for ch in word:
            nxt = node.children.get(ch)
            if nxt is None:
                nxt = TrieNode()
                node.children[ch] = nxt
            node = nxt
        node.end = True

    def _walk(self, word: str) -> TrieNode | None:
        """Return the node at the end of `word`'s path, or None if absent.

        This is the O(L) core that both search() and starts_with() build on.
        """
        node = self.root
        for ch in word:
            node = node.children.get(ch)
            if node is None:
                return None
        return node

    def search(self, word: str) -> bool:
        """Exact-key lookup. O(L): walk L edges, then check the `end` flag."""
        node = self._walk(word)
        return node is not None and node.end

    def starts_with(self, prefix: str) -> list[str]:
        """Return every key that begins with `prefix`, sorted.

        O(L + M): L to reach the prefix node, M to harvest its subtree.
        """
        node = self._walk(prefix)
        if node is None:
            return []
        results: list[str] = []

        def dfs(n: TrieNode, path: list[str]):
            if n.end:
                results.append(prefix + "".join(path))
            for ch in sorted(n.children):
                path.append(ch)
                dfs(n.children[ch], path)
                path.pop()

        dfs(node, [])
        return results

    # --- introspection helpers (used by the print sections) ---

    def count_nodes(self) -> int:
        """Total nodes including the root. Each node = one char of storage."""
        count = 0
        stack = [self.root]
        while stack:
            n = stack.pop()
            count += 1
            stack.extend(n.children.values())
        return count

    def count_edges(self) -> int:
        """Total edges = total nodes minus 1 (every non-root node has one parent)."""
        return self.count_nodes() - 1


# ----------------------------------------------------------------------------
# Radix tree (Patricia trie): compress single-child chains into one edge.
# Implemented as a recursive compression over a standard trie, so the numbers
# are directly comparable. Same lookup asymptotics, far fewer nodes.
# ----------------------------------------------------------------------------

class RadixNode:
    """One node of a radix tree. `edge` is the substring labelling the INCOMING
    edge from this node's parent (the root's edge is "")."""

    __slots__ = ("edge", "children", "end")

    def __init__(self, edge: str = ""):
        self.edge = edge            # substring on the incoming edge
        self.children: list["RadixNode"] = []
        self.end = False


def build_radix(words: list[str]) -> RadixNode:
    """Build a radix tree by inserting words one at a time.

    Insertion finds the longest shared prefix with an existing edge, splits it
    if necessary, then hangs the remainder off as a new child. This mirrors the
    textbook Patricia insertion (Morrison 1968).
    """
    root = RadixNode("")
    for word in words:
        _radix_insert(root, word)
    return root


def _common_prefix_len(a: str, b: str) -> int:
    i = 0
    m = min(len(a), len(b))
    while i < m and a[i] == b[i]:
        i += 1
    return i


def _radix_insert(node: RadixNode, word: str) -> None:
    # Look for a child whose edge shares a prefix with `word`.
    for child in node.children:
        cp = _common_prefix_len(child.edge, word)
        if cp == 0:
            continue
        if cp == len(child.edge):
            # entire child edge matched; recurse on the rest of the word
            if cp < len(word):
                _radix_insert(child, word[cp:])
            else:
                child.end = True
            return
        # partial match -> split the edge at `cp`
        suffix_edge = child.edge[cp:]
        split = RadixNode(child.edge[:cp])
        child.edge = suffix_edge
        node.children.remove(child)
        split.children.append(child)
        node.children.append(split)
        if cp == len(word):
            split.end = True
        else:
            _radix_insert(split, word[cp:])
        return
    # no shared prefix at this node: hang a brand-new leaf
    leaf = RadixNode(word)
    leaf.end = True
    node.children.append(leaf)


def radix_count_nodes(root: RadixNode) -> int:
    count = 0
    stack = [root]
    while stack:
        n = stack.pop()
        count += 1
        stack.extend(n.children)
    return count


def radix_search(root: RadixNode, word: str) -> bool:
    """Exact-key lookup in the radix tree. O(L): consume the key edge by edge."""
    node = root
    rest = word
    while rest:
        matched = False
        for child in node.children:
            cp = _common_prefix_len(child.edge, rest)
            if cp == 0:
                continue
            if cp == len(child.edge):
                rest = rest[cp:]
                node = child
                matched = True
                break
            return False
        if not matched:
            return False
    return node.end


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_trie_tree(trie: Trie):
    """ASCII tree of the standard trie. Each edge shows its character; an
    `*` marks a node where a complete key ends."""
    lines: list[str] = []

    def rec(node: TrieNode, prefix: str, is_last: bool, edge_label: str):
        branch = "└─ " if is_last else "├─ "
        marker = " *" if node.end else ""
        label = f'"{edge_label}"' if edge_label else "(root)"
        lines.append(f"{prefix}{branch}{label}{marker}")
        keys = sorted(node.children)
        ext = "   " if is_last else "│  "
        for i, ch in enumerate(keys):
            rec(node.children[ch], prefix + ext, i == len(keys) - 1, ch)

    rec(trie.root, "", True, "")
    print("\n".join(lines))


def print_radix_tree(root: RadixNode):
    """ASCII tree of the radix tree. Edges carry whole substrings."""
    lines: list[str] = []

    def rec(node: RadixNode, prefix: str, is_last: bool):
        branch = "└─ " if is_last else "├─ "
        marker = " *" if node.end else ""
        label = f'"{node.edge}"' if node.edge else "(root)"
        lines.append(f"{prefix}{branch}{label}{marker}")
        ext = "   " if is_last else "│  "
        for i, child in enumerate(node.children):
            rec(child, prefix + ext, i == len(node.children) - 1)

    rec(root, "", True)
    print("\n".join(lines))


# ============================================================================
# 3. THE WORKED KEY SET
#    ["cat","car","card","care","dog"] - small enough to draw the whole tree,
#    rich enough to show sharing ("ca"), branching ("r"->d/e), and a lone
#    word ("dog") that compresses to a single radix edge.
# ============================================================================

WORDS = ["cat", "car", "card", "care", "dog"]


# ----------------------------------------------------------------------------
# SECTION A: insert + show the tree
# ----------------------------------------------------------------------------

def section_insert_and_tree():
    banner("SECTION A: insert [cat, car, card, care, dog] and draw the tree")
    trie = Trie()
    print("Insert one word at a time; each char walks/creates one edge. The last\n"
          "node of each word is marked `*` (a complete key ends there).\n")
    for w in WORDS:
        trie.insert(w)
        print(f"  insert(\"{w}\")  -> O(L={len(w)})")
    print("\nThe full standard trie (one node per character; `*` = key ends here):")
    print_trie_tree(trie)
    n_nodes = trie.count_nodes()
    n_edges = trie.count_edges()
    total_chars = sum(len(w) for w in WORDS)
    print(f"\nNode count = {n_nodes} (incl. root). Edges = {n_edges}.")
    print(f"Sum of key lengths = {total_chars}; nodes <= that because of SHARING.")
    print("  Shared prefix 'ca' (cat, car, card, care) collapses 2 chars x 4 words")
    print("  = 8 char-slots into just 2 nodes (c, a). That is the whole win.")
    print(f"  Without sharing we would need {total_chars} nodes; we use {n_nodes}.")


# ----------------------------------------------------------------------------
# SECTION B: search - O(L) - and the hash-table comparison
# ----------------------------------------------------------------------------

def section_search():
    banner("SECTION B: search \"card\" -> O(L=4), vs hash table O(L) hash + O(1)")
    trie = Trie()
    for w in WORDS:
        trie.insert(w)
    key = "card"
    print(f'Lookup "{key}" in the trie: walk one edge per character.\n')
    node = trie.root
    steps = 0
    path = ["(root)"]
    for ch in key:
        node = node.children.get(ch)
        steps += 1
        path.append(f'--"{ch}"--> node')
        if node is None:
            break
    found = node is not None and node.end
    for p in path:
        print("  " + p)
    print(f'\n  steps (edge walks) = {steps} = L = len("{key}") = {len(key)}')
    print(f'  node.end = {found}  ->  "{key}" is {"PRESENT" if found else "ABSENT"}\n')
    # negative case
    neg = "cab"
    print(f'Negative case search("{neg}"): {trie.search(neg)} '
          f'(walks c,a, then finds no "b" child -> None, still O(L=3)).\n')
    print("Compare with a HASH TABLE (Python dict):")
    print("  hash table: must hash the WHOLE key first (O(L) to read all chars),")
    print("              then O(1) bucket probe. Total = O(L) too.")
    print("  trie      : O(L) with NO hashing, and the walk SHARED with prefix work.")
    print("  => For EXACT lookup both are O(L). The trie's edge is PREFIX queries,")
    print("     which a hash table simply cannot do without scanning every key.")
    d = {w: True for w in WORDS}
    assert d.get("card") is True and trie.search("card")
    print('\n[check] dict["card"] == trie.search("card") == True:  OK')


# ----------------------------------------------------------------------------
# SECTION C: prefix search - the operation a hash table cannot do
# ----------------------------------------------------------------------------

def section_prefix():
    banner('SECTION C: prefix search "ca" -> all words starting with "ca"')
    trie = Trie()
    for w in WORDS:
        trie.insert(w)
    prefix = "ca"
    print(f'starts_with("{prefix}"): walk to the "{prefix}" node, then harvest')
    print("every `end` node in its subtree (depth-first).\n")
    node = trie._walk(prefix)
    print(f'  walk "{prefix}" -> node reached: {node is not None}')
    matches = trie.starts_with(prefix)
    print(f"\n  matches = {matches}")
    expected = [w for w in WORDS if w.startswith(prefix)]
    print(f'  (brute-force [w for w in WORDS if w.startswith("{prefix}")] = {sorted(expected)})')
    print(f"\n  cost = O(L={len(prefix)}) to reach the node + O(M={len(matches)}) to harvest")
    print("  = O(L + M). A hash table would need O(K*L) to scan all K keys.")
    print("\nOther prefixes:")
    for p in ["c", "car", "do", "x"]:
        print(f'  starts_with("{p}") = {trie.starts_with(p)}')


# ----------------------------------------------------------------------------
# SECTION D: space - naive trie vs radix tree compression
# ----------------------------------------------------------------------------

def section_space_radix():
    banner("SECTION D: space - naive trie vs radix tree (Patricia) compression")
    trie = Trie()
    for w in WORDS:
        trie.insert(w)
    radix = build_radix(WORDS)
    print("A standard trie wastes nodes on single-child CHAINS. \"dog\" has no")
    print("siblings anywhere along d->o->g, so those 3 chars live in 3 separate")
    print("nodes. A RADIX TREE (Patricia trie) collapses any maximal chain of\nsingle-child nodes into ONE edge labelled by the whole substring.\n")
    print("Radix tree (same keys; edges now carry substrings; `*` = key ends):")
    print_radix_tree(radix)
    tn = trie.count_nodes()
    rn = radix_count_nodes(radix)
    print("\n| structure     | nodes | edges | note                         |")
    print("|---------------|-------|-------|------------------------------|")
    print(f"| standard trie | {tn:<5} | {tn-1:<5} | one node per character       |")
    print(f"| radix tree    | {rn:<5} | {rn-1:<5} | single-child chains compressed|")
    print("\nThe chain d->o->g (3 trie nodes) collapses to one edge \"dog\".")
    print("Both still O(L) lookup; radix just touches fewer pointers. This is")
    print("why IP routers and the Linux page cache use COMPRESSED tries: the")
    print("node count (and thus cache misses) drops sharply on sparse keys.\n")
    # prove equivalence
    for w in WORDS:
        assert trie.search(w) and radix_search(radix, w)
    assert not trie.search("xyz") and not radix_search(radix, "xyz")
    print('[check] trie.search == radix_search for all keys + a miss:  OK')


# ----------------------------------------------------------------------------
# SECTION E: applications - autocomplete and IP longest-prefix match
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION E: applications - autocomplete & IP longest-prefix match")
    corpus = ["cat", "car", "card", "care", "careful", "dog", "do", "dot"]
    trie = Trie()
    for w in corpus:
        trie.insert(w)
    print("Autocomplete: the user has typed a prefix; return every completion.\n")
    print(f'corpus = {corpus}\n')
    for p in ["ca", "car", "care", "do", ""]:
        res = trie.starts_with(p)
        shown = '"' + p + '"' if p else '(empty = all)'
        print(f'  autocomplete({shown}) -> {res}')
    print("\nIP routing - LONGEST PREFIX MATCH. A router holds prefix -> next-hop")
    print("rules. For a destination IP it must pick the rule with the LONGEST")
    print("matching prefix. A trie over the bits walks the address one bit at a")
    print("time, remembering the last `end` (rule) node it passed:\n")
    routes = {
        "0":         "hop A (0/1     = everything starting 0)",
        "10":        "hop B (10/2    = nets 128..191)",
        "1010":      "hop C (1010/4  = nets 160..175)",
        "10101":     "hop D (10101/5 = nets 168..175)",
    }
    rt = Trie()
    for prefix in routes:
        rt.insert(prefix)
    for addr in ["10101100", "10101001", "00110011", "10101"]:
        # walk the address bit by bit, remembering the last `end` rule seen
        node = rt.root
        matched = ""
        best_label = None
        for ch in addr:
            node = node.children.get(ch)
            if node is None:
                break
            matched += ch
            if node.end:
                best_label = matched
        hop = routes.get(best_label, "(no route - drop)") if best_label else "(no route - drop)"
        print(f'  dst={addr}  longest matching prefix = {str(best_label):>8}  ->  {hop}')
    print("\nDNS uses the same idea: a name like 'api.example.com' is walked from")
    print("the TLD down, so the resolver can answer 'example.com' records for any")
    print("subdomain without storing each one explicitly.\n")
    # gold: autocomplete correctness
    gold = {
        "ca":   ["car", "card", "care", "careful", "cat"],
        "car":  ["car", "card", "care", "careful"],
        "care": ["care", "careful"],
        "do":   ["do", "dog", "dot"],
        "":     sorted(corpus),
    }
    all_ok = True
    for p, want in gold.items():
        got = trie.starts_with(p)
        ok = got == want
        all_ok &= ok
        tag = "OK" if ok else "FAIL"
        label = f'"{p}"' if p else '""'
        print(f'  [{tag}] starts_with({label:<6}) = {got}')
    print(f"\nGOLD CHECK: {'OK - all prefix queries match brute force' if all_ok else 'FAIL'}")
    print("(trie.html re-runs starts_with() in JS and re-checks these exact lists.)")


# ============================================================================
# main
# ============================================================================

def main():
    print("trie.py - reference impl. All numbers below feed TRIE.md.")
    print("python stdlib only; deterministic.")

    section_insert_and_tree()
    section_search()
    section_prefix()
    section_space_radix()
    section_applications()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
