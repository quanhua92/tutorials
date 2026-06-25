// build_tooling.ts — Phase 6 bundle (member: metaprog).
//
// GOAL (one line): show, by reading the repo's own tsconfig files via node:fs
// and asserting their parsed values, how the TypeScript TOOLCHAIN splits into
// three roles — `tsc` (typecheck/emit), `tsx`/`esbuild` (run/erase types), and
// `tsup`/`esbuild` (bundle) — and why the tsconfig.json is the build CONTRACT
// that all three honor.
//
// This is the GROUND TRUTH for BUILD_TOOLING.md. Every config value, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): the TS toolchain has SPLIT roles. `tsc`
// TYPECHECKS (it is the "vet" gate — `tsc --noEmit` emits nothing and exits
// non-zero on any type error). `tsx`/`esbuild` RUN `.ts directly at high speed
// by ERASING types WITHOUT type-checking (esbuild strips annotations,
// interfaces, generics — no validation). `tsup`/`esbuild` BUNDLE for publish
// (emit .js + .d.ts + .map). Because tsx skips checking, a program can RUN
// happily in tsx yet FAIL `tsc` — the classic "runs in tsx but fails tsc" trap.
// That split is WHY the Justfile has a separate `just typecheck` gate alongside
// `just run`. Understanding it is the TS analog of knowing Rust's build.rs +
// Cargo and Go's //go:build + ldflags splits.
//
// DETERMINISM NOTE: this bundle does NOT spawn tsc/tsx/tsup as subprocesses
// (output would be nondeterministic / version-dependent). Instead it reads the
// repo's own tsconfig.base.json + metaprog/tsconfig.json via node:fs, parses
// them, and ASSERTS the option values — which are static, deterministic facts.
// It also demonstrates type erasure observably: a value typed `: number` is
// just a number at runtime (typeof === "number"); an `interface` leaves NO
// runtime trace. Bundlers + sourcemaps are documented via a real (constructed)
// sourcemap anatomy walkthrough.
//
// Run:
//     pnpm exec tsx build_tooling.ts   (or: just run build_tooling)

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

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

// --- typed shapes for a parsed tsconfig.json (NO `any`; fields are optional) ---
//
// tsconfig.json is JSON, so `JSON.parse` returns the structural shape below.
// Every field is optional (tsc accepts partial configs), so we read each via
// optional chaining and assert the EXACT value the repo has committed. This is
// a deterministic read of a static file — no spawn, no version drift.

interface CompilerOptions {
  target?: string;
  module?: string;
  moduleResolution?: string;
  lib?: string[];
  types?: string[];
  strict?: boolean;
  noUncheckedIndexedAccess?: boolean;
  exactOptionalPropertyTypes?: boolean;
  noImplicitOverride?: boolean;
  noFallthroughCasesInSwitch?: boolean;
  noImplicitReturns?: boolean;
  noUnusedLocals?: boolean;
  noUnusedParameters?: boolean;
  esModuleInterop?: boolean;
  forceConsistentCasingInFileNames?: boolean;
  skipLibCheck?: boolean;
  isolatedModules?: boolean;
  verbatimModuleSyntax?: boolean;
  declaration?: boolean;
  sourceMap?: boolean;
  noEmit?: boolean;
  outDir?: string;
}

interface TsConfig {
  extends?: string;
  compilerOptions?: CompilerOptions;
  include?: string[];
  exclude?: string[];
}

// readConfig parses a tsconfig JSON file into the typed shape above.
// `as unknown as TsConfig` forces the cast through `unknown` (no `any` leak).
function readConfig(p: string): TsConfig {
  const text = readFileSync(p, "utf8");
  return JSON.parse(text) as unknown as TsConfig;
}

// requireStr returns a string option or throws (used only for keys we KNOW the
// repo commits, so a throw means the contract was edited and this bundle must
// be revisited).
function requireStr(cfg: TsConfig, key: keyof CompilerOptions): string {
  const opts = cfg.compilerOptions;
  if (!opts) {
    throw new Error("compilerOptions missing");
  }
  const v = opts[key];
  if (typeof v !== "string") {
    throw new Error(`option ${String(key)} is not a string`);
  }
  return v;
}

// resolve the two real config paths from THIS file's location via import.meta.
// import.meta.url is the ESM way to find "where am I?" (🔗 MODULES_PACKAGES).
const here = dirname(fileURLToPath(import.meta.url));
const BASE_PATH = join(here, "..", "tsconfig.base.json");
const MEMBER_PATH = join(here, "tsconfig.json");

// ============================================================================
// Section A — The toolchain split: tsc (check/emit) vs tsx/esbuild (run/erase)
//                                  vs tsup (bundle); the type-erasure proof.
// ============================================================================

function sectionA(): void {
  sectionBanner("A — The toolchain split & the type-erasure proof");

  // TS's static layer — annotations, interfaces, type aliases, generics — is
  // ERASED at runtime by tsx/esbuild (and by `tsc` at emit). What survives is
  // a plain JS program. The ONLY type info the runtime has is what `typeof`
  // and `instanceof` (runtime operators) can see. This is observable:

  const answer: number = 42; // a VALUE with a type annotation
  interface User {
    id: number;
    name: string;
  }
  type Alias = { kind: "alias" };
  const u: User = { id: 1, name: "alice" };
  const a: Alias = { kind: "alias" };

  console.log("Type-erasure proof (run via tsx = esbuild strips types):");
  console.log(`  const answer: number = 42   -> typeof answer = ${typeof answer}`);
  console.log(`  const u:      User     = {} -> typeof u      = ${typeof u}   (interface User is GONE)`);
  console.log(`  const a:      Alias    = {} -> typeof a      = ${typeof a}   (type Alias is GONE)`);
  console.log('  There is no "number"/"User"/"Alias" string at runtime — typeof');
  console.log('  returns one of the 8 JS runtime strings only (see VALUES_TYPES_COERCION).');

  check('typeof answer === "number" (annotation erased, value remains)', typeof answer === "number");
  check('typeof u === "object" (interface User leaves NO runtime trace)', typeof u === "object");
  check('typeof a === "object" (type Alias leaves NO runtime trace)', typeof a === "object");

  // The "runs in tsx but fails tsc" trap, demonstrated WITHOUT writing broken
  // code. We CANNOT make this file fail tsc (it would break the gate), so we
  // show the MECHANISM: tsx/esbuild does not type-check, it only erases. The
  // line below assigns a string to a number-typed slot THROUGH `unknown` (a
  // type-only cast that is erased), so at RUNTIME the value is the string "1"
  // — yet tsx runs it without complaint. `tsc` would reject the assignment
  // `const n: number = "1"` directly; here we route through unknown to keep
  // this file type-clean while proving the RUNTIME accepts the wrong type.
  // Route `n` and its typeof through `unknown` so tsc CANNOT narrow the result
  // to the declared type — this is honest: the RUNTIME typeof sees the actual
  // value, while tsc only sees the (erased) annotation. Without this routing,
  // tsc would flag `typeof n === "string"` as no-overlap (TS2367) — itself a
  // perfect illustration that tsc trusts the type, tsx trusts the value.
  const wrong: unknown = "1"; // runtime value is the STRING "1"
  const n: number = wrong as number; // `as number` is ERASED -> no runtime check
  const nType: unknown = typeof n; // unknown => tsc cannot const-fold to "number"
  const nVal: unknown = n; // route value through unknown for the literal compare
  console.log("");
  console.log('The "runs in tsx but fails tsc" trap (mechanism):');
  console.log(`  const n: number = ("1" as number)  -> typeof n = ${nType}   value = ${JSON.stringify(nVal)}`);
  console.log("  tsx/esbuild RAN this (no type-check); tsc would REJECT `as number` from");
  console.log('  string->number as unsound. THIS is why `just typecheck` is a separate gate.');

  check('tsx ran a string-as-number assignment (typeof n === "string", NOT number)', nType === "string");
  check('value survived as the string "1" (erasure keeps the value, drops the type)', nVal === "1");

  // The three roles, summarized as a deterministic decision table (printed, not
  // spawned — invoking tsc/tsup would be nondeterministic / version-dependent):
  console.log("");
  console.log("The three toolchain roles (tsc | tsx/esbuild | tsup):");
  console.log("  tsc --noEmit        TYPECHECK gate (vet)        emits nothing; exits non-zero on error");
  console.log("  tsx file.ts         RUN (dev)                   esbuild erases types in-memory; no .js");
  console.log("  tsup / esbuild      BUNDLE (publish)           emits .js + .d.ts + .map to dist/");
  console.log("  ONLY tsc checks types. tsx/esbuild ERASE types without checking.");
}

// ============================================================================
// Section B — tsconfig.json is the build CONTRACT (read & assert real values)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — tsconfig.json is the build contract (read tsconfig.base.json)");

  const base = readConfig(BASE_PATH);
  const o = base.compilerOptions;
  if (!o) {
    throw new Error("tsconfig.base.json has no compilerOptions");
  }

  console.log(`Read: ${BASE_PATH}  (the repo's shared base, read via node:fs)`);
  console.log("Parsed compilerOptions (the CONTRACT every member inherits):");

  // target: the JS SYNTAX LEVEL tsc emits (down-levels newer syntax to this).
  const target = requireStr(base, "target");
  console.log(`  target                 = ${JSON.stringify(target)}`);
  check('base.target === "ES2023"', target === "ES2023");

  // module + moduleResolution: how tsc emits/interprets imports.
  const moduleOpt = requireStr(base, "module");
  const modRes = requireStr(base, "moduleResolution");
  console.log(`  module                 = ${JSON.stringify(moduleOpt)}`);
  console.log(`  moduleResolution       = ${JSON.stringify(modRes)}`);
  check('base.module === "NodeNext"', moduleOpt === "NodeNext");
  check('base.moduleResolution === "NodeNext"', modRes === "NodeNext");

  // lib: which type-definitions (ES2023 libs) are visible. Array — under
  // noUncheckedIndexedAccess we guard the index access.
  const lib = o.lib;
  const hasEs2023 = Array.isArray(lib) && lib.length > 0 && lib[0] === "ES2023";
  console.log(`  lib                    = ${JSON.stringify(lib)}`);
  check('base.lib[0] === "ES2023"', hasEs2023);

  // types: which ambient @types packages are auto-included.
  const types = o.types;
  const hasNodeTypes = Array.isArray(types) && types.includes("node");
  console.log(`  types                  = ${JSON.stringify(types)}`);
  check('base.types includes "node"', hasNodeTypes);

  // The strict family (the heart of the contract).
  console.log(`  strict                 = ${o.strict}`);
  console.log(`  noUncheckedIndexedAccess = ${o.noUncheckedIndexedAccess}`);
  console.log(`  exactOptionalPropertyTypes = ${o.exactOptionalPropertyTypes}`);
  console.log(`  noImplicitOverride     = ${o.noImplicitOverride}`);
  console.log(`  noFallthroughCasesInSwitch = ${o.noFallthroughCasesInSwitch}`);
  console.log(`  noImplicitReturns      = ${o.noImplicitReturns}`);
  console.log(`  noUnusedLocals         = ${o.noUnusedLocals}`);
  console.log(`  noUnusedParameters     = ${o.noUnusedParameters}`);
  check("base.strict === true", o.strict === true);
  check("base.noUncheckedIndexedAccess === true", o.noUncheckedIndexedAccess === true);
  check("base.exactOptionalPropertyTypes === true", o.exactOptionalPropertyTypes === true);
  check("base.noImplicitOverride === true", o.noImplicitOverride === true);
  check("base.noFallthroughCasesInSwitch === true", o.noFallthroughCasesInSwitch === true);
  check("base.noImplicitReturns === true", o.noImplicitReturns === true);
  check("base.noUnusedLocals === true", o.noUnusedLocals === true);
  check("base.noUnusedParameters === true", o.noUnusedParameters === true);

  // Interop / safety / module-system flags.
  console.log(`  esModuleInterop        = ${o.esModuleInterop}`);
  console.log(`  forceConsistentCasingInFileNames = ${o.forceConsistentCasingInFileNames}`);
  console.log(`  skipLibCheck           = ${o.skipLibCheck}`);
  console.log(`  isolatedModules        = ${o.isolatedModules}`);
  console.log(`  verbatimModuleSyntax   = ${o.verbatimModuleSyntax}`);
  console.log(`  noEmit                 = ${o.noEmit}`);
  check("base.esModuleInterop === true", o.esModuleInterop === true);
  check("base.forceConsistentCasingInFileNames === true", o.forceConsistentCasingInFileNames === true);
  check("base.skipLibCheck === true", o.skipLibCheck === true);
  check("base.isolatedModules === true", o.isolatedModules === true);
  check("base.verbatimModuleSyntax === false (type imports auto-elided)", o.verbatimModuleSyntax === false);

  // noEmit: the headline. The base contract is TYPECHECK-ONLY — tsc never
  // writes a .js here. Emission is the bundler's job (Section D). This is why
  // `just typecheck` is a pure vet gate.
  check("base.noEmit === true (tsc is a TYPECHECK gate, not an emitter)", o.noEmit === true);
}

// ============================================================================
// Section C — extends (member inherits base) + resolution + isolatedModules
//             + verbatimModuleSyntax + type imports
// ============================================================================

function sectionC(): void {
  sectionBanner("C — extends inheritance, moduleResolution, isolatedModules, type imports");

  const base = readConfig(BASE_PATH);
  const member = readConfig(MEMBER_PATH);
  const m = member.compilerOptions;
  if (!m) {
    throw new Error("metaprog/tsconfig.json has no compilerOptions");
  }

  console.log(`Read: ${MEMBER_PATH}  (this member's tsconfig, read via node:fs)`);
  console.log(`  extends                = ${JSON.stringify(member.extends)}`);
  console.log(`  include                = ${JSON.stringify(member.include)}`);
  console.log(`  compilerOptions.types  = ${JSON.stringify(m.types)}`);
  console.log(`  compilerOptions.lib    = ${JSON.stringify(m.lib)}`);

  check('member.extends === "../tsconfig.base.json" (inheritance link)', member.extends === "../tsconfig.base.json");
  check('member.include === ["*.ts"]', JSON.stringify(member.include) === JSON.stringify(["*.ts"]));

  // extends semantics: the member does NOT redeclare `strict` — so tsc's
  // documented extends rule gives it the base value. We prove the inheritance
  // by reading BOTH files: the member file literally has no `strict` key, and
  // the base has strict:true, so the EFFECTIVE value (post-merge) is true.
  // (JSON.parse does NOT do the merge; tsc does, at load time.)
  const memberDeclaresStrict = m.strict !== undefined;
  const baseStrict = base.compilerOptions?.strict === true;
  console.log("");
  console.log("extends inheritance proof (read both files, reason about the merge):");
  console.log(`  member redeclares strict? ${memberDeclaresStrict}   (absent => inherits base)`);
  console.log(`  base.strict === true?    ${baseStrict}   (=> effective member strict === true)`);
  check("member does NOT redeclare strict (inherits base via extends)", memberDeclaresStrict === false);
  check("base.strict === true (so the member's effective strict === true)", baseStrict === true);

  // lib OVERRIDE (not merge): in tsconfig `extends`, `lib` REPLACES the base
  // array (arrays are not concatenated). The member sets ESNext.decorators so
  // decorators type-check here; it must repeat ES2023 or lose it. The member
  // DOES repeat it — the effective lib is the member's array verbatim.
  const memberLibHasDecorators = Array.isArray(m.lib) && m.lib.includes("ESNext.decorators");
  const memberLibKeepsES2023 = Array.isArray(m.lib) && m.lib.includes("ES2023");
  console.log("");
  console.log("lib is REPLACED (not merged) under extends — the member repeats ES2023:");
  console.log(`  member.lib includes "ES2023"?           ${memberLibKeepsES2023}   (re-declared, else lost)`);
  console.log(`  member.lib includes "ESNext.decorators"? ${memberLibHasDecorators}   (Phase 6 metaprog needs it)`);
  check('member.lib re-declares "ES2023" (else extends would DROP it)', memberLibKeepsES2023 === true);
  check('member.lib adds "ESNext.decorators" (for TC39 decorators)', memberLibHasDecorators === true);

  // moduleResolution NodeNext: the modern resolver. With module:NodeNext, ESM
  // vs CJS is decided per-file (package.json "type"), and bare-specifier
  // resolution follows Node's modern algorithm. (🔗 MODULES_PACKAGES.)
  const modRes = requireStr(base, "moduleResolution");
  console.log("");
  console.log("moduleResolution NodeNext (modern; per-file ESM/CJS via package.json):");
  console.log(`  effective moduleResolution = ${JSON.stringify(modRes)}`);
  console.log("  metaprog/package.json \"type\": \"module\" => this file is ESM =>");
  console.log("  import.meta.url is available (used above to resolve the config paths).");
  check('effective moduleResolution === "NodeNext"', modRes === "NodeNext");

  // isolatedModules + verbatimModuleSyntax: the erasure-safety pair.
  //   isolatedModules:true => every file must transform INDEPENDENTLY (esbuild
  //     compiles per-file, no cross-file type info). Consequence: you cannot
  //     re-export a mere TYPE with a plain `export { T }` — the transpiler
  //     can't tell T is a type. Use `export type { T }`.
  //   verbatimModuleSyntax:false => tsc is ALLOWED to auto-elide imports it
  //     sees are type-only. If it were true, you would be FORCED to write
  //     `import type { T }` for any import used only as a type.
  const iso = base.compilerOptions?.isolatedModules === true;
  const vms = base.compilerOptions?.verbatimModuleSyntax === false;
  console.log("");
  console.log("isolatedModules + verbatimModuleSyntax (the erasure-safety pair):");
  console.log(`  isolatedModules: ${iso}   -> each file must transform standalone (per-file esbuild)`);
  console.log(`  verbatimModuleSyntax: false  -> tsc auto-elides type-only imports (no forced \`import type\`)`);
  check("isolatedModules === true (per-file transform requirement)", iso === true);
  check("verbatimModuleSyntax === false (auto-elide; not strict import-type enforcement)", vms === true);

  // type vs value imports — the OBSERVABLE distinction, with no sibling import:
  // a `type` alias is erased (no runtime name); a `const` value is kept. The
  // module-level `import type { T }` is exactly this distinction at the import
  // boundary — it tells esbuild "this name is type-only, drop it entirely."
  type Port = 8080; // type alias — ERASED
  const realPort: Port = 8080; // value — KEPT
  console.log("");
  console.log("type vs value (the `import type` boundary, observed locally):");
  console.log(`  type Port = 8080; const realPort: Port = 8080;`);
  console.log(`  -> typeof realPort = ${typeof realPort}   value = ${realPort}   (Port alias is gone; value kept)`);
  check('typeof realPort === "number" (type alias Port erased; value kept)', typeof realPort === "number");
  check("realPort === 8080 (the value survives erasure)", realPort === 8080);
}

// ============================================================================
// Section D — Bundlers (tsup/esbuild): emit .js + .d.ts + sourcemap anatomy
// ============================================================================

// A minimal, REAL SourceMap v3 shape (the spec). `mappings` is VLQ-encoded.
// We construct a deterministic example and decode it to make the format
// observable — no bundler spawned.
interface SourceMap {
  version: 3;
  file?: string;
  sourceRoot?: string;
  sources: string[];
  sourcesContent: (string | null)[];
  names: string[];
  mappings: string;
}

// The base64 alphabet used by sourcemap VLQ (spec-defined, fixed).
const VLQ_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

// decodeVlq decodes a VLQ `mappings` field into its integer groups. Each
// non-`;`/non-`,` run is ONE value; values come in groups of 1, 4, or 5
// (genCol, srcIdx, srcLine, srcCol[, nameIdx]). This decoder returns the flat
// list of decoded integers for a single segment string (no separators).
function decodeVlq(input: string): number[] {
  const out: number[] = [];
  let value = 0;
  let shift = 0;
  for (const ch of input) {
    const bits = VLQ_B64.indexOf(ch);
    if (bits < 0) {
      continue; // ignore separators if passed in
    }
    const continuation = (bits & 0x20) !== 0;
    value += (bits & 0x1f) << shift;
    shift += 5;
    if (!continuation) {
      const negate = (value & 1) !== 0;
      value >>= 1;
      out.push(negate ? -value : value);
      value = 0;
      shift = 0;
    }
  }
  return out;
}

function sectionD(): void {
  sectionBanner("D — Bundlers (tsup/esbuild): .js + .d.ts + sourcemap anatomy");

  // tsup (esbuild-based, zero-config for libs) / esbuild directly / rollup all
  // do the same three outputs for a publishable TS library:
  //   dist/index.js      <- type-erased, possibly bundled, JS
  //   dist/index.d.ts    <- DECLARATION emit (the types, for consumers' tsc)
  //   dist/index.js.map  <- SOURCEMAP (emitted line -> original .ts line)
  // We DOCUMENT these (spawning a bundler would be nondeterministic); the
  // sourcemap format we make observable by constructing a real one.

  console.log("A publishable TS library's build output (tsup/esbuild, documented):");
  console.log("  dist/<name>.js       type-erased JS (esbuild strips annotations/interfaces)");
  console.log("  dist/<name>.d.ts     DECLARATION emit (declaration:true) — consumer's tsc reads it");
  console.log("  dist/<name>.js.map   SOURCEMAP — maps emitted .js line -> original .ts line");
  console.log("");
  console.log("Why .d.ts: TS types are ERASED from the .js (Section A), so a consumer's");
  console.log("tsc could not see them. The .d.ts ships the type surface separately. This");
  console.log("is the whole reason `declaration: true` exists — it does NOT affect the .js.");
  console.log("");
  console.log("Why sourcemaps: a stack trace in dist/index.js line 42 is useless without");
  console.log("the original .ts. The .map lets devtools/debuggers reconstruct the .ts line.");

  // A real, constructed SourceMap v3 for a 1-line transform:
  //   original:   "const x: number = 1;"   (.ts)
  //   emitted:    "const x = 1;"            (.js, annotation erased)
  // mappings "AAAA" = one segment, group of 4 zeros:
  //   genCol=0, srcIdx=0, srcLine=0, srcCol=0  (all deltas from 0)
  const sm: SourceMap = {
    version: 3,
    file: "index.js",
    sources: ["../src/index.ts"],
    sourcesContent: ["const x: number = 1;"],
    names: [],
    mappings: "AAAA",
  };

  console.log("");
  console.log("Constructed SourceMap v3 (deterministic example, NOT spawned):");
  console.log(`  version: ${sm.version}`);
  console.log(`  file:    ${JSON.stringify(sm.file)}`);
  console.log(`  sources: ${JSON.stringify(sm.sources)}`);
  console.log(`  sourcesContent: ${JSON.stringify(sm.sourcesContent)}`);
  console.log(`  names:   ${JSON.stringify(sm.names)}`);
  console.log(`  mappings: ${JSON.stringify(sm.mappings)}   (VLQ-encoded segments)`);

  check("sourcemap version === 3 (the only spec version)", sm.version === 3);
  check('mappings "AAAA" decodes to [0,0,0,0]', JSON.stringify(decodeVlq("AAAA")) === JSON.stringify([0, 0, 0, 0]));

  // A richer segment: erasure shifted the emitted column. "gB" decodes to a
  // single value 16 (col 16). Combined with the segment grammar (groups of 4),
  // this is how devtools walk emitted->original positions.
  console.log("");
  console.log("VLQ decode demos (the mapping grammar):");
  console.log(`  decodeVlq("AAAA") = ${JSON.stringify(decodeVlq("AAAA"))}   (genCol0,src0,line0,col0)`);
  console.log(`  decodeVlq("gB")   = ${JSON.stringify(decodeVlq("gB"))}   (a single value 16 — col delta)`);
  console.log("  Grammar: segments separated by ','; lines by ';'. Each segment is a");
  console.log("  group of 1|4|5 VLQ values (genCol [,srcIdx,srcLine,srcCol [,nameIdx]]).");
  check('decodeVlq("gB") === [16] (VLQ sign/magnitude, base64-continued)', JSON.stringify(decodeVlq("gB")) === JSON.stringify([16]));
}

// ============================================================================
// Section E — Choosing the tool per task + cross-language parallels
// ============================================================================

function sectionE(): void {
  sectionBanner("E — Choosing the tool per task + cross-language build splits");

  // The decision is governed by WHAT you need (run / check / publish), not by
  // preference. Pinned as a deterministic table.
  const table: ReadonlyArray<readonly [string, string, string]> = [
    ["dev / run", "tsx file.ts", "esbuild erases types in-memory; no .js artifact"],
    ["CI typecheck gate", "tsc --noEmit", "the ONLY step that checks types; exits non-zero on error"],
    ["emit declarations", "tsc --emitDeclarationOnly", ".d.ts for consumers (declaration:true)"],
    ["publish / bundle", "tsup / esbuild", ".js + .d.ts + .map into dist/"],
    ["project references", "tsc --build", "incremental, builds referenced projects in order"],
  ];

  console.log("Pick the tool by the TASK (deterministic decision table):");
  console.log("  task                  tool                       why");
  console.log("  --------------------  -------------------------  -----------------------------------");
  for (const [task, tool, why] of table) {
    console.log(`  ${task.padEnd(20)}  ${tool.padEnd(25)} ${why}`);
  }

  check("dev-run uses tsx (esbuild erase + run, no artifact)", table[0]![1] === "tsx file.ts");
  check("CI gate uses tsc --noEmit (typecheck only)", table[1]![1] === "tsc --noEmit");
  check("publish uses tsup/esbuild (bundle .js + .d.ts + .map)", table[3]![1] === "tsup / esbuild");

  // import.meta.url — the ESM build-time-ish hook we already used to resolve the
  // config paths. It is set by the RUNTIME (Node), not by a build step, but it
  // is the canonical "where am I?" for ESM (replacing CJS's __dirname).
  console.log("");
  console.log("import.meta.url — the ESM 'where am I?' (used above to find the configs):");
  console.log(`  import.meta.url -> file://...metaprog/build_tooling.ts`);
  console.log("  (CJS equivalent: __dirname/__filename, injected by the module wrapper.)");

  check("import.meta.url is a string (available in ESM, Node-set)", typeof import.meta.url === "string");

  // Cross-language: the SAME problem (split build roles) solved differently.
  console.log("");
  console.log("Cross-language build splits (the same problem, three ecosystems):");
  console.log("  TS   : tsc (check) | tsx/esbuild (run) | tsup (bundle)   [this bundle]");
  console.log("  Rust : cargo build (compile) | build.rs (codegen)        [../rust/BUILD_CONFIG.md]");
  console.log("  Go   : go build | //go:build tags | -ldflags -X          [../go/BUILD_LDFLAGS_GENERATE.md]");
  console.log("  Each splits 'configure / generate / check / emit' across distinct tools.");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("build_tooling.ts — Phase 6 bundle (member: metaprog).");
  console.log("Every config value below is READ from the repo's own tsconfig files via");
  console.log("node:fs and ASSERTED — nothing spawned, nothing hand-computed. Type");
  console.log("erasure is observed at runtime (typeof); bundlers/sourcemaps are documented.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
