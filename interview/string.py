"""
string.py - Reference implementation of the string-manipulation pattern in its
three shapes: single-pass validation, normalize-and-reformat, and state-machine
parsing/counting.

This is the SINGLE SOURCE OF TRUTH for STRING.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 string.py > string_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - the proofreader with one finger
============================================================================
A string is just a LIST of characters. Almost every "easy" string problem on
LeetCode is solved by walking that list left to right with ONE finger (the
cursor), and at each character doing ONE of three things:

  * VALIDATION  : classify the char (upper/lower, letter/digit, space/not) and
                  check it against a rule. P520 Detect Capital.
  * REFORMATTING: normalize first (strip noise, fix case), then rebuild the
                  string in chunks. P482 License Key Formatting.
  * PARSING     : run a tiny state machine - usually a single boolean flag like
                  `in_segment` - and count transitions. P434 Number of Segments.

The reason the pattern exists: string problems look fiddly but are almost always
O(n) single-pass. The trap is reaching for regex / nested loops when a clean
NORMALIZE step (remove dashes, uppercase) followed by slicing makes the rest
trivial. Clean the data FIRST, then the rule is one line.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  cursor          the current character index i as you scan left -> right.
                  Every variant is "for i, ch in enumerate(s):".
  normalize       a preprocessing pass that strips noise so the main rule sees
                  only clean data. For P482: s.replace("-", "").upper().
  state flag      a boolean carried across iterations that remembers context.
                  P434 uses `in_segment` (am I currently inside a word?).
  group boundary  in reformatting, the indices where a new chunk begins. For
                  P482 the FIRST group is the short one: first_len = len % k.
  transition      the event that changes the answer. P434 counts
                  space -> non-space transitions; P520 compares whole-string
                  predicates (isupper / islower).

============================================================================
THE LOOP (all three variants share this skeleton)
============================================================================
    # VALIDATION
    def validate(s):
        return s.isupper() or s.islower() or s[1:].islower()

    # REFORMAT (normalize -> chunk from the front)
    def reformat(s, k):
        cleaned = s.replace("-", "").upper()
        first_len = len(cleaned) % k
        groups = [cleaned[:first_len]] if first_len else []
        for i in range(first_len, len(cleaned), k):
            groups.append(cleaned[i:i+k])
        return "-".join(groups)

    # PARSE / COUNT (one boolean flag)
    def count_segments(s):
        count, in_seg = 0, False
        for ch in s:
            if ch != " " and not in_seg:
                count += 1; in_seg = True
            elif ch == " ":
                in_seg = False
        return count

KEY FACTS (all verified + asserted in code):
    P482 ("5F3Z-2e-9-w", k=4)  ->  "5F3Z-2E9W"
    P482 ("2-5g-3-J",    k=2)  ->  "2-5G-3J"
    P520 "USA"   -> True ;  "FlaG" -> False ;  "Google" -> True
    P434 "Hello, my name is John" -> 5

References:
    LeetCode P482 / P520 / P434 (problem statements).
    tier1_foundation/string/README.md and DSA_CHEATSHEET.md string section.
"""


# ============================================================================
# 0. THE THREE TEMPLATE SKELETONS (memorize these)
# ============================================================================

def template_validation(word):
    """Variant 1: VALIDATION - does the string satisfy a fixed set of rules?

    The rule set for P520 (capital use is correct) is exactly three cases:
    all-uppercase, all-lowercase, or title-case (first upper, rest lower).
    Note `word[1:].islower()`: the empty slice returned for a single-char word
    is never reached because isupper()/islower() already returns True for it.
    """
    return word.isupper() or word.islower() or word[1:].islower()


def template_reformat(s, k):
    """Variant 2: REFORMAT - normalize, then rebuild in chunks from the FRONT.

    The gotcha that defines this problem: the FIRST group is the short one
    (len(cleaned) % k chars), NOT the last. Compute first_len, slice it off,
    then walk the rest in perfect k-steps.
    """
    cleaned = s.replace("-", "").upper()
    first_len = len(cleaned) % k
    groups = [cleaned[:first_len]] if first_len else []
    for i in range(first_len, len(cleaned), k):
        groups.append(cleaned[i:i + k])
    return "-".join(groups)


def template_parse_count(s):
    """Variant 3: PARSE/COUNT - a one-boolean state machine scanning left-right.

    Count space -> non-space transitions. Equivalent to len(s.split()) but
    shows the cursor/flag machinery that generalizes to harder parsers.
    """
    count, in_seg = 0, False
    for ch in s:
        if ch != " " and not in_seg:
            count += 1
            in_seg = True
        elif ch == " ":
            in_seg = False
    return count


# ============================================================================
# 1. THE THREE PROBLEMS (canonical LeetCode solutions)
# ============================================================================

def license_key_formatting(s, k):
    """P482 License Key Formatting (reformat from the right, first group short).

    Strip dashes, uppercase, then partition so every group after the first has
    exactly k chars. first_len = len(cleaned) % k makes the front group absorb
    the remainder.
    """
    cleaned = s.replace("-", "").upper()
    first_len = len(cleaned) % k
    groups = [cleaned[:first_len]] if first_len else []
    for i in range(first_len, len(cleaned), k):
        groups.append(cleaned[i:i + k])
    return "-".join(groups)


def detect_capital(word):
    """P520 Detect Capital (validation rules).

    Correct capital use = all-upper OR all-lower OR title-case. The [1:]
    slice elegantly handles single-character words too.
    """
    return word.isupper() or word.islower() or word[1:].islower()


def count_segments(s):
    """P434 Number of Segments in a String (parsing/counting).

    A segment is a contiguous run of non-space chars. Count the
    space -> non-space transitions with an `in_segment` flag.
    """
    count, in_seg = 0, False
    for ch in s:
        if ch != " " and not in_seg:
            count += 1
            in_seg = True
        elif ch == " ":
            in_seg = False
    return count


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

BANNER = "=" * 72


def banner(title):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_cursor(s, i):
    """Render s with the cursor [i] underlined by brackets around s[i]."""
    if not (0 <= i < len(s)):
        return s
    return s[:i] + "[" + s[i] + "]" + s[i + 1:]


# ============================================================================
# 3. THE WORKED EXAMPLES
# ============================================================================

def section_template():
    banner("SECTION A: the three template skeletons")
    print("Every string problem is one of three shapes. Memorize the skeleton")
    print("for each; the problems are just a different `rule` / `chunk size` /")
    print("`state flag`.\n")

    print("-- variant 1: VALIDATION (does the string match a rule set?) --")
    for w in ("USA", "leetcode", "Google", "FlaG"):
        print(f"  template_validation({w!r:10}) -> {template_validation(w)}")
    print("  trick: word.isupper() or word.islower() or word[1:].islower();")
    print("  the [1:] slice handles single-char words automatically.\n")

    print("-- variant 2: REFORMAT (normalize, then chunk from the front) --")
    for s, k in (("5F3Z-2e-9-w", 4), ("2-5g-3-J", 2)):
        print(f"  template_reformat({s!r}, {k}) -> {template_reformat(s, k)!r}")
    print("  trick: cleaned = s.replace('-','').upper(); first_len = len%k;")
    print("  the FIRST group is the short one - slice it off the FRONT.\n")

    print("-- variant 3: PARSE/COUNT (one boolean flag, count transitions) --")
    for s in ("Hello, my name is John", "Hello"):
        print(f"  template_parse_count({s!r}) -> {template_parse_count(s)}")
    print("  trick: count, in_seg = 0, False; bump count on space->non-space.")
    print("  Equivalent shortcut: len(s.split()).\n")

    # self-check on the templates themselves
    assert template_validation("USA") is True
    assert template_validation("FlaG") is False
    assert template_reformat("5F3Z-2e-9-w", 4) == "5F3Z-2E9W"
    assert template_reformat("2-5g-3-J", 2) == "2-5G-3J"
    assert template_parse_count("Hello, my name is John") == 5
    print("[check] template skeletons produce correct values:  OK")


def section_p482():
    banner("SECTION B: P482 License Key Formatting")
    s = "5F3Z-2e-9-w"
    k = 4
    print(f"Problem: reformat {s!r} so every group after the first has exactly")
    print(f"k={k} chars, dashes between groups, all uppercase.")
    print("Shape: REFORMAT. Two phases - normalize, then chunk from the front.\n")
    print("Phase 1 - NORMALIZE (cursor scans left -> right; drop '-', upper):\n")
    print(f"  {'i':>2}  {'ch':>3}  {'action':<10} {'cleaned (so far)':<18}")
    print("  " + "-" * 48)

    cleaned_chars = []
    for i, ch in enumerate(s):
        if ch == "-":
            action = "drop '-'"
        elif ch.islower():
            action = f"upper->{ch.upper()}"
            cleaned_chars.append(ch.upper())
        else:
            action = "keep"
            cleaned_chars.append(ch)
        print(f"  {i:>2}  {ch:>3}  {action:<10} {''.join(cleaned_chars)!r:<18}")
    cleaned = "".join(cleaned_chars)

    print(f"\nPhase 2 - CHUNK (first_len = len(cleaned) % k = {len(cleaned)} % {k}"
          f" = {len(cleaned) % k}):")
    first_len = len(cleaned) % k
    groups = [cleaned[:first_len]] if first_len else []
    print(f"  first group  = cleaned[:{first_len}] = {cleaned[:first_len]!r}")
    for i in range(first_len, len(cleaned), k):
        grp = cleaned[i:i + k]
        groups.append(grp)
        print(f"  next group   = cleaned[{i}:{i + k}] = {grp!r}")
    result = "-".join(groups)
    print(f"\n  '-'.join({groups}) = {result!r}")

    final = license_key_formatting(s, k)
    print(f"\n  -> license_key_formatting({s!r}, {k}) = {final!r}")
    print("Read it: normalize collapses the 5 dashes and lower-case 'e','w';")
    print("len(cleaned)=8 divides evenly into 4, so no short front group and")
    print("we get two equal halves '5F3Z' and '2E9W'.\n")

    # second canonical example
    s2, k2 = "2-5g-3-J", 2
    r2 = license_key_formatting(s2, k2)
    print(f"  second example: license_key_formatting({s2!r}, {k2}) = {r2!r}")
    print(f"  cleaned='25G3J' (len 5), first_len = 5%2 = 1 -> front group '2',")
    print(f"  then '5G', '3J' -> '2-5G-3J'. The SHORT group is at the FRONT.\n")

    assert final == "5F3Z-2E9W"
    assert r2 == "2-5G-3J"
    print("[check] P482 answers match LeetCode:  OK")


def section_p520():
    banner("SECTION C: P520 Detect Capital")
    print("Problem: return True if capital use in `word` is correct, i.e. one of")
    print("  (1) ALL uppercase   (2) ALL lowercase   (3) title case (first upper,")
    print("  rest lower).  Shape: VALIDATION.\n")
    print("Cursor classifies each char U(pper)/L(ower), then applies the rule:\n")
    print(f"  {'word':<10} {'char pattern':<16} {'all-up?':>7} "
          f"{'all-low?':>8} {'title?':>7} {'valid?':>7}")
    print("  " + "-" * 60)

    words = ["USA", "FlaG", "Google", "leetcode", "A"]
    for w in words:
        pattern = "".join("U" if c.isupper() else "L" for c in w)
        all_up = w.isupper()
        all_low = w.islower()
        title = bool(w) and w[0].isupper() and w[1:].islower()
        valid = detect_capital(w)
        print(f"  {w:<10} {pattern:<16} {str(all_up):>7} {str(all_low):>8} "
              f"{str(title):>7} {str(valid):>7}")

    print("\n  -> rule: word.isupper() or word.islower() or word[1:].islower()")
    print("Read it: 'FlaG' is U L L U - neither all-same nor title, so False.")
    print("'Google' is U L L L L L = title case -> True. Single char 'A' is")
    print("all-upper -> True (the [1:] slice is empty and never consulted).\n")

    assert detect_capital("USA") is True
    assert detect_capital("FlaG") is False
    assert detect_capital("Google") is True
    assert detect_capital("leetcode") is True
    assert detect_capital("A") is True
    print("[check] P520 answers match LeetCode:  OK")


def section_p434():
    banner("SECTION D: P434 Number of Segments in a String")
    s = "Hello, my name is John"
    print(f"Problem: count contiguous runs of non-space chars in {s!r}.")
    print("Shape: PARSE/COUNT - one boolean flag `in_segment`, count the")
    print("space -> non-space transitions.\n")
    print("Trace (cursor i; only transition rows shown - rows where `in_seg`")
    print("flips; interior chars of a segment produce no change):\n")
    print(f"  {'i':>2}  {'ch':>3}  {'in_seg(before)':>14} {'action':<26} "
          f"{'count':>5}")
    print("  " + "-" * 58)

    count, in_seg = 0, False
    for i, ch in enumerate(s):
        if ch != " " and not in_seg:
            action = "start of segment -> count += 1"
            count += 1
            in_seg = True
            print(f"  {i:>2}  {ch:>3}  {str(False):>14} {action:<26} {count:>5}")
        elif ch == " " and in_seg:
            action = "space -> end of segment"
            in_seg = False
            print(f"  {i:>2}  {' ':>3}  {str(True):>14} {action:<26} {count:>5}")
        # else: interior of segment or repeated space - no state change

    final = count_segments(s)
    print(f"\n  -> count_segments({s!r}) = {final}")
    print("Read it: count incremented at i=0 ('H'), 7 ('m'), 10 ('n'), 15 ('i'),")
    print("18 ('J') = five segments. Equivalent one-liner: len(s.split()).\n")

    # a couple of edge cases
    assert count_segments("Hello") == 1
    assert count_segments("") == 0
    assert count_segments("     ") == 0
    print("  edges: count_segments('Hello')=1, ('')=0, ('     ')=0")
    assert final == 5
    print("[check] P434 answers match LeetCode:  OK")


def section_gold():
    banner("SECTION E: GOLD values (pinned for string.html)")
    # The .html recomputes these on the SAME inputs in JS and checks them.
    k1 = license_key_formatting("5F3Z-2e-9-w", 4)
    k2 = license_key_formatting("2-5g-3-J", 2)
    k3 = license_key_formatting("r", 1)
    c1 = detect_capital("USA")
    c2 = detect_capital("FlaG")
    c3 = detect_capital("Google")
    c4 = detect_capital("leetcode")
    c5 = detect_capital("A")
    s1 = count_segments("Hello, my name is John")
    s2 = count_segments("Hello")
    s3 = count_segments("")
    print(f'license_key_formatting("5F3Z-2e-9-w", 4) = {k1!r}')
    print('GOLD P482 #1: "5F3Z-2E9W"')
    print(f'license_key_formatting("2-5g-3-J", 2)    = {k2!r}')
    print('GOLD P482 #2: "2-5G-3J"')
    print(f'license_key_formatting("r", 1)           = {k3!r}')
    print('GOLD P482 #3: "R"')
    print(f'detect_capital("USA")     = {c1}')
    print(f'detect_capital("FlaG")    = {c2}')
    print(f'detect_capital("Google")  = {c3}')
    print(f'detect_capital("leetcode")= {c4}')
    print(f'detect_capital("A")       = {c5}')
    print('GOLD P520: True, False, True, True, True')
    print(f'count_segments("Hello, my name is John") = {s1}')
    print(f'count_segments("Hello")                 = {s2}')
    print(f'count_segments("")                      = {s3}')
    print('GOLD P434: 5, 1, 0')
    # self-consistency asserts - these ARE the gold values
    assert k1 == "5F3Z-2E9W"
    assert k2 == "2-5G-3J"
    assert k3 == "R"
    assert (c1, c2, c3, c4, c5) == (True, False, True, True, True)
    assert (s1, s2, s3) == (5, 1, 0)
    print("\n[check] all GOLD values reproduce from the implementations:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("string.py - reference impl. All numbers below feed STRING.md.")
    section_template()
    section_p482()
    section_p520()
    section_p434()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
