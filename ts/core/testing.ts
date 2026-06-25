// testing.ts — Phase 5 bundle (Standard Library Essentials).
//
// GOAL (one line): demonstrate, by running a tiny embedded test suite INLINE
// (no subprocess), how node:assert/strict's assertions behave, how a test
// runner works (a from-scratch test/describe/it + setup/teardown that counts
// pass/fail), how table-driven tests + spies + async-rejection assertions are
// structured, and the red→green TDD discipline — all pinning the outcomes as
// check()'d invariants.
//
// This is the GROUND TRUTH for TESTING.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// LINEAGE (why this bundle exists): modern TS/JS testing has converged on TWO
// stdlib-adjacent pillars — Node ships a BUILT-IN test runner (`node:test`,
// stable since Node 20) plus `node:assert/strict`, and Vitest is the popular
// third-party runner (Jest-compatible API, ESM-native, Vite-powered). Both rest
// on the SAME primitives: an assertion that THROWS on mismatch (🔗
// ERRORS_EXCEPTIONS — an `AssertionError` IS an exception), wrapped in a runner
// that catches the throw and records pass/fail. This bundle uses the REAL
// `node:assert/strict` (the genuine stdlib assertion library) for assertions,
// and builds a tiny FROM-SCRATCH runner so you see exactly what node:test /
// Vitest do internally — no magic, no subprocess, fully deterministic.
//
// DETERMINISM NOTE: every test runs INLINE and is AWAITED in sequence (no
// parallel workers, no subprocess, no wall-clock timing, no Math.random). The
// pass/fail counts are therefore exact and reproducible. We NEVER spawn a test
// runner as a child process (that path is nondeterministic: path-dependent TAP
// output, timing-sensitive ordering). assert.pass/fail counts are asserted.
//
// Run:
//     pnpm exec tsx testing.ts   (or: just run testing)

import assert from "node:assert/strict";

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// ============================================================================
// The code under test (tiny, deterministic, used by sections A–E)
// ============================================================================

// clamp pins a number into [min, max]. Classic table-driven target: it has
// clean edge cases (below min, at min, mid, at max, above max) and one error
// path (min > max).
function clamp(value: number, min: number, max: number): number {
  if (min > max) {
    throw new RangeError("clamp: min must be <= max");
  }
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

// fetchUser is the async code-under-test for Section D: it can RESOLVE (ok) or
// REJECT (RangeError), which is exactly what assert.rejects asserts over.
async function fetchUser(id: number): Promise<{ readonly name: string }> {
  if (id < 0) {
    throw new RangeError("fetchUser: negative id");
  }
  return { name: "ada" };
}

// ============================================================================
// A tiny FROM-SCRATCH test runner (the demystified node:test / Vitest core)
// ============================================================================
//
// Every JS test runner (node:test, Vitest, Jest, Mocha) does the SAME three
// things under the hood:
//   1. register (name, fn) pairs (test/it);
//   2. invoke fn inside a try/catch — if it throws OR its returned promise
//      rejects, the test FAILS; otherwise it PASSES;
//   3. run before/after (setup/teardown) hooks around each test.
// This class implements exactly that, inline, so the pass/fail counts the .md
// prints are produced by logic you can read — not by a black-box subprocess.
//
// The REAL assertion library (`node:assert/strict`) is used INSIDE test bodies:
// it throws an AssertionError on mismatch (🔗 ERRORS_EXCEPTIONS), and THIS
// runner's try/catch is what converts that throw into a recorded FAIL.

interface TestOutcome {
  readonly name: string;
  readonly passed: boolean;
  readonly error: string | undefined;
}

type TestFn = () => unknown | Promise<unknown>;

class MiniRunner {
  private readonly outcomes: TestOutcome[] = [];
  private readonly befores: Array<() => void> = [];
  private readonly afters: Array<() => void> = [];
  private depth = 0;

  // beforeEach registers a hook run BEFORE every subsequent test() on this
  // runner. (node:test / Vitest expose the same name with the same semantics.)
  beforeEach(fn: () => void): void {
    this.befores.push(fn);
  }

  // afterEach registers a hook run AFTER every subsequent test() — even if it
  // threw. Used for cleanup (closing handles, restoring spies).
  afterEach(fn: () => void): void {
    this.afters.push(fn);
  }

  // test registers-and-runs one case: befores -> fn -> afters, catching any
  // throw/rejection as a FAIL. Returns the boolean outcome so callers can
  // assert on it. Awaiting it serializes order (deterministic output).
  async test(name: string, fn: TestFn): Promise<boolean> {
    for (const hook of this.befores) hook();
    let passed = true;
    let error: string | undefined;
    try {
      await fn();
    } catch (err) {
      passed = false;
      error = err instanceof Error ? err.message : String(err);
    } finally {
      for (const hook of this.afters) hook();
    }
    this.outcomes.push({ name, passed, error });
    const tag = passed ? "PASS" : "FAIL";
    const indent = "  ".repeat(this.depth + 1);
    // Print only the first line of the error so a multi-line AssertionError
    // diff stays on one FAIL line (cleaner, still deterministic).
    const firstLine = error === undefined ? "" : error.split("\n", 1)[0];
    const tail = passed ? "" : `  -- ${firstLine}`;
    console.log(`${indent}${tag}  ${name}${tail}`);
    return passed;
  }

  // describe is the BDD grouping primitive (Jest/Vitest/node:test): it prints
  // a header and indents the it() calls made inside body. The body is awaited
  // so the inner tests run in source order (deterministic).
  async describe(label: string, body: () => Promise<void>): Promise<void> {
    console.log(`  ${"  ".repeat(this.depth)}${label}:`);
    this.depth++;
    try {
      await body();
    } finally {
      this.depth--;
    }
  }

  // it is test() by another name — the BDD spelling used inside describe().
  async it(name: string, fn: TestFn): Promise<boolean> {
    return this.test(name, fn);
  }

  // summary prints and returns the aggregate counts. The .md asserts these.
  summary(): { readonly passes: number; readonly fails: number; readonly total: number } {
    const passes = this.outcomes.filter((o) => o.passed).length;
    const fails = this.outcomes.length - passes;
    const total = this.outcomes.length;
    console.log(`  -> ${passes} passed, ${fails} failed (${total} total)`);
    return { passes, fails, total };
  }
}

// ============================================================================
// Section A — node:assert/strict: equal / deepEqual / throws (AssertionError)
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — node:assert/strict: equal / deepEqual / throws");

  // node:assert/strict is the STRICT assertion mode: equal aliases strictEqual
  // (uses ===), and deepEqual aliases deepStrictEqual (recurses + Object.is on
  // primitives). It is the mode node:test and Vitest users reach for. The
  // legacy `node:assert` uses == and is footgun-heavy (see VALUES_TYPES_COERCION
  // §D) — avoid it.
  console.log("node:assert/strict: equal=strictEqual (===), deepEqual=deepStrictEqual.");
  console.log("On mismatch it throws AssertionError (code 'ERR_ASSERTION').");

  // 1) strictEqual uses === — so 1 !== "1" (no coercion, unlike legacy equal).
  let threwStrictEqual = false;
  try {
    assert.strictEqual(1, "1");
  } catch (err) {
    threwStrictEqual = true;
    const e = err as NodeJS.ErrnoException & { code?: string; operator?: string };
    console.log(`  strictEqual(1, "1") threw: ${e.name}  code=${e.code}  operator=${e.operator}`);
  }
  check('strictEqual(1, "1") throws AssertionError (===, no coercion)', threwStrictEqual);

  // equal (strict mode) IS strictEqual — so it ALSO throws on 1 vs "1".
  let threwEqual = false;
  try {
    assert.equal(1, "1");
  } catch {
    threwEqual = true;
  }
  check('equal(1, "1") also throws (strict mode aliases strictEqual)', threwEqual);

  // 2) deepEqual vs equal — the KEY distinction. equal is SHALLOW + ===; for
  //    objects === compares REFERENCES, so two structurally-equal objects are
  //    NOT equal. deepEqual RECURSES the enumerable own-properties, so two
  //    structurally-equal nested objects ARE deepEqual.
  console.log("");
  console.log("deepEqual vs equal (the key distinction):");
  console.log("  equal:      shallow, uses ===  -> objects compare by REFERENCE");
  console.log("  deepEqual:  recursive structural compare  -> by VALUE");

  // deepEqual succeeds on nested identical structure:
  assert.deepEqual({ a: { b: 1 } }, { a: { b: 1 } });
  console.log('  deepEqual({a:{b:1}}, {a:{b:1}})  -> OK   (recurses, value-equal)');
  check("deepEqual on nested identical structure", true);

  // equal (===) FAILS on two distinct-but-equal objects (different references):
  let threwEqualObjs = false;
  try {
    assert.equal({ a: 1 }, { a: 1 });
  } catch {
    threwEqualObjs = true;
  }
  console.log('  equal({a:1}, {a:1})            -> throws (=== compares references)');
  check("equal on two distinct objects throws (reference inequality)", threwEqualObjs);

  // deepEqual also catches a real mismatch (nested value differs):
  let threwDeepMismatch = false;
  try {
    assert.deepEqual({ a: { b: 1 } }, { a: { b: 2 } });
  } catch {
    threwDeepMismatch = true;
  }
  check("deepEqual on nested mismatched structure throws", threwDeepMismatch);

  // 3) throws: asserts that fn() THROWS. If fn does NOT throw, throws itself
  //    throws AssertionError — so a "passed without throwing" test is caught.
  //    Optional 2nd arg matches the error (class, RegExp, or validator).
  console.log("");
  console.log("assert.throws(fn[, matcher]) — asserts fn throws:");

  // (a) fn that DOES throw -> throws() is satisfied (no error).
  assert.throws(() => {
    throw new TypeError("boom");
  });
  console.log('  throws(() => { throw TypeError })    -> OK   (fn did throw)');
  check("throws passes when fn throws", true);

  // (b) fn that does NOT throw -> throws() raises AssertionError.
  let throwsAsserted = false;
  try {
    assert.throws(() => {
      /* does not throw */
    });
  } catch (err) {
    throwsAsserted = true;
    const e = err as NodeJS.ErrnoException & { code?: string };
    console.log(`  throws(() => { /* no throw */ }) -> ${e.name} (code=${e.code})`);
  }
  check("throws raises AssertionError when fn does NOT throw", throwsAsserted);

  // (c) matcher: throws can verify the error CLASS.
  assert.throws(
    () => {
      throw new RangeError("min>max");
    },
    RangeError,
  );
  console.log("  throws(fn, RangeError)               -> OK   (matched class)");
  check("throws matches the error class", true);

  // (d) matcher can be a validator fn returning true (or throwing on wrong).
  assert.throws(
    () => {
      throw new Error("nope");
    },
    (err: Error) => err.message === "nope",
  );
  check("throws accepts a validator matcher", true);

  // 4) The real code-under-test, asserted via assert.strictEqual:
  assert.strictEqual(clamp(-5, 0, 100), 0);
  assert.strictEqual(clamp(50, 0, 100), 50);
  assert.strictEqual(clamp(999, 0, 100), 100);
  console.log("  clamp(-5,0,100)=0  clamp(50,0,100)=50  clamp(999,0,100)=100  -> OK");
  check("clamp strictEqual assertions all pass", true);

  // 5) clamp's error path: min>max throws RangeError — assert via throws.
  assert.throws(
    () => clamp(5, 10, 1),
    RangeError,
  );
  check("clamp(5,10,1) throws RangeError (min>max)", true);
}

// ============================================================================
// Section B — Table-driven tests + the mini in-process runner
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — Table-driven tests + the mini in-process runner");

  // TABLE-DRIVEN: one [] of {input, expected}, ranged in a loop, each checked
  // with the SAME assertion. This is the canonical shape in Go (testing.go)
  // and Rust (testing.rs) too — table-driven is a CROSS-LANGUAGE idiom.
  console.log("Table-driven test: an array of {input, expected} cases, looped.");
  interface ClampCase {
    readonly label: string;
    readonly input: number;
    readonly min: number;
    readonly max: number;
    readonly expected: number;
  }
  const cases: ReadonlyArray<ClampCase> = [
    { label: "below min", input: -5, min: 0, max: 100, expected: 0 },
    { label: "at min", input: 0, min: 0, max: 100, expected: 0 },
    { label: "mid", input: 50, min: 0, max: 100, expected: 50 },
    { label: "at max", input: 100, min: 0, max: 100, expected: 100 },
    { label: "above max", input: 999, min: 0, max: 100, expected: 100 },
  ];

  console.log("");
  console.log("  label        input   expected   actual   pass");
  console.log("  -----        -----   --------   ------   ----");
  let passed = 0;
  for (const c of cases) {
    const actual = clamp(c.input, c.min, c.max);
    const ok = actual === c.expected;
    if (ok) passed++;
    console.log(
      `  ${c.label.padEnd(12)} ${String(c.input).padStart(5)}   ${String(c.expected).padStart(8)}   ${String(actual).padStart(6)}   ${ok ? "PASS" : "FAIL"}`,
    );
  }
  console.log(`  -> ${passed}/${cases.length} cases passed`);
  check("table-driven: all 5 clamp cases pass", passed === cases.length);

  // THE MINI IN-PROCESS RUNNER — run a real (tiny) suite through MiniRunner.
  // This is the demystified node:test / Vitest core: register test, catch
  // throw, count. We ALSO run a deliberately-failing test to prove the runner
  // records a FAIL instead of crashing the process.
  console.log("");
  console.log("Mini in-process runner (test/describe/it, from scratch):");
  const r = new MiniRunner();

  await r.test("strictEqual: 2+2 === 4", () => assert.strictEqual(2 + 2, 4));
  await r.test("deepEqual: nested objects", () =>
    assert.deepEqual({ a: { b: 1 } }, { a: { b: 1 } }),
  );
  await r.test("clamp via real assertion", () => assert.strictEqual(clamp(150, 0, 100), 100));
  // A deliberately-FAILING test: the runner must CATCH the AssertionError and
  // record FAIL, NOT crash. (1 !== 2.)
  await r.test("deliberately failing: 1 === 2 (expected FAIL)", () =>
    assert.strictEqual(1, 2),
  );

  const s = r.summary();
  check("mini runner counted 3 passes", s.passes === 3);
  check("mini runner counted 1 fail (caught, did not crash)", s.fails === 1);
  check("mini runner ran 4 tests total", s.total === 4);

  // describe/it — the BDD grouping shape (node:test, Vitest, Jest all expose
  // it). Inside describe, tests are indented; the depth is tracked.
  console.log("");
  console.log("describe/it (BDD grouping shape — same as node:test/Vitest/Jest):");
  const r2 = new MiniRunner();
  await r2.describe("String#repeat", async () => {
    await r2.it('repeats a string', () => assert.strictEqual("ab".repeat(3), "ababab"));
    await r2.it('repeat(0) is empty', () => assert.strictEqual("x".repeat(0), ""));
  });
  await r2.describe("Math", async () => {
    await r2.it("max of three", () => assert.strictEqual(Math.max(1, 7, 3), 7));
  });
  const s2 = r2.summary();
  check("describe/it: 3 grouped tests pass", s2.passes === 3 && s2.fails === 0);
}

// ============================================================================
// Section C — Mocking: a tiny spy/mock + assert.rejects (async tests)
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — Mocking (a tiny spy) + assert.rejects (async tests)");

  // A SPY wraps a function and RECORDS its calls (args + count) while still
  // delegating to the real impl. A MOCK goes further: it REPLACES the impl
  // with a stub return value. Vitest exposes both as vi.fn() / vi.spyOn();
  // node:test has mock.method/mock.fn. Here we build both from scratch —
  // they are just closures over a calls[] array.
  console.log("A spy = closure over a calls[] array; a mock = spy + stub return.");
  console.log("(Vitest: vi.fn() / vi.spyOn(); node:test: mock.fn / mock.method.)");

  // makeSpy: records args, delegates to impl. Specialized to (number)=>number
  // to stay `any`-free under strict mode.
  function makeSpy(impl: (x: number) => number): {
    fn: (x: number) => number;
    calls: number[][];
  } {
    const calls: number[][] = [];
    const fn = (x: number): number => {
      calls.push([x]);
      return impl(x);
    };
    return { fn, calls };
  }

  // makeMock: records args, ALWAYS returns a fixed stub value (no impl call).
  function makeMock<T>(stubReturn: T): {
    fn: (x: number) => T;
    calls: number[][];
  } {
    const calls: number[][] = [];
    const fn = (x: number): T => {
      calls.push([x]);
      return stubReturn;
    };
    return { fn, calls };
  }

  // Spy in action: delegate + record.
  console.log("");
  console.log("makeSpy((x) => x * 2)  — delegates AND records:");
  const { fn: doubleSpy, calls: spyCalls } = makeSpy((x) => x * 2);
  console.log(`  doubleSpy(5)  -> ${doubleSpy(5)}`);
  console.log(`  doubleSpy(3)  -> ${doubleSpy(3)}`);
  console.log(`  doubleSpy(7)  -> ${doubleSpy(7)}`);
  console.log(`  spy.calls     -> ${JSON.stringify(spyCalls)}`);
  check("spy recorded 3 calls", spyCalls.length === 3);
  check("spy recorded call args [5,3,7]", spyCalls[0]?.[0] === 5 && spyCalls[1]?.[0] === 3 && spyCalls[2]?.[0] === 7);
  check("spy delegated to impl (5*2=10)", spyCalls[0]?.[0] !== undefined && doubleSpy(5) === 10);

  // Mock in action: stub return + record (impl NEVER called).
  console.log("");
  console.log('makeMock("STUB")  — returns stub, records, ignores impl:');
  const { fn: mockFn, calls: mockCalls } = makeMock<string>("STUB");
  console.log(`  mockFn(1) -> ${mockFn(1)}`);
  console.log(`  mockFn(2) -> ${mockFn(2)}`);
  console.log(`  mock.calls -> ${JSON.stringify(mockCalls)}`);
  check("mock always returns the stub value", mockFn(99) === "STUB");
  check("mock recorded 3 calls (2 above + 1 here)", mockCalls.length === 3);

  // ASYNC TESTS via assert.rejects — awaits a promise (or async fn) and asserts
  // it REJECTS with the expected error. The mirror of throws, for Promises.
  // assert.rejects RETURNS a promise; you must await it (as a test body would).
  console.log("");
  console.log("assert.rejects(asyncFn[, matcher]) — asserts the promise REJECTS:");

  // (a) fetchUser(-1) rejects with RangeError -> rejects() is satisfied.
  await assert.rejects(() => fetchUser(-1), RangeError);
  console.log("  rejects(() => fetchUser(-1), RangeError) -> OK   (did reject)");
  check("assert.rejects passes when the promise rejects as expected", true);

  // (b) fetchUser(1) RESOLVES (does NOT reject) -> rejects() itself rejects.
  let rejectsAsserted = false;
  try {
    await assert.rejects(() => fetchUser(1));
  } catch (err) {
    rejectsAsserted = true;
    const e = err as NodeJS.ErrnoException & { code?: string };
    console.log(`  rejects(() => fetchUser(1))            -> ${e.name} (promise resolved, not rejected)`);
  }
  check("assert.rejects raises when the promise does NOT reject", rejectsAsserted);

  // The same logic inside the mini runner: an async test body awaits rejects.
  console.log("");
  console.log("Async test inside the mini runner (body is async, runner awaits it):");
  const r = new MiniRunner();
  await r.test("fetchUser(-1) rejects RangeError", async () => {
    await assert.rejects(() => fetchUser(-1), RangeError);
  });
  await r.test("fetchUser(1) resolves to {name:'ada'}", async () => {
    const u = await fetchUser(1);
    assert.deepEqual(u, { name: "ada" });
  });
  const s = r.summary();
  check("mini runner ran 2 async tests, both pass", s.passes === 2 && s.fails === 0);
}

// ============================================================================
// Section D — Setup/teardown (beforeEach/afterEach)
// ============================================================================

async function sectionD(): Promise<void> {
  sectionBanner("D — Setup/teardown (beforeEach/afterEach)");

  // beforeEach runs BEFORE each test; afterEach runs AFTER each test (even on
  // throw). Use them to reset shared state, stub/unstub the clock, restore
  // spied methods. node:test, Vitest, and Jest all expose the identical names.
  // Here: a shared counter is RESET to 0 before every test, proving the hook
  // fires per-test, not once.
  console.log("beforeEach: runs before EACH test. afterEach: runs after EACH test.");
  console.log("(node:test / Vitest / Jest all expose these exact names.)");

  const r = new MiniRunner();
  let counter = 0;
  const log: string[] = [];

  r.beforeEach(() => {
    counter = 0; // fresh state for every test
    log.push("before");
  });
  r.afterEach(() => {
    log.push("after"); // cleanup marker after every test
  });

  await r.test("counter starts at 0 (beforeEach ran)", () =>
    assert.strictEqual(counter, 0),
  );
  await r.test("increment to 1 inside this test", () => {
    counter++;
    assert.strictEqual(counter, 1);
  });
  await r.test("counter is 0 AGAIN (beforeEach re-ran between tests)", () =>
    assert.strictEqual(counter, 0),
  );

  const s = r.summary();
  console.log(`  hook trace: ${JSON.stringify(log)}`);
  check("beforeEach reset state between tests: 3 passes", s.passes === 3 && s.fails === 0);
  // 3 tests * (1 before + 1 after) = 6 hook markers, strictly interleaved:
  // ["before","after","before","after","before","after"]
  check(
    "hook trace is 6 markers (before/after x 3), strictly interleaved",
    log.length === 6 && log[0] === "before" && log[1] === "after" && log[5] === "after",
  );
}

// ============================================================================
// Section E — TDD red→green→refactor + Vitest + cross-language (documented)
// ============================================================================

async function sectionE(): Promise<void> {
  sectionBanner("E — TDD red→green + Vitest + cross-language (documented)");

  // TDD = Test-Driven Development. The loop is RED -> GREEN -> REFACTOR:
  //   RED:     write a test for behavior that doesn't exist yet -> it FAILS.
  //   GREEN:   write the MINIMUM code to make it pass.
  //   REFACTOR: clean up the code (extract, rename) with tests as a safety net.
  // We demonstrate the discipline inline on a slugify helper.
  console.log("TDD: RED (write failing test) -> GREEN (minimal impl) -> REFACTOR.");
  console.log("");

  // --- RED stage: the test exists before the behavior does. ---
  // Desired: slugify("Hello, World!") === "hello-world". Define the spec:
  const specInput = "Hello, World!";
  const specExpected = "hello-world";

  // A naive first implementation (intentionally WRONG) -> RED:
  function slugifyV1(s: string): string {
    return s.toLowerCase(); // forgot to replace non-alphanumerics
  }
  const redActual = slugifyV1(specInput);
  const redPass = redActual === specExpected;
  console.log(`RED   slugifyV1("${specInput}") = "${redActual}"  (expected "${specExpected}") -> ${redPass ? "PASS?!" : "FAIL"}`);
  check("RED: v1 fails the spec (lowercase only is not enough)", redPass === false);

  // --- GREEN stage: minimal fix to make the test pass. ---
  function slugifyV2(s: string): string {
    return s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }
  const greenActual = slugifyV2(specInput);
  const greenPass = greenActual === specExpected;
  console.log(`GREEN slugifyV2("${specInput}") = "${greenActual}"  (expected "${specExpected}") -> ${greenPass ? "PASS" : "FAIL"}`);
  check("GREEN: v2 satisfies the spec", greenPass);

  // Run the GREEN version through a table-driven guard (regression safety):
  const slugCases: ReadonlyArray<readonly [string, string]> = [
    ["Hello, World!", "hello-world"],
    ["  multiple   spaces  ", "multiple-spaces"],
    ["---trim-dashes---", "trim-dashes"],
    ["UPPER Case", "upper-case"],
  ];
  let slugPassed = 0;
  for (const [input, expected] of slugCases) {
    if (slugifyV2(input) === expected) slugPassed++;
  }
  console.log(`REFACTOR guard: ${slugPassed}/${slugCases.length} slugify cases pass`);
  check("REFACTOR guard: all 4 slugify cases pass", slugPassed === slugCases.length);

  // --- Coverage & the snapshot trap (DOCUMENTED, not run) ---
  // Coverage = % of lines/branches/functions executed by the suite. c8 and
  // istanbul (which c8 wraps) instrument the code and report. node:test
  // integrates via `node --test --experimental-test-coverage`; Vitest via
  // `vitest --coverage` (provider: v8/istanbul). 100% line coverage does NOT
  // mean bug-free: it counts EXECUTION, not ASSERTION quality.
  console.log("");
  console.log("Coverage (documented): c8 / istanbul instrument code; node --test");
  console.log("  --experimental-test-coverage and vitest --coverage report it.");
  console.log("  100% lines != bug-free: it counts execution, not assertion quality.");

  // The SNAPSHOT TRAP: snapshot tests serialize output and FAIL on ANY change.
  // Great for stable UIs/serializers; brittle for anything that drifts (dates,
  // UUIDs, unordered keys). Vitest/Jest auto-UPDATE snapshots with a flag,
  // which can silently bless a bug. Document.
  console.log("");
  console.log("Snapshot trap (documented): locks serialized output; brittle on drift");
  console.log("  (dates/UUIDs/unordered keys). Auto-update can silently bless a bug.");

  // Vitest & node:test — the two pillars (DOCUMENTED API surface).
  console.log("");
  console.log("Vitest (the popular third-party runner, Jest-compatible):");
  console.log("  import { describe, it, expect, vi } from 'vitest';");
  console.log("  vi.fn() / vi.spyOn() — the lib version of makeSpy/makeMock above.");
  console.log("  ESM-native, Vite-powered, watch mode, in-source testing.");
  console.log("node:test (the built-in Node runner, stable since Node 20):");
  console.log("  import { test, describe, it, beforeEach, afterEach } from 'node:test';");
  console.log("  Zero deps. TAP output. Pairs with node:assert/strict (this bundle).");

  // Cross-language: Go and Rust both ship an integrated, compiler-aware test
  // story — the contrast sharpens what "JS testing" is. (See ## Sources.)
  console.log("");
  console.log("Cross-language (🔗 ../go/TESTING.md, ../rust/TESTING.md):");
  console.log("  Go:    func TestX(t *testing.T); table-driven; func Benchmark(b *testing.B); b.ReportAllocs()");
  console.log("  Rust:  #[test] fn x(); #[should_panic]; assert_eq!(got, want); cargo test");
  console.log("  JS:    node:test + node:assert/strict (this bundle) OR Vitest. Throws = AssertionError.");
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("testing.ts — Phase 5 bundle (Standard Library Essentials).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. The test suite runs INLINE (no subprocess); pass/fail");
  console.log("counts are deterministic and asserted via check().");
  console.log("");
  console.log("Real assertion library: node:assert/strict (stdlib, built-in).");
  console.log("Runner: a from-scratch test/describe/it (demystifies node:test/Vitest).");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();
  sectionBanner("DONE — all sections printed");
}

await main();
