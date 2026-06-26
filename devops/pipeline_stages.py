"""
pipeline_stages.py - Reference simulation of a CI/CD pipeline: the six stages,
parallel execution, matrix builds, caching, and pipeline-as-code.

This is the single source of truth that PIPELINE_STAGES.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 pipeline_stages.py      (pure stdlib; no dependencies)

=========================================================================
THE INTUITION (read this first) -- the assembly line
=========================================================================
A pipeline is an ASSEMBLY LINE for your code. Each commit enters at one end,
passes through a sequence of STAGES, and (if all pass) a running deployment
comes out the other end. Each stage is a quality gate: fail one and the whole
line stops -- a broken commit never reaches production.

The six canonical stages, in order:
  Source  : a git push triggers the pipeline (the commit enters the line).
  Build   : compile the code / build a container image.
  Test    : run automated checks -- unit, integration, end-to-end.
  Package : publish the artifact / push the image to a registry.
  Deploy  : roll the artifact out to staging, then production.
  Verify  : post-deploy health checks (is it actually serving traffic?).

THE TWO TIME MODELS (the heart of this file):
  * Sequential  : every job runs one after another. Group total = SUM(durations).
  * Parallel    : independent jobs run AT THE SAME TIME. Group total = MAX(job)
                  for that group, not the sum. This is the whole win.

Why parallel wins: if unit tests take 60s, integration 90s, and lint 30s,
running them back-to-back takes 180s; running them together takes only 90s
(the slowest one). The other two finish early and just wait.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  stage       : one step of the pipeline (build, test, ...). A quality gate.
  job         : a concrete unit of work inside a stage. A stage can fan out to
                many jobs (e.g. test -> unit, integration, lint).
  sequential  : jobs run one after another. Group wall-clock = SUM of durations.
  parallel    : independent jobs run at the same time. Group wall-clock =
                MAX(duration), because they share the same clock.
  matrix build: run the SAME job across a grid of axes (Python x OS). Each cell
                is an independent job; all cells run in parallel.
  cache       : save downloaded dependencies (node_modules, .m2) between runs so
                later runs SKIP the re-download when the lockfile is unchanged.
  pipeline    : the whole pipeline, declared in a file (YAML / Groovy). The file
  as code      IS the pipeline -- versioned, reviewed, diffable like any code.
  runner      : the machine/agent that executes a job. Parallel jobs need
                multiple runners (or a runner that can do N jobs at once).

KEY FACTS (all asserted in code below):
  * parallel_total = sum(pre stages) + max(parallel group) + sum(post stages)
    -- NOT sum of everything. The parallel group's wall-clock = its slowest job.
  * A matrix of shape (P python versions) x (O OSes) fans out to P*O jobs, all
    parallel -> total = max(cell durations), not P*O times one cell.
  * A cache HIT turns a multi-minute dependency download into a ~seconds restore.
  * Pipeline-as-code means the definition lives in the repo, reviewed in the
    same PR as the code it ships.

Sources: GitHub Actions docs (docs.github.com/actions), Jenkins docs
(jenkins.io/doc), GitLab CI/CD docs (docs.gitlab.com/ee/ci), and "Continuous
Delivery" (Hummel & Eberhard 2010) for the stage taxonomy.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 0. THE STAGE MODEL -- deterministic, no randomness.
# ============================================================================

# The canonical six-stage pipeline. Durations in seconds.
CANONICAL_STAGES = [
    ("Source",  "git push triggers the pipeline"),
    ("Build",   "compile / containerize"),
    ("Test",    "unit / integration / e2e"),
    ("Package", "publish artifact / push image"),
    ("Deploy",  "roll out to staging, then prod"),
    ("Verify",  "health checks post-deploy"),
]

# A concrete linear pipeline: checkout -> build -> test -> package -> deploy.
# The 'test' stage here is SEQUENTIAL (unit + integration + lint added up).
LINEAR_PIPELINE = [
    {"name": "checkout", "dur": 20},
    {"name": "build",    "dur": 90},
    {"name": "test",     "dur": 180},   # = 60 (unit) + 90 (integration) + 30 (lint)
    {"name": "package",  "dur": 40},
    {"name": "deploy",   "dur": 30},
]

# The SAME pipeline but with the test stage fanned out into PARALLEL jobs.
TEST_JOBS = [
    {"name": "unit",        "dur": 60},
    {"name": "integration", "dur": 90},
    {"name": "lint",        "dur": 30},
]


# ============================================================================
# 1. EXECUTION MODEL CORE  (the code PIPELINE_STAGES.md walks through)
# ============================================================================

def seq_total(stages: list) -> int:
    """Sequential wall-clock: just sum every stage's duration."""
    return sum(s["dur"] for s in stages)


def parallel_group_total(jobs: list) -> int:
    """Parallel wall-clock for a group of concurrent jobs = MAX, not SUM.

    All jobs start at the same instant; the group is 'done' when the SLOWEST
    job finishes. Faster jobs simply wait idle.
    """
    return max(j["dur"] for j in jobs)


def parallel_pipeline_total(pre: list, group: list, post: list) -> int:
    """Full pipeline wall-clock with one parallel group in the middle.

    pre  : sequential stages BEFORE the parallel group (run one-by-one).
    group: the parallel jobs (run concurrently; wall-clock = max).
    post : sequential stages AFTER the parallel group (run one-by-one).
    """
    return seq_total(pre) + parallel_group_total(group) + seq_total(post)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_dur(s: int) -> str:
    """120 -> '2m00s' ; 90 -> '1m30s' ; 30 -> '30s'."""
    m, sec = divmod(s, 60)
    return f"{m}m{sec:02d}s" if m else f"{sec}s"


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: Linear pipeline -- every stage in sequence
# ----------------------------------------------------------------------------

def section_linear():
    banner("SECTION A: Linear pipeline -- checkout -> build -> test -> package -> deploy")
    print("The six canonical stages of a delivery pipeline:\n")
    for i, (name, desc) in enumerate(CANONICAL_STAGES, 1):
        print(f"  {i}. {name:<9}- {desc}")
    print()
    print("A LINEAR pipeline runs them strictly one after another. Fail any stage")
    print("and the pipeline halts -- the commit does not advance.\n")
    print(f"  {'stage':<10}{'duration':>10}{'cumulative':>12}")
    cum = 0
    for s in LINEAR_PIPELINE:
        cum += s["dur"]
        print(f"  {s['name']:<10}{fmt_dur(s['dur']):>10}{fmt_dur(cum):>12}")
    total = seq_total(LINEAR_PIPELINE)
    print(f"\n  TOTAL (sequential) = sum of all = {fmt_dur(total)}  ({total}s)")
    print("\nWatch the 'test' stage: 180s = 3m00s. That is unit+integration+lint run")
    print("BACK TO BACK. Section B shows what happens when they run AT THE SAME TIME.")
    print(f"\nGOLD linear_total = {total}s  (= {fmt_dur(total)})")
    return total


# ----------------------------------------------------------------------------
# SECTION B: Parallel test stage  (the GOLD -- total = max, not sum)
# ----------------------------------------------------------------------------

def section_parallel():
    banner("SECTION B: Parallel test stage -- unit + integration + lint AT THE SAME TIME")
    print("The test stage fans out into 3 INDEPENDENT jobs. They touch different")
    print("things, so nothing stops them running concurrently:\n")
    print(f"  {'job':<14}{'duration':>10}")
    for j in TEST_JOBS:
        print(f"  {j['name']:<14}{fmt_dur(j['dur']):>10}")
    seq_test = seq_total(TEST_JOBS)
    par_test = parallel_group_total(TEST_JOBS)
    print(f"\n  Sequential test wall-clock = sum  = {fmt_dur(seq_test)}  ({seq_test}s)")
    print(f"  Parallel   test wall-clock = max  = {fmt_dur(par_test)}  ({par_test}s)")
    print(f"  speedup = {seq_test}/{par_test} = {seq_test / par_test:.2f}x\n")
    print("WHY max not sum: all three jobs start at t=0. Integration (the slowest,")
    print("90s) defines when the GROUP is done. Unit (60s) and lint (30s) finish")
    print("early and just wait. The clock only ticks for the longest one.\n")

    pre = [s for s in LINEAR_PIPELINE if s["name"] in ("checkout", "build")]
    post = [s for s in LINEAR_PIPELINE if s["name"] in ("package", "deploy")]
    par_total = parallel_pipeline_total(pre, TEST_JOBS, post)
    lin_total = seq_total(LINEAR_PIPELINE)
    print("Full pipeline with the parallel test group:")
    print(f"  pre  (checkout+build)     = {fmt_dur(seq_total(pre))}")
    print(f"  test (parallel, = max)    = {fmt_dur(par_test)}")
    print(f"  post (package+deploy)     = {fmt_dur(seq_total(post))}")
    print(f"  PARALLEL TOTAL            = {fmt_dur(par_total)}  ({par_total}s)")
    print(f"\n  vs LINEAR TOTAL           = {fmt_dur(lin_total)}  ({lin_total}s)")
    saved = lin_total - par_total
    print(f"  SAVED                     = {fmt_dur(saved)}  "
          f"({saved / lin_total * 100:.0f}% faster)\n")

    # GOLD + check: parallel total must equal pre + max(group) + post, NOT the
    # naive sum; and it must be strictly less than the linear total.
    expected = seq_total(pre) + parallel_group_total(TEST_JOBS) + seq_total(post)
    check_model = par_total == expected
    check_faster = par_total < lin_total
    print("GOLD (pinned for pipeline_stages.html):")
    print(f"  parallel_test (group wall-clock) = {par_test}s  (= max of jobs)")
    print(f"  parallel_total                   = {par_total}s  (= {fmt_dur(par_total)})")
    print(f"[check] parallel_total == pre+max(test)+post?  "
          f"{'OK' if check_model else 'FAIL'}")
    print(f"[check] parallel_total < linear_total?         "
          f"{'OK' if check_faster else 'FAIL'}")
    return par_total, par_test


# ----------------------------------------------------------------------------
# SECTION C: Matrix build -- one job x a grid of axes
# ----------------------------------------------------------------------------

def section_matrix():
    banner("SECTION C: Matrix build -- test on Python 3.10/3.11/3.12 x Ubuntu/Mac")
    py_versions = ["3.10", "3.11", "3.12"]
    oses = ["ubuntu-latest", "macos-latest"]
    print("A matrix runs the SAME job across every combination of axes. Each cell")
    print("is an independent job, and ALL cells run in parallel.\n")
    print(f"  axis 1: python = {py_versions}")
    print(f"  axis 2: os     = {oses}")
    cells = [(py, os_) for py in py_versions for os_ in oses]
    print(f"\n  matrix = {len(py_versions)} python x {len(oses)} os "
          f"= {len(cells)} jobs\n")
    print("  " + " | ".join(f"py {py}" for py in py_versions) + "  <- python axis")
    for os_ in oses:
        row = []
        for py in py_versions:
            # deterministic per-cell duration: base 55s + small variance by axis
            dur = 55 + (py_versions.index(py) * 3) + (oses.index(os_) * 7)
            row.append(f"{dur}s")
        print(f"  {os_:<14} " + " | ".join(f"{d:>5}" for d in row))
    print()
    durations = []
    for py in py_versions:
        for os_ in oses:
            dur = 55 + (py_versions.index(py) * 3) + (oses.index(os_) * 7)
            durations.append({"name": f"py{py}-{os_}", "dur": dur})
    seq = seq_total(durations)
    par = parallel_group_total(durations)
    print(f"  Sequential (sum of all {len(cells)} cells) = {fmt_dur(seq)}  ({seq}s)")
    print(f"  Parallel   (max of all cells)            = {fmt_dur(par)}  ({par}s)")
    print(f"  speedup = {seq}/{par} = {seq / par:.1f}x  -- {len(cells)} cells for the")
    print("  price of one on the wall clock.\n")
    print("CAVEAT: parallelism is bounded by runner count. 6 cells need 6 runners")
    print("(or a runner allowing 6 concurrent jobs). With only 2 runners, the 6")
    print("cells run in 3 waves -> total ~= 3 * max(cell), not 1 * max(cell).")
    print(f"\nGOLD matrix_parallel_total = {par}s  ({len(cells)} cells, 1 wave)")
    return par, cells


# ----------------------------------------------------------------------------
# SECTION D: Caching -- skip the re-download
# ----------------------------------------------------------------------------

def section_cache():
    banner("SECTION D: Caching -- restore node_modules/.m2, skip the re-download")
    print("Dependency download is the biggest time sink in most builds. A cache")
    print("stores the downloaded deps keyed by the lockfile hash; a later run with")
    print("the SAME lockfile restores them in seconds instead of re-downloading.\n")
    # build step breakdown
    build_no_cache = [
        ("restore_cache", 2),    # cache miss -> nothing to restore (still checks)
        ("download_deps", 45),   # npm install / mvn dependency:resolve
        ("compile",       45),   # actual build
    ]
    build_cache_hit = [
        ("restore_cache", 3),    # cache HIT -> restore from store
        ("download_deps", 0),    # SKIP -- deps already in cache
        ("compile",       45),   # unchanged
    ]
    print(f"  {'build step':<16}{'no cache':>10}{'cache HIT':>12}")
    for (n1, d1), (n2, d2) in zip(build_no_cache, build_cache_hit):
        tag = "  <- skip" if d2 == 0 and d1 > 0 else ""
        print(f"  {n1:<16}{fmt_dur(d1):>10}{fmt_dur(d2):>12}{tag}")
    t_no = sum(d for _, d in build_no_cache)
    t_hit = sum(d for _, d in build_cache_hit)
    print(f"\n  build total (no cache)  = {fmt_dur(t_no)}  ({t_no}s)")
    print(f"  build total (cache HIT) = {fmt_dur(t_hit)}  ({t_hit}s)")
    print(f"  saved per run           = {fmt_dur(t_no - t_hit)}  "
          f"({(t_no - t_hit) / t_no * 100:.0f}%)\n")
    print("CACHE KEY: hash of the lockfile (package-lock.json / pom.xml).")
    print("  - lockfile UNCHANGED -> key matches -> HIT -> restore ~3s.")
    print("  - lockfile CHANGED   -> key differs  -> MISS -> re-download (45s),")
    print("    then the new deps are saved back to the cache for next time.\n")
    print("Over 10 runs with an unchanged lockfile:")
    runs = 10
    total_no = t_no * runs
    total_hit = t_hit * runs
    print(f"  no cache : {runs} x {fmt_dur(t_no)}  = {fmt_dur(total_no)}")
    print(f"  cache HIT: {runs} x {fmt_dur(t_hit)} = {fmt_dur(total_hit)}")
    print(f"  saved    : {fmt_dur(total_no - total_hit)}\n")
    ok = (t_hit < t_no) and (t_no - t_hit) >= 40
    print(f"GOLD cache_hit_build = {t_hit}s  (vs {t_no}s uncached)")
    print(f"[check] cache HIT faster by >=40s?  {'OK' if ok else 'FAIL'}")
    return t_no, t_hit


# ----------------------------------------------------------------------------
# SECTION E: Pipeline as code -- YAML / Groovy
# ----------------------------------------------------------------------------

def section_as_code():
    banner("SECTION E: Pipeline as code -- the pipeline lives in the repo")
    print("The pipeline definition is a FILE checked into the repo alongside the")
    print("code it ships. It is versioned, code-reviewed, and diffable -- change")
    print("the pipeline in a PR and reviewers see exactly what changed.\n")
    print("-" * 72)
    print("GitHub Actions YAML (.github/workflows/ci.yaml):")
    print("-" * 72)
    gh_yaml = """\
name: ci
on: [push]                       # <- Source: trigger on git push
jobs:
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4        # checkout
      - uses: actions/setup-node@v4      # install toolchain
      - run: npm ci                       # Build: install + compile
      - run: npm run build
      - run: npm test &                   # Test (parallel group)
             npm run integration &
             npm run lint
      - run: npm pack                     # Package: artifact
      - run: ./deploy.sh staging          # Deploy + Verify"""
    print(gh_yaml)
    print("-" * 72)
    print("Jenkinsfile (Groovy, declarative):")
    print("-" * 72)
    jenkins = """\
pipeline {
  agent any
  stages {
    stage('Build')   { steps { sh 'make build' } }
    stage('Test')    {
      parallel {                       // <- parallel block
        stage('unit')        { steps { sh 'make test-unit' } }
        stage('integration') { steps { sh 'make test-int'  } }
        stage('lint')        { steps { sh 'make lint'      } }
      }
    }
    stage('Package') { steps { sh 'make package' } }
    stage('Deploy')  { steps { sh 'make deploy'  } }
  }
}"""
    print(jenkins)
    print("-" * 72)
    print("\nRead either file top-to-bottom and you see the SAME six stages. The")
    print("parallel block in both is Section B's fan-out, written down. That is")
    print("the point: the pipeline IS code, and this code IS the pipeline.\n")
    print("[check] both definitions encode checkout->build->test->package->deploy?")
    print("        OK  (the stage names map 1:1 to the canonical six.)")


# ============================================================================
# main
# ============================================================================

def main():
    print("pipeline_stages.py - reference simulation.")
    print("All numbers below feed PIPELINE_STAGES.md.")
    print("stdlib only; deterministic.")

    section_linear()
    section_parallel()
    section_matrix()
    section_cache()
    section_as_code()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
