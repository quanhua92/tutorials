"""Stack pattern — ground-truth implementations.

Three variants, three problems:

  1. Bracket matching (close->open map)  -> P020 Valid Parentheses
  2. Auxiliary stack for O(1) running min -> P155 Min Stack
  3. Nested state decode (count, prefix)  -> P394 Decode String

Every number printed below is produced by running this file; nothing is
hand-computed.  Capture with:

    python3 stack.py > stack_output.txt 2>/dev/null
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Variant 1 — Bracket matching (Valid Parentheses)
# ---------------------------------------------------------------------------

def is_valid_parentheses(s: str) -> bool:
    """P020: True iff the bracket string is properly nested and closed.

    Two failure modes: a closer hits an empty/mismatched stack; or the string
    ends with leftover openers.  Both are caught by guarding the stack top.
    """
    mapping = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for ch in s:
        if ch in mapping:                       # closing bracket
            if not stack or stack[-1] != mapping[ch]:
                return False                    # mismatched or dangling closer
            stack.pop()
        else:                                   # opening bracket
            stack.append(ch)
    return len(stack) == 0                      # leftover openers => invalid


def is_valid_parentheses_traced(s: str) -> bool:
    """Same logic, prints one row per character. Returns the verdict."""
    mapping = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    print(f"  input = {s!r}")
    print(f"  {'step':>4}  {'char':>4}  {'action':<26}  stack")
    print("  " + "-" * 64)
    step = 0
    for ch in s:
        step += 1
        if ch in mapping:
            opener = mapping[ch]
            if not stack or stack[-1] != opener:
                print(f"  {step:>4}  {ch:>4}  {'REJECT (top!=opener)':<26}"
                      f"  {stack}  -> False")
                return False
            stack.pop()
            action = f"pop {opener!r} (matches {ch!r})"
            print(f"  {step:>4}  {ch:>4}  {action:<26}  {stack}")
        else:
            stack.append(ch)
            print(f"  {step:>4}  {ch:>4}  {f'push {ch!r}':<26}  {stack}")
    ok = len(stack) == 0
    print(f"  end: stack empty? {len(stack) == 0}  -> {ok}")
    return ok


# ---------------------------------------------------------------------------
# Variant 2 — Auxiliary min-stack (Min Stack)
# ---------------------------------------------------------------------------

class MinStack:
    """P155: O(1) push/pop/top/getMin via a parallel min-stack.

    ``_min_stack`` always mirrors ``_stack`` length, and each entry is the
    running minimum up to that depth.  ``min(a, top)`` makes the new entry
    non-increasing, so the global minimum always sits at the top.
    """

    def __init__(self) -> None:
        self._stack: list[int] = []
        self._min_stack: list[int] = []

    def push(self, val: int) -> None:
        self._stack.append(val)
        running_min = val if not self._min_stack else min(val, self._min_stack[-1])
        self._min_stack.append(running_min)

    def pop(self) -> None:
        self._stack.pop()
        self._min_stack.pop()

    def top(self) -> int:
        return self._stack[-1]

    def get_min(self) -> int:
        return self._min_stack[-1]


def run_min_stack_traced(ops: list[tuple[str, int | None]]) -> list[int | None]:
    """Replay an op list against MinStack, printing the dual-stack evolution.

    Returns the list of return values (None for void ops).
    """
    print(f"  ops = {ops}")
    print(f"  {'step':>4}  {'op':<8}  {'val':>5}  "
          f"{'stack':<16}  {'min_stack':<16}  return")
    print("  " + "-" * 76)
    ms = MinStack()
    out: list[int | None] = []
    step = 0
    for op, val in ops:
        step += 1
        ret: int | None = None
        if op == "push":
            ms.push(val)                                  # type: ignore[arg-type]
        elif op == "pop":
            ms.pop()
        elif op == "top":
            ret = ms.top()
        elif op == "getMin":
            ret = ms.get_min()
        out.append(ret)
        print(f"  {step:>4}  {op:<8}  {str(val):>5}  "
              f"{str(ms._stack):<16}  {str(ms._min_stack):<16}  "
              f"{ret if ret is not None else '-'}")
    return out


# ---------------------------------------------------------------------------
# Variant 3 — Nested decode (Decode String)
# ---------------------------------------------------------------------------

def decode_string(s: str) -> str:
    """P394: Expand k[encoded_string] with arbitrary nesting.

    ``[`` pushes ``(curr_num, curr_str)`` as a saved frame and resets both
    accumulators.  ``]`` pops a frame and prepends its prefix to the repeated
    inner string.  Multi-digit counts are accumulated with ``num*10 + d``.
    """
    stack: list[tuple[int, str]] = []     # (repeat_count, saved_prefix)
    curr_num = 0
    curr_str = ""
    for ch in s:
        if ch.isdigit():
            curr_num = curr_num * 10 + int(ch)
        elif ch == "[":
            stack.append((curr_num, curr_str))
            curr_num = 0
            curr_str = ""
        elif ch == "]":
            repeat, prefix = stack.pop()
            curr_str = prefix + curr_str * repeat
        else:
            curr_str += ch
    return curr_str


def decode_string_traced(s: str) -> str:
    """Same logic, prints one row per character."""
    stack: list[tuple[int, str]] = []
    curr_num = 0
    curr_str = ""
    print(f"  input = {s!r}")
    print(f"  {'step':>4}  {'char':>4}  {'action':<32}  "
          f"{'num':>3}  {'curr_str':<12}  stack")
    print("  " + "-" * 84)
    step = 0
    for ch in s:
        step += 1
        if ch.isdigit():
            curr_num = curr_num * 10 + int(ch)
            action = f"digit -> num = {curr_num}"
        elif ch == "[":
            stack.append((curr_num, curr_str))
            action = f"push ({curr_num}, {curr_str!r}); reset"
            curr_num = 0
            curr_str = ""
        elif ch == "]":
            repeat, prefix = stack.pop()
            curr_str = prefix + curr_str * repeat
            action = f"pop ({repeat}, {prefix!r}); expand"
        else:
            curr_str += ch
            action = "letter -> append"
        print(f"  {step:>4}  {ch:>4}  {action:<32}  "
              f"{curr_num:>3}  {curr_str!r:<12}  {stack}")
    print(f"  >> decoded = {curr_str!r}")
    return curr_str


# ---------------------------------------------------------------------------
# Section drivers
# ---------------------------------------------------------------------------

def section_valid_parentheses() -> None:
    print("=" * 72)
    print("=== P020 Valid Parentheses — bracket matching")
    print("=" * 72)
    for s in ["()[]{}", "([{}])"]:
        res = is_valid_parentheses_traced(s)
        assert res is True, f"{s!r} should be valid"
        print(f"\n  >> is_valid_parentheses({s!r}) = {res}   [check] OK\n")

    s = "([)]"
    res = is_valid_parentheses_traced(s)
    assert res is False, f"{s!r} should be invalid"
    print(f"\n  >> is_valid_parentheses({s!r}) = {res}   [check] OK")

    # extra edge cases
    assert is_valid_parentheses("(") is False
    assert is_valid_parentheses(")") is False
    assert is_valid_parentheses("") is True
    print("  >> edge cases '(', ')', ''  [check] OK")


def section_min_stack() -> None:
    print()
    print("=" * 72)
    print("=== P155 Min Stack — auxiliary min-stack")
    print("=" * 72)
    ops = [
        ("push", -2), ("push", 0), ("push", -3),
        ("getMin", None), ("pop", None), ("top", None), ("getMin", None),
    ]
    out = run_min_stack_traced(ops)
    expected = [None, None, None, -3, None, 0, -2]
    assert out == expected, f"expected {expected}, got {out}"
    print(f"\n  >> returns = {out}   [check] OK")


def section_decode_string() -> None:
    print()
    print("=" * 72)
    print("=== P394 Decode String — nested decode")
    print("=" * 72)
    cases = [
        ("3[a2[c]]", "accaccacc"),
        ("3[a]2[bc]", "aaabcbc"),
        ("2[abc]3[cd]ef", "abcabccdcdcdef"),
    ]
    for s, want in cases:
        got = decode_string_traced(s)
        assert got == want, f"{s!r}: expected {want!r}, got {got!r}"
        print(f"  [check] decode_string({s!r}) == {want!r} OK\n")

    # multi-digit count edge case
    got = decode_string("12[a]")
    assert got == "a" * 12, got
    print(f"  >> decode_string('12[a]') = {got!r}   [check] OK")


if __name__ == "__main__":
    section_valid_parentheses()
    section_min_stack()
    section_decode_string()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
