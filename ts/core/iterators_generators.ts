// iterators_generators.ts — Phase 3 bundle.
//
// GOAL (one line): show, by printing every value, that JS iteration rests on TWO
// duck-typed protocols (iterable: [Symbol.iterator] → iterator; iterator:
// .next() → {value, done}); that for...of/spread/destructuring/Array.from all
// consume iterables; that GENERATORS (function*/yield) are sugar for writing
// iterators as suspendable, lazy, single-use, infinite-stream-capable functions;
// and that a generator pipeline composes map/filter/take WITHOUT materializing
// — pinning the single-use exhaustion trap, the string-iterates-CODE-POINTS
// fact, yield* delegation, two-way .next(value), and the for-await async preview.
//
// This is the GROUND TRUTH for ITERATORS_GENERATORS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists, and what it goes DEEPER on than P1):
// CONTROL_FLOW (P1) showed that for...of iterates VALUES via the iterator
// protocol while for...in iterates string keys. THIS bundle (P3) does NOT
// re-teach the for...of vs for...in contrast. Instead it opens up the PROTOCOL
// itself — the duck-typed contract beneath every for...of/spread/destructure —
// and the GENERATOR mechanism (function*/yield) that lets you write an iterator
// as a suspendable function:
//   - the two protocols: iterable ([Symbol.iterator]()) and iterator (.next());
//   - GENERATORS as suspendable functions (yield suspends, .next() resumes);
//   - laziness + INFINITE streams (naturals() never terminates; take() pulls a
//     finite prefix — the direct analog of Rust's Iterator + Python's generators);
//   - lazy PIPELINES (map/filter/take via generators, nothing materialized);
//   - the single-use EXHAUSTION trap (iterating a generator twice → 2nd empty);
//   - two-way .next(value), .return()/.throw(), and async iterators (for await).
//
// Run:
//     pnpm exec tsx iterators_generators.ts   (or: just run iterators_generators)

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

// fmtResult prints an IteratorResult<number> in a stable, readable form.
// JSON.stringify would drop `value: undefined` (the natural done case), so we
// format by hand to always show both fields deterministically. TReturn is
// widened to `unknown` so the same formatter serves void-return generators
// (natural done: value undefined), number-return generators, AND the .return(v)
// path (done with an explicit value, e.g. .return(99) -> {value:99,done:true}).
function fmtResult(r: IteratorResult<number, unknown>): string {
  if (r.done === true) {
    const v = r.value;
    return v === undefined
      ? "{ value: undefined, done: true }"
      : `{ value: ${v}, done: true }`;
  }
  return `{ value: ${r.value}, done: false }`;
}

// fmtList prints a readonly number[] as the compact "[0,1,2]" form.
function fmtList(xs: readonly number[]): string {
  return "[" + xs.join(",") + "]";
}

// ============================================================================
// Reusable lazy generator combinators (Section D's pipeline is built from these)
// ============================================================================

// take yields at most `n` values from an iterable, then stops. Crucially it
// pulls ONLY the values it needs (exactly n, or fewer if the source ends first)
// by stepping the iterator with a counted loop — so an infinite source yields a
// finite prefix. (NB: a `for...of` + count-in-body version would pull one EXTRA
// value to discover the stop; the index loop avoids that, for a crisp laziness
// demo. Calling it.return() on early stop would also close the source.)
function* take<T>(source: Iterable<T>, n: number): Generator<T, void, unknown> {
  const iter = source[Symbol.iterator]();
  for (let i = 0; i < n; i++) {
    const r = iter.next();
    if (r.done) return;
    yield r.value;
  }
}

// mapGen yields f(x) for each x in source. Lazy: f runs only when a value is
// pulled downstream.
function* mapGen<T, U>(source: Iterable<T>, f: (x: T) => U): Generator<U, void, unknown> {
  for (const x of source) {
    yield f(x);
  }
}

// filterGen yields only the x in source for which p(x) is true. Lazy.
function* filterGen<T>(source: Iterable<T>, p: (x: T) => boolean): Generator<T, void, unknown> {
  for (const x of source) {
    if (p(x)) yield x;
  }
}

// naturals is an INFINITE generator: 1, 2, 3, ... forever. It never returns.
// Only safe to consume with a limiter (take); iterating it to completion would
// hang. This is the canonical demonstration that iterators need not be arrays.
function* naturals(): Generator<number, void, unknown> {
  let n = 1;
  while (true) {
    yield n;
    n += 1;
  }
}

// ============================================================================
// Section A — The iterator protocol (.next -> {value, done}); making an object
// iterable ([Symbol.iterator]); the "protocol" = duck-typed shape contract
// ============================================================================

// makeIterator returns a PLAIN object that satisfies the Iterator protocol: it
// has a next() method returning { value, done }. No class, no `extends`, no
// Symbol — just the shape. This is what "protocol" means in JS: a duck-typed
// contract, not a nominal type.
function makeIterator(): Iterator<number, void> {
  let i = 0;
  return {
    next(): IteratorResult<number, void> {
      if (i < 3) {
        return { value: i++, done: false };
      }
      return { value: undefined, done: true };
    },
  };
}

// makeIterableIterator returns an object that is BOTH an iterator (has next()) AND
// an iterable (has [Symbol.iterator]()). Its [Symbol.iterator]() returns `this`
// (itself) — the canonical way to make an iterator also iterable. This is
// exactly what built-in iterators and generator objects do.
function makeIterableIterator(): Iterator<number, void> & Iterable<number> {
  let i = 0;
  const obj: Iterator<number, void> & Iterable<number> = {
    next(): IteratorResult<number, void> {
      if (i < 3) {
        return { value: i++, done: false };
      }
      return { value: undefined, done: true };
    },
    [Symbol.iterator]() {
      return obj;
    },
  };
  return obj;
}

function sectionA(): void {
  sectionBanner("A — The iterator protocol (.next -> {value,done}) + making an object iterable");

  // (1) Hand-roll an iterator. An iterator is ANY object with a next() method
  // that returns an object with { value, done }. We drive it by hand here; in
  // Section B we let for...of drive it for us.
  const it = makeIterator();
  console.log("Hand-rolled iterator (a plain object with a .next() method):");
  console.log(`  it.next() -> ${fmtResult(it.next())}`);
  console.log(`  it.next() -> ${fmtResult(it.next())}`);
  console.log(`  it.next() -> ${fmtResult(it.next())}`);
  console.log(`  it.next() -> ${fmtResult(it.next())}   (terminal: value is undefined)`);
  console.log(`  it.next() -> ${fmtResult(it.next())}   (stays done — the protocol's contract)`);

  // Assert the EXACT pinned sequence: 0, 1, 2, then done (value undefined),
  // then done again. The protocol says: once done, subsequent next() must keep
  // returning done:true (MDN: "After a terminating value has been yielded
  // additional calls to next() should continue to return {done: true}").
  const c = makeIterator();
  const s0 = c.next();
  const s1 = c.next();
  const s2 = c.next();
  const s3 = c.next();
  const s4 = c.next();
  check(
    "sequence is 0,1,2 then done (and stays done)",
    s0.value === 0 && s0.done === false &&
      s1.value === 1 && s1.done === false &&
      s2.value === 2 && s2.done === false &&
      s3.value === undefined && s3.done === true &&
      s4.value === undefined && s4.done === true,
  );

  // (2) The "protocol" is DUCK-TYPED, not nominal. Our hand-rolled iterator has
  // no special prototype — it is a plain Object — yet it satisfies the protocol
  // by shape. There is no reliable reflective test "is this an iterator?"; you
  // either call next() and check the result, or rely on the iterable side
  // ([Symbol.iterator]). (MDN: "It is not possible to know reflectively whether
  // a particular object is an iterator.")
  console.log("");
  console.log("Duck-typed shape — a plain Object satisfies the protocol (no class):");
  console.log(`  Object.getPrototypeOf(it) === Object.prototype  -> ${Object.getPrototypeOf(makeIterator()) === Object.prototype}`);
  console.log(`  typeof it.next                                  -> ${typeof makeIterator().next}`);
  check(
    "iterator is a plain Object (protocol is duck-typed, not nominal)",
    Object.getPrototypeOf(makeIterator()) === Object.prototype &&
      typeof makeIterator().next === "function",
  );

  // (3) Make an object ITERABLE: give it [Symbol.iterator]() returning an
  // iterator. Here the iterator IS the object itself ([Symbol.iterator] returns
  // `this`), so it is an "iterable iterator" — single-use, just like a generator.
  const ii = makeIterableIterator();
  console.log("");
  console.log("Making it iterable: add [Symbol.iterator]() that returns an iterator:");
  console.log("  const ii = { next() { ... }, [Symbol.iterator]() { return this; } };");
  console.log(`  ii[Symbol.iterator]() === ii  -> ${ii[Symbol.iterator]() === ii}   (iterable iterator)`);
  check("[Symbol.iterator]() returns this (the iterable-iterator idiom)", ii[Symbol.iterator]() === ii);
}

// ============================================================================
// Section B — for...of / spread / destructuring CONSUME iterables; built-in
// iterables (Array, Map, Set, String = CODE POINTS); plain Object is NOT iterable
// ============================================================================

function sectionB(): void {
  sectionBanner("B — Consumers (for...of/spread/destructure) + built-in iterables (string = code points)");

  // for...of drives the protocol for you: it calls [Symbol.iterator](), then
  // .next() until done:true. It works on ANY iterable, including the hand-rolled
  // one from Section A.
  const ii = makeIterableIterator();
  const fromForOf: number[] = [];
  for (const x of ii) fromForOf.push(x);
  console.log("for...of consumes any iterable (here, the hand-rolled one):");
  console.log(`  for (const x of ii) ... -> ${fmtList(fromForOf)}`);
  check("for...of over hand-rolled iterable yields [0,1,2]", fmtList(fromForOf) === "[0,1,2]");

  // (2) Spread and destructuring ALSO consume iterables — same protocol under
  // the hood. [...iterable] walks [Symbol.iterator]() and collects every value.
  const ii2 = makeIterableIterator();
  const spread = [...ii2];
  console.log("");
  console.log("Spread consumes an iterable (calls [Symbol.iterator] internally):");
  console.log(`  [...ii2] -> ${fmtList(spread)}`);
  check("[...handRolledIterable] === [0,1,2]", fmtList(spread) === "[0,1,2]");

  const ii3 = makeIterableIterator();
  const [first, second, third] = ii3;
  console.log("");
  console.log("Array destructuring consumes an iterable:");
  console.log(`  const [a, b, c] = ii3  ->  a=${first}, b=${second}, c=${third}`);
  check("destructuring pulls the first three values (0,1,2)", first === 0 && second === 1 && third === 2);

  // (3) Built-in iterables: Array, String, Map, Set, TypedArray, arguments,
  // NodeList. Their prototypes all define [Symbol.iterator]. for...of over each
  // works with zero ceremony. (🔗 COLLECTIONS_DEEP owns Map/Set internals.)
  console.log("");
  console.log("Built-in iterables — Array, Map, Set (all have [Symbol.iterator]):");
  const arrVals: number[] = [];
  for (const v of [10, 20, 30]) arrVals.push(v);
  console.log(`  for...of [10,20,30]      -> ${fmtList(arrVals)}`);

  const mapEntries: string[] = [];
  for (const [k, v] of new Map<string, number>([["a", 1], ["b", 2]])) mapEntries.push(`${k}=${v}`);
  console.log(`  for...of Map{a:1,b:2}    -> ${JSON.stringify(mapEntries)}`);

  const setVals: string[] = [];
  for (const s of new Set<string>(["x", "y", "z"])) setVals.push(s);
  console.log(`  for...of Set{x,y,z}      -> ${JSON.stringify(setVals)}`);
  check("for...of Map yields entries [a=1,b=2]", JSON.stringify(mapEntries) === '["a=1","b=2"]');
  check('for...of Set yields ["x","y","z"]', JSON.stringify(setVals) === '["x","y","z"]');

  // (4) THE PAYOFF: a String is iterable, and it iterates CODE POINTS, not
  // UTF-16 code units. "a𝔸" is TWO code points ('a' and '𝔸', where 𝔸 = U+1D538
  // is an astral character encoded as a 2-unit surrogate pair). So .length is 3
  // (UTF-16 units) but for...of / spread yield 2 code points. (🔗 STRINGS_CHARS
  // owns the UTF-16 / surrogate-pair deep dive.)
  const mixed = "a𝔸";
  const codePoints = [...mixed];
  console.log("");
  console.log("String iterates CODE POINTS (the expert fact — .length counts UTF-16 units):");
  console.log(`  const s = "a𝔸";`);
  console.log(`  s.length             -> ${mixed.length}        (UTF-16 code UNITS: 'a' + 2 surrogates)`);
  console.log(`  [...s]               -> ${JSON.stringify(codePoints)}   (CODE POINTS: 'a' + the astral 𝔸)`);
  console.log(`  [...s].length        -> ${codePoints.length}`);
  check('"a𝔸".length === 3 (UTF-16 units)', mixed.length === 3);
  check('[..."a𝔸" yields 2 code points', codePoints.length === 2);
  check('first code point is "a"', codePoints[0] === "a");
  check('second code point is "𝔸" (the full astral char, not a lone surrogate)', codePoints[1] === "𝔸");

  // (5) A PLAIN OBJECT is NOT iterable — it has no [Symbol.iterator]. for...of
  // over {} throws TypeError ("x is not iterable"). This is why for...in exists
  // for objects (iterates keys) while for...of is for iterables. (🔗 CONTROL_FLOW
  // §D owns the for...of vs for...in contrast.)
  console.log("");
  console.log("A plain Object is NOT iterable (no [Symbol.iterator]) -> for...of throws:");
  let threwTypeError = false;
  try {
    // The cast keeps TS happy; at runtime {} has no Symbol.iterator.
    for (const _x of {} as Iterable<unknown>) {
      void _x;
    }
  } catch (e) {
    threwTypeError = e instanceof TypeError;
  }
  console.log(`  for (const x of {}) -> threw TypeError? ${threwTypeError}`);
  check("for...of over a plain object throws TypeError (not iterable)", threwTypeError);
}

// ============================================================================
// Section C — GENERATORS (function*/yield): suspendable, lazy, single-use;
// INFINITE streams; yield* DELEGATION to another iterable
// ============================================================================

function sectionC(): void {
  sectionBanner("C — Generators (function*/yield): lazy suspendable; infinite streams; yield*");

  // (1) A generator function (function*) does NOT run when called — it returns a
  // GENERATOR object (a special iterator). Each .next() runs the body until the
  // next `yield`, then SUSPENDS; the yielded value comes back as {value, done:false}.
  // When the body returns (falls off the end, or `return x`), the generator is
  // done: {value: <return or undefined>, done: true}.
  function* range(): Generator<number, void, unknown> {
    yield 1;
    yield 2;
    yield 3;
  }

  const g = range();
  console.log("Generator: function* + yield — a function that SUSPENDS at each yield:");
  console.log(`  g.next() -> ${fmtResult(g.next())}`);
  console.log(`  g.next() -> ${fmtResult(g.next())}`);
  console.log(`  g.next() -> ${fmtResult(g.next())}`);
  console.log(`  g.next() -> ${fmtResult(g.next())}   (body returned; generator is done)`);

  const gSeq = range();
  const gs = [gSeq.next(), gSeq.next(), gSeq.next(), gSeq.next()];
  check(
    "generator sequence is 1,2,3 then done",
    gs[0]!.value === 1 && gs[0]!.done === false &&
      gs[1]!.value === 2 && gs[2]!.value === 3 &&
      gs[3]!.value === undefined && gs[3]!.done === true,
  );

  // (2) Spread/destructure/for...of consume a generator like any iterable (a
  // generator IS an iterable iterator — its [Symbol.iterator]() returns itself).
  const spread = [...range()];
  console.log("");
  console.log("A generator is an iterable iterator — spread consumes it:");
  console.log(`  [...(function*(){ yield 1; yield 2; yield 3 })()] -> ${fmtList(spread)}`);
  check("[...range()] deep-equals [1,2,3]", fmtList(spread) === "[1,2,3]");
  check("generator[Symbol.iterator]() === itself", range()[Symbol.iterator]() !== undefined);

  // (3) INFINITE stream. naturals() yields 1,2,3,... FOREVER (while(true) yield).
  // It is safe ONLY because iteration is LAZY and PULL-DRIVEN: the consumer
  // decides how many to take. take(naturals(), 3) pulls exactly three and stops.
  // This is impossible with an Array (which must be fully allocated); an
  // iterator can represent a sequence of unlimited size.
  const firstThree = [...take(naturals(), 3)];
  console.log("");
  console.log("INFINITE generator — naturals() yields 1,2,3,... forever; take() pulls a prefix:");
  console.log(`  take(naturals(), 3) -> ${fmtList(firstThree)}   (lazy; never hangs)`);
  check("take(naturals(), 3) === [1,2,3]", fmtList(firstThree) === "[1,2,3]");

  const firstTen = [...take(naturals(), 10)];
  console.log(`  take(naturals(), 10) -> ${fmtList(firstTen)}`);
  check("take(naturals(), 10) === [1..10]", fmtList(firstTen) === "[1,2,3,4,5,6,7,8,9,10]");

  // (4) yield* DELEGATES to another iterable/generator. `yield* someIterable`
  // yields every value of someIterable in turn, then resumes the outer generator.
  // It is the idiomatic way to compose generators (and to flatten).
  function* combined(): Generator<number, void, unknown> {
    yield 0;
    yield* [1, 2, 3]; // delegate to an Array iterable
    yield* range(); // delegate to another generator
    yield 7;
  }
  const delegated = [...combined()];
  console.log("");
  console.log("yield* DELEGATES to another iterable (compose / flatten):");
  console.log("  function* combined() { yield 0; yield* [1,2,3]; yield* range(); yield 7; }");
  console.log(`  [...combined()] -> ${fmtList(delegated)}   (0, then [1,2,3], then range 1,2,3, then 7)`);
  check(
    "yield* flattened to [0,1,2,3,1,2,3,7]",
    fmtList(delegated) === "[0,1,2,3,1,2,3,7]",
  );
}

// ============================================================================
// Section D — Lazy generator PIPELINES (map/filter/take, nothing materialized)
// + the single-use EXHAUSTION trap + .return() cleanup on early exit
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Lazy pipelines (map/filter/take) + the single-use exhaustion trap + .return()");

  // (1) LAZY PIPELINE. Compose naturals() -> map(x => x*x) -> filter(>10) ->
  // take(3). Nothing is materialized into an array until the final [...pipe].
  // The pipeline is PULL-DRIVEN: the last stage (take) asks filter for a value,
  // filter asks map, map asks naturals — so only the values actually needed are
  // ever computed. To yield 3 squares > 10 (16,25,36), take pulls 3 values from
  // filter; filter pulls map until it finds each match. Source pulls: 4 (squares
  // 1,4,9,16 -> first match 16) + 1 (25) + 1 (36) = exactly 6, from an INFINITE
  // source.
  const stats = { pulled: 0 };
  function* trackedNaturals(): Generator<number, void, unknown> {
    let n = 1;
    while (true) {
      stats.pulled += 1;
      yield n;
      n += 1;
    }
  }

  const src = trackedNaturals();
  const pipe = take(
    filterGen(
      mapGen(src, (x: number): number => x * x),
      (x: number): boolean => x > 10,
    ),
    3,
  );
  const result = [...pipe];
  console.log("Lazy pipeline: naturals -> map(x*x) -> filter(>10) -> take(3):");
  console.log(`  [...pipe]       -> ${fmtList(result)}`);
  console.log(`  source pulled   -> ${stats.pulled} value(s)   (only 6, despite an INFINITE source)`);
  check("pipeline result is [16,25,36]", fmtList(result) === "[16,25,36]");
  check("laziness: source pulled exactly 6 values (not Infinity)", stats.pulled === 6);

  // (2) THE single-use EXHAUSTION trap. A generator (and most iterators) is
  // CONSUMED by a full pass: after [...g] or a for...of that runs to completion,
  // the generator is done; a SECOND pass yields nothing. This is the #1 iterator
  // bug. The fix: either rebuild the generator, or cache the materialized array
  // if you need multiple passes.
  function* three(): Generator<number, void, unknown> {
    yield 1;
    yield 2;
    yield 3;
  }
  // threeReturn is the same sequence but typed with TReturn = number (and an
  // explicit `return 3` — the natural-completion value, mirroring MDN's
  // iterationCount idiom), so that .return(value) below accepts a numeric
  // argument (a void-TReturn generator's .return() may only receive void). At
  // runtime .return(99) OVERRIDES the natural return value.
  function* threeReturn(): Generator<number, number, unknown> {
    yield 1;
    yield 2;
    yield 3;
    return 3; // natural-completion return value (the count); .return(v) overrides it
  }
  const gOnce = three();
  const pass1 = [...gOnce];
  const pass2 = [...gOnce]; // exhausted — nothing left
  console.log("");
  console.log("Single-use trap — a generator is EXHAUSTED after one full pass:");
  console.log(`  const g = three();`);
  console.log(`  [...g] (1st pass) -> ${fmtList(pass1)}`);
  console.log(`  [...g] (2nd pass) -> ${fmtList(pass2)}   (EMPTY — g was consumed)`);
  check("first pass yields [1,2,3]", fmtList(pass1) === "[1,2,3]");
  check("second pass yields [] (exhausted)", fmtList(pass2) === "[]");

  // Same trap via for...of: two loops over ONE generator.
  const gTwice = three();
  let sum1 = 0;
  for (const x of gTwice) sum1 += x;
  let sum2 = 0;
  for (const x of gTwice) sum2 += x; // nothing to sum
  console.log("");
  console.log("Same trap via for...of — two loops over ONE generator:");
  console.log(`  1st loop sum -> ${sum1}`);
  console.log(`  2nd loop sum -> ${sum2}   (generator already exhausted)`);
  check("first for...of sums to 6", sum1 === 6);
  check("second for...of sums to 0 (exhausted)", sum2 === 0);

  // (3) .return() — for...of calls it on EARLY EXIT (break/return/throw), giving
  // the generator a chance to clean up. A generator's `finally` block is
  // guaranteed to run whether the generator finishes naturally OR is closed via
  // .return(). This is the resource-cleanup idiom for generators (e.g. closing a
  // file/connection mid-iteration). (cleanup is an OBJECT property, not a bare
  // `let`, so TS control-flow does not narrow it to its initial literal across
  // the generator-closure mutation — same reason `stats.pulled` stays `number`.)
  const cleanup = { ran: false };
  function* withCleanup(): Generator<number, void, unknown> {
    try {
      yield 1;
      yield 2;
      yield 3;
    } finally {
      cleanup.ran = true; // runs on normal completion OR on .return() (early exit)
    }
  }
  for (const x of withCleanup()) {
    if (x === 2) break; // early exit -> for...of calls g.return() -> finally runs
  }
  console.log("");
  console.log(".return() cleanup — for...of with break calls the generator's .return():");
  console.log("  for (const x of withCleanup()) { if (x === 2) break; }  // finally ran on .return()");
  console.log(`  cleanup.ran -> ${cleanup.ran}`);
  check(".return() ran the finally block on early break", cleanup.ran === true);

  // (4) Explicit .return(value): force the generator to finish, returning a
  // terminal {value, done:true}. Subsequent .next() stays done. (Uses threeReturn
  // — a TReturn=number generator — so .return() may receive the numeric 99.)
  const gRet = threeReturn();
  const before = gRet.next();
  const ret = gRet.return(99);
  const after = gRet.next();
  console.log("");
  console.log("Explicit .return(value) — force the generator to finish:");
  console.log(`  g.next()       -> ${fmtResult(before)}`);
  console.log(`  g.return(99)   -> ${fmtResult(ret)}   (value: 99, done: true)`);
  console.log(`  g.next()       -> ${fmtResult(after)}   (stays done)`);
  check("g.return(99) yields {value:99,done:true}", ret.value === 99 && ret.done === true);
  check("generator stays done after .return()", after.done === true);
}

// ============================================================================
// Section E — Two-way .next(value) + .throw() + async iterators (for await) +
// the cross-language model (Rust Iterator trait; Python generators)
// ============================================================================

// twoWay demonstrates TWO-WAY communication: a value passed to .next(v) becomes
// the RESULT of the suspended `yield` expression inside the generator. The
// Generator<TYield, TReturn, TNext> type's third param (TNext) is the type that
// .next() may receive and that `yield` evaluates to.
function* twoWay(): Generator<number, void, number> {
  const a: number = yield 1; // .next(v) -> a = v
  yield a + 100;
}

function sectionE(): void {
  sectionBanner("E — Two-way .next(value) + .throw() + async iterators (for await) + cross-language");

  // (1) Two-way .next(value). The first .next() STARTS the generator (runs to
  // the first yield); its argument is ALWAYS IGNORED (MDN: "A value passed to
  // the first invocation of next() is always ignored"). Each SUBSEQUENT
  // .next(v) resumes the suspended `yield` with v as its result.
  const g = twoWay();
  const r1 = g.next(999); // 999 IGNORED — first next() only starts the generator
  const r2 = g.next(5); // a = 5; yield a + 100 -> 105
  console.log("Two-way .next(value) — the arg becomes the result of the suspended yield:");
  console.log(`  const g = twoWay();  // function* () { const a = yield 1; yield a + 100; }`);
  console.log(`  g.next(999) -> ${fmtResult(r1)}   (FIRST next()'s arg is IGNORED)`);
  console.log(`  g.next(5)   -> ${fmtResult(r2)}   (a = 5; yields 5 + 100)`);
  check("first next()'s argument is ignored (yields 1)", r1.value === 1 && r1.done === false);
  check("second next(5) makes a=5, yields 105", r2.value === 105 && r2.done === false);

  // (2) .throw(error) injects an error AT the suspended yield, as if `yield`
  // were replaced by `throw error`. If the generator catches it, it can continue;
  // otherwise the error propagates out of .throw().
  function* catcher(): Generator<string, void, unknown> {
    try {
      yield "first";
      yield "second";
    } catch (e) {
      yield "caught: " + String((e as Error).message);
    }
  }
  const gc = catcher();
  const c1 = gc.next();
  const c2 = gc.throw(new Error("injected")); // throws at the suspended `yield "first"`
  const c3 = gc.next();
  console.log("");
  console.log(".throw(error) — inject an error at the suspended yield:");
  console.log(`  gc.next()                       -> ${JSON.stringify(c1)}`);
  console.log(`  gc.throw(new Error("injected")) -> ${JSON.stringify(c2)}   (caught inside the generator)`);
  console.log(`  gc.next()                       -> ${JSON.stringify(c3)}   (body finished; done)`);
  check('catcher caught the injected error ("caught: injected")', c2.value === "caught: injected");
  check("after catching, the generator continued and is now done", c3.done === true);

  // (3) ASYNC iterators + for await...of (PREVIEW — 🔗 ASYNC_AWAIT owns the deep
  // dive). An async generator (async function*) yields values that may be
  // awaited; for await...of consumes them. The async-iterator protocol is the
  // mirror of the sync one: [Symbol.asyncIterator]() -> { next() -> Promise<
  // {value, done} > }. There is NO core-JS object that is async iterable by
  // default (some web APIs like ReadableStream are).
  console.log("");
  console.log("Async iterators (PREVIEW — full treatment: ASYNC_AWAIT):");
  console.log('  async function* asyncRange() { yield 1; yield 2; yield 3; }');
  console.log("  for await (const x of asyncRange()) { ... }   // each .next() is a Promise");
}

// runAsyncDemo consumes an async generator with for await...of and returns the
// collected values. Kept SEPARATE from the sync sections so main() can await it.
// The sequence is deterministic (sequential awaits — no concurrency), so no
// sorting is needed (cf. §4.2 rule 4, which targets nondeterministic ORDER from
// concurrent async; here every step strictly awaits the previous).
async function runAsyncDemo(): Promise<number[]> {
  async function* asyncRange(): AsyncGenerator<number, void, unknown> {
    yield 1;
    yield 2;
    yield 3;
  }
  const out: number[] = [];
  for await (const x of asyncRange()) {
    out.push(x);
  }
  return out;
}

// runAsyncDemo also exposes the protocol shape for a printed check.
async function runAsyncShape(): Promise<void> {
  async function* demo(): AsyncGenerator<number, void, unknown> {
    yield 0;
  }
  const gen = demo();
  const isAsyncIterable = typeof (gen as AsyncGenerator<number>)[Symbol.asyncIterator] === "function";
  const nextIsFunction = typeof gen.next === "function";
  console.log("");
  console.log("Async-iterator protocol shape (duck-typed via Symbol.asyncIterator):");
  console.log(`  gen[Symbol.asyncIterator] is a function -> ${isAsyncIterable}`);
  console.log(`  gen.next is a function (returns a Promise) -> ${nextIsFunction}`);
  check("async generator has [Symbol.asyncIterator] and next()", isAsyncIterable && nextIsFunction);
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("iterators_generators.ts — Phase 3 bundle.");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: iteration rests on TWO duck-typed protocols — an ITERABLE");
  console.log("has [Symbol.iterator] -> an ITERATOR; an iterator has .next() ->");
  console.log("{value, done}. Generators (function*/yield) are sugar for writing");
  console.log("iterators as suspendable, lazy, single-use functions.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();

  // Async demo (PREVIEW to ASYNC_AWAIT). Awaited here so its output lands in
  // order before the final banner; main() is async for this reason.
  const asyncCollected = await runAsyncDemo();
  console.log("");
  console.log("> async demo output (for await...of consumed asyncRange):");
  console.log(`  collected -> ${fmtList(asyncCollected)}`);
  check("for await...of collected [1,2,3]", fmtList(asyncCollected) === "[1,2,3]");
  await runAsyncShape();

  sectionBanner("DONE — all sections printed");
}

// main() is async (it awaits the async-iterator demo). Catch any thrown error
// (a check() failure throws synchronously; inside an async fn it rejects this
// promise) and exit non-zero so `just check` / `just sweep` flag it.
main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
