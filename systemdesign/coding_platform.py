#!/usr/bin/env python3
"""
coding_platform.py - Coding Platform (LeetCode) system design simulation (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds CODING_PLATFORM.md
and is recomputed identically in coding_platform.html (gold-checked).

Core model: an ONLINE JUDGE = SUBMISSION QUEUE + SANDBOXED EXECUTION + TEST RUNNER.
  - Submission queue: Kafka partitioned by language, priority lanes
    (contest < practice), pulled by a specialized worker pool.
  - Sandbox: gVisor (user-space kernel, ~10ms) or Firecracker (KVM microVM,
    ~125ms; pre-warmed ~10ms) with cgroup limits (memory.max, cpu.max,
    pids.max) + wall-clock watchdog + network namespace.
  - Test runner: compile -> run per test case -> compare output -> verdict,
    with precedence CE > TLE > MLE > RE > WA > AC; stop on first failure.
  - Compilation cache: source-hash keyed artifact store; skip recompile on hit.
  - Leaderboard: ICPC-style ranking (solved DESC, penalty ASC) via a Redis-style
    sorted set with score = solved * 1e9 - penalty (two keys in one float).

Sections:
  1. Submission queue (language-partitioned priority lanes + worker pull order)
  2. Sandbox execution (gVisor vs Firecracker startup + cgroup limits -> verdicts)
  3. Test case runner (compile -> run -> compare; verdict precedence)
  4. Compilation cache (source-hash hit/miss; time saved)
  5. Leaderboard (contest ranking, 5-min penalty, tie-break via sorted set)
  6. Scale estimation (submissions/day, QPS, storage, sandbox fleet)
  7. GOLD values pinned for coding_platform.html
"""

import bisect
import hashlib
import heapq

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

LINE = "=" * 74


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1000.0:
            return "%.2f %s" % (n, unit)
        n /= 1000.0
    return "%.2f EB" % n


def fmt_int(n):
    return "{:,}".format(n)


# ---------------------------------------------------------------------------
# verdicts + precedence
# ---------------------------------------------------------------------------

CE = "COMPILE_ERROR"
WA = "WRONG_ANSWER"
TLE = "TIME_LIMIT_EXCEEDED"
MLE = "MEMORY_LIMIT_EXCEEDED"
RE = "RUNTIME_ERROR"
AC = "ACCEPTED"

# Precedence: CE stops everything before execution; among execution faults
# TLE outranks MLE outranks RE outranks WA. First non-AC verdict wins.
VERDICT_PRECEDENCE = [CE, TLE, MLE, RE, WA, AC]
VERDICT_SHORT = {CE: "CE", TLE: "TLE", MLE: "MLE", RE: "RE", WA: "WA", AC: "AC"}


# ---------------------------------------------------------------------------
# SortedSet - Redis ZSET analogue (skip list + hash table role)
# ---------------------------------------------------------------------------

class SortedSet:
    """Dual structure: dict member->score + sorted [(score, member)] ascending.
    ZREVRANGE reverses it (highest score = rank 0). Matches Redis ZSET
    semantics including the lexicographic tie-break on equal scores."""

    def __init__(self):
        self._scores = {}
        self._sorted = []

    def __len__(self):
        return len(self._scores)

    def zadd(self, member, score):
        if member in self._scores:
            old = self._scores[member]
            if score == old:
                return False
            idx = bisect.bisect_left(self._sorted, (old, member))
            self._sorted.pop(idx)
        self._scores[member] = score
        bisect.insort(self._sorted, (score, member))
        return True

    def score(self, member):
        return self._scores.get(member)

    def _asc_rank(self, member):
        s = self._scores[member]
        return bisect.bisect_left(self._sorted, (s, member))

    def zrevrank(self, member):
        if member not in self._scores:
            return None
        return len(self._sorted) - 1 - self._asc_rank(member)

    def zrevrange(self, start, stop):
        """Ranks start..stop inclusive (0 = top, descending)."""
        n = len(self._sorted)
        if start < 0:
            start += n
        if stop < 0:
            stop += n
        if start < 0:
            start = 0
        if stop >= n:
            stop = n - 1
        if n == 0 or start > stop:
            return []
        asc_lo = n - 1 - stop
        asc_hi = n - 1 - start
        chunk = list(reversed(self._sorted[asc_lo:asc_hi + 1]))
        return [(m, s) for (s, m) in chunk]


# ---------------------------------------------------------------------------
# Sandbox cgroup limits (mandatory even inside gVisor / Firecracker)
# ---------------------------------------------------------------------------

MEM_MAX_KB = 256 * 1024        # memory.max  -> 256 MB; breach triggers OOM kill -> MLE
CPU_MAX_MS = 2000              # cpu.max     -> 2 s CPU per test; breach -> TLE
PIDS_MAX = 1                   # pids.max    -> fork-bomb prevention
WALL_WATCHDOG_MS = CPU_MAX_MS + 2000  # external wall-clock; catches sleep-evasion -> TLE

SANDBOX_RUNTIMES = [
    # (name, startup_ms, cpu_overhead_pct, isolation_note)
    ("gVisor",                   10,  20.0, "user-space kernel (Sentry), ~200 syscalls intercepted"),
    ("Firecracker",              125, 1.5, "KVM microVM, separate kernel per execution"),
    ("Firecracker (pre-warmed)", 10,  1.5, "pool of ready VMs amortizes the 125ms cold start"),
]


# ---------------------------------------------------------------------------
# SECTION 1 - Submission queue: language-partitioned priority lanes
# ---------------------------------------------------------------------------

PRACTICE_PRIO = 1
CONTEST_PRIO = 0


class JudgeQueue:
    """One Kafka partition: a min-heap keyed by (priority, sequence).
    Contest submissions (priority 0) always dequeue before practice (priority 1),
    FIFO within each lane."""

    def __init__(self):
        self._heap = []
        self._seq = 0

    def submit(self, sub_id, lane):
        prio = CONTEST_PRIO if lane == "contest" else PRACTICE_PRIO
        heapq.heappush(self._heap, (prio, self._seq, sub_id))
        self._seq += 1

    def pull_all(self):
        out = []
        while self._heap:
            _, _, sid = heapq.heappop(self._heap)
            out.append(sid)
        return out


def section_queue():
    banner("SECTION 1: Submission queue (language-partitioned, priority lanes)")
    print("Kafka topic judge-queue is PARTITIONED BY LANGUAGE so workers only load")
    print("the relevant runtime image. Each partition has two consumer groups:")
    print("  judge-contest-{lang}  (priority 0, pre-scaled before contests)")
    print("  judge-normal-{lang}   (priority 1, HPA on consumer lag)")
    print("Source code lives in S3 (~100KB max); the Kafka message carries only")
    print("metadata (~1KB): submission_id, problem_id, lang, s3_key, lane.")
    print()

    submissions = [
        ("S1", "python", "practice"),
        ("S2", "cpp",    "practice"),
        ("S3", "python", "contest"),
        ("S4", "java",   "practice"),
        ("S5", "cpp",    "contest"),
        ("S6", "python", "contest"),
    ]
    print("Submit sequence (6 submissions, mixed languages + lanes):")
    for sid, lang, lane in submissions:
        print("  %-3s  %-7s  %-8s" % (sid, lang, lane))
    print()

    partitions = {}
    for sid, lang, lane in submissions:
        partitions.setdefault(lang, JudgeQueue()).submit(sid, lane)

    print("Per-partition pull order (contest first, then practice, FIFO within):")
    all_orders = {}
    for lang in ("python", "cpp", "java"):
        q = partitions.get(lang)
        order = q.pull_all() if q else []
        all_orders[lang] = ",".join(order)
        print("  %-7s -> %s" % (lang, ", ".join(order) if order else "(empty)"))
    print()
    print("Contest S3/S6 jump the practice S1 in the python partition even though")
    print("S1 was submitted first. Workers are specialized: a python worker never")
    print("loads the cpp toolchain.")
    print()

    ok = (all_orders["python"] == "S3,S6,S1" and
          all_orders["cpp"] == "S5,S2" and
          all_orders["java"] == "S4")
    print("[check] contest-lane priority + language partitioning correct? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Sandbox: gVisor vs Firecracker + cgroup resource limits
# ---------------------------------------------------------------------------

def section_sandbox():
    banner("SECTION 2: Sandbox execution (gVisor vs Firecracker + cgroup limits)")
    print("Docker alone shares the host kernel; kernel exploits escape containers.")
    print("Defense in depth: sandbox runtime + cgroup limits + seccomp-BPF +")
    print("network namespace (no routes -> ENETUNREACH) + isolated worker nodes.")
    print()

    print("Sandbox runtime comparison:")
    print("  %-26s %10s %12s  %s" % ("runtime", "startup", "cpu overhead", "isolation"))
    for name, startup, overhead, note in SANDBOX_RUNTIMES:
        print("  %-26s %7dms %11.1f%%  %s" % (name, startup, overhead, note))
    print()
    print("Decision: gVisor for practice (fast startup matters); pre-warmed")
    print("Firecracker for contests (strongest isolation + amortized 10ms startup).")
    print()

    print("cgroup resource limits (mandatory even with a sandbox runtime):")
    print("  memory.max        = %d KB (%d MB)   breach -> OOM kill -> MLE" %
          (MEM_MAX_KB, MEM_MAX_KB // 1024))
    print("  cpu.max           = %d ms (%.1f s)     breach -> TLE" %
          (CPU_MAX_MS, CPU_MAX_MS / 1000.0))
    print("  pids.max          = %d                fork bomb -> killed -> RE" % PIDS_MAX)
    print("  wall-clock watch  = %d ms           external; catches sleep-evasion -> TLE" %
          WALL_WATCHDOG_MS)
    print("  network namespace = no egress       any socket -> ENETUNREACH")
    print()

    # verdict decision tree for a single test case
    print("Per-test-case verdict decision (first match wins):")
    cases = [
        ("compile fails",            CE),
        ("cpu_ms > %d" % CPU_MAX_MS, TLE),
        ("mem_kb > %d" % MEM_MAX_KB, MLE),
        ("fork bomb / crash",        RE),
        ("output mismatch",          WA),
        ("all checks pass",          AC),
    ]
    for desc, v in cases:
        print("  %-28s -> %-18s (%s)" % (desc, v, VERDICT_SHORT[v]))
    print()

    ok = (SANDBOX_RUNTIMES[0][1] == 10 and
          SANDBOX_RUNTIMES[1][1] == 125 and
          SANDBOX_RUNTIMES[2][1] == 10 and
          MEM_MAX_KB == 256 * 1024 and
          CPU_MAX_MS == 2000 and
          WALL_WATCHDOG_MS == 4000)
    print("[check] startup/limit constants match design spec? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Test case runner: compile -> run -> compare -> verdict
# ---------------------------------------------------------------------------

class Fault(Exception):
    """A sandbox-detected execution fault (crash, segfault, fork bomb)."""
    def __init__(self, verdict):
        self.verdict = verdict


class Program:
    """A deterministic submission model. 'source' is hashed for the compile cache;
    'behavior' drives the simulated resource profile + output so every verdict
    type is reproducible without actually executing untrusted code."""

    def __init__(self, name, source, behavior, lang="cpp"):
        self.name = name
        self.source = source
        self.behavior = behavior
        self.lang = lang
        self.compile_ok = behavior != "syntax_error"

    def run_one(self, test_input):
        """Run one test case inside the sandbox.
        Returns (output, cpu_ms, mem_kb) or raises Fault(RE)."""
        parts = test_input.split()
        a, b = int(parts[0]), int(parts[1])
        s = str(a + b)
        if self.behavior == "correct":
            return (s, 50, 50_000)
        if self.behavior == "off_by_one":
            return (s.replace(s, str(a + b + 1)), 50, 50_000)
        if self.behavior == "slow":
            return (s, 3_000, 50_000)      # 3000ms CPU > 2000ms limit -> TLE
        if self.behavior == "hungry":
            return (s, 50, 300_000)        # 300MB > 256MB -> MLE
        if self.behavior == "crash":
            raise Fault(RE)                 # null deref / segfault -> RE
        return (s, 50, 50_000)


# Problem: "Two Sum" - read "a b", print a+b
TWO_SUM = [
    ("2 7",     "9"),
    ("0 0",     "0"),
    ("-1 1",    "0"),
    ("100 200", "300"),
    ("123 456", "579"),
]

DEMO_PROGRAMS = [
    Program("correct",     "print(a+b)",            "correct"),
    Program("off_by_one",  "print(a+b+1)",          "off_by_one"),
    Program("slow",        "while True: pass",      "slow"),
    Program("hungry",      "x=[0]*10**8",           "hungry"),
    Program("crash",       "print(1/0)",            "crash"),
    Program("broken",      "prin a+b",              "syntax_error"),
]


def judge_program(prog, tests):
    """Full judge pipeline: compile -> run each test under cgroup limits -> verdict.
    Stops on the first non-AC test case (real judges don't waste sandbox slots)."""
    if not prog.compile_ok:
        return {"verdict": CE, "compiled": False, "per_test": [],
            "total_ms": 0, "peak_kb": 0, "tests_run": 0}
    per_test = []
    worst = AC
    worst_pri = len(VERDICT_PRECEDENCE)
    total_ms = 0
    peak_kb = 0
    for i, (inp, expected) in enumerate(tests):
        cpu, mem = 0, 0
        try:
            out, cpu, mem = prog.run_one(inp)
            if cpu > CPU_MAX_MS:
                v = TLE
            elif mem > MEM_MAX_KB:
                v = MLE
            elif out.strip() != expected.strip():
                v = WA
            else:
                v = AC
        except Fault as f:
            v = f.verdict
        per_test.append((i + 1, v, cpu, mem))
        total_ms += cpu
        peak_kb = max(peak_kb, mem)
        pri = VERDICT_PRECEDENCE.index(v)
        if pri < worst_pri:
            worst_pri = pri
            worst = v
        if v != AC:
            break
    return {"verdict": worst, "compiled": True, "per_test": per_test,
            "total_ms": total_ms, "peak_kb": peak_kb, "tests_run": len(per_test)}


def section_runner():
    banner("SECTION 3: Test case runner (compile -> run -> compare -> verdict)")
    print("Problem 'Two Sum': read 'a b', print a+b. %d test cases (hidden)." %
          len(TWO_SUM))
    print("Limits: cpu.max=%dms, memory.max=%dMB, wall-watch=%dms." %
          (CPU_MAX_MS, MEM_MAX_KB // 1024, WALL_WATCHDOG_MS))
    print()

    print("Verdict precedence: CE > TLE > MLE > RE > WA > AC (first match wins).")
    print()

    print("%-14s %-9s %5s %8s %9s  %s" %
          ("program", "verdict", "test", "cpu_ms", "peak_kb", "note"))
    verdict_map = {}
    for prog in DEMO_PROGRAMS:
        r = judge_program(prog, TWO_SUM)
        verdict_map[prog.name] = r["verdict"]
        first = r["per_test"][0] if r["per_test"] else (0, "-", 0, 0)
        note = "compiled" if r["compiled"] else "syntax error -> no execution"
        print("  %-12s %-9s %5d %8d %9d  %s" %
              (prog.name, r["verdict"], first[0], first[2], first[3], note))
    print()
    print("The 'correct' program passes all %d tests -> AC. Every other program"
          % len(TWO_SUM))
    print("stops on its first failing test: off_by_one fails test 1 (WA), slow")
    print("blows the CPU budget (TLE), hungry exceeds memory.max (MLE), crash")
    print("segfaults (RE), broken never compiles (CE).")
    print()

    ok = (verdict_map["correct"] == AC and
          verdict_map["off_by_one"] == WA and
          verdict_map["slow"] == TLE and
          verdict_map["hungry"] == MLE and
          verdict_map["crash"] == RE and
          verdict_map["broken"] == CE)
    print("[check] all six verdicts produced correctly? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Compilation cache: source-hash keyed artifact store
# ---------------------------------------------------------------------------

COMPILE_MS = {"python": 0, "cpp": 2000, "java": 1500, "go": 800, "rust": 3000}


class CompileCache:
    """Key = sha256(lang + source)[:16]. On a hit, skip recompilation entirely."""

    def __init__(self):
        self._store = {}

    def key(self, lang, source):
        return hashlib.sha256((lang + "\x00" + source).encode()).hexdigest()[:16]

    def get_or_compile(self, lang, source):
        ms = COMPILE_MS.get(lang, 0)
        k = self.key(lang, source)
        if k in self._store:
            return (True, 0, k)          # hit -> 0 ms
        self._store[k] = {"lang": lang, "ms": ms}
        return (False, ms, k)            # miss -> paid ms


def section_cache():
    banner("SECTION 4: Compilation cache (source-hash keyed)")
    print("Compiled languages (C++/Java/Go/Rust) pay 0.8-3s per compile. Users")
    print("resubmit near-identical code dozens of times; caching the artifact by")
    print("sha256(lang + source) skips the recompile entirely on a hit.")
    print()
    print("Compile times by language:")
    for lang, ms in sorted(COMPILE_MS.items(), key=lambda x: -x[1]):
        print("  %-7s %5d ms" % (lang, ms))
    print()

    cache = CompileCache()
    cpp_src = '#include<bits/stdc++.h>\nint main(){int a,b;cin>>a>>b;cout<<a+b;}'

    print("Demo: submit the SAME C++ program twice (contest re-submit pattern).")
    hit1, ms1, k1 = cache.get_or_compile("cpp", cpp_src)
    print("  submit #1  hit=%-5s compile=%4dms  key=%s" % (hit1, ms1, k1))
    hit2, ms2, k2 = cache.get_or_compile("cpp", cpp_src)
    print("  submit #2  hit=%-5s compile=%4dms  key=%s" % (hit2, ms2, k2))
    saved = ms1 - ms2
    print("  time saved by cache = %d ms" % saved)
    print()

    # python compiles to bytecode (~0ms) so cache is a no-op there
    hit3, ms3, k3 = cache.get_or_compile("python", "print(a+b)")
    print("  python    hit=%-5s compile=%4dms  (interpreted -> ~0ms)" % (hit3, ms3))
    print()

    ok = (hit1 is False and hit2 is True and k1 == k2 and saved == COMPILE_MS["cpp"])
    print("[check] first submit misses, second hits, key stable, saved=%dms? " %
          COMPILE_MS["cpp"] + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Leaderboard: ICPC ranking via composite-score sorted set
# ---------------------------------------------------------------------------

PENALTY_PER_WRONG_SEC = 5 * 60   # 5 min per wrong submission (LeetCode-style)
SCORE_PACK = 1_000_000_000       # solved * 1e9 - penalty (penalty << 1e9)

CONTEST_SUBMISSIONS = [
    # (user, problem, verdict, minute_from_contest_start)
    ("alice", "P1", AC, 5),
    ("alice", "P2", AC, 10),
    ("alice", "P3", AC, 15),
    ("carol", "P1", AC, 12),
    ("carol", "P2", AC, 18),
    ("carol", "P3", AC, 45),
    ("bob",   "P1", WA, 8),
    ("bob",   "P1", AC, 20),
    ("bob",   "P2", AC, 30),
    ("dave",  "P1", WA, 10),     # P1 never accepted -> no penalty for this WA
    ("dave",  "P2", AC, 40),
    ("eve",   "P2", AC, 50),
]


def compute_standings(submissions):
    solved = {}
    penalty = {}
    wrong = {}
    for (user, prob, verdict, minute) in submissions:
        solved.setdefault(user, set())
        penalty.setdefault(user, 0)
        wrong.setdefault(user, {})
        if verdict == WA:
            wrong[user][prob] = wrong[user].get(prob, 0) + 1
        elif verdict == AC and prob not in solved[user]:
            solved[user].add(prob)
            w = wrong[user].get(prob, 0)
            penalty[user] += minute * 60 + w * PENALTY_PER_WRONG_SEC
    return solved, penalty, wrong


def section_leaderboard():
    banner("SECTION 5: Leaderboard (ICPC ranking, 5-min penalty, sorted set)")
    print("Rank by (solved DESC, penalty ASC). Penalty = sum over ACCEPTED problems")
    print("of (accept_minute*60 + wrong_count_on_that_problem * %d)." %
          PENALTY_PER_WRONG_SEC)
    print("Wrong submissions on a problem that is NEVER accepted incur NO penalty")
    print("(dave's P1 WA@10 is free because dave never solved P1).")
    print()

    solved, penalty, wrong = compute_standings(CONTEST_SUBMISSIONS)
    lb = SortedSet()
    for user in solved:
        s = len(solved[user])
        p = penalty[user]
        score = s * SCORE_PACK - p
        lb.zadd(user, score)

    print("Composite score = solved * 1e9 - penalty  (packs two sort keys into")
    print("one float so ZREVRANGE returns solved-DESC then penalty-ASC in one op):")
    print()
    print("  %-6s %7s %9s %14s  %s" % ("user", "solved", "penalty", "zset_score", "wrong detail"))
    rows = lb.zrevrange(0, len(lb) - 1)
    for rank, (user, score) in enumerate(rows):
        s = len(solved[user])
        p = penalty[user]
        wdet = ", ".join("%s:%d" % (pr, wrong[user].get(pr, 0))
                         for pr in sorted(solved[user])) or "-"
        print("  %-6s %7d %7ds %14d  %s" % (user, s, p, score, wdet))
    print()

    top3 = [u for (u, _) in lb.zrevrange(0, 2)]
    alice_pen = penalty["alice"]
    bob_pen = penalty["bob"]
    carol_pen = penalty["carol"]
    dave_pen = penalty["dave"]
    eve_pen = penalty["eve"]
    print("Top 3: %s" % ", ".join(top3))
    print("Tie-break demo: alice & carol both solved 3, but alice's penalty")
    print("(%ds) < carol's (%ds) -> alice ranks #1." % (alice_pen, carol_pen))
    print()

    ok = (top3 == ["alice", "carol", "bob"] and
          alice_pen == 1800 and carol_pen == 4500 and
          bob_pen == 3300 and dave_pen == 2400 and eve_pen == 3000 and
          len(solved["bob"]) == 2 and len(solved["dave"]) == 1)
    print("[check] top3, penalties, solved counts match ICPC rules? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - Scale estimation
# ---------------------------------------------------------------------------

def section_scale():
    banner("SECTION 6: Scale estimation")
    subs_per_day = 2_000_000
    bytes_per_meta = 5_000          # ~5KB metadata per submission
    tests_per_problem = 100         # avg 30-200; use 100
    contest_peak_qps = 2_000
    practice_peak_qps = 200
    wall_per_sub_ms = 3_000         # ~3s end-to-end (compile + 100 tests in sandbox)

    meta_day = subs_per_day * bytes_per_meta
    meta_year = meta_day * 365
    sandbox_exec_day = subs_per_day * tests_per_problem
    sandbox_fleet = contest_peak_qps * (wall_per_sub_ms / 1000.0)

    print("Assumptions:")
    print("  submissions / day            = %s" % fmt_int(subs_per_day))
    print("  metadata / submission        = %d B (code in S3, ~100KB max)" % bytes_per_meta)
    print("  test cases / problem (avg)   = %d" % tests_per_problem)
    print("  practice peak                = %d /s" % practice_peak_qps)
    print("  contest peak                 = %d /s  (30-60 min burst)" % contest_peak_qps)
    print("  wall-clock / submission      = %.1f s  (compile + tests in sandbox)" %
          (wall_per_sub_ms / 1000.0))
    print()

    print("Throughput:")
    print("  practice peak QPS            = %d /s" % practice_peak_qps)
    print("  contest peak QPS             = %d /s  (10x practice)" % contest_peak_qps)
    print("  sandbox executions / day     = %s  (subs * %d tests)" %
          (fmt_int(sandbox_exec_day), tests_per_problem))
    print()

    print("Storage (Postgres metadata + S3 source):")
    print("  metadata / day               = %s" % fmt_bytes(meta_day))
    print("  metadata / year              = %s" % fmt_bytes(meta_year))
    print()

    print("Sandbox fleet sizing (contest peak):")
    print("  concurrent sandboxes needed  = %.0f  (peak_qps * wall_per_sub)" % sandbox_fleet)
    print("  -> K8s pre-scales worker pods 30 min before contest (node provisioning")
    print("     takes 2-5 min; reactive HPA cannot meet the burst).")
    print()

    ok = (meta_year == 3_650_000_000_000 and
          sandbox_exec_day == 200_000_000 and
          sandbox_fleet == 6000)
    print("[check] 3.65TB/year metadata, 200M sandbox execs/day, 6000-slot fleet? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - GOLD values pinned for coding_platform.html
# ---------------------------------------------------------------------------

def section_gold():
    banner("SECTION 7: GOLD values (pinned for coding_platform.html)")

    # queue
    subs = [("S1", "python", "practice"), ("S2", "cpp", "practice"),
            ("S3", "python", "contest"), ("S4", "java", "practice"),
            ("S5", "cpp", "contest"), ("S6", "python", "contest")]
    parts = {}
    for sid, lang, lane in subs:
        parts.setdefault(lang, JudgeQueue()).submit(sid, lane)
    py_order = ",".join(parts["python"].pull_all())
    cpp_order = ",".join(parts["cpp"].pull_all())
    java_order = ",".join(parts["java"].pull_all())

    # sandbox
    gvisor_ms = SANDBOX_RUNTIMES[0][1]
    firecracker_ms = SANDBOX_RUNTIMES[1][1]
    prewarm_ms = SANDBOX_RUNTIMES[2][1]

    # test runner verdicts
    vmap = {}
    for prog in DEMO_PROGRAMS:
        vmap[prog.name] = judge_program(prog, TWO_SUM)["verdict"]

    # compile cache
    cache = CompileCache()
    cpp_src = '#include<bits/stdc++.h>\nint main(){int a,b;cin>>a>>b;cout<<a+b;}'
    cache.get_or_compile("cpp", cpp_src)
    hit2, ms2, _ = cache.get_or_compile("cpp", cpp_src)
    saved_ms = COMPILE_MS["cpp"]

    # leaderboard
    solved, penalty, _ = compute_standings(CONTEST_SUBMISSIONS)
    lb = SortedSet()
    scores = {}
    for user in solved:
        sc = len(solved[user]) * SCORE_PACK - penalty[user]
        scores[user] = sc
        lb.zadd(user, sc)
    top3 = ",".join(u for (u, _) in lb.zrevrange(0, 2))
    alice_solved = len(solved["alice"])
    alice_pen = penalty["alice"]
    bob_solved = len(solved["bob"])
    bob_pen = penalty["bob"]

    # scale
    meta_year_tb = round(2_000_000 * 5_000 * 365 / 1e12, 2)

    gold = [
        ("queue_n_submissions",        len(subs)),
        ("queue_python_pull",          py_order),
        ("queue_cpp_pull",             cpp_order),
        ("queue_java_pull",            java_order),
        ("sandbox_gvisor_ms",          gvisor_ms),
        ("sandbox_firecracker_ms",     firecracker_ms),
        ("sandbox_prewarmed_ms",       prewarm_ms),
        ("sandbox_mem_max_mb",         MEM_MAX_KB // 1024),
        ("sandbox_cpu_max_ms",         CPU_MAX_MS),
        ("verdict_precedence",         ",".join(VERDICT_PRECEDENCE)),
        ("test_n_cases",               len(TWO_SUM)),
        ("verdict_correct",            vmap["correct"]),
        ("verdict_off_by_one",         vmap["off_by_one"]),
        ("verdict_slow",               vmap["slow"]),
        ("verdict_hungry",             vmap["hungry"]),
        ("verdict_crash",              vmap["crash"]),
        ("verdict_broken",             vmap["broken"]),
        ("compile_cache_saved_ms",     saved_ms),
        ("compile_cache_hit",          "true" if hit2 else "false"),
        ("lb_n_users",                 len(solved)),
        ("lb_n_problems",              3),
        ("lb_top3",                    top3),
        ("lb_alice_solved",            alice_solved),
        ("lb_alice_penalty_sec",       alice_pen),
        ("lb_alice_score",             scores["alice"]),
        ("lb_bob_solved",              bob_solved),
        ("lb_bob_penalty_sec",         bob_pen),
        ("lb_bob_score",               scores["bob"]),
        ("submissions_per_day",        2_000_000),
        ("storage_per_year_tb",        meta_year_tb),
        ("practice_peak_qps",          200),
        ("contest_peak_qps",           2_000),
        ("sandbox_exec_per_day",       200_000_000),
    ]
    for k, v in gold:
        print("  %-28s = %s" % (k, v))
    print()

    ok = (py_order == "S3,S6,S1" and
          gvisor_ms == 10 and firecracker_ms == 125 and
          vmap["correct"] == AC and vmap["broken"] == CE and
          saved_ms == 2000 and hit2 is True and
          top3 == "alice,carol,bob" and
          alice_pen == 1800 and bob_pen == 3300 and
          scores["alice"] == 2_999_998_200 and
          meta_year_tb == 3.65)
    print("[check] GOLD reproduces from queue + sandbox + runner + cache + lb? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# coding_platform.py - Coding Platform (LeetCode) system design simulation")
    print("# Pure Python stdlib only. Numbers below feed CODING_PLATFORM.md")
    print("# and coding_platform.html (gold-checked).")
    section_queue()
    section_sandbox()
    section_runner()
    section_cache()
    section_leaderboard()
    section_scale()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
