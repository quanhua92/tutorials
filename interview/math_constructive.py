"""
math.py - Reference implementation of the Math / Constructive pattern for:
  * Information-theory base counting       (P458 Poor Pigs)
  * Rejection sampling / geometry          (P478 Random Point in a Circle)
  * Constructive palindrome mirroring      (P479 Largest Palindrome Product)

This is the SINGLE SOURCE OF TRUTH for MATH.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 math.py > math_constructive_output.txt

Pure Python stdlib only. Deterministic (a fixed-seed LCG drives every
"random" value so the .html can reproduce it byte-for-byte).

============================================================================
THE INTUITION (read this first) - find the hidden formula
============================================================================
Math problems in coding interviews ask you to find a hidden formula instead
of simulating step by step. Do NOT write a `while` loop that increments a
counter a billion times - there is a closed-form shortcut. Three flavors
cover the canonical set:

  1. INFORMATION THEORY (P458 Poor Pigs). Each pig is one DIGIT in a base
     `tests+1` numeral. With `tests` testing rounds a pig can die in round
     0..tests-1 OR survive all rounds - that is `tests+1` distinct states.
     So `pigs` pigs distinguish `(tests+1)^pigs` buckets. Find the smallest
     integer `pigs` with `(tests+1)^pigs >= buckets`. The `+1` in the base
     is the whole trick: it encodes the implicit "survived" state.

  2. REJECTION SAMPLING / GEOMETRY (P478 Random Point in Circle). To sample
     uniformly inside a disk, sample uniformly in the bounding square
     `[-r, r]^2` and REJECT points whose squared distance from the center
     exceeds r^2. The acceptance probability is the area ratio
     (pi*r^2) / (2r)^2 = pi/4 ~ 0.7854, so ~21.5% of points are thrown away.
     NEVER sample a radius uniformly - area grows with r^2, so a uniform r
     crowds points toward the center.

  3. CONSTRUCTIVE MIRRORING (P479 Largest Palindrome Product). To find the
     largest palindrome that factors as a*b (both n-digit), do NOT scan all
     ~10^2n products. Instead GENERATE palindromes largest-first: take the
     upper half `left` (from 10^n-1 downward), MIRROR it into a 2n-digit
     palindrome, then ask "does some n-digit `right` divide it?" stopping
     once `right*right < palindrome`. The first factorable palindrome is the
     answer. n=1 is a special case (answer 9 = 3*3).

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  information       how many distinct outcomes a measurement can produce.
  theory            `T+1` states per pig per round; pigs in parallel multiply.
  base              the radix of a positional numeral. Base b with d digits
                   expresses 0 .. b^d - 1, i.e. b^d distinct values.
  rejection         sample from an easy distribution (the bounding square),
  sampling          then throw away samples that violate a constraint (outside
                   the disk). Unbiased because every interior point is equally
                   likely to be PROPOSED.
  acceptance rate   fraction of proposed samples kept = area(target)/area(box)
                   = (pi*r^2) / (2r)^2 = pi/4 ~ 0.7854 for a disk in its box.
  palindrome        reads the same forwards and backwards, e.g. 9009, 123321.
  mirror / reflect  build a palindrome by taking a prefix `left` and appending
                   its reverse: left=90 -> "90" + "09" = "9009".
  prefix / left     the upper half of the candidate palindrome (the digits you
                   choose; the lower half is forced by mirroring).
  modulo 1337       P479 returns the answer mod 1337 (a LeetCode quirk) because
                   the raw palindrome for n=8 has 16 digits.

============================================================================
THE SKELETON (all three variants share the "find the formula" mindset)
============================================================================
    # 1. P458: each pig = one digit in base (tests+1); smallest pigs >= buckets
    tests = minutesToTest // minutesToDie
    pigs = 0
    while (tests + 1) ** pigs < buckets:
        pigs += 1

    # 2. P478: propose a point in the bounding square, reject if outside disk
    while True:
        x, y = uniform(-1, 1), uniform(-1, 1)
        if x * x + y * y <= 1:
            break

    # 3. P479: mirror the upper half into a palindrome, test for an n-digit factor
    if n == 1: return 9
    upper = 10 ** n - 1
    for left in range(upper, lower - 1, -1):
        pal = mirror(left)
        right = upper
        while right * right >= pal:
            if pal % right == 0:
                return pal % 1337
            right -= 1
"""

from __future__ import annotations

# NOTE: this file is named math.py, which shadows the stdlib `math` module.
# Define PI locally instead of `import math` so the required filename works.
PI = 3.14159265358979323846264338327950288


# ============================================================================
# DETERMINISTIC PRNG - same LCG in math.py and math.html (gold-check match)
# ============================================================================
def lcg_stream(seed: int = 42):
    """Numerical-Recipes LCG: a=1664525, c=1013904223, m=2^32.

    Yields floats in [0, 1). Reproduced EXACTLY in the .html so the rejection
    trace and acceptance rate match byte-for-byte.
    """
    state = seed & 0xFFFFFFFF
    while True:
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        yield state / 4294967296.0


def uniform_minus1_1(rng):
    """Map a [0,1) draw to [-1,1) - the bounding square coordinate."""
    return next(rng) * 2.0 - 1.0


# ============================================================================
# TEMPLATE 1 - INFORMATION THEORY (P458 Poor Pigs)
# ============================================================================
def poor_pigs(buckets: int, minutes_to_die: int, minutes_to_test: int) -> int:
    """Minimum pigs to identify the one poisoned bucket.

    Each pig has `tests + 1` observable states (die in round 0..tests-1, or
    survive). `pigs` pigs in parallel encode `(tests+1)^pigs` distinct
    outcomes, so we need the smallest `pigs` with that capacity >= buckets.

    Time:  O(log(buckets) / log(tests+1))   -- tiny
    Space: O(1)
    """
    tests = minutes_to_test // minutes_to_die
    pigs = 0
    while (tests + 1) ** pigs < buckets:
        pigs += 1
    return pigs


def trace_poor_pigs(buckets: int, minutes_to_die: int, minutes_to_test: int):
    """Record the capacity `(tests+1)^pigs` at each increment until it covers
    `buckets`. One row per candidate pig count."""
    tests = minutes_to_test // minutes_to_die
    base = tests + 1
    rows = []
    pigs = 0
    while True:
        capacity = base ** pigs
        ok = capacity >= buckets
        rows.append({
            "pigs": pigs,
            "base": base,
            "capacity": capacity,
            "buckets": buckets,
            "ok": ok,
            "expr": f"{base}^{pigs} = {capacity}",
        })
        if ok:
            return rows
        pigs += 1


# ============================================================================
# TEMPLATE 2 - REJECTION SAMPLING (P478 Random Point in a Circle)
# ============================================================================
class RandomPointInCircle:
    """Uniform sampler for the disk of `radius` centered at (x_c, y_c).

    Proposes a point in the bounding square [-1, 1]^2 (scaled later) and
    rejects it if it falls outside the unit disk. Acceptance ~ pi/4 ~ 78.5%.
    """

    def __init__(self, radius: float, x_center: float, y_center: float,
                 seed: int = 42):
        self.radius = radius
        self.xc = x_center
        self.yc = y_center
        self._rng = lcg_stream(seed)

    def rand_point(self) -> tuple[float, float]:
        while True:
            x = uniform_minus1_1(self._rng)
            y = uniform_minus1_1(self._rng)
            if x * x + y * y <= 1.0:               # inside the unit disk
                return (self.xc + x * self.radius, self.yc + y * self.radius)


def trace_rejection(sampler: RandomPointInCircle, attempts: int):
    """Record the first `attempts` proposals: the raw square coords, the
    squared radius, and accept/reject."""
    rng = lcg_stream(42)                            # fresh stream for the trace
    rows = []
    for k in range(1, attempts + 1):
        x = uniform_minus1_1(rng)
        y = uniform_minus1_1(rng)
        d2 = x * x + y * y
        rows.append({
            "attempt": k,
            "x": x,
            "y": y,
            "d2": d2,
            "accept": d2 <= 1.0,
        })
    return rows


def acceptance_rate(seed: int, trials: int) -> tuple[int, int, float]:
    """Empirical acceptance rate over `trials` proposals."""
    rng = lcg_stream(seed)
    accepted = 0
    for _ in range(trials):
        x = uniform_minus1_1(rng)
        y = uniform_minus1_1(rng)
        if x * x + y * y <= 1.0:
            accepted += 1
    return accepted, trials, accepted / trials


# ============================================================================
# TEMPLATE 3 - CONSTRUCTIVE PALINDROME MIRRORING (P479 Largest Palindrome)
# ============================================================================
def mirror_to_palindrome(left: int) -> int:
    """Mirror the digits of `left` to build a palindrome, e.g. 90 -> 9009."""
    pal = left
    tmp = left
    while tmp > 0:
        pal = pal * 10 + tmp % 10
        tmp //= 10
    return pal


def is_palindrome(n: int) -> bool:
    s = str(n)
    return s == s[::-1]


def largest_palindrome(n: int) -> int:
    """Largest palindrome that is the product of two n-digit numbers, mod 1337.

    For n == 1 the answer is 9 (3*3) directly. Otherwise mirror the upper half
    `left` (from 10^n-1 downward) into a 2n-digit palindrome, then test whether
    some n-digit `right` divides it, stopping a given palindrome once
    `right*right < palindrome` (no factor can exist below sqrt(palindrome)).

    Time:  O(10^n) worst case over the left/right scan (n <= 8, so fine)
    Space: O(1)
    """
    if n == 1:
        return 9
    upper = 10 ** n - 1
    lower = 10 ** (n - 1)
    left = upper
    while left >= lower:
        pal = mirror_to_palindrome(left)
        right = upper
        while right * right >= pal:
            if pal % right == 0:
                return pal % 1337
            right -= 1
        left -= 1
    return 0


def trace_largest_palindrome(n: int):
    """Record the candidate palindromes scanned (largest-first) until the first
    factorable one is found. Each row: left, the mirrored palindrome, whether an
    n-digit divisor exists, and (if so) the factor pair."""
    if n == 1:
        return [{"left": 3, "palindrome": 9, "factorable": True,
                 "factor": "3 x 3", "note": "n=1 special case: 3*3=9"}]
    upper = 10 ** n - 1
    lower = 10 ** (n - 1)
    rows = []
    left = upper
    while left >= lower:
        pal = mirror_to_palindrome(left)
        right = upper
        factor_pair = None
        while right * right >= pal:
            if pal % right == 0:
                factor_pair = (right, pal // right)
                break
            right -= 1
        rows.append({
            "left": left,
            "palindrome": pal,
            "factorable": factor_pair is not None,
            "factor_pair": factor_pair,
        })
        if factor_pair is not None:
            return rows
        left -= 1
    return rows


# ============================================================================
# SECTION A - P458 POOR PIGS (worked example)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P458 Poor Pigs  (information theory, base tests+1)")
    print("=" * 72)
    print()
    print("Each pig is one DIGIT in base (tests+1). With `tests` testing")
    print("rounds, a pig either dies in round 0..tests-1 or survives all")
    print("rounds - that is tests+1 distinct observable states. So `pigs`")
    print("pigs in parallel distinguish (tests+1)^pigs buckets. Find the")
    print("smallest pigs with (tests+1)^pigs >= buckets.")
    print()
    print("The +1 in the base is the whole trick: it is the implicit")
    print("'survived every round' state.")
    print()

    cases = [
        (4, 15, 15, "LC example 1: 1 round"),
        (4, 15, 30, "LC example 2: 2 rounds"),
        (1000, 15, 60, "stress: 1000 buckets, 4 rounds"),
    ]
    for buckets, die, test, label in cases:
        tests = test // die
        base = tests + 1
        ans = poor_pigs(buckets, die, test)
        print(f"--- {label} ---")
        print(f"  buckets={buckets}, minutesToDie={die}, minutesToTest={test}")
        print(f"  tests = {test} // {die} = {tests}   -> base = tests+1 = {base}")
        print()
        rows = trace_poor_pigs(buckets, die, test)
        print("  pigs | (tests+1)^pigs | >= buckets? | decision")
        print("  -----+---------------+------------+-------------------------")
        for r in rows:
            decision = "RETURN " + str(r["pigs"]) if r["ok"] else "too small, +1 pig"
            mark = ">=" if r["ok"] else "< "
            print(f"   {r['pigs']}   | {r['base']}^{r['pigs']} = {r['capacity']:<10} | "
                  f"{mark} {r['buckets']:<3}        | {decision}")
        print()
        print(f"  => poor_pigs({buckets}, {die}, {test}) = {ans}")
        print()

    print("--- more canonical checks ---")
    print(f"  poor_pigs(1, 1, 1)   = {poor_pigs(1, 1, 1)}    (1 bucket needs 0 pigs)")
    print(f"  poor_pigs(125, 1, 4) = {poor_pigs(125, 1, 4)}    (5^3=125, base 5)")
    print(f"  poor_pigs(25, 1, 1)  = {poor_pigs(25, 1, 1)}    (2^4=16<25<=2^5=32)")
    print()


# ============================================================================
# SECTION B - P478 RANDOM POINT IN A CIRCLE (worked example)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P478 Random Point in a Circle  (rejection sampling)")
    print("=" * 72)
    print()
    print("Sample uniformly inside a disk. The trap: do NOT pick a radius")
    print("uniformly in [0, r] - area grows as r^2, so a uniform radius")
    print("crowds points near the center. Instead sample a point uniformly")
    print("in the bounding SQUARE [-1,1]^2 and REJECT it if it falls")
    print("outside the unit disk (x*x + y*y > 1). Every interior point is")
    print("equally likely to be proposed, so the survivors are uniform.")
    print()
    print("Acceptance probability = area(disk) / area(square)")
    print("                      = (pi*r^2) / (2r)^2 = pi/4 ~ 0.7854")
    print("So ~21.5% of proposals are thrown away - a fine price for")
    print("correctness.")
    print()

    sampler = RandomPointInCircle(1.0, 0.0, 0.0, seed=42)
    print("--- first 8 proposals inside the unit square (seed=42) ---")
    print("  attempt | x       | y       | x^2+y^2 | decision")
    print("  --------+---------+---------+---------+----------")
    rows = trace_rejection(sampler, 8)
    for r in rows:
        decision = "ACCEPT" if r["accept"] else "reject"
        print(f"    {r['attempt']:>2}   | {r['x']:+.4f} | {r['y']:+.4f} | "
              f"{r['d2']:.4f}  | {decision}")
    print()

    acc, trials, rate = acceptance_rate(42, 20000)
    print(f"--- empirical acceptance over {trials} proposals (seed=42) ---")
    print(f"  accepted = {acc} / {trials} = {rate:.4f}")
    print(f"  theory   = pi/4 = {PI / 4:.4f}")
    print(f"  relative error = {abs(rate - PI / 4) / (PI / 4) * 100:.2f}%")
    print()

    print("--- 3 accepted points for a disk of radius 2 centered at (1, 3) ---")
    s2 = RandomPointInCircle(2.0, 1.0, 3.0, seed=7)
    for i in range(3):
        px, py = s2.rand_point()
        print(f"  randPoint #{i + 1} -> ({px:+.4f}, {py:+.4f})   "
              f"(offset from center: ({px - 1:+.4f}, {py - 3:+.4f}), |offset|<=2)")
    print()

    print("--- why NOT to sample radius uniformly ---")
    print("  If r ~ Uniform(0,1) and theta ~ Uniform(0,2*pi): the point density")
    print("  at radius rho is proportional to rho * (1/rho) d rho... no - the")
    print("  Jacobian of (r, theta) is r, so density ~ 1/(2*pi) * 1 (constant")
    print("  in r on [0,1]) gives a 2D density ~ 1/(2*pi*r): BLOW UP at center.")
    print("  Fix if you must use polar: r = sqrt(uniform(0,1)), not uniform(0,1).")
    print()


# ============================================================================
# SECTION C - P479 LARGEST PALINDROME PRODUCT (worked example)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P479 Largest Palindrome Product  (constructive mirroring)")
    print("=" * 72)
    print()
    print("Find the largest palindrome equal to a*b with a, b both n-digit.")
    print("Do NOT scan all ~10^2n products. GENERATE palindromes largest-")
    print("first: pick the upper half `left` (from 10^n-1 downward), MIRROR")
    print("it into a 2n-digit palindrome, then ask 'does some n-digit right")
    print("divide it?', stopping once right*right < palindrome (no factor")
    print("can exist below sqrt). The first factorable palindrome wins.")
    print()
    print("n=1 is special: 9 = 3*3 (mirroring is meaningless for 1 digit).")
    print()

    n = 2
    print(f"--- n={n}: scan palindromes from left=99 downward ---")
    rows = trace_largest_palindrome(n)
    print("  left | palindrome | right scan      | factorable?")
    print("  -----+------------+-----------------+------------")
    for r in rows:
        if r["factorable"]:
            note = f"YES -> {r['factor_pair'][0]} x {r['factor_pair'][1]}"
        else:
            note = "no (right^2 < pal before any divisor)"
        mark = " *" if r["factorable"] else ""
        print(f"   {r['left']}  | {r['palindrome']:<10} | "
              f"right={10**n - 1}..| {note}{mark}")
    winner = rows[-1]
    pal = winner["palindrome"]
    a, b = winner["factor_pair"]
    print()
    print(f"  => largest palindrome = {pal} = {a} x {b}")
    print(f"     {pal} mod 1337 = {pal % 1337}   (LeetCode wants the result mod 1337)")
    print()

    print("--- full table n=1..8 ---")
    print("  n | largest palindrome = factors        | mod 1337")
    print("  --+-------------------------------------+---------")
    # We compute the raw palindrome (not mod) by re-deriving the factor.
    for nn in range(1, 9):
        mod_ans = largest_palindrome(nn)
        if nn == 1:
            print(f"  {nn} | 9 = 3 x 3                            | 9")
            continue
        rr = trace_largest_palindrome(nn)[-1]
        pp = rr["palindrome"]
        fa, fb = rr["factor_pair"]
        print(f"  {nn} | {pp} = {fa} x {fb}".ljust(60) + f"| {mod_ans}")
    print()

    print("--- canonical LeetCode check ---")
    print(f"  largest_palindrome(1) = {largest_palindrome(1)}    (expected 9)")
    print(f"  largest_palindrome(2) = {largest_palindrome(2)}   (expected 987)")
    print()

    print("--- correctness: every reported palindrome IS a palindrome ---")
    for nn in range(1, 9):
        if nn == 1:
            continue
        rr = trace_largest_palindrome(nn)[-1]
        assert is_palindrome(rr["palindrome"]), f"not a palindrome: n={nn}"
    print("  all palindromes for n=2..8 verified palindrome OK")
    print()


# ============================================================================
# SECTION D - COMPLEXITY, GOTCHAS, PROBLEM TABLE
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - Complexity, killer gotchas, problem table")
    print("=" * 72)
    print()
    print("Complexity")
    print("----------")
    print("  Problem                                Time              Space")
    print("  -------------------------------------- ----------------- ------")
    print("  P458 Poor Pigs (base counting)         O(log buckets)    O(1)")
    print("  P478 Random Point (rejection sample)   O(1) expected     O(1)")
    print("     each point ~ 4/pi ~ 1.27 proposals")
    print("  P479 Largest Palindrome (mirroring)    O(10^n) worst     O(1)")
    print("  Closed-form / formula math generally   O(1) or O(log n)  O(1)")
    print("  Digit construction (palindrome/perm)   O(n) or O(10^n)   O(1)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. THE +1 IN POOR PIGS. The base is (tests+1), NOT tests. The +1")
    print("     encodes 'survived every round' - a real, observable state.")
    print("     Forgetting it under-counts buckets by a factor of (tests+1)/tests.")
    print("  2. UNIFORM RADIUS CLUSTERS AT CENTER. Sampling r ~ U(0,R) gives a")
    print("     2D density ~ 1/(2*pi*r) that blows up at the origin. Either use")
    print("     rejection sampling on the bounding square, OR polar with")
    print("     r = R*sqrt(U(0,1)). NEVER r = R*U(0,1).")
    print("  3. n=1 SPECIAL CASE FOR PALINDROMES. Mirroring a 1-digit prefix is")
    print("     meaningless; the answer for P479 n=1 is 9 (=3*3) directly. A")
    print("     general mirror loop would skip or miscompute it.")
    print(" 4. STOP THE FACTOR SCAN AT sqrt. When checking 'does n-digit right")
    print("     divide palindrome?', stop once right*right < palindrome: no")
    print("     divisor smaller than sqrt can pair with one <= sqrt. This prunes")
    print("     the inner loop from O(10^n) toward O(sqrt(palindrome)).")
    print("  5. OVERFLOW / MOD. Python handles bignums, but P479 demands the")
    print("     answer mod 1337. Apply the mod ONLY at the return, never inside")
    print("     the factor test (you must test the real palindrome for divisibility).")
    print("  6. FORMULA EDGE CASES. Math formulas break at n=0, n=1, single")
    print("     digits, and exact powers of 10. Always test those boundaries.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                          Diff   Key trick")
    print("  -------------------------------- ------  -----------------------------------------")
    print("  P458 Poor Pigs                   Hard   (tests+1)^pigs >= buckets; loop until covers")
    print("  P478 Random Point in Circle      Medium reject square proposals outside the disk")
    print("  P479 Largest Palindrome Product  Hard   mirror upper half -> palindrome; factor scan")
    print("  P556 Next Greater Element III    Medium next-permutation on digits, watch 2^31-1")
    print("  P564 Find the Closest Palindrome Hard   5 candidates: prefix+-1 mirrored, 10^k-1, 10^k+1")
    print("  P507 Perfect Number              Easy   Euclid formula: 2^(p-1)*(2^p-1) for prime p")
    print("  P204 Count Primes                Easy   Sieve of Eratosthenes, O(n log log n)")


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()

    # ---- assertions (mirror LeetCode test cases) ----
    assert poor_pigs(4, 15, 15) == 2          # LC example 1
    assert poor_pigs(4, 15, 30) == 2          # LC example 2
    assert poor_pigs(1, 1, 1) == 0            # 1 bucket needs 0 pigs
    assert poor_pigs(1000, 15, 60) == 5       # 5^4=625 < 1000 <= 5^5=3125
    assert poor_pigs(125, 1, 4) == 3          # 5^3 = 125 exactly
    assert poor_pigs(25, 1, 1) == 5           # 2^4=16 < 25 <= 2^5=32

    # P478: every accepted point lies inside the disk
    s = RandomPointInCircle(3.0, 2.0, -1.0, seed=123)
    for _ in range(500):
        px, py = s.rand_point()
        assert (px - 2.0) ** 2 + (py + 1.0) ** 2 <= 3.0 ** 2 + 1e-9
    # acceptance rate is within 2% of pi/4 over 20000 trials
    _acc, _tot, _rate = acceptance_rate(42, 20000)
    assert abs(_rate - PI / 4) < 0.02

    # P479: canonical LeetCode answers (mod 1337)
    assert largest_palindrome(1) == 9
    assert largest_palindrome(2) == 987
    assert largest_palindrome(3) == 123       # 906609 -> 906609 % 1337 = 123
    assert largest_palindrome(8) == 475       # 9999000000009999 % 1337 = 475

    # mirror correctness
    assert mirror_to_palindrome(90) == 9009
    assert mirror_to_palindrome(99) == 9999
    assert mirror_to_palindrome(9) == 99
    assert is_palindrome(9009) and is_palindrome(123321) and not is_palindrome(1234)

    print("=" * 72)
    print("[check] poor_pigs / random_point / largest_palindrome ... OK")
    print("=" * 72)
