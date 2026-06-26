"""
trie.py - Reference implementation of the Trie (prefix tree) pattern for:
prefix matching / autocomplete, wildcard dictionary search (P211), and
word search on a character grid (P212).

This is the SINGLE SOURCE OF TRUTH for TRIE.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 trie.py > trie_output.txt

Pure Python stdlib only. Deterministic (no random, no PYTHONHASHSEED
dependence: children are visited in sorted order for stable traces).

============================================================================
THE INTUITION (read this first) - a tree grown from shared beginnings
============================================================================
Imagine a dictionary where you look up a word by walking letter by letter.
"car", "cat", and "cart" share the first two letters "ca", so instead of
storing "ca" three times, the trie stores one path c -> a, then SPLITS into
"r" (car), "t" (cat), and "r -> t" (cart). This is a tree whose EDGES are
characters and whose NODES are positions inside words.

The mechanism, in three moves:

    word --insert--> walk root->...->leaf, creating missing nodes
                     mark the final node is_end = True
    word --search--> walk root->...->leaf, return (reached AND is_end)
    prefix --starts_with--> walk root->..., return (reached at all)

The is_end flag is the CRITICAL detail: it is what separates
search("app") == False from starts_with("app") == True when only "apple"
has been inserted.

Three interview idioms all reuse this one structure:

    1. PREFIX OPERATIONS      - "autocomplete", "all words starting with X" (P208)
    2. WILDCARD DICTIONARY    - "search with '.' matches any char"          (P211)
    3. WORD SEARCH ON GRID    - "find dictionary words in a Boggle board"   (P212)

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  trie          a tree where each EDGE is labeled with one character.
  node          a position in the tree; holds children {char: node} + is_end.
  root          the empty-string node; every word starts descending from it.
  is_end        True if some inserted word ENDS at this node. Distinguishes
                search from starts_with. Without it both behave identically.
  children      dict mapping the next character -> the child node. (Alternative:
                a fixed array of 26 for lowercase-only alphabets, ~3-5x faster.)
  prefix        a path from the root to some node (not necessarily an is_end).
  wildcard '.'  matches ANY single character (P211); at a '.', branch into ALL
                children of the current node (DFS or BFS).
  pruning       in grid search, after finding a word null its word field and
                pop childless nodes from their parent so dead branches are not
                re-explored (kills the P212 TLE).

============================================================================
THE SKELETON (the three idioms share TrieNode)
============================================================================
    class TrieNode:
        def __init__(self):
            self.children = {}          # char -> TrieNode
            self.is_end = False         # marks end of a complete word
            self.word = None            # full word (for grid search, P212)

    class Trie:                                     # P208
        def insert(self, w):
            node = self.root
            for ch in w:
                node = node.children.setdefault(ch, TrieNode())
            node.is_end = True

    def wildcard_search(root, pattern):             # P211
        def dfs(node, i):
            if i == len(pattern): return node.is_end
            ch = pattern[i]
            if ch == '.':
                return any(dfs(c, i+1) for c in node.children.values())
            return ch in node.children and dfs(node.children[ch], i+1)
        return dfs(root, 0)
"""

from __future__ import annotations


# ============================================================================
# TRIENODE + TRIE  (P208 Implement Trie - the foundation)
# ============================================================================
class TrieNode:
    """A single trie node.

    children : dict mapping one character -> child TrieNode.
    is_end   : True if a complete inserted word ends here.
    word     : the full word, set on the end node; used by grid search (P212)
               to record which word was found, and nulled after collecting it.
    """

    __slots__ = ("children", "is_end", "word")

    def __init__(self) -> None:
        self.children: dict[str, TrieNode] = {}
        self.is_end: bool = False
        self.word: str | None = None


class Trie:
    """P208 Implement Trie (Prefix Tree).

    insert / search / starts_with are all O(L) where L = word length.
    Space is O(total chars) worst case but shared prefixes compress hard.
    """

    def __init__(self) -> None:
        self.root = TrieNode()
        self.node_count = 1            # root counts as one node

    def insert(self, word: str) -> None:
        """Insert *word*: walk from root, creating any missing child nodes,
        then set is_end on the final node."""
        node = self.root
        for ch in word:
            if ch not in node.children:
                node.children[ch] = TrieNode()
                self.node_count += 1
            node = node.children[ch]
        node.is_end = True

    def _find(self, prefix: str) -> TrieNode | None:
        """Walk the trie following *prefix*. Return the terminal node or None."""
        node = self.root
        for ch in prefix:
            if ch not in node.children:
                return None
            node = node.children[ch]
        return node

    def search(self, word: str) -> bool:
        """True iff *word* was inserted (reached a node AND is_end)."""
        node = self._find(word)
        return node is not None and node.is_end

    def starts_with(self, prefix: str) -> bool:
        """True iff ANY inserted word begins with *prefix* (is_end ignored)."""
        return self._find(prefix) is not None


def insert_with_trace(trie: Trie, word: str) -> list[dict]:
    """Insert *word* into *trie* and return a per-character trace.

    Each step records: char index, the character, whether the node already
    existed (shared) or was newly created, and whether it is a word end.
    Used by Section A to show prefix compression character by character.
    """
    steps: list[dict] = []
    node = trie.root
    created = 0
    shared = 0
    for i, ch in enumerate(word):
        if ch in node.children:
            shared += 1
            steps.append({"idx": i, "char": ch, "action": "shared"})
            node = node.children[ch]
        else:
            node.children[ch] = TrieNode()
            trie.node_count += 1
            created += 1
            steps.append({"idx": i, "char": ch, "action": "new"})
            node = node.children[ch]
        if node.is_end:
            steps[-1]["word_end"] = word
    node.is_end = True
    steps.append({"idx": len(word), "char": "", "action": "done",
                  "word": word, "created": created, "shared": shared})
    return steps


def render_tree(trie: Trie) -> str:
    """Pretty-print the trie as an indented tree using box-drawing characters.

    Edges are characters; '●' marks an is_end node (a complete word).
    Children are visited in sorted character order for a deterministic layout.
    """
    lines: list[str] = []

    def dfs(node: TrieNode, prefix: str, edge_char: str,
            is_last: bool, is_root: bool) -> None:
        if is_root:
            lines.append("root")
            child_prefix = ""
        else:
            connector = "L__ " if is_last else "|-- "
            mark = " (*)" if node.is_end else ""
            lines.append(f"{prefix}{connector}{edge_char}{mark}")
            child_prefix = prefix + ("    " if is_last else "|   ")
        items = sorted(node.children.items())
        for idx, (ch, child) in enumerate(items):
            last = (idx == len(items) - 1)
            dfs(child, child_prefix, ch, last, False)

    dfs(trie.root, "", "", True, True)
    return "\n".join(lines)


# ============================================================================
# PROBLEM 2 - P211 DESIGN ADD AND SEARCH WORDS DATA STRUCTURE (wildcard '.')
# ============================================================================
class WordDictionary:
    """P211. A trie whose search accepts '.' as a wildcard for any one char.

    addWord is identical to Trie.insert.
    search splits at '.': branch into ALL children and recurse (DFS).
    Worst case O(26^k * L) where k = number of '.' in the pattern, but in
    practice the trie prunes most branches immediately (no matching child).

    GOTCHA: at the END of the pattern you MUST check is_end, just like search.
    """

    def __init__(self) -> None:
        self.root = TrieNode()

    def add_word(self, word: str) -> None:
        node = self.root
        for ch in word:
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
        node.is_end = True

    def search(self, word: str) -> bool:
        def dfs(node: TrieNode, i: int) -> bool:
            if i == len(word):
                return node.is_end
            ch = word[i]
            if ch == ".":
                for child in node.children.values():
                    if dfs(child, i + 1):
                        return True
                return False
            if ch not in node.children:
                return False
            return dfs(node.children[ch], i + 1)

        return dfs(self.root, 0)


def trace_wildcard(wd: WordDictionary, pattern: str) -> list[dict]:
    """Trace the wildcard DFS: record each node visited, the char matched, the
    depth, and whether the branch succeeded. Used by Section B."""
    trace: list[dict] = []
    success = [False]

    def dfs(node: TrieNode, i: int, via: str) -> bool:
        at_end = (i == len(pattern))
        trace.append({"depth": i, "via": via, "is_end": node.is_end,
                      "at_pattern_end": at_end,
                      "char": pattern[i] if not at_end else ""})
        if at_end:
            return node.is_end
        ch = pattern[i]
        if ch == ".":
            for cch in sorted(node.children):
                if dfs(node.children[cch], i + 1, cch):
                    success[0] = True
                    return True
            return False
        if ch not in node.children:
            return False
        return dfs(node.children[ch], i + 1, ch)

    result = dfs(wd.root, 0, "(root)")
    trace.append({"result": result, "pattern": pattern})
    return trace


# ============================================================================
# PROBLEM 3 - P212 WORD SEARCH II (trie + backtracking on a grid)
# ============================================================================
def find_words(board: list[list[str]], words: list[str],
               trace: list | None = None) -> list[str]:
    """P212 Word Search II.

    Build ONE trie from all words (storing the full word at each end node),
    then run a SINGLE backtracking DFS over the grid that simultaneously
    follows trie edges. When a node.word is hit, record the word, null the
    field (avoid duplicates), and prune childless branches on the way back.

    CRITICAL optimizations:
      * mark the cell visited in-place (board[r][c] = '#'), restore after;
        O(1) extra space vs an O(M*N) visited set.
      * prune: after backtracking, if a child has no children and no word,
        pop it from the parent so the dead branch is never re-explored.
        This is what prevents the TLE on large inputs.

    Time:  O(M*N * 4^L) worst case, but trie pruning makes it far faster.
    Space: O(W*L) for the trie + O(L) recursion stack.
    """
    root = TrieNode()
    for w in words:
        node = root
        for ch in w:
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
        node.is_end = True
        node.word = w

    rows, cols = len(board), len(board[0])
    found: list[str] = []

    def dfs(r: int, c: int, parent: TrieNode) -> None:
        ch = board[r][c]
        if ch not in parent.children:
            return
        node = parent.children[ch]
        if trace is not None:
            trace.append({"event": "descend", "r": r, "c": c, "char": ch})
        if node.word is not None:
            found.append(node.word)
            if trace is not None:
                trace.append({"event": "found", "r": r, "c": c,
                              "word": node.word})
            node.word = None              # avoid finding the same word twice
        board[r][c] = "#"                 # mark visited in-place
        for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and board[nr][nc] != "#":
                dfs(nr, nc, node)
        board[r][c] = ch                  # restore on backtrack
        if not node.children and node.word is None:
            del parent.children[ch]        # prune the now-dead branch
            if trace is not None:
                trace.append({"event": "prune", "r": r, "c": c, "char": ch})

    for r in range(rows):
        for c in range(cols):
            if root.children:             # stop early once trie is empty
                dfs(r, c, root)
    return found


def count_nodes(board: list[list[str]], words: list[str]) -> int:
    """Count the trie nodes for the given words (for the compression stat)."""
    root = TrieNode()
    n = 1
    for w in words:
        node = root
        for ch in w:
            if ch not in node.children:
                node.children[ch] = TrieNode()
                n += 1
            node = node.children[ch]
    return n


def find_path(board: list[list[str]], word: str) -> list[tuple[int, int]] | None:
    """Return one valid grid path spelling *word*, or None. For the worked
    example trace (Section C) only - find_words itself does not need this."""
    rows, cols = len(board), len(board[0])
    path: list[tuple[int, int]] = []

    def dfs(r: int, c: int, i: int) -> bool:
        if i == len(word):
            return True
        if (r < 0 or r >= rows or c < 0 or c >= cols
                or board[r][c] != word[i] or (r, c) in path):
            return False
        path.append((r, c))
        for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            if dfs(r + dr, c + dc, i + 1):
                return True
        path.pop()
        return False

    for r in range(rows):
        for c in range(cols):
            if dfs(r, c, 0):
                return path
    return None


# ============================================================================
# SECTION A - TRIE FUNDAMENTALS: insert trace + tree rendering (P208)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - Trie fundamentals: character-by-character tree building")
    print("=" * 72)
    print()
    print("Mechanism:  word -> walk root..leaf, create missing nodes, set is_end")
    print("Edges ARE characters; nodes ARE positions; '*' marks a word's end.")
    print()
    words = ["app", "apple", "apply", "apt", "bat"]
    total_chars = sum(len(w) for w in words)
    print(f"Insert {len(words)} words: {words}")
    print(f"  raw characters = {total_chars}")
    print()
    trie = Trie()
    for w in words:
        steps = insert_with_trace(trie, w)
        final = steps[-1]
        print(f'  Insert "{w}" ({len(w)} chars): '
              f'{final["created"]} new, {final["shared"]} shared')
        for s in steps[:-1]:
            tag = "NEW node" if s["action"] == "new" else "shared"
            we = f'  -> WORD END "{s["word_end"]}"' if "word_end" in s else ""
            print(f'    idx {s["idx"]}  char {s["char"]!r}  {tag}{we}')
        print()
    print("Resulting prefix tree ('*' = is_end, a complete word):")
    print()
    for line in render_tree(trie).splitlines():
        print("    " + line)
    print()
    nodes = trie.node_count
    shared = total_chars - (nodes - 1)
    pct = 100.0 * shared / total_chars
    print(f"  raw chars inserted = {total_chars}")
    print(f"  trie nodes (excl root) = {nodes - 1}")
    print(f"  shared characters = {shared}  ({pct:.0f}% prefix compression)")
    print()
    print("The is_end flag is what separates search from starts_with:")
    print('    search("app")   ->', trie.search("app"),     "  (app was inserted)")
    print('    search("ap")    ->', trie.search("ap"),      "  (prefix only, no is_end)")
    print('    search("apple") ->', trie.search("apple"),   "  (full word)")
    print('    search("apt")   ->', trie.search("apt"),     "  (full word)")
    print('    search("bat")   ->', trie.search("bat"),     "  (full word)")
    print('    search("ba")    ->', trie.search("ba"),      "  (prefix only)")
    print()
    print('    starts_with("ap")  ->', trie.starts_with("ap"),  "  (app/apple/apt...)")
    print('    starts_with("app") ->', trie.starts_with("app"), "  (multiple words)")
    print('    starts_with("xyz") ->', trie.starts_with("xyz"), "  (dead branch)")
    print()
    print("search vs starts_with: search REQUIRES is_end; starts_with only")
    print("requires that the walk reached the end of the prefix. Forgetting")
    print("the is_end check is the #1 trie interview bug.")
    print()


# ============================================================================
# SECTION B - P211 DESIGN ADD AND SEARCH WORDS (wildcard '.')
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P211 Design Add and Search Words (wildcard '.')")
    print("=" * 72)
    print()
    print("Same trie as P208, but search treats '.' as 'match ANY character'.")
    print("At a '.', branch into ALL children of the current node (DFS).")
    print()
    wd = WordDictionary()
    for w in ("bad", "dad", "mad"):
        wd.add_word(w)
    print("addWord: bad, dad, mad")
    print()
    print("Trie after inserts:")
    print()
    t = Trie()
    for w in ("bad", "dad", "mad"):
        t.insert(w)
    for line in render_tree(t).splitlines():
        print("    " + line)
    print()
    queries = ["pad", "bad", ".ad", "b..", "...", ".."]
    print("  query      result   why")
    print("  ---------- ------   -----------------------------------------")
    for q in queries:
        r = wd.search(q)
        if "." not in q:
            why = "exact word match" if r else "not in dictionary"
        else:
            dots = q.count(".")
            why = (f"'.' branches into all children at {dots} level(s); "
                   f"{'a path reaches is_end' if r else 'no path completes'}")
        print(f'  search("{q}")  {str(r):<6}   {why}')
    print()
    print("--- detail: trace of search('.ad') ---")
    print("The '.' at depth 0 fans out into the three root children (b, d, m).")
    print("Each then walks 'a','d' exactly; b->a->d and d->a->d and m->a->d")
    print("all reach an is_end node, so the first success short-circuits.")
    print()
    for s in trace_wildcard(wd, ".ad")[:-1]:
        print(f"    depth {s['depth']}: via {s['via']!r}  "
              f"char={s['char']!r}  is_end={s['is_end']}")
    print(f'    => search(".ad") = {trace_wildcard(wd, ".ad")[-1]["result"]}')
    print()
    print("GOTCHA: even with wildcards you MUST check is_end at the end. A")
    print("pattern that walks a valid prefix but stops short of a word end")
    print('must return False (search("..") -> False: "ba","da","ma" are not words).')
    print()


# ============================================================================
# SECTION C - P212 WORD SEARCH II (trie + backtracking on a grid)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P212 Word Search II (trie + grid backtracking)")
    print("=" * 72)
    print()
    print("Build ONE trie from all words, then run a SINGLE DFS over the grid")
    print("following trie edges. Found words are collected; dead branches are")
    print("pruned so the same path is never re-explored (kills the TLE).")
    print()
    board = [
        ["o", "a", "a", "n"],
        ["e", "t", "a", "e"],
        ["i", "h", "k", "r"],
        ["i", "f", "l", "v"],
    ]
    words = ["oath", "pea", "eat", "rain"]
    print("board:")
    for row in board:
        print("    " + " ".join(row))
    print(f"words = {words}")
    print()

    # show the trie built from the words
    trie = Trie()
    for w in words:
        trie.insert(w)
    print("Trie built from words:")
    print()
    for line in render_tree(trie).splitlines():
        print("    " + line)
    print()

    # full solve (mutates a copy so the board stays printable)
    import copy
    trace: list[dict] = []
    found = find_words(copy.deepcopy(board), words, trace=trace)
    print(f"find_words(board, words) -> {sorted(found)}")
    print(f"  (expected ['eat', 'oath'])")
    print()

    # focused trace: how 'oath' was found, cell by cell
    print("--- focused trace: the grid path that spells 'oath' ---")
    path = find_path(board, "oath")
    if path:
        labels = ["o", "a", "t", "h"]
        for i, (r, c, lab) in enumerate(zip(range(len(path)), [p[0] for p in path],
                                           labels)):
            print(f"    step {i}: char '{lab}' at cell ({path[i][0]},{path[i][1]})")
        print(f"    => 'oath' collected, node.word nulled to block duplicates")
    print()
    print("Why the others fail:")
    print('  "pea"  - no cell holds "p", so the trie root has no "p" child;')
    print("           the DFS never starts.")
    print('  "rain" - no connected r->a->i->n path exists on this board.')
    print()

    # pruning stat
    before = count_nodes(board, words)
    print(f"trie nodes before search: {before} (incl root)")
    print("After find_words, every fully-found word is pruned from the trie:")
    print("  'oath' and 'eat' had their leaf chains popped, so re-scanning")
    print("  the board touches a much smaller tree. This is the optimization")
    print("  that turns the naive O(W * M*N * 4^L) into something tractable.")
    print()

    # a second, tiny board for clarity
    board2 = [["a", "b"], ["c", "d"]]
    words2 = ["abdc", "abcd", "acdb", "acbd"]
    print(f"smoke test: board={board2}, words={words2}")
    found2 = find_words(copy.deepcopy(board2), words2)
    print(f"  find_words -> {sorted(found2)}  (expected ['abdc','acdb'])")
    print()


# ============================================================================
# SECTION D - COMPLEXITY, GOTCHAS, PROBLEM TABLE
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - Complexity, killer gotchas, problem table")
    print("=" * 72)
    print()
    print("Complexity (L = word length, N = number of words, s = alphabet size)")
    print("----------------------------------------------------------------")
    print("  Operation                       Time             Space")
    print("  ------------------------------  ---------------  ---------")
    print("  insert / search / starts_with   O(L)             O(N*L) total")
    print("  wildcard search (k dots)        O(s^k * L) wc    O(L) stack")
    print("  all words with prefix P         O(L + results)   O(results)")
    print("  word search II (MxN grid)       O(M*N*4^L) wc    O(W*L) trie")
    print("  delete with pruning             O(L)             O(L) stack")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. is_end IS THE WHOLE POINT: search('app') must check node.is_end.")
    print("     If only 'apple' was inserted, search('app') is False but")
    print("     starts_with('app') is True. Forgetting this collapses the two.")
    print("  2. EMPTY STRING: search('') returns root.is_end; starts_with('')")
    print("     is always True (the root is reachable with zero steps).")
    print("  3. GRID DFS - RESTORE THE CELL: set board[r][c]='#' before")
    print("     recursing, restore board[r][c]=ch AFTER. Forgetting the restore")
    print("     silently breaks every subsequent search from a sibling cell.")
    print("  4. GRID DFS - PRUNE OR TLE: after collecting a word, null")
    print("     node.word AND pop childless nodes from their parent. Without")
    print("     this the same word is found repeatedly and dead branches are")
    print("     re-walked -> TLE on large boards.")
    print("  5. PASS THE PARENT NODE into the grid DFS (not the current node)")
    print("     so you have the reference needed to del parent.children[ch].")
    print("  6. WILDCARD '...' CAN BE EXPENSIVE: k dots means s^k branches.")
    print("     The trie prunes branches with no matching child, but an all-dot")
    print("     query over a dense trie still fans out widely.")
    print("  7. dict CHILDREN vs ARRAY[26]: dict handles any alphabet and is")
    print("     space-efficient for sparse trees; array[26] is ~3-5x faster per")
    print("     step but wastes memory. Use array[26] only for lowercase-only.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                         Diff   Key trick")
    print("  ------------------------------- ------ ----------------------------------------")
    print("  P208 Implement Trie             Medium insert/search/starts_with share _find; is_end separates search from starts_with")
    print("  P211 Add & Search Words         Medium '.' branches into all children via DFS(node, i); check is_end at the end")
    print("  P212 Word Search II             Hard   one trie + one grid DFS; store word at leaf; in-place '#' marking; prune childless branches")
    print("  P421 Max XOR of Two Numbers     Medium binary trie over bits; greedily pick the opposite bit at each level")
    print("  P648 Replace Words              Medium insert roots; find shortest prefix that is a word; replace on first hit")
    print("  P677 Map Sum Pairs              Medium store value at is_end; prefix sum via subtree DFS or a count field")
    print("  P745 Prefix & Suffix Search     Hard   insert 'suffix#word'; query with 'suffix#prefix'")
    print("  P1268 Search Suggestions        Medium sort words; for each prefix binary-search the top 3 lexicographic matches")
    print()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()

    # ---- assertions (all deterministic) ----
    # P208 fundamentals
    t = Trie()
    for w in ("app", "apple", "apply", "apt", "bat"):
        t.insert(w)
    assert t.node_count == 11                       # root + 10
    assert t.search("app") is True
    assert t.search("apple") is True
    assert t.search("apply") is True
    assert t.search("apt") is True
    assert t.search("bat") is True
    assert t.search("ap") is False                  # prefix, not a word
    assert t.search("ba") is False
    assert t.search("appl") is False                # prefix of apple
    assert t.search("xyz") is False
    assert t.starts_with("ap") is True
    assert t.starts_with("app") is True
    assert t.starts_with("b") is True
    assert t.starts_with("xyz") is False
    assert t.starts_with("") is True                # empty prefix always matches
    # prefix compression: 19 chars -> 10 nodes (+root)
    assert sum(len(w) for w in ("app", "apple", "apply", "apt", "bat")) == 19
    assert t.node_count - 1 == 10

    # P211 wildcard
    wd = WordDictionary()
    for w in ("bad", "dad", "mad"):
        wd.add_word(w)
    assert wd.search("pad") is False
    assert wd.search("bad") is True
    assert wd.search(".ad") is True
    assert wd.search("b..") is True
    assert wd.search("...") is True                 # bad, dad, mad
    assert wd.search("..") is False                 # no 2-letter words
    assert wd.search("b.d") is True
    assert wd.search("z..") is False                # no word starts with z
    assert wd.search("....") is False               # no 4-letter words

    # P212 word search II
    board = [
        ["o", "a", "a", "n"],
        ["e", "t", "a", "e"],
        ["i", "h", "k", "r"],
        ["i", "f", "l", "v"],
    ]
    words = ["oath", "pea", "eat", "rain"]
    import copy
    found = find_words(copy.deepcopy(board), words)
    assert sorted(found) == ["eat", "oath"], found
    # tiny smoke test
    board2 = [["a", "b"], ["c", "d"]]
    found2 = find_words(copy.deepcopy(board2), ["abdc", "abcd", "acdb", "acbd"])
    assert sorted(found2) == ["abdc", "acdb"], found2
    # no-match case
    assert find_words(copy.deepcopy(board2), ["xyz"]) == []
    # pruning reduces trie: words present get removed
    found3 = find_words(copy.deepcopy(board), ["oath", "pea", "eat", "rain"])
    assert sorted(found3) == ["eat", "oath"]

    # node counter: oath(4)+pea(3)+eat(3)+rain(4) = 14 nodes, no shared prefixes
    assert count_nodes(board, ["oath", "pea", "eat", "rain"]) == 15   # incl root

    print("=" * 72)
    print("[check] trie / wildcard / word-search ... OK")
    print("=" * 72)
