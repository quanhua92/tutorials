"""
bit_manipulation.py - Reference implementation of Bit Manipulation for:
  * XOR self-inverse cancellation  (P136 Single Number)
  * Brian Kernighan's bit counting (P191 Number of 1 Bits)
  * DP-on-bits counting             (P338 Counting Bits)

This is the SINGLE SOURCE OF TRUTH for BIT_MANIPULATION.md. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

    python3 bit_manipulation.py > bit_manipulation_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - a row of light switches
============================================================================
Computers store every integer as a row of 0s and 1s. Think of each bit as a
light switch: it is either ON (1) or OFF (0). Normal arithmetic (+, -, *, /)
operates on the whole number at once. Bit manipulation operates on the
INDIVIDUAL switches directly - flipping, masking, counting them.

Three switch tricks cover almost every interview question:

  1. XOR is a "cancel switch": flipping a switch twice returns it to where it
     started. So a ^ a = 0 (cancel) and a ^ 0 = a (no-op). XOR everything in
     a list and every value that appears an even number of times cancels to 0;
     only the odd-one-out survives. This finds the unique number in O(n)/O(1).

  2. n & (n-1) is the "turn off the rightmost ON switch" move. Subtracting 1
     borrows through the trailing zeros and flips the lowest 1 to 0. AND-ing
     that back keeps every other bit unchanged but kills exactly one 1-bit.
     Loop while n != 0: n &= n - 1; count += 1  -> counts the ON switches, and
     the loop runs EXACTLY once per set bit (not once per bit position).

  3. i >> 1 is "shift the whole switch row one step right" (drop the last
     switch). The number of ON switches in i equals the ON switches in i>>1
     PLUS the switch we dropped (i & 1). That recurrence
        ans[i] = ans[i >> 1] + (i & 1)
     fills the popcount for 0..n in O(n) using a subproblem already computed.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  bit              a single 0 or 1. Position 0 is the least-significant bit
                   (rightmost). Position k represents the value 2^k.
  popcount /       the number of 1-bits in an integer (its Hamming weight).
  Hamming weight   Examples: 0=0, 1=1, 2->10=1, 3->11=2, 7->111=3.
  set bit          a bit position that holds a 1. "Clearing a set bit" turns
                   it to 0.
  XOR (^)          bitwise exclusive-or. 1^1=0, 0^0=0, 1^0=1, 0^1=1.
                   Self-inverse: a^a=0. Identity: a^0=a. Commutative+assoc.
  AND (&)          1&1=1, everything else 0. Used as a "mask": keep only the
                   bits that are 1 in BOTH operands.
  n & (n-1)        clears the LOWEST set bit of n. The workhorse of popcount.
  n & (-n)         isolates the lowest set bit of n (two's complement: -n =
                   ~n + 1). Gives a mask with exactly that one bit set.
  shift (>>, <<)   move every bit left/right by k positions. i >> 1 = i // 2
                   for non-negative i. i << k = i * (2**k).
  LSB              least-significant bit, position 0. Equals (n & 1).
  power of two     a positive number with EXACTLY one set bit: 1,2,4,8,16,...
                   Test: n > 0 and (n & (n-1)) == 0.

============================================================================
THE SKELETON (all three variants share the bit primitives above)
============================================================================
    # 1. XOR fold: every pair cancels, the unique element survives
    res = 0
    for x in nums:
        res ^= x

    # 2. Brian Kernighan: clear the lowest set bit, loop once per 1-bit
    count = 0
    while n:
        n &= n - 1
        count += 1

    # 3. DP on bits: reuse the popcount of i >> 1, add the dropped LSB
    ans = [0] * (n + 1)
    for i in range(1, n + 1):
        ans[i] = ans[i >> 1] + (i & 1)
"""

from __future__ import annotations


# ============================================================================
# BINARY FORMATTING HELPERS
# ============================================================================
def fmt_bin(n: int, width: int | None = None) -> str:
    """Render n as a 0b-prefixed binary string, zero-padded to `width` bits.

    Negative numbers use two's-complement style display only for the helper;
    the actual algorithms operate on the integer value directly.
    """
    if n < 0:
        n &= 0xFFFFFFFF
    bits = bin(n)[2:] if n else "0"
    if width is not None:
        bits = bits.zfill(width)
    return "0b" + bits


def bit_width(n: int) -> int:
    """Number of bits needed to represent n (at least 1)."""
    return max(1, n.bit_length())


# ============================================================================
# TEMPLATE 1 - XOR SELF-INVERSE (P136 Single Number)
# ============================================================================
def single_number(nums: list[int]) -> int:
    """Return the element that appears exactly once (all others appear twice).

    XOR is commutative, associative, self-inverse (a^a=0), and identity
    (a^0=a). Folding every element cancels each pair to 0; the lone survivor
    is left in the accumulator.

    Time:  O(n)
    Space: O(1)
    """
    result = 0
    for num in nums:
        result ^= num
    return result


def trace_single_number(nums: list[int]) -> list[dict]:
    """Record the XOR accumulator after each element. Used by the worked
    example so the .md and .html can show bit-by-bit cancellation."""
    steps: list[dict] = [{"step": 0, "num": None, "acc": 0,
                          "note": "start: acc = 0"}]
    acc = 0
    for i, num in enumerate(nums):
        prev = acc
        acc ^= num
        steps.append({
            "step": i + 1,
            "num": num,
            "prev_acc": prev,
            "acc": acc,
            "note": f"acc ^= {num}",
        })
    return steps


# ============================================================================
# TEMPLATE 2 - BRIAN KERNIGHAN'S ALGORITHM (P191 Number of 1 Bits)
# ============================================================================
def hamming_weight(n: int) -> int:
    """Count the 1-bits in n using Brian Kernighan's algorithm.

    `n &= n - 1` clears the lowest set bit. The loop runs exactly once per
    set bit, so it is O(k) where k = popcount(n) - much faster than testing
    every one of the 32 bit positions.

    Time:  O(popcount(n))
    Space: O(1)
    """
    count = 0
    while n:
        n &= n - 1
        count += 1
    return count


def trace_kernighan(n: int) -> list[dict]:
    """Record each `n &= n-1` iteration: the value before, n-1, the AND
    result, and which bit position was cleared."""
    steps: list[dict] = [{"iter": 0, "n_before": n, "count": 0,
                          "note": f"start: n = {n}"}]
    count = 0
    it = 0
    cur = n
    while cur:
        it += 1
        low_mask = cur & (-cur)                 # isolate lowest set bit
        cleared_pos = low_mask.bit_length() - 1  # position of that bit
        nm1 = cur - 1
        result = cur & (cur - 1)
        steps.append({
            "iter": it,
            "n_before": cur,
            "n_minus_1": nm1,
            "result": result,
            "cleared": cleared_pos,
            "count": it,
        })
        cur = result
        count = it
    return steps


# ============================================================================
# TEMPLATE 3 - DP ON BITS (P338 Counting Bits)
# ============================================================================
def count_bits(n: int) -> list[int]:
    """Return ans of length n+1 where ans[i] = popcount(i) for 0..n.

    Recurrence: ans[i] = ans[i >> 1] + (i & 1).
    - i >> 1 drops the LSB; ans[i>>1] was already computed (smaller index).
    - (i & 1) is the dropped bit: 0 or 1.
    Adding them reconstructs the full popcount in O(1) per cell.

    Time:  O(n)
    Space: O(n)  (the output array)
    """
    ans: list[int] = [0] * (n + 1)
    for i in range(1, n + 1):
        ans[i] = ans[i >> 1] + (i & 1)
    return ans


def trace_count_bits(n: int) -> list[dict]:
    """Record each DP step: i, i>>1, ans[i>>1], (i&1), and ans[i]."""
    ans: list[int] = [0] * (n + 1)
    steps: list[dict] = [{"i": 0, "half": None, "lsb": None,
                          "ans_prev": None, "ans": 0,
                          "note": "base case: ans[0] = 0"}]
    for i in range(1, n + 1):
        half = i >> 1
        lsb = i & 1
        ans[i] = ans[half] + lsb
        steps.append({
            "i": i,
            "half": half,
            "lsb": lsb,
            "ans_prev": ans[half],
            "ans": ans[i],
        })
    return steps


# ============================================================================
# SECTION A - P136 SINGLE NUMBER (worked example)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P136 Single Number  (XOR self-inverse cancellation)")
    print("=" * 72)
    print()
    nums = [4, 1, 2, 1, 2]
    print(f"nums = {nums}   (every element appears twice except one)")
    print()
    print("XOR properties in play:")
    print("    a ^ a = 0   (a number XOR'd with itself is zero)")
    print("    a ^ 0 = a   (a number XOR'd with zero is itself)")
    print("    XOR is commutative and associative")
    print("    => pairs cancel, the lone survivor remains in the accumulator")
    print()
    print("Step-by-step fold (acc starts at 0):")
    print()
    steps = trace_single_number(nums)
    width = max(bit_width(abs(x)) for x in nums)
    print("  step | num | num (bin)    | acc after (bin)   | note")
    print("  -----+-----+--------------+-------------------+----------------")
    for s in steps:
        if s["step"] == 0:
            print(f"   {s['step']}   |  -  |     -        | {fmt_bin(0, width):17} | start: acc = 0")
        else:
            num = s["num"]
            print(f"   {s['step']}   |  {num}  | {fmt_bin(num, width):12} | "
                  f"{fmt_bin(s['acc'], width):17} | {s['note']}")
    print()
    print(f"  => pairs (1^1) and (2^2) cancel to 0; 4 ^ 0 ^ 0 = 4 survives.")
    print()
    result = single_number(nums)
    print(f"single_number({nums}) -> {result}   (expected 4)")
    print()
    print("--- edge cases ---")
    print(f"  [2, 2, 1]         -> {single_number([2, 2, 1])}    (expected 1)")
    print(f"  [1]               -> {single_number([1])}    (expected 1, lone element)")
    print(f"  [-1, -1, -2]      -> {single_number([-1, -1, -2])}   (expected -2, works on negatives)")
    print()


# ============================================================================
# SECTION B - P191 NUMBER OF 1 BITS (worked example)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P191 Number of 1 Bits  (Brian Kernighan's algorithm)")
    print("=" * 72)
    print()
    n = 11  # LeetCode example 1: 0b1011
    print(f"n = {n}   binary = {fmt_bin(n, 8)}   (8-bit view)")
    print()
    print("Why n & (n-1) clears the LOWEST set bit:")
    print("    Subtracting 1 borrows through the trailing zeros and flips")
    print("    the rightmost 1 to 0. AND-ing that back keeps every other bit")
    print("    but kills exactly one 1-bit.")
    print()
    print("Brian Kernighan loop - runs EXACTLY once per set bit:")
    print()
    steps = trace_kernighan(n)
    width = bit_width(n)
    print("  iter | n before (bin) | n - 1 (bin)   | n & (n-1) (bin) | cleared bit | count")
    print("  -----+----------------+---------------+-----------------+-------------+------")
    for s in steps:
        if s["iter"] == 0:
            print(f"   {s['iter']}   | {fmt_bin(s['n_before'], width):14} |       -       |        -        |      -      |   0")
        else:
            print(f"   {s['iter']}   | {fmt_bin(s['n_before'], width):14} | "
                  f"{fmt_bin(s['n_minus_1'], width):13} | "
                  f"{fmt_bin(s['result'], width):15} | "
                  f"pos {s['cleared']:>2}        |   {s['count']}")
    print()
    print(f"  => loop ran {steps[-1]['count']} times for a number with "
          f"{hamming_weight(n)} set bits.")
    print()
    print(f"hamming_weight({n}) -> {hamming_weight(n)}   (expected 3)")
    print()
    print("--- LeetCode canonical inputs ---")
    print(f"  n = 0b1011      = 11        -> {hamming_weight(11)}      (expected 3)")
    print(f"  n = 0b10000000  = 128       -> {hamming_weight(128)}      (expected 1, power of two)")
    print(f"  n = 0           = 0         -> {hamming_weight(0)}      (expected 0, loop never enters)")
    print(f"  n = 0b11111111  = 255       -> {hamming_weight(255)}     (expected 8, all bits set)")
    print()
    print("--- bigger number: n = 23 (0b10111, 4 set bits) ---")
    n2 = 23
    print(f"n = {n2}   binary = {fmt_bin(n2)}")
    steps2 = trace_kernighan(n2)
    width2 = bit_width(n2)
    print("  iter | n before | n - 1    | n&(n-1)  | cleared | count")
    print("  -----+----------+----------+----------+---------+------")
    for s in steps2[1:]:
        print(f"   {s['iter']}   | {fmt_bin(s['n_before'], width2):8} | "
              f"{fmt_bin(s['n_minus_1'], width2):8} | {fmt_bin(s['result'], width2):8} | "
              f"pos {s['cleared']:>2}   |   {s['count']}")
    print(f"  => hamming_weight(23) = {hamming_weight(23)} (4 iterations, not 5 bit-tests)")
    print()


# ============================================================================
# SECTION C - P338 COUNTING BITS (worked example)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P338 Counting Bits  (DP on bits, O(n))")
    print("=" * 72)
    print()
    n = 5  # LeetCode example 2
    print(f"n = {n}   want ans[i] = popcount(i) for every i in 0..{n}")
    print()
    print("The recurrence:  ans[i] = ans[i >> 1] + (i & 1)")
    print("    i >> 1    drops the LSB; ans[i>>1] is already known (smaller idx)")
    print("    (i & 1)   is the bit we just dropped: 0 if i is even, 1 if odd")
    print("    => popcount(i) = popcount(i//2) + (i is odd ? 1 : 0)")
    print()
    print("Filling the DP table step by step:")
    print()
    steps = trace_count_bits(n)
    width = bit_width(n)
    print("  i  | i (bin)    | i >> 1 | (i & 1) | ans[i>>1] | ans[i] = prev + lsb")
    print("  ----+------------+--------+---------+-----------+---------------------")
    for s in steps:
        if s["i"] == 0:
            print(f"   {s['i']}  | {fmt_bin(0, width):10} |   -    |    -    |     -     | 0  (base case)")
        else:
            print(f"   {s['i']}  | {fmt_bin(s['i'], width):10} |  {s['half']:>4}  |"
                  f"    {s['lsb']}    |    {s['ans_prev']:>2}     | "
                  f"{s['ans_prev']} + {s['lsb']} = {s['ans']}")
    print()
    result = count_bits(n)
    print(f"count_bits({n}) -> {result}   (expected [0,1,1,2,1,2])")
    print()
    print("--- LeetCode canonical inputs ---")
    print(f"  n = 0 -> {count_bits(0)}        (expected [0])")
    print(f"  n = 1 -> {count_bits(1)}     (expected [0,1])")
    print(f"  n = 2 -> {count_bits(2)}     (expected [0,1,1])")
    print(f"  n = 7 -> {count_bits(7)} (expected [0,1,1,2,1,2,2,3])")
    print()
    print("--- correctness vs bin().count('1') ---")
    print("  (proves the DP matches the hardware/string popcount)")
    all_match = all(count_bits(i)[i] == bin(i).count("1")
                    for i in range(0, 32) for _ in [None])
    brute = [bin(i).count("1") for i in range(0, 8)]
    dp = count_bits(7)
    print(f"  bin().count for 0..7 : {brute}")
    print(f"  count_bits(7)        : {dp}")
    print(f"  match across 0..31   : {all_match}")
    print()


# ============================================================================
# SECTION D - COMPLEXITY TABLE & GOTCHAS
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - Complexity, killer gotchas, problem table")
    print("=" * 72)
    print()
    print("Complexity")
    print("----------")
    print("  Operation                       Time            Space")
    print("  ------------------------------- --------------- --------")
    print("  Single Number, XOR fold (P136)  O(n)            O(1)")
    print("  Hamming weight, Kernighan (P191) O(popcount(n)) O(1)")
    print("  Counting Bits, DP on bits (P338) O(n)           O(n)")
    print("  Bit get/set/clear/toggle at i   O(1)            O(1)")
    print("  Subset enumeration, n bits      O(n * 2^n)      O(n * 2^n)")
    print()
    print("Core bit identities (memorize)")
    print("------------------------------")
    print("  a ^ a = 0           XOR self-inverse (pairs cancel)")
    print("  a ^ 0 = a           XOR identity")
    print("  n & (n - 1)         clears the LOWEST set bit of n")
    print("  n & (-n)            isolates the lowest set bit (two's complement)")
    print("  (n >> i) & 1        get bit at position i")
    print("  n | (1 << i)        set bit at position i")
    print("  n & ~(1 << i)       clear bit at position i")
    print("  n ^ (1 << i)        toggle bit at position i")
    print("  n > 0 and n&(n-1)==0   power-of-two test (the n>0 guard is critical)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. POWER-OF-TWO ZERO TRAP: 0 & (0-1) == 0, so the formula says 0")
    print("     is a power of 2. ALWAYS guard with n > 0:")
    print("         n > 0 and (n & (n - 1)) == 0")
    print("  2. n & (n-1) IS NOT n - 1. It clears the lowest set bit but keeps")
    print("     every other bit. For n = 0b1010 (10): n-1 = 0b1001, n&(n-1) =")
    print("     0b1000 (8). Subtracting 1 alone would give 9 - wrong for popcount.")
    print("  3. PYTHON's ~ IS NOT 'flip bits'. Because ints have infinite")
    print("     length, ~n = -(n+1). To flip the significant bits, build a mask")
    print("     and XOR: mask = (1 << n.bit_length()) - 1; return n ^ mask.")
    print("  4. XOR SWAP ALIASING: a ^= a sets a to 0. Never XOR-swap when the")
    print("     two indices might be the same (e.g. swap(arr[i], arr[i])).")
    print("  5. SHIFT >= WORD SIZE is undefined in C/C++. In Java, 1 << 32 wraps")
    print("     to 1 << 0. In Python it just works (bignum). Use 1L << n in C++.")
    print("  6. 'Every element appears k times except one': count bits at each")
    print("     position modulo k instead of a HashMap. O(32n) time, O(1) space.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                          Diff   Key trick")
    print("  -------------------------------- ------  -----------------------------------------")
    print("  P136 Single Number               Easy    res=0; for x: res^=x  - pairs cancel")
    print("  P191 Number of 1 Bits            Easy    Brian Kernighan: n &= n-1 loops popcount times")
    print("  P338 Counting Bits               Easy    DP: ans[i] = ans[i>>1] + (i&1)")
    print("  P268 Missing Number              Easy    res=n; for i,x: res ^= i ^ x  (or sum formula)")
    print("  P476 Number Complement           Easy    mask=(1<<bit_length)-1; return num ^ mask")
    print("  P461 Hamming Distance            Easy    XOR then popcount the result")
    print("  P190 Reverse Bits                Easy    res = (res<<1) | (n&1); n >>= 1, 32 times")
    print()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()

    # ---- assertions (mirror LeetCode test cases) ----
    assert single_number([2, 2, 1]) == 1
    assert single_number([4, 1, 2, 1, 2]) == 4
    assert single_number([1]) == 1
    assert single_number([-1, -1, -2]) == -2

    assert hamming_weight(0b00000000000000000000000000001011) == 3
    assert hamming_weight(0b00000000000000000000000010000000) == 1
    assert hamming_weight(0) == 0
    assert hamming_weight(0b11111111111111111111111111111111) == 32

    assert count_bits(2) == [0, 1, 1]
    assert count_bits(5) == [0, 1, 1, 2, 1, 2]
    assert count_bits(0) == [0]
    assert count_bits(1) == [0, 1]
    assert count_bits(7) == [0, 1, 1, 2, 1, 2, 2, 3]

    # ---- cross-check DP vs brute popcount for a wider range ----
    assert count_bits(1000) == [bin(i).count("1") for i in range(1001)]

    print("=" * 72)
    print("[check] single_number / hamming_weight / count_bits ... OK")
    print("=" * 72)
