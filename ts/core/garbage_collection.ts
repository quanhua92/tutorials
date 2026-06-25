// garbage_collection.ts — Phase 3 bundle (Memory & Object Semantics).
//
// GOAL (one line): show, by printing the DETERMINISTIC facts, how JS/V8
// garbage collection works — reachability from roots, the WeakRef / WeakMap /
// WeakSet / FinalizationRegistry opt-out APIs, and the closure / cache /
// timer retention leak class — WITHOUT asserting any GC-timing-dependent
// reclamation.
//
// This is the GROUND TRUTH for GARBAGE_COLLECTION.md. Every number, table,
// and worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// DETERMINISM CAVEAT (the key rule for THIS bundle): garbage collection timing
// is NONDETERMINISTIC — V8 decides when and whether to collect based on heap
// pressure and heuristics. So we NEVER assert that an object "has been
// collected" or that a WeakRef "is now undefined" after dropping a reference.
// We assert ONLY deterministic facts: reachability (a WeakRef.deref() returns
// the value WHILE still strongly referenced), that global.gc() (via
// --expose-gc) runs without error, that a retained closure keeps an object
// alive. Reclamation is framed as "may", not "will".
//
// LINEAGE (why this bundle exists): V8 (Node's engine) uses a GENERATIONAL,
// concurrent, incremental mark-sweep collector ("Orinoco"). Memory is
// reclaimed when an object becomes UNREACHABLE (no path of references from a
// root). Unlike Rust (no GC — deterministic Drop/RAII) or Go (concurrent
// tri-color GC, a close sibling), JS lets you OPT IN to non-retention via
// weak references. The bug class this bundle targets is ACCIDENTAL RETENTION:
// closures, caches, event listeners, and global arrays keeping objects alive
// long after they are needed. This is the cross-language memory pivot.
//
// Run:
//     just run garbage_collection
//     # with --expose-gc for the gc demos:
//     node --expose-gc --import tsx core/garbage_collection.ts

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

// The --expose-gc flag installs global.gc as a synchronous "collect now"
// function. It is ABSENT by default. We access it via a typed cast (never
// `any`) and guard every use so the bundle runs clean WITHOUT the flag too.
type GcFn = () => void;
function getGc(): GcFn | undefined {
  const maybe = (globalThis as { gc?: GcFn }).gc;
  return typeof maybe === "function" ? maybe : undefined;
}

// ============================================================================
// Section A — Reachability, roots & the mark-sweep idea
// ============================================================================

function sectionA(): void {
  sectionBanner("A — Reachability, roots & the mark-sweep idea");

  // An object is REACHABLE if there is a path of STRONG references from a ROOT
  // to it. V8's roots include: the execution stack (locals on the call stack),
  // the global object, and the handles held by the embedder. Reachability is
  // the GC's proxy for "liveness" — a reachable object must be kept; an
  // unreachable object MAY be collected.

  // A local variable on this function's call stack is a root -> its object is
  // reachable while this frame exists.
  const held = { payload: 42 };
  const ref = new WeakRef(held);

  console.log("ROOTS (V8): the call stack (locals), the global object, embedder handles.");
  console.log("An object is reachable if a STRONG-reference path exists from a root.");
  console.log("Reachable objects MUST be kept; unreachable ones MAY be collected.\n");

  console.log(`held.payload      -> ${held.payload}`);
  console.log(`new WeakRef(held) -> a NON-retaining view of the same object`);
  console.log(`ref.deref()      -> ${JSON.stringify(ref.deref())}   (obj still strongly held)`);
  console.log(`ref.deref() === held -> ${ref.deref() === held}   (the WeakRef resolves to the live object)`);

  // DETERMINISTIC: while `held` is strongly referenced, the WeakRef MUST
  // resolve to it. This is a reachability fact, NOT a reclamation fact.
  check("WeakRef.deref() === held while held is strongly referenced", ref.deref() === held);
  check("WeakRef.deref() !== undefined for a reachable object", ref.deref() !== undefined);

  // A second object reachable ONLY through `held` (a property) is also alive.
  const nested = held;
  check("an aliased reference resolves to the same object (nested === held)", nested === held);

  // The mark-sweep algorithm (the foundation every modern engine builds on):
  //   1. MARK  — start at the roots, follow every strong pointer, mark each
  //              reached object. Anything unmarked is unreachable = garbage.
  //   2. SWEEP — walk the heap, return unmarked objects' memory to a free list.
  //   3. (optional) COMPACT — copy survivors together to defragment.
  // This is why CIRCLES are reclaimed: a cycle with no path from a root is
  // never marked, even though its members point at each other.
  console.log("");
  console.log("Mark-sweep (the foundation): MARK from roots via strong refs,");
  console.log("SWEEP unmarked (unreachable) memory back to a free list,");
  console.log("(optionally) COMPACT survivors to defragment.");
  console.log("Cycles are NOT a leak here: a rootless cycle is never marked.");
}

// ============================================================================
// Section B — WeakRef + global.gc (guarded --expose-gc)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — WeakRef + global.gc (guarded --expose-gc)");

  const gc = getGc();
  const gcExposed = gc !== undefined;

  console.log("--expose-gc installs global.gc as a synchronous 'collect now' function.");
  console.log("It is ABSENT by default. The bundle guards it so it runs either way.\n");
  console.log(`global.gc exposed?  -> ${gcExposed}   (${gcExposed ? "--expose-gc in effect" : "not exposed; gc-dependent demos SKIP gracefully"})`);

  if (gcExposed) {
    // DETERMINISTIC when exposed: gc() itself does not throw. (Whether it
    // actually collects THIS object is a heuristic — we never assert that.)
    gc();
    console.log("[check] gc exposed (--expose-gc): global.gc() ran without error: OK");
  } else {
    console.log("[check] gc exposed: SKIPPED (run with --expose-gc for the gc demos)");
  }

  // A WeakRef is a NON-retaining reference: creating one does NOT keep the
  // target alive. While the target is strongly held elsewhere, deref() returns
  // it; once the target is only weakly reachable, deref() MAY return undefined.
  const obj = { id: "B-target" };
  const w = new WeakRef(obj);

  console.log("");
  console.log("WeakRef is NON-retaining: it does not extend the target's lifetime.");
  console.log(`w.deref() === obj  -> ${w.deref() === obj}   (obj still strongly held by local)`);

  // DETERMINISTIC reachability assertion (the pinned value for this bundle):
  check("new WeakRef(obj).deref() === obj while obj is strongly held", w.deref() === obj);

  // Demonstrate the deref contract without depending on reclamation timing:
  // deref() returns the object OR undefined. We type-check the union but do
  // NOT assert which branch — that depends on GC heuristics.
  const maybe: { id: string } | undefined = w.deref();
  console.log(`typeof w.deref()   -> ${typeof maybe}   (object while reachable; undefined if collected)`);
  check("w.deref() returns the object type while it is reachable", typeof maybe === "object");

  // After the last strong reference is dropped, the object becomes ELIGIBLE.
  // We reassign to drop the local strong path, then print ONLY the documented
  // contract — never the runtime deref value, because that is nondeterministic.
  console.log("");
  console.log("After the last strong reference is dropped the object becomes ELIGIBLE");
  console.log("for collection — but deref() MAY return the object OR undefined:");
  console.log("V8's GC heuristics decide, so reclamation is framed as 'may', not 'will'.");

  if (gcExposed) {
    // Calling gc() again does not throw (deterministic). It MAY trigger a
    // collection, but we deliberately do not read w.deref() afterwards.
    gc();
    check("global.gc() called again without error (reclamation NOT asserted)", true);
  }
  // Note: `obj` is intentionally still in scope here to keep this function
  // type-stable; the eligibility discussion above is conceptual. We never
  // assert a post-drop deref value.
  void obj;
}

// ============================================================================
// Section C — WeakMap, WeakSet (weak keys) & FinalizationRegistry
// ============================================================================

function sectionC(): void {
  sectionBanner("C — WeakMap, WeakSet (weak keys) & FinalizationRegistry");

  // WeakMap / WeakSet hold their KEYS weakly: if a key is unreachable from
  // everywhere EXCEPT the weak structure, the key (and, for WeakMap, its
  // entry) MAY be collected. The key MUST be an object (or a non-registered
  // symbol) — primitives are rejected at runtime (a TypeError).

  // --- WeakMap --------------------------------------------------------------
  const wm = new WeakMap<object, string>();
  const key = { name: "wm-key" };
  wm.set(key, "wm-value");

  console.log("WeakMap: KEYS are weakly held; the value is reachable WHILE the key is.");
  console.log(`wm.get(key)  -> ${JSON.stringify(wm.get(key))}   (key strongly held)`);
  console.log(`wm.has(key)  -> ${wm.has(key)}`);
  check("WeakMap.get(key) === value while key is strongly held", wm.get(key) === "wm-value");
  check("WeakMap.has(key) === true", wm.has(key) === true);

  // WeakMap keys must be objects — a primitive key throws TypeError at runtime.
  let primitiveThrew = false;
  let primitiveError = "";
  try {
    // Cast through unknown to bypass the type guard and reach the REAL runtime
    // check (WeakMap.prototype.set rejects non-object keys).
    const setter = wm.set as unknown as (k: unknown, v: string) => WeakMap<object, string>;
    setter("primitive-string", "x");
  } catch (e) {
    primitiveThrew = true;
    primitiveError = e instanceof TypeError ? "TypeError" : "other";
  }
  console.log(`wm.set("primitive", x) -> ${primitiveThrew ? `throws ${primitiveError}` : "no throw"}   (keys must be objects)`);
  check("WeakMap rejects a primitive key (TypeError at runtime)", primitiveThrew && primitiveError === "TypeError");

  // --- WeakSet --------------------------------------------------------------
  const ws = new WeakSet<object>();
  const member = { name: "ws-member" };
  ws.add(member);

  console.log("");
  console.log("WeakSet: members are weakly held; presence does not keep them alive.");
  console.log(`ws.has(member) -> ${ws.has(member)}`);
  check("WeakSet.has(member) === true", ws.has(member) === true);

  const nonmember = { name: "ws-nonmember" };
  check("WeakSet.has(nonmember) === false (never added)", ws.has(nonmember) === false);

  // Weak structures are NOT iterable and have NO size (by design: exposing the
  // key set would let you observe GC liveness, which the spec forbids).
  console.log("");
  console.log("WeakMap/WeakSet are NOT iterable and expose NO .size (by spec design:");
  console.log("iterating keys would observe GC liveness, which must stay invisible).");
  check('WeakMap has no "size" property', !("size" in wm));
  check('WeakSet has no "size" property', !("size" in ws));

  // --- FinalizationRegistry -------------------------------------------------
  // A FinalizationRegistry lets you register a callback that MAY run after a
  // target object is garbage-collected. The callback is NONDETERMINISTIC: it
  // MAY run, MAY run late, or MAY NEVER run. We demonstrate the API surface
  // (register / unregister) — which IS deterministic — but NEVER assert that
  // the callback fires.
  const finalizedKeys: string[] = [];
  const registry = new FinalizationRegistry((held: string) => {
    // This callback MAY run after the target is collected. We push into an
    // array but never assert its length (nondeterministic).
    finalizedKeys.push(held);
  });

  const target = { name: "fr-target" };
  const token = { name: "fr-unregister-token" };

  let registerOk = false;
  try {
    registry.register(target, "held-A", token);
    registerOk = true;
  } catch {
    registerOk = false;
  }
  check("FinalizationRegistry.register(target, held, token) does not throw", registerOk);

  // unregister(token) returns true iff a target registered with that token was
  // found and removed. Deterministic.
  const unregistered = registry.unregister(token);
  check("FinalizationRegistry.unregister(token) === true (was registered)", unregistered === true);

  console.log("");
  console.log("FinalizationRegistry: a callback that MAY run after a target is collected.");
  console.log("It is NONDETERMINISTIC — it may run late, or never. Use only for");
  console.log("non-critical cleanup; never assert that it fires.");
  console.log(`registry.unregister(token) -> ${unregistered}   (deterministic: target was registered)`);

  // finalizedKeys may be empty or non-empty depending on GC; we do NOT print
  // its length because that would be nondeterministic across runs.
  void finalizedKeys;
}

// ============================================================================
// Section D — Retention bugs: closures, caches, timers, listeners
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Retention bugs: closures, caches, timers, listeners");

  // The GC reclaims ONLY unreachable objects. The leak class in JS is
  // ACCIDENTAL RETENTION: a long-lived reference keeps an object alive past
  // its usefulness. The four classic vectors are closures, caches, timers,
  // and listeners. We demonstrate the closure-retention pattern (the only
  // one we can assert deterministically: a reachable closure keeps its
  // captured object alive).

  // --- A closure retains its captured environment ---------------------------
  // makeRetainer creates a "big" object and returns a getter that closes over
  // it. As long as the getter is reachable, the big object is reachable too —
  // the WeakRef resolves to it. (This is the 🔗 CLOSURES_CAPTURE connection.)
  function makeRetainer(): { ref: WeakRef<{ rows: number[] }>; getter: () => number } {
    const big = { rows: [10, 20, 30, 40] };
    const ref = new WeakRef(big);
    // The closure captures `big` BY REFERENCE (a live binding). `big` stays
    // reachable for as long as this closure is reachable.
    const getter = (): number => big.rows.length;
    return { ref, getter };
  }

  const { ref, getter } = makeRetainer();
  console.log("makeRetainer() returns a getter that closes over a 'big' object.");
  console.log("While the getter is reachable, the big object is reachable too.");

  // DETERMINISTIC: the reachable closure keeps its captured object alive.
  check("closure-retained object: WeakRef.deref() !== undefined (closure keeps it alive)", ref.deref() !== undefined);
  check("closure-retained object: getter() === 4 (captures the live binding)", getter() === 4);

  // --- A growing cache as a retention leak ----------------------------------
  // A plain Map keyed by string STRONGLY holds its values: entries never
  // become garbage, so the cache grows without bound. The fix is a WeakMap
  // (object keys) or a WeakRef-wrapped value so entries CAN be collected.
  const cache = new Map<string, { data: number[] }>();
  for (let i = 0; i < 3; i++) {
    cache.set(`key-${i}`, { data: [i, i * 2] });
  }
  console.log("");
  console.log("A plain Map<string, V> STRONGLY holds values -> entries never collect.");
  console.log(`cache.size after 3 inserts -> ${cache.size}   (grows without bound)`);
  check("plain Map retains all entries (size === 3)", cache.size === 3);

  // The weak-keyed alternative: a Map<string, WeakRef<V>> whose values can be
  // reclaimed, plus a FinalizationRegistry to clean up dead entries (the MDN
  // canonical pattern). We assert the API shape, not reclamation.
  const weakCache = new Map<string, WeakRef<{ data: number[] }>>();
  const live = { data: [1, 2] };
  weakCache.set("live", new WeakRef(live));
  const entry = weakCache.get("live");
  console.log(`weakCache.get('live')?.deref()?.data -> ${JSON.stringify(entry?.deref()?.data)}   (value while live held)`);
  check("WeakRef-wrapped cache value resolves while the object is held", entry?.deref() === live);

  // --- Documented leak vectors (not runnable as asserts) --------------------
  console.log("");
  console.log("Other retention vectors (documented — Node/browser specific):");
  console.log("  * setInterval callback: keeps its captured closure alive until cleared.");
  console.log("  * addEventListener: keeps the listener (and its closure) alive until removed.");
  console.log("  * detached DOM nodes (browser): a node removed from the DOM but held by JS.");
  console.log("  * global/module-top arrays: live for the process lifetime, never swept.");
  console.log("Fix: clear timers (clearInterval), remove listeners, null stale references,");
  console.log("and prefer WeakMap/WeakRef caches so entries CAN be reclaimed.");
}

// ============================================================================
// Section E — V8 generational + Orinoco model (quotes) + cross-language
// ============================================================================

function sectionE(): void {
  sectionBanner("E — V8 generational + Orinoco model + cross-language");

  // These are ENGINE FACTS (V8.dev), not runnable assertions about a specific
  // collection. We print the model and assert only deterministic structural
  // facts (the shape of process.memoryUsage, not its values).

  console.log("V8 heap layout (generational):");
  console.log("  YOUNG generation = nursery + intermediate (semi-space: From/To).");
  console.log("    Allocations start in the nursery; survivors of one minor GC become");
  console.log("    'intermediate'; survivors of a second minor GC are promoted to OLD.");
  console.log("  OLD generation    = collected by the major (mark-compact) GC.");
  console.log("");
  console.log("Generational Hypothesis: 'most objects die young' (V8.dev). So minor GCs");
  console.log("(Scavenger) are frequent and cheap (copy only survivors); major GCs");
  console.log("(mark-compact) are rare and costly (mark the whole old generation).");

  // Two collectors in V8: Major (Mark-Compact, whole heap) + Minor (Scavenger,
  // young gen). Documented; not asserted at runtime.
  console.log("");
  console.log("Two collectors: Minor GC (Scavenger, young gen, copies survivors) +");
  console.log("Major GC (Mark-Compact, whole heap). Orinoco adds parallel,");
  console.log("incremental, and concurrent techniques to keep them off the main thread.");

  // Orinoco's three techniques (V8.dev verbatim definitions):
  console.log("");
  console.log("Orinoco techniques (V8.dev 'Trash talk'):");
  console.log("  PARALLEL    — main + helper threads work together during a stop-the-world");
  console.log("                pause; total pause divided across threads.");
  console.log("  INCREMENTAL — main thread does small GC slices interleaved with JS;");
  console.log("                spreads work over time (does not reduce total main-thread time).");
  console.log("  CONCURRENT  — helper threads do GC entirely in the background while the");
  console.log("                main thread runs JS uninterrupted (the hardest, best technique).");

  // Deterministic structural fact: process.memoryUsage exists and reports the
  // V8 heap fields. The VALUES vary per run, so we print only the SORTED key
  // names (the shape), never the numbers.
  const mem = process.memoryUsage();
  const memKeys = Object.keys(mem).sort();
  console.log("");
  console.log("process.memoryUsage() — V8 heap fields (keys only; values are run-specific):");
  for (const k of memKeys) {
    console.log(`  ${k}`);
  }
  check('process.memoryUsage() reports "heapUsed"', "heapUsed" in mem);
  check('process.memoryUsage() reports "heapTotal"', "heapTotal" in mem);
  check('process.memoryUsage() reports "external"', "external" in mem);
  check('process.memoryUsage() reports "arrayBuffers"', "arrayBuffers" in mem);

  // Cross-language: JS's GC-managed reachability model vs. Go and Rust.
  console.log("");
  console.log("Cross-language memory models:");
  console.log("  JS   — GC reclaims UNREACHABLE objects; weak refs are an OPT-IN escape hatch.");
  console.log("  Go   — concurrent tri-color mark-sweep GC (a close sibling); GOGC/GOMEMLIMIT");
  console.log("         tune trigger + soft limit; no weak-map primitive in the language.");
  console.log("  Rust — NO GC: deterministic Drop/RAII frees the instant the owner leaves");
  console.log("         scope. Memory bugs become compile errors (the borrow checker).");

  // Node --max-old-space-size raises V8's old-generation limit; exceeding it
  // throws a JavaScript heap out of memory (FATAL) error. Documented, not run.
  console.log("");
  console.log("Node memory flags (documented):");
  console.log("  --max-old-space-size=N  raise V8's old-generation heap limit (MB).");
  console.log("  Exceeding it -> 'JavaScript heap out of memory' (FATAL alloc failure).");
  console.log("  --expose-gc             install global.gc for synchronous collection.");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("garbage_collection.ts — Phase 3 bundle (Memory & Object Semantics).");
  console.log("Deterministic facts only: reachability, weak-ref APIs, retention bugs.");
  console.log("GC TIMING is nondeterministic — reclamation is framed as 'may', not 'will'.");
  console.log("");
  console.log("Reminder: every check() asserts a DETERMINISTIC invariant. We never assert");
  console.log("that an object 'has been collected' — that depends on V8's GC heuristics.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
