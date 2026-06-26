"""
kmp_string.py - Reference implementation of the Knuth-Morris-Pratt (KMP) string
matching algorithm (Knuth, Morris, Pratt 1977).

This is the SINGLE SOURCE OF TRUTH for KMP_STRING.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 kmp_string.py > kmp_string_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

========================================================================
THE INTUITION (read this first) -- the never-re-read-what-you-already-know rule
========================================================================
Suppose you are searching for a PATTERN inside a long TEXT, left to right, and
you hit a MISMATCH after matching k characters. The naive matcher throws away
ALL of that matched work and shifts the pattern by just one position, re-doing
the k comparisons on the next attempt. On a nasty input (many A's) this is
O(n*m).

KMP's insight: those k matched characters are KNOWN. Somewhere inside the
matched PREFIX of the pattern there may be a shorter prefix that is ALSO a
suffix of what we just matched. If so, we can shift the pattern so that this
"border" lines up, and we do NOT have to re-check those border characters --
they are already guaranteed to match. The amount we are allowed to skip is read
off a precomputed table, the FAILURE FUNCTION (a.k.a. LPS: Longest Proper Prefix
which is also a Suffix).

  * failure[ j ] = length of the longest PROPER prefix of pattern[0..j] that is
                   also a suffix of pattern[0..j]. ("proper" = not the whole
                   string, so failure[0] = 0.)
  * On a mismatch at pattern position j, set j = failure[j-1] -- this is the
    longest shift that preserves all the matching we have already done.

THE REASON KMP EXISTS: it cuts string search from O(n*m) WORST case down to
O(n+m) -- O(m) to build the failure table, O(n) to scan the text. Crucially the
text pointer NEVER GOES BACKWARDS (streamable), which is why KMP is the backbone
of tools that search data too large to re-read (grep -F on pipes, DNA motif
scanners, intrusion-detection signatures).

========================================================================
PLAIN-ENGLISH GLOSSARY
========================================================================
  pattern       the short string P (length m) we are searching for.
  text          the long string T (length n) we search inside.
  match         a starting index i in T such that T[i..i+m-1] == P.
  naive match   the obvious O(n*m) algorithm: try P at every position, compare
                char-by-char, on mismatch shift by ONE and restart.
  failure func  failure[j] = length of the longest proper prefix of P[0..j]
  (LPS)         that is also a suffix of P[0..j]. Precomputed once in O(m).
  border        a string that is both a proper prefix and a suffix of P[0..j].
  shift         on a mismatch at index j, jump j back to failure[j-1] instead
                of back to 0; the text pointer i does NOT move back.

========================================================================
THE ALGORITHM IN TWO HALVES (all asserted in code below)
========================================================================
  HALF 1 - BUILD the failure function (the LPS table), in O(m):
      failure[0] = 0
      for j in 1..m-1:
          use failure[j-1] to extend or fall back, comparing P[j] with P[len].
  HALF 2 - SEARCH the text in O(n), never moving i backwards:
      for i in 0..n-1:
          while mismatch and j>0: j = failure[j-1]   # skip, do NOT re-check
          if P[j]==T[i]: j++
          if j==m: record match at i-m+1; j = failure[j-1]  # keep scanning

KEY FACTS (all asserted / gold-checked below):
    failure table for "ABABCABAB" = [0,0,1,2,0,1,2,3,4]   (CLRS example)
    naive worst-case comparisons on (A^15, "AAAAAAB") >> KMP comparisons
    KMP comparison count <= 2*n  (each index compared at most twice: ammortized)
    KMP finds EXACTLY the same matches as naive (gold check, incl. overlaps)

References:
    Knuth, Morris, Pratt (1977), "Fast Pattern Matching in Strings",
    SIAM J. Comput. 6(2):323-350. -- the original KMP paper.
    CLRS, Introduction to Algorithms, 3rd ed. -- ch.32 (String Matching), §32.4.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code KMP_STRING.md walks through)
# ============================================================================

def naive_search(text: str, pattern: str) -> tuple[list[int], int]:
    """The obvious O(n*m) matcher. Try the pattern at every starting position,
    compare char by char. On a mismatch, shift by ONE and restart from scratch.
    Returns (list of match start indices, total char comparisons made).

    Used as the GOLD reference (it is trivially correct) and as the worst-case
    baseline KMP improves on. The comparison counter is the whole point: it
    shows the redundant re-checking KMP eliminates.
    """
    n, m = len(text), len(pattern)
    matches: list[int] = []
    comps = 0
    if m == 0:
        return [i for i in range(n + 1)], 0
    for i in range(n - m + 1):
        j = 0
        while j < m:
            comps += 1
            if text[i + j] != pattern[j]:
                break
            j += 1
        if j == m:                              # full match
            matches.append(i)
    return matches, comps


def build_lps(pattern: str) -> tuple[list[int], int]:
    """Build the failure function (LPS table) for `pattern` in O(m).

    failure[j] = length of the longest PROPER prefix of pattern[0..j] that is
    also a suffix of pattern[0..j]. Returns (table, comparisons made during
    build). This is CLRS 32.4's COMPUTE-PREFIX-FUNCTION.
    """
    m = len(pattern)
    failure = [0] * m
    k = 0                                        # length of current longest border
    comps = 0
    for j in range(1, m):
        # fall back while we cannot extend the border
        while k > 0 and pattern[j] != pattern[k]:
            comps += 1
            k = failure[k - 1]
        comps += 1
        if pattern[j] == pattern[k]:
            k += 1
        failure[j] = k
    return failure, comps


def kmp_search(text: str, pattern: str) -> tuple[list[int], int, list[int]]:
    """KMP string matching in O(n+m). Returns (match start indices, text-scan
    comparisons, LPS table). The text pointer i NEVER moves backwards.

    On a mismatch at pattern index j, set j = failure[j-1] and retry WITHOUT
    advancing i -- this is the skip that makes KMP linear.
    """
    n, m = len(text), len(pattern)
    if m == 0:
        return [i for i in range(n + 1)], 0, [0] * m
    failure, _ = build_lps(pattern)
    matches: list[int] = []
    j = 0
    comps = 0
    for i in range(n):
        while j > 0 and text[i] != pattern[j]:
            comps += 1
            j = failure[j - 1]                   # SKIP: reuse the border, don't move i back
        comps += 1
        if text[i] == pattern[j]:
            j += 1
        if j == m:                               # full match found
            matches.append(i - m + 1)
            j = failure[j - 1]                   # continue scanning for overlaps
    return matches, comps, failure


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_lps_trace(pattern: str) -> None:
    """Step-by-step trace of the LPS build, showing the border reasoning."""
    m = len(pattern)
    failure, _ = build_lps(pattern)
    print(f"pattern = {pattern!r}  (length {m})\n")
    print("For each position j we ask: what is the longest proper prefix of")
    print("pattern[0..j] that is also a suffix of pattern[0..j]?\n")
    print("| j | char | P[0..j]      | longest border | failure[j] |")
    print("|---|------|--------------|----------------|------------|")
    for j in range(m):
        prefix = pattern[: j + 1]
        border = prefix[: failure[j]]
        print(f"| {j} | {pattern[j]}    | {prefix:<12} | {border:<14} | {failure[j]:<10} |")
    print(f"\nLPS table = {failure}")
    return failure


def bracket_text(text: str, matches: list[int], m: int) -> str:
    """ASCII visual: put [ ] around each match in the text (for short strings)."""
    marks = [0] * (len(text) + 1)
    for start in matches:
        marks[start] += 1
        marks[start + m] -= 1
    out = ""
    depth = 0
    for i, ch in enumerate(text):
        if marks[i] > 0:
            out += "[" * marks[i]
            depth += marks[i]
        out += ch
        if i + 1 < len(text) + 1:
            d = marks[i + 1]
            if d < 0:
                out += "]" * (-d)
                depth += d
    return out


# ----------------------------------------------------------------------------
# SECTION A: naive matching and its O(n*m) worst case
# ----------------------------------------------------------------------------

def section_naive() -> None:
    banner("SECTION A: naive matching  (the O(n*m) worst case KMP kills)")
    # worst case: text all A's, pattern A...AB. Naive re-checks the A run at
    # every shift.
    text = "A" * 15
    pattern = "A" * 6 + "B"                       # length 7
    n, m = len(text), len(pattern)
    print(f"text    = {text!r}   (n = {n})")
    print(f"pattern = {pattern!r}   (m = {m})\n")
    print("Naive tries the pattern at every position i. At each i it compares")
    print("A's that match, then fails on the final B, then shifts by ONE and")
    print("re-compares all those same A's. That redundant re-checking is O(n*m).\n")
    matches, comps = naive_search(text, pattern)
    worst = (n - m + 1) * m
    print(f"matches found : {matches}")
    print(f"comparisons   : {comps}")
    print(f"upper bound   : (n-m+1)*m = ({n}-{m}+1)*{m} = {worst}")
    print(f"[check] comps <= (n-m+1)*m? {comps <= worst}")
    print("\nEach of the 9 starting positions does up to 7 comparisons (the A's")
    print("match, then B fails) before shifting by one. KMP will turn these 9*7")
    print("comparisons into a single linear pass -- see Section C.")


# ----------------------------------------------------------------------------
# SECTION B: LPS computation for "ABABCABAB" (the CLRS example)
# ----------------------------------------------------------------------------

def section_lps() -> None:
    banner("SECTION B: LPS (failure function) for 'ABABCABAB'  (the CLRS example)")
    pattern = "ABABCABAB"
    failure = print_lps_trace(pattern)
    expected = [0, 0, 1, 2, 0, 1, 2, 3, 4]
    print(f"[check] LPS == [0,0,1,2,0,1,2,3,4] (CLRS)? {failure == expected}")
    print("\nReading the table: at j=8 (last B), failure[8]=4 means the 9-char")
    print("prefix 'ABABCABAB' has a 4-char border 'ABAB' (a proper prefix that is")
    print("also a suffix). On a mismatch after matching up to j=8, KMP jumps j to")
    print("failure[7]=3 -- it already KNOWS 'ABA' lines up, so it skips them.")


# ----------------------------------------------------------------------------
# SECTION C: KMP matching -- use LPS to skip comparisons
# ----------------------------------------------------------------------------

def section_kmp_search() -> None:
    banner("SECTION C: KMP matching  (use LPS to skip redundant comparisons)")
    text = "ABABDABACDABABCABAB"
    pattern = "ABABCABAB"
    n, m = len(text), len(pattern)
    print(f"text    = {text!r}   (n = {n})")
    print(f"pattern = {pattern!r}   (m = {m})\n")
    matches_kmp, comps_kmp, failure = kmp_search(text, pattern)
    matches_naive, comps_naive = naive_search(text, pattern)
    print(f"LPS table        : {failure}")
    print(f"KMP matches      : {matches_kmp}")
    print(f"KMP comparisons  : {comps_kmp}")
    print(f"naive comparisons: {comps_naive}")
    print(f"savings          : naive {comps_naive} -> KMP {comps_kmp} "
          f"({(1 - comps_kmp / comps_naive) * 100:.0f}% fewer)")
    print(f"[check] KMP comps <= 2*n = {2 * n}? {comps_kmp <= 2 * n}")
    print(f"[check] KMP matches == naive matches? {matches_kmp == matches_naive}")
    print(f"\nMatch positions visualised (pattern occurs at index "
          f"{matches_kmp[0] if matches_kmp else 'none'}):")
    print(f"  text   : {text}")
    if matches_kmp:
        s = matches_kmp[0]
        print(f"  pattern: {' ' * s}{pattern}")
    print("\nWHY KMP wins: when the matcher fails at a position, instead of")
    print("restarting from scratch it consults the LPS table to reuse the border")
    print("it already matched. The text pointer i never goes backwards, so the")
    print("whole scan is O(n).")


# ----------------------------------------------------------------------------
# SECTION D: naive O(n*m) vs KMP O(n+m) -- the comparison count head-to-head
# ----------------------------------------------------------------------------

def section_comparison() -> None:
    banner("SECTION D: naive O(n*m) vs KMP O(n+m)  (comparison-count head-to-head)")
    print("Run both matchers on inputs of growing size and count char comparisons.\n")
    print("| text        | pattern     |  n |  m | naive comps | KMP comps | "
          "ratio naive/KMP |")
    print("|-------------|-------------|----|----|-------------|-----------|"
          "------------------|")
    cases = [
        ("A" * 10, "A" * 4 + "B"),
        ("A" * 20, "A" * 6 + "B"),
        ("A" * 40, "A" * 8 + "B"),
        ("A" * 80, "A" * 10 + "B"),
        ("ABABDABACDABABCABAB", "ABABCABAB"),
        ("AAAAAABAAAAAABAAAAAAB", "AAAAAAB"),
    ]
    for text, pattern in cases:
        n, m = len(text), len(pattern)
        _, cn = naive_search(text, pattern)
        _, ck, _ = kmp_search(text, pattern)
        ratio = cn / ck if ck else float("inf")
        tt = text if len(text) <= 13 else text[:10] + "..."
        pt = pattern if len(pattern) <= 13 else pattern[:10] + "..."
        print(f"| {tt:<11} | {pt:<11} | {n:<2} | {m:<2} | "
              f"{cn:<11} | {ck:<9} | {ratio:<16.1f} |")
    print()
    print("Read it as: naive comparisons grow like n*m (quadratic in the A-runs);")
    print("KMP comparisons stay near 2*n (linear). On the 80-char all-A text with")
    print("an 11-char A...B pattern, naive does ~700 comparisons while KMP does")
    print("~160 -- a 4-5x saving that widens as the input grows.")
    print("\nBig-O summary:")
    print("  naive preprocessing: O(1)   search: O(n*m) worst case")
    print("  KMP   preprocessing: O(m)   search: O(n)   worst case  ->  O(n+m) total")


# ----------------------------------------------------------------------------
# SECTION E: applications -- grep, bioinformatics (DNA motif search)
# ----------------------------------------------------------------------------

def section_applications() -> None:
    banner("SECTION E: applications  (grep, bioinformatics / DNA motif search)")
    # 1. literal grep: count occurrences of a literal word in a sentence
    sentence = "the cat sat on the mat that the cat liked"
    word = "cat"
    cat_hits, _, _ = kmp_search(sentence, word)
    print("--- (1) grep-style literal search ---")
    print(f"text    = {sentence!r}")
    print(f"pattern = {word!r}")
    print(f"KMP finds {len(cat_hits)} occurrence(s) at index(es) {cat_hits}\n")

    # 2. DNA motif search: count overlapping occurrences of a motif in a genome
    genome = "GATATATGCATATACTT"                     # classic "finding a motif" input
    motif = "ATAT"
    dna_hits, _, _ = kmp_search(genome, motif)
    dna_naive, _ = naive_search(genome, motif)
    print("--- (2) bioinformatics: find a DNA motif (overlapping matches) ---")
    print(f"genome = {genome!r}")
    print(f"motif  = {motif!r}")
    print(f"KMP finds motif at index(es) {dna_hits}  ({len(dna_hits)} sites, incl. overlaps)")
    print(f"naive finds motif at index(es) {dna_naive}")
    print(f"[check] KMP == naive (incl. overlaps)? {dna_hits == dna_naive}")
    print("\nNote overlapping sites: 'ATAT' occurs at indices 1, 3, 9 (the 'ATAT'")
    print("starting at 1 overlaps the one at 3). KMP's failure-function fallback")
    print("is exactly what lets it catch overlaps without re-scanning.\n")
    print("Why KMP (not regex/naive) in these domains:")
    print("  - grep -F on a STREAM: text pointer never goes back, so KMP can")
    print("    search data too large to hold in memory (pipes, log tails).")
    print("  - DNA motif scanners search gigabase genomes for exact motifs; the")
    print("    O(n+m) guarantee (vs O(n*m)) is the difference between minutes and")
    print("    hours. Aho-Corasick generalizes KMP to many patterns at once.")
    print("  - intrusion detection (Snort signatures) precomputes LPS-style tables")
    print("    for thousands of literal attack signatures and streams packets.")


# ============================================================================
# 3. GOLD CHECK  (KMP finds the same matches as naive, on many inputs)
# ============================================================================

def gold_check() -> None:
    banner("GOLD CHECK: KMP finds ALL occurrences a naive search finds (incl. overlaps)")
    # a battery of (text, pattern) pairs chosen to stress edge cases:
    #  - worst-case A-runs, overlapping matches, no match, full match, single char
    battery = [
        ("ABABDABACDABABCABAB", "ABABCABAB"),       # CLRS pattern, one match
        ("AAAAAABAAAAAABAAAAAAB", "AAAAAAB"),        # overlapping-ish, multiple
        ("ABABABAB", "ABAB"),                        # overlapping matches 0,2,4
        ("GATATATGCATATACTT", "ATAT"),               # DNA motif, overlapping
        ("AAAAAAAAAA", "AAAA"),                      # dense overlaps
        ("XYZXYZXYZ", "XYZXYZ"),                     # periodic, overlaps
        ("HELLO WORLD", "XYZ"),                      # no match
        ("ABCDEFG", "ABCDEFG"),                      # full match at 0
        ("AAAA", "A"),                               # single-char pattern, 4 matches
        ("", "AB"),                                  # empty text
        ("AB", ""),                                  # empty pattern
    ]
    all_ok = True
    print(f"{'text':<22} {'pattern':<11} {'naive':<14} {'KMP':<14} {'match?'}")
    print("-" * 72)
    for text, pattern in battery:
        naive_hits, _ = naive_search(text, pattern)
        kmp_hits, _, _ = kmp_search(text, pattern)
        ok = naive_hits == kmp_hits
        all_ok = all_ok and ok
        tt = text if len(text) <= 20 else text[:17] + "..."
        pt = pattern if len(pattern) <= 11 else pattern[:8] + "..."
        print(f"{tt:<22} {pt:<11} {str(naive_hits):<14} {str(kmp_hits):<14} "
              f"{'OK' if ok else 'FAIL'}")
    print()
    # pin the LPS gold and one canonical match set for kmp_string.html
    lps, _ = build_lps("ABABCABAB")
    canon_text = "ABABDABACDABABCABAB"
    canon_pat = "ABABCABAB"
    canon_hits, canon_comps, _ = kmp_search(canon_text, canon_pat)
    print("GOLD (pinned for kmp_string.html):")
    print(f"  LPS('ABABCABAB')         = {lps}")
    print(f"  KMP('{canon_text}','{canon_pat}') = {canon_hits}, comps = {canon_comps}")
    print(f"[check] KMP == naive on all {len(battery)} cases? "
          f"{'OK' if all_ok else 'FAIL'}")
    assert all_ok, "KMP and naive disagree!"
    assert lps == [0, 0, 1, 2, 0, 1, 2, 3, 4]
    assert canon_hits == [10]


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("kmp_string.py - reference impl. All numbers below feed KMP_STRING.md.")
    print("KMP = skip redundant comparisons using a precomputed LPS table.")

    section_naive()
    section_lps()
    section_kmp_search()
    section_comparison()
    section_applications()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
